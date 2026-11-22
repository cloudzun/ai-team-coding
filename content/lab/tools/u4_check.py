#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""u4_check.py -- 单元四（对话里查数的薄插件）G2 前抽验：一条命令只查三件事，输出几行中文 PASS/FAIL。

课程材料（阶段四 单元四）。只用 Python 3.12 标准库；不起服务、只读算指纹、只发 HTTP。

它查三件事（每件事一行）：
  1. 业务库没被写：把 --db 指向的业务库算 SHA-256，和 --before 基线里的比。
     基线用本脚本存（`--save-before`），也认得 db_fingerprint.py 的输出。
     给了 --ops 运营库时，再查 price_change_requests 行数没比基线多
     （基线里没记行数就记“未检查”，按不通过算）。
  2. 卡片数值与接口一致：读 --card（在 DSH 页面控制台执行 window.__cardExport() 存下来的
     那份 JSON），按它里面的 params 自己向 --base 的同一只读接口再取一次数，逐行比 value
     （比例与百分点差容差 0.001，金额容差 0.01）；label 只查是否含该数值的显示形式。
     支持区级对比卡（homestay_compare）与走势卡（homestay_trend）。
  3. 后端只读：向 --base 的对比接口发一个写方法请求（POST），必须被拒（4xx/405）；
     发完再取一次业务库指纹与运营库行数，必须仍不变。
     没给 --ops 时这一句只报真的查过的项（业务库指纹），运营库写“未检查（没给 --ops）”。

== 最简用法（学员只跑这一行）==
    python u4_check.py --db <库> --ops <运营库> --base http://127.0.0.1:<端口> --before <开工前基线> --card <导出的 JSON> --record <运行目录>\\evidence\\user-check.md

  开工前先存一次基线（一条命令，只在开工前做一次）：
      python u4_check.py --db <库> --ops <运营库> --before before.txt --save-before
  --record 把本次运行的命令行、三项 PASS/FAIL 与退出码，追加写进那份 user-check.md 的
  「## 1 命令与输出」一节（文件不存在就按骨架新建；「## 2 人眼」「## 3 结论」留给学员自己写）。

== 用法 ==
  G2 前一条命令：
      python v2/lab/tools/u4_check.py --db <库> --ops <运营库> --base http://127.0.0.1:<端口> ^
          --before before.txt --card <导出的卡片 JSON> --record <运行目录>\\evidence\\user-check.md

  负向对照（夹具里有一行数值被改，必须判红）：
      python v2/lab/tools/u4_check.py --db <库> --ops <运营库> --base http://127.0.0.1:<端口> ^
          --before before.txt --card v2/lab/fixtures/u4/bad_card.json

== 参数 ==
  --db      业务库（homestay.db）路径，只读打开；用来算指纹。
  --before  基线文件：本脚本 `--save-before` 写的（sha256 + 运营库行数），或 db_fingerprint.py 的输出。
  --base    服务地址，例如 http://127.0.0.1:<端口>（端口示例用 8801，自己挑，起服务前确认没被占用）。
  --ops     可选：运营库（ops.db）路径，只读打开；查 price_change_requests 行数没增加。
  --card    可选：`window.__cardExport()` 存下来的 JSON；不给就记“未检查”，按不通过算。
  --record  可选：把本次运行的命令行、三项 PASS/FAIL 与退出码，追加进这个 user-check.md
            的「## 1 命令与输出」一节；文件不存在就按骨架新建（2、3 节留空给学员）。
  --save-before  可选：只存基线（业务库指纹 + 给了 --ops 时的 price_change_requests 行数）
            到 --before，然后退出；不查三件事。开工前跑一次。
  --timeout 可选：单次 HTTP 超时秒数，默认 8。

== 退出码 ==
  0 三件事都通过；1 至少一件不通过，或者参数/输入有问题（缺项也按不通过处理）。

== 缺项也算不通过 ==
  --db / --before / --base / --card 少给任何一个，对应那一段打印“未检查”，最后判不通过。
  --ops 是可选的：不给就跳过运营库行数这一项（文字里注明），其余照查。

== 不打印什么 ==
  不打印卡片全部行、不打印运营库整行内容、不打印业务库内容；失败时只说第几行、行号、
  卡片值与接口值（G2 抽验记录里要据此写 user-check.md）。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

HEX64 = re.compile(r"\b[0-9a-fA-F]{64}\b")
OPS_COUNT_RE = re.compile(r"^\s*(?:ops\.)?price_change_requests\s*[:=]\s*(\d+)\s*$", re.M)
RATIO_TOL = Decimal("0.001")   # 比例、百分点差、评分：与导出契约的默认容差一致
MONEY_TOL = Decimal("0.01")    # 金额：分
DASH = "—"
COMPARE_LABEL = {"occupancy": "入住率", "adr": "平均房价"}


def setup_stdio() -> None:
    """中文输出不乱码：控制台交给宿主编码，重定向时兜底。"""
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


def read_texts(path: Path) -> list[str]:
    """按 UTF-8（含 BOM）、UTF-16、GBK 依次试读，返回能读出来的几种文本。"""
    raw = path.read_bytes()
    texts: list[str] = []
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        texts.append(raw.decode("utf-16", errors="replace"))
    texts.append(raw.decode("utf-8-sig", errors="replace").replace("\x00", ""))
    try:
        texts.append(raw.decode("gbk").replace("\x00", ""))
    except UnicodeDecodeError:
        pass
    return texts


def read_baseline(path: Path) -> str | None:
    """从基线文件里取 sha256（db_fingerprint.py 的输出、本脚本的基线都认）。"""
    for text in read_texts(path):
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


def read_ops_baseline(path: Path) -> int | None:
    """从基线文件里取 price_change_requests 的行数（没有这一行就返回 None）。"""
    for text in read_texts(path):
        m = OPS_COUNT_RE.search(text)
        if m:
            return int(m.group(1))
    return None


def open_ro(db_path: Path):
    import sqlite3

    try:
        uri = db_path.resolve().as_uri() + "?mode=ro"
    except ValueError:
        uri = "file:" + db_path.resolve().as_posix() + "?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.execute("PRAGMA query_only = ON")
    con.execute("SELECT count(*) FROM sqlite_master").fetchone()
    return con


def ops_rows(ops: Path | None) -> int | None:
    """运营库里 price_change_requests 的行数；库不在或没有这张表时返回 None。"""
    if ops is None or not ops.is_file():
        return None
    try:
        con = open_ro(ops)
    except Exception:
        return None
    try:
        row = con.execute("SELECT count(*) FROM price_change_requests").fetchone()
        return int(row[0]) if row else None
    except Exception:
        return None
    finally:
        con.close()


# ---------------------------------------------------------------- 显示形式（与插件同一把尺）

def _dec(v) -> Decimal:
    return Decimal(str(v))


def _round(v, places: int) -> str:
    """十进制定点、四舍五入（half-up，远离零），与插件 roundDecimal 同一把尺。"""
    try:
        q = _dec(v).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return str(v)
    text = f"{q:.{places}f}"
    if text.startswith("-") and Decimal(text) == 0:   # 负零归零
        text = text[1:]
    return text


def show_ratio(v) -> str:
    """0–1 比例 → 一位小数百分比（入住率、占比）。"""
    return DASH if v is None else f"{_round(_dec(v) * 100, 1)}%"


def show_money(v) -> str:
    """金额 → 取整带 ¥（平均房价、RevPAR）。"""
    return DASH if v is None else f"¥{_round(v, 0)}"


def show_score(v) -> str:
    """评分 → 两位小数。"""
    return DASH if v is None else _round(v, 2)


# 每个指标：接口字段、显示形式、容差
COMPARE_FIELD = {"occupancy": ("occupancy", show_ratio, RATIO_TOL), "adr": ("adr", show_money, MONEY_TOL)}
TREND_FIELD = {
    "occupancy": ("occupancy", show_ratio, RATIO_TOL),
    "adr": ("adr", show_money, MONEY_TOL),
    "revpar": ("revpar", show_money, MONEY_TOL),
    "rating": ("rating", show_score, RATIO_TOL),
}


# ---------------------------------------------------------------- HTTP

def get_json(base: str, path: str, timeout: float) -> dict:
    url = base.rstrip("/") + path
    req = urllib.request.Request(url, method="GET", headers={"accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - 只连学员自己的服务
        return json.loads(resp.read().decode("utf-8"))


def post_json_refused(base: str, path: str, body: bytes, timeout: float) -> tuple[bool, str]:
    """发一个写方法请求，返回 (是否被拒得对, 说明)。"""
    url = base.rstrip("/") + path
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"content-type": "application/json", "accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            code = resp.status
            return False, f"写方法竟然被接受（HTTP {code}）：后端不该允许 POST {path}"
    except urllib.error.HTTPError as exc:
        code = exc.code
        if 400 <= code < 500:
            return True, f"POST {path} 被拒（HTTP {code}）"
        return False, f"POST {path} 没被拒成 4xx，而是 HTTP {code}"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return False, f"连不上 {base}（服务没起？{exc.__class__.__name__}）"


def fetch_backend_rows(base: str, card: dict, timeout: float) -> tuple[dict | None, str, callable | None]:
    """按卡片的 params 向同一只读接口取数，返回 (key→value, 显示形式函数, 错误说明)。"""
    tool = card.get("tool")
    params = card.get("params") if isinstance(card.get("params"), dict) else {}

    if tool == "homestay_compare":
        start, end = params.get("start"), params.get("end")
        metric = params.get("metric", "occupancy")
        if not (isinstance(start, str) and isinstance(end, str)):
            return None, "", "卡片 params 里没有 start / end，认不出查的是哪一期"
        if metric not in COMPARE_FIELD:
            return None, "", f"卡片 metric={metric!r} 不是 occupancy / adr"
        field, show, _tol = COMPARE_FIELD[metric]
        try:
            payload = get_json(base, f"/api/districts?start={start}&end={end}", timeout)
        except urllib.error.HTTPError as exc:
            return None, "", f"接口 {exc.code}：GET /api/districts?start={start}&end={end}"
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return None, "", f"连不上 {base}（服务没起？{exc.__class__.__name__}）"
        except ValueError:
            return None, "", "接口返回的不是 JSON"
        rows = payload.get("districts") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            return None, "", "接口返回里没有 districts 数组"
        return {r.get("district_id"): r.get(field) for r in rows if isinstance(r, dict)}, show, ""

    if tool == "homestay_trend":
        metric = params.get("metric", "occupancy")
        frm, to = params.get("from"), params.get("to")
        if metric not in TREND_FIELD:
            return None, "", f"卡片 metric={metric!r} 不是 occupancy / adr / revpar / rating"
        if not (isinstance(frm, str) and isinstance(to, str)):
            return None, "", "卡片 params 里没有 from / to，认不出查的是哪一段"
        field, show, _tol = TREND_FIELD[metric]
        district = params.get("district")
        district_id = None
        if isinstance(district, str) and district.strip():
            district_id = resolve_district(base, district.strip(), timeout)
            if district_id is None:
                return None, "", f"卡片 district={district!r} 在 /api/districts 里对不上"
        path = f"/api/trend?district={district_id}" if district_id else "/api/trend"
        try:
            payload = get_json(base, path, timeout)
        except urllib.error.HTTPError as exc:
            return None, "", f"接口 {exc.code}：GET {path}"
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return None, "", f"连不上 {base}（服务没起？{exc.__class__.__name__}）"
        except ValueError:
            return None, "", "接口返回的不是 JSON"
        months, values = payload.get("months"), payload.get(metric)
        if not isinstance(months, list) or not isinstance(values, list) or len(months) != len(values):
            return None, "", f"接口返回里没有 months / {metric}，或两者长度不一致"
        pairs = {m: v for m, v in zip(months, values) if isinstance(m, str) and frm <= m <= to}
        return pairs, show, ""

    return None, "", (f"本检查只对区级对比卡（homestay_compare）与走势卡（homestay_trend）；"
                      f"--card 里 tool={tool!r}，请导出这两种卡片")


def resolve_district(base: str, key: str, timeout: float) -> str | None:
    """区名或编号 → 编号。规则与插件一致：编号、区名、带不带“区”字都收。"""
    upper = key.upper()
    if re.fullmatch(r"D0[1-8]", upper):
        return upper
    try:
        payload = get_json(base, "/api/districts", timeout)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ValueError):
        return None
    for d in payload.get("districts") or []:
        if not isinstance(d, dict):
            continue
        name = d.get("name")
        if isinstance(name, str) and (name == key or name == f"{key}区" or name.rstrip("区") == key):
            return d.get("district_id")
    return None


# ---------------------------------------------------------------- 检查 1：业务库与运营库

def check_no_write(db: Path | None, before: Path | None, ops: Path | None) -> tuple[bool, str]:
    if db is None:
        return False, "未检查（没给 --db 业务库）"
    if not db.is_file():
        return False, f"找不到业务库 {db}"
    if before is None:
        return False, "未检查（没给 --before 基线；先跑一次 --save-before）"
    if not before.is_file():
        return False, f"找不到基线 {before}"
    want = read_baseline(before)
    if want is None:
        return False, f"基线文件里读不出 sha256：{before}（先跑一次 --save-before，或 db_fingerprint.py）"
    digest = sha256_file(db)
    if want != digest:
        return False, (f"业务库已变（基线 {want[:12]}… 现在 {digest[:12]}…）："
                       f"跑过插件后业务库不该有任何改动")
    parts = [f"与基线一致（sha256 前 12 位 {digest[:12]}）"]
    if ops is None:
        parts.append("运营库未检查（没给 --ops）")
        return True, "；".join(parts)
    if not ops.is_file():
        return False, f"找不到运营库 {ops}（先跑一次单元三的巡检，或把 --ops 指对）"
    base_rows = read_ops_baseline(before)
    if base_rows is None:
        return False, (f"未检查：基线 {before.name} 里没有 price_change_requests 行数"
                       f"（用 --save-before 存基线才会记）")
    now_rows = ops_rows(ops)
    if now_rows is None:
        return False, f"运营库里读不出 price_change_requests 行数：{ops}"
    if now_rows != base_rows:
        return False, (f"运营库 price_change_requests 行数变了（基线 {base_rows} 行，现在 {now_rows} 行）："
                       f"插件只读，不该新增申请")
    parts.append(f"运营库 price_change_requests 仍 {now_rows} 行")
    return True, "；".join(parts)


# ---------------------------------------------------------------- 检查 2：卡片数值

def load_card(path: Path | None) -> tuple[dict | None, str]:
    if path is None:
        return None, "未检查（没给 --card；先在 DSH 控制台跑 window.__cardExport() 存成 JSON）"
    if not path.is_file():
        return None, f"找不到卡片 JSON {path}"
    try:
        card = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        return None, f"读不了 {path}：{exc}"
    except ValueError as exc:
        return None, f"{path.name} 不是合法 JSON：{exc}"
    if not isinstance(card, dict):
        return None, f"{path.name} 顶层不是对象（应是 {{tool, params, rows}}）"
    rows = card.get("rows")
    if not isinstance(rows, list) or not rows:
        return None, f"{path.name} 里 rows 不是非空数组"
    bad = [i for i, r in enumerate(rows)
           if not isinstance(r, dict) or not isinstance(r.get("key"), str) or not isinstance(r.get("label"), str)
           or "value" not in r]
    if bad:
        return None, f"{path.name} 第 {bad[0] + 1} 行缺 key / label / value"
    return card, ""


def check_card(card: dict | None, base: str, timeout: float) -> tuple[bool, str]:
    if card is None:
        return False, "未检查（没给 --card）"
    if not base:
        return False, "未检查（没给 --base 服务地址）"
    rows, show, err = fetch_backend_rows(base, card, timeout)
    if rows is None:
        return False, err
    metric = card.get("params", {}).get("metric", "occupancy") if isinstance(card.get("params"), dict) else "occupancy"
    if card.get("tool") == "homestay_compare":
        tol = COMPARE_FIELD[metric][2]
    else:
        tol = TREND_FIELD[metric][2]
    problems: list[str] = []
    for i, row in enumerate(card.get("rows") or []):
        key, label, got = row["key"], row["label"], row["value"]
        if key not in rows:
            problems.append(f"第 {i + 1} 行 {key}：接口里没有这一行")
            continue
        want = rows[key]
        if want is None or got is None:
            if want is not None or got is not None:
                problems.append(f"第 {i + 1} 行 {key}：卡片 {got!r} / 接口 {want!r}，一边有一边空")
            continue
        try:
            delta = abs(_dec(got) - _dec(want))
        except (InvalidOperation, TypeError, ValueError):
            problems.append(f"第 {i + 1} 行 {key}：value 不是数（卡片 {got!r}）")
            continue
        if delta > tol:
            problems.append(f"第 {i + 1} 行 {key}：卡片 {show(got)}（{got}）≠ 接口 {show(want)}（{want}）")
            continue
        expect_text = show(want)
        if expect_text not in label:
            problems.append(f"第 {i + 1} 行 {key}：label「{label}」里没有「{expect_text}」")
    if problems:
        head = "；".join(problems[:2])
        more = f"；另有 {len(problems) - 2} 处" if len(problems) > 2 else ""
        return False, head + more
    tol_text = f"金额容差 {MONEY_TOL}" if tol == MONEY_TOL else f"比例容差 {RATIO_TOL}"
    return True, f"{len(card.get('rows') or [])} 行与接口一致（{tol_text}），label 都含显示值"


# ---------------------------------------------------------------- 检查 3：后端只读

def readonly_tail(db: Path | None, ops: Path | None, ops_before: int | None) -> str:
    """「发过写请求后没变」那一句：只写真的查过的项（没给 --ops 就别说“运营库行数没变”）。"""
    db_checked = db is not None and db.is_file()
    db_part = "业务库指纹没变" if db_checked else "业务库未检查（没给 --db）"
    if ops is not None and ops.is_file() and ops_before is not None:
        if db_checked:
            return "业务库指纹与运营库行数都没变"
        return f"{db_part}；运营库行数没变"
    skip = ("没给 --ops" if ops is None
            else "找不到 --ops 指的运营库" if not ops.is_file()
            else "开始前读不出 price_change_requests 行数")
    return f"{db_part}；运营库未检查（{skip}）"


def check_readonly(base: str, db: Path | None, ops: Path | None,
                   sha_before: str | None, ops_before: int | None, timeout: float) -> tuple[bool, str]:
    if not base:
        return False, "未检查（没给 --base 服务地址）"
    ok, why = post_json_refused(base, "/api/districts", b"{}", timeout)
    if not ok:
        return False, why
    if db is not None and db.is_file():
        if sha_before is None:
            return False, "业务库指纹没取到，判不了“发过写请求后没变”"
        sha_after = sha256_file(db)
        if sha_after != sha_before:
            return False, (f"发过写请求后业务库指纹变了（{sha_before[:12]}… → {sha_after[:12]}…）："
                           f"后端不该在只读请求里写业务库")
    if ops is not None and ops.is_file() and ops_before is not None:
        after = ops_rows(ops)
        if after is not None and after != ops_before:
            return False, f"发过写请求后运营库 price_change_requests 从 {ops_before} 行变成 {after} 行"
    return True, f"{why}；{readonly_tail(db, ops, ops_before)}"


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


# ---------------------------------------------------------------- --save-before

def save_baseline(db: Path | None, ops: Path | None, before: Path | None) -> int:
    if db is None or before is None:
        print("存基线要同时给 --db 与 --before")
        return 1
    if not db.is_file():
        print(f"找不到业务库 {db}")
        return 1
    lines = ["u4_check baseline v1", f"db: {db.resolve()}", f"bytes: {db.stat().st_size}",
             f"sha256: {sha256_file(db)}"]
    if ops is not None:
        if not ops.is_file():
            print(f"找不到运营库 {ops}")
            return 1
        rows = ops_rows(ops)
        if rows is None:
            print(f"运营库里读不出 price_change_requests 行数：{ops}")
            return 1
        lines.append(f"price_change_requests: {rows}")
    try:
        before.parent.mkdir(parents=True, exist_ok=True)
        before.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    except OSError as exc:
        print(f"写不了基线 {before}：{exc}")
        return 1
    print(f"基线已存：{before}")
    print(f"  - 业务库 sha256 前 12 位：{lines[3].split(': ')[1][:12]}")
    if ops is not None:
        print(f"  - 运营库 price_change_requests：{lines[4].split(': ')[1]} 行")
    print("  开工前存这一份就够；G2 前跑检查命令时用同一个 --before。")
    return 0


# ---------------------------------------------------------------- 主流程

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="u4_check.py",
        add_help=False,
        description="单元四 G2 前抽验：一条命令查三件事（业务库没被写、卡片数值与接口一致、后端只读）。",
        epilog=(
            "最简用法（学员只跑这一行）：\n"
            "  python u4_check.py --db <库> --ops <运营库> --base http://127.0.0.1:<端口> "
            "--before <开工前基线> --card <导出的卡片 JSON> --record <运行目录>\\evidence\\user-check.md\n"
            "\n"
            "第一步（开工前做一次）：先存基线\n"
            "  python v2/lab/tools/u4_check.py --db data/homestay.db --ops data/ops.db "
            "--before before.txt --save-before\n"
            "  没给 --before 或有基线但文件里没有 sha256 时本脚本判红（“未检查”按不通过算）。\n"
            "\n"
            "第二步（G2 前一条命令）：\n"
            "  python v2/lab/tools/u4_check.py --db data/homestay.db --ops data/ops.db "
            "--base http://127.0.0.1:<端口> --before before.txt --card card.json "
            "--record <运行目录>\\evidence\\user-check.md\n"
            "  卡片 JSON 这样取：在 DSH 页面控制台跑 window.__cardExport()，把返回值存成 card.json。\n"
            "  给了 --record，就把命令行、三项输出与退出码写进那份 user-check.md 的\n"
            "  「## 1 命令与输出」；「## 2 人眼」「## 3 结论」留给学员自己写。\n"
            "\n"
            "负向对照（夹具里有一行数值被改，必须判红）：\n"
            "  python v2/lab/tools/u4_check.py --db data/homestay.db --ops data/ops.db "
            "--base http://127.0.0.1:<端口> --before before.txt "
            "--card v2/lab/fixtures/u4/bad_card.json\n"
            "\n"
            "卡片对账支持区级对比卡（homestay_compare）与走势卡（homestay_trend）：\n"
            "  按卡片里的 params 向同一只读接口再取一次数，逐行比 value；比例与百分点差容差 0.001、\n"
            "  金额容差 0.01；label 只查是否含该数值的显示形式。\n"
            "\n"
            "退出码：0 三件事都通过；1 至少一件不通过或参数不全。\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("-h", "--help", action="help", help="显示这段中文说明后退出")
    p.add_argument("--db", metavar="PATH", help="业务库（homestay.db）路径，只读打开")
    p.add_argument("--before", metavar="PATH", help="基线文件：--save-before 写的，或 db_fingerprint.py 的输出")
    p.add_argument("--base", metavar="URL", help="服务地址，例如 http://127.0.0.1:8801（被占用就换空闲端口）")
    p.add_argument("--ops", metavar="PATH", help="可选：运营库（ops.db）路径，只读打开；查行数没增加")
    p.add_argument("--card", metavar="PATH", help="可选：window.__cardExport() 存下来的卡片 JSON")
    p.add_argument("--record", metavar="PATH",
                   help="把本次命令行、三项 PASS/FAIL 与退出码追加进这个 user-check.md 的"
                        "「## 1 命令与输出」")
    p.add_argument("--save-before", action="store_true", help="只存基线到 --before，然后退出（开工前跑一次）")
    p.add_argument("--timeout", type=float, default=8.0, metavar="SEC", help="单次 HTTP 超时秒数，默认 8")
    return p


def main(argv: list[str] | None = None) -> int:
    setup_stdio()
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(argv)

    db = Path(args.db).expanduser() if args.db else None
    ops = Path(args.ops).expanduser() if args.ops else None
    before = Path(args.before).expanduser() if args.before else None
    card_path = Path(args.card).expanduser() if args.card else None
    record = Path(args.record).expanduser() if args.record else None

    if args.save_before:
        return save_baseline(db, ops, before)

    print("u4_check 单元四 G2 前抽验（三件事）")
    sha_before = sha256_file(db) if db is not None and db.is_file() else None
    ops_before = ops_rows(ops) if ops is not None and ops.is_file() else None
    card, card_err = load_card(card_path)

    results: list[tuple[str, bool, str]] = []
    for label, fn in (
        ("业务库与运营库", lambda: check_no_write(db, before, ops)),
        ("卡片数值", lambda: check_card(card, args.base or "", args.timeout)),
        ("后端只读", lambda: check_readonly(args.base or "", db, ops, sha_before, ops_before, args.timeout)),
    ):
        ok, detail = fn()
        if card is None and label == "卡片数值":
            detail = card_err or detail
        results.append((label, ok, detail))

    lines = [f"[{'PASS' if ok else 'FAIL'}] {label}：{detail}" for label, ok, detail in results]
    bad = [r for r in results if not r[1]]
    if bad:
        tail = f"结论：不通过（{len(bad)} 项不通过）-> 退出码 1"
        code = 1
    else:
        tail = "结论：三件事全部通过 -> 退出码 0"
        code = 0
    for line in lines:
        print(line)
    print(tail)

    if record is not None:
        printed = "\n".join(["u4_check 单元四 G2 前抽验（三件事）"] + lines + [tail])
        ok, info = write_record(record, record_block("u4_check.py", raw_argv, printed, code))
        print(f"记录：{'已写进' if ok else '没写成'} {info}")
    return code


if __name__ == "__main__":
    sys.exit(main())
