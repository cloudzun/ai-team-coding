<!-- Chapter: 2  Author: AI 写稿  Version: V3.0  Updated: 2026-11-22 -->

# 第 2 章 搭最小环境与环境自检

## 本章目标

本章 1 学时。做完本章，你手里有一套“渔具包”，而且有记录证明它能用。后面四个单元，你都靠这套渔具做事。具体地，你能：

1. 列出渔具包的十项，说出每一项在课程里干什么；讲清 gstack、技能、gstack-sprint、看板各是什么、不是什么。
2. 运行环境自检脚本，读懂每一行是绿还是红，处理红项，拿到自动项全绿、退出码为 0 的整段输出。
3. 完成 gstack 自检（三步）、同名冲突自检、看板生成器演示各一次，每项留下记录。
4. 说出“内容校验和”和“文件指纹”各回答什么问题；用只读方式打开课程数据库，记下各表行数。
5. 把大模型接口的访问地址与密钥放进被版本控制忽略的本地配置文件，并验证确实被忽略。
6. 把本章自检记录里的事实写成任务书栏 8（端口与环境事实），并做一次端口占用检查。
7. 自学时，在自己的机器上从零装好渔具包（“环境准备”一节）：手动装 DSH、配模型、选工作区，其余让 DSH 照四段提示词自己装，每一处都看到成功的标志。

验收标准（组内三人共同交出）：

- 环境自检整段输出，末行为“自动项全部通过，可以开始”；浏览器、DSH 会话、大模型接口三项人工勾选全部勾上。
- gstack 自检：`gstack_status.txt` 退出码为 0 且 `claude` 一行结果列为 `current`；`gstack_doctor.txt` 末行含 `0 fail`；DSH 会话里九个技能名都在，并加载一个技能读出标题。
- 同名冲突自检：`same_name.txt` 末行“同名技能共 1 份”，且描述以“课程副本”开头。看板演示：`records/board-demo/` 里有 `BOARD.html` 与 `BOARD.md`，生成命令退出码为 0。
- 各表行数记录一份，与自检输出一致；数据库文件指纹对比末行为“不变”。
- 栏 8 一份（`records/column8.md`），每条事实都能指出对应的自检记录；端口占用检查记录一份（`records/port_check.txt`）。
- 问题清单一份：没解决的项写明现象与卡在哪一步；全绿时写“无”。
- 自学者另有一条：“环境准备”里手动三件事和四段提示词，每一处“看到什么算成功”都对上；课堂上讲师已预装的，不必做。

## 讲解

### 2.1 渔具包清单

课程教的是“渔”，渔具就是 gstack 和围着它配齐的东西，合称渔具包，单元一到单元四共用。gstack 与课程版 gstack-sprint 技能，课堂上由讲师预装，你只做自检；自学、用自己的机器时，先照后面的“环境准备”一节，让 DSH 帮你装，再做自检。其余随课堂分发或用你自己的机器。

| 项 | 它在课程里干什么 | 怎么确认 |
|---|---|---|
| 1 DSH（宿主） | 全课统一的工作台：你和 gstack 的对话、技能加载、子任务派发都在 DSH 会话里发生 | 开一个会话，看到会话界面 |
| 2 gstack（课堂上讲师预装；自学自己装） | 一套现成的工作方法：想清需求、写规格、评审、验收都有对应技能，你的任务书由它们加工 | gstack 自检三步 |
| 3 课程版 gstack-sprint 技能（课堂上讲师预装；自学自己放） | 把一次交付拆成 8 环的流程表，第 4 章起每个单元都按它走 | DSH 里加载它，读出标题 |
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
- 在 DSH / gstack 里叫什么：**gstack**；课程所用版本含几十个技能，会话里按短名称加载，例如 `office-hours`、`spec`、`qa-only`。

**技能**
- 类比：一张写好的工序卡。先做什么、再做什么、做完交什么，写在纸上，谁拿到都能照办。
- 定义：技能是一份带名字和适用场景描述的 Markdown 说明文件，宿主按名字加载它，agent 照里面的步骤做事。
- 边界：它不是程序，不会自己运行；加载了技能不等于做完了事，照它做出来的东西仍要你验。
- 在 DSH / gstack 里叫什么：**技能（skill）**，文件名 `SKILL.md`；DSH 用 `skill` 工具按名字加载。

**gstack-sprint**
- 类比：装修队的施工流程表。先量房、出图、审图、施工、验收、交钥匙，每步有人负责，关键几步要业主签字。
- 定义：课程版 gstack-sprint 是一个技能，规定一次版本交付走 8 环（环 0 到环 7）：lead 编排并判每环的门禁，子 agent 执行各环，你在 G1、G2 两道闸门拍板。
- 边界：它不是自动驾驶，你要写任务书、回字母、纠偏、过闸门；它也不在 gstack 自带的那几十个技能里，是课程发放的副本，放在另一个技能目录。lead 是你在 DSH 主会话里对话的 agent，子 agent 是 lead 派出去干具体活的 agent；8 环各是什么，第 1 章已讲。
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

## 环境准备：自己的机器从零装起

课堂上，DSH、gstack、课程版 gstack-sprint 由讲师预装，你直接做后面的“实操”。自学，或用自己的机器时，先把本节做完，再进“实操”的步骤 1。做完后，机器上有：Git（含 Git Bash）、Python 3.12、Node.js、Bun、DSH、你自己的大模型接口、锁定版本的 gstack、课程版 gstack-sprint、课程总包。系统用 Windows 11，要能上网；浏览器用系统自带的 Edge 即可。

本节的主路线里，你只用手做三件事：装 DSH、在设置里配模型、选一个空文件夹当工作区。其余的软件和文件，全部由你把本节给的提示词发给 DSH，让 DSH 自己装。提示词分四段，每段一个检查点。一次只发一段：把整段复制发给 DSH，等它答完，看到这一段后面写的“成功”标志，再发下一段。每段提示词里都写死了版本和来源，要求 DSH 不得自行换版本、遇到错误先把原文报给你再给方案、做完按清单逐项回答“是/否 + 证据”。密钥只填在设置里，不要贴进对话。DSH 弹出批准框时，先看一眼它要执行的命令，地址和软件名应当就是提示词里写的那些，再批准。某一段怎么都走不通，用本节末尾的“备用做法”自己动手装。

### 手动一 装 DSH

入口是 DeepSeek 官网下载页 https://www.deepseek.com/download/ ，下载 Windows 版，安装包约 300 MB。安装向导一路确认，安装位置保持默认；Windows 提示“已保护你的电脑”时，点“更多信息”再点“仍要运行”。装完，从开始菜单打开 DeepSeek Harness。课程编写时验证的 DSH 版本是 0.2.2-rc.5，这是预览版，界面可能随版本变化。

- 成功：打开后看到 DSH 的主界面（第一次可能先出现欢迎页，按提示确认即可）。

### 手动二 给 DSH 配大模型接口

DSH 自己不带模型。课程里 agent 做事、后面的产品调用，都要用你自己的大模型接口；兼容 OpenAI 接口的服务商都行。下面以硅基流动（SiliconFlow）为例，换别家就换成它文档里给的访问地址、模型名和你的密钥。密钥你自己到服务商网站申请；它只填在下面这一处，不贴进对话、截图和任何要交的记录。

系统语言是中文时，DSH 的界面和回复都是中文；系统语言是英文时是英文，下面括注对应的英文名。在 DSH 里打开“设置 → 模型”（Settings → Models），点“添加模型提供商”，把卡片切到“自定义模型 API”，按下表填写后保存：

| 项 | 例如 |
|---|---|
| Provider ID | `siliconflow`（小写，保存后不能改） |
| 基础 URL | `https://api.siliconflow.cn/v1` |
| API 协议 | OpenAI Chat Completions |
| API 密钥 | 你自己的密钥 |
| 模型 | `deepseek-ai/DeepSeek-V3.2`（点“获取可用模型”搜索后勾选，或直接手填模型 ID） |

- 成功：“设置 → 模型”页出现 `siliconflow` 卡片，卡片里有 `deepseek-ai/DeepSeek-V3.2`。

这三样（访问地址、模型名、密钥）也是后面步骤 5 的 `.env` 里 `LLM_BASE_URL`、`LLM_MODEL`、`LLM_API_KEY` 要填的值，到时用同一组。

### 手动三 选一个空文件夹当工作区

在文件管理器里新建一个空文件夹，名字用英文、不含空格，例如 `l1-course`，不要放进已有的项目文件夹里。在 DSH 里点“选择工作区”（Select workspace），添加并选中它（没选工作区时，输入框是灰的）。新开一个会话，在模型菜单里选 `deepseek-ai/DeepSeek-V3.2`，发一句“你好”。后面四段提示词都在这个会话里发。

- 成功：会话里收到模型的回复文字。收到报错，回到手动二检查地址、模型名、密钥有没有填错。

### 段 1 装工具

这一段让 DSH 装 Git（含 Git Bash）、Python 3.12、Node.js LTS、Bun。整段复制，发给 DSH：

```text
请帮我在这台 Windows 11 电脑上装四样工具：Git（含 Git Bash）、Python 3.12、Node.js LTS、Bun。我不敲命令，由你来做。

版本要求，不许自行换：
- Git：Git for Windows 当前稳定版，必须带 Git Bash。
- Python：3.12 系列（3.12.x），不要装 3.13 或更新的版本。
- Node.js：LTS 版，不要装 Current 版。
- Bun：1.4.2 或更高。

做法：
1. 先用 winget 逐条安装，命令固定为：
   winget install --id Git.Git -e --accept-package-agreements --accept-source-agreements
   winget install --id Python.Python.3.12 -e --accept-package-agreements --accept-source-agreements
   winget install --id OpenJS.NodeJS.LTS -e --accept-package-agreements --accept-source-agreements
   winget install --id Oven-sh.Bun -e --accept-package-agreements --accept-source-agreements
2. winget 不能用，或其中某一条失败（例如提示源数据缺失），就对失败的那一项改用官网安装包。只能用下面这些来源，别的网站不要用：
   - Git：https://git-scm.com/download/win ，64 位安装包，静默参数 /VERYSILENT /NORESTART /SP-
   - Python：https://www.python.org/downloads/windows/ ，选 3.12.x 的 64 位安装包，静默参数 /quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1
   - Node.js：https://nodejs.org/ ，LTS 的 64 位 Windows 安装包（.msi），静默安装 msiexec /i 安装包文件 /qn
   - Bun：在 PowerShell 里运行 irm bun.sh/install.ps1 | iex
3. 装完后，刚装的软件可能还没进当前窗口的 PATH。检查前先从系统里重新读取用户和系统两份 PATH，再运行：
   git --version
   python --version
   node --version
   bun --version
   Test-Path "C:\Program Files\Git\bin\bash.exe"
   如果重读后仍然找不到命令，先告诉我，不要自行重装。
4. 如果 python 命令弹出应用商店、或没有任何输出，先把现象原文报给我，再给处理方案，等我同意再做。

遇到任何错误，先把错误原文完整贴给我，再给出处理方案并说明理由；上面列出的备用来源可以直接用，列表之外的做法先问我。不要把任何密钥写进命令或回复。

全部做完后，按下面清单逐项回答，每项写“是”或“否”，并附证据（命令输出原文）：
1. Git 已装好：git --version 的输出；C:\Program Files\Git\bin\bash.exe（Git Bash）是否存在
2. Python 是 3.12：python --version 的输出，是否以 3.12 开头
3. Node.js 已装好：node --version 的输出
4. Bun 是 1.4.2 或更高：bun --version 的输出
最后一行写“四项都是”或“有否项：…”。
```

- 成功：DSH 的回复里，四项都是“是”，Git、Node.js 打印版本号，Python 以 3.12 开头，Bun 是 1.4.2 或更高，且 Git Bash 的 `bash.exe` 存在。
- 批准框：DSH 弹批准框时，看一眼它要执行的命令，应当是 `winget install` 或上面写的官网地址，再批准；Windows 弹出“是否允许此应用对你的设备进行更改”时点“是”。

### 段 2 下载课程材料

这一段让 DSH 把课程总包下载并解压到工作区。整段复制，发给 DSH：

```text
请帮我把课程材料下载并解压到当前工作目录。我不敲命令，由你来做。

固定来源，不许自行换地址：
https://github.com/cloudzun/ai-team-coding/releases/download/v2/ai-team-coding-materials.zip

做法：
1. 先打印当前工作目录的路径并列出里面的内容，确认它是我选的那个空文件夹。如果里面已经有别的文件，先告诉我，不要继续。
2. 在 PowerShell 里下载：
   curl.exe -L --fail -o "$env:TEMP\ai-team-coding-materials.zip" https://github.com/cloudzun/ai-team-coding/releases/download/v2/ai-team-coding-materials.zip
3. 用 Expand-Archive 解压到当前工作目录：
   Expand-Archive -Path "$env:TEMP\ai-team-coding-materials.zip" -DestinationPath . -Force
   必须用 Expand-Archive，不要用 tar：tar 在部分系统区域下会丢掉中文名的文件。
4. 解压后，在当前工作目录里用 Test-Path 检查下面各项，并列出 v2 下的文件夹：
   v2\kit\db\homestay.db
   v2\kit\student-pack
   v2\kit\gstack-sprint\SKILL.md（还要报告文件大小，必须大于 0 字节）
   v2\kit\tools\demo\board.json

遇到任何错误（下载失败、解压失败、缺文件），先把错误原文完整贴给我，再给出处理方案并说明理由，等我同意再换做法。不要把别处的文件拷进来凑数。

全部做完后，按下面清单逐项回答，每项写“是”或“否”，并附证据（命令输出原文）：
1. v2\kit\db\homestay.db 在位
2. v2\kit\student-pack 在位
3. v2\kit\gstack-sprint\SKILL.md 在位，且大小大于 0 字节
4. v2\kit\tools\demo\board.json 在位
5. v2 下有 checkpoints、kit、lab 三个文件夹
最后一行写“五项都是”或“有否项：…”。
```

- 成功：DSH 的回复里五项都是“是”，工作区里多出一个 `v2` 文件夹；`homestay.db`、`student-pack`、`SKILL.md` 都在，`SKILL.md` 不是 0 字节。
- 批准框：DSH 弹批准框时，看一眼它要执行的命令，下载地址应当就是提示词里那一条 GitHub 地址，解压用的是 `Expand-Archive`，再批准。

### 段 3 装 gstack 并放入课程版技能

这一段让 DSH 在 Git Bash 里装 gstack、锁定到课程用的提交号，再把课程版 gstack-sprint 放进 DSH 读取的另一个技能目录。整段复制，发给 DSH：

```text
请帮我在这台 Windows 11 电脑上安装 gstack，并放入课程版 gstack-sprint 技能。我不敲命令，由你来做。前提：Git（含 Git Bash）已装好，当前工作目录里已有 v2\kit\gstack-sprint 文件夹。

固定内容，不许自行换版本、换来源：
- gstack 来源：https://github.com/garrytan/gstack.git
- 版本：按提交号 e66c43c57209a17e2d9a79847a2e985c27ca80bd 固定，对应 gstack 1.91.191.0。这一版没有版本标签，所以不要拉最新版，不要用分支名或标签，不要用 git clone 直接拉。
- 安装位置：~/.claude/skills/gstack

第一部分：在 Git Bash 里装 gstack。用 C:\Program Files\Git\bin\bash.exe -l 运行下面这些 bash 命令，不要在 PowerShell 里直接运行。先检查 ~/.claude/skills/gstack 是否已存在且里面有文件；如果是，先停下告诉我，不要删除或覆盖。否则依次运行：
   mkdir -p ~/.claude/skills/gstack && cd ~/.claude/skills/gstack
   git init -q
   git remote add origin https://github.com/garrytan/gstack.git
   git fetch --depth 1 origin e66c43c57209a17e2d9a79847a2e985c27ca80bd
   git checkout -q FETCH_HEAD
   git rev-parse HEAD
   cat VERSION
   ./setup --no-prefix --no-browser < /dev/null
   echo "退出码 $?"
   ./setup --status
说明：./setup 会下载依赖并生成技能说明，要跑很久。请把命令的超时设得足够长，或放后台运行并等它自己结束，不要中途打断，也不要重复运行。它的最后一行应是 gstack ready (claude)。输出里的 CSO unavailable、Chromium install skipped、Claude Code CLI not found、codex not installed 这类提示可以忽略；其他 error 或 fail 要按下面的错误规则处理。不要给 ./setup 加别的参数，不要修改 gstack 目录里的任何文件。

第二部分：放课程版技能。在 PowerShell 里，在当前工作目录运行：
   New-Item -ItemType Directory -Force "$HOME\.agents\skills" | Out-Null
   如果 "$HOME\.agents\skills\gstack-sprint" 已经存在，先停下告诉我，不要直接复制（直接复制会多嵌套一层）。
   Copy-Item "v2\kit\gstack-sprint" "$HOME\.agents\skills\gstack-sprint" -Recurse
   Select-String -Path "$HOME\.agents\skills\gstack-sprint\SKILL.md" -Pattern '^name: gstack-sprint' -Encoding UTF8
   Test-Path "$HOME\.agents\skills\gstack-sprint\gstack-sprint"   （应为 False，True 说明嵌套了）

遇到任何错误，先把错误原文完整贴给我，再给出处理方案并说明理由，等我同意再换做法。不要把任何密钥写进命令或回复。

全部做完后，按下面清单逐项回答，每项写“是”或“否”，并附证据（命令输出原文）：
1. gstack 固定在指定提交号：git rev-parse HEAD 的输出等于 e66c43c57209a17e2d9a79847a2e985c27ca80bd
2. 版本号是 1.91.191.0：cat VERSION 的输出
3. ./setup 跑完且退出码为 0：退出码那一行，以及最后一行是否为 gstack ready (claude)
4. ./setup --status 里 claude 一行的结果列是 current，Install checks 里 section links 写 all resolve：贴这两行原文
5. 课程版技能已放好：Select-String 打印出含 name: gstack-sprint 的一行，且没有 gstack-sprint\gstack-sprint 这一层嵌套
最后一行写“五项都是”或“有否项：…”。
```

- 成功：DSH 的回复里五项都是“是”，`VERSION` 是 `1.91.191.0`，`claude` 一行是 `current`，课程版 `gstack-sprint` 已放进 `~/.agents/skills`。
- 批准框：DSH 弹批准框时，看一眼它要执行的命令，gstack 只能从 `https://github.com/garrytan/gstack.git` 取、版本是那串提交号，复制技能的目标是 `.agents\skills\gstack-sprint`，再批准；这一段要跑很久，屏幕停着不动是正常的，等它报完。

### 段 4 装 Skills Manager

这一段让 DSH 给自己装社区插件 DSH Skills Manager。DSH 自带读取 `~/.agents/skills`，但不读 `~/.claude/skills`，gstack 要靠这个插件才读得到；它是社区维护的插件（Apache-2.0 许可），不是 DeepSeek 官方出品。整段复制，发给 DSH：

```text
请帮我给我正在使用的这个 DSH 安装社区插件 DSH Skills Manager，让 DSH 能读到我机器上 Claude Code 与 Shared Agent 两个技能目录里的技能。我不敲命令，由你来做。

固定内容，不许自行换：
- npm 包名：@michengai/dsh-skills-manager，装最新版，不要换成别的包。
- npm 源：https://registry.npmjs.org/ ，不要换成镜像或别的源。
- 装到我正在用的这个 DSH 里。

做法：
1. 用 DSH 自己的插件安装能力安装（例如 plugin_manager 工具）。需要批准时我会点批准。
2. 装完后，告诉我它的版本号和许可证。
3. 告诉我怎么让它生效。不要自己退出或重启 DSH，由我自己操作：我会把 DSH 完全退出（包括任务栏托盘里的图标）再重新打开。

遇到任何错误（连不上 npm 源、版本要求不满足、安装被拒），先把错误原文完整贴给我，再给出处理方案并说明理由，等我同意再换做法。不要把任何密钥写进命令或回复。

全部做完后，按下面清单逐项回答，每项写“是”或“否”，并附证据（输出原文）：
1. 安装成功：包名、版本号，以及用的是哪个 npm 源
2. 许可证已报告：预期是 Apache-2.0
3. 已告诉我让它生效的步骤：包括“完全退出 DSH，含托盘图标，再重新打开”，以及重开后到设置里哪一页确认
最后一行写“三项都是”或“有否项：…”。
```

DSH 回复三项都是“是”之后，自己把 DSH 完全退出（托盘里的图标也要退出），再重新打开，然后打开“设置”，找到“技能”（Skills）页（系统语言是英文时界面是英文，设置叫 Settings）。

- 成功：重开后，“设置”里出现“技能”（Skills）页，“Claude Code”与“Shared Agent”两个来源都已开启；“Claude Code”下能看到 gstack 的技能（如 `office-hours`、`spec`、`qa-only`），“Shared Agent”下能看到 `gstack-sprint`。
- 批准框：DSH 弹批准框时，看一眼它要执行的命令，包名应当是 `@michengai/dsh-skills-manager`、源是 `https://registry.npmjs.org/`，再批准。

做到这里，回到“实操”，从步骤 1 开始；步骤 3 的 gstack 自检、步骤 4 的 DSH 四句话和同名冲突自检，就是对这四段的验收。

### 备用做法：自己动手装

上面的提示词走不通（比如批准框一直被拒绝，或下载被网络拦住），或者你想自己看清每一步，就用这一部分：命令都在窗口里自己敲，分准备 1 到准备 8 八步，每步都有“看到什么算成功”。准备 2、3、7 就是主路线里的手动一、二、三，已经做过的跳过；做完八步后，同样回到“实操”，从步骤 1 开始。

照抄命令，每一步末尾一句话告诉你看到什么算成功。没看到，先别往下做。命令标明在哪个窗口里运行：**PowerShell** 指开始菜单里的 Windows PowerShell，**Git Bash** 指开始菜单里的 Git Bash（准备 1 装完才有）。

#### 准备 1 装 Git、Python 3.12、Node.js、Bun

在 PowerShell 里逐条运行：

```powershell
winget install --id Git.Git -e --accept-package-agreements --accept-source-agreements
winget install --id Python.Python.3.12 -e --accept-package-agreements --accept-source-agreements
winget install --id OpenJS.NodeJS.LTS -e --accept-package-agreements --accept-source-agreements
winget install --id Oven-sh.Bun -e --accept-package-agreements --accept-source-agreements
```

装完，关掉所有终端窗口，新开一个 PowerShell，运行：

```powershell
git --version
python --version
node --version
bun --version
```

- 成功：四条都打印版本号；Python 以 3.12 开头，Bun 是 1.4.2 或更高。
- 提示“不是可识别的命令”：这个窗口没有重开，关掉重开；仍不行，把对应那条 `winget install` 再跑一遍。`python` 弹出应用商店或没有输出：在“设置 → 应用 → 高级应用设置 → 应用执行别名”里关掉 `python.exe` 的开关，再新开窗口。

#### 准备 2 装 DSH

入口是 DeepSeek 官网下载页 https://www.deepseek.com/download/ ，下载 Windows 版；产品介绍页是 https://www.deepseek.com/harness/ 。也可以在 PowerShell 里直接下载并运行安装包，命令如下：

```powershell
curl.exe -L --fail -o "$HOME\Downloads\dsh-setup.exe" https://download.deepseek.com/desktop/dsh-latest-windows-x64.exe
Start-Process "$HOME\Downloads\dsh-setup.exe" -Wait
```

备注：上面命令里的地址 `https://download.deepseek.com/desktop/dsh-latest-windows-x64.exe` 是 Windows 版安装包的直链。课程编写时验证的 DSH 版本是 0.2.2-rc.5，这是预览版，界面可能随版本变化。

安装包约 300 MB。安装向导一路确认；Windows 提示“已保护你的电脑”时，点“更多信息”再点“仍要运行”。装完，从开始菜单打开 DeepSeek Harness。

- 成功：打开后看到 DSH 的主界面（第一次可能先出现欢迎页，按提示确认即可）。

#### 准备 3 给 DSH 配大模型接口

DSH 自己不带模型。课程里 agent 做事、后面的产品调用，都要用你自己的大模型接口；兼容 OpenAI 接口的服务商都行。下面以硅基流动（SiliconFlow）为例，换别家就换成它文档里给的访问地址、模型名和你的密钥。密钥你自己到服务商网站申请；它只填在下面这一处，不贴进对话、截图和任何要交的记录。

系统语言是英文时，DSH 的界面和回复都是英文：“设置”叫 Settings，“模型”叫 Models，下面括注对应的英文名。在 DSH 里打开“设置 → 模型”（Settings → Models），点“添加模型提供商”，把卡片切到“自定义模型 API”，按下表填写后保存：

| 项 | 例如 |
|---|---|
| Provider ID | `siliconflow`（小写，保存后不能改） |
| 基础 URL | `https://api.siliconflow.cn/v1` |
| API 协议 | OpenAI Chat Completions |
| API 密钥 | 你自己的密钥 |
| 模型 | `deepseek-ai/DeepSeek-V3.2`（点“获取可用模型”搜索后勾选，或直接手填模型 ID） |

- 成功：“设置 → 模型”页出现 `siliconflow` 卡片，卡片里有 `deepseek-ai/DeepSeek-V3.2`。

这三样（访问地址、模型名、密钥）也是后面步骤 5 的 `.env` 里 `LLM_BASE_URL`、`LLM_MODEL`、`LLM_API_KEY` 要填的值，到时用同一组。

#### 准备 4 下载课程总包并解压

在 PowerShell 里运行：

```powershell
New-Item -ItemType Directory -Force "$HOME\l1-course" | Out-Null
curl.exe -L --fail -o "$HOME\l1-course\materials.zip" https://github.com/cloudzun/ai-team-coding/releases/download/v2/ai-team-coding-materials.zip
Expand-Archive "$HOME\l1-course\materials.zip" "$HOME\l1-course" -Force
Set-Location "$HOME\l1-course"
Get-ChildItem v2 | Select-Object Name
Test-Path v2\kit\checksums.txt
Test-Path v2\kit\db\homestay.db
Test-Path v2\kit\student-pack
```

解压命令用 `Expand-Archive`，不用 `tar`：系统区域不是中文时，`tar -xf` 会丢掉中文名的文件。解开后，`l1-course` 里应有 `v2` 文件夹。用户目录下的 `l1-course` 文件夹，就是后面所说“含 `v2` 文件夹的那一层目录”；以后在 PowerShell 里先 `Set-Location "$HOME\l1-course"` 再运行命令。

- 成功：`Get-ChildItem` 列出 `checkpoints`、`kit`、`lab` 三个文件夹，三条 `Test-Path` 都输出 `True`，即 `v2\kit\db\homestay.db` 与 `v2\kit\student-pack` 两份资料都在。

#### 准备 5 装 gstack，锁定到课程用的版本

课程按 gstack 1.91.191.0 这一版写。这一版没有打版本标签，所以用提交号锁定，不要直接拉最新版（最新版的内容会变）。在 Git Bash 里逐条运行：

```bash
mkdir -p ~/.claude/skills/gstack && cd ~/.claude/skills/gstack
git init -q
git remote add origin https://github.com/garrytan/gstack.git
git fetch --depth 1 origin e66c43c57209a17e2d9a79847a2e985c27ca80bd
git checkout -q FETCH_HEAD
cat VERSION
./setup --no-prefix --no-browser
echo "退出码 $?"
./setup --status
```

`./setup` 过程中若出现 y/N 的提问，直接按回车；不回答也会自动跳过。`--no-browser` 是跳过 gstack 自带浏览器的下载，本课用不到它。`./setup` 会自动安装依赖并生成技能说明，需要等它跑完，屏幕最后一行是 `gstack ready (claude)`。其中 `CSO unavailable` 和浏览器相关的跳过提示（如 `Chromium install skipped`）可以忽略。

- 成功：`cat VERSION` 打印 `1.91.191.0`；`./setup` 末行是 `gstack ready (claude)`；`退出码 0`；`./setup --status` 里 `claude` 一行的结果列是 `current`。

gstack 采用 MIT 许可，许可证文件是目录里的 `LICENSE`。

#### 准备 6 放入课程版 gstack-sprint

课程版 gstack-sprint 在总包的 `v2\kit\gstack-sprint\` 里，放到 DSH 读取的另一个技能目录 `~/.agents/skills`。在 PowerShell 里运行：

```powershell
New-Item -ItemType Directory -Force "$HOME\.agents\skills" | Out-Null
Copy-Item "$HOME\l1-course\v2\kit\gstack-sprint" "$HOME\.agents\skills\gstack-sprint" -Recurse
Select-String -Path "$HOME\.agents\skills\gstack-sprint\SKILL.md" -Pattern '^name: gstack-sprint' -Encoding UTF8
```

- 成功：最后一条打印出含 `name: gstack-sprint` 的一行。若提示找不到路径，说明准备 4 没做完。

若最后一条没有任何输出，先运行 `Get-ChildItem "$HOME\.agents\skills" -Recurse`，对照下面两种情况改：

- `SKILL.md` 的大小是 0 字节：总包里的这个文件不完整。重新做准备 4 的下载与解压（`-Force` 会覆盖），再 `Remove-Item "$HOME\.agents\skills\gstack-sprint" -Recurse`，然后重跑上面的 `Copy-Item` 和 `Select-String`。
- 看到 `gstack-sprint\gstack-sprint` 两层目录：目标目录已存在时，`Copy-Item` 会把文件复制进多出来的一层。先 `Remove-Item "$HOME\.agents\skills\gstack-sprint" -Recurse` 删掉整个目录，再重跑 `Copy-Item`。

#### 准备 7 选工作区，确认模型能答

在 DSH 里点“选择工作区”，添加并选中用户目录下的 `l1-course` 文件夹（没选工作区时，输入框是灰的）。新开一个会话，在模型菜单里选 `deepseek-ai/DeepSeek-V3.2`，发一句“你好”。系统语言是英文时，界面是英文，回复也可能是英文，这是正常的。

- 成功：会话里收到模型的回复文字；回复里若主动提到 L1 course edition，说明课程版技能已被读到。收到报错，回到准备 3 检查地址、模型名、密钥有没有填错。

#### 准备 8 让 DSH 读到 gstack 和课程版技能

DSH 自带读取 `~/.agents/skills`，课程版 gstack-sprint 已在那里；gstack 在 `~/.claude/skills`，DSH 自己不读这个目录，要装一个社区插件 DSH Skills Manager（Apache-2.0 许可，不是 DeepSeek 官方出品）。在准备 7 的会话里发这句话：

> 请把 npm 包 @michengai/dsh-skills-manager 最新版安装到我的 DSH，使用官方 npm 源 https://registry.npmjs.org/ ，装完告诉我怎么让它生效。

出现批准框就批准；装完把 DSH 完全退出（托盘里的图标也要退出），再重新打开，然后打开“设置”（系统语言是英文时界面是英文，设置叫 Settings，插件相关页叫 Plugins，技能页叫 Skills）。

- 成功：设置里出现“技能”（Skills）页，页里“Claude Code”来源下能看到 `gstack` 一套的技能（如 `office-hours`、`spec`、`qa-only`），“Shared Agent”来源下能看到 `gstack-sprint`，两个来源都已开启。

做到这里，回到“实操”，从步骤 1 开始；步骤 3 的 gstack 自检、步骤 4 的 DSH 四句话和同名冲突自检，就是对这八步的验收。

## 实操

命令都在“含 `v2` 文件夹的那一层目录”（步骤 1 的空目录）里运行，以 Windows PowerShell 为主；gstack 自检的命令在 Git Bash 里运行，也在这一层目录。三个角色：业务核对校验和并读资料，分析只读记行数并跑看板演示，技术确认渔具包可用。

### 步骤 1 起点

起点：每组一个空目录、一台能联网的机器、课程数据包。顺序不能换：先建目录，再 `git init`，然后才写忽略规则、验证。记录一律放进 `records`，不放进 `v2/kit/db/`。
```powershell
# 建目录（Git Bash：mkdir -p v2/kit/db v2/lab records）
New-Item -ItemType Directory -Force v2\kit\db, v2\lab, records
# 先把数据包放进 v2\kit、工具箱与样例页放进 v2\lab（拖放也行），再拷库文件；尖括号换成文件所在位置（Git Bash：cp）
# 自学：总包里已带 v2\kit\db\homestay.db（“环境准备”段 2 解压后就在），下面这行跳过
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
`setup --status` 会列出好几个宿主的行，课程只看 `claude` 这一行，因为 DSH 读的是它所在的技能目录。体检里 `warn` 和 `not configured` 不是失败：`codex` 一行显示 not configured，只影响环 3 里“外部意见（Outside Voice）”那一步，第 1 章的 8 环表里已列。再看 DSH 有没有把这个目录读进来，第三步放到步骤 4。这一项在界面里看，要在段 4 做完、DSH 完全退出重开过一次之后才有：打开 DSH 的“设置”（英文界面叫 Settings）里的“技能”（Skills）页，看到“Claude Code”与“Shared Agent”两个来源都已开启，并且展开“Claude Code”能看到 gstack 的技能（如 `office-hours`、`spec`、`qa-only`）。技能页没有这两个来源，说明段 4 还没生效。
- 产物：`records/gstack_status.txt`、`records/gstack_doctor.txt`；版本号，以及技能页两个来源是否开启，写进 `records/tech_notes.md`。
- 验收：两条命令退出码都是 0；`claude` 一行结果列为 `current`；体检末行含 `0 fail`；技能页里“Claude Code”与“Shared Agent”两个来源都已开启，“Claude Code”下能看到 gstack 的技能。

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
| `setup --status` 退出码为 1，或 `section links` 不是 all resolve；`gstack-doctor` 末行 `fail` 不是 0 | gstack 本身有问题；课堂机上不要自己重装：整段输出贴进 `issues.md`，请讲师处理。自己的机器：回到“环境准备”段 3，先请 DSH 把 `~/.claude/skills/gstack` 改名移走（不删除），再发一遍段 3 的提示词 |
| 找不到 `~/.claude/skills/gstack`，或 DSH 里 `gstack`、`gstack-sprint` 不在技能列表 | 没装到这台机器，或技能页里的来源被关：看步骤 3 的技能页，“Claude Code”与“Shared Agent”都要开启。自己的机器回到“环境准备”段 3、段 4 补装；课堂机仍不对就换用已通过自检的机器，并记入 `issues.md` |

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

- 渔具包十项：DSH、gstack、课程版 gstack-sprint、看板生成器、课程数据包、学员工具箱、Git、Python 3.12、浏览器、大模型接口；gstack 与课程版技能课堂上由讲师预装，你只做自检；自学时按“环境准备”一节自己装。
- gstack 是一套技能；技能是 DSH 按名字加载的说明文件；gstack-sprint 是把一次交付拆成 8 环的课程版技能；看板是 `board.json` 加两份生成物。
- 问“是不是同一份数据”看内容校验和；问“文件有没有被改”用文件指纹前后对比；只读打开只管所打开的那个库；凭据只放在被忽略的本地配置文件里。
- 任务书栏 8 写你们机器上的事实：系统与命令行、有哪些运行环境、默认端口；起服务前先查端口，被占用就换空闲端口并告诉你，同一时刻一个实例，用完复查释放。各章照抄这一栏。

## 下章预告

先看一节“8 环演示”：讲师用一次真实运行记录，带全班在每个决策点先投票、再揭晓，你只看、只举牌，不动手。再进第 3 章“业务、数据与需求”：你已经能只读地打开库，下一步弄清运营负责人到底要什么、数据里有哪些容易算岔的地方。你们会把诉求收敛成一份写明成功标准的需求清单，再填一张数据事实卡；只读打开课程数据库，核实几处口径上有歧义的地方，把核实到的事实记在卡上；并亲眼看一次写入被只读连接挡回来。这两份东西是第 4 至 7 章任务书前几栏的原料。
