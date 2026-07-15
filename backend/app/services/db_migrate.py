"""SQLite → MySQL 迁移服务（供「数据库迁移」页调用）。

流程：测试连通 → 建库(utf8mb4) → 目标建 schema(Alembic) → 校验目标为空 → 逐表拷数据 →
（调用方）写配置 + 热切换 + 清空 SQLite 业务数据。

拷贝按外键依赖顺序，保留自增主键；只写模型声明的真实列——MySQL 的「活跃唯一」生成列不在
模型里，插入时由 MySQL 自算，绝不手写。
"""
from __future__ import annotations

import logging
import re
from urllib.parse import quote_plus

import pymysql
from sqlmodel import Session, delete, select

from ..database import build_engine
from ..models import (
    ColumnLayout,
    FxRate,
    MiscExpense,
    OrderItem,
    PluginConfig,
    Setting,
    ShipmentOrder,
    StagingItem,
    TagOption,
    TaobaoOrder,
    TaobaoStaging,
    User,
)

log = logging.getLogger("soroban.db.migrate")

# 按外键依赖排序：被引用的表在前（拷贝用正序，清空用逆序）。
MIGRATION_ORDER = [
    User, ShipmentOrder, TaobaoOrder, OrderItem, TaobaoStaging, StagingItem,
    MiscExpense, FxRate, Setting, ColumnLayout, TagOption, PluginConfig,
]

_DB_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")


def build_mysql_url(host: str, port: int, user: str, password: str, database: str) -> str:
    """密码/用户名做 URL 编码（含 @ : / 等特殊字符）；强制 utf8mb4。"""
    return (
        f"mysql+pymysql://{quote_plus(user)}:{quote_plus(password)}"
        f"@{host}:{int(port)}/{database}?charset=utf8mb4"
    )


def test_connection(host: str, port: int, user: str, password: str, database=None):
    """(ok, version_or_error)。database 传 None 时只连到服务器（不选库）。"""
    try:
        conn = pymysql.connect(
            host=host, port=int(port), user=user, password=password,
            database=database, connect_timeout=8,
        )
        with conn.cursor() as cur:
            cur.execute("SELECT VERSION()")
            ver = cur.fetchone()[0]
        conn.close()
        return True, ver
    except Exception as e:                                  # noqa: BLE001
        return False, str(e)


def ensure_database(host: str, port: int, user: str, password: str, database: str) -> None:
    """建库（utf8mb4），已存在则跳过。库名做白名单校验，防注入。"""
    if not _DB_NAME_RE.match(database):
        raise ValueError(f"非法数据库名：{database!r}（仅允许字母/数字/下划线）")
    conn = pymysql.connect(host=host, port=int(port), user=user, password=password, connect_timeout=8)
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"CREATE DATABASE IF NOT EXISTS `{database}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
    finally:
        conn.close()


def is_target_empty(engine) -> bool:
    """目标业务表是否全空（防止对已有数据的库重复导入）。"""
    with Session(engine) as s:
        for model in MIGRATION_ORDER:
            if s.exec(select(model)).first():
                return False
    return True


def copy_data(src_engine, dst_engine) -> dict:
    """逐表 SQLite→MySQL 拷贝，返回每表行数。"""
    counts: dict[str, int] = {}
    with Session(src_engine) as src, Session(dst_engine) as dst:
        for model in MIGRATION_ORDER:
            cols = list(model.__table__.columns.keys())
            rows = src.exec(select(model)).all()
            for r in rows:
                dst.add(model(**{c: getattr(r, c) for c in cols}))
            dst.commit()
            counts[model.__tablename__] = len(rows)
            log.info("迁移 %s：%d 行", model.__tablename__, len(rows))
    return counts


def clear_sqlite_business(sqlite_engine) -> None:
    """切到 MySQL 后清空 SQLite 里的业务数据（保留 app_db_config 等系统配置）。
    逆依赖顺序删除，避免外键冲突。"""
    with Session(sqlite_engine) as s:
        for model in reversed(MIGRATION_ORDER):
            s.exec(delete(model))
        s.commit()
