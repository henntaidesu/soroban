"""淘宝订单 CRUD。软删过滤、乐观锁、金额重算、OrderItem 子表替换。"""

import datetime as dt
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlmodel import Session, select

from ..auth import get_current_user
from ..database import get_session
from ..models import ShipmentOrder, OrderItem, TaobaoOrder, User
from ..schemas import TaobaoCreate, TaobaoRead, TaobaoUpdate
from .common import conflict, guarded_bump, not_found, soft_delete

router = APIRouter(
    prefix="/api/taobao", tags=["taobao"], dependencies=[Depends(get_current_user)]
)


def _check_shipment(session: Session, jf_id):
    """挂靠的集运订单必须存在且未软删（防悬空/无效外链）。"""
    if jf_id is not None:
        jf = session.get(ShipmentOrder, jf_id)
        if not jf or jf.deleted_at is not None:
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
    unassigned: Optional[bool] = Query(None, description="仅未挂靠集运的订单（供 JF 页点选添加）"),
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

    _check_shipment(session, payload.shipment_order_id)
    data = payload.model_dump(exclude={"items"})
    order = TaobaoOrder(**data)
    if order.fx_rate is None:                 # 新建时写入当天汇率
        order.fx_rate = current_rate(session)
    order.compute_money()
    order.items = [OrderItem(name=it.name, quantity=it.quantity) for it in payload.items]
    session.add(order)
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
    if "shipment_order_id" in payload.model_fields_set:
        _check_shipment(session, payload.shipment_order_id)
    if not guarded_bump(session, TaobaoOrder, order_id, payload.version):
        conflict()

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
    session.commit()
    return {"ok": True}
