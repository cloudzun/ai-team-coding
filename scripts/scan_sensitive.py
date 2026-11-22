#!/usr/bin/env python3
"""scan_sensitive.py —— 扫 content/ 与 dist/ 里不该出现的东西。0 命中才算过。

类别：盘符与用户目录、sk- 类密钥、邮箱、圈数字、/verify、“待确认 / 以…为准”、分钟、试走/样板。
本课为自编通用课程，没有客户敏感词表。
允许名单（逐条列明，依据 l1-textbook/v2/reviews/stageC_终扫.md）：
  - ch4 里 lead 原话两处、ch5 里产品页固定提示文案两处（“以…为准”）
  - u3_check.py 一处注释（“以存档点 DDL 为准”）
  - env_check.py 一处安装位置探测路径（盘符）
跳过：二进制、zip、*.db、app/static/vendor/（第三方压缩库与许可证，非本课文字）。
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGETS = [ROOT / "content", ROOT / "dist"]

RULES = [
    ("盘符/用户目录", re.compile(r"(?<![A-Za-z0-9_])[A-Za-z]:[\\/]|[\\/]Users[\\/][^\\/\s\"']+|/home/[a-z][\w.-]*")),
    ("sk- 类密钥", re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}")),
    ("邮箱", re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}")),
    ("圈数字", re.compile("[\u2460-\u24ff\u2776-\u2793\u3251-\u325f\u32b1-\u32bf]")),
    ("/verify", re.compile(r"/verify")),
    ("待确认/以…为准", re.compile(r"待确认|以[^。\n，,；;]{0,12}为准")),
    ("分钟", re.compile(r"分钟")),
    ("试走/样板", re.compile(r"试走|样板")),
]

# 允许名单：行内出现该子串即放行（只对应上面写明的几处）
# 另：下面 ALLOW 里的 env_check.py 盘符路径、_ask.html 产品页文案（与 ch5 相同的那句），同样经 lead 裁定放行。
ALLOW = [
    ("待确认/以…为准", "以你工具箱的实际格式为准"),
    ("待确认/以…为准", "请以下方数据为准"),
    ("待确认/以…为准", "整改工单以存档点 DDL 为准"),
    ("盘符/用户目录", "C:/Program Files/DeepSeek Harness"),
]
# 存档点源码注释/示例域名，lead 裁定放行：stageC 终扫没有覆盖存档点的应用源码，本脚本扫到了下面三类。
# 它们在教材仓库的 checkpoints/*/app 里（本站只读，不改）；输出里单独列出。
ALLOW_EXTRA = [
    ("待确认/以…为准", "主题以被引评论原文为准", "pipeline.py"),   # 产品回答里的固定说明文案，三个存档点各一处
    ("圈数字", "// 路径", "stage2/app/static/js/dashboard.js"),    # 代码注释里的 ①②③，共 4 行
    ("邮箱", "ops@homestay.example", "ops_store.py"),             # 保留域名 .example 的演示地址，两个存档点各一处
]
SKIP_DIR = ("vendor",)
SKIP_SUFFIX = {".zip", ".db", ".png", ".jpg", ".gif", ".ico", ".woff", ".woff2"}


def iter_files(base):
    for p in sorted(base.rglob("*")):
        if not p.is_file():
            continue
        if p.suffix.lower() in SKIP_SUFFIX:
            continue
        if any(part in SKIP_DIR for part in p.relative_to(base).parts):
            continue
        yield p


def main():
    hits, allowed, extra, scanned = [], [], [], 0
    for base in TARGETS:
        if not base.exists():
            print(f"缺目录 {base.name}/（先 sync / build）")
            return 1
        for p in iter_files(base):
            try:
                text = p.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            scanned += 1
            rel = p.relative_to(ROOT).as_posix()
            for ln, line in enumerate(text.splitlines(), 1):
                for cat, rx in RULES:
                    for m in rx.finditer(line):
                        s = max(0, m.start() - 12)
                        snippet = line[s:m.end() + 12].strip()
                        rec = (cat, rel, ln, snippet)
                        if any(c == cat and sub in line for c, sub in ALLOW):
                            allowed.append(rec)
                        elif any(c == cat and sub in line and f in rel for c, sub, f in ALLOW_EXTRA):
                            extra.append(rec)
                        else:
                            hits.append(rec)
    print(f"== scan_sensitive.py：扫描 {scanned} 个文本文件（content/ + dist/）==")
    print(f"允许名单放行：{len(allowed)} 处")
    for cat, rel, ln, sn in allowed:
        print(f"  allow [{cat}] {rel}:{ln}  {sn}")
    print(f"存档点源码注释/示例域名（lead 裁定放行）：{len(extra)} 处（见脚本 ALLOW_EXTRA）")
    for cat, rel, ln, sn in extra:
        print(f"  extra [{cat}] {rel}:{ln}  {sn}")
    print(f"命中：{len(hits)}")
    for cat, rel, ln, sn in hits:
        print(f"  HIT [{cat}] {rel}:{ln}  {sn}")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
