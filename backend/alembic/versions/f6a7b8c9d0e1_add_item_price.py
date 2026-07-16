"""add orderitem/stagingitem price_cny(单价) + auto(自动生成标记)

最小单位改为「物品」：物品带单价，订单价 = Σ(单价×数量)（派生）。方言无关（add_column）。
既有行的数据回填由一次性脚本完成（见 tools/backfill_item_price.py，本迁移只加列）。

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-07-16 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f6a7b8c9d0e1'
down_revision: Union[str, Sequence[str], None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    for table in ("orderitem", "stagingitem"):
        op.add_column(table, sa.Column('price_cny', sa.Numeric(precision=12, scale=2), nullable=True))
        op.add_column(table, sa.Column('auto', sa.Boolean(), nullable=False, server_default=sa.text('0')))


def downgrade() -> None:
    """Downgrade schema."""
    for table in ("orderitem", "stagingitem"):
        op.drop_column(table, 'auto')
        op.drop_column(table, 'price_cny')
