#!/usr/bin/env node
// Issue569 회귀 테스트 — hub mermaid 가 라벨 글자 하나로 통째로 오류 박스가 되지 않는다.
//
//   왜 필요한가: mermaid 11.6+ 는 라벨 안 `x@` 를 edge-ID 문법(`e1@-->`)으로 가로채
//   다이어그램 전체를 «Syntax error» 박스로 바꾼다(2026-09-28 fWarrange 라이브 뷰 실발생).
//   렌더러가 저작 원문을 그대로 넘기는 한 작성 룰로는 막지 못한다 — Issue183·733 에 이어
//   세 번째다. 그래서 **서버가 실제로 싣는 스크립트 원문**을 그대로 실행해 보정·판정·적용
//   계약과 두 런타임(md 셸·htm)의 단일 출처를 고정한다.
//
//   파서는 대역(stub)이다 — 실 mermaid 의 11.6+ 동작(ego-browser 실측: 따옴표 밖 라벨에서
//   `@` 앞에 공백 아닌 글자가 붙으면 실패)을 본떴다. 실 CDN 대조는 Issue569 결과에 기록.
//
//   실행: node plugins/fpm-core/services/hub/test_mermaid_heal_issue569.js
//   종료: 0=전건 통과 · 1=판정 실패 · 2=스크립트 취득 실패
'use strict';
const vm = require('vm');
const { execFileSync } = require('child_process');

let src;
try {
  const out = execFileSync('python3', ['-c', [
    'import json, md_shell, server',
    'print(json.dumps({',
    '  "js": getattr(md_shell, "MERMAID_JS", None),',
    '  "cdn": md_shell.CDN_MERMAID,',
    '  "render": md_shell.RENDER_JS,',
    '  "runtime": server.MERMAID_RUNTIME.decode("utf-8"),',
    '}))',
  ].join('\n')], { cwd: __dirname, encoding: 'utf-8', stdio: ['ignore', 'pipe', 'inherit'] });
  src = JSON.parse(out.trim().split('\n').pop());
} catch (e) {
  console.error('스크립트 취득 실패:', e.message);
  process.exit(2);
}

let pass = 0, fail = 0;
function check(name, cond, detail) {
  if (cond) { pass++; console.log('  ok   ' + name); return; }
  fail++;
  console.log('  FAIL ' + name + (detail === undefined ? '' : '\n       ' + JSON.stringify(detail)));
}
function done() {
  console.log(`\n${pass} passed, ${fail} failed`);
  process.exit(fail ? 1 : 0);
}

// ── 1. 단일 출처 — 두 서빙 경로가 같은 한 벌을 싣는다 ───────────────────────────
const js = src.js || '';
check('md_shell.MERMAID_JS 가 있다', js.length > 0);
check('CDN 이 정확 버전으로 고정됐다 (부동 major 태그 아님)',
  /\/mermaid@\d+\.\d+\.\d+\//.test(src.cdn), src.cdn);
check('md 셸 RENDER_JS 가 공용 MERMAID_JS 를 싣는다', !!js && src.render.includes(js));
check('htm 런타임 MERMAID_RUNTIME 이 공용 MERMAID_JS 를 싣는다', !!js && src.runtime.includes(js));
check('htm 런타임이 같은 고정 CDN 을 쓴다', src.runtime.includes(src.cdn));
check('공용 JS 밖에서 mermaid.run 을 직접 부르지 않는다',
  !!js && !/mermaid\.run\(/.test(src.render.split(js).join(''))
    && !/mermaid\.run\(/.test(src.runtime.split(js).join('')));
if (!js) done();

// ── 가짜 DOM — run() 의 적용 단계만 흉내 낸다 ─────────────────────────────────
function escapeHtml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}
function decodeHtml(s) {
  return s.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'").replace(/&amp;/g, '&');
}
function fakeEl(tag, attrs, html) {
  return {
    tagName: tag.toUpperCase(), attrs: Object.assign({}, attrs || {}), children: [],
    className: '', style: {}, replacedBy: null, _html: html || '', _text: undefined,
    getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; },
    setAttribute(k, v) { this.attrs[k] = String(v); },
    hasAttribute(k) { return k in this.attrs; },
    appendChild(c) { this.children.push(c); return c; },
    replaceWith(n) { this.replacedBy = n; },
    get innerHTML() { return this._html; },
    set innerHTML(v) { this._html = v; this._text = undefined; },
    get textContent() { return this._text !== undefined ? this._text : decodeHtml(this._html); },
    set textContent(v) { this._text = v; this._html = escapeHtml(v); },
    get value() { return decodeHtml(this._html); },  // textarea — 엔티티만 푼다
  };
}
let nodes = [];
const document = {
  body: {},
  createElement: (tag) => fakeEl(tag),
  querySelectorAll: () => nodes.filter((n) => !n.replacedBy),
};
const runCalls = [];

// 11.6+ 실측을 본뜬 파서: 따옴표 구간을 지운 뒤, 라벨(`[ ( { |` 이후)에서 `@` 앞에
// 공백·여는 괄호가 아닌 글자가 붙어 있으면 실패. `BROKEN` 은 보정으로도 못 고치는 오류.
function stubParse(t) {
  if (/BROKEN/.test(t)) return Promise.reject(new Error('Parse error on line 2:\n...BROKEN\n---^'));
  const bare = t.replace(/"[^"]*"/g, '""');
  if (/[\[({|][^\])}|\n]*[^\s\[({|]@/.test(bare)) {
    return Promise.reject(new Error("Parse error on line 4:\nExpecting 'SEMI', 'NEWLINE'"));
  }
  return Promise.resolve(true);
}
const win = {
  mermaid: {
    initialize() {},
    parse: stubParse,
    run(opts) { runCalls.push(opts.nodes.slice()); return Promise.resolve(); },
  },
};
const ctx = vm.createContext({
  window: win, document, console, Promise,
  getComputedStyle: () => ({ backgroundColor: 'rgb(255, 255, 255)' }),
});
vm.runInContext(js, ctx);
const M = win.hubMermaid;
check('window.hubMermaid 가 quoteLabels·plan·run 을 노출한다',
  !!M && ['quoteLabels', 'plan', 'run'].every((k) => typeof M[k] === 'function'));
if (!M) done();

// ── 2. quoteLabels — 따옴표 없는 라벨만 감싼다 ─────────────────────────────────
// 신고 원문: fWarrange _doc_work/htm/hub_htm_20260928_130646_a_deleg-a-done.md
const REPORT = [
  'flowchart LR',
  '  A[xcstrings 수동 추출] --> D[키 자동 등록 안 됨]',
  '  B[Xcode 심볼 생성 충돌] --> E[4키 넣으면 빌드 실패]',
  '  C[%@ ↔ %lld 불일치] --> F[조회 실패]',
  '  D & E & F --> G[en UI 에 한글 노출]',
  '  G --> H[check_l10n_coverage.py<br/>tdd #12 가드]',
].join('\n');
const q = M.quoteLabels(REPORT);
check('신고 라벨 `%@` 가 따옴표로 감싸진다', q.includes('C["%@ ↔ %lld 불일치"] --> F["조회 실패"]'), q);
check('`<br/>` 든 라벨도 감싸진다', q.includes('H["check_l10n_coverage.py<br/>tdd #12 가드"]'), q);
check('엣지·`&` 구조는 그대로다', q.includes('  D & E & F --> G["en UI 에 한글 노출"]'), q);

const same = (name, s) => check(name, M.quoteLabels(s) === s, M.quoteLabels(s));
same('이미 따옴표인 라벨은 그대로', 'flowchart LR\n  A["x@y [z]"] --> B');
same('`@{…}` 모양 문법은 건드리지 않는다', 'flowchart LR\n  A@{ shape: rect, label: "x" } --> B');
same('edge ID 문법은 건드리지 않는다', 'flowchart LR\n  A e1@--> B');
same('style·classDef·click 줄은 건드리지 않는다',
  'flowchart LR\n  classDef k fill:#f9f\n  style A fill:#fff\n  click A "https://x.y/[a]"');
same('`%%` 주석 줄은 건드리지 않는다', 'flowchart LR\n  %% A[x@y] 메모\n  A --> B');
same('flowchart·graph 가 아니면 건드리지 않는다', 'sequenceDiagram\n  A->>B: user@mail [x]');
check('edge 라벨 `|…|` 도 감싼다',
  M.quoteLabels('flowchart LR\n  A -->|x@ y| B') === 'flowchart LR\n  A -->|"x@ y"| B',
  M.quoteLabels('flowchart LR\n  A -->|x@ y| B'));
check('겹괄호 모양은 긴 것부터 맞춰 모양을 보존한다',
  M.quoteLabels('graph TD\n  A((원@형)) --> B[(d@b)] --> C{{h@x}} --> D([s@t])')
    === 'graph TD\n  A(("원@형")) --> B[("d@b")] --> C{{"h@x"}} --> D(["s@t"])',
  M.quoteLabels('graph TD\n  A((원@형)) --> B[(d@b)] --> C{{h@x}} --> D([s@t])'));
check('라벨 속 괄호도 한 덩어리로 감싼다',
  M.quoteLabels('flowchart LR\n  A[f(x) 호출] --> B') === 'flowchart LR\n  A["f(x) 호출"] --> B',
  M.quoteLabels('flowchart LR\n  A[f(x) 호출] --> B'));

// ── 3. plan — 유효하면 그대로 / 보정되면 보정본 / 아니면 원문 표시 ──────────────
(async () => {
  const OK = 'flowchart LR\n  A[x] --> B[y]';
  let r = await M.plan(OK, stubParse);
  check('유효한 다이어그램은 손대지 않는다', r.mode === 'keep' && r.text === OK, r);

  r = await M.plan(REPORT, stubParse);
  check('신고 원문은 보정본으로 렌더된다', r.mode === 'heal' && r.text === q, r.mode);

  const BAD = 'flowchart LR\n  A[BROKEN] --> B';
  r = await M.plan(BAD, stubParse);
  check('보정해도 안 되면 원문 표시로 물러난다 (오류 첫 줄 동반)',
    r.mode === 'fallback' && r.text === BAD && r.err === 'Parse error on line 2:', r);

  r = await M.plan('sequenceDiagram\n  BROKEN', stubParse);
  check('보정 대상 밖의 오류도 원문 표시', r.mode === 'fallback', r);

  r = await M.plan(OK, () => { throw new Error('sync boom'); });
  check('동기 throw 하는 파서도 원문 표시로 수렴', r.mode === 'fallback' && /sync boom/.test(r.err), r);

  // ── 4. run — 가짜 DOM 에 적용 ──────────────────────────────────────────────
  const vOk = fakeEl('pre', { class: 'mermaid' }, escapeHtml(OK));
  const vHeal = fakeEl('pre', { class: 'mermaid' }, escapeHtml(REPORT));
  const vBad = fakeEl('pre', { class: 'mermaid' }, escapeHtml(BAD));
  const vDone = fakeEl('pre', { class: 'mermaid', 'data-processed': 'true' }, '<svg></svg>');
  nodes = [vOk, vHeal, vBad, vDone];
  await M.run();
  check('mermaid.run 은 1회, 유효·보정 노드만 받는다',
    runCalls.length === 1 && runCalls[0].length === 2
      && runCalls[0][0] === vOk && runCalls[0][1] === vHeal, runCalls.map((c) => c.length));
  check('유효 노드 원문은 그대로', vOk.textContent === OK);
  check('보정 노드는 보정본으로 교체 (엔티티 풀린 원문 기준)', vHeal.textContent === q, vHeal.textContent);
  const box = vBad.replacedBy;
  const flat = (n) => [n].concat(...(n ? n.children.map(flat) : []));
  check('실패 노드는 오류 박스 대신 원문 코드블록으로 교체',
    !!box && box.className === 'mermaid-fallback'
      && flat(box).some((n) => n && n.tagName === 'CODE' && n.textContent === BAD), box && box.className);
  check('원문 표시에 오류 첫 줄이 함께 뜬다',
    !!box && flat(box).some((n) => n && /Parse error on line 2:/.test(n.textContent || '')));
  check('이미 렌더된 노드(data-processed)는 다시 잡지 않는다', !vDone.hasAttribute('data-hub-mmd'));

  await Promise.all([M.run(), M.run()]);
  check('중복·동시 호출은 같은 노드를 다시 렌더하지 않는다', runCalls.length === 1, runCalls.length);

  const vLate = fakeEl('pre', { class: 'mermaid' }, escapeHtml(OK));
  nodes.push(vLate);
  await M.run();
  check('뒤에 붙은 노드(라이브 뷰 append)는 다음 호출에서 렌더된다',
    runCalls.length === 2 && runCalls[1].length === 1 && runCalls[1][0] === vLate, runCalls.length);
  done();
})().catch((e) => { console.error(e); process.exit(1); });
