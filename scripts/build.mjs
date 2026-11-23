// build.mjs —— 把 content/（教材同步镜像）渲染成纯静态站 dist/，并打下载包、离线包。
// 零框架：marked + 自写模板。站内链接一律相对路径。末尾自检，任何一项不绿则退出码 1。
import fs from 'node:fs'
import path from 'node:path'
import crypto from 'node:crypto'
import zlib from 'node:zlib'
import { fileURLToPath } from 'node:url'
import { marked } from 'marked'
import { load as yamlLoad } from 'js-yaml'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const CONTENT = path.join(ROOT, 'content')
const DIST = path.join(ROOT, 'dist')
const RELEASE = path.join(ROOT, 'release')
const BUILD_DIR = path.join(ROOT, '.build')
const SITE_NAME = '带 AI 团队写代码：从任务书到交付'
const SITE_SHORT = '带 AI 团队写代码'
const EXPECTED_PAGES = 17

const errors = []
const fail = (msg) => { errors.push(msg) }
const sha256 = (buf) => crypto.createHash('sha256').update(buf).digest('hex')
const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
const fmtBytes = (n) => n.toLocaleString('en-US')

// ───────────────────────── 白名单 / 黑名单（二次防线） ─────────────────────────
function globToRegex(g) {
  let out = ''
  for (let i = 0; i < g.length; i++) {
    const c = g[i]
    if (c === '*') {
      if (g[i + 1] === '*') {
        if (g[i + 2] === '/') { out += '(?:.*/)?'; i += 2 } else { out += '.*'; i += 1 }
      } else out += '[^/]*'
    } else if (c === '?') out += '[^/]'
    else out += c.replace(/[.+^${}()|[\]\\]/g, '\\$&')
  }
  return new RegExp('^' + out + '$')
}
function readPatterns(file) {
  return fs.readFileSync(file, 'utf8').split(/\r?\n/).map((s) => s.trim()).filter((s) => s && !s.startsWith('#'))
}
const whitelist = readPatterns(path.join(ROOT, 'scripts/whitelist.txt')).map((p) => ({ p, rx: globToRegex(p), hits: 0 }))
const blackRaw = readPatterns(path.join(ROOT, 'scripts/blacklist.txt'))
const blackExcept = blackRaw.filter((b) => b.startsWith('!')).map((b) => globToRegex(b.slice(1)))
const blacklist = blackRaw.filter((b) => !b.startsWith('!')).map((b) =>
  b.endsWith('/') ? { kind: 'dir', rx: globToRegex(b.slice(0, -1)) }
    : b.includes('/') ? { kind: 'path', rx: globToRegex(b) } : { kind: 'name', rx: globToRegex(b) })
function isBlacklisted(rel) {
  const segs = rel.split('/')
  let hit = false
  for (const b of blacklist) {
    if (b.kind === 'dir') { if (segs.slice(0, -1).some((s) => b.rx.test(s))) hit = true }
    else if (b.kind === 'path') { if (b.rx.test(rel)) hit = true }
    else if (b.rx.test(segs[segs.length - 1])) hit = true
  }
  if (hit && blackExcept.some((rx) => rx.test(rel))) return false
  return hit
}
function walk(dir, base = dir, acc = []) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, e.name)
    if (e.isDirectory()) walk(full, base, acc)
    else acc.push(path.relative(base, full).split(path.sep).join('/'))
  }
  return acc
}
if (!fs.existsSync(CONTENT)) { console.error('content/ 不存在，先跑 scripts/sync-content.ps1'); process.exit(1) }
const contentFiles = walk(CONTENT).sort()
for (const rel of contentFiles) {
  if (isBlacklisted(rel)) { fail(`content/ 里有黑名单文件：${rel}`); continue }
  const hit = whitelist.filter((w) => w.rx.test(rel))
  if (!hit.length) fail(`content/ 里有白名单外文件：${rel}`)
  hit.forEach((w) => w.hits++)
}
whitelist.filter((w) => w.hits === 0).forEach((w) => fail(`白名单条目未命中任何文件：${w.p}`))
const contentSet = new Set(contentFiles)
const readC = (rel) => {
  if (!contentSet.has(rel)) throw new Error(`content/ 缺文件：${rel}`)
  return fs.readFileSync(path.join(CONTENT, rel))
}
const fileSha = (rel) => sha256(readC(rel))

// ───────────────────────── 课程库（不入库，打包前核对） ─────────────────────────
// 两种模式：
//   本地默认模式：库文件由维护者用 --db-source <文件> 或环境变量 HOMESTAY_DB 指定；SHA-256 必须等于 content/kit/checksums.txt 的 db_file_sha256。
//                 生成总包与离线包，并把总包/离线包的字节数与 SHA-256 写入 release-manifest.json（入库）。
//   发布模式（CI）：--release-assets <tag> 或环境变量 RELEASE_ASSETS_TAG。没有库，不生成总包/离线包；
//                 下载页的总包与离线包按钮指向 GitHub Release 附件，字节数与 SHA-256 只读 release-manifest.json。
const argv = process.argv.slice(2)
const argOf = (name) => { const i = argv.indexOf(name); return i >= 0 ? argv[i + 1] : undefined }
const RELEASE_TAG = argOf('--release-assets') || process.env.RELEASE_ASSETS_TAG || ''
const RELEASE_MODE = Boolean(RELEASE_TAG)
const LOCAL_TAG = argOf('--tag') || 'v5'
const REPO_SLUG = process.env.RELEASE_REPO || 'cloudzun/ai-team-coding'
const MATERIALS_FILE = 'ai-team-coding-materials.zip'
const OFFLINE_FILE = 'ai-team-coding-offline.zip'
const releaseUrl = (tag, file) => `https://github.com/${REPO_SLUG}/releases/download/${tag}/${file}`
const MANIFEST_PATH = path.join(ROOT, 'release-manifest.json')
// content/ 指纹：路径 + 每个文件的 SHA-256。manifest 记录它，CI 用它确认总包没有落后于 content/。
const CONTENT_DIGEST = sha256(Buffer.from(contentFiles.map((f) => `${f}\0${fileSha(f)}`).join('\n')))
const ckText = readC('kit/checksums.txt').toString('utf8')
const ckv = (k) => (ckText.match(new RegExp('^' + k + '\\s*=\\s*(.+)$', 'm')) || [])[1]?.trim()
const DB_EXPECT = { sha: ckv('db_file_sha256'), bytes: Number(ckv('db_bytes')), content: ckv('db_content_sha256'), rel: ckv('db_relpath') }
if (!DB_EXPECT.sha || !DB_EXPECT.bytes) { console.error('checksums.txt 缺 db_file_sha256 / db_bytes'); process.exit(1) }
const DB_ZIP_PATH = 'v2/kit/' + (DB_EXPECT.rel || 'db/homestay.db')
let dbBuf = null
let dbSha = null
let MANIFEST = null
if (RELEASE_MODE) {
  if (!fs.existsSync(MANIFEST_PATH)) { console.error('发布模式需要 release-manifest.json（由本地带库构建生成并入库）'); process.exit(1) }
  MANIFEST = JSON.parse(fs.readFileSync(MANIFEST_PATH, 'utf8'))
  const mm = MANIFEST.materials || {}
  const oo = MANIFEST.offline || {}
  if (MANIFEST.tag !== RELEASE_TAG) { console.error(`发布模式 tag=${RELEASE_TAG}，但 release-manifest.json 的 tag=${MANIFEST.tag}`); process.exit(1) }
  if (!(mm.file === MATERIALS_FILE && mm.bytes > 0 && /^[0-9a-f]{64}$/.test(mm.sha256) && Array.isArray(mm.entries) && mm.entries.length && mm.db_path === DB_ZIP_PATH)) { console.error('release-manifest.json 的 materials 项不完整'); process.exit(1) }
  if (!(oo.file === OFFLINE_FILE && oo.bytes > 0 && /^[0-9a-f]{64}$/.test(oo.sha256))) { console.error('release-manifest.json 的 offline 项不完整'); process.exit(1) }
  if (MANIFEST.content_digest !== CONTENT_DIGEST) {
    console.error('release-manifest.json 已落后于 content/（内容指纹不一致）：请在本地带库重新构建，重新生成并提交 manifest，再把新的总包与离线包更新到 Release。')
    process.exit(1)
  }
  console.log(`发布模式：tag=${RELEASE_TAG}，总包与离线包指向 GitHub Release，数值取自 release-manifest.json（内容指纹一致）`)
} else {
  const dbSource = argOf('--db-source') || process.env.HOMESTAY_DB
  if (!dbSource) {
    console.error('缺课程库：请用 --db-source <库文件路径> 或环境变量 HOMESTAY_DB 指定（由维护者提供，库不入库）。')
    console.error('例：npm run build -- --db-source <homestay.db 的路径>；CI 用：node scripts/build.mjs --release-assets v5')
    process.exit(1)
  }
  if (!fs.existsSync(dbSource)) { console.error('课程库文件不存在（--db-source / HOMESTAY_DB 指向的路径）'); process.exit(1) }
  dbBuf = fs.readFileSync(dbSource)
  dbSha = sha256(dbBuf)
  if (dbSha !== DB_EXPECT.sha || dbBuf.length !== DB_EXPECT.bytes) {
    console.error('课程库校验失败：与 checksums.txt 不符')
    console.error('  期望 db_file_sha256 = ' + DB_EXPECT.sha + '，db_bytes = ' + DB_EXPECT.bytes)
    console.error('  实际 SHA-256        = ' + dbSha + '，字节数 = ' + dbBuf.length)
    process.exit(1)
  }
  console.log('课程库校验：SHA-256 与 checksums.txt 的 db_file_sha256 一致（' + dbBuf.length.toLocaleString('en-US') + ' 字节）')
}

// ───────────────────────── Markdown 预处理 ─────────────────────────
// 1) 围栏外剥 HTML 注释  2) 围栏与行内代码外，把 **…** 直接转成 <strong>（中文标点邻接时 CommonMark 不认加粗）
function cleanProse(chunk) {
  const noComment = chunk.replace(/<!--[\s\S]*?-->/g, '')
  return noComment.split('\n').map((line) => {
    const codes = []
    let s = line.replace(/(`+)([\s\S]*?[^`])\1(?!`)/g, (m) => { codes.push(m); return `\u0000${codes.length - 1}\u0000` })
    s = s.replace(/\*\*(?=\S)([^*\n]+?)(?<=\S)\*\*/g, '<strong>$1</strong>')
    return s.replace(/\u0000(\d+)\u0000/g, (_, i) => codes[Number(i)])
  }).join('\n')
}
function preprocess(src, label) {
  const lines = src.replace(/\r\n/g, '\n').split('\n')
  const out = []
  let fence = null
  let buf = []
  const flush = () => { if (buf.length) { out.push(cleanProse(buf.join('\n'))); buf = [] } }
  for (const line of lines) {
    if (!fence) {
      const m = line.match(/^\s*(`{3,}|~{3,})/)
      if (m) { flush(); fence = { ch: m[1][0], len: m[1].length }; out.push(line) } else buf.push(line)
    } else {
      out.push(line)
      const m = line.match(/^\s*(`{3,}|~{3,})\s*$/)
      if (m && m[1][0] === fence.ch && m[1].length >= fence.len) fence = null
    }
  }
  flush()
  if (fence) fail(`${label}：代码围栏未闭合`)
  return out.join('\n')
}

// ───────────────────────── marked 渲染器 ─────────────────────────
function slug(text) {
  const t = text.replace(/<[^>]+>/g, '').replace(/`/g, '').toLowerCase()
    .replace(/[^\p{L}\p{N}\s-]/gu, '').trim().replace(/\s+/g, '-')
  return t || 's'
}
function highlightStates(escaped) {
  return escaped
    .replace(/\b(PASS)\b/g, '<span class="st st-pass">$1</span>')
    .replace(/\b(FAIL)\b/g, '<span class="st st-fail">$1</span>')
    .replace(/(推断)/g, '<span class="st st-infer">$1</span>')
}
marked.use({
  gfm: true,
  tokenizer: { url() { return undefined } }, // 裸网址不自动成链（多为本机地址，站点应离线可用）
  renderer: {
    heading(token) {
      const inner = this.parser.parseInline(token.tokens)
      const id = token.id || slug(token.text)
      return `<h${token.depth} id="${esc(id)}">${inner}<a class="anchor" href="#${esc(id)}" aria-label="本节链接">#</a></h${token.depth}>\n`
    },
    code(token) {
      const lang = (token.lang || '').split(/\s+/)[0]
      return `<div class="code"><div class="code-bar"><span class="lang">${esc(lang || 'text')}</span><button class="copy" type="button" aria-label="复制代码">复制</button></div><pre><code>${highlightStates(esc(token.text))}</code></pre></div>\n`
    },
    link(token) {
      // 站内无外链：http(s) 地址只作文字展示（多为本机地址）；相对链接照常
      const inner = this.parser.parseInline(token.tokens)
      if (/^https?:/i.test(token.href)) {
        return inner === esc(token.href) || inner === token.href ? `<code class="url">${esc(token.href)}</code>` : `${inner} <code class="url">${esc(token.href)}</code>`
      }
      return `<a href="${esc(token.href)}">${inner}</a>`
    },
    checkbox(token) {
      return `<input type="checkbox" disabled${token.checked ? ' checked' : ''}> `
    },
  },
})
function renderTokens(tokens) {
  const arr = [...tokens]
  arr.links = {}
  return marked.parser(arr).replace(/<table>/g, '<div class="tablewrap"><table>').replace(/<\/table>/g, '</table></div>')
}

// ───────────────────────── 章节装载 ─────────────────────────
// 顺序：1、2、8 环演示、3、4–8
const CHAPTER_DEFS = [
  ['ch1', 'chapters/ch1_任务书与流程.md'],
  ['ch2', 'chapters/ch2_搭最小环境.md'],
  ['ch2b', 'chapters/ch2b_8环演示.md'],
  ['ch3', 'chapters/ch3_业务数据与需求.md'],
  ['ch4', 'chapters/ch4_单元一_看板任务书.md'],
  ['ch5', 'chapters/ch5_单元二_问数任务书.md'],
  ['ch6', 'chapters/ch6_单元三_巡检任务书.md'],
  ['ch7', 'chapters/ch7_单元四_插件任务书.md'],
  ['ch8', 'chapters/ch8_复盘与展望.md'],
]
const chapters = CHAPTER_DEFS.map(([id, rel]) => {
  const raw = readC(rel).toString('utf8')
  const tokens = marked.lexer(preprocess(raw, rel))
  const used = new Map()
  const headings = []
  for (const t of tokens) {
    if (t.type !== 'heading') continue
    let id0 = slug(t.text)
    const n = (used.get(id0) || 0) + 1
    used.set(id0, n)
    if (n > 1) id0 = `${id0}-${n}`
    t.id = id0
    headings.push(t)
  }
  const h1 = headings.find((h) => h.depth === 1)
  if (!h1) fail(`${rel}：没有一级标题`)
  const title = h1 ? h1.text : id
  const m = title.match(/^第\s*(\S+?)\s*章\s*(.*)$/)
  return { id, rel, out: `textbook/${id}.html`, tokens, headings, title, num: m ? m[1] : id, short: m ? m[2] : title, sha: sha256(Buffer.from(raw)) }
})
const chapterById = Object.fromEntries(chapters.map((c) => [c.id, c]))

// 切片
function findHeading(ch, text) {
  const hits = ch.headings.filter((h) => h.text === text)
  return hits
}
function sectionTokens(ch, h) {
  const i = ch.tokens.indexOf(h)
  let j = i + 1
  while (j < ch.tokens.length && !(ch.tokens[j].type === 'heading' && ch.tokens[j].depth <= h.depth)) j++
  return ch.tokens.slice(i + 1, j)
}
const sectionNo = (text) => { const m = text.match(/^(\d+(?:\.\d+)*)\s/); return m ? m[1] : null }

// ───────────────────────── 页面模板 ─────────────────────────
const FAVICON = `data:image/svg+xml,${encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="7" fill="#0b1320"/><circle cx="16" cy="16" r="9" fill="none" stroke="#ffb23f" stroke-width="3" stroke-dasharray="5 2.2"/><circle cx="16" cy="7" r="2.6" fill="#ffb23f"/></svg>')}`
const NAV = [
  { key: 'home', label: '首页', href: 'index.html' },
  { key: 'textbook', label: '教材', href: 'textbook/ch1.html' },
  { key: 'demo', label: '8 环演示', href: 'textbook/ch2b.html' },
  { key: 'labs', label: '实验', href: 'labs/u0.html' },
  { key: 'download', label: '下载', href: 'downloads.html' },
]
function brandMark() {
  return `<svg class="brand-mark" viewBox="0 0 32 32" aria-hidden="true"><circle cx="16" cy="16" r="10" fill="none" stroke="#ffb23f" stroke-width="3" stroke-dasharray="5.4 2.5"/><circle cx="16" cy="6" r="2.8" fill="#ffb23f"/></svg>`
}
function page({ out, title, section, body, sidebar = '', toc = '', pageClass = '', description = '' }) {
  const depth = out.split('/').length - 1
  const rel = depth ? '../'.repeat(depth) : ''
  const nav = NAV.map((n) => `<a href="${rel}${n.href}"${n.key === section ? ' class="on" aria-current="page"' : ''}>${n.label}</a>`).join('')
  const html = `<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${esc(title)} · ${esc(SITE_SHORT)}</title>
${description ? `<meta name="description" content="${esc(description)}">\n` : ''}<link rel="icon" href="${FAVICON}">
<link rel="stylesheet" href="${rel}assets/site.css">
</head>
<body class="${pageClass}">
<a class="skip" href="#main">跳到正文</a>
<header class="topbar">
  <div class="topbar-in">
    <a class="brand" href="${rel}index.html">${brandMark()}<span class="brand-t">${esc(SITE_NAME)}</span></a>
    <nav class="topnav" aria-label="主导航">${nav}</nav>
  </div>
</header>
<div class="shell${sidebar ? ' has-side' : ''}${toc ? ' has-toc' : ''}">
${sidebar ? `<aside class="side"><details class="side-d" open><summary>目录</summary>${sidebar}</details></aside>` : ''}
<main id="main" class="main">
${body}
</main>
${toc ? `<aside class="toc" aria-label="本页目录"><div class="toc-in"><p class="toc-h">本页目录</p>${toc}</div></aside>` : ''}
</div>
<footer class="foot"><div class="foot-in"><span>${esc(SITE_NAME)}</span><span>离线可用：全部链接为相对路径，同一份文件夹可放在根目录、子路径或本地直接打开。</span></div></footer>
<script src="${rel}assets/site.js" defer></script>
</body>
</html>
`
  return { out, html }
}
const pages = []
const addPage = (p) => pages.push(p)

function tocFrom(headings, maxDepth = 3, minDepth = 2) {
  const items = headings.filter((h) => h.depth >= minDepth && h.depth <= maxDepth)
  if (!items.length) return ''
  return '<ul>' + items.map((h) => `<li class="d${h.depth}"><a href="#${esc(h.id)}">${esc(h.text.replace(/<[^>]+>/g, '').replace(/`/g, ''))}</a></li>`).join('') + '</ul>'
}

// ─── 教材页 ───
function chapterSidebar(cur, rel) {
  return `<nav class="chapnav" aria-label="章节">` + chapters.map((c) =>
    `<a href="${rel}${c.out}"${c.id === cur ? ' class="on" aria-current="page"' : ''}><span class="cn">${esc(c.num === 'ch' ? '' : '第 ' + c.num + ' 章')}</span><span class="ct">${esc(c.short)}</span></a>`).join('') + `</nav>`
}
chapters.forEach((c, i) => {
  const prev = chapters[i - 1]
  const next = chapters[i + 1]
  const tokens = c.tokens
  // 8 环演示页：顶部挂演示入口（演示页只从这里链接）
  let demoCall = ''
  if (c.id === 'ch2b') {
    demoCall = `<a class="demo-call" href="../demo/index.html"><span class="demo-call-k">投屏页</span><span class="demo-call-t">打开 8 环演示</span><span class="demo-call-s">整屏深色页面，按原样收录；看完用浏览器的后退键回到本页。</span><span class="demo-call-go" aria-hidden="true">→</span></a>`
  }
  let bodyHtml = renderTokens(tokens)
  // 紧跟一级标题后面插入演示入口
  if (demoCall) bodyHtml = bodyHtml.replace(/(<\/h1>\n)/, `$1${demoCall}\n`)
  const body = `<article class="doc">
<p class="crumb"><a href="../index.html">首页</a> / 教材 / ${esc(c.num === 'ch' ? c.title : '第 ' + c.num + ' 章')}</p>
${bodyHtml}
<nav class="pager" aria-label="上一章与下一章">
${prev ? `<a class="prev" href="../${prev.out}"><small>上一页</small>${esc(prev.title)}</a>` : '<span></span>'}
${next ? `<a class="next" href="../${next.out}"><small>下一页</small>${esc(next.title)}</a>` : '<span></span>'}
</nav>
<p class="srcmeta">源文件 <code>v2/${esc(c.rel)}</code> · SHA-256 <code>${c.sha.slice(0, 16)}…</code></p>
</article>`
  addPage(page({
    out: c.out, title: c.title, section: c.id === 'ch2b' ? 'demo' : 'textbook', body,
    sidebar: chapterSidebar(c.id, '../'), toc: tocFrom(c.headings),
  }))
})

// ─── 实验页 ───
const labsCfg = yamlLoad(fs.readFileSync(path.join(ROOT, 'labs/labs.yml'), 'utf8'))
const reportLabs = []
const labs = labsCfg.labs

// 下载包定义（先于实验页，实验页要回链）
const PACKS = [
  { id: 'kit', file: 'v2-kit.zip', title: '渔具包（学员件）', desc: '口径表、运营手册、表结构说明、导出契约、交付约定三份、checksums.txt、README，看板生成脚本与演示文件（tools/demo），课程版 gstack-sprint 技能（gstack-sprint/SKILL.md）；db 目录只留空位', include: ['kit/**'] },
  { id: 'tools', file: 'v2-lab-tools.zip', title: '检查与自检脚本', desc: 'env_check、db_fingerprint、chart_check、u2/u3/u4_check', include: ['lab/tools/**'] },
  { id: 'templates', file: 'v2-lab-templates.zip', title: '模板', desc: '任务书模板、示范任务书、需求清单、事实卡、自查清单等', include: ['lab/templates/**'] },
  { id: 'fixtures', file: 'v2-lab-fixtures-u2-u4.zip', title: '坏夹具（单元二至四）', desc: 'u2 问答记录、u3 运营库、u4 卡片导出', include: ['lab/fixtures/u2/**', 'lab/fixtures/u3/**', 'lab/fixtures/u4/**'] },
  { id: 'sample', file: 'v2-lab-sample.zip', title: '样例页', desc: '单元一样例演练用的页面与期望值', include: ['lab/sample/**'] },
  { id: 'stage1', file: 'v2-checkpoints-stage1.zip', title: '阶段一存档点', desc: '单元一做好的起点', include: ['checkpoints/stage1/**'] },
  { id: 'stage2', file: 'v2-checkpoints-stage2.zip', title: '阶段二存档点', desc: '单元二做好的起点', include: ['checkpoints/stage2/**'] },
  { id: 'stage3', file: 'v2-checkpoints-stage3.zip', title: '阶段三存档点', desc: '单元三做好的起点', include: ['checkpoints/stage3/**'] },
  { id: 'stage4', file: 'v2-checkpoints-stage4.zip', title: '阶段四存档点', desc: '单元四做好的起点', include: ['checkpoints/stage4/**'] },
]
PACKS.forEach((p) => { p.rxs = p.include.map(globToRegex); p.files = contentFiles.filter((f) => p.rxs.some((rx) => rx.test(f))) })
const packFor = (rel) => PACKS.find((p) => p.rxs.some((rx) => rx.test(rel)))

function loadFileSlice(rel) {
  const raw = readC(rel).toString('utf8')
  const tokens = marked.lexer(preprocess(raw, rel))
  let skipped = null
  if (tokens.length && tokens[0].type === 'heading' && tokens[0].depth === 1) skipped = tokens.shift()
  else if (tokens.length > 1 && tokens[0].type === 'space' && tokens[1].type === 'heading' && tokens[1].depth === 1) { tokens.shift(); skipped = tokens.shift() }
  return { tokens, base: 1, sha: sha256(Buffer.from(raw)), title: skipped ? skipped.text : null }
}
function labPage(lab, li) {
  const ch = chapterById[lab.chapter]
  const usedIds = new Set()
  const heads = []
  const reportSlices = []
  const sourcesMeta = new Map()
  const sections = lab.slices.map((sl, si) => {
    const n = String(si + 1).padStart(2, '0')
    const secId = `s${si + 1}`
    let toks
    let base
    let origin
    const rep = { label: sl.label, kind: sl.file ? 'file' : 'chapter', hits: 0 }
    if (sl.file) {
      const f = loadFileSlice(sl.file)
      toks = f.tokens; base = f.base
      sourcesMeta.set(sl.file, f.sha)
      const pk = packFor(sl.file)
      origin = `出处：<code>v2/${esc(sl.file)}</code>${pk ? `（在<a href="../downloads.html#pack-${pk.id}">下载页“${esc(pk.title)}”</a>包里）` : ''}`
      rep.source = sl.file; rep.hits = 1
    } else {
      const c = chapterById[sl.chapter]
      if (!c) { fail(`${lab.id}：未知章节 ${sl.chapter}`); return '' }
      const hits = findHeading(c, sl.heading)
      rep.source = c.rel; rep.heading = sl.heading; rep.hits = hits.length
      if (hits.length !== 1) { fail(`实验切片 ${lab.id}「${sl.label}」：标题“${sl.heading}”在 ${c.rel} 里命中 ${hits.length} 次（必须恰好 1 次）`); return '' }
      const h = hits[0]
      base = h.depth
      toks = sectionTokens(c, h)
      if (sl.intro) {
        // 只取该节在第一个子标题之前的导语
        const k = toks.findIndex((t) => t.type === 'heading')
        if (k >= 0) toks = toks.slice(0, k)
        rep.intro = true
      }
      sourcesMeta.set(c.rel, c.sha)
      if (sl.code_match) {
        const codes = toks.filter((t) => t.type === 'code')
        const chosen = []
        rep.code_hits = []
        for (const pat of sl.code_match) {
          const m = codes.filter((t) => t.text.includes(pat))
          rep.code_hits.push(m.length)
          if (m.length !== 1) { fail(`实验切片 ${lab.id}「${sl.label}」：代码块子串“${pat}”命中 ${m.length} 个（必须恰好 1 个）`); continue }
          if (!chosen.includes(m[0])) chosen.push(m[0])
        }
        toks = codes.filter((t) => chosen.includes(t))
      }
      const no = sectionNo(h.text)
      const href = `../${c.out}#${h.id}`
      origin = `出处：<a href="${href}">第 ${esc(c.num)} 章${no ? ' ' + esc(no) + ' 节' : '“' + esc(h.text) + '”'}</a>${sl.code_match ? '（只取其中的代码块）' : ''}${sl.intro ? '（只取该节开头的导语）' : ''}`
    }
    // 子标题降级：基准标题 → 本页 h2，其下一级 → h3
    const out = toks.map((t) => {
      if (t.type !== 'heading') return t
      const d = Math.min(6, Math.max(3, t.depth - base + 2))
      let id0 = `${secId}-${t.id || slug(t.text)}`
      while (usedIds.has(id0)) id0 += 'x'
      usedIds.add(id0)
      heads.push({ depth: d, id: id0, text: t.text })
      return { ...t, depth: d, id: id0 }
    })
    heads.push({ depth: 2, id: secId, text: sl.label, _order: heads.length })
    reportSlices.push(rep)
    return { secId, n, label: sl.label, html: renderTokens(out), origin }
  })
  // 目录：h2 在各自小节子标题之前
  const tocItems = []
  sections.forEach((s) => {
    if (!s) return
    tocItems.push({ depth: 2, id: s.secId, text: s.label })
  })
  const bodySections = sections.filter(Boolean).map((s) => `<section class="slice" id="${s.secId}" data-slice="${s.secId}">
<header class="slice-h"><span class="slice-n" aria-hidden="true">${s.n}</span><h2>${esc(s.label)}<a class="anchor" href="#${s.secId}" aria-label="本节链接">#</a></h2></header>
<div class="slice-b">
${s.html}
</div>
<p class="origin">${s.origin}</p>
</section>`).join('\n')
  const srcList = [...sourcesMeta.entries()].map(([r, h]) => `<li><code>v2/${esc(r)}</code> <span>${h}</span></li>`).join('')
  const tabs = labs.map((l) => `<a href="${l.id}.html"${l.id === lab.id ? ' class="on" aria-current="page"' : ''}>${esc(l.title.replace(/\u3000/g, ' '))}</a>`).join('')
  const body = `<article class="doc labdoc">
<p class="crumb"><a href="../index.html">首页</a> / 实验 / ${esc(lab.title.replace(/\u3000/g, ' '))}</p>
<h1>${esc(lab.title.replace(/\u3000/g, ' '))}<small>实验手册</small></h1>
<p class="lead">${esc(lab.intro)}</p>
<div class="labtabs" role="tablist">${tabs}</div>
${bodySections}
<details class="srcmeta-d"><summary>本页源文件与 SHA-256（页面不另写事实，全部切自下列文件）</summary><ul class="srcs">${srcList}</ul></details>
</article>`
  const sidebar = `<nav class="chapnav" aria-label="实验">` + labs.map((l) =>
    `<a href="${l.id}.html"${l.id === lab.id ? ' class="on" aria-current="page"' : ''}><span class="cn">${esc(l.title.split('\u3000')[0])}</span><span class="ct">${esc(l.title.split('\u3000')[1] || '')}</span></a>`).join('') + `</nav>`
  reportLabs.push({ id: lab.id, page: `labs/${lab.id}.html`, slices: reportSlices, sources: Object.fromEntries(sourcesMeta) })
  addPage(page({
    out: `labs/${lab.id}.html`, title: `${lab.title.replace(/\u3000/g, ' ')} 实验手册`, section: 'labs', body, sidebar,
    toc: '<ul>' + tocItems.map((t) => `<li class="d2"><a href="#${t.id}">${esc(t.text)}</a></li>`).join('') + '</ul>',
  }))
}
labs.forEach(labPage)

// ─── 首页 ───
function ringSvg() {
  const cx = 170, cy = 170, r = 120
  let nodes = ''
  for (let i = 0; i < 8; i++) {
    const a = -Math.PI / 2 + i * Math.PI / 4
    const x = (cx + r * Math.cos(a)).toFixed(1)
    const y = (cy + r * Math.sin(a)).toFixed(1)
    nodes += `<g class="rn" style="--i:${i}"><circle cx="${x}" cy="${y}" r="19"/><text x="${x}" y="${y}" dy=".36em">${i}</text></g>`
  }
  // 门禁 G1（环 0 之后）、G2（环 5 与环 6 之间）
  for (const [k, label] of [[0.5, 'G1'], [5.5, 'G2']]) {
    const a = -Math.PI / 2 + k * Math.PI / 4
    const x = (cx + r * Math.cos(a)).toFixed(1)
    const y = (cy + r * Math.sin(a)).toFixed(1)
    nodes += `<g class="rg"><rect x="${(x - 17).toFixed(1)}" y="${(y - 11).toFixed(1)}" width="34" height="22" rx="3"/><text x="${x}" y="${y}" dy=".36em">${label}</text></g>`
  }
  return `<svg class="ring" viewBox="0 0 340 340" role="img" aria-label="环 0 到环 7 首尾相接的示意图，环 0 之后是 G1，环 5 与环 6 之间是 G2">
<circle class="ring-track" cx="${cx}" cy="${cy}" r="${r}"/>
<circle class="ring-arc" cx="${cx}" cy="${cy}" r="${r}" pathLength="100"/>
<text class="ring-c1" x="${cx}" y="${cy - 6}">任务书</text><text class="ring-c2" x="${cx}" y="${cy + 24}">8 环</text>
${nodes}</svg>`
}
{
  // 首页不再放“四个单元一张图”那张表（表只留在第 1 章 1.3 节，教材不改）
  const body = `<section class="hero">
  <div class="hero-l">
    <p class="eyebrow">课件网站 · 教材 / 演示 / 实验 / 下载</p>
    <h1><span class="h1a">带 AI 团队写代码</span><span class="h1b">从任务书到交付</span></h1>
    <p class="hero-p">教材、8 环演示、实验手册与课程材料下载，在同一个站点里。</p>
    <p class="cta"><a class="btn btn-a" href="textbook/ch1.html">从第 1 章开始读</a><a class="btn btn-d" href="textbook/ch2b.html">看 8 环演示</a></p>
  </div>
  <div class="hero-r">${ringSvg()}</div>
</section>
<section class="band">
  <h2 class="band-h"><span class="tick"></span>从这里进</h2>
  <div class="cards">
    <a class="card" href="textbook/ch1.html"><span class="card-k">01</span><strong>教材</strong><span>第 1–8 章与 8 环演示，一章一页，左侧章目录，右侧本页目录。</span></a>
    <a class="card card-dark" href="textbook/ch2b.html"><span class="card-k">02</span><strong>8 环演示</strong><span>投屏页，深色，按原样收录；入口在第 2b 章。</span></a>
    <a class="card" href="labs/u0.html"><span class="card-k">03</span><strong>实验</strong><span>环境准备与单元一至四。按标题从章节里切片拼成，每段回链出处。</span></a>
    <a class="card" href="downloads.html"><span class="card-k">04</span><strong>下载</strong><span>渔具包、检查脚本、模板、夹具、样例页与四个存档点，列文件名、字节数与 SHA-256。</span></a>
  </div>
</section>`
  addPage(page({ out: 'index.html', title: '首页', section: 'home', body, pageClass: 'home' }))
}

// ───────────────────────── 下载包 ─────────────────────────
function crc32(buf) { return zlib.crc32(buf) >>> 0 }
function makeZip(entries) {
  const parts = []
  const central = []
  let offset = 0
  const dosDate = ((2026 - 1980) << 9) | (1 << 5) | 1
  for (const e of entries) {
    const name = Buffer.from(e.name, 'utf8')
    const crc = crc32(e.data)
    const comp = e.data.length ? zlib.deflateRawSync(e.data, { level: 9 }) : Buffer.alloc(0)
    const useDef = comp.length < e.data.length
    const body = useDef ? comp : e.data
    const method = useDef ? 8 : 0
    const lh = Buffer.alloc(30)
    lh.writeUInt32LE(0x04034b50, 0); lh.writeUInt16LE(20, 4); lh.writeUInt16LE(0x0800, 6); lh.writeUInt16LE(method, 8)
    lh.writeUInt16LE(0, 10); lh.writeUInt16LE(dosDate, 12); lh.writeUInt32LE(crc, 14)
    lh.writeUInt32LE(body.length, 18); lh.writeUInt32LE(e.data.length, 22); lh.writeUInt16LE(name.length, 26); lh.writeUInt16LE(0, 28)
    parts.push(lh, name, body)
    const ch = Buffer.alloc(46)
    ch.writeUInt32LE(0x02014b50, 0); ch.writeUInt16LE(20, 4); ch.writeUInt16LE(20, 6); ch.writeUInt16LE(0x0800, 8); ch.writeUInt16LE(method, 10)
    ch.writeUInt16LE(0, 12); ch.writeUInt16LE(dosDate, 14); ch.writeUInt32LE(crc, 16)
    ch.writeUInt32LE(body.length, 20); ch.writeUInt32LE(e.data.length, 24); ch.writeUInt16LE(name.length, 28)
    ch.writeUInt16LE(0, 30); ch.writeUInt16LE(0, 32); ch.writeUInt16LE(0, 34); ch.writeUInt16LE(0, 36); ch.writeUInt32LE(0, 38); ch.writeUInt32LE(offset, 42)
    central.push(ch, name)
    offset += lh.length + name.length + body.length
  }
  const cd = Buffer.concat(central)
  const end = Buffer.alloc(22)
  end.writeUInt32LE(0x06054b50, 0); end.writeUInt16LE(0, 4); end.writeUInt16LE(0, 6)
  end.writeUInt16LE(entries.length, 8); end.writeUInt16LE(entries.length, 10); end.writeUInt32LE(cd.length, 12); end.writeUInt32LE(offset, 16); end.writeUInt16LE(0, 20)
  return Buffer.concat([...parts, cd, end])
}

// 清空 dist 后重建
fs.rmSync(DIST, { recursive: true, force: true })
fs.mkdirSync(path.join(DIST, 'downloads'), { recursive: true })
const packReport = []
for (const p of PACKS) {
  const entries = p.files.map((f) => ({ name: `v2/${f}`, data: readC(f) }))
  const zip = makeZip(entries)
  fs.writeFileSync(path.join(DIST, 'downloads', p.file), zip)
  p.bytes = zip.length
  p.sha = sha256(zip)
  p.entries = entries.map((e) => ({ name: e.name, bytes: e.data.length }))
  packReport.push({ id: p.id, file: p.file, bytes: p.bytes, sha256: p.sha, count: p.entries.length })
}

// 总包：9 个分包的全部文件合并 + 课程库，统一 v2/ 前缀（库解开后在 v2/kit/db/homestay.db）
const ALL = { id: 'all', file: MATERIALS_FILE, title: '全部学员材料（一次下载）' }
if (RELEASE_MODE) {
  // CI：没有库，不生成总包；数值取自 release-manifest.json
  const mm = MANIFEST.materials
  ALL.bytes = mm.bytes; ALL.sha = mm.sha256; ALL.entries = mm.entries; ALL.fileCount = mm.entries.length - 1
  ALL.href = releaseUrl(RELEASE_TAG, MATERIALS_FILE)
} else {
  ALL.href = `downloads/${MATERIALS_FILE}`
  const names = new Set()
  const entries = []
  for (const p of PACKS) for (const f of p.files) if (!names.has(f)) { names.add(f); entries.push({ name: 'v2/' + f, data: readC(f) }) }
  entries.push({ name: DB_ZIP_PATH, data: dbBuf })
  entries.sort((a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0))
  const zip = makeZip(entries)
  fs.writeFileSync(path.join(DIST, 'downloads', ALL.file), zip)
  ALL.bytes = zip.length; ALL.sha = sha256(zip)
  ALL.entries = entries.map((e) => ({ name: e.name, bytes: e.data.length }))
  ALL.fileCount = entries.length - 1
}

// ─── 下载页 ───
{
  const ck = readC('kit/checksums.txt').toString('utf8')
  const kv = (k) => (ck.match(new RegExp(`^${k}\\s*=\\s*(.+)$`, 'm')) || [])[1]?.trim()
  const dbContent = kv('db_content_sha256'); const dbFile = kv('db_file_sha256'); const dbBytes = kv('db_bytes'); const dbRel = kv('db_relpath')
  if (!dbContent || !dbFile || !dbBytes) fail('下载页：checksums.txt 缺 db_* 项')
  const rows = PACKS.map((p) => `<tr id="pack-${p.id}">
<td><a class="dl" href="downloads/${esc(p.file)}" download>${esc(p.file)}</a><div class="dl-t">${esc(p.title)}</div></td>
<td>${esc(p.desc)}</td>
<td class="num">${p.entries.length}</td>
<td class="num">${fmtBytes(p.bytes)}</td>
<td class="hash"><code>${p.sha}</code></td>
</tr>
<tr class="files-row"><td colspan="5"><details><summary>列出 ${p.entries.length} 个文件</summary><table class="files"><thead><tr><th>文件（zip 内路径）</th><th class="num">字节数</th></tr></thead><tbody>${p.entries.map((e) => `<tr><td><code>${esc(e.name)}</code></td><td class="num">${fmtBytes(e.bytes)}</td></tr>`).join('')}</tbody></table></details></td></tr>`).join('\n')
  const offlineLine = RELEASE_MODE
    ? `<p class="dl-all-o">离线包：<a href="${esc(releaseUrl(RELEASE_TAG, OFFLINE_FILE))}" download>${esc(OFFLINE_FILE)}</a>（${fmtBytes(MANIFEST.offline.bytes)} 字节，SHA-256 <code>${MANIFEST.offline.sha256}</code>）。含全部页面与总包，解压后双击 <code>start.cmd</code> 即可离线打开。</p>`
    : ''
  const body = `<article class="doc dldoc">
<p class="crumb"><a href="index.html">首页</a> / 下载</p>
<h1>下载<small>课程材料</small></h1>
<p class="lead">所有包解开后都带 <code>v2/</code> 前缀，章节里写的命令路径原样可用。文件数、字节数与 SHA-256 都列在下面。</p>
<section class="dl-all" id="pack-all" aria-labelledby="all-h">
<p class="dl-all-k">一次下载全部</p>
<h2 id="all-h">${esc(ALL.title)}</h2>
<p class="dl-all-s">下面 9 个分包的全部内容合并，再加上课程库；含课程版 gstack-sprint 技能。解开后课程库在 <code>${esc(DB_ZIP_PATH)}</code>。</p>
<p class="dl-all-f"><a class="btn btn-a" href="${esc(ALL.href)}" download>下载 ${esc(ALL.file)}${RELEASE_MODE ? '（GitHub Release）' : ''}</a></p>
${offlineLine}
<dl class="dl-all-m">
<div><dt>字节数</dt><dd>${fmtBytes(ALL.bytes)}</dd></div>
<div><dt>文件数</dt><dd>${ALL.fileCount} 个材料文件 + 课程库 1 个</dd></div>
<div class="wide"><dt>SHA-256</dt><dd><code>${ALL.sha}</code></dd></div>
</dl>
<details><summary>列出全部 ${ALL.entries.length} 个文件</summary><table class="files"><thead><tr><th>文件（zip 内路径）</th><th class="num">字节数</th></tr></thead><tbody>${ALL.entries.map((e) => `<tr><td><code>${esc(e.name)}</code></td><td class="num">${fmtBytes(e.bytes)}</td></tr>`).join('')}</tbody></table></details>
</section>
<h2 id="packs">按需单独下载<a class="anchor" href="#packs" aria-label="本节链接">#</a></h2>
<div class="tablewrap dl-wrap"><table class="dl-table">
<thead><tr><th>包</th><th>内含</th><th class="num">文件数</th><th class="num">字节数</th><th>SHA-256</th></tr></thead>
<tbody>
${rows}
</tbody></table></div>
<h3 id="verify-pack">核对下载的包<a class="anchor" href="#verify-pack" aria-label="本节链接">#</a></h3>
<div class="code"><div class="code-bar"><span class="lang">powershell</span><button class="copy" type="button" aria-label="复制代码">复制</button></div><pre><code>Get-FileHash .\\ai-team-coding-materials.zip -Algorithm SHA256   # 与页面上对应行的 SHA-256 逐位一致即可</code></pre></div>
<h2 id="course-db">课程库 homestay.db<a class="anchor" href="#course-db" aria-label="本节链接">#</a></h2>
<p>课程库在“一次下载全部”总包和离线包里，解开后位于 <code>${esc(DB_ZIP_PATH)}</code>；不在 9 个分包里，也不放进代码仓库。用下面的校验和与命令核对。以下数值抄自渔具包的 <code>checksums.txt</code>。</p>
<div class="tablewrap"><table>
<thead><tr><th>项</th><th>值</th><th>怎么用</th></tr></thead>
<tbody>
<tr><td><code>db_content_sha256</code></td><td class="hash"><code>${esc(dbContent || '')}</code></td><td>数据内容校验和；判断“数据是不是同一份”只看这一项</td></tr>
<tr><td><code>db_file_sha256</code></td><td class="hash"><code>${esc(dbFile || '')}</code></td><td>识别这一份库文件（文件级）</td></tr>
<tr><td><code>db_bytes</code></td><td class="num"><code>${esc(dbBytes ? fmtBytes(Number(dbBytes)) : '')}</code></td><td>文件字节数</td></tr>
</tbody></table></div>
<div class="code"><div class="code-bar"><span class="lang">powershell</span><button class="copy" type="button" aria-label="复制代码">复制</button></div><pre><code>python v2\\lab\\tools\\env_check.py
python v2\\lab\\tools\\db_fingerprint.py v2\\kit\\db\\homestay.db</code></pre></div>
<p class="origin">出处：渔具包 <code>v2/kit/README.md</code> 第 3 节“怎么核对”与 <code>v2/kit/checksums.txt</code>。</p>
</article>`
  addPage(page({
    out: 'downloads.html', title: '下载', section: 'download', body,
    toc: '<ul><li class="d2"><a href="#pack-all">一次下载全部</a></li><li class="d2"><a href="#packs">按需单独下载</a></li><li class="d3"><a href="#verify-pack">核对下载的包</a></li><li class="d2"><a href="#course-db">课程库 homestay.db</a></li></ul>',
  }))
}

// ───────────────────────── 写出 dist ─────────────────────────
fs.mkdirSync(path.join(DIST, 'assets'), { recursive: true })
fs.copyFileSync(path.join(ROOT, 'site/site.css'), path.join(DIST, 'assets/site.css'))
fs.copyFileSync(path.join(ROOT, 'site/site.js'), path.join(DIST, 'assets/site.js'))
for (const p of pages) {
  const f = path.join(DIST, p.out)
  fs.mkdirSync(path.dirname(f), { recursive: true })
  fs.writeFileSync(f, p.html, 'utf8')
}
// 演示页原样（字节级拷贝）
fs.mkdirSync(path.join(DIST, 'demo'), { recursive: true })
fs.copyFileSync(path.join(CONTENT, 'demo/8环演示.html'), path.join(DIST, 'demo/index.html'))

// ───────────────────────── 自检 ─────────────────────────
function textOf(html) {
  return html.replace(/<pre[\s\S]*?<\/pre>/g, ' ').replace(/<code[\s\S]*?<\/code>/g, ' ').replace(/<[^>]+>/g, ' ')
}
const htmlFiles = walk(DIST).filter((f) => f.endsWith('.html')).sort()
if (htmlFiles.length !== EXPECTED_PAGES) fail(`页数 ${htmlFiles.length} ≠ ${EXPECTED_PAGES}：${htmlFiles.join(', ')}`)
for (const f of htmlFiles) {
  if (f === 'demo/index.html') continue
  const html = fs.readFileSync(path.join(DIST, f), 'utf8')
  const txt = textOf(html)
  if (txt.includes('**')) fail(`${f}：正文残留 **`)
  const so = (html.match(/<strong>/g) || []).length
  const sc = (html.match(/<\/strong>/g) || []).length
  if (so !== sc) fail(`${f}：<strong> 不成对 ${so}/${sc}`)
  if (html.includes('<!--')) fail(`${f}：残留 HTML 注释`)
  const extLinks = (html.match(/<a [^>]*href="https?:\/\/[^"]*"/g) || []).map((s) => s.replace(/^.*href="|"$/g, ''))
  const allowedExt = RELEASE_MODE ? new Set([releaseUrl(RELEASE_TAG, MATERIALS_FILE), releaseUrl(RELEASE_TAG, OFFLINE_FILE)]) : new Set()
  for (const u of extLinks) if (!allowedExt.has(u)) fail(`${f}：有外链 ${u}`)
}
// 首页：不再出现“四个单元一张图”表（表只在第 1 章 1.3 节），保留“从这里进”四张卡
{
  const home = fs.readFileSync(path.join(DIST, 'index.html'), 'utf8')
  if (home.includes('四个单元一张图')) fail('首页：不应再有“四个单元一张图”')
  if (!home.includes('从这里进')) fail('首页：缺“从这里进”')
  const cards = (home.match(/<a class="card(?: card-dark)?" href="[^"]+">/g) || []).length
  if (cards !== 4) fail(`首页：“从这里进”卡片 ${cards} 张，应为 4 张`)
}
const demoSrc = fs.readFileSync(path.join(CONTENT, 'demo/8环演示.html'))
if (sha256(demoSrc) !== sha256(fs.readFileSync(path.join(DIST, 'demo/index.html')))) fail('演示页与源文件不一致')
for (const p of RELEASE_MODE ? PACKS : [...PACKS, ALL]) if (!fs.existsSync(path.join(DIST, 'downloads', p.file))) fail(`缺下载包 ${p.file}`)
if (RELEASE_MODE && fs.existsSync(path.join(DIST, 'downloads', MATERIALS_FILE))) fail('发布模式下 dist 里不应有总包')
for (const lab of reportLabs) for (const s of lab.slices) if (s.hits !== 1) fail(`实验 ${lab.id} 切片 ${s.label} 命中 ${s.hits}`)

fs.mkdirSync(BUILD_DIR, { recursive: true })
fs.writeFileSync(path.join(BUILD_DIR, 'report.json'), JSON.stringify({
  pages: htmlFiles, labs: reportLabs, packs: packReport,
  mode: RELEASE_MODE ? 'release' : 'local', tag: RELEASE_MODE ? RELEASE_TAG : null,
  release_urls: RELEASE_MODE ? { materials: releaseUrl(RELEASE_TAG, MATERIALS_FILE), offline: releaseUrl(RELEASE_TAG, OFFLINE_FILE) } : null,
  materials: { file: ALL.file, bytes: ALL.bytes, sha256: ALL.sha, count: ALL.entries.length, db_path: DB_ZIP_PATH, db_sha256: dbSha },
  chapters: chapters.map((c) => ({ id: c.id, rel: c.rel, sha256: c.sha, out: c.out })),
}, null, 2))

if (errors.length) {
  console.error('\n构建自检失败：')
  errors.forEach((e) => console.error('  ✗ ' + e))
  process.exit(1)
}

// ───────────────────────── 离线包与发布清单（仅本地带库模式） ─────────────────────────
if (RELEASE_MODE) {
  console.log(`构建完成（发布模式 ${RELEASE_TAG}）：${htmlFiles.length} 页，${PACKS.length} 个下载包；总包与离线包不在 dist 里，下载按钮指向 GitHub Release`)
  console.log('自检 PASS：manifest 内容指纹 · 白名单/黑名单 · 切片命中 · 页数 17 · 首页无 1.3 表、含从这里进四张卡 · 无残留 ** / 注释 · 仅两个 Release 外链 · 演示页字节一致 · 9 个分包齐全')
} else {
  fs.rmSync(RELEASE, { recursive: true, force: true })
  fs.mkdirSync(RELEASE, { recursive: true })
  const offEntries = walk(DIST).sort().map((f) => ({ name: f, data: fs.readFileSync(path.join(DIST, f)) }))
  offEntries.push({ name: 'start.cmd', data: fs.readFileSync(path.join(ROOT, 'scripts/start.cmd')) })
  const offZip = makeZip(offEntries)
  fs.writeFileSync(path.join(RELEASE, OFFLINE_FILE), offZip)
  // release-manifest.json：入库的小清单，CI 发布模式只读它（不含时间戳，重复构建结果一致）
  const manifest = {
    tag: LOCAL_TAG,
    repo: REPO_SLUG,
    content_digest: CONTENT_DIGEST,
    materials: { file: ALL.file, bytes: ALL.bytes, sha256: ALL.sha, db_path: DB_ZIP_PATH, entries: ALL.entries },
    offline: { file: OFFLINE_FILE, bytes: offZip.length, sha256: sha256(offZip) },
  }
  fs.writeFileSync(MANIFEST_PATH, JSON.stringify(manifest, null, 2) + '\n')
  console.log(`构建完成：${htmlFiles.length} 页，${PACKS.length} 个下载包，总包 ${fmtBytes(ALL.bytes)} 字节，离线包 ${fmtBytes(offZip.length)} 字节；已写 release-manifest.json（tag=${LOCAL_TAG}）`)
  console.log('自检 PASS：课程库校验 · 白名单/黑名单 · 切片命中 · 页数 17 · 首页无 1.3 表、含从这里进四张卡 · 无残留 ** / 注释 / 外链 · 演示页字节一致 · 下载包与总包齐全')
}