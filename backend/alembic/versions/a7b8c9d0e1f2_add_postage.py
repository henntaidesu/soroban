"""add taobaoorder/taobaostaging postage_cny (邮费)

邮费为可编辑的每单字段：空=包邮(0)。订单价 = Σ(单价×数量) + 邮费。方言无关（add_column）。
既有行 NULL=包邮，订单价不变，无需回填。

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-07-16 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, Sequence[str], None] = 'f6a7b8c9d0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    for table in ("taobaoorder", "taobaostaging"):
        op.add_column(table, sa.Column('postage_cny', sa.Numeric(precision=12, scale=2), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    for table in ("taobaoorder", "taobaostaging"):
        op.drop_column(table, 'postage_cny')
