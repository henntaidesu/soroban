"""淘宝抓取暂存（机器人只写这里，人手动导入才进正表）+ 暂存物品行。"""

import datetime as dt
from decimal import Decimal
from typing import Optional

from sqlalchemy import Column, Index, Text, text
from sqlmodel import Field, Relationship, SQLModel

from ..base import StagingStatus, utcnow


class TaobaoStaging(SQLModel, table=True):
    # 淘宝订单号本身全局唯一 → 对非空 order_no 建部分唯一索引（去重键，供 bot upsert）；
    # 允许多条 order_no 为空的手动新建行（SQLite 多 NULL 视为不同，部分索引也不约束 NULL）。
    # MySQL 侧同样由迁移用「生成列 + 唯一键」等价实现（见 app/db/dialect.py）。
    __table_args__ = (
        Index(
            "ix_staging_order_no",
            "order_no",
            unique=True,
            sqlite_where=text("order_no IS NOT NULL"),
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    order_no: Optional[str] = Field(default=None, max_length=64)  # 可空：手动新建空行后再填
    taobao_account: Optional[str] = Field(default=None, max_length=64)
    shop: Optional[str] = Field(default=None, max_length=255)
    price_cny: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2)
    fx_rate: Optional[Decimal] = Field(default=None, max_digits=10, decimal_places=4)  # 新建/抓取时记当天汇率，导入一同迁移
    order_date: Optional[dt.date] = None
    express_no: Optional[str] = Field(default=None, max_length=64)
    raw_json: Optional[str] = Field(default=None, sa_column=Column(Text))  # 原始留底
    status: str = Field(default=StagingStatus.pending.value, max_length=32, index=True)  # 导入工作流状态：待处理/已导入/已忽略
    order_status: Optional[str] = Field(default=None, max_length=32)  # 淘宝订单真实状态(已付/已发/…)；导入后与账本 status 联动
    imported_taobao_order_id: Optional[int] = Field(
        default=None, foreign_key="taobaoorder.id"
    )
    version: int = Field(default=1)                         # 乐观锁（人工/爬虫并发编辑同一暂存行）
    scraped_at: dt.datetime = Field(default_factory=utcnow)
    updated_at: dt.datetime = Field(default_factory=utcnow)

    items: list["StagingItem"] = Relationship(
        back_populates="staging",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class StagingItem(SQLModel, table=True):
    """暂存订单的物品行（一单多物），结构对齐 OrderItem。"""

    id: Optional[int] = Field(default=None, primary_key=True)
    staging_id: int = Field(foreign_key="taobaostaging.id", index=True)
    name: str = Field(max_length=255)
    quantity: int = Field(default=1)

    staging: Optional[TaobaoStaging] = Relationship(back_populates="items")
