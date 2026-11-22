# 民宿托管经营系统 · 单元四收尾的一种参考实现（单元三两规则版 + DSH 薄插件）

这套代码对应课程单元四（把查数能力装进对话）收尾时的一种做法：**单元三那一版原样保留**（城市经营看板 + 问数面板 + 小区地图 + 巡检 Agent），再加一个薄插件 `dsh-plugin/`，把后端已有的 4 个只读查询包成对话里的工具，每次调用在对话里出一张图表卡片。

插件不连数据库、也不重算指标：口径、同比、市场基准仍由单元三的后端（`app/`）算好，插件只发 HTTP 请求、挑字段、拼展示文案。所以**顺序是「先起后端，再装插件」**（第 10 节）。

它是**参考实现，不是标准答案**。规则编号、参数取值、建议措辞、界面文案都可以和你做出来的不一样；验收只看不变量（判定权与执行权分开、预览后才落表、没人批准改不了数据、幅度不超上限、建议能回查证据与规则编号）。

巡检 Agent 这一版只做两条规则：

- **N-01** 不调价情形里以房东关房为条件的那一条：房东关房导致成交少时，不给降价建议；
- **P-01** 单次调价幅度上限：一次调价不超过上限，超了拒绝并给出规则编号与允许范围。

其余规则类别本版没有实现，页面、接口、审批流程在没有它们时照常工作（第 5 节）。

单元四在这套代码上多了三样东西，细节都在**第 10、11 节**：

- `dsh-plugin/`（7 个文件）：薄插件本体，4 个只读工具 + 4 张卡片；
- `app/queries.py` 的一处定点补丁：`/api/districts` 多返回 `adr_prev_year`、`adr_yoy` 两个键（「平均房价」对比要用），**只加字段、不改任何口径**；
- 「起后端 → 装插件 → 导出卡片数据」的说明与只读白名单。

## 1 运行环境

| 项 | 要求 |
|---|---|
| Python | 3.12 |
| 依赖 | 见 `requirements.txt`（FastAPI + uvicorn + jinja2 等，固定版本） |
| 前端 | 无构建链，不需要 Node；图表库已本地化在 `app/static/vendor/` |
| 业务库 | `data/homestay.db`（只读打开；文件不进版本库，按课程数据包放到该位置） |
| 运营库 | `data/ops.db`（首次使用时自动建表；可随时删掉重建） |

## 2 启动

在仓库根目录执行（PowerShell 示例；其他平台把路径分隔符换掉即可）：

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
copy .env.example .env                                  # 可选；不填也能启动
.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8801
```

打开 <http://127.0.0.1:8801/>。课程统一用 8801；被占用就换空闲端口，并记下实际用的端口，后面的步骤都用它。起之前先确认没被占用（PowerShell：`Get-NetTCPConnection -LocalPort <端口> -State Listen`）。

单元四的插件默认就连 `http://127.0.0.1:8801`。所以换端口时两边要一起改：要么把后端固定在 8801，要么改插件的 `baseUrl` 再重启 DSH（第 10.2 节）。

停止：在启动窗口按 `Ctrl+C`。

运营库操作（服务停着时做）：

```powershell
.venv\Scripts\python -m app.ops_store --reset            # 删除并重建 data/ops.db
```

## 3 环境变量（仓库根 `.env`，不进版本库）

环境变量同名且非空时优先于 `.env`。键名与说明见 `.env.example`，这里只列用途：

| 键 | 用途 |
|---|---|
| `LLM_BASE_URL` | OpenAI 兼容接口地址（问数与巡检共用） |
| `LLM_MODEL` | 模型名（问数与巡检共用） |
| `LLM_API_KEY` | 模型接口密钥（可选）：有值时请求头加 `Authorization: Bearer …`，本地无鉴权接口可留空 |
| `AMAP_JS_KEY` | 地图 Web 端 Key（会下发到浏览器） |
| `AMAP_JS_SECURITY_CODE` | 地图安全密钥（只留在服务端，由 `/_AMapService` 代理追加） |
| `AMAP_WEB_SERVICE_KEY` | 地图 Web 服务 Key（应用不直接用） |
| `INSPECT_N01_MAIN_SHARE` | 巡检参数：关房占比的判定值，取值见第 4 节 |
| `INSPECT_N01_MIN_CALENDAR_NIGHTS` | 巡检参数：当期日历晚数下限 |
| `INSPECT_N01_MAX_GROSS_OCCUPANCY` | 巡检参数：毛入住率上限 |

不填模型相关的前两项时：问数接口返回 503；巡检照常跑完，报告与类别说明换成模板文字（页面会标“已降级为规则模式”）。不填地图 Key 时：页面不加载在线底图，自动退回离线散点，不报错。

想现场看降级：只把 `LLM_BASE_URL` 指向一个不可达地址再启动，巡检的建议集合不变，只有报告文字变成模板。

## 4 两条规则与参数

规则原文在 `docs/运营手册.md`，指标口径在 `docs/指标口径表.md`。代码里的取值是**参考实现的取舍**，不是标准答案。

### N-01 不调价情形 · 房东关房

手册说：房东关房期间、以及成交晚数低主要由房东关房造成时，不调价；关房不算空置（口径表 T-01）。手册对“成交少”“主要”只有定性说法，落地要先把它们量化。

本实现这样落：当期（数据截止日所在季）满足三条的在线房源，产出一条“不处理”建议，动作是“不处理”，引用 N-01 与 T-01，并附三条证据（日历晚数、毛入住率、房东关房晚数）：

| 条件 | 参数（环境变量） | 参考实现的默认值 |
|---|---|---|
| 当期日历晚数达到下限（否则谈不上“成交少”） | `INSPECT_N01_MIN_CALENDAR_NIGHTS` | 60 |
| 毛入住率低于上限（否则不算“成交少”） | `INSPECT_N01_MAX_GROSS_OCCUPANCY` | 0.55 |
| 房东关房晚数 ÷ 日历晚数达到判定值（即“主要由房东关房造成”） | `INSPECT_N01_MAIN_SHARE` | 0.30 |

**这三个数是参考实现的取值，学员要在自己的需求里自定**，并把“主要”的量化写进需求歧义声明；换一组参数，命中的房源集合就会变，这是正常的。

### P-01 单次调价幅度上限

手册说：单次调价幅度上限 15%（涨或降都算，以当前平日价为基数），超过上限的申请一律驳回。

本实现两处用到同一条上限：

1. **扫描**：当前价相对上一档是人工上调、且上调幅度已经超过上限的在线房源，产出一条“调价申请”建议——优先回调到上一档；上一档一次够不着时，只降一个上限（当前价 × 0.85 向上取整），并标“需人工评估”，剩下的差距留给人工（手册 P-05 同样是“先申请上限以内”）。
2. **写入**：预览（`POST /api/ops/preview`）与提交（`POST /api/ops/commit`）各校验一次，幅度超过上限就拒绝，返回规则编号 `P-01` 与允许的价格范围；同一房源已有未关闭的调价申请时也不许再申请（两条各自合规的申请叠加起来就绕过了上限）。

扫描只用到手册里的 15%，没有其它阈值常量。

## 5 本版没有的规则类别

区级跑输、小区评论集中主题、入住子评分偏低、房价偏离市场这几类扫描规则，以及它们各自的阈值常量，本版**删掉了**（不是改值）。删掉之后：

- 巡检查不出这几类问题，报告里也不会出现对应类别；
- 页面与接口在缺少这些类别时正常工作：建议清单只显示实际出现的类别，分类筛选按出现的类别生成，类别说明只渲染有内容的类别；
- 审批流程与两条规则无关的部分（预览、提交、批准/驳回、审计、邮件草稿）照常工作。

要把它们补回来，先在自己的需求里写清判据，再改代码；阈值一律取运营手册的字面值，或写进需求歧义声明。

## 6 审批与运营库

写操作全在运营库 `data/ops.db`，业务库 `data/homestay.db` 始终只读（打开方式带 `mode=ro`；跑完巡检业务库文件指纹不变）。

三张业务表与一张内部表：

| 表 | 用途 |
|---|---|
| `price_change_requests` | 调价申请（原价、拟调价、幅度、理由、证据、状态、审批人） |
| `maintenance_tickets` | 整改工单（房源、问题类型、证据、状态） |
| `audit_log` | 每次工具调用一行（时间、工具名、参数、结果），含被拒绝的调用；只经接口查看，页面不展示 |
| `previews` | 预览记录（内部表）：预览时算好的行，提交时才落进上面两张业务表 |

流程是三段，不能合并：

1. **预览**：只算出“将要写入的那一行”，不落表；校验不过就直接返回拒绝原因与规则编号；
2. **提交**：由人触发（页面按钮或接口），逐条**按当时库状态重跑**校验，通过的才落表，状态为“待审”；
3. **审批**：由人触发，只改状态（批准 / 驳回），不改价格记录；工单批准后在 `outbox/` 生成一封给房东的邮件草稿（`.eml`，`X-Draft: true`），不发送。

工具清单里只有读工具与两个“预览”写工具（`preview_price_change`、`preview_ticket`），没有提交与审批；清单外的名字一律拒绝并记一行审计。

## 7 接口

| 接口 | 参数与返回 |
|---|---|
| `GET /api/agent/run/{run_id}` | 巡检进度与结果：`state`、`mode`、`degraded`、`degrade_reason`、`steps[]`、`suggestions[]`、`category_notes`、`report`、`meta`、`params`（本次用的巡检参数） |
| `POST /api/agent/run` | `{use_llm: bool = true}` → `{run_id}`；后台执行，页面轮询上一条 |
| `POST /api/ops/preview` | `{kind:"price_change", listing_id, proposed_price, reason, evidence}` 或 `{kind:"ticket", listing_id, issue_type, evidence}` → `{ok, preview_id?, reject_reason?, rules?, row?}` |
| `POST /api/ops/commit` | `{preview_ids:[...]}` → `{committed:[{kind,id,preview_id}], rejected:[{preview_id, reason}]}` |
| `GET /api/ops/items` | 调价申请与整改工单两张表全部行 |
| `POST /api/ops/decision` | `{kind, id, decision:"approve"|"reject"}`；只有“待审”可决策，工单批准时返回 `outbox` 路径 |
| `GET /api/ops/audit` | `run_id`（可选）→ `{rows:[...]}` |

看板与问数接口（单元一、二，未改动）：`/api/meta`、`/api/kpi`、`/api/trend`、`/api/compare`、`/api/structure`、`/api/distribution`、`/api/geo`、`/api/districts`、`/api/communities`、`/api/communities/listings`、`POST /api/ask`。

## 8 目录

| 路径 | 内容 |
|---|---|
| `app/main.py` | FastAPI 入口：页面、看板接口、地图安全密钥代理；问数路由与巡检路由缺模块时降级启动 |
| `app/config.py` | 读 `.env` 与环境变量 → `settings`（含三个巡检参数） |
| `app/queries.py` | 只读连接与聚合（看板、问数共用） |
| `app/ask/` | 问数（NL2SQL + 确定性诊断）与只读 SQL 护栏 `app/sqlguard.py` |
| `app/agent/rules.py` | 两条规则的单一真相源：扫描、处置、理由与说明模板、三个参数 |
| `app/agent/tools.py` | 工具清单与唯一入口 `dispatch_tool`（清单外拒绝并记审计） |
| `app/agent/runner.py` | 巡检编排：程序判 → 模型查与写 → 模板补齐 → 报告 |
| `app/agent/llm_gate.py` | 唯一调用模型客户端的包装；每次调用记一行 `logs/agent_llm.jsonl`（不记提示词与回答正文） |
| `app/ops_store.py` | 运营库：建表、校验、预览/提交/审批、审计、邮件草稿 |
| `app/tools/metrics.py` | 房源级指标（R12 入住率、R13 关房晚数、R16 价格）的单一实现 |
| `app/templates/`、`app/static/` | 页面模板与前端资源（含本地化的图表库） |
| `dsh-plugin/` | 单元四的 DSH 薄插件：4 个只读工具 + 卡片渲染（第 10 节） |
| `docs/运营手册.md`、`docs/指标口径表.md` | 规则与口径的来源 |

## 9 校正过的几处

- 模型接口地址与模型名只从配置读，代码里不留默认值：没配就走规则模式，不会连到别人的服务上。
- 提示词里举例不再点具体区名，改成“按问句里的区名原样写”。
- `/api/districts` 多返回两个键 `adr_prev_year`（上年同期平均房价）与 `adr_yoy`（变化率），给单元四插件的「平均房价对比」用；**只加字段，已有字段的口径与算法都没动**。旧版后端没有这两个键时，插件的平均房价对比会报 `E_HOMESTAY_HTTP` 并提示重启后端。
- 插件 id 与包名一致（id `dsh-homestay`、包名 `@local/dsh-homestay`）；工具描述里的区名举例改成泛称（“如该区名称，带不带『区』字都行”）。
- 插件源码里只留代码与展示文案：内部规格编号、评审意见编号、工作过程代号都不在包里。
- 本 README 只写启动、规则、参数、审批与运营库；数据生成方式、验收判据、试跑记录见课程材料。

## 10 单元四：把 4 个只读工具装进对话（DSH 薄插件）

**先起后端，再装插件。** 插件只调本存档点后端的 4 个只读接口，不连库、不重算口径。后端没起时 4 个工具都报 `E_HOMESTAY_DOWN`，提示里带启动命令。

### 10.1 工具与它们发的请求（只读白名单）

| 工具 | 参数 | 发的请求 | 卡片 `kind` |
|---|---|---|---|
| `homestay_compare` | `start`、`end`（`YYYY-MM-DD`，2024-10-01 ≤ start ≤ end ≤ 2026-09-30）；`metric`：`occupancy`（缺省）\| `adr` | `GET /api/districts` 一次 | `homestay-compare` |
| `homestay_trend` | `district`（可省：`D01`–`D08` 或区名）；`metric`：`occupancy`（缺省）\| `adr` \| `revpar` \| `rating`；`from`、`to`（`YYYY-MM`，缺省 2025-10 ~ 2026-09，跨度 ≤ 24 个月） | `GET /api/trend`；`district` 传区名时先 `GET /api/districts` 取编号 | `homestay-trend` |
| `homestay_communities` | `start`、`end`（同上边界）；`district`（可省）；`sort`：`yoy`（缺省）\| `occupancy`；`order`：`asc`（缺省）\| `desc`；`limit` 1–20 | `GET /api/communities`；同上，传区名时先取编号 | `homestay-communities` |
| `homestay_ask` | `question`（去掉首尾空白后 1–200 字） | `POST /api/ask`（超时 120 秒） | `homestay-ask` |

- **只发上表这 4 种请求**。插件不碰 `/api/ops/*`、`/api/agent/*`，不发写请求，也不直接打开 `data/homestay.db`。
- GET 超时 8 秒、问数 120 秒。参数不过关时**不发请求**，直接报 `E_HOMESTAY_ARGS`。
- 平均房价对比（`metric=adr`）要用 `/api/districts` 的 `adr_prev_year`、`adr_yoy` 两个键，本存档点的 `app/queries.py` 已经补上（第 9 节）。

### 10.2 装插件

`dsh-plugin/` 是一个 DSH 插件包：包名 `@local/dsh-homestay`，插件 id `dsh-homestay`（两者一致），`package.json` 里 `dsh.bundle.patch` 指向 `cordis.patch.yml`。7 个文件各管什么：

| 文件 | 作用 |
|---|---|
| `index.js` | Host 侧：注册 4 个工具、发 HTTP、校验参数与响应、算展示文案与卡片数据 |
| `client.js` | Web 侧：把卡片数据画成 React + SVG 图表（不引外部图表库） |
| `cordis.patch.yml` | 装载入口：插件 id、包名、`config`（换端口改这里） |
| `locale/zh.json`、`locale/en.json` | 插件管理器里显示的标题与说明 |
| `icon.svg` | 插件图标 |
| `package.json` | 包声明：名字、版本、`dsh.bundle.patch`、`dsh.client` 注入 |

三种装法，任选一种：

1. **界面（推荐）**：DSH 的「插件」→「添加插件」→ 选本地目录，指到本存档点的 `dsh-plugin/`。
2. **命令行**：`dsh plugin --profile <你的 profile 名> add "link:<本存档点绝对路径>/dsh-plugin"`。`link:` 是链接安装，不复制文件；改完源码重启 DSH 就生效，不用重装。
3. **插件管理器工具**：`install_bundle`，`target` 传 `dsh-plugin/` 的绝对路径。

装完**新开一个会话**（工具清单在会话开始时装载），然后说一句会用到工具的话，例如“用 homestay_trend 看看全公司最近的入住率走势”，应当看到工具调用 + 一张卡片。

**换端口**：插件不读 `.env`、不读环境变量，端口只有 `cordis.patch.yml` 一处。改完重启 DSH（链接装的不必重装）：

```yaml
- insert:
    - id: dsh-homestay
      name: '@local/dsh-homestay'
      config:
        baseUrl: 'http://127.0.0.1:8812'
```

**卸载 / 只停用**：插件管理器里「删除」或「停用」这条 bundle；命令行装的可 `dsh plugin --profile <profile> remove @local/dsh-homestay`（这条只是把包装出 profile，插件列表里那一行若还在，到界面里删掉或停用即可）。

> 同一台 DSH 里若已经装过同名插件（`@local/dsh-homestay`），**先卸掉旧的再装**：两条同 id 的插件会互相顶掉，症状是工具时有时无。

### 10.3 对象 id 与数据边界

- **区**：编号 `D01`–`D08`；区名由 `GET /api/districts` 返回，工具卡片上也显示区名。`district` 两种写法都收（带不带“区”字都行），对不上会报 `E_HOMESTAY_ARGS` 并把合法取值列出来。
- **小区**：模拟名称，按 `GET /api/communities` 返回的名字写；一个区里的小区数不等，`limit` 只截排行前 N 条。
- **时间**：数据覆盖 2024-10-01 ~ 2026-09-30；日粒度接口两端都在这个范围里，月粒度接口 2024-10 ~ 2026-09、跨度 ≤ 24 个月。月度缺省 `2025-10 ~ 2026-09` 就是“最近 12 个月”（以数据截止月为终点）。
- **`as_of`**：`/api/districts`、`/api/communities` 的 `as_of` 等于请求里的 `end`；房源数按 `end` 当天在线计。

### 10.4 卡片数据怎么导出

插件**没有**导出按钮——卡片是画在页面上的 DOM。数据有三条出口：一条一键取、一条机器可读、一条从页面上抠。

**1. 一键导出 `window.__cardExport()`（最省事）**：在 DSH 页面控制台执行 `window.__cardExport()`，同步返回最近一张卡片的结构化数据；还没出过卡片（或最近那张是错误卡）时返回 `null`：

```json
{"tool": "homestay_compare",
 "params": {"start": "2025-01-01", "end": "2025-03-31", "metric": "occupancy"},
 "rows": [{"key": "D08", "label": "钱塘区 49.9%", "value": 0.4989}]}
```

`tool` 是工具名，`params` 是这次调用的参数，`rows[]` 是图上的行：`key` 为区编号 / 月份 / 小区名，`label` 是卡片上该行显示的文字，`value` 是机器值（比例与百分点差用 0–1 小数，金额与评分取原值）。把返回值存成 `card.json`，就能直接喂给检查命令的 `--card`。

**2. 结构化数据（不经 DSH 取数）**：每个工具的结果里都带 `presentationMeta`（`v: 2`，就是卡片的数据源），字段有 `kind` / `title` / `subtitle` / `footnote` / `series` / `rows` / `points` / `axis`（按卡片类型不同）。这份数据跟卡片上的显示串是同一份，不经 DSH 也能取：

```js
// 在 dsh-plugin/ 的同级目录建一个 .mjs 文件，node 跑它（不需要 DSH）
import { __test } from './dsh-plugin/index.js'
const tools = __test.createTools({ baseUrl: 'http://127.0.0.1:8801' })
const def = tools.homestay_compare
const value = await def.execute({ start: '2026-07-01', end: '2026-09-30' }, {})
console.log(JSON.stringify(def.output.presentationMeta({}, value), null, 2))
```

`__test.createTools(config)` 是 `index.js` 里导出的测试入口，与 `apply()` 注册的是同一份定义；`config.baseUrl` 换地址，`config.fetch` 可以注入一个记录器把发出去的请求全记下来（对账“只发白名单请求”就用它）。

**3. 页面上的锚点（人眼 + 控制台）**：每张卡片的根节点带 `data-homestay-card="<状态>"` 与 `data-kind`，里面用 `data-hs-title`、`data-hs-subtitle`、`data-hs-foot`、`data-hs-table`、`data-hs-row`（行，`data-key`）、`data-hs-mark`（柱/点，`data-series`/`data-key`）、`data-hs-label`（刻度文字，`data-key`/`data-field`）标好。在页面按 F12 粘这段，可把当前页面上所有卡片导出成一段 JSON（`copy()` 直接进剪贴板）：

```js
copy(JSON.stringify([...document.querySelectorAll('[data-homestay-card]')].map((card) => ({
  kind: card.dataset.kind,
  state: card.getAttribute('data-homestay-card'),
  title: card.querySelector('[data-hs-title]')?.textContent ?? null,
  subtitle: card.querySelector('[data-hs-subtitle]')?.textContent ?? null,
  foot: card.querySelector('[data-hs-foot]')?.textContent ?? null,
  rows: [...card.querySelectorAll('[data-hs-row]')].map((tr) => ({
    key: tr.dataset.key,
    cells: [...tr.children].map((td) => td.textContent),
  })),
  marks: [...card.querySelectorAll('[data-hs-mark]')].map((n) => ({ series: n.dataset.series, key: n.dataset.key })),
  labels: [...card.querySelectorAll('[data-hs-label]')].map((n) => ({ key: n.dataset.key, field: n.dataset.field, text: n.textContent })),
})), null, 2))
```

锚点名按 `client.js` 里的写法取；这段片段是按锚点写的，存档点交付时没有安装宿主插件，所以**片段本身没在真实卡片上跑过**，第一次用请先拿一张卡片核对字段对不对。

> **仍然没有的**：导出按钮与自动截图。一键取数已经在第 1 条（`window.__cardExport()`）；要图请自己截屏。

### 10.5 错误码

message 一律以 `[<码>] ` 开头，取码用正则 `\[(E_HOMESTAY_[A-Z]+)\]`：

| 码 | 含义 | 怎么办 |
|---|---|---|
| `E_HOMESTAY_ARGS` | 参数不合法（越界、枚举错、区名对不上、问数题面长度不对） | 不发请求；按提示改参数 |
| `E_HOMESTAY_DOWN` | 连不上后端（含端口不对） | 按第 2 节起后端；确认插件 `baseUrl` 与实际端口一致。提示按插件配置的端口给出启动命令 |
| `E_HOMESTAY_TIMEOUT` | GET 超过 8 秒 / 问数超过 120 秒 | 稍后重试 |
| `E_HOMESTAY_LLM` | 问数后端 503，模型不可达 | 只有 `homestay_ask` 会中；查 `LLM_BASE_URL`、`LLM_MODEL`、`LLM_API_KEY` |
| `E_HOMESTAY_HTTP` | 后端返回非 2xx 或响应缺字段（比如旧后端缺 `adr_prev_year`） | 看提示里的字段名；重启本存档点后端 |

## 11 单元四怎么验收（基础版）

判据还是老样子：只看不变量，不看文案。这一版给的是“控制台/接口导出 + 人眼”，**没有**随包的自动截图工具。

1. **工具能注册、能返回**：新会话里让模型调一次工具，对话里出现工具调用；宿主没有卡片槽位时（第二档验收），也应看到结构化结果与文字表格。
2. **数字与接口一致**：用 10.4 的 `__test.createTools` 把同一个参数跑一遍，导出 `presentationMeta`；或在控制台用 `window.__cardExport()` 直接取卡片数据；再用浏览器或 `curl` 打同一个接口，两者按口径表逐项对（比率 0–1、百分点差、变化率、四舍五入位数）。
3. **只发只读白名单**：注入记录用的 `fetch`，跑 4 个工具，把发出的 URL 全列出来——应当只有 `/api/districts`、`/api/trend`、`/api/communities`、`/api/ask` 四个，方法只有 GET 与那一个 POST。
4. **后端停了报明确错误**：停掉后端再调一次，应当看到 `E_HOMESTAY_DOWN`，而不是白屏或空卡片。
5. **业务库没被写**：工具跑一圈前后，`data/homestay.db` 的大小与 SHA-256 不变。
6. **卡片是人眼验收**：颜色、刻度、标题与副标题看得过去；“刷新页面后卡片还在”这类要人眼看，脚本不代判。
