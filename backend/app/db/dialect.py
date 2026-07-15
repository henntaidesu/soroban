"""方言翻译层：把 SQLite / MySQL 之间的「语法差异」集中翻译，业务模型与迁移只声明意图。

目前翻译的差异：
1. **软删/空值感知的唯一约束**——本项目多处需要「仅对未软删且关键列非空的行唯一」：
   - SQLite：直接用带 WHERE 的**部分唯一索引**（partial unique index）。
   - MySQL：不支持部分索引 → 改用 **STORED 生成列**（删除行/空值时算出 NULL，而 NULL 在
     唯一索引里互不冲突），再对生成列建唯一键。语义与 SQLite 部分索引完全等价。

   两条路径都由本模块产出（见 emit_active_unique / drop_active_unique），迁移脚本只描述
   「哪几列、什么条件下唯一」，不关心具体方言。

2. **方言探测**——is_sqlite / is_mysql 供 database.py、env.py、迁移按方言短路。
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.engine import Connection, Dialect, Engine


def _name(bind=None) -> str:
    """取当前方言名。bind 可传 Connection/Engine/Dialect；不传则用 Alembic 的 op.get_bind()。"""
    if bind is None:
        from alembic import op  # 延迟导入：非迁移场景（database.py）不依赖 alembic 上下文
        bind = op.get_bind()
    if isinstance(bind, Dialect):
        return bind.name
    if isinstance(bind, (Connection, Engine)):
        return bind.dialect.name
    return getattr(getattr(bind, "dialect", None), "name", str(bind))


def is_sqlite(bind=None) -> bool:
    return _name(bind) == "sqlite"


def is_mysql(bind=None) -> bool:
    return _name(bind) in ("mysql", "mariadb")


# --- 软删/空值感知唯一约束的方言翻译（迁移里调用）---------------------------------

def emit_active_unique(
    op,
    *,
    table: str,
    index_name: str,
    gen_col: str,
    mysql_expr: str,
    sqlite_columns: str,
    sqlite_where: str,
) -> None:
    """建「活跃行唯一」约束。

    - table         表名
    - index_name    唯一索引名（两方言一致，便于 drop）
    - gen_col       MySQL 侧生成列列名（SQLite 不建列）
    - mysql_expr    MySQL 生成列表达式；活跃行算出唯一键、其余算出 NULL
                    （NULL 不参与唯一 → 等价于「仅活跃行唯一」）
    - sqlite_columns 部分索引的列/表达式列表，如 "order_no, COALESCE(platform, '')"
    - sqlite_where  部分索引 WHERE 条件，如 "order_no IS NOT NULL AND is_delete = 0"
    """
    if is_mysql(op.get_bind()):
        op.execute(
            f"ALTER TABLE `{table}` ADD COLUMN `{gen_col}` VARCHAR(512) "
            f"GENERATED ALWAYS AS ({mysql_expr}) STORED"
        )
        op.execute(f"CREATE UNIQUE INDEX `{index_name}` ON `{table}` (`{gen_col}`)")
    else:
        op.execute(
            f'CREATE UNIQUE INDEX "{index_name}" ON "{table}" ({sqlite_columns}) '
            f"WHERE {sqlite_where}"
        )


def drop_active_unique(op, *, table: str, index_name: str, gen_col: str) -> None:
    """撤销 emit_active_unique 建的约束（含 MySQL 侧的生成列）。"""
    if is_mysql(op.get_bind()):
        op.execute(f"DROP INDEX `{index_name}` ON `{table}`")
        op.execute(f"ALTER TABLE `{table}` DROP COLUMN `{gen_col}`")
    else:
        op.execute(f'DROP INDEX IF EXISTS "{index_name}"')
