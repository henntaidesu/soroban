"""君丰订单 CRUD。金额 = 运费(CNY→JPY) + 特殊费_日元。"""

import datetime as dt
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy import update as sa_update
from sqlmodel import Session, select

from ..auth import get_current_user
from ..database import get_session
from ..models import JunfengOrder, TaobaoOrder
from ..schemas import JunfengCreate, JunfengRead, JunfengUpdate, TaobaoBrief
from .common import conflict, guarded_bump, not_found, soft_delete

router = APIRouter(
    prefix="/api/junfeng", tags=["junfeng"], dependencies=[Depends(get_current_user)]
)


def _read(session: Session, order: JunfengOrder) -> JunfengRead:
    """构造响应，其中 taobao_orders 只含未软删的关联淘宝订单（不泄露已删数据）。"""
    r = JunfengRead.model_validate(order)
    children = session.exec(
        select(TaobaoOrder).where(
            TaobaoOrder.junfeng_order_id == order.id,
            TaobaoOrder.deleted_at.is_(None),
        )
    ).all()
    r.taobao_orders = [
        TaobaoBrief(id=c.id, order_no=c.order_no, date=c.date, shop=c.shop,
                    status=c.status, jpy_settled=c.jpy_settled)
        for c in children
    ]
    return r


@router.get("")
def list_orders(
    session: Session = Depends(get_session),
    date_from: Optional[dt.date] = None,
    date_to: Optional[dt.date] = None,
    status: Optional[str] = None,
    q: Optional[str] = Query(None, description="按君丰单号搜索"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    conds = [JunfengOrder.deleted_at.is_(None)]
    if date_from:
        conds.append(JunfengOrder.date >= date_from)
    if date_to:
        conds.append(JunfengOrder.date <= date_to)
    if status:
        conds.append(JunfengOrder.status == status)
    if q:
        conds.append(JunfengOrder.junfeng_no.contains(q, autoescape=True))

    total = session.exec(select(func.count()).select_from(JunfengOrder).where(*conds)).one()
    rows = session.exec(
        select(JunfengOrder)
        .where(*conds)
        .order_by(JunfengOrder.date.desc(), JunfengOrder.id.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return {"items": [_read(session, r) for r in rows], "total": total}


@router.post("", response_model=JunfengRead)
def create_order(payload: JunfengCreate, session: Session = Depends(get_session)):
    from ..services.fx import current_rate  # 局部导入避免循环

    order = JunfengOrder(**payload.model_dump())
    if order.fx_rate is None:                 # 新建时写入当天汇率
        order.fx_rate = current_rate(session)
    order.compute_money()
    session.add(order)
    session.commit()
    session.refresh(order)
    return _read(session, order)


@router.get("/{order_id}", response_model=JunfengRead)
def get_order(order_id: int, session: Session = Depends(get_session)):
    order = session.get(JunfengOrder, order_id)
    if not order or order.deleted_at is not None:
        not_found("君丰订单")
    return _read(session, order)


@router.patch("/{order_id}", response_model=JunfengRead)
def update_order(order_id: int, payload: JunfengUpdate, session: Session = Depends(get_session)):
    order = session.get(JunfengOrder, order_id)
    if not order or order.deleted_at is not None:
        not_found("君丰订单")
    if not guarded_bump(session, JunfengOrder, order_id, payload.version):
        conflict()

    data = payload.model_dump(exclude_unset=True, exclude={"version"})
    for key, value in data.items():
        setattr(order, key, value)
    order.compute_money()

    session.add(order)
    session.commit()
    session.refresh(order)
    return _read(session, order)


@router.delete("/{order_id}")
def delete_order(order_id: int, session: Session = Depends(get_session)):
    order = session.get(JunfengOrder, order_id)
    if not order or order.deleted_at is not None:
        not_found("君丰订单")
    # 解除关联淘宝订单的挂靠，避免留下指向已删君丰单的悬空外键
    session.execute(
        sa_update(TaobaoOrder)
        .where(TaobaoOrder.junfeng_order_id == order_id, TaobaoOrder.deleted_at.is_(None))
        .values(junfeng_order_id=None)
    )
    soft_delete(order)
    session.add(order)
    session.commit()
    return {"ok": True}
