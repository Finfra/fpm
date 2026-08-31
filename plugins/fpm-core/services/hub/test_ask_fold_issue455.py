#!/usr/bin/env python3
# test_ask_fold_issue455.py — Issue455 회귀 테스트
#
# ⚠️ 글로벌 SCAR 아님 (___pm 프로젝트 소유). `..ask` 모달의 **질문 접기**를 검증한다.
#   폼 생성 지점(prj3 hooks/fpm-ask-intercept.sh)은 여기 범위가 아니다 — 접기는
#   모달 shim(server.py ASK_MODAL_CSS·ASK_MODAL_JS) 소관이라 prj1 에서 지킨다.
#
# 2단 구성:
#   1. 계약 검사 — 스니펫에 접기 클래스·CSP 제약(인라인 핸들러 0)이 살아 있는가. 항상 실행
#   2. 동작 검사 — node+jsdom 으로 실제 DOM 을 만들어 접힘·요약·예외 3종을 본다.
#      도구가 없으면 **skip 을 명시**하고 넘어간다(거짓 통과 금지 — Issue435 교훈).
#
# 실행: python3 services/hub/test_ask_fold_issue455.py
"""`..ask` 모달 질문 접기(Issue455) 계약 + DOM 동작 테스트."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server  # noqa: E402

PASS = 0
FAIL = 0
SKIP = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok   {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}")


def skip(name, why):
    global SKIP
    SKIP += 1
    print(f"  skip {name} — {why}")


SNIP = server._ask_modal_snippet({"title": "t", "form_html": "__FORM__"}).decode()

# ── 1. 계약 ──────────────────────────────────────────────────────────────
print("[계약]")
for frag in ("fpm-q-tog", "fpm-q-caret", "fpm-q-pick", "fpm-q-done"):
    check(f"스니펫에 {frag}", frag in SNIP)
# Issue452 와 같은 제약: md 셸의 nonce 부여를 그대로 타야 하므로 인라인 핸들러 금지.
check("인라인 이벤트 핸들러 없음(CSP)",
      not re.search(r"""\son[a-z]+\s*=\s*["']""", server.ASK_MODAL_JS))
check("addEventListener 로만 배선", server.ASK_MODAL_JS.count("addEventListener") >= 5)
# 접힌 카드는 legend 만 남는다 — 그 규칙이 CSS 에 있어야 요약이 보인다.
check("접힘 시 legend 만 표시",
      "fieldset.fpm-q-done > *:not(legend){display:none" in server.ASK_MODAL_CSS)

# ── 2. DOM 동작 (node + jsdom) ───────────────────────────────────────────
print("\n[동작]")
JS_TEST = r"""
const { JSDOM } = require('jsdom');
const SNIP = require('fs').readFileSync(process.argv[2], 'utf8');
const out = [];
const ck = (n, c) => out.push([n, !!c]);

function build(n, cls) {
  let form = '';
  for (let i = 0; i < n; i++) {
    const kind = i === 1 ? 'checkbox' : 'radio';
    form += `<fieldset${cls ? ' class="q-card"' : ''}><legend>질문 ${i}</legend>` +
      `<label><input type="${kind}" name="q${i}" value="a"><strong>A 옵션</strong> 긴 설명이 붙는다</label>` +
      `<label><input type="${kind}" name="q${i}" value="b"><strong>B 옵션</strong> 다른 설명</label>` +
      `<label><input type="${kind}" name="q${i}" value="other">기타 (직접 입력)` +
      `<input type="text" class="q-other"></label></fieldset>`;
  }
  return new JSDOM(`<!doctype html><body><p>본문</p>${SNIP.replace('__FORM__', form)}</body>`,
    { runScripts: 'dangerously' }).window;
}
const fire = (el, t) => el.dispatchEvent(new el.ownerDocument.defaultView.Event(t, { bubbles: true }));
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', { bubbles: true }));

let w = build(3, true);
let s = [...w.document.querySelectorAll('.fpm-ask-body fieldset')];
ck('legend 가 토글로 승격', s.every(f => f.querySelector('legend').classList.contains('fpm-q-tog')));
ck('caret·요약 자리 삽입', s.every(f => f.querySelector('.fpm-q-caret') && f.querySelector('.fpm-q-pick')));

let r = s[0].querySelector('input[value=a]'); r.checked = true; fire(r, 'change');
ck('radio 선택 시 접힘', s[0].classList.contains('fpm-q-done'));
ck('요약은 라벨만 (설명 제외)', s[0].querySelector('.fpm-q-pick').textContent === 'A 옵션');
ck('다른 카드는 그대로', !s[1].classList.contains('fpm-q-done'));

let c = s[1].querySelector('input[value=a]'); c.checked = true; fire(c, 'change');
ck('checkbox 는 자동 접기 안 함', !s[1].classList.contains('fpm-q-done'));
let c2 = s[1].querySelector('input[value=b]'); c2.checked = true; fire(c2, 'change');
ck('checkbox 다중 요약', s[1].querySelector('.fpm-q-pick').textContent === 'A 옵션 · B 옵션');

let o = s[2].querySelector('input[value=other]'); o.checked = true; fire(o, 'change');
ck("'기타' 선택은 접지 않음", !s[2].classList.contains('fpm-q-done'));
let t = s[2].querySelector('.q-other'); t.value = '직접 쓴 답'; fire(t, 'input');
ck('자유입력이 요약에 반영', s[2].querySelector('.fpm-q-pick').textContent.includes('직접 쓴 답'));

let lg = s[1].querySelector('legend');
click(w, lg); ck('legend 클릭으로 접힘', s[1].classList.contains('fpm-q-done'));
click(w, lg); ck('legend 재클릭으로 펼침', !s[1].classList.contains('fpm-q-done'));

let w1 = build(1, true);
let s1 = w1.document.querySelector('.fpm-ask-body fieldset');
let r1 = s1.querySelector('input[value=a]'); r1.checked = true; fire(r1, 'change');
ck('카드 1개면 자동 접기 안 함', !s1.classList.contains('fpm-q-done'));
click(w1, s1.querySelector('legend'));
ck('카드 1개도 수동 토글은 됨', s1.classList.contains('fpm-q-done'));

// 폼 HTML 은 Claude 생성이라 class 가 어긋날 수 있다 — legend 만 있으면 붙어야 한다.
let w2 = build(2, false);
let s2 = [...w2.document.querySelectorAll('.fpm-ask-body fieldset')];
let r2 = s2[0].querySelector('input[value=a]'); r2.checked = true; fire(r2, 'change');
ck('q-card class 없어도 동작', s2[0].classList.contains('fpm-q-done'));

console.log(JSON.stringify(out));
"""


def _node_env():
    """jsdom 을 찾을 수 있는 NODE_PATH 를 만든다 — 전역 설치 위치가 일정하지 않다."""
    node = shutil.which("node")
    if not node:
        return None
    try:
        root = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True,
                              timeout=20).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        root = ""
    cands = [p for p in (root, os.path.join(os.getcwd(), "node_modules")) if p]
    # 전역 패키지가 자기 node_modules 안에 끼고 있는 경우까지 훑는다(1단계만).
    if root and os.path.isdir(root):
        for name in os.listdir(root):
            nm = os.path.join(root, name, "node_modules")
            if os.path.isdir(os.path.join(nm, "jsdom")):
                cands.append(nm)
    env = dict(os.environ, NODE_PATH=os.pathsep.join(cands))
    probe = subprocess.run([node, "-e", "require('jsdom')"], env=env,
                           capture_output=True, timeout=60)
    return (node, env) if probe.returncode == 0 else None


_ne = _node_env()
if not _ne:
    skip("DOM 동작 검사", "node+jsdom 미보유 (계약 검사만 수행)")
else:
    node, env = _ne
    with tempfile.TemporaryDirectory() as td:
        js, snip = os.path.join(td, "t.js"), os.path.join(td, "snip.html")
        with open(js, "w", encoding="utf-8") as f:
            f.write(JS_TEST)
        with open(snip, "w", encoding="utf-8") as f:
            f.write(SNIP)
        p = subprocess.run([node, js, snip], env=env, capture_output=True,
                           text=True, timeout=120)
    if p.returncode != 0:
        check("jsdom 실행", False)
        print("   " + (p.stderr or "").strip()[:400])
    else:
        for name, ok in json.loads(p.stdout.strip().splitlines()[-1]):
            check(name, ok)

print(f"\n결과: PASS {PASS} / FAIL {FAIL} / SKIP {SKIP}")
sys.exit(1 if FAIL else 0)
