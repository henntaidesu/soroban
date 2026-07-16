"""看板聚合：对 jpy_settled 求和；排除软删与不计入状态（取消/退款）（P4）。"""

from collections import defaultdict

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlmodel import Session, select

from ..auth import get_current_user
from ..database import get_session
from ..db.dialect import is_mysql
from ..models import EXCLUDED_STATUSES, ShipmentOrder, MiscExpense, TaobaoOrder
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


def _by_month(session: Session, model, has_status: bool, bucket: dict) -> None:
    conds = _valid_conds(model, has_status)
    month = _month_expr(session, model.date)
    rows = session.exec(
        select(month, func.coalesce(func.sum(model.jpy_settled), 0))
        .where(*conds)
        .group_by(month)
    ).all()
    for m, total in rows:
        if m is not None:
            bucket[m] += int(total)


@router.get("", response_model=DashboardRead)
def dashboard(session: Session = Depends(get_session)):
    taobao_jpy = _sum(session, TaobaoOrder, True)
    shipment_jpy = _sum(session, ShipmentOrder, True)
    misc_jpy = _sum(session, MiscExpense, False)

    bucket: dict[str, int] = defaultdict(int)
    _by_month(session, TaobaoOrder, True, bucket)
    _by_month(session, ShipmentOrder, True, bucket)
    _by_month(session, MiscExpense, False, bucket)
    by_month = [MonthTotal(month=m, jpy=bucket[m]) for m in sorted(bucket)]

    return DashboardRead(
        total_jpy=taobao_jpy + shipment_jpy + misc_jpy,
        taobao_jpy=taobao_jpy,
        shipment_jpy=shipment_jpy,
        misc_jpy=misc_jpy,
        taobao_count=_count(session, TaobaoOrder, True),
        shipment_count=_count(session, ShipmentOrder, True),
        misc_count=_count(session, MiscExpense, False),
        by_month=by_month,
        fx_rate=current_rate(session),
    )
