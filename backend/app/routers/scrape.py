"""触发外部爬虫（独立进程，代码在 soroban 仓库外的 scraper/）。

soroban 只负责「按配置启动它」，不含任何抓取逻辑。爬虫抓完自行走 /api/staging 回灌暂存表。
按命令以列表形式启动（无 shell），account 作为单个参数传入，无注入面。
"""

import shlex
import subprocess
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from ..auth import get_current_user
from ..config import settings

router = APIRouter(
    prefix="/api/scrape", tags=["scrape"], dependencies=[Depends(get_current_user)]
)


@router.post("")
def trigger(account: Optional[str] = Query(None, description="仅抓某个淘宝账号；不填=爬虫按自身配置抓全部")):
    if not settings.SCRAPER_CMD:
        raise HTTPException(
            status_code=400,
            detail="未配置爬虫：在 soroban 后端 .env 设 SCRAPER_CMD / SCRAPER_CWD（见 scraper/taobao/README）。",
        )
    cmd = shlex.split(settings.SCRAPER_CMD)
    if account:
        cmd += ["--account", account]
    try:
        # fire-and-forget：立即返回，爬虫在独立进程里跑（输出进它自己的 scrape.log）
        proc = subprocess.Popen(
            cmd, cwd=settings.SCRAPER_CWD or None,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
        )
    except (OSError, ValueError) as e:
        raise HTTPException(status_code=500, detail=f"启动爬虫失败：{e}")
    return {"started": True, "pid": proc.pid}
