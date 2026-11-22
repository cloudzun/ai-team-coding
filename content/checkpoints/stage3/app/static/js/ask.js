/* 问数面板（规格 4.1）。
 * 只做三件事：提交问题、按响应渲染、按 data-ask-state 切换面板状态。
 * 不碰 data-view，不影响 r1 的六视角遍历。 */
(function () {
  'use strict';

  var panel = document.querySelector('[data-panel="ask"]');
  if (!panel) return;

  var form = panel.querySelector('[data-ask-form]');
  var input = panel.querySelector('[data-ask-input]');
  var submit = panel.querySelector('[data-ask-submit]');
  var stateMsg = panel.querySelector('[data-ask-state-msg]');
  var answerEl = panel.querySelector('[data-ask-answer]');
  var loadingEl = panel.querySelector('[data-ask-loading]');
  var errorEl = panel.querySelector('[data-ask-error]');
  var degradedEl = panel.querySelector('[data-ask-degraded]');
  var degradeReasonEl = panel.querySelector('[data-ask-degrade-reason]');
  var diagnosisEl = panel.querySelector('[data-ask-diagnosis]');
  var citationsEl = panel.querySelector('[data-ask-citations]');
  var stepsEl = panel.querySelector('[data-ask-steps]');
  var stepListEl = panel.querySelector('[data-ask-step-list]');
  var stepCountEl = panel.querySelector('[data-ask-step-count]');
  var examplesEl = panel.querySelector('[data-ask-examples]');

  var MAX_TABLE_ROWS = 20;
  var STATE_TEXT = {
    idle: '可以提问',
    loading: '正在查询…',
    ready: '已完成',
    error: '查询失败',
    refused: '已拒绝'
  };

  function setState(state) {
    panel.setAttribute('data-ask-state', state);
    if (stateMsg) stateMsg.textContent = STATE_TEXT[state] || '';
    if (loadingEl) loadingEl.hidden = state !== 'loading';
    if (errorEl) errorEl.hidden = state !== 'error';
    if (submit) {
      submit.disabled = state === 'loading';
      submit.textContent = state === 'loading' ? '查询中…' : '提问';
    }
  }

  function clearResult() {
    if (answerEl) { answerEl.hidden = true; answerEl.textContent = ''; }
    if (degradedEl) degradedEl.hidden = true;
    if (diagnosisEl) { diagnosisEl.hidden = true; diagnosisEl.textContent = ''; }
    if (citationsEl) { citationsEl.hidden = true; citationsEl.textContent = ''; }
    if (stepsEl) stepsEl.hidden = true;
    if (stepListEl) stepListEl.textContent = '';
    if (stepCountEl) stepCountEl.textContent = '0';
  }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function renderSteps(steps) {
    if (!steps || !steps.length) return;
    stepListEl.textContent = '';
    steps.forEach(function (step, index) {
      var box = el('div', 'ask-step');
      box.setAttribute('data-step', String(index + 1));

      var head = el('div', 'ask-step-head');
      head.appendChild(el('b', null, '第 ' + (index + 1) + ' 步'));
      head.appendChild(el('span', null, step.purpose || '查询'));
      head.appendChild(el('span', 'ask-step-meta',
        '返回 ' + (step.row_count || 0) + ' 行' + (step.truncated ? '（已截断到 200 行）' : '') +
        ' · ' + (step.elapsed_ms || 0) + ' ms'));
      box.appendChild(head);

      if (step.sql) {
        var sql = el('pre', null, null);
        sql.setAttribute('data-step-sql', '');
        sql.textContent = step.sql;
        box.appendChild(sql);
      }

      if (step.error) {
        box.appendChild(el('p', 'ask-step-error', '这一步执行失败：' + step.error));
      }

      if (step.columns && step.columns.length) {
        var wrap = el('div', 'ask-table-wrap');
        var table = el('table', 'ask-table');
        var thead = el('thead');
        var hrow = el('tr');
        step.columns.forEach(function (name) { hrow.appendChild(el('th', null, name)); });
        thead.appendChild(hrow);
        table.appendChild(thead);
        var tbody = el('tbody');
        (step.rows || []).slice(0, MAX_TABLE_ROWS).forEach(function (row) {
          var tr = el('tr');
          step.columns.forEach(function (name, i) {
            var value = row[i];
            var cell = el('td', typeof value === 'number' ? 'num' : null,
              value === null || value === undefined ? '—' : value);
            tr.appendChild(cell);
          });
          tbody.appendChild(tr);
        });
        table.appendChild(tbody);
        wrap.appendChild(table);
        box.appendChild(wrap);

        var total = step.row_count || 0;
        if (total > MAX_TABLE_ROWS || step.truncated) {
          box.appendChild(el('p', 'ask-step-more',
            '共 ' + total + ' 行，仅显示前 ' + Math.min(total, MAX_TABLE_ROWS) + ' 行'));
        }
      }

      stepListEl.appendChild(box);
    });
    if (stepCountEl) stepCountEl.textContent = String(steps.length);
    stepsEl.hidden = false;
  }

  function renderCitations(citations) {
    if (!citations || !citations.length) {
      citationsEl.hidden = true;
      return;
    }
    citationsEl.textContent = '';
    citations.forEach(function (item) {
      var details = el('details', 'ask-citation');
      var summary = el('summary');
      summary.setAttribute('data-review-id', item.review_id);
      summary.textContent = item.review_id;
      details.appendChild(summary);

      var body = el('div', 'ask-citation-body');
      body.appendChild(el('div', 'ask-citation-meta',
        (item.community || '') + ' · ' + (item.review_date || '') + ' · 评分 ' +
        (item.rating === null || item.rating === undefined ? '—' : item.rating)));
      var content = el('p', 'ask-citation-content');
      content.textContent = item.content || '';
      body.appendChild(content);
      details.appendChild(body);
      citationsEl.appendChild(details);
    });
    citationsEl.hidden = false;
  }

  function renderEvidence(evidence) {
    var wrap = el('span', 'ask-evidence');
    wrap.appendChild(el('span', null, '证据'));
    (evidence || []).forEach(function (item) {
      if (item && typeof item.step === 'number') {
        wrap.appendChild(el('span', null, '第 ' + item.step + ' 步'));
      } else if (item && item.review_id) {
        wrap.appendChild(el('span', null, item.review_id));
      }
    });
    return wrap;
  }

  function renderDiagnosis(diagnosis) {
    if (!diagnosis) {
      diagnosisEl.hidden = true;
      return;
    }
    diagnosisEl.textContent = '';

    if (diagnosis.findings && diagnosis.findings.length) {
      var block = el('div', 'ask-diag-block');
      block.appendChild(el('h3', null, '发现'));
      var list = el('ol');
      diagnosis.findings.forEach(function (item) {
        var li = el('li');
        li.appendChild(el('span', null, item.statement || ''));
        li.appendChild(renderEvidence(item.evidence));
        list.appendChild(li);
      });
      block.appendChild(list);
      diagnosisEl.appendChild(block);
    }

    if (diagnosis.suggestions && diagnosis.suggestions.length) {
      var sblock = el('div', 'ask-diag-block');
      sblock.appendChild(el('h3', null, '建议'));
      var olist = el('ol');
      diagnosis.suggestions.forEach(function (item) {
        var li = el('li');
        li.appendChild(el('strong', null, item.action || ''));
        if (item.rationale) li.appendChild(el('span', null, '：' + item.rationale));
        li.appendChild(renderEvidence(item.evidence));
        olist.appendChild(li);
      });
      sblock.appendChild(olist);
      diagnosisEl.appendChild(sblock);
    }

    diagnosisEl.hidden = !diagnosisEl.childNodes.length;
  }

  function render(payload) {
    clearResult();
    var mode = payload.mode || 'query';
    if (mode === 'refused') setState('refused');
    else setState('ready');

    if (answerEl) {
      answerEl.textContent = payload.answer || '';
      answerEl.hidden = !payload.answer;
    }

    var meta = payload.meta || {};
    if (meta.degraded && degradedEl) {
      if (degradeReasonEl) degradeReasonEl.textContent = meta.degrade_reason || '未知';
      degradedEl.hidden = false;
    }

    renderDiagnosis(payload.diagnosis);
    renderCitations(payload.citations);
    renderSteps(payload.steps);

    if (stateMsg && meta.elapsed_ms) {
      stateMsg.textContent = (STATE_TEXT[mode === 'refused' ? 'refused' : 'ready'] || '已完成') +
        ' · 用时 ' + (meta.elapsed_ms / 1000).toFixed(1) + ' 秒';
    }
  }

  function fail(message) {
    clearResult();
    setState('error');
    if (errorEl) errorEl.textContent = message || '模型服务不可用，看板其余部分不受影响';
  }

  function ask(question) {
    var text = (question || '').trim();
    if (!text) {
      input.focus();
      return;
    }
    input.value = text;
    clearResult();
    setState('loading');

    fetch('/api/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: text })
    }).then(function (response) {
      if (response.status === 503) {
        fail('模型服务不可用，看板其余部分不受影响');
        return null;
      }
      if (!response.ok) {
        fail(response.status === 422
          ? '问题需为 1–200 字，请调整后再试'
          : '查询失败（HTTP ' + response.status + '），看板其余部分不受影响');
        return null;
      }
      return response.json();
    }).then(function (payload) {
      if (payload) render(payload);
    }).catch(function () {
      fail('模型服务不可用，看板其余部分不受影响');
    });
  }

  if (form) {
    form.addEventListener('submit', function (event) {
      event.preventDefault();
      ask(input ? input.value : '');
    });
  }

  if (input) {
    input.addEventListener('keydown', function (event) {
      if (event.key === 'Enter' && !event.isComposing) {
        event.preventDefault();
        ask(input.value);
      }
    });
  }

  if (examplesEl) {
    examplesEl.addEventListener('click', function (event) {
      var button = event.target.closest('button');
      if (!button || !examplesEl.contains(button)) return;
      ask(button.textContent || '');
    });
  }

  setState('idle');
})();
