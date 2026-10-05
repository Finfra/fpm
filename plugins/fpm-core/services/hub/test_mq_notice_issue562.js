#!/usr/bin/env node
// Issue562 회귀 테스트 — /mq **통지(done_unacked)** 행은 [확인] 하나만 내고, 누르면 «후속 없음» 으로 종결한다.
//
//   왜 필요한가: 통지에 [확인](ack → acked_done)·[버림](dismiss → dismissed) 두 버튼이 있었는데,
//   사람이 읽고 닫는 동작은 하나다. prj3 handoff 도 둘 다 «후속 없음» 으로 닫는다 —
//   운영 정책 `handoff_no_followup_actions` 에 acked_done 이 있다(prj3#Issue681).
//   ⚠️ 스크립트 기본값(`post_executed,dismissed`)만 보면 acked_done 이 빠진 것처럼 보인다 —
//   Issue562 등록 시 그렇게 오판했다. 그래서 ⑤ 로 운영 정책 쪽 전제를 함께 지킨다.
//
//   판정 5종:
//     ① 통지 행 버튼 = 정확히 1개, 라벨 «확인»
//     ② 그 버튼을 누르면 `aoa-mq-ack:<id>:ack` 를 보내고 드롭 확인창(confirm)을 띄우지 않는다
//     ③ 예약(due) 행의 [완료]·[연기]·[취소] 는 그대로
//     ④ 하단 범례에 «버림» 이 없고 확인=acked_done 으로 적힌다
//     ⑤ 전제: prj3 policy `handoff_no_followup_actions` 에 acked_done 포함 (policy 부재 시 skip)
//
//   실행: node plugins/fpm-core/services/hub/test_mq_notice_issue562.js [url]
//         (기본 http://127.0.0.1:9876/mq — hub 가 떠 있어야 한다)
//   종료: 0=전건 통과 · 1=판정 실패 · 2=페이지·스크립트 취득 실패
'use strict';
const vm = require('vm');
const URL_ = process.argv[2] || 'http://127.0.0.1:9876/mq';

const FIX = [
  { id:'N-1', status:'done_unacked', type:'alert',     _bucket:'open', message:'통지',     result:null },
  { id:'D-1', status:'due',          type:'scheduled', _bucket:'open', message:'예약 작업', result:null },
];

function fetchPage(url){
  const http = url.startsWith('https') ? require('https') : require('http');
  return new Promise((ok, no) => {
    http.get(url, r => { let b=''; r.on('data', c=>b+=c); r.on('end', ()=>ok(b)); }).on('error', no);
  });
}

// test_mq_render_issue521.js 와 같은 절단 — 스케줄 탭 이하는 부트스트랩이 많고 이 판정과 무관하다.
function queueScript(html){
  const m = html.match(/<script>([\s\S]*?)<\/script>/);
  if(!m) return null;
  let js = m[1];
  const cut = js.indexOf('// ── prj3#Issue570');
  if(cut > 0) js = js.slice(0, cut);
  return js.replace(/^\s*load\(\);\s*setInterval\(load,\s*60000\);\s*$/m, '');
}

function sandbox(sent, confirms, alerts){
  const els = {};
  // fillOpts() 가 select 의 options[0] 을 읽는다 — load() 경로까지 태우므로 흉내 낸다.
  const el = () => ({ textContent:'', innerHTML:'', value:'', checked:false, hidden:false,
    options:[{outerHTML:'<option></option>'}], style:{}, dataset:{}, classList:{add(){},remove(){},toggle(){}},
    addEventListener(){}, querySelectorAll:()=>[], closest:()=>({querySelectorAll:()=>[]}), appendChild(){} });
  const document = { getElementById:id=>els[id]||(els[id]=el()), querySelectorAll:()=>[],
    querySelector:()=>el(), createElement:()=>el(), addEventListener(){}, body:el() };
  // act() 는 접수 뒤 load() 로 /mq-data 를 다시 읽는다 — 빈 목록으로 답한다.
  const fetch = async (url, opt) => {
    if(url === '/mq-ack'){
      sent.push(JSON.parse(opt.body).question);
      return { json: async () => ({ ok:true, consumed:false, lock:{} }) };
    }
    return { json: async () => ({ ok:true, items:[], open_count:0, done_count:0, mq_dir:'-' }) };
  };
  const ctx = { document, window:{}, console, URL, URLSearchParams, Date, Math, JSON,
    location:{href:'http://x/mq', search:''}, history:{pushState(){},replaceState(){}},
    addEventListener(){}, setInterval:()=>0, setTimeout:()=>0, clearTimeout(){},
    fetch, EventSource:function(){}, localStorage:{getItem:()=>null, setItem(){}},
    confirm:()=>{ confirms.push(1); return true; }, prompt:()=>null,
    alert:m=>{ alerts.push(String(m)); } };
  ctx.globalThis = ctx;
  return ctx;
}

(async () => {
  let html;
  try { html = await fetchPage(URL_); }
  catch(e){ console.error(`⛔ 페이지 취득 실패 (${URL_}): ${e.message} — hub 가 떠 있는지 확인`); process.exit(2); }
  const js = queueScript(html);
  if(!js){ console.error('⛔ 인라인 스크립트 추출 실패 — 페이지 구조가 바뀌었다'); process.exit(2); }

  const sent = [], confirms = [], alerts = [];
  const ctx = sandbox(sent, confirms, alerts);
  const probe = `
    pass = () => true;
    DATA = ${JSON.stringify(FIX)};
    ACKED = {};
    render();
    globalThis.__OUT = document.getElementById("rows").innerHTML;
  `;
  try { vm.runInNewContext(js + probe, ctx, { filename:'mq-inline.js' }); }
  catch(e){ console.error(`⛔ 스크립트 실행 실패: ${e.message}`); process.exit(2); }

  const rows = String(ctx.__OUT || '').split('<tr').slice(1);
  const rowOf = id => rows.find(r => r.includes(`'${id}'`)) || '';
  const buttons = row => [...row.matchAll(/<button[^>]*onclick="act\('([^']+)','([^']+)'[^>]*>([^<]*)<\/button>/g)]
    .map(m => ({ action:m[2], label:m[3].trim() }));
  let fail = 0;
  const check = (ok, msg) => { if(!ok) fail++; console.log(`${ok?'✅':'❌'} ${msg}`); };

  // ① 통지 행 버튼 1개
  const nb = buttons(rowOf('N-1'));
  // Issue565: 라벨 앞 이모지(👁)는 허용 — 판정 대상은 «버튼이 확인 하나» 다
  check(nb.length === 1 && /^(?:\S+\s)?확인$/.test(nb[0].label),
    `① 통지 행 버튼 = ${JSON.stringify(nb.map(b=>b.label+':'+b.action))} (기대: [확인] 1개)`);

  // ② 누르면 ack 를 보내고 드롭 확인창 없음
  if(nb.length === 1){
    try {
      await vm.runInNewContext(`act('N-1', ${JSON.stringify(nb[0].action)}, {closest:()=>({querySelectorAll:()=>[]})})`, ctx);
    } catch(e){ console.error(`⛔ act() 실행 실패: ${e.message}`); process.exit(2); }
  }
  check(sent.length === 1 && sent[0] === 'aoa-mq-ack:N-1:ack',
    `② 전송 = ${JSON.stringify(sent)} (기대: ["aoa-mq-ack:N-1:ack"] — acked_done)`);
  check(alerts.length === 0, `② 접수 실패 alert ${JSON.stringify(alerts)} (기대: 없음)`);
  check(confirms.length === 0, `② 드롭 확인창 호출 ${confirms.length}회 (기대: 0 — 통지 확인은 드롭이 아니다)`);

  // ③ 예약 행 회귀
  const db = buttons(rowOf('D-1')).map(b => b.action);
  check(['confirm','snooze','dismiss'].every(a => db.includes(a)),
    `③ 예약 행 액션 = ${JSON.stringify(db)} (기대: confirm·snooze·dismiss 유지)`);

  // ④ 범례
  const note = (html.match(/<div class="note" id="note">([\s\S]*?)<\/div>/) || [,''])[1];
  check(note && !/버림/.test(note) && /확인<\/b>=[^·]*acked_done/.test(note),
    '④ 범례에 «버림» 이 없고 확인=acked_done 으로 적힌다');

  // ⑤ 운영 정책 전제 — 이 버튼 하나가 «후속 없음» 으로 닫힌다는 근거
  const fs = require('fs'), path = require('path');
  const pol = path.join(process.env.HOME || '', '.claude', 'data', 'aoa', 'mq', 'policy.yml');
  if(!fs.existsSync(pol)) console.log(`⏭  ⑤ policy 부재(${pol}) — skip`);
  else {
    const m = fs.readFileSync(pol, 'utf8').match(/^handoff_no_followup_actions:\s*([^#\n]+)/m);
    const acts = m ? m[1].split(',').map(x => x.trim()) : [];
    check(acts.includes('acked_done'),
      `⑤ handoff_no_followup_actions = ${JSON.stringify(acts)} (기대: acked_done 포함 — 없으면 확인한 통지가 이슈후보로 승격)`);
  }

  console.log(fail ? `\n실패 ${fail}건` : '\n전건 통과');
  process.exit(fail ? 1 : 0);
})();
