/* 区域地图 · 高德 JS API 2.0
 *
 * 规格第 4.2 节：
 *  - 脚本由本文件动态插入（document.createElement("script")），绑 onerror 与 10s 超时；
 *  - 安全密钥不下发：页面只设 window._AMapSecurityConfig.serviceHost = "/_AMapService"（同源代理）；
 *  - 8 个区气泡挂在区中心（GCJ-02），直径 16 + 44×sqrt(listings ÷ 最大 listings)，颜色按入住率同比分档；
 *  - 分档只在 window.__yoyBin 一个函数里；测试钩子 window.__amap、window.__mapState；
 *  - 脚本失败或 10s 未就绪 → provider="fallback"，交给 dashboard.js 画 r1 离线散点。
 */
(function () {
  'use strict';

  var MAP_TIMEOUT_MS = 10000;
  var BUBBLE_MIN = 16;
  var BUBBLE_SPAN = 44;
  var MAX_ZOOM = 12;          // 规格 4.2：缩放上限 12 级（实际按容器取不超过 12 的最大档）
  var SELECTED_OUTLINE = '#1d2433';

  // ---------------------------------------------------------------- 分档（唯一实现）
  var BINS = [
    { label: '大幅下滑', color: '#b2182b', max: -0.10 },
    { label: '下滑', color: '#ef8a62', max: -0.03 },
    { label: '持平', color: '#cccccc', max: 0.03 },
    { label: '上升', color: '#67a9cf', max: 0.10 },
    { label: '大幅上升', color: '#2166ac', max: Infinity }
  ];
  function yoyBin(v) {
    var x = typeof v === 'number' && isFinite(v) ? v : 0;   // 缺值按持平处理
    for (var i = 0; i < BINS.length; i += 1) {
      if (x < BINS[i].max) return { label: BINS[i].label, color: BINS[i].color };
    }
    return { label: BINS[4].label, color: BINS[4].color };
  }
  window.__yoyBin = yoyBin;

  // ---------------------------------------------------------------- 状态
  var state = { provider: 'pending', selected: '' };
  window.__mapState = state;
  window.__amap = null;

  var geoView = document.querySelector('[data-view="geo"]');
  var mapEl = document.querySelector('[data-map="amap"]');
  var tipEl = document.querySelector('[data-map-tip]');
  if (!geoView || !mapEl) return;

  var cfg = window.__MAP_CFG || {};
  // 必须在加载高德脚本之前设置；这里只有同源代理地址，没有安全密钥。
  // 高德要求 serviceHost 是绝对地址且以 /_AMapService 为一级路由（相对路径会弹告警）。
  var serviceHost = cfg.serviceHost || '/_AMapService';
  if (!/^https?:\/\//i.test(serviceHost)) serviceHost = window.location.origin + serviceHost;
  window._AMapSecurityConfig = { serviceHost: serviceHost };

  var settled = false;   // 已定档：amap 成功 / fallback
  var map = null;
  var bubbles = {};      // district_id -> DOM
  var markers = [];      // AMap.Marker
  var districtData = null;

  // ---------------------------------------------------------------- 工具
  var fmtPct = function (v) { return isNum(v) ? (halfUp(v, 3) / 10).toFixed(1) + '%' : '—'; };
  var fmtPP = function (v) {
    if (!isNum(v)) return '—';
    var k = halfUp(v, 3) / 10;
    return (k > 0 ? '+' : k < 0 ? '−' : '') + Math.abs(k).toFixed(1) + 'pp';
  };
  var fmtYuan = function (v) { return isNum(v) ? '¥' + halfUp(v, 0) : '—'; };
  var fmtRating = function (v) { return isNum(v) ? (halfUp(v, 2) / 100).toFixed(2) : '样本不足'; };
  function isNum(x) { return typeof x === 'number' && isFinite(x); }
  function halfUp(x, digits) {
    // 定点四舍五入（远离零），规避二进制浮点误差
    var s = Math.abs(x).toFixed(12);
    var k = Math.round(Number(s + 'e' + digits));
    return x < 0 ? -k : k;
  }
  // 浅色档位（持平灰、下滑橙）用深色字，保证气泡上的字看得清
  function textColor(hex) {
    var m = /^#?([0-9a-f]{6})$/i.exec(hex || '');
    if (!m) return '#ffffff';
    var n = parseInt(m[1], 16);
    var r = (n >> 16) & 255, g = (n >> 8) & 255, b = n & 255;
    var lum = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
    return lum > 0.62 ? '#2a2f3a' : '#ffffff';
  }

  function setProvider(p) {
    state.provider = p;
    if (geoView) geoView.setAttribute('data-map-provider', p);
  }

  // ---------------------------------------------------------------- 就绪 / 退回
  function notifyReady() {
    if (settled) return;
    settled = true;
    setProvider('amap');
    if (window.dashboard && window.dashboard.onMapReady) window.dashboard.onMapReady();
  }

  function notifyFallback() {
    if (settled) return;
    settled = true;
    setProvider('fallback');
    if (map && map.destroy) {
      try { map.destroy(); } catch (e) { /* 忽略 */ }
    }
    map = null;
    window.__amap = null;
    if (window.dashboard && window.dashboard.onMapFallback) window.dashboard.onMapFallback();
  }

  function notifyError() {
    settled = true;
    setProvider('error');
    if (window.dashboard && window.dashboard.onMapError) window.dashboard.onMapError();
  }

  // ---------------------------------------------------------------- 脚本动态插入
  function insertScript(src, timeoutMs) {
    return new Promise(function (resolve, reject) {
      var script = document.createElement('script');
      script.async = true;
      script.charset = 'utf-8';
      script.src = src;
      var done = false;
      function finish(ok, err) {
        if (done) return;
        done = true;
        if (ok) resolve(); else reject(err || new Error('script error'));
      }
      script.onload = function () { finish(true); };
      script.onerror = function () { finish(false, new Error('script onerror')); };
      setTimeout(function () { finish(false, new Error('script timeout')); }, timeoutMs);
      document.head.appendChild(script);
    });
  }

  // ---------------------------------------------------------------- 气泡
  function hoverText(d, periodText, asOf) {
    var gap = isNum(d.occupancy) && isNum(d.market_occupancy) ? d.occupancy - d.market_occupancy : null;
    return periodText + ' · ' + d.name + '\n' +
      '入住率 ' + fmtPct(d.occupancy) + '（同比 ' + fmtPP(d.occupancy_yoy) + '）\n' +
      '平均房价 ' + fmtYuan(d.adr) + '\n' +
      '评分 ' + fmtRating(d.rating) + '\n' +
      '与市场差距 ' + fmtPP(gap) + '\n' +
      '在线房源 ' + (d.listings == null ? '—' : d.listings) + ' 套（截至 ' + asOf + '）';
  }

  function hoverHtml(d, periodText, asOf) {
    var gap = isNum(d.occupancy) && isNum(d.market_occupancy) ? d.occupancy - d.market_occupancy : null;
    return '<b>' + d.name + '</b>　<span class="tip-sub">' + periodText + '</span>' +
      '<span class="tip-row">入住率 <b>' + fmtPct(d.occupancy) + '</b>　同比 ' + fmtPP(d.occupancy_yoy) + '</span>' +
      '<span class="tip-row">平均房价 <b>' + fmtYuan(d.adr) + '</b>　评分 ' + fmtRating(d.rating) + '</span>' +
      '<span class="tip-row">与市场差距 ' + fmtPP(gap) + '（市场 ' + fmtPct(d.market_occupancy) + '）</span>' +
      '<span class="tip-row tip-sub">在线房源 ' + (d.listings == null ? '—' : d.listings) + ' 套，截至 ' + asOf + '</span>';
  }

  function bubbleEl(d, maxListings, periodText, asOf) {
    var ratio = maxListings > 0 ? (d.listings || 0) / maxListings : 0;
    var dia = BUBBLE_MIN + BUBBLE_SPAN * Math.sqrt(ratio);
    var bin = yoyBin(d.occupancy_yoy);
    var el = document.createElement('div');
    el.className = 'map-bubble';
    el.setAttribute('data-bubble', d.district_id);
    el.setAttribute('data-bin', bin.label);
    el.setAttribute('data-color', bin.color);
    el.setAttribute('role', 'button');
    el.setAttribute('tabindex', '0');
    el.setAttribute('aria-label', d.name);
    el.setAttribute('aria-pressed', 'false');
    el.style.width = dia.toFixed(2) + 'px';
    el.style.height = dia.toFixed(2) + 'px';
    el.style.backgroundColor = bin.color;
    el.style.color = textColor(bin.color);
    el.style.fontSize = Math.max(9, Math.min(12, dia * 0.19)).toFixed(1) + 'px';
    el.title = hoverText(d, periodText, asOf);
    var name = document.createElement('span');
    name.className = 'map-bubble-name';
    name.textContent = d.name.length > 2 ? d.name.slice(0, 2) : d.name;
    var count = document.createElement('span');
    count.className = 'map-bubble-count';
    count.textContent = d.listings == null ? '' : String(d.listings);
    el.appendChild(name);
    el.appendChild(count);
    el.addEventListener('click', function (ev) {
      ev.preventDefault();
      ev.stopPropagation();
      toggle(d.district_id);
    });
    el.addEventListener('keydown', function (ev) {
      if (ev.key === 'Enter' || ev.key === ' ' || ev.key === 'Spacebar') {
        ev.preventDefault();
        ev.stopPropagation();
        toggle(d.district_id);
      }
    });
    el.addEventListener('mouseenter', function () { showTip(el, d, periodText, asOf); });
    el.addEventListener('mouseleave', hideTip);
    el.addEventListener('focus', function () { showTip(el, d, periodText, asOf); });
    el.addEventListener('blur', hideTip);
    return el;
  }

  function showTip(el, d, periodText, asOf) {
    if (!tipEl) return;
    tipEl.innerHTML = hoverHtml(d, periodText, asOf);
    tipEl.hidden = false;
    var shell = tipEl.parentElement.getBoundingClientRect();
    var rect = el.getBoundingClientRect();
    var left = rect.left - shell.left + rect.width / 2;
    var top = rect.top - shell.top;
    tipEl.style.left = Math.max(8, Math.min(shell.width - 232, left - 116)) + 'px';
    tipEl.style.top = Math.max(8, top - tipEl.offsetHeight - 10) + 'px';
  }
  function hideTip() { if (tipEl) tipEl.hidden = true; }

  // 选中态：气泡加 3px 深色描边（outline 不影响尺寸测量）
  function paintSelection() {
    Object.keys(bubbles).forEach(function (id) {
      var el = bubbles[id];
      var on = id === state.selected;
      el.classList.toggle('is-selected', on);
      el.setAttribute('aria-pressed', on ? 'true' : 'false');
      el.style.outline = on ? '3px solid ' + SELECTED_OUTLINE : '';
      el.style.outlineOffset = on ? '2px' : '';
    });
  }
  window.__mapSelect = function (district) {
    state.selected = district || '';
    paintSelection();
  };

  function toggle(id) {
    var next = state.selected === id ? '' : id;
    if (window.dashboard && window.dashboard.selectDistrict) {
      window.dashboard.selectDistrict(next);
      state.selected = next;
      paintSelection();
    } else {
      window.__mapSelect(next);
    }
  }

  // ---------------------------------------------------------------- 地图初始化
  function ensureMarkerClass(AMap) {
    if (AMap.Marker) return Promise.resolve();
    return new Promise(function (resolve, reject) {
      if (!AMap.plugin) { reject(new Error('AMap.Marker 不可用')); return; }
      AMap.plugin(['AMap.Marker'], function () {
        if (AMap.Marker) resolve(); else reject(new Error('AMap.Marker 加载失败'));
      });
    });
  }

  function fetchDistricts() {
    return fetch('/api/districts', { headers: { Accept: 'application/json' } })
      .then(function (res) {
        if (!res.ok) {
          var err = new Error('HTTP ' + res.status);
          err.__api = true;
          throw err;
        }
        return res.json();
      })
      .catch(function (err) {
        err.__api = true;      // 接口类失败：报 error，不退回散点
        throw err;
      });
  }

  function buildMarkers(AMap, data) {
    var list = data.districts || [];
    if (!list.length) throw new Error('区内无数据');
    var maxListings = list.reduce(function (m, d) { return Math.max(m, d.listings || 0); }, 0);
    var periodText = data.start + ' 至 ' + data.end;
    var asOf = data.as_of || data.end;
    list.forEach(function (d) {
      var el = bubbleEl(d, maxListings, periodText, asOf);
      bubbles[d.district_id] = el;
      var marker = new AMap.Marker({
        position: [d.lng_gcj, d.lat_gcj],
        content: el,
        anchor: 'center',
        zIndex: 100 + (d.listings || 0)
      });
      marker.__district = d;
      markers.push(marker);
    });
    map.add(markers);
    // 图例补充期间与截止日（静态文案在模板里，这里只填动态值）
    var periodEl = geoView.querySelector('[data-legend-period]');
    if (periodEl) periodEl.textContent = periodText;
    var asOfEl = geoView.querySelector('[data-legend-asof]');
    if (asOfEl) asOfEl.textContent = asOf;
    return list.length;
  }

  function initMap(AMap, data) {
    districtData = data;
    var list = data.districts;
    map = new AMap.Map(mapEl, {
      zoom: MAX_ZOOM,
      center: [geoLng(list), geoLat(list)],
      viewMode: '2D',
      resizeEnable: true,
      zooms: [9, 15]
    });
    window.__amap = map;
    buildMarkers(AMap, data);
    fitToBubbles(list);
    map.on('movestart', hideTip);
    map.on('zoomstart', hideTip);
  }

  // 缩放策略（规格 4.2 允许 12 级；但同时要求 8 个气泡两两不重叠且都在视野里）：
  // 取「能装下全部气泡」与「12 级」的较小者，且不低于「两两不重叠」所需档位。
  // 气泡直径是像素值、不随缩放变化，所以迭代两轮收敛。
  function maxListingsOf(list) {
    return list.reduce(function (m, d) { return Math.max(m, d.listings || 0); }, 0);
  }
  function radiusOf(d, maxListings) {
    return (BUBBLE_MIN + BUBBLE_SPAN * Math.sqrt(maxListings > 0 ? (d.listings || 0) / maxListings : 0)) / 2;
  }
  function geoLng(list) {
    var xs = list.map(function (d) { return d.lng_gcj; });
    return (Math.min.apply(null, xs) + Math.max.apply(null, xs)) / 2;
  }
  function geoLat(list) {
    var ys = list.map(function (d) { return d.lat_gcj; });
    return (Math.min.apply(null, ys) + Math.max.apply(null, ys)) / 2;
  }
  function pixelBox(list, maxListings) {
    var box = { x0: Infinity, y0: Infinity, x1: -Infinity, y1: -Infinity };
    list.forEach(function (d) {
      var p = map.lngLatToContainer([d.lng_gcj, d.lat_gcj]);
      var r = radiusOf(d, maxListings);
      box.x0 = Math.min(box.x0, p.getX() - r);
      box.x1 = Math.max(box.x1, p.getX() + r);
      box.y0 = Math.min(box.y0, p.getY() - r);
      box.y1 = Math.max(box.y1, p.getY() + r);
    });
    return box;
  }
  // 两两不重叠所需的最小缩放
  function overlapZoom(list, maxListings) {
    var z = map.getZoom();
    var need = 0;
    for (var i = 0; i < list.length; i += 1) {
      for (var j = i + 1; j < list.length; j += 1) {
        var a = map.lngLatToContainer([list[i].lng_gcj, list[i].lat_gcj]);
        var b = map.lngLatToContainer([list[j].lng_gcj, list[j].lat_gcj]);
        var dist = Math.hypot(a.getX() - b.getX(), a.getY() - b.getY());
        if (dist <= 0) continue;
        need = Math.max(need, (radiusOf(list[i], maxListings) + radiusOf(list[j], maxListings) + 2) / dist);
      }
    }
    return z + Math.log2(Math.max(need, 1e-6));
  }
  function fitToBubbles(list) {
    if (!map || !list || !list.length) return null;
    var maxListings = maxListingsOf(list);
    var rect = mapEl.getBoundingClientRect();
    var pad = 24;
    var availW = Math.max(200, rect.width - 2 * pad);
    var availH = Math.max(160, rect.height - 2 * pad);
    var z = map.getZoom();
    for (var k = 0; k < 2; k += 1) {
      var box = pixelBox(list, maxListings);
      var scaleFit = Math.min(availW / Math.max(1, box.x1 - box.x0), availH / Math.max(1, box.y1 - box.y0));
      var zFit = z + Math.log2(Math.max(scaleFit, 1e-6));
      var zFloor = overlapZoom(list, maxListings);
      z = Math.min(MAX_ZOOM, Math.max(Math.min(zFit, MAX_ZOOM), zFloor));
      z = Math.min(MAX_ZOOM, z);
      map.setZoomAndCenter(z, [geoLng(list), geoLat(list)]);
    }
    return map.getZoom();
  }

  function start() {
    var bootTimer = setTimeout(function () {
      if (!settled) notifyFallback();
    }, MAP_TIMEOUT_MS);

    if (!cfg.jsKey) {
      clearTimeout(bootTimer);
      notifyFallback();
      return;
    }
    var url = 'https://webapi.amap.com/maps?v=2.0&key=' + encodeURIComponent(cfg.jsKey);
    insertScript(url, MAP_TIMEOUT_MS)
      .then(function () {
        if (settled) return null;
        var AMap = window.AMap;
        if (!AMap || !AMap.Map) throw new Error('AMap 未就绪');
        return ensureMarkerClass(AMap).then(function () {
          if (settled) return null;
          return fetchDistricts();
        });
      })
      .then(function (data) {
        if (settled || !data) return null;
        if (!data.districts || data.districts.length !== 8) throw new Error('区数据不完整');
        initMap(window.AMap, data);
        clearTimeout(bootTimer);
        // 两帧后再宣布就绪：等浏览器完成一次布局，验收量到的是真实尺寸
        requestAnimationFrame(function () {
          requestAnimationFrame(notifyReady);
        });
        return null;
      })
      .catch(function (err) {
        clearTimeout(bootTimer);
        if (window.console) console.warn('[地图]', err && err.message ? err.message : err);
        if (err && err.__api) notifyError();   // /api/districts 失败：地理视角 error
        else notifyFallback();                 // 脚本或地图初始化失败：退回离线散点
      });
  }

  var resizeTimer = null;
  window.addEventListener('resize', function () {
    if (!map || !map.resize) return;
    map.resize();
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () {
      if (districtData) fitToBubbles(districtData.districts);   // 容器变了重新贴合，保持“都看得见 + 不重叠”
    }, 180);
  });

  start();
})();
