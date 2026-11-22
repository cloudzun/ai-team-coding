"""问数编排：模式判定 → 写 SQL → 只读执行 → 写回答 → 可追溯/引用校验 → 模板兜底 → 日志。"""
from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime
from pathlib import Path

from app import sqlguard

from . import context, format as fmt, llm, trace

ROOT = Path(__file__).resolve().parents[2]
LOG_PATH = ROOT / "logs" / "ask.jsonl"

MAX_CALLS = 10            # 每次提问的模型调用上限（规格 1.4）
MAX_STEPS_DIAGNOSE = 4    # 规格 3.2
SQL_TIMEOUT_S = 5.0       # 规格 2.5 默认值
PROMPT_ROWS_PER_STEP = 40 # 喂给模型的每步行数（控制上下文）
PROMPT_REVIEW_ROWS = 8    # 评论步骤只喂 8 条：够引 3 条，不会把成文调用拖到 30s 超时
# 实测：这个网关把 reasoning 也计入 max_tokens——600/1000 时 content 直接为空，
# 1200 只回半截 SQL，1600 反而触发 30s 超时。所以规划 / 成文都不设上限。
PLAN_MAX_TOKENS = None
ANSWER_MAX_TOKENS = None
PLAN_TIMEOUT_DIAGNOSE = 12.0  # diagnose 的规划调用只等 12s：超时直接换确定性骨架（骨架稳定 25–30s）
DEFAULT_PERIOD_DAYS = 183     # 解析不出期间时的默认对比窗口（最近半年 vs 上年同期）
QUERY_ANSWER_LIMIT = 200
DIAGNOSE_ANSWER_LIMIT = 400
MAX_REWRITES = 1
REFUSED_ANSWER = "只能查询，不能修改数据。"

_WRITE_HINT_ZH = re.compile(
    r"(改成|改为|修改|更改|改成|删除|删掉|删去|清空|重置|新建|新增|插入|更新|写入|挂进来|挂载|建表|调价|上调|下调|涨价|降价|改价|取消|撤单|作废|删除订单|执行)"
)
_WRITE_HINT_EN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|replace|attach|detach|pragma|vacuum|reindex|truncate)\b",
    re.IGNORECASE,
)
_REVIEW_ID_RE = re.compile(r"\bR\d{6}\b")
_LOG_LOCK = threading.Lock()


class BudgetExceeded(Exception):
    """模型调用次数触顶。"""


# ---------------------------------------------------------------- 小工具
def looks_like_write(question: str) -> bool:
    return bool(_WRITE_HINT_ZH.search(question) or _WRITE_HINT_EN.search(question))


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _call(messages: list[dict], meta: dict, max_tokens: int | None = None,
          timeout: float | None = None) -> str:
    if meta["llm_calls"] >= MAX_CALLS:
        raise BudgetExceeded()
    meta["llm_calls"] += 1
    if timeout:
        return llm.chat(messages, max_tokens=max_tokens, timeout=timeout)
    return llm.chat(messages, max_tokens=max_tokens)


def _log(row: dict) -> None:
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(row, ensure_ascii=False)
        with _LOG_LOCK:
            with LOG_PATH.open("a", encoding="utf-8") as fp:
                fp.write(line + "\n")
    except OSError:
        pass


def _payload(question: str, mode: str, answer: str, steps: list[dict], citations: list[dict],
             diagnosis: dict | None, meta: dict) -> dict:
    return {
        "question": question,
        "mode": mode,
        "answer": answer,
        "steps": steps,
        "citations": citations,
        "diagnosis": diagnosis,
        "meta": meta,
    }


def _finish(result: dict, t0: float, log_steps: list[dict] | None = None) -> dict:
    meta = result["meta"]
    meta["elapsed_ms"] = int((time.monotonic() - t0) * 1000)
    result["steps"] = [_public_step(s) for s in result["steps"]]
    _log(
        {
            "ts": _now_iso(),
            "question": result["question"],
            "mode": result["mode"],
            "steps": log_steps
            if log_steps is not None
            else [{"sql": s.get("sql"), "row_count": s.get("row_count"), "error": s.get("error")} for s in result["steps"]],
            "answer": result["answer"],
            "meta": meta,
        }
    )
    return result


def _public_step(step: dict) -> dict:
    out = {
        "purpose": step.get("purpose") or "",
        "sql": step.get("sql") or "",
        "columns": step.get("columns") or [],
        "rows": step.get("rows") or [],
        "row_count": step.get("row_count", 0),
        "truncated": bool(step.get("truncated")),
        "elapsed_ms": step.get("elapsed_ms", 0),
    }
    if step.get("error"):
        out["error"] = step["error"]
    return out


# ---------------------------------------------------------------- 规划
_DIAGNOSE_HINT = re.compile(
    r"(为什么|为啥|怎么回事|问题出在哪|哪里出问题|抱怨|说什么|不满|差评|主要问题|是不是市场|整个市场"
    r"|原因|为何|怎么会|导致|因素|归因|因为什么)"
)
_WHY_HINT = re.compile(r"(为什么|为啥|怎么回事|问题出在哪|哪里出问题|是不是市场|整个市场|是否.{0,4}市场)")


def _plan_plain_sql(question: str, meta: dict, strict: bool = False, slim: bool = True,
                    timeout: float | None = None) -> dict:
    """只让它输出 SQL 文本（比 JSON 契约快很多）。"""
    tail = (
        "直接给出 SQL，不要在正文里推演。只输出 SQL 文本：不要 JSON、不要解释、不要代码围栏。"
        "优先用一条 SQL（多个 CTE / UNION ALL）把问题需要的指标一次取全；确实需要评论证据时才加第二条，"
        "两条之间用单独一行 --- 分隔。"
    )
    if strict:
        tail = "只输出一条 SQL，不要再推演、不要解释。多个 CTE 或 UNION ALL 把指标一次取全。"
    why = bool(_WHY_HINT.search(question))
    # 第 1 次用极简提示（快），第 2 次退回完整提示（成功率高）
    system = context.why_sql_prompt() if (why and slim) else context.sql_system_prompt(question)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"问题：{question}\n\n{tail}"},
    ]
    text = _call(messages, meta, timeout=timeout)
    try:  # 万一它还是给了 JSON
        data = llm.json_object(text)
        if data.get("sql"):
            return {"mode": "query", "steps": [{"purpose": "查询数据", "sql": llm.strip_code_fences(str(data["sql"]))}]}
        if data.get("steps"):
            steps = [
                {"purpose": str(s.get("purpose") or "查询数据"), "sql": llm.strip_code_fences(str(s.get("sql") or ""))}
                for s in data["steps"]
                if isinstance(s, dict) and s.get("sql")
            ][:MAX_STEPS_DIAGNOSE]
            if steps:
                mode = "diagnose" if _DIAGNOSE_HINT.search(question) else "query"
                return {"mode": mode, "steps": steps if mode == "diagnose" else steps[:1]}
    except ValueError:
        pass
    body = llm.strip_code_fences(text)
    chunks = [c.strip() for c in re.split(r"\n\s*-{3,}\s*\n", body) if c.strip()]
    steps = []
    for idx, chunk in enumerate(chunks[:MAX_STEPS_DIAGNOSE]):
        sql = llm.strip_code_fences(chunk)
        if not sql.lower().startswith(("select", "with")):
            continue
        steps.append({"purpose": "查询数据" if idx == 0 else f"补充证据 {idx}", "sql": sql})
    if not steps:
        raise ValueError("E_PLAN_FORMAT")
    mode = "diagnose" if _DIAGNOSE_HINT.search(question) else "query"
    return {"mode": mode, "steps": steps if mode == "diagnose" else steps[:1]}


# ---------------------------------------------------------------- diagnose 确定性兜底
_PERIOD_RULES = (
    ("下半年", 7, 1, 12, 31),
    ("上半年", 1, 1, 6, 30),
    ("一季度", 1, 1, 3, 31),
    ("二季度", 4, 1, 6, 30),
    ("三季度", 7, 1, 9, 30),
    ("四季度", 10, 1, 12, 31),
    ("Q1", 1, 1, 3, 31),
    ("Q2", 4, 1, 6, 30),
    ("Q3", 7, 1, 9, 30),
    ("Q4", 10, 1, 12, 31),
    ("全年", 1, 1, 12, 31),
)
_YEAR_RE = re.compile(r"(\d{4})\s*年")
_D0, _D1 = None, None  # 数据范围在运行时取


def _day(y: int, m: int, d: int) -> str:
    return f"{y:04d}-{m:02d}-{d:02d}"


def _minus_year(day: str) -> str:
    from datetime import date as _date
    value = _date.fromisoformat(day)
    try:
        return value.replace(year=value.year - 1).isoformat()
    except ValueError:
        return value.replace(year=value.year - 1, day=28).isoformat()


def _clamp(day: str, lo: str, hi: str) -> str:
    return max(lo, min(hi, day))


def _parse_district(question: str) -> tuple[str | None, str]:
    for district_id, name in context.district_pairs():
        if name in question:
            return district_id, name
    return None, "全公司"


def _parse_periods(question: str, default_days: int | None = None) -> tuple[str, str, str, str, str]:
    """返回 (本期说明, 本期起, 本期止, 基期起, 基期止)。只做日期映射，不含任何指标值。"""
    first, last, _ = context.date_range()
    year_match = _YEAR_RE.search(question)
    for word, m1, d1, m2, d2 in _PERIOD_RULES:
        if word not in question:
            continue
        year = int(year_match.group(1)) if year_match else int(last[:4])
        cur_start, cur_end = _day(year, m1, d1), _day(year, m2, d2)
        prev_start, prev_end = _minus_year(cur_start), _minus_year(cur_end)
        if cur_end < first or cur_start > last:  # 整个期间都在数据范围外 → 用默认窗口
            break
        cur_start = _clamp(cur_start, first, last)
        cur_end = _clamp(cur_end, first, last)
        prev_start = _clamp(prev_start, first, last)
        prev_end = _clamp(prev_end, first, last)
        label = f"{year} 年{word}"
        return label, cur_start, cur_end, prev_start, prev_end
    # 解析不出期间：默认窗口（规划骨架用最近半年，评论骨架用最近一季）
    from datetime import date as _date, timedelta as _timedelta
    span = default_days or DEFAULT_PERIOD_DAYS
    cur_end = _clamp(last, first, last)
    cur_start = (_date.fromisoformat(cur_end) - _timedelta(days=span)).isoformat()
    cur_start = _clamp(cur_start, first, last)
    label = "最近一季" if default_days else "最近半年"
    return label, cur_start, cur_end, _minus_year(cur_start), _minus_year(cur_end)


REVIEW_KEYS = ("评论", "评分", "抱怨", "住客", "差评", "说什么", "口碑", "不满")
_RATING_RE = re.compile(r"(?:不高于|低于|不超过|≤|<=|少于|小于)\s*(\d(?:\.\d)?)\s*分")
_SAMPLE_RE = re.compile(r"(?:不少于|不低于|至少|>=|≥)\s*(\d+)\s*条")
_ONLINE_MONTH_RE = re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月[^，。]{0,6}上线")


def _is_review_question(question: str) -> bool:
    return any(k in question for k in REVIEW_KEYS)


def _parse_rating_cap(question: str) -> float:
    for match in _RATING_RE.finditer(question):
        try:
            value = float(match.group(1))
        except ValueError:
            continue
        if 1 <= value <= 5:
            return value
    return 4.5  # 默认低分口径：rating < 4.5（运营手册 Q-01 的观察线写的是“低于”）


def _parse_min_samples(question: str) -> int:
    match = _SAMPLE_RE.search(question)
    if match:
        try:
            value = int(match.group(1))
            if 1 <= value <= 1000:
                return value
        except ValueError:
            pass
    return 5  # 默认样本门槛 5 条（运营手册 Q-05：少于 5 条只记录，不下结论）


def _prior_community(steps: list[dict]) -> str | None:
    """从前面成功的步骤里取小区名（评论骨架要用它定位到那个小区）。"""
    for step in steps:
        cols = [str(c).lower() for c in (step.get("columns") or [])]
        if "community" not in cols or step.get("error"):
            continue
        idx = cols.index("community")
        values = [str(row[idx]) for row in (step.get("rows") or []) if idx < len(row) and row[idx]]
        if len(set(values)) == 1 and values:
            return values[0]
    return None


def _review_skeleton_sql(question: str, steps: list[dict]) -> tuple[str, str]:
    """评论明细骨架：review_id / listing_id / community / review_date / rating / content，LIMIT 20。"""
    _, cur_s, cur_e, _, _ = _parse_periods(question, default_days=92)
    if not any(rule[0] in question for rule in _PERIOD_RULES):
        # 问句没指明期间：不要凭空加评论日期窗口（例如"3 月上线的那批房源的评论"可以来自任何时间）
        first_day, last_day, _ = context.date_range()
        cur_s, cur_e = first_day, last_day
    cap = _parse_rating_cap(question)
    where = [f"r.review_date BETWEEN '{cur_s}' AND '{cur_e}'", f"r.rating < {cap}", "r.rating IS NOT NULL"]

    community = _prior_community(steps)
    district_id, _ = _parse_district(question)
    needs_target = (
        not community
        and "小区" in question
        and any(k in question for k in ("最低", "最差", "最少"))
    )
    if community:
        where.append("l.community = '" + community.replace("'", "''") + "'")
    elif district_id:
        where.append(f"l.district_id = '{district_id}'")

    online = _ONLINE_MONTH_RE.search(question)
    if online:
        year, month = int(online.group(1)), int(online.group(2))
        start = f"{year:04d}-{month:02d}-01"
        end = f"{year:04d}-{month:02d}-31"
        where.append(f"l.online_date BETWEEN '{start}' AND '{end}'")

    if needs_target:
        min_n = _parse_min_samples(question)
        sql = (
            "WITH target AS (SELECT l.community AS community "
            "FROM reviews r JOIN listings l ON l.listing_id = r.listing_id "
            f"WHERE r.review_date BETWEEN '{cur_s}' AND '{cur_e}' AND r.rating IS NOT NULL "
            f"GROUP BY l.community HAVING COUNT(r.rating) >= {min_n} "
            "ORDER BY AVG(r.rating) ASC LIMIT 1), "
            "stat AS (SELECT l.community AS community, ROUND(AVG(r.rating), 2) AS avg_rating, "
            "COUNT(r.rating) AS review_count FROM reviews r JOIN listings l ON l.listing_id = r.listing_id "
            "JOIN target t ON t.community = l.community "
            f"WHERE r.review_date BETWEEN '{cur_s}' AND '{cur_e}' AND r.rating IS NOT NULL "
            "GROUP BY l.community) "
            "SELECT r.review_id, r.listing_id, l.community, r.review_date, r.rating, r.content, "
            "st.avg_rating, st.review_count "
            "FROM reviews r JOIN listings l ON l.listing_id = r.listing_id "
            "JOIN target t ON t.community = l.community "
            "JOIN stat st ON st.community = l.community WHERE " + " AND ".join(where) + " "
            "ORDER BY r.rating ASC, r.review_date DESC LIMIT 20"
        )
        scope = "评分最低的小区"
    else:
        sql = (
            "SELECT r.review_id, r.listing_id, l.community, r.review_date, r.rating, r.content "
            "FROM reviews r JOIN listings l ON l.listing_id = r.listing_id "
            "WHERE " + " AND ".join(where) + " "
            "ORDER BY r.rating ASC, r.review_date DESC LIMIT 20"
        )
        scope = community or ("该区" if district_id else "全公司")
    purpose = f"{scope} {cur_s} 至 {cur_e} 评分低于 {cap:g} 的评论明细（确定性骨架）"
    return purpose, sql


def _apply_step_fallback(question: str, steps: list[dict], force: bool = False) -> tuple[list[dict], bool]:
    """诊断步骤失败时（或整体走了规划骨架的评论类问题）补一条评论明细骨架，别让整题失败。"""
    failed = [s for s in steps if s.get("error")]
    if not failed and not force:
        return steps, False
    if not (_is_review_question(question) or any("reviews" in str(s.get("sql") or "").lower() for s in failed)):
        return steps, False
    purpose, sql = _review_skeleton_sql(question, steps)
    t0 = time.monotonic()
    try:
        result = sqlguard.run_readonly(sql, max_rows=20, timeout_s=SQL_TIMEOUT_S)
    except (sqlguard.SqlRejected, sqlguard.SqlError, sqlguard.SqlTimeout):
        return steps, False
    step = {"purpose": purpose, "sql": sql, "error": None, "elapsed_ms": int((time.monotonic() - t0) * 1000)}
    step.update(result)
    return steps + [step], True


def _skeleton_plan(question: str) -> dict:
    """规划超时 / 给不出可用 SQL 时的确定性兜底：一条参数化骨架 SQL（口径同两期骨架）。"""
    district_id, district_name = _parse_district(question)
    label, cur_s, cur_e, prev_s, prev_e = _parse_periods(question)
    cur_m, prev_m = cur_s[:7], prev_s[:7]
    cur_m_e, prev_m_e = cur_e[:7], prev_e[:7]

    sell_district = f"l.district_id = '{district_id}' AND " if district_id else ""
    sold_district = f"AND l.district_id = '{district_id}' " if district_id else ""
    market_district = f" AND district_id = '{district_id}'" if district_id else ""

    sql = f"""WITH RECURSIVE p1(d) AS (SELECT '{prev_s}' UNION ALL SELECT date(d,'+1 day') FROM p1 WHERE d < '{prev_e}'),
               p2(d) AS (SELECT '{cur_s}' UNION ALL SELECT date(d,'+1 day') FROM p2 WHERE d < '{cur_e}'),
sell AS (
  SELECT l.listing_id, 'prev' AS period, COUNT(*) AS n FROM listings l JOIN p1 d
    ON d.d >= l.online_date AND (l.offline_date IS NULL OR d.d < l.offline_date)
  WHERE {sell_district}NOT EXISTS (SELECT 1 FROM owner_blocks b
        WHERE b.listing_id = l.listing_id AND d.d BETWEEN b.start_date AND b.end_date)
  GROUP BY l.listing_id
  UNION ALL
  SELECT l.listing_id, 'cur', COUNT(*) FROM listings l JOIN p2 d
    ON d.d >= l.online_date AND (l.offline_date IS NULL OR d.d < l.offline_date)
  WHERE {sell_district}NOT EXISTS (SELECT 1 FROM owner_blocks b
        WHERE b.listing_id = l.listing_id AND d.d BETWEEN b.start_date AND b.end_date)
  GROUP BY l.listing_id
), sold AS (
  SELECT l.listing_id, 'prev' AS period, SUM(b.nights) AS nights, SUM(b.total_amount) AS amount
  FROM bookings b JOIN listings l ON l.listing_id = b.listing_id
  WHERE b.status = '完成' AND b.checkin_date BETWEEN '{prev_s}' AND '{prev_e}' {sold_district}GROUP BY l.listing_id
  UNION ALL
  SELECT l.listing_id, 'cur', SUM(b.nights), SUM(b.total_amount)
  FROM bookings b JOIN listings l ON l.listing_id = b.listing_id
  WHERE b.status = '完成' AND b.checkin_date BETWEEN '{cur_s}' AND '{cur_e}' {sold_district}GROUP BY l.listing_id
), occ AS (
  SELECT s.period, 1.0 * SUM(COALESCE(so.nights,0)) / SUM(s.n) AS occupancy,
         1.0 * SUM(COALESCE(so.amount,0)) / SUM(COALESCE(so.nights,0)) AS adr
  FROM sell s LEFT JOIN sold so ON so.listing_id = s.listing_id AND so.period = s.period
  GROUP BY s.period
)
SELECT (SELECT ROUND(occupancy,4) FROM occ WHERE period='cur')  AS occupancy_cur,
       (SELECT ROUND(occupancy,4) FROM occ WHERE period='prev') AS occupancy_prev,
       (SELECT ROUND(adr,2)       FROM occ WHERE period='cur')  AS adr_cur,
       (SELECT ROUND(adr,2)       FROM occ WHERE period='prev') AS adr_prev,
       (SELECT ROUND(AVG(occupancy_rate),4) FROM market_benchmark
         WHERE month BETWEEN '{cur_m}' AND '{cur_m_e}'{market_district}) AS market_occupancy_cur,
       (SELECT ROUND(AVG(occupancy_rate),4) FROM market_benchmark
         WHERE month BETWEEN '{prev_m}' AND '{prev_m_e}'{market_district}) AS market_occupancy_prev,
       (SELECT ROUND(AVG(avg_price),2) FROM market_benchmark
         WHERE month BETWEEN '{cur_m}' AND '{cur_m_e}'{market_district}) AS market_price_cur,
       (SELECT ROUND(AVG(avg_price),2) FROM market_benchmark
         WHERE month BETWEEN '{prev_m}' AND '{prev_m_e}'{market_district}) AS market_price_prev,
       '{cur_s} 至 {cur_e}' AS period_cur, '{prev_s} 至 {prev_e}' AS period_prev"""

    purpose = f"{district_name} {label}与上年同期：入住率 / 平均房价 / 同期市场基准（确定性骨架）"
    return {"mode": "diagnose", "fallback": True, "steps": [{"purpose": purpose, "sql": sql.strip()}]}


def _diagnose_plan(question: str) -> dict:
    """diagnose 的取数：确定性骨架，不让模型写 SQL（规格 3.2 v2.6）。"""
    steps: list[dict] = []
    numeric_keys = ("入住率", "入住", "房价", "价格", "市场", "为什么", "怎么回事", "下降", "上升", "涨")
    want_numeric = (not _is_review_question(question)) or any(k in question for k in numeric_keys)
    if want_numeric:
        steps.append(_skeleton_plan(question)["steps"][0])
    if _is_review_question(question):
        purpose, sql = _review_skeleton_sql(question, steps)
        steps.append({"purpose": purpose, "sql": sql})
    if not steps:
        steps.append(_skeleton_plan(question)["steps"][0])
    return {"mode": "diagnose", "skeleton": True, "steps": steps[:MAX_STEPS_DIAGNOSE]}


def _plan(question: str, meta: dict) -> dict:
    """diagnose 用骨架取数（0 次模型调用）；query 仍让模型写一条 SQL。"""
    if _DIAGNOSE_HINT.search(question):
        return _diagnose_plan(question)
    why = bool(_WHY_HINT.search(question))
    try:
        return _plan_plain_sql(question, meta, strict=why)
    except (llm.LLMUnavailable, ValueError):
        pass
    # query 保持原样：换完整提示再试一次
    return _plan_plain_sql(question, meta, strict=not why, slim=False)


def _plan_json(question: str, meta: dict) -> dict:
    messages = [
        {"role": "system", "content": context.sql_system_prompt(question)},
        {"role": "user", "content": f"问题：{question}\n\n请输出 JSON。"},
    ]
    for attempt in range(2):
        text = _call(messages, meta)  # 超时由 _plan 退化为"只写 SQL"，这里不再重试
        try:
            data = llm.json_object(text)
        except ValueError:
            messages = messages + [
                {"role": "assistant", "content": text},
                {"role": "user", "content": "上面的输出不是合法 JSON。只输出一个 JSON 对象，不要解释、不要代码围栏。"},
            ]
            continue
        mode = str(data.get("mode") or "").strip().lower()
        if mode == "refused":
            reason = str(data.get("reason") or "").strip()
            answer = REFUSED_ANSWER + (reason if reason and reason not in REFUSED_ANSWER else "")
            return {"mode": "refused", "answer": fmt.trim_to(answer, QUERY_ANSWER_LIMIT), "steps": []}
        if mode == "diagnose":
            raw_steps = data.get("steps") or []
            steps = []
            for item in raw_steps:
                if not isinstance(item, dict):
                    continue
                sql = llm.strip_code_fences(str(item.get("sql") or ""))
                if not sql:
                    continue
                steps.append({"purpose": str(item.get("purpose") or "查询数据").strip(), "sql": sql})
                if len(steps) >= MAX_STEPS_DIAGNOSE:
                    break
            if steps:
                return {"mode": "diagnose", "steps": steps}
        sql = llm.strip_code_fences(str(data.get("sql") or ""))
        if sql:
            return {"mode": "query", "steps": [{"purpose": "查询数据", "sql": sql}]}
        messages = messages + [
            {"role": "assistant", "content": text},
            {"role": "user", "content": "这个 JSON 里没有可执行的 SQL。请按约定重新输出。"},
        ]
    raise BudgetExceeded() if meta["llm_calls"] >= MAX_CALLS else ValueError("E_PLAN_FORMAT")


# ---------------------------------------------------------------- 执行
def _execute_step(step: dict, question: str, meta: dict) -> dict:
    purpose = step.get("purpose") or "查询数据"
    sql = step.get("sql") or ""
    out = {"purpose": purpose, "sql": sql, "columns": [], "rows": [], "row_count": 0,
           "truncated": False, "elapsed_ms": 0, "error": None}
    t0 = time.monotonic()
    error_text = None
    try:
        result = sqlguard.run_readonly(sql, max_rows=200, timeout_s=SQL_TIMEOUT_S)
        out.update(result)
        out["elapsed_ms"] = int((time.monotonic() - t0) * 1000)
        return out
    except (sqlguard.SqlRejected, sqlguard.SqlError, sqlguard.SqlTimeout) as exc:
        error_text = f"{type(exc).__name__}: {getattr(exc, 'code', '')} {exc}".strip()
        if isinstance(exc, sqlguard.SqlTimeout):
            error_text = "执行超时（超过 5 秒），SQL 需要先聚合再返回"

    # 超时不值得再花一次模型调用（30s）去"修"——诊断路径随后会用确定性骨架补一步
    timed_out = error_text.startswith("执行超时")
    fixed = None if timed_out else _repair_sql(sql, error_text, question, meta)
    if fixed and fixed.strip() != sql.strip():
        t1 = time.monotonic()
        try:
            result = sqlguard.run_readonly(fixed, max_rows=200, timeout_s=SQL_TIMEOUT_S)
            out.update(result)
            out["sql"] = fixed
            out["elapsed_ms"] = int((time.monotonic() - t1) * 1000)
            return out
        except (sqlguard.SqlRejected, sqlguard.SqlError, sqlguard.SqlTimeout) as exc:
            error_text = f"{type(exc).__name__}: {getattr(exc, 'code', '')} {exc}".strip()
    out["error"] = (error_text or "SQL 执行失败")[:300]
    out["elapsed_ms"] = int((time.monotonic() - t0) * 1000)
    return out


def _repair_sql(sql: str, error_text: str | None, question: str, meta: dict) -> str | None:
    messages = [
        {"role": "system", "content": context.sql_system_prompt(question)},
        {
            "role": "user",
            "content": (
                f"问题：{question}\n\n下面这条 SQL 执行失败了，请修正后重新给出 SQL（可以顺便改成多步，但仍受步数上限约束）。\n"
                f"SQL:\n{sql}\n\n报错：{error_text}\n\n只输出一个 JSON 对象，形如 "
                '{"mode":"query","sql":"SELECT ..."} 或 {"mode":"diagnose","steps":[...]}。'
            ),
        },
    ]
    try:
        text = _call(messages, meta)
        data = llm.json_object(text)
    except (llm.LLMUnavailable, ValueError):
        return None
    except BudgetExceeded:
        return None
    sql2 = llm.strip_code_fences(str(data.get("sql") or ""))
    if sql2:
        return sql2
    steps = data.get("steps") or []
    if isinstance(steps, list) and steps and isinstance(steps[0], dict):
        return llm.strip_code_fences(str(steps[0].get("sql") or "")) or None
    return None


def _execute_all(planned: list[dict], question: str, meta: dict) -> list[dict]:
    return [_execute_step(step, question, meta) for step in planned]


# ---------------------------------------------------------------- 写回答
CONTENT_PREVIEW = 120


def _rows_preview(step: dict) -> list:
    """喂给模型的行：评论正文只留前 120 字，控制上下文长度（成文只需要主题，不需要全文）。"""
    columns = [str(c).lower() for c in (step.get("columns") or [])]
    cut = [i for i, name in enumerate(columns) if "content" in name]
    limit = PROMPT_REVIEW_ROWS if cut else PROMPT_ROWS_PER_STEP
    rows = (step.get("rows") or [])[:limit]
    if not cut:
        return rows
    out = []
    for row in rows:
        row = list(row)
        for i in cut:
            if i < len(row) and isinstance(row[i], str) and len(row[i]) > CONTENT_PREVIEW:
                row[i] = row[i][:CONTENT_PREVIEW] + "…"
        out.append(row)
    return out


def _steps_digest(steps: list[dict]) -> str:
    parts = []
    for idx, step in enumerate(steps, 1):
        head = f"第 {idx} 步（{step.get('purpose')}）"
        if step.get("error"):
            parts.append(f"{head}\nSQL: {step['sql']}\n执行失败：{step['error']}")
            continue
        lines = [
            f"{head}",
            f"SQL: {step['sql']}",
            f"结果列: {json.dumps(step.get('columns') or [], ensure_ascii=False)}",
            f"总行数: {step.get('row_count')}（truncated={bool(step.get('truncated'))}）",
            "数据行（JSON 数组，按结果列顺序）:",
        ]
        lines.append(json.dumps(_rows_preview(step), ensure_ascii=False))
        hint = fmt.render_hint(step)
        if hint:
            lines.append("建议写法（回答里用这些写法才可追溯到结果行）:")
            lines.append(hint)
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


def _ask_answer(question: str, mode: str, steps: list[dict], meta: dict, feedback: list[str] | None = None) -> dict:
    limit = DIAGNOSE_ANSWER_LIMIT if mode == "diagnose" else QUERY_ANSWER_LIMIT
    user = (
        f"问题：{question}\n\n实际执行的 SQL 与结果：\n{_steps_digest(steps)}\n\n"
        f"请按要求输出 JSON。回答不超过 {limit} 字，不要出现结果里没有的数字。"
    )
    if feedback:
        user += "\n\n上一版回答不合格，必须修正：" + "；".join(feedback)
    messages = [
        {"role": "system", "content": context.answer_system_prompt()},
        {"role": "user", "content": user},
    ]
    last_text = ""
    for attempt in range(2):
        try:
            last_text = _call(messages, meta, max_tokens=ANSWER_MAX_TOKENS)
        except llm.LLMUnavailable:
            if attempt == 0 and meta["llm_calls"] < MAX_CALLS:
                continue
            raise
        try:
            return llm.json_object(last_text)
        except ValueError:
            messages = messages + [
                {"role": "assistant", "content": last_text},
                {"role": "user", "content": "上面的输出不是合法 JSON。只输出一个 JSON 对象。"},
            ]
    raise ValueError("E_ANSWER_FORMAT")


def _diagnosis_text(diagnosis: dict | None) -> str:
    if not diagnosis:
        return ""
    chunks = []
    for item in diagnosis.get("findings") or []:
        chunks.append(str(item.get("statement") or ""))
    for item in diagnosis.get("suggestions") or []:
        chunks.append(str(item.get("action") or ""))
        chunks.append(str(item.get("rationale") or ""))
    return " ".join(chunks)


def _available_review_ids(steps: list[dict]) -> set[str]:
    found: set[str] = set()
    for step in steps:
        columns = [str(c).lower() for c in (step.get("columns") or [])]
        if "review_id" not in columns:
            continue
        idx = columns.index("review_id")
        for row in step.get("rows") or []:
            if idx < len(row) and row[idx] is not None:
                found.add(str(row[idx]).strip())
    return found


def _cited_ids(text: str) -> list[str]:
    seen: list[str] = []
    for match in _REVIEW_ID_RE.finditer(text or ""):
        rid = match.group(0)
        if rid not in seen:
            seen.append(rid)
    return seen


def _coerce_diagnosis(raw: dict, steps: list[dict], available: set[str]) -> dict | None:
    if not isinstance(raw, dict):
        return None

    def clean_evidence(items) -> list[dict]:
        out: list[dict] = []
        for item in items or []:
            if not isinstance(item, dict):
                continue
            step_no = item.get("step")
            review_id = item.get("review_id")
            if isinstance(step_no, int) and 1 <= step_no <= len(steps):
                out.append({"step": step_no})
            elif isinstance(review_id, str) and review_id in available:
                out.append({"review_id": review_id})
        return out

    findings = []
    for item in raw.get("findings") or []:
        if not isinstance(item, dict):
            continue
        statement = fmt.sanitize_markdown(str(item.get("statement") or "")).strip()
        evidence = clean_evidence(item.get("evidence"))
        if statement and evidence:
            findings.append({"statement": statement, "evidence": evidence})
    suggestions = []
    for item in raw.get("suggestions") or []:
        if not isinstance(item, dict):
            continue
        action = fmt.sanitize_markdown(str(item.get("action") or "")).strip()
        rationale = fmt.sanitize_markdown(str(item.get("rationale") or "")).strip()
        evidence = clean_evidence(item.get("evidence"))
        if action:
            suggestions.append({"action": action, "rationale": rationale, "evidence": evidence})
    if not findings and not suggestions:
        return None
    return {"findings": findings, "suggestions": suggestions}


def _fallback_diagnosis(steps: list[dict]) -> dict:
    findings = []
    for idx, step in enumerate(steps, 1):
        if step.get("error"):
            continue
        findings.append(
            {
                "statement": f"第 {idx} 步（{step.get('purpose')}）返回 {step.get('row_count', 0)} 行结果，详见下方明细。",
                "evidence": [{"step": idx}],
            }
        )
    return {"findings": findings, "suggestions": []}


# ---------------------------------------------------------------- 引用详情
def _cell(step: dict, name: str):
    cols = [str(c).lower() for c in (step.get("columns") or [])]
    if name not in cols:
        return None
    idx = cols.index(name)
    rows = step.get("rows") or []
    if not rows or idx >= len(rows[0]):
        return None
    return rows[0][idx]


def _step_no(steps: list[dict], step: dict, column: str) -> int:
    for index, item in enumerate(steps, 1):
        if item is step:
            return index
        if column in [str(c).lower() for c in (item.get("columns") or [])]:
            return index
    return 1


def _deterministic_diagnose(question: str, steps: list[dict]) -> tuple[str, dict] | None:
    """按规格 3.6（v2.6）从骨架结果行确定性生成回答文本与 diagnosis（值与判定全部取自结果行）。"""
    _, district_name = _parse_district(question)
    numeric = None
    review = None
    for step in steps:
        cols = [str(c).lower() for c in (step.get("columns") or [])]
        if numeric is None and "occupancy_cur" in cols and "occupancy_prev" in cols:
            numeric = step
        if review is None and "review_id" in cols:
            review = step

    findings: list[dict] = []
    answer_parts: list[str] = []

    if numeric is not None:
        no = _step_no(steps, numeric, "occupancy_cur")
        occ_c = _cell(numeric, "occupancy_cur")
        occ_p = _cell(numeric, "occupancy_prev")
        mkt_c = _cell(numeric, "market_occupancy_cur")
        mkt_p = _cell(numeric, "market_occupancy_prev")
        adr_c = _cell(numeric, "adr_cur")
        adr_p = _cell(numeric, "adr_prev")
        mpr_c = _cell(numeric, "market_price_cur")
        mpr_p = _cell(numeric, "market_price_prev")
        if None not in (occ_c, occ_p, mkt_c, mkt_p):
            own_pp = (occ_c - occ_p) * 100
            mkt_pp = (mkt_c - mkt_p) * 100
            trend = "基本持平" if abs(mkt_pp) <= 0.5 else ("同步下降" if mkt_pp < 0 else "同步上升")
            conclusion = "不是市场整体问题，是自身跑输市场" if (own_pp < 0 and mkt_pp >= -0.5) else "与市场同步"
            direction = "下降" if own_pp < 0 else "上升"
            findings.append({
                "statement": (
                    f"{district_name}本期入住率 {fmt.fmt_pct(occ_c)}，上年同期 {fmt.fmt_pct(occ_p)}，"
                    f"{direction} {abs(own_pp):.1f} 个百分点；同期市场基准 {fmt.fmt_pct(mkt_p)} → {fmt.fmt_pct(mkt_c)}，"
                    f"{trend}，说明{conclusion}。"
                ),
                "evidence": [{"step": no}],
            })
            answer_parts.append(
                f"{district_name}本期入住率 {fmt.fmt_pct(occ_c)}，上年同期 {fmt.fmt_pct(occ_p)}，{direction} {abs(own_pp):.1f} 个百分点；"
                f"同期市场基准 {fmt.fmt_pct(mkt_p)} → {fmt.fmt_pct(mkt_c)}，{trend}，说明{conclusion}。"
            )
        if None not in (adr_c, adr_p, mpr_c, mpr_p) and adr_p and mpr_p:
            own_rate = adr_c / adr_p - 1
            mkt_rate = mpr_c / mpr_p - 1
            if abs(own_rate - mkt_rate) <= 0.02:
                price_note = "接近"
            else:
                price_note = "高于" if own_rate > mkt_rate else "低于"
            findings.append({
                "statement": (
                    f"本期平均房价 {fmt.fmt_money(adr_c)}、上年同期 {fmt.fmt_money(adr_p)}；"
                    f"同期市场均价 {fmt.fmt_money(mpr_p)} → {fmt.fmt_money(mpr_c)}，自身涨幅{price_note}市场。"
                ),
                "evidence": [{"step": no}],
            })
            answer_parts.append(
                f"平均房价 {fmt.fmt_money(adr_c)}，上年同期 {fmt.fmt_money(adr_p)}；"
                f"市场均价 {fmt.fmt_money(mpr_p)} → {fmt.fmt_money(mpr_c)}，自身涨幅{price_note}市场。"
            )
        findings.append({"statement": "以上为区级汇总口径，未拆分到房源与渠道。", "evidence": [{"step": no}]})

    if review is not None:
        no = _step_no(steps, review, "review_id")
        communities = sorted({
            str(row[[str(c).lower() for c in review["columns"]].index("community")])
            for row in (review.get("rows") or [])
            if "community" in [str(c).lower() for c in review["columns"]]
        })
        scope = "、".join(communities) if communities else "全部小区"
        count = review.get("row_count") or 0
        avg_rating = _cell(review, "avg_rating") if "avg_rating" in [str(c).lower() for c in (review.get("columns") or [])] else None
        if avg_rating is not None:
            findings.append({
                "statement": f"低分评论集中在 {scope}，该小区平均评分 {fmt.fmt_cell('rating', avg_rating)} 分，"
                             f"结果共 {count} 条低分评论，主题见被引评论。",
                "evidence": [{"step": no}],
            })
        else:
            findings.append({
                "statement": f"低分评论集中在 {scope}，结果共 {count} 条低分评论，主题见被引评论。",
                "evidence": [{"step": no}],
            })
        answer_parts.append(f"低分评论集中在{scope}，共 {count} 条，主题见被引评论。")
        findings.append({"statement": "以上为评论明细汇总，未做文本聚类，主题以被引评论原文为准。", "evidence": [{"step": no}]})

    if not findings:
        return None
    answer = fmt.trim_to("".join(answer_parts), DIAGNOSE_ANSWER_LIMIT)
    return answer, {"findings": findings[:4], "suggestions": []}


def _step_review_ids(steps: list[dict], limit: int = 20) -> list[str]:
    """按步骤结果行里的 review_id 列收集被引编号（去重、最多 20 条）。"""
    out: list[str] = []
    for step in steps:
        cols = [str(c).lower() for c in (step.get("columns") or [])]
        if "review_id" not in cols:
            continue
        idx = cols.index("review_id")
        for row in step.get("rows") or []:
            if idx >= len(row):
                continue
            rid = row[idx]
            if isinstance(rid, str) and _REVIEW_ID_RE.fullmatch(rid) and rid not in out:
                out.append(rid)
                if len(out) >= limit:
                    return out
    return out


CITATION_TIMEOUT_S = 15.0  # 回库取引用详情是常数级 IN 查询，给足超时，别被模型 SQL 的 5s 口径误伤


def _citations_from_steps(ids: list[str], steps: list[dict] | None) -> list[dict]:
    """退化路径：直接用步骤结果行里已有的列组装 citations（不依赖回库查询）。"""
    if not steps:
        return []
    wanted = ["review_id", "listing_id", "community", "review_date", "rating", "content"]
    found: dict[str, dict] = {}
    for step in steps:
        cols = [str(c).lower() for c in (step.get("columns") or [])]
        if "review_id" not in cols:
            continue
        index = {name: cols.index(name) for name in wanted if name in cols}
        ridx = index["review_id"]
        for row in step.get("rows") or []:
            if ridx >= len(row):
                continue
            rid = row[ridx]
            if not isinstance(rid, str) or rid not in ids or rid in found:
                continue
            found[rid] = {
                name: (row[idx] if idx < len(row) else None) for name, idx in index.items()
            }
    return [found[rid] for rid in ids if rid in found]


def _citations(ids: list[str], steps: list[dict] | None = None) -> list[dict]:
    """被引评论详情：一条 IN 查询一次取回；失败也不吞成空数组，退回结果行组装。

    硬约束：返回的 ID 必须都出现在某一步结果行的 review_id 列里（规格 3.4）。
    """
    if not ids:
        return []
    safe = [rid for rid in ids if _REVIEW_ID_RE.fullmatch(rid)]
    if steps is not None:
        available = set(_step_review_ids(steps, limit=200))
        safe = [rid for rid in safe if rid in available]
    if not safe:
        return []
    sql = (
        "SELECT r.review_id, r.listing_id, l.community, r.review_date, r.rating, r.content "
        "FROM reviews r JOIN listings l ON l.listing_id = r.listing_id "
        "WHERE r.review_id IN (" + ",".join(f"'{rid}'" for rid in safe) + ")"
    )
    rows = []
    try:
        rows = sqlguard.run_readonly(sql, max_rows=200, timeout_s=CITATION_TIMEOUT_S).get("rows") or []
    except (sqlguard.SqlRejected, sqlguard.SqlError, sqlguard.SqlTimeout):
        rows = []
    by_id = {str(row[0]): row for row in rows}
    out = []
    for rid in safe:
        row = by_id.get(rid)
        if not row:
            continue
        out.append(
            {
                "review_id": row[0],
                "listing_id": row[1],
                "community": row[2],
                "review_date": row[3],
                "rating": row[4],
                "content": row[5],
            }
        )
    if out:
        return out
    return _citations_from_steps(safe, steps)


# ---------------------------------------------------------------- 主流程
def _refused(question: str, answer: str, meta: dict) -> dict:
    return _payload(question, "refused", fmt.trim_to(answer, QUERY_ANSWER_LIMIT), [], [], None, meta)


def ask(raw_question: str) -> dict:
    """/api/ask 的全部逻辑。LLM 不可达时抛 llm.LLMUnavailable。"""
    t0 = time.monotonic()
    question = (raw_question or "").strip()
    _, model = llm.llm_settings()
    meta = {
        "llm_calls": 0,
        "model": model,
        "elapsed_ms": 0,
        "degraded": False,
        "degrade_reason": None,
        "untraceable": [],
    }

    # 0) 明显的写操作/非查询意图：不执行任何 SQL
    if looks_like_write(question):
        return _finish(_refused(question, REFUSED_ANSWER, meta), t0)

    # 1) 规划
    try:
        plan = _plan(question, meta)
    except ValueError:
        return _finish(_degraded(question, "query", [], meta, "E_PLAN_FORMAT"), t0)
    except BudgetExceeded:
        return _finish(_degraded(question, "query", [], meta, "E_CALL_BUDGET"), t0)

    mode = plan["mode"]
    if mode == "refused":
        return _finish(_refused(question, plan["answer"], meta), t0)
    if plan.get("fallback"):
        # 走的是代码里的骨架 SQL：回答仍由模型解读，所以 degraded 保持 false，只记原因码
        meta["degrade_reason"] = "E_PLAN_FALLBACK"
    if mode == "query" and _DIAGNOSE_HINT.search(question):
        mode = "diagnose"  # "为什么 / 抱怨什么"类必须产出 diagnosis（规格 3.2）

    # 2) 执行
    planned = plan["steps"]
    if mode == "diagnose":
        planned = planned[:MAX_STEPS_DIAGNOSE]
    try:
        steps = _execute_all(planned, question, meta)
    except BudgetExceeded:
        steps = _execute_all_partial(planned, question, meta)

    if mode == "diagnose":
        # 某一步 SQL 超时 / 出错时不整题失败：补一条参数化的评论明细骨架（失败那步仍保留并带 error）
        steps, used_step_fallback = _apply_step_fallback(
            question, steps, force=bool(plan.get("fallback")) and _is_review_question(question)
        )
        if used_step_fallback:
            meta["degrade_reason"] = "E_STEP_FALLBACK"
            meta["degraded"] = False

    # 3) 写回答（带一次重写机会）
    answer_payload: dict = {}
    problems: list[str] = []
    for attempt in range(MAX_REWRITES + 1):
        try:
            answer_payload = _ask_answer(question, mode, steps, meta, feedback=problems or None)
        except ValueError:
            answer_payload = {}
        except llm.LLMUnavailable as exc:
            if not getattr(exc, "timed_out", False):
                raise  # 连不上 → 503（规格 2.4）；超时按"成文失败"走确定性回答（规格 3.2 v2.6）
            payload = {"problems": ["成文调用超时"], "reason": "E_LLM_TIMEOUT", "untraceable": []}
            break
        except BudgetExceeded:
            meta["degraded"] = True
            meta["degrade_reason"] = "E_CALL_BUDGET"
            return _finish(_degraded(question, mode, steps, meta, "E_CALL_BUDGET"), t0, _log_steps(steps))
        payload = _normalize_answer(answer_payload, mode, steps, question)
        problems = payload["problems"]
        if not problems:
            if mode == "diagnose" and payload.get("diagnosis"):
                # 数值骨架在场时，diagnosis 用确定性生成（值/判定都来自结果行），避免模型漏写指标
                deterministic = _deterministic_diagnose(question, steps)
                if deterministic and deterministic[1]["findings"]:
                    payload["diagnosis"] = deterministic[1]
            meta.update({k: v for k, v in payload["meta"].items()})
            return _finish(
                _payload(question, mode, payload["answer"], steps, payload["citations"],
                         payload["diagnosis"], meta),
                t0,
                _log_steps(steps),
            )
        if attempt == MAX_REWRITES:
            break

    # 4) 退回确定性回答
    meta["untraceable"] = payload.get("untraceable") or []
    reason = payload.get("reason") or "E_UNTRACEABLE_NUMBER"
    diagnosis = None
    if mode == "diagnose":
        # 规格 3.6（v2.6）：diagnosis 由代码从骨架结果行确定性生成，不许为 null
        deterministic = _deterministic_diagnose(question, steps)
        if deterministic:
            answer, diagnosis = deterministic
        else:
            answer = fmt.template_answer(mode, steps, DIAGNOSE_ANSWER_LIMIT)
            diagnosis = _fallback_diagnosis(steps)
    else:
        answer = fmt.template_answer(mode, steps, QUERY_ANSWER_LIMIT)
    meta["degraded"] = True
    meta["degrade_reason"] = reason
    # 规格 3.6（v2.5）：退回时引用不丢——步骤结果行里有 review_id 就填进 citations
    citations = _citations(_step_review_ids(steps), steps)
    result = _payload(question, mode, answer, steps, citations, diagnosis, meta)
    return _finish(result, t0, _log_steps(steps))


def _log_steps(steps: list[dict]) -> list[dict]:
    return [{"sql": s.get("sql"), "row_count": s.get("row_count"), "error": s.get("error")} for s in steps]


def _execute_all_partial(planned: list[dict], question: str, meta: dict) -> list[dict]:
    steps = []
    for step in planned:
        try:
            steps.append(_execute_step(step, question, meta))
        except BudgetExceeded:
            break
    return steps


def _degraded(question: str, mode: str, steps: list[dict], meta: dict, reason: str) -> dict:
    meta["degraded"] = True
    meta["degrade_reason"] = reason
    answer = fmt.template_answer(mode, steps, DIAGNOSE_ANSWER_LIMIT if mode == "diagnose" else QUERY_ANSWER_LIMIT)
    if not answer:
        answer = "这次没能拿到可用的查询结果，请换个问法再试。"
    diagnosis = None
    if mode == "diagnose":
        deterministic = _deterministic_diagnose(question, steps)
        if deterministic:
            answer, diagnosis = deterministic
        else:
            diagnosis = _fallback_diagnosis(steps)
    citations = _citations(_step_review_ids(steps), steps)
    return _payload(question, mode, answer, steps, citations, diagnosis, meta)


def _normalize_answer(raw: dict, mode: str, steps: list[dict], question: str) -> dict:
    """清洗 + 校验（3.4 / 3.5 / 评论引用）。返回 {answer, citations, diagnosis, problems, reason, untraceable}。"""
    problems: list[str] = []
    limit = DIAGNOSE_ANSWER_LIMIT if mode == "diagnose" else QUERY_ANSWER_LIMIT
    answer = fmt.sanitize_markdown(str((raw or {}).get("answer") or ""))
    if not answer:
        problems.append("answer 为空或全是 Markdown 标记")
    diagnosis = _coerce_diagnosis((raw or {}).get("diagnosis") or (raw or {}), steps, _available_review_ids(steps)) if mode == "diagnose" else None

    if len(answer) > limit:
        # 不为此多花一次模型调用：按标点截断即可（结论在第一句，不会被切掉）
        answer = fmt.trim_to(answer, limit)

    diag_text = _diagnosis_text(diagnosis)
    combined = answer + ("\n" + diag_text if diag_text else "")
    untraceable = trace.untraceable_numbers(combined, question, steps)
    if untraceable:
        problems.append(
            "回答里有结果行里找不到的数字：" + "、".join(untraceable[:8]) +
            "。只能使用结果行里的值、行数，或同一列两个值相减/相除得到的值；否则删掉这些数字"
        )

    available = _available_review_ids(steps)
    cited = _cited_ids(combined)
    bad_citations = [rid for rid in cited if rid not in available]
    reason = "E_UNTRACEABLE_NUMBER" if untraceable else None
    if bad_citations:
        problems.append(
            "引用了结果里不存在的评论编号：" + "、".join(bad_citations[:8]) +
            "。只能引用某一步结果行 review_id 列里出现过的编号"
        )
        reason = reason or "E_BAD_CITATION"

    if mode == "diagnose" and not diagnosis:
        problems.append("缺少 diagnosis：请给出 findings（至少 1 条，带 evidence）与 suggestions")

    answer = fmt.trim_to(answer, limit) if answer else answer
    return {
        "answer": answer,
        "citations": _citations(cited, steps),
        "diagnosis": diagnosis,
        "problems": problems,
        "reason": reason,
        "untraceable": untraceable,
        "meta": {},
    }
