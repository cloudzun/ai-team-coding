"""巡检规则：两条规则版的单一真相源。

本版只保留两类规则（教学存档点·阶段三的两规则版）：

1. **N-01 不调价情形 · 房东关房**（运营手册“什么情况不调价”里以房东关房为条件的那一条）
   房东关房期间、成交晚数低且主要由房东关房造成时，不调价、也不给降价建议。
   手册对“成交少”“主要”只有定性说法，本实现把这两处判断量化成参数，
   取值从配置（`.env` 或环境变量）读取，见 `app/config.py` 与 README。
   这是参考实现的取值，不是标准答案：参数必须写进自己的需求歧义声明里。

2. **P-01 单次调价幅度上限**（运营手册“定价规则”里的幅度上限条）
   单次调价幅度不得超过 15%（涨或降都算，以当前平日价为基数）。
   扫描发现“当前价相对上一档的人工上调已经超过上限”的房源，给出一次回调的建议；
   写入层（`app/ops_store.py`）在预览与提交时按同一条上限再校验，超过则拒绝并回 `P-01` 与允许范围。

执行顺序 N-01 → P-01：后者排除前者已产出建议（含 action=none）的房源。
阈值判断一律用精确值（Fraction / Decimal / 整数），价格用整数或 Decimal 运算。
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction

from app.config import settings
from app.tools import metrics

AS_OF = "2026-09-30"                      # 巡检日期：固定为数据截止日（指标口径表 C-07）
Q3 = ("2026-07-01", "2026-09-30")         # 当期评估窗：数据截止日所在季

RULE_ORDER = ("N-01", "P-01")
RULE_TITLES = {
    "N-01": "不调价情形：房东关房",
    "P-01": "单次调价幅度上限",
}
RULE_CODES = {
    "N-01": ["N-01", "T-01"],
    "P-01": ["P-01", "P-06"],
}
MAX_CHANGE = Decimal("0.15")              # 手册 P-01：单次调价幅度上限 15%


def d(v) -> Decimal:
    return Decimal(repr(v)) if isinstance(v, float) else Decimal(v)


def pct1(x: Decimal) -> str:
    """比例 → 百分数一位小数文本（half-up）。"""
    return str((x * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def metric(key, value, ref, params) -> dict:
    return {"key": key, "value": value, "ref": ref, "params": dict(params)}


def q3_params(lid: str) -> dict:
    return {"listing_id": lid, "start": Q3[0], "end": Q3[1]}


# ---------------------------------------------------------------- 参数（参考实现取值，可改）
def n01_main_share() -> Fraction:
    """手册“主要由房东关房造成”的量化参数：关房晚数 ÷ 日历晚数 的判定值。"""
    return Fraction(d(settings.n01_main_share))


def n01_min_calendar_nights() -> int:
    """手册“成交晚数低”的口径：当期日历晚数不低于该值才纳入判断。"""
    return int(settings.n01_min_calendar_nights)


def n01_max_gross_occupancy() -> Fraction:
    """手册“成交晚数低”的口径：毛入住率低于该值才算成交少。"""
    return Fraction(d(settings.n01_max_gross_occupancy))


# ---------------------------------------------------------------- 处置公式
def p01_proposed(current: int, previous: int) -> int:
    """回调到上一档；上一档离得太远时只降一个上限（ceil(当前价 × 0.85)）。整数运算。"""
    return max(previous, (current * 85 + 99) // 100)


def change_pct(current: int, proposed: int) -> float:
    return float((Decimal(proposed) / Decimal(current) - 1).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def raise_pct(current: int, previous: int) -> float:
    return float((Decimal(current) / Decimal(previous) - 1).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------- N-01 不调价（房东关房）
def scan_n01(st: metrics.Store, candidates: list[str]) -> list[dict]:
    """房东关房期间 + 成交少 + 主要由房东关房造成 → 不调价。"""
    share_min = n01_main_share()
    min_cal = n01_min_calendar_nights()
    max_gross = n01_max_gross_occupancy()
    out = []
    for lid in candidates:
        r12 = st.r12(lid, *Q3)
        cal = r12["calendar_nights"]
        if cal < min_cal or r12["exact_gross_occupancy"] >= max_gross:
            continue
        blocks = st.r13(lid, *Q3)
        closed = sum(blocks.values())          # 房东关房晚数（C-04：起止都含，按原因拆分后求和）
        share = Fraction(closed, cal)
        if not closed or share < share_min:
            continue
        p = q3_params(lid)
        out.append({
            "listing_id": lid,
            "metrics": [
                metric("calendar_nights", cal, "R12", p),
                metric("gross_occupancy", r12["gross_occupancy"], "R12", p),
                metric("owner_block_nights", closed, "R13", p),
                metric("owner_block_share", float(share), "R13", p),
            ],
            "owner_block_share": float(share),
        })
    return out


# ---------------------------------------------------------------- P-01 幅度上限
def scan_p01(st: metrics.Store, candidates: list[str]) -> list[dict]:
    """当前价相对上一档的人工上调已超过上限 → 建议一次回调到上限以内。"""
    out = []
    for lid in candidates:
        price = st.r16(lid, AS_OF)
        if price is None or price["source"] != "人工" or not price["previous_price"]:
            continue
        cur, prev = price["current_price"], price["previous_price"]
        if d(cur) / d(prev) - 1 <= MAX_CHANGE:
            continue
        proposed = p01_proposed(cur, prev)
        p = {"listing_id": lid, "day": AS_OF}
        out.append({
            "listing_id": lid,
            "current_price": cur,
            "previous_price": prev,
            "effective_date": price["effective_date"],
            "proposed_price": proposed,
            "change_pct": change_pct(cur, proposed),
            "raise_pct": raise_pct(cur, prev),
            # 一次回调没有回到上一档：剩下的差距要人工评估（手册 P-05 同样要求“先申请上限以内”）
            "needs_manual_review": proposed > prev,
            "metrics": [
                metric("current_price", cur, "R16", p),
                metric("previous_price", prev, "R16", p),
            ],
        })
    return out


# ---------------------------------------------------------------- 模板（理由 / 说明 / 类别说明 / 报告）
def _m(metrics_list: list[dict], key: str):
    for m in metrics_list:
        if m["key"] == key:
            return m["value"]
    return None


def reason_p01(hit: dict) -> str:
    """调价申请的理由文本（写进待审批行，审批人据此判断）。"""
    text = (
        f"当前平日价{hit['current_price']}元相对上一档{hit['previous_price']}元的人工上调幅度为"
        f"{pct1(d(hit['raise_pct']))}%，超过单次调价幅度上限15%（P-01）；"
        f"建议回调至{hit['proposed_price']}元（{pct1(d(hit['change_pct']))}%），幅度在上限以内。"
    )
    if hit["needs_manual_review"]:
        text += "一次回调没有回到上一档价格，剩余差距需人工评估后再定（P-05）。"
    return text + "经人工批准后生效（P-06）。"


def explanation(rule_id: str, hit: dict, ctx: dict) -> str:
    """每条建议的说明（≤120 字，一律模板）。"""
    ms = hit.get("metrics", [])
    if rule_id == "N-01":
        return (f"Q3日历{_m(ms, 'calendar_nights')}晚，房东关房{_m(ms, 'owner_block_nights')}晚，"
                f"毛入住率{pct1(d(_m(ms, 'gross_occupancy')))}%；成交少主要由房东关房造成，"
                f"关房不算空置，不调价（N-01）。")
    if rule_id == "P-01":
        text = (f"当前平日价{hit['current_price']}元高于上一档{hit['previous_price']}元，"
                f"上调{pct1(d(hit['raise_pct']))}%，超过单次上限15%（P-01）；"
                f"建议回调至{hit['proposed_price']}元（{pct1(d(hit['change_pct']))}%）")
        return text + ("，剩余差距需人工评估。" if hit["needs_manual_review"] else "。")
    return ""


def note_template(rule_id: str, n: int) -> str:
    """类别说明模板（≤60 字，无 Markdown，只用条数）。"""
    return {
        "N-01": f"成交晚数少主要由房东关房造成，{n}套房源不调价。",
        "P-01": f"当前价相对上一档的上调幅度超过单次上限，{n}套房源申请回调。",
    }[rule_id]


def report_template(counts: dict[str, int], manual: int, total: int) -> str:
    parts = []
    for rid, label in (("P-01", "超上限回调申请"), ("N-01", "房东关房不调价")):
        if counts.get(rid):
            parts.append(f"{label}{counts[rid]}条")
    body = "、".join(parts) if parts else "无"
    text = (f"巡检日期按数据截止日2026-09-30计，共产出{total}条建议：{body}。"
            "调价申请的幅度均不超过单次上限15%（P-01），房东关房造成的成交少不算空置、不降价（N-01）。")
    if manual:
        text += f"其中{manual}条一次回调没有回到上一档，已标注需人工评估。"
    text += "所有建议均为待审批预览，需运营确认提交并审批后才生效；批准只改申请状态，不改价格记录。"
    return text
