"""看板聚合：对 jpy_settled 求和；排除软删与已取消（P4）。"""

from collections import defaultdict

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlmodel import Session, select

from ..auth import get_current_user
from ..database import get_session
from ..models import CANCELLED_STATUSES, JunfengOrder, MiscExpense, TaobaoOrder
from ..schemas import DashboardRead, MonthTotal
from ..services.fx import current_rate

router = APIRouter(
    prefix="/api/dashboard", tags=["dashboard"], dependencies=[Depends(get_current_user)]
)

_CANCELLED = tuple(CANCELLED_STATUSES)


def _valid_conds(model, has_status: bool):
    conds = [model.deleted_at.is_(None)]
    if has_status:
        conds.append(model.status.notin_(_CANCELLED))
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


def _by_month(session: Session, model, has_status: bool, bucket: dict) -> None:
    conds = _valid_conds(model, has_status)
    month = func.strftime("%Y-%m", model.date)
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
    junfeng_jpy = _sum(session, JunfengOrder, True)
    misc_jpy = _sum(session, MiscExpense, False)

    bucket: dict[str, int] = defaultdict(int)
    _by_month(session, TaobaoOrder, True, bucket)
    _by_month(session, JunfengOrder, True, bucket)
    _by_month(session, MiscExpense, False, bucket)
    by_month = [MonthTotal(month=m, jpy=bucket[m]) for m in sorted(bucket)]

    return DashboardRead(
        total_jpy=taobao_jpy + junfeng_jpy + misc_jpy,
        taobao_jpy=taobao_jpy,
        junfeng_jpy=junfeng_jpy,
        misc_jpy=misc_jpy,
        taobao_count=_count(session, TaobaoOrder, True),
        junfeng_count=_count(session, JunfengOrder, True),
        misc_count=_count(session, MiscExpense, False),
        by_month=by_month,
        fx_rate=current_rate(session),
    )
