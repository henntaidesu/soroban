"""App configuration. Reads from environment / .env (see .env.example)."""

from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    SECRET_KEY: str = "dev-insecure-key-change-me"
    DATABASE_URL: str = "sqlite:///./soroban.db"
    TOKEN_EXPIRE_DAYS: int = 90  # 登录有效期 3 个月
    ALGORITHM: str = "HS256"

    # --- Exchange rate (open.er-api.com, free, no key) ---
    # 抓取逻辑从 hiyori 移植、本项目自带一份；不调用 hiyori 的接口（部署位置可能不同）。
    FX_BASE: str = "CNY"
    FX_QUOTE: str = "JPY"
    FX_REFRESH: int = 21600  # 6h；免费源约每日更新一次

    # Frontend dev origin(s) for CORS.
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    # --- 外部爬虫触发（代码在 soroban 仓库外的 scraper/ 里）---
    # 全部订单页「抓取」按钮 → POST /api/scrape → 按此命令启动爬虫子进程。不配则该按钮报「未配置」。
    # 例：SCRAPER_CMD="/…/scraper/taobao/.venv/bin/python -m taobao_scraper.run"
    SCRAPER_CMD: Optional[str] = None
    SCRAPER_CWD: Optional[str] = None   # 爬虫工作目录（-m 解析用），一般是 scraper/taobao/


settings = Settings()
