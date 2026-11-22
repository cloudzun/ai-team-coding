# 样例页：一张图、一段导出、一次对账

单元一“样例演练”用的材料。三步走完：打开页面 → 控制台导出 → 跑对账脚本，看正常页通过、装反页变红。

## 目录里有什么

| 文件 | 是什么 |
|---|---|
| `index.html` | 一张“按月入住率：本期 vs 上年同期”的折线图，手写 SVG，不依赖任何 CDN；页面自带 `window.__chartExport()` |
| `index_swapped.html` | 同一张图，但渲染时把两个系列的图例名对调了（数据没动）。导出函数本身没改 |
| `sample_expected.json` | 这张图的期望值，形状与 `chart_check.py --expected` 一致 |

样例页里的数字是虚构的整齐数字，**不是课程数据库的数值**，所以这里不需要 `ref.sql`：期望值直接写进 JSON。
页面顶部也标了这一点，演练时可以直接指着那句话讲“界面上的模拟数据声明”。

## 为什么导出要从页面节点读（防自报）

如果导出函数直接回传脚本里那份数据数组，图装反了，导出的数字照样“正确”，判据就白写了。
样例页的导出函数只读已经渲染出来的 SVG 节点：

- 数值：由数据点的纵坐标反算回 0 到 1 的比例（`py()` 的逆运算），不是读数据数组；
- 横轴类目：取刻度文字的文本，并按横坐标就近对齐；
- 系列名：取图例里的文字；
- 显示文字：取每个点上方那段文字，作为 `label`。

`index_swapped.html` 只改了图例上的两个名字。导出函数照实读，所以导出的“本期”挂着上年同期的数值——
这就是装反能被抓到的原因。

## 三步演练

### 第 1 步　打开页面

直接双击 `index.html` 即可：样式、脚本、图都在文件里，不发任何请求，用 `file://` 打开就能跑。

想走“本地静态服务”也行：在本目录起一个服务，端口在 8811 到 8819 里挑一个空闲的。

```text
Get-NetTCPConnection -LocalPort 8813 -State Listen      # 没有输出就是这个端口空闲
python -m http.server 8813
```

然后访问 `http://127.0.0.1:8813/index.html`。演练结束把自己起的服务停掉。

### 第 2 步　控制台导出

在页面上按 F12 打开控制台，执行：

```javascript
copy(JSON.stringify(await window.__chartExport(), null, 2))
```

新建 `export.json`，粘贴保存。导出的对象有四块：`page`、`filters`、`kpis`、`charts`；
`charts` 里是 `series`，每个系列下是 `points`，每个点带 `x`、`value`、`label`。

再打开 `index_swapped.html`，同样执行一次，存成 `export_swapped.json`。

### 第 3 步　跑对账

在 `sample` 目录执行：

```text
python ..\tools\chart_check.py --expected sample_expected.json --export export.json
```

每个对象一行 PASS，末行“全部通过”，退出码 0。

换成装反页的导出：

```text
python ..\tools\chart_check.py --expected sample_expected.json --export export_swapped.json
```

图表那一行 FAIL，逐条列出超差点，退出码 1。

最后做负向自检：拿正常页的导出，让脚本先把两个系列名对调再比。

```text
python ..\tools\chart_check.py --expected sample_expected.json --export export.json --swap "本期,上年同期"
```

正确的看板此时必须变红。如果它仍然全绿，说明这条判据对装反不敏感，要换判据，不是看板没问题。

## 三个角色各看什么

- 业务角色：给演示脚本的某一步补写“证明什么”。
- 分析角色：对一条判据问两问——零工作量能不能过？照错实现写会不会被打红？
- 技术角色：读导出的 `x`、`value`、`label` 三层，写出“怎样判这段数据与眼睛看到的一致”。

## 常见现象

| 现象 | 原因 |
|---|---|
| 导出里没有 `charts` | 页面还没渲染完就调用了，或调用的是别的对象；确认执行 `await window.__chartExport()` |
| 粘贴进文件的 JSON 多包了一层引号 | 脚本会先解一层，不必手工改 |
| 报“缺系列” | 导出的系列名与期望里的写法不一致（多了空格、简繁或括号不同），以期望文件里的写法对齐 |
| 退出码 2 | 参数或文件有问题，脚本没跑起来；报错信息会指出是哪个文件 |
| 退出码 1 | 脚本跑了，有对象没对上；告警（WARN）不影响退出码 |
