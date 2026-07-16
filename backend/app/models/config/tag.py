"""标签选项（列头可管理的下拉集：如淘宝账号、收货人）。"""

from typing import Optional

from sqlalchemy import Index
from sqlmodel import Field, SQLModel


class TagOption(SQLModel, table=True):
    __table_args__ = (
        Index("ix_tagoption_field_value", "field", "value", unique=True),
    )
    id: Optional[int] = Field(default=None, primary_key=True)
    field: str = Field(max_length=32, index=True)      # 归属字段：platform_account / recipient
    value: str = Field(max_length=128)
    color: Optional[int] = Field(default=None)   # 调色盘序号（0..N-1），建标签时分配、之后不变（稳定不撞色）
