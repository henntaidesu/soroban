"""baseline schema

方言感知：
- 字符串列一律用带长度的 sa.String(N) / 长文本用 sa.Text()（MySQL 的 VARCHAR 必须有长度；
  SQLite 不强制、VARCHAR(N) 与 VARCHAR 等价）。
- 三处「软删/空值感知」唯一约束（taobaoorder.order_no、shipmentorder.shipment_no、
  taobaostaging.order_no）由 app.db.dialect 翻译：SQLite→部分唯一索引，MySQL→生成列+唯一键。
- 建表带 mysql_engine=InnoDB / mysql_charset=utf8mb4（SQLite 忽略这些 kwarg）。

Revision ID: 53b7e33debd0
Revises:
Create Date: 2026-07-14 21:08:17.617350

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.db.dialect import drop_active_unique, emit_active_unique


# revision identifiers, used by Alembic.
revision: str = '53b7e33debd0'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 建表统一带上 MySQL 引擎/字符集（SQLite 忽略）。
_MYSQL = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'columnlayout',
        sa.Column('table_name', sa.String(length=32), nullable=False),
        sa.Column('columns_json', sa.Text(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('table_name'),
        **_MYSQL,
    )
    op.create_table(
        'fxrate',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('rate', sa.Numeric(precision=10, scale=4), nullable=False),
        sa.Column('fetched_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        **_MYSQL,
    )
    op.create_index(op.f('ix_fxrate_date'), 'fxrate', ['date'], unique=True)

    op.create_table(
        'pluginconfig',
        sa.Column('plugin_id', sa.String(length=64), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('params_json', sa.Text(), nullable=False),
        sa.Column('schedule_minutes', sa.Integer(), nullable=False),
        sa.Column('last_run_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('plugin_id'),
        **_MYSQL,
    )
    op.create_table(
        'setting',
        sa.Column('key', sa.String(length=128), nullable=False),
        sa.Column('value', sa.Text(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('key'),
        **_MYSQL,
    )
    op.create_table(
        'tagoption',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('field', sa.String(length=32), nullable=False),
        sa.Column('value', sa.String(length=128), nullable=False),
        sa.Column('color', sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        **_MYSQL,
    )
    op.create_index(op.f('ix_tagoption_field'), 'tagoption', ['field'], unique=False)
    op.create_index('ix_tagoption_field_value', 'tagoption', ['field', 'value'], unique=True)

    op.create_table(
        'user',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('username', sa.String(length=64), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('display_name', sa.String(length=128), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        **_MYSQL,
    )
    op.create_index(op.f('ix_user_username'), 'user', ['username'], unique=True)

    op.create_table(
        'miscexpense',
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('source', sa.String(length=32), nullable=False),
        sa.Column('payer_id', sa.Integer(), nullable=True),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('price_cny', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('fx_rate', sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column('jpy_override', sa.Integer(), nullable=True),
        sa.Column('override_note', sa.String(length=255), nullable=True),
        sa.Column('jpy_auto', sa.Integer(), nullable=True),
        sa.Column('jpy_settled', sa.Integer(), nullable=True),
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('category', sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(['payer_id'], ['user.id'], ),
        sa.PrimaryKeyConstraint('id'),
        **_MYSQL,
    )
    op.create_index(op.f('ix_miscexpense_date'), 'miscexpense', ['date'], unique=False)
    op.create_index(op.f('ix_miscexpense_deleted_at'), 'miscexpense', ['deleted_at'], unique=False)
    op.create_index(op.f('ix_miscexpense_source'), 'miscexpense', ['source'], unique=False)

    op.create_table(
        'shipmentorder',
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('source', sa.String(length=32), nullable=False),
        sa.Column('payer_id', sa.Integer(), nullable=True),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('price_cny', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('fx_rate', sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column('jpy_override', sa.Integer(), nullable=True),
        sa.Column('override_note', sa.String(length=255), nullable=True),
        sa.Column('jpy_auto', sa.Integer(), nullable=True),
        sa.Column('jpy_settled', sa.Integer(), nullable=True),
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('shipment_no', sa.String(length=64), nullable=True),
        sa.Column('weight', sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column('intl_tracking_no', sa.String(length=128), nullable=True),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('special_fee_jpy', sa.Integer(), nullable=True),
        sa.Column('recipient', sa.String(length=128), nullable=True),
        sa.ForeignKeyConstraint(['payer_id'], ['user.id'], ),
        sa.PrimaryKeyConstraint('id'),
        **_MYSQL,
    )
    op.create_index(op.f('ix_shipmentorder_date'), 'shipmentorder', ['date'], unique=False)
    op.create_index(op.f('ix_shipmentorder_deleted_at'), 'shipmentorder', ['deleted_at'], unique=False)
    op.create_index(op.f('ix_shipmentorder_source'), 'shipmentorder', ['source'], unique=False)
    op.create_index(op.f('ix_shipmentorder_status'), 'shipmentorder', ['status'], unique=False)
    # 软删/空值感知唯一：集运单号非空且未软删时唯一
    emit_active_unique(
        op,
        table='shipmentorder',
        index_name='ix_shipmentorder_shipment_no_active',
        gen_col='shipment_no_active_key',
        mysql_expr="CASE WHEN shipment_no IS NOT NULL AND deleted_at IS NULL THEN shipment_no END",
        sqlite_columns='shipment_no',
        sqlite_where='shipment_no IS NOT NULL AND deleted_at IS NULL',
    )

    op.create_table(
        'taobaoorder',
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('source', sa.String(length=32), nullable=False),
        sa.Column('payer_id', sa.Integer(), nullable=True),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('price_cny', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('fx_rate', sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column('jpy_override', sa.Integer(), nullable=True),
        sa.Column('override_note', sa.String(length=255), nullable=True),
        sa.Column('jpy_auto', sa.Integer(), nullable=True),
        sa.Column('jpy_settled', sa.Integer(), nullable=True),
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('order_no', sa.String(length=64), nullable=True),
        sa.Column('shop', sa.String(length=255), nullable=True),
        sa.Column('url', sa.Text(), nullable=True),
        sa.Column('category', sa.String(length=64), nullable=True),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('express_no', sa.String(length=64), nullable=True),
        sa.Column('express_company', sa.String(length=64), nullable=True),
        sa.Column('taobao_account', sa.String(length=64), nullable=True),
        sa.Column('shipment_order_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['payer_id'], ['user.id'], ),
        sa.ForeignKeyConstraint(['shipment_order_id'], ['shipmentorder.id'], ),
        sa.PrimaryKeyConstraint('id'),
        **_MYSQL,
    )
    op.create_index(op.f('ix_taobaoorder_date'), 'taobaoorder', ['date'], unique=False)
    op.create_index(op.f('ix_taobaoorder_deleted_at'), 'taobaoorder', ['deleted_at'], unique=False)
    op.create_index(op.f('ix_taobaoorder_express_no'), 'taobaoorder', ['express_no'], unique=False)
    op.create_index(op.f('ix_taobaoorder_shipment_order_id'), 'taobaoorder', ['shipment_order_id'], unique=False)
    op.create_index(op.f('ix_taobaoorder_source'), 'taobaoorder', ['source'], unique=False)
    op.create_index(op.f('ix_taobaoorder_status'), 'taobaoorder', ['status'], unique=False)
    op.create_index(op.f('ix_taobaoorder_taobao_account'), 'taobaoorder', ['taobao_account'], unique=False)
    # 软删/空值感知唯一：订单号非空且未软删时唯一（platform 列由下一版迁移加入后升级为复合键）
    emit_active_unique(
        op,
        table='taobaoorder',
        index_name='ix_taobaoorder_order_no_active',
        gen_col='order_no_active_key',
        mysql_expr="CASE WHEN order_no IS NOT NULL AND deleted_at IS NULL THEN order_no END",
        sqlite_columns='order_no',
        sqlite_where='order_no IS NOT NULL AND deleted_at IS NULL',
    )

    op.create_table(
        'orderitem',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('taobao_order_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['taobao_order_id'], ['taobaoorder.id'], ),
        sa.PrimaryKeyConstraint('id'),
        **_MYSQL,
    )
    op.create_index(op.f('ix_orderitem_taobao_order_id'), 'orderitem', ['taobao_order_id'], unique=False)

    op.create_table(
        'taobaostaging',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('order_no', sa.String(length=64), nullable=True),
        sa.Column('taobao_account', sa.String(length=64), nullable=True),
        sa.Column('shop', sa.String(length=255), nullable=True),
        sa.Column('price_cny', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('fx_rate', sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column('order_date', sa.Date(), nullable=True),
        sa.Column('express_no', sa.String(length=64), nullable=True),
        sa.Column('raw_json', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('order_status', sa.String(length=32), nullable=True),
        sa.Column('imported_taobao_order_id', sa.Integer(), nullable=True),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('scraped_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['imported_taobao_order_id'], ['taobaoorder.id'], ),
        sa.PrimaryKeyConstraint('id'),
        **_MYSQL,
    )
    op.create_index(op.f('ix_taobaostaging_status'), 'taobaostaging', ['status'], unique=False)
    # 软删无关，仅「订单号非空时唯一」（去重键，供 bot upsert）
    emit_active_unique(
        op,
        table='taobaostaging',
        index_name='ix_staging_order_no',
        gen_col='order_no_active_key',
        mysql_expr="CASE WHEN order_no IS NOT NULL THEN order_no END",
        sqlite_columns='order_no',
        sqlite_where='order_no IS NOT NULL',
    )

    op.create_table(
        'stagingitem',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('staging_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['staging_id'], ['taobaostaging.id'], ),
        sa.PrimaryKeyConstraint('id'),
        **_MYSQL,
    )
    op.create_index(op.f('ix_stagingitem_staging_id'), 'stagingitem', ['staging_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_stagingitem_staging_id'), table_name='stagingitem')
    op.drop_table('stagingitem')

    drop_active_unique(op, table='taobaostaging', index_name='ix_staging_order_no', gen_col='order_no_active_key')
    op.drop_index(op.f('ix_taobaostaging_status'), table_name='taobaostaging')
    op.drop_table('taobaostaging')

    op.drop_index(op.f('ix_orderitem_taobao_order_id'), table_name='orderitem')
    op.drop_table('orderitem')

    drop_active_unique(op, table='taobaoorder', index_name='ix_taobaoorder_order_no_active', gen_col='order_no_active_key')
    op.drop_index(op.f('ix_taobaoorder_taobao_account'), table_name='taobaoorder')
    op.drop_index(op.f('ix_taobaoorder_status'), table_name='taobaoorder')
    op.drop_index(op.f('ix_taobaoorder_source'), table_name='taobaoorder')
    op.drop_index(op.f('ix_taobaoorder_shipment_order_id'), table_name='taobaoorder')
    op.drop_index(op.f('ix_taobaoorder_express_no'), table_name='taobaoorder')
    op.drop_index(op.f('ix_taobaoorder_deleted_at'), table_name='taobaoorder')
    op.drop_index(op.f('ix_taobaoorder_date'), table_name='taobaoorder')
    op.drop_table('taobaoorder')

    drop_active_unique(op, table='shipmentorder', index_name='ix_shipmentorder_shipment_no_active', gen_col='shipment_no_active_key')
    op.drop_index(op.f('ix_shipmentorder_status'), table_name='shipmentorder')
    op.drop_index(op.f('ix_shipmentorder_source'), table_name='shipmentorder')
    op.drop_index(op.f('ix_shipmentorder_deleted_at'), table_name='shipmentorder')
    op.drop_index(op.f('ix_shipmentorder_date'), table_name='shipmentorder')
    op.drop_table('shipmentorder')

    op.drop_index(op.f('ix_miscexpense_source'), table_name='miscexpense')
    op.drop_index(op.f('ix_miscexpense_deleted_at'), table_name='miscexpense')
    op.drop_index(op.f('ix_miscexpense_date'), table_name='miscexpense')
    op.drop_table('miscexpense')

    op.drop_index(op.f('ix_user_username'), table_name='user')
    op.drop_table('user')

    op.drop_index('ix_tagoption_field_value', table_name='tagoption')
    op.drop_index(op.f('ix_tagoption_field'), table_name='tagoption')
    op.drop_table('tagoption')

    op.drop_table('setting')
    op.drop_table('pluginconfig')

    op.drop_index(op.f('ix_fxrate_date'), table_name='fxrate')
    op.drop_table('fxrate')
    op.drop_table('columnlayout')
