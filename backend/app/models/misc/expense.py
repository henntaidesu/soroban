"""杂项支出。"""

from typing import Optional

from sqlmodel import Field

from ..base import LedgerBase


class MiscExpense(LedgerBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(max_length=255)                       # 名称
    category: Optional[str] = Field(default=None, max_length=64)  # 分类
