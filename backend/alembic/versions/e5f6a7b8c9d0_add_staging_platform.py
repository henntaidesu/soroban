"""add taobaostaging.platform (来源平台：淘宝/闲鱼/京东)

方言无关：add_column 在 SQLite 与 MySQL 上皆可直接执行。与账本 taobaoorder.platform 对齐，
导入暂存行时随单迁移。淘宝插件抓取的行默认「淘宝」。

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-07-16 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, Sequence[str], None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('taobaostaging', sa.Column('platform', sa.String(length=32), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('taobaostaging', 'platform')
