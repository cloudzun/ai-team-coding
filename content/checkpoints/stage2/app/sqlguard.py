"""只读 SQL 执行入口：G1–G7。

规格第 2.5 / 3.3 节。`/api/ask` 执行的每条模型 SQL 都必须经过 `run_readonly`。

- G1 单语句：去掉末尾分号后只有一条（引号/注释内的分号不算）。
- G2 必须以 SELECT 或 WITH 开头。
- G3 不含写关键字（按词边界、大小写不敏感；注释与字符串内的不算）。
- G4 只引用业务表：连接上装 authorizer，读到非业务表即拒。
- G5 authorizer 只放行 SELECT / READ / FUNCTION(非 load_extension) / RECURSIVE。
- G6 set_progress_handler 超时中断。
- G7 最多取 max_rows 行，多余不取，truncated=true。

连接一律 `mode=ro` + `PRAGMA query_only`，不会在仓库或临时目录生成 db/journal/wal。
"""
from __future__ import annotations

import re
import sqlite3
import time
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "homestay.db"

# 9 张业务表（3 张写入表：audit_log / maintenance_tickets / price_change_requests 之外）
ALLOWED_TABLES = frozenset(
    {
        "bookings",
        "districts",
        "listings",
        "market_benchmark",
        "meta",
        "owner_blocks",
        "owners",
        "price_history",
        "reviews",
    }
)

FORBIDDEN_KEYWORDS = (
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "ALTER",
    "CREATE",
    "REPLACE",
    "ATTACH",
    "DETACH",
    "PRAGMA",
    "VACUUM",
    "REINDEX",
)
_KEYWORD_RE = re.compile(r"\b(" + "|".join(FORBIDDEN_KEYWORDS) + r")\b", re.IGNORECASE)

# sqlite3 常量（老版本 Python 可能未导出，用 SQLite 头文件里的数值兜底）
_A_SELECT = getattr(sqlite3, "SQLITE_SELECT", 21)
_A_READ = getattr(sqlite3, "SQLITE_READ", 20)
_A_FUNCTION = getattr(sqlite3, "SQLITE_FUNCTION", 31)
_A_RECURSIVE = getattr(sqlite3, "SQLITE_RECURSIVE", 33)
_OK = getattr(sqlite3, "SQLITE_OK", 0)
_DENY = getattr(sqlite3, "SQLITE_DENY", 1)

_EXTRA_FORBIDDEN = frozenset(
    {"sqlite_master", "sqlite_schema", "sqlite_temp_master", "sqlite_temp_schema"}
)

_denied_objects: frozenset[str] | None = None


class SqlRejected(Exception):
    """防护拒绝。code 为 E_MULTI / E_NOT_SELECT / E_KEYWORD / E_TABLE / E_AUTH。"""

    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        self.message = message or code
        super().__init__(f"{code}: {self.message}")


class SqlTimeout(Exception):
    """执行超时（被 progress handler 中断）。"""


class SqlError(Exception):
    """SQL 本身写错了（语法 / 不存在的列等），可交给模型修一次。"""


def disallowed_objects() -> frozenset[str]:
    """库里所有非业务表对象（含 sqlite_master 系列）；CTE 别名不在其中，因此不会被误杀。"""
    global _denied_objects
    if _denied_objects is None:
        names: set[str] = set(_EXTRA_FORBIDDEN)
        try:
            con = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True)
            try:
                names.update(
                    r[0].lower()
                    for r in con.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")
                )
            finally:
                con.close()
        except sqlite3.Error:
            pass
        _denied_objects = frozenset(names - {t.lower() for t in ALLOWED_TABLES})
    return _denied_objects


# ---------------------------------------------------------------- 切分与掩码
def _scan(sql: str) -> tuple[str, list[tuple[int, int]]]:
    """返回 (掩码后的 SQL, 每条语句在原串里的 [start, end))。

    掩码：字符串字面量、带引号标识符、注释全部替换成空格，长度与原串一一对应。
    顶层分号仍然是分号，用于切分语句。
    """
    masked = list(sql)
    spans: list[tuple[int, int]] = []
    i, n, start = 0, len(sql), 0
    while i < n:
        ch = sql[i]
        if ch in ("'", '"', "`"):
            j = i + 1
            while j < n:
                if sql[j] == ch:
                    if j + 1 < n and sql[j + 1] == ch:
                        j += 2
                        continue
                    break
                j += 1
            end = min(j + 1, n)
            for k in range(i, end):
                masked[k] = " "
            i = end
            continue
        if ch == "[":
            j = sql.find("]", i + 1)
            end = n if j < 0 else j + 1
            for k in range(i, end):
                masked[k] = " "
            i = end
            continue
        if sql.startswith("--", i):
            j = sql.find("\n", i)
            end = n if j < 0 else j
            for k in range(i, end):
                masked[k] = " "
            i = end
            continue
        if sql.startswith("/*", i):
            j = sql.find("*/", i + 2)
            end = n if j < 0 else min(j + 2, n)
            for k in range(i, end):
                masked[k] = " "
            i = end
            continue
        if ch == ";":
            spans.append((start, i))
            start = i + 1
        i += 1
    spans.append((start, n))
    return "".join(masked), spans


def _check(sql: str) -> None:
    if not isinstance(sql, str) or not sql.strip():
        raise SqlRejected("E_NOT_SELECT", "SQL 为空")
    masked, spans = _scan(sql)
    parts = [(a, b) for a, b in spans if masked[a:b].strip()]
    if len(parts) > 1:  # G1
        raise SqlRejected("E_MULTI", "只允许一条语句")
    if not parts:
        raise SqlRejected("E_NOT_SELECT", "SQL 为空")
    body = masked[parts[0][0] : parts[0][1]].lstrip()
    head = body[:6].upper()
    if not (body[:6].upper() == "SELECT" or body[:4].upper() == "WITH"):  # G2
        raise SqlRejected("E_NOT_SELECT", "只允许 SELECT / WITH 查询")
    hit = _KEYWORD_RE.search(masked)  # G3
    if hit:
        raise SqlRejected("E_KEYWORD", f"不允许的关键字 {hit.group(1).upper()}")


# ---------------------------------------------------------------- 执行
def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True, timeout=5.0)
    con.execute("PRAGMA query_only=ON")
    return con


def run_readonly(sql: str, max_rows: int = 200, timeout_s: float = 5.0) -> dict:
    """执行一条只读 SQL。

    返回 {"columns": [...], "rows": [...], "row_count": int, "truncated": bool}。
    被拒绝抛 SqlRejected(code)；超时抛 SqlTimeout；SQL 写错抛 SqlError。
    """
    _check(sql)  # G1 G2 G3

    denied: dict[str, str] = {}

    def authorizer(action: int, arg1, arg2, dbname, source):  # noqa: ANN001
        if action in (_A_SELECT, _A_RECURSIVE):
            return _OK
        if action == _A_READ:
            name = (arg1 or "").lower()
            if name in disallowed_objects():  # G4
                denied.setdefault("code", "E_TABLE")
                denied.setdefault("detail", str(arg1))
                return _DENY
            return _OK
        if action == _A_FUNCTION:
            if (arg2 or "").lower() == "load_extension":
                denied.setdefault("code", "E_AUTH")
                denied.setdefault("detail", "load_extension")
                return _DENY
            return _OK
        denied.setdefault("code", "E_AUTH")  # G5
        denied.setdefault("detail", f"action={action} {arg1 or ''}")
        return _DENY

    con = _connect()
    try:
        con.set_authorizer(authorizer)
        deadline = time.monotonic() + max(0.1, timeout_s)

        def guard() -> int:  # G6
            return 1 if time.monotonic() > deadline else 0

        con.set_progress_handler(guard, 1000)
        try:
            cur = con.execute(sql)
            columns = [d[0] for d in (cur.description or [])]
            fetched = cur.fetchmany(max_rows + 1)  # G7
        except sqlite3.OperationalError as exc:
            msg = str(exc)
            if "interrupted" in msg.lower():
                raise SqlTimeout(f"执行超过 {timeout_s:g}s 被中断") from None
            if denied:
                raise SqlRejected(denied.get("code", "E_AUTH"), denied.get("detail", msg)) from None
            raise SqlError(msg) from None
        except sqlite3.DatabaseError as exc:
            if denied:
                raise SqlRejected(denied.get("code", "E_AUTH"), denied.get("detail", "")) from None
            if "interrupted" in str(exc).lower():
                raise SqlTimeout(f"执行超过 {timeout_s:g}s 被中断") from None
            raise SqlError(str(exc)) from None
    finally:
        try:
            con.set_progress_handler(None, 0)
            con.set_authorizer(None)
        except sqlite3.Error:
            pass
        con.close()

    truncated = len(fetched) > max_rows
    rows = [_clean_row(r) for r in fetched[:max_rows]]
    return {
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "truncated": truncated,
    }


def _clean_row(row: tuple) -> list[Any]:
    out: list[Any] = []
    for v in row:
        if isinstance(v, (bytes, bytearray, memoryview)):
            out.append(bytes(v).hex())
        else:
            out.append(v)
    return out
