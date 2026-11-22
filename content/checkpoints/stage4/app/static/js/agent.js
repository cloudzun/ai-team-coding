/* 巡检面板。
 * 开始巡检 → 轮询 /api/agent/run/{id} 逐步显示工具调用 → 建议清单（勾选）→
 * 确认提交到待审批 → 待审批列表批准 / 驳回。不碰 data-view。 */
(function () {
  'use strict';

  var panel = document.querySelector('[data-panel="agent"]');
  if (!panel) return;

  function $(sel) { return panel.querySelector(sel); }
  var runBtn = $('[data-agent-run]');
  var useLlm = $('[data-agent-use-llm]');
  var stateMsg = $('[data-agent-state-msg]');
  var stepsEl = $('[data-agent-steps]');
  var stepCount = $('[data-agent-step-count]');
  var degradedEl = $('[data-agent-degraded]');
  var degradeReason = $('[data-agent-degrade-reason]');
  var errorEl = $('[data-agent-error]');
  var reportBox = $('[data-agent-report]');
  var reportText = $('[data-agent-report-text]');
  var notesEl = $('[data-agent-notes]');
  var sugBox = $('[data-agent-suggestions-box]');
  var sugList = $('[data-agent-suggestions]');
  var sugCount = $('[data-agent-suggestion-count]');
  var filterEl = $('[data-agent-filter]');
  var checkAll = $('[data-agent-check-all]');
  var commitBtn = $('[data-agent-commit]');
  var commitResult = $('[data-agent-commit-result]');
  var opsItems = $('[data-ops-items]');
  var opsRefresh = $('[data-agent-ops-refresh]');
  var decisionResult = $('[data-agent-decision-result]');

  // 两规则版：规则编号直接用运营手册的编号；没有出现过的类别不会渲染，也不报错。
  var RULE_NAMES = { 'N-01': '房东关房不调价', 'P-01': '幅度上限回调' };
  var RULE_ORDER = ['P-01', 'N-01'];
  var ACTION_NAMES = { price_change: '调价申请', ticket: '整改工单', none: '不处理' };
  var METRIC_NAMES = {
    current_price: '当前平日价', previous_price: '上一档平日价',
    calendar_nights: '日历晚数', gross_occupancy: '毛入住率',
    owner_block_nights: '房东关房晚数', owner_block_share: '关房占比'
  };
  var STATE_TEXT = { idle: '尚未巡检', running: '巡检中…', ready: '巡检完成', error: '巡检失败' };
  var POLL_MS = 800;
  var current = null;      // 最近一次巡检结果
  var committedPreviews = {};
  var activeRule = '';

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = String(text);
    return n;
  }

  function setState(state, msg) {
    panel.setAttribute('data-agent-state', state);
    stateMsg.textContent = msg || STATE_TEXT[state] || '';
    runBtn.disabled = state === 'running';
    runBtn.textContent = state === 'running' ? '巡检中…' : '开始巡检';
  }

  function api(method, url, body) {
    var opts = { method: method, headers: { 'Content-Type': 'application/json' } };
    if (body !== undefined) opts.body = JSON.stringify(body);
    return fetch(url, opts).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (data) {
        if (!r.ok) {
          var err = new Error((data && (data.detail || data.message)) || ('HTTP ' + r.status));
          err.status = r.status;
          throw err;
        }
        return data;
      });
    });
  }

  function fmtMetric(m) {
    var v = m.value;
    var key = m.key;
    var txt;
    if (v === null || v === undefined) txt = '—';
    else if (/occupancy|share/.test(key)) txt = (v * 100).toFixed(2).replace(/\.?0+$/, '') + '%（' + v + '）';
    else if (/price|adr/.test(key)) txt = v + ' 元';
    else txt = String(v);
    return (METRIC_NAMES[key] || key) + ' ' + txt;
  }

  // ------------------------------------------------------------------ 步骤
  function renderSteps(steps) {
    var have = stepsEl.children.length;
    for (var i = have; i < steps.length; i++) {
      var s = steps[i];
      var li = el('li', 'agent-step' + (s.ok ? '' : ' is-fail'));
      li.setAttribute('data-tool-call', s.tool);
      li.setAttribute('data-by', s.by);
      li.appendChild(el('code', 'agent-step-tool', s.tool));
      li.appendChild(el('span', 'agent-step-by', s.by === 'llm' ? '模型选' : '规则'));
      li.appendChild(el('span', 'agent-step-summary', s.summary || ''));
      stepsEl.appendChild(li);
    }
    stepCount.textContent = String(steps.length);
    if (steps.length && panel.getAttribute('data-agent-state') === 'running') {
      stepsEl.scrollTop = stepsEl.scrollHeight;
    }
  }

  // ------------------------------------------------------------------ 建议
  function selectable(s) {
    return s.action !== 'none' && s.preview && s.preview.ok && s.preview_id && !committedPreviews[s.preview_id];
  }

  function renderSuggestion(s) {
    var card = el('article', 'agent-sug');
    card.setAttribute('data-suggestion', s.suggestion_id);
    card.setAttribute('data-listing', s.scope.listing_id);
    card.setAttribute('data-action', s.action);
    card.setAttribute('data-rule', s.rule_id);
    if (s.needs_manual_review) card.classList.add('is-manual');

    var head = el('div', 'agent-sug-head');
    if (s.action !== 'none') {
      var cb = el('input');
      cb.type = 'checkbox';
      cb.setAttribute('data-agent-pick', s.preview_id || '');
      cb.setAttribute('aria-label', '勾选 ' + s.scope.listing_id + ' ' + ACTION_NAMES[s.action]);
      cb.checked = selectable(s) && checkAll.checked;
      cb.disabled = !selectable(s);
      cb.addEventListener('change', updateCommitBtn);
      head.appendChild(cb);
    }
    head.appendChild(el('b', 'agent-sug-id', s.scope.listing_id));
    head.appendChild(el('span', 'agent-tag agent-tag-' + s.action, ACTION_NAMES[s.action] +
      (s.issue_type ? ' · ' + s.issue_type : '')));
    head.appendChild(el('span', 'agent-tag agent-tag-rule', s.rule_id + ' ' + (RULE_NAMES[s.rule_id] || '')));
    if (s.scope.community) head.appendChild(el('span', 'agent-sug-scope', s.scope.community));
    if (s.action === 'price_change') {
      head.appendChild(el('span', 'agent-sug-price', s.current_price + ' → ' + s.proposed_price + ' 元（' +
        (s.change_pct * 100).toFixed(2) + '%）'));
    }
    if (s.needs_manual_review) {
      var mr = el('span', 'agent-tag agent-tag-manual', '需人工评估');
      mr.setAttribute('data-needs-manual-review', 'true');
      head.appendChild(mr);
    }
    if (s.preview_id && committedPreviews[s.preview_id]) head.appendChild(el('span', 'agent-tag agent-tag-done', '已提交'));
    if (s.preview && !s.preview.ok) head.appendChild(el('span', 'agent-tag agent-tag-fail', '预览未通过：' + (s.preview.reject_reason || '')));
    card.appendChild(head);

    card.appendChild(el('p', 'agent-sug-expl', s.explanation));
    if (s.preview && s.preview.row && s.preview.row.reason) {
      var rs = el('p', 'agent-sug-reason');
      rs.appendChild(el('b', null, '申请理由：'));
      rs.appendChild(document.createTextNode(s.preview.row.reason));
      card.appendChild(rs);
    }

    var ev = el('div', 'agent-sug-evidence');
    (s.evidence.metrics || []).forEach(function (m) {
      var chip = el('span', 'agent-metric', fmtMetric(m));
      chip.title = m.ref + ' ' + JSON.stringify(m.params);
      chip.setAttribute('data-metric', m.key);
      ev.appendChild(chip);
    });
    card.appendChild(ev);

    var foot = el('div', 'agent-sug-foot');
    if (s.evidence.review_ids && s.evidence.review_ids.length) {
      foot.appendChild(el('span', 'agent-sug-reviews', '评论 ID：' + s.evidence.review_ids.join('、')));
    }
    foot.appendChild(el('span', 'agent-sug-rules', '条款：' + s.rules.join('、')));
    card.appendChild(foot);
    return card;
  }

  function renderFilter(sugs) {
    filterEl.textContent = '';
    var counts = {};
    sugs.forEach(function (s) { counts[s.rule_id] = (counts[s.rule_id] || 0) + 1; });
    var all = el('button', 'agent-filter-btn' + (activeRule === '' ? ' is-active' : ''), '全部 ' + sugs.length);
    all.type = 'button';
    all.addEventListener('click', function () { activeRule = ''; renderSuggestions(); });
    filterEl.appendChild(all);
    RULE_ORDER.forEach(function (r) {
      if (!counts[r]) return;
      var b = el('button', 'agent-filter-btn' + (activeRule === r ? ' is-active' : ''), RULE_NAMES[r] + ' ' + counts[r]);
      b.type = 'button';
      b.setAttribute('data-agent-filter-rule', r);
      b.addEventListener('click', function () { activeRule = r; renderSuggestions(); });
      filterEl.appendChild(b);
    });
  }

  function renderSuggestions() {
    if (!current) return;
    var sugs = current.suggestions || [];
    sugBox.hidden = !sugs.length;
    var picks = sugs.filter(selectable).length;
    sugCount.textContent = '共 ' + sugs.length + ' 条 · 可提交 ' + picks + ' 条';
    renderFilter(sugs);
    sugList.textContent = '';
    var ordered = sugs.slice().sort(function (a, b) {
      return RULE_ORDER.indexOf(a.rule_id) - RULE_ORDER.indexOf(b.rule_id) ||
        (b.needs_manual_review ? 1 : 0) - (a.needs_manual_review ? 1 : 0);
    });
    ordered.forEach(function (s) {
      var card = renderSuggestion(s);
      if (activeRule && s.rule_id !== activeRule) card.hidden = true;
      sugList.appendChild(card);
    });
    updateCommitBtn();
  }

  function pickedIds() {
    var ids = [];
    sugList.querySelectorAll('input[data-agent-pick]').forEach(function (cb) {
      if (cb.checked && !cb.disabled && cb.getAttribute('data-agent-pick')) ids.push(cb.getAttribute('data-agent-pick'));
    });
    return ids;
  }

  function updateCommitBtn() {
    var n = pickedIds().length;
    commitBtn.disabled = n === 0;
    commitBtn.textContent = n ? '确认提交到待审批（' + n + ' 条）' : '确认提交到待审批';
  }

  function renderReport(s) {
    reportBox.hidden = !s.report;
    reportText.textContent = s.report || '';
    notesEl.textContent = '';
    RULE_ORDER.forEach(function (r) {
      var note = s.category_notes && s.category_notes[r];
      if (!note) return;
      var li = el('li', null);
      li.appendChild(el('b', null, RULE_NAMES[r] + '：'));
      li.appendChild(document.createTextNode(note));
      notesEl.appendChild(li);
    });
  }

  function renderRun(s) {
    renderSteps(s.steps || []);
    if (s.state === 'running') return;
    current = s;
    renderReport(s);
    renderSuggestions();
    var degraded = !!s.degraded;
    degradedEl.hidden = !degraded;
    degradeReason.textContent = degraded ? (s.degrade_reason || '') : '';
    var meta = s.meta || {};
    setState(s.state === 'ready' ? 'ready' : 'error',
      (s.state === 'ready' ? '巡检完成' : '巡检失败') + ' · ' + (s.mode === 'agent' ? '模型参与' : '规则模式') +
      ' · 模型调用 ' + (meta.llm_calls || 0) + ' 次 · ' + ((meta.elapsed_ms || 0) / 1000).toFixed(1) + ' 秒');
  }

  function poll(runId) {
    api('GET', '/api/agent/run/' + encodeURIComponent(runId)).then(function (s) {
      renderRun(s);
      if (s.state === 'running') setTimeout(function () { poll(runId); }, POLL_MS);
    }).catch(function (e) {
      errorEl.hidden = false;
      errorEl.textContent = '读取巡检进度失败：' + e.message;
      setState('error');
    });
  }

  runBtn.addEventListener('click', function () {
    stepsEl.textContent = '';
    stepCount.textContent = '0';
    errorEl.hidden = true;
    commitResult.hidden = true;
    degradedEl.hidden = true;
    reportBox.hidden = true;
    sugBox.hidden = true;
    current = null;
    committedPreviews = {};
    activeRule = '';
    setState('running');
    api('POST', '/api/agent/run', { use_llm: !!useLlm.checked }).then(function (r) {
      poll(r.run_id);
    }).catch(function (e) {
      errorEl.hidden = false;
      errorEl.textContent = '巡检启动失败：' + e.message;
      setState('error');
    });
  });

  checkAll.addEventListener('change', function () {
    sugList.querySelectorAll('input[data-agent-pick]').forEach(function (cb) {
      if (!cb.disabled) cb.checked = checkAll.checked;
    });
    updateCommitBtn();
  });

  commitBtn.addEventListener('click', function () {
    var ids = pickedIds();
    if (!ids.length) return;
    commitBtn.disabled = true;
    api('POST', '/api/ops/commit', { preview_ids: ids }).then(function (r) {
      (r.committed || []).forEach(function (c) { committedPreviews[c.preview_id] = true; });
      (r.rejected || []).forEach(function (c) { committedPreviews[c.preview_id] = true; });
      var lines = ['已提交 ' + (r.committed || []).length + ' 条进入待审批'];
      if ((r.rejected || []).length) {
        lines.push('未通过 ' + r.rejected.length + ' 条：' + r.rejected.map(function (x) {
          return x.reason.split(' ')[0];
        }).join('、'));
      }
      commitResult.hidden = false;
      commitResult.textContent = lines.join('；');
      renderSuggestions();
      loadItems();
    }).catch(function (e) {
      commitResult.hidden = false;
      commitResult.textContent = '提交失败：' + e.message;
      updateCommitBtn();
    });
  });

  // ------------------------------------------------------------------ 待审批
  function itemRow(kind, row) {
    var id = kind === 'ticket' ? row.ticket_id : row.request_id;
    var box = el('div', 'agent-ops-item is-' + row.status);
    box.setAttribute('data-ops-item', kind + '-' + id);
    box.setAttribute('data-kind', kind);
    box.setAttribute('data-status', row.status);
    box.appendChild(el('b', 'agent-sug-id', row.listing_id));
    box.appendChild(el('span', 'agent-tag agent-tag-' + (kind === 'ticket' ? 'ticket' : 'price_change'),
      kind === 'ticket' ? '整改工单 · ' + row.issue_type : '调价申请'));
    if (kind !== 'ticket') {
      box.appendChild(el('span', 'agent-sug-price', row.current_price + ' → ' + row.proposed_price + ' 元（' +
        (row.change_pct * 100).toFixed(2) + '%）'));
    }
    box.appendChild(el('span', 'agent-ops-status', row.status + (row.approver ? ' · ' + row.approver : '')));
    var actions = el('span', 'agent-ops-actions');
    [['approve', '批准'], ['reject', '驳回']].forEach(function (pair) {
      var b = el('button', 'agent-decide agent-decide-' + pair[0], pair[1]);
      b.type = 'button';
      b.setAttribute('data-decision', pair[0]);
      b.disabled = row.status !== '待审';
      b.addEventListener('click', function () { decide(kind, id, pair[0], b); });
      actions.appendChild(b);
    });
    box.appendChild(actions);
    if (kind !== 'ticket' && row.reason) box.title = row.reason;
    return box;
  }

  function loadItems() {
    return api('GET', '/api/ops/items').then(function (r) {
      opsItems.textContent = '';
      var rows = [];
      (r.maintenance_tickets || []).forEach(function (x) { rows.push(['ticket', x]); });
      (r.price_change_requests || []).forEach(function (x) { rows.push(['price_change', x]); });
      if (!rows.length) {
        opsItems.appendChild(el('p', 'agent-empty', '暂无待审批项'));
        return;
      }
      var pending = rows.filter(function (x) { return x[1].status === '待审'; }).length;
      opsItems.appendChild(el('p', 'agent-ops-count', '共 ' + rows.length + ' 条，其中待审 ' + pending + ' 条'));
      rows.forEach(function (x) { opsItems.appendChild(itemRow(x[0], x[1])); });
    }).catch(function () { /* 后端未就绪时静默 */ });
  }

  function decide(kind, id, verdict, btn) {
    btn.disabled = true;
    api('POST', '/api/ops/decision', { kind: kind, id: id, decision: verdict }).then(function (r) {
      decisionResult.hidden = false;
      decisionResult.textContent = (kind === 'ticket' ? '工单 #' : '调价申请 #') + id + ' 已' + r.status +
        (r.outbox ? ' · 已生成邮件草稿 ' + r.outbox + '（未发送）' : '');
      loadItems();
    }).catch(function (e) {
      decisionResult.hidden = false;
      decisionResult.textContent = '操作失败：' + e.message;
      loadItems();
    });
  }

  opsRefresh.addEventListener('click', loadItems);
  setState('idle');
  loadItems();
})();
