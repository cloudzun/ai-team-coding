"""数字可追溯检查（规格第 3.5 节，逐条按文字实现）。

1 提取 → 2 豁免 → 3 候选值（结果行数值 / row_count / 同列两值差与比值）→
4 渲染（Decimal(str(v)) + ROUND_HALF_UP）→ 5 绝对值逐字比对 → 6 返回不可追溯清单。
"""
from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal
from itertools import combinations

NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
ISO_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
RANGE_RE = re.compile(r"\d+\s*[–—\-~～至]\s*\d+\s*(?:月|日|号|季度)")
UNITS = ("个百分点", "pp", "%", "万", "亿", "元")
# 编号前缀：L 房源号、R 评论号、D 区、T 口径表规则号、N/P/Q/F/C 运营手册规则号（N-01、P-01 …）；
# 后一组以“字母-数字”形态出现，前一个字是 '-'，所以另由 _ID_HYPHEN 那一条整串豁免。
_ID_PREFIX = frozenset("LRDTNPQFCM")
_ID_HYPHEN = frozenset("-－–—")
_DERIVE_COLUMN_CAP = 60


def _decimal(text: str) -> Decimal:
    return Decimal(text.replace(",", ""))


def unit_after(text: str, end: int) -> str:
    rest = text[end : end + 8].lstrip()
    low = rest.lower()
    for unit in UNITS:
        if low.startswith(unit.lower()):
            return unit
    return ""


def extract_numbers(answer: str, question: str) -> list[dict]:
    """第 1、2 步：提取数字并剔除豁免项。返回 [{text, value, unit}]。"""
    question_values = {_decimal(m.group(0)) for m in NUMBER_RE.finditer(question or "")}
    dates = [(m.start(), m.end()) for m in ISO_DATE_RE.finditer(answer)]
    ranges = [(m.start(), m.end()) for m in RANGE_RE.finditer(answer)]

    out: list[dict] = []
    for m in NUMBER_RE.finditer(answer):
        start, end = m.start(), m.end()
        raw = m.group(0)
        value = _decimal(raw)

        if any(a <= start and end <= b for a, b in dates):  # ISO 日期里的数字
            continue
        if any(a <= start and end <= b for a, b in ranges):  # 7–12 月 这类区间端点
            continue
        if "." not in raw and len(raw) == 4 and 2000 <= value <= 2099:  # 年份
            continue
        before = answer[:start].rstrip()
        if before.endswith("第"):  # 序数
            continue
        if before[-1:] in ("Q", "q"):  # Q3
            continue
        if before[-1:] in _ID_PREFIX:  # L\d+ / R\d+ / D\d\d / T\d\d / N01 / P01
            continue
        if (len(raw) <= 4 and before[-1:] in _ID_HYPHEN
                and before[-2:-1].isascii() and before[-2:-1].isalpha()):
            continue  # N-01 / P-01 / Q-05 / M-07 这类“字母-数字”编号：整串不当数字
        tail = answer[end : end + 3].lstrip()
        if tail[:1] in ("月", "日", "号"):  # 紧跟月 / 日 / 号
            continue
        if tail.startswith("季度"):
            continue
        if value in question_values:  # 问题原文出现过的数字
            continue
        out.append({"text": raw.replace(",", ""), "value": value, "unit": unit_after(answer, end)})
    return out


def _numeric_cells(step: dict) -> dict[str, list[tuple[Decimal, bool]]]:
    """{列名: [(数值, 是否来自 SQLite 的 int 单元格)]}。"""
    columns = step.get("columns") or []
    by_col: dict[str, list[tuple[Decimal, bool]]] = {}
    for idx, name in enumerate(columns):
        values: list[tuple[Decimal, bool]] = []
        for row in step.get("rows") or []:
            if idx >= len(row):
                continue
            v = row[idx]
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                continue
            values.append((Decimal(str(v)), isinstance(v, int)))
        if values:
            by_col.setdefault(str(name), []).extend(values)
    return by_col


def candidate_values(steps: list[dict]) -> dict[Decimal, bool]:
    """第 3 步：所有候选值 → {值: 是否来自整数类型单元格}（同一 Decimal 去重）。

    含：每步结果行的数值单元格、每步 row_count、同一步同列任意两值的 a−b 与 a÷b−1、
    以及不同步骤同名列的这两种派生（按列名合并后一起组合）。
    只有来自 SQLite `int` 单元格 / `row_count` 的候选值，才享受"0 位小数"渲染（规格 3.5 第 4 条）。
    """
    pool: dict[Decimal, bool] = {}

    def add(value: Decimal, is_int: bool = False) -> None:
        pool[value] = pool.get(value, False) or is_int

    columns: dict[str, list[tuple[Decimal, bool]]] = {}
    for step in steps:
        for name, values in _numeric_cells(step).items():
            for value, is_int in values:
                add(value, is_int)
            columns.setdefault(name, []).extend(values)
        rc = step.get("row_count")
        if isinstance(rc, (int, float)) and not isinstance(rc, bool):
            add(Decimal(str(rc)), isinstance(rc, int))

    for values in columns.values():
        sample = values[:_DERIVE_COLUMN_CAP]
        for (a, _), (b, _) in combinations(sample, 2):
            # 派生值由 Python 浮点算出，按"非整数来源"处理（不用 0 位渲染）
            add(a - b)
            add(b - a)
            if b != 0:
                add(a / b - 1)
            if a != 0:
                add(b / a - 1)
    return pool


def _places_for(unit: str, value: Decimal, int_source: bool) -> tuple[int, ...]:
    if unit in ("%", "pp", "个百分点"):
        return (0, 1, 2)
    if unit == "万":
        return (0, 1, 2)
    if unit == "亿":
        return (1, 2)
    # 其他：默认 1、2 位；只有整数类型来源才额外允许 0 位（规格 3.5 第 4 条）
    return (0, 1, 2) if int_source else (1, 2)


def _scale_candidates(unit: str) -> tuple[tuple[Decimal, bool], ...]:
    """返回若干 (倍数, 是否相乘)。百分比要乘 100；万 / 亿既认除，也认“数值本身已是万 / 亿”。"""
    if unit in ("%", "pp", "个百分点"):
        return ((Decimal(100), True),)
    if unit == "万":
        return ((Decimal(10000), False), (Decimal(1), True))
    if unit == "亿":
        return ((Decimal(100000000), False), (Decimal(1), True))
    return ((Decimal(1), True),)


def render_forms(value: Decimal, unit: str, int_source: bool = False) -> set[str]:
    """第 4 步：把一个候选值渲染成"回答里可能写成的文本"（绝对值，去符号）。

    万 / 亿 有两种来源：结果行是原始元（除以 10000 / 亿），或结果行本身已经是万 / 亿
    （模型在 SQL 里先除过、答案照抄），所以两种缩放都要渲染一份。
    """
    forms: set[str] = set()
    for factor, multiply in _scale_candidates(unit):
        scaled = value * factor if multiply else value / factor
        for places in _places_for(unit, value, int_source):
            try:
                quant = Decimal(1).scaleb(-places)
                rounded = scaled.quantize(quant, rounding=ROUND_HALF_UP)
            except Exception:  # noqa: BLE001 - 极端数值不参与比对
                continue
            if rounded == 0:
                rounded = abs(rounded)
            forms.add(f"{rounded:.{places}f}".lstrip("-"))
    return forms


def traceable_forms(candidates: dict[Decimal, bool], units: set[str]) -> dict[str, set[str]]:
    forms: dict[str, set[str]] = {}
    for unit in units:
        bucket: set[str] = set()
        for value, int_source in candidates.items():
            bucket |= render_forms(value, unit, int_source)
        forms[unit] = bucket
    return forms


def untraceable_numbers(answer: str, question: str, steps: list[dict]) -> list[str]:
    """返回回答里不可追溯的数字文本（带单位，便于回显给模型）。"""
    extracted = extract_numbers(answer, question)
    if not extracted:
        return []
    forms = traceable_forms(candidate_values(steps), {item["unit"] for item in extracted})
    bad: list[str] = []
    for item in extracted:
        text = item["text"].lstrip("-")
        if text in forms.get(item["unit"], set()):
            continue
        shown = text + item["unit"]
        if shown not in bad:
            bad.append(shown)
    return bad
