"""rename 淘宝→商品：表 taobaoorder→orders / taobaostaging→orderstaging，
列 taobao_account→platform_account、taobao_order_id→order_id、imported_taobao_order_id→imported_order_id，
并迁移 columnlayout/tagoption 里存的键值数据。

设计（见 app/db/dialect.py）：
- 表/列改名两方言同语法：`ALTER TABLE ... RENAME TO/COLUMN`（MySQL 8+ / SQLite 3.25+ 均原生支持，
  且都会自动更新引用它的外键；SQLite 3.51 会同步更新其它表 FK 定义里的表名/列名）。
- 「活跃行唯一」约束在 MySQL 是「生成列 + 唯一键」、SQLite 是「部分唯一索引」——改名前先 drop、
  改名后按新表名/新索引名 re-emit（复用 drop_active_unique/emit_active_unique），生成列表达式
  只引用 order_no/platform/is_delete（未改），故重建即正确。
- 其余普通索引：MySQL 用 `RENAME INDEX`，SQLite 用 `DROP + CREATE`（不支持索引改名）。
- columnlayout(主键 table_name='taobao') 与 tagoption(field='taobao_account') 是**数据**，用 UPDATE 迁移。

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-07-16 20:10:00.000000
"""
from typing import Sequence, Union

from alembic import op

from app.db.dialect import drop_active_unique, emit_active_unique, is_mysql, is_sqlite


# revision identifiers, used by Alembic.
revision: str = 'b8c9d0e1f2a3'
down_revision: Union[str, Sequence[str], None] = 'a7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 活跃唯一约束的 MySQL 生成列表达式（与 d4e5f6a7b8c9 / baseline 一致，列名未变，直接沿用）。
_ORDERS_MYSQL = (
    "CASE WHEN order_no IS NOT NULL AND is_delete = 0 "
    "THEN CONCAT(order_no, CHAR(31 USING utf8mb4), COALESCE(platform, '')) END"
)
_STAGING_MYSQL = "CASE WHEN order_no IS NOT NULL THEN order_no END"

# orders 表所有普通索引：(旧名, 新名, 列)。活跃唯一索引单独由 emit/drop 处理，不在此列。
_ORDERS_IX = [
    ("ix_taobaoorder_date", "ix_orders_date", '"date"'),
    ("ix_taobaoorder_is_delete", "ix_orders_is_delete", '"is_delete"'),
    ("ix_taobaoorder_express_no", "ix_orders_express_no", '"express_no"'),
    ("ix_taobaoorder_shipment_order_id", "ix_orders_shipment_order_id", '"shipment_order_id"'),
    ("ix_taobaoorder_source", "ix_orders_source", '"source"'),
    ("ix_taobaoorder_status", "ix_orders_status", '"status"'),
    ("ix_taobaoorder_platform", "ix_orders_platform", '"platform"'),
    ("ix_taobaoorder_taobao_account", "ix_orders_platform_account", '"platform_account"'),
]


def _rename_col(table: str, old: str, new: str) -> None:
    # 反引号在 MySQL 与 SQLite 都被接受为标识符引号；RENAME COLUMN 两方言同语法。
    op.execute(f"ALTER TABLE `{table}` RENAME COLUMN `{old}` TO `{new}`")


def _rename_index(table: str, old: str, new: str, cols: str) -> None:
    """普通（非唯一）索引改名。cols 仅 SQLite 重建时用（已带引号的列列表）。"""
    if is_mysql(op.get_bind()):
        op.execute(f"ALTER TABLE `{table}` RENAME INDEX `{old}` TO `{new}`")
    else:
        op.execute(f'DROP INDEX IF EXISTS "{old}"')
        op.execute(f'CREATE INDEX "{new}" ON "{table}" ({cols})')


def upgrade() -> None:
    """Upgrade schema."""
    # 1) 先撤活跃唯一（含 MySQL 生成列/唯一键、SQLite 部分索引）
    drop_active_unique(op, table='taobaoorder',
                       index_name='ix_taobaoorder_order_no_platform_active',
                       gen_col='order_no_platform_active_key')
    drop_active_unique(op, table='taobaostaging',
                       index_name='ix_staging_order_no',
                       gen_col='order_no_active_key')

    # 2) 改列名（外键随列自动更新）
    _rename_col('orderitem', 'taobao_order_id', 'order_id')
    _rename_col('taobaostaging', 'taobao_account', 'platform_account')
    _rename_col('taobaostaging', 'imported_taobao_order_id', 'imported_order_id')
    _rename_col('taobaoorder', 'taobao_account', 'platform_account')

    # 3) 改表名（引用它的外键自动更新为新表名）
    # ⚠️ SQLite：Alembic 迁移期默认 legacy_alter_table=ON，此时 RENAME TABLE **不会**重指
    # 其它表里指向它的外键（orderitem/orderstaging/stagingitem 会悬空指向已消失的
    # taobaoorder/taobaostaging，开着 foreign_keys 时写入即崩）。显式关掉，让 3.25+ 自动重指。
    # （app 运行期连接恒 foreign_keys=ON 可歪打正着重指，但裸 `alembic upgrade` 会 OFF→踩雷，故显式修。）
    if is_sqlite(op.get_bind()):
        op.execute("PRAGMA legacy_alter_table=OFF")
    op.rename_table('taobaoorder', 'orders')
    op.rename_table('taobaostaging', 'orderstaging')

    # 4) 普通索引按新表名/新列名改名
    for old, new, cols in _ORDERS_IX:
        _rename_index('orders', old, new, cols)
    _rename_index('orderstaging', 'ix_taobaostaging_status', 'ix_orderstaging_status', '"status"')
    _rename_index('orderitem', 'ix_orderitem_taobao_order_id', 'ix_orderitem_order_id', '"order_id"')

    # 5) 按新表名/新索引名重建活跃唯一
    emit_active_unique(
        op, table='orders',
        index_name='ix_orders_order_no_platform_active',
        gen_col='order_no_platform_active_key',
        mysql_expr=_ORDERS_MYSQL,
        sqlite_columns="order_no, COALESCE(platform, '')",
        sqlite_where='order_no IS NOT NULL AND is_delete = 0',
    )
    emit_active_unique(
        op, table='orderstaging',
        index_name='ix_staging_order_no',
        gen_col='order_no_active_key',
        mysql_expr=_STAGING_MYSQL,
        sqlite_columns='order_no',
        sqlite_where='order_no IS NOT NULL',
    )

    # 6) 迁移应用数据里存的键：列布局键、标签字段名
    op.execute("UPDATE columnlayout SET table_name = 'orders' WHERE table_name = 'taobao'")
    op.execute("UPDATE tagoption SET field = 'platform_account' WHERE field = 'taobao_account'")


def downgrade() -> None:
    """Downgrade schema（严格逆序逐步还原，可与 upgrade 往返）。"""
    op.execute("UPDATE tagoption SET field = 'taobao_account' WHERE field = 'platform_account'")
    op.execute("UPDATE columnlayout SET table_name = 'taobao' WHERE table_name = 'orders'")

    # 撤新表上的活跃唯一
    drop_active_unique(op, table='orders',
                       index_name='ix_orders_order_no_platform_active',
                       gen_col='order_no_platform_active_key')
    drop_active_unique(op, table='orderstaging',
                       index_name='ix_staging_order_no',
                       gen_col='order_no_active_key')

    # 普通索引改回旧名（此时表仍叫 orders/orderstaging、列仍是新名）
    for old, new, cols in _ORDERS_IX:
        _rename_index('orders', new, old, cols)
    _rename_index('orderstaging', 'ix_orderstaging_status', 'ix_taobaostaging_status', '"status"')
    _rename_index('orderitem', 'ix_orderitem_order_id', 'ix_orderitem_taobao_order_id', '"order_id"')

    # 表名改回（同 upgrade：SQLite 需关 legacy_alter_table 才会重指子表外键）
    if is_sqlite(op.get_bind()):
        op.execute("PRAGMA legacy_alter_table=OFF")
    op.rename_table('orders', 'taobaoorder')
    op.rename_table('orderstaging', 'taobaostaging')

    # 列名改回
    _rename_col('taobaoorder', 'platform_account', 'taobao_account')
    _rename_col('taobaostaging', 'platform_account', 'taobao_account')
    _rename_col('taobaostaging', 'imported_order_id', 'imported_taobao_order_id')
    _rename_col('orderitem', 'order_id', 'taobao_order_id')

    # 重建旧名活跃唯一
    emit_active_unique(
        op, table='taobaoorder',
        index_name='ix_taobaoorder_order_no_platform_active',
        gen_col='order_no_platform_active_key',
        mysql_expr=_ORDERS_MYSQL,
        sqlite_columns="order_no, COALESCE(platform, '')",
        sqlite_where='order_no IS NOT NULL AND is_delete = 0',
    )
    emit_active_unique(
        op, table='taobaostaging',
        index_name='ix_staging_order_no',
        gen_col='order_no_active_key',
        mysql_expr=_STAGING_MYSQL,
        sqlite_columns='order_no',
        sqlite_where='order_no IS NOT NULL',
    )
