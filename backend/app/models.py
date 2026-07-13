"""Data models (SQLModel tables) for soroban.

金额规则（见 docs/README.md）：
- price_cny / fx_rate / jpy_override 是「输入」列。
- jpy_auto / jpy_settled 是「派生」列，但落库为普通 int 列，写入时由
  compute_money() 用 Decimal + ROUND_HALF_UP 精确算出（不用 float，不用生成列）。
- 结算优先级：jpy_override 有值就用它，否则用 jpy_auto。
"""

import datetime as dt
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Optional

from sqlalchemy import Index, text
from sqlmodel import Field, Relationship, SQLModel


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


# --- 枚举（作为「允许值」的唯一真相；DB 里存字符串值，schema 里做校验）----------

class Source(str, Enum):
    manual = "manual"
    imported = "imported"       # 从暂存表导入
    taobao_bot = "taobao_bot"
    shipment_bot = "shipment_bot"


class TaobaoStatus(str, Enum):
    unpaid = "待付款"       # 等待买家付款
    paid = "待发货"         # 买家已付款、待卖家发货
    shipped = "待收货"      # 卖家已发货
    received = "交易成功"
    refunded = "退款"
    cancelled = "交易关闭"


class ShipmentStatus(str, Enum):
    packing = "打包中"
    shipped = "已发出"
    arrived = "已签收"
    cancelled = "已取消"


class StagingStatus(str, Enum):
    pending = "待处理"
    imported = "已导入"
    ignored = "已忽略"


# 看板合计要排除的状态：未付款/退款/交易关闭都不计入（金额与物品仍照常显示，只是不加总）。
# 不再用「负数行」冲抵退款——打上退款/关闭标记即自动不计入。
EXCLUDED_STATUSES = {
    TaobaoStatus.unpaid.value,          # 待付款：还没花钱，不计入
    TaobaoStatus.refunded.value,        # 退款
    TaobaoStatus.cancelled.value,       # 交易关闭
    ShipmentStatus.cancelled.value,     # 集运已取消
}


# --- 共通基类：日期/备注/来源/付款人/乐观锁/软删/时间戳 + 金额输入与派生 --------

class LedgerBase(SQLModel):
    date: dt.date = Field(index=True)                       # 记录日期
    note: Optional[str] = None
    source: str = Field(default=Source.manual.value, index=True)
    payer_id: Optional[int] = Field(default=None, foreign_key="user.id")
    version: int = Field(default=1)                          # 乐观锁
    deleted_at: Optional[dt.datetime] = Field(default=None, index=True)  # 软删
    created_at: dt.datetime = Field(default_factory=utcnow)
    updated_at: dt.datetime = Field(default_factory=utcnow)

    # 金额输入列
    price_cny: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2)
    fx_rate: Optional[Decimal] = Field(default=None, max_digits=10, decimal_places=4)
    jpy_override: Optional[int] = Field(default=None)
    override_note: Optional[str] = Field(default=None)
    # 金额派生列（落库；写入时算，勿手改）
    jpy_auto: Optional[int] = Field(default=None)
    jpy_settled: Optional[int] = Field(default=None)

    def compute_money(self, extra_jpy: int = 0) -> None:
        """用 Decimal 精确重算 jpy_auto / jpy_settled。extra_jpy 供集运加特殊费。
        先把 cny/rate 量化到入库精度，保证派生日元与最终存储/展示值一致。"""
        if self.price_cny is not None and self.fx_rate is not None:
            cny = Decimal(self.price_cny).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            rate = Decimal(self.fx_rate).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
            auto = int((cny * rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP)) + extra_jpy
        elif extra_jpy:
            auto = extra_jpy
        else:
            auto = None
        self.jpy_auto = auto
        self.jpy_settled = self.jpy_override if self.jpy_override is not None else auto


# --- 用户 -------------------------------------------------------------------

class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(unique=True, index=True)
    password_hash: str
    display_name: Optional[str] = None
    is_active: bool = Field(default=True)
    created_at: dt.datetime = Field(default_factory=utcnow)


# --- 淘宝订单 + 订单行 -------------------------------------------------------

class TaobaoOrder(LedgerBase, table=True):
    # P3: 订单号唯一但要兼容软删 → 部分唯一索引（仅未删且非空的行）
    __table_args__ = (
        Index(
            "ix_taobaoorder_order_no_active",
            "order_no",
            unique=True,
            sqlite_where=text("order_no IS NOT NULL AND deleted_at IS NULL"),
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    order_no: Optional[str] = Field(default=None)            # 淘宝订单号
    shop: Optional[str] = None                               # 店铺
    url: Optional[str] = None                                # 商品链接
    category: Optional[str] = None                           # 分类
    status: str = Field(default=TaobaoStatus.paid.value, index=True)
    express_no: Optional[str] = Field(default=None, index=True)   # 快递号（归组用）
    express_company: Optional[str] = None                    # 快递公司
    taobao_account: Optional[str] = Field(default=None, index=True)  # 淘宝账号（2个）
    shipment_order_id: Optional[int] = Field(
        default=None, foreign_key="shipmentorder.id", index=True
    )  # 可空 = 已买未集运

    shipment_order: Optional["ShipmentOrder"] = Relationship(back_populates="taobao_orders")
    items: list["OrderItem"] = Relationship(
        back_populates="taobao_order",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class OrderItem(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    taobao_order_id: int = Field(foreign_key="taobaoorder.id", index=True)
    name: str                                               # 物品名
    quantity: int = Field(default=1)                        # 数量（无单价，见 A3）

    taobao_order: Optional[TaobaoOrder] = Relationship(back_populates="items")


# --- 集运订单 ---------------------------------------------------------------

class ShipmentOrder(LedgerBase, table=True):
    __table_args__ = (
        Index(
            "ix_shipmentorder_shipment_no_active",
            "shipment_no",
            unique=True,
            sqlite_where=text("shipment_no IS NOT NULL AND deleted_at IS NULL"),
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    shipment_no: Optional[str] = Field(default=None)         # 集运单号
    weight: Optional[Decimal] = Field(default=None, max_digits=8, decimal_places=2)  # 重量kg
    intl_tracking_no: Optional[str] = None                 # 国际运单号
    status: str = Field(default=ShipmentStatus.packing.value, index=True)
    special_fee_jpy: Optional[int] = Field(default=None)    # 特殊费（恒日元：关税/消费税等）
    recipient: Optional[str] = None                         # 收货人（标签，从可管理集里选）

    taobao_orders: list[TaobaoOrder] = Relationship(back_populates="shipment_order")

    def compute_money(self, extra_jpy: int = 0) -> None:
        # 集运 jpy_auto = round(运费×汇率) + 特殊费_日元
        super().compute_money(extra_jpy=(self.special_fee_jpy or 0) + extra_jpy)


# --- 杂项 -------------------------------------------------------------------

class MiscExpense(LedgerBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str                                               # 名称
    category: Optional[str] = None                          # 分类


# --- 汇率缓存（P7：持久化，抓取失败回退最近一条）----------------------------

class FxRate(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    date: dt.date = Field(unique=True, index=True)          # 该日汇率
    rate: Decimal = Field(max_digits=10, decimal_places=4)  # 1 CNY = rate JPY
    fetched_at: dt.datetime = Field(default_factory=utcnow)


# --- 配置表（预留 key-value；敏感凭证勿明文入库）----------------------------

class Setting(SQLModel, table=True):
    key: str = Field(primary_key=True)
    value: Optional[str] = None
    updated_at: dt.datetime = Field(default_factory=utcnow)


# --- 标签选项（列头可管理的下拉集：如淘宝账号、收货人）----------------------

class TagOption(SQLModel, table=True):
    __table_args__ = (
        Index("ix_tagoption_field_value", "field", "value", unique=True),
    )
    id: Optional[int] = Field(default=None, primary_key=True)
    field: str = Field(index=True)      # 归属字段：taobao_account / recipient
    value: str
    color: Optional[int] = Field(default=None)   # 调色盘序号（0..N-1），建标签时分配、之后不变（稳定不撞色）


# --- 爬虫插件配置（soroban 做管理层：存每个插件的启用/参数/定时；插件本体在 scraper/ 下）---

class PluginConfig(SQLModel, table=True):
    plugin_id: str = Field(primary_key=True)                # 对应 plugin.toml 的 id
    enabled: bool = Field(default=False)                    # 是否启用（定时抓取才生效）
    params_json: str = Field(default="{}")                  # 用户在插件管理页填的参数（如 accounts）
    schedule_minutes: int = Field(default=0)               # 定时抓取间隔（分钟），0=不定时
    last_run_at: Optional[dt.datetime] = Field(default=None)  # 上次自动抓取时间（定时循环判断用）
    updated_at: dt.datetime = Field(default_factory=utcnow)


# --- 列布局（每个表的列顺序+宽度，存后端，所有人一致）------------------------

class ColumnLayout(SQLModel, table=True):
    table_name: str = Field(primary_key=True)       # taobao / shipment / misc / staging
    columns_json: str = Field(default="[]")          # 有序 [{"key":..,"width":..}, ...]
    updated_at: dt.datetime = Field(default_factory=utcnow)


# --- 淘宝抓取暂存（预留：机器人只写这里，人手动导入才进正表）----------------

class TaobaoStaging(SQLModel, table=True):
    # 淘宝订单号本身全局唯一 → 对非空 order_no 建部分唯一索引（去重键，供 bot upsert）；
    # 允许多条 order_no 为空的手动新建行（SQLite 多 NULL 视为不同，部分索引也不约束 NULL）。
    __table_args__ = (
        Index(
            "ix_staging_order_no",
            "order_no",
            unique=True,
            sqlite_where=text("order_no IS NOT NULL"),
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    order_no: Optional[str] = None          # 可空：手动新建空行后再填
    taobao_account: Optional[str] = None
    shop: Optional[str] = None
    price_cny: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2)
    fx_rate: Optional[Decimal] = Field(default=None, max_digits=10, decimal_places=4)  # 新建/抓取时记当天汇率，导入一同迁移
    order_date: Optional[dt.date] = None
    express_no: Optional[str] = None
    raw_json: Optional[str] = None                          # 原始留底
    status: str = Field(default=StagingStatus.pending.value, index=True)  # 导入工作流状态：待处理/已导入/已忽略
    order_status: Optional[str] = Field(default=None)       # 淘宝订单真实状态(已付/已发/…)；导入后与账本 status 联动
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
    name: str
    quantity: int = Field(default=1)

    staging: Optional[TaobaoStaging] = Relationship(back_populates="items")
