# 民宿托管经营系统 · 单元三收尾的一种参考实现（两规则版）

这套代码对应课程单元三（巡检 Agent）收尾时的一种做法：城市经营看板 + 问数面板 + 小区地图（单元一、二的成果原样保留）+ 巡检 Agent（本单元新增）。

它是**参考实现，不是标准答案**。规则编号、参数取值、建议措辞、界面文案都可以和你做出来的不一样；验收只看不变量（判定权与执行权分开、预览后才落表、没人批准改不了数据、幅度不超上限、建议能回查证据与规则编号）。

巡检 Agent 这一版只做两条规则：

- **N-01** 不调价情形里以房东关房为条件的那一条：房东关房导致成交少时，不给降价建议；
- **P-01** 单次调价幅度上限：一次调价不超过上限，超了拒绝并给出规则编号与允许范围。

其余规则类别本版没有实现，页面、接口、审批流程在没有它们时照常工作（第 5 节）。

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
| `docs/运营手册.md`、`docs/指标口径表.md` | 规则与口径的来源 |

## 9 校正过的几处

- 模型接口地址与模型名只从配置读，代码里不留默认值：没配就走规则模式，不会连到别人的服务上。
- 提示词里举例不再点具体区名，改成“按问句里的区名原样写”。
- 本 README 只写启动、规则、参数、审批与运营库；数据生成方式、验收判据、试跑记录见课程材料。
