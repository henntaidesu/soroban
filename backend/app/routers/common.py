"""Shared router helpers: optimistic lock (DB-level guard), soft delete, errors."""

from fastapi import HTTPException, status
from sqlalchemy import update as sa_update
from sqlmodel import Session

from ..models import utcnow


def not_found(name: str = "记录"):
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{name}不存在")


def conflict():
    """P5：乐观锁冲突 → 409，前端提示刷新。"""
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="数据已被他人或机器人修改，请刷新后重试",
    )


def guarded_bump(session: Session, model, obj_id: int, expected_version: int) -> bool:
    """原子地在 DB 层用 `WHERE version=expected` 守卫并自增 version（同时刷新 updated_at）。
    返回 False 表示版本已变（并发/交错写），调用方应抛 409。此 UPDATE 与后续的字段改动
    在同一事务提交，保证并发下不会丢失更新。"""
    conds = [model.id == obj_id, model.version == expected_version]
    if hasattr(model, "is_delete"):                     # 暂存表用硬删、无 is_delete 列，跳过该条件
        conds.append(model.is_delete.is_(False))
    res = session.execute(
        sa_update(model).where(*conds).values(version=model.version + 1, updated_at=utcnow())
    )
    return res.rowcount == 1


def soft_delete(obj) -> None:
    obj.is_delete = True
