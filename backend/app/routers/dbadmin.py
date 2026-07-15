"""数据库管理 / 迁移接口（/api/db）。

- GET  /api/db/status   当前后端 + MySQL 连接信息（不含密码）
- POST /api/db/test     测试一组 MySQL 连接参数
- POST /api/db/migrate  SQLite → MySQL：建库→建表→拷数据→热切换→清空 SQLite 业务数据

均需登录。迁移是一次性动作：完成后业务数据只在 MySQL，SQLite 仅保留 app_db_config。
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.engine import make_url

from ..auth import get_current_user
from ..database import (
    build_engine,
    control_engine,
    current_backend,
    run_migrations,
    set_data_engine,
)
from ..db import control
from ..services import db_migrate

log = logging.getLogger("soroban.db.admin")

router = APIRouter(prefix="/api/db", tags=["db"], dependencies=[Depends(get_current_user)])


class MySQLConfig(BaseModel):
    host: str
    port: int = 3306
    user: str
    password: str = ""
    database: str = "soroban"


@router.get("/status")
def status():
    cfg = control.read_config(control_engine())
    info = {"backend": current_backend()}
    if cfg["mysql_url"]:
        u = make_url(cfg["mysql_url"])
        info["mysql"] = {"host": u.host, "port": u.port, "user": u.username, "database": u.database}
    return info


@router.post("/test")
def test(c: MySQLConfig):
    ok, msg = db_migrate.test_connection(c.host, c.port, c.user, c.password, c.database or None)
    # database 可能尚未建 → 再退一步只测服务器连通
    if not ok:
        ok2, msg2 = db_migrate.test_connection(c.host, c.port, c.user, c.password, None)
        if ok2:
            return {"ok": True, "version": msg2, "note": f"服务器可连，但库 {c.database} 暂不存在（迁移时会自动创建）"}
        raise HTTPException(status_code=400, detail=f"连接失败：{msg2}")
    return {"ok": True, "version": msg}


@router.post("/migrate")
def migrate(c: MySQLConfig):
    """第一步：把本地 SQLite 数据拷入 MySQL（建库 → 建表 → 拷数据）。
    **不切换、不清空**——应用仍在用 SQLite，可反复验证。目标 MySQL 库须为空。"""
    if current_backend() == "mysql":
        raise HTTPException(status_code=400, detail="当前已在使用 MySQL，无需再次迁移")

    # 1) 连通性（服务器层）
    ok, msg = db_migrate.test_connection(c.host, c.port, c.user, c.password, None)
    if not ok:
        raise HTTPException(status_code=400, detail=f"MySQL 连接失败：{msg}")

    # 2) 建库（utf8mb4）
    try:
        db_migrate.ensure_database(c.host, c.port, c.user, c.password, c.database)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    url = db_migrate.build_mysql_url(c.host, c.port, c.user, c.password, c.database)

    # 3) 目标建 schema（Alembic，含方言生成列）
    try:
        run_migrations(url)
    except Exception as e:                                  # noqa: BLE001
        log.exception("MySQL 建表失败")
        raise HTTPException(status_code=500, detail=f"MySQL 建表失败：{e}")

    # 4) 目标须为空，避免重复导入撞唯一约束
    dst_engine = build_engine(url)
    try:
        if not db_migrate.is_target_empty(dst_engine):
            raise HTTPException(status_code=409, detail=f"目标库 {c.database} 已有业务数据，请换空库或先清空后重试")
        # 5) 拷数据（SQLite→MySQL）
        counts = db_migrate.copy_data(control_engine(), dst_engine)
    except HTTPException:
        raise
    except Exception as e:                                  # noqa: BLE001
        log.exception("数据拷贝失败")
        raise HTTPException(status_code=500, detail=f"数据拷贝失败：{e}")
    finally:
        dst_engine.dispose()

    return {"ok": True, "counts": counts, "total": sum(counts.values())}


@router.post("/switch")
def switch(c: MySQLConfig):
    """第二步：切换到 MySQL（写配置 + 热切换，无需重启），并清空本地 SQLite 业务数据。
    要求目标 MySQL 已迁移过（有数据），否则拒绝——防止切到空库并清掉 SQLite 导致丢数据。"""
    if current_backend() == "mysql":
        raise HTTPException(status_code=400, detail="当前已在使用 MySQL")

    ok, msg = db_migrate.test_connection(c.host, c.port, c.user, c.password, c.database)
    if not ok:
        raise HTTPException(status_code=400, detail=f"MySQL 连接失败：{msg}")

    url = db_migrate.build_mysql_url(c.host, c.port, c.user, c.password, c.database)
    dst_engine = build_engine(url)

    # 目标必须已建表且有数据（即已迁移过），否则切过去会丢数据
    try:
        empty = db_migrate.is_target_empty(dst_engine)
    except Exception:                                      # noqa: BLE001  表不存在等 → 视为未迁移
        dst_engine.dispose()
        raise HTTPException(status_code=400, detail="目标 MySQL 尚未迁移（无表/无数据），请先点「迁移数据库」")
    if empty:
        dst_engine.dispose()
        raise HTTPException(status_code=400, detail="目标 MySQL 无数据，请先点「迁移数据库」")

    # 写配置 + 热切换（此后 get_session 走 MySQL）
    control.write_config(control_engine(), "mysql", url)
    set_data_engine(dst_engine, url)

    # 清空 SQLite 业务数据（保留 app_db_config）
    try:
        db_migrate.clear_sqlite_business(control_engine())
    except Exception as e:                                  # noqa: BLE001
        log.warning("清空 SQLite 业务数据失败（不影响已切换到 MySQL）：%s", e)

    return {"ok": True, "backend": "mysql"}
