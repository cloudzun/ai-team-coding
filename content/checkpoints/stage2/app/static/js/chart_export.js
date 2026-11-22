/* 城市经营看板 · 图表导出窗口（window.__chartExport）
 *
 * 只读取两类来源：
 *   1. 已渲染的图表实例（ECharts getOption() 的当前配置）——系列名、点位与数值；
 *   2. 页面节点（KPI 卡的显示文字、选区控件的当前值、区块标题）——显示文本与筛选状态。
 * 不重新请求接口，也不转发后端返回的原始数据。
 *
 * 返回值结构见课程接口约定第 2 节：
 *   { page, filters, kpis: [{id, value, label}], charts: [{id, title, series: [{name, points: [{x, value, label}]}]}] }
 */
(function () {
  'use strict';

  var PAGE = 'dashboard';
  var ROUND = 1e6;          // 导出数值统一保留 6 位小数，去掉二进制浮点噪声

  // 图表 id → 所属页面区块 → 取数方式
  var CHARTS = [
    { id: 'trend',        view: 'trend',        kind: 'category' },
    { id: 'compare',      view: 'compare',      kind: 'category' },
    { id: 'channel',      view: 'structure',    kind: 'category' },
    { id: 'roomtype',     view: 'structure',    kind: 'pie' },
    { id: 'distribution', view: 'distribution', kind: 'boxplot' },
    { id: 'geo',          view: 'geo',          kind: 'xy' }
  ];

  // 箱线图每个箱体导出为五条系列，顺序与 ECharts boxplot 的数据列一致
  var BOX_FIELDS = ['最小值', '下四分位', '中位数', '上四分位', '最大值'];

  // KPI 卡（页面 data-kpi 属性）→ 导出 id
  var KPI_CARDS = [
    { card: 'occupancy', id: 'occupancy_latest' },
    { card: 'adr',       id: 'adr_latest' },
    { card: 'revpar',    id: 'revpar_latest' },
    { card: 'rating',    id: 'rating_latest' }
  ];

  function isNum(x) { return typeof x === 'number' && isFinite(x); }
  function round(x) { return isNum(x) ? Math.round(x * ROUND) / ROUND : null; }
  function text(el) { return el ? (el.textContent || '').trim() : ''; }

  // 把页面显示的文本还原成数值：百分比按小数、金额去符号、评分按小数。
  // 还原不出数字（“—”“样本不足”等）时返回 null，显示文本仍保留在 label 里。
  function parseDisplay(raw) {
    var t = String(raw == null ? '' : raw).trim().replace(/\s+/g, '');
    if (!t || t === '—' || t === '-' || t === '--') return null;
    var pct = /^(-?\d+(?:\.\d+)?)%$/.exec(t);
    if (pct) return round(parseFloat(pct[1]) / 100);
    var money = /^¥(-?\d+(?:\.\d+)?)$/.exec(t);
    if (money) return round(parseFloat(money[1]));
    var plain = /^-?\d+(?:\.\d+)?$/.exec(t);
    if (plain) return round(parseFloat(t));
    return null;
  }

  function viewSection(view) { return document.querySelector('[data-view="' + view + '"]'); }

  // 区块标题取页面 h2 的正文（不含 <small> 副标题）
  function viewTitle(view) {
    var sec = viewSection(view);
    if (!sec) return null;
    var h = sec.querySelector('.view-head h2');
    if (!h) return null;
    var t = '';
    for (var i = 0; i < h.childNodes.length; i += 1) {
      if (h.childNodes[i].nodeType === 3) t += h.childNodes[i].textContent;
    }
    t = t.trim();
    return t || text(h) || null;
  }

  function chartInstance(id) {
    var d = window.dashboard;
    return d && d.charts ? d.charts[id] : null;
  }

  // 图表实例的当前配置；未渲染过（清空状态）时返回 null
  function chartOption(id) {
    var chart = chartInstance(id);
    if (!chart) return null;
    var opt;
    try { opt = chart.getOption(); } catch (e) { return null; }
    if (!opt || !Array.isArray(opt.series) || !opt.series.length) return null;
    return opt;
  }

  function categories(opt) {
    var ax = opt.xAxis;
    var first = Array.isArray(ax) ? ax[0] : ax;
    return first && Array.isArray(first.data) ? first.data : [];
  }

  function pointsOf(data, xs) {
    var out = [];
    for (var i = 0; i < data.length; i += 1) {
      var d = data[i];
      if (d === null || d === undefined) continue;
      var v = (typeof d === 'object' && !Array.isArray(d)) ? d.value : d;
      var x = xs[i];
      out.push({
        x: x === undefined || x === null ? String(i) : String(x),
        value: round(v),
        label: null            // 折线、柱状、散点不在画布上标注数值
      });
    }
    return out;
  }

  // 类目轴 + 数值系列（折线、柱状、散点）
  function readCategory(opt) {
    var xs = categories(opt);
    return opt.series.map(function (s) {
      return { name: s.name || '', points: pointsOf(Array.isArray(s.data) ? s.data : [], xs) };
    });
  }

  // 饼图：一个系列，点名作图，标签是画布上实际显示的百分比文本
  function readPie(opt) {
    var s = opt.series[0] || {};
    var items = Array.isArray(s.data) ? s.data : [];
    var total = 0;
    items.forEach(function (it) { if (it && isNum(it.value)) total += it.value; });
    var fmt = s.label && typeof s.label.formatter === 'function' ? s.label.formatter : null;
    var points = items.map(function (it) {
      var percent = total > 0 && isNum(it.value) ? (it.value / total) * 100 : 0;
      var label = null;
      if (fmt) {
        try { label = fmt({ name: it.name, value: it.value, percent: percent }); } catch (e) { label = null; }
        if (typeof label !== 'string') label = null;
      }
      if (label === null) label = percent.toFixed(1) + '%';
      return { x: String(it.name), value: round(it.value), label: label };
    });
    return [{ name: s.name || '', points: points }];
  }

  // 箱线图：每个箱体拆成五条系列，数值取自已渲染的数据列
  function readBoxplot(opt) {
    var xs = categories(opt);
    var s = opt.series[0] || {};
    var rows = Array.isArray(s.data) ? s.data : [];
    return BOX_FIELDS.map(function (name, k) {
      var points = [];
      for (var i = 0; i < rows.length; i += 1) {
        var row = rows[i];
        var cell = Array.isArray(row) ? row[k] : (row && Array.isArray(row.value) ? row.value[k] : null);
        points.push({ x: xs[i] === undefined ? String(i) : String(xs[i]), value: round(cell), label: null });
      }
      return { name: name, points: points };
    });
  }

  // 经纬度散点：每个区一条系列，点名为房源编号，数值取纬度（经度已作为横轴，页面提示里同时显示两者）
  function readXY(opt) {
    return opt.series.map(function (s) {
      var rows = Array.isArray(s.data) ? s.data : [];
      var points = [];
      rows.forEach(function (r) {
        if (!Array.isArray(r) || r.length < 2) return;
        points.push({ x: String(r[2] === undefined ? r[0] : r[2]), value: round(r[1]), label: null });
      });
      return { name: s.name || '', points: points };
    });
  }

  function readChart(def) {
    var opt = chartOption(def.id);
    var series = [];
    if (opt) {
      if (def.kind === 'pie') series = readPie(opt);
      else if (def.kind === 'boxplot') series = readBoxplot(opt);
      else if (def.kind === 'xy') series = readXY(opt);
      else series = readCategory(opt);
    }
    return { id: def.id, title: viewTitle(def.view), series: series };
  }

  function readKpis() {
    return KPI_CARDS.map(function (k) {
      var card = document.querySelector('[data-kpi="' + k.card + '"]');
      var el = card ? card.querySelector('[data-field="value"]') : null;
      var shown = text(el);
      // 卡片渲染时把未截断的数值写在节点的 data-value 上；没有该属性时退回读显示文字
      var exact = el && el.hasAttribute ? el.getAttribute('data-value') : null;
      var value;
      if (exact === null || exact === undefined) value = parseDisplay(shown);
      else value = exact === '' ? null : round(parseFloat(exact));
      if (!isNum(value)) value = null;
      return {
        id: k.id,
        value: value,
        label: shown && shown !== '—' ? shown : null
      };
    });
  }

  function readFilters() {
    var el = document.querySelector('[data-current-district]');
    return { district: text(el) || null };
  }

  function build() {
    return {
      page: PAGE,
      filters: readFilters(),
      kpis: readKpis(),
      charts: CHARTS.map(readChart)
    };
  }

  // 切区后各视角要重新取数；等它们不再是“加载中”再导出，避免拿到上一轮的数字
  function pending() {
    var n = 0;
    document.querySelectorAll('[data-view]').forEach(function (el) {
      if (el.getAttribute('data-state') === 'loading') n += 1;
    });
    return n;
  }

  function waitIdle(timeoutMs) {
    return new Promise(function (resolve) {
      var started = Date.now();
      (function tick() {
        if (!pending() || Date.now() - started > timeoutMs) { resolve(); return; }
        setTimeout(tick, 100);
      }());
    });
  }

  window.__chartExport = function () {
    return waitIdle(4000).then(build);
  };
}());
