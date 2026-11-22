// @local/dsh-homestay — 薄插件：把本机 homestay-l1 后端（FastAPI）的只读接口包成 4 个对话工具。
//
// The business logic (metrics, YoY, prior-year date rule, market baseline) stays in FastAPI
// (127.0.0.1:8801). This Host plugin registers 4 read-only model-facing tools that call the
// service over HTTP with the runtime's fetch, select / filter / sort / slice the payload,
// render model-facing text, and project card data through output.presentationMeta
// （卡片展示契约见课程材料）。插件不对指标做任何算术。
//
// 格式化只在这里做一次：每个展示字符串——给模型看的 render 文本，以及 presentationMeta 里的
// 文本（text.*、labelText、坐标轴刻度、标题、脚注、表格单元格）——都由本文件生成；
// client.js 只负责把现成的串画出来。
//
// API sources (DSH 0.2.2-rc.3 docs/cookbook/adding-a-tool.md; dsh-tools/src/contracts.ts):
//   ctx.tools.register({ name, description, parameters, output: { schema, render, presentationMeta },
//   isConcurrencySafe, execute }); execute returns one canonical lossless-JSON value; presentationMeta
//   会随结果存进 meta；要响应 exec.signal。不声明 timeoutMs，超时由请求层自己控制。

export const name = 'dsh-homestay'
export const inject = ['tools']

const DEFAULT_BASE = 'http://127.0.0.1:8801'
const MIN_DAY = '2024-10-01'
const MAX_DAY = '2026-09-30'
const MIN_MONTH = '2024-10'
const MAX_MONTH = '2026-09'
const DEFAULT_FROM = '2025-10'
const DEFAULT_TO = '2026-09'
const MAX_SPAN_MONTHS = 24
const GET_TIMEOUT_MS = 8000
const ASK_TIMEOUT_MS = 120000
const ASK_ROWS = 20
const META_LIMIT_BYTES = 32 * 1024
const DAY_RE = /^\d{4}-\d{2}-\d{2}$/
const MONTH_RE = /^\d{4}-(0[1-9]|1[0-2])$/

/**
 * 按实际服务地址拼“启动后端”的提示：端口取自 config.baseUrl（缺省才用 DEFAULT_BASE 的端口），
 * 不把某个端口写死在文案里；地址里没写端口就给不含端口的通用提示。
 */
function startHint(base) {
  try {
    const url = new URL(base)
    if (url.port) {
      return `请先在项目目录启动：.venv\\Scripts\\uvicorn app.main:app --host ${url.hostname || '127.0.0.1'} --port ${url.port} --no-access-log`
    }
  } catch { /* 不是带端口的绝对地址：落到下面的通用提示 */ }
  return '请按 README 启动后端，端口与插件配置一致'
}

// ------------------------------------------------------------------ 错误码
// The message always starts with `[<code>] ` so the code survives as text even when the
// 结构化 error.code 拿不到时也能从文本里取到码。惰性尝试宿主提供的 HarnessError
// (no top-level await); fall back to a look-alike class.
let harnessErrorSource = 'unresolved'
let HomestayError = makeErrorClass(class HarnessError extends Error {
  constructor(message, code, options) {
    super(message, options)
    this.code = code
    this.name = new.target.name
  }
})
let resolving

function makeErrorClass(Base) {
  return class HomestayError extends Base {
    constructor(message, code, options) {
      super(`[${code}] ${message}`, code, options)
      this.name = 'HomestayError'
    }
  }
}

async function ensureErrorClass() {
  resolving ??= import('@deepseek-ai/dsh-error').then(
    (mod) => {
      if (typeof mod?.HarnessError === 'function') {
        HomestayError = makeErrorClass(mod.HarnessError)
        harnessErrorSource = '@deepseek-ai/dsh-error'
      } else harnessErrorSource = 'fallback'
    },
    () => { harnessErrorSource = 'fallback' },
  )
  await resolving
}

const fail = (code, message, options) => { throw new HomestayError(message, code, options) }
const argsError = message => fail('E_HOMESTAY_ARGS', message)

// ------------------------------------------------------------------ 格式化
// half-up away from zero on the shortest decimal representation (String(v) == Python repr),
// done with decimal-string / BigInt arithmetic — no toFixed, no Math.round(v * 10^n).
const DASH = '—'
const isNum = v => typeof v === 'number' && Number.isFinite(v)

/** |v| * 10^shift rounded half-up to `places` decimals → { neg, text } (text has no sign). */
function roundDecimal(v, shift, places) {
  let s = String(v)
  let neg = false
  if (s[0] === '-') { neg = true; s = s.slice(1) }
  let exp = 0
  const e = s.search(/e/i)
  if (e >= 0) { exp = Number(s.slice(e + 1)); s = s.slice(0, e) }
  const dot = s.indexOf('.')
  if (dot >= 0) { exp -= s.length - dot - 1; s = s.slice(0, dot) + s.slice(dot + 1) }
  // value = s * 10^exp; we want N = round(value * 10^(shift + places))
  const k = exp + shift + places
  let n
  if (k >= 0) n = BigInt(s + '0'.repeat(k))
  else {
    const cut = -k
    const padded = s.padStart(cut + 1, '0')
    const head = padded.slice(0, padded.length - cut)
    n = BigInt(head) + (padded[padded.length - cut] >= '5' ? 1n : 0n)
  }
  const digits = n.toString().padStart(places + 1, '0')
  const text = places > 0 ? `${digits.slice(0, digits.length - places)}.${digits.slice(digits.length - places)}` : digits
  return { neg: neg && n !== 0n, text }
}

const signed = r => `${r.neg ? '-' : '+'}${r.text}`
const unsigned = r => `${r.neg ? '-' : ''}${r.text}`

export const format = Object.freeze({
  /** 0–1 比例 → 保留 1 位小数的百分比 */
  ratio: v => (isNum(v) ? `${unsigned(roundDecimal(v, 2, 1))}%` : DASH),
  /** 比值差 → 带符号的百分点，保留 1 位小数 */
  pp: v => (isNum(v) ? `${signed(roundDecimal(v, 2, 1))}pp` : DASH),
  /** 变化率 → 带符号的百分比，保留 1 位小数 */
  pct: v => (isNum(v) ? `${signed(roundDecimal(v, 2, 1))}%` : DASH),
  /** 金额 → 取整后加 ¥ */
  yuan: v => (isNum(v) ? `¥${unsigned(roundDecimal(v, 0, 0))}` : DASH),
  /** 评分 → 保留 2 位小数 */
  score: v => (isNum(v) ? unsigned(roundDecimal(v, 0, 2)) : DASH),
  /** ask table cell: raw String(v), null → — */
  cell: v => (v === null || v === undefined || (typeof v === 'number' && !Number.isFinite(v)) ? DASH : String(v)),
})

/** Axis tick text for a ratio axis: whole percents drop the `.0` (`0%`, `25%`, `12.5%`). */
function ratioTick(v) {
  const r = roundDecimal(v, 2, 1)
  return `${unsigned({ neg: r.neg, text: r.text.endsWith('.0') ? r.text.slice(0, -2) : r.text })}%`
}

// ------------------------------------------------------------------ 坐标轴（3–6 个刻度）
const tickNumber = (mant, exp) => Number(`${mant}e${exp}`)

function makeAxis(min, max, ticks, fmt) {
  return { min, max, ticks: ticks.map(value => ({ value, text: fmt(value) })) }
}

/** Fixed 0–1 axis for ratio metrics (compare occupancy, communities sort=occupancy). */
function ratioAxis() {
  return makeAxis(0, 1, [0, 0.25, 0.5, 0.75, 1], ratioTick)
}

/** Nice outward-rounded axis with 3–6 ticks; includeZero forces min ≤ 0 ≤ max. */
function niceAxis(values, includeZero, fmt) {
  const vals = values.filter(isNum)
  let lo = vals.length ? Math.min(...vals) : 0
  let hi = vals.length ? Math.max(...vals) : 1
  if (includeZero) { lo = Math.min(lo, 0); hi = Math.max(hi, 0) }
  if (!(hi > lo)) {
    const pad = hi === 0 ? 1 : Math.abs(hi) * 0.1
    lo -= includeZero && lo === 0 ? 0 : pad
    hi += pad
    if (includeZero) { lo = Math.min(lo, 0); hi = Math.max(hi, 0) }
  }
  const span = hi - lo
  const steps = [[1, 0], [2, 0], [25, -1], [5, 0]]
  for (let k = Math.floor(Math.log10(span)) - 2; k < 20; k++) {
    for (const [m, de] of steps) {
      const e = k + de
      const step = tickNumber(m, e)
      const a = Math.floor(lo / step + 1e-9)
      const b = Math.ceil(hi / step - 1e-9)
      if (b - a + 1 > 6) continue
      const last = Math.max(b, a + 2)
      const ticks = []
      for (let i = a; i <= last; i++) ticks.push(tickNumber(i * m, e))
      return makeAxis(ticks[0], ticks[ticks.length - 1], ticks, fmt)
    }
  }
  return makeAxis(lo, hi, [lo, hi, hi], fmt) /* unreachable for finite spans */
}

/** Symmetric axis around zero (communities sort=yoy): -M, 0, +M with M a nice ceiling. */
function symmetricAxis(values, fmt) {
  const vals = values.filter(isNum)
  const m = vals.length ? Math.max(...vals.map(Math.abs)) : 0
  let M = 0.1
  if (m > 0) {
    const k = Math.floor(Math.log10(m))
    M = tickNumber(1, k + 1)
    for (const c of [10, 20, 25, 30, 40, 50, 60, 80, 100]) {
      const cand = tickNumber(c, k - 1)
      if (cand >= m - 1e-12) { M = cand; break }
    }
  }
  return makeAxis(-M, M, [-M, 0, M], fmt)
}

// ------------------------------------------------------------------ args (no request on failure)
function validDay(value) {
  if (typeof value !== 'string' || !DAY_RE.test(value)) return false
  const d = new Date(`${value}T00:00:00Z`)
  return !Number.isNaN(d.getTime()) && d.toISOString().slice(0, 10) === value
}

function checkPeriod(args) {
  const start = typeof args?.start === 'string' ? args.start.trim() : args?.start
  const end = typeof args?.end === 'string' ? args.end.trim() : args?.end
  if (!validDay(start)) argsError(`start 必须是 YYYY-MM-DD 合法日期，收到 ${JSON.stringify(args?.start ?? null)}`)
  if (!validDay(end)) argsError(`end 必须是 YYYY-MM-DD 合法日期，收到 ${JSON.stringify(args?.end ?? null)}`)
  if (!(MIN_DAY <= start && start <= end && end <= MAX_DAY)) {
    argsError(`期间须满足 ${MIN_DAY} ≤ start ≤ end ≤ ${MAX_DAY}（收到 start=${start}，end=${end}）`)
  }
  return { start, end }
}

const blank = v => v === undefined || v === null || (typeof v === 'string' && v.trim() === '')

function pickEnum(args, key, allowed, fallback) {
  const raw = args?.[key]
  if (blank(raw)) return fallback
  const v = typeof raw === 'string' ? raw.trim() : raw
  if (!allowed.includes(v)) argsError(`${key} 只能是 ${allowed.join(' / ')}，收到 ${JSON.stringify(raw)}`)
  return v
}

function pickDistrict(args) {
  const raw = args?.district
  if (blank(raw)) return null
  if (typeof raw !== 'string') argsError(`district 必须是区编号（D01–D08）或区名，收到 ${JSON.stringify(raw)}`)
  return raw.trim()
}

const monthIndex = ym => Number(ym.slice(0, 4)) * 12 + Number(ym.slice(5, 7)) - 1
const monthKey = idx => `${Math.floor(idx / 12)}-${String((idx % 12) + 1).padStart(2, '0')}`

function checkCompare(args) {
  const { start, end } = checkPeriod(args)
  const metric = pickEnum(args, 'metric', ['occupancy', 'adr'], 'occupancy')
  return { start, end, metric }
}

function checkTrend(args) {
  const district = pickDistrict(args)
  const metric = pickEnum(args, 'metric', ['occupancy', 'adr', 'revpar', 'rating'], 'occupancy')
  const pickMonth = (key, fallback) => {
    const raw = args?.[key]
    if (blank(raw)) return fallback
    const v = typeof raw === 'string' ? raw.trim() : raw
    if (typeof v !== 'string' || !MONTH_RE.test(v)) argsError(`${key} 必须是 YYYY-MM 月份，收到 ${JSON.stringify(raw)}`)
    return v
  }
  const from = pickMonth('from', DEFAULT_FROM)
  const to = pickMonth('to', DEFAULT_TO)
  if (!(MIN_MONTH <= from && from <= to && to <= MAX_MONTH)) {
    argsError(`月份须满足 ${MIN_MONTH} ≤ from ≤ to ≤ ${MAX_MONTH}（数据截至 ${MAX_MONTH}；收到 from=${from}，to=${to}）`)
  }
  if (monthIndex(to) - monthIndex(from) + 1 > MAX_SPAN_MONTHS) {
    argsError(`from 至 to 跨度不能超过 ${MAX_SPAN_MONTHS} 个月（收到 ${from} ~ ${to}）`)
  }
  return { district, metric, from, to }
}

function checkCommunities(args) {
  const { start, end } = checkPeriod(args)
  const district = pickDistrict(args)
  const sort = pickEnum(args, 'sort', ['yoy', 'occupancy'], 'yoy')
  const order = pickEnum(args, 'order', ['asc', 'desc'], 'asc')
  let limit = 10
  if (!blank(args?.limit)) {
    limit = args.limit
    if (!Number.isInteger(limit) || limit < 1 || limit > 20) argsError(`limit 必须是 1–20 的整数，收到 ${JSON.stringify(args.limit)}`)
  }
  return { start, end, district, sort, order, limit }
}

function checkAsk(args) {
  const raw = args?.question
  if (typeof raw !== 'string') argsError(`question 必须是字符串，收到 ${JSON.stringify(raw ?? null)}`)
  const question = raw.trim()
  const n = Array.from(question).length
  if (n < 1 || n > 200) argsError(`question 去掉首尾空白后须为 1–200 字（收到 ${n} 字）`)
  return { question }
}

// ------------------------------------------------------------------ HTTP (whitelist only)
function makeHttp(config) {
  const base = typeof config?.baseUrl === 'string' && config.baseUrl.trim() !== ''
    ? config.baseUrl.trim().replace(/\/+$/, '')
    : DEFAULT_BASE
  // Resolve fetch at call time so a replaced globalThis.fetch (acceptance recorder) is honored.
  const doFetch = typeof config?.fetch === 'function' ? config.fetch : (...a) => globalThis.fetch(...a)

  async function request(method, path, { body, timeoutMs, signal }) {
    const timeout = AbortSignal.timeout(timeoutMs)
    const combined = signal ? AbortSignal.any([signal, timeout]) : timeout
    const init = { method, signal: combined, headers: { accept: 'application/json' } }
    if (body !== undefined) {
      init.headers['content-type'] = 'application/json; charset=utf-8'
      init.body = JSON.stringify(body)
    }
    let res, text
    try {
      res = await doFetch(`${base}${path}`, init)
      text = await res.text()
    } catch (error) {
      // Caller cancellation propagates unchanged (adding-a-tool.md: honor exec.signal).
      if (signal?.aborted) throw signal.reason ?? error
      if (timeout.aborted) {
        fail('E_HOMESTAY_TIMEOUT', `民宿经营服务 ${base}${path.split('?')[0]} 超过 ${timeoutMs / 1000} 秒未响应，可稍后重试`, { cause: error })
      }
      fail('E_HOMESTAY_DOWN',
        `无法连接民宿经营服务 ${base}（${error?.cause?.code ?? error?.cause?.errors?.[0]?.code ?? error?.cause?.message ?? error?.message ?? 'fetch failed'}）。${startHint(base)}`,
        { cause: error })
    }
    let data
    let parsed = true
    try { data = JSON.parse(text) } catch { parsed = false }
    if (!res.ok) {
      if (res.status === 503 && data?.error === 'E_LLM') {
        fail('E_HOMESTAY_LLM', '问数服务的模型不可达，可稍后重试')
      }
      let detail = parsed && data && data.detail !== undefined ? data.detail : String(text).slice(0, 300)
      if (typeof detail !== 'string') detail = JSON.stringify(detail)
      fail(res.status === 422 ? 'E_HOMESTAY_ARGS' : 'E_HOMESTAY_HTTP', `服务返回 HTTP ${res.status}：${detail}`)
    }
    if (!parsed) fail('E_HOMESTAY_HTTP', `服务返回的不是 JSON（${path.split('?')[0]}）`)
    return data
  }

  return {
    base,
    getDistricts: (start, end, signal) => {
      const qs = start ? `?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}` : ''
      return request('GET', `/api/districts${qs}`, { timeoutMs: GET_TIMEOUT_MS, signal })
    },
    getTrend: (districtId, signal) =>
      request('GET', `/api/trend${districtId ? `?district=${encodeURIComponent(districtId)}` : ''}`, { timeoutMs: GET_TIMEOUT_MS, signal }),
    getCommunities: (start, end, signal) =>
      request('GET', `/api/communities?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`, { timeoutMs: GET_TIMEOUT_MS, signal }),
    postAsk: (question, signal) => request('POST', '/api/ask', { body: { question }, timeoutMs: ASK_TIMEOUT_MS, signal }),
  }
}

const numOrNull = v => (isNum(v) ? v : null)
const shapeError = what => fail('E_HOMESTAY_HTTP', `服务响应缺少必需字段：${what}`)

function districtRows(payload) {
  if (!payload || !Array.isArray(payload.districts)) shapeError('/api/districts 的 districts 数组')
  for (const d of payload.districts) {
    if (!d || typeof d.district_id !== 'string' || typeof d.name !== 'string') shapeError('/api/districts 的 district_id / name')
  }
  return payload.districts
}

/** Resolve D01–D08 or a district name (with or without the trailing 区) via /api/districts. */
async function resolveDistrict(http, input, signal) {
  const rows = districtRows(await http.getDistricts(null, null, signal))
  const key = input.trim()
  const upper = key.toUpperCase()
  const hit = rows.find(d => d.district_id === upper)
    ?? rows.find(d => d.name === key || d.name === `${key}区` || d.name.replace(/区$/, '') === key)
  if (!hit) {
    argsError(`district 对不上：${JSON.stringify(input)}。合法取值为 ${rows.map(d => d.district_id).join('、')}，或区名：${rows.map(d => d.name).join('、')}`)
  }
  return { id: hit.district_id, name: hit.name }
}

// ------------------------------------------------------------------ markdown helpers
const mdCell = s => String(s).replace(/\|/g, '\\|').replace(/\r?\n/g, ' ')
function mdTable(head, rows) {
  return [
    `| ${head.map(mdCell).join(' | ')} |`,
    `|${head.map(() => '---').join('|')}|`,
    ...rows.map(r => `| ${r.map(mdCell).join(' | ')} |`),
  ].join('\n')
}
const textBlocks = text => [{ type: 'text', text }]

// ------------------------------------------------------------------ schemas
const nNum = { oneOf: [{ type: 'number' }, { type: 'null' }] }
const nStr = { oneOf: [{ type: 'string' }, { type: 'null' }] }
const obj = (properties, required = Object.keys(properties)) =>
  (required.length ? { type: 'object', additionalProperties: false, required, properties } : { type: 'object', additionalProperties: false, properties })
const districtRef = { oneOf: [obj({ id: { type: 'string' }, name: { type: 'string' } }), { type: 'null' }] }

// ================================================================== homestay_compare (2.1)
const COMPARE_LABEL = { occupancy: '入住率', adr: '平均房价' }

function compareText(value) {
  const occ = value.metric === 'occupancy'
  const fmtV = occ ? format.ratio : format.yuan
  const fmtY = occ ? format.pp : format.pct
  return value.districts.map(d => ({
    value: fmtV(d.value),
    prevYear: fmtV(d.prevYear),
    yoy: fmtY(d.yoy),
    market: occ ? format.ratio(d.market) : DASH,
  }))
}

function compareRender(_args, value) {
  const occ = value.metric === 'occupancy'
  const texts = compareText(value)
  const head = occ ? ['区', '本期', '上年同期', '同比', '市场基准'] : ['区', '本期', '上年同期', '同比']
  const rows = value.districts.map((d, i) => {
    const t = texts[i]
    return occ ? [d.name, t.value, t.prevYear, t.yoy, t.market] : [d.name, t.value, t.prevYear, t.yoy]
  })
  const note = occ
    ? '口径：入住率同比为百分点差（本期减上年同期）；市场基准为各房型简单平均；— 表示无数据；模拟数据。'
    : '口径：平均房价同比为变化率（两期房价均先舍入到分再算）；— 表示无数据；模拟数据。'
  return textBlocks(`杭州 8 区${COMPARE_LABEL[value.metric]}对比（${value.start} ~ ${value.end}）\n${mdTable(head, rows)}\n${note}`)
}

function compareMeta(_args, value) {
  const occ = value.metric === 'occupancy'
  const texts = compareText(value)
  const series = [{ key: 'cur', label: '本期' }, { key: 'prev', label: '上年同期' }]
  if (occ) series.push({ key: 'market', label: '市场基准' })
  const rows = value.districts.map((d, i) => ({
    key: d.id, name: d.name, value: d.value, prevYear: d.prevYear, market: occ ? d.market : null, text: texts[i],
  }))
  const axis = occ
    ? ratioAxis()
    : niceAxis(value.districts.flatMap(d => [d.value, d.prevYear]), true, format.yuan)
  return {
    kind: 'homestay-compare', v: 2,
    title: `民宿经营对比 · ${COMPARE_LABEL[value.metric]}`,
    subtitle: `${value.start} ~ ${value.end}`,
    footnote: occ ? '模拟数据；入住率同比为百分点差；市场基准为各房型简单平均' : '模拟数据；平均房价同比为变化率',
    metric: value.metric, unit: value.unit, yoyKind: value.yoyKind,
    series, rows, axis,
  }
}

function defineCompare(http) {
  return {
    name: 'homestay_compare',
    description:
      '查询杭州 8 个区民宿经营指标的本期与上年同期对比（数据来自本机民宿经营服务 127.0.0.1:8801，只读）。'
      + 'metric=occupancy（入住率，缺省）返回每区本期、上年同期、同比（百分点差）与市场基准；metric=adr（平均房价）返回本期、上年同期与同比变化率。'
      + `参数 start/end 为 YYYY-MM-DD，须满足 ${MIN_DAY} ≤ start ≤ end ≤ ${MAX_DAY}（数据截至 2026-09-30）。`
      + '界面会把结果画成分组柱状图卡片（本期 / 上年同期，入住率另有市场基准虚线）。服务未启动时报错 E_HOMESTAY_DOWN；参数越界报 E_HOMESTAY_ARGS。',
    parameters: obj({
      start: { type: 'string', description: `期间开始日 YYYY-MM-DD，${MIN_DAY} ≤ start ≤ end` },
      end: { type: 'string', description: `期间结束日 YYYY-MM-DD，end ≤ ${MAX_DAY}` },
      metric: { type: 'string', enum: ['occupancy', 'adr'], description: 'occupancy=入住率（缺省，含市场基准）；adr=平均房价' },
    }, ['start', 'end']),
    output: {
      schema: obj({
        start: { type: 'string' }, end: { type: 'string' },
        metric: { type: 'string', enum: ['occupancy', 'adr'] },
        unit: { type: 'string', enum: ['ratio', 'CNY'] },
        yoyKind: { type: 'string', enum: ['diff', 'pct'] },
        districts: {
          type: 'array',
          items: obj({ id: { type: 'string' }, name: { type: 'string' }, value: nNum, prevYear: nNum, yoy: nNum, market: nNum }),
        },
      }),
      render: compareRender,
      presentationMeta: compareMeta,
    },
    isConcurrencySafe: () => true,
    async execute(args, exec) {
      await ensureErrorClass()
      const { start, end, metric } = checkCompare(args)
      const payload = await http.getDistricts(start, end, exec?.signal)
      const occ = metric === 'occupancy'
      const keys = occ ? ['occupancy', 'occupancy_prev_year', 'occupancy_yoy', 'market_occupancy'] : ['adr', 'adr_prev_year', 'adr_yoy']
      const rows = districtRows(payload)
      for (const d of rows) {
        for (const k of keys) {
          if (!Object.hasOwn(d, k)) {
            shapeError(`/api/districts 的 ${k}${k.startsWith('adr_') ? '（后端跑的还是上一轮的代码：重启服务，端口与插件配置一致）' : ''}`)
          }
        }
      }
      const districts = rows
        .map(d => ({
          id: d.district_id, name: d.name,
          value: numOrNull(d[keys[0]]), prevYear: numOrNull(d[keys[1]]), yoy: numOrNull(d[keys[2]]),
          market: occ ? numOrNull(d.market_occupancy) : null,
        }))
        .sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0))
      return { start, end, metric, unit: occ ? 'ratio' : 'CNY', yoyKind: occ ? 'diff' : 'pct', districts }
    },
  }
}

// ================================================================== homestay_trend (2.2)
const TREND_LABEL = { occupancy: '入住率', adr: '平均房价', revpar: '每间可售房收入(RevPAR)', rating: '评分' }
const TREND_UNIT = { occupancy: 'ratio', adr: 'CNY', revpar: 'CNY', rating: 'score' }
const TREND_FMT = { occupancy: format.ratio, adr: format.yuan, revpar: format.yuan, rating: format.score }
const TREND_TICK = { occupancy: ratioTick, adr: format.yuan, revpar: format.yuan, rating: format.score }

const scopeName = d => (d ? d.name : '全公司')

function trendRender(_args, value) {
  const f = TREND_FMT[value.metric]
  const rows = value.points.map(p => [p.month, f(p.value), f(p.prevYear)])
  const lines = [
    `${scopeName(value.district)} ${TREND_LABEL[value.metric]}月度走势（${value.from} ~ ${value.to}）`,
    mdTable(['月份', '本期', '上年同月'], rows),
  ]
  if (value.metric === 'rating') lines.push('评分有效样本 < 5 条的月份为空（—）。')
  lines.push('模拟数据。')
  return textBlocks(lines.join('\n'))
}

function trendMeta(_args, value) {
  const f = TREND_FMT[value.metric]
  const points = value.points.map(p => ({
    key: p.month, value: p.value, prevYear: p.prevYear, text: { value: f(p.value), prevYear: f(p.prevYear) },
  }))
  const last = points[points.length - 1]
  return {
    kind: 'homestay-trend', v: 2,
    title: `${scopeName(value.district)} ${TREND_LABEL[value.metric]}月度走势`,
    subtitle: `${value.from} ~ ${value.to}`,
    footnote: value.metric === 'rating' ? '模拟数据；评分有效样本 < 5 条的月份为空' : '模拟数据',
    metric: value.metric, unit: value.unit,
    series: [{ key: 'cur', label: '本期' }, { key: 'prev', label: '上年同月' }],
    points,
    latest: last
      ? { key: last.key, labelText: `${last.key} 本期 ${last.text.value} · 上年同月 ${last.text.prevYear}` }
      : { key: value.to, labelText: `${value.to} 本期 ${DASH} · 上年同月 ${DASH}` },
    axis: niceAxis(value.points.flatMap(p => [p.value, p.prevYear]), false, TREND_TICK[value.metric]),
  }
}

function defineTrend(http) {
  return {
    name: 'homestay_trend',
    description:
      '查询民宿经营指标的月度走势（本期与上年同月两条线；数据来自本机民宿经营服务 127.0.0.1:8801，只读）。'
      + 'district 可传 D01–D08 或区名（如该区名称，带不带“区”字都行），不传即全公司；metric：occupancy 入住率（缺省）、adr 平均房价、revpar 每间可售房收入、rating 评分。'
      + `from/to 为 YYYY-MM，须满足 ${MIN_MONTH} ≤ from ≤ to ≤ ${MAX_MONTH}，跨度 ≤ ${MAX_SPAN_MONTHS} 个月。`
      + '数据截至 2026-09；‘最近 N 个月’以 2026-09 为终点；不传 from/to 即最近 12 个月（2025-10 至 2026-09）。'
      + '界面会把结果画成双折线卡片。服务未启动时报错 E_HOMESTAY_DOWN；参数越界或区名对不上报 E_HOMESTAY_ARGS。',
    parameters: obj({
      district: { type: 'string', description: '区编号 D01–D08 或区名；不传 = 全公司' },
      metric: { type: 'string', enum: ['occupancy', 'adr', 'revpar', 'rating'], description: 'occupancy=入住率（缺省）；adr=平均房价；revpar=每间可售房收入；rating=评分' },
      from: { type: 'string', description: `开始月份 YYYY-MM，≥ ${MIN_MONTH}；缺省 ${DEFAULT_FROM}` },
      to: { type: 'string', description: `结束月份 YYYY-MM，≤ ${MAX_MONTH}（数据截至 2026-09）；缺省 ${DEFAULT_TO}` },
    }, []),
    output: {
      schema: obj({
        district: districtRef,
        metric: { type: 'string', enum: ['occupancy', 'adr', 'revpar', 'rating'] },
        unit: { type: 'string', enum: ['ratio', 'CNY', 'score'] },
        from: { type: 'string' }, to: { type: 'string' },
        points: { type: 'array', items: obj({ month: { type: 'string' }, value: nNum, prevYear: nNum }) },
      }),
      render: trendRender,
      presentationMeta: trendMeta,
    },
    isConcurrencySafe: () => true,
    async execute(args, exec) {
      await ensureErrorClass()
      const { district, metric, from, to } = checkTrend(args)
      const signal = exec?.signal
      const ref = district ? await resolveDistrict(http, district, signal) : null
      const payload = await http.getTrend(ref?.id ?? null, signal)
      if (!payload || !Array.isArray(payload.months) || !Array.isArray(payload[metric]) || payload[metric].length !== payload.months.length) {
        shapeError(`/api/trend 的 months / ${metric}`)
      }
      const byMonth = new Map(payload.months.map((m, i) => [m, numOrNull(payload[metric][i])]))
      // prevYear = 同一条序列上月份键 − 12 的那一点（查同月键，不做区间平移）
      const points = payload.months
        .filter(m => typeof m === 'string' && from <= m && m <= to)
        .sort()
        .map(m => {
          const prevKey = monthKey(monthIndex(m) - 12)
          return { month: m, value: byMonth.get(m), prevYear: byMonth.has(prevKey) ? byMonth.get(prevKey) : null }
        })
      return { district: ref, metric, unit: TREND_UNIT[metric], from, to, points }
    },
  }
}

// ================================================================== homestay_communities (2.3)
function cmpCodePoint(a, b) {
  const x = Array.from(a), y = Array.from(b)
  const n = Math.min(x.length, y.length)
  for (let i = 0; i < n; i++) {
    const d = x[i].codePointAt(0) - y[i].codePointAt(0)
    if (d) return d
  }
  return x.length - y.length
}

const COMM_SORT_LABEL = { yoy: '入住率同比', occupancy: '入住率' }

function commTitle(value) {
  const ext = value.order === 'asc' ? '最低' : '最高'
  return `${scopeName(value.district)}小区${COMM_SORT_LABEL[value.sort]}${ext} ${value.rows.length} 个`
}
const commSubtitle = value => `${value.start} ~ ${value.end} · 在线房源截至 ${value.asOf}`
const commCountText = value => `共 ${value.rows.length} 行（符合条件的小区 ${value.matched} 个）`

function commText(value) {
  return value.rows.map(r => ({
    bar: value.sort === 'yoy' ? format.pp(r.yoy) : format.ratio(r.occupancy),
    occupancy: format.ratio(r.occupancy),
    prevYear: format.ratio(r.prevYear),
    yoy: format.pp(r.yoy),
    listings: format.cell(r.listings),
  }))
}

function communitiesRender(_args, value) {
  const texts = commText(value)
  const rows = value.rows.map((r, i) => [r.community, r.districtId, texts[i].listings, texts[i].occupancy, texts[i].prevYear, texts[i].yoy])
  return textBlocks([
    `${commTitle(value)}（${value.start} ~ ${value.end}，在线房源截至 ${value.asOf}）`,
    mdTable(['小区', '所属区编号', '在线房源', '本期入住率', '上年同期', '同比'], rows),
    `${commCountText(value)}；同比为百分点差；— 表示无数据。`,
    '小区为模拟名称；模拟数据。',
  ].join('\n'))
}

function communitiesMeta(_args, value) {
  const texts = commText(value)
  const rows = value.rows.map((r, i) => ({
    key: r.community, name: r.community, districtId: r.districtId, listings: r.listings,
    bar: value.sort === 'yoy' ? r.yoy : r.occupancy, text: texts[i],
  }))
  return {
    kind: 'homestay-communities', v: 2,
    title: commTitle(value),
    subtitle: commSubtitle(value),
    footnote: '模拟数据；小区为模拟名称',
    sort: value.sort, order: value.order, matched: value.matched,
    rows,
    axis: value.sort === 'yoy' ? symmetricAxis(rows.map(r => r.bar), format.pp) : ratioAxis(),
    rowCountText: commCountText(value),
  }
}

function defineCommunities(http) {
  return {
    name: 'homestay_communities',
    description:
      '查询小区级民宿入住率与同比排行（数据来自本机民宿经营服务 127.0.0.1:8801，只读；小区为模拟名称）。'
      + `start/end 为 YYYY-MM-DD，须满足 ${MIN_DAY} ≤ start ≤ end ≤ ${MAX_DAY}；district 可传 D01–D08 或区名（如该区名称，带不带“区”字都行），不传即全公司；`
      + 'sort=yoy（入住率同比，缺省）或 occupancy（入住率）；order=asc（缺省，最差在前）或 desc；limit 1–20，缺省 10。'
      + '界面会把结果画成横向条形图（同比零轴居中）加表格。服务未启动时报错 E_HOMESTAY_DOWN；参数越界或区名对不上报 E_HOMESTAY_ARGS。',
    parameters: obj({
      start: { type: 'string', description: `期间开始日 YYYY-MM-DD，${MIN_DAY} ≤ start ≤ end` },
      end: { type: 'string', description: `期间结束日 YYYY-MM-DD，end ≤ ${MAX_DAY}` },
      district: { type: 'string', description: '区编号 D01–D08 或区名；不传 = 全公司' },
      sort: { type: 'string', enum: ['yoy', 'occupancy'], description: 'yoy=按入住率同比（缺省）；occupancy=按本期入住率' },
      order: { type: 'string', enum: ['asc', 'desc'], description: 'asc=从低到高（缺省，最差在前）；desc=从高到低' },
      limit: { type: 'integer', description: '返回条数 1–20，缺省 10' },
    }, ['start', 'end']),
    output: {
      schema: obj({
        start: { type: 'string' }, end: { type: 'string' }, asOf: { type: 'string' },
        district: districtRef,
        sort: { type: 'string', enum: ['yoy', 'occupancy'] },
        order: { type: 'string', enum: ['asc', 'desc'] },
        matched: { type: 'integer' },
        rows: {
          type: 'array',
          items: obj({
            community: { type: 'string' }, districtId: { type: 'string' }, listings: { type: 'integer' },
            occupancy: nNum, prevYear: nNum, yoy: nNum,
          }),
        },
      }),
      render: communitiesRender,
      presentationMeta: communitiesMeta,
    },
    isConcurrencySafe: () => true,
    async execute(args, exec) {
      await ensureErrorClass()
      const { start, end, district, sort, order, limit } = checkCommunities(args)
      const signal = exec?.signal
      const ref = district ? await resolveDistrict(http, district, signal) : null
      const payload = await http.getCommunities(start, end, signal)
      if (!payload || !Array.isArray(payload.communities)) shapeError('/api/communities 的 communities 数组')
      const all = payload.communities.map((c) => {
        if (!c || typeof c.community !== 'string' || typeof c.district_id !== 'string') shapeError('/api/communities 的 community / district_id')
        return {
          community: c.community, districtId: c.district_id,
          listings: Number.isInteger(c.listings) ? c.listings : 0,
          occupancy: numOrNull(c.occupancy), prevYear: numOrNull(c.occupancy_prev_year), yoy: numOrNull(c.occupancy_yoy),
        }
      })
      const field = sort === 'yoy' ? 'yoy' : 'occupancy'
      const dir = order === 'asc' ? 1 : -1
      const kept = all
        .filter(r => !ref || r.districtId === ref.id)
        .filter(r => r[field] !== null)
        .sort((a, b) => (a[field] !== b[field] ? (a[field] < b[field] ? -dir : dir) : cmpCodePoint(a.community, b.community)))
      return {
        start, end,
        asOf: typeof payload.as_of === 'string' ? payload.as_of : end,
        district: ref, sort, order, matched: kept.length,
        rows: kept.slice(0, limit),
      }
    },
  }
}

// ================================================================== homestay_ask (2.4)
/** 选中的步骤 = 最后一条 rows 非空的步骤。 */
const selectedStep = value => [...value.steps].reverse().find(s => s.rows.length > 0) ?? null

// 维度标签列：只有当第 1 列是区 / 小区 / 月份维度时才画条形图。判定方式是按列名查下面这张表，
// 或看取值是否像月份；不再额外发请求去取名字表。列名覆盖 homestay-l1 表结构里的英文标识符
// （districts.district_id/name、listings.community、R01/R02 里的 month/ym 键、period 分桶），
// 再加上问数 SQL 可能产出的中文别名（见下面的 ASK_DIMENSION_COLUMNS）。
//
const ASK_DIMENSION_COLUMNS = new Set([
  'district', 'district_id', 'district_name', 'name', 'community', 'month', 'ym', 'period',
  '区', '区域', '小区', '月份',
])
const MONTH_VALUE_RE = /^\d{4}-\d{2}$/
// 条形图的取值列优先选名字像比率 / 指标的数值列。
const ASK_METRIC_COLUMN_RE = /(occupancy|rate|ratio|share|adr|revpar|price|rating|score|yoy|pct)/

function isDimensionColumn(columnName, rows) {
  if (ASK_DIMENSION_COLUMNS.has(String(columnName).trim().toLowerCase())) return true
  return rows.every(r => typeof r[0] === 'string' && MONTH_VALUE_RE.test(r[0]))
}

function askChart(step, rows) {
  if (!step || rows.length < 2 || rows.length > 20 || step.columns.length < 2) return null
  if (!rows.every(r => typeof r[0] === 'string')) return null
  if (!isDimensionColumn(step.columns[0], rows)) return null
  // 取值列：数值列里优先取最后一列“名字像比率 / 指标”的
  // ratio / metric; otherwise the LAST numeric column (SQL convention: result metric comes last).
  const numericCols = []
  for (let j = 1; j < step.columns.length; j++) {
    const vals = rows.map(r => r[j]).filter(v => v !== null && v !== undefined)
    if (vals.length > 0 && vals.every(isNum)) numericCols.push(j)
  }
  if (numericCols.length === 0) return null
  const metricCols = numericCols.filter(j => ASK_METRIC_COLUMN_RE.test(String(step.columns[j]).toLowerCase()))
  const col = (metricCols.length ? metricCols : numericCols).at(-1)
  const seen = new Set()
  const bars = rows.map((r, i) => {
    let key = r[0]
    if (seen.has(key)) key = `${r[0]}#${i + 1}`
    seen.add(key)
    const value = numOrNull(r[col])
    return { key, label: r[0], value, text: format.cell(value) }
  })
  return {
    labelColumn: step.columns[0], valueColumn: step.columns[col], valueLabel: String(step.columns[col]), bars,
    axis: niceAxis(bars.map(b => b.value), true, format.cell),
  }
}

function askTable(step, rows) {
  return {
    columns: step.columns.map(String),
    rows: rows.map(r => step.columns.map((_, j) => format.cell(r[j]))),
    rowCount: step.rowCount,
    truncated: step.truncated || rows.length < step.rowCount,
    rowCountText: `共 ${step.rowCount} 行`,
  }
}

function askRender(_args, value) {
  const parts = [value.answer || '（问数服务没有返回回答文字）']
  if (value.mode !== 'refused') {
    const step = selectedStep(value)
    if (step) {
      const t = askTable(step, step.rows)
      parts.push(`\n${mdTable(t.columns, t.rows)}\n${t.rowCountText}${step.rows.length < step.rowCount ? `（上表只列前 ${step.rows.length} 行）` : ''}`)
    }
    value.steps.forEach((s, i) => {
      if (s.sql) parts.push(`\n第 ${i + 1} 步${s.purpose ? `（${s.purpose}）` : ''} SQL：\n\`\`\`sql\n${s.sql}\n\`\`\``)
    })
    if (value.degraded) parts.push(`\n问数服务已降级（${value.degradeReason ?? '原因未知'}）。`)
  }
  return textBlocks(parts.join('\n'))
}

const jsonBytes = v => new TextEncoder().encode(JSON.stringify(v)).length

function askMeta(_args, value) {
  const refused = value.mode === 'refused'
  const step = refused ? null : selectedStep(value)
  const build = (rowLimit, sqlLimit) => {
    const rows = step ? step.rows.slice(0, rowLimit) : []
    return {
      kind: 'homestay-ask', v: 2,
      title: '民宿问数',
      subtitle: value.question,
      footnote: '模拟数据；回答由模型生成，表格与 SQL 来自问数服务',
      mode: value.mode,
      answerText: value.answer,
      table: step ? askTable(step, rows) : null,
      chart: step ? askChart(step, rows) : null,
      sqls: refused ? [] : value.steps.map(s => s.sql).filter(s => s).map(s => (s.length > sqlLimit ? `${s.slice(0, sqlLimit)}…` : s)),
      degraded: value.degraded,
      degradeText: value.degraded ? `问数服务已降级（${value.degradeReason ?? '原因未知'}），回答可能不完整` : '',
    }
  }
  // ≤ 32 KB：先把每条 SQL 截到 2000 字符，再把表格截到 10 行。
  let meta = build(ASK_ROWS, Infinity)
  if (jsonBytes(meta) > META_LIMIT_BYTES) meta = build(ASK_ROWS, 2000)
  if (jsonBytes(meta) > META_LIMIT_BYTES) meta = build(10, 2000)
  if (jsonBytes(meta) > META_LIMIT_BYTES && meta.table) {
    // Last resort (not expected): shorten long cell strings so the card still fits.
    const cut = s => (s.length > 200 ? `${s.slice(0, 200)}…` : s)
    meta.table.rows = meta.table.rows.map(r => r.map(cut))
    meta.answerText = cut(meta.answerText.length > 4000 ? meta.answerText.slice(0, 4000) : meta.answerText)
  }
  return meta
}

function defineAsk(http) {
  return {
    name: 'homestay_ask',
    description:
      '用自然语言向本机问数服务（127.0.0.1:8801 的 POST /api/ask，只读）提问，适合原因分析、跨表追问等固定工具答不了的问题。'
      + '问数服务会生成只读 SQL、执行并由模型写回答，耗时约 30–90 秒；改数据、删数据等写操作会被拒绝（mode=refused）。'
      + 'question 去掉首尾空白后 1–200 字。界面会显示回答、结果表、条形图（结果适合时）与可展开的 SQL。'
      + '服务未启动时报错 E_HOMESTAY_DOWN；问数模型不可达报 E_HOMESTAY_LLM；超过 120 秒报 E_HOMESTAY_TIMEOUT。',
    parameters: obj({
      question: { type: 'string', description: '中文问题，1–200 字' },
    }),
    output: {
      schema: obj({
        question: { type: 'string' },
        mode: { type: 'string', enum: ['query', 'diagnose', 'refused'] },
        answer: { type: 'string' },
        steps: {
          type: 'array',
          items: obj({
            purpose: { type: 'string' }, sql: { type: 'string' },
            columns: { type: 'array', items: { type: 'string' } },
            rows: { type: 'array', items: { type: 'array' } },
            rowCount: { type: 'integer' }, truncated: { type: 'boolean' },
          }),
        },
        degraded: { type: 'boolean' },
        degradeReason: nStr,
      }),
      render: askRender,
      presentationMeta: askMeta,
    },
    isConcurrencySafe: () => true,
    async execute(args, exec) {
      await ensureErrorClass()
      const { question } = checkAsk(args)
      const data = await http.postAsk(question, exec?.signal)
      if (!data || typeof data !== 'object' || !['query', 'diagnose', 'refused'].includes(data.mode) || !Array.isArray(data.steps ?? [])) {
        shapeError('/api/ask 的 mode / steps')
      }
      const steps = (data.steps ?? []).map((s) => {
        const columns = Array.isArray(s?.columns) ? s.columns.map(String) : []
        const allRows = Array.isArray(s?.rows) ? s.rows.filter(Array.isArray) : []
        const rows = allRows.slice(0, ASK_ROWS).map(r => r.map(v => (v === undefined || (typeof v === 'number' && !Number.isFinite(v)) ? null : v)))
        const rowCount = Number.isInteger(s?.row_count) ? s.row_count : allRows.length
        return {
          purpose: typeof s?.purpose === 'string' ? s.purpose : '',
          sql: typeof s?.sql === 'string' ? s.sql : '',
          columns, rows, rowCount,
          truncated: Boolean(s?.truncated) || rows.length < rowCount,
        }
      })
      const meta = data.meta && typeof data.meta === 'object' ? data.meta : {}
      return {
        question: typeof data.question === 'string' ? data.question : question,
        mode: data.mode,
        answer: typeof data.answer === 'string' ? data.answer : '',
        steps,
        degraded: Boolean(meta.degraded),
        degradeReason: typeof meta.degrade_reason === 'string' ? meta.degrade_reason : null,
      }
    },
  }
}

// ================================================================== registration
/** 一套工具定义，apply() 与验收脚本共用。 */
export function createTools(config) {
  const http = makeHttp(config)
  return {
    homestay_compare: defineCompare(http),
    homestay_trend: defineTrend(http),
    homestay_communities: defineCommunities(http),
    homestay_ask: defineAsk(http),
  }
}

export function apply(ctx, config) {
  for (const def of Object.values(createTools(config))) ctx.tools.register(def)
}

export const __test = {
  createTools,
  format,
  get harnessErrorSource() { return harnessErrorSource },
}
