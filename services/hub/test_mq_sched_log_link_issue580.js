#!/usr/bin/env node
// Issue580 회귀 테스트 (화면 절반) — /mq 스케줄·잡 탭의 rc pill 옆에 📄 실행 결과 링크가 서는지 판정한다.
//
//   Issue521·549·554·558 과 같은 방식 — **서버가 실제로 내려준 스크립트를 그대로 실행**하고 고정값을 먹인다.
//
//   판정 ① 「최근 실행」 각 행 — rc pill 옆 📄 → /sched-log?job=<라벨>&run=<pid>
//   판정 ② 스케줄 행 「최근」 · 잡 행 「최근」(= 마지막 실행 결과) — 같은 링크
//   판정 ③ 다단계 스텝 라벨(`multi#2`) 은 %23 으로 실린다 — # 가 URL fragment 로 새지 않는다
//   판정 ④ 출력이 없는 기록(pause·resume·락 skip)엔 링크가 없다 · pid 없는 detail 은 run 을 빼고 단다
//
//   실행: node plugins/fpm-core/services/hub/test_mq_sched_log_link_issue580.js [url]
//         (기본 http://127.0.0.1:9876/mq — hub 가 떠 있어야 한다)
//   종료: 0=전건 통과 · 1=판정 실패 · 2=페이지·스크립트 취득 실패
'use strict';
const vm = require('vm');
const URL_ = process.argv[2] || 'http://127.0.0.1:9876/mq';

const LAST = { ts:'2026-09-28T09:00:05', event:'t-0900', job:'j-user', rc:'0', detail:'5s pid=300 raw=0' };
const JOBS = [
  { name:'j-user', source:'user', bindings_n:1, steps:[{kind:'sh', run:'true'}], last:LAST },
  { name:'j-pz',   source:'user', bindings_n:0, steps:[{kind:'sh', run:'true'}],
    last:{ ts:'2026-09-28T08:00:00', event:'hub-ui', job:'j-pz', rc:'pause', detail:'' } },
  { name:'j-none', source:'user', bindings_n:0, steps:[{kind:'sh', run:'true'}] },
];
const BINDS = [ { job:'j-user', event:'t-0900', source:'user' } ];
const EVENTS = [ { name:'t-0900', type:'calendar', spec:'09:00' } ];
const RUNS = [
  LAST,
  { ts:'2026-09-28T08:59:00', event:'t-0900', job:'j-user#2', rc:'1', detail:'3s pid=77' },
  { ts:'2026-09-28T08:58:00', event:'t-0900', job:'j-user', rc:'skip', detail:'lock=busy' },
  { ts:'2026-09-28T08:57:00', event:'hub-ui', job:'j-user', rc:'0', detail:'job=x result=ok 3s' },
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
  const el = () => ({ textContent:'', innerHTML:'', value:'', checked:false, hidden:false, className:'',
    style:{}, dataset:{}, classList:{add(){},remove(){},toggle(){}},
    getBoundingClientRect:()=>({left:0,right:0,top:0,bottom:0,width:0,height:0}),
    addEventListener(){}, querySelectorAll:()=>[], closest:()=>null, appendChild(){}, setAttribute(){} });
  const document = { getElementById:id=>els[id]||(els[id]=el()), querySelectorAll:()=>[],
    querySelector:()=>el(), createElement:()=>el(), body:el(), addEventListener(){} };
  const ctx = { document, window:{}, console, URL, URLSearchParams, Date, Math, JSON,
    location:{href:'http://x/mq', search:''}, history:{pushState(){},replaceState(){}},
    addEventListener(){}, setInterval:()=>0, setTimeout:()=>0, clearTimeout(){},
    fetch:()=>Promise.reject(new Error('네트워크 미사용')), EventSource:function(){},
    localStorage:{getItem:()=>null, setItem(){}},
    prompt:()=>null, confirm:()=>false, alert(){}, innerWidth:1200, innerHeight:800 };
  ctx.globalThis = ctx;
  return ctx;
}
const links = h => [...h.matchAll(/<a class="loglk" href="([^"]+)"[^>]*>📄<\/a>/g)].map(m => m[1].replace(/&amp;/g,'&'));

(async () => {
  let html;
  try { html = await fetchPage(URL_); }
  catch(e){ console.error(`⛔ 페이지 취득 실패 (${URL_}): ${e.message} — hub 가 떠 있는지 확인`); process.exit(2); }
  const js = inlineScript(html);
  if(!js){ console.error('⛔ 인라인 스크립트 추출 실패 — 페이지 구조가 바뀌었다'); process.exit(2); }

  const ctx = sandbox();
  const probe = `
    DATA = []; ACKED = {};
    SDATA = { ok:true, jobs:${JSON.stringify(JOBS)}, bindings:${JSON.stringify(BINDS)},
              events:${JSON.stringify(EVENTS)}, runs:${JSON.stringify(RUNS)} };
    renderSchedule(); globalThis.__S = document.getElementById("s-body").innerHTML;
    renderJobs();     globalThis.__J = document.getElementById("j-body").innerHTML;
  `;
  try { vm.runInNewContext(js + probe, ctx, { filename:'mq-inline.js' }); }
  catch(e){ console.error(`⛔ 스크립트 실행 실패: ${e.message}`); process.exit(2); }

  let fail = 0, n = 0;
  const check = (ok, label) => { n++; if(!ok) fail++; console.log(`${ok?'✅':'❌'} ${label}`); };
  const S = String(ctx.__S || ''), J = String(ctx.__J || '');

  // ① 최근 실행
  const runsTbl = (S.match(/<table class="runs">([\s\S]*?)<\/table>/) || [])[1] || '';
  const rows = runsTbl.split('<tr>').slice(2);                // thead 행 제외
  check(rows.length === 4, `최근 실행 4행 (${rows.length})`);
  check(JSON.stringify(links(rows[0] || '')) === JSON.stringify(['/sched-log?job=j-user&run=300']),
        `① 행 1: 📄 → /sched-log?job=j-user&run=300 — 실제 ${JSON.stringify(links(rows[0]||''))}`);
  check((rows[0] || '').indexOf('pill ok') < (rows[0] || '').indexOf('loglk'), '① 📄 는 rc pill 옆(뒤)');
  // ③ 스텝 라벨
  check(JSON.stringify(links(rows[1] || '')) === JSON.stringify(['/sched-log?job=j-user%232&run=77']),
        `③ 스텝 라벨은 %23 — 실제 ${JSON.stringify(links(rows[1]||''))}`);
  // ④
  check(links(rows[2] || '').length === 0, '④ 락 skip 행엔 📄 없음');
  check(JSON.stringify(links(rows[3] || '')) === JSON.stringify(['/sched-log?job=j-user']),
        `④ pid 없는 detail → run 없이 — 실제 ${JSON.stringify(links(rows[3]||''))}`);

  // ② 스케줄 행 「최근」
  const sRow = (S.split('<tr class="jrow').slice(1)[0]) || '';
  const sLast = (sRow.match(/<td class="jlast">([\s\S]*?)<\/td>/) || [])[1] || '';
  check(JSON.stringify(links(sLast)) === JSON.stringify(['/sched-log?job=j-user&run=300']),
        `② 스케줄 행 「최근」 📄 — 실제 ${JSON.stringify(links(sLast))}`);
  // ② 잡 행 「최근」
  const jRows = J.split('<tr class="jrow').slice(1);
  const jRow = nm => jRows.find(r => r.includes(`class="jname">${nm}`)) || '';
  const jLast = nm => (jRow(nm).match(/<td class="jlast">([\s\S]*?)<\/td>\s*<td class="sacts">/) || [])[1] || '';
  check(JSON.stringify(links(jLast('j-user'))) === JSON.stringify(['/sched-log?job=j-user&run=300']),
        `② 잡 행 「최근」(마지막 실행 결과) 📄 — 실제 ${JSON.stringify(links(jLast('j-user')))}`);
  check(jRow('j-pz') && links(jLast('j-pz')).length === 0, '④ 마지막 기록이 pause 전환이면 📄 없음');
  check(jRow('j-none') && links(jLast('j-none')).length === 0, '실행 기록 없는 잡엔 📄 없음');

  console.log(`\n${fail ? '실패 ' + fail + '건' : '전건 통과'} / ${n}`);
  process.exit(fail ? 1 : 0);
})();
