"""看板聚合：对 jpy_settled 求和；排除软删与不计入状态（取消/退款）（P4）。"""

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlmodel import Session, select

from ..auth import get_current_user
from ..database import get_session
from ..db.dialect import is_mysql
from ..models import EXCLUDED_STATUSES, ShipmentOrder, MiscExpense, Order
from ..schemas import DashboardRead, MonthTotal
from ..services.fx import current_rate

router = APIRouter(
    prefix="/api/dashboard", tags=["dashboard"], dependencies=[Depends(get_current_user)]
)

_EXCLUDED = tuple(EXCLUDED_STATUSES)


def _valid_conds(model, has_status: bool):
    conds = [model.is_delete.is_(False)]
    if has_status:
        conds.append(model.status.notin_(_EXCLUDED))   # 取消/退款不计入
    return conds


def _sum(session: Session, model, has_status: bool) -> int:
    conds = _valid_conds(model, has_status)
    return int(
        session.exec(
            select(func.coalesce(func.sum(model.jpy_settled), 0)).where(*conds)
        ).one()
    )


def _count(session: Session, model, has_status: bool) -> int:
    conds = _valid_conds(model, has_status)
    return int(session.exec(select(func.count()).select_from(model).where(*conds)).one())


def _month_expr(session: Session, date_col):
    """按月分组的 '%Y-%m' 表达式，跨方言：MySQL 用 DATE_FORMAT，SQLite 用 strftime。"""
    if is_mysql(session.get_bind()):
        return func.date_format(date_col, "%Y-%m")
    return func.strftime("%Y-%m", date_col)


def _by_month_cat(session: Session, model, has_status: bool) -> dict:
    """某类目按月的 {月份: (结算日元合计, 单数)}。"""
    conds = _valid_conds(model, has_status)
    month = _month_expr(session, model.date)
    rows = session.exec(
        select(month, func.coalesce(func.sum(model.jpy_settled), 0), func.count())
        .where(*conds)
        .group_by(month)
    ).all()
    return {m: (int(j), int(c)) for m, j, c in rows if m is not None}


@router.get("", response_model=DashboardRead)
def dashboard(session: Session = Depends(get_session)):
    order_jpy = _sum(session, Order, True)
    shipment_jpy = _sum(session, ShipmentOrder, True)
    misc_jpy = _sum(session, MiscExpense, False)

    tb = _by_month_cat(session, Order, True)
    sp = _by_month_cat(session, ShipmentOrder, True)
    mc = _by_month_cat(session, MiscExpense, False)
    by_month = []
    for m in sorted(set(tb) | set(sp) | set(mc), reverse=True):   # 最新月在前（卡片自上而下）
        t_j, t_c = tb.get(m, (0, 0))
        s_j, s_c = sp.get(m, (0, 0))
        x_j, x_c = mc.get(m, (0, 0))
        by_month.append(MonthTotal(
            month=m, jpy=t_j + s_j + x_j,
            order_jpy=t_j, shipment_jpy=s_j, misc_jpy=x_j,
            order_count=t_c, shipment_count=s_c, misc_count=x_c,
        ))

    return DashboardRead(
        total_jpy=order_jpy + shipment_jpy + misc_jpy,
        order_jpy=order_jpy,
        shipment_jpy=shipment_jpy,
        misc_jpy=misc_jpy,
        order_count=_count(session, Order, True),
        shipment_count=_count(session, ShipmentOrder, True),
        misc_count=_count(session, MiscExpense, False),
        by_month=by_month,
        fx_rate=current_rate(session),
    )
