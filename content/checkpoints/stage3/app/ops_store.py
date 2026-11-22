"""待审批库 data/ops.db：唯一可写的库，只由本模块打开。

- 三张业务 / 审计表的 DDL 取自 homestay.db 同名表（只读连接查 sqlite_master），去掉 REFERENCES。
- 写入只走 preview → commit（人）→ decision（人）。
- 校验只覆盖两条规则：P-01 单次调价幅度上限、N-01 不调价情形（房东关房）。
  N-01 的量化参数与巡检扫描共用同一份配置（`app/config.py`），改一处两边同时生效。
- `python -m app.ops_store --reset` 删除并重建 ops.db。
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import threading
import uuid
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction

from app.config import ROOT, settings
from app.tools import metrics

OPS_DB = ROOT / "data" / "ops.db"
OUTBOX = ROOT / "outbox"
BUSINESS_TABLES = ("price_change_requests", "maintenance_tickets")
OPS_TABLES = ("price_change_requests", "maintenance_tickets", "audit_log")
OPEN_STATUSES = ("待审", "批准")
APPROVER = "演示审批人"
AS_OF = "2026-09-30"
Q3 = ("2026-07-01", "2026-09-30")
MAX_PCT = Decimal("0.15")                 # 手册 P-01：单次调价幅度上限 15%

_LOCK = threading.RLock()
_REF_RE = re.compile(r"\s+REFERENCES\s+\w+\s*\([^)]*\)", re.IGNORECASE)
_PREVIEW_DDL = (
    "CREATE TABLE IF NOT EXISTS previews (preview_id TEXT PRIMARY KEY, kind TEXT NOT NULL, "
    "payload TEXT NOT NULL, row TEXT NOT NULL, created_at TEXT NOT NULL, committed INTEGER NOT NULL DEFAULT 0)"
)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def source_ddl() -> dict[str, str]:
    """homestay.db 中三张同名表的 DDL（去掉 REFERENCES）。"""
    con = metrics.connect_ro()
    try:
        rows = dict(con.execute(
            "SELECT name, sql FROM sqlite_master WHERE type = 'table' AND name IN (?, ?, ?)", OPS_TABLES
        ))
    finally:
        con.close()
    return {name: _REF_RE.sub("", rows[name]) for name in OPS_TABLES}


def _connect() -> sqlite3.Connection:
    OPS_DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(OPS_DB, timeout=10, check_same_thread=False)
    con.row_factory = sqlite3.Row
    existing = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if not set(OPS_TABLES) <= existing:
        for name, ddl in source_ddl().items():
            if name not in existing:
                con.execute(ddl)
    con.execute(_PREVIEW_DDL)
    con.commit()
    return con


def reset() -> None:
    """删除并重建 ops.db（验收用）。"""
    with _LOCK:
        for suffix in ("", "-journal", "-wal", "-shm"):
            p = OPS_DB.with_name(OPS_DB.name + suffix)
            if p.exists():
                p.unlink()
        _connect().close()


# ---------------------------------------------------------------- 审计
def audit(tool_name: str, params: dict, result: dict) -> None:
    """audit_log 写一行。"""
    with _LOCK:
        con = _connect()
        try:
            con.execute(
                "INSERT INTO audit_log (ts, tool_name, params, result) VALUES (?, ?, ?, ?)",
                (now_iso(), str(tool_name), json.dumps(params, ensure_ascii=False, default=str),
                 json.dumps(result, ensure_ascii=False, default=str)),
            )
            con.commit()
        finally:
            con.close()


def audit_rows(run_id: str | None = None) -> list[dict]:
    with _LOCK:
        con = _connect()
        try:
            rows = [dict(r) for r in con.execute("SELECT * FROM audit_log ORDER BY log_id")]
        finally:
            con.close()
    if run_id:
        out = []
        for r in rows:
            try:
                if json.loads(r["params"]).get("run_id") == run_id:
                    out.append(r)
            except (ValueError, AttributeError):
                continue
        rows = out
    return rows


# ---------------------------------------------------------------- 校验（两条规则 + 输入校验，单一函数）
def pct_change(current: int, proposed: int) -> Decimal:
    """change_pct = proposed ÷ current − 1，四舍五入到 4 位。"""
    return (Decimal(proposed) / Decimal(current) - 1).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def allow_low(current: int) -> int:
    """上限内允许的最低价（降 15%，向上取整，保证幅度不超过上限）。"""
    return (current * 85 + 99) // 100


def allow_high(current: int) -> int:
    """上限内允许的最高价（涨 15%，向下取整）。"""
    return (current * 115) // 100


def owner_block_share(listing_id: str) -> Fraction | None:
    st = metrics.store()
    cal = st.r12(listing_id, *Q3)["calendar_nights"]
    if not cal:
        return None
    return Fraction(sum(st.r13(listing_id, *Q3).values()), cal)


def n01_main_share() -> Fraction:
    """与 `app.agent.rules` 共用的 N-01 参数（取自同一份配置）。"""
    return Fraction(Decimal(repr(settings.n01_main_share)))


def in_n01(listing_id: str) -> bool:
    """N-01 名单条件：房东关房晚数 ÷ 日历晚数 ≥ 参数（配置里可改）。"""
    share = owner_block_share(listing_id)
    return share is not None and share >= n01_main_share()


def _open_count(con: sqlite3.Connection, table: str, listing_id: str, issue_type: str | None = None) -> int:
    sql = f"SELECT COUNT(*) FROM {table} WHERE listing_id = ? AND status IN ('待审', '批准')"
    args: list = [listing_id]
    if issue_type is not None:
        sql += " AND issue_type = ?"
        args.append(issue_type)
    return con.execute(sql, args).fetchone()[0]


def _as_text(value) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value if value is not None else {}, ensure_ascii=False, default=str)


def validate(payload: dict, con: sqlite3.Connection) -> dict:
    """按当时库状态跑校验。返回 {ok, reject_reason?, rules?, row?}。preview 与 commit 共用。

    两规则版只剩两条业务校验：V1 幅度上限（P-01）、V2 不调价情形（N-01）；
    另有写入路径的输入校验（房源存在、幅度为正整数、工单问题类型在 F-01 七类内、防重复提交）。
    """
    kind = payload.get("kind")
    listing_id = str(payload.get("listing_id") or "")
    st = metrics.store()
    fails: list[tuple[str, str]] = []
    if kind not in ("price_change", "ticket"):
        return {"ok": False, "reject_reason": "E_PARAM kind 须为 price_change 或 ticket", "rules": []}
    if not st.exists(listing_id):  # 输入校验：房源必须在业务库里
        return {"ok": False, "reject_reason": f"E_LISTING 房源 {listing_id or '(空)'} 不存在", "rules": []}
    created = now_iso()

    if kind == "ticket":
        issue_type = str(payload.get("issue_type") or "")
        if issue_type not in metrics.ISSUE_TYPES:  # 输入校验：手册 F-01 的七类
            fails.append(("F-01", f"问题类型“{issue_type}”不在 F-01 七类内"))
        elif _open_count(con, "maintenance_tickets", listing_id, issue_type):  # 手册 F-02：不重复开单
            fails.append(("F-02", "同一房源同一问题已有未关闭工单，不重复开单"))
        row = {"listing_id": listing_id, "issue_type": issue_type,
               "evidence": _as_text(payload.get("evidence")), "status": "待审", "created_at": created}
    else:
        price = st.r16(listing_id, AS_OF)
        try:
            proposed = int(payload.get("proposed_price"))
            if proposed <= 0 or str(proposed) != str(payload.get("proposed_price")).strip().split(".")[0]:
                raise ValueError
        except (TypeError, ValueError):
            return {"ok": False, "reject_reason": "E_PARAM proposed_price 须为正整数", "rules": []}
        if price is None:
            return {"ok": False, "reject_reason": "E_LISTING 房源无当前价格", "rules": []}
        current = price["current_price"]
        pct = pct_change(current, proposed)
        if abs(pct) > MAX_PCT:  # V1（手册 P-01）
            fails.append(("P-01", f"调价幅度 {float(pct) * 100:.2f}% 超过单次上限 15%"
                                  f"（允许范围 ±15%，即 {allow_low(current)}–{allow_high(current)} 元）"))
        if proposed < current and in_n01(listing_id):  # V2（手册 N-01）
            fails.append(("N-01", f"房东关房占比 {float(owner_block_share(listing_id) or 0) * 100:.1f}% "
                                  f"不低于参数 {float(n01_main_share()) * 100:.1f}%，不许降价"))
        if _open_count(con, "price_change_requests", listing_id):  # V3（P-01 的防叠加半边）
            fails.append(("P-01", "已有未关闭的调价申请，不得叠加申请（叠加等于超过单次上限）"))
        row = {"listing_id": listing_id, "current_price": current, "proposed_price": proposed,
               "change_pct": float(pct), "reason": str(payload.get("reason") or ""),
               "evidence": _as_text(payload.get("evidence")), "status": "待审", "approver": None,
               "created_at": created}

    if fails:
        codes = []
        for code, _msg in fails:
            if code not in codes:
                codes.append(code)
        return {"ok": False, "reject_reason": "；".join(f"{c} {m}" for c, m in fails), "rules": codes, "row": row}
    return {"ok": True, "row": row, "rules": []}


# ---------------------------------------------------------------- 预览 / 提交 / 审批
def preview(payload: dict) -> dict:
    """跑全部校验；通过则存一条预览（不写两张业务表）。"""
    with _LOCK:
        con = _connect()
        try:
            res = validate(payload, con)
            if not res["ok"]:
                return res
            pid = "pv-" + uuid.uuid4().hex[:12]
            con.execute(
                "INSERT INTO previews (preview_id, kind, payload, row, created_at) VALUES (?, ?, ?, ?, ?)",
                (pid, payload["kind"], json.dumps(payload, ensure_ascii=False, default=str),
                 json.dumps(res["row"], ensure_ascii=False), now_iso()),
            )
            con.commit()
            return {"ok": True, "preview_id": pid, "row": res["row"]}
        finally:
            con.close()


def commit(preview_ids: list[str]) -> dict:
    """按批内顺序（先全部工单、后全部调价）逐条重跑校验并生效。"""
    committed, rejected = [], []
    with _LOCK:
        con = _connect()
        try:
            found = []
            for pid in preview_ids:
                rec = con.execute("SELECT * FROM previews WHERE preview_id = ?", (str(pid),)).fetchone()
                found.append((str(pid), rec))
            ordered = [x for x in found if x[1] is not None and x[1]["kind"] == "ticket"] + \
                      [x for x in found if x[1] is not None and x[1]["kind"] == "price_change"]
            for pid, rec in found:
                if rec is None:
                    rejected.append({"preview_id": pid, "reason": "E_PREVIEW 未知的 preview_id"})
            for pid, _rec in ordered:
                rec = con.execute("SELECT * FROM previews WHERE preview_id = ?", (pid,)).fetchone()
                if rec["committed"]:
                    rejected.append({"preview_id": pid, "reason": "E_PREVIEW 该预览已提交过"})
                    continue
                payload = json.loads(rec["payload"])
                res = validate(payload, con)
                if not res["ok"]:
                    rejected.append({"preview_id": pid, "reason": res["reject_reason"]})
                    continue
                row = res["row"]
                if rec["kind"] == "ticket":
                    cur = con.execute(
                        "INSERT INTO maintenance_tickets (listing_id, issue_type, evidence, status, created_at) "
                        "VALUES (?, ?, ?, '待审', ?)",
                        (row["listing_id"], row["issue_type"], row["evidence"], row["created_at"]),
                    )
                else:
                    cur = con.execute(
                        "INSERT INTO price_change_requests (listing_id, current_price, proposed_price, change_pct, "
                        "reason, evidence, status, approver, created_at) VALUES (?, ?, ?, ?, ?, ?, '待审', NULL, ?)",
                        (row["listing_id"], row["current_price"], row["proposed_price"], row["change_pct"],
                         row["reason"], row["evidence"], row["created_at"]),
                    )
                con.execute("UPDATE previews SET committed = 1 WHERE preview_id = ?", (pid,))
                committed.append({"kind": rec["kind"], "id": cur.lastrowid, "preview_id": pid})
            con.commit()
        finally:
            con.close()
    return {"committed": committed, "rejected": rejected}


def items() -> dict:
    with _LOCK:
        con = _connect()
        try:
            return {
                "price_change_requests": [dict(r) for r in con.execute(
                    "SELECT * FROM price_change_requests ORDER BY request_id")],
                "maintenance_tickets": [dict(r) for r in con.execute(
                    "SELECT * FROM maintenance_tickets ORDER BY ticket_id")],
            }
        finally:
            con.close()


class DecisionError(Exception):
    def __init__(self, status: int, message: str) -> None:
        self.status = status
        super().__init__(message)


def decision(kind: str, item_id, verdict: str) -> dict:
    """待审 → 批准 / 驳回。工单批准生成 outbox 邮件草稿。"""
    if verdict not in ("approve", "reject"):
        raise DecisionError(422, "decision 须为 approve 或 reject")
    if kind not in ("price_change", "ticket"):
        raise DecisionError(422, "kind 须为 price_change 或 ticket")
    try:
        item_id = int(item_id)
    except (TypeError, ValueError):
        raise DecisionError(422, "id 须为整数") from None
    status = "批准" if verdict == "approve" else "驳回"
    with _LOCK:
        con = _connect()
        try:
            if kind == "price_change":
                row = con.execute("SELECT * FROM price_change_requests WHERE request_id = ?", (item_id,)).fetchone()
            else:
                row = con.execute("SELECT * FROM maintenance_tickets WHERE ticket_id = ?", (item_id,)).fetchone()
            if row is None:
                raise DecisionError(404, "记录不存在")
            if row["status"] != "待审":
                raise DecisionError(409, f"当前状态为“{row['status']}”，只有待审可决策")
            if kind == "price_change":
                con.execute("UPDATE price_change_requests SET status = ?, approver = ? WHERE request_id = ?",
                            (status, APPROVER, item_id))
            else:
                con.execute("UPDATE maintenance_tickets SET status = ? WHERE ticket_id = ?", (status, item_id))
            outbox_path = None
            if kind == "ticket" and verdict == "approve":
                outbox_path = write_notice(dict(row))
            con.commit()
        finally:
            con.close()
    out = {"ok": True, "kind": kind, "id": item_id, "status": status}
    if outbox_path:
        out["outbox"] = outbox_path
    return out


def write_notice(ticket: dict) -> str:
    """工单批准 → outbox/ 下生成一封给房东的通知邮件草稿（.eml，本地文件，不发送）。"""
    st = metrics.store()
    lid = ticket["listing_id"]
    listing = st.listings[lid]
    email = st.owner_email.get(listing["owner_id"], "")
    try:
        evidence = json.loads(ticket["evidence"] or "{}")
    except ValueError:
        evidence = {}
    review_ids = evidence.get("review_ids") or []
    lines_metrics = []
    for m in evidence.get("metrics") or []:
        if isinstance(m, dict) and "key" in m:
            lines_metrics.append(f"  - {m['key']} = {m.get('value')}（{m.get('ref')}）")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    OUTBOX.mkdir(parents=True, exist_ok=True)
    path = OUTBOX / f"ticket-{ticket['ticket_id']}-{lid}-{stamp}.eml"
    body = "\n".join([
        f"To: {email}",
        "From: ops@homestay.example",
        f"Subject: =?utf-8?B?{_b64(f'【整改通知】房源 {lid} · {ticket['issue_type']}')}?=",
        "Content-Type: text/plain; charset=utf-8",
        "X-Draft: true（草稿，仅生成到本地 outbox，不发送）",
        "",
        f"房东 {listing['owner_id']} 您好：",
        "",
        f"您托管的房源 {lid}（{listing['community']}）近期评论集中反映“{ticket['issue_type']}”问题，"
        f"运营已批准整改工单 #{ticket['ticket_id']}（F-02、F-03）。",
        "",
        f"房源 ID：{lid}",
        f"问题类型：{ticket['issue_type']}",
        "证据评论 ID：" + ("、".join(review_ids) if review_ids else "（无）"),
        "证据指标：",
        *(lines_metrics or ["  - （无）"]),
        "",
        "请在一个月内完成整改，届时运营将复查对应评分与评论主题占比。",
        "",
        "—— 托管运营团队（模拟数据，演示用草稿）",
        "",
    ])
    path.write_text(body, encoding="utf-8")
    return str(path.relative_to(ROOT)).replace("\\", "/")


def _b64(text: str) -> str:
    import base64
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ops.db 管理")
    parser.add_argument("--reset", action="store_true", help="删除并重建 data/ops.db")
    args = parser.parse_args(argv)
    if args.reset:
        reset()
        print(f"已重建 {OPS_DB.relative_to(ROOT)}（{', '.join(OPS_TABLES)}）")
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
