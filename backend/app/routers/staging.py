"""淘宝抓取暂存（全部淘宝订单）→ 人工确认「导入」才进正式账本。

机器人（将来）只写这里；现在支持手动新建/内联编辑。一单多物用 StagingItem 子表，
结构对齐账本的 TaobaoOrder/OrderItem。导入=从暂存行生成 TaobaoOrder（含全部物品）。"""

import datetime as dt
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy import update as sa_update
from sqlmodel import Session, select

from ..auth import get_current_user
from ..database import get_session
from ..models import (
    OrderItem,
    Source,
    StagingItem,
    StagingStatus,
    TaobaoOrder,
    TaobaoStaging,
    TaobaoStatus,
    utcnow,
)
from ..schemas import StagingCreate, StagingItemRead, StagingRead, StagingUpdate, TaobaoRead
from .common import build_items, conflict, guarded_bump, not_found

router = APIRouter(
    prefix="/api/staging", tags=["staging"], dependencies=[Depends(get_current_user)]
)

# 已导入行：暂存字段 → 账本字段的映射（单一真源写穿账本；status=导入工作流状态留暂存自身）。
# price_cny 不在此列：它由物品单价×数量派生（见 sync_from_items），改价走物品、不直接写。
_SHARED_TO_ORDER = {
    "order_date": "date",
    "order_no": "order_no",
    "shop": "shop",
    "taobao_account": "taobao_account",
    "platform": "platform",
    "express_no": "express_no",
    "postage_cny": "postage_cny",
    "fx_rate": "fx_rate",
    "order_status": "status",
}


def _linked_order(session: Session, row: TaobaoStaging) -> Optional[TaobaoOrder]:
    """已导入且账本订单仍在（未软删）→ 返回该订单，否则 None。"""
    if row.imported_taobao_order_id is None:
        return None
    order = session.get(TaobaoOrder, row.imported_taobao_order_id)
    return order if order and not order.is_delete else None


def _read(session: Session, row: TaobaoStaging) -> StagingRead:
    """已导入行的共享字段用账本的实时值覆盖显示（单一真源，两页永远一致）。"""
    data = StagingRead.model_validate(row)
    order = _linked_order(session, row)
    if order is not None:
        data.order_date = order.date
        data.order_no = order.order_no
        data.shop = order.shop
        data.taobao_account = order.taobao_account
        data.express_no = order.express_no
        data.price_cny = order.price_cny
        data.postage_cny = order.postage_cny
        data.fx_rate = order.fx_rate
        data.order_status = order.status
        data.items = [
            StagingItemRead(id=it.id, name=it.name, quantity=it.quantity,
                            price_cny=it.price_cny, auto=it.auto)
            for it in order.items
        ]
    return data


@router.get("")
def list_staging(
    session: Session = Depends(get_session),
    status: Optional[str] = None,
    taobao_account: Optional[str] = None,
    q: Optional[str] = Query(None, description="按订单号/店铺搜索"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    conds = []
    if status:
        conds.append(TaobaoStaging.status == status)
    if taobao_account:
        conds.append(TaobaoStaging.taobao_account == taobao_account)
    if q:
        conds.append(
            (TaobaoStaging.order_no.contains(q, autoescape=True))
            | (TaobaoStaging.shop.contains(q, autoescape=True))
        )
    total = session.exec(select(func.count()).select_from(TaobaoStaging).where(*conds)).one()
    rows = session.exec(
        select(TaobaoStaging)
        .where(*conds)
        .order_by(TaobaoStaging.scraped_at.desc(), TaobaoStaging.id.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return {"items": [_read(session, r) for r in rows], "total": total}


@router.post("", response_model=StagingRead)
def create_staging(payload: StagingCreate, session: Session = Depends(get_session)):
    from ..services.fx import rate_for_date  # 局部导入避免循环

    row = TaobaoStaging(**payload.model_dump(exclude={"items", "price_cny"}))  # 价由物品派生
    if row.fx_rate is None:                  # 按下单日期匹配汇率；无记录则退回当前(入库当天)汇率
        row.fx_rate = rate_for_date(session, row.order_date)
    # 最小单位是物品：至少 1 条。播种用「货款」= 种子价 - 邮费，避免邮费摊进单价再被 sync 重复计
    seed_goods = (payload.price_cny - (payload.postage_cny or 0)) if payload.price_cny is not None else None
    row.items = [StagingItem(**d) for d in build_items(payload.items, seed_goods, payload.shop)]
    row.sync_from_items()                    # price_cny = Σ(单价×数量) + 邮费
    session.add(row)
    session.commit()
    session.refresh(row)
    return _read(session, row)


@router.patch("/{row_id}", response_model=StagingRead)
def update_staging(row_id: int, payload: StagingUpdate, session: Session = Depends(get_session)):
    row = session.get(TaobaoStaging, row_id)
    if not row:
        not_found("暂存记录")
    # 暂存行乐观锁：加载后被爬虫/他人改过 → 409，前端刷新（version 原子自增 + 刷新 updated_at）
    if not guarded_bump(session, TaobaoStaging, row_id, payload.version):
        conflict()
    data = payload.model_dump(exclude_unset=True, exclude={"items", "version", "price_cny"})  # 价由物品派生
    order = _linked_order(session, row)

    if order is not None:
        # 已导入：共享字段写穿到账本（唯一真源），仅「导入状态」留在暂存自身。
        # 账本侧再走一次乐观锁：原子自增账本 version，让淘宝页也能察觉此次改动。
        if not guarded_bump(session, TaobaoOrder, order.id, order.version):
            conflict()
        for key, value in data.items():
            if key in _SHARED_TO_ORDER:
                setattr(order, _SHARED_TO_ORDER[key], value)
                setattr(row, key, value)   # 暂存行自身原始列也同步，避免 tags._data_values / 列表筛选读到陈旧值
            elif key == "status":
                row.status = value
        if payload.items is not None:                   # 物品写穿账本（单一真源）+ 暂存镜像，两页一致
            seed = payload.price_cny if payload.price_cny is not None else order.price_cny
            seed_goods = (seed - (order.postage_cny or 0)) if seed is not None else None
            built = build_items(payload.items, seed_goods, order.shop)
            order.items = [OrderItem(**d) for d in built]
            row.items = [StagingItem(**d) for d in built]
        order.sync_from_items()                         # 账本价+日元由物品派生（fx 变也重算）
        row.sync_from_items()                           # 暂存价镜像
        session.add(order)
        session.add(row)
        session.commit()                                # order_no 撞账本唯一索引 → IntegrityError → 409
        session.refresh(row)
        return _read(session, row)

    # 未导入：编辑暂存自身副本
    for key, value in data.items():
        setattr(row, key, value)
    if payload.items is not None:                       # 给了 items 就整体替换（[] → 自动补 1 条占位）
        # seed 兜底（货款口径）：物品无单价时用「当前价 - 邮费」重播种，绝不清零、也不重复计邮费
        seed = payload.price_cny if payload.price_cny is not None else row.price_cny
        seed_goods = (seed - (row.postage_cny or 0)) if seed is not None else None
        row.items = [StagingItem(**d) for d in build_items(payload.items, seed_goods, row.shop)]
    row.sync_from_items()
    session.add(row)
    session.commit()
    session.refresh(row)
    return _read(session, row)


@router.delete("/{row_id}")
def delete_staging(row_id: int, session: Session = Depends(get_session)):
    row = session.get(TaobaoStaging, row_id)
    if not row:
        not_found("暂存记录")
    session.delete(row)
    session.commit()
    return {"ok": True}


@router.post("/{row_id}/ignore", response_model=StagingRead)
def ignore_staging(row_id: int, session: Session = Depends(get_session)):
    # 原子标记忽略：version 在 DB 层自增（而非 Python 读-改-写），避免并发忽略/爬虫写
    # 丢失 version 自增、绕过乐观锁；与 import_staging 的原子门闸同风格。
    res = session.execute(
        sa_update(TaobaoStaging)
        .where(TaobaoStaging.id == row_id)
        .values(status=StagingStatus.ignored.value,
                version=TaobaoStaging.version + 1, updated_at=utcnow())
    )
    if res.rowcount != 1:
        not_found("暂存记录")
    session.commit()
    row = session.get(TaobaoStaging, row_id)
    return _read(session, row)


@router.post("/{row_id}/import", response_model=TaobaoRead)
def import_staging(row_id: int, session: Session = Depends(get_session)):
    """从暂存行生成正式淘宝订单（含全部物品），并标记暂存为已导入。"""
    from ..services.fx import rate_for_date  # 局部导入避免循环

    row = session.get(TaobaoStaging, row_id)
    if not row:
        not_found("暂存记录")
    if row.imported_taobao_order_id is not None:
        raise HTTPException(status_code=409, detail="该记录已导入")

    order = TaobaoOrder(
        date=row.order_date or dt.date.today(),
        order_no=row.order_no,
        shop=row.shop,
        taobao_account=row.taobao_account,
        platform=row.platform,               # 来源随单迁移到账本
        express_no=row.express_no,
        postage_cny=row.postage_cny,         # 邮费随单迁移
        fx_rate=row.fx_rate or rate_for_date(session, row.order_date),  # 优先暂存记录的汇率；否则按下单日期匹配
        status=row.order_status or TaobaoStatus.paid.value,   # 订单状态一同迁移
        source=Source.imported.value,
    )
    # 物品（含单价/auto）随单迁移；订单价由物品派生（= 暂存价，一致）。暂存无物品时兜底自动生成 1 条。
    if row.items:
        order.items = [OrderItem(name=it.name, quantity=it.quantity, price_cny=it.price_cny, auto=it.auto)
                       for it in row.items]
    else:
        # 0 物品兜底：种子用货款(总价-邮费)，避免 sync 再加邮费重复计（对齐其它 build_items 站点）
        seed_goods = (row.price_cny - (row.postage_cny or 0)) if row.price_cny is not None else None
        order.items = [OrderItem(**d) for d in build_items([], seed_goods, row.shop)]
    order.sync_from_items()
    session.add(order)
    session.flush()                             # 拿到 order.id

    # 原子门闸：只有 imported 仍为空的那次导入能成功，防并发/重复导入建重复单
    claimed = session.execute(
        sa_update(TaobaoStaging)
        .where(TaobaoStaging.id == row_id, TaobaoStaging.imported_taobao_order_id.is_(None))
        .values(
            status=StagingStatus.imported.value,
            order_status=order.status,          # 快照对齐账本（此后以账本为准，读时覆盖）
            imported_taobao_order_id=order.id,
            version=TaobaoStaging.version + 1,
            updated_at=utcnow(),
        )
    )
    if claimed.rowcount != 1:                    # 被别人抢先导入 → 回滚刚建的订单
        raise HTTPException(status_code=409, detail="该记录已导入")

    session.commit()                            # order_no 与账本冲突 → IntegrityError → 全局 409
    session.refresh(order)
    return order
