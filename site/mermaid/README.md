# site/mermaid —— mermaid 预渲染缓存（入库）

教材里的 ` ```mermaid ` 代码块在**构建时**渲染成内嵌 SVG，页面里不加载任何 mermaid 脚本（离线可用）。
渲染结果就存在这个目录：`<hash>.svg`，文件名为源码哈希，**要提交入库**。

- 哈希 = 源码 + mermaid 版本 + 主题配置 + 字体族（见 `scripts/mermaid.mjs` 的 `mermaidKey`）。
  改了图或主题，哈希变，旧的 SVG 可以删掉（构建只会用得到的那些）。
- 构建时命中缓存 -> 直接内嵌，**不需要浏览器**；CI（ubuntu、没有 Chrome）就靠这个。
- 未命中 -> 用本机 Chrome / Edge 渲染一次并写在这里（`PUPPETEER_EXECUTABLE_PATH` 可指定浏览器）；
  本机没有浏览器且缓存缺失时，构建直接失败并提示先在本机构建。
- **发布模式（`--release-assets`，CI 用的那个）只认缓存、不现渲染**：未命中就失败并列出缺哪几个文件，
  免得 Linux 上渲出来的字形和本地不同，CI 产物与本地不一致。

所以：**给教材加了新的 mermaid 图之后，在本机跑一次 `npm run build -- --db-source <库文件>`，
把新增的 `site/mermaid/<hash>.svg` 一起提交**，CI 才构建得过去。

本目录不参与站点拷贝（`dist/` 里没有它），只为构建提供缓存。
