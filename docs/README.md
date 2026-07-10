# soroban 开发记录

设计决策与开发进度。对外介绍见根目录 [README](../README.md)。

> **约定**：本 `docs/` 目录存放所有开发/设计文档，以后新文档一律放这里。

## 业务背景

个人代购／集运：在淘宝下单（付人民币）→ 国内快递 → 君丰(JF)集运把多个包裹合并转运到日本（付国际运费）→ 另有杂项开销。**最终统一按日元结算**，需要双币记账和汇率折算。使用者 2 人 + 将来的抓取机器人共用一本账。

## 技术栈决策

- **前端 Vue 3 + Element Plus**（原定 React+AntD，落地时改用与 `mercari_manage` 同栈，见下）：核心是「列表 + 编辑弹窗 + 看板」，Element Plus 的 Table/Form/Dialog 对这种场景够用够好看。数据请求 Axios + REST，需要时轮询即可看到机器人的更新（无需 WebSocket）。
  - **为何改栈**：mercari_manage（卖出侧）已是 Vue3+Element Plus，直接复用其 Layout/http(JWT)/暗色主题；且 soroban(买) 与 mercari(卖) 是同一生意两半，同栈利于将来打通利润核算。
- **后端 FastAPI + SQLModel**：Python 栈，和已有的 hiyori 项目同源。将来的抓取机器人走同一套 SQLModel 写库。
- **SQLite + WAL**：个人单机足够，WAL 让「2 人 + 机器人」的低并发读写互不阻塞。升级信号：高频并发写或上公网多人 → 换 Postgres，SQLModel 层基本不动。
- **Alembic**：从第一天管迁移（骨架期暂用 `create_all`，稳定后切 Alembic）。
- **不用 WebSocket / NiceGUI**：曾评估 NiceGUI（纯 Python 全栈），但它强依赖常连 WS；用户倾向无状态 REST + 精致前端，故走 React。

## 数据模型

三张业务表 + User。**金额统一「5 列」**，三张表都用：

| 列 | 谁填 | 说明 |
|---|---|---|
| `price_cny` | 手填/机器人，可空 | 原始人民币 |
| `fx_rate` | 预填当日汇率，**可改**，可空 | CNY→JPY，记实际成交汇率 |
| `jpy_auto` | **派生**（不可手填） | = round(price_cny × fx_rate) |
| `jpy_override` | 手填，可空 | 实付日元 |
| `jpy_settled` | **派生**（不可手填） | override 有则用之，否则用 auto |

> auto／settled 做成派生列，避免三列手动改到打架。直接用日元付款的情况：`price_cny`/`fx_rate` 留空，只填 `jpy_override`。

### 淘宝订单 TaobaoOrder
日期、订单号（唯一，可空）、店铺、链接、分类、状态（枚举：已付/已发/已收）、`快递号`（可空，归组用，多单可共享同一个）、`快递公司`（可空）、`淘宝账号`（有 2 个号，也便于机器人区分抓哪个）、`junfeng_order_id`（外键→君丰，**可空**=已买未集运）、金额 5 列（**订单总价，已含国内快递费**）。物品明细见 `OrderItem` 子表。

### 订单行 OrderItem（一单多物）
`taobao_order_id`（外键→淘宝订单）、`物品名`、`数量`。**不含单价/价格**（价格只记在订单级，见 A3）。一个淘宝订单可含多行。

### 君丰订单 JunfengOrder
日期、君丰单号（唯一，可空）、重量、国际运单号、状态（枚举：打包中/已发出/已签收）、备注、金额 5 列（`price_cny` = 国际运费）、`特殊费_日元`（int，直填，如关税/消费税，币种**恒日元**）。**本表 `jpy_auto` = round(运费×汇率) + 特殊费_日元**；`jpy_settled` 仍 override 优先。反查 `taobao_orders`。（国内快递费不在此，已折入淘宝订单总价。）

### 杂项 MiscExpense
日期、名称、分类、备注、金额 5 列。

### 共通字段（三张表）
- `source`：`manual` / `taobao_bot` / `junfeng_bot`，区分人填还是机器人抓
- `payer_id`：外键→User，付款人（多人分摊用）
- `version`：乐观锁，人和机器人同改一行时防「后写覆盖」
- `created_at` / `updated_at`
- 索引：`日期`、`快递号`

### User
登录用。用户名 + 密码哈希。登录 token 有效期 3 个月（`TOKEN_EXPIRE_DAYS=90`）。开发期用 `python -m app.seed` 建一个 admin（默认 admin/admin123），不做开放注册。

### 看板
总额 = 淘宝(商品+快递) + 君丰(运费) + 杂项 的 `jpy_settled` 相加。

## 关系设计

- 淘宝 ↔ 君丰 = **一对多**。外键只放在淘宝一侧；ORM 提供双向导航（`taobao.junfeng_order` / `junfeng.taobao_orders`）。**不要**两边都存链接（两个真相源会漂）。
- 原本是三层（淘宝 < 快递单 < 君丰），但快递费并入淘宝、快递单不单独记费 → 砍掉快递单表，`快递号` 降为淘宝订单上的字段 → 回到干净的三张表。代价：快递号分组不被数据库强制一致，个人规模可接受。

## 决策日志

- ✅ 项目命名 `soroban`（算盤），与 hiyori 同风格
- ✅ 双币结算 = 存人民币 + 记当日汇率 + 派生日元 + 可覆盖
- ✅ 登录系统要做；**token 有效期 3 个月（90 天）**（原定超长，改为 90 天）
- ✅ 付款人字段（FK→User）
- ✅ 淘宝账号字段（2 个号）
- ✅ source / version 字段，唯一约束（订单号、君丰单号），日期/快递号索引
- ✅ **退款/取消**：加 `退款/已取消` 状态，**允许金额为负**；看板只对「有效行」求和（排除已取消）
- ✅ **结算优先级**：手填 `jpy_override` **永远最高级**，覆盖一切自动值；机器人绝不碰它
- ✅ **软删除**：三张业务表加 `deleted_at`，删除只标记不物理删，所有查询过滤 `deleted_at IS NULL`。理由：账本留痕 + 多人/机器人易误删
- ✅ **看板求和**：`jpy_auto`/`jpy_settled` 落库为普通 int 列，**写入时由 `compute_money()` 用 Decimal + ROUND_HALF_UP 精确算出**（应用维护，非 DB 生成列）。SUM/GROUP BY 照常走 SQL。
  - **落地时的取舍（原计划是 SQLite 生成列，已改）**：SQLite 把 Decimal 存成 float，生成列里 `ROUND(price_cny*fx_rate)` 有浮点边界误差风险；改用 Python Decimal 精确计算更正确，也绕开 Alembic 认不全生成列的问题（原 P2）。所有写路径都过 `compute_money()`，机器人只写暂存表不写正表，故不会漂。
- ✅ **汇率记录 + 兜底**：新增 `FxRate` 表缓存每日汇率（`date` 唯一, `rate`, `fetched_at`）；录单时取当日汇率预填，**抓取失败就用最近一次成功的汇率做基准**；每条订单仍存自己的 `fx_rate` 快照
- ✅ **开发用 admin 账号**：先用 CLI/种子脚本建一个 admin，暂不做开放注册
- ✅ **配置表**：新增 key-value `Setting` 表存应用配置（含将来淘宝账号相关配置）。⚠️ 敏感凭证（cookie/session）不明文入库，用加密或 env/单独安全存储
- ✅ **前端要好用**：列表支持筛选（日期段/状态/账号/快递号/JF 单）、搜索（订单号）、分页
- ⏸️ **收入／利润**：暂不做，留口子（见 TODO）
- ⏸️ **快递单独立成表**：暂不做。若将来「一个淘宝订单拆进多个快递号/包裹」，加关联表回填即可，迁移便宜。

### 第二轮审查决策

- ✅ **金钱类型**：CNY 用 `Decimal(12,2)`，JPY 用 `int`，**全程禁用 float**
- ✅ **汇率口径 + 校验**：`fx_rate = 1 CNY = X JPY`（X≈20）；加合理性范围校验（约 5~50），防手误 20→200 导致成本 ×10
- ✅ **导入后变更告警**：暂存行导入正表后，淘宝端若再变化（尤其退款/改价），正表不自动改；需「暂存 diff → 告警」提示人回去改（否则账悄悄错）
- ✅ **乐观锁冲突 UX**：保存撞版本返回 409，前端弹「已被他人/机器人修改，请刷新」，不静默丢
- ✅ **SECRET_KEY**：强随机、进 env、绝不提交（.env 已在 .gitignore）
- ✅ **A3 价格口径**：`price_cny` = **订单总价**，不记单品价
- ✅ **C4 按月归属**：看板按月用**每条记录自身的日期**（现金制）；商品与运费可能落在不同月，接受
- ✅ **A1 君丰费用结构（定稿）**：国内快递费**折入淘宝订单总价**（不在君丰）。君丰金额 = **运费**（CNY→JPY）+ **`特殊费_日元`**（int 直填，如关税/消费税，恒日元）。`jpy_auto = round(运费×汇率) + 特殊费_日元`，`jpy_override` 整单覆盖优先。（原计划的君丰「快递费」列取消，避免与淘宝重复。）
- ✅ **A2 一单多物（定稿）**：加轻量子表 `OrderItem(物品名, 数量)`，**不含单价**；价格仍在订单级、订单号仍唯一。
- ✅ **gitignore 补漏**：已加 `*.db`/`*.db-wal`/`*.db-shm`、`node_modules/`、`frontend/dist/`
- ⏸️ **C3 批量操作**：暂不做

## 淘宝抓取架构（本轮定）

机器人**只写「淘宝抓取暂存表」，绝不直接写淘宝订单正表**。原因：淘宝账号里还有很多非集运的购买记录，不一定都进账本。

- 新增 `TaobaoStaging`（抓取暂存/收件箱）：订单号、物品名、数量、店铺、价格 CNY、下单日期、淘宝账号、快递号(如有)、`raw_json`(原始留底)、`status`(`待处理/已导入/已忽略`)、`imported_taobao_order_id`(FK→正表, 可空)、`scraped_at`、`updated_at`；唯一键 (订单号, 淘宝账号) 去重。
- 流程：机器人抓 → 进暂存表；人在收件箱**手动点「导入」**才生成正式淘宝订单（`source=imported`），或点「忽略」。重抓只更新暂存，**永不动正表** —— 天然保证机器人不覆盖任何人工字段。
- 正表淘宝订单只由人写入（手工录入 或 从暂存导入）；`version` 乐观锁仍用于 2 人并发编辑。

## 待定 / TODO

- [ ] **部署形态**（#7）：跑在哪？登录必须 HTTPS；淘宝抓取从日本 IP 可能被墙/需国内代理 —— 决定机器人部署位置
- [ ] **备份策略**（#8）：WAL 下 SQLite 用 `.backup`/litestream，不能裸 copy 文件
- [ ] **收入/利润**（#9）：加 `Sale` 表（售出价/平台/手续费/关联淘宝订单）；连带要定国际运费按（重量/货值/件数）分摊到单品算「到手成本」
- [ ] 君丰订单是否也走同样的「暂存-导入」流程（JF 单基本都是集运货，可能可直接抓）
- [ ] 淘宝账号是否从字符串升级为表 + 抓取凭证的安全存储方案
- [ ] 快递号分组一致性：UI 是否加「同快递号挂了不同 JF 单」的软告警
- [ ] 退款是否支持部分退款（金额级冲抵）还是仅整单取消
- [ ] **对接快递单号平台查物流**：接国家/第三方快递查询平台（如快递100 / 快递鸟 / 官方接口），按淘宝「快递号」或君丰「国际运单号」自动拉物流状态并展示（可加缓存/定时刷新）。
- [ ] **更换汇率 API**：现用 open.er-api 免费源仅约每日更新；将来换更实时/更可靠的汇率源（改 `backend/app/services/fx.py::fetch_rate`，其余持久化/兜底逻辑可复用）。

## 待自动化（Roadmap）

- 抓淘宝订单：需登录态、反爬重，现实做法是 Playwright 带持久化登录态**半自动**抓，或手动/CSV 导入。设计上把「数据导入」做成统一入口，抓取只是加一个数据源。
- 抓君丰订单：看其是否有导出/接口，通常比淘宝好搞。
- 汇率自动填充：**从 hiyori 移植抓取逻辑（直连 open.er-api.com），在 soroban 内自成一份 `services/fx.py`**。⚠️ 不要调用 hiyori 正在跑的接口——两个项目部署位置可能不同，soroban 的汇率必须能独立运行、不依赖 hiyori 是否在线。

## 进度

**首版 MVP 已落地并自测通过**（2026-07-09）：
- 后端（`backend/app/`）：models、schemas、auth(JWT)、routers(taobao/junfeng/misc/dashboard/fx/auth)、services/fx、seed、main 全部完成；后端 smoke test 25/25 通过；真实 HTTP 端到端跑通（登录/CRUD/看板/汇率），FX 实测拉到真实汇率并持久化。
- 前端（`frontend/`）：Vue3+Element Plus，登录、Layout 侧边栏、看板、淘宝/君丰/杂项三张「列表+编辑弹窗」页，MoneyFields 实时预览；`npm run build` 与 `npm run dev` 均通过。
- 运行：后端 `cd backend && uvicorn app.main:app --reload`（先 `python -m app.seed` 建号）；前端 `cd frontend && npm run dev`（代理 /api→8000）。

**未实现（预留）**：Alembic（仍用 create_all）、机器人抓取与收件箱 UI、收入/利润(Sale)、导出、i18n(ja/en)。

### 首版代码审查（多智能体对抗审查，已全部修复）
落地后跑了一轮 5 维度并行审查 + 每条发现独立对抗验证，确认并修复 7 个缺陷（回归测试覆盖）：
1. [高] `JunfengRead.taobao_orders` 经 relationship 序列化未过滤软删 → 已改为过滤后单独组装 `TaobaoBrief`。
2. [高] 重复 order_no/junfeng_no 触发 IntegrityError 冒泡成 500 → 加全局 `IntegrityError`→409 处理器。
3. [中] `price_cny` >2 位小数使入库 CNY 与派生 JPY 不一致 → schema 与 `compute_money` 双重量化(0.01/0.0001, ROUND_HALF_UP)。
4. [中] 乐观锁只在内存比对、UPDATE 无 `WHERE version` → 并发丢失更新 → 改为 DB 层原子 `guarded_bump`（`WHERE version=期望` + rowcount 检查）。
5. [中] 软删君丰订单未清理子淘宝订单的 `junfeng_order_id`（悬空外键）→ 删除时先置空未软删子订单的挂靠。
6. [低] `int(user_id)` 在 try 外，非数字 sub → 500 而非 401 → 移入 try 并 `except (JWTError, TypeError, ValueError)`。
7. [低] 前端预览 `Math.round` 负数半值方向与后端 ROUND_HALF_UP 相反 → 改为远离零取整。

自测：后端 25 项冒烟 + 8 项修复回归 全过；前端 build/dev 通过；真实 HTTP E2E 通过。

### 第二版：Notion 式内联编辑 + 全部淘宝订单（暂存）页
- **UI 全面改版**：新增可复用组件 `NotionTable.vue`（点单元格直接改、失焦/回车自动保存、派生列只读、底部「＋ 新建一行」）。淘宝/君丰/杂项三页与新暂存页统一用它。行内保存走 PATCH `{version,[字段]}`，用返回值 `Object.assign` 更新本地行（含新 version 与派生金额）。淘宝的「物品(一单多物)」与「所属君丰」在展开面板里编辑。
- **新页「全部淘宝订单」= 暂存表 `TaobaoStaging`**：承载一个淘宝号下所有订单（含不集运的），逐单点「导入」才建正式 `TaobaoOrder`（source=imported、汇率自动预填、item_name→OrderItem），或「忽略」。现支持手动新建/内联编辑；将来爬虫只写这张表。后端 `routers/staging.py`（list/create/patch/delete/ignore/import）。
- **暂存去重**：`order_no` 部分唯一索引（`WHERE order_no IS NOT NULL`）——淘宝单号全局唯一即去重键，同时允许多条空行手动录入。
- 第二轮对抗审查修复 3 个：暂存唯一索引 NULL 不去重→改部分唯一索引；暂存页 saveCell 缺 try/catch（409 静默丢失）→补齐并刷新回退；淘宝普通单元格自动保存会覆盖展开面板里未保存的物品编辑→saveCell 不覆盖 items。
- 自测：后端 staging 13/13 + 内联版本流 8/8 + 索引 4/4；前端 build 通过；start.sh 全栈 E2E（空行→填→导入）通过。

### 第三版：改成 Gotion 表格格式
参考 mercari_manage 的 Gotion（Notion 克隆）重写表格 UI：原生 `<table>` 网格 + 行号列（悬停变删除）+ 置顶列头 + 幽灵新建行（在底行任意格输入即建行）+ 无边框内嵌输入 + select 用 tag 弹层。拆成两个组件：`GotionCell.vue`（自管编辑态的单元格，仿 Gotion cell-types）+ `NotionTable.vue`（网格外壳）。soroban 保持固定列 schema（非 Gotion 的动态列），只借其视觉与交互格式。四页 addRow 改为接收幽灵行数据。
- **真机验证**：装 Playwright + Chromium 跑 headless 浏览器 E2E，11/11 通过（登录→暂存网格渲染→列头→幽灵行建行→内联编辑触发 PATCH→淘宝网格+展开→看板卡片→无 console 报错），并截图肉眼确认 Gotion 外观（行号/占位/派生金额蓝色/幽灵行）。
- **新建行置顶**：幽灵新建行从底部移到表头下方，与「最新在上」一致。

### 第四版：暂存页支持一单多物
「全部淘宝订单」暂存页结构对齐账本淘宝订单页：新增 `StagingItem` 子表（对齐 `OrderItem`，`TaobaoStaging.items` cascade all,delete-orphan），移除单字段 `item_name/quantity`。暂存 create/patch 用 items 列表（patch 给了就整体替换），**import 把全部物品复制成账本 OrderItem**。前端暂存页加物品摘要只读列 + 展开面板编辑（加/删/保存物品），与淘宝页同款。
- 自测：后端多物 7/7（create/patch替换/blank/import复制全部/list/cascade删除）；对抗审查 **0 缺陷**；headless 截图确认物品摘要 + 展开编辑器（设定集×1，A3海报×2）。
- 踩坑记录：期间发现是 `uvicorn --reload` 残留僵尸进程占着 8000 端口、握着被 rm 的旧 db inode，导致看到旧数据——彻底 kill 端口后即恢复（代码/数据本身无误）。

### 第五版：列可拖动换位/拖宽，布局存后端
列头可拖拽换位、拖右边缘改宽；**顺序+宽度存后端**（新增 `ColumnLayout` 表 per `table_name`，JSON `[{key,width}]`），所有人/每次渲染按后端布局一致。列定义仍在代码里（含类型/label/格式/slot），后端只存「顺序+宽度」，`NotionTable.buildCols` 合并（按保存顺序重排 base 列、套宽度；base 新增列附加在后、已删列忽略）。借鉴 Gotion 的列拖拽/拖宽，但持久化到后端而非动态列。
- 后端 `routers/layout.py` GET/PUT（upsert）；前端 `NotionTable` 加 `tableName` prop，各页传 taobao/junfeng/misc/staging。
- 自测：后端 6/6（空/put/persist/upsert/独立/422）；headless 8/8（后端顺序应用于渲染、拖宽变宽+PUT、reload 持久、原生 DnD 换位+PUT、0 报错）。
- 对抗审查修 2 个：初始拉取布局的竞态（拉取期间用户改动被 GET 旧值覆盖）→ 加 `dirtyDuringLoad` 标志；后端 upsert TOCTOU → 改 `INSERT ... ON CONFLICT DO UPDATE` 原子 upsert。修后 headless 8/8 复验通过。
- **操作列移到第一列**（行号之后、固定不参与拖拽）：让操作按钮始终可见、且不侵入拖拽/布局逻辑避免引 bug（用户明确不想出别的 bug，故未做成可拖动）。headless 6/6。

> 停服务教训：`lsof -ti tcp:PORT` 会连**客户端连接**(如 VS Code 连到 dev server)一起列出，按此 kill 会误杀 VS Code helper；停 dev server 要用 `lsof -ti tcp:PORT -sTCP:LISTEN` 只杀监听进程。另外新 turn 里 shell cwd 会重置到项目根，起 vite 前要显式 cd 到 frontend。

### 第六版：操作列收窄 + 君丰关联点选（单向）
- **操作列收窄**：`actionsWidth` 默认 72（只有删除的三页），暂存页 176（导入/忽略/删除）。
- **淘宝页「君丰(点选)」列**：readonly 列里放 el-select 富选择器，选项显示每个君丰单的「单号·日期·状态·运费结算」，选中即 PATCH `junfeng_order_id`（复用 saveCell，排除 items）。移除了展开面板里的君丰 select（避免重复入口）。
- **君丰页**：展开面板把关联淘宝订单改成**只读小表格**（订单号/日期/店铺/状态/结算¥）——`TaobaoBrief` schema 加了 date/shop/status 字段，`junfeng._read` 填充。
- **单向关联**：挂靠关系只在淘宝页编辑（FK 在淘宝侧），君丰页只读展示；不做双向编辑，避免两边改同一个 FK 引 bug（用户明确要求）。
- 自测：后端 5/5（enriched brief + 从淘宝侧 relink/unlink + 旧君丰清空）；headless 7/7（操作列窄、君丰选项含参数、点选触发 PATCH、单元格显示单号、君丰页只读表、列头正确、0 报错）。

### 第七版：全面审计 + 加固（6 维度多智能体审查，6 bug + 27 risk 确认）
**已修的 bug/加固**：
- 暂存导入**原子幂等门闸**（建单后 `UPDATE staging SET imported WHERE imported IS NULL` rowcount 校验，防并发/重复导入建重复单，尤其 order_no 为空时）；"已导入" 400→409。
- 淘宝 create/update **校验 junfeng_order_id 存在且未软删**（否则 422），防悬空/挂到已删君丰单。
- 四个列表端点 **limit/offset 上下限**（`Query(ge,le)`，防超大 limit / 负值 DoS）。
- 汇率抓取**入库前区间校验 [5,50]** + 全程 **logging**（抓取失败/成功/循环异常）。
- **前端补 `覆盖¥`(jpy_override) 可编辑列**（三张表）——此前 override 这一核心功能在 UI 无入口。
- GotionCell **数值校验**（非数字不提交）+ **防 blur/enter 重复提交**（重复 PATCH 撞乐观锁 409）。
- LIKE 搜索 **autoescape**（% _ 通配）；列布局 **table_name 白名单**；IntegrityError 提示文案放宽（不再只说订单号重复）；**CORS allow_credentials=False**（令牌走 header 不用 cookie）；启动**校验 SECRET_KEY** 不安全默认值→醒目 WARNING。
- 删除 money.js 死代码；前端删除/忽略/导入等变更**统一 try/catch**（消除未捕获 rejection）；暂存 saveCell 仅 409 才整页重拉。
- 新增 **`backup.sh`**（WAL 安全 `sqlite3 .backup` + 保留 30 份），`backups/` 已 gitignore。

**部署前置（上公网/多人前必做，当前本地可接受）**：
1. **SECRET_KEY**：`.env` 设强随机（start.sh 首次已自动生成；勿用默认）。
2. **admin 弱口令**：默认 `admin/admin123` 仅本地；部署前改密（`SOROBAN_ADMIN_PASS`），别把 demo.py 带上生产。
3. **HTTPS + 登录限流**：反代层（nginx/caddy）加 TLS 与基础限流（登录端点无限流）。
4. **CORS_ORIGINS**：收敛为精确前端域名。

**已知技术债 / 待办（记录，不急）**：
- **Alembic**：仍用 `create_all`。**下次改模型且已有真实数据前必须引入 Alembic**，否则新列/改约束不生效。
- **备份**：用 `backup.sh` 挂 cron；重要数据可上 litestream。
- **时区口径**：`created_at/updated_at` 存 UTC；"今天/本月"判断用 JST；看板按业务 `date`（无 tz）。统一以业务 date 或显式 JST 为准。
- **jpy_auto/settled 是应用维护列**：靠"机器人只写暂存表"约定保证一致；引入君丰 bot 前不得让其直接写正表。
- **暂存无乐观锁**：人工+将来机器人写同一行末写胜；接机器人前给 staging 加 version 或约定 bot 只写空字段。
- **审计字段**：将来多角色/机器人可加 `created_by/updated_by` hook（当前 `source`+`payer_id` 已部分覆盖）。
- **bcrypt<4.1** 为兼容 passlib 的钉子；将来迁 argon2/直接 bcrypt 时处理；requirements 用 `>=`，可加 lock 文件。

### 第八版：新建订单自动写入当天汇率 + 暂存加 fx_rate 列（为迁移记录）
- 淘宝/君丰**新建时**若未给 fx_rate，后端自动填 `current_rate()`（当天汇率）；显式传的汇率不覆盖。于是 CNY 一填就能自动算日元。
- **暂存表 `TaobaoStaging` 新增 `fx_rate` 列**（含 [5,50] 校验）：手动新建/将来机器人抓取时都记下当天汇率；前端暂存页加「汇率」列。
- **导入迁移**：从暂存导入账本时，`fx_rate = 暂存记录的汇率 or 当天汇率`——优先用抓取当天记下的那个，历史才准（不是用导入当天的）。
- 自测：后端 7/7（三处 create 自动填、显式不覆盖、暂存保留、导入迁移 25.5 而非当天、settled 用迁移汇率）；headless 4/4（暂存汇率列、新淘宝行自动填 23.88）。

### 第九版：已导入行 暂存↔账本 双向联动（单一真源）+ 订单状态拆列 + 点物品即展开
- **点「物品」列即展开**：`NotionTable` 加列标记 `expand: true`，点这类单元格 toggle 该行详情面板（淘宝页 + 暂存页的物品编辑区）。原展开箭头照常。
- **已导入行两页都能改、且联动**（用户选「两页都能改」）：**不做两份拷贝互相同步**（那才是易出 bug 的互锁），而是**单一真源**——导入后账本订单是唯一数据：
  - **读**（overlay）：`staging.py::_read` 对已导入行用关联账本订单的实时值覆盖显示（下单日期/订单号/店铺/淘宝号/快递号/人民币/汇率/订单状态/物品），两页永远一致。
  - **写**（write-through）：改已导入的暂存行时，共享字段写穿到账本（`_SHARED_TO_ORDER` 映射，`order_date→date`），`compute_money()` 重算、`order.version+1`（让账本页乐观锁能察觉）；未导入行仍改暂存自身副本。
  - order_no 写穿撞账本唯一索引 → 全局 409；不回写暂存自身 order_no，避免误撞暂存去重索引。
- **状态拆成两列**：暂存原来的单一「状态」是**导入工作流**（待处理/已导入/已忽略），无法映射账本；现拆为 **导入状态**（工作流，留暂存）+ **订单状态**（`order_status`：已付/已发/…，与账本 `status` 联动）。新增 `TaobaoStaging.order_status`；导入时 `order.status = row.order_status or 已付` 一同迁移。**这是为爬虫铺路**：将来爬虫更新暂存行的订单状态即可同步进账本（爬虫不频繁，故不做实时）。
- **修订早前约定**：这**有意放宽**「机器人只写暂存、绝不动正表」——但仅限**已导入**行（人已确认入账），共享字段经暂存写穿到账本属预期；未导入行仍只写暂存。相应 [第二轮] 的「导入后变更告警」需求由此联动直接满足。
- 自测：后端 TestClient 23/23（导入迁移订单状态、overlay 覆盖、双向写穿、导入状态不被污染、jpy 重算、version bump→过期 409、order_no 撞唯一→409、未导入行本地存/导入迁移）；headless E2E 10/10（两状态列、导入、暂存改状态→账本、账本改状态→暂存 双向联动、无报错）。

### 第十版：菜单改名「全部订单」+ 表格加 ID 列 + 行号删除图标去重
- **改名**：菜单/路由/页面标题「全部淘宝订单」→「全部订单」（仅显示文字；`/staging`、`TaobaoStaging`、`/api/staging` 等代码/表名/接口**均不动** —— 用户明确「大改名先搁着」）。「淘宝订单」保持不变。
- **最左单列 = ID（合并了行号 / 新建 / 删除）**：几轮迭代后定型——`NotionTable` 最左是一个固定 56px 列（非拖拽、不入布局系统、位置稳定），表头「ID」：
  - 数据行显示 `row.id`（数据库真实主键）；悬停该格 → 变红色垃圾桶 → 点击删除（各页绑 `@delete=delRow/doDelete`，带确认弹窗）。
  - 幽灵新建行的「＋/✓」按钮也在此列首格（`commitNew`）。
  - **去掉了原「行号」列**（用户：行号不需要，删除和 ID 合并成一格）。
- **「操作」列瘦身**：淘宝/君丰/杂项的操作列原本只有「删除」，删除既已并入 ID 格，这三页整列移除（无 `#actions` slot → `hasActions=false`）；全部订单的操作列保留「导入/忽略」，宽度 176→128。
- 自测：headless 16/16（四页最左即 ID 列无行号残留、数据行首格 gtn-td-id、淘宝首行 ID==后端 id、幽灵「＋」在 ID 首格、ID 格垃圾桶删除真生效 行数-1、无报错）。
- 修复两处（headless 8/8）：① 幽灵新建行里空的展开/操作格无边框 class → 网格竖/横线断，给 `.gtn-new td` 补 `border-right/bottom`（有展开列的三页可见）；② 「全部订单」菜单图标名 `Inbox` 在 @element-plus/icons-vue **不存在**（故不渲染）→ 改 `Tickets`（Layout nav + router meta 同步）。

### 第十一版：君丰页「点选式」关联淘宝订单（双向编辑，同一外键）
- **需求**：淘宝先买、集运后建，故「JF 里挑淘宝单」比「每个淘宝单去点选 JF」更贴流程。JF 页展开面板从只读改成**可编辑**：已关联淘宝单每行显示 **订单号 · 物品×数量 · 结算金额** + 「移除」；下方一个 el-select 点选下拉「＋添加淘宝订单（未挂靠）」，选项同样显示订单号·物品×数量·结算金额。淘宝页「君丰(点选)」列**保留**（两页都能改）。
- **为何双向安全**：JF↔淘宝是**同一个外键** `TaobaoOrder.junfeng_order_id`，两页改的是同一字段，不存在暂存↔账本那种「两份拷贝分叉」。
- **后端**：`POST/DELETE /api/junfeng/{jf}/taobao/{tb}` 逐单增删；`GET /api/taobao?unassigned=true` 只列未挂靠；`TaobaoBrief` 加 `items`；`_read` 用 `selectinload` 载入子物品。attach 只接未挂靠的单，已挂别的 JF → 422（防误抢，先移除再加）。
- **多智能体对抗审查（3 维度 reviewer→逐条 skeptic 复核）发现并修复**：
  - 🔴 attach/detach 原为「读-判断-写」+ 裸 `tb.version += 1`，**并发下会静默双挂/误抢**、且丢失并发的 version 自增（削弱乐观锁）。→ 改成**原子守卫 UPDATE**：`UPDATE ... WHERE junfeng_order_id IS NULL AND deleted_at IS NULL` 靠 rowcount 判定（0→422），`version = version + 1` 在 DB 层自增，与 `guarded_bump` 同风格。
  - 🟡 `TaobaoBrief` 加 items 引入子物品 N+1 → `selectinload` 批量载入。
  - （对抗复核否掉 1 条误报：淘宝页 `.tag` 死 CSS 属改动前既有，不算本次缺陷。）
- 自测：后端 TestClient **20/20**（增删/幂等/422/404/version→409/unassigned/面板带物品金额）；**并发压测 20/20**（同单同时挂 A/B，恒为「一个 200 + 一个 422」，静默双挂 0、无 500）；无头 E2E **8/8**（点选加入→面板+后端外键、移除→清空、下拉显示物品金额、无报错）。
- **君丰表加「淘宝订单」列**（可拖动列，显示 `N 单：订单号…` 摘要，空时「点击添加」）：点该格即展开上面的关联编辑面板（复用 `expand:true` 机制，与淘宝/暂存页点「物品」展开同源）。headless 8/8。

### 第十二版：退款/取消不计入合计（弃用负数冲抵）+ 全面禁负数
- **记账模型调整**（用户定）：不再「额外开一行、用负数冲抵退款」。订单打上 **退款 / 已取消** 标记即**自动不计入看板合计**——金额与物品仍照常显示，只是不加总。
- 后端：`models.CANCELLED_STATUSES` → `EXCLUDED_STATUSES`（并入淘宝 `退款`）；`dashboard._valid_conds` 用它 `status.notin_(...)` 排除求和/计数/按月。君丰仅 `已取消`（无退款态），杂项无 status 列不受影响；暂存本就不进看板。
- **全面禁负数**（「系统不需要负数」）：`MoneyIn.price_cny / jpy_override` 与 `StagingBase.price_cny` 加非负校验（<0 → 422，提示「退款/取消请用状态标记」）；0 与正数照常。覆盖淘宝/君丰/杂项/暂存四处。
- demo 去掉两条负数示例：淘宝 `TB250704050` 退款 `-25→+25`（演示「退款照显但不计入」）；杂项「超卖退款到账 `-500`」→「关税补缴 `+650`」。
- 自测：后端 TestClient **14/14**（退款/取消不计入合计与计数、金额仍算出、列表仍显示、四处禁负数 422、0/正数放行）；headless **7/7**（看板渲染、退款单正金额+标签仍显示、负数输入弹错且不落库、无报错）。

### 第十三版：「君丰订单」全量重命名为「集运订单」（Shipment）
- 去掉供应商专属词，统一为通用的「集运订单」。**代码/表/接口/变量全部重命名**，一次性大改（用户明确要求）。
- 命名对照（本文档以上所有 `君丰/Junfeng/junfeng_*` 均为当时命名，现行代码一律用右侧）：

  | 旧 | 新 |
  |---|---|
  | 君丰订单（显示） | 集运订单 |
  | `JunfengOrder` / 表 `junfengorder` | `ShipmentOrder` / 表 `shipmentorder` |
  | `JunfengStatus` / `JUNFENG_STATUS` | `ShipmentStatus` / `SHIPMENT_STATUS` |
  | `JunfengCreate/Update/Read/Base` | `ShipmentCreate/Update/Read/Base` |
  | `shipment_no`←`junfeng_no` | `shipment_no` |
  | `junfeng_order_id`（淘宝外键） | `shipment_order_id` |
  | `junfeng_order`（关系） | `shipment_order` |
  | `/api/junfeng`（+ `/{id}/taobao/{tb}`） | `/api/shipment` |
  | `Source.junfeng_bot` | `Source.shipment_bot` |
  | 看板 `junfeng_jpy/junfeng_count` | `shipment_jpy/shipment_count` |
  | `routers/junfeng.py` | `routers/shipment.py` |
  | 前端 `views/Junfeng`、`junfengApi`、`shipmentOptions`、`table-name/布局键 junfeng` | `views/Shipment`、`shipmentApi`、`shipmentOptions`、`shipment` |

- 方式：对 `backend/app`+`frontend/src` 全部 `.py/.vue/.js` 做大小写一致的整词替换（`junfeng→shipment`、`Junfeng→Shipment`、`JUNFENG→SHIPMENT`、`君丰→集运`），共 15 文件；两文件改名；无真实数据故 `create_all` 直接重灌演示库。docs 历史日志保留旧名作当时记录。
- 自测：后端启动+重灌 OK，`/api/shipment` 200 / 旧 `/api/junfeng` 404，看板出 `shipment_jpy`；代码残留 junfeng/君丰 = **0**；后端 TestClient **20/20（attach/detach 边界）+ 14/14（退款/禁负）**、并发 **20/20**、无头 E2E **11/11**（菜单=集运订单无君丰、页面/URL、点选关联打 `/api/shipment/{id}/taobao/{tb}` 写 `shipment_order_id`、淘宝页「集运(点选)」列、看板、0 报错）全部对新接口重跑通过。
