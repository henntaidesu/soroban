"""taobaoorder: (order_no, platform) 唯一，替换原单列 order_no 唯一索引

保证「订单号 + 来源」唯一；id 仍为自增主键（不改主键）。仅约束 order_no 非空且未软删的行，
手动空行草稿（order_no 为空）照旧可多条并存。

方言翻译（见 app/db/dialect.py）：
- SQLite：部分唯一索引 ON (order_no, COALESCE(platform,'')) WHERE 未删且非空。
- MySQL：生成列 = 活跃行时 CONCAT(order_no, 分隔符, COALESCE(platform,''))，否则 NULL；
  再对生成列建唯一键。分隔符用 CHAR(31)（单元分隔符，不会出现在订单号/平台名中），
  避免 ('12','3X') 与 ('123','X') 拼接后相等的边界碰撞。

Revision ID: c2d3e4f5a6b7
Revises: b1f2a3c4d5e6
Create Date: 2026-07-15 22:30:00.000000

"""
from typing import Sequence, Union

from alembic import op

from app.db.dialect import drop_active_unique, emit_active_unique


# revision identifiers, used by Alembic.
revision: str = 'c2d3e4f5a6b7'
down_revision: Union[str, Sequence[str], None] = 'b1f2a3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_MYSQL_COMPOSITE = (
    "CASE WHEN order_no IS NOT NULL AND deleted_at IS NULL "
    "THEN CONCAT(order_no, CHAR(31 USING utf8mb4), COALESCE(platform, '')) END"
)


def upgrade() -> None:
    """Upgrade schema."""
    # 撤销 baseline 建的单列活跃唯一（含 MySQL 侧生成列）
    drop_active_unique(op, table='taobaoorder', index_name='ix_taobaoorder_order_no_active',
                       gen_col='order_no_active_key')
    # 建 (order_no, platform) 复合活跃唯一
    emit_active_unique(
        op,
        table='taobaoorder',
        index_name='ix_taobaoorder_order_no_platform_active',
        gen_col='order_no_platform_active_key',
        mysql_expr=_MYSQL_COMPOSITE,
        sqlite_columns="order_no, COALESCE(platform, '')",
        sqlite_where='order_no IS NOT NULL AND deleted_at IS NULL',
    )


def downgrade() -> None:
    """Downgrade schema."""
    drop_active_unique(op, table='taobaoorder', index_name='ix_taobaoorder_order_no_platform_active',
                       gen_col='order_no_platform_active_key')
    emit_active_unique(
        op,
        table='taobaoorder',
        index_name='ix_taobaoorder_order_no_active',
        gen_col='order_no_active_key',
        mysql_expr="CASE WHEN order_no IS NOT NULL AND deleted_at IS NULL THEN order_no END",
        sqlite_columns='order_no',
        sqlite_where='order_no IS NOT NULL AND deleted_at IS NULL',
    )
