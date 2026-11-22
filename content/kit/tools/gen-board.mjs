// gstack-sprint 看板生成器
// 用法: node gen-board.mjs <board.json> [输出目录]
// 输入单一数据源 board.json，输出 BOARD.html（人看）+ BOARD.md（agent/搜索用）。
// 零依赖，自包含，不联网。

import { readFileSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'

const [, , jsonPath, outDirArg] = process.argv
if (!jsonPath) {
  console.error('usage: node gen-board.mjs <board.json> [outDir]')
  process.exit(2)
}

const src = resolve(jsonPath)
const outDir = outDirArg ? resolve(outDirArg) : dirname(src)
const b = JSON.parse(readFileSync(src, 'utf8'))

const esc = (s = '') =>
  String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]))

const rings = Array.isArray(b.rings) ? b.rings : []
const waiting = Array.isArray(b.waiting) ? b.waiting : []
const auto = Array.isArray(b.auto) ? b.auto : []
const decisions = Array.isArray(b.decisions) ? b.decisions : []
const precedents = Array.isArray(b.precedents) ? b.precedents : []
const cur = b.current ?? {}

const formLabel = b.formLabel ?? { A: '绿地', B: '升级', C: '重构' }[b.form] ?? '未定'
const doneCount = rings.filter((r) => r.state === 'done').length
const pct = rings.length ? Math.round((doneCount / rings.length) * 100) : 0

const stateIcon = (s) =>
  ({ done: '✓', active: '▶', fail: '✕', stale: '⟳', pending: '·' }[s] ?? '·')
const stateText = (s) =>
  ({ done: '完成', active: '进行中', fail: '未过', stale: '待重验', pending: '未开始' }[s] ?? '未开始')

function mdTable(headers, rows) {
  const head = `| ${headers.join(' | ')} |`
  const sep = `|${headers.map(() => '---').join('|')}|`
  const body = rows.map((r) => `| ${r.map((c) => String(c ?? '').replace(/\|/g, '\\|')).join(' | ')} |`).join('\n')
  return [head, sep, body].join('\n')
}

// ---------- BOARD.md ----------
const md = []
md.push(`# 看板 · ${b.project ?? '未命名'} · ${b.run ?? ''}`)
md.push('')
md.push(`更新：${b.updated ?? ''}`)
md.push('')
md.push('## 现在在哪')
md.push(
  `形态：${b.form ?? '?'} ${formLabel} ｜ 当前：环 ${cur.ring ?? '—'} ${cur.name ?? ''} ｜ 门禁：${cur.gate ?? '—'} ｜ 已用：${cur.elapsed ?? '—'} ｜ 下一步：${cur.next ?? '—'}`,
)
md.push(`进度：${doneCount}/${rings.length} 环（${pct}%）`)
md.push('')
md.push('## 环进度')
md.push(
  mdTable(
    ['环', '状态', '门禁', '用时', '记录'],
    rings.map((r) => [`${r.id ?? ''} ${r.name ?? ''}`, `${stateIcon(r.state)} ${stateText(r.state)}`, r.gate ?? '—', r.duration ?? '—', r.record ?? '—']),
  ),
)
md.push('')
md.push('## ⏸ 等你（必须决策，流程停在这）')
if (waiting.length === 0) md.push('无')
for (const w of waiting) {
  md.push(`### ${w.id ?? ''} — ${w.question ?? ''}`)
  for (const [i, o] of (w.options ?? []).entries()) md.push(`${String.fromCharCode(65 + i)}) ${o.label ?? ''}　代价：${o.cost ?? '—'}`)
  md.push(`推荐：${w.recommend ?? '—'}，因为 ${w.reason ?? '—'}`)
  md.push(`默认：${w.default ?? '—'}`)
  md.push('')
}
md.push('## ⚡ 我已按推荐执行（可否决）')
if (auto.length === 0) md.push('无')
for (const a of auto) md.push(`- ${a.id ?? ''}（环 ${a.ring ?? '?'}）${a.decision ?? ''}　依据：${a.reason ?? '—'}　重做成本：${a.redo ?? '—'}`)
md.push('')
md.push('## 决策台账')
md.push(
  mdTable(
    ['#', '环', '问题', '选择', '依据', '谁拍', '可否决'],
    decisions.map((d) => [d.id ?? '', d.ring ?? '', d.question ?? '', d.choice ?? '', d.evidence ?? '', d.who ?? '', d.vetoable ?? '']),
  ),
)
md.push('')
md.push('## 判例（可复用）')
if (precedents.length === 0) md.push('无')
for (const p of precedents) md.push(`- ${p.id ?? ''}：${p.rule ?? ''} —— 来自 ${p.from ?? '—'}`)
md.push('')

writeFileSync(join(outDir, 'BOARD.md'), md.join('\n'), 'utf8')

// ---------- BOARD.html ----------
const ringCells = rings
  .map((r) => {
    const cls = `ring ${r.state ?? 'pending'}`
    return `<li class="${cls}">
      <span class="dot">${esc(stateIcon(r.state))}</span>
      <span class="rid">${esc(r.id ?? '')}</span>
      <span class="rname">${esc(r.name ?? '')}</span>
      <span class="rgate">${esc(r.gate ?? '—')}</span>
      <span class="rtime">${esc(r.duration ?? '')}</span>
    </li>`
  })
  .join('\n')

const waitingHtml = waiting.length
  ? waiting
      .map(
        (w) => `<article class="card wait">
        <header><span class="tag">${esc(w.id ?? '')}</span><h3>${esc(w.question ?? '')}</h3></header>
        <ul class="opts">${(w.options ?? [])
          .map((o, i) => `<li><b>${String.fromCharCode(65 + i)})</b> ${esc(o.label ?? '')}<span class="cost">代价：${esc(o.cost ?? '—')}</span></li>`)
          .join('')}</ul>
        <p class="rec"><b>推荐 ${esc(w.recommend ?? '—')}</b>，因为 ${esc(w.reason ?? '—')}</p>
        <p class="dflt">默认：${esc(w.default ?? '—')}</p>
      </article>`,
      )
      .join('\n')
  : '<p class="empty">无。流程没有卡在你这里。</p>'

const autoHtml = auto.length
  ? auto
      .map(
        (a) => `<article class="card auto">
        <header><span class="tag">${esc(a.id ?? '')}</span><h3>${esc(a.decision ?? '')}</h3></header>
        <p>环 ${esc(a.ring ?? '?')}　依据：${esc(a.reason ?? '—')}</p>
        <p class="redo">重做成本：${esc(a.redo ?? '—')}　→ 你说不行我就改</p>
      </article>`,
      )
      .join('\n')
  : '<p class="empty">无。</p>'

const decisionRows = decisions
  .map(
    (d) => `<tr>
      <td class="mono">${esc(d.id ?? '')}</td>
      <td>${esc(d.ring ?? '')}</td>
      <td>${esc(d.question ?? '')}</td>
      <td><b>${esc(d.choice ?? '')}</b></td>
      <td class="muted">${esc(d.evidence ?? '')}</td>
      <td>${esc(d.who ?? '')}</td>
      <td>${esc(d.vetoable ?? '')}</td>
    </tr>`,
  )
  .join('\n')

const precedentHtml = precedents.length
  ? precedents.map((p) => `<li><span class="mono">${esc(p.id ?? '')}</span> ${esc(p.rule ?? '')}<span class="muted">　来自 ${esc(p.from ?? '—')}</span></li>`).join('\n')
  : '<li class="empty">无</li>'

const html = `<!doctype html>
<html lang="zh-CN">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>看板 · ${esc(b.project ?? '')}</title>
<style>
  :root{
    --bg:#0f1216; --panel:#171c22; --line:#252d36; --fg:#e6e9ee; --muted:#8b95a3;
    --ok:#3fb950; --run:#58a6ff; --wait:#f85149; --auto:#d29922; --idle:#39414b;
  }
  *{box-sizing:border-box}
  body{margin:0;padding:32px;background:var(--bg);color:var(--fg);
    font:15px/1.6 "Segoe UI",-apple-system,"Microsoft YaHei",sans-serif}
  .wrap{max-width:1080px;margin:0 auto}
  h1{font-size:20px;margin:0 0 4px;font-weight:600}
  h2{font-size:13px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);
    margin:32px 0 12px;font-weight:600}
  .meta{color:var(--muted);font-size:13px}
  .badge{display:inline-block;padding:2px 10px;border-radius:999px;font-size:12px;
    border:1px solid var(--line);margin-right:8px}
  .status{display:flex;flex-wrap:wrap;gap:24px;margin:20px 0 8px;padding:16px 20px;
    background:var(--panel);border:1px solid var(--line);border-radius:10px}
  .status div{font-size:13px;color:var(--muted)}
  .status b{display:block;font-size:16px;color:var(--fg);font-weight:600;margin-top:2px}
  .bar{display:block;width:100%;height:6px;background:var(--idle);border-radius:3px;overflow:hidden;margin:8px 0 0}
  .bar>i{display:block;height:100%;background:var(--ok);width:${pct}%}
  h2 .sq{display:inline-block;width:8px;height:8px;border-radius:2px;margin-right:8px;vertical-align:middle}
  h2 .sq.wait{background:var(--wait)} h2 .sq.auto{background:var(--auto)}
  ul.rings{list-style:none;padding:0;margin:0;display:grid;
    grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px}
  ul.rings li{display:flex;flex-direction:column;gap:2px;padding:10px 12px;
    background:var(--panel);border:1px solid var(--line);border-radius:8px;font-size:13px}
  ul.rings li.done{border-color:rgba(63,185,80,.45)}
  ul.rings li.active{border-color:var(--run);box-shadow:0 0 0 1px var(--run) inset}
  ul.rings li.fail{border-color:var(--wait)}
  .ring .dot{font-size:14px}
  .done .dot{color:var(--ok)} .active .dot{color:var(--run)}
  .fail .dot{color:var(--wait)} .pending .dot{color:var(--idle)}
  ul.rings li.stale{border-color:rgba(210,153,34,.45)}
  .stale .dot{color:var(--auto)}
  .rid{font-family:ui-monospace,Consolas,monospace;color:var(--muted);font-size:11px}
  .rname{font-weight:600}
  .rgate,.rtime{color:var(--muted);font-size:12px}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:10px;
    padding:16px 18px;margin:10px 0}
  .card.wait{border-left:3px solid var(--wait)}
  .card.auto{border-left:3px solid var(--auto)}
  .card header{display:flex;align-items:baseline;gap:10px}
  .card h3{font-size:15px;margin:0;font-weight:600}
  .tag{font-family:ui-monospace,Consolas,monospace;font-size:12px;color:var(--muted);
    border:1px solid var(--line);border-radius:5px;padding:1px 6px}
  ul.opts{list-style:none;padding:0;margin:12px 0 8px}
  ul.opts li{padding:6px 0;border-top:1px dashed var(--line)}
  .cost{color:var(--muted);margin-left:10px;font-size:13px}
  .rec{margin:8px 0 2px;color:var(--fg)}
  .dflt{margin:0;color:var(--muted);font-size:13px}
  .redo{margin:6px 0 0;color:var(--auto);font-size:13px}
  .empty{color:var(--muted);font-size:14px;margin:6px 0}
  table{width:100%;border-collapse:collapse;font-size:13px;background:var(--panel);
    border:1px solid var(--line);border-radius:10px;overflow:hidden}
  th,td{text-align:left;padding:9px 12px;border-bottom:1px solid var(--line);vertical-align:top}
  th{color:var(--muted);font-weight:600;font-size:12px;letter-spacing:.04em}
  tr:last-child td{border-bottom:none}
  .mono{font-family:ui-monospace,Consolas,monospace}
  .muted{color:var(--muted)}
  ul.prev{list-style:none;padding:0;margin:0;font-size:13px}
  ul.prev li{padding:8px 0;border-bottom:1px dashed var(--line)}
  ul.prev li:last-child{border-bottom:none}
  footer{margin-top:36px;color:var(--muted);font-size:12px}
</style>
<div class="wrap">
  <h1>${esc(b.project ?? '未命名')}</h1>
  <p class="meta">
    <span class="badge">形态 ${esc(b.form ?? '?')} ${esc(formLabel)}</span>
    <span class="badge">轮次 ${esc(b.run ?? '—')}</span>
    更新 ${esc(b.updated ?? '—')}
  </p>

  <div class="status">
    <div>当前<b>环 ${esc(cur.ring ?? '—')} ${esc(cur.name ?? '')}</b></div>
    <div>门禁<b>${esc(cur.gate ?? '—')}</b></div>
    <div>已用<b>${esc(cur.elapsed ?? '—')}</b></div>
    <div>下一步<b>${esc(cur.next ?? '—')}</b></div>
    <div>进度<b>${doneCount}/${rings.length}（${pct}%）</b><span class="bar"><i></i></span></div>
  </div>

  <h2>环进度</h2>
  <ul class="rings">
${ringCells}
  </ul>

  <h2><span class="sq wait"></span>等你（必须决策，流程停在这）</h2>
  ${waitingHtml}

  <h2><span class="sq auto"></span>我已按推荐执行（可否决）</h2>
  ${autoHtml}

  <h2>决策台账</h2>
  <table>
    <thead><tr><th>#</th><th>环</th><th>问题</th><th>选择</th><th>依据</th><th>谁拍</th><th>可否决</th></tr></thead>
    <tbody>
${decisionRows || '<tr><td colspan="7" class="empty">无</td></tr>'}
    </tbody>
  </table>

  <h2>判例（可复用）</h2>
  <ul class="prev">
${precedentHtml}
  </ul>

  <footer>由 gen-board.mjs 从 board.json 生成 · 单一数据源，勿手改本文件</footer>
</div>
</html>
`

writeFileSync(join(outDir, 'BOARD.html'), html, 'utf8')
console.log(`wrote ${join(outDir, 'BOARD.md')}`)
console.log(`wrote ${join(outDir, 'BOARD.html')}`)
