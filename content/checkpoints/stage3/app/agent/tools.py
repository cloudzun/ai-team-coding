"""Agent 工具清单与唯一调用入口 dispatch_tool（两规则版）。

- 清单里只有读工具与两个“预览”写工具；没有提交、审批类工具。
- 名字不在清单内一律 {ok: false, reason: "E_TOOL"}，不改业务表，写一行审计。
- 每次调用（含被拒）在 audit_log 写一行，params 含 run_id。
"""
from __future__ import annotations

from app import ops_store
from app.tools import metrics

from . import rules

READ_TOOLS = (
    "scan_owner_blocks",      # N-01 候选：房东关房导致成交少
    "scan_raises_over_cap",   # P-01 候选：人工上调幅度已超过单次上限
    "listing_occupancy",      # R12
    "listing_blocks",         # R13
    "price_now",              # R16
    "price_history",          # 价格记录
)
WRITE_TOOLS = ("preview_price_change", "preview_ticket")
TOOL_NAMES = READ_TOOLS + WRITE_TOOLS

# 模型在排查环节可选的读工具（单房源）
INVESTIGATE_TOOLS = {
    "listing_occupancy": "单房源某期入住率、可售晚数、成交晚数（R12）",
    "listing_blocks": "单房源某期房东关房晚数，按原因拆分（R13）",
    "price_history": "单房源全部价格记录：生效日、平日价、周末价、来源（人工/规则）",
    "price_now": "单房源当前平日价与上一档平日价（R16）",
}


class ToolError(Exception):
    pass


def _lid(params: dict) -> str:
    lid = str(params.get("listing_id") or "")
    if not metrics.store().exists(lid):
        raise ToolError(f"E_LISTING 房源 {lid or '(空)'} 不存在")
    return lid


def _window(params: dict) -> tuple[str, str]:
    start = str(params.get("start") or rules.Q3[0])
    end = str(params.get("end") or rules.Q3[1])
    if not ("2023-10-01" <= start <= end <= "2026-09-30"):
        raise ToolError("E_PARAM 日期须在 2023-10-01 至 2026-09-30 之间且 start ≤ end")
    return start, end


def _candidates() -> list[str]:
    return metrics.store().online_listings(rules.AS_OF)


def _clean(obj):
    """去掉 exact_*（Fraction）字段，保证结果可 JSON 序列化。"""
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items() if not str(k).startswith("exact_")}
    if isinstance(obj, list):
        return [_clean(v) for v in obj]
    return obj


def _run(name: str, params: dict) -> tuple[str, object]:
    st = metrics.store()
    if name == "scan_owner_blocks":
        hits = rules.scan_n01(st, _candidates())
        return f"房东关房导致成交少的在线房源 {len(hits)} 套", hits
    if name == "scan_raises_over_cap":
        hits = rules.scan_p01(st, _candidates())
        return f"当前价相对上一档上调幅度超过单次上限的在线房源 {len(hits)} 套", hits
    if name == "listing_occupancy":
        lid = _lid(params)
        r = st.r12(lid, *_window(params))
        return f"{lid} 可售 {r['available_nights']} 晚、成交 {r['sold_nights']} 晚、入住率 {r['occupancy']}", r
    if name == "listing_blocks":
        lid = _lid(params)
        r = st.r13(lid, *_window(params))
        txt = "、".join(f"{k}{v}晚" for k, v in r.items()) or "无关房"
        return f"{lid} 关房：{txt}", r
    if name == "price_now":
        lid = _lid(params)
        r = st.r16(lid, str(params.get("day") or rules.AS_OF))
        if r is None:
            return f"{lid} 无价格记录", None
        return f"{lid} 当前平日价 {r['current_price']}（{r['source']}），上一档 {r['previous_price']}", r
    if name == "price_history":
        lid = _lid(params)
        rows = st.price_history(lid, str(params.get("day") or rules.AS_OF))
        txt = " → ".join(f"{r['effective_date']} {r['weekday_price']}（{r['source']}）" for r in rows[-4:])
        return f"{lid} 价格记录 {len(rows)} 条：{txt}", rows
    if name == "preview_price_change":
        res = ops_store.preview({**params, "kind": "price_change"})
        if not res["ok"]:
            raise ToolError(res["reject_reason"])
        return f"{params.get('listing_id')} 调价预览通过：{res['row']['current_price']}→{res['row']['proposed_price']}", res
    if name == "preview_ticket":
        res = ops_store.preview({**params, "kind": "ticket"})
        if not res["ok"]:
            raise ToolError(res["reject_reason"])
        return f"{params.get('listing_id')} {params.get('issue_type')}工单预览通过", res
    raise ToolError("E_TOOL")  # 不会到达：名字已在清单内


def dispatch_tool(name: str, params: dict, run_id: str) -> dict:
    """Agent 调工具的唯一入口。返回 {ok, summary?, data?, reason?}。"""
    params = dict(params or {})
    audit_params = {**params, "run_id": run_id}
    if name not in TOOL_NAMES:
        result = {"ok": False, "reason": f"E_TOOL 工具“{name}”不在清单内（Agent 不能提交或审批）"}
        ops_store.audit(str(name), audit_params, result)
        return result
    try:
        summary, data = _run(name, params)
        result = {"ok": True, "summary": summary, "data": _clean(data)}
        audit_result = {"ok": True, "summary": summary}
        if name in WRITE_TOOLS:
            audit_result["preview_id"] = data.get("preview_id")
    except ToolError as exc:
        result = {"ok": False, "reason": str(exc), "summary": str(exc)}
        audit_result = {"ok": False, "reason": str(exc)}
    except Exception as exc:  # noqa: BLE001 - 工具内部错误也要入审计，不拖垮巡检
        msg = f"E_INTERNAL {exc.__class__.__name__}: {exc}"
        result = {"ok": False, "reason": msg, "summary": msg}
        audit_result = {"ok": False, "reason": msg}
    ops_store.audit(name, audit_params, audit_result)
    return result
