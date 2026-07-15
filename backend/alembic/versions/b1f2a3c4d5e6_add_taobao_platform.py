"""add taobaoorder.platform (来源平台：闲鱼/淘宝/京东)

Revision ID: b1f2a3c4d5e6
Revises: 53b7e33debd0
Create Date: 2026-07-15 22:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'b1f2a3c4d5e6'
down_revision: Union[str, Sequence[str], None] = '53b7e33debd0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('taobaoorder', schema=None) as batch_op:
        batch_op.add_column(sa.Column('platform', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
        batch_op.create_index(batch_op.f('ix_taobaoorder_platform'), ['platform'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('taobaoorder', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_taobaoorder_platform'))
        batch_op.drop_column('platform')
