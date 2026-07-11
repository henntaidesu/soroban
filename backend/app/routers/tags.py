"""标签选项：列头可管理的下拉集（如淘宝账号、集运收货人）。字段白名单限定。

删除某标签只是把它移出「可选集」，不改动已用该值的历史行。"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session, select

from ..auth import get_current_user
from ..database import get_session
from ..models import TagOption
from ..schemas import TagIn

router = APIRouter(
    prefix="/api/tags", tags=["tags"], dependencies=[Depends(get_current_user)]
)

_ALLOWED_FIELDS = {"taobao_account", "recipient"}


def _check_field(field: str) -> None:
    if field not in _ALLOWED_FIELDS:
        raise HTTPException(status_code=422, detail=f"未知标签字段: {field}")


def _values(session: Session, field: str) -> list[str]:
    rows = session.exec(
        select(TagOption).where(TagOption.field == field).order_by(TagOption.id)
    ).all()
    return [r.value for r in rows]


@router.get("/{field}", response_model=list[str])
def list_tags(field: str, session: Session = Depends(get_session)):
    _check_field(field)
    return _values(session, field)


@router.post("/{field}", response_model=list[str])
def add_tag(field: str, payload: TagIn, session: Session = Depends(get_session)):
    _check_field(field)
    value = payload.value.strip()
    if not value:
        raise HTTPException(status_code=422, detail="标签不能为空")
    # 原子去重插入：已存在则忽略（并发/重复添加都安全，不抛 409）
    session.execute(
        sqlite_insert(TagOption)
        .values(field=field, value=value)
        .on_conflict_do_nothing(index_elements=["field", "value"])
    )
    session.commit()
    return _values(session, field)


@router.delete("/{field}/{value:path}", response_model=list[str])
def remove_tag(field: str, value: str, session: Session = Depends(get_session)):
    _check_field(field)
    row = session.exec(
        select(TagOption).where(TagOption.field == field, TagOption.value == value)
    ).first()
    if row:
        session.delete(row)
        session.commit()
    return _values(session, field)
