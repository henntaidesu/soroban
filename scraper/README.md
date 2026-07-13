# scraper/ — 爬虫集合（在 soroban 目录下，但被 soroban 的 git 排除）

放在 `soroban/scraper/` 下方便一起放，但 soroban 的 `.gitignore` 用 `/scraper/*/` **排除了各爬虫子目录**
（只保留本 README）——所以每个平台的爬虫**各自成库、各自 venv/Playwright、不进 soroban 的 git 与依赖**，
对 soroban 源项目零污染。爬虫不 import soroban 代码，只通过 soroban 的 **HTTP API** 把订单回灌到暂存表
（`TaobaoStaging` / 全部订单页）。

```
scraper/
  taobao/     ← 淘宝（先做这个）
  jd/         ← 京东（以后）
  pdd/        ← 拼多多（以后）
```

soroban 那边只加了**一个瘦触发端点** `POST /api/scrape` + 全部订单页一个「抓取」按钮，
按配置启动对应爬虫子进程。其余全在这里。

方案背景见 `soroban/docs/taobao-爬虫方案.md`。
