"""物品列表（对接的最小单位）：把所有 OrderItem 拉平成一张表，附父订单只读上下文。

只读列表：筛选/搜索/分页与淘宝订单页一致。物品编辑仍在淘宝订单页的展开面板里做
（那里改物品会重算订单价并镜像暂存）。已软删订单的物品不出现。"""
import datetime as dt
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlmodel import Session, select

from ..auth import get_current_user
from ..database import get_session
from ..models import OrderItem, TaobaoOrder
from ..schemas import ItemListRead

router = APIRouter(
    prefix="/api/items", tags=["items"], dependencies=[Depends(get_current_user)]
)

_Q = Decimal("0.01")


@router.get("")
def list_items(
    session: Session = Depends(get_session),
    date_from: Optional[dt.date] = None,
    date_to: Optional[dt.date] = None,
    status: Optional[str] = None,
    taobao_account: Optional[str] = None,
    platform: Optional[str] = None,
    q: Optional[str] = Query(None, description="按物品名/订单号/商品搜索"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    conds = [TaobaoOrder.is_delete.is_(False)]   # 只列未软删订单的物品
    if date_from:
        conds.append(TaobaoOrder.date >= date_from)
    if date_to:
        conds.append(TaobaoOrder.date <= date_to)
    if status:
        conds.append(TaobaoOrder.status == status)
    if taobao_account:
        conds.append(TaobaoOrder.taobao_account == taobao_account)
    if platform:
        conds.append(TaobaoOrder.platform == platform)
    if q:
        conds.append(
            OrderItem.name.contains(q, autoescape=True)
            | TaobaoOrder.order_no.contains(q, autoescape=True)
            | TaobaoOrder.shop.contains(q, autoescape=True)
        )

    join = (OrderItem, TaobaoOrder.id == OrderItem.taobao_order_id)
    total = session.exec(
        select(func.count()).select_from(TaobaoOrder).join(*join).where(*conds)
    ).one()
    rows = session.exec(
        select(OrderItem, TaobaoOrder)
        .join(TaobaoOrder, TaobaoOrder.id == OrderItem.taobao_order_id)
        .where(*conds)
        .order_by(TaobaoOrder.date.desc(), TaobaoOrder.id.desc(), OrderItem.id.asc())
        .offset(offset)
        .limit(limit)
    ).all()

    items = []
    for it, o in rows:
        amount = None
        if it.price_cny is not None:
            amount = (Decimal(it.price_cny) * (it.quantity or 1)).quantize(_Q, rounding=ROUND_HALF_UP)
        items.append(ItemListRead(
            id=it.id, name=it.name, quantity=it.quantity, price_cny=it.price_cny,
            amount_cny=amount, auto=it.auto,
            order_id=o.id, date=o.date, order_no=o.order_no, shop=o.shop,
            taobao_account=o.taobao_account, platform=o.platform, status=o.status,
            express_no=o.express_no,
        ))
    return {"items": items, "total": total}
