#!/usr/bin/env node
// Issue656_2 회귀 테스트 — /mq 내용 열은 **제목이 먼저** 보인다.
//   본문 첫 줄의 ` — ` 앞(90자 이내)이 굵은 제목(.mtitle)이 되고 나머지는 같은 문단의 .mrest 로 이어진다(Issue657: 줄 분리 철회, 3줄 클램프는 문단 전체).
//   제목으로 뗄 거리가 없는 한 줄 짧은 본문은 종전처럼 본문뿐이다(Issue506·565 래퍼 계약 보존).
//   서버가 내려준 인라인 스크립트를 그대로 실행한다(test_mq_render_issue521.js 와 같은 방식).
//   실행: node plugins/fpm-core/services/hub/test_mq_title_issue656.js [url]  (hub 기동 필요)
'use strict';
const vm = require('vm');
const URL_ = process.argv[2] || 'http://127.0.0.1:9876/mq';

function fetchPage(url){
  const http = require('http');
  return new Promise((ok, no) => {
    http.get(url, r => { let b=''; r.on('data', c=>b+=c); r.on('end', ()=>ok(b)); }).on('error', no);
  });
}
function queueScript(html){
  const m = html.match(/<script>([\s\S]*?)<\/script>/);
  if(!m) return null;
  let js = m[1];
  const cut = js.indexOf('// ── prj3#Issue570');
  if(cut > 0) js = js.slice(0, cut);
  return js.replace(/^\s*load\(\);\s*setInterval\(load,\s*60000\);\s*$/m, '');
}
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
  if(!js){ console.error('⛔ 인라인 스크립트 추출 실패'); process.exit(2); }
  const ctx = sandbox();
  try { vm.runInNewContext(js + '\nglobalThis.__S = msgSplit; globalThis.__C = msgCell;', ctx, { filename:'mq-inline.js' }); }
  catch(e){ console.error(`⛔ 스크립트 실행 실패: ${e.message}`); process.exit(2); }

  let fail = 0;
  const check = (name, cond) => { if(!cond) fail++; console.log(`${cond?'✅':'❌'} ${name}`); };
  const S = ctx.__S, C = ctx.__C;

  let r = S('[컨펌] [H:보안] fg1 vLLM --api-key 인증 활성화 여부 — 종전 mq 2026 이 결정 문구 없이 닫혀 재상신');
  check('` — ` 앞이 제목(선두 태그 포함)', r.title === '[컨펌] [H:보안] fg1 vLLM --api-key 인증 활성화 여부');
  check('` — ` 뒤가 나머지', r.rest === '종전 mq 2026 이 결정 문구 없이 닫혀 재상신');

  r = S('[컨펌] 결정 묶음\n1) 하나\n2) 둘');
  check('여러 줄이면 첫 줄이 제목', r.title === '[컨펌] 결정 묶음');
  check('다음 줄들이 나머지', r.rest === '1) 하나\n2) 둘');

  r = S('본문');
  check('한 줄 짧은 본문은 제목 없음 — 본문뿐', r.title === '' && r.rest === '본문');

  r = S('가'.repeat(120) + ' — 뒤');
  check('제목 후보가 90자를 넘으면 쪼개지 않는다', r.title === '' && r.rest.startsWith('가'));

  r = S('');
  check('빈 값은 빈 값', r.title === '' && r.rest === '');

  const h = C({ id:'T', message:'[컨펌] 제목 — 상세 <b>x</b>' });
  // Issue657: 제목은 본문과 한 문단 — 단독 줄 분리 금지. 제목·나머지는 하나의 .mtxt 안에서 공백으로 이어진다
  check('제목은 .mtitle, 나머지는 .mrest — 한 .mtxt 안에서 공백으로 이어짐', h.includes('<span class="mtxt"><b class="mtitle">[컨펌] 제목</b> <span class="mrest">상세 &lt;b&gt;x&lt;/b&gt;</span></span>'));
  check('제목·나머지는 .mbody 래퍼 안(클릭 → 문서 보기)', /<div class="mbody" data-id="T"[^>]*>[\s\S]*mtitle[\s\S]*<\/div>/.test(h));
  check('제목 없는 본문에는 .mtitle 이 없다', !C({ id:'T', message:'본문' }).includes('mtitle'));

  console.log(fail ? `\n실패 ${fail}건` : '\n전건 통과');
  process.exit(fail ? 1 : 0);
})();
