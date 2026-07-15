"""soroban 打包入口（PyInstaller 冻结后即 soroban.exe）。

单进程：uvicorn 起 FastAPI（app.main:app），后端**同源**托管打入包内的前端 frontend/dist，
API 与页面同端口。运行前把工作目录切到 exe 同级，使 .env、sqlite:///./soroban.db、scraper/
都相对 exe 目录解析——整包可随目录一起分发。

开发/源码运行不需要它，照旧用 start.bat 或 `uvicorn app.main:app`。
"""

import os
import sys
from pathlib import Path


def _runtime_dir() -> Path:
    """运行时数据目录：打包后取 exe 同级，源码运行取 backend/。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def main() -> None:
    rt = _runtime_dir()
    os.chdir(rt)  # 让 .env / soroban.db（默认 sqlite:///./soroban.db）落在 exe 同级

    # 默认 0.0.0.0：监听所有网卡，局域网/外网才能访问（仅本机用可设 HOST=127.0.0.1）。
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("BACKEND_PORT", "8620"))

    import uvicorn
    from app.main import app  # 触发建表/迁移在 lifespan 内进行

    # 幂等建库/迁移 + 确保有 admin（首次分发即可登录；已存在则跳过）。
    from app.seed import main as seed_admin
    try:
        seed_admin()
    except Exception as e:  # 建号失败不阻断启动（日志提示即可）
        print(f"[warn] 初始化 admin 失败：{e}")

    shown = "127.0.0.1" if host == "0.0.0.0" else host
    print(f"soroban 已启动，监听 {host}:{port}  (API 文档 /docs)")
    print(f"  本机访问 -> http://{shown}:{port}")
    if host == "0.0.0.0":
        print(f"  外网/局域网访问 -> http://<本机IP>:{port}（需放行防火墙 TCP {port}）")
    print("默认登录：admin / admin123（首次请用 seed 或改密）。按 Ctrl+C 退出。")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
