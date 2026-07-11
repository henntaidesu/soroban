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
from ..schemas import StagingCreate, StagingItemRead, StagingRead, StagingUpdate, TaobaoRead
from .common import conflict, guarded_bump, not_found

router = APIRouter(
    prefix="/api/staging", tags=["staging"], dependencies=[Depends(get_current_user)]
)

# 已导入行：暂存字段 → 账本字段的映射（单一真源写穿账本；status=导入工作流状态留暂存自身）
_SHARED_TO_ORDER = {
    "order_date": "date",
    "order_no": "order_no",
    "shop": "shop",
    "taobao_account": "taobao_account",
    "express_no": "express_no",
    "price_cny": "price_cny",
    "fx_rate": "fx_rate",
    "order_status": "status",
}


def _linked_order(session: Session, row: TaobaoStaging) -> Optional[TaobaoOrder]:
    """已导入且账本订单仍在（未软删）→ 返回该订单，否则 None。"""
    if row.imported_taobao_order_id is None:
        return None
    order = session.get(TaobaoOrder, row.imported_taobao_order_id)
    return order if order and order.deleted_at is None else None


def _read(session: Session, row: TaobaoStaging) -> StagingRead:
    """已导入行的共享字段用账本的实时值覆盖显示（单一真源，两页永远一致）。"""
    data = StagingRead.model_validate(row)
    order = _linked_order(session, row)
    if order is not None:
        data.order_date = order.date
        data.order_no = order.order_no
        data.shop = order.shop
        data.taobao_account = order.taobao_account
        data.express_no = order.express_no
        data.price_cny = order.price_cny
        data.fx_rate = order.fx_rate
        data.order_status = order.status
        data.items = [StagingItemRead(id=it.id, name=it.name, quantity=it.quantity) for it in order.items]
    return data


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
    return {"items": [_read(session, r) for r in rows], "total": total}


@router.post("", response_model=StagingRead)
def create_staging(payload: StagingCreate, session: Session = Depends(get_session)):
    from ..services.fx import current_rate  # 局部导入避免循环

    row = TaobaoStaging(**payload.model_dump(exclude={"items"}))
    if row.fx_rate is None:                  # 新建/抓取时记当天汇率
        row.fx_rate = current_rate(session)
    row.items = [StagingItem(name=it.name, quantity=it.quantity) for it in payload.items]
    session.add(row)
    session.commit()
    session.refresh(row)
    return _read(session, row)


@router.patch("/{row_id}", response_model=StagingRead)
def update_staging(row_id: int, payload: StagingUpdate, session: Session = Depends(get_session)):
    row = session.get(TaobaoStaging, row_id)
    if not row:
        not_found("暂存记录")
    # 暂存行乐观锁：加载后被爬虫/他人改过 → 409，前端刷新（version 原子自增 + 刷新 updated_at）
    if not guarded_bump(session, TaobaoStaging, row_id, payload.version):
        conflict()
    data = payload.model_dump(exclude_unset=True, exclude={"items", "version"})
    order = _linked_order(session, row)

    if order is not None:
        # 已导入：共享字段写穿到账本（唯一真源），仅「导入状态」留在暂存自身。
        # 账本侧再走一次乐观锁：原子自增账本 version，让淘宝页也能察觉此次改动。
        if not guarded_bump(session, TaobaoOrder, order.id, order.version):
            conflict()
        for key, value in data.items():
            if key in _SHARED_TO_ORDER:
                setattr(order, _SHARED_TO_ORDER[key], value)
            elif key == "status":
                row.status = value
        order.compute_money()
        if payload.items is not None:                   # 物品也写穿账本（[] = 清空）
            order.items.clear()
            for it in payload.items:
                order.items.append(OrderItem(name=it.name, quantity=it.quantity))
        session.add(order)
        session.add(row)
        session.commit()                                # order_no 撞账本唯一索引 → IntegrityError → 409
        session.refresh(row)
        return _read(session, row)

    # 未导入：编辑暂存自身副本
    for key, value in data.items():
        setattr(row, key, value)
    if payload.items is not None:                       # 给了 items 就整体替换（[] = 清空）
        row.items.clear()
        for it in payload.items:
            row.items.append(StagingItem(name=it.name, quantity=it.quantity))
    session.add(row)
    session.commit()
    session.refresh(row)
    return _read(session, row)


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
    row.version += 1
    row.updated_at = utcnow()
    session.add(row)
    session.commit()
    session.refresh(row)
    return _read(session, row)


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
        fx_rate=row.fx_rate or current_rate(session),   # 优先用暂存记录的当天汇率，一同迁移
        status=row.order_status or TaobaoStatus.paid.value,   # 订单状态一同迁移
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
            order_status=order.status,          # 快照对齐账本（此后以账本为准，读时覆盖）
            imported_taobao_order_id=order.id,
            version=TaobaoStaging.version + 1,
            updated_at=utcnow(),
        )
    )
    if claimed.rowcount != 1:                    # 被别人抢先导入 → 回滚刚建的订单
        raise HTTPException(status_code=409, detail="该记录已导入")

    session.commit()                            # order_no 与账本冲突 → IntegrityError → 全局 409
    session.refresh(order)
    return order
