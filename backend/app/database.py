"""Database engine + session. SQLite in WAL mode (读写不互相阻塞)."""

import logging
from sqlite3 import Connection as SQLite3Connection

from sqlalchemy import event, text
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from .config import settings

log = logging.getLogger("soroban.db")

# check_same_thread=False: FastAPI 在多个线程里用同一连接池
engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False},
)


@event.listens_for(Engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    """每条新连接都开 WAL + 外键约束。"""
    if isinstance(dbapi_connection, SQLite3Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def create_db_and_tables() -> None:
    """建表 + 加列式补迁移。没有 Alembic：新增的**表**由 create_all 自动建；已存在表上
    新增的**可空列**由 _add_missing_columns 自动 ALTER 补上。改列类型/约束/索引/删列等
    结构性变更**不在自动范围**——需先 ./backup.sh 再手动迁移（见 README「更新」章）。"""
    from . import models  # noqa: F401  确保所有模型都注册到 metadata，否则 create_all 建不全
    SQLModel.metadata.create_all(engine)
    _add_missing_columns()


def _add_missing_columns() -> None:
    """对比 model 定义与实际表结构，自动补齐缺失的『可空』列（安全幂等的加列式迁移）。
    非空且无 server_default 的新列不能安全 ALTER 到已有行 → 只告警、不自动加（需手动）。"""
    dialect = engine.dialect
    with engine.begin() as conn:
        for table in SQLModel.metadata.sorted_tables:
            existing = {r[1] for r in conn.execute(text(f"PRAGMA table_info({table.name})"))}
            if not existing:
                continue                                  # 表还不存在（create_all 已建，这里防御）
            for col in table.columns:
                if col.name in existing:
                    continue
                if not col.nullable and col.server_default is None:
                    log.warning("表 %s 缺非空列 %s（无默认）→ 需手动迁移，跳过自动加列", table.name, col.name)
                    continue
                coltype = col.type.compile(dialect=dialect)
                try:
                    conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {coltype}'))
                    log.info("自动加列 %s.%s (%s)", table.name, col.name, coltype)
                except Exception as e:                    # 单列失败不阻断启动
                    log.warning("自动加列 %s.%s 失败：%s", table.name, col.name, e)


def get_session():
    with Session(engine) as session:
        yield session
