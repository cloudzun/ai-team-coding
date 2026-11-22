# ref.sql 写法 · 单元一 数据看板

`ref.sql` 是分析角色自己写的参考 SQL，用来算出“页面上的数应该是多少”。检查脚本读它、只读地跑它，再和页面导出的数据逐点对。这份文档讲分段写法，并给一个完整可运行的示例。

## 1 约定

- 一个文件放多段查询。每段前面一行注释声明对应的对象：`-- chart: <id>` 或 `-- kpi: <id>`。`<id>` 要和导出数据里的对象 id 一致。
- `chart` 段返回三列，列名顺序固定：`series`（系列名）、`x`（横轴类目）、`value`（数值）。
- `kpi` 段返回一行一列：`value`。
- 可选项写在段头注释里：`-- unit: ratio` 或 `money` 或 `other` 指明数值的类别，决定用哪把容差；`-- tol: 0.005` 为这一段单独指定容差。
- 只读：文件里出现 INSERT、UPDATE、DELETE、CREATE、DROP、ALTER、ATTACH、REPLACE、PRAGMA 写法等写语句时，脚本拒绝运行。
- 默认容差：比例 0.001，金额 0.01 元。比例类的值用 0 到 1 的小数，不用百分数。
- 参考 SQL 的 `value` 与页面导出的 `value` 是同一把尺：都是 0–1 小数（比例类）或原值（金额、评分）。页面上显示的百分数文字在导出的 `label` 里，不在 `value` 里。
- 导出数据一律按渔具包里的 `导出契约.md`（课程统一导出契约）：图表点位是 `charts[].series[].points[]`，每点 `{x, value, label}`，字段名只用 `points`（不是 `data`）。形状见第 3 节示例与《示范需求_单元一》第 7 节。

## 2 一个完整示例

下面这个文件有两段：一个 `kpi` 段，一个按月入住率的 `chart` 段。窗口是 D08 区、2024-01 至 2024-06。口径全部来自指标口径表：可售晚数扣除关房并只计在线期间（M-01、C-03、C-04），成交晚数只算已完成订单并按入住日所在月份归属（M-02、C-02、C-05），入住率 = 成交晚数 ÷ 可售晚数（M-03），比例用 0 到 1 的小数（C-06）。

```sql
-- 示例：D08 区，2024-01 至 2024-06
-- 口径：指标口径表 M-01、M-02、M-03，约定 C-02、C-03、C-04、C-05

-- chart: occ_monthly
-- unit: ratio
WITH RECURSIVE days(d) AS (
  SELECT '2024-01-01' UNION ALL SELECT date(d, '+1 day') FROM days WHERE d < '2024-06-30'
),
sellable AS (
  SELECT l.listing_id, substr(days.d, 1, 7) AS ym, COUNT(*) AS sellable_nights
  FROM listings l
  JOIN days ON days.d >= l.online_date AND (l.offline_date IS NULL OR days.d < l.offline_date)
  WHERE l.district_id = 'D08'
    AND NOT EXISTS (SELECT 1 FROM owner_blocks b
                    WHERE b.listing_id = l.listing_id AND days.d BETWEEN b.start_date AND b.end_date)
  GROUP BY l.listing_id, ym
),
sold AS (
  SELECT listing_id, substr(checkin_date, 1, 7) AS ym, SUM(nights) AS sold_nights
  FROM bookings WHERE status = '完成' GROUP BY listing_id, ym
)
SELECT '本期' AS series, s.ym AS x,
       ROUND(1.0 * COALESCE(SUM(so.sold_nights), 0) / SUM(s.sellable_nights), 4) AS value
FROM sellable s LEFT JOIN sold so ON so.listing_id = s.listing_id AND so.ym = s.ym
GROUP BY s.ym
UNION ALL
SELECT '市场基准', month, ROUND(AVG(occupancy_rate), 4)
FROM market_benchmark
WHERE district_id = 'D08' AND month BETWEEN '2024-01' AND '2024-06'
GROUP BY month
ORDER BY 1, 2;

-- kpi: occupancy_window
-- unit: ratio
WITH RECURSIVE days(d) AS (
  SELECT '2024-01-01' UNION ALL SELECT date(d, '+1 day') FROM days WHERE d < '2024-06-30'
),
sellable AS (
  SELECT l.listing_id, substr(days.d, 1, 7) AS ym, COUNT(*) AS sellable_nights
  FROM listings l
  JOIN days ON days.d >= l.online_date AND (l.offline_date IS NULL OR days.d < l.offline_date)
  WHERE l.district_id = 'D08'
    AND NOT EXISTS (SELECT 1 FROM owner_blocks b
                    WHERE b.listing_id = l.listing_id AND days.d BETWEEN b.start_date AND b.end_date)
  GROUP BY l.listing_id, ym
),
sold AS (
  SELECT listing_id, substr(checkin_date, 1, 7) AS ym, SUM(nights) AS sold_nights
  FROM bookings WHERE status = '完成' GROUP BY listing_id, ym
)
SELECT ROUND(1.0 * COALESCE(SUM(so.sold_nights), 0) / SUM(s.sellable_nights), 4) AS value
FROM sellable s LEFT JOIN sold so ON so.listing_id = s.listing_id AND so.ym = s.ym;
```

### 逐段读

| 部分 | 做什么 | 对应口径 |
|---|---|---|
| `days` | 把窗口内的每一天展开成一行 | 可售晚数要按天扣除关房 |
| `sellable` | 每个房源每个月的可售晚数：在线期间内的天，扣掉落在关房区间里的天 | M-01、C-03、C-04；区间两端都包含 |
| `sold` | 每个房源每个月的成交晚数：只算已完成订单，整笔订单归到入住日所在月份 | M-02、C-02、C-05 |
| `LEFT JOIN` 加 `COALESCE` | 当月没有成交的房源，成交晚数记 0，不丢掉它的可售晚数 | 否则入住率偏高 |
| `ROUND(…, 4)` | 保留四位小数，比例用 0 到 1 的小数 | C-06；容差 0.001 之内 |
| 市场基准那一行 | 同区各房型当月 `occupancy_rate` 的简单平均 | M-09；区级市场基准为简单平均 |
| `ORDER BY 1, 2` | 先按系列名、再按横轴排序，便于人读 | 不影响比对 |

`kpi` 段重复了 `chart` 段的取数，因为每段是一条独立的语句，段与段之间不共享临时表。写完以后，用其中一段的月度结果自己心算汇总一遍，确认两段口径一致。

## 3 配一份导出数据，跑通它

页面没做出来之前，可以先手写一份导出数据，把脚本跑通。导出数据的形状见《示范需求_单元一》第 7 节。示例 `ref.sql` 对应的导出如下（`label` 是页面上实际显示的文字）：

```json
{
  "page": "demo",
  "filters": {"district": "D08"},
  "kpis": [{"id": "occupancy_window", "value": 0.6115, "label": "61.2%"}],
  "charts": [
    {
      "id": "occ_monthly",
      "title": "按月入住率：本期与市场基准",
      "series": [
        {"name": "本期", "points": [
          {"x": "2024-01", "value": 0.5512, "label": "55.1%"},
          {"x": "2024-02", "value": 0.4195, "label": "42.0%"},
          {"x": "2024-03", "value": 0.6159, "label": "61.6%"},
          {"x": "2024-04", "value": 0.6835, "label": "68.4%"},
          {"x": "2024-05", "value": 0.6736, "label": "67.4%"},
          {"x": "2024-06", "value": 0.7093, "label": "70.9%"}
        ]},
        {"name": "市场基准", "points": [
          {"x": "2024-01", "value": 0.5026, "label": "50.3%"},
          {"x": "2024-02", "value": 0.3915, "label": "39.2%"},
          {"x": "2024-03", "value": 0.5687, "label": "56.9%"},
          {"x": "2024-04", "value": 0.6218, "label": "62.2%"},
          {"x": "2024-05", "value": 0.6360, "label": "63.6%"},
          {"x": "2024-06", "value": 0.6376, "label": "63.8%"}
        ]}
      ]
    }
  ]
}
```

把示例 SQL 存成 `ref.sql`，上面的 JSON 存成 `export.json`，在仓库根目录执行（`<课程库路径>` 换成你们环境里课程数据库的路径）：

```text
python v2\lab\tools\chart_check.py --db <课程库路径> --ref ref.sql --export export.json
```

应当看到每个对象一行 PASS，末行写“全部通过”，退出码 0：

```text
[1/2] chart occ_monthly      PASS  2 个系列 / 12 个点全部对上（容差 0.001，ratio）
[2/2] kpi   occupancy_window PASS  值 0.6115 与期望一致（容差 0.001）
汇总：对象 2 个，PASS 2，FAIL 0，WARN 0；容差 比例 0.001、金额 0.01 -> 全部通过（退出码 0）
```

再做负向自检：让脚本先把两个系列名对调再比，检查必须变红，退出码为 1 才算这一步通过。

```text
python v2\lab\tools\chart_check.py --db <课程库路径> --ref ref.sql --export export.json --swap "本期,市场基准"
```

应当看到图表那一行 FAIL，并列出“超差点”，末行写“装反后有 1 个对象转红，符合预期”。

## 4 常见错误

| 现象 | 原因 | 怎么改 |
|---|---|---|
| 退出码 2，提示 SQL 出现在第一个声明之前 | 第一个 `-- chart:` 或 `-- kpi:` 之前写了 SQL | 把 SQL 挪到声明之后，之前只留注释 |
| 退出码 2，提示拒绝运行 | 段里出现写语句关键字，列名或字符串字面量不算 | 只保留 SELECT；用 `WITH` 就够了，不需要建临时表 |
| 提示 chart 段必须返回三列 | 列数不是三列 | 用 `AS series`、`AS x`、`AS value` 对齐三列 |
| 提示某系列的 x 出现了不止一次 | 分组少了一层，同一系列同一横轴出现两行 | 检查 `GROUP BY` |
| 缺系列或缺失点 | 导出里的系列名或 x 与 `ref.sql` 里的写法不一致（空格、简繁、括号） | 以 `ref.sql` 里的写法对齐 |
| 比例类的值判成金额 | 没写 `unit`，又有值大于 1 | 段头写 `-- unit: ratio`；评分这类写 `-- unit: other` |
| 提示“系列 … 的 points 不是数组” | 导出里图表点位的字段名不是 `points`（例如写成了 `data`），数字本身可能是对的 | 让页面的导出函数把字段改成 `points`；这是契约问题，不是数据问题 |
| 超差点的差值恰好差 100 倍，或 kpi 报 WARN“按百分比读作 63.7，应当显示 6370 左右” | 页面把百分数 63.7 写进了导出的 `value`，而契约要求 0–1 小数 0.637 | 让导出的 `value` 取 0–1 小数，`label` 保留“63.7%”；不要去改参考 SQL 迁就它 |
| 脚本提示导出里有未声明的对象 | 页面导出了 `ref.sql` 没有的对象 | 为它补一段，或在判据清单里写明降为人眼判据 |
| 选区对账时 `district_yoy` 报“多余点”或“缺失点” | `ref_d08.sql` 里的 `district_yoy` 段加了区条件，只剩一个区；而页面的对比图选区后仍是 8 个区 | 这一段不加区条件，原样抄全公司 `ref.sql` 里的写法，见第 6 节 |
| 评分的 kpi 段 FAIL，差在小数点后第二位 | 参考 SQL 的 `ROUND` 位数和页面导出保留的位数不一致，默认容差 0.001 容不下 | 两边约定同一位数，写进需求的口径歧义声明；或在段头写 `-- tol: 0.005` |

## 5 换成你们组自己的

- 示例的区和时间窗只用来演示写法。你们组的 `ref.sql` 要按你们需求里的窗口来写，不要拿示例的数值当期望值。
- 单元一至少写这几段：最近一期的四项指标（`kpi` 段）、按月入住率（`chart` 段）、按区的同比 `district_yoy`（`chart` 段，系列为本期、上年同期、市场基准，`x` 是区名）。有余力再补房型结构。
- 同比的计算口径看指标口径表 T-03；评分类段注意 M-07 的样本规则。
- 应用里的取数 SQL 由施工方自己写，写法可以不同，只要结果与你的 `ref.sql` 一致。是否把这一点写成判据，见《关键决策卡》卡二。
- 不确定表里有哪些字段，先看 `v2/kit/表结构说明.md`，再动手写。

### 5.1 按区的同比：`district_yoy`

本单元对比图的期间已经定了：本期取最近一期 2026Q3（2026-07-01 至 2026-09-30），上年同期取 2025Q3（2025-07-01 至 2025-09-30）。入住率是“期间总成交晚数 ÷ 期间总可售晚数”，不是三个月各自的入住率再平均（口径表 M-01 至 M-03、T-03）。市场基准取本期三个月里同区各房型 `occupancy_rate` 的简单平均（M-09）。三个系列名写成 `本期`、`上年同期`、`市场基准`，`x` 是区名，永远是 8 个区。

```sql
-- chart: district_yoy
-- unit: ratio
-- 期间：本期 2026-07-01 至 2026-09-30（2026Q3），上年同期 2025-07-01 至 2025-09-30（2025Q3）
-- 口径：M-01、M-02、M-03、M-09，约定 C-02、C-03、C-04、C-05
--   入住率 = 期间总成交晚数 ÷ 期间总可售晚数；订单按入住日整笔归属；市场基准为简单平均
WITH RECURSIVE days(d) AS (
  SELECT '2025-07-01' UNION ALL SELECT date(d, '+1 day') FROM days WHERE d < '2026-09-30'
),
period_days AS (
  SELECT d,
         CASE WHEN d BETWEEN '2026-07-01' AND '2026-09-30' THEN '本期'
              WHEN d BETWEEN '2025-07-01' AND '2025-09-30' THEN '上年同期' END AS series
  FROM days
),
sellable AS (
  SELECT l.district_id, pd.series, COUNT(*) AS sellable_nights
  FROM listings l
  JOIN period_days pd ON pd.series IS NOT NULL
                     AND pd.d >= l.online_date AND (l.offline_date IS NULL OR pd.d < l.offline_date)
  WHERE NOT EXISTS (SELECT 1 FROM owner_blocks b
                    WHERE b.listing_id = l.listing_id AND pd.d BETWEEN b.start_date AND b.end_date)
  GROUP BY l.district_id, pd.series
),
sold AS (
  SELECT l.district_id,
         CASE WHEN b.checkin_date BETWEEN '2026-07-01' AND '2026-09-30' THEN '本期'
              WHEN b.checkin_date BETWEEN '2025-07-01' AND '2025-09-30' THEN '上年同期' END AS series,
         SUM(b.nights) AS sold_nights
  FROM bookings b JOIN listings l ON l.listing_id = b.listing_id
  WHERE b.status = '完成'
    AND (b.checkin_date BETWEEN '2026-07-01' AND '2026-09-30'
         OR b.checkin_date BETWEEN '2025-07-01' AND '2025-09-30')
  GROUP BY l.district_id, series
)
SELECT s.series, d.name AS x,
       ROUND(1.0 * COALESCE(so.sold_nights, 0) / s.sellable_nights, 4) AS value
FROM sellable s
JOIN districts d ON d.district_id = s.district_id
LEFT JOIN sold so ON so.district_id = s.district_id AND so.series = s.series
UNION ALL
SELECT '市场基准', d.name, ROUND(AVG(m.occupancy_rate), 4)
FROM market_benchmark m JOIN districts d ON d.district_id = m.district_id
WHERE m.month BETWEEN '2026-07' AND '2026-09'
GROUP BY d.district_id
ORDER BY 1, 2;
```

写的时候留意三处：

- 两个期间的天数、订单都要各自落在自己的起止日里，别把两个季度混在一个 `GROUP BY` 里。
- 区名取自 `districts` 表（连接字段见《表结构说明》），页面对比图的横轴写区名，这里的 `x` 要和它逐字一致。
- 本单元的对比图用 2026Q3 对 2025Q3。你们组如果想改期间，要先在需求里改，再同步改这一段的日期。

### 5.2 房型结构：`room_type_mix`

房型结构可以照下面写：系列是房型名，`x` 是筛选范围（全公司或区名），占比用 0 到 1 的小数，口径按指标口径表 M-11 与 C-03。联动到某个区时，把区条件加进 `WHERE`，`x` 一起改成区名，写法见第 6 节。

```sql
-- chart: room_type_mix
-- unit: ratio
-- 口径：指标口径表 M-11、C-03；截至数据截止日 2026-09-30 在线房源按房型计数
WITH online AS (
  SELECT room_type FROM listings
  WHERE online_date <= '2026-09-30'
    AND (offline_date IS NULL OR offline_date > '2026-09-30')
)
SELECT room_type AS series, '全公司' AS x,
       ROUND(1.0 * COUNT(*) / (SELECT COUNT(*) FROM online), 4) AS value
FROM online
GROUP BY room_type
ORDER BY value DESC;
```

### 5.3 评分：当期怎么归属

指标口径表 M-07 写“当期评论总评分的算术平均”，约定 C-02 只规定了订单按入住日归属月份，没有规定评论按哪个日期归属。这是一个真实的口径歧义：评论日期（`reviews.review_date`）和评论所属订单的入住日（`bookings.checkin_date`）常常不在同一个月，所以两种归法算出的评分一般不同；个别窗口碰巧相同，也不能因此省掉这条裁定。

本单元的裁定（见《示范需求_单元一》第 6 节）：按评论日期落在期内来算。你们组可以裁成别的，但要写进需求，并在 `ref.sql` 的段内注释里写明，让页面照做。下面是按这条裁定写的一段示例，区仍取 D08，窗口取 2024 年 3 月一个月：

```sql
-- kpi: rating_window
-- unit: other
-- 口径：M-07。“当期”按评论日期 reviews.review_date 落在 2024-03-01 至 2024-03-31 内来算，
--       不是按评论所属订单的入住日（本需求的裁定，见《示范需求_单元一》第 6 节）。
--       空值不计；有效评分少于 5 条时页面显示“样本不足”，这一句会返回空值。
--       检查脚本遇到空值会报“值不是数字”并退出（退出码 2）：这是提醒你，样本不足的情形改成人眼判据，
--       看页面是否显示“样本不足”，不要写成数值判据。
--       小数位数与页面导出保持一致（这里保留 2 位）；位数不同，默认容差 0.001 容不下。
SELECT CASE WHEN COUNT(r.rating) >= 5 THEN ROUND(AVG(r.rating), 2) END AS value
FROM reviews r
JOIN listings l ON l.listing_id = r.listing_id
WHERE l.district_id = 'D08'
  AND r.review_date BETWEEN '2024-03-01' AND '2024-03-31';
```

## 6 选区对账：`ref_d08.sql` 最少要写哪几段

联动只改“选区后会变的对象”。选定一个区以后，指标卡、按月入住率、房型结构跟着变；按区对比图本来就是 8 个区并列，不随选区收缩，只高亮选中的区。所以选区对账用的 `ref_d08.sql`，最少要写这几段：

| 段 | 要不要加区条件 | 怎么改 |
|---|---|---|
| 四个 `kpi` 段：`occupancy_latest`、`adr_latest`、`revpar_latest`、`rating_latest` | 加 | 在 `listings` 上加 `WHERE l.district_id = 'D08'`，订单和评论都先连到 `listings` 再过滤 |
| `chart: occ_monthly` | 加 | 同上；`x` 仍是年月，不改成区名 |
| `chart: room_type_mix` | 加 | `WHERE` 里加区条件；`x` 从“全公司”改成区名 |
| `chart: district_yoy` | 不加 | 原样抄全公司 `ref.sql` 里的这一段，仍是 8 个区 |

`district_yoy` 段如果不写，脚本只对导出里的这张图报 WARN，不判红；写上才能证明联动时对比图没有被误改成单区。导出文件用选区之后的那一份（`filters` 里是区名），文件名自取，下面叫 `export_d08.json`。

下面是除 `district_yoy` 之外的六段，窗口是演示用的，你们组按自己需求里的期间改；`district_yoy` 那一段照第 5.1 节原样接在这个文件的最后。

```sql
-- 选区对账示例：D08 区。除 district_yoy 外，每段都带了 D08 的区条件。
-- 口径：指标口径表 M-01 至 M-05、M-07、M-11，约定 C-02 至 C-05

-- kpi: occupancy_latest
-- unit: ratio
WITH RECURSIVE days(d) AS (
  SELECT '2026-09-01' UNION ALL SELECT date(d, '+1 day') FROM days WHERE d < '2026-09-30'
),
sellable AS (
  SELECT COUNT(*) AS n
  FROM listings l
  JOIN days ON days.d >= l.online_date AND (l.offline_date IS NULL OR days.d < l.offline_date)
  WHERE l.district_id = 'D08'
    AND NOT EXISTS (SELECT 1 FROM owner_blocks b
                    WHERE b.listing_id = l.listing_id AND days.d BETWEEN b.start_date AND b.end_date)
),
sold AS (
  SELECT SUM(b.nights) AS n
  FROM bookings b JOIN listings l ON l.listing_id = b.listing_id
  WHERE l.district_id = 'D08' AND b.status = '完成'
    AND b.checkin_date BETWEEN '2026-09-01' AND '2026-09-30'
)
SELECT ROUND(1.0 * sold.n / sellable.n, 4) AS value FROM sellable, sold;

-- kpi: adr_latest
-- unit: money
SELECT ROUND(1.0 * SUM(b.total_amount) / SUM(b.nights), 2) AS value
FROM bookings b JOIN listings l ON l.listing_id = b.listing_id
WHERE l.district_id = 'D08' AND b.status = '完成'
  AND b.checkin_date BETWEEN '2026-09-01' AND '2026-09-30';

-- kpi: revpar_latest
-- unit: money
WITH RECURSIVE days(d) AS (
  SELECT '2026-09-01' UNION ALL SELECT date(d, '+1 day') FROM days WHERE d < '2026-09-30'
),
sellable AS (
  SELECT COUNT(*) AS n
  FROM listings l
  JOIN days ON days.d >= l.online_date AND (l.offline_date IS NULL OR days.d < l.offline_date)
  WHERE l.district_id = 'D08'
    AND NOT EXISTS (SELECT 1 FROM owner_blocks b
                    WHERE b.listing_id = l.listing_id AND days.d BETWEEN b.start_date AND b.end_date)
),
revenue AS (
  SELECT SUM(b.total_amount) AS amt
  FROM bookings b JOIN listings l ON l.listing_id = b.listing_id
  WHERE l.district_id = 'D08' AND b.status = '完成'
    AND b.checkin_date BETWEEN '2026-09-01' AND '2026-09-30'
)
SELECT ROUND(1.0 * revenue.amt / sellable.n, 2) AS value FROM sellable, revenue;

-- kpi: rating_latest
-- unit: other
-- 口径：M-07；当期按评论日期 review_date 落在期内来算（见第 5.3 节）
SELECT CASE WHEN COUNT(r.rating) >= 5 THEN ROUND(AVG(r.rating), 2) END AS value
FROM reviews r JOIN listings l ON l.listing_id = r.listing_id
WHERE l.district_id = 'D08'
  AND r.review_date BETWEEN '2026-09-01' AND '2026-09-30';

-- chart: occ_monthly
-- unit: ratio
WITH RECURSIVE days(d) AS (
  SELECT '2026-07-01' UNION ALL SELECT date(d, '+1 day') FROM days WHERE d < '2026-09-30'
),
sellable AS (
  SELECT substr(days.d, 1, 7) AS ym, COUNT(*) AS n
  FROM listings l
  JOIN days ON days.d >= l.online_date AND (l.offline_date IS NULL OR days.d < l.offline_date)
  WHERE l.district_id = 'D08'
    AND NOT EXISTS (SELECT 1 FROM owner_blocks b
                    WHERE b.listing_id = l.listing_id AND days.d BETWEEN b.start_date AND b.end_date)
  GROUP BY ym
),
sold AS (
  SELECT substr(b.checkin_date, 1, 7) AS ym, SUM(b.nights) AS n
  FROM bookings b JOIN listings l ON l.listing_id = b.listing_id
  WHERE l.district_id = 'D08' AND b.status = '完成'
    AND b.checkin_date BETWEEN '2026-07-01' AND '2026-09-30'
  GROUP BY ym
)
SELECT '入住率' AS series, s.ym AS x, ROUND(1.0 * COALESCE(so.n, 0) / s.n, 4) AS value
FROM sellable s LEFT JOIN sold so ON so.ym = s.ym
ORDER BY 2;

-- chart: room_type_mix
-- unit: ratio
WITH online AS (
  SELECT room_type FROM listings
  WHERE district_id = 'D08'
    AND online_date <= '2026-09-30'
    AND (offline_date IS NULL OR offline_date > '2026-09-30')
)
SELECT room_type AS series, (SELECT name FROM districts WHERE district_id = 'D08') AS x,
       ROUND(1.0 * COUNT(*) / (SELECT COUNT(*) FROM online), 4) AS value
FROM online
GROUP BY room_type
ORDER BY value DESC;
```

对账命令和全公司那次一样，只换文件：

```text
python v2\lab\tools\chart_check.py --db <课程库路径> --ref ref_d08.sql --export export_d08.json
```

如果用阶段一存档点验收，它导出的图表 id 和系列名与这里不同（对比图是 `compare`，房型结构是 `roomtype`），而且房型结构点的 `value` 是在线房源套数，不是占比，照存档点 README 第 4 节改段头、系列名和取数。
