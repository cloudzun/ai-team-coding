#!/usr/bin/env python3
"""环境自检：逐项打印绿/红，自动项全部通过时退出码为 0。

用法：
    python v2/lab/tools/env_check.py
    python v2/lab/tools/env_check.py [--db <库文件路径>] [--kit <数据包目录>]

默认：数据包目录取本脚本所在位置（v2/lab/tools）的 v2/kit；库文件取 <数据包>/db/homestay.db。

自动项：
    Python 版本 >= 3.12
    库文件存在
    库文件的内容校验和等于 <数据包>/checksums.txt 登记值
    以只读 URI（mode=ro）能读到全部业务表，并打印行数
    只读方式下一次写入被拒（并核对写尝试之后文件指纹没变）
    指标口径表与运营手册在位、校验和一致
    git 可用
    DSH 是否安装（查不到给黄色"请人工确认"，不判红）

人工勾选项（脚本判定不了，只打印清单，不计入退出码）：浏览器、coding agent、大模型接口。

只用 Python 3.12 标准库；Windows PowerShell 与 Git Bash 均可运行。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

GREEN, RED, YELLOW = "绿", "红", "黄"
MARK = {GREEN: "[绿]", RED: "[红]", YELLOW: "[黄]"}

MIN_PY = (3, 12)
BUSINESS_TABLES = [
    "meta", "districts", "owners", "listings", "price_history",
    "owner_blocks", "bookings", "reviews", "market_benchmark",
]
STAGE3_TABLES = ["price_change_requests", "maintenance_tickets", "audit_log"]

MANUAL_ITEMS = [
    ("浏览器", "打开一个本地页面（用 file:// 打开一个 .html，或打开你自己起的本地服务），"
               "在开发者工具控制台执行 1+1 得到 2"),
    ("coding agent", "在你的项目目录里新建或修改一个文件，并让它运行一条命令、读到输出"),
    ("大模型接口", "完成一次问答请求并看到回复文本（用你的客户端或 SDK）"),
]


def setup_stdio() -> None:
    """中文输出不乱码：控制台交给宿主编码；重定向时跟随宿主编码，宿主编码表示不了中文才切 UTF-8。"""
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None:
            continue
        try:
            enc = (getattr(stream, "encoding", "") or "").lower()
            is_tty = bool(getattr(stream, "isatty", lambda: False)())
            if is_tty:
                stream.reconfigure(errors="replace")
                continue
            try:
                "中文口径".encode(enc)
                can_cjk = True
            except Exception:
                can_cjk = False
            if can_cjk:
                stream.reconfigure(errors="replace")
            else:
                stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


class Report:
    def __init__(self) -> None:
        self.items: list[dict] = []

    def add(self, level: str, title: str, details: list[str] | None = None) -> None:
        self.items.append({"level": level, "title": title, "details": [d for d in (details or []) if d]})

    def print(self) -> None:
        for item in self.items:
            print(f"{MARK[item['level']]} {item['title']}")
            for d in item["details"]:
                print(f"      {d}")
        print()

    def counts(self) -> dict[str, int]:
        c = {GREEN: 0, RED: 0, YELLOW: 0}
        for item in self.items:
            c[item["level"]] += 1
        return c


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def parse_checksums(path: Path) -> dict:
    data: dict = {"files": [], "path": str(path)}
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        key, sep, value = s.partition("=")
        if not sep:
            continue
        key = key.strip().lower()
        value = value.strip()
        if key == "file":
            parts = [p.strip() for p in value.split("|")]
            if len(parts) == 3 and len(parts[0]) == 64:
                data["files"].append({"sha256": parts[0].lower(), "bytes": parts[1], "path": parts[2]})
        else:
            data[key] = value
    return data


def open_ro(db: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)


def content_checksum(db: Path) -> tuple[str, list[str], dict[str, int]]:
    """数据内容校验和：所有表按表名排序、每张表按主键排序，逐行序列化后算 sha256。"""
    con = open_ro(db)
    try:
        h = hashlib.sha256()
        tables = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        counts: dict[str, int] = {}
        for t in tables:
            cols = con.execute(f"PRAGMA table_info({t})").fetchall()
            pk = [c[1] for c in sorted(cols, key=lambda c: c[5]) if c[5] > 0] or [c[1] for c in cols]
            h.update(f"#{t}\n".encode())
            n = 0
            for row in con.execute(f"SELECT * FROM {t} ORDER BY {', '.join(pk)}"):
                h.update((json.dumps(list(row), ensure_ascii=False) + "\n").encode("utf-8"))
                n += 1
            counts[t] = n
        return h.hexdigest(), tables, counts
    finally:
        con.close()


def detect_dsh() -> tuple[list[str], list[Path]]:
    found: list[str] = []
    exe = shutil.which("dsh")
    if exe:
        found.append(f"命令 dsh 可用（{exe}）")
    home = os.environ.get("DSH_HOME")
    if home and Path(home).exists():
        found.append(f"环境变量 DSH_HOME 指向 {home}")

    probes: list[Path] = []
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA")
        roaming = os.environ.get("APPDATA")
        profile = os.environ.get("USERPROFILE")
        if local:
            probes += [Path(local) / "Programs" / "DeepSeek Harness", Path(local) / "dsh"]
        if roaming:
            probes += [Path(roaming) / "dsh", Path(roaming) / "DeepSeek Harness"]
        if profile:
            probes += [Path(profile) / ".dsh", Path(profile) / "AppData" / "Local" / "Programs" / "DeepSeek Harness"]
        probes.append(Path("C:/Program Files/DeepSeek Harness"))
    else:
        home_dir = os.environ.get("HOME")
        if home_dir:
            probes += [Path(home_dir) / ".dsh", Path(home_dir) / ".local" / "bin" / "dsh",
                       Path(home_dir) / ".local" / "share" / "deepseek-harness"]
        probes.append(Path("/Applications/DeepSeek Harness.app"))
    for p in probes:
        if p.exists():
            text = f"安装位置 {p}"
            if text not in found:
                found.append(text)
    return found, probes


def main(argv: list[str]) -> int:
    here = Path(__file__).resolve().parent
    default_kit = here.parents[1] / "kit"

    ap = argparse.ArgumentParser(description="课程数据包环境自检")
    ap.add_argument("--db", help="库文件路径（默认 <数据包>/db/homestay.db）")
    ap.add_argument("--kit", default=str(default_kit), help="数据包目录（默认 v2/kit）")
    args = ap.parse_args(argv[1:])

    kit = Path(args.kit).expanduser().resolve()
    db = Path(args.db).expanduser().resolve() if args.db else kit / "db" / "homestay.db"

    report = Report()
    print("环境自检 · 民宿托管经营系统")
    print("-" * 62)
    print(f"数据包目录：{kit}")
    print(f"库文件    ：{db}")
    print(f"Python    ：{sys.version.split()[0]}（{sys.executable}）")
    print("-" * 62)

    # 1 Python 版本
    if sys.version_info >= MIN_PY:
        report.add(GREEN, f"Python 版本 {sys.version.split()[0]}（要求 >= 3.12）")
    else:
        report.add(RED, f"Python 版本 {sys.version.split()[0]} 低于 3.12",
                   ["装 Python 3.12 或更新版本，用新版本重新运行本脚本"])

    # 2 数据包与校验登记表
    checks: dict | None = None
    if not kit.is_dir():
        report.add(RED, f"数据包目录不存在：{kit}", ["用 --kit 指向数据包目录"])
    else:
        cpath = kit / "checksums.txt"
        if cpath.is_file():
            checks = parse_checksums(cpath)
            if checks.get("db_content_sha256"):
                report.add(GREEN, "找到 checksums.txt，登记了数据内容校验和")
            else:
                report.add(RED, "checksums.txt 里没有 db_content_sha256", ["重拿一份数据包"])
                checks = None
        else:
            report.add(RED, f"缺 checksums.txt：{cpath}", ["重拿一份数据包"])

    # 3 库文件存在
    file_digest = None
    file_size = None
    if not db.is_file():
        report.add(RED, f"库文件不存在：{db}",
                   ["把课堂分发的 homestay.db 放到数据包的 db/ 目录，或用 --db 指向库文件"])
    else:
        try:
            file_size = db.stat().st_size
            file_digest = sha256_file(db)
            report.add(GREEN, f"库文件存在：{file_size:,} 字节")
        except OSError as exc:
            report.add(RED, f"读不了库文件：{exc}")

    # 4 内容校验和
    digest = None
    if file_digest is None:
        report.add(RED, "数据内容校验和：未执行（库文件不可用）")
        report.add(RED, "只读读取业务表：未执行（库文件不可用）")
        report.add(RED, "只读写入被拒：未执行（库文件不可用）")
    else:
        try:
            digest, tables, counts = content_checksum(db)
        except sqlite3.Error as exc:
            report.add(RED, f"数据内容校验和：打不开数据库（{exc}）",
                       ["确认文件是完整的 SQLite 库，没被截断或正在被别的程序写入"])
            report.add(RED, "只读读取业务表：未执行（库打不开）")
            report.add(RED, "只读写入被拒：未执行（库打不开）")
            tables, counts = [], {}
        if digest is not None:
            want = (checks or {}).get("db_content_sha256", "").strip().lower()
            file_note = []
            want_file = (checks or {}).get("db_file_sha256", "").strip().lower()
            if file_digest and want_file:
                if file_digest == want_file:
                    file_note.append("文件级 SHA-256 与登记值一致：拿到的是课堂分发的这一份文件")
                else:
                    file_note.append(f"文件级 SHA-256 与登记值不同（{file_digest}），内容校验和一致即数据相同；"
                                     "同一份数据重新生成时文件字节可能不同")
            if want and digest == want:
                report.add(GREEN, f"数据内容校验和一致：{digest}",
                           ["判断“数据是不是同一份”只看这一项"] + file_note)
            elif want:
                report.add(RED, f"数据内容校验和不符：实测 {digest}，登记 {want}",
                           ["重拿课堂分发的库文件；别用自己改过的库跑核对"])
            else:
                report.add(RED, "数据内容校验和：核不上登记值", ["重拿一份数据包"])

            # 5 只读读取业务表
            missing = [t for t in BUSINESS_TABLES if t not in tables]
            if missing:
                report.add(RED, f"只读读取业务表：缺表 {'、'.join(missing)}",
                           ["库文件不是这一版数据包，重拿一份"])
            else:
                rows = [f"{t} {counts.get(t, 0):,}" for t in BUSINESS_TABLES]
                detail = ["业务表行数（只读模式读到）："]
                for i in range(0, len(rows), 3):
                    detail.append("  " + "、".join(rows[i:i + 3]))
                extra = [t for t in STAGE3_TABLES if t in tables]
                if extra:
                    detail.append("阶段三写入表已建好：" + "、".join(f"{t} {counts.get(t, 0)}" for t in extra))
                    if any(counts.get(t, 0) for t in extra):
                        detail.append("提示：阶段三表里已有数据，说明这个库被自己写过；练习请用副本")
                report.add(GREEN, "只读 URI（mode=ro）打开成功，业务表全部可读", detail)

            # 6 只读写入被拒
            rejected, message = attempt_write(db)
            if rejected:
                after = sha256_file(db)
                if after == file_digest:
                    report.add(GREEN, f"只读方式下一次写入被拒：{message}", ["写尝试之后文件指纹未变"])
                else:
                    report.add(RED, "只读方式下文件被改动了",
                               [f"写入尝试后文件 SHA-256 变了（{after}），重拿库文件"])
            else:
                report.add(RED, f"只读方式下写入竟然成功：{message}",
                           ["库不是只读打开的，别在这个库上练习写入；重拿库文件"])

    # 7 两份资料
    if checks and checks.get("files"):
        missing = []
        bad = []
        ok = []
        for meta in checks["files"]:
            p = kit / meta["path"]
            if not p.is_file():
                missing.append(meta["path"])
                continue
            try:
                size = p.stat().st_size
                got = sha256_file(p)
            except OSError as exc:
                bad.append(f"{meta['path']}（读不了：{exc}）")
                continue
            if got == meta["sha256"] and (not meta["bytes"].isdigit() or size == int(meta["bytes"])):
                ok.append(f"{meta['path']}（{size:,} 字节）")
            else:
                bad.append(f"{meta['path']}（校验和不符）")
        if missing or bad:
            details = []
            if missing:
                details.append(f"缺失：{'、'.join(missing)}")
            if bad:
                details.append(f"不符：{'、'.join(bad)}")
            details.append("从数据包重新拿一份，不要改这两份资料")
            report.add(RED, "两份资料不齐或已改动", details)
        else:
            report.add(GREEN, "指标口径表与运营手册在位、校验和一致", ok)
    else:
        report.add(RED, "两份资料：未执行（缺 checksums.txt 或表里没有 file 登记）")

    # 8 git
    git_exe = shutil.which("git")
    if not git_exe:
        report.add(RED, "git 不在 PATH 上", ["装 Git 并确认在终端里能跑 git --version"])
    else:
        try:
            out = subprocess.run([git_exe, "--version"], capture_output=True, text=True,
                                 encoding="utf-8", errors="replace", timeout=15)
            if out.returncode == 0 and out.stdout.strip():
                report.add(GREEN, f"git 可用：{out.stdout.strip()}")
            else:
                report.add(RED, "git 命令跑不起来", [(out.stderr or out.stdout).strip()[:200]])
        except (OSError, subprocess.SubprocessError) as exc:
            report.add(RED, f"git 命令跑不起来：{exc}")

    # 9 DSH（查不到只给黄色）
    found, probes = detect_dsh()
    if found:
        report.add(GREEN, "DSH 已安装", found)
    else:
        report.add(YELLOW, "没找到 DSH，请人工确认",
                   ["已查：dsh 命令、环境变量 DSH_HOME、" +
                    "、".join(str(p) for p in probes[:4])])

    report.print()

    counts = report.counts()
    print("-" * 62)
    print(f"自动项：绿 {counts[GREEN]} / 黄 {counts[YELLOW]} / 红 {counts[RED]}")
    print("人工勾选项（脚本判定不了，不计入退出码）：")
    for name, how in MANUAL_ITEMS:
        print(f"  [ ] {name}：{how}")
    if counts[RED]:
        print(f"结论：有 {counts[RED]} 项红色未通过，按上面的提示处理；仍不通过就把整段输出交给讲师。")
        return 1
    print("结论：自动项全部通过，可以开始。")
    return 0


def attempt_write(db: Path) -> tuple[bool, str]:
    """以只读 URI 打开，尝试一次写入；被拒绝返回 (True, 错误消息)。"""
    con = open_ro(db)
    try:
        try:
            con.execute("INSERT INTO audit_log (ts, tool_name, params, result) VALUES "
                        "('自检写入尝试', 'env_check', '{}', 'probe')")
            con.commit()
            return False, "插入 audit_log 成功"
        except sqlite3.Error as exc:
            msg = str(exc)
            if "no such table" in msg.lower():
                try:
                    con.execute("CREATE TABLE __env_check_probe (x INTEGER)")
                    con.commit()
                    return False, "建表成功"
                except sqlite3.Error as exc2:
                    return True, str(exc2)
            return True, msg
    finally:
        try:
            con.close()
        except Exception:
            pass


if __name__ == "__main__":
    setup_stdio()
    sys.exit(main(sys.argv))
