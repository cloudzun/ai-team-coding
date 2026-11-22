# 单元二 问答记录夹具 `good_answers.jsonl` / `bad_answers.jsonl`

> 这是随工具箱发给学员的对照夹具：给 `u2_check.py` 第 3 项（回答里的数字可追溯）做“写得对判得绿、装坏必判红”的对照；G2 前用它确认检查命令“装坏必判红”。

两份文件都是**一份问答记录**，形状就是 `POST /api/ask` 的原始返回（`question / mode / answer / steps[] / citations[] / diagnosis / meta`），一行一条 JSON：

| 文件 | 内容 | 第 3 项应得 |
|---|---|---|
| `good_answers.jsonl` | 2 条：D08 2025 年二季度入住率与平均房价（同比 2024 年二季度）、该区该季有效评分条数与平均分。回答里的数字都能在结果行里找到（原值、同行两列之差、行数） | **PASS**（退出码 0，三项全绿） |
| `bad_answers.jsonl` | 1 条：同上第一条，但把“下降 4.65 个百分点”改成了“下降 **11.4** 个百分点”——结果行里算不出这个数；这条的 `meta.untraceable` 故意留空 | **FAIL**：`第 1 条有无法追溯的数字：11.4 个百分点`（退出码 1） |

## 为什么坏的那条要故意留空 `meta.untraceable`

服务自己也会做一遍数字可追溯检查，并把结果写进 `meta.untraceable`。**读那个字段的检查器，在被测方自报干净时会放过编造数字。** `bad_answers.jsonl` 里 `untraceable` 是空的、`degraded` 是 `false`，就是要证明 `u2_check.py` 不看它、自己从结果行算。

## 数字怎么来的

`make_answers.py` 只读打开业务库，现算下面两组数（口径同存档点 `app/ask/pipeline.py::_skeleton_plan`：入住率 = 完成单入住间夜 / 扣掉房东关房后的可售房源晚数，平均房价 = 完成单金额 / 完成单入住间夜；市场基准取 `market_benchmark` 该区该季各月算术平均），再拼成两份文件：

| 项 | 2025Q2（本期） | 2024Q2（上年同期） |
|---|---|---|
| D08 入住率 | 0.6422 | 0.6887 |
| D08 平均房价 | 305.99 元 | 289.45 元 |
| 市场基准入住率 | 0.6324 | 0.6318 |
| 市场均价 | 324.42 元 | 318.17 元 |
| 有效评分 | 527 条，平均 4.67 分 | — |

问句与数字**没有**取自讲师答案：`instructor-kit/out/golden_qa.json` 里没有 D08、没有 2025Q2（两处计数都是 0），`stories.json` 里 D08 也是 0 次（7 个故事只点到 D03）。两份文件只用于避让，正文一个字没抄。

重新生成（换库或想换窗口时）：

```powershell
py -3.12 v2\lab\fixtures\u2\make_answers.py <业务库 homestay.db 路径> v2\lab\fixtures\u2
```

生成脚本只读打开业务库，只写输出目录里的两个 `.jsonl`。

## 怎么跑（负向演练：一条命令，学员自己在 G2 之前跑）

**这一步由学员自己在 G2 之前、在项目外跑一条命令；不交给 builder，也不由 lead 代跑。** 目的只有一个：亲眼确认检查命令「装坏必判红」——坏夹具必须判红（退出码 1），正夹具必须判绿（退出码 0）。

先起服务、再存一次基线（只在动手前做一次），然后一条命令跑负向演练（端口示例写 8801，被占用就换空闲端口，命令里的端口同步换；`<运行目录>` 换成项目目录的 `sprint-runs` 下最新的那个子目录，命令把命令行、输出和退出码写进它的 `evidence\user-check.md`）：

```powershell
py -3.12 v2\lab\tools\db_fingerprint.py data\homestay.db > before.txt
py -3.12 v2\lab\tools\u2_check.py --db data\homestay.db --base http://127.0.0.1:8801 --before before.txt --answers v2\lab\fixtures\u2\bad_answers.jsonl --record <运行目录>\evidence\user-check.md
```

应得：`[FAIL] 回答数字可追溯：第 1 条有无法追溯的数字：11.4 个百分点`，退出码 1。

把 `--answers` 换成 `v2\lab\fixtures\u2\good_answers.jsonl` 再跑同一行，应得三行 PASS、退出码 0。
跑完你就知道：这台机器上的检查命令既会判红、也会判绿，不是“怎么写都红”也不是“怎么写都绿”。

只验第 3 项（不起服务也能看这一行，另两项会打印“未检查”并把退出码判 1）：

```powershell
py -3.12 v2\lab\tools\u2_check.py --answers v2\lab\fixtures\u2\bad_answers.jsonl
# [FAIL] 回答数字可追溯：第 1 条有无法追溯的数字：11.4 个百分点
```

## 边界（别当答案样例用）

- 两条问答记录是**手写的夹具**，不是模型跑出来的回答，也不是验收口径：`meta.model` 写的是 `fixture`，`elapsed_ms` 是占位。
- 检查器认得“原值、同行两列或同列两行的差与比值”，所以某些编造数字可能恰好等于某两个结果值的比值（被算作可追溯）。这是“允许差值与比值”这条规则的固有代价，不是漏检某一条。
- 分数、金额、百分点的显示位数按写几位小数放宽半位（写 1 位就容差 0.05），金额另有 0.01 元容差；这两条容差是“看起来对得上”的下限，不代替人眼抽验。
