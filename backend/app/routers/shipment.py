"""集运订单 CRUD。金额 = 运费(CNY→JPY) + 特殊费_日元。"""

import datetime as dt
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy import update as sa_update
from sqlalchemy.orm import selectinload
from sqlmodel import Session, select

from ..auth import get_current_user
from ..database import get_session
from ..models import ShipmentOrder, TaobaoOrder, utcnow
from ..schemas import ShipmentCreate, ShipmentRead, ShipmentUpdate, OrderItemRead, TaobaoBrief
from .common import conflict, guarded_bump, not_found, soft_delete

router = APIRouter(
    prefix="/api/shipment", tags=["shipment"], dependencies=[Depends(get_current_user)]
)


def _read(session: Session, order: ShipmentOrder) -> ShipmentRead:
    """构造响应，其中 taobao_orders 只含未软删的关联淘宝订单（不泄露已删数据）。"""
    r = ShipmentRead.model_validate(order)
    children = session.exec(
        select(TaobaoOrder)
        .where(
            TaobaoOrder.shipment_order_id == order.id,
            TaobaoOrder.deleted_at.is_(None),
        )
        .options(selectinload(TaobaoOrder.items))   # 批量载入子订单物品，避免 N+1
    ).all()
    r.taobao_orders = [
        TaobaoBrief(id=c.id, order_no=c.order_no, date=c.date, shop=c.shop,
                    status=c.status, jpy_settled=c.jpy_settled,
                    items=[OrderItemRead(id=it.id, name=it.name, quantity=it.quantity) for it in c.items])
        for c in children
    ]
    return r


@router.get("")
def list_orders(
    session: Session = Depends(get_session),
    date_from: Optional[dt.date] = None,
    date_to: Optional[dt.date] = None,
    status: Optional[str] = None,
    q: Optional[str] = Query(None, description="按集运单号搜索"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    conds = [ShipmentOrder.deleted_at.is_(None)]
    if date_from:
        conds.append(ShipmentOrder.date >= date_from)
    if date_to:
        conds.append(ShipmentOrder.date <= date_to)
    if status:
        conds.append(ShipmentOrder.status == status)
    if q:
        conds.append(ShipmentOrder.shipment_no.contains(q, autoescape=True))

    total = session.exec(select(func.count()).select_from(ShipmentOrder).where(*conds)).one()
    rows = session.exec(
        select(ShipmentOrder)
        .where(*conds)
        .order_by(ShipmentOrder.date.desc(), ShipmentOrder.id.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return {"items": [_read(session, r) for r in rows], "total": total}


@router.post("", response_model=ShipmentRead)
def create_order(payload: ShipmentCreate, session: Session = Depends(get_session)):
    from ..services.fx import current_rate  # 局部导入避免循环

    order = ShipmentOrder(**payload.model_dump())
    if order.fx_rate is None:                 # 新建时写入当天汇率
        order.fx_rate = current_rate(session)
    order.compute_money()
    session.add(order)
    session.commit()
    session.refresh(order)
    return _read(session, order)


@router.get("/{order_id}", response_model=ShipmentRead)
def get_order(order_id: int, session: Session = Depends(get_session)):
    order = session.get(ShipmentOrder, order_id)
    if not order or order.deleted_at is not None:
        not_found("集运订单")
    return _read(session, order)


@router.patch("/{order_id}", response_model=ShipmentRead)
def update_order(order_id: int, payload: ShipmentUpdate, session: Session = Depends(get_session)):
    order = session.get(ShipmentOrder, order_id)
    if not order or order.deleted_at is not None:
        not_found("集运订单")
    if not guarded_bump(session, ShipmentOrder, order_id, payload.version):
        conflict()

    data = payload.model_dump(exclude_unset=True, exclude={"version"})
    for key, value in data.items():
        setattr(order, key, value)
    order.compute_money()

    session.add(order)
    session.commit()
    session.refresh(order)
    return _read(session, order)


@router.post("/{jf_id}/taobao/{tb_id}", response_model=ShipmentRead)
def attach_taobao(jf_id: int, tb_id: int, session: Session = Depends(get_session)):
    """把一个淘宝订单挂到本集运单（点选添加）。同一个外键 shipment_order_id，与淘宝页共用。
    仅允许「未挂靠」的淘宝单：已挂在别的集运单 → 422（先移除再加，防误抢）。"""
    jf = session.get(ShipmentOrder, jf_id)
    if not jf or jf.deleted_at is not None:
        not_found("集运订单")
    tb = session.get(TaobaoOrder, tb_id)
    if not tb or tb.deleted_at is not None:
        not_found("淘宝订单")
    if tb.shipment_order_id == jf_id:
        return _read(session, jf)                     # 已挂本单，幂等
    # 原子挂载：仅当 DB 里仍未挂靠（且未软删）才成功，靠 rowcount 判定 —— 避免
    # 「读-判断-写」在并发下双挂/误抢；version 在 DB 层自增，不丢失并发的自增（与 guarded_bump 同风格）。
    res = session.execute(
        sa_update(TaobaoOrder)
        .where(
            TaobaoOrder.id == tb_id,
            TaobaoOrder.shipment_order_id.is_(None),
            TaobaoOrder.deleted_at.is_(None),
        )
        .values(shipment_order_id=jf_id, version=TaobaoOrder.version + 1, updated_at=utcnow())
    )
    if res.rowcount != 1:                              # 已被（含并发）挂到别的集运单
        raise HTTPException(status_code=422, detail="该淘宝订单已挂靠其他集运单，请先移除")
    session.commit()
    return _read(session, jf)


@router.delete("/{jf_id}/taobao/{tb_id}", response_model=ShipmentRead)
def detach_taobao(jf_id: int, tb_id: int, session: Session = Depends(get_session)):
    """从本集运单移除一个淘宝订单（解除外键）。仅当它确实挂在本单才动（幂等）。"""
    jf = session.get(ShipmentOrder, jf_id)
    if not jf or jf.deleted_at is not None:
        not_found("集运订单")
    tb = session.get(TaobaoOrder, tb_id)
    if not tb or tb.deleted_at is not None:
        not_found("淘宝订单")
    # 原子解除：仅当它确实挂在本单才动（幂等）；version 在 DB 层自增，不丢并发自增。
    session.execute(
        sa_update(TaobaoOrder)
        .where(TaobaoOrder.id == tb_id, TaobaoOrder.shipment_order_id == jf_id)
        .values(shipment_order_id=None, version=TaobaoOrder.version + 1, updated_at=utcnow())
    )
    session.commit()
    return _read(session, jf)


@router.delete("/{order_id}")
def delete_order(order_id: int, session: Session = Depends(get_session)):
    order = session.get(ShipmentOrder, order_id)
    if not order or order.deleted_at is not None:
        not_found("集运订单")
    # 解除关联淘宝订单的挂靠，避免留下指向已删集运单的悬空外键
    session.execute(
        sa_update(TaobaoOrder)
        .where(TaobaoOrder.shipment_order_id == order_id, TaobaoOrder.deleted_at.is_(None))
        .values(shipment_order_id=None)
    )
    soft_delete(order)
    session.add(order)
    session.commit()
    return {"ok": True}
