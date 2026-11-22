#!/usr/bin/env python3
"""库文件指纹：打印库文件的 SHA-256 与字节数，可选与上一次输出自动比对。

用法：
    python v2/lab/tools/db_fingerprint.py <库文件路径>
    python v2/lab/tools/db_fingerprint.py <库文件路径> <上次输出文件>

不比对时输出四行，可直接重定向保存：
    db_fingerprint v1
    db: <绝对路径>
    bytes: <字节数>
    sha256: <64 位小写十六进制>

带比对文件时再追加两行：
    compare_sha256: <上次的 sha256>
    result: 不变
    （或 result: 已变）

退出码：0 未比对或结果不变；1 结果已变；2 参数或读文件出错。
只用 Python 3.12 标准库；Windows PowerShell 与 Git Bash 均可运行。
"""
from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

HEX64 = re.compile(r"\b[0-9a-fA-F]{64}\b")


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
            ok = False
            try:
                "中文口径".encode(enc)
                ok = True
            except Exception:
                ok = False
            if ok:
                stream.reconfigure(errors="replace")
            else:
                stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def read_previous(path: Path) -> str:
    """从上次的输出文件里取 sha256：优先读 'sha256:' 行，否则取第一个 64 位十六进制串。

    兼容不同宿主的重定向编码：UTF-8、UTF-8 BOM、GBK、UTF-16（含 BOM，或 ASCII 部分夹着 0x00）。
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
    raise ValueError("输出文件里没有 64 位十六进制 sha256")


def main(argv: list[str]) -> int:
    if len(argv) not in (2, 3):
        print("用法：python db_fingerprint.py <库文件路径> [上次输出文件]", file=sys.stderr)
        return 2
    db = Path(argv[1]).expanduser()
    if not db.is_file():
        print(f"错误：找不到库文件 {db}", file=sys.stderr)
        return 2
    try:
        size = db.stat().st_size
        digest = sha256_file(db)
    except OSError as exc:
        print(f"错误：读不了库文件 {db}（{exc}）", file=sys.stderr)
        return 2

    print("db_fingerprint v1")
    print(f"db: {db.resolve()}")
    print(f"bytes: {size}")
    print(f"sha256: {digest}")

    if len(argv) == 3:
        prev_path = Path(argv[2]).expanduser()
        if not prev_path.is_file():
            print(f"错误：找不到上次输出文件 {prev_path}", file=sys.stderr)
            return 2
        try:
            prev = read_previous(prev_path)
        except (OSError, ValueError) as exc:
            print(f"错误：解析上次输出失败（{exc}）", file=sys.stderr)
            return 2
        print(f"compare_sha256: {prev}")
        if prev == digest:
            print("result: 不变")
            return 0
        print("result: 已变")
        return 1
    return 0


if __name__ == "__main__":
    setup_stdio()
    sys.exit(main(sys.argv))
