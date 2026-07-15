"""软删改用布尔列 is_delete，替换 deleted_at 时间戳

三个账本表（taobaoorder / shipmentorder / miscexpense）：加 is_delete(bool, 默认 0)，
从 deleted_at 回填（deleted_at 非空 → 已删），删除 deleted_at 列及其索引。
两处「活跃唯一」约束（taobaoorder、shipmentorder）改用 is_delete = 0 重建
（含 MySQL 生成列表达式），暂存表 ix_staging_order_no 不涉软删、无需改。

Revision ID: d4e5f6a7b8c9
Revises: c2d3e4f5a6b7
Create Date: 2026-07-15 23:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.db.dialect import drop_active_unique, emit_active_unique


# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, Sequence[str], None] = 'c2d3e4f5a6b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_LEDGER_TABLES = ('taobaoorder', 'shipmentorder', 'miscexpense')

# 活跃唯一约束改用 is_delete = 0（原为 deleted_at IS NULL）
_TAOBAO_MYSQL = (
    "CASE WHEN order_no IS NOT NULL AND is_delete = 0 "
    "THEN CONCAT(order_no, CHAR(31 USING utf8mb4), COALESCE(platform, '')) END"
)
_TAOBAO_MYSQL_OLD = (
    "CASE WHEN order_no IS NOT NULL AND deleted_at IS NULL "
    "THEN CONCAT(order_no, CHAR(31 USING utf8mb4), COALESCE(platform, '')) END"
)


def upgrade() -> None:
    """Upgrade schema."""
    # 1) 加 is_delete 并从 deleted_at 回填
    for tbl in _LEDGER_TABLES:
        op.add_column(tbl, sa.Column('is_delete', sa.Boolean(), nullable=False,
                                     server_default=sa.text('0')))
        op.execute(f"UPDATE {tbl} SET is_delete = 1 WHERE deleted_at IS NOT NULL")
        op.create_index(op.f(f'ix_{tbl}_is_delete'), tbl, ['is_delete'], unique=False)

    # 2) 重建活跃唯一约束（改看 is_delete = 0）
    drop_active_unique(op, table='taobaoorder',
                       index_name='ix_taobaoorder_order_no_platform_active',
                       gen_col='order_no_platform_active_key')
    emit_active_unique(
        op, table='taobaoorder',
        index_name='ix_taobaoorder_order_no_platform_active',
        gen_col='order_no_platform_active_key',
        mysql_expr=_TAOBAO_MYSQL,
        sqlite_columns="order_no, COALESCE(platform, '')",
        sqlite_where='order_no IS NOT NULL AND is_delete = 0',
    )
    drop_active_unique(op, table='shipmentorder',
                       index_name='ix_shipmentorder_shipment_no_active',
                       gen_col='shipment_no_active_key')
    emit_active_unique(
        op, table='shipmentorder',
        index_name='ix_shipmentorder_shipment_no_active',
        gen_col='shipment_no_active_key',
        mysql_expr="CASE WHEN shipment_no IS NOT NULL AND is_delete = 0 THEN shipment_no END",
        sqlite_columns='shipment_no',
        sqlite_where='shipment_no IS NOT NULL AND is_delete = 0',
    )

    # 3) 删除 deleted_at 列及其索引（此时无索引/生成列再依赖它）
    for tbl in _LEDGER_TABLES:
        op.drop_index(op.f(f'ix_{tbl}_deleted_at'), table_name=tbl)
        op.drop_column(tbl, 'deleted_at')


def downgrade() -> None:
    """Downgrade schema."""
    # 1) 恢复 deleted_at，从 is_delete 回填（已删 → 用 updated_at 近似删除时间，无则 created_at）
    for tbl in _LEDGER_TABLES:
        op.add_column(tbl, sa.Column('deleted_at', sa.DateTime(), nullable=True))
        op.execute(f"UPDATE {tbl} SET deleted_at = COALESCE(updated_at, created_at) WHERE is_delete = 1")
        op.create_index(op.f(f'ix_{tbl}_deleted_at'), tbl, ['deleted_at'], unique=False)

    # 2) 活跃唯一约束改回 deleted_at IS NULL
    drop_active_unique(op, table='taobaoorder',
                       index_name='ix_taobaoorder_order_no_platform_active',
                       gen_col='order_no_platform_active_key')
    emit_active_unique(
        op, table='taobaoorder',
        index_name='ix_taobaoorder_order_no_platform_active',
        gen_col='order_no_platform_active_key',
        mysql_expr=_TAOBAO_MYSQL_OLD,
        sqlite_columns="order_no, COALESCE(platform, '')",
        sqlite_where='order_no IS NOT NULL AND deleted_at IS NULL',
    )
    drop_active_unique(op, table='shipmentorder',
                       index_name='ix_shipmentorder_shipment_no_active',
                       gen_col='shipment_no_active_key')
    emit_active_unique(
        op, table='shipmentorder',
        index_name='ix_shipmentorder_shipment_no_active',
        gen_col='shipment_no_active_key',
        mysql_expr="CASE WHEN shipment_no IS NOT NULL AND deleted_at IS NULL THEN shipment_no END",
        sqlite_columns='shipment_no',
        sqlite_where='shipment_no IS NOT NULL AND deleted_at IS NULL',
    )

    # 3) 删除 is_delete
    for tbl in _LEDGER_TABLES:
        op.drop_index(op.f(f'ix_{tbl}_is_delete'), table_name=tbl)
        op.drop_column(tbl, 'is_delete')
