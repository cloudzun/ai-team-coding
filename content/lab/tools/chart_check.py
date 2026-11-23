#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""chart_check.py -- 把"页面上导出的一套数字"和"自己写的期望值"逐对象、逐系列、逐点对上。

课程材料（阶段一 数据看板 / 样例演练）。只用 Python 3.12 标准库，不联网、不起服务。

它检查两样东西：
  1. 导出的对象齐不齐：ref.sql（或期望 JSON）里声明的每个 id，导出里都得有；
  2. 每个对象的值对不对：按 id -> 系列名 -> x 三层对齐，逐点比 value，越界就报超差。

== 期望值从哪里来（二选一） ==
  A) --db <库路径> --ref <ref.sql>
     按下面“ref.sql 写法”一节读参考 SQL，脚本自己执行，以 mode=ro 打开数据库，
     只读，不会写库。ref.sql 里出现写语句时脚本拒绝运行。
  B) --expected <期望.json>
     期望值直接从一份 JSON 读（形状与导出契约等价），用于数据库里没有的样例页。

== ref.sql 写法 ==
     -- chart: occ_monthly            （对象 id 必须与导出里的 id 一致）
     SELECT '本期' AS series, ym AS x, occupancy AS value FROM ...
     UNION ALL
     SELECT '上年同期', ym, occupancy_prev_year FROM ...
     -- kpi: occ_latest
     SELECT 0.86 AS value
  - 每段由一行注释 `-- chart: <id>` 或 `-- kpi: <id>` 声明，段内容到下一段声明为止。
  - chart 段必须返回三列：series（系列名）、x（横轴类目）、value（数值）。
  - kpi 段必须返回一行一列：value。
  - 段头可以追加两项可选项（写在声明行或该段第一句 SQL 之前的注释里）：
      `-- tol: 0.005`   这一段用自己的容差，覆盖命令行给的默认值；
      `-- unit: ratio` / `-- unit: money` / `-- unit: other`
                        这一段的值是比例、金额还是别的，决定用哪把默认容差、label 怎么读。
    不写 unit 时按数值量级猜：这一段所有期望值的绝对值都不超过 1，就按比例比；否则按金额比。
    （比例和金额之外的东西，比如评分 4.63，请显式写 `-- unit: other`，它用比例那把容差。）

== 导出文件 ==
  页面里 `await window.__chartExport()` 的返回值，JSON.stringify 之后存成的文件（见渔具包里的 `导出契约.md`）。
  如果存成了"被 JSON 编码两次的字符串"，脚本会先解一层再读。

== 容差 ==
  - 比例：--tol-ratio，默认 0.001（比的是 0-1 的小数，不是百分数）。
  - 金额：--tol-money，默认 0.01（元）。
  - 段头 `-- tol:` 覆盖上面两个默认值。

== kpi 的 label 额外核对（只报 WARN，从不报 FAIL）==
  导出的 kpi 若带 label（页面上实际显示的文字），脚本会把它读回来与 value 对一遍：
    - label 里有 %：把 value 乘 100 当百分数来读；否则按原值读；
    - 允许偏差 = 半个末位（label 保留几位小数就按几位）+ 容差；
    - 读不出数字、差得离谱，都只打印 WARN，不改变该对象的 PASS/FAIL，也不改变退出码。
  这条是"眼睛看到的和数值对不对得上"的软检查，宁可少报红，也不要因为显示格式不同把正确的看板判死。

== 什么算 FAIL、什么只算 WARN ==
  FAIL（这个对象判红，退出码 1）：
    - 期望里声明了、导出里没有的对象；
    - 期望里的系列名，导出里没有（缺系列）；同一个系列名在导出里出现两次；
    - 期望里有的 x，导出里没有（缺失点）；导出里多出来的 x（多余点）；
    - 同一个 x 的 value 差超过该段容差（超差点）。
  WARN（只提示，不影响 PASS/FAIL 与退出码）：
    - 导出的系列名没在期望里声明（可能只是期望少写了一段）；
    - 导出的对象没在期望里声明（没被检查过，提醒一句）；
    - kpi 的 label 与 value 对不上（下面单独说明）。

== --swap A,B ==
  负向自检：先在导出数据里把 A、B 两个系列名对调，再照常比。一个正确的看板此时必须变红；
  如果对调后仍然全绿，脚本会直接告诉你"这条判据对装反不敏感"。
  注意：带 --swap 时退出码仍按"有 FAIL 就是 1"，也就是负向自检正常时应看到退出码 1。

== --before：顺带证明业务库没被写（可选，与单元二到四的检查命令同款） ==
  课程纪律是"每单元一条检查命令"：对账之外，还要证明这一轮没写过业务库。
  同时给了 --db 与 --before 时，脚本在对账各项之后多打一项"业务库指纹"，
  措辞与 u2/u3/u4_check 一致：
    [PASS] 业务库指纹：与基线一致（sha256 前 12 位 3f2a1b0c9d8e）
    [FAIL] 业务库指纹：已变（基线 3f2a1b0c9d8e… 现在 9a8b7c6d5e4f…）：看板只读，业务库不该有任何改动
  这一项 FAIL 也计入退出码 1；它单列一项，不混进对象的 PASS/FAIL 个数里。
  --before 必须与 --db 一起给：只给 --before 不给 --db 是参数错误（退出码 2）。
  基线文件怎么来（开工前跑一次，只跑一次）：
    python db_fingerprint.py <库文件> > before.txt
  Windows PowerShell 5.1 的 `>` 重定向会写成 UTF-16，本脚本按 u2/u3 的读法照样读得进
  （UTF-8、带 BOM、GBK 也都认）。
  不给 --before 时，本脚本的输出与行为跟没有这个选项时逐字一致。

== 退出码 ==
  0 全 PASS（WARN 不影响退出码）；1 至少一个对象 FAIL；2 参数或输入文件有问题，没跑起来。

== --record（可选，一条命令顺手写抽验记录） ==
  --record <运行目录>\\evidence\\user-check.md
  给了就把本次运行的命令行、这一屏输出（逐项 PASS/FAIL 与汇总）和退出码，追加写进那份
  user-check.md 的「## 1 命令与输出」一节；文件不存在就按骨架新建（「## 2 人眼三问」
  「## 3 结论」留给学员自己写）。文件可能是 UTF-8（带不带 BOM 都行）或 UTF-16，
  写回时统一存成 UTF-8。不给 --record 时，输出与行为跟没有这个选项时完全一样。
  参数或输入文件有问题（退出码 2）时脚本没跑起来，不写记录。
  单元一推荐的一条命令（正向，对账 + 业务库指纹 + 抽验记录）：
    python chart_check.py --db <库> --ref <ref.sql> --export <导出.json> --before <开工前指纹> --record <运行目录>\\evidence\\user-check.md
  负向同款（把两个系列名对调，必须变红）：
    python chart_check.py --db <库> --ref <ref.sql> --export <导出.json> --swap "本期,上年同期" --before <开工前指纹> --record <运行目录>\\evidence\\user-check.md

== 输出编码 ==
  只用中文 + ASCII 符号（PASS/FAIL/WARN、->）。不改管道编码，打印时用 replace 兜底，
  所以 Windows 控制台（GBK）与 UTF-8 终端都不会抛 UnicodeEncodeError、也不会出现半截乱码。
"""

import argparse
import contextlib
import hashlib
import io
import json
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

DEFAULT_TOL_RATIO = 0.001
DEFAULT_TOL_MONEY = 0.01

# 出现这些关键字（字符串字面量与注释之外的正文里）就拒绝执行。
WRITE_KEYWORDS = ("insert", "update", "delete", "create", "drop", "alter",
                  "attach", "detach", "vacuum", "reindex", "replace", "truncate")
# 只读 PRAGMA 的白名单；白名单以外或带 = 的 PRAGMA 一律当写语句拒绝。
READONLY_PRAGMAS = {"table_info", "table_xinfo", "table_list", "index_list", "index_info",
                    "index_xinfo", "foreign_key_list", "database_list", "collation_list",
                    "compile_options", "integrity_check", "quick_check"}

DECL_RE = re.compile(r"^\s*--\s*(chart|kpi)\s*:\s*([A-Za-z0-9_.\-]+)\s*(.*)$")
TOL_RE = re.compile(r"tol\s*[:=]\s*([0-9]+(?:\.[0-9]+)?)")
UNIT_RE = re.compile(r"unit\s*[:=]\s*(ratio|money|other)")
NUM_RE = re.compile(r"[-+]?[0-9][0-9,]*(?:\.[0-9]+)?")
PRAGMA_RE = re.compile(r"\bpragma\s+([a-z_]+)\s*([=(]?)")
HEX64 = re.compile(r"\b[0-9a-fA-F]{64}\b")

UNIT_TOLERANCE = {"ratio": "tol_ratio", "money": "tol_money", "other": "tol_ratio"}


class InputError(Exception):
    """输入文件或参数的问题：打印一行原因，退出码 2。"""


class ChineseParser(argparse.ArgumentParser):
    """argparse 默认的报错是英文；这里包一层中文提示，学生知道下一步做什么。"""

    def error(self, message):
        print("错误：命令行参数不完整或写法不对。", file=sys.stderr)
        print(f"  {message}", file=sys.stderr)
        print("  用 --help 看全部参数与样例。", file=sys.stderr)
        raise SystemExit(2)


# --------------------------------------------------------------------------- 小工具

def fmt_num(v):
    """数值打印：去掉多余的 0，比 .6g 更好读。"""
    if isinstance(v, int) and not isinstance(v, bool):
        return str(v)
    s = f"{v:.6f}".rstrip("0").rstrip(".")
    return s if s not in ("", "-") else "0"


def join_limited(items, limit=6):
    """一行里最多列 6 项，剩下的折成一句，免得输出刷屏。"""
    if len(items) <= limit:
        return "；".join(items)
    return "；".join(items[:limit]) + f"；……另有 {len(items) - limit} 处"


def read_text(path, what):
    p = Path(path)
    if not p.is_file():
        raise InputError(f"{what}不存在：{p}")
    try:
        # utf-8-sig：记事本存下来带 BOM 的文件也能读。
        return p.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        raise InputError(f"{what}不是 UTF-8 文本：{p}")


def as_float(raw, where):
    if isinstance(raw, bool) or raw is None:
        raise InputError(f"{where} 的值不是数字：{raw!r}")
    if isinstance(raw, (int, float)):
        return float(raw)
    try:
        return float(str(raw).strip())
    except (TypeError, ValueError):
        raise InputError(f"{where} 的值不是数字：{raw!r}")


# --------------------------------------------------------------------------- ref.sql

def strip_literals(sql):
    """去掉 SQL 里的字符串字面量与注释，只留可以找关键字的正文。"""
    out, i, n = [], 0, len(sql)
    while i < n:
        c = sql[i]
        if c == "'":                       # 单引号字符串，'' 表示一个单引号
            i += 1
            while i < n:
                if sql[i] == "'":
                    if i + 1 < n and sql[i + 1] == "'":
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            out.append(" ")
        elif c == '"':                     # 双引号标识符
            i += 1
            while i < n:
                if sql[i] == '"':
                    if i + 1 < n and sql[i + 1] == '"':
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            out.append(" ")
        elif sql[i:i + 2] == "--":         # 行注释
            while i < n and sql[i] != "\n":
                i += 1
        elif sql[i:i + 2] == "/*":         # 块注释
            end = sql.find("*/", i + 2)
            i = n if end < 0 else end + 2
            out.append(" ")
        else:
            out.append(c)
            i += 1
    return "".join(out)


def find_write_statements(sql):
    """返回问题清单；空清单表示只有读语句。"""
    body = strip_literals(sql)
    low = body.lower()
    problems = []
    for kw in WRITE_KEYWORDS:
        # 用词边界匹配，避免把 created_at 之类的列名当关键字。
        if re.search(rf"(?<![a-z0-9_]){kw}(?![a-z0-9_])", low):
            problems.append(f"出现了写语句关键字 {kw.upper()}")
    for m in PRAGMA_RE.finditer(low):
        name, tail = m.group(1), m.group(2)
        if name not in READONLY_PRAGMAS:
            problems.append(f"PRAGMA {name} 不在只读白名单里")
        elif tail in ("=", "("):
            problems.append(f"PRAGMA {name}{tail}… 会改设置，不是只读查询")
    return problems


def parse_ref(path):
    """把 ref.sql 切成若干对象定义。返回 [{kind,id,sql,tol,unit,line}]。"""
    text = read_text(path, "参考 SQL 文件")
    objects, cur = [], None
    for lineno, line in enumerate(text.splitlines(), 1):
        m = DECL_RE.match(line)
        if m:
            cur = {"kind": m.group(1), "id": m.group(2), "sql": [],
                   "tol": None, "unit": None, "line": lineno}
            tail = m.group(3)
            t, u = TOL_RE.search(tail), UNIT_RE.search(tail)
            cur["tol"] = float(t.group(1)) if t else None
            cur["unit"] = u.group(1) if u else None
            objects.append(cur)
            continue
        stripped = line.strip()
        if cur is None:
            if stripped and not stripped.startswith("--"):
                raise InputError(f"参考 SQL 第 {lineno} 行：SQL 出现在第一个 "
                                 f"`-- chart:` / `-- kpi:` 声明之前")
            continue
        if stripped.startswith("--") or not stripped:
            # 段头（第一句 SQL 之前）的注释里可以追加 tol / unit 覆盖。
            if stripped.startswith("--") and not cur["sql"]:
                if cur["tol"] is None:
                    t = TOL_RE.search(stripped)
                    if t:
                        cur["tol"] = float(t.group(1))
                if cur["unit"] is None:
                    u = UNIT_RE.search(stripped)
                    if u:
                        cur["unit"] = u.group(1)
            continue
        cur["sql"].append(line)

    if not objects:
        raise InputError(f"参考 SQL 文件里没有 `-- chart: <id>` 或 `-- kpi: <id>` 声明：{path}")

    seen = set()
    for obj in objects:
        where = f"参考 SQL 第 {obj['line']} 行（{obj['kind']} {obj['id']}）"
        if obj["id"] in seen:
            raise InputError(f"{where}：id 重复")
        seen.add(obj["id"])
        sql = "\n".join(obj["sql"]).strip()
        if not sql:
            raise InputError(f"{where}：声明之后没有 SQL")
        problems = find_write_statements(sql)
        if problems:
            raise InputError(f"{where}：拒绝运行，参考 SQL 只允许只读查询 -> "
                             + "；".join(sorted(set(problems))))
        obj["sql"] = sql
    return objects


# --------------------------------------------------------------------------- 数据库

def sha256_file(path, chunk=1 << 20):
    """库文件的 SHA-256，与 db_fingerprint.py / u2/u3_check 同一个算法。"""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def read_baseline(path):
    """从 --before 基线文件里取 sha256（与 u2/u3 同一套读法）。

    兼容：db_fingerprint.py 的输出（含 `sha256:` 行）、只写了 64 位十六进制、
    文件被不同终端重定向成 UTF-8 / 带 BOM / GBK / UTF-16（含 BOM，或 ASCII 部分夹着 0x00）。
    """
    raw = Path(path).read_bytes()
    texts = []
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


def check_fingerprint(db, before):
    """业务库指纹：和 --before 基线里的 SHA-256 比；措辞与 u2/u3_check 一致。"""
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
    return False, f"已变（基线 {want[:12]}… 现在 {short}…）：看板只读，业务库不该有任何改动"


def open_readonly(db_path):
    p = Path(db_path)
    if not p.is_file():
        raise InputError(f"数据库文件不存在：{p}")
    try:
        uri = p.resolve().as_uri() + "?mode=ro"
    except ValueError:
        uri = "file:" + p.resolve().as_posix() + "?mode=ro"
    try:
        con = sqlite3.connect(uri, uri=True)
        con.execute("PRAGMA query_only = ON")     # 双保险：连上之后再钉一次只读
        con.execute("SELECT count(*) FROM sqlite_master").fetchone()
    except sqlite3.Error as exc:
        raise InputError(f"打不开数据库（只读模式）：{p} -> {exc}")
    return con


def expected_from_db(db_path, ref_path, tol_ratio, tol_money):
    objects = parse_ref(ref_path)
    con = open_readonly(db_path)
    result = []
    try:
        for obj in objects:
            where = f"参考 SQL 第 {obj['line']} 行（{obj['kind']} {obj['id']}）"
            try:
                rows = con.execute(obj["sql"]).fetchall()
            except sqlite3.Error as exc:
                raise InputError(f"{where}：执行失败 -> {exc}")
            result.append(build_expected(obj, rows, where, tol_ratio, tol_money))
    finally:
        con.close()
    return result


def build_expected(obj, rows, where, tol_ratio, tol_money):
    item = {"id": obj["id"], "kind": obj["kind"], "tol": obj["tol"], "unit": obj["unit"]}
    if obj["kind"] == "kpi":
        if len(rows) != 1 or len(rows[0]) != 1:
            raise InputError(f"{where}：kpi 段必须返回一行一列，实际 {len(rows)} 行")
        item["value"] = as_float(rows[0][0], where)
        values = [item["value"]]
    else:
        series, values, seen_points = {}, [], set()
        for row in rows:
            if len(row) != 3:
                raise InputError(f"{where}：chart 段必须返回三列（series, x, value），"
                                 f"实际 {len(row)} 列")
            name, x, value = str(row[0]).strip(), str(row[1]).strip(), as_float(row[2], where)
            if (name, x) in seen_points:      # 同一个系列同一个 x 出现两次：参考 SQL 写重了
                raise InputError(f"{where}：系列 {name} 的 x={x} 出现了不止一次")
            seen_points.add((name, x))
            series.setdefault(name, []).append({"x": x, "value": value})
            values.append(value)
        if not series:
            raise InputError(f"{where}：chart 段没有返回任何行")
        item["series"] = series
    apply_unit_and_tol(item, values, tol_ratio, tol_money)
    return item


def apply_unit_and_tol(item, values, tol_ratio, tol_money):
    """决定这一段的容差：段头 tol 优先；否则按 unit（不写就按量级猜）。"""
    if item["unit"] is None:
        item["unit"] = "ratio" if all(abs(v) <= 1.0 + 1e-12 for v in values) else "money"
    default = tol_money if UNIT_TOLERANCE[item["unit"]] == "tol_money" else tol_ratio
    if item["tol"] is None:
        item["tol"] = default


def expected_from_json(path, tol_ratio, tol_money):
    """--expected：形状与导出契约等价，kpis/charts 按 id 对齐。"""
    data = load_json(path, "期望 JSON")
    objects = []
    for raw in data.get("kpis") or []:
        if not isinstance(raw, dict) or "id" not in raw:
            raise InputError("期望 JSON 的 kpis 里有一项缺少 id")
        item = {"id": str(raw["id"]), "kind": "kpi",
                "value": as_float(raw.get("value"), f"期望 JSON kpi {raw['id']}"),
                "unit": raw.get("unit"), "tol": raw.get("tol")}
        item["tol"] = float(item["tol"]) if item["tol"] is not None else None
        apply_unit_and_tol(item, [item["value"]], tol_ratio, tol_money)
        objects.append(item)
    for raw in data.get("charts") or []:
        if not isinstance(raw, dict) or "id" not in raw:
            raise InputError("期望 JSON 的 charts 里有一项缺少 id")
        cid = str(raw["id"])
        series, values = {}, []
        for s in raw.get("series") or []:
            if not isinstance(s, dict) or "name" not in s:
                raise InputError(f"期望 JSON 图表 {cid} 的 series 里有一项缺少 name")
            name = str(s["name"]).strip()
            if name in series:
                raise InputError(f"期望 JSON 图表 {cid} 的系列名重复：{name}")
            points = []
            seen_x = set()
            for p in s.get("points") or []:
                if not isinstance(p, dict) or "x" not in p or "value" not in p:
                    raise InputError(f"期望 JSON 图表 {cid} / 系列 {name} 的点缺少 x 或 value")
                x = str(p["x"]).strip()
                if x in seen_x:
                    raise InputError(f"期望 JSON 图表 {cid} / 系列 {name} 的 x={x} 出现了不止一次")
                seen_x.add(x)
                v = as_float(p["value"], f"期望 JSON 图表 {cid} / 系列 {name} / x={x}")
                points.append({"x": x, "value": v})
                values.append(v)
            if not points:
                raise InputError(f"期望 JSON 图表 {cid} / 系列 {name} 没有任何点")
            series[name] = points
        if not series:
            raise InputError(f"期望 JSON 图表 {cid} 没有任何系列")
        item = {"id": cid, "kind": "chart", "series": series,
                "unit": raw.get("unit"), "tol": raw.get("tol")}
        item["tol"] = float(item["tol"]) if item["tol"] is not None else None
        apply_unit_and_tol(item, values, tol_ratio, tol_money)
        objects.append(item)
    if not objects:
        raise InputError(f"期望 JSON 里没有 kpis / charts：{path}")
    ids = [o["id"] for o in objects]
    if len(ids) != len(set(ids)):
        raise InputError("期望 JSON 里有重复的 id")
    return objects


# --------------------------------------------------------------------------- 导出文件

def load_json(path, what):
    text = read_text(path, what)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise InputError(f"{what} 不是合法 JSON：{path} -> {exc}")
    if isinstance(data, str):      # 控制台里 copy 出来又整体加了引号的情况
        try:
            data = json.loads(data)
        except json.JSONDecodeError as exc:
            raise InputError(f"{what} 是被编码了两次的 JSON，第二层解不开：{exc}")
    if not isinstance(data, dict):
        raise InputError(f"{what} 的顶层应当是一个对象（JSON object），实际是 {type(data).__name__}")
    return data


def load_export(path):
    data = load_json(path, "导出文件")
    charts, kpis = data.get("charts"), data.get("kpis")
    if charts is None and kpis is None:
        raise InputError("导出文件里既没有 charts 也没有 kpis，"
                         "确认用的是 `await window.__chartExport()` 的完整返回值")
    for key, value in (("charts", charts), ("kpis", kpis)):
        if value is not None and not isinstance(value, list):
            raise InputError(f"导出文件的 {key} 应当是数组")
    return data


def swap_series_names(export, name_a, name_b):
    """把导出里的两个系列名对调（点不动），负向自检用。"""
    hit = 0
    for chart in export.get("charts") or []:
        for s in chart.get("series") or []:
            if not isinstance(s, dict):
                continue
            name = s.get("name")
            if name == name_a:
                s["name"] = name_b
                hit += 1
            elif name == name_b:
                s["name"] = name_a
                hit += 1
    return hit


# --------------------------------------------------------------------------- 比对

def compare_kpi(exp, got):
    """返回 (ok, 短原因, 明细行列表)。"""
    if got is None:
        return False, "导出里找不到这个 kpi", ["缺失：" f"kpi {exp['id']}"]
    raw = got.get("value")
    try:
        value = as_float(raw, f"导出 kpi {exp['id']}")
    except InputError as exc:
        return False, "导出的 value 不是数字", [str(exc)]
    diff = abs(value - exp["value"])
    if diff > exp["tol"]:
        return False, f"值超出容差（差 {fmt_num(diff)} > {fmt_num(exp['tol'])}）", [
            f"导出 {fmt_num(value)}，期望 {fmt_num(exp['value'])}，"
            f"差 {fmt_num(diff)} > 容差 {fmt_num(exp['tol'])}（{exp['unit']}）"]
    return True, f"值 {fmt_num(value)} 与期望一致（容差 {fmt_num(exp['tol'])}）", []


def compare_chart(exp, got):
    if got is None:
        return False, "导出里找不到这张图表", [f"缺失：chart {exp['id']}"]
    raw_series = got.get("series")
    if not isinstance(raw_series, list):
        return False, "导出的 series 不是数组", [f"导出 chart {exp['id']} 的 series 不是数组"]
    got_series, dup = {}, []
    for s in raw_series:
        if not isinstance(s, dict) or "name" not in s:
            return False, "导出的 series 里有项缺少 name", []
        name = str(s["name"]).strip()
        if name in got_series:
            dup.append(name)
        pts = s.get("points")
        if not isinstance(pts, list):
            return False, f"系列 {name} 的 points 不是数组", []
        got_series[name] = pts

    missing_series = [n for n in exp["series"] if n not in got_series]
    extra_series = [n for n in got_series if n not in exp["series"]]
    missing_pts, extra_pts, bad_pts, bad_x = [], [], [], []
    for name, exp_points in exp["series"].items():
        if name not in got_series:
            continue
        got_map = {}
        for p in got_series[name]:
            if not isinstance(p, dict) or "x" not in p or "value" not in p:
                return False, f"系列 {name} 有点缺少 x 或 value", []
            got_map[str(p["x"]).strip()] = p["value"]
        exp_x = set()
        for p in exp_points:
            exp_x.add(p["x"])
            if p["x"] not in got_map:
                missing_pts.append(f"{name} x={p['x']}")
                continue
            try:
                value = as_float(got_map[p["x"]], f"导出 chart {exp['id']} / {name} / x={p['x']}")
            except InputError as exc:
                bad_pts.append(str(exc))
                continue
            diff = abs(value - p["value"])
            if diff > exp["tol"]:
                bad_pts.append(f"{name} x={p['x']}：导出 {fmt_num(value)}，"
                               f"期望 {fmt_num(p['value'])}，差 {fmt_num(diff)}")
        for x in got_map:
            if x not in exp_x:
                extra_pts.append(f"{name} x={x}")

    details = []
    if missing_series:
        details.append("缺系列：" + "、".join(missing_series))
    if extra_series:
        details.append("多系列（未在期望里声明，只提示不计红）：" + "、".join(extra_series))
    if dup:
        details.append("系列名重复：" + "、".join(sorted(set(dup))))
    if missing_pts:
        details.append("缺失点：" + join_limited(missing_pts))
    if extra_pts:
        details.append("多余点：" + join_limited(extra_pts))
    if bad_x:
        details.append("读不出的点：" + join_limited(bad_x))
    for line in bad_pts:
        details.append("超差点：" + line)

    hard = bool(missing_series or dup or missing_pts or extra_pts or bad_pts or bad_x)
    if not hard:
        n = sum(len(v) for v in exp["series"].values())
        reason = (f"{len(exp['series'])} 个系列 / {n} 个点全部对上"
                  f"（容差 {fmt_num(exp['tol'])}，{exp['unit']}）")
        if extra_series:
            reason += "，另有未声明的系列"
        return True, reason, details
    parts = []
    if missing_series:
        parts.append(f"缺系列 {len(missing_series)}")
    if missing_pts:
        parts.append(f"缺失点 {len(missing_pts)}")
    if extra_pts:
        parts.append(f"多余点 {len(extra_pts)}")
    if bad_pts:
        parts.append(f"超差点 {len(bad_pts)}")
    if bad_x:
        parts.append(f"读不出的点 {len(bad_x)}")
    if dup:
        parts.append(f"系列名重复 {len(dup)}")
    if extra_series:
        parts.append(f"多系列 {len(extra_series)}（不计红）")
    return False, "，".join(parts), details


def check_label(label, value, unit, tol):
    """kpi 的 label 软核对：一致返回 None，否则返回一句说明（只报 WARN）。"""
    if label is None:
        return None
    if not isinstance(label, str):
        return "label 不是字符串，读不出显示文字"
    text = label.strip()
    if not text:
        return "label 是空字符串"
    m = NUM_RE.search(text)
    if not m:
        return f"label {text!r} 里读不出数字"
    raw = m.group(0).replace(",", "")
    try:
        shown = float(raw)
    except ValueError:
        return f"label {text!r} 里读不出数字"
    percent = "%" in text
    expected = value * 100.0 if percent else value
    decimals = len(raw.split(".")[1]) if "." in raw else 0
    # 半个末位（label 显示到哪一位就按哪一位）+ 这一段自己的容差
    allowed = 0.5 * (10 ** -decimals) + (tol * (100.0 if percent else 1.0))
    if abs(shown - expected) > allowed:
        how = "百分比" if percent else "原值"
        return (f"label {text!r} 按{how}读作 {fmt_num(shown)}，与 value {fmt_num(value)} "
                f"对不上（应当显示 {fmt_num(expected)} 左右，允许偏差 {fmt_num(allowed)}，"
                f"单位 {unit}）")
    return None


# --------------------------------------------------------------------------- --record：写进 user-check.md

# 节标题识别：数字编号与标题关键字都认——旧骨架的第 2 节是「## 2 人眼」，新骨架是
# 「## 2 人眼三问」，追加时两种都要能找到第 1 节的边界（F51 口径三末条）。
SECTION1_RE = re.compile(r"^##(?!#)[ \t]*(?:1(?![0-9])|[^\n]*命令与输出)", re.M)
SECTION2_RE = re.compile(r"^##(?!#)[ \t]*(?:2(?![0-9])|[^\n]*人眼)", re.M)
SECTION3_RE = re.compile(r"^##(?!#)[ \t]*(?:3(?![0-9])|[^\n]*结论)", re.M)
RECORD_NOTE = "> 本节由检查命令自动生成，不要手改。"
# 新建时只写三节（F51 口径一、口径三）：第 1 节归命令，第 2 节人眼三问与第 3 节结论
# 留给学员自己写；三问用口径页的统一步骤措辞，冒号后留空。
RECORD_SKELETON = (
    "# 用户抽验记录\n"
    "\n"
    "## 1 命令与输出\n"
    "（检查命令自动写入，不要手改）\n"
    "## 2 人眼三问\n"
    "1. 数字对上了吗：\n"
    "2. 一眼看得懂吗：\n"
    "3. 有没有明显错的：\n"
    "## 3 结论\n"
    "放行 / 打回 + 退回哪一环：\n"
)


class _Tee:
    """把 stdout 同时写一份到内存里：屏幕上的输出原样保留，记录里也一字不差。"""

    def __init__(self, stream, buffer):
        self._stream = stream
        self._buffer = buffer

    def write(self, data):
        self._buffer.write(data)
        return self._stream.write(data)

    def flush(self):
        self._stream.flush()

    def __getattr__(self, name):          # isatty / encoding 之类照旧问真身
        return getattr(self._stream, name)


def _cmdline(tool: str, argv: list[str]) -> str:
    """本次运行的命令行（规范化成 `python <脚本名> …`，只含参数，不含任何密钥）。"""
    parts = ["python", tool]
    for item in argv:
        parts.append(f'"{item}"' if (" " in item or "\t" in item) else item)
    return " ".join(parts)


def record_block(tool: str, argv: list[str], printed: str, exit_code: int) -> str:
    """一段 Markdown：命令行、本次输出、退出码。"""
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
    """把一段记录插进「## 1 命令与输出」里（插在下一节之前）；没有这一节就在末尾补一节。

    下一节按编号 2/3 或标题里的“人眼”“结论”认：旧骨架的「## 2 人眼」与新骨架的
    「## 2 人眼三问」都能定位；第 2、3 节由学员写，追加时原样保留。
    """
    if not text.endswith("\n"):
        text += "\n"
    first = SECTION1_RE.search(text)
    if first is None:
        return text.rstrip("\n") + "\n\n## 1 命令与输出\n\n" + block + "\n"
    after = first.end()
    stops = [m.start() for m in (SECTION2_RE.search(text, after),
                                 SECTION3_RE.search(text, after)) if m]
    insert_at = min(stops) if stops else len(text)
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


# --------------------------------------------------------------------------- 主流程

def build_parser():
    p = ChineseParser(
        prog="chart_check.py",
        description="把页面导出的图表数据（window.__chartExport()）与自己的期望值逐对象、"
                    "逐系列、逐点对上。期望值来自 ref.sql + 只读库，或来自一份期望 JSON。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "容差\n"
            "  比例  --tol-ratio  默认 0.001（比 0-1 的小数）\n"
            "  金额  --tol-money  默认 0.01（元）\n"
            "  段头 `-- tol: 0.005` 覆盖该段（也可写在段头注释里）\n"
            "  段头 `-- unit: ratio|money|other` 指定该段单位；不写时按量级猜：\n"
            "  该段所有期望值绝对值都不超过 1 就按比例比，否则按金额比。\n"
            "\n"
            "判红与提示\n"
            "  FAIL：缺对象、缺系列、系列名重复、缺失点、多余点、超差点。\n"
            "  WARN（不影响退出码）：导出里多出来的系列或对象（期望值没声明）、\n"
            "        kpi 的显示文字与数值对不上。\n"
            "\n"
            "kpi 的 label 软核对（只报 WARN，不影响 PASS/FAIL 与退出码）\n"
            "  带 % 的 label：value×100 后与 label 里的数字比；不带 %：按原值比。\n"
            "  允许偏差 = 半个末位（label 显示几位小数按几位）+ 该段容差。\n"
            "  读不出数字、差得离谱，都只打印 WARN。\n"
            "\n"
            "负向自检\n"
            "  --swap \"本期,上年同期\"  导出的系列名先对调再比；正确的看板必须变红。\n"
            "  带 --swap 时退出码仍按“有 FAIL 就是 1”，所以自检正常时退出码就是 1。\n"
            "\n"
            "抽验记录（可选）\n"
            "  --record <运行目录>\\evidence\\user-check.md\n"
            "  把本次的命令行、上面这一屏输出（逐项 PASS/FAIL 与汇总）与退出码，追加写进那份\n"
            "  user-check.md 的「## 1 命令与输出」；文件不存在就按骨架新建（「## 2 人眼三问」\n"
            "  「## 3 结论」留给学员自己写）。文件是 UTF-8（带不带 BOM）或 UTF-16 都读得进，\n"
            "  写回统一存成 UTF-8。不给 --record 时不写文件，输出与此前完全一样。\n"
            "  参数或输入文件有问题（退出码 2）时不写记录。\n"
            "\n"
            "业务库指纹（可选，与单元二到四的检查命令同款）\n"
            "  第一步（开工前做一次，只做一次）：存指纹基线\n"
            "    python v2/lab/tools/db_fingerprint.py <库> > before.txt\n"
            "    （Windows PowerShell 5.1 的 `>` 会写成 UTF-16，本脚本照样读得进）\n"
            "\n"
            "  正向：单元一推荐的一条命令（对账 + 业务库指纹 + 抽验记录）\n"
            "    python chart_check.py --db <库> --ref <ref.sql> --export <导出.json> "
            "--before <开工前指纹> --record <运行目录>\\evidence\\user-check.md\n"
            "\n"
            "  负向：把两个系列名对调，必须变红（退出码 1）\n"
            "    python chart_check.py --db <库> --ref <ref.sql> --export <导出.json> "
            "--swap \"本期,上年同期\" --before <开工前指纹> "
            "--record <运行目录>\\evidence\\user-check.md\n"
            "\n"
            "  给了 --before，对账各项之后多打一行 [PASS] / [FAIL] 业务库指纹，措辞与\n"
            "  u2/u3/u4_check 一致；这一项 FAIL 也计入退出码 1。\n"
            "  --before 必须与 --db 一起给（只给 --before 是参数错误，退出码 2）。\n"
            "  不给 --before 时，输出与行为跟没有这个选项时逐字一致。\n"
            "\n"
            "退出码\n"
            "  0 全 PASS；1 至少一个 FAIL；2 参数或输入文件有问题，没跑起来。\n"
            "\n"
            "样例（数据不在库里时）\n"
            "  python chart_check.py --expected sample_expected.json --export export.json\n"
            "  python chart_check.py --expected sample_expected.json --export export.json "
            "--record <运行目录>\\evidence\\user-check.md\n"
        ),
    )
    p.add_argument("--export", required=True, metavar="PATH",
                   help="页面导出的 JSON（window.__chartExport() 的返回值）")
    p.add_argument("--db", metavar="PATH", help="课程数据库路径，只读打开（需同时给 --ref）")
    p.add_argument("--ref", metavar="PATH", help="参考 SQL 文件，按 `-- chart:` / `-- kpi:` 分段")
    p.add_argument("--expected", metavar="PATH",
                   help="期望值 JSON（与导出契约等价），作为 --db/--ref 的替代输入")
    p.add_argument("--tol-ratio", type=float, default=DEFAULT_TOL_RATIO, metavar="FLOAT",
                   help=f"比例容差，默认 {DEFAULT_TOL_RATIO}")
    p.add_argument("--tol-money", type=float, default=DEFAULT_TOL_MONEY, metavar="FLOAT",
                   help=f"金额容差，默认 {DEFAULT_TOL_MONEY}")
    p.add_argument("--swap", metavar="A,B",
                   help="负向自检：把导出里的两个系列名对调后再比（正确的看板必须变红）")
    p.add_argument("--before", metavar="PATH",
                   help="开工前存的指纹基线（db_fingerprint.py 的输出），需与 --db 一起给；"
                        "给了就在对账各项之后多报一项“业务库指纹”")
    p.add_argument("--record", metavar="PATH",
                   help="把本次命令行、各项 PASS/FAIL 输出与退出码追加进这个 user-check.md 的"
                        "「## 1 命令与输出」")
    return p


def resolve_tolerances(args):
    if args.tol_ratio < 0 or args.tol_money < 0:
        raise InputError("容差不能是负数")
    return args.tol_ratio, args.tol_money


def resolve_expected_source(args, tol_ratio, tol_money):
    use_sql = bool(args.db) or bool(args.ref)
    if use_sql and args.expected:
        raise InputError("--expected 与 --db/--ref 只能二选一")
    if use_sql:
        if not (args.db and args.ref):
            raise InputError("--db 与 --ref 必须一起给（或改用 --expected）")
        return expected_from_db(args.db, args.ref, tol_ratio, tol_money), "ref.sql + 只读库"
    if args.expected:
        return expected_from_json(args.expected, tol_ratio, tol_money), "期望 JSON"
    raise InputError("要给期望值：--db ... --ref ...，或者 --expected ...")


def parse_swap(text):
    names = [n.strip() for n in text.split(",")]
    if len(names) != 2 or not names[0] or not names[1]:
        raise InputError('--swap 的写法是 "A,B"（两个系列名，逗号分隔），例如 --swap "本期,上年同期"')
    if names[0] == names[1]:
        raise InputError("--swap 的两个系列名不能相同")
    return names[0], names[1]


def swap_hint(swap):
    """正向通过时的末行提示：给了 --swap 就照实参里的两个系列名写，没给就用通用写法。

    不再写死某一对系列名：对账对象可能只画了别的系列（例如“本期”与“市场基准”），
    写死会让学员照抄一个在本份数据里对调不生效的命令。
    """
    if swap:
        return (f'提示：把它当负向自检用，加 --swap "{swap[0]},{swap[1]}"；'
                f'正确的看板此时必须变红。')
    return ('提示：把它当负向自检用，加 --swap "系列名A,系列名B"'
            '（换成导出里要装反的那两个系列名）；正确的看板此时必须变红。')


MAX_DETAIL = 6          # 每个对象最多列几条明细，免得一份表刷满一屏


def print_header(args, objects, source, swap):
    print("=" * 78)
    print("chart_check 图表导出对账")
    print(f"期望值来源：{source}")
    if args.expected:
        print(f"  {Path(args.expected).resolve()}")
    else:
        print(f"  参考 SQL：{Path(args.ref).resolve()}")
        print(f"  数据库（mode=ro，只读）：{Path(args.db).resolve()}")
    print(f"导出文件：{Path(args.export).resolve()}")
    if args.before:
        print(f"开工前指纹：{Path(args.before).expanduser().resolve()}")
    print(f"对象 {len(objects)} 个：" + "、".join(o["id"] for o in objects))
    if args.swap:
        print(f"负向自检：导出里的系列名 {swap[0]} <-> {swap[1]} 先对调，再照常比")


def main(argv=None):
    try:
        sys.stdout.reconfigure(errors="replace")   # 打不出的字符换成 ?，不抛异常
        sys.stderr.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass

    raw_argv = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(argv)
    record = Path(args.record).expanduser() if args.record else None
    try:
        if args.before and not args.db:
            raise InputError("--before 要与 --db 一起给：先指明业务库，再给开工前存的指纹基线")
        tol_ratio, tol_money = resolve_tolerances(args)
        objects, source = resolve_expected_source(args, tol_ratio, tol_money)
        export = load_export(args.export)
        swap = parse_swap(args.swap) if args.swap else None
    except InputError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2

    if record is None:
        return report(args, objects, source, swap, export, tol_ratio, tol_money)

    # 给了 --record：这一屏输出同时收一份，跑完再原样追加进 user-check.md 的第 1 节。
    printed = io.StringIO()
    with contextlib.redirect_stdout(_Tee(sys.stdout, printed)):
        code = report(args, objects, source, swap, export, tol_ratio, tol_money)
    ok, info = write_record(record, record_block("chart_check.py", raw_argv, printed.getvalue(), code))
    print(f"记录：{'已写进' if ok else '没写成'} {info}")
    return code


def report(args, objects, source, swap, export, tol_ratio, tol_money):
    """把这一屏对账结果打印出来；返回值就是要给宿主的退出码（0 全 PASS，1 有 FAIL）。"""
    print_header(args, objects, source, swap)

    hits = 0
    if swap:
        hits = swap_series_names(export, *swap)
        if hits == 0:
            print(f"  注意：导出里找不到系列名 {swap[0]} / {swap[1]}，对调没有生效，"
                  f"这一次不能算有效的负向自检")

    page = export.get("page")
    if page is not None:
        print(f"导出页：{page}")
    print("-" * 78)

    width = max([len(o["id"]) for o in objects] + [12])
    n_pass = n_fail = n_warn = 0
    for index, obj in enumerate(objects, 1):
        got = None
        pool = export.get("kpis" if obj["kind"] == "kpi" else "charts") or []
        for candidate in pool:
            if isinstance(candidate, dict) and str(candidate.get("id")) == obj["id"]:
                got = candidate
                break
        if obj["kind"] == "kpi":
            ok, reason, details = compare_kpi(obj, got)
        else:
            ok, reason, details = compare_chart(obj, got)

        warns = []
        if ok and obj["kind"] == "kpi" and got is not None:
            warn = check_label(got.get("label"), obj["value"], obj["unit"], obj["tol"])
            if warn:
                warns.append(warn)

        if ok:
            n_pass += 1
        else:
            n_fail += 1
        n_warn += len(warns)

        status = "PASS" if ok else "FAIL"
        print(f"[{index}/{len(objects)}] {obj['kind']:<5} {obj['id']:<{width}} {status}  {reason}")
        for line in details[:MAX_DETAIL]:
            print(f"    - {line}")
        if len(details) > MAX_DETAIL:
            print(f"    - ……另有 {len(details) - MAX_DETAIL} 条明细未列出")
        for w in warns:
            print(f"    ! WARN {w}")

    # 导出里有、期望值里没声明的对象：不判红，但要提示，免得以为它被检查过了。
    exp_ids = {o["id"] for o in objects}
    extra_objects = []
    for kind, key in (("kpi", "kpis"), ("chart", "charts")):
        for item in export.get(key) or []:
            if isinstance(item, dict) and str(item.get("id")) not in exp_ids:
                extra_objects.append(f"{kind} {item.get('id')}")

    # 业务库指纹（可选）：与 u2/u3/u4_check 同款，对账各项之后多这一项。
    # 单列一项，不混进对象的 PASS/FAIL 个数；它 FAIL 同样计入退出码 1。
    fp_ok = True
    fp_part = ""
    if args.before:
        fp_ok, fp_reason = check_fingerprint(Path(args.db).expanduser(),
                                             Path(args.before).expanduser())
        print(f"[{'PASS' if fp_ok else 'FAIL'}] 业务库指纹：{fp_reason}")
        fp_part = f"业务库指纹 {'PASS' if fp_ok else 'FAIL'}；"

    print("-" * 78)
    if extra_objects:
        n_warn += len(extra_objects)
        print(f"WARN 导出里有 {len(extra_objects)} 个对象未在期望值里声明（不计红）："
              + join_limited(extra_objects))
    ok_all = n_fail == 0 and fp_ok
    print(f"汇总：对象 {len(objects)} 个，PASS {n_pass}，FAIL {n_fail}，WARN {n_warn}；"
          f"{fp_part}"
          f"容差 比例 {fmt_num(tol_ratio)}、金额 {fmt_num(tol_money)} -> "
          f"{'全部通过' if ok_all else '不通过'}（退出码 {0 if ok_all else 1}）")
    if swap:
        if n_fail:
            print(f"负向自检结果：装反后有 {n_fail} 个对象转红，符合预期（此时退出码 1 是正确的）")
        else:
            print("负向自检结果：装反后仍然全绿，这条判据对装反不敏感，需要换判据")
    elif ok_all and any(isinstance(c, dict) and c.get("series")
                        for c in export.get("charts") or []):
        # 走到这一支说明这次没带 --swap（带了会走上面那一支），所以提示用通用写法；
        # 提示文本由 swap_hint 按实参生成，将来哪支都放这句时，会直接写出实际的系列名。
        # 导出里没有任何 charts 系列（只有 kpis）时不提 --swap：这份导出没有可装反的系列。
        print(swap_hint(swap))
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
