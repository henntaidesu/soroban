"""控制存储：始终在 SQLite（soroban.db）里保存「当前用哪个数据库后端」+ MySQL 连接串。

- 无论业务数据在 SQLite 还是 MySQL，这张 `app_db_config` 表**永远留在 SQLite**——这也是
  「SQLite 不删除、只保留基本系统配置」的落点。
- MySQL 连接串（含密码）用 SECRET_KEY 派生的 Fernet 密钥**加密**后入库；就算 soroban.db
  被拷走，也拿不到明文密码。SECRET_KEY 变更 → 解密失败 → 视为无配置、回退 SQLite。
- 这张表**不属于** SQLModel.metadata（用独立 MetaData + Core），故 Alembic 永远不会把它建到
  MySQL 去，也不会纳入业务迁移链。
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import logging
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    insert,
    select,
    update,
)
from sqlalchemy.engine import Engine

from ..config import settings

log = logging.getLogger("soroban.db.control")

control_metadata = MetaData()

app_db_config = Table(
    "app_db_config",
    control_metadata,
    Column("id", Integer, primary_key=True),           # 恒为 1（单行配置）
    Column("backend", String(16), nullable=False),     # 'sqlite' | 'mysql'
    Column("mysql_url_enc", Text, nullable=True),      # Fernet 加密后的完整 DSN
    Column("updated_at", DateTime, nullable=False),
)


def _fernet() -> Fernet:
    # 由 SECRET_KEY 派生 32 字节 → urlsafe base64 → Fernet 密钥
    key = base64.urlsafe_b64encode(hashlib.sha256(settings.SECRET_KEY.encode()).digest())
    return Fernet(key)


def encrypt(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def decrypt(token: str) -> Optional[str]:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        log.error("MySQL 连接串解密失败（SECRET_KEY 可能已变更）→ 视为无 MySQL 配置")
        return None


def ensure_schema(engine: Engine) -> None:
    """在控制 SQLite 上建 app_db_config 表（幂等）。"""
    control_metadata.create_all(engine)


def read_config(engine: Engine) -> dict:
    """返回 {'backend': 'sqlite'|'mysql', 'mysql_url': str|None}。无配置时默认 sqlite。"""
    with engine.connect() as conn:
        row = conn.execute(select(app_db_config).where(app_db_config.c.id == 1)).first()
    if row is None:
        return {"backend": "sqlite", "mysql_url": None}
    url = decrypt(row.mysql_url_enc) if row.mysql_url_enc else None
    backend = row.backend if not (row.backend == "mysql" and url is None) else "sqlite"
    return {"backend": backend, "mysql_url": url}


def write_config(engine: Engine, backend: str, mysql_url: Optional[str] = None) -> None:
    enc = encrypt(mysql_url) if mysql_url else None
    now = dt.datetime.now(dt.timezone.utc)
    with engine.begin() as conn:
        exists = conn.execute(select(app_db_config.c.id).where(app_db_config.c.id == 1)).first()
        if exists:
            conn.execute(
                update(app_db_config).where(app_db_config.c.id == 1)
                .values(backend=backend, mysql_url_enc=enc, updated_at=now)
            )
        else:
            conn.execute(
                insert(app_db_config)
                .values(id=1, backend=backend, mysql_url_enc=enc, updated_at=now)
            )
