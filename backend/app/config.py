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

    # Frontend dev origin(s) for CORS（默认前端端口 8621；同源托管/vite 代理下其实用不到）。
    CORS_ORIGINS: list[str] = ["http://localhost:8621", "http://127.0.0.1:8621"]

    # --- 爬虫插件目录（soroban 扫这里的 soroban-scraper-* 子目录作为插件）---
    # 默认 = soroban 仓库下的 scraper/；可用环境变量覆盖到别处。
    SCRAPER_DIR: Optional[str] = None


settings = Settings()
