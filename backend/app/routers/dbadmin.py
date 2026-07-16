"""数据库管理 / 迁移接口（/api/db）——SQLite ↔ MySQL 双向 + 记录连接过的库。

- GET    /api/db/status              当前后端 + 已保存的连接列表（均不含密码）
- POST   /api/db/test                测试一个目标（MySQL 参数 / 已存连接 / 本地）；成功即记住
- POST   /api/db/migrate             把当前数据整表覆盖到目标（建库/建表/拷数据，不切换）
- POST   /api/db/switch              热切换到目标（无需重启；不清源库，故可逆）
- DELETE /api/db/connections/{id}    删除一条已保存连接（不能删当前正在用的）

目标(Target)三选一：{connection_id} 一键复用已存连接 / {backend:'mysql', host...} 新连接 /
{backend:'sqlite'} 本地库。安全：DSN 全程 Fernet 加密存储，密码永不回传前端；库名白名单防注入；
全部端点需登录。
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.engine import make_url

from ..auth import get_current_user
from ..database import (
    build_engine,
    control_engine,
    control_url,
    current_backend,
    get_engine,
    run_migrations,
    set_data_engine,
)
from ..db import control
from ..services import db_migrate

log = logging.getLogger("soroban.db.admin")

router = APIRouter(prefix="/api/db", tags=["db"], dependencies=[Depends(get_current_user)])


class Target(BaseModel):
    """迁移/切换的目标库。三种指定方式见模块文档。"""
    connection_id: Optional[int] = None      # 复用已保存连接（一键切换）
    backend: Optional[str] = None            # 'sqlite' | 'mysql'
    host: Optional[str] = None
    port: int = 3306
    user: Optional[str] = None
    password: str = ""
    database: Optional[str] = None


# --- 解析目标 ------------------------------------------------------------------

def _mysql_conn_fields(t: Target):
    """→ (host, port, user, password, database)。connection_id 时从已存 DSN 解出。"""
    if t.connection_id is not None:
        url = control.get_connection_url(control_engine(), t.connection_id)
        if not url:
            raise HTTPException(status_code=404, detail="连接不存在或无法解密（SECRET_KEY 可能已变更）")
        u = make_url(url)
        return u.host, int(u.port or 3306), u.username, u.password or "", u.database
    if not (t.host and t.user and t.database):
        raise HTTPException(status_code=400, detail="MySQL 参数不完整（需 host / user / database）")
    return t.host, int(t.port or 3306), t.user, t.password or "", t.database


def _resolve_target(t: Target):
    """→ (backend, url, engine, owns)。owns=True 表示 engine 是新建的、用完需 dispose。"""
    if t.connection_id is None and t.backend == "sqlite":
        return "sqlite", control_url(), control_engine(), False
    host, port, user, pw, db = _mysql_conn_fields(t)
    url = db_migrate.build_mysql_url(host, port, user, pw, db)
    return "mysql", url, build_engine(url), True


def _active_identity() -> dict:
    """当前生效后端 + （MySQL 时）连接标识，供前端展示/比对。不含密码。"""
    backend = current_backend()
    d = {"backend": backend}
    if backend == "mysql":
        cfg = control.read_config(control_engine())
        if cfg["mysql_url"]:
            u = make_url(cfg["mysql_url"])
            d.update(host=u.host, port=u.port, user=u.username, database=u.database)
    return d


def _is_same_as_active(backend: str, url: str) -> bool:
    """目标是否就是当前正在使用的库（防止把线上库当迁移目标清空 / 重复切换）。"""
    active = current_backend()
    if backend == "sqlite":
        return active == "sqlite"
    if active != "mysql":
        return False
    cfg = control.read_config(control_engine())
    if not cfg["mysql_url"]:
        return False
    a, b = make_url(cfg["mysql_url"]), make_url(url)
    return (a.host, a.port, a.username, a.database) == (b.host, b.port, b.username, b.database)


def _remember(host, port, user, pw, db) -> int:
    """把 MySQL 连接记入「连接过的库」（加密 DSN）。返回连接 id。"""
    url = db_migrate.build_mysql_url(host, port, user, pw, db)
    return control.upsert_connection(
        control_engine(), backend="mysql", url=url,
        host=host, port=port, user=user, database=db,
    )


# --- 端点 ----------------------------------------------------------------------

@router.get("/status")
def status():
    return {"active": _active_identity(), "connections": control.list_connections(control_engine())}


@router.post("/test")
def test(t: Target):
    if t.connection_id is None and t.backend == "sqlite":
        return {"ok": True, "kind": "sqlite"}      # 本地库永远可用
    host, port, user, pw, db = _mysql_conn_fields(t)
    ok, msg = db_migrate.test_connection(host, port, user, pw, db)
    if ok:
        cid = _remember(host, port, user, pw, db)
        return {"ok": True, "version": msg, "connection_id": cid}
    # 库尚不存在 → 退一步只测服务器连通（迁移时会自动建库）
    ok2, msg2 = db_migrate.test_connection(host, port, user, pw, None)
    if ok2:
        cid = _remember(host, port, user, pw, db)
        return {"ok": True, "version": msg2, "connection_id": cid,
                "note": f"服务器可连，但库 {db} 暂不存在（迁移时会自动创建）"}
    raise HTTPException(status_code=400, detail=f"连接失败：{msg2}")


@router.post("/migrate")
def migrate(t: Target):
    """把**当前数据库**的数据整表覆盖到目标（建库→建表→拷数据）。不切换、不动当前库。"""
    backend, url, tgt, owns = _resolve_target(t)
    if _is_same_as_active(backend, url):
        raise HTTPException(status_code=400, detail="目标就是当前正在使用的数据库，无需迁移")
    try:
        if backend == "mysql":
            host, port, user, pw, db = _mysql_conn_fields(t)
            ok, msg = db_migrate.test_connection(host, port, user, pw, None)
            if not ok:
                raise HTTPException(status_code=400, detail=f"MySQL 连接失败：{msg}")
            try:
                db_migrate.ensure_database(host, port, user, pw, db)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            _remember(host, port, user, pw, db)
        # 目标建/更新 schema（Alembic，含方言生成列）；本地 SQLite 目标同样确保升到 head
        try:
            run_migrations(url)
        except Exception as e:                                  # noqa: BLE001
            log.exception("目标建表失败")
            raise HTTPException(status_code=500, detail=f"目标建表失败：{e}")
        # 整表覆盖拷贝：当前数据引擎 → 目标
        try:
            counts = db_migrate.copy_data(get_engine(), tgt)
        except HTTPException:
            raise
        except Exception as e:                                  # noqa: BLE001
            log.exception("数据拷贝失败")
            raise HTTPException(status_code=500, detail=f"数据拷贝失败：{e}")
    finally:
        if owns:
            tgt.dispose()
    return {"ok": True, "counts": counts, "total": sum(counts.values())}


@router.post("/switch")
def switch(t: Target):
    """热切换到目标（无需重启）。要求目标已迁移过（有数据），否则拒绝以防丢数据。不清空源库。"""
    backend, url, tgt, owns = _resolve_target(t)
    if _is_same_as_active(backend, url):
        raise HTTPException(status_code=400, detail="当前已在使用该数据库")

    # 目标必须已建表且有数据（= 迁移过），否则拒绝
    try:
        empty = db_migrate.is_target_empty(tgt)
    except Exception:                                          # noqa: BLE001  表不存在等
        if owns:
            tgt.dispose()
        raise HTTPException(status_code=400, detail="目标数据库尚未建表/迁移，请先点「迁移到此库」")
    if empty:
        if owns:
            tgt.dispose()
        raise HTTPException(status_code=400, detail="目标数据库无数据，请先点「迁移到此库」")

    if backend == "mysql":
        host, port, user, pw, db = _mysql_conn_fields(t)
        control.write_config(control_engine(), "mysql", url)
        set_data_engine(tgt, url)                              # tgt 成为线上引擎，不再 dispose
        cid = _remember(host, port, user, pw, db)
        control.touch_connection(control_engine(), cid)
    else:
        # 切回本地 SQLite：数据引擎复位为控制引擎（set_data_engine 会释放旧 MySQL 引擎）
        control.write_config(control_engine(), "sqlite", None)
        set_data_engine(control_engine(), control_url())
    return {"ok": True, "backend": backend}


@router.delete("/connections/{cid}")
def remove_connection(cid: int):
    url = control.get_connection_url(control_engine(), cid)
    if url and _is_same_as_active("mysql", url):
        raise HTTPException(status_code=400, detail="不能删除当前正在使用的连接，请先切换到其它数据库")
    control.delete_connection(control_engine(), cid)
    return {"ok": True}
