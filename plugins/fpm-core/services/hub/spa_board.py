"""Mode C dashboard 컴포지터 JS — SESSION_SHELL_HTML 조립용 string export.

Issue30: server.py 에서 추출. renderDashboard + dispatchWidgetAction
+ dashStop/dashRefresh/dashKillPane (controls 액션) 포함.
renderWidget 의존 (spa_widgets.WIDGET_JS 와 동일 scope 에서 concat 필수).
"""

DASHBOARD_JS = r"""
function renderDashboard(content) {
  const data = parseJSON(content);
  if (!data) {
    return `<div class="form-msg err">⚠ dashboard JSON 파싱 실패</div><pre>${esc(content)}</pre>`;
  }
  const widgets = Array.isArray(data.widgets) ? data.widgets : [];
  // Issue63: status 배지 + 메타 칩 — runner 생존을 detail page 에서 가시화.
  //   서버가 runner pid dead 감지 시 status=stopped override + _runner_dead 플래그를 주입.
  const st = data._runner_dead ? 'stopped' : (data.status || 'running');
  const stMap = {
    running: ['🟢', 'running', 'st-running'],
    stopped: ['🔴', 'stopped', 'st-stopped'],
    done:    ['✅', 'done',    'st-done'],
  };
  const sm = stMap[st] || ['⚪', String(st), 'st-unknown'];
  const deadNote = data._runner_dead ? `<span class="st-deadnote">⚠ runner 종료됨</span>` : '';
  const statusBadge = `<span class="dash-status ${sm[2]}">${sm[0]} ${esc(sm[1])}${deadNote}</span>`;
  const titleTxt = data.title ? esc(data.title) : 'dashboard';
  const header = `<div class="dash-head"><h2>${titleTxt}</h2>${statusBadge}</div>`;
  const chips = [];
  if (data.pid) chips.push('pid ' + esc(data.pid));
  if (data.worker_pid) chips.push('worker ' + esc(data.worker_pid));
  if (typeof data.iter === 'number') chips.push('iter ' + data.iter);
  if (data.interval) chips.push('every ' + esc(data.interval) + 's');
  if (data.updated_at) chips.push('upd ' + esc(String(data.updated_at).slice(11, 19)));
  const metaBar = chips.length ? `<div class="dash-meta">${chips.map(c => `<span class="chip">${c}</span>`).join('')}</div>` : '';
  if (!widgets.length) return `${header}${metaBar}<em>(no widgets)</em>`;
  // Issue50: controls 바 — stop/kill_pane 버튼 렌더. Issue27: refresh 버튼 추가
  const controls = (data.controls && typeof data.controls === 'object') ? data.controls : {};
  const pid = data.pid;
  const winName = data.window_name || '';
  let ctrlBar = '';
  if (pid) {
    const refreshBtn = controls.refresh ? `<button class="dash-ctrl refresh" onclick="dashRefresh(${pid}, this)">🔄 refresh</button>` : '';
    const stopBtn = controls.stop ? `<button class="dash-ctrl stop" onclick="dashStop(${pid}, this)">⏹ stop pid=${pid}</button>` : '';
    const killBtn = (controls.kill_pane && winName) ? `<button class="dash-ctrl kill" onclick="dashKillPane(${pid}, '${esc(winName)}', this)">✕ kill pane ${esc(winName)}</button>` : '';
    if (refreshBtn || stopBtn || killBtn) ctrlBar = `<div class="dash-controls">${refreshBtn}${stopBtn}${killBtn}</div>`;
  }
  // Issue24 Phase 3: 위젯 action 래핑 — clickable wrapper + data attrs
  // Issue77 (글로벌 .claude#Issue91 짝): width 힌트 — w.width==='full' 시 그리드 전폭(1컬럼 행).
  //   action 위젯도 width:full 가능 → widget-actionable 과 w-full 클래스 병행 부착.
  const rendered = widgets.map((w, i) => {
    const html = renderWidget(w);
    const isFull = w && w.width === 'full';
    if (w && w.action && typeof w.action === 'object') {
      const a = w.action;
      const attrs = `data-action-type="${esc(a.type || '')}" data-widget-index="${i}" data-widget-type="${esc(w.type || '')}" data-action-url="${esc(a.url || '')}"`;
      const label = (w.title || w.label || w.type || ('widget#' + i));
      const cls = isFull ? 'widget-actionable w-full' : 'widget-actionable';
      return `<div class="${cls}" ${attrs} data-label="${esc(label)}" title="action: ${esc(a.type)}">${html}</div>`;
    }
    // action 없는 width:full 위젯 — w-full wrapper 로 감싸 전폭 행 점유.
    if (isFull) return `<div class="w-full">${html}</div>`;
    return html;
  }).join('');
  return `${header}${metaBar}${ctrlBar}<div class="dash-grid">${rendered}</div>`;
}

// Issue24 Phase 3: 위젯 action click dispatcher (delegated)
async function dispatchWidgetAction(wrapper) {
  const atype = wrapper.dataset.actionType;
  const widx = parseInt(wrapper.dataset.widgetIndex);
  const wtype = wrapper.dataset.widgetType;
  const label = wrapper.dataset.label;
  if (atype === 'link') {
    const url = wrapper.dataset.actionUrl;
    if (url) window.open(url, '_blank', 'noopener,noreferrer');
    return;
  }
  if (atype === 'notify') {
    try {
      const r = await fetch(ACTION_URL, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({widget_index: widx, widget_type: wtype, action_type: 'notify', label: label})
      });
      if (r.ok) { wrapper.classList.add('action-ok'); setTimeout(() => wrapper.classList.remove('action-ok'), 1500); }
      else { wrapper.classList.add('action-err'); setTimeout(() => wrapper.classList.remove('action-err'), 2500); }
    } catch (e) { console.warn('notify failed', e); }
    return;
  }
  if (atype === 'control') {
    // 기존 /control endpoint 위임 — pid 는 wrapper data 에 없으면 dashboard payload pid 사용 (생략)
    console.warn('control action: handle via existing /control endpoint with pid');
  }
}

document.addEventListener('click', (e) => {
  const wrapper = e.target.closest('.widget-actionable');
  if (wrapper) dispatchWidgetAction(wrapper);
});

async function dashStop(pid, btn) {
  if (!confirm('runner pid=' + pid + ' 정지? (graceful SIGTERM, worker_pid 자동 회수)')) return;
  btn.disabled = true; btn.textContent = '...';
  try {
    const r = await fetch('/control?cwd=' + CWD_Q + '&token=' + encodeURIComponent(TOKEN), {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({action: 'stop', pid: pid})
    });
    const j = await r.json();
    if (r.ok) { btn.textContent = '✅ ' + (j.status || 'stopped'); }
    else { btn.disabled = false; btn.textContent = '❌ ' + (j.error || r.status); }
  } catch (e) { btn.disabled = false; btn.textContent = '❌ ' + e.message; }
}

// Issue27: refresh 버튼 — runner SIGUSR1 + 클라이언트 DOM 강제 swap (양쪽 다)
async function dashRefresh(pid, btn) {
  const orig = btn.textContent;
  btn.disabled = true; btn.textContent = '⏳';
  try {
    const r = await fetch('/control?cwd=' + CWD_Q + '&token=' + encodeURIComponent(TOKEN), {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({action: 'refresh', pid: pid})
    });
    const j = await r.json();
    if (!r.ok) {
      btn.disabled = false; btn.textContent = '❌ ' + (j.error || r.status);
      setTimeout(() => { btn.textContent = orig; }, 2500);
      return;
    }
    // 클라이언트 DOM 강제 swap (서버 push 도착 전 즉시 갱신)
    try { await reload(true); } catch (e) { console.warn('reload failed', e); }
    btn.textContent = '✅';
    setTimeout(() => { btn.disabled = false; btn.textContent = orig; }, 800);
  } catch (e) {
    btn.disabled = false; btn.textContent = '❌ ' + e.message;
    setTimeout(() => { btn.textContent = orig; }, 2500);
  }
}

async function dashKillPane(pid, win, btn) {
  if (!confirm('tmux window pm:' + win + ' 강제 종료? (runner + worker + pane 동반)')) return;
  btn.disabled = true; btn.textContent = '...';
  try {
    const r = await fetch('/control?cwd=' + CWD_Q + '&token=' + encodeURIComponent(TOKEN), {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({action: 'kill_pane', pid: pid, window_name: win})
    });
    const j = await r.json();
    if (r.ok) { btn.textContent = '✅ killed ' + win; }
    else { btn.disabled = false; btn.textContent = '❌ ' + (j.error || r.status); }
  } catch (e) { btn.disabled = false; btn.textContent = '❌ ' + e.message; }
}
"""
