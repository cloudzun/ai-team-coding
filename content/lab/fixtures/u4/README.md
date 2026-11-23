# 单元四 负向对照夹具 `bad_card.json`

> 这是随工具箱发给学员的坏样例：给 `u4_check.py` 做“卡片上的数被改了一位也判得出来”的对照。
> **G2 之前跑，可交 qa 跑，不交给 builder；学员自己读输出、写人眼三问与结论。**

两个文件，形状就是 `window.__cardExport()` 的返回（`tool`、`params`、`rows[{key,label,value}]`）：

- `good_card.json`：一张区级对比卡的导出——8 个区 × 2025-01-01 ~ 2025-03-31、入住率。数值由插件自己的 `__test.createTools` 调后端实跑得到，不是手写的。
- `bad_card.json`：同一张卡，只把 D08 那一行的 `value` 从 `0.4989` 改成 `0.5289`（`label` 没动）。所以只有“卡片数值”这一项该判红。

## 应得结果

先起后端、存一次基线，再跑负向对照（端口示例写 8801，被占用就换空闲端口，命令里的端口同步换）：

```powershell
py -3.12 v2\lab\tools\u4_check.py --db <业务库> --ops <运营库> --before before.txt --save-before
py -3.12 v2\lab\tools\u4_check.py --db <业务库> --ops <运营库> --base http://127.0.0.1:8801 --before before.txt --card v2\lab\fixtures\u4\bad_card.json
```

应得：三项里只有「卡片数值」一行 FAIL，报 `第 8 行 D08：卡片 52.9%（0.5289）≠ 接口 49.9%（0.4989）`，退出码 1。

把 `--card` 换成你自己从 DSH 控制台导出的那份（或随包的 `good_card.json`），应当三行全 PASS、退出码 0。

若 `good_card.json` 每一行都红，先核对数据包是不是同一份（`v2\kit\checksums.txt` 的 `db_file_sha256`）；不是的话，用你自己导出的卡改一位数值来当坏夹具，判定一样成立。
