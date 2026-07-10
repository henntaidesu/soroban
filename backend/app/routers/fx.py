"""汇率查询：当前 CNY→JPY（含历史兜底）+ 手动刷新。"""

import datetime as dt

from fastapi import APIRouter, Depends
from sqlmodel import Session

from ..auth import get_current_user
from ..config import settings
from ..database import get_session
from ..schemas import FxRead
from ..services.fx import JST, latest_stored, refresh_and_store

router = APIRouter(
    prefix="/api/fx", tags=["fx"], dependencies=[Depends(get_current_user)]
)


@router.get("", response_model=FxRead)
def get_fx(session: Session = Depends(get_session)):
    row = latest_stored(session)
    if not row:
        return FxRead(base=settings.FX_BASE, quote=settings.FX_QUOTE)
    today = dt.datetime.now(JST).date()
    return FxRead(
        base=settings.FX_BASE,
        quote=settings.FX_QUOTE,
        rate=row.rate,
        date=row.date,
        stale=row.date < today,
    )


@router.post("/refresh", response_model=FxRead)
async def refresh(session: Session = Depends(get_session)):
    row = await refresh_and_store(session)
    if not row:
        return FxRead(base=settings.FX_BASE, quote=settings.FX_QUOTE)
    today = dt.datetime.now(JST).date()
    return FxRead(
        base=settings.FX_BASE,
        quote=settings.FX_QUOTE,
        rate=row.rate,
        date=row.date,
        stale=row.date < today,
    )
