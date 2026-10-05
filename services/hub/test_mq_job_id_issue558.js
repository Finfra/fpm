#!/usr/bin/env node
// Issue558 회귀 테스트 — /mq 잡 탭 행에 📋 잡 ID 팝업이 스케줄 탭(Issue540)과 같은 규약으로 서는지 판정한다.
//
//   Issue521·549·554 와 같은 방식 — **서버가 실제로 내려준 스크립트를 그대로 실행**하고 고정값을 먹인다.
//
//   판정 ① 렌더: 사용자·시스템 잡 모두 액션 열 맨 앞에 📋(.sid-copy · data-kind="job") — 사용자 잡의 .agrid 6버튼은 그대로
//   판정 ② 팝업: jobMenuOpen() 이 #sch-menu 에 머리(잡 이름) + 잡 ID 복사 · 실행 명령 복사 · 지금 실행 · 설명 · 스케줄 보기
//   판정 ③ 동작: id → 잡 이름 복사 · cmd → dispatch 명령 복사 · run → confirm 후 run 전송(취소면 무전송)
//                note → jobNote(시스템 잡은 disabled) · sched → 스케줄 탭
//   판정 ④ hover: 📋 hover-intent 가 data-kind 로 갈린다 — 잡 버튼은 잡 팝업, 스케줄 버튼은 종전 스케줄 팝업(회귀)
//
//   실행: node plugins/fpm-core/services/hub/test_mq_job_id_issue558.js [url]
//         (기본 http://127.0.0.1:9876/mq — hub 가 떠 있어야 한다)
//   종료: 0=전건 통과 · 1=판정 실패 · 2=페이지·스크립트 취득 실패
'use strict';
const vm = require('vm');
const URL_ = process.argv[2] || 'http://127.0.0.1:9876/mq';

const JOBS = [
  { name:'j-user', source:'user',   bindings_n:2, steps:[{kind:'sh', run:'true'}] },
  { name:'sys-j',  source:'system', desc:'시스템', bindings_n:1, steps:[{kind:'sh', run:'true'}] },
];
const BINDS = [ { job:'j-user', event:'t-0703', source:'user' } ];
const EVENTS = [ { name:'t-0703', type:'calendar', spec:'07:03' } ];

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
// hover 경로를 실제로 태우려고 document 리스너와 setTimeout 콜백을 **적어 둔다**(즉시 실행하지 않는다)
function sandbox(){
  const els = {}, listeners = {}, timers = [];
  const rect = () => ({ left:0, right:100, top:0, bottom:20, width:100, height:20 });
  const el = () => ({ textContent:'', innerHTML:'', value:'', checked:false, hidden:false,
    style:{}, dataset:{}, classList:{add(){},remove(){},toggle(){}}, getBoundingClientRect:rect,
    addEventListener(){}, querySelectorAll:()=>[], closest:()=>null, appendChild(){}, setAttribute(){} });
  const document = { getElementById:id=>els[id]||(els[id]=el()), querySelectorAll:()=>[],
    querySelector:()=>el(), createElement:()=>el(), body:el(),
    addEventListener(t, fn){ (listeners[t] = listeners[t] || []).push(fn); } };
  const ctx = { document, window:{}, console, URL, URLSearchParams, Date, Math, JSON,
    location:{href:'http://x/mq', search:''}, history:{pushState(){},replaceState(){}},
    addEventListener(){}, setInterval:()=>0, setTimeout:fn=>{ timers.push(fn); return timers.length; }, clearTimeout(){},
    fetch:()=>Promise.reject(new Error('네트워크 미사용')), EventSource:function(){},
    localStorage:{getItem:()=>null, setItem(){}},
    prompt:()=>null, confirm:()=>false, alert(){}, innerWidth:1200, innerHeight:800,
    __listeners:listeners, __timers:timers, __rect:rect };
  ctx.globalThis = ctx;
  return ctx;
}
const cellOf = (tr, cls) => ((tr.match(new RegExp(`<td class="${cls}">([\\s\\S]*?)<\\/td>`)) || [])[1] || '');
const btnLabels = h => [...h.matchAll(/<button[^>]*>([\s\S]*?)<\/button>/g)].map(m => m[1].replace(/<[^>]+>/g,'').trim());
const actsOf = h => [...h.matchAll(/<button[^>]*data-act="([^"]+)"[^>]*>([\s\S]*?)<\/button>/g)]
  .map(m => ({ act:m[1], label:m[2].replace(/<[^>]+>/g,'').replace(/\s+/g,' ').trim(), disabled:/\sdisabled/.test(m[0].split('>')[0]) }));

(async () => {
  let html;
  try { html = await fetchPage(URL_); }
  catch(e){ console.error(`⛔ 페이지 취득 실패 (${URL_}): ${e.message} — hub 가 떠 있는지 확인`); process.exit(2); }
  const js = inlineScript(html);
  if(!js){ console.error('⛔ 인라인 스크립트 추출 실패 — 페이지 구조가 바뀌었다'); process.exit(2); }

  const ctx = sandbox();
  const probe = `
    DATA = []; ACKED = {};
    SDATA = { ok:true, jobs: ${JSON.stringify(JOBS)}, bindings: ${JSON.stringify(BINDS)}, events: ${JSON.stringify(EVENTS)}, runs:[] };
    SSYS = true;                              // 시스템 잡은 기본 숨김(Issue584) — 시스템 행 📋 를 보려면 켠다
    renderJobs();
    globalThis.__OUT = document.getElementById("j-body").innerHTML;
    // ── 부작용은 네트워크·클립보드 대신 받아 적는다
    globalThis.__COPIES = []; copyText = (t, l) => __COPIES.push([t, l]);
    globalThis.__POSTS = [];  sPost = async p => { __POSTS.push(p); return {ok:true, msg:"ok"}; };
    sReload = async () => {}; jMsg = () => {}; sMsg = () => {};
    globalThis.__TABS = [];   showTab = t => __TABS.push(t);
    globalThis.__NOTES = [];  jobNote = n => __NOTES.push(n);
  `;
  try { vm.runInNewContext(js + probe, ctx, { filename:'mq-inline.js' }); }
  catch(e){ console.error(`⛔ 스크립트 실행 실패: ${e.message}`); process.exit(2); }

  let fail = 0, n = 0;
  const check = (ok, label) => { n++; if(!ok) fail++; console.log(`${ok?'✅':'❌'} ${label}`); };
  const out = String(ctx.__OUT || '');
  const rows = out.split('<tr class="jrow').slice(1);
  const rowOf = nm => rows.find(r => r.includes(`class="jname">${nm}`)) || '';
  const RU = rowOf('j-user'), RS = rowOf('sys-j');
  check(RU && RS, `잡 2행 렌더 (${rows.length}건)`);

  // ① 렌더
  const idBtnRe = nm => new RegExp(`<button class="mini sid-copy"[^>]*data-kind="job"[^>]*data-job="${nm}"[^>]*onclick="jobMenuOpen\\(this\\)"[^>]*>📋</button>`);
  const aU = cellOf(RU, 'sacts'), aS = cellOf(RS, 'sacts');
  check(idBtnRe('j-user').test(aU) && aU.indexOf('📋') < aU.indexOf('<div class="agrid">'),
        '사용자 잡: 액션 열 맨 앞에 📋(data-kind="job") — .agrid 앞');
  const grid = ((aU.match(/<div class="agrid">([\s\S]*?)<\/div>/) || [])[1] || '');
  check(JSON.stringify(btnLabels(grid)) === JSON.stringify(['▶ 실행','✎ 수정','⏸ 멈춤','⏰ 예약','🗓＋','✕ 삭제']),
        `.agrid 6버튼 그대로(Issue554) — 실제 ${JSON.stringify(btnLabels(grid))}`);
  check(idBtnRe('sys-j').test(aS) && JSON.stringify(btnLabels(aS)) === JSON.stringify(['📋']),
        `시스템 잡: 📋 만 — 실제 ${JSON.stringify(btnLabels(aS))}`);

  // ② 팝업
  if(typeof ctx.jobMenuOpen !== 'function'){
    check(false, 'jobMenuOpen 이 정의되어 있다');
    console.log(`\n실패 ${fail}건 / ${n}`); process.exit(1);
  }
  const menu = () => ctx.document.getElementById('sch-menu');
  const btn = nm => ({ dataset:{ kind:'job', job:nm }, getBoundingClientRect:ctx.__rect });
  const open = nm => { const m = menu(); m.hidden = true; m.dataset.id = ''; ctx.jobMenuOpen(btn(nm)); return m; };
  const click = async (m, act) => {
    const a = actsOf(m.innerHTML).find(x => x.act === act) || {};
    await m.onclick({ target:{ closest:() => ({ dataset:{ act }, disabled:!!a.disabled }) } });
  };

  let m = open('j-user');
  const head = ((m.innerHTML.match(/<div class="sch-menu-head">([\s\S]*?)<\/div>/) || [])[1] || '');
  const acts = actsOf(m.innerHTML);
  check(m.hidden === false && head === 'j-user', `팝업 열림 · 머리 = 잡 이름 — 실제 hidden=${m.hidden} head=${JSON.stringify(head)}`);
  check(JSON.stringify(acts.map(a => a.act)) === JSON.stringify(['id','cmd','run','note','sched']),
        `항목 순서 id·cmd·run·note·sched — 실제 ${JSON.stringify(acts.map(a => a.act))}`);
  const lab = k => (acts.find(a => a.act === k) || {}).label || '';
  check(lab('id').includes('잡 ID 복사') && lab('cmd').includes('실행 명령 복사') && lab('run').includes('지금 실행')
        && lab('note').includes('설명 추가') && lab('sched').includes('스케줄 보기 (2)'),
        `라벨 — ${JSON.stringify(acts.map(a => a.label))}`);
  check(acts.every(a => !a.disabled), '사용자 잡: 비활성 항목 없음');

  // ③ 동작
  await click(m, 'id');
  check(JSON.stringify(ctx.__COPIES[0]) === JSON.stringify(['j-user','잡 ID']), `잡 ID 복사 = 잡 이름 — 실제 ${JSON.stringify(ctx.__COPIES[0])}`);
  check(m.hidden === true, '항목을 누르면 팝업이 닫힌다');
  await click(open('j-user'), 'cmd');
  check(JSON.stringify(ctx.__COPIES[1]) === JSON.stringify(['bash ~/.claude/hooks/schedule.sh dispatch --job j-user','실행 명령']),
        `실행 명령 복사 — 실제 ${JSON.stringify(ctx.__COPIES[1])}`);
  ctx.confirm = () => false; await click(open('j-user'), 'run');
  check(ctx.__POSTS.length === 0, `지금 실행 — confirm 취소면 전송 없음 (실제 ${ctx.__POSTS.length}건)`);
  ctx.confirm = () => true;  await click(open('j-user'), 'run');
  check(ctx.__POSTS.length === 1 && ctx.__POSTS[0].action === 'run' && ctx.__POSTS[0].name === 'j-user',
        `지금 실행 — confirm 후 run 전송 — 실제 ${JSON.stringify(ctx.__POSTS)}`);
  await click(open('j-user'), 'note');
  check(JSON.stringify(ctx.__NOTES) === JSON.stringify(['j-user']), `설명 → jobNote — 실제 ${JSON.stringify(ctx.__NOTES)}`);
  await click(open('j-user'), 'sched');
  check(JSON.stringify(ctx.__TABS) === JSON.stringify(['s']), `스케줄 보기 → 스케줄 탭 — 실제 ${JSON.stringify(ctx.__TABS)}`);

  m = open('sys-j');
  const sa = actsOf(m.innerHTML);
  check(JSON.stringify(sa.filter(a => a.disabled).map(a => a.act)) === JSON.stringify(['note']),
        `시스템 잡: 설명만 비활성 — 실제 ${JSON.stringify(sa.filter(a => a.disabled).map(a => a.act))}`);
  await click(m, 'note');
  check(ctx.__NOTES.length === 1, '시스템 잡: 비활성 설명은 눌러도 동작 없음');
  await click(open('sys-j'), 'id');
  check(JSON.stringify(ctx.__COPIES[2]) === JSON.stringify(['sys-j','잡 ID']), '시스템 잡도 잡 ID 복사');

  // ④ hover — 실제 mouseover 리스너 → hover-intent 타이머 → 팝업
  const hover = target => {
    const mm = menu(); mm.hidden = true; mm.dataset.id = ''; mm.innerHTML = '';
    ctx.__timers.length = 0;
    const ev = { target:{ closest:sel => (sel === '.sid-copy' ? target : null) } };
    (ctx.__listeners.mouseover || []).forEach(fn => fn(ev));
    ctx.__timers.forEach(fn => fn());
    return mm.innerHTML;
  };
  const hj = hover(btn('j-user'));
  check(hj.includes('잡 ID 복사') && !hj.includes('스케줄 ID 복사'), 'hover: 잡 📋 → 잡 팝업');
  const hs = hover({ dataset:{ job:'j-user', event:'t-0703' }, getBoundingClientRect:ctx.__rect });
  check(hs.includes('스케줄 ID 복사') && hs.includes('j-user@t-0703'), 'hover: 스케줄 📋 → 종전 스케줄 팝업 (Issue540 회귀)');

  console.log(fail ? `\n실패 ${fail}건 / ${n}` : `\n전건 통과 (${n}/${n})`);
  process.exit(fail ? 1 : 0);
})();
