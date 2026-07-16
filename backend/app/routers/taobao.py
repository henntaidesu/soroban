"""淘宝订单 CRUD。软删过滤、乐观锁、金额重算、OrderItem 子表替换。"""

import datetime as dt
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import func
from sqlalchemy import update as sa_update
from sqlmodel import Session, select

from ..auth import get_current_user
from ..database import get_session
from ..models import ShipmentOrder, OrderItem, StagingItem, StagingStatus, TaobaoOrder, TaobaoStaging, utcnow
from ..schemas import TaobaoCreate, TaobaoRead, TaobaoUpdate
from .common import build_items, conflict, guarded_bump, not_found, soft_delete

_MAX_OCR_BYTES = 10 * 1024 * 1024   # 截图一般 <2MB，限 10MB 防大图拖垮识别

router = APIRouter(
    prefix="/api/taobao", tags=["taobao"], dependencies=[Depends(get_current_user)]
)


def _check_shipment(session: Session, shipment_id):
    """挂靠的集运订单必须存在且未软删（防悬空/无效外链）。"""
    if shipment_id is not None:
        shipment = session.get(ShipmentOrder, shipment_id)
        if not shipment or shipment.is_delete:
            raise HTTPException(status_code=422, detail="所属集运订单不存在或已删除")


def _mirror_to_staging(session: Session, order: TaobaoOrder, built_items) -> None:
    """若此淘宝单由暂存导入而来：把账本当前的共享字段(+物品)镜像回其暂存行，保持「暂存=账本镜像」。
    否则删单/清账本会把暂存复位为待处理、再导入时用到陈旧的暂存快照，丢掉在淘宝页做的物品/价格编辑。
    built_items 为 build_items 的产物（非空才镜像物品；None=仅镜像共享字段，如只改了状态）。"""
    st = session.exec(
        select(TaobaoStaging).where(TaobaoStaging.imported_taobao_order_id == order.id)
    ).first()
    if st is None:
        return
    st.order_date, st.order_no, st.shop = order.date, order.order_no, order.shop
    st.taobao_account, st.platform, st.express_no = order.taobao_account, order.platform, order.express_no
    st.postage_cny, st.fx_rate, st.order_status = order.postage_cny, order.fx_rate, order.status
    if built_items is not None:
        st.items = [StagingItem(**d) for d in built_items]
    st.sync_from_items()
    st.updated_at = utcnow()
    session.add(st)


@router.get("")
def list_orders(
    session: Session = Depends(get_session),
    id: Optional[int] = Query(None, description="定位单条：供集运页点订单号跳转过来隔离显示"),
    date_from: Optional[dt.date] = None,
    date_to: Optional[dt.date] = None,
    status: Optional[str] = None,
    taobao_account: Optional[str] = None,
    express_no: Optional[str] = None,
    shipment_order_id: Optional[int] = None,
    unassigned: Optional[bool] = Query(None, description="仅未挂靠集运的订单（供集运页点选添加）"),
    q: Optional[str] = Query(None, description="按订单号搜索"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    conds = [TaobaoOrder.is_delete.is_(False)]
    if id is not None:
        conds.append(TaobaoOrder.id == id)
    if unassigned:
        conds.append(TaobaoOrder.shipment_order_id.is_(None))
    if date_from:
        conds.append(TaobaoOrder.date >= date_from)
    if date_to:
        conds.append(TaobaoOrder.date <= date_to)
    if status:
        conds.append(TaobaoOrder.status == status)
    if taobao_account:
        conds.append(TaobaoOrder.taobao_account == taobao_account)
    if express_no:
        conds.append(TaobaoOrder.express_no == express_no)
    if shipment_order_id is not None:
        conds.append(TaobaoOrder.shipment_order_id == shipment_order_id)
    if q:
        conds.append(TaobaoOrder.order_no.contains(q, autoescape=True))

    total = session.exec(select(func.count()).select_from(TaobaoOrder).where(*conds)).one()
    rows = session.exec(
        select(TaobaoOrder)
        .where(*conds)
        .order_by(TaobaoOrder.date.desc(), TaobaoOrder.id.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return {"items": [TaobaoRead.model_validate(r) for r in rows], "total": total}


@router.post("/ocr")
async def ocr_order(file: UploadFile = File(...)):
    """识别订单详情截图，抽取快递公司/快递号/订单号/成交价供前端自动填表。
    OCR 为 CPU 密集且较慢，放线程池执行 → 不阻塞事件循环，前端可连续上传多张并发识别。"""
    from fastapi.concurrency import run_in_threadpool

    from ..services.ocr import OcrUnavailable, recognize_order

    if file.content_type and not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="请上传图片文件")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="图片为空")
    if len(data) > _MAX_OCR_BYTES:
        raise HTTPException(status_code=413, detail="图片过大（上限 10MB）")
    try:
        return await run_in_threadpool(recognize_order, data)
    except OcrUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("", response_model=TaobaoRead)
def create_order(payload: TaobaoCreate, session: Session = Depends(get_session)):
    from ..services.fx import current_rate  # 局部导入避免循环

    data = payload.model_dump(exclude={"items", "price_cny"})   # 订单价由物品派生，不直接落库
    order = TaobaoOrder(**data)
    _check_shipment(session, order.shipment_order_id)   # 挂靠的集运单不存在/已删 → 友好 422（而非 FK 撞库转 409）
    if order.fx_rate is None:                 # 新建时写入当天汇率
        order.fx_rate = current_rate(session)
    # 最小单位是物品：至少 1 条（无物品则按商品名+货款自动生成，灰显可改）。
    # 播种用「货款」= 订单价种子 - 邮费，避免把邮费也摊进物品单价（否则 sync 加邮费会重复计）。
    seed_goods = (payload.price_cny - (payload.postage_cny or 0)) if payload.price_cny is not None else None
    order.items = [OrderItem(**d) for d in build_items(payload.items, seed_goods, payload.shop)]
    order.sync_from_items()                   # price_cny = Σ(单价×数量) + 邮费，并重算日元
    session.add(order)
    session.flush()                           # 写入并占写锁；FK 保证集运单硬存在
    # 同事务内复核集运单未软删（此为本事务首次读取该单、非身份映射缓存），闭合并发软删 TOCTOU
    _check_shipment(session, order.shipment_order_id)
    session.commit()
    session.refresh(order)
    return order


@router.get("/{order_id}", response_model=TaobaoRead)
def get_order(order_id: int, session: Session = Depends(get_session)):
    order = session.get(TaobaoOrder, order_id)
    if not order or order.is_delete:
        not_found("淘宝订单")
    return order


@router.patch("/{order_id}", response_model=TaobaoRead)
def update_order(order_id: int, payload: TaobaoUpdate, session: Session = Depends(get_session)):
    order = session.get(TaobaoOrder, order_id)
    if not order or order.is_delete:
        not_found("淘宝订单")
    if not guarded_bump(session, TaobaoOrder, order_id, payload.version):
        conflict()
    # 集运单存活校验放在 guarded_bump 之后：此时写事务已开启并持写锁，校验与写入同一事务，
    # 闭合「校验通过 → 集运单被并发软删 → 仍挂上」的 TOCTOU（与 attach_taobao 的 EXISTS 守卫同效）。
    if "shipment_order_id" in payload.model_fields_set:
        _check_shipment(session, payload.shipment_order_id)

    # price_cny 由物品派生，不接受直接改（订单列表 RMB 只读，改价走物品）
    data = payload.model_dump(exclude_unset=True, exclude={"version", "items", "price_cny"})
    for key, value in data.items():
        setattr(order, key, value)

    # seed 兜底（货款口径）：物品都无单价时用「订单当前价 - 邮费」重播种，避免把邮费摊进单价再被 sync 重复加
    seed = payload.price_cny if payload.price_cny is not None else order.price_cny
    seed_goods = (seed - (order.postage_cny or 0)) if seed is not None else None
    built = None
    if payload.items is not None:            # 给了 items 就整体替换（[] → 自动补 1 条占位）
        built = build_items(payload.items, seed_goods, order.shop)
        order.items = [OrderItem(**d) for d in built]
    elif not order.items:                    # 兜底：历史订单可能无物品 → 补占位，守住「≥1 物品」不变量
        order.items = [OrderItem(**d) for d in build_items([], seed_goods, order.shop)]
    order.sync_from_items()                  # 无论是否改物品：价格恒由物品派生，并按新 fx/override 重算日元
    _mirror_to_staging(session, order, built)  # 若由暂存导入：镜像回暂存行，避免删单后重导丢失编辑

    session.add(order)
    session.commit()
    session.refresh(order)
    return order


@router.delete("/{order_id}")
def delete_order(order_id: int, session: Session = Depends(get_session)):
    order = session.get(TaobaoOrder, order_id)
    if not order or order.is_delete:
        not_found("淘宝订单")
    soft_delete(order)
    session.add(order)
    # 若此单是从暂存导入的：删除后把暂存行的挂靠清掉、状态回「待处理」，使其可重新导入
    # （对齐集运删除时清子订单外键的做法，避免暂存行永远卡在「已导入」且指向已删订单）。
    session.execute(
        sa_update(TaobaoStaging)
        .where(TaobaoStaging.imported_taobao_order_id == order_id)
        .values(imported_taobao_order_id=None, status=StagingStatus.pending.value,
                version=TaobaoStaging.version + 1, updated_at=utcnow())
    )
    session.commit()
    return {"ok": True}
