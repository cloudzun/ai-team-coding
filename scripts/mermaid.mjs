// mermaid.mjs —— 构建期把教材里的 ```mermaid 代码块预渲染成内嵌 SVG（离线、页面不加载任何外部脚本）。
//
// 选型：mermaid（纯 JS，devDependency）+ puppeteer-core（devDependency，安装时不下载浏览器），
//       浏览器用本机已装的 Chrome / Edge；可用环境变量 PUPPETEER_EXECUTABLE_PATH 或 MERMAID_BROWSER 指定。
//       不用 @mermaid-js/mermaid-cli：它内含的 puppeteer 会在安装时下载 Chromium（CI 上也要多下 170 MB），
//       而这里只需要「拿本机浏览器把一个 SVG 算出来」这一件事。
//
// 缓存：site/mermaid/<hash>.svg 入库。hash = 源码 + mermaid 版本 + 主题配置 + 字体族的 SHA-256 前 16 位。
//       命中缓存直接内嵌，完全不碰浏览器 —— CI（ubuntu、无 Chrome）也能构建。
//       未命中且本机没有浏览器 -> 抛错并提示「先在本机构建生成 mermaid 缓存」。
import fs from 'node:fs'
import path from 'node:path'
import crypto from 'node:crypto'
import { fileURLToPath } from 'node:url'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const NODE_MODULES = path.join(ROOT, 'node_modules')
const MERMAID_PKG = path.join(NODE_MODULES, 'mermaid', 'package.json')
const MERMAID_BUNDLE = path.join(NODE_MODULES, 'mermaid', 'dist', 'mermaid.min.js')

export const CACHE_DIR = path.join(ROOT, 'site', 'mermaid')
/** 与 site.css 的 --sans 完全一致，构建期与阅读期用同一套字体，宽度才算得准。 */
export const FONT_STACK = 'Tahoma, "Microsoft YaHei", "微软雅黑", "PingFang SC", sans-serif'

function versionOf(p) {
  try { return JSON.parse(fs.readFileSync(p, 'utf8')).version } catch { return '' }
}
export const MERMAID_VERSION = versionOf(MERMAID_PKG)

/** 浅色主题；颜色取站点色板（琥珀 #ffb23f / 深蓝 #0b1320 / 纸白 #fffdf7）。 */
export const MERMAID_CONFIG = {
  startOnLoad: false,
  theme: 'base',
  darkMode: false,
  fontFamily: FONT_STACK,
  // 关键：关掉 HTML 标签，节点文字用 <text>/<tspan> 画（内嵌 <br/> 也转成 tspan），
  // 输出是纯 SVG，不含 foreignObject —— 打印、另存为图片、塞进别的编辑器都不会丢字。
  htmlLabels: false,
  themeVariables: {
    darkMode: false,
    background: '#fffdf7',
    fontFamily: FONT_STACK,
    fontSize: '15px',
    primaryColor: '#fff1d4',
    primaryTextColor: '#0b1320',
    primaryBorderColor: '#ffb23f',
    secondaryColor: '#f3ecd9',
    secondaryTextColor: '#0b1320',
    secondaryBorderColor: '#cfc3a3',
    tertiaryColor: '#eae1c8',
    tertiaryTextColor: '#0b1320',
    tertiaryBorderColor: '#cfc3a3',
    mainBkg: '#fffdf7',
    nodeBorder: '#ffb23f',
    nodeTextColor: '#0b1320',
    lineColor: '#8a5200',
    textColor: '#0b1320',
    edgeLabelBackground: '#fffdf7',
    clusterBkg: '#fbf7ec',
    clusterBorder: '#cfc3a3',
    titleColor: '#0b1320',
    actorBkg: '#fff1d4',
    actorBorder: '#ffb23f',
    actorTextColor: '#0b1320',
    noteBkgColor: '#fff1d4',
    noteBorderColor: '#ffb23f',
    noteTextColor: '#0b1320',
    pie1: '#ffb23f',
    pie2: '#0b1320',
  },
  flowchart: { htmlLabels: false, useMaxWidth: true, curve: 'basis', padding: 12, nodeSpacing: 40, rankSpacing: 48, diagramPadding: 8 },
  sequence: { useMaxWidth: true },
  gantt: { useMaxWidth: true },
  er: { useMaxWidth: true },
}

/** 缓存键：改了源码、mermaid 版本、主题或字体族的任何一项都会产生新的 SVG。 */
export function mermaidKey(src) {
  const norm = String(src).replace(/\r\n/g, '\n').replace(/[ \t]+$/gm, '').trimEnd() + '\n'
  const seed = JSON.stringify({ schema: 2, mermaid: MERMAID_VERSION || '?', config: MERMAID_CONFIG, src: norm })
  return crypto.createHash('sha256').update(seed).digest('hex').slice(0, 16)
}

export function cachePath(key) {
  return path.join(CACHE_DIR, key + '.svg')
}

/** 读缓存；没有则返回 null。 */
export function readCache(key) {
  try { return fs.readFileSync(cachePath(key), 'utf8') } catch { return null }
}

export function writeCache(key, svg) {
  fs.mkdirSync(CACHE_DIR, { recursive: true })
  fs.writeFileSync(cachePath(key), svg, 'utf8')
}

// ───────────────────────── SVG 收尾 ─────────────────────────
// 去掉 mermaid 输出的固定宽高与 style（改为 viewBox + CSS 的 max-width:100%），
// 换成稳定 id（缓存文件两次构建字节一致），其余属性（role / aria / aria-roledescription）原样保留。
export function sanitizeSvg(svg, key) {
  const s = String(svg).trim()
  const m = s.match(/^<svg\b([^>]*)>/)
  if (!m) throw new Error('mermaid 输出不是以 <svg> 开头')
  const attrs = m[1]
  const viewBox = (attrs.match(/\bviewBox="([^"]+)"/) || [])[1]
  if (!viewBox) throw new Error('mermaid 输出的 <svg> 没有 viewBox')
  const rest = attrs
    .replace(/\s(?:width|height|style|id|class|viewBox)="[^"]*"/g, '')
    .replace(/\s+/g, ' ')
    .trim()
  const open = `<svg id="mmd-${key}" class="mermaid-svg" data-mmd="${key}"${rest ? ' ' + rest : ''} viewBox="${viewBox}">`
  const body = s.slice(m[0].length)
  if (body.includes('<script')) throw new Error('mermaid 输出里出现 <script>，拒绝内嵌')
  return open + body
}

// ───────────────────────── 找本机浏览器 ─────────────────────────
function firstExisting(list) {
  for (const p of list) if (p && fs.existsSync(p)) return p
  return ''
}

export function findBrowser(explicit) {
  const env = explicit || process.env.PUPPETEER_EXECUTABLE_PATH || process.env.MERMAID_BROWSER || process.env.CHROME_PATH
  if (env) {
    if (!fs.existsSync(env)) throw new Error(`指定的浏览器不存在：${env}`)
    return env
  }
  const pf = process.env.ProgramFiles || 'C:\\Program Files'
  const pf86 = process.env['ProgramFiles(x86)'] || 'C:\\Program Files (x86)'
  const local = process.env.LOCALAPPDATA || ''
  return firstExisting([
    path.join(pf, 'Google/Chrome/Application/chrome.exe'),
    path.join(pf86, 'Google/Chrome/Application/chrome.exe'),
    local && path.join(local, 'Google/Chrome/Application/chrome.exe'),
    path.join(pf, 'Microsoft/Edge/Application/msedge.exe'),
    path.join(pf86, 'Microsoft/Edge/Application/msedge.exe'),
    path.join(pf, 'Chromium/Application/chrome.exe'),
    '/usr/bin/google-chrome',
    '/usr/bin/google-chrome-stable',
    '/usr/bin/chromium',
    '/usr/bin/chromium-browser',
    '/snap/bin/chromium',
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
  ])
}

const NO_BROWSER_HINT =
  'mermaid 缓存缺失，且本机找不到可用的 Chrome/Edge（也可用环境变量 PUPPETEER_EXECUTABLE_PATH 指定）。\n' +
  '  请先在装有浏览器的机器上构建一次，把生成的 site/mermaid/<hash>.svg 提交入库，CI 就不再需要浏览器。'

// ───────────────────────── 渲染 ─────────────────────────
/**
 * 渲染一批 mermaid 源码。返回 Map<key, svg>；调用方负责写缓存。
 * @param {{key: string, src: string}[]} items
 * @param {{browser?: string, timeoutMs?: number, onProgress?: (i: number, n: number) => void}} [opts]
 */
export async function renderMermaid(items, opts = {}) {
  if (!items.length) return new Map()
  if (!MERMAID_VERSION) throw new Error(`缺 mermaid 依赖：${MERMAID_PKG} 不存在，先 npm ci（或 npm install）`)
  if (!fs.existsSync(MERMAID_BUNDLE)) throw new Error(`缺 mermaid 浏览器包：${MERMAID_BUNDLE}`)
  const exe = findBrowser(opts.browser)
  if (!exe) throw new Error(NO_BROWSER_HINT)
  const puppeteer = (await import('puppeteer-core')).default

  const timeout = opts.timeoutMs || 120000
  const browser = await puppeteer.launch({
    executablePath: exe,
    headless: true,
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu', '--hide-scrollbars', '--mute-audio'],
  })
  try {
    const page = await browser.newPage()
    page.setDefaultTimeout(timeout)
    await page.setViewport({ width: 1280, height: 900, deviceScaleFactor: 1 })
    await page.setContent('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"></head><body></body></html>', { waitUntil: 'load' })
    await page.addScriptTag({ content: fs.readFileSync(MERMAID_BUNDLE, 'utf8') })
    const hasApi = await page.evaluate(() => Boolean(window.mermaid || (window.__esbuild_esm_mermaid_nm && window.__esbuild_esm_mermaid_nm.mermaid)))
    if (!hasApi) throw new Error('mermaid.min.js 加载后找不到全局 API')

    const out = new Map()
    // 一张一张渲染，报错能定位到具体是哪张图。
    const n = items.length
    for (let i = 0; i < n; i++) {
      const it = items[i]
      if (opts.onProgress) opts.onProgress(i, n)
      const res = await page.evaluate(async ({ config, id, src }) => {
        const mermaid = window.mermaid || window.__esbuild_esm_mermaid_nm.mermaid
        mermaid.initialize({ ...config, startOnLoad: false })
        try {
          const r = await mermaid.render(id, src)
          return { ok: true, svg: r.svg }
        } catch (e) {
          return { ok: false, err: String((e && (e.message || e.str)) || e).slice(0, 1200) }
        }
      }, { config: MERMAID_CONFIG, id: 'mmd-' + it.key, src: it.src })
      if (!res.ok) throw new Error(`mermaid 渲染失败（key ${it.key}）：${res.err}\n  源码：\n${it.src}`)
      out.set(it.key, sanitizeSvg(res.svg, it.key))
    }
    return out
  } finally {
    await browser.close().catch(() => {})
  }
}
