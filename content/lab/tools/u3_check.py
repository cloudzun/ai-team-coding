#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""u3_check.py -- 单元三（巡检 Agent）G2 前抽验：一条命令只查三件事，输出几行中文 PASS/FAIL。

课程材料（阶段三 单元三）。只用 Python 3.12 标准库；不起服务、只读打开两个库、只发 HTTP。

它查三件事（每件事一行）：
  1. 业务库指纹不变：把 --db 指向的业务库算 SHA-256，和 --before 里的基线比。
     **--db 要填产品运行时实际打开的那份业务库**（存档点与按书施工的产品是 data\\homestay.db；
     若产品直接读 kit\\db\\homestay.db 就填它）。
     基线文件直接用现成的 db_fingerprint.py 输出（`python db_fingerprint.py <库> > before.txt`），
     也认得只写了一个 64 位十六进制串、或用 `sha256:` 开头的文本文件。
  2. 运营库干净：三张写入表（调价申请、整改工单、审计日志）里，凡是有 status 列的表，状态值只能取：
     调价申请 —— 待审 / 批准 / 驳回 三个之一（三段流程不合并，所以没有第四个状态）；
     整改工单 —— 待审 / 批准 / 驳回 / 已完成（按存档点 DDL，手册 F-04 的复查闭环会用到“已完成”）。
     并且“已批准”的调价申请，幅度一律不超过运营手册 P-01 的单次上限 15%。
     三张表里**调价申请表 0 行**时判红（“运营库还没有任何调价申请”）：空表也能过，等于
     “什么都不做也算做完”；学员的 G2 步骤本来就要求先提交两条、批准一条。
     只看调价申请表而不看三表是否全空——本脚本第 3 项自己会往审计写一行，
     按“三表全 0”判的话，同一条命令第二次跑就会变绿。
  3. 超上限必被拒：向 --base 指的服务发一条调价请求，拟调价故意越过 15% 上限，
     必须被拒绝，且返回里带规则编号 P-01 与允许的价格范围（两个整数）。

== 最简用法（学员只跑这一行）==
    python u3_check.py --db <产品实际读的业务库> --ops <运营库> --base http://127.0.0.1:<端口> --before <开工前指纹> --record <运行目录>\\evidence\\user-check.md

  --record 把本次运行的命令行、三项 PASS/FAIL 与退出码，追加写进那份 user-check.md 的
  「## 1 命令与输出」一节（文件不存在就按骨架新建；「## 2 人眼」「## 3 结论」留给学员自己写）。
  检查命令自己写记录，学员只剩“看页面写人眼结论”这一件事。

== 用法 ==
  先确认产品实际读哪份业务库：**--db 就填那一份**——存档点与按书施工的产品是 data\\homestay.db；
  若产品直接读 kit\\db\\homestay.db，就填 kit\\db\\homestay.db。两份库初始内容相同，基线可以通用。

  抽验前先存基线（服务跑之前做一次就行）：
      python v2/lab/tools/db_fingerprint.py data\\homestay.db > before.txt
  G2 前一条命令：
      python v2/lab/tools/u3_check.py --db data\\homestay.db --ops data\\ops.db ^
          --base http://127.0.0.1:<端口> --before before.txt --record <运行目录>\\evidence\\user-check.md

  负向对照（夹具里有一条“已批准”的超限调价，必须判红）：
      python v2/lab/tools/u3_check.py --ops v2/lab/fixtures/u3/bad_ops.db ^
          --db data\\homestay.db --base http://127.0.0.1:<端口> --before before.txt ^
          --record <运行目录>\\evidence\\user-check.md

== 参数 ==
  --db      产品运行时**实际打开的那份**业务库（homestay.db）路径，只读打开；用来算指纹，
            也用来挑一套有当前价的房源发请求。存档点与按书施工的产品是 data\\homestay.db；
            若产品直接读 kit\\db\\homestay.db 就填它。填错库，指纹就守不住“业务库只读”这条。
  --ops     运营库（ops.db）路径，只读打开；查状态与已批准幅度，也用来避开已有未关闭申请的房源。
  --base    服务地址，例如 http://127.0.0.1:<端口>（端口示例用 8801，自己挑，起服务前确认没被占用）。
  --before  指纹基线文件（db_fingerprint.py 的输出）；缺了判红，所以先跑第一步存基线。
  --record  可选：把本次运行的命令行、三项 PASS/FAIL 与退出码，追加进这个 user-check.md
            的「## 1 命令与输出」一节；文件不存在就按骨架新建（2、3 节留空给学员）。
  --listing 可选：指定发请求用的房源编号；不给就按业务库里的在线房源自动挑（最多试 5 套）。
  --as-of   可选：巡检“当前日”，默认 2026-09-30（指标口径表 C-07 的数据截止日）。
  --timeout 可选：单次 HTTP 超时秒数，默认 8。

== 退出码 ==
  0 三件事都通过；1 至少一件不通过，或者参数/输入有问题（缺项也按不通过处理，见下）。

== 缺项也算不通过 ==
  --db / --ops / --base / --before 少给任何一个，对应那一段打印“未检查”，最后结论判不通过。
  这样一条命令就能当门禁用：四项都给齐，才是真的把三件事都查过了。

== 不打印什么 ==
  不打印运营库整行内容、不逐个列出房源清单；失败时只说表名、行号、状态值，
  通过时只说允许范围与那一条越界请求的两个整数（G2 抽验记录里要据此写 user-check.md）。
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import urllib.error
import urllib.request
from datetime import datetime
from fractions import Fraction
from pathlib import Path

HEX64 = re.compile(r"\b[0-9a-fA-F]{64}\b")
WRITE_TABLES = ("price_change_requests", "maintenance_tickets", "audit_log")
# 状态域按表分别定（lead 2026-11-21 裁定）：
#   调价申请只有三段（预览 → 人提交 → 人批准/驳回），所以状态只有三值；
#   整改工单以存档点 DDL 为准，CHECK 里还允许“已完成”（手册 F-04 的复查闭环会用到关闭状态），
#   不把正常实现误伤成红。
ALLOWED_STATUS = {
    "price_change_requests": ("待审", "批准", "驳回"),
    "maintenance_tickets": ("待审", "批准", "驳回", "已完成"),
}
MAX_PCT = Fraction(15, 100)          # 运营手册 P-01：单次调价幅度上限 15%（涨或降都算）
DEFAULT_AS_OF = "2026-09-30"         # 指标口径表 C-07：数据截止日


def setup_stdio() -> None:
    """中文输出不乱码：跟 db_fingerprint.py 一样，控制台交给宿主编码，重定向时兜底。"""
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None:
            continue
        try:
            enc = (getattr(stream, "encoding", "") or "").lower()
            if getattr(stream, "isatty", lambda: False)():
                stream.reconfigure(errors="replace")
                continue
            try:
                "中文".encode(enc)
                stream.reconfigure(errors="replace")
            except Exception:
                stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


# ---------------------------------------------------------------- 小工具

def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    import hashlib

    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def read_baseline(path: Path) -> str | None:
    """从基线文件里取 sha256。

    兼容四种情况：db_fingerprint.py 的输出（含 `sha256:` 行）、只写了 64 位十六进制、
    文件被不同终端重定向成 GBK / UTF-16、以及最后一个 64 位串出现在别的说明文字里。
    """
    raw = path.read_bytes()
    texts: list[str] = []
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        texts.append(raw.decode("utf-16", errors="replace"))
    texts.append(raw.decode("utf-8-sig", errors="replace").replace("\x00", ""))
    try:
        texts.append(raw.decode("gbk").replace("\x00", ""))
    except UnicodeDecodeError:
        pass
    for text in texts:
        for line in text.splitlines():
            s = line.strip()
            if s.lower().startswith("sha256:"):
                value = s.split(":", 1)[1].strip().lower()
                if HEX64.fullmatch(value):
                    return value
        m = HEX64.search(text)
        if m:
            return m.group(0).lower()
    return None


def open_ro(db_path: Path) -> sqlite3.Connection:
    """只读打开（mode=ro + query_only 双保险），不写任何东西。"""
    try:
        uri = db_path.resolve().as_uri() + "?mode=ro"
    except ValueError:
        uri = "file:" + db_path.resolve().as_posix() + "?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.execute("PRAGMA query_only = ON")
    con.execute("SELECT count(*) FROM sqlite_master").fetchone()
    return con


def table_columns(con: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in con.execute(f"PRAGMA table_info({table})")]


# ---------------------------------------------------------------- 检查 1：业务库指纹

def check_fingerprint(db: Path, before: Path | None) -> tuple[bool, str]:
    if not db.is_file():
        return False, f"找不到业务库 {db}"
    digest = sha256_file(db)
    short = digest[:12]
    if before is None:
        return False, "未检查（没给 --before 基线；先跑 db_fingerprint.py 存一份）"
    if not before.is_file():
        return False, f"找不到指纹基线 {before}"
    want = read_baseline(before)
    if want is None:
        return False, f"基线文件里读不出 sha256：{before}"
    if want == digest:
        return True, f"与基线一致（sha256 前 12 位 {short}）"
    return False, f"已变（基线 {want[:12]}… 现在 {short}…）：跑过巡检后业务库不该有任何改动"


# ---------------------------------------------------------------- 检查 2：运营库

def check_ops(ops: Path | None) -> tuple[bool, str]:
    """三张写入表：零工作量（调价申请 0 行判红）+ 状态域 + 已批准调价的幅度上限。"""
    if ops is None:
        return False, "未检查（没给 --ops 运营库）"
    if not ops.is_file():
        return False, f"找不到运营库 {ops}（服务还没写过任何一次 ops 调用？）"
    try:
        con = open_ro(ops)
    except sqlite3.Error as exc:
        return False, f"打不开运营库（只读）{ops}：{exc}"
    try:
        names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        missing = [t for t in WRITE_TABLES if t not in names]
        if missing:
            return False, f"运营库里缺写入表：{'、'.join(missing)}"
        counts = {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in WRITE_TABLES}
        summary = "三表 " + "/".join(str(counts[t]) for t in WRITE_TABLES) + " 行（调价申请/整改工单/审计）"
        problems: list[str] = []

        # 2a 零工作量：调价申请表 0 行 = 还没按第 6 章提交过任何调价申请。
        #    空表也 PASS，等于“什么都不做也算做完”；学员 G2 步骤本就要求先提交两条、批准一条。
        #    只看调价申请表，不看三表是否全空：第 3 项（被拒的 preview）自己也会往审计写一行，
        #    若按“三表全 0”判，同一条命令第二次跑就会因为审计有行而变绿，零工作量照样能过；
        #    第 6 章 4.4 的判栏表写的也是“调价申请一条都没有”即判红。
        if counts["price_change_requests"] == 0:
            brief = "/".join(str(counts[t]) for t in WRITE_TABLES)
            return False, ("运营库还没有任何调价申请：先按第 6 章在页面提交两条、批准一条再跑"
                           f"（三表 {brief} 行）")

        # 2b 状态域：只有带 status 列的表才有这一项；取值范围按表定（见 ALLOWED_STATUS）
        for table, allowed in ALLOWED_STATUS.items():
            if "status" not in table_columns(con, table):
                problems.append(f"{table} 没有 status 列")
                continue
            marks = ", ".join("?" for _ in allowed)
            bad = con.execute(
                f"SELECT status, count(*) FROM {table} "
                f"WHERE status IS NULL OR status NOT IN ({marks}) GROUP BY status",
                allowed,
            ).fetchall()
            for status, n in bad:
                shown = "（空）" if status is None else str(status)
                problems.append(f"{table} 有 {n} 行状态是「{shown}」，只允许 {'/'.join(allowed)}")

        # 2c 已批准的调价：幅度不得超过 P-01 的 15%
        cols = table_columns(con, "price_change_requests")
        if {"current_price", "proposed_price", "status"} <= set(cols):
            rows = con.execute(
                "SELECT request_id, current_price, proposed_price, change_pct FROM "
                "price_change_requests WHERE status = '批准'"
            ).fetchall()
            over = []
            for rid, current, proposed, stored in rows:
                try:
                    current, proposed = int(current), int(proposed)
                except (TypeError, ValueError):
                    over.append((rid, "原价或拟调价不是整数"))
                    continue
                if current <= 0:
                    over.append((rid, "原价不是正数"))
                    continue
                pct = abs(Fraction(proposed, current) - 1)
                if pct > MAX_PCT:
                    # 只说行号与幅度，不打印金额明细
                    over.append((rid, f"幅度 {float(pct) * 100:.2f}% 超过 15%"))
            for rid, why in over:
                problems.append(f"已批准调价 #{rid} {why}（P-01）")
        else:
            problems.append("price_change_requests 缺 current_price/proposed_price/status 列")

        if problems:
            return False, "；".join(problems[:4]) + (f"；另有 {len(problems) - 4} 处" if len(problems) > 4 else "")
        return True, (summary + "；状态域合规（调价申请三值、整改工单含“已完成”），"
                      "已批准调价幅度都不超 15%")
    except sqlite3.Error as exc:
        return False, f"读运营库出错：{exc}"
    finally:
        con.close()


# ---------------------------------------------------------------- 检查 3：超上限必被拒

def pick_listing(db: Path, as_of: str, wanted: str | None) -> list[tuple[str, int]]:
    """挑当期在线、且有当前平日价的房源，返回 [(listing_id, 当前平日价)]（按编号排序）。

    只读打开业务库；返回清单而不是单个值，是为了某套房源恰好已有未关闭申请时能换一套再试。
    """
    try:
        con = open_ro(db)
    except sqlite3.Error:
        return []
    try:
        if wanted:
            rows = [wanted]
        else:
            rows = [r[0] for r in con.execute(
                "SELECT listing_id FROM listings WHERE online_date <= ? "
                "AND (offline_date IS NULL OR offline_date > ?) ORDER BY listing_id",
                (as_of, as_of),
            )]
        found: list[tuple[str, int]] = []
        for lid in rows:
            got = con.execute(
                "SELECT weekday_price FROM price_history WHERE listing_id = ? "
                "AND effective_date <= ? ORDER BY effective_date DESC LIMIT 1",
                (lid, as_of),
            ).fetchone()
            if got and int(got[0]) > 0:
                found.append((lid, int(got[0])))
        return found
    except sqlite3.Error:
        return []
    finally:
        con.close()


def post_json(base: str, path: str, payload: dict, timeout: float) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(base + path, data=data, method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - 只连学员自己的服务
        return json.loads(resp.read().decode("utf-8"))


def open_listings(ops: Path | None) -> set[str]:
    """运营库里已有“未关闭”申请的房源：这些房源再申请会被“不得叠加”拒绝，挑它们测不出上限。"""
    if ops is None or not ops.is_file():
        return set()
    try:
        con = open_ro(ops)
    except sqlite3.Error:
        return set()
    try:
        return {r[0] for r in con.execute(
            "SELECT listing_id FROM price_change_requests WHERE status IN ('待审', '批准')")}
    except sqlite3.Error:
        return set()
    finally:
        con.close()


def check_http(base: str, db: Path | None, ops: Path | None, as_of: str,
               wanted: str | None, timeout: float) -> tuple[bool, str]:
    if not base:
        return False, "未检查（没给 --base 服务地址）"
    if db is None or not db.is_file():
        return False, "未检查（要给 --db 业务库，才挑得出房源与当前价）"
    candidates = pick_listing(db, as_of, wanted)
    if not candidates:
        return False, f"未检查（业务库里找不到当期在线、有当前价的房源{('，' + wanted) if wanted else ''}）"
    busy = open_listings(ops)
    free = [c for c in candidates if c[0] not in busy] or candidates
    last = "没有试出结论"
    for lid, current in free[:5]:          # 最多试 5 套，避免一套房源的具体情况把整条判据卡死
        # 故意越过上限：涨到 floor(当前价 × 1.15) 再加 1 元，比 15% 多出一个最小单位
        high = (current * 115) // 100
        proposed = high + 1
        payload = {"kind": "price_change", "listing_id": lid, "proposed_price": proposed,
                   "reason": "G2 前抽验：故意送一条超上限的调价请求，预期被拒（P-01）",
                   "evidence": {"metrics": [{"key": "current_price", "value": current, "ref": "R16"}]}}
        try:
            res = post_json(base, "/api/ops/preview", payload, timeout)
        except urllib.error.HTTPError as exc:
            return False, f"服务返回 HTTP {exc.code}（预期是 200 + ok=false）"
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return False, f"连不上 {base}（服务没起？{exc.__class__.__name__}）"
        except ValueError as exc:
            return False, f"服务返回的不是 JSON：{exc}"

        reason = str(res.get("reject_reason") or "")
        rules = [str(r) for r in (res.get("rules") or [])]
        if res.get("ok") is True:
            return False, (f"竟然通过了：拟调价 {proposed} 元相对当前 {current} 元超过 15% 上限"
                           f"却没被拒（房源 {lid}）")
        nums = [int(x) for x in re.findall(r"\d+", reason)]
        want_low, want_high = (current * 85 + 99) // 100, high
        if "P-01" in rules and want_low in nums and want_high in nums:
            return True, (f"被拒，规则编号 P-01，允许范围 {want_low}–{want_high} 元"
                          f"（拟调价 {proposed} 元越界）")
        # 没拿到“规则编号 + 允许范围”：可能是这套房源已有未关闭申请、或服务端库里没有它，
        # 换一套再试；全都这样才判红。
        last = (f"被拒但没同时给出 P-01 与允许范围 {want_low}–{want_high} 元"
                f"（返回 rules={rules or '空'}，原因：{reason[:60] or '空'}）")
    return False, last


# ---------------------------------------------------------------- --record：写进 user-check.md

SECTION1_RE = re.compile(r"^##\s*1(?![0-9])", re.M)
SECTION2_RE = re.compile(r"^##\s*2(?![0-9])", re.M)
RECORD_NOTE = "> 本节由检查命令自动生成，不要手改。"
RECORD_SKELETON = (
    "# 用户抽验记录\n"
    "\n"
    "## 1 命令与输出\n"
    "\n"
    "## 2 人眼\n"
    "\n"
    "## 3 结论（记录人、抽验时间、被抽验版本）\n"
)


def _cmdline(tool: str, argv: list[str]) -> str:
    """本次运行的命令行（规范化成 `python <脚本名> …`，只含参数，不含任何密钥）。"""
    parts = ["python", tool]
    for item in argv:
        parts.append(f'"{item}"' if (" " in item or "\t" in item) else item)
    return " ".join(parts)


def record_block(tool: str, argv: list[str], printed: str, exit_code: int) -> str:
    """一段 Markdown：命令行、三项输出、退出码。"""
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return "\n".join([
        f"### {tool} 运行记录（{stamp}）",
        "",
        RECORD_NOTE,
        "",
        f"- 命令：`{_cmdline(tool, argv)}`",
        f"- 退出码：{exit_code}",
        "",
        "```text",
        printed.rstrip(),
        "```",
    ])


def _merge_into_section1(text: str, block: str) -> str:
    """把一段记录插进「## 1 命令与输出」里（在「## 2」之前）；没有这一节就在末尾补一节。"""
    if not text.endswith("\n"):
        text += "\n"
    first = SECTION1_RE.search(text)
    if first is None:
        return text.rstrip("\n") + "\n\n## 1 命令与输出\n\n" + block + "\n"
    second = SECTION2_RE.search(text, first.end())
    insert_at = second.start() if second else len(text)
    head, tail = text[:insert_at], text[insert_at:]
    if not head.endswith("\n\n"):
        head = head.rstrip("\n") + "\n\n"
    return head + block + "\n\n" + tail


def write_record(path: Path, block: str) -> tuple[bool, str]:
    """追加写进 user-check.md 的「## 1 命令与输出」；文件不存在就按骨架新建（2、3 节留空给学员）。"""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return False, f"建不了目录 {path.parent}：{exc}"
    if path.exists():
        try:
            raw = path.read_bytes()
        except OSError as exc:
            return False, f"读不了 {path}：{exc}"
        text = ""
        for enc in ("utf-8-sig", "utf-16", "gbk"):
            try:
                text = raw.decode(enc)
            except UnicodeDecodeError:
                continue
            break
        else:
            return False, f"读不了 {path}（编码认不出来）"
    else:
        text = RECORD_SKELETON
    try:
        path.write_text(_merge_into_section1(text, block), encoding="utf-8", newline="\n")
    except OSError as exc:
        return False, f"写不了 {path}：{exc}"
    return True, str(path)


# ---------------------------------------------------------------- 主流程

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="u3_check.py",
        add_help=False,
        description="单元三 G2 前抽验：一条命令查三件事（业务库指纹不变、运营库状态域与 P-01、超上限必被拒）。",
        epilog=(
            "最简用法（学员只跑这一行）：\n"
            "  python u3_check.py --db <产品实际读的业务库> --ops <运营库> --base http://127.0.0.1:<端口> "
            "--before <开工前指纹> --record <运行目录>\\evidence\\user-check.md\n"
            "\n"
            "--db 填哪份库：填产品运行时**实际打开的那份业务库**（存档点与按书施工的产品是\n"
            "  data\\homestay.db；若产品直接读 kit\\db\\homestay.db 就填它）。\n"
            "  填错库，指纹就守不住“业务库只读”：写坏运行时那份也不会红。\n"
            "\n"
            "第一步（必做，只在巡检开跑之前做一次）：先存指纹基线\n"
            "  python v2/lab/tools/db_fingerprint.py data\\homestay.db > before.txt\n"
            "  没给 --before 时本脚本判红（“未检查”按不通过算），所以这一步不能省。\n"
            "\n"
            "第二步（G2 前一条命令）：\n"
            "  python v2/lab/tools/u3_check.py --db data\\homestay.db --ops data\\ops.db "
            "--base http://127.0.0.1:<端口> --before before.txt "
            "--record <运行目录>\\evidence\\user-check.md\n"
            "  给了 --record，就把命令行、三项输出与退出码写进那份 user-check.md 的\n"
            "  「## 1 命令与输出」；「## 2 人眼」「## 3 结论」留给学员自己写。\n"
            "\n"
            "负向对照（夹具里有一条“已批准”的超限调价，必须判红）：\n"
            "  python v2/lab/tools/u3_check.py --ops v2/lab/fixtures/u3/bad_ops.db "
            "--db data\\homestay.db --base http://127.0.0.1:<端口> --before before.txt "
            "--record <运行目录>\\evidence\\user-check.md\n"
            "\n"
            "空运营库判红：调价申请表 0 行时第 2 项判红（先按第 6 章在页面提交两条、\n"
            "  批准一条再跑）；空表也能 PASS，等于“什么都不做也算做完”。只看调价申请表、\n"
            "  不看三表是否全空：第 3 项自己会往审计写一行，按三表全空判会漏掉第二次跑。\n"
            "\n"
            "状态域口径：调价申请只有 待审/批准/驳回；整改工单另有“已完成”（按存档点 DDL）。\n"
            "\n"
            "退出码：0 三件事都通过；1 至少一件不通过或参数不全。\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("-h", "--help", action="help", help="显示这段中文说明后退出")
    p.add_argument("--db", metavar="PATH",
                   help="产品运行时实际打开的那份业务库（存档点与按书施工的产品是 data\\homestay.db；"
                        "产品直接读 kit\\db\\homestay.db 就填它），只读打开")
    p.add_argument("--ops", metavar="PATH", help="运营库（ops.db）路径，只读打开")
    p.add_argument("--base", metavar="URL", help="服务地址，例如 http://127.0.0.1:8801（被占用就换空闲端口）")
    p.add_argument("--before", metavar="PATH", help="指纹基线文件（db_fingerprint.py 的输出）")
    p.add_argument("--record", metavar="PATH",
                   help="把本次命令行、三项 PASS/FAIL 与退出码追加进这个 user-check.md 的"
                        "「## 1 命令与输出」")
    p.add_argument("--listing", metavar="ID", help="可选：发请求用的房源编号；不给就自动挑一套")
    p.add_argument("--as-of", metavar="YYYY-MM-DD", default=DEFAULT_AS_OF,
                   help=f"巡检“当前日”，默认 {DEFAULT_AS_OF}")
    p.add_argument("--timeout", type=float, default=8.0, metavar="SEC", help="单次 HTTP 超时秒数，默认 8")
    return p


def main(argv: list[str] | None = None) -> int:
    setup_stdio()
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(argv)

    db = Path(args.db).expanduser() if args.db else None
    ops = Path(args.ops).expanduser() if args.ops else None
    before = Path(args.before).expanduser() if args.before else None
    record = Path(args.record).expanduser() if args.record else None

    print("u3_check 单元三 G2 前抽验（三件事）")
    results: list[tuple[str, bool, str, str]] = []
    for label, fn in (
        ("业务库指纹", lambda: check_fingerprint(db, before) if db else (False, "未检查（没给 --db）")),
        ("运营库", lambda: check_ops(ops)),
        ("超上限调价", lambda: check_http(args.base or "", db, ops, args.as_of,
                                          args.listing, args.timeout)),
    ):
        ok, detail = fn()
        tag = "PASS" if ok else "FAIL"
        if "未检查" in detail:
            tag = "FAIL"
        results.append((label, ok, detail, tag))

    lines = [f"[{tag}] {label}：{detail}" for label, _ok, detail, tag in results]
    bad = [r for r in results if not r[1]]
    if bad:
        # 未检查也走这一支：缺项就是没做完，按不通过算（见文件头“缺项也算不通过”）
        tail = f"结论：不通过（{len(bad)} 项不通过）-> 退出码 1"
        code = 1
    else:
        tail = "结论：三件事全部通过 -> 退出码 0"
        code = 0
    for line in lines:
        print(line)
    print(tail)

    if record is not None:
        printed = "\n".join(["u3_check 单元三 G2 前抽验（三件事）"] + lines + [tail])
        ok, info = write_record(record, record_block("u3_check.py", raw_argv, printed, code))
        print(f"记录：{'已写进' if ok else '没写成'} {info}")
    return code


if __name__ == "__main__":
    sys.exit(main())
