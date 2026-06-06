"""Mode B (form) JS 렌더러 — SESSION_SHELL_HTML 조립용 string export.

Issue30: server.py 에서 추출. inferType + renderField + renderForm + collectAnswers
+ submitForm + renderAnswerPlaceholder + copyAnswersJSON 7개 함수 포함.
"""

FORM_JS = r"""
// Issue18 Phase 2: Mode B form renderer (field type 확장)
// supported types: radio (default w/options), checkbox (multiSelect), text, textarea, number, slider, date
function inferType(q) {
  if (q.type) return q.type;
  if (Array.isArray(q.options) && q.options.length) return q.multiSelect ? 'checkbox' : 'radio';
  return 'text';
}

function renderField(q, qi) {
  const type = inferType(q);
  const fieldName = `q${qi}`;
  const required = q.required ? ' required' : '';
  if (type === 'radio' || type === 'checkbox') {
    const opts = Array.isArray(q.options) ? q.options : [];
    return `<div class="q-opts">${opts.map((o, oi) => `
      <label class="q-opt">
        <input type="${type}" name="${fieldName}" value="${esc(o.label)}" data-qi="${qi}" data-oi="${oi}"${required}>
        <div class="q-opt-body">
          <div class="q-opt-label">${esc(o.label)}</div>
          ${o.description ? `<div class="q-opt-desc">${esc(o.description)}</div>` : ''}
        </div>
      </label>`).join('') || '<em>(no options)</em>'}</div>`;
  }
  if (type === 'text') {
    return `<div class="q-field">
      <input type="text" name="${fieldName}" data-qi="${qi}" data-type="text" placeholder="${esc(q.placeholder || '')}" value="${esc(q.default || '')}"${required}>
      ${q.hint ? `<div class="q-hint">${esc(q.hint)}</div>` : ''}
    </div>`;
  }
  if (type === 'textarea') {
    const rows = Number(q.rows) || 4;
    return `<div class="q-field">
      <textarea name="${fieldName}" data-qi="${qi}" data-type="textarea" rows="${rows}" placeholder="${esc(q.placeholder || '')}"${required}>${esc(q.default || '')}</textarea>
      ${q.hint ? `<div class="q-hint">${esc(q.hint)}</div>` : ''}
    </div>`;
  }
  if (type === 'number') {
    const min = q.min !== undefined ? ` min="${q.min}"` : '';
    const max = q.max !== undefined ? ` max="${q.max}"` : '';
    const step = q.step !== undefined ? ` step="${q.step}"` : '';
    return `<div class="q-field">
      <input type="number" name="${fieldName}" data-qi="${qi}" data-type="number"${min}${max}${step} value="${esc(q.default !== undefined ? q.default : '')}"${required}>
      ${q.hint ? `<div class="q-hint">${esc(q.hint)}</div>` : ''}
    </div>`;
  }
  if (type === 'slider') {
    const min = q.min !== undefined ? q.min : 0;
    const max = q.max !== undefined ? q.max : 100;
    const step = q.step !== undefined ? q.step : 1;
    const def = q.default !== undefined ? q.default : Math.round((Number(min) + Number(max)) / 2);
    return `<div class="q-field">
      <div class="q-slider-row">
        <input type="range" name="${fieldName}" data-qi="${qi}" data-type="slider" min="${min}" max="${max}" step="${step}" value="${def}" oninput="this.nextElementSibling.textContent=this.value">
        <span class="q-slider-val">${def}</span>
      </div>
      ${q.hint ? `<div class="q-hint">${esc(q.hint)} (범위 ${min}~${max})</div>` : `<div class="q-hint">범위 ${min}~${max}</div>`}
    </div>`;
  }
  if (type === 'date') {
    return `<div class="q-field">
      <input type="date" name="${fieldName}" data-qi="${qi}" data-type="date" value="${esc(q.default || '')}"${required}>
      ${q.hint ? `<div class="q-hint">${esc(q.hint)}</div>` : ''}
    </div>`;
  }
  return `<div class="form-msg err">⚠ unknown field type: ${esc(type)}</div>`;
}

function renderForm(content) {
  const data = parseJSON(content);
  if (!data || !Array.isArray(data.questions)) {
    return `<div class="form-msg err">⚠ form JSON 파싱 실패. 기대 스키마: {questions:[{question, header, type?, options?, multiSelect?, required?, placeholder?, default?, min?, max?, step?, rows?, hint?}]}</div><pre>${esc(content)}</pre>`;
  }
  const cards = data.questions.map((q, qi) => {
    const reqMark = q.required ? '<span class="q-required-mark">*</span>' : '';
    return `
      <div class="q-card" data-qi="${qi}" data-type="${esc(inferType(q))}">
        <div class="q-head">
          ${q.header ? `<span class="q-header">${esc(q.header)}</span>` : ''}
          <span class="q-title">${esc(q.question || '(no question)')}${reqMark}</span>
        </div>
        ${renderField(q, qi)}
      </div>`;
  }).join('');
  return `
    <form id="qa-form">
      ${cards}
      <div class="form-actions">
        <button type="button" class="btn-submit" id="qa-submit">전송</button>
        <span class="form-msg" id="qa-msg"></span>
      </div>
    </form>`;
}

function collectAnswers() {
  const out = [];
  const cards = contentEl.querySelectorAll('.q-card');
  cards.forEach(card => {
    const question = card.querySelector('.q-title').textContent.replace(/\*$/, '');
    const fieldType = card.dataset.type;
    let value;
    if (fieldType === 'radio' || fieldType === 'checkbox') {
      const inputs = card.querySelectorAll('input:checked');
      if (inputs.length === 0) value = null;
      else if (inputs.length === 1) value = inputs[0].value;
      else value = Array.from(inputs).map(i => i.value);
    } else if (fieldType === 'textarea') {
      const ta = card.querySelector('textarea');
      const v = ta ? ta.value.trim() : '';
      value = v === '' ? null : v;
    } else if (fieldType === 'number' || fieldType === 'slider') {
      const inp = card.querySelector('input');
      if (!inp || inp.value === '') value = null;
      else value = Number(inp.value);
    } else {
      const inp = card.querySelector('input');
      const v = inp ? inp.value.trim() : '';
      value = v === '' ? null : v;
    }
    out.push({question, value});
  });
  return out;
}

async function submitForm() {
  const btn = document.getElementById('qa-submit');
  const msg = document.getElementById('qa-msg');
  btn.disabled = true;
  msg.textContent = '전송 중...';
  msg.className = 'form-msg';
  const answers = collectAnswers();
  try {
    const r = await fetch(ANSWER_URL, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({answers})
    });
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status));
    msg.textContent = '✓ 전송됨';
    msg.className = 'form-msg ok';
    // Issue26: 즉시 paste-back UI 렌더 (reload 의존 제거)
    // server 가 동일 placeholder 를 session content 로 저장하므로 SSE swap 도 일치
    const record = j.record || {sid: SID, ts: j.ts, answers, source: 'session_answer'};
    renderAnswerPlaceholder(record);
  } catch (e) {
    msg.textContent = '❌ ' + e.message;
    msg.className = 'form-msg err';
    btn.disabled = false;
  }
}

// Issue26: 답변 JSON + 복사 버튼 paste-back fallback UI
function renderAnswerPlaceholder(record) {
  const jsonStr = JSON.stringify(record, null, 2);
  const html = ''
    + '<div class="answer-placeholder">'
    + '<p><strong>✓ 답변 전송됨</strong> — Claude 처리 대기 중...</p>'
    + '<p style="color:var(--muted);font-size:0.9em">'
    + 'polling 누락·timeout·세션 교체로 회수 실패 시 아래 JSON 을 채팅에 paste 하면 회수 가능.'
    + '</p>'
    + '<div class="answer-actions">'
    + '<button type="button" class="copy-btn" onclick="copyAnswersJSON(this)" data-json="' + esc(jsonStr) + '">📋 JSON 복사</button>'
    + '<span class="copy-msg" id="copy-msg"></span>'
    + '</div>'
    + '<pre class="answer-json">' + esc(jsonStr) + '</pre>'
    + '</div>';
  const contentEl = document.getElementById('content');
  if (contentEl) contentEl.innerHTML = html;
}

// Issue26: 복사 버튼 핸들러 (server-side placeholder 와 client-side 양쪽 사용)
function copyAnswersJSON(btn) {
  const jsonStr = btn.getAttribute('data-json') || '';
  const msg = document.getElementById('copy-msg');
  // data-json 은 HTML escape 된 상태 → DOM 자동 decode (innerHTML 경유 시 자동)
  // 단 attribute 는 escape 보존되므로 textarea 우회 decode
  const ta = document.createElement('textarea');
  ta.innerHTML = jsonStr;
  const decoded = ta.value;
  navigator.clipboard.writeText(decoded).then(() => {
    if (msg) { msg.textContent = '✅ 복사됨 — 채팅에 paste'; msg.className = 'copy-msg ok'; }
    btn.disabled = true;
    setTimeout(() => { btn.disabled = false; if (msg) msg.textContent = ''; }, 4000);
  }).catch(e => {
    if (msg) { msg.textContent = '❌ 복사 실패: ' + e.message; msg.className = 'copy-msg err'; }
  });
}
"""
