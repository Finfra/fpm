#!/usr/bin/env node
// Issue554 회귀 테스트 — /mq 잡 탭 레이아웃: 1열(잡 · 스텝)에 몰린 정보를 옆 열로 나눴는지 판정한다.
//
//   사용자 지적(2026-09-27 주석 스크린샷) 4가지를 구조 성질로 바꿔 검사한다.
//     ① 설명은 스케줄 탭처럼 **이름 줄**(.jname) 안에 — 별도 설명 줄(div.jdesc)이 없다
//     ② «걸린 곳» 은 «최근» 열에 합친다 — thead 에 «최근 · 걸린 곳» 한 열(단독 «걸린 곳»·«최근» 열 없음), 걸린 곳은 최근 **아래**
//        (Issue555 가 «스텝» 열을 끼워 넣었다 — 열 **번호**가 아니라 셀 class 로 찾아 성질만 지킨다)
//     ③ 액션 6버튼은 3열 grid 한 벌 — 실행·수정·멈춤(재개) / 예약·🗓＋·삭제 두 행
//     ④ «⏸ 멈춤»·«🔒 시스템» 표시는 이름 줄에서 빠져 «걸린 곳»(🗓) **왼쪽**에 선다
//
//   Issue521·549 와 같은 방식 — **서버가 실제로 내려준 스크립트를 그대로 실행**하고 고정값을 먹인다.
//   실행: node plugins/fpm-core/services/hub/test_mq_job_layout_issue554.js [url]
//         (기본 http://127.0.0.1:9876/mq — hub 가 떠 있어야 한다)
//   종료: 0=전건 통과 · 1=판정 실패 · 2=페이지·스크립트 취득 실패
'use strict';
const vm = require('vm');
const URL_ = process.argv[2] || 'http://127.0.0.1:9876/mq';

const JOBS = [
  { name:'j-desc', source:'user', desc:'설명 있음', bindings_n:2, last:{rc:0, ts:'2026-09-26T23:04:00'},
    steps:[{kind:'sh', run:'true'}], cwd:'/tmp/w', timeout:60 },
  { name:'j-pz',   source:'user', paused:true, bindings_n:0, last:{rc:0, ts:'2026-09-27T15:17:00'},
    steps:[{kind:'sh', run:'true'}] },
  { name:'sys-j',  source:'system', desc:'시스템 설명', bindings_n:1, steps:[{kind:'sh', run:'true'}] },
];
const QUEUE = [ { id:'q1', job:'j-desc', _bucket:'open', status:'pending' } ];   // → j-desc 에 ⏰ 1

function fetchPage(url){
  const http = url.startsWith('https') ? require('https') : require('http');
  return new Promise((ok, no) => {
    http.get(url, r => { let b=''; r.on('data', c=>b+=c); r.on('end', ()=>ok(b)); }).on('error', no);
  });
}
// 큐 파트의 초기 load()·60초 폴링만 뗀다 — fetch 없는 sandbox 에서 미처리 거부를 남기지 않게
function inlineScript(html){
  const m = html.match(/<script>([\s\S]*?)<\/script>/);
  if(!m) return null;
  return m[1].replace(/^\s*load\(\);\s*setInterval\(load,\s*60000\);\s*$/m, '');
}
function sandbox(){
  const els = {};
  const el = () => ({ textContent:'', innerHTML:'', value:'', checked:false, hidden:false,
    style:{}, dataset:{}, classList:{add(){},remove(){},toggle(){}},
    addEventListener(){}, querySelectorAll:()=>[], closest:()=>null, appendChild(){}, setAttribute(){} });
  const document = { getElementById:id=>els[id]||(els[id]=el()), querySelectorAll:()=>[],
    querySelector:()=>el(), createElement:()=>el(), addEventListener(){}, body:el() };
  const ctx = { document, window:{}, console, URL, URLSearchParams, Date, Math, JSON,
    location:{href:'http://x/mq', search:''}, history:{pushState(){},replaceState(){}},
    addEventListener(){}, setInterval:()=>0, setTimeout:()=>0, clearTimeout(){},
    fetch:()=>Promise.reject(new Error('네트워크 미사용')), EventSource:function(){},
    localStorage:{getItem:()=>null, setItem(){}},
    prompt:()=>null, confirm:()=>false, alert(){}, innerWidth:1200, innerHeight:800 };
  ctx.globalThis = ctx;
  return ctx;
}
const cells = tr => [...tr.matchAll(/<td[^>]*>([\s\S]*?)<\/td>/g)].map(m => m[1]);
const cellOf = (tr, cls) => ((tr.match(new RegExp(`<td class="${cls}">([\\s\\S]*?)<\\/td>`)) || [])[1] || '');
const nameLine = tr => ((tr.match(/<div class="jname">([\s\S]*?)<\/div>/) || [])[1] || '');
const btnLabels = h => [...h.matchAll(/<button[^>]*>([\s\S]*?)<\/button>/g)].map(m => m[1].replace(/<[^>]+>/g,'').trim());

(async () => {
  let html;
  try { html = await fetchPage(URL_); }
  catch(e){ console.error(`⛔ 페이지 취득 실패 (${URL_}): ${e.message} — hub 가 떠 있는지 확인`); process.exit(2); }
  const js = inlineScript(html);
  if(!js){ console.error('⛔ 인라인 스크립트 추출 실패 — 페이지 구조가 바뀌었다'); process.exit(2); }

  const ctx = sandbox();
  const probe = `
    DATA = ${JSON.stringify(QUEUE)}; ACKED = {};
    SDATA = { ok:true, jobs: ${JSON.stringify(JOBS)}, bindings:[], events:[], runs:[] };
    SSYS = true;                              // 시스템 잡은 기본 숨김(Issue584) — 상태 표시 판정을 위해 켠다
    renderJobs();
    globalThis.__OUT = document.getElementById("j-body").innerHTML;
  `;
  try { vm.runInNewContext(js + probe, ctx, { filename:'mq-inline.js' }); }
  catch(e){ console.error(`⛔ 스크립트 실행 실패: ${e.message}`); process.exit(2); }

  let fail = 0, n = 0;
  const check = (ok, label) => { n++; if(!ok) fail++; console.log(`${ok?'✅':'❌'} ${label}`); };
  const out = String(ctx.__OUT || '');

  // ② thead — «최근 · 걸린 곳» 한 열, «걸린 곳»·«최근» 단독 열 없음, 끝 열은 액션(빈 머리)
  const ths = [...((out.match(/<thead>([\s\S]*?)<\/thead>/) || [])[1] || '').matchAll(/<th[^>]*>([\s\S]*?)<\/th>/g)].map(m => m[1].trim());
  check(ths.includes('최근 · 걸린 곳') && !ths.includes('걸린 곳') && !ths.includes('최근') && ths[ths.length-1] === '',
        `thead 에 «최근 · 걸린 곳» 한 열 · 단독 열 없음 — 실제 ${JSON.stringify(ths)}`);

  const rows = out.split('<tr class="jrow').slice(1);
  const rowOf = nm => rows.find(r => r.includes(`class="jname">${nm}`)) || '';
  const R = { d: rowOf('j-desc'), p: rowOf('j-pz'), s: rowOf('sys-j') };
  check(R.d && R.p && R.s, `잡 3행 렌더 (${rows.length}건)`);
  check([R.d, R.p, R.s].every(r => cells(r).length === ths.length), `각 행 셀 수 = thead 열 수(${ths.length}) — 실제 ${[R.d,R.p,R.s].map(r=>cells(r).length).join('/')}`);

  // ① 설명은 이름 줄 안 · 별도 설명 줄 없음
  const nlD = nameLine(R.d);
  check(nlD.includes('설명 있음') && nlD.includes(`jobNote('j-desc')`), '설명 + ✎ 가 이름 줄(.jname) 안에 선다');
  check(![R.d, R.p, R.s].some(r => /<div class="jdesc">/.test(r)), '별도 설명 줄(div.jdesc) 없음');
  check(nameLine(R.s).includes('시스템 설명') && !nameLine(R.s).includes('jobNote('), '시스템 잡도 설명은 이름 줄 · ✎ 없음');

  // ② + ④ 2열 = 최근(위) → 상태 표시 → 걸린 곳
  const c2 = r => cellOf(r, 'jlast');
  const at = (h, s) => h.indexOf(s);
  const d2 = c2(R.d), p2 = c2(R.p), s2 = c2(R.s);
  check(at(d2,'09-26 23:04') >= 0 && at(d2,'🗓 2') > at(d2,'09-26 23:04') && at(d2,'⏰ 1') > at(d2,'🗓 2'),
        '2열: 최근 실행 → 🗓 2 → ⏰ 1 순 (걸린 곳은 최근 아래)');
  check(!nameLine(R.p).includes('멈춤'), '«⏸ 멈춤» 이 이름 줄에서 빠졌다');
  check(at(p2,'⏸ 멈춤') >= 0 && at(p2,'⏸ 멈춤') < at(p2,'🗓 0') && at(p2,'09-27 15:17') < at(p2,'⏸ 멈춤'),
        '«⏸ 멈춤» 은 2열에서 최근 아래 · 🗓 0 왼쪽');
  check(!nameLine(R.s).includes('🔒') && at(s2,'🔒 시스템') >= 0 && at(s2,'🔒 시스템') < at(s2,'🗓 1'),
        '«🔒 시스템» 도 이름 줄에서 빠져 🗓 1 왼쪽');

  // ③ 액션 — 3열 grid 한 벌 · 순서
  const c3 = r => cellOf(r, 'sacts');
  const grid = h => ((h.match(/<div class="agrid">([\s\S]*?)<\/div>/) || [])[1] || null);
  const gD = grid(c3(R.d)), gP = grid(c3(R.p));
  check(JSON.stringify(gD && btnLabels(gD)) === JSON.stringify(['▶ 실행','✎ 수정','⏸ 멈춤','⏰ 예약','🗓＋','✕ 삭제']),
        `액션 grid 순서(행1 실행·수정·멈춤 / 행2 예약·🗓＋·삭제) — 실제 ${JSON.stringify(gD && btnLabels(gD))}`);
  check(gP && btnLabels(gP)[2] === '▶ 재개', `멈춘 잡은 3번째가 «▶ 재개» — 실제 ${JSON.stringify(gP && btnLabels(gP)[2])}`);
  // Issue558: 시스템 잡에도 📋(잡 ID 팝업)는 선다 — 복사·실행은 편집이 아니다. 편집 액션은 여전히 없다
  check(JSON.stringify(btnLabels(c3(R.s))) === JSON.stringify(['📋']), `시스템 잡 액션은 📋 만 — 실제 ${JSON.stringify(btnLabels(c3(R.s)))}`);
  check(/\.agrid\{[^}]*display:inline-grid[^}]*grid-template-columns:repeat\(3,auto\)/.test(html),
        'CSS: .agrid 는 inline-grid · 3열 (6버튼 → 2행)');

  console.log(fail ? `\n실패 ${fail}건 / ${n}` : `\n전건 통과 (${n}/${n})`);
  process.exit(fail ? 1 : 0);
})();
