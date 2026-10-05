#!/usr/bin/env node
// Issue593 회귀 테스트 (화면 절반) — /mq 잡 탭 각 행의 «📄 최신 결과» 링크.
//   Issue580 과 같은 방식 — 서버가 내려준 스크립트를 그대로 실행하고 고정값(prj3#Issue893 필드 형태)을 먹인다.
//   ① result_latest 있음 → /sched-result?job=<잡> 링크(파일명·상대 시각)
//   ② result 선언 없음 → 칸 없음 · 일치 0건(result_latest null) → «결과 없음» 회색(링크 아님)
//   ③ .htm/.html 결과 → 파일명만 회색(링크 아님)
//
//   실행: node plugins/fpm-core/services/hub/test_mq_sched_result_link_issue593.js [url]
//   종료: 0=전건 통과 · 1=판정 실패 · 2=페이지·스크립트 취득 실패
'use strict';
const vm = require('vm');
const URL_ = process.argv[2] || 'http://127.0.0.1:9876/mq';
const NOW = Math.floor(Date.now() / 1000);
const step = [{ kind:'sh', run:'true' }];
const JOBS = [
  { name:'j-has',  source:'user', bindings_n:0, steps:step, result:['_doc_work/report/*.md'],
    result_latest:{ path:'/Users/x/_doc_work/report/2026.10.03_a.md', mtime:NOW - 7200 } },
  { name:'j-none', source:'user', bindings_n:0, steps:step, result:[], result_latest:null },
  { name:'j-zero', source:'user', bindings_n:0, steps:step, result:['out/*.md'], result_latest:null },
  { name:'j-htm',  source:'user', bindings_n:0, steps:step, result:['out/*.htm'],
    result_latest:{ path:'/Users/x/out/r.htm', mtime:NOW - 30 } },
  { name:'j-old',  source:'user', bindings_n:0, steps:step },
];
function fetchPage(url){
  const http = url.startsWith('https') ? require('https') : require('http');
  return new Promise((ok, no) => { http.get(url, r => { let b=''; r.on('data', c=>b+=c); r.on('end', ()=>ok(b)); }).on('error', no); });
}
function inlineScript(html){
  const m = html.match(/<script>([\s\S]*?)<\/script>/);
  return m ? m[1].replace(/^\s*load\(\);\s*setInterval\(load,\s*60000\);\s*$/m, '') : null;
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
(async () => {
  let html;
  try { html = await fetchPage(URL_); }
  catch(e){ console.error(`⛔ 페이지 취득 실패 (${URL_}): ${e.message}`); process.exit(2); }
  const js = inlineScript(html);
  if(!js){ console.error('⛔ 인라인 스크립트 추출 실패'); process.exit(2); }
  const ctx = sandbox();
  const probe = `DATA = []; ACKED = {};
    SDATA = { ok:true, jobs:${JSON.stringify(JOBS)}, bindings:[], events:[], runs:[] };
    renderJobs(); globalThis.__J = document.getElementById("j-body").innerHTML;`;
  try { vm.runInNewContext(js + probe, ctx, { filename:'mq-inline.js' }); }
  catch(e){ console.error(`⛔ 스크립트 실행 실패: ${e.message}`); process.exit(2); }
  let fail = 0, n = 0;
  const check = (ok, label) => { n++; if(!ok) fail++; console.log(`${ok?'✅':'❌'} ${label}`); };
  const rows = String(ctx.__J || '').split('<tr class="jrow').slice(1);
  const last = nm => ((rows.find(r => r.includes(`class="jname">${nm}`)) || '').match(/<td class="jlast">([\s\S]*?)<\/td>\s*<td class="sacts">/) || [])[1] || '';
  const lk = h => [...h.matchAll(/<a class="reslk" href="([^"]+)"/g)].map(m => m[1]);

  const a = last('j-has');
  check(JSON.stringify(lk(a)) === JSON.stringify(['/sched-result?job=j-has']), `① 링크 → /sched-result?job=j-has — ${JSON.stringify(lk(a))}`);
  check(a.includes('📄 최신 결과') && a.includes('2026.10.03_a.md'), '① 파일명이 보인다');
  check(a.includes('2시간 전'), '① 상대 시각(2시간 전)');
  check(!last('j-none').includes('reslk'), '② result 선언 없음(빈 목록) → 칸 없음');
  check(!last('j-old').includes('reslk'), '② result 필드 자체가 없는 옛 잡 → 칸 없음');
  const z = last('j-zero');
  check(z.includes('결과 없음') && lk(z).length === 0, '② 일치 0건 → «결과 없음» 회색, 링크 아님');
  const h = last('j-htm');
  check(h.includes('r.htm') && lk(h).length === 0 && h.includes('reslk none'), '③ .htm 결과 → 파일명만 회색');
  console.log(`\n${fail ? '실패 ' + fail + '건' : '전건 통과'} / ${n}`);
  process.exit(fail ? 1 : 0);
})();
