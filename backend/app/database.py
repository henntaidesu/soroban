"""Database engine + session. SQLite in WAL mode (读写不互相阻塞)。
建表/迁移走 Alembic（见 backend/alembic/、README「更新」章）。"""

import asyncio
import logging
import sys
from pathlib import Path
from sqlite3 import Connection as SQLite3Connection

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, create_engine

from .config import settings

log = logging.getLogger("soroban.db")
# backend/（alembic.ini 所在）；PyInstaller 打包后 alembic.ini/alembic/ 打入 _MEIPASS 根。
_ROOT = (
    Path(sys._MEIPASS)                              # type: ignore[attr-defined]
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parents[1]
)

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


def _wal_truncate() -> None:
    """把 WAL 里的改动合并回主库并**截断** -wal 文件（回收其占用的磁盘空间）。
    运行期截断只清空 -wal（文件仍在，因库还开着）；进程退出、连接全关后 SQLite 才删除 -wal/-shm。"""
    if not settings.DATABASE_URL.startswith("sqlite"):
        return
    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")


async def wal_checkpoint_loop(interval: int = 600) -> None:
    """后台循环：每 interval 秒（默认 10 分钟）截断一次 WAL，控制 -wal 体积、及时回收空间。
    放进 lifespan；单轮异常不结束循环。"""
    while True:
        await asyncio.sleep(interval)
        try:
            _wal_truncate()
        except Exception as e:                          # 单轮失败不结束循环
            log.warning("周期性 WAL checkpoint 失败：%s", e)


def checkpoint_and_dispose() -> None:
    """进程干净退出前调用：截断 WAL，再关闭连接池。
    连接全部关闭后 SQLite 会自动删除 soroban.db-wal / soroban.db-shm。
    （若进程被强杀，收尾不执行，这两个文件会残留——WAL 模式的固有行为，下次启动自动接管，不丢数据。）"""
    try:
        _wal_truncate()
    except Exception as e:                              # 检查点失败不阻断关闭
        log.warning("关库前 WAL checkpoint 失败：%s", e)
    finally:
        engine.dispose()                               # 关掉池内所有连接，触发 -wal/-shm 回收
