#!/usr/bin/env bash
# soroban 一键启动：首次运行自动建 venv、装依赖、建 admin；之后直接起后端+前端。
# 用法：./start.sh   （Ctrl+C 同时停掉两个服务）
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
PY_BIN="$BACKEND/.venv/bin/python"
UVICORN_BIN="$BACKEND/.venv/bin/uvicorn"

green() { printf "\033[32m%s\033[0m\n" "$1"; }
yellow() { printf "\033[33m%s\033[0m\n" "$1"; }
red() { printf "\033[31m%s\033[0m\n" "$1"; }

command -v python3 >/dev/null || { red "缺少 python3"; exit 1; }
command -v node >/dev/null || { red "缺少 node（前端需要）"; exit 1; }

# ---- 后端首次设置 ----
if [ ! -d "$BACKEND/.venv" ]; then
  yellow "首次运行：创建 Python 虚拟环境并安装后端依赖…"
  python3 -m venv "$BACKEND/.venv"
  "$PY_BIN" -m pip install --quiet --upgrade pip
  "$PY_BIN" -m pip install --quiet -r "$BACKEND/requirements.txt"
  green "后端依赖已安装。"
fi

# .env：不存在则从模板生成，并写入随机 SECRET_KEY
if [ ! -f "$BACKEND/.env" ]; then
  SECRET="$("$PY_BIN" -c 'import secrets; print(secrets.token_hex(32))')"
  sed "s|^SECRET_KEY=.*|SECRET_KEY=$SECRET|" "$BACKEND/.env.example" > "$BACKEND/.env"
  green "已生成 backend/.env（含随机 SECRET_KEY）。"
fi

# 建/确认 admin 账号（幂等）
( cd "$BACKEND" && "$PY_BIN" -m app.seed )

# ---- 前端首次设置 ----
if [ ! -d "$FRONTEND/node_modules" ]; then
  yellow "首次运行：安装前端依赖（npm install）…"
  ( cd "$FRONTEND" && npm install )
  green "前端依赖已安装。"
fi

# ---- 启动 ----
BACK_PID=""
FRONT_PID=""
cleanup() {
  echo
  yellow "正在停止…"
  [ -n "$BACK_PID" ] && kill "$BACK_PID" 2>/dev/null || true
  [ -n "$FRONT_PID" ] && kill "$FRONT_PID" 2>/dev/null || true
  # 顺手清掉可能残留的子进程
  pkill -P "$BACK_PID" 2>/dev/null || true
  pkill -P "$FRONT_PID" 2>/dev/null || true
  exit 0
}
trap cleanup INT TERM

green "启动后端  → http://127.0.0.1:8000  (API 文档 /docs)"
( cd "$BACKEND" && exec "$UVICORN_BIN" app.main:app --host 127.0.0.1 --port 8000 --reload ) &
BACK_PID=$!

green "启动前端  → http://localhost:5173"
( cd "$FRONTEND" && exec npm run dev ) &
FRONT_PID=$!

echo
green "soroban 已启动。默认账号 admin / admin123"
green "浏览器打开 http://localhost:5173 ，Ctrl+C 停止全部。"
echo

wait
