"""标签选项：列头可管理的下拉集（如淘宝账号、集运收货人）。字段白名单限定。

- 每个标签持久化一个**颜色序号**（0..N-1）：建标签时分配、之后不再变动，故加/删标签
  不会改动其它标签的颜色（稳定），且前 N 个各不相同（不撞色）。
- 数据里出现过的值（爬虫/直写库写进订单）会**自动登记为标签并分配颜色**，无需手动登记。
- 正在被数据使用中的标签**不可删除**（前端隐藏删除按钮，后端亦拒绝）——避免删掉在用的值。
"""

from collections import Counter

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session, select

from ..auth import get_current_user
from ..database import get_session
from ..models import ShipmentOrder, StagingStatus, TagOption, TaobaoOrder, TaobaoStaging
from ..schemas import TagIn, TagOut

router = APIRouter(
    prefix="/api/tags", tags=["tags"], dependencies=[Depends(get_current_user)]
)

_ALLOWED_FIELDS = {"taobao_account", "recipient"}
_N_COLORS = 10   # 与前端 TAG_PALETTE 长度一致

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


def _data_values(session: Session, field: str) -> set[str]:
    """该字段在数据里实际用到的值（订单/暂存/集运，排除软删）。"""
    out: set[str] = set()
    for model, col in _FIELD_SOURCES.get(field, ()):
        stmt = select(col).where(col.is_not(None)).distinct()
        if hasattr(model, "is_delete"):
            stmt = stmt.where(model.is_delete.is_(False))
        if model is TaobaoStaging:
            # 已忽略的暂存行是「看过后丢弃」的抓取结果，不算真在用（否则其账号会被误锁、误自动登记）
            stmt = stmt.where(TaobaoStaging.status != StagingStatus.ignored.value)
        for v in session.exec(stmt).all():
            if v:
                out.add(v)
    return out


def _pick_color(counts: Counter) -> int:
    """挑一个颜色序号：优先没被用过的最小序号（前 N 个不撞色）；都用过了取用得最少的。"""
    for i in range(_N_COLORS):
        if counts[i] == 0:
            return i
    return min(range(_N_COLORS), key=lambda i: (counts[i], i))


def _sync(session: Session, field: str) -> list[TagOption]:
    """确保该字段所有标签都在库、都有颜色：补登记数据里出现的新值、回填历史空颜色。"""
    rows = session.exec(
        select(TagOption).where(TagOption.field == field).order_by(TagOption.id)
    ).all()
    counts = Counter(r.color for r in rows if r.color is not None)
    existing = {r.value for r in rows}
    changed = False
    for r in rows:                                  # 回填迁移前遗留的空颜色
        if r.color is None:
            r.color = _pick_color(counts)
            counts[r.color] += 1
            session.add(r)
            changed = True
    for v in sorted(_data_values(session, field) - existing):   # 自动登记数据里的新值
        color = _pick_color(counts)
        counts[color] += 1
        # 原子去重插入：并发 GET/写同时首见同一新值也安全（撞唯一键则忽略，不会让 GET 抛 409）
        session.execute(
            sqlite_insert(TagOption)
            .values(field=field, value=v, color=color)
            .on_conflict_do_nothing(index_elements=["field", "value"])
        )
        changed = True
    if changed:
        session.commit()
        rows = session.exec(
            select(TagOption).where(TagOption.field == field).order_by(TagOption.id)
        ).all()
    return rows


def _list(session: Session, field: str) -> list[TagOut]:
    rows = _sync(session, field)
    used = _data_values(session, field)
    return [TagOut(value=r.value, color=r.color, in_use=r.value in used) for r in rows]


@router.get("/{field}", response_model=list[TagOut])
def list_tags(field: str, session: Session = Depends(get_session)):
    _check_field(field)
    return _list(session, field)


@router.post("/{field}", response_model=list[TagOut])
def add_tag(field: str, payload: TagIn, session: Session = Depends(get_session)):
    _check_field(field)
    value = payload.value.strip()
    if not value:
        raise HTTPException(status_code=422, detail="标签不能为空")
    rows = session.exec(select(TagOption).where(TagOption.field == field)).all()
    if not any(r.value == value for r in rows):     # 新值才分配颜色（前 N 个不撞色）
        counts = Counter(r.color for r in rows if r.color is not None)
        color = _pick_color(counts)
        # 原子去重插入：并发/重复添加都安全（撞唯一键则忽略，颜色不生效）
        session.execute(
            sqlite_insert(TagOption)
            .values(field=field, value=value, color=color)
            .on_conflict_do_nothing(index_elements=["field", "value"])
        )
        session.commit()
    return _list(session, field)


@router.delete("/{field}/{value:path}", response_model=list[TagOut])
def remove_tag(field: str, value: str, session: Session = Depends(get_session)):
    _check_field(field)
    if value in _data_values(session, field):       # 使用中不可删（与前端隐藏删除按钮呼应）
        raise HTTPException(status_code=409, detail="该标签正被数据使用，不能删除")
    row = session.exec(
        select(TagOption).where(TagOption.field == field, TagOption.value == value)
    ).first()
    if row:
        session.delete(row)
        session.commit()
    return _list(session, field)
