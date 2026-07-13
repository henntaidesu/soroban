"""soroban FastAPI app entrypoint."""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from . import models  # noqa: F401  确保建表前所有模型已注册
from .config import settings
from .database import create_db_and_tables
from .routers import auth, dashboard, fx, shipment, layout, misc, plugins, staging, tags, taobao
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
    create_db_and_tables()          # MVP 阶段用 create_all；真数据前切 Alembic
    tasks = [asyncio.create_task(fx_loop()), asyncio.create_task(scheduler_loop())]
    try:
        yield
    finally:
        for t in tasks:
            t.cancel()


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
    auth.router, taobao.router, shipment.router, misc.router,
    staging.router, dashboard.router, fx.router, layout.router, tags.router, plugins.router,
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
