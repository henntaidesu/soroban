"""Database engine + session. SQLite in WAL mode (读写不互相阻塞)。
建表/迁移走 Alembic（见 backend/alembic/、README「更新」章）。"""

import logging
from pathlib import Path
from sqlite3 import Connection as SQLite3Connection

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, create_engine

from .config import settings

log = logging.getLogger("soroban.db")
_ROOT = Path(__file__).resolve().parents[1]   # backend/（alembic.ini 所在）

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
    """用 Alembic 迁移到最新（`upgrade head`，幂等，启动/seed/demo 都调它）。
    - 全新库：跑 baseline + 后续迁移，建全 schema。
    - pre-Alembic 旧库（有表但无 alembic_version）：自动 stamp 到 baseline 再升级，无缝接管、不重复建表。
    - 已纳管的库：只应用 baseline 之后的新迁移（git pull 后自动跟上）。
    改了 models 后，生成新迁移：`cd backend && alembic revision --autogenerate -m "..."` 并提交（见 README）。"""
    from alembic import command
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from sqlalchemy import inspect as sa_inspect

    cfg = Config(str(_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

    with engine.connect() as conn:
        tables = set(sa_inspect(conn).get_table_names())
    if tables and "alembic_version" not in tables:      # pre-Alembic 旧库：现有 schema 即 baseline
        base_rev = ScriptDirectory.from_config(cfg).get_base()
        command.stamp(cfg, base_rev)
        log.info("检测到 pre-Alembic 旧库 → 已 stamp 到 baseline %s", base_rev)
    command.upgrade(cfg, "head")


def get_session():
    with Session(engine) as session:
        yield session
