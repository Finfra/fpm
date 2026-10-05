#!/usr/bin/env node
// Issue565 회귀 테스트 (화면 절반) — /mq 큐 탭 행에 📋 mq ID 메뉴가 스케줄·잡 탭(Issue540·558)과 같은 규약으로 서고,
//   내용 본문을 누르면 문서 뷰(/mq-doc)로 넘어가는지 판정한다.
//
//   Issue521·558 과 같은 방식 — 페이지의 인라인 스크립트를 **그대로 실행**하고 고정값을 먹인다.
//   페이지 출처: 인자 없으면 server.py 의 `_MQ_PAGE_HTML` 원문(hub 기동 불요) · URL 을 주면 그 서버가 내려준 것.
//
//   판정 ① 렌더: 미종결·종결 행 모두 처리 열 맨 앞에 📋(.sid-copy · data-kind="mq" · data-id) — 종전 액션은 그대로
//                내용 본문은 .mbody(data-id) 로 감싸 클릭 대상 — 진행 3종 줄은 그 밖
//   판정 ② 본문 클릭: 선택 없음 → 새 탭 /mq-doc?id= · 텍스트 선택 중·링크·버튼 클릭은 넘어가지 않는다
//   판정 ③ 팝업: mqMenuOpen() 이 #sch-menu 에 머리(id) + mq ID 복사 · 내용 복사 · 문서로 보기 · 문서 링크 복사
//   판정 ④ hover: 📋 hover-intent 가 data-kind 로 갈린다 — mq → mq 팝업, 잡·스케줄은 종전 팝업(회귀)
//
//   실행: node plugins/fpm-core/services/hub/test_mq_id_menu_issue565.js [url]
//   종료: 0=전건 통과 · 1=판정 실패 · 2=페이지·스크립트 취득 실패
'use strict';
const vm = require('vm');
const fs = require('fs');
const path = require('path');
const URL_ = process.argv[2] || '';

const Q = { id:'20260928-102923-001', status:'due', type:'scheduled', source:'claude@.claude', _bucket:'queue',
            due_ts:'2026-09-28T09:00:00', message:'[컨펌] 결정 묶음\n1) 하나\n2) 둘',
            progress:'재점검 중', progress_ts:'2026-09-28T00:35:00' };
const D = { id:'20260901-000001-001', status:'confirmed', type:'alert', source:'claude@x', _bucket:'done', message:'끝' };
const N = { id:'20260928-000009-001', status:'done_unacked', type:'watch', source:'claude@x', _bucket:'queue', message:'봇이 끝냄' };

function fetchPage(url){
  const http = url.startsWith('https') ? require('https') : require('http');
  return new Promise((ok, no) => {
    http.get(url, r => { let b=''; r.on('data', c=>b+=c); r.on('end', ()=>ok(b)); }).on('error', no);
  });
}
function pageFromSource(){
  const src = fs.readFileSync(path.join(__dirname, 'server.py'), 'utf8');
  const m = src.match(/_MQ_PAGE_HTML = r"""([\s\S]*?)"""/);
  return m ? m[1] : '';
}
function inlineScript(html){
  const m = html.match(/<script>([\s\S]*?)<\/script>/);
  if(!m) return null;
  return m[1].replace(/^\s*load\(\);\s*setInterval\(load,\s*60000\);\s*$/m, '');
}
function sandbox(){
  const els = {}, listeners = {}, timers = [];
  const rect = () => ({ left:0, right:100, top:0, bottom:20, width:100, height:20 });
  const el = () => ({ textContent:'', innerHTML:'', value:'', checked:false, hidden:false,
    style:{}, dataset:{}, classList:{add(){},remove(){},toggle(){}}, getBoundingClientRect:rect,
    addEventListener(){}, querySelectorAll:()=>[], querySelector:()=>null, closest:()=>null,
    appendChild(){}, setAttribute(){}, options:[{outerHTML:'<option value="">전체</option>'}] });
  const document = { getElementById:id=>els[id]||(els[id]=el()), querySelectorAll:()=>[],
    querySelector:()=>el(), createElement:()=>el(), body:el(),
    addEventListener(t, fn){ (listeners[t] = listeners[t] || []).push(fn); } };
  const opens = [];
  const win = { open:(u, t) => { opens.push([u, t]); return null; }, getSelection:() => ({ toString:() => win.__sel || '' }) };
  const ctx = { document, window:win, console, URL, URLSearchParams, Date, Math, JSON,
    location:{href:'http://x/mq', search:''}, history:{pushState(){},replaceState(){}},
    addEventListener(){}, setInterval:()=>0, setTimeout:fn=>{ timers.push(fn); return timers.length; }, clearTimeout(){},
    fetch:()=>Promise.reject(new Error('네트워크 미사용')), EventSource:function(){},
    localStorage:{getItem:()=>null, setItem(){}}, navigator:{},
    prompt:()=>null, confirm:()=>false, alert(){}, innerWidth:1200, innerHeight:800,
    __listeners:listeners, __timers:timers, __rect:rect, __opens:opens };
  ctx.globalThis = ctx;
  return ctx;
}
const lastTd = tr => { const t = tr.split('<td'); return t[t.length-1] || ''; };
const msgTd = tr => ((tr.match(/<td class="msg">([\s\S]*?)<\/td>/) || [])[1] || '');
const actsOf = h => [...h.matchAll(/<button[^>]*data-act="([^"]+)"[^>]*>([\s\S]*?)<\/button>/g)]
  .map(m => ({ act:m[1], label:m[2].replace(/<[^>]+>/g,'').replace(/\s+/g,' ').trim() }));

(async () => {
  let html;
  if(URL_){
    try { html = await fetchPage(URL_); }
    catch(e){ console.error(`⛔ 페이지 취득 실패 (${URL_}): ${e.message} — hub 가 떠 있는지 확인`); process.exit(2); }
  } else html = pageFromSource();
  const js = inlineScript(html || '');
  if(!js){ console.error('⛔ 인라인 스크립트 추출 실패 — 페이지 구조가 바뀌었다'); process.exit(2); }

  const ctx = sandbox();
  const probe = `
    DATA = ${JSON.stringify([Q, D, N])}; ACKED = {};
    render();
    globalThis.__OUT = document.getElementById("rows").innerHTML;
    globalThis.__COPIES = []; copyText = (t, l) => __COPIES.push([t, l]);
    SDATA = { ok:true, jobs:[{name:'j-user', source:'user', bindings_n:0, steps:[]}],
              bindings:[{job:'j-user', event:'t-0703', source:'user'}], events:[], runs:[] };
  `;
  try { vm.runInNewContext(js + probe, ctx, { filename:'mq-inline.js' }); }
  catch(e){ console.error(`⛔ 스크립트 실행 실패: ${e.message}`); process.exit(2); }

  let fail = 0, n = 0;
  const check = (ok, label) => { n++; if(!ok) fail++; console.log(`${ok?'✅':'❌'} ${label}`); };
  const out = String(ctx.__OUT || '');
  const rows = out.split('<tr').slice(1);
  // idCell() 은 id 를 `<i>시각-순번</i><b>날짜</b>` 로 접는다(Issue498·500) — 그 꼴로 찾는다
  const rowOf = id => rows.find(r => r.includes(`<i>${id.slice(9)}</i><b>${id.slice(0,8)}</b>`)) || '';
  const RQ = rowOf(Q.id), RD = rowOf(D.id);
  check(RQ && RD && rows.length === 3, `큐 3행 렌더 (${rows.length}건)`);

  // ① 렌더
  // 📋 와 액션 묶음은 .qacts(flex) 한 줄 — .acts 는 grid 블록이라 감싸지 않으면 📋 아래로 떨어진다
  const idBtnRe = id => new RegExp(`^[^<]*>\\s*<div class="qacts">\\s*<button class="mini sid-copy"[^>]*data-kind="mq"[^>]*data-id="${id}"[^>]*onclick="mqMenuOpen\\(this\\)"[^>]*>📋</button>`);
  const aQ = lastTd(RQ), aD = lastTd(RD);
  check(idBtnRe(Q.id).test(aQ) && aQ.indexOf('📋') < aQ.indexOf('<div class="acts">'),
        '미종결 행: 처리 열 맨 앞에 📋(data-kind="mq", data-id) — .acts 앞');
  // 처리 버튼 라벨에도 이모지 — 스케줄·잡 탭(▶ 실행 · ✎ 수정 · ✕ 삭제)과 같은 기호 체계(사용자 요청 2026-09-28)
  const actLabels = h => [...h.matchAll(/<button class="a[^"]*"[^>]*onclick="act\([^)]*\)"[^>]*>([^<]*)<\/button>/g)].map(m => m[1].trim());
  check(JSON.stringify(actLabels(aQ)) === JSON.stringify(['▶ 진행','✓ 완료','⏳ 연기','✕ 취소']),
        `미종결 행: 처리 버튼 = ▶ 진행 · ✓ 완료 · ⏳ 연기 · ✕ 취소 — 실제 ${JSON.stringify(actLabels(aQ))}`);
  check(/<button class="a danger"[^>]*act\('[^']+','dismiss'/.test(aQ), '✕ 취소는 danger (잡 탭 ✕ 삭제와 같은 붉은 hover)');
  const aN = lastTd(rowOf(N.id));
  check(JSON.stringify(actLabels(aN)) === JSON.stringify(['👁 확인']), `통지 행: 👁 확인 하나 — 실제 ${JSON.stringify(actLabels(aN))}`);
  check(idBtnRe(D.id).test(aD) && aD.includes('종결됨'), '종결 행에도 📋 — 종결됨 칩은 그대로');
  const mQ = msgTd(RQ);
  const mb = (mQ.match(/<div class="mbody" data-id="([^"]+)"[^>]*onclick="mqDocClick\(event,this\)"[^>]*>([\s\S]*?)<\/div>/) || []);
  check(mb[1] === Q.id && mb[2].includes('[컨펌] 결정 묶음'), `내용 본문 = .mbody(data-id, onclick) — 실제 ${JSON.stringify(mQ.slice(0,160))}`);
  check(!String(mb[2] || '').includes('재점검 중') && mQ.includes('재점검 중'), '진행 3종 줄은 .mbody 밖');

  // ② 본문 클릭
  if(typeof ctx.mqDocClick !== 'function'){
    check(false, 'mqDocClick 이 정의되어 있다');
  } else {
    const elOf = id => ({ dataset:{ id } });
    const ev = (inLink) => ({ target:{ closest:sel => (inLink && /a|button/.test(sel) ? {} : null) } });
    ctx.window.__sel = ''; ctx.mqDocClick(ev(false), elOf(Q.id));
    check(JSON.stringify(ctx.__opens[0]) === JSON.stringify([`/mq-doc?id=${Q.id}`, '_blank']),
          `선택 없음 → 새 탭 /mq-doc — 실제 ${JSON.stringify(ctx.__opens[0])}`);
    ctx.window.__sel = '6건만'; ctx.mqDocClick(ev(false), elOf(Q.id));
    check(ctx.__opens.length === 1, '텍스트 선택 중이면 넘어가지 않는다 (복사하려고 끄는 중)');
    ctx.window.__sel = ''; ctx.mqDocClick(ev(true), elOf(Q.id));
    check(ctx.__opens.length === 1, '링크·버튼 클릭은 넘어가지 않는다');
  }

  // ③ 팝업
  if(typeof ctx.mqMenuOpen !== 'function'){
    check(false, 'mqMenuOpen 이 정의되어 있다');
    console.log(`\n실패 ${fail}건 / ${n}`); process.exit(1);
  }
  const menu = () => ctx.document.getElementById('sch-menu');
  const btn = id => ({ dataset:{ kind:'mq', id }, getBoundingClientRect:ctx.__rect });
  const open = id => { const m = menu(); m.hidden = true; m.dataset.id = ''; ctx.mqMenuOpen(btn(id)); return m; };
  const click = async (m, act) => { await m.onclick({ target:{ closest:() => ({ dataset:{ act }, disabled:false }) } }); };
  let m = open(Q.id);
  const head = ((m.innerHTML.match(/<div class="sch-menu-head">([\s\S]*?)<\/div>/) || [])[1] || '');
  const acts = actsOf(m.innerHTML);
  check(m.hidden === false && head === Q.id, `팝업 열림 · 머리 = mq id — 실제 hidden=${m.hidden} head=${JSON.stringify(head)}`);
  check(JSON.stringify(acts.map(a => a.act)) === JSON.stringify(['id','msg','doc','link']),
        `항목 순서 id·msg·doc·link — 실제 ${JSON.stringify(acts.map(a => a.act))}`);
  const lab = k => (acts.find(a => a.act === k) || {}).label || '';
  check(lab('id').includes('mq ID 복사') && lab('msg').includes('내용 복사') && lab('doc').includes('문서로 보기')
        && lab('link').includes('문서 링크 복사'), `라벨 — ${JSON.stringify(acts.map(a => a.label))}`);
  await click(m, 'id');
  check(JSON.stringify(ctx.__COPIES[0]) === JSON.stringify([Q.id, 'mq ID']), `mq ID 복사 — 실제 ${JSON.stringify(ctx.__COPIES[0])}`);
  check(m.hidden === true, '항목을 누르면 팝업이 닫힌다');
  await click(open(Q.id), 'msg');
  check(JSON.stringify(ctx.__COPIES[1]) === JSON.stringify([Q.message, '내용']), `내용 복사 = 원문(개행 포함) — 실제 ${JSON.stringify(ctx.__COPIES[1])}`);
  const before = ctx.__opens.length;
  await click(open(Q.id), 'doc');
  check(JSON.stringify(ctx.__opens[before]) === JSON.stringify([`/mq-doc?id=${Q.id}`, '_blank']),
        `문서로 보기 → 새 탭 — 실제 ${JSON.stringify(ctx.__opens[before])}`);
  await click(open(Q.id), 'link');
  check(JSON.stringify(ctx.__COPIES[2]) === JSON.stringify([`http://x/mq-doc?id=${Q.id}`, '문서 링크']),
        `문서 링크 복사 = 절대 URL — 실제 ${JSON.stringify(ctx.__COPIES[2])}`);
  await click(open(D.id), 'id');
  check(JSON.stringify(ctx.__COPIES[3]) === JSON.stringify([D.id, 'mq ID']), '종결 항목도 mq ID 복사');

  // ④ hover — 실제 mouseover 리스너 → hover-intent 타이머 → 팝업
  const hover = target => {
    const mm = menu(); mm.hidden = true; mm.dataset.id = ''; mm.innerHTML = '';
    ctx.__timers.length = 0;
    const e = { target:{ closest:sel => (sel === '.sid-copy' ? target : null) } };
    (ctx.__listeners.mouseover || []).forEach(fn => fn(e));
    ctx.__timers.forEach(fn => fn());
    return mm.innerHTML;
  };
  const hq = hover(btn(Q.id));
  check(hq.includes('mq ID 복사') && !hq.includes('잡 ID 복사') && !hq.includes('스케줄 ID 복사'), 'hover: mq 📋 → mq 팝업');
  const hj = hover({ dataset:{ kind:'job', job:'j-user' }, getBoundingClientRect:ctx.__rect });
  check(hj.includes('잡 ID 복사'), 'hover: 잡 📋 → 잡 팝업 (Issue558 회귀)');
  const hs = hover({ dataset:{ job:'j-user', event:'t-0703' }, getBoundingClientRect:ctx.__rect });
  check(hs.includes('스케줄 ID 복사'), 'hover: 스케줄 📋 → 스케줄 팝업 (Issue540 회귀)');

  console.log(fail ? `\n실패 ${fail}건 / ${n}` : `\n전건 통과 (${n}/${n})`);
  process.exit(fail ? 1 : 0);
})();
