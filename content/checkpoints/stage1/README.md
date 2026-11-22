# 城市经营看板（阶段一存档点）

这是课程单元一结束时的一种参考实现，不是标准答案。同样的需求可以有别的目录结构、别的图表库、别的接口切分方式；这里给的是“跑得起来、数字能回源、图表能导出”的一版，用来对照自己做的看板，或者在自己卡住时拆开看某个视角是怎么取数的。

页面有六个视角：经营状态（四个指标卡）、月度趋势、各区入住率对比、结构（渠道订单占比与房型结构）、价格分布、房源分布；联动入口有三个：右上角的区域选择器、点对比图里的柱子、点房源分布里的散点。选定一个区后，除对比图外的视角都按所选区重新取数——对比图不收缩，只把选中的区高亮。对比图里“本期”与“上年同期”是两根并列柱，两柱之间的缝隙很窄，点在中缝上可能点不中，这时点柱体本身（或点区名）就行。

## 1 目录

| 路径 | 内容 |
|---|---|
| `app/main.py` | FastAPI 入口：`GET /` 页面与 7 个 JSON 接口，参数非法返回 422 |
| `app/queries.py` | 数据层：只读连接、启动时一次性算好全部聚合结果 |
| `app/templates/index.html` | 页面模板（DOM 锚点、区块标题与指标卡） |
| `app/static/js/dashboard.js` | 取数、绘图、区级联动、竞态处理 |
| `app/static/js/chart_export.js` | 图表导出窗口 `window.__chartExport()`，见第 4 节 |
| `app/static/css/dashboard.css` | 样式 |
| `app/static/vendor/` | 本地化的 ECharts 5.5.1 及其 Apache-2.0 `LICENSE` / `NOTICE` |
| `docs/` | 指标口径表、运营手册（课程数据包里的同一份文档） |
| `data/` | 数据库放在这里，见第 2 节；库文件不进版本库 |

## 2 启动

前提：Python 3.12，并已经有课程数据包里的库文件（数据包在 `v2/kit/`，库在 `v2/kit/db/homestay.db`，是按只读方式使用的同一份数据）。把库复制成存档点根目录下的 `data/homestay.db`——文件名和目录都要一致，`.gitignore` 已忽略 `data/*.db`。

在存档点根目录执行（Windows）：

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8801
```

macOS / Linux 把中间两行换成 `.venv/bin/python -m pip install -r requirements.txt` 与 `.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8801`。已经装了 `uv` 的话，也可以用 `uv venv --python 3.12` 加 `uv pip install -r requirements.txt` 建环境。

打开 <http://127.0.0.1:8801/>。启动时会先把全部聚合算进内存（约 1 秒），之后每个接口直接返回缓存。

**端口被占用时换一个空闲端口。** 缺省端口是 8801。启动报“端口已被占用”，或者浏览器里打开的不是这个看板，就换一个端口：

```powershell
# 先查：没有任何输出，说明 8802 空闲
Get-NetTCPConnection -LocalPort 8802 -State Listen -ErrorAction SilentlyContinue
# 再把启动命令里的 --port 8801 换成 --port 8802
.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8802
```

浏览器地址同步换成 <http://127.0.0.1:8802/>；本页后面凡是写到 8801 的地方（打开地址、确认端口释放的命令）都按新端口改。其余步骤不变。

停止：启动窗口按 `Ctrl+C`，再用 PowerShell 确认端口已释放（换了端口就把 8801 改成新端口）：

```powershell
(Get-NetTCPConnection -LocalPort 8801 -State Listen -ErrorAction SilentlyContinue | Measure-Object).Count   # 应为 0
```

启动命令必须在存档点根目录执行：数据库路径写的是相对路径 `data/homestay.db`。

- 库只以 `sqlite3.connect("file:data/homestay.db?mode=ro", uri=True)` 打开，不写库、不建表、不生成任何库文件；想自证这一点，比对启动前后的库文件指纹（SHA-256，用课程材料 `v2/lab/tools/db_fingerprint.py`）即可。
- 依赖只有 `requirements.txt` 里的 14 个 Python 包，没有前端构建链；ECharts 已本地化，页面只请求 127.0.0.1。
- 这一版不需要任何环境变量、密钥或外部服务，也不调用任何模型接口。

## 3 接口

| 接口 | 参数 |
|---|---|
| `GET /api/meta` | — |
| `GET /api/kpi` | `district`（空 = 全公司，或 `D01`–`D08`） |
| `GET /api/trend` | `district` |
| `GET /api/compare` | `start`、`end`（缺省 `2026-07-01`、`2026-09-30`；须满足 `2024-10-01 ≤ start ≤ end ≤ 2026-09-30`） |
| `GET /api/structure` | `district` |
| `GET /api/distribution` | `district` |
| `GET /api/geo` | `district` |

## 4 导出图表与关键数字

页面加载完成（或切完区）后，在浏览器控制台执行：

```javascript
copy(JSON.stringify(await window.__chartExport()))
```

粘到编辑器里存成 `export.json`，供验收脚本与自写参考 SQL 对账。返回对象：

| 字段 | 内容 |
|---|---|
| `page` | 固定 `dashboard` |
| `filters` | 当前筛选状态，`{"district": "全公司"}` 或区名 |
| `kpis` | 四个指标卡：`id` 为 `occupancy_latest`、`adr_latest`、`revpar_latest`、`rating_latest`；`value` 是渲染时的数值，`label` 是页面显示文字 |
| `charts` | 六个图表对象：`id`（`trend`、`compare`、`channel`、`roomtype`、`distribution`、`geo`）、`title` 区块标题、`series` 系列数组，点结构为 `{x, value, label}`；每张图的系列名和点的含义见下表 |

### 图表 id 与系列名

用存档点验收时，`ref.sql` 的段头和系列名要照下表写，不是单元一示范需求里的 id（例如示范里的 `district_yoy` 在这里叫 `compare`）。系列名要逐字一致，包括括号。

| 图表 id | 视角 | 系列名 | 点的 `x` | 点的 `value` | 选区后 |
|---|---|---|---|---|---|
| `trend` | 月度趋势 | `入住率`、`平均房价` | 年月 | 入住率为 0 到 1 的小数；平均房价为元 | 按所选区重取 |
| `compare` | 各区入住率对比 | `本期`、`上年同期`、`市场基准（简单平均）` | 区名，固定 8 个区 | 入住率，0 到 1 的小数 | **不变**，仍是 8 个区 |
| `channel` | 渠道订单占比 | 每个渠道一个系列，系列名就是渠道名 | 季度（如 `2025Q3` 的写法） | 占比，0 到 1 的小数 | 按所选区重取 |
| `roomtype` | 房型结构 | 一个系列 `房型占比` | 房型名 | **在线房源套数**（不是占比；饼图扇区上显示的百分比在 `label` 里） | 按所选区重取 |
| `distribution` | 价格分布 | `最小值`、`下四分位`、`中位数`、`上四分位`、`最大值` 五条系列 | 房型名 | 每晚价，元 | 按所选区重取 |
| `geo` | 房源分布 | 每个区一个系列，系列名就是区名 | 房源编号 | 纬度 | 按所选区重取 |

四张指标卡 `occupancy_latest`、`adr_latest`、`revpar_latest`、`rating_latest` 也按所选区重取。

### 选区后，哪些图会变

在页面上点选一个区（点对比图的柱子或区名、点房源分布里的点，或用右上角的区域选择器），`filters` 里的 `district` 就从 `全公司` 变成区名，指标卡、`trend`、`channel`、`roomtype`、`distribution`、`geo` 跟着变。**`compare` 不随选区收缩**：它本来就是 8 个区并列，选中的区只是高亮，导出里仍是 8 个区、数值与选区前相同。

选区对账（单元一第 4 章）的 `ref_d08.sql` 因此这样写：指标卡对应的 `kpi` 段和 `trend`、`roomtype` 加区条件；`compare` 段原样保留 8 个区，不加区条件。最小段清单见《ref_sql写法_单元一》第 6 节。再点一次同一个区回到全公司，导出应与最初那一份一致。

存档点的 `roomtype` 点值是套数，参考 SQL 要按套数写，段头写 `-- unit: other`：

```sql
-- chart: roomtype
-- unit: other
-- 存档点写法：一个系列“房型占比”，x 是房型名，value 是截至 2026-09-30 在线的房源套数（示例为 D08 区）
SELECT '房型占比' AS series, room_type AS x, COUNT(*) AS value
FROM listings
WHERE district_id = 'D08'
  AND online_date <= '2026-09-30'
  AND (offline_date IS NULL OR offline_date > '2026-09-30')
GROUP BY room_type
ORDER BY x;
```

### 取值来源

取值来源只有两处：图表实例的当前配置（ECharts `getOption()`）与页面节点（指标卡节点的数值属性与显示文字、区块标题、筛选控件的当前值），不重新请求接口、不转发接口返回的原始数据。切区后各视角要重新取数，导出函数会等到没有“加载中”的区块再返回，所以用 `await` 拿结果。

几个约定：

- 系列与点位直接对应画布上已经画出来的数据：折线、柱状、散点按系列导出；箱线图的每个箱体拆成 `最小值`、`下四分位`、`中位数`、`上四分位`、`最大值` 五条系列；饼图一条系列，点名作图。
- `label` 只在画布上真的显示了数值文本时才有值（饼图扇区上的百分比），其余图表的点位没有数值标签，`label` 为 `null`。
- 数值统一保留 6 位小数，用于去掉二进制浮点的尾数噪声。
- 房源分布图是经纬度散点，导出为“系列 = 区名，点 `x` = 房源编号，`value` = 纬度（4 位小数）”；导出契约每个点只有一个数值，经度没有单列，页面上悬停提示里经纬度都在。

## 5 已知的口径歧义

界面上的数字都能回源到 `docs/指标口径表.md`，但下面几处是这一版实现自己的取舍，验收时按这里写明的口径理解，别按别的口径反推：

1. **指标卡的 `value` 比页面文字更精确**：卡片渲染时把未截断的数值写在节点的 `data-value` 上，导出读这一份，所以 `value` 可能是 `0.1234` 这样的四位小数，而同一张卡片 `label` 显示 `12.3%`。四条指标卡的精度分别是：入住率 4 位小数、平均房价 2 位小数、每间可售房收入 2 位小数、平均评分 2 位小数（舍入方式为 half-up）。
2. **对比图的市场基准是简单平均**：对该区在该期间内所有市场基准行（分行型、分月）取算术平均，不按可售晚数加权。它和“自己”的加权口径不同，所以市场基准与本期两条柱子相减，只是个粗略参照。
3. **对比图不随区级筛选变化**：它固定画全公司 8 个区，选中区只把柱子与区名高亮，不改变数据；缺省区间是 2026 年三季度（数据截止日所在季）对上年同期。
4. **价格分布的须线是最小值与最大值**：箱线图按最小、下四分位、中位数、上四分位、最大五个数画，没有按 1.5 倍四分位距剔除异常值。
5. **趋势图画了入住率与平均房价两条线**：每间可售房收入与平均评分在数据里、也在这张图的悬停提示里，但没有单独画线，导出也只含画出来的两条系列。
6. **结构视角两处口径**：渠道订单占比含取消单（口径表 M-10 允许，但要求注明），按订单入住月归属到季度；房型结构是截至 2026-09-30 仍在线的房源数。
7. **评分样本不足**：当月有效评分少于 5 条时，页面显示“样本不足”，导出里 `value` 为 `null`、`label` 保留页面文字；本次数据下全公司当月不是这种情况，换成某个区、某个时间窗可能出现。
8. **评分的“当月”按评论日期归属**：平均评分按评论日期（`reviews.review_date`）所在月份统计，不按评论所属订单的入住日；与单元一示范需求的裁定一致。两种归法的结果一般不同，自己写参考 SQL 时要照这一条。
9. **比例的四舍五入**：库内中间结果按 half-up 保留 4 位小数（金额与评分 2 位），页面按 1 位小数百分比展示，展示值可能与精确值相差最多 0.05 个百分点。
