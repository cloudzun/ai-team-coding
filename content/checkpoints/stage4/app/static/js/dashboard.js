/* 城市经营看板 · 前端（原生 JS + 本地 ECharts） */
(function () {
  'use strict';

  // ------------------------------------------------------------------ 基础
  const DISTRICTS = window.DISTRICTS || [];
  const NAME = {};
  const ID_BY_NAME = {};
  DISTRICTS.forEach(function (d) { NAME[d.district_id] = d.name; ID_BY_NAME[d.name] = d.district_id; });

  const C = {
    ink: '#1d2433', muted: '#6b7280', line: '#e7e2d6', grid: '#efebe2',
    teal: '#2a9d8f', sky: '#457b9d', coral: '#e76f51', sand: '#e9b949', navy: '#1d3557',
    plum: '#6d597a', mint: '#8ab17d', orange: '#f4a261',
    prev: '#b9cfdc', hiPrev: '#f6c1b0',
    marketPrev: '#7f97ad'
  };
  const DISTRICT_COLORS = {
    D01: '#e76f51', D02: '#6d597a', D03: '#2a9d8f', D04: '#457b9d',
    D05: '#e9b949', D06: '#8ab17d', D07: '#c2557a', D08: '#1d3557'
  };
  const CHANNEL_COLORS = ['#2a9d8f', '#457b9d', '#e9b949', '#e76f51', '#6d597a', '#8ab17d'];
  const ROOM_COLORS = ['#2a9d8f', '#e9b949', '#457b9d', '#e76f51', '#6d597a', '#8ab17d'];
  const FONT = '"PingFang SC","Microsoft YaHei","Noto Sans CJK SC",sans-serif';

  // ------------------------------------------------------------------ 格式化（half-up，远离零）
  function scaled(x, digits) {
    // 返回 round(|x| * 10^digits) 带符号整数；先转成定长小数字符串，规避二进制浮点误差
    const s = Math.abs(x).toFixed(12);
    const k = Math.round(Number(s + 'e' + digits));
    return x < 0 ? -k : k;
  }
  function isNum(x) { return typeof x === 'number' && isFinite(x); }
  function fmtPct(x) { return isNum(x) ? (scaled(x, 3) / 10).toFixed(1) + '%' : '—'; }
  function fmtYuan(x) { return isNum(x) ? '¥' + String(scaled(x, 0)) : '—'; }
  function fmtRating(x) { return isNum(x) ? (scaled(x, 2) / 100).toFixed(2) : '样本不足'; }
  function signed(k, scale, decimals, suffix) {
    if (k === 0) return (0).toFixed(decimals) + suffix;
    return (k > 0 ? '+' : '-') + (Math.abs(k) / scale).toFixed(decimals) + suffix;
  }
  const DELTA = {
    occupancy: function (v) { return signed(scaled(v, 3), 10, 1, 'pp'); },
    rating: function (v) { return signed(scaled(v, 2), 100, 2, ''); },
    adr: function (v) { return signed(scaled(v, 3), 10, 1, '%'); },
    revpar: function (v) { return signed(scaled(v, 3), 10, 1, '%'); }
  };
  const VALUE = { occupancy: fmtPct, adr: fmtYuan, revpar: fmtYuan, rating: fmtRating };
  function pctAxis(v) { return Math.round(v * 100) + '%'; }

  // ------------------------------------------------------------------ 图表实例
  const charts = {};
  document.querySelectorAll('[data-chart]').forEach(function (el) {
    const name = el.getAttribute('data-chart');
    // 地理视角默认由高德地图接管，退回态才在这里初始化 ECharts（见 ensureGeoChart）
    if (name === 'geo') return;
    charts[name] = echarts.init(el, null, { renderer: 'canvas' });
  });
  const baseText = { fontFamily: FONT, color: C.ink };
  const tooltipBase = {
    backgroundColor: 'rgba(255,255,255,.97)', borderColor: C.line, borderWidth: 1,
    textStyle: { color: C.ink, fontFamily: FONT, fontSize: 12 },
    extraCssText: 'box-shadow:0 6px 18px rgba(29,36,51,.12);border-radius:10px;'
  };
  const axisCommon = {
    axisLine: { lineStyle: { color: '#cfc8b8' } },
    axisTick: { show: false },
    axisLabel: { color: C.muted, fontSize: 11 },
    nameTextStyle: { color: C.muted, fontSize: 11 },
    splitLine: { lineStyle: { color: C.grid } }
  };
  function axis(extra) { return Object.assign({}, JSON.parse(JSON.stringify(axisCommon)), extra); }
  function mergeAxisLabel(base, extra) { return Object.assign({}, axisCommon.axisLabel, extra); }

  // ------------------------------------------------------------------ 视角状态
  const STATE_TEXT = { loading: '加载中…', error: '加载失败', empty: '暂无数据', ready: '' };
  function viewEl(name) { return document.querySelector('[data-view="' + name + '"]'); }
  function setState(name, state) {
    const el = viewEl(name);
    el.setAttribute('data-state', state);
    const msg = el.querySelector('[data-state-msg]');
    if (msg) msg.textContent = STATE_TEXT[state];
  }

  // ------------------------------------------------------------------ 状态：指标卡
  function renderStatus(d) {
    ['occupancy', 'adr', 'revpar', 'rating'].forEach(function (k) {
      const card = document.querySelector('[data-kpi="' + k + '"]');
      card.querySelector('[data-field="value"]').textContent = VALUE[k](d[k]);
      ['yoy', 'mom'].forEach(function (p) {
        const el = card.querySelector('[data-field="' + p + '"]');
        const v = d[p] ? d[p][k] : null;
        const text = isNum(v) ? DELTA[k](v) : '—';
        el.textContent = text;
        el.classList.toggle('pos', text.charAt(0) === '+');
        el.classList.toggle('neg', text.charAt(0) === '-');
      });
    });
  }
  function clearStatus() {
    document.querySelectorAll('[data-view="status"] [data-field]').forEach(function (el) {
      el.textContent = '—'; el.classList.remove('pos', 'neg');
    });
  }

  // ------------------------------------------------------------------ 趋势
  function renderTrend(d) {
    const chart = charts.trend;
    chart.setOption({
      textStyle: baseText,
      color: [C.teal, C.coral],
      animationDuration: 500,
      tooltip: Object.assign({}, tooltipBase, {
        trigger: 'axis',
        axisPointer: { type: 'line', lineStyle: { color: '#b8b09c' } },
        formatter: function (ps) {
          const i = ps[0].dataIndex;
          return '<b>' + d.months[i] + '</b><br/>' +
            dot(C.teal) + '入住率　<b>' + fmtPct(d.occupancy[i]) + '</b><br/>' +
            dot(C.coral) + '平均房价　<b>' + fmtYuan(d.adr[i]) + '</b><br/>' +
            '<span style="color:#6b7280">每间可售房收入 ' + fmtYuan(d.revpar[i]) +
            '　平均评分 ' + fmtRating(d.rating[i]) + '</span>';
        }
      }),
      legend: { data: ['入住率', '平均房价'], top: 0, left: 'center', itemWidth: 16, itemHeight: 8, textStyle: { color: C.ink, fontSize: 12 } },
      grid: { left: 52, right: 60, top: 38, bottom: 30 },
      xAxis: axis({
        type: 'category', data: d.months, boundaryGap: false, name: '',
        splitLine: { show: false },
        axisLabel: mergeAxisLabel(null, {
          interval: function (i, v) { return v.slice(5) === '01' || v.slice(5) === '07' || i === 0; },
          formatter: function (v) { return v.slice(5) === '01' || v === d.months[0] ? v.slice(0, 4) + '年' + Number(v.slice(5)) + '月' : Number(v.slice(5)) + '月'; }
        })
      }),
      yAxis: [
        axis({ type: 'value', name: '入住率', scale: true, axisLabel: mergeAxisLabel(null, { formatter: pctAxis }) }),
        axis({ type: 'value', name: '平均房价（元）', scale: true, splitLine: { show: false },
               axisLabel: mergeAxisLabel(null, { formatter: function (v) { return '¥' + v; } }) })
      ],
      series: [
        {
          name: '入住率', type: 'line', data: d.occupancy, smooth: 0.25, symbol: 'circle', symbolSize: 5,
          lineStyle: { width: 2.5 },
          areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: 'rgba(42,157,143,.28)' }, { offset: 1, color: 'rgba(42,157,143,0)' }]) }
        },
        {
          name: '平均房价', type: 'line', yAxisIndex: 1, data: d.adr, smooth: 0.25, symbol: 'circle', symbolSize: 4,
          lineStyle: { width: 2, type: [6, 3] }
        }
      ]
    }, true);
  }
  function dot(color) {
    return '<span style="display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px;background:' + color + '"></span>';
  }

  // ------------------------------------------------------------------ 对比（只取一次数，切区只高亮）
  let compareData = null;
  function renderCompare() {
    const d = compareData;
    if (!d) return;
    const names = d.districts.map(function (x) { return x.name; });
    const ids = d.districts.map(function (x) { return x.district_id; });
    const sel = current;
    const cur = d.districts.map(function (x) { return x.occupancy; });
    const prev = d.districts.map(function (x) { return x.occupancy_prev_year; });
    const market = d.districts.map(function (x) { return x.market_occupancy; });
    const marketPrev = d.districts.map(function (x) { return x.market_occupancy_prev_year; });
    viewEl('compare').setAttribute('data-highlight', sel);
    charts.compare.setOption({
      textStyle: baseText,
      animationDuration: 400,
      tooltip: Object.assign({}, tooltipBase, {
        trigger: 'axis', axisPointer: { type: 'shadow', shadowStyle: { color: 'rgba(29,53,87,.05)' } },
        formatter: function (ps) {
          const x = d.districts[ps[0].dataIndex];
          const yoy = isNum(x.occupancy) && isNum(x.occupancy_prev_year) ? DELTA.occupancy(x.occupancy - x.occupancy_prev_year) : '—';
          return '<b>' + x.name + '</b>（' + d.start + ' 至 ' + d.end + '）<br/>' +
            dot(C.teal) + '本期　<b>' + fmtPct(x.occupancy) + '</b><br/>' +
            dot(C.prev) + '上年同期　<b>' + fmtPct(x.occupancy_prev_year) + '</b>　<span style="color:#6b7280">同比 ' + yoy + '</span><br/>' +
            dot(C.navy) + '市场基准（简单平均）　<b>' + fmtPct(x.market_occupancy) + '</b><br/>' +
            dot(C.marketPrev) + '上年市场基准（简单平均）　<b>' + fmtPct(x.market_occupancy_prev_year) + '</b><br/>' +
            '<span style="color:#9aa1ad">点击筛选 / 再次点击恢复全公司</span>';
        }
      }),
      legend: {
        top: 0, right: 6, itemWidth: 14, itemHeight: 8, textStyle: { color: C.ink, fontSize: 12 },
        data: [
          { name: '本期', itemStyle: { color: C.teal } },
          { name: '上年同期', itemStyle: { color: C.prev } },
          { name: '市场基准（简单平均）', icon: 'rect', itemStyle: { color: C.navy } },
          { name: '上年市场基准（简单平均）', icon: 'line', itemStyle: { color: C.marketPrev } }
        ]
      },
      grid: { left: 48, right: 14, top: 52, bottom: 30 },
      xAxis: axis({
        type: 'category', data: names, splitLine: { show: false },
        axisLabel: mergeAxisLabel(null, {
          interval: 0, fontSize: 12,
          formatter: function (v) { return ID_BY_NAME[v] === sel ? '{hi|' + v + '}' : v; },
          rich: { hi: { color: C.coral, fontWeight: 'bold', fontSize: 12 } }
        })
      }),
      yAxis: axis({ type: 'value', name: '入住率', min: 0, max: 1, axisLabel: mergeAxisLabel(null, { formatter: pctAxis }) }),
      series: [
        {
          name: '本期', type: 'bar', data: cur, barWidth: 16, barGap: '15%',
          itemStyle: {
            borderRadius: [4, 4, 0, 0],
            color: function (p) { return ids[p.dataIndex] === sel ? C.coral : C.teal; }
          },
          emphasis: { focus: 'none' }
        },
        {
          name: '上年同期', type: 'bar', data: prev, barWidth: 16,
          itemStyle: {
            borderRadius: [4, 4, 0, 0],
            color: function (p) { return ids[p.dataIndex] === sel ? C.hiPrev : C.prev; }
          },
          emphasis: { focus: 'none' }
        },
        {
          name: '市场基准（简单平均）', type: 'scatter', data: market, symbol: 'rect', symbolSize: [42, 3], z: 5,
          itemStyle: { color: C.navy }
        },
        {
          name: '上年市场基准（简单平均）', type: 'line', data: marketPrev, z: 4,
          symbol: 'diamond', symbolSize: 8,
          lineStyle: { width: 1.6, type: [4, 3], color: C.marketPrev },
          itemStyle: { color: C.marketPrev },
          emphasis: { focus: 'none' }
        }
      ]
    }, true);
  }

  // ------------------------------------------------------------------ 结构
  function renderStructure(d) {
    const channels = Object.keys(d.channel_share);
    charts.channel.setOption({
      textStyle: baseText,
      color: CHANNEL_COLORS,
      animationDuration: 400,
      tooltip: Object.assign({}, tooltipBase, {
        trigger: 'axis', axisPointer: { type: 'shadow', shadowStyle: { color: 'rgba(29,53,87,.05)' } },
        formatter: function (ps) {
          return '<b>' + ps[0].axisValue + '</b> 渠道订单占比（含取消单）<br/>' + ps.map(function (p) {
            return dot(p.color) + p.seriesName + '　<b>' + fmtPct(p.value) + '</b>';
          }).join('<br/>');
        }
      }),
      legend: { data: channels, top: 0, left: 'center', itemWidth: 12, itemHeight: 8, textStyle: { color: C.ink, fontSize: 12 } },
      grid: { left: 42, right: 14, top: 52, bottom: 50 },
      xAxis: axis({ type: 'category', data: d.quarters, splitLine: { show: false },
                    axisLabel: mergeAxisLabel(null, { interval: 0, rotate: 40, fontSize: 10, margin: 8, hideOverlap: false }) }),
      yAxis: axis({ type: 'value', name: '订单占比', min: 0, max: 1, axisLabel: mergeAxisLabel(null, { formatter: pctAxis }) }),
      series: channels.map(function (c) {
        return { name: c, type: 'bar', stack: '渠道', data: d.channel_share[c], barWidth: '58%',
                 itemStyle: { borderColor: '#fff', borderWidth: 0.5 } };
      })
    }, true);

    const total = d.room_type_mix.reduce(function (s, x) { return s + x.n; }, 0);
    charts.roomtype.setOption({
      textStyle: baseText,
      color: ROOM_COLORS,
      animationDuration: 400,
      tooltip: Object.assign({}, tooltipBase, { trigger: 'item', formatter: function (p) {
        return '<b>' + p.name + '</b><br/>在线房源 ' + p.value + ' 套（' + p.percent.toFixed(1) + '%）';
      } }),
      legend: { bottom: 0, left: 'center', itemWidth: 10, itemHeight: 10, itemGap: 8, textStyle: { color: C.ink, fontSize: 12 },
                data: d.room_type_mix.map(function (x) { return x.room_type; }),
                formatter: function (name) {
                  const x = d.room_type_mix.find(function (r) { return r.room_type === name; });
                  return name + ' ' + (x ? x.n : 0);
                } },
      title: {
        text: String(total), subtext: '在线房源（套）', left: 'center', top: '37%',
        textStyle: { fontSize: 22, fontWeight: 800, color: C.ink, fontFamily: FONT },
        subtextStyle: { fontSize: 11, color: C.muted, fontFamily: FONT }, itemGap: 2
      },
      series: [{
        name: '房型占比', type: 'pie', radius: ['40%', '72%'], center: ['50%', '45%'],
        padAngle: 1.5,
        itemStyle: { borderColor: '#fff', borderWidth: 2, borderRadius: 4 },
        label: { position: 'inside', fontSize: 10, color: '#fff', fontWeight: 600,
                 formatter: function (p) { return p.percent.toFixed(1) + '%'; } },
        labelLine: { show: false },
        data: d.room_type_mix.map(function (x) { return { name: x.room_type, value: x.n }; })
      }]
    }, true);
  }

  // ------------------------------------------------------------------ 分布
  function renderDistribution(d) {
    const rows = d.room_types;
    const cats = rows.map(function (r) { return r.room_type; });
    charts.distribution.setOption({
      textStyle: baseText,
      animationDuration: 400,
      title: {
        text: '2026Q3 已完成订单 · 每晚价（元）', subtext: '箱体为 Q1–Q3，中线为中位数，须线为最小值与最大值',
        left: 0, top: 0, itemGap: 4,
        textStyle: { fontSize: 12, fontWeight: 600, color: C.ink, fontFamily: FONT },
        subtextStyle: { fontSize: 11, color: C.muted, fontFamily: FONT }
      },
      tooltip: Object.assign({}, tooltipBase, {
        trigger: 'item',
        formatter: function (p) {
          const r = rows[p.dataIndex];
          if (!r) return '';
          return '<b>' + r.room_type + '</b>　2026Q3 已完成订单 ' + r.n + ' 单<br/>' +
            '最大值　' + fmtYuan(r.max) + '<br/>上四分位　' + fmtYuan(r.q3) + '<br/>' +
            '<b>中位数　' + fmtYuan(r.median) + '</b><br/>下四分位　' + fmtYuan(r.q1) + '<br/>最小值　' + fmtYuan(r.min);
        }
      }),
      grid: { left: 58, right: 16, top: 78, bottom: 44 },
      xAxis: axis({
        type: 'category', data: cats, splitLine: { show: false },
        axisLabel: mergeAxisLabel(null, {
          interval: 0, lineHeight: 15,
          formatter: function (v, i) { return '{b|' + v + '}\n{n|' + rows[i].n + ' 单}'; },
          rich: { b: { color: C.ink, fontSize: 12 }, n: { color: C.muted, fontSize: 10 } }
        })
      }),
      yAxis: axis({ type: 'value', name: '每晚价（元）', scale: true, axisLabel: mergeAxisLabel(null, { formatter: function (v) { return '¥' + v; } }) }),
      series: [{
        name: '每晚价', type: 'boxplot', boxWidth: [18, 46],
        data: rows.map(function (r) { return [r.min, r.q1, r.median, r.q3, r.max]; }),
        itemStyle: {
          color: 'rgba(69,123,157,.16)', borderColor: C.sky, borderWidth: 1.6
        },
        emphasis: { itemStyle: { color: 'rgba(231,111,81,.18)', borderColor: C.coral } }
      }]
    }, true);
  }

  // ------------------------------------------------------------------ 地理
  let geoData = null;
  const GEO_GRID = { left: 62, right: 24, top: 44, bottom: 40 };
  function geoExtent(points) {
    // 保持经纬方向等距（经度按 cos(纬度) 缩放），避免空间形状被拉伸
    let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
    points.forEach(function (p) {
      if (p.lon < x0) x0 = p.lon; if (p.lon > x1) x1 = p.lon;
      if (p.lat < y0) y0 = p.lat; if (p.lat > y1) y1 = p.lat;
    });
    const el = document.querySelector('[data-chart="geo"]');
    const w = Math.max(200, el.clientWidth - GEO_GRID.left - GEO_GRID.right);
    const h = Math.max(150, el.clientHeight - GEO_GRID.top - GEO_GRID.bottom);
    const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
    const k = Math.cos(cy * Math.PI / 180);
    let dx = Math.max(x1 - x0, 0.01) * 1.08, dy = Math.max(y1 - y0, 0.01) * 1.12;
    // 每像素度数：取两方向较大者
    const perPx = Math.max(dx * k / w, dy / h);
    dx = perPx * w / k; dy = perPx * h;
    return { xmin: cx - dx / 2, xmax: cx + dx / 2, ymin: cy - dy / 2, ymax: cy + dy / 2 };
  }
  // ------------------------------------------------------------------ 地理（退回态：r1 离线散点）
  // 地图可用时由 map.js 接管；只有 provider=fallback 才初始化/渲染这张 ECharts 散点。
  const geoFallbackEl = document.querySelector('[data-chart="geo"]');
  function ensureGeoChart() {
    if (!charts.geo && geoFallbackEl) {
      charts.geo = echarts.init(geoFallbackEl, null, { renderer: 'canvas' });
      // 路径 3（退回态）：点散点筛选所在区
      charts.geo.on('click', function (p) {
        if (p.componentType === 'series') toggleDistrict(ID_BY_NAME[p.seriesName]);
      });
    }
    return charts.geo;
  }
  function geoProvider() {
    return (window.__mapState && window.__mapState.provider) || 'pending';
  }
  function renderGeo(d) {
    geoData = d;
    const chart = ensureGeoChart();
    if (!chart) return;
    const byDistrict = {};
    d.points.forEach(function (p) { (byDistrict[p.district_id] = byDistrict[p.district_id] || []).push(p); });
    const ids = DISTRICTS.map(function (x) { return x.district_id; }).filter(function (id) { return byDistrict[id]; });
    const ext = geoExtent(d.points);
    const fmt = function (v) { return v.toFixed(2) + '°'; };
    chart.setOption({
      textStyle: baseText,
      animation: false,                      // 点位多，关闭动画；也保证重绘后立即可点
      tooltip: Object.assign({}, tooltipBase, {
        trigger: 'item',
        formatter: function (p) {
          return dot(p.color) + '<b>' + p.seriesName + '</b>　' + p.value[2] + '<br/>' + p.value[3] +
            '<br/><span style="color:#6b7280">经度 ' + p.value[0].toFixed(4) + '，纬度 ' + p.value[1].toFixed(4) + '</span>' +
            '<br/><span style="color:#9aa1ad">点击筛选该区 / 再次点击恢复全公司</span>';
        }
      }),
      legend: {
        top: 0, left: 'center', selectedMode: false, itemWidth: 10, itemHeight: 10, icon: 'circle',
        textStyle: { color: C.ink, fontSize: 12 },
        data: ids.map(function (id) { return NAME[id]; }),
        formatter: function (name) { const id = ID_BY_NAME[name]; return name + ' ' + (byDistrict[id] ? byDistrict[id].length : 0); }
      },
      grid: GEO_GRID,
      xAxis: axis({ type: 'value', name: '经度', nameLocation: 'middle', nameGap: 24, min: ext.xmin, max: ext.xmax,
                    axisLabel: mergeAxisLabel(null, { formatter: fmt, showMinLabel: false, showMaxLabel: false }),
                    splitLine: { lineStyle: { color: C.grid, type: 'dashed' } } }),
      yAxis: axis({ type: 'value', name: '纬度', nameLocation: 'middle', nameGap: 46, min: ext.ymin, max: ext.ymax,
                    axisLabel: mergeAxisLabel(null, { formatter: fmt, showMinLabel: false, showMaxLabel: false }),
                    splitLine: { lineStyle: { color: C.grid, type: 'dashed' } } }),
      series: ids.map(function (id) {
        return {
          name: NAME[id], type: 'scatter', symbolSize: 8, cursor: 'pointer',
          itemStyle: { color: DISTRICT_COLORS[id] || C.sky, opacity: 0.82, borderColor: '#fff', borderWidth: 0.6 },
          emphasis: { scale: 1.6, itemStyle: { opacity: 1 } },
          data: byDistrict[id].map(function (p) { return [p.lon, p.lat, p.listing_id, p.room_type]; })
        };
      })
    }, true);
  }

  // ------------------------------------------------------------------ 取数与联动
  const VIEWS = [
    { name: 'status', api: '/api/kpi', render: renderStatus, clear: clearStatus,
      empty: function (d) { return !d || d.occupancy == null; } },
    { name: 'trend', api: '/api/trend', render: renderTrend, clear: function () { charts.trend.clear(); },
      empty: function (d) { return !d.months || !d.months.length; } },
    { name: 'structure', api: '/api/structure', render: renderStructure,
      clear: function () { charts.channel.clear(); charts.roomtype.clear(); },
      empty: function (d) { return !d.quarters.length && !d.room_type_mix.length; } },
    { name: 'distribution', api: '/api/distribution', render: renderDistribution,
      clear: function () { charts.distribution.clear(); },
      empty: function (d) { return !d.room_types.length; } },
    // geo 的就绪状态由地图决定（amap 冒泡就位 / fallback 散点画完），故 defer
    { name: 'geo', api: '/api/geo', defer: true,
      render: function (d) { geoData = d; },
      clear: function () { geoData = null; if (charts.geo) charts.geo.clear(); },
      empty: function (d) { return !d.points.length; } }
  ];

  // 地理视角状态：amap 就绪由 map.js 通知；fallback 画完散点才算 ready
  function applyGeoState() {
    const p = geoProvider();
    if (p === 'amap') { setState('geo', 'ready'); return; }
    if (p === 'fallback') {
      if (geoData && geoData.points && geoData.points.length) {
        renderGeo(geoData);
        setState('geo', 'ready');
      } else {
        setState('geo', 'empty');
      }
    }
    // pending：保持 loading，等地图脚本出结果
  }

  let current = '';
  let seq = 0;
  let inflight = [];
  const select = document.querySelector('select[data-filter="district"]');
  const currentEl = document.querySelector('[data-current-district]');

  function loadView(v, district, token) {
    setState(v.name, 'loading');
    const ctrl = new AbortController();
    inflight.push(ctrl);
    const url = v.api + '?district=' + encodeURIComponent(district);
    return fetch(url, { signal: ctrl.signal, headers: { Accept: 'application/json' } })
      .then(function (res) {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return res.json();
      })
      .then(function (data) {
        if (token !== seq) return;           // 迟到的旧响应：丢弃
        if (v.empty(data)) {
          v.clear();
          if (!v.defer) setState(v.name, 'empty');
          else applyGeoState();
          return;
        }
        v.render(data);
        if (v.defer) applyGeoState();
        else setState(v.name, 'ready');
      })
      .catch(function (err) {
        if (token !== seq) return;
        if (window.console) console.warn('[看板]', v.name, err);
        v.clear();
        setState(v.name, 'error');
      });
  }

  function selectDistrict(district) {
    district = district || '';
    current = district;
    seq += 1;
    const token = seq;
    inflight.forEach(function (c) { c.abort(); });
    inflight = [];
    if (select.value !== district) select.value = district;
    currentEl.textContent = district ? NAME[district] : '全公司';
    if (window.__mapSelect) window.__mapSelect(district);   // 地图上的选中气泡跟着走
    renderCompare();                         // 对比视角不重新取数，只高亮
    VIEWS.forEach(function (v) { loadView(v, district, token); });
  }
  function toggleDistrict(id) {
    if (!id) return;
    selectDistrict(current === id ? '' : id);
  }

  function loadCompare() {
    setState('compare', 'loading');
    fetch('/api/compare', { headers: { Accept: 'application/json' } })
      .then(function (res) { if (!res.ok) throw new Error('HTTP ' + res.status); return res.json(); })
      .then(function (d) {
        if (!d.districts || !d.districts.length) { charts.compare.clear(); setState('compare', 'empty'); return; }
        compareData = d;
        renderCompare();
        setState('compare', 'ready');
      })
      .catch(function (err) {
        if (window.console) console.warn('[看板] compare', err);
        compareData = null;
        charts.compare.clear();
        setState('compare', 'error');
      });
  }

  // 路径 1：选择器（鼠标与键盘都会触发 change）
  select.addEventListener('change', function () { selectDistrict(select.value); });

  // 路径 2：对比图点柱（含该区所在列的空白处）
  charts.compare.on('click', function (p) {
    if (!compareData) return;
    const x = compareData.districts[p.dataIndex];
    if (x) toggleDistrict(x.district_id);
  });
  charts.compare.getZr().on('click', function (e) {
    if (e.target || !compareData) return;
    const pt = [e.offsetX, e.offsetY];
    if (!charts.compare.containPixel('grid', pt)) return;
    const idx = charts.compare.convertFromPixel({ xAxisIndex: 0 }, pt);
    const i = Array.isArray(idx) ? idx[0] : idx;
    const x = compareData.districts[Math.round(i)];
    if (x) toggleDistrict(x.district_id);
  });

  // 路径 3：地理视角（amap 时点击气泡由 map.js 绑在 DOM 上；fallback 时点散点）
  let resizeTimer = null;
  window.addEventListener('resize', function () {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () {
      Object.keys(charts).forEach(function (k) { charts[k].resize(); });
      if (geoData && geoProvider() === 'fallback') renderGeo(geoData);
    }, 120);
  });

  // ------------------------------------------------------------------ 地图集成点（供 map.js 调用）
  const geoView = viewEl('geo');
  function mapShowFallbackUI() {
    const frame = geoView.querySelector('[data-map="amap"]');
    const chartEl = geoView.querySelector('[data-chart="geo"]');
    if (frame) frame.hidden = true;
    if (chartEl) chartEl.hidden = false;
  }
  function onMapReady() {
    if (geoView) geoView.setAttribute('data-map-provider', 'amap');
    applyGeoState();
  }
  function onMapFallback() {
    if (geoView) {
      geoView.setAttribute('data-map-provider', 'fallback');
      const notice = geoView.querySelector('[data-map-notice]');
      if (notice) {
        notice.hidden = false;
        notice.textContent = '地图服务不可用，已切换为离线散点';
      }
    }
    mapShowFallbackUI();
    applyGeoState();
  }
  function onMapError() {
    if (geoView) geoView.setAttribute('data-map-provider', 'error');
    setState('geo', 'error');
  }

  window.dashboard = {
    selectDistrict: selectDistrict,
    charts: charts,
    geoProvider: geoProvider,
    applyGeoState: applyGeoState,
    onMapReady: onMapReady,
    onMapFallback: onMapFallback,
    onMapError: onMapError
  };

  loadCompare();
  selectDistrict(select.value || '');
})();
