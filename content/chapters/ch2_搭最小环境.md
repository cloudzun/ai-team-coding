<!-- Chapter: 2  Author: AI 写稿  Version: V2.5  Updated: 2026-11-22 -->

# 第 2 章 搭最小环境与环境自检

## 本章目标

本章 1 学时。做完本章，你手里有一套“渔具包”，而且有记录证明它能用。后面四个单元，你都靠这套渔具做事。具体地，你能：

1. 列出渔具包的十项，说出每一项在课程里干什么；讲清 gstack、技能、gstack-sprint、看板各是什么、不是什么。
2. 运行环境自检脚本，读懂每一行是绿还是红，处理红项，拿到自动项全绿、退出码为 0 的整段输出。
3. 完成 gstack 自检（三步）、同名冲突自检、看板生成器演示各一次，每项留下记录。
4. 说出“内容校验和”和“文件指纹”各回答什么问题；用只读方式打开课程数据库，记下各表行数。
5. 把大模型接口的访问地址与密钥放进被版本控制忽略的本地配置文件，并验证确实被忽略。
6. 把本章自检记录里的事实写成任务书栏 8（端口与环境事实），并做一次端口占用检查。

验收标准（组内三人共同交出）：

- 环境自检整段输出，末行为“自动项全部通过，可以开始”；浏览器、DSH 会话、大模型接口三项人工勾选全部勾上。
- gstack 自检：`gstack_status.txt` 退出码为 0 且 `claude` 一行结果列为 `current`；`gstack_doctor.txt` 末行含 `0 fail`；DSH 会话里九个技能名都在，并加载一个技能读出标题。
- 同名冲突自检：`same_name.txt` 末行“同名技能共 1 份”，且描述以“课程副本”开头。看板演示：`records/board-demo/` 里有 `BOARD.html` 与 `BOARD.md`，生成命令退出码为 0。
- 各表行数记录一份，与自检输出一致；数据库文件指纹对比末行为“不变”。
- 栏 8 一份（`records/column8.md`），每条事实都能指出对应的自检记录；端口占用检查记录一份（`records/port_check.txt`）。
- 问题清单一份：没解决的项写明现象与卡在哪一步；全绿时写“无”。

## 讲解

### 2.1 渔具包清单

课程教的是“渔”，渔具就是 gstack 和围着它配齐的东西，合称渔具包，单元一到单元四共用。gstack 与课程版 gstack-sprint 技能由讲师预装，你只做自检，不自己装；其余随课堂分发或用你自己的机器。

| 项 | 它在课程里干什么 | 怎么确认 |
|---|---|---|
| 1 DSH（宿主） | 全课统一的工作台：你和 gstack 的对话、技能加载、子任务派发都在 DSH 会话里发生 | 开一个会话，看到会话界面 |
| 2 gstack（讲师预装） | 一套现成的工作方法：想清需求、写规格、评审、验收都有对应技能，你的任务书由它们加工 | gstack 自检三步 |
| 3 课程版 gstack-sprint 技能（讲师预装） | 把一次交付拆成 8 环的流程表，第 4 章起每个单元都按它走 | DSH 里加载它，读出标题 |
| 4 看板生成器 | 把记录进度的 `board.json` 变成 `BOARD.html` 与 `BOARD.md`；需要 Node.js | 跑演示，退出码 0 |
| 5 课程数据包 | 数据库、指标口径表、运营手册、表结构说明、导出契约：所有“对不对”都对着它们判 | 自检脚本逐项核对 |
| 6 学员工具箱 | 检查脚本（环境自检、库指纹、图表检查）与样例页：你自己验收 gstack 的产出时用 | 自检脚本；浏览器打开样例页 |
| 7 Git（含 Git Bash） | 版本控制；凭据纪律靠它的忽略规则；gstack 自检要在 Git Bash 里运行 | `git --version` 有输出 |
| 8 Python 3.12 | 只用标准库，跑检查脚本与只读查询；产品代码不由你写 | `python --version` 显示 3.12 或更高 |
| 9 浏览器（Chrome 或 Edge） | 控制台能执行脚本，用来导出页面数据 | 打开样例页，控制台执行 `1+1` 得到 2 |
| 10 大模型接口 | 单元二起产品要调用，需要兼容 OpenAI 接口的访问地址与密钥；本章只验证连通 | 用客户端或 SDK 发一次问答 |

第 5、6 项里，后面各单元还会用到下面几样，到时再讲用法：

- 《交付约定_单元二》《交付约定_单元三》《交付约定_单元四》（`v2/kit/`）
- 单元二、三、四的检查命令：`u2_check.py`、`u3_check.py`、`u4_check.py`（`v2/lab/tools/`）
- 各单元的坏夹具（`v2/lab/fixtures/`）
- 阶段一至阶段四存档点（`v2/checkpoints/stage1` 至 `stage4`）
- 模板与卡片（`v2/lab/templates/`）

宿主（Harness）是承载对话与工具的软件，本课统一用 DSH。你在课程里的位置是“用户”：写任务书、对 lead 列出的选项回字母、发现跑偏时纠偏、在两道闸门拍板；具体代码由 gstack 流程里的 agent 去写。三个角色分工保留：业务核对数据，分析只读记账，技术确认渔具包可用。

### 2.2 四个新概念

**gstack**
- 类比：一间配齐工具的木工房。锯、刨、尺都在架子上，你只要知道哪件活用哪件工具。
- 定义：gstack 是一套装在宿主里的技能，每个技能是一种工作方法，覆盖想清需求、规格与计划评审、测试验收、发布等环节。
- 边界：它不是会自己写代码的 agent，套件里没有“写业务代码”的技能；它也不是 DSH 自带的，DSH 是把它装出来的技能目录当作技能来源读进来。
- 在 DSH / gstack 里叫什么：**gstack**；课程所用版本含 56 个技能，会话里按短名称加载，例如 `office-hours`、`spec`、`qa-only`。

**技能**
- 类比：一张写好的工序卡。先做什么、再做什么、做完交什么，写在纸上，谁拿到都能照办。
- 定义：技能是一份带名字和适用场景描述的 Markdown 说明文件，宿主按名字加载它，agent 照里面的步骤做事。
- 边界：它不是程序，不会自己运行；加载了技能不等于做完了事，照它做出来的东西仍要你验。
- 在 DSH / gstack 里叫什么：**技能（skill）**，文件名 `SKILL.md`；DSH 用 `skill` 工具按名字加载。

**gstack-sprint**
- 类比：装修队的施工流程表。先量房、出图、审图、施工、验收、交钥匙，每步有人负责，关键几步要业主签字。
- 定义：课程版 gstack-sprint 是一个技能，规定一次版本交付走 8 环（环 0 到环 7）：lead 编排并判每环的门禁，子 agent 执行各环，你在 G1、G2 两道闸门拍板。
- 边界：它不是自动驾驶，你要写任务书、回字母、纠偏、过闸门；它也不在 gstack 的 56 个技能里，是课程发放的副本，放在另一个技能目录。lead 是你在 DSH 主会话里对话的 agent，子 agent 是 lead 派出去干具体活的 agent；8 环各是什么，第 1 章已讲。
- 在 DSH / gstack 里叫什么：**gstack-sprint**（课程版）。

**看板**
- 类比：工地门口的进度牌。路过的人不用问，抬头就知道做到哪一步、哪件事在等业主。
- 定义：看板是一份 `board.json`，记录当前环、各环状态和等你拍板的事；生成器把它渲染成给人看的 `BOARD.html` 和给 agent 查的 `BOARD.md`。
- 边界：它不是项目管理软件，也不是 agent 的口头汇报；要改看板，改的是 `board.json`，两份生成物会被下一次生成覆盖。
- 在 DSH / gstack 里叫什么：**board.json、BOARD.html、BOARD.md**；生成器是渔具包里的 `gen-board.mjs`。

### 2.3 数据与纪律

后面的判据都要“按口径表自己算期望值，再和系统输出比”。每台机器上的数据不是同一份，同一道题就没有同一个正确数字，所以先让全班数据一致，并能证明。下面四个概念先用表格走完四步，细节在实操里用到时再看。

| 概念 | 类比 | 定义 | 边界 | 在课程里叫什么 |
|---|---|---|---|---|
| 确定性数据 | 全班考同一套试卷，分数才能互相比较 | 用固定种子、不调用模型生成的数据，同一版本在哪里得到的内容都一样 | 不等于真实，课程库全部是模拟数据；也不等于很干净，保留了真实经营数据常有的不整齐 | 课程数据库，一个 SQLite 文件，放进数据包的 `db/`；DSH 与 gstack 没有对应说法，通用叫法是“固定版本的模拟数据集” |
| 内容校验和与文件指纹 | 核对一本书：内容校验和逐字核对正文，不管印刷装订；文件指纹是样书的封条，一丝不能变 | 内容校验和是所有表按表名排序、每张表按主键排序、逐行写成文本后算出的 SHA-256，与字节布局无关；文件指纹是整个库文件逐字节算出的 SHA-256，另附字节数 | 指纹不变只说明文件没被动过，不说明数据对不对；内容校验和一致说明数据相同，不要求文件字节相同 | `checksums.txt` 里的 `db_content_sha256` 与 `db_file_sha256`；通用叫法是“数据校验和”和“文件哈希” |
| 只读打开 | 善本阅览室，可以看可以抄，不能在书上写字 | 以只读方式连上数据库，经这条连接发出的写语句会被数据库本身拒绝 | 只管这一条连接打开的那个库，不保证别的程序不改文件，所以还要看指纹前后不变 | SQLite 连接串里的 `mode=ro`；通用叫法是“只读连接” |
| 凭据纪律 | 家门钥匙不挂在门把手上，更不拍照发群里 | 把接口的访问地址与密钥只放在被版本控制忽略的本地配置文件里 | 密钥不进对话、提交、截图和你交的任何记录；提交过一次就可能已泄露，事后删除不能挽回 | 本地配置文件（常见做法是 `.env`）加 `.gitignore` 忽略规则；通用叫法是“凭据与代码分离” |

问“是不是同一份数据”，看内容校验和；问“这份文件有没有被改”，用文件指纹做前后对比。纪律：全课查数一律只读打开；不在 `db/` 里建表、改数据，不修改 `checksums.txt` 与数据包里的资料文件。

### 2.4 自检一览

本章四类自检，各留一份记录：环境自检、gstack 自检（安装状态、体检、DSH 里加载技能三步）、同名冲突自检（名字以 gstack-sprint 开头的技能只有 1 份且是课程版）、看板生成器演示。环境自检脚本逐项打印 `[绿]`、`[红]`，个别项给 `[黄]`；全部通过时退出码为 0，有红项为 1，黄色不计入。九项自动判定：Python 版本、数据包登记、库文件、内容校验和、只读读表、只读写入被拒且指纹未变、两份资料、Git、DSH 安装。人工勾选三项：浏览器、大模型接口，以及脚本里写作 coding agent 的那一项，在本课对应你的 DSH 会话。可选参数 `--db` 指定库文件（默认 `v2/kit/db/homestay.db`），`--kit` 指定数据包目录（默认 `v2/kit`）。

## 实操

命令都在“含 `v2` 文件夹的那一层目录”（步骤 1 的空目录）里运行，以 Windows PowerShell 为主；gstack 自检的命令在 Git Bash 里运行，也在这一层目录。三个角色：业务核对校验和并读资料，分析只读记行数并跑看板演示，技术确认渔具包可用。

### 步骤 1 起点

起点：每组一个空目录、一台能联网的机器、课程数据包。顺序不能换：先建目录，再 `git init`，然后才写忽略规则、验证。记录一律放进 `records`，不放进 `v2/kit/db/`。
```powershell
# 建目录（Git Bash：mkdir -p v2/kit/db v2/lab records）
New-Item -ItemType Directory -Force v2\kit\db, v2\lab, records
# 先把数据包放进 v2\kit、工具箱与样例页放进 v2\lab（拖放也行），再拷库文件；尖括号换成文件所在位置（Git Bash：cp）
Copy-Item "<课堂分发的库文件路径>" v2\kit\db\homestay.db
git init
Add-Content .gitignore ".env"
git check-ignore -v .env   # 有输出说明已被忽略（.env 还没建也能验）
Get-ChildItem v2\kit\db   # 确认库文件就位（Git Bash：ls -l v2/kit/db/）
```
- 产物：目录就绪；`.gitignore` 里有 `.env` 一行；三人各认领一个角色。
- 验收：能看到 `homestay.db`，字节数与 `v2/kit/checksums.txt` 里的 `db_bytes` 相同；`git check-ignore -v .env` 有输出；`v2/kit/tools/gen-board.mjs` 在位。

### 步骤 2 记下起点指纹，跑第一次环境自检
```powershell
# 本章开始时的文件指纹，存起来留到步骤 6 对比；第一次自检屏幕显示并存档（Git Bash：加 | tee records/env_check_1.txt）
python v2/lab/tools/db_fingerprint.py v2/kit/db/homestay.db > records/fp_before.txt
python v2/lab/tools/env_check.py | Tee-Object records/env_check_1.txt
```
- 产物：`records/fp_before.txt`、`records/env_check_1.txt`。
- 验收：技术角色敲命令，业务、分析角色一起读输出，全组说得出有几项红、各在哪一行（红项下缩进的一行是改法，汇总行在三项人工勾选之前，全绿时为 `自动项：绿 9 / 黄 0 / 红 0`；末行全绿时为 `结论：自动项全部通过，可以开始。`）；`fp_before.txt` 的 `sha256` 与 `checksums.txt` 的 `db_file_sha256` 逐位相同，或已记下不同。

### 步骤 3 三个角色并行

**业务角色：核对校验和，读数据包资料**
```powershell
# 算库文件 SHA-256 并转小写，与 checksums.txt 的 db_file_sha256 对照（Git Bash：sha256sum v2/kit/db/homestay.db）
(Get-FileHash v2\kit\db\homestay.db -Algorithm SHA256).Hash.ToLower()
```
再对照 `records/env_check_1.txt` 里“数据内容校验和”一行，与 `db_content_sha256` 比前 8 位和后 8 位。然后读 `v2/kit/student-pack/` 下的指标口径表与运营手册各一遍，各写一句话：它按哪几类编号组织。再读 `v2/kit/导出契约.md`，写一句话：比例类数值的 `value` 用什么形式。`v2/kit/表结构说明.md` 列出每张表的字段名、类型和含义，以后写查询前先看它。
- 产物：`records/business_notes.md`（校验和核对结论加三句话）。
- 验收：文件级 SHA-256 与登记值一致或已记下不同；内容校验和前后 8 位一致；前两句话与 `v2/kit/README.md` 第 1 节对两份资料的描述相符；第三句话与 `导出契约.md` 第 3 节相符。

**分析角色：只读打开，记各表行数**
把下面的小脚本存成 `records/read_tables.py`，运行 `python records/read_tables.py`，输出存成 `records/table_counts.txt`（PowerShell 在后面加 `| Tee-Object records/table_counts.txt`，Git Bash 加 `| tee records/table_counts.txt`）。
```python
import sqlite3
# mode=ro：只读打开，任何写语句都会被数据库本身拒绝
con = sqlite3.connect("file:v2/kit/db/homestay.db?mode=ro", uri=True)
names = [r[0] for r in con.execute(
    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
for t in names:
    print(t, con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0])
con.close()
```
- 产物：`records/table_counts.txt`，每张表一行。
- 验收：九张业务表（`meta`、`districts`、`owners`、`listings`、`price_history`、`owner_blocks`、`bookings`、`reviews`、`market_benchmark`）的行数与自检输出里的“业务表行数”逐表一致；另有 `price_change_requests`、`maintenance_tickets`、`audit_log` 三张表且行数为 0，属于单元三预留，记下即可。

**技术角色：gstack 自检前两步，加 DSH 的技能来源**
前两步在 Git Bash 里运行，都是只读命令，不会改动 gstack。先在开始菜单打开 **Git Bash**，用 `cd` 进到含 `v2` 文件夹的那一层目录，再运行下面的命令，不要粘贴到 PowerShell 窗口里，否则 `~`、`${PIPESTATUS[0]}` 会直接报语法错误。
```bash
# 第 1 步：安装状态。claude 一行的结果列应为 current；Install checks 里 section links 应写 all resolve
~/.claude/skills/gstack/setup --status | tee records/gstack_status.txt
echo "退出码 ${PIPESTATUS[0]}"   # 0 才对；技能说明里的链接断了会退出 1
# 第 2 步：体检。末行形如“N ok, N warn, N not configured, 0 fail”，只看 0 fail
~/.claude/skills/gstack/bin/gstack-doctor | tee records/gstack_doctor.txt
echo "退出码 ${PIPESTATUS[0]}"
cat ~/.claude/skills/gstack/VERSION   # 版本号，记进记录
```
`setup --status` 会列出好几个宿主的行，课程只看 `claude` 这一行，因为 DSH 读的是它所在的技能目录。体检里 `warn` 和 `not configured` 不是失败：`codex` 一行显示 not configured，只影响环 3 里“外部意见（Outside Voice）”那一步，第 1 章的 8 环表里已列。再在 PowerShell 里看 DSH 的技能管理器有没有把这个目录读进来，第三步放到步骤 4：
```powershell
# 只读：claude 源对应 gstack 的技能目录，agents 源对应课程版 gstack-sprint 所在的目录；两个应都是 True
(Get-Content "$HOME/.dsh/skills-manager/state.json" -Raw | ConvertFrom-Json).sources | Select-Object claude, agents
```
- 产物：`records/gstack_status.txt`、`records/gstack_doctor.txt`；版本号与两个源的状态写进 `records/tech_notes.md`。
- 验收：两条命令退出码都是 0；`claude` 一行结果列为 `current`；体检末行含 `0 fail`；两个源为 True。

### 步骤 4 DSH 里确认技能、同名冲突自检、看板演示

**技术角色：gstack 自检第三步，在 DSH 会话里**
在含 `v2` 的那一层目录里开一个 DSH 会话，依次发下面四句话，每句看到结果再发下一句。前三句只加载、只读，不运行任何技能里的命令。

1. 列出你现在能加载的技能里这九个名字是否都在：`gstack`、`office-hours`、`spec`、`plan-ceo-review`、`plan-eng-review`、`plan-design-review`、`plan-devex-review`、`qa-only`、`gstack-sprint`。只列名字，不运行任何技能。
2. 用 `skill` 工具加载 `landing-report`，只回复它正文的标题和第一节的标题，不要运行里面的命令。
3. 用 `skill` 工具加载 `gstack-sprint`，只回复它描述的第一句话和第 1.5 节的标题，不要开始任何流程。
4. 在当前工作目录（含 `v2` 的那一层）新建 `records/dsh_probe.txt`，写一行字，再运行 `python --version`，把输出读给我。

判据：第 1 句，九个名字都在；第 2 句，回复含标题 `/landing-report — Version Queue Dashboard`，没有“技能不存在”之类的报错；第 3 句，描述第一句以“课程副本（L1 课程版）”开头，第 1.5 节标题是“L1 课程版（本课默认形态）”；第 4 句，文件被写出并读到 Python 版本。四句合起来就是“DSH 读到了 gstack”的最小证据，也顺带勾掉环境自检里的 DSH 会话那一项。

**业务角色：同名冲突自检**
DSH 按技能说明开头的 `name` 行识别技能。机器上若有两份都叫 gstack-sprint 的技能，会话里加载到哪一份没有保证，所以只能留一份，而且要是课程版。下面的命令只读，列出各技能目录里名字以 gstack-sprint 开头的全部技能。
```powershell
$dirs = ".agents", ".claude", ".codex", ".dsh", ".config\opencode" | ForEach-Object { Join-Path $HOME "$_\skills" }
$hits = foreach ($f in Get-ChildItem $dirs -Filter SKILL.md -Recurse -Depth 1 -ErrorAction SilentlyContinue) {
  $n = Select-String $f.FullName -Pattern '^name:\s*(gstack-sprint\S*)' | Select-Object -First 1
  if (-not $n) { continue }
  $d = Select-String $f.FullName -Pattern '^description:\s*(.{0,14})' | Select-Object -First 1
  [pscustomobject]@{ Name = $n.Matches[0].Groups[1].Value; Where = $f.FullName; Desc = $d.Matches[0].Groups[1].Value }
}
$hits | Format-List | Out-String | Tee-Object records/same_name.txt
"同名技能共 $(@($hits).Count) 份" | Tee-Object -Append records/same_name.txt
```
输出文件用编辑器或 PowerShell 查看即可（在 Windows PowerShell 5.1 下是 UTF-16 编码，末尾有空行，不影响判断）。判据：共 1 份，`Name` 是 `gstack-sprint`，`Desc` 是“课程副本（L1 课程版）。用”；旧版技能的 `Desc` 不是这个开头。共 0 份，说明课程版没装到位。共 2 份以上，多出来的是旧同名技能，或是别人改了名字的副本；讲师机和你自己的机器上都可能有早先装的旧 gstack-sprint，处理办法相同：把旧的整个目录移出技能目录，不删除。
```powershell
# 目录名与位置按上面 Where 一行填写
New-Item -ItemType Directory -Force "$HOME\skill-backup" | Out-Null
Move-Item "$HOME\.agents\skills\<旧技能目录名>" "$HOME\skill-backup\"
```
移走后重跑检查，直到只剩 1 份课程版；若连课程版也被一起移走或覆盖，向讲师要课程版重新放入，不要自己改写技能文件。处理完新开一个 DSH 会话，重做技术角色的第 3 句。

**分析角色：看板生成器演示运行一次**
```powershell
# 用渔具包里的演示数据生成两份看板，输出到 records\board-demo，不动渔具包里的原文件
New-Item -ItemType Directory -Force records\board-demo
node v2/kit/tools/gen-board.mjs v2/kit/tools/demo/board.json records/board-demo
Get-ChildItem records\board-demo
Select-String -Path records\board-demo\BOARD.md -Pattern '环进度'   # BOARD.md 里应有“环进度”一节
```
用浏览器打开 `records/board-demo/BOARD.html` 看一眼：这是一张按环列出进度的页面。命令报 `node` 不是可识别的命令时，说明没装 Node.js，装好后新开终端再试。
- 产物：`records/dsh_probe.txt`、`records/same_name.txt`、`records/board-demo/`。
- 验收：DSH 四句话的判据都满足；`same_name.txt` 末行“同名技能共 1 份”；生成命令退出码为 0，`records/board-demo/` 里有 `BOARD.html` 与 `BOARD.md`，`BOARD.md` 里搜得到“环进度”。

### 步骤 5 处理红项，补齐人工项，配置凭据

技术角色对照下一节处理步骤 2 到 4 的红项；业务、分析角色把没解决的红项逐条写进 `records/issues.md`（现象、卡在哪一步），协助读错误信息。技术角色再做三件事：打开 `v2/lab/sample/index.html`（样例页，单元一会用到），按 F12，在控制台执行 `1+1` 得到 2；配置并验证凭据；用你的客户端或 SDK 完成一次问答请求，看到回复文本。
```powershell
# 尖括号里换成你自己的访问地址、模型名与密钥；变量名与存档点一致，不要改名
# 本地接口不验密钥时，LLM_API_KEY 那行可以留空；最后一行没有输出就回去检查 .gitignore
Set-Content .env "LLM_BASE_URL=<兼容 OpenAI 接口的访问地址>"
Add-Content .env "LLM_MODEL=<模型名，按接口文档给的标识写>"
Add-Content .env "LLM_API_KEY=<你的密钥>"
git check-ignore -v .env
```
如果报“不是 Git 仓库”，说明命令没有在步骤 1 运行 `git init` 的那一层目录里运行，回到含 `v2` 的那一层再试。密钥不要出现在截图、聊天窗口、DSH 会话和任何记录里。
- 产物：`records/issues.md`（没有问题写“无”）；`.env` 本身不交。
- 验收：红项已处理或已写入问题清单；控制台得到 2；`git check-ignore -v .env` 有输出；问答请求已完成或已记入问题清单。

### 步骤 6 复检、指纹对比、交记录
```powershell
# 复检：自动项应全绿，退出码为 0；指纹对比带上步骤 2 的输出，末行给“不变”或“已变”
python v2/lab/tools/env_check.py | Tee-Object records/env_check_final.txt
python v2/lab/tools/db_fingerprint.py v2/kit/db/homestay.db records/fp_before.txt | Tee-Object records/fp_compare.txt
```
- 产物：`records` 目录里除起点的 `fp_before.txt` 外，还有 `env_check_final.txt`、`gstack_status.txt`、`gstack_doctor.txt`、`same_name.txt`、`board-demo/`、`table_counts.txt`、`fp_compare.txt`、`issues.md`、`business_notes.md`、`tech_notes.md`、`dsh_probe.txt`。
- 验收：自检末行为“自动项全部通过，可以开始”；指纹对比末行为 `result: 不变`；章首验收标准逐条勾上。

## 常见红灯与处理

| 红项（现象） | 原因与处理 |
|---|---|
| `Python 版本 … 低于 3.12` | 终端里的 `python` 指向旧版本：装 3.12 或更新版本，用它重新运行 |
| `数据包目录不存在`、`缺 checksums.txt`、`里面没有 db_content_sha256` | 不在含 `v2` 的那一层运行，或数据包不完整：换到那一层，或用 `--kit` 指向数据包目录；不完整就重新拿一份，不要自己补写登记表 |
| `库文件不存在`，并带出后三项“未执行” | `homestay.db` 没放进 `db/`：放到 `v2/kit/db/homestay.db` 或用 `--db` 指向它；后三项是连带红 |
| `读不了库文件`、`打不开数据库`、`数据内容校验和不符`、`缺表`、`两份资料不齐或已改动`、`只读方式下写入竟然成功`、`文件被改动了` | 文件被占用、拷贝被截断，拷错版本，或被写过、改过：关掉占用它的程序，重拿课堂分发的文件；练习写入用副本，不在 `db/` 里做 |
| `git 不在 PATH 上` 或 `git 命令跑不起来`；生成看板时 `node` 不是可识别的命令 | 没装 Git 或 Node.js，或终端没刷新：装好后新开终端运行 `git --version`、`node --version` |
| `[黄] 没找到 DSH，请人工确认` | 不是红项；确认 DSH 能启动、能开会话，装在别处就在问题清单里写明位置 |
| `setup --status` 退出码为 1，或 `section links` 不是 all resolve；`gstack-doctor` 末行 `fail` 不是 0 | gstack 本身有问题，不要自己重装：整段输出贴进 `issues.md`，请讲师处理 |
| 找不到 `~/.claude/skills/gstack`，或 DSH 里 `gstack`、`gstack-sprint` 不在技能列表 | 没装到这台机器，或技能管理器的源被关：看步骤 3 的两个源，仍不对就换用已通过自检的机器，并记入 `issues.md` |

文件级 SHA-256 与登记值不同而内容校验和一致，不是红项：数据相同、文件字节不同，脚本会在“数据内容校验和一致”下面注明。判断不了的红项，把脚本整段输出（含末行结论）贴出来，比描述“打不开数据库”更有用。

## 降级路径

本章没通过的项记入问题清单，用下面的办法继续，不阻塞后面的单元。
- 库文件不通过校验：重新拷一份课堂备好的现成数据库文件放进 `v2/kit/db/`，再跑自检，核对内容校验和。
- 大模型接口不通：先做单元一，单元二开始前补齐；问题清单写明现象和已试过的办法。
- 某台机器的 gstack 自检不通过、DSH 里看不到技能，或整体起不来：先用组里已通过的一台，两人合用，第三人负责记录，第 4 章开工前补齐。

## 栏 8 端口与环境事实怎么写

任务书第 8 栏告诉 lead 两件事：这台机器上有什么，服务该用哪个端口。lead 只看得到你写的这一页，不知道你的命令行是什么、有没有 Node.js、8801 是不是已经被占着。这一栏不随单元变；本章做完自检，手里正好有它要的事实，所以放在这里讲，之后各章照抄。第 1 章的 9 栏表里它排第 8 栏。

**范例**（第 4 章成品任务书栏 8 原文；“数据看板”是单元一的产物，后面各章换成该单元的产物名，其余照抄）

> - 系统是 Windows，命令行用 PowerShell；有 Python 和 Node.js。
> - 我们要做的数据看板，服务默认用 8801；起之前先查端口，被占用就换一个空闲端口并告诉我。同一时刻只留一个服务实例，用完关掉并复查端口已释放。

**为什么这样写**

1. 第一条的每个词都能在本章自检记录里找到。“有 Python”对着环境自检输出里的 Python 版本一行；“有 Node.js”对着步骤 4 看板演示能跑通；“PowerShell”是本章命令的运行环境。gstack 自检虽然在 Git Bash 里跑，它检查的是渔具包，不是让 lead 生成产品命令用的命令行，所以栏里不写。不写这一条，lead 只能猜你的机器。
2. 8801 是课程里服务的默认端口，但此刻空不空要查，所以写成“起之前先查端口”，对应下面的端口占用检查。“被占用就换一个空闲端口并告诉我”里的“告诉我”不能省：换了端口，浏览器地址和后面的抽验命令都要跟着换，你得知道换成了几号。
3. “同一时刻只留一个服务实例，用完关掉并复查”和本章另外两条自检是同一个道理。同名冲突自检说的是：两份同名技能同时在，会话里加载到哪一份没有保证；两个服务同时占着端口，谁在响应也说不清。库指纹的做法是前后各取一次再对比，不靠“应该没动过”；端口也一样，用完再查一遍，数到 0 才算释放。

**错误示范**

- “环境是正常的开发机，端口随便。” 没有系统，没有命令行，没有端口号：lead 只能自己猜；“随便”还让它可能选任何端口，你抽验时不知道该打开哪个地址。
- “服务用 8801，已确认空闲。” 把一次检查的结果当成永远成立的事实：本章的端口占用检查只证明检查那一刻没有进程在监听，换一天、换一台机器、别的程序先起来，它就不成立。栏里要写的是“起之前先查，被占用就换”。

**自查**

- 系统、命令行、有哪些运行环境，三样各有一句，每一句你都能指出它对应本章哪份自检记录。
- 默认端口、起之前先查、被占用就换并告诉你、同一时刻一个实例、用完关掉并复查释放，这五件事都在。
- 没有“已确认空闲”这类某一刻的检查结果，也没有访问地址和密钥。
- 往后栏 8 还会加条目：第 5 章起多一条模型接口的变量名（`LLM_BASE_URL`、`LLM_MODEL`、`LLM_API_KEY`），值只放本地配置文件，不进对话、不进任务书、不进提交；第 7 章再加 DSH 启动令牌，它同属凭据，不写值，不进截图，也不交给任何子 agent。

**写你自己的。** 步骤 6 复检之后，由技术角色主笔，业务、分析角色按自查三条读一遍。

1. 跑一次端口占用检查，输出存档，留在 `records` 里：

```powershell
# 连接数大于 0，说明 8801 被占用：换一个空闲端口，把 8801 改成换后的号再跑一次，并记下换成了几号
$r = Get-NetTCPConnection -LocalPort 8801 -State Listen -ErrorAction SilentlyContinue
"监听 8801 的连接数：$(($r | Measure-Object).Count)" | Tee-Object records/port_check.txt
```

2. 把本章自检记录里的事实抄进栏 8：命令行对着本章步骤用的终端，Python 对着 `records/env_check_final.txt` 里的 Python 版本一行，Node.js 对着 `records/board-demo/` 能生成。抄的是你们机器上的事实，不是范例里的字：自检里缺了哪样，栏里就写“没有”，并记进 `records/issues.md`。端口一句照范例抄，换了端口就在末尾补一句换成几号。
3. 存成 `records/column8.md`。第 4 章起，任务书的栏 8 整段从这份文件抄。

- 产物：`records/port_check.txt`、`records/column8.md`。
- 验收：栏 8 每一条事实都能在自检记录里指出出处；自查三条都过；端口检查记录里有连接数，若换了端口，`column8.md` 里写明新端口号。

## 本章小结

- 渔具包十项：DSH、gstack、课程版 gstack-sprint、看板生成器、课程数据包、学员工具箱、Git、Python 3.12、浏览器、大模型接口；gstack 与课程版技能由讲师预装，你只做自检。
- gstack 是一套技能；技能是 DSH 按名字加载的说明文件；gstack-sprint 是把一次交付拆成 8 环的课程版技能；看板是 `board.json` 加两份生成物。
- 问“是不是同一份数据”看内容校验和；问“文件有没有被改”用文件指纹前后对比；只读打开只管所打开的那个库；凭据只放在被忽略的本地配置文件里。
- 任务书栏 8 写你们机器上的事实：系统与命令行、有哪些运行环境、默认端口；起服务前先查端口，被占用就换空闲端口并告诉你，同一时刻一个实例，用完复查释放。各章照抄这一栏。

## 下章预告

先看一节“8 环演示”：讲师用一次真实运行记录，带全班在每个决策点先投票、再揭晓，你只看、只举牌，不动手。再进第 3 章“业务、数据与需求”：你已经能只读地打开库，下一步弄清运营负责人到底要什么、数据里有哪些容易算岔的地方。你们会把诉求收敛成一份写明成功标准的需求清单，再填一张数据事实卡；只读打开课程数据库，核实几处口径上有歧义的地方，把核实到的事实记在卡上；并亲眼看一次写入被只读连接挡回来。这两份东西是第 4 至 7 章任务书前几栏的原料。
