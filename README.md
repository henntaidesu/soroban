# soroban（算盤）

个人代购／集运记账系统。追踪「淘宝下单 → 快递 → 君丰(JF)集运到日本 → 杂项」的全流程开销，**统一按日元结算**，双币（人民币／日元）记账。

## 功能

- **看板**：总支出、按月趋势、各类占比（淘宝商品／君丰运费／杂项）
- **淘宝订单**：可编辑表格，支持手动录入 + 加行 + 改行
- **君丰订单**：一个 JF 订单关联多个淘宝订单（集运合包）
- **杂项支出**
- **双币结算**：填人民币自动按当日汇率折算日元，可手动覆盖实付金额
- **登录**：多人共用一本账，登录状态长期保持

## 技术栈

| 层 | 选型 |
|---|---|
| 前端 | Vue 3 + Element Plus + Vite + Axios |
| 后端 | FastAPI + SQLModel |
| 数据库 | SQLite（WAL 模式） |
| 迁移 | Alembic |
| 汇率 | open.er-api.com（CNY→JPY） |

## 目录结构

```
soroban/
├── backend/            FastAPI + SQLModel
│   ├── app/
│   │   ├── config.py   配置（读 .env）
│   │   ├── database.py engine + WAL
│   │   ├── models.py   数据模型
│   │   ├── routers/    REST 接口
│   │   ├── services/   汇率等
│   │   └── bot/        （将来）订单自动抓取
│   └── requirements.txt
├── frontend/           React + Vite + Ant Design
└── docs/               开发记录、设计决策
```

## 本地运行

**一键启动（推荐）**：
```bash
./start.sh
```
首次运行自动建 venv、装前后端依赖、生成 `.env`（随机 SECRET_KEY）、建 admin；之后直接同时起后端(8000)+前端(5173)。浏览器开 http://localhost:5173 （默认 `admin` / `admin123`），Ctrl+C 一起停。

---

手动分开跑：

后端：
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # 编辑 SECRET_KEY 等
python -m app.seed            # 建 admin（默认 admin/admin123）
uvicorn app.main:app --reload --port 8000
```

前端（另开一个终端）：
```bash
cd frontend
npm install
npm run dev                   # http://localhost:5173 （代理 /api → :8000）
```

## 状态

✅ 首版 MVP 已完成并自测通过：登录 + 三张「列表/编辑」页 + 看板 + 双币结算 + 汇率。
详见 [docs/](docs/)。机器人抓取、收入/利润等为预留项。
