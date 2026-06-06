// ask-form-template.js — hub Q&A form JS SSOT 템플릿 (Issue68)
//
// ⚠️ 글로벌 SCAR 변경 가드 (Issue46): 본 template 은 모든 프로젝트가 공유.
//   cwd ≠ ~/.claude 면 즉시 수정 금지 → ~/.claude/Issue.md 이슈 등록 후 처리.
//   설계 SSOT: ~/.claude/_doc_arch/hub-mode-arch.md. 절차: ~/.claude/rules/global-scar-change-rules.md
//
// 소비처 (3 생성 경로 — 본 파일이 단일 출처):
//   - hooks/ask-intercept.sh   (Mode B — AskUserQuestion intercept)
//   - hooks/ask-marker-detect.sh   (Mode D — <!-- htm-form:auto --> 마커)
//   - commands/hub.md              (hub 스킬 본문)
// 주입 placeholder:
//   {ANSWER_URL}        → ___pm htm-server answer 엔드포인트 절대 URL
//   {OPEN_PROJECT_URL}  → ___pm htm-server /open-project 엔드포인트 (Issue132 — VSCode focus)
//   {PROJECT_CWD_JSON}  → 프로젝트 cwd 의 JSON 문자열(따옴표 포함). open-project body 임베드용
// 구조 차이 흡수:
//   submit-close-btn / submit-session-btn 은 null-safe — Mode D 는 버튼 없이도 동작 (있으면 바인딩, 없으면 skip)

// Issue39: .q-other 입력 → 동일 fieldset __other__ radio 자동 check
document.querySelectorAll('.q-other').forEach(inp => {
  inp.addEventListener('input', () => {
    const r = inp.closest('fieldset').querySelector('input[value="__other__"]');
    if (r) r.checked = !!inp.value.trim();
  });
});

// Issue43: 카드별 radio/checkbox + .q-other + .q-textarea 통합 수집
function collectAnswers() {
  return Array.from(document.querySelectorAll('.q-card')).map(card => {
    const checked = card.querySelectorAll('input[type=radio]:checked, input[type=checkbox]:checked');
    const other = (card.querySelector('.q-other')?.value || '').trim();
    const textarea = (card.querySelector('.q-textarea')?.value || '').trim();
    const answers = Array.from(checked).map(el => el.value).filter(v => v !== '__other__');
    if (other) answers.push('Other: ' + other);
    if (textarea) answers.push(textarea);
    return { question: card.dataset.question, answers };
  });
}

// 전송 결과 렌더 — 메시지 + JSON paste-back 박스(textarea + 복사 버튼).
// JSON 박스는 성공/실패 양쪽 항상 노출 (Claude polling 만료 대비 복구 수단).
// 색만 status 로 분기: 성공 = 흐린 녹색, 실패 = 빨강.
function renderStatus(st, payload, msg, ok) {
  const fg = ok ? '#080' : '#c00';
  const bg = ok ? '#f3faf3' : '#fff5f5';
  const hint = ok
    ? 'ℹ️ Claude polling 만료(10분 경과) 후라면 회수 안 됨 — 그 경우 아래 JSON 을 채팅에 paste (클릭 시 전체 선택):'
    : '⚠️ 자동 회수 실패 — 아래 JSON 을 채팅에 그대로 paste (클릭 시 전체 선택):';
  st.innerHTML = '<span style="color:' + fg + '">' + msg + '</span>'
    + '<br><small style="color:' + fg + '">' + hint + '</small>';
  const ta = document.createElement('textarea');
  ta.readOnly = true;
  ta.value = JSON.stringify(payload);
  ta.style.cssText = 'width:100%;min-height:4.5em;margin-top:0.4em;font-family:monospace;font-size:0.85em;'
    + 'color:' + fg + ';background:' + bg + ';border:1px solid ' + fg + ';border-radius:4px;padding:0.4em;box-sizing:border-box;';
  ta.onclick = () => ta.select();
  st.appendChild(ta);
  // Issue66: 원클릭 클립보드 복사 버튼
  const copyBtn = document.createElement('button');
  copyBtn.type = 'button';
  copyBtn.textContent = '📋 복사';
  copyBtn.style.cssText = 'margin-top:0.3em;font-size:0.85em;padding:0.2em 0.6em;cursor:pointer;';
  copyBtn.onclick = async () => {
    try { await navigator.clipboard.writeText(ta.value); }
    catch { ta.select(); document.execCommand('copy'); }
    copyBtn.textContent = '✅ 복사됨';
    setTimeout(() => { copyBtn.textContent = '📋 복사'; }, 1500);
  };
  st.appendChild(copyBtn);
}

// Issue55/57: 공통 함수 — 전송·전송 후 닫기 버튼 양쪽 재사용
async function submitAnswers() {
  const payload = collectAnswers();
  try {
    const r = await fetch('{ANSWER_URL}', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload)
    });
    const j = await r.json();
    const st = document.getElementById('status');
    if (r.ok) {
      renderStatus(st, payload, '✅ 전송 완료. Claude 회수 대기 중. 창 닫아도 됩니다.', true);
    } else {
      renderStatus(st, payload, '❌ ' + (j.error || r.status), false);
    }
    return r.ok;
  } catch (e) {
    renderStatus(document.getElementById('status'), payload,
      '❌ 전송 실패: ' + e.message + ' — `/dashboard-server status` 확인 후 재전송', false);
    return false;
  }
}

document.getElementById('submit-btn').addEventListener('click', submitAnswers);

// Issue: Enter 키로 폼 전송 (implicit submit 가로채기 → 페이지 reload 방지)
document.getElementById('qa-form')?.addEventListener('submit', e => {
  e.preventDefault();
  submitAnswers();
});
// Issue57: submit-close-btn 은 선택적 — Mode D(marker-detect)는 버튼 없음 (null-safe)
const closeBtn = document.getElementById('submit-close-btn');
if (closeBtn) closeBtn.addEventListener('click', async () => {
  const ok = await submitAnswers();
  if (ok) window.close();
});

// Issue132: submit-session-btn (전송 후 해당 세션으로) — POST 성공 시 /open-project 로
// 프로젝트 cwd 를 VSCode 로 열어(=세션 포커스) 폼 창 닫기. proj-badge(hub.md)와 동일 endpoint.
// null-safe — Mode D 는 버튼 없음. open-project 실패 시 alert(fail-loud) + 창 유지.
const sessionBtn = document.getElementById('submit-session-btn');
if (sessionBtn) sessionBtn.addEventListener('click', async () => {
  const ok = await submitAnswers();
  if (!ok) return;
  try {
    const r = await fetch('{OPEN_PROJECT_URL}', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({cwd: {PROJECT_CWD_JSON}})
    });
    const j = await r.json().catch(() => ({}));
    if (j && j.error) { alert('VSCode 열기 실패: ' + j.error); return; }
  } catch (e) { alert('hub 서버 미응답 — VSCode 열기 실패'); return; }
  window.close();
});
