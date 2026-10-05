#!/usr/bin/env node
// Issue555 회귀 테스트 — /mq 잡 탭: 스텝이 1열에서 빠져 **독립된 2열**에 서는지 판정한다.
//
//   사용자 지적(2026-09-27): "스텝은 두번째 컬럼으로 독립, 첫번째 컬럼에 내용이 너무 많음"
//     ① thead = 잡 | 스텝 | 최근 · 걸린 곳 | (액션) — 4열
//     ② 1열(잡) 은 이름 줄(.jname)만 — 스텝 칩(.stp)·메타 줄(.jmeta) 없음
//     ③ 2열(td.jsteps) 에 스텝 칩 전부 + 메타 줄(cwd · timeout · 실패 무시) — 메타는 스텝 실행 조건이라 칩과 함께 옮긴다
//     ④ 2열 폭은 내용을 따르되 상한이 있다 — `.jsteps-in{width:max-content; max-width:…}` (긴 cwd 가 표를 밀지 않게)
//
//   Issue521·549·554 와 같은 방식 — **서버가 실제로 내려준 스크립트를 그대로 실행**하고 고정값을 먹인다.
//   실행: node plugins/fpm-core/services/hub/test_mq_job_steps_col_issue555.js [url]
//         (기본 http://127.0.0.1:9876/mq — hub 가 떠 있어야 한다)
//   종료: 0=전건 통과 · 1=판정 실패 · 2=페이지·스크립트 취득 실패
'use strict';
const vm = require('vm');
const URL_ = process.argv[2] || 'http://127.0.0.1:9876/mq';

const JOBS = [
  { name:'j-one',   source:'user', desc:'한 스텝', bindings_n:1, last:{rc:0, ts:'2026-09-26T23:04:00'},
    steps:[{kind:'sh', run:'echo one'}], cwd:'/tmp/w', timeout:60 },
  { name:'j-multi', source:'user', bindings_n:0, on_error:'continue',
    steps:[{kind:'scar', cmd:'/daily-digest'}, {kind:'script', path:'hooks/disk-check.sh'}] },
  { name:'sys-j',   source:'system', desc:'시스템', bindings_n:1, steps:[{kind:'sh', run:'true'}] },
];

function fetchPage(url){
  const http = url.startsWith('https') ? require('https') : require('http');
  return new Promise((ok, no) => {
    http.get(url, r => { let b=''; r.on('data', c=>b+=c); r.on('end', ()=>ok(b)); }).on('error', no);
  });
}
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
const tdOpen = tr => [...tr.matchAll(/<td([^>]*)>/g)].map(m => m[1].trim());
const chips = h => (h.match(/class="stp /g) || []).length;

(async () => {
  let html;
  try { html = await fetchPage(URL_); }
  catch(e){ console.error(`⛔ 페이지 취득 실패 (${URL_}): ${e.message} — hub 가 떠 있는지 확인`); process.exit(2); }
  const js = inlineScript(html);
  if(!js){ console.error('⛔ 인라인 스크립트 추출 실패 — 페이지 구조가 바뀌었다'); process.exit(2); }

  const ctx = sandbox();
  const probe = `
    DATA = []; ACKED = {};
    SDATA = { ok:true, jobs: ${JSON.stringify(JOBS)}, bindings:[], events:[], runs:[] };
    SSYS = true;
    renderJobs();
    globalThis.__OUT = document.getElementById("j-body").innerHTML;
  `;
  try { vm.runInNewContext(js + probe, ctx, { filename:'mq-inline.js' }); }
  catch(e){ console.error(`⛔ 스크립트 실행 실패: ${e.message}`); process.exit(2); }

  let fail = 0, n = 0;
  const check = (ok, label) => { n++; if(!ok) fail++; console.log(`${ok?'✅':'❌'} ${label}`); };
  const out = String(ctx.__OUT || '');

  // ① thead 4열
  const ths = [...((out.match(/<thead>([\s\S]*?)<\/thead>/) || [])[1] || '').matchAll(/<th[^>]*>([\s\S]*?)<\/th>/g)].map(m => m[1].trim());
  check(JSON.stringify(ths) === JSON.stringify(['잡','스텝','최근 · 걸린 곳','']),
        `thead = 잡 | 스텝 | 최근 · 걸린 곳 | (액션) — 실제 ${JSON.stringify(ths)}`);

  const rows = out.split('<tr class="jrow').slice(1);
  const rowOf = nm => rows.find(r => r.includes(`class="jname">${nm}`)) || '';
  const R = { one: rowOf('j-one'), multi: rowOf('j-multi'), sys: rowOf('sys-j') };
  check(R.one && R.multi && R.sys, `잡 3행 렌더 (${rows.length}건)`);
  check(Object.values(R).every(r => cells(r).length === 4), `각 행 4셀 — 실제 ${Object.values(R).map(r=>cells(r).length).join('/')}`);
  check(Object.values(R).every(r => tdOpen(r)[1] === 'class="jsteps"'), `2열 셀이 td.jsteps — 실제 ${Object.values(R).map(r=>JSON.stringify(tdOpen(r)[1])).join(' ')}`);

  // ② 1열 = 이름 줄만
  const c1 = r => cells(r)[0] || '', c2 = r => cells(r)[1] || '';
  check(Object.values(R).every(r => c1(r).includes('class="jname"') && chips(c1(r)) === 0 && !c1(r).includes('class="jmeta"')),
        '1열에는 이름 줄만 — 스텝 칩·메타 줄 없음');

  // ③ 2열 = 스텝 칩 전부 + 메타
  check(chips(c2(R.one)) === 1 && chips(c2(R.multi)) === 2 && chips(c2(R.sys)) === 1,
        `2열 스텝 칩 수 1·2·1 — 실제 ${[R.one,R.multi,R.sys].map(r=>chips(c2(r))).join('·')}`);
  check(c2(R.one).includes('class="jmeta"') && c2(R.one).includes('/tmp/w · 60s'), '메타 줄(cwd · timeout)은 2열 칩 아래');
  check(c2(R.multi).includes('실패 무시'), '다중 스텝 «실패 무시» 도 2열');
  check(c2(R.one).indexOf('class="stp ') < c2(R.one).indexOf('class="jmeta"'), '2열 안 순서 — 칩 → 메타');

  // ④ 2열 폭 상한 규칙
  check(/\.jsteps-in\{[^}]*width:max-content[^}]*max-width:\d+(\.\d+)?rem/.test(html),
        'CSS: .jsteps-in 은 width:max-content + max-width(rem) — 내용 폭을 따르되 상한');

  console.log(fail ? `\n실패 ${fail}건 / ${n}` : `\n전건 통과 (${n}/${n})`);
  process.exit(fail ? 1 : 0);
})();
