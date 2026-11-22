"""巡检编排（两规则版）：程序判、模型查与写、人批。

顺序 N-01（不调价，房东关房）→ P-01（幅度上限回调）。
模型只做：P-01 的排查选工具（≤2 次）→ 两类类别说明（1 次）→ 报告（1 次），总计 ≤3 次。
任何失败、超时或触顶，该项及之后各项按规则模式补齐；巡检始终以 ready 结束。
"""
from __future__ import annotations

import json
import re
import threading
import time
import uuid
from datetime import datetime

from app.ask import trace
from app.tools import metrics

from . import llm_gate, rules
from .tools import INVESTIGATE_TOOLS, TOOL_NAMES, dispatch_tool

MAX_LLM_CALLS = 3
PER_CALL_TOOLS = 2
INVESTIGATE_SAMPLE = 5          # 给模型看的房源样本数（控制提示词长度与时延）
NOTE_MAX = 60
REPORT_MAX = 400
RULES_INVESTIGATE_SAMPLE = 2
MD_RE = re.compile(r"(\*\*|__|`|^\s*#|^\s*[-*+]\s|^\s*\d+\.\s|\[[^\]]*\]\(|^\s*>|\|)", re.MULTILINE)
# 文字里允许出现的常量（规则编号、上限、巡检日期），不算“不可追溯数字”
ALLOWED_CONSTANTS = "15 15% 2026 9 30 3 Q3 一年"

RUNS: dict[str, dict] = {}
_RUNS_LOCK = threading.Lock()


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class Budget:
    """模型调用计数与降级状态。"""

    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled
        self.calls = 0
        self.failed: str | None = None if enabled else "E_RULES_MODE use_llm=false"
        self.reasons: list[str] = [] if enabled else ["E_RULES_MODE use_llm=false"]

    def usable(self) -> bool:
        # 某项失败 / 超时只让该项走模板，后续各项照常尝试；只有触顶才全部补齐
        return self.enabled and self.calls < MAX_LLM_CALLS

    def exhausted(self) -> bool:
        return self.enabled and self.calls >= MAX_LLM_CALLS

    def mark(self, reason: str) -> None:
        if self.failed is None:
            self.failed = reason
        if reason not in self.reasons:
            self.reasons.append(reason)


class Run:
    def __init__(self, run_id: str, use_llm: bool) -> None:
        self.run_id = run_id
        self.budget = Budget(use_llm)
        self.t0 = time.perf_counter()
        self.state = {
            "run_id": run_id, "state": "running", "mode": "agent" if use_llm else "rules",
            "use_llm": use_llm, "degraded": not use_llm,
            "degrade_reason": None if use_llm else "E_RULES_MODE use_llm=false",
            "started_at": now_iso(), "steps": [], "suggestions": [], "category_notes": {},
            "report": "", "meta": {"llm_calls": 0, "elapsed_ms": 0},
            "params": {"n01_main_share": float(rules.n01_main_share())},
        }
        self.done_listings: set[str] = set()

    # ------------------------------------------------------------------ 工具 / 模型
    def tool(self, name: str, params: dict, by: str = "rules") -> dict:
        res = dispatch_tool(name, params, self.run_id)
        if name in TOOL_NAMES:
            with _RUNS_LOCK:
                self.state["steps"].append({
                    "seq": len(self.state["steps"]) + 1, "tool": name, "params": params,
                    "ok": res["ok"], "summary": res.get("summary") or res.get("reason", ""), "by": by,
                })
        return res

    def ask_model(self, purpose: str, messages: list[dict]) -> dict | None:
        """一次模型调用并解析 JSON；失败标记降级并返回 None。"""
        if not self.budget.usable():
            if self.budget.exhausted():
                self.budget.mark("E_LLM_BUDGET 模型调用次数已达上限")
            return None
        self.budget.calls += 1
        self.state["meta"]["llm_calls"] = self.budget.calls
        try:
            text = llm_gate.call_model(self.run_id, self.budget.calls, purpose, messages)
            return llm_gate.json_object(text)
        except llm_gate.LLMUnavailable as exc:
            code = "E_LLM_TIMEOUT" if getattr(exc, "timed_out", False) else "E_LLM_UNAVAILABLE"
            self.budget.mark(f"{code} {purpose}：{exc}")
        except ValueError as exc:
            self.budget.mark(f"E_LLM_BAD_JSON {purpose}：{exc}")
        except Exception as exc:  # noqa: BLE001
            self.budget.mark(f"E_LLM_ERROR {purpose}：{exc.__class__.__name__}")
        return None

    # ------------------------------------------------------------------ 建议
    def add(self, rule_id: str, scope: dict, action: str, hit: dict, ctx: dict, *, preview: dict | None = None) -> dict:
        lid = scope["listing_id"]
        sug = {
            "suggestion_id": f"{rule_id}-{lid}",
            "rule_id": rule_id,
            "scope": scope,
            "action": action,
            "needs_manual_review": bool(hit.get("needs_manual_review", False)),
            "rules": list(rules.RULE_CODES[rule_id]),
            "evidence": {"metrics": [dict(m) for m in hit["metrics"]], "review_ids": []},
            "explanation": rules.explanation(rule_id, hit, ctx),
        }
        if action == "price_change":
            sug["current_price"] = hit["current_price"]
            sug["proposed_price"] = hit["proposed_price"]
            sug["change_pct"] = hit["change_pct"]
        if action != "none" and preview is not None:
            if preview.get("ok"):
                data = preview["data"]
                sug["preview_id"] = data["preview_id"]
                sug["preview"] = {"ok": True, "row": data["row"]}
            else:
                sug["preview_id"] = None
                sug["preview"] = {"ok": False, "row": None, "reject_reason": preview.get("reason")}
        with _RUNS_LOCK:
            self.state["suggestions"].append(sug)
        self.done_listings.add(lid)
        return sug

    def candidates(self) -> list[str]:
        return [lid for lid in metrics.store().online_listings(rules.AS_OF) if lid not in self.done_listings]

    # ------------------------------------------------------------------ 主流程
    def execute(self) -> None:
        st = metrics.store()

        # N-01：房东关房导致成交少 → 不调价（不处理，带证据与规则编号）
        res = self.tool("scan_owner_blocks", {"as_of": rules.AS_OF, "window": list(rules.Q3)})
        for hit in res.get("data") or []:
            lid = hit["listing_id"]
            x = st.listings[lid]
            self.add("N-01", {"district_id": x["district_id"], "community": x["community"], "listing_id": lid},
                     "none", hit, {})

        # P-01：人工上调已超幅度上限 → 一次回调申请（预览，不落表）
        res = self.tool("scan_raises_over_cap", {"as_of": rules.AS_OF})
        hits = [h for h in (res.get("data") or []) if h["listing_id"] not in self.done_listings]
        self.investigate(hits)
        for hit in hits:
            lid = hit["listing_id"]
            pv = self.tool("preview_price_change", {
                "listing_id": lid, "proposed_price": hit["proposed_price"], "reason": rules.reason_p01(hit),
                "evidence": {"metrics": hit["metrics"], "review_ids": []}})
            x = st.listings[lid]
            self.add("P-01", {"district_id": x["district_id"], "community": x["community"], "listing_id": lid},
                     "price_change", hit, {}, preview=pv)

        self.write_notes()
        self.write_report()

    # ------------------------------------------------------------------ P-01 排查（模型选工具，失败走固定顺序）
    def investigate(self, hits: list[dict]) -> None:
        if not hits:
            return
        ids = [h["listing_id"] for h in hits]
        history: list[dict] = []
        used_llm = False
        if self.budget.usable():
            plan = self.ask_model("P-01_investigate", self.investigate_prompt(hits, history))
            if plan is not None:
                used_llm = True
                calls = plan.get("calls") if isinstance(plan.get("calls"), list) else []
                for c in calls[:PER_CALL_TOOLS]:
                    if not isinstance(c, dict):
                        continue
                    name = str(c.get("tool") or "")
                    lid = str(c.get("listing_id") or "")
                    if name not in TOOL_NAMES:
                        # 清单外的名字：dispatch_tool 拒绝并入审计，不进 steps
                        dispatch_tool(name, {"listing_id": lid}, self.run_id)
                        continue
                    if name not in INVESTIGATE_TOOLS or lid not in ids:
                        continue
                    params = {"listing_id": lid}
                    if name not in ("price_now", "price_history"):
                        params.update({"start": rules.Q3[0], "end": rules.Q3[1]})
                    r = self.tool(name, params, by="llm")
                    history.append({"tool": name, "listing_id": lid, "summary": r.get("summary")})
        if used_llm:
            return
        # 规则模式：固定顺序（每类抽前 RULES_INVESTIGATE_SAMPLE 套）
        for lid in ids[:RULES_INVESTIGATE_SAMPLE]:
            for name in ("price_history", "listing_occupancy"):
                params = {"listing_id": lid}
                if name != "price_history":
                    params.update({"start": rules.Q3[0], "end": rules.Q3[1]})
                self.tool(name, params)

    def investigate_prompt(self, hits: list[dict], history: list[dict]) -> list[dict]:
        tool_lines = "\n".join(f"- {k}: {v}" for k, v in INVESTIGATE_TOOLS.items())
        situation = (f"程序已判定下列 {len(hits)} 套房源当前平日价相对上一档的人工上调幅度超过单次上限，"
                     f"处置（一次回调申请）已由规则确定。")
        sample = [{"listing_id": h["listing_id"], "current_price": h["current_price"],
                   "previous_price": h["previous_price"], "proposed_price": h["proposed_price"]} for h in hits[:INVESTIGATE_SAMPLE]]
        system = ("你是民宿托管公司的巡检助手。你不能决定处置，只能挑选还需要额外查看的证据。"
                  "只输出一个 JSON 对象，不要输出其他文字。格式："
                  '{"calls":[{"tool":"工具名","listing_id":"房源ID"}],"done":true或false}。'
                  f"calls 最多 {PER_CALL_TOOLS} 个；工具名只能从下列清单中选；listing_id 只能从给定房源中选；"
                  "不需要再查时 calls 为空数组、done 为 true。\n可用工具：\n" + tool_lines)
        user = situation + "\n房源：" + json.dumps(sample, ensure_ascii=False)
        if history:
            user += "\n已查结果：" + json.dumps(history, ensure_ascii=False)
        user += "\n请挑选最能帮助审批人判断的额外证据，选 1 到 2 个即可。直接输出 JSON，不要解释。"
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]

    # ------------------------------------------------------------------ 类别说明 / 报告
    def by_rule(self) -> dict[str, list[dict]]:
        out: dict[str, list[dict]] = {}
        for s in self.state["suggestions"]:
            out.setdefault(s["rule_id"], []).append(s)
        return out

    def trace_steps(self, groups: dict[str, list[dict]]) -> list[dict]:
        """可追溯检查的候选值：各类建议数、每个证据指标值、价格与幅度。"""
        steps = [{"columns": ["rule", "count"], "rows": [[k, len(v)] for k, v in groups.items()],
                  "row_count": len(groups)}]
        manual = sum(1 for s in self.state["suggestions"] if s["needs_manual_review"])
        steps.append({"columns": ["count"], "rows": [[len(self.state["suggestions"])], [manual]]})
        cols: dict[str, list] = {}
        for items in groups.values():
            for s in items:
                for m in s["evidence"]["metrics"]:
                    if isinstance(m["value"], (int, float)):
                        cols.setdefault(m["key"], []).append(m["value"])
                for k in ("current_price", "proposed_price", "change_pct"):
                    if isinstance(s.get(k), (int, float)):
                        cols.setdefault(k, []).append(s[k])
        for k, vals in cols.items():
            uniq = list(dict.fromkeys(vals))
            steps.append({"columns": [k], "rows": [[v] for v in uniq]})
        return steps

    def facts(self, groups: dict[str, list[dict]]) -> dict:
        out = {}
        for rid in rules.RULE_ORDER:
            items = groups.get(rid) or []
            if not items:
                continue
            first = items[0]
            out[rid] = {
                "类别": rules.RULE_TITLES[rid], "条数": len(items),
                "处置": {"price_change": "调价申请", "ticket": "整改工单", "none": "不处理"}[first["action"]],
                "示例": first["explanation"],
            }
            if rid == "P-01":
                out[rid]["需人工评估条数"] = sum(1 for s in items if s["needs_manual_review"])
        return out

    def check_text(self, text: str, limit: int, groups) -> str | None:
        """返回不合格原因；合格返回 None。"""
        if not isinstance(text, str) or not text.strip():
            return "E_EMPTY"
        if len(text) > limit:
            return "E_TOO_LONG"
        if MD_RE.search(text):
            return "E_MARKDOWN"
        bad = trace.untraceable_numbers(text, ALLOWED_CONSTANTS, self.trace_steps(groups))
        if bad:
            return "E_UNTRACEABLE_NUMBER " + "、".join(bad[:5])
        return None

    def write_notes(self) -> None:
        groups = self.by_rule()
        templates = {rid: rules.note_template(rid, len(groups[rid])) for rid in rules.RULE_ORDER if groups.get(rid)}
        notes = None
        if self.budget.usable() and templates:
            system = ("你是民宿托管公司的运营同事。为每类巡检建议各写一句类别说明，给审批人看。"
                      f"每句不超过 {NOTE_MAX} 个字，纯文本，不用 Markdown，不用列表符号。"
                      "引用数字只能照抄给定材料中的数字，不要自己计算新数字；小数最多写两位，比例写成百分数。"
                      '只输出一个 JSON 对象，键为规则编号（如 "N-01"），值为这句说明。')
            user = "巡检材料：" + json.dumps(self.facts(groups), ensure_ascii=False)
            obj = self.ask_model("category_notes", [{"role": "system", "content": system},
                                                    {"role": "user", "content": user}])
            if obj is not None:
                cand = {rid: str(obj.get(rid) or "").strip() for rid in templates}
                problems = [p for p in (self.check_text(cand[rid], NOTE_MAX, {rid: groups[rid]}) for rid in templates) if p]
                if problems:
                    self.budget.reasons.append(problems[0] + "（category_notes 已换模板）")
                else:
                    notes = cand
        elif self.budget.exhausted() and templates:
            self.budget.mark("E_LLM_BUDGET 模型调用次数已达上限")
        self.state["category_notes"] = notes or templates
        self.notes_by_llm = notes is not None

    def write_report(self) -> None:
        groups = self.by_rule()
        counts = {rid: len(v) for rid, v in groups.items()}
        manual = sum(1 for s in self.state["suggestions"] if s["needs_manual_review"])
        template = rules.report_template(counts, manual, len(self.state["suggestions"]))
        report = None
        if self.budget.usable():
            system = ("你是民宿托管公司的运营同事，给运营负责人（审批人）写一份巡检报告。"
                      f"不超过 {REPORT_MAX} 个字，纯文本，一到三段，不用 Markdown、标题、列表符号或表格。"
                      "先说结论，再按类别说清楚建议做什么、为什么、哪些需人工评估。"
                      "引用数字只能照抄给定材料中的数字，不要自己计算新数字；小数最多写两位，比例写成百分数。"
                      '只输出一个 JSON 对象：{"report":"报告正文"}。')
            payload = {"巡检日期": rules.AS_OF, "建议总数": len(self.state["suggestions"]),
                       "需人工评估条数": manual, "各类": self.facts(groups),
                       "类别说明": self.state["category_notes"]}
            obj = self.ask_model("report", [{"role": "system", "content": system},
                                            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}])
            if obj is not None:
                text = str(obj.get("report") or "").strip()
                problem = self.check_text(text, REPORT_MAX, groups)
                if problem:
                    self.budget.reasons.append(problem + "（report 已换模板）")
                else:
                    report = text
        elif self.budget.exhausted():
            self.budget.mark("E_LLM_BUDGET 模型调用次数已达上限")
        self.state["report"] = report or template
        self.report_by_llm = report is not None

    # ------------------------------------------------------------------ 收尾
    def finish(self, error: str | None = None) -> None:
        b = self.budget
        llm_steps = any(s["by"] == "llm" for s in self.state["steps"])
        used_llm_text = getattr(self, "notes_by_llm", False) or getattr(self, "report_by_llm", False)
        degraded = (not b.enabled) or bool(b.reasons)
        with _RUNS_LOCK:
            self.state["degraded"] = degraded
            self.state["degrade_reason"] = "；".join(b.reasons) if degraded else None
            self.state["mode"] = "agent" if (b.enabled and (llm_steps or used_llm_text)) else "rules"
            self.state["meta"] = {"llm_calls": b.calls, "elapsed_ms": int((time.perf_counter() - self.t0) * 1000),
                                  "suggestions": len(self.state["suggestions"])}
            if error:
                self.state["error"] = error
            self.state["state"] = "ready"
            self.state["finished_at"] = now_iso()


def _worker(run: Run) -> None:
    try:
        run.execute()
        run.finish()
    except Exception as exc:  # noqa: BLE001 - 兜底：已产出的建议保留，报告用模板，仍以 ready 结束
        run.budget.reasons.append(f"E_INTERNAL {exc.__class__.__name__}: {exc}")
        try:
            if not run.state.get("report"):
                groups = run.by_rule()
                run.state["category_notes"] = {rid: rules.note_template(rid, len(v)) for rid, v in groups.items()}
                run.state["report"] = rules.report_template({k: len(v) for k, v in groups.items()},
                                                            sum(1 for s in run.state["suggestions"] if s["needs_manual_review"]),
                                                            len(run.state["suggestions"]))
        finally:
            run.finish(error=f"{exc.__class__.__name__}: {exc}")


def start(use_llm: bool) -> str:
    run_id = "run-" + datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    run = Run(run_id, use_llm)
    with _RUNS_LOCK:
        RUNS[run_id] = run.state
    threading.Thread(target=_worker, args=(run,), name=f"agent-{run_id}", daemon=True).start()
    return run_id


def run_sync(use_llm: bool) -> dict:
    """同步跑一次（自证脚本用）。"""
    run_id = "run-" + datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    run = Run(run_id, use_llm)
    with _RUNS_LOCK:
        RUNS[run_id] = run.state
    _worker(run)
    return run.state


def snapshot(run_id: str) -> dict | None:
    with _RUNS_LOCK:
        st = RUNS.get(run_id)
        if st is None:
            return None
        return json.loads(json.dumps(st, ensure_ascii=False, default=str))
