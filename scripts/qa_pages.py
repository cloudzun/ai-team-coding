#!/usr/bin/env python3
"""qa_pages.py local —— 静态门禁：路由自动发现、每页无死链、实验切片命中、页数=18+已上线交付附件数。
死链与孤页检查覆盖 dist/ 下全部 html，含 labs/appendix/ 下的交付附件页。

只读 dist/ 与 .build/report.json（build.mjs 写出）。任何异常 -> 退出码 1。
"""
import hashlib
import json
import re
import sys
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
REPORT = ROOT / ".build" / "report.json"
CONTENT = ROOT / "content"
EXPECTED_PAGES = 18  # 基础页数；实际门禁 = 18 + appendix/appendix.yml 里 published: true 的条数
APPENDIX_YML = ROOT / "appendix" / "appendix.yml"

problems = []


def parse_appendix_yml(text):
    """极简行解析 appendix.yml（CI 没装 PyYAML，不引新依赖）。

    只认本仓的写法：顶层 `appendices:`，每条以 `  - id: xxx` 开头，条目里有 `published: true|false`、
    `attach: [u0, u1]`。返回 [{id, published, attach}]。读不懂（缺 published、值不是 true/false、
    条目外出现字段）就抛 ValueError，不静默当 0。
    """
    items = []
    in_list = False
    cur = None
    for ln, raw in enumerate(text.splitlines(), 1):
        line = raw.split(" #")[0].rstrip() if not raw.lstrip().startswith("#") else ""
        if not line.strip():
            continue
        if re.match(r"^appendices:\s*(\[\s*\])?$", line):
            in_list = True
            continue
        if not in_list:
            raise ValueError(f"第 {ln} 行：appendices: 之前不应有其他字段：{raw!r}")
        m = re.match(r"^\s*-\s+id:\s*(\S+)\s*$", line)
        if m:
            cur = {"id": m.group(1).strip("'\""), "published": None, "attach": [], "_ln": ln}
            items.append(cur)
            continue
        m = re.match(r"^\s+(\w+):\s*(.*)$", line)
        if not m or cur is None:
            raise ValueError(f"第 {ln} 行读不懂：{raw!r}")
        key, val = m.group(1), m.group(2).strip()
        if key == "published":
            if val not in ("true", "false"):
                raise ValueError(f"第 {ln} 行：published 只能是 true / false，实际 {val!r}")
            cur["published"] = val == "true"
        elif key == "attach":
            mm = re.fullmatch(r"\[(.*)\]", val)
            if not mm:
                raise ValueError(f"第 {ln} 行：attach 要写成 [u0, u1] 这种行内列表")
            cur["attach"] = [s.strip().strip("'\"") for s in mm.group(1).split(",") if s.strip()]
    for it in items:
        if it["published"] is None:
            raise ValueError(f"第 {it['_ln']} 行起的条目 {it['id']} 缺 published")
    return items


def _selftest_parse():
    """自测：按 appendix.yml 的实际写法解析，published 数必须对；读不懂必须报错。"""
    sample = (
        "# 注释\n"
        "appendices:\n"
        "  - id: a1\n    title: 甲 # 行尾注释\n    file: a1/appendix.md\n    baseline: abc\n"
        "    published: true\n    attach: [u0, u1, u2, u3, u4]\n"
        "  - id: a2\n    title: 乙\n    file: a2/appendix.md\n    baseline: abc\n"
        "    published: false\n    attach: [u4]\n"
        "  - id: a3\n    title: 丙\n    file: a3/appendix.md\n    baseline: abc\n"
        "    published: true\n    attach: []\n"
    )
    got = parse_appendix_yml(sample)
    assert [i["id"] for i in got if i["published"]] == ["a1", "a3"], got
    assert got[0]["attach"] == ["u0", "u1", "u2", "u3", "u4"] and got[2]["attach"] == [], got
    for broken in ("appendices:\n  - id: x\n    published: yes\n",
                   "appendices:\n  - id: x\n    title: t\n",
                   "appendices:\n  - {id: x, published: true}\n"):
        try:
            parse_appendix_yml(broken)
        except ValueError:
            continue
        raise AssertionError(f"应报错却没报：{broken!r}")
checks = []


def ok(name, detail=""):
    checks.append((True, name, detail))


def bad(name, detail):
    problems.append(f"{name}: {detail}")
    checks.append((False, name, detail))


class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ids = set()
        self.links = []   # (tag, attr, value)
        self.h1 = 0
        self.title = ""
        self._in_title = False
        self.slices = []  # data-slice section ids
        self.origin_links = {}  # section id -> has link
        self._cur_slice = None
        self._in_origin = False
        self._slice_depth = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            self.ids.add(a["id"])
        if tag == "h1":
            self.h1 += 1
        if tag == "title":
            self._in_title = True
        for key in ("href", "src"):
            if key in a and a[key] is not None:
                self.links.append((tag, key, a[key]))
        if tag == "section" and "data-slice" in a:
            self.slices.append(a["data-slice"])
            self._cur_slice = a["data-slice"]
            self.origin_links[self._cur_slice] = 0
        if tag == "p" and a.get("class") == "origin":
            self._in_origin = True
        if tag == "a" and self._in_origin and self._cur_slice:
            self.origin_links[self._cur_slice] += 1

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag == "p":
            self._in_origin = False
        if tag == "section":
            self._cur_slice = None

    def handle_data(self, data):
        if self._in_title:
            self.title += data


def sha256(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "local"
    if mode != "local":
        print("只实现了 local 模式（静态门禁）。浏览器模式由人用真浏览器验收。")
        return 2
    if not DIST.exists():
        print("dist/ 不存在，先 npm run build")
        return 1
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    mode = report.get("mode", "local")  # local = 带库本地构建；release = CI 发布模式
    release_urls = set((report.get("release_urls") or {}).values())
    print(f"构建模式：{mode}" + (f"（tag {report['tag']}）" if mode == "release" else ""))

    # 0 交付附件配置：自测解析器，再读 appendix.yml（读不懂直接失败，不当 0）
    try:
        _selftest_parse()
    except AssertionError as e:
        print(f"appendix.yml 解析器自测失败：{e}")
        return 1
    appx = []
    if APPENDIX_YML.exists():
        try:
            appx = parse_appendix_yml(APPENDIX_YML.read_text(encoding="utf-8"))
        except ValueError as e:
            print(f"appendix/appendix.yml 解析失败：{e}")
            return 1
    appx_on = [a for a in appx if a["published"]]
    ok("交付附件配置", f"appendix.yml {len(appx)} 条，published=true {len(appx_on)} 条（解析器自测通过）")
    expected = EXPECTED_PAGES + len(appx_on)

    # 1 路由自动发现
    htmls = sorted(p.relative_to(DIST).as_posix() for p in DIST.rglob("*.html"))
    if len(htmls) == expected:
        ok("页数", f"{len(htmls)} = {EXPECTED_PAGES} + 附件 {len(appx_on)}")
    else:
        bad("页数", f"发现 {len(htmls)} 页，应为 {expected}（{EXPECTED_PAGES} + 附件 {len(appx_on)}）：{htmls}")
    # 1b 交付附件页：已上线的必须存在、下线的不许出现；attach 的实验页正文要链到附件
    appx_pages = {f"labs/appendix/{a['id']}.html" for a in appx_on}
    stray = [h for h in htmls if h.startswith("labs/appendix/") and h not in appx_pages]
    miss = sorted(p for p in appx_pages if p not in htmls)
    no_link = []
    for a in appx_on:
        for lid in a["attach"]:
            lp = DIST / "labs" / f"{lid}.html"
            if not lp.exists() or f'href="appendix/{a["id"]}.html"' not in lp.read_text(encoding="utf-8"):
                no_link.append(f"labs/{lid}.html -> {a['id']}")
    if stray or miss or no_link:
        bad("交付附件页", f"缺页 {miss}；不该有的页 {stray}；实验页没链到附件 {no_link}")
    else:
        ok("交付附件页", f"{len(appx_on)} 页齐全，attach 的实验页都有入链；下线条目不出页")
    if sorted(report["pages"]) == htmls:
        ok("路由清单与构建报告一致")
    else:
        bad("路由清单", "dist/ 里的 html 与 .build/report.json 不一致")

    parsed = {}
    for rel in htmls:
        pg = Page()
        pg.feed((DIST / rel).read_text(encoding="utf-8"))
        parsed[rel] = pg

    # 2 每页：标题、h1、死链、锚点
    dead = 0
    inbound = {r: 0 for r in htmls}
    for rel, pg in parsed.items():
        if rel != "demo/index.html":
            if pg.h1 != 1:
                bad("h1", f"{rel} 有 {pg.h1} 个 h1")
            if not pg.title.strip():
                bad("title", f"{rel} 没有标题")
        base = (DIST / rel).parent
        for tag, key, val in pg.links:
            if val.startswith(("data:", "mailto:", "javascript:")):
                continue
            if re.match(r"^[a-z][a-z0-9+.-]*:", val, re.I):
                if mode == "release" and val in release_urls:
                    continue
                bad("外链", f"{rel}: {val}")
                continue
            if val.startswith("/"):
                bad("绝对路径链接", f"{rel}: {val}（应为相对路径）")
                continue
            u = urlsplit(val)
            target = (base / unquote(u.path)).resolve() if u.path else (DIST / rel).resolve()
            if target.is_dir():
                target = target / "index.html"
            try:
                trel = target.relative_to(DIST.resolve()).as_posix()
            except ValueError:
                bad("死链", f"{rel}: {val} 指向 dist/ 之外")
                dead += 1
                continue
            if not target.exists():
                bad("死链", f"{rel}: {val}")
                dead += 1
                continue
            if trel in inbound and trel != rel:
                inbound[trel] += 1
            if u.fragment and target.suffix == ".html":
                tp = parsed.get(trel)
                if tp is not None and unquote(u.fragment) not in tp.ids:
                    bad("锚点缺失", f"{rel}: {val}")
                    dead += 1
    if not dead:
        ok("死链", "0（含 #锚点、src、zip 链接）")
    orphans = [r for r, n in inbound.items() if n == 0 and r != "index.html"]
    if orphans:
        bad("孤儿页", f"没有任何页面链到：{orphans}")
    else:
        ok("孤儿页", "0")

    # 首页：不放“四个单元一张图”表（表只在第 1 章 1.3 节），保留“从这里进”四张卡
    home_html = (DIST / "index.html").read_text(encoding="utf-8")
    home_cards = len(re.findall(r'<a class="card(?: card-dark)?" href="[^"]+">', home_html))
    if "四个单元一张图" in home_html:
        bad("首页", "不应再有“四个单元一张图”")
    elif "从这里进" not in home_html or home_cards != 4:
        bad("首页", f"“从这里进”卡片 {home_cards} 张，应含 4 张")
    else:
        ok("首页", "无 1.3 表，含从这里进四张卡")

    # 演示页只从第 2b 章（8 环演示）链接
    demo_in = [r for r, pg in parsed.items() if any(v.endswith("demo/index.html") for _, _, v in pg.links)]
    if demo_in == ["textbook/ch2b.html"]:
        ok("演示页入口", "只从第 2b 章 textbook/ch2b.html 链接")
    else:
        bad("演示页入口", f"链到演示页的页面：{demo_in}")

    # 3 实验切片命中
    for lab in report["labs"]:
        pg = parsed.get(lab["page"])
        if pg is None:
            bad("实验页", f"{lab['page']} 不存在")
            continue
        n = len(lab["slices"])
        if len(pg.slices) != n:
            bad("实验切片", f"{lab['page']} 页内 {len(pg.slices)} 段，配置 {n} 段")
        for s in lab["slices"]:
            if s["hits"] != 1:
                bad("实验切片命中", f"{lab['id']}「{s['label']}」命中 {s['hits']} 次")
            for h in s.get("code_hits", []):
                if h != 1:
                    bad("代码块命中", f"{lab['id']}「{s['label']}」子串命中 {h} 个")
        for sid, cnt in pg.origin_links.items():
            if cnt < 1:
                bad("出处回链", f"{lab['page']}#{sid} 没有出处链接")
        # 源文件哈希：报告值 = 当前 content/ 文件
        for rel, h in lab["sources"].items():
            if sha256(CONTENT / rel) != h:
                bad("切片源哈希", f"{lab['id']} {rel} 与构建时不一致（content/ 变了没重建？）")
    if not any(p.startswith("实验") for p in problems):
        ok("实验切片", f"{len(report['labs'])} 页 / {sum(len(l['slices']) for l in report['labs'])} 段，标题恰好命中一次，每段有出处回链")

    # 4 章节哈希
    stale = [c["rel"] for c in report["chapters"] if sha256(CONTENT / c["rel"]) != c["sha256"]]
    if stale:
        bad("章节哈希", f"content/ 与构建时不一致：{stale}")
    else:
        ok("章节哈希", f"{len(report['chapters'])} 章与构建时一致")

    # 5 演示页原样
    if sha256(DIST / "demo" / "index.html") == sha256(CONTENT / "demo" / "8环演示.html"):
        ok("演示页", "与教材仓库同步件字节一致")
    else:
        bad("演示页", "与源文件不一致")

    # 6 页面文本：残留标记
    for rel, pg in parsed.items():
        if rel == "demo/index.html":
            continue
        html = (DIST / rel).read_text(encoding="utf-8")
        text = re.sub(r"<pre[\s\S]*?</pre>|<code[\s\S]*?</code>|<[^>]+>", " ", html)
        if "**" in text:
            bad("残留 **", rel)
        if "<!--" in html:
            bad("残留注释", rel)
    ok("残留检查", "无 ** / HTML 注释") if not any(p.startswith(("残留")) for p in problems) else None

    # 6b mermaid 预渲染：dist 里不许残留 mermaid 代码块，每个图都要有内嵌 SVG（构建期已渲染好，页面不跑脚本）
    mm_info = report.get("mermaid") or {}
    mm_keys = set(mm_info.get("keys") or [])
    mm_figs = 0
    mm_bad = []
    for rel in htmls:
        if rel == "demo/index.html":
            continue
        html = (DIST / rel).read_text(encoding="utf-8")
        if '<span class="lang">mermaid</span>' in html:
            mm_bad.append(f"{rel} 残留 mermaid 代码块")
        for m in re.finditer(r'<figure class="mermaid-fig" data-mermaid="([0-9a-f]+)"[^>]*>([\s\S]*?)</figure>', html):
            key, inner = m.group(1), m.group(2)
            mm_figs += 1
            root = re.match(r"\s*<svg\b[^>]*>", inner)
            if not root:
                mm_bad.append(f"{rel}: {key} 的 figure 里没有 <svg>")
                continue
            tag = root.group(0)
            if 'viewBox="' not in tag:
                mm_bad.append(f"{rel}: {key} 的 <svg> 缺 viewBox")
            if re.search(r'\s(?:width|height)="', tag):
                mm_bad.append(f"{rel}: {key} 的 <svg> 还带固定宽高")
            if key not in mm_keys:
                mm_bad.append(f"{rel}: {key} 不在 .build/report.json 的图表清单里")
            if not (ROOT / "site" / "mermaid" / f"{key}.svg").exists():
                mm_bad.append(f"{rel}: {key} 缺少缓存文件 site/mermaid/{key}.svg")
    if not mm_bad and mm_figs == mm_info.get("figures", 0):
        ok("mermaid 预渲染", f"{mm_figs} 个图内嵌 SVG（viewBox、无固定宽高），0 个残留代码块；缓存 site/mermaid/*.svg")
    else:
        for msg in mm_bad or [f"图数 {mm_figs} ≠ report.json 的 {mm_info.get('figures')}"]:
            bad("mermaid 预渲染", msg)

    # 7 下载包
    dl = (DIST / "downloads.html").read_text(encoding="utf-8")
    forbid = re.compile(r"_sources\.md$|(^|/)_build/|(^|/)_scout/|(^|/)reviews/|(^|/)syllabus/|HANDOFF|(?<!kit/tools/demo/)BOARD|lab/fixtures/pilot/|__pycache__|\.pyc$")
    for p in report["packs"]:
        zp = DIST / "downloads" / p["file"]
        if not zp.exists():
            bad("下载包", f"缺 {p['file']}")
            continue
        if sha256(zp) != p["sha256"] or zp.stat().st_size != p["bytes"]:
            bad("下载包", f"{p['file']} 与报告不一致")
        if p["sha256"] not in dl or f"{p['bytes']:,}" not in dl:
            bad("下载页", f"{p['file']} 的 SHA-256 / 字节数没出现在页面上")
        with zipfile.ZipFile(zp) as z:
            if z.testzip() is not None:
                bad("zip", f"{p['file']} 损坏")
            for n in z.namelist():
                if not n.startswith("v2/"):
                    bad("zip 前缀", f"{p['file']}: {n}")
                if forbid.search(n) or (n.endswith(".db") and n != "v2/lab/fixtures/u3/bad_ops.db"):
                    bad("zip 禁入文件", f"{p['file']}: {n}")
    if not any(p.startswith("下载") or p.startswith("zip") for p in problems):
        ok("下载包", f"{len(report['packs'])} 个，zip 完好、带 v2/ 前缀、无禁入文件、页面列出字节数与 SHA-256")
    # 自学要用的四个文件：看板演示三件 + 课程版技能，必须在渔具包里
    must = ["v2/kit/tools/demo/board.json", "v2/kit/tools/demo/BOARD.md", "v2/kit/tools/demo/BOARD.html", "v2/kit/gstack-sprint/SKILL.md"]
    with zipfile.ZipFile(DIST / "downloads" / "v2-kit.zip") as kz:
        miss = [n for n in must if n not in kz.namelist()]
    if miss:
        bad("渔具包必备文件", f"v2-kit.zip 缺 {miss}")
    else:
        ok("渔具包必备文件", "含 tools/demo 三件与课程版 gstack-sprint/SKILL.md")
    if mode == "local":
        # 总包：9 个分包全部内容 + 课程库；库的 SHA-256 与 checksums.txt 一致
        m = report["materials"]
        ckt = (CONTENT / "kit" / "checksums.txt").read_text(encoding="utf-8")
        db_expect = re.search(r"^db_file_sha256\s*=\s*(\S+)", ckt, re.M).group(1)
        mz = DIST / "downloads" / m["file"]
        if not mz.exists():
            bad("总包", f"缺 {m['file']}")
        else:
            if sha256(mz) != m["sha256"] or mz.stat().st_size != m["bytes"]:
                bad("总包", "与构建报告不一致")
            if m["sha256"] not in dl or f"{m['bytes']:,}" not in dl:
                bad("总包", "下载页没有列出总包的 SHA-256 / 字节数")
            if f"downloads/{m['file']}" not in dl:
                bad("总包", "下载页没有总包链接")
            if dl.find("pack-all") > dl.find("id=\"packs\""):
                bad("总包", "“一次下载全部”应在分包表之上")
            with zipfile.ZipFile(mz) as z:
                names = z.namelist()
                if z.testzip() is not None:
                    bad("总包", "zip 损坏")
                expect = set()
                for p in report["packs"]:
                    with zipfile.ZipFile(DIST / "downloads" / p["file"]) as pz:
                        expect.update(pz.namelist())
                dbp = m["db_path"]
                missing = sorted(expect - set(names))
                extra = sorted(set(names) - expect - {dbp})
                if missing or extra:
                    bad("总包内容", f"缺 {missing[:3]} 多 {extra[:3]}")
                if dbp != "v2/kit/db/homestay.db" or dbp not in names:
                    bad("总包库路径", f"库应在 v2/kit/db/homestay.db，实际 {dbp}")
                else:
                    h = hashlib.sha256(z.read(dbp)).hexdigest()
                    if h != db_expect:
                        bad("总包库校验", f"库 SHA-256 {h} ≠ checksums.txt {db_expect}")
                for n in names:
                    if not n.startswith("v2/"):
                        bad("总包前缀", n)
                    if forbid.search(n) or (n.endswith(".db") and n not in ("v2/lab/fixtures/u3/bad_ops.db", dbp)):
                        bad("总包禁入文件", n)
            if not any(p.startswith("总包") for p in problems):
                ok("总包", f"{m['file']} {m['bytes']:,} 字节；含 9 个分包全部内容 + 库（v2/kit/db/homestay.db，SHA-256 = checksums.txt 的 db_file_sha256）；页面置顶")
    else:
        # 发布模式：dist 里没有总包；下载按钮指向 Release 附件，数值取自 release-manifest.json
        man = json.loads((ROOT / "release-manifest.json").read_text(encoding="utf-8"))
        tag = report["tag"]
        base = "https://github.com/cloudzun/ai-team-coding/releases/download/" + tag + "/"
        if not re.fullmatch(r"v\d+(\.\d+)*", tag):
            bad("发布 tag", tag)
        want_m = base + "ai-team-coding-materials.zip"
        want_o = base + "ai-team-coding-offline.zip"
        if report["release_urls"] != {"materials": want_m, "offline": want_o}:
            bad("发布链接", f"报告里的链接格式不对：{report['release_urls']}")
        for label, url in (("总包", want_m), ("离线包", want_o)):
            if f'href="{url}"' in dl:
                ok(f"下载按钮 {label}", url)
            else:
                bad(f"下载按钮 {label}", f"下载页没有 href={url}")
        hrefs = re.findall(r'href="(https?://[^"]*)"', dl)
        if sorted(set(hrefs)) != sorted({want_m, want_o}):
            bad("下载页外链", f"只允许两个 Release 链接，实际 {sorted(set(hrefs))}")
        for key in ("materials", "offline"):
            mm = man[key]
            if mm["sha256"] not in dl or f"{mm['bytes']:,}" not in dl:
                bad("manifest 数值", f"{key} 的字节数 / SHA-256 没出现在下载页")
        if man["tag"] != tag:
            bad("manifest tag", f"{man['tag']} ≠ {tag}")
        if (DIST / "downloads" / "ai-team-coding-materials.zip").exists():
            bad("发布模式", "dist 里不应有总包")
        if dl.find("pack-all") > dl.find('id="packs"') or dl.find("pack-all") < 0:
            bad("总包卡片", "“一次下载全部”应在分包表之上")
        if not any(q.startswith(("发布", "下载按钮", "下载页外链", "manifest", "总包")) for q in problems):
            ok("发布模式下载卡片", "总包与离线包指向 Release 附件，数值取自 release-manifest.json，卡片置顶")
    if "checksums.txt" in dl and "db_content_sha256" in dl:
        ok("课程库", "只显示校验和与核对命令")
    else:
        bad("课程库", "下载页缺 checksums 校验和")
    for n in (CONTENT / "kit").rglob("*.db"):
        bad("课程库入站", str(n))

    # 8 离线包（仅本地带库模式）
    if mode == "local":
        off = ROOT / "release" / "ai-team-coding-offline.zip"
        if off.exists():
            with zipfile.ZipFile(off) as z:
                names = set(z.namelist())
                if "start.cmd" in names and "index.html" in names and "demo/index.html" in names:
                    ok("离线包", f"{len(names)} 个文件，含 start.cmd")
                else:
                    bad("离线包", "缺 start.cmd / index.html / demo/index.html")
                mp = "downloads/" + m["file"]
                if mp in names and z.getinfo(mp).file_size == m["bytes"] and ("href=\"" + mp + "\"") in z.read("downloads.html").decode("utf-8"):
                    ok("离线包总包", "含总包，且 downloads.html 链到它")
                else:
                    bad("离线包总包", "离线包里缺总包，或下载页没链到它")
                if z.testzip() is not None:
                    bad("离线包", "zip 损坏")
        else:
            bad("离线包", "release/ai-team-coding-offline.zip 不存在")

    if mode == "local":
        mf = ROOT / "release-manifest.json"
        if not mf.exists():
            bad("release-manifest", "本地带库构建应生成 release-manifest.json")
        else:
            man = json.loads(mf.read_text(encoding="utf-8"))
            offz = ROOT / "release" / "ai-team-coding-offline.zip"
            if man["materials"]["sha256"] != report["materials"]["sha256"] or man["materials"]["bytes"] != report["materials"]["bytes"]:
                bad("release-manifest", "总包数值与本次构建不一致")
            elif not offz.exists() or man["offline"]["sha256"] != sha256(offz) or man["offline"]["bytes"] != offz.stat().st_size:
                bad("release-manifest", "离线包数值与 release/ 里的文件不一致")
            else:
                ok("release-manifest", f"tag={man['tag']}，总包/离线包字节数与 SHA-256 与本次构建一致")
    print("== qa_pages.py local ==")
    for good, name, detail in checks:
        print(("  PASS " if good else "  FAIL ") + name + (f"  {detail}" if detail else ""))
    print(f"异常数：{len(problems)}")
    for p in problems:
        print("  ! " + p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
