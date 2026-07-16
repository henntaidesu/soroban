"""soroban FastAPI app entrypoint."""

import asyncio
import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from . import models  # noqa: F401  确保建表前所有模型已注册
from .config import settings
from .database import checkpoint_and_dispose, create_db_and_tables, wal_checkpoint_loop
from .routers import auth, dashboard, dbadmin, fx, items, shipment, layout, misc, plugins, staging, tags, taobao
from .routers.plugins import scheduler_loop
from .services.fx import fx_loop

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("soroban")

_INSECURE_KEYS = {"", "dev-insecure-key-change-me", "change-me-to-a-long-random-string"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.SECRET_KEY in _INSECURE_KEYS or len(settings.SECRET_KEY) < 16:
        log.warning(
            "⚠️ SECRET_KEY 是不安全的默认值或过短，仅可用于本地开发。"
            "上公网前务必在 .env 设置强随机 SECRET_KEY，否则登录 token 可被伪造！"
        )
    create_db_and_tables()          # Alembic upgrade head（幂等；旧库自动接管，见 database.py）
    tasks = [
        asyncio.create_task(fx_loop()),
        asyncio.create_task(scheduler_loop()),
        # 控制引擎恒为 SQLite（存 app_db_config），故 WAL 截断循环始终运行
        asyncio.create_task(wal_checkpoint_loop(600)),   # 每 10 分钟截断一次 WAL
    ]
    try:
        yield
    finally:
        for t in tasks:
            t.cancel()
        checkpoint_and_dispose()        # 合并并截断 WAL、关连接池 → 回收 -wal/-shm


app = FastAPI(title="soroban", version="0.1.0", lifespan=lifespan)

# 令牌走 Authorization 头、不使用 cookie，故 allow_credentials=False（更安全）
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

for r in (
    auth.router, taobao.router, shipment.router, misc.router, items.router,
    staging.router, dashboard.router, fx.router, layout.router, tags.router, plugins.router,
    dbadmin.router,
):
    app.include_router(r)


@app.exception_handler(IntegrityError)
async def _integrity_handler(request: Request, exc: IntegrityError):
    # 数据库完整性冲突（唯一约束/外键/必填等）→ 干净的 409，而非 500。
    # 真实约束记进日志（前端只给通用提示，不臆断具体原因，避免误导排查方向）。
    log.warning("IntegrityError on %s %s: %s", request.method, request.url.path, exc.orig)
    return JSONResponse(
        status_code=409,
        content={"detail": "数据完整性冲突（唯一约束/外键/必填），请检查后重试"},
    )


@app.get("/api/health", tags=["health"])
def health():
    return {"ok": True}


# 生产托管：若前端已 `npm run build` 出 frontend/dist，则由后端**同源**托管静态文件。
# 挂在最后 → /api/* 仍走上面的路由；其余路径回退到 SPA（index.html）。这样生产只需跑
# 一个 uvicorn（不用再单独起 vite，也无跨域），dev 时没有 dist 目录则跳过、照旧用 vite。
from pathlib import Path  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

# 打包后前端 frontend/dist 打入 _MEIPASS；源码运行时取仓库里的 frontend/dist。
_DIST = (
    Path(sys._MEIPASS) / "frontend" / "dist"        # type: ignore[attr-defined]
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parents[2] / "frontend" / "dist"
)
if _DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(_DIST), html=True), name="frontend")
    log.info("已挂载前端静态文件（生产同源托管）：%s", _DIST)
