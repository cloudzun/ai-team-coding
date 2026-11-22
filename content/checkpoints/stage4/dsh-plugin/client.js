// @local/dsh-homestay — Web 客户端那一半（卡片渲染）。
//
// 在 `tool.call.toolview` 槽位按工具名各注册一个卡片视图（槽位接口见 DSH 文档）。
// 图表用原生 React + SVG 画：React 从浏览器模块表里取，不额外引入任何 Harness Client 包。
// 只读：本文件不发任何网络请求，只按 presentationMeta 画图。
//
//
// Props used (ToolCallOwnerProps): phase ('preparing'|'start'|'result'), block
// (StartedToolCall.argsRaw on start; ToolResultNode content/isError/error/meta on
// result), toolName, useDisclosure.
//
// 展示字符串的唯一来源：每个可见的数字串都已由 Host 侧算好，
// 放在 block.meta（presentationMeta v2）里。本文件只把数值映射成几何，
// 不做格式化、不舍入、不推导指标。
// Unknown kind, v !== 2 or a missing/mistyped required field renders the plain
// tool text (data-homestay-card="fallback") instead of throwing.
window.__ModuleLoader__.load({
  id: '@local/dsh-homestay',
  factory(require) {
    const React = require('react')
    const h = React.createElement

    const zh = () => {
      try { return !String(document.documentElement.lang || navigator.language || 'zh').toLowerCase().startsWith('en') } catch { return true }
    }
    const L = (zhText, enText) => (zh() ? zhText : enText)

    const TOOLS = ['homestay_compare', 'homestay_trend', 'homestay_communities', 'homestay_ask']
    const KIND_OF_TOOL = {
      homestay_compare: 'homestay-compare',
      homestay_trend: 'homestay-trend',
      homestay_communities: 'homestay-communities',
      homestay_ask: 'homestay-ask',
    }
    const TOOL_TITLE = {
      homestay_compare: () => L('民宿经营对比', 'Homestay comparison'),
      homestay_trend: () => L('民宿经营走势', 'Homestay trend'),
      homestay_communities: () => L('小区入住率排行', 'Community ranking'),
      homestay_ask: () => L('民宿问数', 'Homestay Q&A'),
    }

    // 序列颜色属于图表的“美术”部分（可以直接写字面色值）；
    // every container, text and rule uses --dsw-alias-* tokens.
    const C = { cur: '#3b82f6', prev: '#a3acb9', market: '#f59e0b', up: '#16a34a', down: '#dc2626', bar: '#3b82f6' }

    const S = {
      card: {
        border: '0.5px solid var(--dsw-alias-border-l1)', borderRadius: 10, padding: '8px 12px',
        margin: '4px 0', color: 'var(--dsw-alias-label-primary)', background: 'var(--dsw-alias-bg-base)',
        fontSize: 13, lineHeight: 1.45, maxWidth: 760, boxSizing: 'border-box',
      },
      // Head is always one line (v4.2 height budget): title/subtitle shrink with an ellipsis;
      // textContent keeps the full string for the DOM checks.
      head: { display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'nowrap', minWidth: 0, height: 20 },
      // 标题不缩字号也不省略，放不下时让副标题让步。
      title: { fontWeight: 600, flex: 'none', whiteSpace: 'nowrap' },
      sub: { color: 'var(--dsw-alias-label-secondary)', fontSize: 12, flex: '0 1 auto', minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' },
      latest: { color: 'var(--dsw-alias-label-primary)', fontSize: 12, fontWeight: 500, flex: 'none', whiteSpace: 'nowrap' },
      foot: { color: 'var(--dsw-alias-label-secondary)', fontSize: 11, lineHeight: '16px', marginTop: 2, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' },
      legend: { display: 'flex', gap: 14, fontSize: 12, lineHeight: '16px', height: 16, overflow: 'hidden', color: 'var(--dsw-alias-label-secondary)', margin: '4px 0 2px', flexWrap: 'wrap' },
      sw: (c, line) => ({ display: 'inline-block', width: line ? 14 : 10, height: line ? 2 : 10, background: c, borderRadius: line ? 0 : 2, marginRight: 5, verticalAlign: 'middle' }),
      error: { color: 'var(--dsw-alias-state-error-primary)', whiteSpace: 'pre-wrap', fontSize: 12, marginTop: 4 },
      code: { color: 'var(--dsw-alias-state-error-primary)', fontSize: 12, fontWeight: 600 },
      pre: { whiteSpace: 'pre-wrap', fontSize: 12, color: 'var(--dsw-alias-label-secondary)', margin: '6px 0 0' },
      answer: { whiteSpace: 'pre-wrap', margin: '6px 0 2px', lineHeight: '19px' },
      answerClamp: lines => ({ display: '-webkit-box', WebkitBoxOrient: 'vertical', WebkitLineClamp: lines, overflow: 'hidden' }),
      degrade: { color: 'var(--dsw-alias-label-secondary)', fontSize: 12, lineHeight: '16px', margin: '2px 0', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' },
      sql: {
        whiteSpace: 'pre-wrap', fontSize: 11.5, margin: '6px 0 0', padding: '6px 8px', borderRadius: 6,
        border: '0.5px solid var(--dsw-alias-border-l1)', color: 'var(--dsw-alias-label-primary)',
        fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace', overflowX: 'auto',
      },
      toggle: {
        border: '0.5px solid var(--dsw-alias-border-l2)', background: 'transparent', color: 'var(--dsw-alias-label-secondary)',
        borderRadius: 6, fontSize: 12, lineHeight: '16px', padding: '1px 8px', cursor: 'pointer', marginLeft: 'auto', flex: 'none',
      },
      tableWrap: { overflowX: 'auto' },
      table: { borderCollapse: 'collapse', width: '100%', fontSize: 12, marginTop: 6 },
      th: { textAlign: 'right', fontWeight: 500, color: 'var(--dsw-alias-label-secondary)', borderBottom: '0.5px solid var(--dsw-alias-border-l2)', padding: '3px 6px', whiteSpace: 'nowrap' },
      td: { textAlign: 'right', padding: '3px 6px', borderBottom: '0.5px solid var(--dsw-alias-border-l1)', whiteSpace: 'nowrap' },
      note: { color: 'var(--dsw-alias-label-secondary)', fontSize: 11.5, marginTop: 4 },
      // maxWidth = viewBox width: the chart never scales up, so its height in px equals the
      // viewBox height on any container >= 680px (v4.2 height budget).
      svg: { display: 'block', width: '100%', maxWidth: 680, height: 'auto' },
    }
    // 默认态高度预算（≤ 360px）。卡片外框 = 内边距 8+8、边框 1、
    // 头部 20、脚部 2+16 ⇒ 55px，剩下的都给正文。
    const CHROME = 55
    const LEGEND = 22 // margin 4+2, line 16
    const BUDGET = 360 - CHROME // 305
    const NOTE = 22 // S.note: margin 4 + 11.5px * 1.45 line ~ 17 (rounded up)
    const HB_PAD = 18 + 4 // HBars padT + padB
    // Estimated row heights of the HTML table (12px * 1.45 line + 3+3 padding + 0.5 border).
    const TABLE_ROW = 24, TABLE_EXTRA = 6 + 24 + 22 // margin, header row, row-count note
    const ANSWER_LINE = 19, ANSWER_PAD = 8
    const ANSWER_LINE_UNITS = 88 // conservative line capacity at ~600px: CJK = 2 units, ASCII = 1 unit
    /** Layout estimate only (no metric is derived): wrapped line count of the answer text. */
    function answerLines(text) {
      let lines = 0
      for (const para of String(text).split('\n')) {
        let units = 0
        for (const ch of para) units += ch.charCodeAt(0) > 0xff ? 2 : 1
        lines += Math.max(1, Math.ceil(units / ANSWER_LINE_UNITS))
      }
      return lines
    }
    const clampInt = (v, lo, hi) => Math.max(lo, Math.min(hi, Math.floor(v)))
    const AXIS_TEXT = { fill: 'var(--dsw-alias-label-secondary)', fontSize: 11 }
    const NAME_TEXT = { fill: 'var(--dsw-alias-label-primary)', fontSize: 11 }

    // ---- 校验（只认必需字段，其余字段忽略） ----
    const isObj = v => v !== null && typeof v === 'object' && !Array.isArray(v)
    const isStr = v => typeof v === 'string'
    const isNum = v => typeof v === 'number' && Number.isFinite(v)
    const isNumOrNull = v => v === null || isNum(v)
    const isArr = Array.isArray
    const all = (arr, pred) => isArr(arr) && arr.every(pred)
    const strFields = (o, keys) => isObj(o) && keys.every(k => isStr(o[k]))

    function okAxis(a) {
      return isObj(a) && isNum(a.min) && isNum(a.max) && a.min <= a.max
        && all(a.ticks, t => isObj(t) && isNum(t.value) && isStr(t.text))
    }
    const okSeries = s => all(s, x => isObj(x) && isStr(x.key) && isStr(x.label))
    const okEnvelope = m => isObj(m) && m.v === 2 && isStr(m.kind) && isStr(m.title) && isStr(m.subtitle) && isStr(m.footnote)

    const VALIDATORS = {
      'homestay-compare': m => isStr(m.metric) && isStr(m.unit) && isStr(m.yoyKind) && okSeries(m.series) && okAxis(m.axis)
        && all(m.rows, r => isObj(r) && isStr(r.key) && isStr(r.name) && isNumOrNull(r.value) && isNumOrNull(r.prevYear)
          && isNumOrNull(r.market) && strFields(r.text, ['value', 'prevYear', 'yoy', 'market'])),
      'homestay-trend': m => isStr(m.metric) && isStr(m.unit) && okSeries(m.series) && okAxis(m.axis)
        && strFields(m.latest, ['key', 'labelText'])
        && all(m.points, p => isObj(p) && isStr(p.key) && isNumOrNull(p.value) && isNumOrNull(p.prevYear)
          && strFields(p.text, ['value', 'prevYear'])),
      'homestay-communities': m => isStr(m.sort) && isStr(m.order) && isNum(m.matched) && okAxis(m.axis)
        && all(m.rows, r => isObj(r) && isStr(r.key) && isStr(r.name) && isStr(r.districtId) && isNum(r.listings)
          && isNumOrNull(r.bar) && strFields(r.text, ['bar', 'occupancy', 'prevYear', 'yoy', 'listings'])),
      'homestay-ask': m => isStr(m.mode) && isStr(m.answerText) && all(m.sqls, isStr)
        && typeof m.degraded === 'boolean' && isStr(m.degradeText)
        && (m.table === null || (isObj(m.table) && all(m.table.columns, isStr) && all(m.table.rows, isArr)
          && isNum(m.table.rowCount) && typeof m.table.truncated === 'boolean'))
        && (m.chart === null || (isObj(m.chart) && isStr(m.chart.labelColumn) && isStr(m.chart.valueColumn) && okAxis(m.chart.axis)
          && all(m.chart.bars, b => isObj(b) && isStr(b.key) && isStr(b.label) && isNumOrNull(b.value) && isStr(b.text)))),
    }

    /** @returns the meta when it satisfies the v2 contract for this tool, else null. */
    function readMeta(meta, toolName) {
      try {
        if (!okEnvelope(meta)) return null
        const want = KIND_OF_TOOL[toolName]
        if (want && meta.kind !== want) return null
        const check = VALIDATORS[meta.kind]
        return check && check(meta) ? meta : null
      } catch { return null }
    }

    function textOf(block) {
      const content = isArr(block?.content) ? block.content : []
      return content.filter(b => b && b.type === 'text' && isStr(b.text)).map(b => b.text).join('\n')
    }

    const CODE_RE = /\[(E_HOMESTAY_[A-Z]+)\]/
    function errorCode(block, text) {
      const structured = block?.error?.code
      if (isStr(structured) && structured) return structured
      const m = CODE_RE.exec(text)
      return m ? m[1] : null
    }

    function readArgs(block) {
      try {
        const raw = block?.argsRaw ?? block?.call?.argsRaw
        const v = isStr(raw) ? JSON.parse(raw) : null
        return isObj(v) ? v : null
      } catch { return null }
    }

    // ---- 卡片导出：window.__cardExport() ----
    // 最近一张渲染成功的卡片的结构化数据，字段与工具返回同源：
    //   tool  工具名；params 这次调用的参数；rows[] 图上的行 {key, label, value}。
    // value 是图上的机器值（比例 0–1 小数、金额与评分取原值），label 是卡片上该行显示的文字。
    // 还没出过卡片时返回 null；不改变任何显示，也不发请求。
    const shownLabel = (name, shown) => (isStr(name) && name && name !== shown ? `${name} ${shown}` : shown)
    function cardRows(meta) {
      if (meta.kind === 'homestay-compare') {
        return meta.rows.map(r => ({ key: r.key, label: shownLabel(r.name, r.text.value), value: r.value }))
      }
      if (meta.kind === 'homestay-trend') {
        return meta.points.map(p => ({ key: p.key, label: shownLabel(p.key, p.text.value), value: p.value }))
      }
      if (meta.kind === 'homestay-communities') {
        return meta.rows.map(r => ({ key: r.key, label: shownLabel(r.name, r.text.bar), value: r.bar }))
      }
      if (meta.kind === 'homestay-ask') {
        return (meta.chart ? meta.chart.bars : []).map(b => ({ key: b.key, label: shownLabel(b.label, b.text), value: b.value }))
      }
      return []
    }
    let lastCard = null // 最近一张卡片；换会话/刷新后重新开始
    function rememberCard(toolName, params, meta) {
      lastCard = { tool: toolName, params: params || {}, rows: cardRows(meta) }
    }
    try {
      window.__cardExport = () => (lastCard === null ? null : JSON.parse(JSON.stringify(lastCard)))
    } catch { /* 没有 window 的环境（非浏览器）跳过，不影响渲染 */ }

    const seriesLabel = (series, key, dflt) => {
      const s = isArr(series) ? series.find(x => x && x.key === key) : null
      return s && isStr(s.label) ? s.label : dflt
    }
    const hasSeries = (series, key) => isArr(series) && series.some(x => x && x.key === key)
    // 现成的变化率串自带正负号，按符号给颜色：这里不做减法。
    const signColor = t => (!isStr(t) ? 'var(--dsw-alias-label-secondary)'
      : t.startsWith('+') ? C.up : (t.startsWith('-') || t.startsWith('\u2212')) ? C.down : 'var(--dsw-alias-label-secondary)')

    // ---- shared pieces ----
    function Shell({ state, kind, children }) {
      return h('div', { style: S.card, 'data-homestay-card': state, 'data-kind': kind }, children)
    }
    function Head({ title, subtitle, extra, toggle }) {
      return h('div', { style: S.head },
        h('span', { style: S.title, 'data-hs-title': '' }, title),
        isStr(subtitle) ? h('span', { style: S.sub, title: subtitle, 'data-hs-subtitle': '' }, subtitle) : null,
        extra || null,
        toggle || null)
    }
    function Foot({ text }) {
      return isStr(text) ? h('div', { style: S.foot, 'data-hs-foot': '' }, text) : null
    }
    function Toggle({ disclosure, open, closed }) {
      return h('button', {
        type: 'button', style: S.toggle, 'data-hs-toggle': '',
        'aria-expanded': disclosure.expanded ? 'true' : 'false', onClick: disclosure.toggle,
      }, disclosure.expanded ? open : closed)
    }
    function Legend({ items }) {
      return h('div', { style: S.legend }, items.map(it => h('span', { key: it.key },
        h('i', { style: S.sw(it.color, it.line) }), it.label)))
    }
    /** columns: [{label, left?}]; rows: [{key, cells: [string]}] */
    function Table({ columns, rows }) {
      return h('div', { style: S.tableWrap },
        h('table', { style: S.table, 'data-hs-table': '' },
          h('thead', null, h('tr', null, columns.map((c, i) => h('th', { key: i, style: c.left ? { ...S.th, textAlign: 'left' } : S.th }, c.label)))),
          h('tbody', null, rows.map((r, i) => h('tr', { key: i, 'data-hs-row': '', 'data-key': r.key },
            r.cells.map((cell, j) => h('td', { key: j, style: columns[j] && columns[j].left ? { ...S.td, textAlign: 'left' } : S.td }, cell)))))))
    }
    /** 折叠区：只用 CSS 隐藏，[data-hs-table]/[data-hs-row] 仍留在 DOM 里。 */
    function Fold({ open, children }) {
      return h('div', { style: { display: open ? 'block' : 'none' } }, children)
    }
    const mark = (series, key) => ({ 'data-hs-mark': '', 'data-series': series, 'data-key': key })
    const label = (key, field) => ({ 'data-hs-label': '', 'data-key': key, 'data-field': field })

    // ---- 对比：分组柱状图 ----
    function CompareChart({ m }) {
      const W = 680, H = 270, padL = 52, padR = 10, padT = 14, padB = 46
      const plotW = W - padL - padR, plotH = H - padT - padB
      const { min, max } = m.axis
      const y = v => padT + ((max - v) / ((max - min) || 1)) * plotH
      const base = min <= 0 && max >= 0 ? 0 : min
      const yb = y(base)
      const n = m.rows.length
      const gw = n > 0 ? plotW / n : plotW
      const bw = Math.min(22, gw * 0.3)
      const withMarket = hasSeries(m.series, 'market')
      const kids = []
      m.axis.ticks.forEach((t, i) => {
        kids.push(h('line', { key: `g${i}`, x1: padL, x2: W - padR, y1: y(t.value), y2: y(t.value), style: { stroke: 'var(--dsw-alias-border-l1)' }, strokeWidth: 0.6 }))
        kids.push(h('text', { key: `gt${i}`, x: padL - 6, y: y(t.value) + 4, textAnchor: 'end', style: AXIS_TEXT }, t.text))
      })
      const bar = (series, key, v, x, fill) => h('rect', {
        key: series, ...mark(series, key), x, y: Math.min(y(v), yb), width: bw, height: Math.abs(yb - y(v)), fill,
      })
      m.rows.forEach((r, i) => {
        const cx = padL + gw * i + gw / 2
        const g = []
        if (isNum(r.value)) g.push(bar('cur', r.key, r.value, cx - bw - 1, C.cur))
        if (isNum(r.prevYear)) g.push(bar('prev', r.key, r.prevYear, cx + 1, C.prev))
        if (withMarket && isNum(r.market)) {
          g.push(h('line', {
            key: 'market', ...mark('market', r.key), x1: cx - bw - 5, x2: cx + bw + 5, y1: y(r.market), y2: y(r.market),
            stroke: C.market, strokeWidth: 2.2, strokeDasharray: '4 2',
          }))
        }
        g.push(h('text', { key: 'n', x: cx, y: H - padB + 16, textAnchor: 'middle', style: NAME_TEXT }, r.name))
        g.push(h('text', {
          key: 'y', ...label(r.key, 'yoy'), x: cx, y: H - padB + 32, textAnchor: 'middle',
          style: { fontSize: 11, fontWeight: 500, fill: signColor(r.text.yoy) },
        }, r.text.yoy))
        kids.push(h('g', { key: `d${i}` }, g))
      })
      if (min <= 0 && max >= 0) {
        kids.push(h('line', { key: 'zero', 'data-hs-axis': 'zero', x1: padL, x2: W - padR, y1: y(0), y2: y(0), style: { stroke: 'var(--dsw-alias-border-l2)' }, strokeWidth: 1 }))
      }
      return h('svg', { viewBox: `0 0 ${W} ${H}`, width: '100%', style: S.svg, role: 'img', 'aria-label': m.title }, kids)
    }

    function CompareBody({ m, disclosure }) {
      const withMarket = hasSeries(m.series, 'market')
      const curL = seriesLabel(m.series, 'cur', L('本期', 'Current'))
      const prevL = seriesLabel(m.series, 'prev', L('上年同期', 'Prior year'))
      const mktL = seriesLabel(m.series, 'market', L('市场基准', 'Market'))
      const legend = [{ key: 'cur', label: curL, color: C.cur }, { key: 'prev', label: prevL, color: C.prev }]
      if (withMarket) legend.push({ key: 'market', label: mktL, color: C.market, line: true })
      const cols = [{ label: L('区', 'District'), left: true }, { label: curL }, { label: prevL }, { label: L('同比', 'YoY') }]
      if (withMarket) cols.push({ label: mktL })
      const rows = m.rows.map(r => ({
        key: r.key,
        cells: [r.name, r.text.value, r.text.prevYear, r.text.yoy].concat(withMarket ? [r.text.market] : []),
      }))
      return h(Shell, { state: 'chart', kind: m.kind },
        h(Head, { title: m.title, subtitle: m.subtitle, toggle: h(Toggle, { disclosure, open: L('收起数据', 'Hide data'), closed: L('查看数据', 'Show data') }) }),
        h(Legend, { items: legend }),
        h(CompareChart, { m }),
        h(Fold, { open: disclosure.expanded }, h(Table, { columns: cols, rows })),
        h(Foot, { text: m.footnote }))
    }

    // ---- 走势：双折线 ----
    function TrendChart({ m }) {
      const W = 680, H = 260, padL = 52, padR = 16, padT = 14, padB = 34, inner = 12
      const plotW = W - padL - padR, plotH = H - padT - padB
      const { min, max } = m.axis
      const y = v => padT + ((max - v) / ((max - min) || 1)) * plotH
      const n = m.points.length
      const span = plotW - 2 * inner
      const x = i => padL + inner + (n > 1 ? (i * span) / (n - 1) : span / 2)
      const kids = []
      m.axis.ticks.forEach((t, i) => {
        kids.push(h('line', { key: `g${i}`, x1: padL, x2: W - padR, y1: y(t.value), y2: y(t.value), style: { stroke: 'var(--dsw-alias-border-l1)' }, strokeWidth: 0.6 }))
        kids.push(h('text', { key: `gt${i}`, x: padL - 6, y: y(t.value) + 4, textAnchor: 'end', style: AXIS_TEXT }, t.text))
      })
      const sparse = n > 12
      m.points.forEach((p, i) => {
        if (sparse && (i & 1) === 1) return
        kids.push(h('text', { key: `mx${i}`, x: x(i), y: H - padB + 16, textAnchor: 'middle', style: AXIS_TEXT }, p.key))
      })
      const lineOf = (series, field, color, dash) => {
        const segs = []
        let cur = []
        m.points.forEach((p, i) => {
          if (isNum(p[field])) cur.push(`${x(i)},${y(p[field])}`)
          else if (cur.length) { segs.push(cur); cur = [] }
        })
        if (cur.length) segs.push(cur)
        segs.forEach((pts, j) => kids.push(h('polyline', {
          key: `${series}-l${j}`, points: pts.join(' '), fill: 'none', stroke: color, strokeWidth: 2,
          strokeDasharray: dash || undefined, strokeLinejoin: 'round',
        })))
      }
      lineOf('prev', 'prevYear', C.prev, '5 3')
      lineOf('cur', 'value', C.cur)
      const dots = (series, field, color) => m.points.forEach((p, i) => {
        if (!isNum(p[field])) return
        kids.push(h('circle', { key: `${series}-c${i}`, ...mark(series, p.key), cx: x(i), cy: y(p[field]), r: 3, fill: color }))
      })
      dots('prev', 'prevYear', C.prev)
      dots('cur', 'value', C.cur)
      return h('svg', { viewBox: `0 0 ${W} ${H}`, width: '100%', style: S.svg, role: 'img', 'aria-label': m.title }, kids)
    }

    function TrendBody({ m, disclosure }) {
      const curL = seriesLabel(m.series, 'cur', L('本期', 'Current'))
      const prevL = seriesLabel(m.series, 'prev', L('上年同月', 'Prior year'))
      const cols = [{ label: L('月份', 'Month'), left: true }, { label: curL }, { label: prevL }]
      const rows = m.points.map(p => ({ key: p.key, cells: [p.key, p.text.value, p.text.prevYear] }))
      return h(Shell, { state: 'chart', kind: m.kind },
        h(Head, {
          title: m.title, subtitle: m.subtitle,
          extra: h('span', { style: S.latest, ...label(m.latest.key, 'latest') }, m.latest.labelText),
          toggle: h(Toggle, { disclosure, open: L('收起数据', 'Hide data'), closed: L('查看数据', 'Show data') }),
        }),
        h(Legend, { items: [{ key: 'cur', label: curL, color: C.cur, line: true }, { key: 'prev', label: prevL, color: C.prev, line: true }] }),
        h(TrendChart, { m }),
        h(Fold, { open: disclosure.expanded }, h(Table, { columns: cols, rows })),
        h(Foot, { text: m.footnote }))
    }

    // ---- horizontal bars: communities (5.3) and ask (5.4) ----
    /** items: [{key, name, value (number|null), text}] */
    /** 在 `avail` 像素里放下 n 根柱子的行高，取值在 minRow 与 24 之间。 */
    const hbarRow = (n, avail, minRow) => clampInt((avail - HB_PAD) / Math.max(1, n), minRow, 24)
    const hbarHeight = (n, rowH) => HB_PAD + Math.max(1, n) * rowH
    function HBars({ items, axis, colorOf, title, rowH = 24 }) {
      const W = 680, nameW = 124, labelPad = 58, padR = 8, padT = 18, padB = 4
      const barH = Math.min(14, rowH - 4)
      const fs = rowH < 14 ? 10 : 11
      const n = items.length
      const H = padT + Math.max(1, n) * rowH + padB
      const { min, max } = axis
      const x0 = nameW + labelPad, x1 = W - padR - labelPad
      const x = v => x0 + ((v - min) / ((max - min) || 1)) * (x1 - x0)
      const base = min <= 0 && max >= 0 ? 0 : min
      const xb = x(base)
      const kids = []
      axis.ticks.forEach((t, i) => {
        kids.push(h('line', { key: `g${i}`, x1: x(t.value), x2: x(t.value), y1: padT - 4, y2: H - padB, style: { stroke: 'var(--dsw-alias-border-l1)' }, strokeWidth: 0.6 }))
        kids.push(h('text', { key: `gt${i}`, x: x(t.value), y: padT - 8, textAnchor: 'middle', style: AXIS_TEXT }, t.text))
      })
      items.forEach((it, i) => {
        const cy = padT + i * rowH + rowH / 2
        kids.push(h('text', { key: `n${i}`, x: nameW - 6, y: cy + 4, textAnchor: 'end', style: { ...NAME_TEXT, fontSize: fs } }, it.name))
        if (!isNum(it.value)) return
        const xv = x(it.value)
        kids.push(h('rect', {
          key: `b${i}`, ...mark('bar', it.key), x: Math.min(xv, xb), y: cy - barH / 2, width: Math.abs(xv - xb), height: barH,
          fill: colorOf(it),
        }))
        const neg = it.value < base
        kids.push(h('text', {
          key: `l${i}`, ...label(it.key, 'bar'), x: neg ? xv - 4 : xv + 4, y: cy + 4, textAnchor: neg ? 'end' : 'start',
          style: { fontSize: fs, fill: 'var(--dsw-alias-label-primary)' },
        }, it.text))
      })
      if (min <= 0 && max >= 0) {
        kids.push(h('line', { key: 'zero', 'data-hs-axis': 'zero', x1: x(0), x2: x(0), y1: padT - 4, y2: H - padB, style: { stroke: 'var(--dsw-alias-label-secondary)' }, strokeWidth: 1 }))
      }
      return h('svg', { viewBox: `0 0 ${W} ${H}`, width: '100%', style: S.svg, role: 'img', 'aria-label': title }, kids)
    }

    // Default-state height (v4.2): chrome 55 + bars (22 + n*rowH) [+ count note 22] <= 360.
    // n<=10: rowH 24 -> 55+262+22 = 339. n=20: note moves into the fold, rowH 14 -> 55+302 = 357.
    function CommunitiesBody({ m, disclosure }) {
      const signed = m.axis.min < 0
      const items = m.rows.map(r => ({ key: r.key, name: r.name, value: r.bar, text: r.text.bar }))
      const colorOf = it => (!signed ? C.bar : it.value < 0 ? C.down : C.up)
      const cols = [
        { label: L('小区', 'Community'), left: true }, { label: L('区', 'District'), left: true }, { label: L('在线房源', 'Listings') },
        { label: L('本期', 'Current') }, { label: L('上年同期', 'Prior year') }, { label: L('同比', 'YoY') },
      ]
      const rows = m.rows.map(r => ({ key: r.key, cells: [r.name, r.districtId, r.text.listings, r.text.occupancy, r.text.prevYear, r.text.yoy] }))
      const countText = isStr(m.rowCountText) ? m.rowCountText : isObj(m.table) && isStr(m.table.rowCountText) ? m.table.rowCountText : null
      const n = items.length
      const noteFits = countText !== null && hbarHeight(n, 14) + NOTE <= BUDGET
      const rowH = hbarRow(n, BUDGET - (noteFits ? NOTE : 0), 14)
      const count = countText !== null ? h('div', { style: S.note }, countText) : null
      return h(Shell, { state: 'chart', kind: m.kind },
        h(Head, { title: m.title, subtitle: m.subtitle, toggle: h(Toggle, { disclosure, open: L('收起数据', 'Hide data'), closed: L('查看数据', 'Show data') }) }),
        n ? h(HBars, { items, axis: m.axis, colorOf, title: m.title, rowH }) : h('div', { style: S.note }, L('没有符合条件的小区', 'No matching communities')),
        noteFits ? count : null,
        h(Fold, { open: disclosure.expanded }, h(Table, { columns: cols, rows }), noteFits ? null : count),
        h(Foot, { text: m.footnote }))
    }

    // Default-state height (v4.2), estimated from fixed CSS line heights:
    //   chrome 55 + answer (8 + lines*19) + degrade 20 + chart (22 + n*rowH) + table (52 + rows*24) <= 360.
    // 1) everything fits -> table shown; 2) else the table goes into the fold; 3) still too tall ->
    // chart rows shrink (>= 10px) leaving room for up to 4 answer lines, then the answer is clamped to the
    // lines that fit and its full text is shown when the fold opens (CSS line-clamp only).
    function AskBody({ m, disclosure }) {
      const refused = m.mode === 'refused'
      const open = disclosure.expanded
      const fixed = m.degraded && m.degradeText ? 20 : 0
      // 画不画条形由 index.js 决定：有 chart 就画。
      const nBars = !refused && m.chart ? m.chart.bars.length : 0
      // Optional ready-made value-column caption above the bars (index.js chart.valueLabel); 18px line.
      const valueLabel = nBars && isStr(m.chart.valueLabel) && m.chart.valueLabel ? m.chart.valueLabel : null
      const VL = valueLabel ? 18 : 0
      const tableH = !refused && m.table ? TABLE_EXTRA + m.table.rows.length * TABLE_ROW : 0
      const lines = answerLines(m.answerText)
      const ansFull = ANSWER_PAD + lines * ANSWER_LINE
      // ASK_SLACK: extra 8px margin for the ask card only (lead: all ask variants <= 352px), because
      // its answer height is an estimate (wrapped-line count), unlike the fixed-geometry charts.
      const ASK_SLACK = 8
      const avail = BUDGET - fixed - VL - ASK_SLACK
      let rowH = 24
      let tableFolded = false
      let clampLines = 0
      if (ansFull + (nBars ? hbarHeight(nBars, 24) : 0) + tableH > avail) {
        tableFolded = tableH > 0
        if (nBars && ansFull + hbarHeight(nBars, 24) > avail) {
          rowH = hbarRow(nBars, avail - Math.min(ansFull, ANSWER_PAD + 4 * ANSWER_LINE), 10)
        }
        const chartH = nBars ? hbarHeight(nBars, rowH) : 0
        const fit = Math.max(1, Math.floor((avail - chartH - ANSWER_PAD) / ANSWER_LINE))
        if (lines > fit) clampLines = fit
      }
      const foldable = !refused && (m.sqls.length > 0 || tableFolded) || clampLines > 0
      const toggle = foldable ? h(Toggle, { disclosure, open: L('收起详情', 'Hide details'), closed: L('查看详情', 'Show details') }) : null
      const parts = [h(Head, { key: 'head', title: m.title, subtitle: m.subtitle, toggle })]
      parts.push(h('div', { key: 'answer', style: clampLines && !open ? { ...S.answer, ...S.answerClamp(clampLines) } : S.answer }, m.answerText))
      if (m.degraded && m.degradeText) parts.push(h('div', { key: 'degrade', style: S.degrade }, m.degradeText))
      if (!refused) {
        if (valueLabel) {
          parts.push(h('div', {
            key: 'valueLabel', ...label(m.chart.valueColumn, 'valueLabel'), title: valueLabel,
            style: { color: 'var(--dsw-alias-label-secondary)', fontSize: 11.5, lineHeight: '16px', marginTop: 2, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' },
          }, valueLabel))
        }
        if (nBars) {
          const items = m.chart.bars.map(b => ({ key: b.key, name: b.label, value: b.value, text: b.text }))
          parts.push(h(HBars, { key: 'chart', items, axis: m.chart.axis, colorOf: () => C.bar, title: m.title, rowH }))
        }
        if (m.table) {
          const cols = m.table.columns.map((c, i) => ({ label: c, left: i === 0 }))
          const rows = m.table.rows.map((r, i) => ({ key: String(i), cells: r.map(c => (isStr(c) ? c : '—')) }))
          // 行数文案由 index.js 算好；没有就不显示行数。
          const count = isStr(m.table.rowCountText) ? h('div', { style: S.note }, m.table.rowCountText) : null
          parts.push(h(Fold, { key: 'table', open: !tableFolded || open }, h(Table, { columns: cols, rows }), count))
        }
        if (m.sqls.length) {
          parts.push(h(Fold, { key: 'sql', open }, m.sqls.map((q, i) => h('pre', { key: `sql${i}`, style: S.sql }, q))))
        }
      }
      parts.push(h(Foot, { key: 'foot', text: m.footnote }))
      return h(Shell, { state: 'chart', kind: m.kind }, parts)
    }

    const BODIES = {
      'homestay-compare': CompareBody,
      'homestay-trend': TrendBody,
      'homestay-communities': CommunitiesBody,
      'homestay-ask': AskBody,
    }

    function Fallback({ toolName, kind, block }) {
      return h(Shell, { state: 'fallback', kind },
        h(Head, { title: (TOOL_TITLE[toolName] || TOOL_TITLE.homestay_compare)() }),
        h('pre', { style: S.pre }, textOf(block)))
    }

    // 渲染体抛异常时不能把槽位条目弄成空白：退回显示工具文本。
    class Boundary extends React.Component {
      constructor(props) { super(props); this.state = { failed: false } }
      static getDerivedStateFromError() { return { failed: true } }
      render() { return this.state.failed ? h(Fallback, this.props.fallback) : this.props.children }
    }

    function HomestayView(props) {
      const { phase, block } = props
      const disclosure = props.useDisclosure()
      // 结果阶段的 block 上没有 argsRaw（参数在 call.argsRaw 里，会话窗口截断时连它也没有），
      // 所以开始渲染时把参数记下来给 __cardExport 兜底。
      const argsRef = React.useRef(null)
      const toolName = isStr(props.toolName) && props.toolName ? props.toolName : (isStr(block?.name) ? block.name : '')
      const title = (TOOL_TITLE[toolName] || TOOL_TITLE.homestay_compare)()
      if (phase !== 'result') {
        const args = phase === 'start' ? readArgs(block) : null
        if (args) argsRef.current = args
        const summary = args
          ? Object.keys(args).filter(k => args[k] !== null && typeof args[k] !== 'object').map(k => `${k}=${args[k]}`).join(' · ')
          : ''
        return h(Shell, { state: 'pending', kind: toolName },
          h('div', { style: S.head },
            h('span', { style: S.title, 'data-hs-title': '' }, title),
            summary ? h('span', { style: S.sub }, summary) : null,
            args ? h('span', { style: S.sub }, L('查询中…', 'querying…')) : null))
      }
      if (block?.isError) {
        const text = textOf(block)
        const code = errorCode(block, text)
        return h(Shell, { state: 'error', kind: toolName },
          h('div', { style: S.head },
            h('span', { style: S.title, 'data-hs-title': '' }, title),
            code ? h('span', { style: S.code }, code) : null),
          h('div', { style: S.error }, text || L('调用失败', 'Call failed')))
      }
      const meta = readMeta(block?.meta, toolName)
      const fallbackKind = isObj(block?.meta) && isStr(block.meta.kind) ? block.meta.kind : toolName
      const fb = { toolName, kind: fallbackKind, block }
      if (meta === null) return h(Fallback, fb)
      // 参数优先取结果块回填的 call.argsRaw；会话窗口截断拿不到时用开始阶段记下的那份。
      rememberCard(toolName, readArgs(block) ?? argsRef.current, meta)
      return h(Boundary, { fallback: fb }, h(BODIES[meta.kind], { m: meta, disclosure }))
    }

    return {
      inject: ['slots'],
      apply(ctx) {
        // One inject per key, each in the exact documented form (dsh-client-ui-tool README).
        for (const key of TOOLS) {
          ctx.slots.inject('tool.call.toolview', () => ctx.slots.register({ name: 'tool.call.toolview', key }, HomestayView))
        }
      },
    }
  },
})
