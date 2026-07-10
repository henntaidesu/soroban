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
from ..schemas import StagingCreate, StagingRead, StagingUpdate, TaobaoRead
from .common import not_found

router = APIRouter(
    prefix="/api/staging", tags=["staging"], dependencies=[Depends(get_current_user)]
)


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
    return {"items": [StagingRead.model_validate(r) for r in rows], "total": total}


@router.post("", response_model=StagingRead)
def create_staging(payload: StagingCreate, session: Session = Depends(get_session)):
    row = TaobaoStaging(**payload.model_dump(exclude={"items"}))
    row.items = [StagingItem(name=it.name, quantity=it.quantity) for it in payload.items]
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


@router.patch("/{row_id}", response_model=StagingRead)
def update_staging(row_id: int, payload: StagingUpdate, session: Session = Depends(get_session)):
    row = session.get(TaobaoStaging, row_id)
    if not row:
        not_found("暂存记录")
    for key, value in payload.model_dump(exclude_unset=True, exclude={"items"}).items():
        setattr(row, key, value)
    if payload.items is not None:                       # 给了 items 就整体替换（[] = 清空）
        row.items.clear()
        for it in payload.items:
            row.items.append(StagingItem(name=it.name, quantity=it.quantity))
    row.updated_at = utcnow()
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


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
    row = session.get(TaobaoStaging, row_id)
    if not row:
        not_found("暂存记录")
    row.status = StagingStatus.ignored.value
    row.updated_at = utcnow()
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


@router.post("/{row_id}/import", response_model=TaobaoRead)
def import_staging(row_id: int, session: Session = Depends(get_session)):
    """从暂存行生成正式淘宝订单（含全部物品），并标记暂存为已导入。"""
    from ..services.fx import current_rate  # 局部导入避免循环

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
        express_no=row.express_no,
        price_cny=row.price_cny,
        fx_rate=current_rate(session),          # 用当前汇率预填，可到账本再改
        status=TaobaoStatus.paid.value,
        source=Source.imported.value,
    )
    order.compute_money()
    order.items = [OrderItem(name=it.name, quantity=it.quantity) for it in row.items]
    session.add(order)
    session.flush()                             # 拿到 order.id

    # 原子门闸：只有 imported 仍为空的那次导入能成功，防并发/重复导入建重复单
    claimed = session.execute(
        sa_update(TaobaoStaging)
        .where(TaobaoStaging.id == row_id, TaobaoStaging.imported_taobao_order_id.is_(None))
        .values(
            status=StagingStatus.imported.value,
            imported_taobao_order_id=order.id,
            updated_at=utcnow(),
        )
    )
    if claimed.rowcount != 1:                    # 被别人抢先导入 → 回滚刚建的订单
        raise HTTPException(status_code=409, detail="该记录已导入")

    session.commit()                            # order_no 与账本冲突 → IntegrityError → 全局 409
    session.refresh(order)
    return order
