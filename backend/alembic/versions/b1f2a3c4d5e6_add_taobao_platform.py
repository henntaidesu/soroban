"""add taobaoorder.platform (来源平台：闲鱼/淘宝/京东)

方言无关：add_column / create_index 在 SQLite 与 MySQL 上皆可直接执行。
仅把原 AutoString() 改成带长度的 sa.String(32) 以兼容 MySQL。

Revision ID: b1f2a3c4d5e6
Revises: 53b7e33debd0
Create Date: 2026-07-15 22:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b1f2a3c4d5e6'
down_revision: Union[str, Sequence[str], None] = '53b7e33debd0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('taobaoorder', sa.Column('platform', sa.String(length=32), nullable=True))
    op.create_index(op.f('ix_taobaoorder_platform'), 'taobaoorder', ['platform'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_taobaoorder_platform'), table_name='taobaoorder')
    op.drop_column('taobaoorder', 'platform')
