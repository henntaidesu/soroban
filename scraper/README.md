# scraper/ — 爬虫插件集合（在 soroban 目录下，但被 soroban 的 git 排除）

放在 `soroban/scraper/` 下方便一起放，但 soroban 的 `.gitignore` 用 `/scraper/*/` **排除了各爬虫子目录**
（只保留本 README）——所以每个平台的爬虫**各自成库、各自 venv/Playwright、不进 soroban 的 git 与依赖**，
对 soroban 源项目零污染。爬虫不 import soroban 代码，只通过 soroban 的 **HTTP API** 把订单回灌到暂存表
（`TaobaoStaging` / 全部订单页）。

```
scraper/
  soroban-scraper-taobao/   ← 淘宝（先做这个，各自成库、含 plugin.toml）
  soroban-scraper-jd/       ← 京东（以后）
  soroban-scraper-pdd/      ← 拼多多（以后）
```

## 插件契约
soroban 自动扫本目录下 `soroban-scraper-*` 子目录作为**插件**：读各自的 `plugin.toml` 清单
（`id`/`name`/`version`/`python`/`entry`/`state_dir`/`params`），在**「插件管理」页**统一做
授权登录、参数、启用/定时；触发时按 manifest 用子进程调插件的**标准 CLI**
（`login`/`fetch`/`status`），并把 soroban 短期 token 下发给它回灌，插件无需存 soroban 密码。
新增一个平台爬虫 = 建一个 `soroban-scraper-<平台>/` + 一份 `plugin.toml` + 实现同款 CLI，soroban 自动认到。

soroban 侧的对接代码在 `backend/app/routers/plugins.py`（发现/配置/触发/定时）。
方案背景见 `soroban/docs/taobao-爬虫方案.md`。
