#!/usr/bin/env python3
# test_fbot_map_issue402.py — Issue402 회귀 테스트 (핀봇 조직도)
#
# ⚠️ 글로벌 SCAR 아님 (___pm 프로젝트 소유). server.py 의 조직도 데이터 수집기
#   (_fbot_root_map / _fbot_dispatch_edges / _fbot_org_data / _fbot_map_mermaid /
#    _render_fbot_map / _fbot_roster)와 홈 섹션 그룹 렌더(JS)를 검증한다.
#
# 이 테스트의 핵심 명제는 하나다 — **엣지는 2원천 합성이어야 한다.**
#   배분 원장(job.kind='fbot_dispatch')만으로 그리면 `fpm-do` 직접 위임이 원장을 거치지
#   않아(prj3#Issue438 ④) 중역핀봇 밑이 텅 빈다. 실측(2026-08-27) 배분 엣지 9건이 전부
#   작업핀봇 소유였고 중역핀봇의 배분 엣지는 0건이었다. 한쪽 원천만 쓰는 회귀가 나면
#   화면은 "봇이 없다" 처럼 보이고 아무도 그것을 버그로 인지하지 못한다 → 박제한다.
#
# 실행: python3 services/hub/test_fbot_map_issue402.py
"""핀봇 조직도(Issue402) 단위 테스트."""
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server  # noqa: E402

PASS = 0
FAIL = 0
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok   {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}")


SCHEMA = """CREATE TABLE bot(
  bot_id TEXT PRIMARY KEY, title TEXT, role TEXT NOT NULL, state TEXT NOT NULL,
  career TEXT NOT NULL, icon TEXT, color TEXT, prj INT, current_task TEXT,
  parent_bot_id TEXT, lease_expires INT, created_at INT NOT NULL) STRICT;
CREATE TABLE job(
  id TEXT PRIMARY KEY, store TEXT, kind TEXT, status TEXT,
  payload TEXT, result TEXT, attempts INT,
  owner TEXT, lease_until INT, blocked_since INT, created_at INT) STRICT;"""

ICON_SVG = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 8 8"><circle r="4"/></svg>'


def build_fixture(tmp):
    """실측 조직을 축약한 픽스처.

    R1(중역) — 배분 원장 **0건**이지만 채용으로 하위 3층을 가진다(핵심 함정 재현).
    R2(작업) — 배분 원장을 독점하고 명부에 없는 대상(고아)에게도 배분한 적이 있다.
    B1       — 부모가 레지스트리에 없다(끊긴 채용 사슬) → 자기 자신이 루트.
    X1·X2    — 서로를 부모로 가리키는 오염 데이터 → 무한 루프 금지 확인용.
    """
    aoa = os.path.join(tmp, "aoa")
    os.makedirs(aoa)
    icons = os.path.join(tmp, "root", "data", "fbot", "icons")
    os.makedirs(icons)
    with open(os.path.join(icons, "exec.svg"), "wb") as f:
        f.write(ICON_SVG)
    now = int(time.time())
    con = sqlite3.connect(os.path.join(aoa, "registry.db"))
    con.executescript(SCHEMA)
    con.executemany(
        "INSERT INTO bot VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            # bot_id, title, role, state, career, icon, color, prj, task, parent, lease, created
            ("R1", "나래", "exec", "working", "probation",
             "data/fbot/icons/exec.svg", "#964E9B", 1, "조직도 구현", None, now + 600, now),
            ("R2", "작업핀봇", "taskmgr", "checkout", "active", None, "#558675", None, "", None, None, now),
            ("C1", "설계핀봇", "architect", "checkout", "probation", None, "#B4857D", None, "", "R1", None, now),
            ("C2", "리서치핀봇", "research", "checkin", "probation", None, "", None, "", "R1", now + 600, now),
            ("G1", "손자봇", "qa", "checkout", "probation", None, "", None, "", "C1", None, now),
            ("W1", "워커1", "qa", "checkout", "probation", None, "#627C9E", None, "", "R2", None, now),
            ("B1", "고립봇", "exec", "checkout", "probation", None, "", None, "", "ghost", None, now),
            ("X1", "순환1", "qa", "checkout", "probation", None, "", None, "", "X2", None, now),
            ("X2", "순환2", "qa", "checkout", "probation", None, "", None, "", "X1", None, now),
        ])
    con.executemany(
        "INSERT INTO job VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [
            # 배분은 전부 R2 소유 — R1 의 배분 엣지는 **0건**이다(핵심 함정).
            ("d1", "fbot", "fbot_dispatch", "done",
             json.dumps({"issue": "T-1", "role": "qa", "worker_bot_id": "W1"}),
             "", 0, "R2", None, None, now - 100),
            ("d2", "fbot", "fbot_dispatch", "cancelled",
             json.dumps({"issue": "T-2", "role": "qa", "worker_bot_id": "W1"}),
             "", 0, "R2", None, None, now - 50),
            # 명부에 없는 대상 — 무시하면 이 엣지가 조용히 사라진다.
            ("d3", "fbot", "fbot_dispatch", "done",
             json.dumps({"issue": "T-3", "worker_bot_id": "GHOSTBOT"}),
             "", 0, "R2", None, None, now - 30),
            # payload 파손·대상 부재 — 반쪽 화살표를 만들면 안 된다.
            ("d4", "fbot", "fbot_dispatch", "done", "{not json", "", 0, "R2", None, None, now),
            ("d5", "fbot", "fbot_dispatch", "done", json.dumps({"issue": "x"}),
             "", 0, "R2", None, None, now),
            # 세션은 엣지가 아니라 배지다.
            ("s1", "", "fbot_session", "done", "", "", 0, "R1", None, None, now),
            ("s2", "", "fbot_session", "done", "", "", 0, "R1", None, None, now),
            ("s3", "fbot", "fbot_session", "done", "", "", 0, "W1", None, None, now),
        ])
    con.commit()
    con.close()
    server.FBOT_AOA_DIR = aoa
    server.FBOT_ROOT = os.path.join(tmp, "root")
    return aoa


def main():
    print("== _fbot_root_map — 그룹 판정 단일원 ==")
    rm = server._fbot_root_map({"a": "", "b": "a", "c": "b", "d": "nope"})
    check("부모 없는 봇은 자기 루트", rm["a"] == "a")
    check("2대 아래도 최상위 루트로 귀속", rm["c"] == "a")
    check("부모가 레지스트리에 없으면 자기 루트(멤버 증발 금지)", rm["d"] == "d")
    cyc = server._fbot_root_map({"x": "y", "y": "x"})   # 걸리면 여기서 영구 정지한다
    check("순환 데이터에서도 종료(무한 루프 없음)", set(cyc) == {"x", "y"})
    check("순환은 자기 자신을 루트로(그룹 미소속 증발 방지)",
          cyc["x"] == "x" and cyc["y"] == "y")

    with tempfile.TemporaryDirectory() as tmp:
        build_fixture(tmp)

        print("\n== _fbot_org_data — 🔴 엣지 2원천 합성 (Issue402 핵심) ==")
        d = server._fbot_org_data()
        check("레지스트리 정상 읽기", d["error"] == "")
        ids = {n["bot_id"] for n in d["nodes"]}
        check("봇 9 + 고아 1 = 노드 10", len(d["nodes"]) == 10)
        check("루트 5그룹(R1·R2·B1·X1·X2)",
              d["roots"] == ["B1", "R1", "R2", "X1", "X2"] or
              sorted(d["roots"]) == ["B1", "R1", "R2", "X1", "X2"])

        hires = {(e["src"], e["dst"]) for e in d["hires"]}
        disp = [(e["src"], e["dst"]) for e in d["dispatch"]]
        check("채용 엣지 — 부모 실재분만", ("R1", "C1") in hires and ("C1", "G1") in hires)
        check("끊긴 부모(ghost)는 엣지를 만들지 않는다",
              not any(s == "ghost" for s, _ in hires))
        check("🔴 R1 의 배분 엣지는 0건이다(함정 재현)",
              not any(s == "R1" for s, _ in disp))
        # 여기가 본 이슈의 존재 이유 — 배분만 그리면 R1 밑이 텅 빈다.
        r1_children = {dst for src, dst in hires if src == "R1"}
        check("🔴 그럼에도 R1 하위가 채용 원천으로 보인다(2원천 합성 성립)",
              r1_children == {"C1", "C2"})
        check("배분 엣지는 payload 파손·대상 부재분을 버린다", len(disp) == 3)
        check("취소 배분도 남긴다(있었으나 무산 ≠ 없었음)",
              any(e["status"] == "cancelled" for e in d["dispatch"]))

        print("\n== 고아 노드 — 구분 표기 (Issue402 상세) ==")
        orph = [n for n in d["nodes"] if n["orphan"]]
        check("고아 1건 검출", len(orph) == 1 and orph[0]["bot_id"] == "GHOSTBOT")
        check("고아를 지우지 않아 엣지가 살아 있다", ("R2", "GHOSTBOT") in disp)
        check("고아는 배분자의 그룹에 얹힌다", orph[0]["root"] == "R2")
        check("고아는 루트 목록에 오르지 않는다", "GHOSTBOT" not in d["roots"])

        print("\n== 노드 배지 — 세션은 엣지가 아니다 ==")
        by = {n["bot_id"]: n for n in d["nodes"]}
        check("R1 세션 2건이 배지로", by["R1"]["sessions"] == 2)
        check("세션은 엣지를 만들지 않는다(자기 참조 화살표 금지)",
              not any(s == dst for s, dst in disp))
        check("개체 아이콘 인라인", by["R1"]["icon_uri"].startswith("data:image/svg+xml;base64,"))
        check("아이콘 없으면 빈 문자열(카드가 깨지지 않음)", by["C2"]["icon_uri"] == "")

        print("\n== ?root= 필터 (Issue402 ⓓ) ==")
        f = server._fbot_org_data("R1")
        fids = {n["bot_id"] for n in f["nodes"]}
        check("R1 하위 트리만", fids == {"R1", "C1", "C2", "G1"})
        check("🔴 배분 0건인 R1 그룹에도 하위 3봇이 남는다", len(fids) - 1 == 3)
        check("필터 안 채용 엣지 3건", len(f["hires"]) == 3)
        check("바깥 배분 엣지는 잘린다", f["dispatch"] == [])
        u = server._fbot_org_data("R1존재하지않음")
        check("루트 아닌 값 → 전체로 폴백 + 표식", u["unknown_root"] and len(u["nodes"]) == 10)
        nr = server._fbot_org_data("C1")
        check("루트가 아닌 봇 id 도 폴백(하위 트리 잘림 방지)", nr["unknown_root"] is True)

        print("\n== mermaid 렌더 (Issue402 ⓓⓔ) ==")
        mmd = server._fbot_map_mermaid(d)
        # LR 인 이유는 렌더러 주석 참조 — TD 는 팬아웃이 넓어 축소율이 0.5 밑으로 떨어진다
        check("flowchart LR 선언", mmd.startswith("flowchart LR"))
        check("루트별 subgraph", mmd.count("subgraph ") == 5)
        check("그룹 헤더에 소속·활성 수", "명(활성 " in mmd)
        check("채용은 실선(--- )", " --- " in mmd)
        check("배분은 화살표 + 이슈·status 라벨",
              '-->|"T-1 · done"|' in mmd)
        check("취소 배분 라벨도 남는다", '-->|"T-2 · cancelled"|' in mmd)
        check("linkStyle 3종(채용·배분·취소) 분리", mmd.count("linkStyle ") == 3)
        check("취소 엣지는 흐리게", "opacity:0.45" in mmd)
        check("개체색 재사용(새 색 체계 금지)", "fill:#964E9B" in mmd)
        check("고아는 점선으로 구분", "stroke-dasharray: 5 3" in mmd)
        check("고아 라벨이 사유를 밝힌다", "명부에 없음" in mmd)
        check("세션 배지", "⚙ 세션 2" in mmd)
        # 라벨 안전화 — 따옴표·대괄호·백틱이 그대로 나가면 노드가 통째로 사라진다.
        lab = server._fbot_mmd_label('a"b[c]`d|e<f>')
        check("라벨 안전화", all(c not in lab for c in '"[]`|<>'))
        check("노드 id 는 영숫자·언더스코어", server._fbot_mmd_id("B_", "a-b.c") == "B_a_b_c")
        check("어두운 개체색 위 글자는 흰색", server._fbot_text_on("#111111") == "#ffffff")
        check("밝은 개체색 위 글자는 검정", server._fbot_text_on("#eeeeee") == "#111111")
        check("색 없으면 검정 폴백", server._fbot_text_on("") == "#111111")

        print("\n== _render_fbot_map — 페이지 ==")
        page = server.Handler._render_fbot_map(d).decode("utf-8")
        check("canonical <header> 합성", "<header>" in page)
        check("mermaid 블록", '<pre class="mermaid">' in page)
        check("mermaid 소스는 HTML 이스케이프(브라우저 textContent 가 복원)",
              "--&gt;" in page and "&lt;br/&gt;" in page)
        check("런타임 <script> 를 저작하지 않는다(서버 표준 주입에 맡김)",
              "mermaid.min.js" not in page)
        check("명부 표 동반(다이어그램 실패해도 읽힌다)", "<h2>명부</h2>" in page)
        check("배분 원장 표 동반", "<h2>배분 원장</h2>" in page)
        check("루트 필터 칩", 'href="/fbot-map?root=R1"' in page)
        check("고아 경고 표시", "GHOSTBOT" in page and "fm-warn" in page)
        check("2원천 설명이 페이지에 있다", "채용" in page and "배분" in page)
        check("취소 행은 흐리게", "fm-cancel" in page)
        check("한글 UTF-8 인코딩 성립", "나래" in page)

        print("\n== _fbot_roster — 홈 그룹핑 payload (Issue402 ⓑ) ==")
        r = server._collect_bots()
        ros = r["bots_roster"]
        check("전원 명부(퇴근 포함)", len(ros) == 9)
        check("활성만 카드에 오른다", r["bots_active"] == 2)
        check("루트 표식", {m["bot_id"] for m in ros if m["is_root"]} >= {"R1", "R2", "B1"})
        check("아이콘은 루트만 싣는다(payload 비대 차단)",
              all(not m["icon_uri"] for m in ros if not m["is_root"]))
        check("활성 있는 그룹이 먼저", ros[0]["root"] == "R1")
        check("그룹 안에서 루트가 먼저", ros[0]["is_root"] is True)
        check("소속 판정은 _fbot_root_map 과 같다",
              {m["bot_id"] for m in ros if m["root"] == "R1"} == {"R1", "C1", "C2", "G1"})

        print("\n== 실패 경로 — 조용히 죽지 않는다 ==")
        db = os.path.join(server.FBOT_AOA_DIR, "registry.db")
        shutil.copy(db, db + ".bak")
        with open(db, "wb") as f:
            f.write(b"not a sqlite file" * 60)
        bad = server._fbot_org_data()
        check("DB 손상 → error 노출(빈 맵으로 위장 금지)", bool(bad["error"]))
        check("DB 손상 시 노드는 비어 있다", bad["nodes"] == [])
        shutil.move(db + ".bak", db)

    with tempfile.TemporaryDirectory() as tmp:
        server.FBOT_AOA_DIR = os.path.join(tmp, "nope")
        server.FBOT_ROOT = tmp
        e = server._fbot_org_data()
        check("fbot 미설치 → 오류가 아닌 빈 결과", e["error"] == "" and e["nodes"] == [])
        check("미설치 시 mermaid 는 빈 문자열", server._fbot_map_mermaid(e) == "")
        os.makedirs(os.path.join(tmp, "aoa2"))
        sqlite3.connect(os.path.join(tmp, "aoa2", "registry.db")).close()
        server.FBOT_AOA_DIR = os.path.join(tmp, "aoa2")
        e2 = server._fbot_org_data()
        check("스키마 미마이그레이션 → 오류가 아님", e2["error"] == "" and e2["nodes"] == [])

    print("\n== 홈 섹션 그룹 렌더(JS) — 서빙 소스를 node 로 실제 실행 ==")
    rc = _run_js_checks()
    if rc is None:
        print("  skip node 미설치 — JS 렌더 검증 생략")
    else:
        globals()["PASS"] += rc[0]
        globals()["FAIL"] += rc[1]

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


# ── 클라이언트 렌더 검증 ────────────────────────────────────────────────
# renderBots 는 서버가 문자열로 들고 있는 JS 라 python 단위테스트로는 닿지 않는다.
#   Issue400·401 과 같은 방식으로 **서빙되는 소스를 그대로 뽑아** node 로 실행한다.
#   재구현을 검사하면 회귀를 못 잡으므로 반드시 원문을 쓴다.
JS_FNS = ("renderBotsIdle", "renderBots", "renderBotGroups", "botChip",
          "botCard", "botDetail")

JS_SHIM = r"""
class El { constructor(id){this.id=id;this._html='';this.style={};this.textContent='';}
  set innerHTML(v){this._html=v;} get innerHTML(){return this._html;} }
const LISTEN = {};
class Grid extends El { addEventListener(type, fn){ LISTEN[type] = fn; } }
const els = { 'bots-section': new El('s'), 'bots-grid': new Grid('g'), 'bots-count': new El('c') };
const document = { getElementById: (id) => els[id] || null };
const window = { __i18n: I18N };
function escapeHtml(s){ return String(s==null?'':s).replace(/[&<>"']/g,
  c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function t(key, vars){ let v = I18N[key]; if(v===undefined) return key;
  if(vars) for(const k in vars) v = v.split('{'+k+'}').join(String(vars[k])); return v; }
function relTime(){ return '1h'; }
const openBotCards = new Set();
let BOTS_ERROR = '';
// closest 를 흉내내는 최소 노드 — 조상 체인을 명시해 실제 위임 선택자를 평가한다.
function node(sel, dataset, parent){
  return { _sel: sel, dataset: dataset || {}, parentNode: parent || null,
    classList: { _s: new Set(), add(c){this._s.add(c);}, remove(c){this._s.delete(c);},
                 contains(c){return this._s.has(c);} },
    setAttribute(){},
    closest(q){ let n = this; while(n){ if(n._sel === q) return n; n = n.parentNode; } return null; } };
}
let PASS=0, FAIL=0;
function check(n, c){ if(c){PASS++; console.log('  ok   '+n);} else {FAIL++; console.log('  FAIL '+n);} }
"""

JS_CHECKS = r"""
renderBots(P.bots, P.bots_total, P.bots_today, P.bots_roster);
let h = els['bots-grid'].innerHTML;
check('루트 그룹 전건 렌더', (h.match(/class="bot-group"/g)||[]).length === P.__groups);
check('🔴 배분 0건인 루트 밑에 하위 봇이 실제로 그려진다',
      h.includes('설계핀봇') && h.includes('리서치핀봇') && h.includes('손자봇'));
check('그룹 헤더에 소속 수·활성 수', h.includes('활성 2/4'));
check('활성 봇은 카드, 퇴근 봇은 칩',
      (h.match(/class="bot-card"/g)||[]).length === 2 &&
      // Issue405 이후 최근 퇴근 칩은 `bot-chip bot-chip-recent` 다. 이 검사가 묻는 것은
      //   "퇴근 봇이 카드가 아니라 칩인가" 이므로 강조 여부와 무관하게 총수를 센다.
      // `bot-chip-age`(강조 칩 안의 시각 span)까지 세지 않도록 경계를 명시한다.
      (h.match(/class="bot-chip["\s]/g)||[]).length === 7);
check('카운트 배지', els['bots-count'].textContent === '2/9');
check('그룹 헤더에 조직도 링크(별도 어포던스)',
      (h.match(/class="bot-map-link"/g)||[]).length === P.__groups &&
      h.includes('/fbot-map?root=R1') && h.includes('target="_blank"'));
check('카드는 여전히 아코디언 계약 보유',
      h.includes('data-bot="R1"') && h.includes('role="button"') && h.includes('tabindex="0"'));

openBotCards.add('R1');
renderBots(P.bots, P.bots_total, P.bots_today, P.bots_roster);
h = els['bots-grid'].innerHTML;
check('재렌더 후 펼침 보존 (Issue401 무회귀)',
      h.includes('bot-card open') && h.includes('aria-expanded="true"') && h.includes('class="bot-detail"'));
openBotCards.clear();

renderBots([], P.bots_total, P.bots_today, P.bots_roster);
h = els['bots-grid'].innerHTML;
check('전원 퇴근 — 유휴 요약 유지 (Issue400 무회귀)', h.includes('bot-idle'));
check('전원 퇴근에도 조직 그룹은 보인다', (h.match(/class="bot-group"/g)||[]).length === P.__groups);

renderBots(P.bots, P.bots_total, P.bots_today, []);
h = els['bots-grid'].innerHTML;
check('roster 부재(구버전 payload) → 평면 카드 폴백',
      !h.includes('bot-group') && h.includes('class="bot-card'));
renderBots([], 0, {}, P.bots_roster);
check('fbot 미설치(total 0) → 섹션 숨김', els['bots-section'].style.display === 'none');
BOTS_ERROR = 'disk I/O error';
renderBots(P.bots, P.bots_total, P.bots_today, P.bots_roster);
h = els['bots-grid'].innerHTML;
check('bots_error 경로에서 조직도도 조용히 죽지 않고 오류를 세운다',
      h.includes('bot-err') && h.includes('disk I/O error') && !h.includes('bot-group'));
BOTS_ERROR = '';

// Issue405 — 퇴근 칩의 최신성. 같은 렌더 안에 24h 이내·초과를 함께 두어 **경계가
//   갈라지는지**를 본다. 이 구분이 없어 "방금 퇴근" 과 "두 달 전 퇴근" 이 같은 칩이었다.
const NOW = Math.floor(Date.now()/1000);
//   픽스처 원장 때문에 일부 봇엔 이미 last_seen 이 있다 — 사본에서 걷어내고 두
//   건만 심어야 "경계가 가르는가" 를 단독으로 볼 수 있다.
const ros2 = P.bots_roster.map(m => { const c = Object.assign({}, m); delete c.last_seen; return c; });
const outs = ros2.filter(m => !m.active);
outs[0].last_seen = NOW - 3600;          // 1시간 전 — 최근
outs[1].last_seen = NOW - 3 * 86400;     // 3일 전 — 오래됨
renderBots(P.bots, P.bots_total, P.bots_today, ros2);
h = els['bots-grid'].innerHTML;
check('24h 이내 퇴근만 강조 칩',
      (h.match(/class="bot-chip bot-chip-recent"/g)||[]).length === 1);
check('강조 칩에 상대시각 동반', h.includes('전 퇴근') && h.includes('bot-chip-age'));
check('24h 초과분은 상대시각 없이 기존 칩',
      (h.match(/class="bot-chip"/g)||[]).length === outs.length - 1);
check('24h 초과여도 툴팁에 마지막 실행을 남긴다(정보 손실 금지)',
      h.includes('마지막 실행'));
check('last_seen 없는 퇴근 봇은 툴팁도 만들지 않는다',
      (h.match(/마지막 실행/g)||[]).length === 2);

check('루트가 명부에 없어도 그룹은 남는다(멤버 증발 금지)',
      (renderBots([], 1, {}, [{bot_id:'z', title:'유령상사', role:'exec', state:'checkout',
        state_label:'퇴근', state_emoji:'⬜', color:'', root:'z', is_root:false,
        active:false, icon_uri:''}]),
       els['bots-grid'].innerHTML.includes('유령상사')));

// 실제 이벤트 위임 — 지도 링크가 카드 아코디언을 빼앗지 않는지 (Issue402 ⓒ)
BIND_SRC;
const click = LISTEN['click'], keydown = LISTEN['keydown'];
check('click·keydown 위임 등록', typeof click === 'function' && typeof keydown === 'function');
const grid = node('#bots-grid', {}, null);
const group = node('.bot-group', {}, grid);
const ghead = node('.bot-group-head', {}, group);
const maplink = node('.bot-map-link', {}, ghead);
const card = node('.bot-card[data-bot]', { bot: 'R1' }, group);
const cname = node('.bot-name', {}, card);
openBotCards.clear();
click({ target: maplink });
check('지도 링크 클릭 → 아코디언 미동작', openBotCards.size === 0);
click({ target: ghead });
check('그룹 헤더 여백 클릭도 미동작', openBotCards.size === 0);
click({ target: cname });
check('카드 클릭 → 펼침', openBotCards.has('R1') && card.classList.contains('open'));
click({ target: cname });
check('다시 클릭 → 접힘', !openBotCards.has('R1'));
let prevented = false;
keydown({ key: ' ', target: cname, preventDefault: () => { prevented = true; } });
check('Space 로 펼침 + 스크롤 차단', openBotCards.has('R1') && prevented);
keydown({ key: 'Enter', target: maplink, preventDefault: () => { throw new Error('링크를 막지 말 것'); } });
check('지도 링크의 Enter 는 아코디언이 가로채지 않는다', openBotCards.has('R1'));

console.log('__RESULT__ ' + PASS + ' ' + FAIL);
"""


def _grab_line(src, prefix):
    """원문에서 상수 선언 한 줄을 그대로 뽑는다 (Issue405).

    shim 에 값을 복제하지 않는 이유는 함수를 원문에서 뽑는 이유와 같다 — 재구현을
    검사하면 24h 경계가 원문에서 갈려도 테스트가 통과해 버린다.
    """
    for line in src.splitlines():
        if line.strip().startswith(prefix):
            return line.strip()
    raise AssertionError(f"상수 미발견: {prefix}")


def _grab_js(src, name):
    i = src.index(f"function {name}(")
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


def _grab_iife(src, name):
    i = src.index(f"(function {name}() {{")
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
    return src[i:k + 1] + ")();"      # IIFE 즉시호출 복원


def _run_js_checks():
    if not shutil.which("node"):
        return None
    with tempfile.TemporaryDirectory() as tmp:
        build_fixture(tmp)
        payload = server._collect_bots()
        payload["__groups"] = len({m["root"] for m in payload["bots_roster"]})
        ko = json.load(open(os.path.join(REPO, "data", "locales", "ko.json"),
                            encoding="utf-8"))
        src = server.HUB_HTML
        js = ("const I18N = " + json.dumps(ko, ensure_ascii=False) + ";\n"
              + "const P = " + json.dumps(payload, ensure_ascii=False) + ";\n"
              + JS_SHIM
              + _grab_line(src, "const BOT_RECENT_SEC") + "\n"
              + "\n".join(_grab_js(src, n) for n in JS_FNS) + "\n"
              + JS_CHECKS.replace("BIND_SRC;", _grab_iife(src, "bindBotToggle")))
        path = os.path.join(tmp, "check.js")
        with open(path, "w", encoding="utf-8") as f:
            f.write(js)
        r = subprocess.run([shutil.which("node"), path],
                           capture_output=True, text=True)
        out = r.stdout.strip()
        print("\n".join(l for l in out.splitlines() if not l.startswith("__RESULT__")))
        if r.returncode != 0 or "__RESULT__" not in out:
            print("  FAIL node 실행 실패:\n" + (r.stderr or "")[:800])
            return (0, 1)
        p, f_ = out.rsplit("__RESULT__", 1)[1].split()
        return (int(p), int(f_))


if __name__ == "__main__":
    sys.exit(main())
