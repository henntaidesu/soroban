"""标签选项：列头可管理的下拉集（如淘宝账号、集运收货人）。字段白名单限定。

下拉可选值 = 手动维护的标签（列头增删/预设） ∪ 数据里实际出现过的值。
后者让**爬虫直接把新账号/收货人写进订单（哪怕绕过 API、直写库）就自动成为可选项**，
无需再单独往 TagOption 里登记。删除某手动标签只是把它移出预设；若该值仍被数据使用，
仍会因「数据里出现过」继续可选（在用的值本就该能再选）。"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session, select

from ..auth import get_current_user
from ..database import get_session
from ..models import ShipmentOrder, TagOption, TaobaoOrder, TaobaoStaging
from ..schemas import TagIn

router = APIRouter(
    prefix="/api/tags", tags=["tags"], dependencies=[Depends(get_current_user)]
)

_ALLOWED_FIELDS = {"taobao_account", "recipient"}

# 每个标签字段 → 数据里承载该值的 (模型, 列)。用于把「数据里出现过的值」并入可选集。
# 淘宝账号同时看正式订单与暂存（爬虫先写暂存，账号即时可选）；收货人看集运订单。
_FIELD_SOURCES = {
    "taobao_account": (
        (TaobaoOrder, TaobaoOrder.taobao_account),
        (TaobaoStaging, TaobaoStaging.taobao_account),
    ),
    "recipient": ((ShipmentOrder, ShipmentOrder.recipient),),
}


def _check_field(field: str) -> None:
    if field not in _ALLOWED_FIELDS:
        raise HTTPException(status_code=422, detail=f"未知标签字段: {field}")


def _values(session: Session, field: str) -> list[str]:
    # 手动标签在前，保留列头里的插入顺序（含尚未被任何行使用的预设）
    manual = [
        r.value for r in session.exec(
            select(TagOption).where(TagOption.field == field).order_by(TagOption.id)
        ).all()
    ]
    seen = set(manual)
    # 数据里出现过、但不在手动集里的值，去重后按序追加（软删表排除已删行）
    extras: list[str] = []
    for model, col in _FIELD_SOURCES.get(field, ()):
        stmt = select(col).where(col.is_not(None)).distinct()
        if hasattr(model, "deleted_at"):
            stmt = stmt.where(model.deleted_at.is_(None))
        for v in session.exec(stmt).all():
            if v and v not in seen:
                seen.add(v)
                extras.append(v)
    return manual + sorted(extras)


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
