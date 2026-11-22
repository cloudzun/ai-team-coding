"""给模型看的上下文，按用途分档。

- `sql_system_prompt(question)`：写 SQL 用。只给相关表 + 列 + 分类字段取值 + **被问到的**口径条目，
  目标单次调用 ≤8s。
- `answer_system_prompt()`：成文用。给完整口径表（提问者看到结论时要能对上口径），目标 ≤15s。

所有取值启动时从库里读一次并缓存；提示词里不写任何具体答案数值或业务线索。
"""
from __future__ import annotations

import re
import sqlite3
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "homestay.db"
METRICS_DOC = ROOT / "docs" / "指标口径表.md"

TABLE_ORDER = [
    "listings",
    "districts",
    "bookings",
    "reviews",
    "owners",
    "owner_blocks",
    "price_history",
    "market_benchmark",
    "meta",
]

# 任何经营问题都绕不开的三张表
CORE_TABLES = ("listings", "districts", "bookings")

# 额外表：命中关键词才给
EXTRA_TABLES = (
    ("reviews", ("评论", "评分", "抱怨", "住客", "评价", "说什么", "差评", "口碑")),
    ("market_benchmark", ("市场", "基准", "均价", "行情")),
    ("owner_blocks", ("关房", "可售", "空置", "自住", "维修")),
    ("price_history", ("调价", "挂牌", "当前价", "价格历史")),
    ("owners", ("房东", "业主")),
    ("meta", ("数据范围", "口径版本")),
)

# 分类字段：命中才注入（districts 永远给）
ENUM_BY_TABLE = {
    "bookings": (
        ("status", ("订单", "完成", "取消", "入住率", "收入", "晚")),
        ("channel", ("渠道", "占比", "平台")),
    ),
    "listings": (
        ("room_type", ("房型", "房价", "价格", "结构")),
    ),
    "owner_blocks": (
        ("reason", ("关房", "可售", "空置", "自住", "维修")),
    ),
}

# 口径条目：命中关键词才带上（C-05/C-06/C-07 永远带）
METRIC_KEYS = {
    "C-01": ("晚数", "订单", "入住", "成交"),
    "C-02": ("月", "归属", "同比", "环比"),
    "C-03": ("在线", "房源", "关房", "可售", "上线"),
    "C-04": ("关房", "可售", "空置"),
    "C-05": ("完成", "订单", "收入", "入住", "房价", "成交"),
    "C-06": ("比例", "百分", "占比", "入住率", "变化", "涨", "降"),
    "C-07": ("时间", "范围", "期间", "月", "季", "半年"),
    "M-01": ("可售", "入住率", "关房", "空置"),
    "M-02": ("成交", "入住率", "晚"),
    "M-03": ("入住率", "入住"),
    "M-04": ("房价", "平均房价", "价格", "adr"),
    "M-05": ("收入", "revpar", "每间可售"),
    "M-06": ("取消",),
    "M-07": ("评分", "评价", "口碑"),
    "M-08": ("评分", "子评分", "清洁", "沟通", "位置", "性价比"),
    "M-09": ("市场", "基准", "差距"),
    "M-10": ("渠道", "占比"),
    "M-11": ("在线", "房源", "多少套", "数量"),
    "T-01": ("空置", "关房"),
    "T-02": ("价格", "挂牌", "当前价"),
    "T-03": ("同比", "下降", "上升", "涨", "降", "变化"),
    "T-04": ("环比",),
}
ALWAYS_METRICS = ("C-05", "C-06")
_ROW_RE = re.compile(r"^\|\s*([CMT]-\d\d)\s*\|")
OCCUPANCY_KEYS = ("入住率", "入住", "可售", "空置", "关房")
TWO_PERIOD_KEYS = ("同比", "上年", "去年", "两期", "同期", "下降", "上升", "涨", "变化", "对比")

TWO_PERIOD_SKELETON = """# 两期同比的骨架（照抄，只填日期与区：<s1>/<e1> 上期，<s2>/<e2> 本期，<district_id> 换成问题里那个区的 id）
WITH RECURSIVE p1(d) AS (SELECT '<s1>' UNION ALL SELECT date(d,'+1 day') FROM p1 WHERE d < '<e1>'),
               p2(d) AS (SELECT '<s2>' UNION ALL SELECT date(d,'+1 day') FROM p2 WHERE d < '<e2>'),
sell AS (
  SELECT l.listing_id, 'prev' AS period, COUNT(*) AS n FROM listings l JOIN p1 d
    ON d.d >= l.online_date AND (l.offline_date IS NULL OR d.d < l.offline_date)
  WHERE l.district_id = '<district_id>' AND NOT EXISTS (SELECT 1 FROM owner_blocks b
        WHERE b.listing_id = l.listing_id AND d.d BETWEEN b.start_date AND b.end_date)
  GROUP BY l.listing_id
  UNION ALL
  SELECT l.listing_id, 'cur', COUNT(*) FROM listings l JOIN p2 d
    ON d.d >= l.online_date AND (l.offline_date IS NULL OR d.d < l.offline_date)
  WHERE l.district_id = '<district_id>' AND NOT EXISTS (SELECT 1 FROM owner_blocks b
        WHERE b.listing_id = l.listing_id AND d.d BETWEEN b.start_date AND b.end_date)
  GROUP BY l.listing_id
), sold AS (
  SELECT l.listing_id, 'prev' AS period, SUM(b.nights) AS nights, SUM(b.total_amount) AS amount
  FROM bookings b JOIN listings l ON l.listing_id = b.listing_id
  WHERE b.status='完成' AND b.checkin_date BETWEEN '<s1>' AND '<e1>' GROUP BY l.listing_id
  UNION ALL
  SELECT l.listing_id, 'cur', SUM(b.nights), SUM(b.total_amount)
  FROM bookings b JOIN listings l ON l.listing_id = b.listing_id
  WHERE b.status='完成' AND b.checkin_date BETWEEN '<s2>' AND '<e2>' GROUP BY l.listing_id
)
SELECT s.period, ROUND(1.0 * SUM(COALESCE(so.nights,0)) / SUM(s.n), 4) AS occupancy,
       ROUND(1.0 * SUM(COALESCE(so.amount,0)) / SUM(COALESCE(so.nights,0)), 2) AS adr
FROM sell s LEFT JOIN sold so ON so.listing_id = s.listing_id AND so.period = s.period
GROUP BY s.period;"""


def _connect() -> sqlite3.Connection:
    return sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True)


def _quote(values: list) -> str:
    return "、".join(f"'{v}'" for v in values)


@lru_cache(maxsize=1)
def table_columns() -> dict[str, str]:
    """{表名: "列名 类型, ..."}"""
    con = _connect()
    try:
        out = {}
        for name in TABLE_ORDER:
            cols = con.execute(f"PRAGMA table_info({name})").fetchall()
            out[name] = ", ".join(f"{c[1]} {c[2]}" for c in cols)
        return out
    finally:
        con.close()


@lru_cache(maxsize=1)
def all_enums() -> dict[tuple[str, str], list[str]]:
    con = _connect()
    try:
        out = {}
        fields = [("bookings", "status"), ("bookings", "channel"),
                  ("listings", "room_type"), ("owner_blocks", "reason"),
                  ("districts", "name")]
        for table, column in fields:
            rows = con.execute(
                f"SELECT DISTINCT {column} FROM {table} WHERE {column} IS NOT NULL ORDER BY 1"
            ).fetchall()
            out[(table, column)] = [r[0] for r in rows]
        return out
    finally:
        con.close()


@lru_cache(maxsize=1)
def district_pairs() -> list[tuple[str, str]]:
    con = _connect()
    try:
        return con.execute("SELECT district_id, name FROM districts ORDER BY district_id").fetchall()
    finally:
        con.close()


@lru_cache(maxsize=1)
def date_range() -> tuple[str, str, str]:
    con = _connect()
    try:
        meta = dict(con.execute("SELECT key, value FROM meta"))
    finally:
        con.close()
    text = meta.get("date_range", "")
    first, last = "2023-10-01", "2026-09-30"
    if "至" in text:
        left, right = [x.strip() for x in text.split("至", 1)]
        if left:
            first = left
        if right:
            last = right
    return first, last, text


@lru_cache(maxsize=1)
def metrics_doc() -> str:
    try:
        return METRICS_DOC.read_text(encoding="utf-8")
    except OSError:
        return "（指标口径表读取失败，按常识口径作答并在回答里说明口径。）"


@lru_cache(maxsize=1)
def _metrics_doc_parts() -> dict[str, object]:
    """把口径表拆成：条目行 dict、第 4 节参考写法片段。"""
    rows: dict[str, str] = {}
    reference = ""
    lines = metrics_doc().splitlines()
    for idx, line in enumerate(lines):
        stripped = line.strip()
        match = _ROW_RE.match(stripped)
        if match:
            rows[match.group(1)] = stripped
        if stripped.startswith("## 4"):
            reference = "\n".join(lines[idx:]).strip()
            break
    return {"rows": rows, "reference": reference}


# ---------------------------------------------------------------- 选片
def tables_for(question: str) -> list[str]:
    names = list(CORE_TABLES)
    for name, keys in EXTRA_TABLES:
        if name not in names and any(k in question for k in keys):
            names.append(name)
    if "owner_blocks" not in names and any(k in question for k in OCCUPANCY_KEYS):
        names.append("owner_blocks")  # 区间入住率的参考写法要用它
    return names


def _schema_text(tables: list[str]) -> str:
    cols = table_columns()
    order = [t for t in TABLE_ORDER if t in tables]
    return "\n".join(f"- {t}({cols[t]})" for t in order)


def _enum_text(question: str, tables: list[str]) -> str:
    lines = []
    for table, fields in ENUM_BY_TABLE.items():
        if table not in tables:
            continue
        for column, keys in fields:
            if any(k in question for k in keys):
                lines.append(f"- {table}.{column}：{_quote(all_enums()[(table, column)])}")
    if "districts" in tables:
        lines.append("- districts.district_id 与 name：" + "、".join(f"{a}={b}" for a, b in district_pairs()))
    if "reviews" in tables:
        lines.append("- reviews.rating 是 1–5 的整数，低分评论一般指 rating ≤ 4")
    return "\n".join(lines)


def _metrics_text(question: str) -> str:
    parts = _metrics_doc_parts()
    rows: dict[str, str] = parts["rows"]  # type: ignore[assignment]
    picked = []
    for code, line in rows.items():
        keys = METRIC_KEYS.get(code, ())
        if code in ALWAYS_METRICS or any(k in question for k in keys):
            picked.append(line)
    return "\n".join(picked)


# ---------------------------------------------------------------- 写 SQL 用（小档）
@lru_cache(maxsize=64)
def sql_system_prompt(question: str) -> str:
    first, last, text = date_range()
    tables = tables_for(question)
    reference = ""
    if any(k in question for k in OCCUPANCY_KEYS):
        reference = "\n\n# 区间入住率的算法（照第 4 节参考写法改：按天展开 → 扣 owner_blocks → 只计在线期间；成交晚数用 bookings.nights 按入住日归属）\n" + str(_metrics_doc_parts()["reference"])
    if any(k in question for k in TWO_PERIOD_KEYS):
        reference += "\n\n" + TWO_PERIOD_SKELETON
    return f"""你是民宿托管公司的经营数据助手，只能读库、不能改数据。数据范围 {first} 至 {last}，"{'当前 / 截至'}"一律指 {last}。

# 相关表
{_schema_text(tables)}

# 分类字段取值（只能用这些）
{_enum_text(question, tables)}

# 口径（只看这几条）
{_metrics_text(question)}{reference}

# SQL 规则
- 只写 SELECT / WITH；不写 INSERT / UPDATE / DELETE / DROP / ALTER / CREATE / REPLACE / ATTACH / PRAGMA；只查上面列出的表。
- 单条执行上限 5 秒、200 行；区间超过 3 个月先聚合，不要 select 明细。
- 一个指标一列一个数：要写进回答的指标，SQL 里就用 AVG / SUM / COUNT 聚合出单值。
  不要把同一个指标按房型或按月展开成多行；市场基准用 AVG(occupancy_rate)、AVG(avg_price) 直接返回一个数。
- 比例类结果列一律用 0–1 小数，SQL 里不要乘 100。
- 评论类问题用一条 JOIN 一次拿全：SELECT r.review_id, r.listing_id, l.community, r.review_date, r.rating, r.content
  FROM reviews r JOIN listings l ON l.listing_id = r.listing_id WHERE <条件> LIMIT 20。
- 两期对比：两个区间各自展开日期再 UNION ALL，不要用一个跨两段的日期范围加 CASE WHEN 分组。
- 问"为什么上升 / 下降"却没指明基准时，按同比与上年同期比，两期数据都要取到；判断"是不是市场都不好"要同时取市场基准两期值。

# 输出
只输出一个 JSON 对象，不要解释、不要代码围栏：
- 一条 SQL 能回答：{{"mode":"query","sql":"SELECT ..."}}
- 需要多步或评论证据：{{"mode":"diagnose","steps":[{{"purpose":"这步看什么","sql":"SELECT ..."}}]}}（最多 4 步，通常 1–2 步）
- 要求改 / 删数据或非查询操作：{{"mode":"refused","reason":"一句话"}}"""


# ---------------------------------------------------------------- why 类写 SQL 用（极简档）
@lru_cache(maxsize=64)
def why_sql_prompt(question: str = "") -> str:
    """因果类问题的写 SQL 提示：只给表结构 + 两期骨架 + 三条规则（不给口径条目全文）。"""
    first, last, _ = date_range()
    cols = table_columns()
    wanted = ("listings", "districts", "bookings", "market_benchmark", "owner_blocks")
    schema = "\n".join(f"- {t}({cols[t]})" for t in wanted)
    return f"""你是民宿托管公司的经营数据助手，只能读库。数据范围 {first} 至 {last}，"截至"指 {last}。

# 表
{schema}

{TWO_PERIOD_SKELETON}

# 规则
1. 一个指标一列一个数：入住率 = 成交晚数 / 可售晚数，平均房价 = 完成订单金额 / 完成晚数；
   市场基准用 AVG(occupancy_rate)、AVG(avg_price) 直接出单值，不要按房型或按月展开成多行。
2. 只输出一条 SQL 文本：不要解释、不要注释、不要代码围栏、不要 JSON。
3. 只写 SELECT / WITH，只能查上面这几张表。"""


# ---------------------------------------------------------------- 成文用（全档）
@lru_cache(maxsize=1)
def _full_context() -> str:
    first, last, text = date_range()
    enums = []
    for table, column in (("bookings", "status"), ("bookings", "channel"),
                          ("listings", "room_type"), ("owner_blocks", "reason")):
        enums.append(f"- {table}.{column}：{_quote(all_enums()[(table, column)])}")
    enums.append("- districts.district_id 与 name：" + "、".join(f"{a}={b}" for a, b in district_pairs()))
    return f"""# 数据库（SQLite，只读，9 张业务表）
{_schema_text(list(TABLE_ORDER))}

# 分类字段的全部取值
{chr(10).join(enums)}

# 数据时间范围
{text}（即 {first} 至 {last}）；"当前 / 截至"一律指 {last}。

# 指标口径（公司内部口径表全文）
{metrics_doc()}"""


@lru_cache(maxsize=1)
def answer_system_prompt() -> str:
    return f"""你是一名民宿托管公司的经营数据助手。你只根据"问题 + 实际执行的 SQL + 结果行"作答，不许引入结果里没有的事实。

{_full_context()}

# 成文规则
- 第一句直接给出问题所问的指标值，再补一到两句解释，像运营同事汇报，不要罗列 SQL。
- 回答里的每个数字都必须是结果行里的某个值、某一行行数，或同一列两个值的差 / 比值变化；宁可少写一个数字，也不要写不可追溯的数字。
- **一个指标只给一个数**：不许写成区间（如"78%–79%"）、不许写"约 X 到 Y"、不许用"六成""三分之一"这类概数。
  如果结果行里同一指标被拆成多行（按房型 / 按月），不要自己心算平均，只引用 SQL 已经算好的汇总列；没有汇总列就说明是按房型拆开，并只引用其中一行的值。
- 结果列是 0–1 小数比例（列名含 occupancy / rate / share / pct / ratio）时，乘 100 写成一位小数的百分数（四舍五入，不要截断）；两期之差写成"个百分点"。金额取整到元，评分保留两位小数。
- 两个不同列之间的差值必须在 SQL 里算成结果列再写，不要自己心算。
- 小于 10 的计数不要写具体条数（写成"若干条"），这类小整数在口径上不可追溯；大于等于 10 的计数可以直接写。
- 回答里的数字优先照抄给你的"建议写法"清单。
- 涉及评论的结论必须写出评论编号（review_id，如 R000123），且该编号必须出现在某一步结果行的 review_id 列里。
- 只要某一步结果行含 review_id 列，回答里就必须至少点名 3 条评论编号（各自一句话说明它支持哪个主题），且只点名结果行里真实存在的编号；不足 3 条时优先多引，不要只给概括。
- 结论要区分"数据显示了什么"和"可能的原因"。
- 月份一律写成"2025 年 12 月"这种形式，不要写成 2025-12 / 2025/12（那种写法里的数字对不上口径）。
- 不用 Markdown：不要 | 表格、不要行首 #、不要 ** 加粗、不要代码块。
- query 模式 ≤200 字；diagnose 模式 ≤400 字。

# 输出（只输出一个 JSON 对象，不要解释、不要代码围栏）
- query：{{"answer":"...","citation_ids":[]}}
- diagnose：{{"answer":"...","citation_ids":["R000123"],
  "findings":[{{"statement":"一句结论","evidence":[{{"step":1}},{{"review_id":"R000123"}}]}}],
  "suggestions":[{{"action":"建议做什么","rationale":"为什么","evidence":[{{"step":2}}]}}]}}
- findings 2–3 条（不要更多），每条都要有 evidence（步号是 1 起的整数，评论用 review_id）；suggestions 最多 2 条。
- 至少一条 finding 同时写出"具体区名（按问句里的区名原样写）"和"市场"两个字，把自身表现与市场基准摆在一起对比。"""
