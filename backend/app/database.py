"""Database engine + session. SQLite in WAL mode (读写不互相阻塞)."""

from sqlite3 import Connection as SQLite3Connection

from sqlalchemy import event, text
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from .config import settings

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
    # 骨架阶段直接建表；正式迭代请改用 Alembic 迁移（见 README）。
    SQLModel.metadata.create_all(engine)
    _add_missing_columns()


# 骨架期没有 Alembic：create_all 不会给已存在的表加新列。此处只做「加列」这种
# 安全幂等的补迁移（新列可空/有默认），让旧库无需重建即可用上新字段。
_ADDED_COLUMNS = {
    "tagoption": {"color": "INTEGER"},
}


def _add_missing_columns() -> None:
    with engine.begin() as conn:
        for table, cols in _ADDED_COLUMNS.items():
            existing = {r[1] for r in conn.execute(text(f"PRAGMA table_info({table})"))}
            for name, sqltype in cols.items():
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {sqltype}"))


def get_session():
    with Session(engine) as session:
        yield session
