#!/usr/bin/env node
// Issue549 회귀 테스트 — /mq 잡 탭의 «✎ 설명» 인라인 편집이 스케줄 탭(bindNote)과 같은 규약으로 서는지 판정한다.
//
//   왜 필요한가: 버튼 유무·전송 payload 는 서버가 내려주는 인라인 스크립트 안에 있어 파이썬 테스트로는
//   닿지 않는다. Issue521 과 같은 방식 — **서버가 실제로 내려준 스크립트를 그대로 실행**하고 고정값을 먹인다.
//
//   판정 ① 렌더: 사용자 잡은 desc 유무에 따라 «✎ 설명»(추가)·«✎»(수정) 버튼이 서고, 시스템 잡에는 없다
//   판정 ② 전송: prompt 값은 trim 해 `job-edit` 로 **desc 만** 보낸다(steps 를 싣지 않는다 — prj3 _build_job 이
//            base 위에 덮는다) · 취소(null)는 보내지 않는다 · 빈 값은 그대로 보낸다(= 지운다) · 200자 초과는 보내지 않는다
//
//   실행: node plugins/fpm-core/services/hub/test_mq_job_note_issue549.js [url]
//         (기본 http://127.0.0.1:9876/mq — hub 가 떠 있어야 한다)
//   종료: 0=전건 통과 · 1=판정 실패 · 2=페이지·스크립트 취득 실패
'use strict';
const vm = require('vm');
const URL_ = process.argv[2] || 'http://127.0.0.1:9876/mq';

const JOBS = [
  { name:'j-no',   source:'user',   steps:[{kind:'sh', run:'true'}] },                   // desc 없음 → «✎ 설명»
  { name:'j-with', source:'user',   desc:'기존 설명', steps:[{kind:'sh', run:'true'}] }, // desc 있음 → «✎»(수정)
  { name:'sys-j',  source:'system', desc:'시스템',    steps:[{kind:'sh', run:'true'}] }, // 시스템 → 버튼 없음
];

function fetchPage(url){
  const http = url.startsWith('https') ? require('https') : require('http');
  return new Promise((ok, no) => {
    http.get(url, r => { let b=''; r.on('data', c=>b+=c); r.on('end', ()=>ok(b)); }).on('error', no);
  });
}

// 스크립트 전체를 돌린다(잡 탭은 뒤쪽에 있다). 큐 파트의 초기 load()·60초 폴링만 뗀다 —
// fetch 없는 sandbox 에서 미처리 거부를 남기지 않게.
function inlineScript(html){
  const m = html.match(/<script>([\s\S]*?)<\/script>/);
  if(!m) return null;
  return m[1].replace(/^\s*load\(\);\s*setInterval\(load,\s*60000\);\s*$/m, '');
}

// renderJobs()·jobNote() 가 쓰는 만큼만 흉내 낸다 — DOM 라이브러리를 들이지 않는다.
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
    SSYS = true;                              // 시스템 잡은 기본 숨김(Issue584) — «버튼 없음» 을 보려면 켠다
    renderJobs();
    globalThis.__OUT = document.getElementById("j-body").innerHTML;
    // ── 전송 판정: 네트워크 대신 payload 를 받아 적는다
    globalThis.__POSTS = [];
    sPost = async p => { __POSTS.push(p); return {ok:true, msg:"ok"}; };
    sReload = async () => {};
    jMsg = () => {};
    globalThis.__DONE = (async () => {
      if(typeof jobNote !== "function") throw new Error("jobNote 가 정의되지 않았다");
      globalThis.prompt = () => "  새 설명  ";     await jobNote("j-no");    // trim 해서 보낸다
      globalThis.prompt = () => null;              await jobNote("j-no");    // 취소 → 안 보낸다
      globalThis.prompt = () => "";                await jobNote("j-with");  // 빈 값 → 그대로(지운다)
      globalThis.prompt = () => "x".repeat(201);   await jobNote("j-with");  // 200자 초과 → 안 보낸다
    })();
  `;
  try { vm.runInNewContext(js + probe, ctx, { filename:'mq-inline.js' }); }
  catch(e){ console.error(`⛔ 스크립트 실행 실패: ${e.message}`); process.exit(2); }

  let fail = 0;
  const check = (ok, label) => { if(!ok) fail++; console.log(`${ok?'✅':'❌'} ${label}`); };

  // ① 렌더
  const rows = String(ctx.__OUT || '').split('<tr').slice(1);
  const rowOf = n => rows.find(r => r.includes(`class="jname">${n}`)) || '';
  const rNo = rowOf('j-no'), rWith = rowOf('j-with'), rSys = rowOf('sys-j');
  check(rNo && rWith && rSys, `잡 3행 렌더 (${rows.length-1}건)`);
  check(rNo.includes(`jobNote('j-no')`) && rNo.includes('설명 추가') && />✎ 설명<\/button>/.test(rNo),
        'desc 없는 사용자 잡 → «✎ 설명» 버튼(설명 추가)');
  check(rWith.includes(`jobNote('j-with')`) && rWith.includes('설명 수정') && />✎<\/button>/.test(rWith)
        && rWith.includes('기존 설명'), 'desc 있는 사용자 잡 → «✎» 버튼(설명 수정) + 기존 설명 표시');
  check(rSys && !rSys.includes('jobNote('), '시스템 잡 → 설명 버튼 없음');

  // ② 전송
  let sendErr = null;
  try { await ctx.__DONE; } catch(e){ sendErr = e; }
  check(!sendErr, `jobNote 호출 4회 완료${sendErr ? ' — ' + sendErr.message : ''}`);
  const posts = ctx.__POSTS || [];
  const same = (a, b) => JSON.stringify(a, Object.keys(a).sort()) === JSON.stringify(b, Object.keys(b).sort());
  check(posts.length === 2, `전송 2건 (취소·200자 초과는 제외) — 실제 ${posts.length}건`);
  check(posts[0] && same(posts[0], {action:'job-edit', name:'j-no', desc:'새 설명'}),
        `1건째 = job-edit · desc 만 · trim — 실제 ${JSON.stringify(posts[0])}`);
  check(posts[1] && same(posts[1], {action:'job-edit', name:'j-with', desc:''}),
        `2건째 = 빈 desc 그대로(지운다) — 실제 ${JSON.stringify(posts[1])}`);

  console.log(fail ? `\n실패 ${fail}건` : `\n전건 통과 (8/8)`);
  process.exit(fail ? 1 : 0);
})();
