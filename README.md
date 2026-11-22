# 带 AI 团队写代码：从任务书到交付 —— 课件站

纯静态课件站：教材（第 1–8 章 + 8 环演示）、演示页、实验手册（单元一至四）、材料下载。共 16 页。
将来的网址：`cloudzun.github.io/ai-team-coding`（站内链接全部相对路径，放根目录、子路径或本地直接打开都行）。

## 目录

| 路径 | 说明 |
|---|---|
| `content/` | 从教材仓库 `v2/` 同步来的白名单镜像，**进库、不手改** |
| `SYNC.json` | 每个同步文件的 SHA-256、字节数、源仓库提交号 |
| `labs/labs.yml` | 实验页配置：只写路由文字，事实按标题从章节切片 |
| `site/` | 样式与脚本（`site.css`、`site.js`） |
| `scripts/` | `sync-content.ps1`、`whitelist.txt`、`blacklist.txt`、`build.mjs`、`qa_pages.py`、`scan_sensitive.py`、`serve-dist.cjs`、`start.cmd` |
| `dist/` | 构建产物（不入库） |
| `release/` | 离线包 `ai-team-coding-offline.zip`（不入库） |

## 首次准备

```powershell
npm install
```

## 发布流程（五步，不跳步、不合并）

```powershell
# 1 只改源：教材仓库 v2/ 内的章节与模板，或本仓 labs/labs.yml、site/、scripts/；不手改 content/、dist/
# 2 同步并构建，末尾自检必须绿（残留 ** / 白名单外文件 / 切片命中 / 页数）
powershell -File scripts/sync-content.ps1 -Source ..\l1-textbook\v2   # 教材仓库与本仓并列时的相对路径；否则写实际路径
npm run build -- --db-source <课程库文件路径>   # 路径由维护者指定；也可用环境变量 HOMESTAY_DB
# 3 静态门禁
python scripts/qa_pages.py local         # 全部页 0 异常
python scripts/scan_sensitive.py         # 0 命中
# 4 本地预览 + 用真浏览器逐页截图：桌面 1440 与 390×844；表格、代码块、清单成形；控制台无 404；实验页每段回链可跳
node scripts/serve-dist.cjs 4380         # 起前先查端口：Get-NetTCPConnection -LocalPort 4380 -State Listen；被占换 4381–4389；用完停掉
# 5 截图与结论交用户 —— 用户确认无误后，才 git add / commit / push
```

**push、建远程仓库、开启 GitHub Pages、绑定域名，都属外部动作，需用户明确授权后才做。**构建与预览都只在本机。

## 课程库 homestay.db

- 库不进 git（`.gitignore` 忽略 `*.db`，只放行 `content/lab/fixtures/u3/bad_ops.db`），也不进 `content/`。
- 构建时由维护者用 `--db-source` 或环境变量 `HOMESTAY_DB` 指定库文件路径（由维护者指定库文件路径，仓库里不写死）。
- 打包前先核对库文件的 SHA-256 与字节数，必须等于 `content/kit/checksums.txt` 的 `db_file_sha256` / `db_bytes`，不等则构建失败；不给路径也失败。
- 库只出现在两处：总包 `dist/downloads/ai-team-coding-materials.zip`（解开后在 `v2/kit/db/homestay.db`）和离线包 `release/ai-team-coding-offline.zip`（内含总包）。`dist/`、`release/` 都不入库。

## 规则要点

- 同步脚本只读教材仓库，只写本仓 `content/` 与 `SYNC.json`；先黑名单后白名单，白名单每一行都必须命中文件，否则失败。
- 黑名单（优先）：`*_sources.md`、`_build/`、`_scout/`、`reviews/`、`syllabus/`、`HANDOFF*`、`BOARD*`、`lab/fixtures/pilot/`、`kit/gstack-sprint/`、`kit/tools/demo/`、`make_*.py`、`*.db`（仅放行 `lab/fixtures/u3/bad_ops.db`）、`__pycache__`、`*.pyc`。
- 构建时再查一遍：`content/` 里凡不在白名单、或命中黑名单的文件，构建失败。
- 实验页没有自己的正文：每段是章节标题的切片，标题必须恰好命中一次，否则构建失败；每段末尾回链出处。
- `demo/index.html` 是教材仓库 `demo/8环演示.html` 的字节级拷贝，只从教材第 2b 章“8 环演示”页链接。
- 下载页顶部是“一次下载全部”总包（9 个分包合并 + 课程库），下面是 9 个分包；课程库一节显示 `checksums.txt` 的校验和与核对命令。
- 离线包：`release/ai-team-coding-offline.zip` = `dist/` + `start.cmd`；解压后双击 `start.cmd`（`python -m http.server 4380 --directory .`），浏览器打开 `http://127.0.0.1:4380/`。
