/* 区域地图（小区级）· 高德 JS API 2.0
 *
 * r3 规格第 4.2 节（沿用 r2 4.2 的加载方式、__yoyBin、__amap、__mapState、退回逻辑）：
 *  - 脚本由本文件动态插入（document.createElement("script")），绑 onerror 与 10s 超时；
 *  - 安全密钥不下发：页面只设 window._AMapSecurityConfig.serviceHost = "/_AMapService"（同源代理）；
 *  - 每个小区一个 AMap.Marker，内容 DOM [data-community="<小区名>"]，居中放在 lng_gcj, lat_gcj；
 *    直径 10 + 26×sqrt(listings ÷ 最大 listings)，颜色按入住率同比分档；小气泡叠在大气泡之上；
 *  - 初始视野包住全部小区中心（上限 13 级），之后用户自由缩放平移；
 *  - 点击小区：展开房源散点 [data-listing-point]（8px，GCJ 坐标），再点收起，点另一个切换；
 *  - 区下拉 → window.__mapSelect(district)：其他区的小区气泡透明度 0.25；地图点击不改区筛选；
 *  - 脚本失败或 10s 未就绪 → provider="fallback"，交给 dashboard.js 画 r1 离线散点。
 */
(function () {
  'use strict';

  var MAP_TIMEOUT_MS = 10000;
  var BUBBLE_MIN = 10;
  var BUBBLE_SPAN = 26;
  var MAX_FIT_ZOOM = 13;       // 初始视野上限 13 级
  var ZOOM_RANGE = [8, 18];    // 用户可自由缩放（放大后才能看清散点）
  var POINT_SIZE = 8;
  var DIM_OPACITY = '0.25';
  var EXPANDED_OUTLINE = '#1d2433';
  var READY_WAIT_MS = 4000;    // 等全部气泡 DOM 挂上的最长时间（之后仍按实际数量判断）

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
  var state = { provider: 'pending', selected: '', expanded: '' };
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

  var DISTRICT_NAME = {};
  (window.DISTRICTS || []).forEach(function (d) { DISTRICT_NAME[d.district_id] = d.name; });

  var settled = false;   // 已定档：amap 成功 / fallback
  var map = null;
  var AMapRef = null;
  var bubbles = {};      // 小区名 -> DOM
  var communityById = {};
  var markers = [];      // 小区 AMap.Marker
  var pointMarkers = []; // 当前展开小区的房源点 AMap.Marker
  var pointCache = {};   // 小区名 -> points
  var expandSeq = 0;
  var communityData = null;

  // ---------------------------------------------------------------- 工具
  function isNum(x) { return typeof x === 'number' && isFinite(x); }
  function halfUp(x, digits) {
    // 定点四舍五入（远离零），规避二进制浮点误差
    var s = Math.abs(x).toFixed(12);
    var k = Math.round(Number(s + 'e' + digits));
    return x < 0 ? -k : k;
  }
  var fmtPct = function (v) { return isNum(v) ? (halfUp(v, 3) / 10).toFixed(1) + '%' : '—'; };
  var fmtPP = function (v) {
    if (!isNum(v)) return '无同比';
    var k = halfUp(v, 3) / 10;
    return (k > 0 ? '+' : k < 0 ? '−' : '') + Math.abs(k).toFixed(1) + 'pp';
  };
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function diameterOf(listings, maxListings) {
    return BUBBLE_MIN + BUBBLE_SPAN * Math.sqrt(maxListings > 0 ? (listings || 0) / maxListings : 0);
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

  // ---------------------------------------------------------------- 悬停
  function districtLabel(c) { return DISTRICT_NAME[c.district_id] || c.district_id; }

  function hoverText(c, asOf) {
    return c.community + ' · ' + districtLabel(c) + '\n' +
      '在线房源 ' + c.listings + ' 套（截至 ' + asOf + '）\n' +
      '入住率 ' + fmtPct(c.occupancy) + '（同比 ' + fmtPP(c.occupancy_yoy) + '）';
  }

  function hoverHtml(c, periodText, asOf) {
    return '<b>' + esc(c.community) + '</b>　<span class="tip-sub">' + esc(districtLabel(c)) + '</span>' +
      '<span class="tip-row">在线房源 <b>' + esc(c.listings) + '</b> 套<span class="tip-sub">（截至 ' + esc(asOf) + '）</span></span>' +
      '<span class="tip-row">入住率 <b>' + fmtPct(c.occupancy) + '</b>　同比 ' + fmtPP(c.occupancy_yoy) + '</span>' +
      '<span class="tip-row tip-sub">' + esc(periodText) + '</span>';
  }

  function showTip(el, c, periodText, asOf) {
    if (!tipEl) return;
    tipEl.innerHTML = hoverHtml(c, periodText, asOf);
    tipEl.hidden = false;
    var shell = tipEl.parentElement.getBoundingClientRect();
    var rect = el.getBoundingClientRect();
    var left = rect.left - shell.left + rect.width / 2;
    var top = rect.top - shell.top;
    tipEl.style.left = Math.max(8, Math.min(shell.width - 232, left - 116)) + 'px';
    var y = top - tipEl.offsetHeight - 10;
    if (y < 8) y = rect.bottom - shell.top + 10;   // 上方放不下就放到气泡下方
    tipEl.style.top = y + 'px';
  }
  function hideTip() { if (tipEl) tipEl.hidden = true; }

  // ---------------------------------------------------------------- 小区气泡
  function bubbleEl(c, maxListings, periodText, asOf) {
    var dia = diameterOf(c.listings, maxListings);
    var bin = yoyBin(c.occupancy_yoy);
    var el = document.createElement('div');
    el.className = 'map-community';
    el.setAttribute('data-community', c.community);
    el.setAttribute('data-district', c.district_id);
    el.setAttribute('data-bin', bin.label);
    el.setAttribute('role', 'button');
    el.setAttribute('tabindex', '0');
    el.setAttribute('aria-label', c.community);
    el.setAttribute('aria-expanded', 'false');
    el.style.width = dia + 'px';
    el.style.height = dia + 'px';
    el.style.backgroundColor = bin.color;
    el.title = hoverText(c, asOf);
    el.addEventListener('click', function (ev) {
      ev.preventDefault();
      ev.stopPropagation();
      toggleExpand(resolveClick(c.community, ev));
    });
    el.addEventListener('keydown', function (ev) {
      if (ev.key === 'Enter' || ev.key === ' ' || ev.key === 'Spacebar') {
        ev.preventDefault();
        ev.stopPropagation();
        toggleExpand(c.community);
      }
    });
    el.addEventListener('mouseenter', function () { showTip(el, c, periodText, asOf); });
    el.addEventListener('mouseleave', hideTip);
    el.addEventListener('focus', function () { showTip(el, c, periodText, asOf); });
    el.addEventListener('blur', hideTip);
    return { el: el, dia: dia };
  }

  // 气泡互相重叠时（小气泡叠在大气泡之上），一次点击可能同时落在几个圆内：
  // 取圆心离点击位置最近的那个，这样点大气泡的圆心也能选中大气泡本身。
  function resolveClick(fallbackName, ev) {
    if (!ev || typeof ev.clientX !== 'number' || (ev.clientX === 0 && ev.clientY === 0 && ev.detail === 0)) {
      return fallbackName;   // 键盘触发的 click：就用元素本身
    }
    var best = fallbackName, bestDist = Infinity;
    Object.keys(bubbles).forEach(function (name) {
      var r = bubbles[name].getBoundingClientRect();
      var dx = ev.clientX - (r.left + r.width / 2);
      var dy = ev.clientY - (r.top + r.height / 2);
      var d = Math.sqrt(dx * dx + dy * dy);
      if (d <= r.width / 2 && d < bestDist) { best = name; bestDist = d; }
    });
    return best;
  }

  // ---------------------------------------------------------------- 区筛选联动（只改透明度，不改区筛选）
  function paintDim() {
    Object.keys(bubbles).forEach(function (name) {
      var el = bubbles[name];
      var c = communityById[name];
      var dim = !!state.selected && c.district_id !== state.selected;
      el.style.opacity = dim ? DIM_OPACITY : '1';
      el.classList.toggle('is-dimmed', dim);
    });
  }
  // dashboard.js 在区下拉变化时调用
  window.__mapSelect = function (district) {
    state.selected = district || '';
    paintDim();
  };

  // ---------------------------------------------------------------- 下钻：房源散点
  function paintExpanded() {
    Object.keys(bubbles).forEach(function (name) {
      var el = bubbles[name];
      var on = name === state.expanded;
      el.classList.toggle('is-expanded', on);
      el.setAttribute('aria-expanded', on ? 'true' : 'false');
      el.style.outline = on ? '3px solid ' + EXPANDED_OUTLINE : '';
      el.style.outlineOffset = on ? '0px' : '';
    });
  }

  function clearPoints() {
    if (map && pointMarkers.length) map.remove(pointMarkers);
    pointMarkers = [];
  }

  function fetchPoints(name) {
    if (pointCache[name]) return Promise.resolve(pointCache[name]);
    var end = communityData ? (communityData.as_of || communityData.end) : '';
    var url = '/api/communities/listings?community=' + encodeURIComponent(name) + '&end=' + encodeURIComponent(end);
    return fetch(url, { headers: { Accept: 'application/json' } })
      .then(function (res) {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return res.json();
      })
      .then(function (d) {
        pointCache[name] = d.points || [];
        return pointCache[name];
      });
  }

  function drawPoints(points) {
    clearPoints();
    if (!map || !AMapRef) return;
    pointMarkers = points.map(function (p) {
      var el = document.createElement('div');
      el.className = 'map-listing-point';
      el.setAttribute('data-listing-point', p.listing_id);
      el.style.width = POINT_SIZE + 'px';
      el.style.height = POINT_SIZE + 'px';
      el.title = p.listing_id + ' · ' + p.room_type;
      return new AMapRef.Marker({
        position: [p.lng_gcj, p.lat_gcj],
        content: el,
        anchor: 'center',
        zIndex: 2000,
        bubble: true,
        clickable: false
      });
    });
    if (pointMarkers.length) map.add(pointMarkers);
  }

  function toggleExpand(name) {
    hideTip();
    var token = ++expandSeq;
    if (state.expanded === name) {      // 再点同一小区：收起
      state.expanded = '';
      clearPoints();
      paintExpanded();
      return;
    }
    state.expanded = name;              // 首次展开或切换到另一个小区
    clearPoints();
    paintExpanded();
    fetchPoints(name)
      .then(function (points) {
        if (token !== expandSeq || state.expanded !== name) return;   // 已切走：丢弃迟到结果
        drawPoints(points);
      })
      .catch(function (err) {
        if (token !== expandSeq) return;
        if (window.console) console.warn('[地图] 房源点', err && err.message ? err.message : err);
        state.expanded = '';
        paintExpanded();
      });
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

  function fetchCommunities() {
    return fetch('/api/communities', { headers: { Accept: 'application/json' } })
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
    var list = data.communities || [];
    var maxListings = list.reduce(function (m, c) { return Math.max(m, c.listings || 0); }, 0);
    var periodText = data.start + ' 至 ' + data.end;
    var asOf = data.as_of || data.end;
    list.forEach(function (c) {
      var b = bubbleEl(c, maxListings, periodText, asOf);
      bubbles[c.community] = b.el;
      communityById[c.community] = c;
      var marker = new AMap.Marker({
        position: [c.lng_gcj, c.lat_gcj],
        content: b.el,
        anchor: 'center',
        // 小气泡叠在大气泡之上：zIndex 随直径递减
        zIndex: 1000 - Math.round(b.dia * 10)
      });
      markers.push(marker);
    });
    map.add(markers);
    paintDim();
    // 图例补充期间与截止日（静态文案在模板里，这里只填动态值）
    var periodEl = geoView.querySelector('[data-legend-period]');
    if (periodEl) periodEl.textContent = periodText;
    var asOfEl = geoView.querySelector('[data-legend-asof]');
    if (asOfEl) asOfEl.textContent = asOf;
    return list.length;
  }

  function centerOf(list) {
    var xs = list.map(function (c) { return c.lng_gcj; });
    var ys = list.map(function (c) { return c.lat_gcj; });
    return [(Math.min.apply(null, xs) + Math.max.apply(null, xs)) / 2,
      (Math.min.apply(null, ys) + Math.max.apply(null, ys)) / 2];
  }

  // 初始视野：全部小区中心（连同气泡半径）落在容器内，缩放不超过 13 级。
  // 气泡直径是像素值、不随缩放变化，所以迭代两轮收敛。
  function fitToCommunities(list) {
    if (!map || !list || !list.length) return null;
    var maxListings = list.reduce(function (m, c) { return Math.max(m, c.listings || 0); }, 0);
    var rect = mapEl.getBoundingClientRect();
    var pad = 16;
    var availW = Math.max(200, rect.width - 2 * pad);
    var availH = Math.max(160, rect.height - 2 * pad);
    var center = centerOf(list);
    var z = map.getZoom();
    for (var k = 0; k < 3; k += 1) {
      var box = { x0: Infinity, y0: Infinity, x1: -Infinity, y1: -Infinity };
      list.forEach(function (c) {
        var p = map.lngLatToContainer([c.lng_gcj, c.lat_gcj]);
        var r = diameterOf(c.listings, maxListings) / 2;
        box.x0 = Math.min(box.x0, p.getX() - r);
        box.x1 = Math.max(box.x1, p.getX() + r);
        box.y0 = Math.min(box.y0, p.getY() - r);
        box.y1 = Math.max(box.y1, p.getY() + r);
      });
      var scaleFit = Math.min(availW / Math.max(1, box.x1 - box.x0), availH / Math.max(1, box.y1 - box.y0));
      z = Math.min(MAX_FIT_ZOOM, z + Math.log2(Math.max(scaleFit, 1e-6)));
      map.setZoomAndCenter(z, center, true);
    }
    return map.getZoom();
  }

  function initMap(AMap, data) {
    communityData = data;
    AMapRef = AMap;
    var list = data.communities;
    map = new AMap.Map(mapEl, {
      zoom: 11,
      center: centerOf(list),
      viewMode: '2D',
      resizeEnable: true,
      zooms: ZOOM_RANGE
    });
    window.__amap = map;
    fitToCommunities(list);
    buildMarkers(AMap, data);
    map.on('movestart', hideTip);
    map.on('zoomstart', hideTip);
  }

  // 全部气泡 DOM 已挂到页面上才宣布就绪
  function whenAllPlaced(n, cb) {
    var t0 = Date.now();
    (function poll() {
      var placed = mapEl.querySelectorAll('[data-community]').length;
      if (placed >= n || Date.now() - t0 > READY_WAIT_MS) { cb(placed); return; }
      requestAnimationFrame(poll);
    })();
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
          return fetchCommunities();
        });
      })
      .then(function (data) {
        if (settled || !data) return null;
        if (!data.communities || !data.communities.length) {
          var err = new Error('小区数据为空');
          err.__api = true;
          throw err;
        }
        initMap(window.AMap, data);
        clearTimeout(bootTimer);
        whenAllPlaced(data.communities.length, function (placed) {
          if (placed >= data.communities.length) {
            // 再等一帧布局，验收量到的是真实尺寸
            requestAnimationFrame(function () { requestAnimationFrame(notifyReady); });
          } else {
            if (window.console) console.warn('[地图] 气泡未全部就位', placed, '/', data.communities.length);
            notifyFallback();
          }
        });
        return null;
      })
      .catch(function (err) {
        clearTimeout(bootTimer);
        if (window.console) console.warn('[地图]', err && err.message ? err.message : err);
        if (err && err.__api) notifyError();   // /api/communities 失败：地理视角 error
        else notifyFallback();                 // 脚本或地图初始化失败：退回离线散点
      });
  }

  var resizeTimer = null;
  window.addEventListener('resize', function () {
    if (!map || !map.resize) return;
    map.resize();
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () {
      if (communityData) fitToCommunities(communityData.communities);   // 容器变了重新贴合
    }, 180);
  });

  start();
})();
