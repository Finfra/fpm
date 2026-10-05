#!/usr/bin/env python3
# test_bot_layout_issue560.py — Issue560 회귀 테스트 (hub 홈 핀봇 현황 배치)
#
# ⚠️ 글로벌 SCAR 아님 (___pm 프로젝트 소유).
#
# 핵심 명제 — **그룹 폭은 활성 카드 수를 따른다(열 수로 클램프).**
#   Issue547 이후 조직 그룹 하나가 `.grid` 한 칸이었다. 활성 10 인 `claude 팀장핀봇` 그룹은
#   카드 10장이 한 열로 내려가고, 활성 1 인 나래·pm 그룹 열은 카드 1장 아래가 통째로 비었다
#   (2026-09-28 사용자 스크린샷). 그룹이 `span min(k, C)` 를 차지하고 그 안의 카드가 같은 열
#   폭으로 가로 배치되면 10장은 3열×4행, 작은 그룹은 남는 칸을 메운다(dense).
#
# 판정은 서빙되는 JS 원문을 뽑아 node 로 실행한다 — 재구현을 검사하면 회귀를 못 잡는다
#   (Issue400·401·402 와 같은 방식).
#
# 실행: python3 services/hub/test_bot_layout_issue560.py
"""hub 핀봇 현황 배치(Issue560) 단위 테스트."""
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS = 0
FAIL = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok   {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}")


def _grab_line(src, prefix):
    for line in src.splitlines():
        if line.strip().startswith(prefix):
            return line.strip()
    raise AssertionError(f"상수 미발견: {prefix}")


def _grab_block(src, head):
    i = src.index(head)
    j = src.index("{", i)
    depth, k = 0, j
    while True:
        c = src[k]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                break
        k += 1
    return src[i:k + 1]


def _grab_js(src, name):
    return _grab_block(src, f"function {name}(")


JS_FNS = ("renderBotsIdle", "renderBots", "botGroupMapHref", "renderBotGroups", "botChip",
          "botCard", "botDetail", "botNameLink", "botGridCols", "fitBotGroups")

# 최소 DOM — getComputedStyle 이 돌려줄 트랙 문자열(TPL)과, innerHTML 에서 그룹을 읽어
#   querySelectorAll('.bot-group') 로 내주는 grid 만 흉내낸다.
JS_SHIM = r"""
let TPL = '360px 360px 360px';
const GROUPS = [];
function mkGroup(cards){
  const props = {};
  return { dataset: { cards: String(cards) },
    style: { gridColumn: '', setProperty(k, v){ props[k] = String(v); }, getPropertyValue(k){ return props[k] || ''; } } };
}
class El { constructor(id){this.id=id;this._html='';this.style={};this.textContent='';}
  set innerHTML(v){this._html=v; GROUPS.length = 0;
    (v.match(/class="bot-group" [^>]*data-cards="(\d+)"/g) || []).forEach(m => {
      GROUPS.push(mkGroup(Number(m.match(/data-cards="(\d+)"/)[1]))); }); }
  get innerHTML(){return this._html;}
  querySelectorAll(q){ return q === '.bot-group' ? GROUPS.slice() : []; } }
const els = { 'bots-section': new El('s'), 'bots-grid': new El('g'), 'bots-count': new El('c') };
const document = { getElementById: (id) => els[id] || null };
const window = { __i18n: I18N, getComputedStyle: () => ({ gridTemplateColumns: TPL }) };
const getComputedStyle = window.getComputedStyle;
function escapeHtml(s){ return String(s==null?'':s).replace(/[&<>"']/g,
  c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function t(key, vars){ let v = I18N[key]; if(v===undefined) return key;
  if(vars) for(const k in vars) v = v.split('{'+k+'}').join(String(vars[k])); return v; }
function relTime(){ return '1h'; }
const openBotCards = new Set();
let BOTS_ERROR = '';
let PASS=0, FAIL=0;
function check(n, c){ if(c){PASS++; console.log('  ok   '+n);} else {FAIL++; console.log('  FAIL '+n);} }

// 스크린샷 재현 — claude 팀장 그룹 활성 10, 나래(본사) 활성 1, pm 팀장 그룹 활성 1
function bot(id, group, head, title){
  return { bot_id: id, title: title || id, role: head ? 'lead' : 'advisor', state: 'working',
    state_label: '작업중', state_emoji: '🟢', career: 'active', color: '', icon_uri: '',
    group: group, group_head: !!head, root: 'fbot-chief', is_root: false, active: true,
    prj: 3, current_task: '', lease_stale: false, lease_expires: null, parent_bot_id: '',
    parent_title: '', session_id: '', tmux_target: '' };
}
const roster = [];
for (let i = 0; i < 10; i++) roster.push(bot('c' + i, 'prj3', i === 0, i === 0 ? 'claude 팀장핀봇' : 'w' + i));
roster.push(bot('chief', 'hq', true, '나래(총괄핀봇)'));
roster.push(bot('pm', 'prj1', true, 'pm 팀장핀봇'));
const bots = roster.slice();
"""

JS_CHECKS = r"""
// 1) 그룹 마크업 — 활성 카드 수를 싣고, 카드는 그룹 안 내부 grid 로 묶인다
renderBots(bots, 30, {}, roster);
let h = els['bots-grid'].innerHTML;
check('그룹에 활성 카드 수(data-cards) 표기',
      h.includes('data-cards="10"') && (h.match(/data-cards="1"/g) || []).length === 2);
check('카드는 그룹 안 .bot-group-cards 로 묶인다',
      (h.match(/class="bot-group-cards"/g) || []).length === 3);
check('카드 수 불변(10+1+1)', (h.match(/class="bot-card"/g) || []).length === 12);

// 2) 렌더 직후 폭 맞춤 — 3열이면 10장 그룹은 3칸, 1장 그룹은 1칸
check('renderBots 가 렌더 직후 폭을 맞춘다(10장 → span 3)',
      GROUPS[0].style.gridColumn === 'span 3' && GROUPS[0].style.getPropertyValue('--bot-cols') === '3');
check('1장 그룹은 1칸', GROUPS[1].style.gridColumn === 'span 1' && GROUPS[2].style.gridColumn === 'span 1');

// 3) 열 수로 클램프 — 좁은 화면(1열)이면 전부 1칸, 4열이면 10장 그룹은 4칸
TPL = '360px';
fitBotGroups(els['bots-grid']);
check('1열이면 전부 span 1(암시 열 생성 금지)',
      GROUPS.every(g => g.style.gridColumn === 'span 1'));
TPL = '300px 300px 300px 300px';
fitBotGroups(els['bots-grid']);
check('4열이면 10장 그룹은 span 4', GROUPS[0].style.gridColumn === 'span 4'
      && GROUPS[0].style.getPropertyValue('--bot-cols') === '4');

// 4) 2장 그룹은 2칸 — 전폭으로 늘리지 않는다(빈 칸을 옆 그룹이 쓴다)
const two = [bot('a0', 'prj9', true, 'a 팀장'), bot('a1', 'prj9', false, 'a 워커'), bot('chief', 'hq', true, '나래')];
TPL = '360px 360px 360px';
renderBots(two, 5, {}, two);
check('2장 그룹은 span 2', GROUPS[0].style.gridColumn === 'span 2');

// 5) 트랙을 못 읽으면(접힌 섹션 → 선언값 repeat(...) · 미표시 none) 손대지 않는다
check('botGridCols: 해석된 px 트랙만 센다', botGridCols(els['bots-grid']) === 3);
TPL = 'repeat(auto-fill, minmax(320px, 1fr))';
check('botGridCols: 선언값(접힘)은 0', botGridCols(els['bots-grid']) === 0);
TPL = 'none';
check('botGridCols: none 은 0', botGridCols(els['bots-grid']) === 0);
GROUPS[0].style.gridColumn = 'span 2';
fitBotGroups(els['bots-grid']);
check('트랙 불명이면 기존 폭 유지', GROUPS[0].style.gridColumn === 'span 2');

console.log('__RESULT__ ' + PASS + ' ' + FAIL);
"""


def _run_js_checks(src):
    if not shutil.which("node"):
        print("  SKIP node 없음")
        return (0, 0)
    ko = json.load(open(os.path.join(REPO, "data", "locales", "ko.json"), encoding="utf-8"))
    js = ("const I18N = " + json.dumps(ko, ensure_ascii=False) + ";\n"
          + JS_SHIM
          + _grab_line(src, "const BOT_RECENT_SEC") + "\n"
          + _grab_line(src, "const BOT_CHIP_MAX") + "\n"
          + _grab_line(src, "const openBotRest") + "\n"
          + "\n".join(_grab_js(src, n) for n in JS_FNS) + "\n"
          + JS_CHECKS)
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "check.js")
        with open(path, "w", encoding="utf-8") as f:
            f.write(js)
        r = subprocess.run([shutil.which("node"), path], capture_output=True, text=True)
    out = r.stdout.strip()
    print("\n".join(l for l in out.splitlines() if not l.startswith("__RESULT__")))
    if r.returncode != 0 or "__RESULT__" not in out:
        print("  FAIL node 실행 실패:\n" + (r.stderr or "")[:800])
        return (0, 1)
    p, f_ = out.rsplit("__RESULT__", 1)[1].split()
    return (int(p), int(f_))


def main():
    global PASS, FAIL
    src = server.HUB_HTML

    print("[CSS] 바깥 grid · 그룹 내부 grid")
    check("#bots-grid 는 auto-fill(그룹 1개여도 카드 폭 일관)",
          "#bots-grid { grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));" in src)
    check("#bots-grid 는 dense 배치(작은 그룹이 빈 칸을 메운다)", "grid-auto-flow: row dense;" in src)
    check("그룹 내부 카드 grid 는 --bot-cols 열",
          ".bot-group-cards { display: grid; grid-template-columns: repeat(var(--bot-cols, 1), minmax(0, 1fr));" in src)
    check("내부 열 간격 = 바깥 .grid 간격(카드 열이 그룹 경계를 넘어 정렬)",
          "column-gap: 1.4rem;" in src
          and ".grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 1.4rem; }" in src)

    print("[JS] 리사이즈 추종")
    check("ResizeObserver 로 폭 재맞춤", "(function bindBotLayout() {" in src and "new ResizeObserver(" in src)
    check("RO 콜백은 rAF 로 미룬다(loop 경고 방지)", "requestAnimationFrame(() => fitBotGroups(grid))" in src)

    print("[JS] 원문 실행")
    p, f = _run_js_checks(src)
    PASS += p
    FAIL += f

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
