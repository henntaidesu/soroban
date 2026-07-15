"""淘宝订单行（一单多物）。"""

from typing import Optional

from sqlmodel import Field, Relationship, SQLModel


class OrderItem(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    taobao_order_id: int = Field(foreign_key="taobaoorder.id", index=True)
    name: str = Field(max_length=255)                       # 物品名
    quantity: int = Field(default=1)                        # 数量（无单价，见 A3）

    taobao_order: Optional["TaobaoOrder"] = Relationship(back_populates="items")  # noqa: F821
