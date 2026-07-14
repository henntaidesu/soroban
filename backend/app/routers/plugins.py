"""爬虫插件（soroban 做管理层）。

soroban 扫 SCRAPER_DIR 下的 `soroban-scraper-*` 目录（各含 plugin.toml）作为插件，负责：
发现、存配置/定时、触发登录/抓取。插件本体是独立进程/venv，soroban 只按 manifest 调它的标准 CLI。
调用为子进程；抓取时把 soroban 短期 token 下发给插件回灌，插件无需存 soroban 密码。
"""

import asyncio
import datetime as dt
import json
import logging
import os
import shlex
import subprocess
import tomllib
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from ..auth import create_access_token, get_current_user
from ..config import settings
from ..database import engine, get_session
from ..models import PluginConfig, User, utcnow
from ..schemas import PluginConfigIn

log = logging.getLogger("soroban.plugins")

router = APIRouter(
    prefix="/api/plugins", tags=["plugins"], dependencies=[Depends(get_current_user)]
)

_SOROBAN_ROOT = Path(__file__).resolve().parents[3]     # …/soroban
_SELF_URL = "http://127.0.0.1:8000"                     # soroban 自身地址（插件在同机，回灌用）


def scraper_dir() -> Path:
    return Path(settings.SCRAPER_DIR) if settings.SCRAPER_DIR else (_SOROBAN_ROOT / "scraper")


def discover() -> list[dict]:
    """扫描插件目录，读各 plugin.toml。返回 manifest 列表（附 _dir）。坏的跳过。"""
    base, out = scraper_dir(), []
    if not base.is_dir():
        return out
    for d in sorted(base.glob("soroban-scraper-*")):
        f = d / "plugin.toml"
        if not (d.is_dir() and f.is_file()):
            continue
        try:
            m = tomllib.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if "id" not in m:
            continue
        m["_dir"] = d
        out.append(m)
    return out


def _find(plugin_id: str) -> dict:
    for m in discover():
        if m.get("id") == plugin_id:
            return m
    raise HTTPException(status_code=404, detail=f"未发现插件: {plugin_id}")


def _accounts(cfg: Optional[PluginConfig]) -> list[str]:
    if not cfg:
        return []
    try:
        raw = json.loads(cfg.params_json).get("accounts", "")
    except Exception:
        raw = ""
    return [a.strip() for a in str(raw).split(",") if a.strip()]


def _authorized(manifest: dict, account: str) -> bool:
    """该账号是否已授权：插件的 state 目录下有 <account>.json（登录会话）即算。"""
    state_dir = manifest.get("state_dir", ".state")
    return (manifest["_dir"] / state_dir / f"{account}.json").is_file()


def _python(manifest: dict) -> Path:
    return manifest["_dir"] / manifest.get("python", ".venv/bin/python")


def _launch(manifest: dict, command: str, extra: list[str], token: Optional[str] = None) -> int:
    """子进程调插件 CLI（fire-and-forget；插件输出进它自己的日志/回灌暂存）。

    token 走**环境变量** SOROBAN_TOKEN 下发，不进 argv——避免短期凭据出现在进程表(ps)/日志里。
    """
    python = _python(manifest)
    if not python.exists():
        raise HTTPException(status_code=400, detail=f"插件未安装：缺 venv（{python}）。见插件 README。")
    cmd = [str(python)] + shlex.split(manifest.get("entry", "")) + [command] + extra
    env = {**os.environ, "SOROBAN_TOKEN": token} if token else None
    try:
        proc = subprocess.Popen(
            cmd, cwd=str(manifest["_dir"]), env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
        )
    except (OSError, ValueError) as e:
        raise HTTPException(status_code=500, detail=f"启动插件失败：{e}")
    return proc.pid


@router.get("")
def list_plugins(session: Session = Depends(get_session)):
    out = []
    for m in discover():
        cfg = session.get(PluginConfig, m["id"])
        params = json.loads(cfg.params_json) if cfg else {}
        accts = _accounts(cfg)
        out.append({
            "id": m["id"], "name": m.get("name", m["id"]), "version": m.get("version"),
            "params": m.get("params", []),
            "installed": _python(m).exists(),
            "config": {
                "enabled": bool(cfg.enabled) if cfg else False,
                "params": params,
                "schedule_minutes": cfg.schedule_minutes if cfg else 0,
                "last_run_at": cfg.last_run_at if cfg else None,
            },
            "accounts": [{"account": a, "authorized": _authorized(m, a)} for a in accts],
        })
    return out


@router.put("/{plugin_id}/config")
def save_config(plugin_id: str, payload: PluginConfigIn, session: Session = Depends(get_session)):
    _find(plugin_id)                                    # 确认插件存在
    cfg = session.get(PluginConfig, plugin_id) or PluginConfig(plugin_id=plugin_id)
    cfg.enabled = payload.enabled
    cfg.params_json = json.dumps(payload.params, ensure_ascii=False)
    cfg.schedule_minutes = max(0, payload.schedule_minutes)
    cfg.updated_at = utcnow()
    session.add(cfg)
    session.commit()
    return {"ok": True}


@router.post("/{plugin_id}/login")
def login(plugin_id: str, account: str = Query(..., description="要授权登录的账号")):
    m = _find(plugin_id)
    return {"started": True, "pid": _launch(m, "login", ["--account", account])}


@router.post("/{plugin_id}/fetch")
def fetch(
    plugin_id: str,
    account: Optional[str] = Query(None, description="仅抓该账号；不填=配置里的全部账号"),
    current: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    m = _find(plugin_id)
    cfg = session.get(PluginConfig, plugin_id)
    accts = [account] if account else _accounts(cfg)
    if not accts:
        raise HTTPException(status_code=400, detail="没有账号可抓：先在插件配置里填账号。")
    token = create_access_token(current)                # 下发短期 token（走环境变量，不进 argv），插件免存密码
    pids = [_launch(m, "fetch", ["--account", a, "--soroban-url", _SELF_URL], token=token) for a in accts]
    return {"started": True, "accounts": accts, "pids": pids}


# --- 定时调度：按每个启用插件的 schedule_minutes 周期触发 fetch --------------

def _due(last: Optional[dt.datetime], minutes: int, now: dt.datetime) -> bool:
    if last is None:
        return True
    if last.tzinfo is None:                             # SQLite 取回可能是 naive，统一按 UTC 处理
        last = last.replace(tzinfo=dt.timezone.utc)
    return (now - last).total_seconds() >= minutes * 60


def _run_due(session: Session) -> None:
    user = session.exec(select(User).where(User.is_active == True)).first()  # noqa: E712
    if not user:
        return
    manifests = {m["id"]: m for m in discover()}
    now, token = utcnow(), None
    for cfg in session.exec(select(PluginConfig).where(PluginConfig.enabled == True)).all():  # noqa: E712
        if cfg.schedule_minutes <= 0 or not _due(cfg.last_run_at, cfg.schedule_minutes, now):
            continue
        m = manifests.get(cfg.plugin_id)
        if not m or not _python(m).exists():
            continue
        token = token or create_access_token(user)
        launched = 0
        for a in _accounts(cfg):
            try:
                _launch(m, "fetch", ["--account", a, "--soroban-url", _SELF_URL], token=token)
                launched += 1
            except HTTPException as e:
                log.warning("定时抓取 %s/%s 启动失败：%s", cfg.plugin_id, a, e.detail)
        if launched:                                    # 只有真的起了进程才推进 last_run_at
            cfg.last_run_at = now                       # 空账号/全部启动失败 → 不推进，下轮重试
            session.add(cfg)
    session.commit()


async def scheduler_loop(interval: int = 60) -> None:
    """后台循环：每 interval 秒检查一次到点的插件并触发抓取（放进 lifespan）。"""
    while True:
        try:
            with Session(engine) as session:
                _run_due(session)
        except Exception as e:                          # 单轮异常不结束循环
            log.warning("插件定时循环异常：%s", e)
        await asyncio.sleep(interval)
