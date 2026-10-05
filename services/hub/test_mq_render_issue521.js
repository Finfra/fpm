#!/usr/bin/env node
// Issue521 회귀 테스트 — /mq 행 액션의 **렌더 게이트**를 상태 조합으로 판정한다.
//
//   왜 필요한가: `[진행]` 표시 조건은 서버가 내려주는 인라인 스크립트 안에 있어
//   파이썬 테스트로는 닿지 않는다. 눈으로 보는 검증은 «결과가 있는 due 항목» 이
//   큐에 없는 날에는 아무것도 증명하지 못한다(2026-09-20 이 그런 날이었다).
//   그래서 **서버가 실제로 내려준 스크립트를 그대로 실행**하고 고정값을 먹인다.
//
//   실행: node plugins/fpm-core/services/hub/test_mq_render_issue521.js [url]
//         (기본 http://127.0.0.1:9876/mq — hub 가 떠 있어야 한다)
//   종료: 0=전건 통과 · 1=판정 실패 · 2=페이지·스크립트 취득 실패
'use strict';
const vm = require('vm');
const URL_ = process.argv[2] || 'http://127.0.0.1:9876/mq';

// 상태 조합 고정값. `result` 가 있으면 사람이 할 일은 종결 판정뿐이라 `[진행]` 은 나오지 않는다.
const FIX = [
  { id:'T-A', status:'due',          _bucket:'open', message:'결과 없음',      result:null,  go:true  },
  { id:'T-B', status:'due',          _bucket:'open', message:'결과 있음',      result:'끝',  go:false },
  { id:'T-C', status:'pending',      _bucket:'open', message:'연기+결과',      result:'끝',  go:false },
  { id:'T-D', status:'in_progress',  _bucket:'open', message:'착수됨',         result:null,  go:false },
  { id:'T-E', status:'due',          _bucket:'open', message:'공백만 든 결과', result:'   ', go:true  },
];

function fetchPage(url){
  const http = url.startsWith('https') ? require('https') : require('http');
  return new Promise((ok, no) => {
    http.get(url, r => { let b=''; r.on('data', c=>b+=c); r.on('end', ()=>ok(b)); }).on('error', no);
  });
}

// 스케줄 탭 이하는 이 판정과 무관하고 부트스트랩이 많다 — 큐 파트만 떼어 실행한다.
function queueScript(html){
  const m = html.match(/<script>([\s\S]*?)<\/script>/);
  if(!m) return null;
  let js = m[1];
  const cut = js.indexOf('// ── prj3#Issue570');
  if(cut > 0) js = js.slice(0, cut);
  return js.replace(/^\s*load\(\);\s*setInterval\(load,\s*60000\);\s*$/m, '');
}

// render() 가 쓰는 만큼만 흉내 낸다 — DOM 라이브러리를 들이지 않는다.
function sandbox(){
  const els = {};
  const el = () => ({ textContent:'', innerHTML:'', value:'', checked:false, hidden:false,
    style:{}, dataset:{}, classList:{add(){},remove(){},toggle(){}},
    addEventListener(){}, querySelectorAll:()=>[], closest:()=>null, appendChild(){} });
  const document = { getElementById:id=>els[id]||(els[id]=el()), querySelectorAll:()=>[],
    querySelector:()=>el(), createElement:()=>el(), addEventListener(){}, body:el() };
  const ctx = { document, window:{}, console, URL, URLSearchParams, Date, Math, JSON,
    location:{href:'http://x/mq', search:''}, history:{pushState(){},replaceState(){}},
    addEventListener(){}, setInterval:()=>0, setTimeout:()=>0, clearTimeout(){},
    fetch:()=>Promise.reject(new Error('네트워크 미사용')), EventSource:function(){},
    localStorage:{getItem:()=>null, setItem(){}} };
  ctx.globalThis = ctx;
  return ctx;
}

(async () => {
  let html;
  try { html = await fetchPage(URL_); }
  catch(e){ console.error(`⛔ 페이지 취득 실패 (${URL_}): ${e.message} — hub 가 떠 있는지 확인`); process.exit(2); }
  const js = queueScript(html);
  if(!js){ console.error('⛔ 인라인 스크립트 추출 실패 — 페이지 구조가 바뀌었다'); process.exit(2); }

  const ctx = sandbox();
  const probe = `
    pass = () => true;                       // 필터는 이 판정 밖 — 전건 통과시킨다
    DATA = ${JSON.stringify(FIX.map(({go, ...x}) => x))};
    ACKED = {};
    render();
    globalThis.__OUT = document.getElementById("rows").innerHTML;
  `;
  try { vm.runInNewContext(js + probe, ctx, { filename:'mq-inline.js' }); }
  catch(e){ console.error(`⛔ 스크립트 실행 실패: ${e.message}`); process.exit(2); }

  const rows = String(ctx.__OUT || '').split('<tr').slice(1);
  let fail = 0;
  for(const f of FIX){
    const row = rows.find(r => r.includes(`'${f.id}'`)) || '';
    const go = /act\('[^']+','start'/.test(row);
    const ok = row && go === f.go;
    if(!ok) fail++;
    console.log(`${ok?'✅':'❌'} ${f.id} status=${f.status} result=${f.result===null?'없음':JSON.stringify(f.result)}`
      + ` → 진행 ${go?'표시':'숨김'} (기대 ${f.go?'표시':'숨김'})`);
  }
  if(rows.length !== FIX.length){ console.log(`❌ 행 수 ${rows.length} ≠ 고정값 ${FIX.length}`); fail++; }
  console.log(fail ? `\n실패 ${fail}건` : `\n전건 통과 (${FIX.length}/${FIX.length})`);
  process.exit(fail ? 1 : 0);
})();
