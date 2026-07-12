"""淘宝订单 CRUD。软删过滤、乐观锁、金额重算、OrderItem 子表替换。"""

import datetime as dt
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy import update as sa_update
from sqlmodel import Session, select

from ..auth import get_current_user
from ..database import get_session
from ..models import ShipmentOrder, OrderItem, StagingStatus, TaobaoOrder, TaobaoStaging, User, utcnow
from ..schemas import TaobaoCreate, TaobaoRead, TaobaoUpdate
from .common import conflict, guarded_bump, not_found, soft_delete

router = APIRouter(
    prefix="/api/taobao", tags=["taobao"], dependencies=[Depends(get_current_user)]
)


def _check_shipment(session: Session, shipment_id):
    """挂靠的集运订单必须存在且未软删（防悬空/无效外链）。"""
    if shipment_id is not None:
        shipment = session.get(ShipmentOrder, shipment_id)
        if not shipment or shipment.deleted_at is not None:
            raise HTTPException(status_code=422, detail="所属集运订单不存在或已删除")


@router.get("")
def list_orders(
    session: Session = Depends(get_session),
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
    conds = [TaobaoOrder.deleted_at.is_(None)]
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


@router.post("", response_model=TaobaoRead)
def create_order(payload: TaobaoCreate, session: Session = Depends(get_session)):
    from ..services.fx import current_rate  # 局部导入避免循环

    data = payload.model_dump(exclude={"items"})
    order = TaobaoOrder(**data)
    if order.fx_rate is None:                 # 新建时写入当天汇率
        order.fx_rate = current_rate(session)
    order.compute_money()
    order.items = [OrderItem(name=it.name, quantity=it.quantity) for it in payload.items]
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
    if not order or order.deleted_at is not None:
        not_found("淘宝订单")
    return order


@router.patch("/{order_id}", response_model=TaobaoRead)
def update_order(order_id: int, payload: TaobaoUpdate, session: Session = Depends(get_session)):
    order = session.get(TaobaoOrder, order_id)
    if not order or order.deleted_at is not None:
        not_found("淘宝订单")
    if not guarded_bump(session, TaobaoOrder, order_id, payload.version):
        conflict()
    # 集运单存活校验放在 guarded_bump 之后：此时写事务已开启并持写锁，校验与写入同一事务，
    # 闭合「校验通过 → 集运单被并发软删 → 仍挂上」的 TOCTOU（与 attach_taobao 的 EXISTS 守卫同效）。
    if "shipment_order_id" in payload.model_fields_set:
        _check_shipment(session, payload.shipment_order_id)

    data = payload.model_dump(exclude_unset=True, exclude={"version", "items"})
    for key, value in data.items():
        setattr(order, key, value)
    order.compute_money()

    if payload.items is not None:            # 给了 items 就整体替换（[] = 清空）
        order.items.clear()
        for it in payload.items:
            order.items.append(OrderItem(name=it.name, quantity=it.quantity))

    session.add(order)
    session.commit()
    session.refresh(order)
    return order


@router.delete("/{order_id}")
def delete_order(order_id: int, session: Session = Depends(get_session)):
    order = session.get(TaobaoOrder, order_id)
    if not order or order.deleted_at is not None:
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
