"""回答格式化：Markdown 清洗、字数上限、模板回答（规格 3.6）。"""
from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal

PCT_KEYS = ("occupancy", "rate", "share", "pct", "ratio")
MONEY_KEYS = ("adr", "price", "revenue", "amount", "revpar")
RATING_KEYS = ("rating", "score")
_SENTENCE_END = "。！？；!?;"
CODE_FENCE_RE = re.compile(r"```[a-zA-Z]*")
HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s*")
BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
INLINE_CODE_RE = re.compile(r"`([^`]*)`")


def quantize_half_up(value, places: int) -> Decimal:
    q = Decimal(1).scaleb(-places)
    return Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP)


def fmt_pct(value) -> str:
    return f"{quantize_half_up(Decimal(str(value)) * 100, 1):.1f}%"


def fmt_money(value) -> str:
    return f"¥{quantize_half_up(value, 0):,.0f}"


def fmt_plain(value) -> str:
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        text = f"{value:.6f}".rstrip("0").rstrip(".")
        return text or "0"
    return str(value)


def fmt_cell(column: str, value) -> str:
    if value is None:
        return "—"
    name = str(column).lower()
    if isinstance(value, str):
        match = _MONTH_RE.fullmatch(value)
        if match:
            return f"{match.group(1)} 年 {int(match.group(2))} 月"  # 避免 YYYY-MM 里的数字不可追溯
    numeric = isinstance(value, (int, float)) and not isinstance(value, bool)
    if numeric:
        if any(k in name for k in RATING_KEYS):
            return f"{quantize_half_up(value, 2):.2f}"
        if any(k in name for k in PCT_KEYS):
            return fmt_pct(value)
        if any(k in name for k in MONEY_KEYS):
            return fmt_money(value)
    return fmt_plain(value)


def fmt_row(columns: list[str], row: list) -> str:
    return "，".join(f"{col} {fmt_cell(col, row[i] if i < len(row) else None)}" for i, col in enumerate(columns))


def sanitize_markdown(text: str) -> str:
    """去掉 Markdown 痕迹：代码围栏、行首 #、** 加粗、行内反引号、表格行。"""
    body = CODE_FENCE_RE.sub("", text or "")
    body = BOLD_RE.sub(r"\1", body)
    body = INLINE_CODE_RE.sub(r"\1", body)
    lines = []
    for raw in body.splitlines():
        line = HEADING_RE.sub("", raw)
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("|"):  # 表格行
            continue
        if re.fullmatch(r"[-|:\s]+", stripped):  # 表格分隔行
            continue
        if stripped.startswith(("- ", "* ", "• ")) and len(stripped) > 2:
            line = "· " + stripped[2:]
        lines.append(line.strip())
    text = " ".join(lines).strip()
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text


def trim_to(text: str, limit: int) -> str:
    """超长时在标点处截断，实在没有标点就硬截。"""
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    head = text[:limit]
    cut = max(head.rfind(ch) for ch in _SENTENCE_END)
    if cut >= limit // 3:
        return head[: cut + 1]
    return head[: limit - 1] + "…"


def template_answer(mode: str, steps: list[dict], limit: int) -> str:
    """规格 3.6 的确定性模板回答。"""
    if not steps:
        return trim_to("这次没有拿到可以展示的查询结果，请换个问法再试。", limit)

    def block(step: dict) -> str:
        columns = step.get("columns") or []
        rows = step.get("rows") or []
        if step.get("error"):
            return "查询失败：" + str(step["error"])[:60]
        if not rows:
            return "没有查到符合条件的数据。"
        lines = [fmt_row(columns, row) for row in rows[:5]]
        total = step.get("row_count", len(rows))
        if total > 5 or step.get("truncated"):
            lines.append(f"共 {total} 行，见下方明细")
        return "；".join(lines)

    if mode == "diagnose":
        parts = []
        for idx, step in enumerate(steps, 1):
            purpose = step.get("purpose") or "查询"
            parts.append(f"第 {idx} 步（{purpose}）：{block(step)}")
        text = "".join(parts)
    else:
        text = "查询结果：" + block(steps[0])
    return trim_to(text, limit)


_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")


def suggestion_for(column: str, value) -> str:
    """给模型一个"这样写才可追溯"的渲染示例（3.5 的第 4 步渲染）。"""
    if value is None:
        return "—"
    name = str(column).lower()
    if isinstance(value, str):
        match = _MONTH_RE.fullmatch(value)
        if match:
            return f"{match.group(1)} 年 {int(match.group(2))} 月"  # 避免 YYYY-MM 里的数字不可追溯
    numeric = isinstance(value, (int, float)) and not isinstance(value, bool)
    if not numeric:
        return fmt_plain(value)
    if any(k in name for k in RATING_KEYS):
        return f"{quantize_half_up(value, 2):.2f}"
    if any(k in name for k in PCT_KEYS) and abs(float(value)) <= 1.0001:
        return fmt_pct(value)
    if any(k in name for k in MONEY_KEYS):
        return f"{quantize_half_up(value, 0):,.0f} 元"
    if isinstance(value, int):
        return f"{quantize_half_up(value, 0):,.0f}"  # 整数类型单元格允许 0 位（规格 3.5 第 4 条）
    return f"{quantize_half_up(value, 1):.1f}"


TEXT_COLUMNS = ("content", "title", "community", "channel", "name", "district", "reason", "status")


def render_hint(step: dict, max_rows: int = 6) -> str:
    """每步结果行的"建议写法"清单：只给数值列的写法（文本列原样引用即可，不进清单，省上下文）。"""
    columns = step.get("columns") or []
    rows = step.get("rows") or []
    if not columns or not rows:
        return ""
    keep = [
        i for i, name in enumerate(columns)
        if not any(k in str(name).lower() for k in TEXT_COLUMNS)
    ]
    if not keep:
        return ""
    lines = []
    for index, row in enumerate(rows[:max_rows]):
        parts = []
        for i in keep:
            value = row[i] if i < len(row) else None
            parts.append(f"{columns[i]} {fmt_plain(value)} → 写成 {suggestion_for(columns[i], value)}")
        if parts:
            lines.append(f"  第 {index + 1} 行：" + "；".join(parts))
    if len(rows) > max_rows:
        lines.append(f"  ……共 {len(rows)} 行")
    return "\n".join(lines)
