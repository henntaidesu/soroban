"""Request/response schemas. Keep money as Decimal/int (P1). Validate fx range (P6)."""

import datetime as dt
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from pydantic import field_validator
from sqlmodel import SQLModel

from .models import ShipmentStatus, Source, StagingStatus, TaobaoStatus

FX_MIN, FX_MAX = Decimal("5"), Decimal("50")   # 1 CNY = X JPY 合理区间（P6）
_CNY_Q = Decimal("0.01")     # 人民币量化到分
_FX_Q = Decimal("0.0001")    # 汇率量化到 4 位
_STAGING_STATUS = {s.value for s in StagingStatus}
_SOURCES = {s.value for s in Source}
_TAOBAO_STATUS = {s.value for s in TaobaoStatus}
_SHIPMENT_STATUS = {s.value for s in ShipmentStatus}


# --- 通用金额输入校验 mixin ---------------------------------------------------

class MoneyIn(SQLModel):
    price_cny: Optional[Decimal] = None
    fx_rate: Optional[Decimal] = None
    jpy_override: Optional[int] = None
    override_note: Optional[str] = None

    @field_validator("price_cny")
    @classmethod
    def _q_cny(cls, v: Optional[Decimal]) -> Optional[Decimal]:
        # 量化到 2 位，保证入库值与派生日元用的是同一个数（防 >2dp 不一致）
        if v is None:
            return None
        v = Decimal(v).quantize(_CNY_Q, rounding=ROUND_HALF_UP)
        if v < 0:
            raise ValueError("金额不能为负数（退款/取消请用状态标记，自动不计入合计）")
        return v

    @field_validator("jpy_override")
    @classmethod
    def _nonneg_override(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v < 0:
            raise ValueError("覆盖金额不能为负数（退款/取消请用状态标记）")
        return v

    @field_validator("fx_rate")
    @classmethod
    def _fx_range(cls, v: Optional[Decimal]) -> Optional[Decimal]:
        if v is None:
            return None
        v = Decimal(v).quantize(_FX_Q, rounding=ROUND_HALF_UP)
        if not (FX_MIN <= v <= FX_MAX):
            raise ValueError(f"汇率 {v} 不在合理区间 [{FX_MIN}, {FX_MAX}]（1元≈20円）")
        return v


class MoneyOut(SQLModel):
    price_cny: Optional[Decimal] = None
    fx_rate: Optional[Decimal] = None
    jpy_override: Optional[int] = None
    override_note: Optional[str] = None
    jpy_auto: Optional[int] = None
    jpy_settled: Optional[int] = None


def _check(value: str, allowed: set[str], label: str) -> str:
    if value not in allowed:
        raise ValueError(f"非法{label}: {value!r}，允许值 {sorted(allowed)}")
    return value


# --- 认证 -------------------------------------------------------------------

class LoginRequest(SQLModel):
    username: str
    password: str


class ChangePassword(SQLModel):
    old_password: str
    new_password: str


class UserRead(SQLModel):
    id: int
    username: str
    display_name: Optional[str] = None


class LoginResponse(SQLModel):
    access_token: str
    token_type: str = "bearer"
    user: UserRead


# --- 淘宝订单 ---------------------------------------------------------------

class OrderItemIn(SQLModel):
    name: str
    quantity: int = 1


class OrderItemRead(SQLModel):
    id: int
    name: str
    quantity: int


class TaobaoBase(MoneyIn):
    date: dt.date
    order_no: Optional[str] = None
    shop: Optional[str] = None
    url: Optional[str] = None
    category: Optional[str] = None
    status: str = TaobaoStatus.paid.value
    platform: Optional[str] = None
    express_no: Optional[str] = None
    express_company: Optional[str] = None
    taobao_account: Optional[str] = None
    shipment_order_id: Optional[int] = None
    payer_id: Optional[int] = None
    note: Optional[str] = None

    @field_validator("status")
    @classmethod
    def _status(cls, v: str) -> str:
        return _check(v, _TAOBAO_STATUS, "淘宝状态")


class TaobaoCreate(TaobaoBase):
    items: list[OrderItemIn] = []


class TaobaoUpdate(MoneyIn):
    version: int                                   # 乐观锁必填
    date: Optional[dt.date] = None
    order_no: Optional[str] = None
    shop: Optional[str] = None
    url: Optional[str] = None
    category: Optional[str] = None
    status: Optional[str] = None
    platform: Optional[str] = None
    express_no: Optional[str] = None
    express_company: Optional[str] = None
    taobao_account: Optional[str] = None
    shipment_order_id: Optional[int] = None
    payer_id: Optional[int] = None
    note: Optional[str] = None
    items: Optional[list[OrderItemIn]] = None      # 给了就整体替换

    @field_validator("status")
    @classmethod
    def _status(cls, v: Optional[str]) -> Optional[str]:
        return v if v is None else _check(v, _TAOBAO_STATUS, "淘宝状态")


class TaobaoRead(MoneyOut):
    id: int
    date: dt.date
    order_no: Optional[str] = None
    shop: Optional[str] = None
    url: Optional[str] = None
    category: Optional[str] = None
    status: str
    platform: Optional[str] = None
    express_no: Optional[str] = None
    express_company: Optional[str] = None
    taobao_account: Optional[str] = None
    shipment_order_id: Optional[int] = None
    payer_id: Optional[int] = None
    note: Optional[str] = None
    source: str
    version: int
    created_at: dt.datetime
    updated_at: dt.datetime
    items: list[OrderItemRead] = []


# --- 集运订单 ---------------------------------------------------------------

class ShipmentBase(MoneyIn):
    date: dt.date
    shipment_no: Optional[str] = None
    weight: Optional[Decimal] = None
    intl_tracking_no: Optional[str] = None
    status: str = ShipmentStatus.packing.value
    special_fee_jpy: Optional[int] = None
    recipient: Optional[str] = None
    payer_id: Optional[int] = None
    note: Optional[str] = None

    @field_validator("status")
    @classmethod
    def _status(cls, v: str) -> str:
        return _check(v, _SHIPMENT_STATUS, "集运状态")

    @field_validator("special_fee_jpy")
    @classmethod
    def _nonneg_fee(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v < 0:
            raise ValueError("特殊费不能为负数（退款/取消请用状态标记）")
        return v


class ShipmentCreate(ShipmentBase):
    pass


class ShipmentUpdate(MoneyIn):
    version: int
    date: Optional[dt.date] = None
    shipment_no: Optional[str] = None
    weight: Optional[Decimal] = None
    intl_tracking_no: Optional[str] = None
    status: Optional[str] = None
    special_fee_jpy: Optional[int] = None
    recipient: Optional[str] = None
    payer_id: Optional[int] = None
    note: Optional[str] = None

    @field_validator("status")
    @classmethod
    def _status(cls, v: Optional[str]) -> Optional[str]:
        return v if v is None else _check(v, _SHIPMENT_STATUS, "集运状态")

    @field_validator("special_fee_jpy")
    @classmethod
    def _nonneg_fee(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v < 0:
            raise ValueError("特殊费不能为负数（退款/取消请用状态标记）")
        return v


class TaobaoBrief(SQLModel):
    id: int
    order_no: Optional[str] = None
    date: dt.date
    shop: Optional[str] = None
    status: str
    jpy_settled: Optional[int] = None
    items: list[OrderItemRead] = []


class ShipmentRead(MoneyOut):
    id: int
    date: dt.date
    shipment_no: Optional[str] = None
    weight: Optional[Decimal] = None
    intl_tracking_no: Optional[str] = None
    status: str
    special_fee_jpy: Optional[int] = None
    recipient: Optional[str] = None
    payer_id: Optional[int] = None
    note: Optional[str] = None
    source: str
    version: int
    created_at: dt.datetime
    updated_at: dt.datetime
    taobao_orders: list[TaobaoBrief] = []


# --- 杂项 -------------------------------------------------------------------

class MiscBase(MoneyIn):
    date: dt.date
    name: str
    category: Optional[str] = None
    payer_id: Optional[int] = None
    note: Optional[str] = None


class MiscCreate(MiscBase):
    pass


class MiscUpdate(MoneyIn):
    version: int
    date: Optional[dt.date] = None
    name: Optional[str] = None
    category: Optional[str] = None
    payer_id: Optional[int] = None
    note: Optional[str] = None


class MiscRead(MoneyOut):
    id: int
    date: dt.date
    name: str
    category: Optional[str] = None
    payer_id: Optional[int] = None
    note: Optional[str] = None
    source: str
    version: int
    created_at: dt.datetime
    updated_at: dt.datetime


# --- 看板 -------------------------------------------------------------------

class MonthTotal(SQLModel):
    month: str          # YYYY-MM
    jpy: int


class DashboardRead(SQLModel):
    total_jpy: int
    taobao_jpy: int
    shipment_jpy: int
    misc_jpy: int
    taobao_count: int
    shipment_count: int
    misc_count: int
    by_month: list[MonthTotal] = []
    fx_rate: Optional[Decimal] = None       # 当前 CNY→JPY（兜底值）


# --- 汇率 -------------------------------------------------------------------

class FxRead(SQLModel):
    base: str = "CNY"
    quote: str = "JPY"
    rate: Optional[Decimal] = None
    date: Optional[dt.date] = None
    stale: bool = False                     # True = 用的是历史兜底值


# --- 淘宝抓取暂存（全部淘宝订单 → 确认导入）---------------------------------

class StagingItemIn(SQLModel):
    name: str
    quantity: int = 1


class StagingItemRead(SQLModel):
    id: int
    name: str
    quantity: int


class StagingBase(SQLModel):
    order_no: Optional[str] = None
    taobao_account: Optional[str] = None
    shop: Optional[str] = None
    price_cny: Optional[Decimal] = None
    fx_rate: Optional[Decimal] = None
    order_date: Optional[dt.date] = None
    express_no: Optional[str] = None
    order_status: Optional[str] = None       # 淘宝订单真实状态（已付/已发/…），导入后与账本联动

    @field_validator("price_cny")
    @classmethod
    def _q_cny(cls, v: Optional[Decimal]) -> Optional[Decimal]:
        if v is None:
            return None
        v = Decimal(v).quantize(_CNY_Q, rounding=ROUND_HALF_UP)
        if v < 0:
            raise ValueError("金额不能为负数（退款/取消请用状态标记，自动不计入合计）")
        return v

    @field_validator("fx_rate")
    @classmethod
    def _fx_range(cls, v: Optional[Decimal]) -> Optional[Decimal]:
        if v is None:
            return None
        v = Decimal(v).quantize(_FX_Q, rounding=ROUND_HALF_UP)
        if not (FX_MIN <= v <= FX_MAX):
            raise ValueError(f"汇率 {v} 不在合理区间 [{FX_MIN}, {FX_MAX}]")
        return v

    @field_validator("order_status")
    @classmethod
    def _order_status(cls, v: Optional[str]) -> Optional[str]:
        return v if v is None else _check(v, _TAOBAO_STATUS, "订单状态")


class StagingCreate(StagingBase):
    status: str = StagingStatus.pending.value
    items: list[StagingItemIn] = []


class StagingUpdate(StagingBase):
    version: int                                       # 乐观锁必填
    status: Optional[str] = None
    items: Optional[list[StagingItemIn]] = None       # 给了就整体替换

    @field_validator("status")
    @classmethod
    def _status(cls, v: Optional[str]) -> Optional[str]:
        return v if v is None else _check(v, _STAGING_STATUS, "暂存状态")


class StagingRead(StagingBase):
    id: int
    version: int
    status: str
    imported_taobao_order_id: Optional[int] = None
    scraped_at: dt.datetime
    items: list[StagingItemRead] = []


# --- 列布局 -----------------------------------------------------------------

class LayoutColumn(SQLModel):
    key: str
    width: int


class LayoutRead(SQLModel):
    table_name: str
    columns: list[LayoutColumn] = []


class LayoutUpdate(SQLModel):
    columns: list[LayoutColumn]


# --- 标签选项（列头可管理的下拉集）------------------------------------------

class TagIn(SQLModel):
    value: str


# --- 爬虫插件配置 -----------------------------------------------------------

class PluginConfigIn(SQLModel):
    enabled: bool = False
    params: dict = {}                 # 用户填的参数（如 {"accounts": "acctA,acctB"}）
    schedule_minutes: int = 0         # 定时抓取间隔（分钟），0=不定时


class TagOut(SQLModel):
    value: str
    color: int                      # 调色盘序号（0..N-1），前端映射到 TAG_PALETTE
    in_use: bool = False            # 是否被数据（订单/暂存/集运）使用中——使用中不可删除
