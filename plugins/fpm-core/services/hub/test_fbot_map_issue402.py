#!/usr/bin/env python3
# test_fbot_map_issue402.py — Issue402 회귀 테스트 (핀봇 조직도)
#
# ⚠️ 글로벌 SCAR 아님 (___pm 프로젝트 소유). server.py 의 조직도 데이터 수집기
#   (_fbot_root_map / _fbot_dispatch_edges / _fbot_org_data /
#    _render_fbot_map / _fbot_roster)와 홈 섹션 그룹 렌더(JS)를 검증한다.
#
# 이 테스트의 핵심 명제는 하나다 — **엣지는 2원천 합성이어야 한다.**
#   배분 원장(job.kind='fbot_dispatch')만으로 그리면 `fpm-do` 직접 위임이 원장을 거치지
#   않아(prj3#Issue438 ④) 총괄핀봇 밑이 텅 빈다. 실측(2026-08-27) 배분 엣지 9건이 전부
#   팀장핀봇 소유였고 총괄핀봇의 배분 엣지는 0건이었다. 한쪽 원천만 쓰는 회귀가 나면
#   화면은 "봇이 없다" 처럼 보이고 아무도 그것을 버그로 인지하지 못한다 → 박제한다.
#
# 실행: python3 services/hub/test_fbot_map_issue402.py
"""핀봇 조직도(Issue402) 단위 테스트."""
import json
import os
import re
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


import importlib.util as _ilu, inspect as _insp, os as _os
_op = _os.path.expanduser("~/.claude/hooks/fbot-org.py")
_org_mod = None
if _os.path.exists(_op):
    _sp = _ilu.spec_from_file_location("fbot_org_t", _op)
    _org_mod = _ilu.module_from_spec(_sp); _sp.loader.exec_module(_org_mod)
# prj3#Issue689 — 팀장 판정 SQL 이 `_lead_rows`(단일 지점)로 옮겨갔다. 생사 판정 소스는 둘을 합쳐 본다
_org_alive_src = (_insp.getsource(_org_mod.team_alive)
                  + (_insp.getsource(_org_mod._lead_rows) if hasattr(_org_mod, "_lead_rows") else "")
                  ) if _org_mod else ""


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
    with open(os.path.join(icons, "chief.svg"), "wb") as f:
        f.write(ICON_SVG)
    now = int(time.time())
    con = sqlite3.connect(os.path.join(aoa, "registry.db"))
    con.executescript(SCHEMA)
    con.executemany(
        "INSERT INTO bot VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            # bot_id, title, role, state, career, icon, color, prj, task, parent, lease, created
            ("R1", "나래", "chief", "working", "probation",
             "data/fbot/icons/chief.svg", "#964E9B", 1, "조직도 구현", None, now + 600, now),
            ("R2", "팀장핀봇", "lead", "checkout", "active", None, "#558675", None, "", None, None, now),
            ("C1", "설계핀봇", "architect", "checkout", "probation", None, "#B4857D", None, "", "R1", None, now),
            ("C2", "리서치핀봇", "research", "checkin", "probation", None, "", None, "", "R1", now + 600, now),
            ("G1", "손자봇", "qa", "checkout", "probation", None, "", None, "", "C1", None, now),
            ("W1", "워커1", "qa", "checkout", "probation", None, "#627C9E", None, "", "R2", None, now),
            ("B1", "고립봇", "chief", "checkout", "probation", None, "", None, "", "ghost", None, now),
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
        check("배분 엣지에 job id 동승(prj3#Issue502 원클릭 종결 대상)",
              {e["job_id"] for e in d["dispatch"]} == {"d1", "d2", "d3"})

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

        # prj1#Issue489 — 조직도 mermaid 렌더는 2세대 보드(Cytoscape)로 대체되어 제거됐다.
        #   `_fbot_map_mermaid`·`_fbot_mmd_*` 는 더 없다. 검증 대상은 **렌더 문자열이 아니라
        #   그 렌더가 먹던 데이터**로 내려온다 — 표기 요구(prj·아이콘·개체색·고아 구분)는
        #   여전히 유효하고, 이제 노드 필드가 그 계약을 진다.
        print("\n== 노드 표기 계약 (Issue402 ⓔ · prj3#Issue496 — 2세대 데이터 층) ==")
        by_id = {n["bot_id"]: n for n in d["nodes"]}
        check("prj 실측치가 노드에 실린다(R1=prj1)", by_id["R1"]["prj"] == 1)
        check("prj NULL 은 None 으로 구분된다(0 이나 빈칸으로 뭉개지 않는다)",
              by_id["R2"]["prj"] is None)
        check("개체 아이콘은 data URI 로 실린다",
              by_id["R1"]["icon_uri"].startswith("data:image/svg+xml;base64,"))
        check("개체 아이콘 부재 시 role 아이콘 폴백(B1)",
              by_id["B1"]["icon_uri"].startswith("data:image/svg+xml;base64,"))
        check("role 아이콘도 없으면 빈 문자열(카드가 깨지지 않는다)",
              by_id["C2"]["icon_uri"] == "")
        check("개체색이 노드에 실린다(새 색 체계 금지 — 기존 색 재사용)",
              by_id["R1"]["color"] == "#964E9B")
        check("고아는 필드로 구분된다(점선 표기의 근거)", by_id["GHOSTBOT"]["orphan"] is True)
        check("고아에는 prj 축이 없다(명부 밖)", by_id["GHOSTBOT"]["prj"] is None)
        check("세션 수가 노드에 실린다(배지의 근거 — R1 은 2세션)",
              by_id["R1"]["sessions"] == 2)
        check("어두운 개체색 위 글자는 흰색", server._fbot_text_on("#111111") == "#ffffff")
        check("밝은 개체색 위 글자는 검정", server._fbot_text_on("#eeeeee") == "#111111")
        check("색 없으면 검정 폴백", server._fbot_text_on("") == "#111111")

        print("\n== _render_fbot_map — 페이지 ==")
        # prj3#Issue488: 기본 화면은 활성만이라 퇴근 봇·종료 배분이 걸러진다.
        #   이 절은 "전부 그렸을 때" 를 검증하므로 전체+기록 보기로 렌더한다(prj1#Issue454).
        page = server.Handler._render_fbot_map(d, True, True).decode("utf-8")
        check("canonical <header> 합성", "<header>" in page)
        # prj1#Issue489 — 2세대 그래프는 Cytoscape 다. 서버는 mermaid 문자열 대신
        #   컨테이너 + 인라인 JSON(`var DATA={org:…,flow:…}`) 을 내고 그림은 클라이언트가 그린다.
        check("Cytoscape 컨테이너 2종(조직·흐름)",
              'id="fb-cy-org"' in page and 'id="fb-cy-flow"' in page)
        check("그래프 데이터가 인라인 JSON 으로 실린다", "var DATA={org:" in page)
        check("런타임 <script> 를 저작하지 않는다(서버 표준 주입에 맡김)",
              "mermaid.min.js" not in page)
        # prj3#Issue494: 명부·원장은 roster 탭으로 분리 — "표는 전수" 원칙은 그대로다.
        rpage = server.Handler._render_fbot_map(d, True, True, "roster").decode("utf-8")
        check("map 탭에는 표가 없다(관계 구조 전용)", "<h2>명부</h2>" not in page)
        check("명부 표는 roster 탭에(다이어그램 실패해도 읽힌다)", "<h2>명부</h2>" in rpage)
        check("배분 원장 표는 roster 탭에", "<h2>배분 원장</h2>" in rpage)
        # prj3#Issue488: 전체 보기에서는 칩이 `&all=1` 을 실어 나른다(칩 이동으로 표시
        #   범위가 풀리면 안 되므로). 칩의 계약은 "root 를 담은 링크" 이므로 접두로 본다.
        check("루트 필터 칩", bool(re.search(r'href="/fbot-map\?(tab=map&amp;)?root=R1', page)))   # prj3#Issue588: 기본 탭 board — map 링크는 tab=map 을 싣는다
        check("고아 경고 표시", "GHOSTBOT" in page and "fm-warn" in page)
        check("2원천 설명이 페이지에 있다", "채용" in page and "배분" in page)
        check("취소 행은 흐리게", "fm-cancel" in rpage)
        check("한글 UTF-8 인코딩 성립", "나래" in page)

        # Issue445 — 명부가 답해야 하는 두 질문: "직속 지시자는 누구인가", "이 봇은 어느
        #   Claude 세션인가". 소속(그룹=루트)만으로는 전자를 답할 수 없다 — G1 은 소속이
        #   나래(루트)지만 **지시자는 설계핀봇**이라, 이 둘이 갈리는 행으로 검사한다.
        for col in ("<th>지시자</th>", "<th>세션</th>", "<th>pane</th>"):
            check(f"명부 열 {col}", col in rpage)
        g1_row = re.search(r"<tr[^>]*>(?:(?!</tr>).)*?<code>G1</code>.*?</tr>", rpage, re.S)
        check("G1 행 존재", g1_row is not None)
        if g1_row:
            check("지시자는 루트가 아니라 **직속 부모** 호칭",
                  "설계핀봇" in g1_row.group(0))
        b1_row = re.search(r"<tr[^>]*>(?:(?!</tr>).)*?<code>B1</code>.*?</tr>", rpage, re.S)
        if b1_row:
            # 부모가 레지스트리에 없다 — 있지도 않은 호칭을 지어내면 안 된다.
            check("끊긴 부모는 지시자를 지어내지 않는다", "ghost" not in b1_row.group(0))
        check("결속 컬럼 없는 구 스키마에서도 페이지가 선다(세션 칸은 —)",
              'class="fm-sid"' not in rpage)
        check("logged status 설명이 범례에 있다", "logged" in page)

        print("\n== _fbot_roster — 홈 그룹핑 payload (Issue402 ⓑ) ==")
        r = server._collect_bots()
        ros = r["bots_roster"]
        check("전원 명부(퇴근 포함)", len(ros) == 9)
        check("활성만 카드에 오른다", r["bots_active"] == 2)
        check("루트 표식", {m["bot_id"] for m in ros if m["is_root"]} >= {"R1", "R2", "B1"})
        check("아이콘은 그룹 헤더(루트·그룹 머리)만 싣는다(payload 비대 차단)",
              all(not m["icon_uri"] for m in ros if not (m["is_root"] or m["group_head"])))
        # Issue547 — 홈 정렬·머리는 prj 조직(group) 축이다. root 는 조직도 관계 축으로 불변.
        _act_g = {m["group"] for m in ros if m["active"]}
        check("활성 있는 그룹이 먼저", ros[0]["group"] in _act_g)
        check("그룹 안에서 머리가 먼저", ros[0]["group_head"] is True)
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
        check("미설치 시 엣지도 빈 결과(그릴 것이 없다)",
              e["hires"] == [] and e["dispatch"] == [])
        os.makedirs(os.path.join(tmp, "aoa2"))
        sqlite3.connect(os.path.join(tmp, "aoa2", "registry.db")).close()
        server.FBOT_AOA_DIR = os.path.join(tmp, "aoa2")
        e2 = server._fbot_org_data()
        check("스키마 미마이그레이션 → 오류가 아님", e2["error"] == "" and e2["nodes"] == [])

    print("\n== Issue445 B — fpm-do 사후 기록(status=logged)이 조직도에 실린다 ==")
    with tempfile.TemporaryDirectory() as tmp:
        aoa = build_fixture(tmp)
        base = server._fbot_org_data()
        r1_before = [e for e in base["dispatch"] if e["src"] == "R1"]
        check("사전: 중역(R1)의 배분 엣지 0건 — 결손 재현", len(r1_before) == 0)
        con = sqlite3.connect(os.path.join(aoa, "registry.db"))
        con.execute(
            "INSERT INTO job VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("dlog", "fbot", "fbot_dispatch", "logged",
             json.dumps({"issue": "prj3#Issue777", "role": "research",
                         "worker_bot_id": "C2", "source": "fpm-do"}),
             "", 0, "R1", None, None, int(time.time())))
        con.commit()
        con.close()
        after = server._fbot_org_data()
        r1_after = [e for e in after["dispatch"] if e["src"] == "R1"]
        check("사후: 중역의 지시 이력이 조직도에 나타난다", len(r1_after) == 1)
        check("대상·이슈가 원장 그대로", r1_after and r1_after[0]["dst"] == "C2"
              and r1_after[0]["issue"] == "prj3#Issue777")
        # `logged` 는 사후 기록이라 활성(`open`)이 아니다 → 전체 보기에서 확인(prj3#Issue488)
        page2 = server.Handler._render_fbot_map(after, True, False, "roster").decode("utf-8")
        check("배분 원장 표에 사후 기록이 뜬다", "prj3#Issue777" in page2)
        # `logged` 는 취소가 아니다 — 흐리게 처리하면 "무산된 배분" 으로 오독된다.
        row = re.search(r"<tr[^>]*>(?:(?!</tr>).)*?prj3#Issue777.*?</tr>", page2, re.S)
        check("사후 기록은 취소 행으로 흐려지지 않는다",
              row is not None and "fm-cancel" not in row.group(0))
        check("조직 데이터에도 그 배분 엣지가 선다",
              any(e["src"] == "R1" for e in after["dispatch"]))

    _check_career_filter_edges()
    _check_hist_toggle()
    _check_issue535()
    _check_board_active_seg()
    _check_issue488()
    _check_issue494()
    _check_issue502()

    print("\n== 홈 섹션 그룹 렌더(JS) — 서빙 소스를 node 로 실제 실행 ==")
    rc = _run_js_checks()
    if rc is None:
        print("  skip node 미설치 — JS 렌더 검증 생략")
    else:
        globals()["PASS"] += rc[0]
        globals()["FAIL"] += rc[1]

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


# ── prj3#Issue488: 활성 필터 · 교착 검출 · 배분 흐름 ────────────────────────
# 대상 3종(`_fbot_filter_active`·`_fbot_cycles`·`_fbot_deadlocks`)은
#   dict 를 받는 순수 함수라 DB 픽스처 없이 **판정 자체**를 정밀하게 세울 수 있다.
def _n488(bid, state="checkin", orphan=False, root=None):
    return {"bot_id": bid, "title": bid, "role": "chief", "state": state,
            "state_label": server.FBOT_STATE_LABEL.get(state, state),
            "state_emoji": "🟢", "career": "", "color": "", "prj": None,
            "current_task": "", "parent": "", "root": root or bid,
            "sessions": 0, "orphan": orphan, "session_id": "", "tmux_target": "",
            "icon_uri": ""}


#   ⚠️ 픽스처의 이슈 값은 `ISS-*` 로 둔다 — `IssueN` 으로 쓰면 tagcheck(prj3#Issue325)가
#     실제 이슈 참조로 읽어 커밋을 막는다. 여기서는 원장에 실리는 **문자열 값**일 뿐이다.
def _e488(src, dst, status="open", issue="ISS-A", ago_h=0.0):
    return {"src": src, "dst": dst, "issue": issue, "role": "chief",
            "status": status, "ts": int(time.time() - ago_h * 3600)}


def _d488(nodes, dispatch, hires=None):
    return {"error": "", "nodes": nodes, "hires": hires or [], "dispatch": dispatch,
            "roots": [n["bot_id"] for n in nodes if n["root"] == n["bot_id"]],
            "root_filter": "", "unknown_root": False}


def _check_board_active_seg():
    """보드 「활성만 | 전체」 — 세그먼트 UI + 조직도 카드까지 같은 판정(seatVisible)으로 거른다.

    종전엔 단독 토글 버튼이라 현재 상태인지 누를 동작인지 안 읽혔고(그래프 탭 ea0e737 과 같은 문제),
    활성만이어도 오른쪽 조직도에는 퇴근 봇·공석 카드가 그대로 섰다(2026-09-26 사용자 관측).
    """
    print("\n== 보드 활성만·전체 세그먼트 + 조직도 카드 필터 ==")
    bh = server._fbot_board_html("", None)
    check("보드 셸 — 세그먼트(활성만|전체) 두 칸", 'id="fb-seg-all"' in bh
          and 'data-all="0"' in bh and 'data-all="1"' in bh)
    check("보드 셸 — 구 단독 토글 버튼 제거", 'id="fb-toggle-all"' not in bh)
    node = shutil.which("node")
    if not node:
        print("  skip node 미설치 — seatVisible 검증 생략")
        return
    js_src = server._FBOT_BOARD_JS
    js = (_grab_line(js_src, "const ACTIVE") + "\n" + _grab_js(js_src, "seatVisible") + "\n" + r"""
const bots={A:{state:"working"},C:{state:"checkout"},W:{state:"checkout"}};
const work=b=>b==="W"?2:0;
const r=[
  seatVisible({bot_id:"A"},bots,work,true,null)===true,
  seatVisible({bot_id:"C"},bots,work,true,null)===false,
  seatVisible({bot_id:"W"},bots,work,true,null)===true,
  seatVisible({bot_id:""},bots,work,true,null)===false,
  seatVisible({bot_id:"C"},bots,work,true,"C")===true,
  seatVisible({bot_id:"C"},bots,work,false,null)===true,
  seatVisible({bot_id:""},bots,work,false,null)===true,
];
console.log(JSON.stringify(r));
""")
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "seat.js")
        with open(p, "w", encoding="utf-8") as f:
            f.write(js)
        out = subprocess.run([node, p], capture_output=True, text=True)
    try:
        r = json.loads(out.stdout.strip().splitlines()[-1])
    except Exception:
        check("seatVisible node 실행: " + (out.stderr or "")[:200], False)
        return
    names = ["활성 봇 표시", "퇴근·일 없음 숨김", "퇴근이라도 기간 안 일 있으면 표시", "활성만이면 공석 숨김",
             "포커스 봇은 퇴근이어도 표시", "전체면 퇴근 봇 표시", "전체면 공석 표시"]
    for n, ok in zip(names, r):
        check("seatVisible — " + n, ok)

    # 트리도 스코프 단위로 거른다 — 활성만인데 20개 팀 줄이 그대로면 전체와 구성이 같아 보인다(2026-09-26 사용자 관측)
    js2 = _grab_js(js_src, "treeScopes") + "\n" + r"""
const sc=[{prj:null},{prj:1},{prj:3},{prj:7}];
const act=s=>s.prj===3;
const a=treeScopes(sc,true,act,"7"), b=treeScopes(sc,false,act,null), c=treeScopes(sc,true,act,null);
console.log(JSON.stringify([
  a.shown.map(s=>s.prj), a.hidden,
  b.shown.length, b.hidden,
  c.shown.map(s=>s.prj), c.hidden]));
"""
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "tree.js")
        with open(p, "w", encoding="utf-8") as f:
            f.write(js2)
        out = subprocess.run([node, p], capture_output=True, text=True)
    try:
        r2 = json.loads(out.stdout.strip().splitlines()[-1])
    except Exception:
        check("treeScopes node 실행: " + (out.stderr or "")[:200], False)
        return
    check("treeScopes — 활성만: 본사+활성 팀+선택 팀만, 나머지 숨김 수", r2[0] == [None, 3, 7] and r2[1] == 1)
    check("treeScopes — 전체: 전부 표시", r2[2] == 4 and r2[3] == 0)
    check("treeScopes — 활성만·선택 없음: 본사+활성 팀", r2[4] == [None, 3] and r2[5] == 2)

    # 새로고침하면 「활성만」이 「전체」로 풀리던 문제(2026-09-27 사용자 관측) — #sel= 이 있으면 ensureSelVisible 이
    #   매 로드마다 activeOnly 를 끄고, 선택값 자체는 저장되지 않았다.
    js3 = (_grab_line(js_src, "const ACTIVE") + "\n" + _grab_js(js_src, "seatVisible") + "\n"
           + _grab_js(js_src, "initActiveOnly") + "\n" + r"""
const bots={C:{state:"checkout"}}, work=()=>0;
console.log(JSON.stringify([
  seatVisible({bot_id:"C",addr:"7/x"},bots,work,true,null,"7/x"),
  seatVisible({bot_id:"",addr:"7/v"},bots,work,true,null,"7/v"),
  seatVisible({bot_id:"C",addr:"7/x"},bots,work,true,null,"7/y"),
  initActiveOnly(null,null), initActiveOnly(null,false), initActiveOnly(null,true),
  initActiveOnly("1",true), initActiveOnly("0",false)]));
""")
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "keep.js")
        with open(p, "w", encoding="utf-8") as f:
            f.write(js3)
        out = subprocess.run([node, p], capture_output=True, text=True)
    try:
        r3 = json.loads(out.stdout.strip().splitlines()[-1])
    except Exception:
        check("initActiveOnly node 실행: " + (out.stderr or "")[:200], False)
        return
    check("seatVisible — 선택 자리(퇴근 봇)는 활성만이어도 표시", r3[0] is True)
    check("seatVisible — 선택 자리(공석)도 활성만이어도 표시", r3[1] is True)
    check("seatVisible — 선택 아닌 퇴근 자리는 숨김", r3[2] is False)
    check("initActiveOnly — 해시·저장값 없으면 기본 활성만", r3[3] is True)
    check("initActiveOnly — 해시 없으면 저장된 이전 선택 복원", r3[4] is False and r3[5] is True)
    check("initActiveOnly — 해시 all= 이 저장값보다 우선", r3[6] is False and r3[7] is True)
    check("ensureSelVisible 는 activeOnly 를 강제로 끄지 않는다",
          "activeOnly" not in _grab_js(js_src, "ensureSelVisible"))

    # Issue538 — 팀장핀봇(자리) 클릭 시 그 팀 레인만. 타 prj 는 배분 왕래(협업)가 있을 때만 함께 선다.
    #   종전엔 레인 한정이 scope:/dept: 선택에만 걸려 자리·봇 선택은 전 레인으로 떨어졌다(2026-09-27 사용자 관측)
    js3 = _grab_js(js_src, "lanePick") + "\n" + r"""
const lanes=[{prj:1},{prj:3},{prj:7},{prj:57}];
const home={L1:"1",L3:"3",L7:"7",L57:"57",T3:"3",N:"hq"};
const of=b=>home[b]?new Set([home[b]]):null;
const jobs=[{owner:"L3",dst:"T3"},{owner:"N",dst:"L57"},{owner:"N",dst:"L1"}];
const k=r=>r?r.map(s=>s.prj):null;
console.log(JSON.stringify([
  k(lanePick(lanes,"57",of,jobs)),
  k(lanePick(lanes,"57",of,jobs.concat([{owner:"L7",dst:"L57"}]))),
  k(lanePick(lanes,"3",of,jobs.concat([{owner:"L3",dst:"L1"}]))),
  k(lanePick(lanes,"hq",of,jobs)),
  k(lanePick(lanes,null,of,jobs))]));
"""
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "pick.js")
        with open(p, "w", encoding="utf-8") as f:
            f.write(js3)
        out = subprocess.run([node, p], capture_output=True, text=True)
    try:
        r3 = json.loads(out.stdout.strip().splitlines()[-1])
    except Exception:
        check("lanePick node 실행: " + (out.stderr or "")[:200], False)
        return
    check("lanePick — 협업 없으면 선택 팀 레인만(본사 경유 배분은 협업 아님)", r3[0] == [57])
    check("lanePick — 배분 왕래한 타 prj 레인은 함께", r3[1] == [7, 57])
    check("lanePick — 반대 방향 배분도 협업", r3[2] == [1, 3])
    check("lanePick — 본사 선택은 한정 없음(null)", r3[3] is None)
    check("lanePick — 선택 없음은 한정 없음(null)", r3[4] is None)
    check("org() — 레인 한정이 lanePick 단일 지점을 거친다", "lanePick(lanesAll" in js_src)


def _check_issue535():
    """prj1#Issue535 — 그래프 옆 패널 "보드에서 이 봇 보기" 가 개체 bot_id 를 `?root=` 에
    실으면 root_filter(루트 봇 전용)가 unknown_root 경고를 띄우고, 탭·토글이 root 를
    보존해 org 탭까지 따라간다(실측 root=fbot-contractor-issue415). 개체 지목은
    botNameLink 와 같은 `tab=board#bot=` 해시 계약이어야 한다."""
    print("\n== 그래프 패널 봇 링크 — 개체 지목은 #bot= (Issue535) ==")
    d = _d488([_n488("BOSS")], [])
    page = server.Handler._render_fbot_map(d, True, True, "map").decode("utf-8")
    check("패널 링크가 개체 id 를 root= 에 싣지 않는다",
          "tab=board&root='+encodeURIComponent(d.bot)" not in page)
    check("패널 링크가 tab=board#bot= 해시로 봇을 지목한다",
          "/fbot-map?tab=board#bot='+encodeURIComponent(d.bot)" in page)


def _check_career_filter_edges():
    """전체 보기(?all=1) 빈 화면 회귀 — 퇴역 필터가 노드만 거르고 엣지를 남기면
    Cytoscape 가 `nonexistant target` 예외로 그래프 전체를 그리지 않는다(사용자 관측
    2026-09-26: 활성만은 그려지고 전체는 빈 화면이라 토글이 뒤바뀐 것처럼 보였다)."""
    print("\n== 전체 보기: 퇴역 필터 후 엣지 끝점이 전부 노드에 있다 ==")
    boss = _n488("BOSS")
    gone = dict(_n488("LEAVE", state="checkout", root="BOSS"), career="leave")
    d = _d488([boss, gone], [_e488("BOSS", "LEAVE", status="done", ago_h=200)],
              hires=[{"src": "BOSS", "dst": "LEAVE"}])
    out = server._fbot_filter_career(d)
    ids = {n["bot_id"] for n in out["nodes"]}
    check("퇴역 봇은 노드에서 빠진다", "LEAVE" not in ids)
    check("채용 엣지 끝점이 전부 노드에 있다",
          all(e["src"] in ids and e["dst"] in ids for e in out["hires"]))
    check("배분 엣지 끝점이 전부 노드에 있다",
          all(e["src"] in ids and e["dst"] in ids for e in out["dispatch"]))
    els = server._fbot_graph_elements(out)
    nids = {n["data"]["id"] for n in els["nodes"]}
    check("Cytoscape 엣지가 없는 노드를 가리키지 않는다",
          all(e["data"]["source"] in nids and e["data"]["target"] in nids for e in els["edges"]))


def _check_hist_toggle():
    """«기록 포함»(?hist=1) 무반응 회귀 — 활성·퇴역 필터가 hist 와 무관하게 오래된 종결
    배분을 먼저 떨궈, 뒤의 hist 분기에 넘어올 엣지가 없었다(사용자 관측 2026-09-26:
    라벨만 바뀌고 «숨긴 배분 87» 그대로). 두 필터 모두 hist 축을 받아야 한다."""
    print("\n== 기록 포함(?hist=1): 오래된 종결 배분이 실제로 드러난다 ==")
    boss = _n488("BOSS")
    w = _n488("W", state="checkout", root="BOSS")
    gone = dict(_n488("LEAVE", state="checkout", root="BOSS"), career="leave")
    old = [_e488("BOSS", "W", status="done", ago_h=200),
           _e488("BOSS", "LEAVE", status="cancelled", ago_h=300)]
    d = _d488([boss, w, gone], old)
    base = server._fbot_filter_active(d)
    check("기본(활성만): 오래된 종결 배분은 숨는다", base["dispatch"] == [])
    act = server._fbot_filter_active(d, hist=True)
    ids = {n["bot_id"] for n in act["nodes"]}
    check("활성만+기록: 종결 배분 2건이 남는다", len(act["dispatch"]) == 2)
    check("활성만+기록: 배분 끝점이 전부 노드에 있다",
          all(e["src"] in ids and e["dst"] in ids for e in act["dispatch"]))
    car = server._fbot_filter_career(d, hist=True)
    cids = {n["bot_id"] for n in car["nodes"]}
    check("전체+기록: 종결 배분 2건이 남는다", len(car["dispatch"]) == 2)
    check("전체+기록: 배분 끝점이 전부 노드에 있다",
          all(e["src"] in cids and e["dst"] in cids for e in car["dispatch"]))
    for a in (False, True):
        pg = server.Handler._render_fbot_map(d, a, True, "map").decode("utf-8")
        check("페이지(all=%d&hist=1): 숨긴 배분 계수가 0" % a, not re.search(r"·배분 [1-9]", pg))
    pg0 = server.Handler._render_fbot_map(d, False, False, "map").decode("utf-8")
    check("페이지(기본): 숨긴 배분 2 가 표시된다", "배분 2" in pg0)


def _check_issue488():
    print("\n== prj3#Issue488 ⓒ 교착 검출 3종 ==")
    # ① 유실 배분 — 받은 쪽이 퇴근했다. 실측 재현(prj3#Issue334 를 맡은
    #   `fbot-igmaker-issue334` 가 open 1.9시간 시점에 이미 checkout 이었다).
    d = _d488([_n488("MGR"), _n488("W1", state="checkout", root="MGR")],
              [_e488("MGR", "W1", issue="ISS-334", ago_h=1.9)])
    dl = server._fbot_deadlocks(d)
    check("퇴근한 대상에게 걸린 open 은 유실 배분", len(dl["orphaned"]) == 1)
    check("유실 사유를 사람 말로 적는다", dl["orphaned"][0]["why"] == "대상이 퇴근함")
    check("1.9h 는 임계(6h) 미만이라 정체로 세지 않는다", dl["stale"] == [])

    # 명부에 아예 없는 대상(고아)도 유실이다 — 수행 주체가 없다는 점에서 같다.
    d = _d488([_n488("MGR"), _n488("GHOST", orphan=True, root="MGR")],
              [_e488("MGR", "GHOST")])
    check("명부에 없는 대상도 유실 배분",
          server._fbot_deadlocks(d)["orphaned"][0]["why"] == "명부에 없음")

    # 정상 — 받은 봇이 살아 있고 오래되지도 않았다. 여기서 오탐이 나면 배너가 늘 켜진다.
    d = _d488([_n488("MGR"), _n488("W1", root="MGR")], [_e488("MGR", "W1")])
    check("살아있는 대상의 최근 open 은 교착 아님",
          server._fbot_deadlocks(d)["count"] == 0)

    # ③ 정체 — 살아 있지만 임계를 넘겼다.
    d = _d488([_n488("MGR"), _n488("W1", root="MGR")], [_e488("MGR", "W1", ago_h=7)])
    dl = server._fbot_deadlocks(d)
    check("임계 초과 open 은 정체", len(dl["stale"]) == 1 and dl["orphaned"] == [])
    check("정체는 경과 시간을 함께 싣는다", dl["stale"][0]["hours"] > 6)

    # 유실이면서 오래된 건 — 같은 사실을 두 번 세지 않는다.
    d = _d488([_n488("MGR"), _n488("W1", state="checkout", root="MGR")],
              [_e488("MGR", "W1", ago_h=9)])
    dl = server._fbot_deadlocks(d)
    check("유실은 정체로 중복 계상하지 않는다",
          len(dl["orphaned"]) == 1 and dl["stale"] == [] and dl["count"] == 1)

    # 끝난 기록은 판정 대상이 아니다 — 기다리는 주체가 없다.
    d = _d488([_n488("MGR"), _n488("W1", state="checkout", root="MGR")],
              [_e488("MGR", "W1", status="done", ago_h=99),
               _e488("MGR", "W1", status="cancelled", ago_h=99),
               _e488("MGR", "W1", status="logged", ago_h=99)])
    check("done·cancelled·logged 는 교착으로 세지 않는다",
          server._fbot_deadlocks(d)["count"] == 0)

    # ② 순환 — 서로를 기다린다. 지금 실데이터엔 없지만 다단계 위임이 쌓이면 생긴다.
    d = _d488([_n488("A"), _n488("B", root="A")],
              [_e488("A", "B", issue="I1"), _e488("B", "A", issue="I2")])
    dl = server._fbot_deadlocks(d)
    check("A→B→A 는 순환 대기", len(dl["cycles"]) == 1)
    check("순환 경로는 시작으로 되돌아온다", dl["cycles"][0][0] == dl["cycles"][0][-1])
    check("자기 자신에게 건 배분도 순환",
          len(server._fbot_cycles([_e488("A", "A")])) == 1)
    check("같은 고리를 회전만 바꿔 두 번 세지 않음",
          len(server._fbot_cycles([_e488("A", "B"), _e488("B", "A"),
                                   _e488("B", "A", issue="dup")])) == 1)
    check("사이클 없는 스타 구조는 0건",
          server._fbot_cycles([_e488("M", "X"), _e488("M", "Y")]) == [])

    print("\n== prj3#Issue488 ⓐ 활성 필터 — 데이터가 아니라 화면만 거른다 ==")
    nodes = [_n488("MGR"), _n488("LIVE", root="MGR"),
             _n488("GONE", state="checkout", root="MGR"),
             _n488("BUSY", state="checkout", root="MGR")]
    disp = [_e488("MGR", "BUSY", issue="OPEN1", ago_h=1), # 열린 배분 — 대상은 퇴근. ago_h=1: 스폰 유예(Issue573, 10분) 밖
            # prj3#Issue556 — 종결 배분은 **오래된 것만** 빠진다(3일 창). ago_h=96 = 4일 전
            _e488("MGR", "GONE", status="done", issue="OLD1", ago_h=96)]
    d = _d488(nodes, disp)
    v = server._fbot_filter_active(d)
    ids = {n["bot_id"] for n in v["nodes"]}
    check("퇴근 봇은 기본 화면에서 빠진다", "GONE" not in ids)
    check("활성 봇은 남는다", "LIVE" in ids and "MGR" in ids)
    check("열린 배분의 대상은 퇴근했어도 남는다(교착을 가리키므로)", "BUSY" in ids)
    check("종료된 배분은 화면에서 빠진다",
          [e["issue"] for e in v["dispatch"]] == ["OPEN1"])
    # prj3#Issue556 — 최근(3일) 종결 배분은 양끝이 퇴근했어도 남는다. 완료 사인(✓)이
    #   붙는 순간 그림에서 빠지면 "중역에게 시킨 일이 어떻게 전파됐나" 를 볼 수 없다
    #   (2026-09-06 실측: 체인 완주 직후 전원 퇴근 → mermaid 0개).
    v2 = server._fbot_filter_active(_d488(nodes, disp + [
        _e488("MGR", "GONE", status="done", issue="NEW1", ago_h=1)]))
    ids2 = {n["bot_id"] for n in v2["nodes"]}
    check("최근 종결 배분의 퇴근 대상은 남는다(Issue556)", "GONE" in ids2)
    check("최근 종결 배분 엣지가 기본 화면에 남는다(Issue556)",
          sorted(e["issue"] for e in v2["dispatch"]) == ["NEW1", "OPEN1"])
    check("원본 data 는 손대지 않는다(표시 계층 필터)",
          len(d["nodes"]) == 4 and len(d["dispatch"]) == 2)
    check("칩 목록(roots)은 거르지 않는다", v["roots"] == d["roots"])

    # prj1#Issue489 — 흐름 그래프도 2세대에서 서버 mermaid 문자열을 만들지 않는다.
    #   교착 판정(`_fbot_deadlocks`)은 그대로 서버 몫이고, 그리는 것은 클라이언트다.
    print("\n== prj3#Issue488 ⓑ 배분 흐름 — 교착 판정(데이터 층) ==")
    dl = server._fbot_deadlocks(d)
    check("교착 판정이 선다(그림의 근거)", isinstance(dl, dict) and "cycles" in dl)
    check("배분 엣지에 이슈가 실린다", any(e["issue"] == "OPEN1" for e in d["dispatch"]))
    check("배분이 없으면 교착도 없다",
          not any(server._fbot_deadlocks(_d488([], [])).get(k)
                  for k in ("cycles", "orphaned", "stale")))

    print("\n== prj3#Issue488 — 페이지 통합 ==")
    page = server.Handler._render_fbot_map(d).decode("utf-8")
    # ⚠️ `fm-dead` 는 <style> 의 클래스 정의에도 있어 문자열 존재만 보면 **항상 참**이다
    #   (실측: 배너 없는 페이지도 통과했다). 실제 사용처인 여는 태그로 본다.
    _BANNER = '<div class="fm-dead">'
    _SOFT = '<div class="fm-warn fm-open">'
    # prj3#Issue502: 퇴근 대상 유실은 ⛔ 가 아니라 ⏳ 미종결 원장(회수 안내 톤)으로 선다.
    check("기본 화면에 미종결 배너가 선다(퇴근 대상은 ⏳)",
          _SOFT in page and "미종결" in page)
    check("퇴근 대상 유실은 붉은 교착 배너가 아니다", _BANNER not in page)
    check("유실 배분 사유가 배너에 적힌다", "대상이 퇴근함" in page)
    check("전체 보기 토글 링크", bool(re.search(r'href="/fbot-map\?(tab=map&amp;)?all=1"', page)))
    check("배분 흐름 섹션", "<h2>배분 흐름</h2>" in page)
    # prj1#Issue451: 명부는 **항상 전수**다(퇴역 보존처) — "활성만" 은 그래프에만 적용된다.
    #   그래서 페이지 전체 부재가 아니라 **그래프 데이터** 부재 + 명부 행 존재를 본다.
    _mm = page[page.index("var DATA={org:"):]
    check("기본은 활성만 — 그래프에 퇴근 봇 없음", "GONE" not in _mm)
    # prj3#Issue494: 명부는 roster 탭 — 전수 보존 검증도 그 탭에서.
    _rp = server.Handler._render_fbot_map(d, False, False, "roster").decode("utf-8")
    check("퇴근 봇도 명부에는 남는다(전수 보존)", ">GONE<" in _rp)
    page_all = server.Handler._render_fbot_map(d, True).decode("utf-8")
    check("전체 보기에서 퇴근 봇이 돌아온다", "B_GONE" in page_all)
    check("전체 보기 토글은 활성으로 되돌린다", bool(re.search(r'href="/fbot-map(\?tab=map)?"', page_all)))
    # 표시 토글은 «현재 상태 라벨 + 반대 방향 버튼» 을 나란히 두면 반대로 읽힌다(사용자 관측
    #   2026-09-26: "표시 전체 · ← 활성만 보기"). 세그먼트로 두고 **현재 칸만 on·비링크**로 그린다.
    check("기본 화면: 표시 세그먼트의 현재 칸은 활성만",
          '<span class="fm-seg-on">활성만</span>' in page)
    check("전체 화면: 표시 세그먼트의 현재 칸은 전체",
          '<span class="fm-seg-on">전체</span>' in page_all)
    check("전체 화면에 «← 활성만 보기» 버튼 문구가 없다", "활성만 보기" not in page_all)
    _healthy = server.Handler._render_fbot_map(
        _d488([_n488("M"), _n488("W", root="M")],
              [_e488("M", "W")])).decode("utf-8")
    check("교착이 없으면 배너도 없다(⛔·⏳ 양쪽)",
          _BANNER not in _healthy and _SOFT not in _healthy)

    print("\n== prj3#Issue578·575 — JSON v2 정규화(jobs·timeline·events) ==")
    _nb2 = [_n488("EXEC", state="working"), _n488("PM", state="checkout", root="EXEC")]
    _e_v = dict(_e488("EXEC", "PM", issue="V1"), job_id="fbotdisp-v-11111111", ts=int(time.time())-100)
    _xj = [
        {"id":"fbotreq-1","kind":"fbot_request","status":"open","owner":"EXEC","created_at":int(time.time())-50,
         "payload":json.dumps({"from":"HR","body":"검토 요청","corr_id":"fbotreq-1"})},
        {"id":"fbotjob-1","kind":"fbot_session","status":"done","owner":"PM","created_at":int(time.time())-80,
         "payload":json.dumps({"cwd":"/x","session_id":"abcd1234","current_task":"작업 X"})},
        {"id":"fbotev-1","kind":"fbot_event","status":"done","owner":"EXEC","created_at":int(time.time())-10,
         "payload":json.dumps({"type":"state:working","detail":"checkin arrow working","ref":""})},
    ]
    _pl2 = server._fbot_board_payload(_d488(_nb2, [_e_v]), {"available":True,"seats":[]}, extra_jobs=_xj)
    check("jobs 통합 — dispatch+request+session+event", set(j["kind"] for j in _pl2["jobs"].values()) == {"dispatch","request","session","event"})
    check("timeline 은 봇별 job id 역순", bool(_pl2["timeline"].get("EXEC")) and _pl2["jobs"][_pl2["timeline"]["EXEC"][0]]["ts"] >= _pl2["jobs"][_pl2["timeline"]["EXEC"][-1]]["ts"])
    check("events 는 fbot_event 만·시간 역순", [e["type"] for e in _pl2["events"]] == ["state:working"])
    check("요약 events_24h 계상", _pl2["summary"]["events_24h"] == 1)
    check("1세대 키(dispatch·scopes·bots) 유지", all(k in _pl2 for k in ("dispatch","scopes","bots")))
    _bh2 = server._fbot_board_html("", None)
    check("보드 셸 2세대 — 모드 토글·스트림·SSE·요청 폼 훅", all(x in _bh2 for x in ('id="fb-mode-task"','id="fb-stream-body"','EventSource','__fbToken')))

    print("\n== prj3#Issue573 — 스폰 대기 유예: 배분 직후 퇴근 대상은 미종결이 아니다 ==")
    _nsp = [_n488("EXEC", state="working"), _n488("PM", state="checkout", root="EXEC")]
    _fresh = dict(_e488("EXEC", "PM", issue="FRESH"), job_id="fbotdisp-7-fresh0000", ts=int(time.time())-20, spawned_at=int(time.time())-15)
    _stale_open = dict(_e488("EXEC", "PM", issue="OLDOPEN"), job_id="fbotdisp-8-oldopen0", ts=int(time.time())-7200)
    _dl = server._fbot_deadlocks(_d488(_nsp, [_fresh, _stale_open]))
    check("배분 15초 뒤 퇴근 대상은 spawning(유예)", [e["issue"] for e in _dl["spawning"]] == ["FRESH"])
    check("유예를 넘긴 open 배분은 종전대로 soft 미종결", [e["issue"] for e in _dl["orphaned"]] == ["OLDOPEN"] and _dl["orphaned"][0]["why"] == "대상이 퇴근함")
    check("hard 교착은 0(둘 다 명부에 있다)", _dl["hard_count"] == 0)
    _pl0 = server._fbot_board_payload(_d488(_nsp, [_fresh, _stale_open]), {"available": True, "seats": []}, dl=_dl)
    check("보드 요약 — 교착 0 · 스폰 대기 1 · 미종결 1", _pl0["summary"]["deadlocks"] == 0 and _pl0["summary"]["spawning"] == 1 and _pl0["summary"]["unsettled"] == 1)
    _pg_sp = server.Handler._render_fbot_map(_d488(_nsp, [_fresh])).decode("utf-8")
    check("배너 — 스폰 대기 안내, 원장 종결 버튼 없음", "스폰 대기" in _pg_sp and 'class="fm-close-btn"' not in _pg_sp)

    print("\n== prj3#Issue569 — 보드 페이로드(/fbot-map.json) · 보드 셸 ==")
    _nb = [_n488("EXEC", state="working"), _n488("PM", state="checkout", root="EXEC"),
           _n488("WK", state="checkout", root="EXEC")]
    _e_a = dict(_e488("EXEC", "PM", issue="A"), job_id="fbotdisp-1-aaaaaaaa", ts=int(time.time())-600)
    _e_b = dict(_e488("PM", "WK", issue="B", status="blocked"), job_id="fbotdisp-2-bbbbbbbb", ts=int(time.time())-300)
    _e_old = dict(_e488("EXEC", "WK", issue="OLD", status="done", ago_h=96), job_id="fbotdisp-3-cccccccc")
    _full = _d488(_nb, [_e_a, _e_b, _e_old])
    _org = {"available": True, "seats": [
        {"addr": "hq/hq-chief-1", "id": "hq-chief-1", "role": "chief", "dept": "hq", "dept_label": "본사", "source": "central",
         "reports_to_addr": "", "vacant": False, "occupant": "EXEC", "scope_prj": None, "scope_title": "본사"},
        {"addr": "2/ops-lead-1", "id": "ops-lead-1", "role": "lead", "dept": "ops", "dept_label": "운영부서", "source": "inherited",
         "reports_to_addr": "hq/hq-chief-1", "vacant": False, "occupant": "PM", "scope_prj": 2, "scope_title": "obsidian"},
        {"addr": "2/dev-architect-1", "id": "dev-architect-1", "role": "architect", "dept": "dev", "dept_label": "개발부서", "source": "inherited",
         "reports_to_addr": "2/ops-lead-1", "vacant": True, "occupant": "", "scope_prj": 2, "scope_title": "obsidian"}]}
    _pl = server._fbot_board_payload(_full, _org, extras={"EXEC": {"last_active_at": int(time.time())-30, "grade": "active", "employment": "employed"}},
                                     inbox={"EXEC": 2}, escal={"EXEC": 1})
    check("페이로드 최상위 키", all(k in _pl for k in ("generated", "summary", "scopes", "bots", "dispatch", "deadlocks")))
    check("bots 는 전수(퇴근 포함) 3", len(_pl["bots"]) == 3 and _pl["bots"]["WK"]["state"] == "checkout")
    check("extras·인박스 집계가 개체에 붙는다", _pl["bots"]["EXEC"]["inbox_open"] == 2 and _pl["bots"]["EXEC"]["escalated"] == 1 and _pl["bots"]["EXEC"]["grade"] == "active")
    check("scopes 는 본사 → prj 순, 자리 3", [sc["prj"] for sc in _pl["scopes"]] == [None, 2] and _pl["summary"]["seats"] == 3 and _pl["summary"]["vacant"] == 1)
    check("자리에 점유자 bot_id·보고선", next(st for sc in _pl["scopes"] for d in sc["depts"] for st in d["seats"] if st["addr"] == "2/ops-lead-1")["reports_to"] == "hq/hq-chief-1")
    _by = {e["job_id"]: e for e in _pl["dispatch"]}
    check("배분 체인 parent — PM→WK 의 부모는 EXEC→PM", _by["fbotdisp-2-bbbbbbbb"]["parent"] == "fbotdisp-1-aaaaaaaa")
    check("problem·recent 판정이 실린다", _by["fbotdisp-2-bbbbbbbb"]["problem"] is True and _by["fbotdisp-3-cccccccc"]["recent"] is False and _by["fbotdisp-1-aaaaaaaa"]["recent"] is True)
    check("요약 — 열린 1 · 문제 1 · 인박스 2", _pl["summary"]["open_dispatch"] == 1 and _pl["summary"]["problem_dispatch"] == 1 and _pl["summary"]["inbox_open"] == 2)
    _bh = server._fbot_board_html("", 2)
    # Issue523 — 2·3열 병합: 트리 | (업무 배당 조직도 / 작업 상세)
    check("보드 셸 — 트리·조직도·작업 상세·기간 토글·요약·필터·폴링", all(x in _bh for x in ('id="fb-tree"', 'id="fb-org"', 'id="fb-work"', 'id="fb-period"', 'id="fb-toggle-problem"', "/fbot-map.json", "setInterval(load, 30000)")))
    check("보드 셸 — 3열 폭 변수(--fb-w3)·구 3열 id 제거", "--fb-w3" not in _bh and 'id="fb-chain"' not in _bh and 'id="fb-detail"' not in _bh)
    check("보드 셸 — 쿼리 전달(prj=2)", 'window.__fbQuery="prj=2"' in _bh)
    # Issue524 — 조직도 ↔ 작업 상세 경계 = 가로 분할 바 하나로 통일(구 resize:vertical 모서리 손잡이 제거)
    check("보드 셸 — 가로 분할 바(.fb-hsplit)·resize:vertical 부재", 'id="fb-hsplit"' in _bh and "row-resize" in _bh and "resize:vertical" not in _bh)
    _pg_b = server.Handler._render_fbot_map(_d488(_nb, [_e_a]), tab="board").decode("utf-8")
    check("tab=board 렌더 — 탭바에 보드 on + 셸 포함", 'class="fm-tab on" href="/fbot-map"' in _pg_b and 'id="fb-tree"' in _pg_b)   # prj3#Issue588: board 가 기본 → 링크에 tab 생략
    check("보드 탭은 그래프 캔버스를 만들지 않는다", 'id="fb-cy-org"' not in _pg_b)

    print("\n== Issue523 — 봇별 work 분류(받은·하는·미룬·지시한) 단일 판정 ==")
    _now = int(time.time())
    _nw = [_n488("CH", state="working"), _n488("LD", state="working", root="CH"),
           _n488("W1", state="working", root="CH"), _n488("W2", state="checkin", root="CH")]
    _w_open = dict(_e488("CH", "LD", issue="OPEN"), job_id="fbotdisp-w1", ts=_now - 600)
    _w_gate = dict(_e488("LD", "W1", issue="GATE", status="blocked"), job_id="fbotdisp-w2", ts=_now - 500)
    _w_stale = dict(_e488("LD", "W2", issue="STALE"), job_id="fbotdisp-w3", ts=_now - 8 * 3600)
    _w_def = dict(_e488("LD", "W1", issue="DEFER", status="deferred"), job_id="fbotdisp-w4", ts=_now - 400)
    _w_done = dict(_e488("LD", "W1", issue="DONE", status="done"), job_id="fbotdisp-w5", ts=_now - 300)
    _w_old = dict(_e488("LD", "W1", issue="OLD", status="done", ago_h=96), job_id="fbotdisp-w6")
    _fw = _d488(_nw, [_w_open, _w_gate, _w_stale, _w_def, _w_done, _w_old])
    _xw = [{"id": "fbotreq-esc", "kind": "fbot_request", "status": "open", "owner": "W2", "created_at": _now - 90,
            "payload": json.dumps({"from": "CH", "body": "수락 대기", "escalated_at": _now - 30})},
           {"id": "fbotreq-ok", "kind": "fbot_request", "status": "open", "owner": "W2", "created_at": _now - 80,
            "payload": json.dumps({"from": "CH", "body": "새 요청"})},
           {"id": "fbotreq-done", "kind": "fbot_request", "status": "done", "owner": "W2", "created_at": _now - 70,
            "payload": json.dumps({"from": "CH", "body": "끝난 요청"})}]
    _plw = server._fbot_board_payload(_fw, {"available": True, "seats": []},
                                      dl=server._fbot_deadlocks(_fw), extra_jobs=_xw)
    _W = {b: _plw["bots"][b]["work"] for b in ("CH", "LD", "W1", "W2")}
    _why = lambda b: {x["id"]: x["why"] for x in _W[b]["deferred"]}
    check("모든 봇에 work 4칸", all(set(w) == {"received", "doing", "deferred", "directed"} for w in _W.values()))
    check("doing — 정체 아닌 open 만(LD: OPEN)", _W["LD"]["doing"] == ["fbotdisp-w1"] and _W["LD"]["received"] == ["fbotdisp-w1"])
    check("gate — blocked 는 미룬 일(why=gate), 하는 일 아님", _why("W1").get("fbotdisp-w2") == "gate" and "fbotdisp-w2" not in _W["W1"]["doing"])
    check("deferred — 명시 보류 상태는 why=deferred", _why("W1").get("fbotdisp-w4") == "deferred")
    check("stale — 정체 판정 open 은 why=stale, 하는 일 아님", _why("W2").get("fbotdisp-w3") == "stale" and "fbotdisp-w3" not in _W["W2"]["doing"])
    check("unaccepted — 에스컬된 open 요청만 미룬 일", _why("W2").get("fbotreq-esc") == "unaccepted" and "fbotreq-ok" not in _why("W2"))
    check("받은 일에 open 요청 2건 포함·종결 요청 제외", {"fbotreq-esc", "fbotreq-ok"} <= set(_W["W2"]["received"]) and "fbotreq-done" not in _W["W2"]["received"])
    check("recent 밖 종결 배분은 받은 일·지시한 일에서 제외", "fbotdisp-w6" not in _W["W1"]["received"] and "fbotdisp-w6" not in _W["LD"]["directed"])
    check("recent 안 종결 배분은 받은 일에 남는다", "fbotdisp-w5" in _W["W1"]["received"])
    check("directed — 배분자 기준, problem 먼저",
          set(_W["LD"]["directed"]) == {"fbotdisp-w2", "fbotdisp-w3", "fbotdisp-w4", "fbotdisp-w5"}
          and _W["LD"]["directed"][0] in ("fbotdisp-w2", "fbotdisp-w3") and _W["CH"]["directed"] == ["fbotdisp-w1"])
    check("deferred 상태 기호 ⏸ · 문제로 치지 않는다", _plw["jobs"]["fbotdisp-w4"]["sign"] == "⏸" and not _plw["jobs"]["fbotdisp-w4"]["problem"])

    print("\n== prj3#Issue561·562 — 상단 상태 요약 · 흐름 필터 ==")
    _n561 = [_n488("M", state="working"), _n488("A", state="waiting_input", root="M"),
             _n488("B", state="checkout", root="M")]
    _summ = server._fbot_state_summary(_n561, [_e488("M", "A"), _e488("M", "B", status="done")])
    check("요약줄에 상태별 개수(작업중 1·수신대기 1·퇴근 1)",
          "작업중 1" in _summ and "수신대기 1" in _summ and "퇴근 1" in _summ)
    check("요약줄에 열린 배분 수", "열린 배분 1" in _summ)
    _e1 = dict(_e488("M", "A", issue="ROOT"), job_id="fbotdisp-1-aaaaaaaa", ts=100)
    _e2 = dict(_e488("A", "B", issue="CHILD"), job_id="fbotdisp-2-bbbbbbbb", ts=200)
    _e3 = dict(_e488("M", "B", issue="OTHER", status="blocked"), job_id="fbotdisp-3-cccccccc", ts=300)
    _fl = server._fbot_flow_filter([_e1, _e2, _e3], None, job="fbotdisp-1-aaaaaaaa")
    check("job 필터 — 그 배분 + 하위 체인만(ROOT·CHILD)",
          sorted(e["issue"] for e in _fl) == ["CHILD", "ROOT"])
    _fp = server._fbot_flow_filter([_e1, _e2, _e3], None, problem=True)
    check("problem 필터 — blocked 만", [e["issue"] for e in _fp] == ["OTHER"])
    check("없는 job 은 빈 목록", server._fbot_flow_filter([_e1], None, job="fbotdisp-9-zzzzzzzz") == [])
    _pg = server.Handler._render_fbot_map(_d488(_n561, [_e1, _e2, _e3]), flow_problem=True).decode("utf-8")
    check("페이지에 지시 선택 select 와 전체 보기 토글", "지시 선택:" in _pg and "전체 보기" in _pg)
    check("페이지 헤더에 상태 요약줄", "열린 배분" in _pg)

    print("\n== prj3#Issue488 — 빈 다이어그램 회귀 (2026-09-01 실발생) ==")
    # 활성 0 + 열린 배분 0 → 그릴 것이 없다. 이때 빈 <pre class="mermaid"></pre> 를 내면
    #   런타임이 파싱에 실패해 페이지 한복판에 **"Syntax Error" 폭탄 그림**을 띄운다.
    #   `?root=fbot-hr`·`?root=fbot-exec-narae` 에서 실제로 그렇게 깨졌다.
    dead_only = _d488([_n488("M", state="checkout"),
                       _n488("W", state="checkout", root="M")],
                      [_e488("M", "W", status="done", ago_h=96)])   # 오래된 종결(Issue556 창 밖)
    p = server.Handler._render_fbot_map(dead_only).decode("utf-8")
    check("활성 0이어도 빈 그래프를 만들지 않는다",
          'id="fb-cy-org"' not in p)
    check("대신 비어 있는 이유와 다음 행동을 적는다",
          "활성인 핀봇이 없습니다" in p and "전체 보기" in p)
    check("전체 보기로 넘기면 조직도가 그려진다",
          "var DATA={org:" in
          server.Handler._render_fbot_map(dead_only, True).decode("utf-8"))


def _check_issue502():
    """prj3#Issue502 — 경보 등급 2분. ⛔ 교착(순환·명부 부재 = 스스로 안 풀림)과
    ⏳ 미종결 원장(대상 퇴근·정체 = 회수·관망)은 심각도가 다르다 — 한 등급으로 내면
    전부 "고장" 으로 읽히고 반복 노출이 경보를 배경 소음으로 만든다.
    """
    print("\n== prj3#Issue502 — 경보 등급 2분(⛔ 교착 / ⏳ 미종결 원장) ==")
    d = _d488([_n488("MGR"), _n488("W1", state="checkout", root="MGR")],
              [_e488("MGR", "W1", ago_h=2)])
    dl = server._fbot_deadlocks(d)
    check("대상 퇴근은 soft(미종결) — 교착 아님",
          dl["soft_count"] == 1 and dl["hard_count"] == 0)
    check("기존 키(orphaned·count) 호환 유지",
          len(dl["orphaned"]) == 1 and dl["count"] == 1)
    d2 = _d488([_n488("MGR"), _n488("GHOST", orphan=True, root="MGR")],
               [_e488("MGR", "GHOST")])
    dl2 = server._fbot_deadlocks(d2)
    check("명부 부재는 hard(⛔ — 수행 주체가 존재하지 않음)",
          dl2["hard_count"] == 1 and dl2["soft_count"] == 0)
    d3 = _d488([_n488("A"), _n488("B", root="A")],
               [_e488("A", "B", issue="I1"), _e488("B", "A", issue="I2")])
    check("순환은 hard", server._fbot_deadlocks(d3)["hard_count"] == 1)
    d4 = _d488([_n488("MGR"), _n488("W1", root="MGR")],
               [_e488("MGR", "W1", ago_h=7)])
    dl4 = server._fbot_deadlocks(d4)
    check("정체는 soft(관망)", dl4["soft_count"] == 1 and dl4["hard_count"] == 0)

    page = server.Handler._render_fbot_map(d).decode("utf-8")
    check("soft 만이면 붉은 교착 배너가 없다", '<div class="fm-dead">' not in page)
    check("⏳ 미종결 원장 배너(회수 안내 톤)",
          '<div class="fm-warn fm-open">' in page and "미종결 원장 1건" in page)
    check("ⓒ 계수 분리 — 진짜 교착 0건이 명시된다", "진짜 교착(⛔)은 0건" in page)

    # ⓑ 원클릭 종결 — job_id 가 있을 때만 버튼. 집행은 lead cancel 경유.
    e = _e488("MGR", "W1", ago_h=2)
    e["job_id"] = "job-XYZ"
    d5 = _d488([_n488("MGR"), _n488("W1", state="checkout", root="MGR")], [e])
    p5 = server.Handler._render_fbot_map(d5).decode("utf-8")
    check("종결 버튼은 job_id 가 있을 때만",
          'data-job="job-XYZ"' in p5 and "fm-close-btn" in p5
          and "data-job" not in page)
    check("집행 경로 고지 — lead cancel 경유(원장 직접 UPDATE 금지)",   # prj3#Issue610 rename
          "fbot-lead.py cancel" in p5)
    check("종결 스크립트가 /fbot-dispatch-close 를 부른다",
          "/fbot-dispatch-close" in p5)
    check("종결 엔드포인트 핸들러 실재",
          hasattr(server.Handler, "_handle_fbot_dispatch_close"))

    p2 = server.Handler._render_fbot_map(d2).decode("utf-8")
    check("hard 는 ⛔ 붉은 배너", '<div class="fm-dead">' in p2 and "⛔ 교착 1건" in p2)
    pr = server.Handler._render_fbot_map(d5, False, False, "roster").decode("utf-8")
    check("⏳ 배너·종결 스크립트가 roster 탭에도(탭 밖 공통)",
          '<div class="fm-warn fm-open">' in pr and "/fbot-dispatch-close" in pr)


def _check_issue494():
    """prj3#Issue494 — 탭 2분할(같은 라우트). map=관계 구조 · roster=명부·배분 원장.

    계약 §조직 관측의 진입점 역할 분담이 근거다 — `/fbot-map` 은 「누가 누구를 부렸나」
    (관계 구조)이고, 명부는 「지금 무엇을 하나」 성격이라 탭으로 가른다. 없애는 것이
    아니라(표는 전수 유지) 같은 라우트 안에서 화면만 분리한다.
    """
    print("\n== prj3#Issue494 — 탭 2분할(map/roster) ==")
    nodes = [_n488("MGR"), _n488("W1", state="checkout", root="MGR")]
    disp = [_e488("MGR", "W1", issue="ISS-OPEN", ago_h=1)]   # 스폰 유예(Issue573) 밖 — 미종결 배너 대상
    d = _d488(nodes, disp)
    pmap = server.Handler._render_fbot_map(d).decode("utf-8")
    prost = server.Handler._render_fbot_map(d, False, False, "roster").decode("utf-8")

    check("기본(map) 탭은 관계 구조 전용 — 표 없음",
          "<h2>명부</h2>" not in pmap and "<h2>배분 원장</h2>" not in pmap)
    check("map 탭에 그래프 캔버스가 선다", 'id="fb-cy-org"' in pmap)
    check("roster 탭에 명부·원장 표", "<h2>명부</h2>" in prost and "<h2>배분 원장</h2>" in prost)
    check("roster 탭에는 그래프 캔버스가 없다", 'id="fb-cy-org"' not in prost)
    check("탭 nav 가 양 탭에 선다",
          'class="fm-tabs"' in pmap and 'class="fm-tabs"' in prost)
    check("roster 링크는 ?tab=roster", 'href="/fbot-map?tab=roster"' in pmap)
    check("map 링크는 tab 쿼리 생략(기본값 계약)", 'href="/fbot-map"' in prost)
    # prj3#Issue538: 탭이 3개가 되며 map 탭 이름이 "조직도"→"관계 구조" 로 바뀌었다.
    #   실제 조직 구조(부서·자리) 탭이 생긴 이상 "조직도" 라는 이름은 그쪽 것이고,
    #   둘 다 "조직" 으로 부르면 사용자가 무엇을 보는지 알 수 없다.
    check("현재 탭에 on 표식",
          '<a class="fm-tab on" href="/fbot-map?tab=map"' in pmap and '>그래프</a>' in pmap  # prj3#Issue580·588: 그래프 탭은 tab=map 명시, 기본=보드
          and 'fm-tab on" href="/fbot-map?tab=roster"' in prost)
    porg = server.Handler._render_fbot_map(d, False, False, "org").decode("utf-8")
    check("조직 구조 탭 — 선언된 자리가 봇 상태와 무관하게 선다",
          'fm-tab on" href="/fbot-map?tab=org"' in porg)
    # prj3#Issue538 조직 생명주기: 전체 뷰는 조직별로 갈리고 본사만 펼쳐 둔다 —
    #   20개 조직 97자리를 평면으로 늘어놓으면 "어느 프로젝트의 개발부서인가" 를 못 읽는다.
    _multi = dict(d, org={"available": True, "scopes": 2, "archived_count": 1,
                          "unseated": [], "stale_drops": [], "title": None,
                          "seats": [
        {"id": "hq-chief-1", "addr": "hq/hq-chief-1", "role": "chief", "dept": "hq",
         "dept_label": "본사", "source": "central", "vacant": True,
         "state_label": "공석", "occupant": "", "scope_prj": None, "scope_title": "본사"},
        {"id": "dev-qa-1", "addr": "16/dev-qa-1", "role": "qa", "dept": "dev",
         "dept_label": "개발부서", "source": "inherited", "vacant": True,
         "state_label": "공석", "occupant": "", "scope_prj": 16, "scope_title": "fWarrange"}]})
    pmulti = server.Handler._render_fbot_map(_multi, False, False, "org").decode("utf-8")
    # prj3#Issue597 이후 펼침 기준은 "본사인가" 가 아니라 **활성 세션이 있는가** 다.
    #   이 픽스처는 두 조직 다 공석이라 양쪽이 접힌 채(idle) 갈리는 것이 정상이다.
    check("전체 뷰 — 조직별로 갈리고, 활성 없는 조직은 접힌다",
          pmulti.count('<details class="fm-scope') == 2
          and pmulti.count('fm-scope idle') == 2
          and pmulti.count(" open>") == 0
          and "prj16 · fWarrange" in pmulti)
    # prj3#Issue689 — 「휴면」 은 3일 구성 판정의 이름이 됐다. 팀장 부재(휴직·PM 없음) 계수는 이름을 갈랐다
    check("팀장 부재 팀은 그리지 않고 계수만 한다(공석 배경 방지)",
          "팀장 부재 1팀" in pmulti)
    # prj3#Issue538: 팀의 생사는 PM핀봇 career 가 답한다. state 를 보면 안 된다 —
    #   checkout 은 cold 라 퇴근을 죽음으로 읽으면 매일 밤 전 조직이 사라진다.
    # 소스 텍스트를 훑지 않는다 — docstring 의 설명까지 잡혀 통과하는 구현도 실패한다
    #   (실측). 판정에 쓰는 **SQL** 이 career 만 읽고 state 를 안 보는지로 확인한다.
    _sql = [l for l in _org_alive_src.splitlines() if "SELECT" in l.upper()]
    check("퇴근(state)은 죽음이 아니다 — 판정 쿼리가 career 만 읽는다",
          bool(_sql) and all("career" in l and "state" not in l for l in _sql))
    check("살아있는 career 는 probation·active 둘뿐",
          _org_mod.ALIVE_CAREERS == ("probation", "active"))
    check("본사는 항상 살아 있다(조직 골격)", _org_mod.team_alive(None) is True)

    # ── prj3#Issue538: 탭마다 축이 다르다 (사용자 관측 2026-09-06) ──────────
    #   조직 탭에 루트 칩을 두면 눌러도 화면이 그대로여서 "탭마다 차이가 없다" 로 읽힌다.
    _d2 = dict(d, org={"available": True, "scopes": 1, "archived_count": 0,
                       "unseated": [], "stale_drops": [], "title": "fWarrange",
                       "all_scopes": [(16, "fWarrange"), (3, "claude")],
                       "seats": [{"id": "ops-lead-1", "addr": "16/ops-lead-1",
                                  "role": "lead", "dept": "ops", "dept_label": "운영부서",
                                  "source": "inherited", "vacant": False, "occupant": "pm16",
                                  "state_label": "퇴근", "scope_prj": 16,
                                  "scope_title": "fWarrange"}]})
    _porg2 = server.Handler._render_fbot_map(_d2, False, False, "org", 16).decode("utf-8")
    check("조직 탭 칩은 프로젝트 축(루트가 아니다)",
          "tab=org&amp;prj=3" in _porg2 and "root=" not in _porg2.split('fm-chips')[1][:400])
    check("prj 를 골라도 다른 prj 로 넘어갈 수 있다(갇히지 않는다)",
          _porg2.count('class="fm-chip') >= 3)
    check("선택한 prj 칩에 on 표식", 'fm-chip on" href="/fbot-map?tab=org&amp;prj=16"' in _porg2)
    check("조직이 하나면 접지 않는다(프로젝트 뷰 형태)",
          '<details class="fm-scope"' not in porg)

    # ── prj3#Issue538 s4: 작업 전파 — 완료 사인·시간축 ─────────────────────
    #   기호가 상태를, 상대시각이 정체를 말한다. 종전 라벨은 status 문자열을 늘어놓아
    #   둘 다 못 했고, 3분 전 배분과 26시간 전 배분이 같은 화살표로 그려졌다.
    check("완료와 취소·회수가 다른 기호",
          server._FBOT_FLOW_SIGN["done"] != server._FBOT_FLOW_SIGN["reaped"]
          and server._FBOT_FLOW_SIGN["reaped"] != server._FBOT_FLOW_SIGN["cancelled"])
    _now = 1_800_000_000
    check("상대시각 — 경계",
          server._fbot_rel_time(_now - 30, _now) == "방금"
          and server._fbot_rel_time(_now - 600, _now) == "10분 전"
          and server._fbot_rel_time(_now - 7200, _now) == "2시간 전"
          and server._fbot_rel_time(_now - 200000, _now) == "2일 전")
    check("ts 없으면 시각을 지어내지 않는다", server._fbot_rel_time(0) == "")
    # prj1#Issue489 — 배분 흐름 mermaid(`_fbot_flow_mermaid`) 도 2세대에서 제거됐다.
    #   기호·상대시각은 이제 **엣지 데이터**(sign·recent)로 나가고 그림은 클라이언트가 그린다.
    _bd = server._fbot_board_data()
    _reaped = [e for e in _bd["dispatch"] if e["status"] == "reaped"]
    check("배분 엣지가 상태 기호를 데이터로 싣는다",
          all(e["sign"] == server._FBOT_FLOW_SIGN["reaped"] for e in _reaped) if _reaped
          else set(server._FBOT_FLOW_SIGN) >= {"reaped", "done", "cancelled"})
    check("reaped 는 closed 와 다른 기호(완료로 뭉치지 않는다)",
          server._FBOT_FLOW_SIGN["reaped"] != server._FBOT_FLOW_SIGN["done"])
    check("상대시각 계산은 그대로 산다(라벨의 근거)",
          server._fbot_rel_time(int(__import__("time").time()) - 3600) == "1시간 전")

    # ⓒ 경보 배너는 탭 밖 상단 공통 — 어느 탭에서도 보여야 한다.
    check("경보 배너가 양 탭 공통(탭 밖 상단)",
          "미종결 원장" in pmap and "미종결 원장" in prost)

    # 필터 공통 — root·all·hist 가 탭 링크·칩에 함께 실린다.
    pall = server.Handler._render_fbot_map(d, True, True).decode("utf-8")
    check("all·hist 상태가 roster 탭 링크에 실린다",
          'href="/fbot-map?tab=roster&amp;all=1&amp;hist=1"' in pall)
    prall = server.Handler._render_fbot_map(d, True, False, "roster").decode("utf-8")
    check("roster 탭의 칩이 tab 을 유지한다", "tab=roster" in
          prall[prall.index('class="fm-chips"'):prall.index("<h2>명부</h2>")])
    check("roster 탭에서 map 복귀 링크가 all 을 유지한다",
          'href="/fbot-map?all=1"' in prall)

    # 크기 — 탭 분리의 목적 자체(26KB 단일 페이지 회귀 방지). 합보다 각각이 작아야 한다.
    both = len(pmap) + len(prost)
    check("각 탭이 통합 페이지보다 작다(분리 실효)",
          len(pmap) < both and len(prost) < both)


# ── 클라이언트 렌더 검증 ────────────────────────────────────────────────
# renderBots 는 서버가 문자열로 들고 있는 JS 라 python 단위테스트로는 닿지 않는다.
#   Issue400·401 과 같은 방식으로 **서빙되는 소스를 그대로 뽑아** node 로 실행한다.
#   재구현을 검사하면 회귀를 못 잡으므로 반드시 원문을 쓴다.
JS_FNS = ("renderBotsIdle", "renderBots", "botGroupMapHref", "renderBotGroups", "botChip",
          "botCard", "botDetail", "botNameLink",  # botNameLink: Issue535 에서 botCard 가 의존
          "botGridCols", "fitBotGroups")  # Issue560: renderBots 가 렌더 직후 그룹 폭을 맞춘다

JS_SHIM = r"""
class El { constructor(id){this.id=id;this._html='';this.style={};this.textContent='';}
  set innerHTML(v){this._html=v;} get innerHTML(){return this._html;} }
const LISTEN = {};
class Grid extends El { addEventListener(type, fn){ LISTEN[type] = fn; } }
const els = { 'bots-section': new El('s'), 'bots-grid': new Grid('g'), 'bots-count': new El('c') };
const document = { getElementById: (id) => els[id] || null };
const window = { __i18n: I18N };
// Issue560: 트랙 해석값이 없는(=레이아웃 없는) 환경 — fitBotGroups 는 폭을 모르면 손대지 않는다.
//   폭 계약 자체는 test_bot_layout_issue560.py 가 검증한다.
function getComputedStyle(){ return { gridTemplateColumns: 'none' }; }
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
// prj3#Issue611(사용자 지시 2026-09-10): 그룹은 **활성 봇을 가진 루트만** 선다. 팀장핀봇이
//   프로젝트마다 상주해 전원 퇴근이 정상인 조직이 20개를 넘고, 전건을 그리면 홈이 명부가 된다.
check('활성 있는 루트만 그룹으로 렌더',
      (h.match(/class="bot-group"/g)||[]).length === P.__activeGroups &&
      P.__activeGroups < P.__groups);
// prj1#Issue449: 오래된 퇴근은 이름 나열 대신 "외 N개" 로 접힌다. 배분 0건 루트의
//   하위가 증발하지 않는다는 원 의도는 활성 카드(리서치핀봇) + 그룹 소속 수(활성 2/4)
//   + 접힘 수 표기로 검증한다 — 이름 전수 나열은 무한 성장이라 폐기된 사양이다.
check('🔴 배분 0건인 루트 밑에 하위가 남는다(카드+접힘 수)',
      h.includes('리서치핀봇') && h.includes('활성 2/4') && h.includes('bot-rest-more'));
check('그룹 헤더에 소속 수·활성 수', h.includes('활성 2/4'));
check('활성 봇은 카드, 퇴근 봇은 칩·접힘(카드 아님)',
      (h.match(/class="bot-card"/g)||[]).length === 2 &&
      // prj1#Issue449: 칩은 최근(24h) 퇴근만. 나머지는 bot-rest-more 로 접힌다 —
      //   카드가 아닌 것(칩+접힘 합)이 퇴근 7 을 전부 설명하는지 본다.
      (h.match(/class="bot-chip["\s]/g)||[]).length
        + (h.match(/bot-rest-more/g)||[]).length >= 1 &&
      (h.match(/class="bot-card"/g)||[]).length + 7 === 9);
check('카운트 배지', els['bots-count'].textContent === '2/9');
check('그룹 헤더에 조직도 링크(별도 어포던스)',
      (h.match(/class="bot-map-link"/g)||[]).length === P.__activeGroups &&
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
// prj3#Issue611: 전원 퇴근이면 그룹은 하나도 서지 않는다. Issue400 의 "전원 퇴근을 숨기지
//   않는다" 는 위 유휴 요약 1줄이 승계한다 — 기능 사망(total 0 → 섹션 자체 숨김)과는 계속 갈린다.
check('전원 퇴근 — 조직 그룹은 서지 않는다',
      (h.match(/class="bot-group"/g)||[]).length === 0);
check('전원 퇴근이어도 섹션은 남는다(사망과 구분)',
      els['bots-section'].style.display !== 'none');

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
// Issue547: roster 정렬 축이 바뀌어도 흔들리지 않게 **화면에 서는 그룹(활성 있는 루트)** 의
//   퇴근 봇을 고른다 — 순서에 기대면 활성 0 그룹(미렌더) 소속이 뽑혀 칩이 아예 안 선다.
const liveRoots = new Set(ros2.filter(m => m.active).map(m => m.root));
const outs = ros2.filter(m => !m.active && liveRoots.has(m.root));
outs[0].last_seen = NOW - 3600;          // 1시간 전 — 최근
outs[1].last_seen = NOW - 3 * 86400;     // 3일 전 — 오래됨
renderBots(P.bots, P.bots_total, P.bots_today, ros2);
h = els['bots-grid'].innerHTML;
check('24h 이내 퇴근만 강조 칩',
      (h.match(/class="bot-chip bot-chip-recent"/g)||[]).length === 1);
check('강조 칩에 상대시각 동반', h.includes('전 퇴근') && h.includes('bot-chip-age'));
// prj1#Issue449: 24h 초과·무기록 퇴근은 칩이 아니라 "외 N개" 로 접힌다.
check('24h 초과·무기록은 접힘(칩은 최근 1개뿐)',
      (h.match(/class="bot-chip["\s]/g)||[]).length === 1 &&
      h.includes('bot-rest-more'));
check('24h 초과여도 툴팁에 마지막 실행을 남긴다(정보 손실 금지)',
      h.includes('마지막 실행'));
// 접힘 이후 '마지막 실행' 툴팁은 살아남은 최근 칩(1개)에만 존재한다.
check('last_seen 없는 퇴근 봇은 툴팁도 만들지 않는다',
      (h.match(/마지막 실행/g)||[]).length === 1);

// prj1#Issue449 + prj3#Issue611: 루트가 명부에서 사라진(끊긴 사슬) 그룹이라도 **일하는 봇이
//   있으면** 통째로 증발시키지 않는다 — id 만 뜨는 편이 소속 봇이 화면에서 사라지는 것보다 낫다.
//   활성 0 이면 숨기는 새 사양과 충돌하지 않는다: 숨김의 기준은 루트의 존재가 아니라 활동이다.
const ghostWorker = {bot_id:'zw', title:'유령 소속 워커', role:'qa', state:'working',
  state_label:'작업중', state_emoji:'🟢', career:'', color:'', root:'z-gone', is_root:false,
  active:true, icon_uri:''};
renderBots([Object.assign({}, ghostWorker, {parent_bot_id:'z-gone', current_task:'', prj:null,
  lease_stale:false, lease_expires:null, parent_title:'', session_id:'', tmux_target:''})],
  2, {}, [ghostWorker]);
h = els['bots-grid'].innerHTML;
check('루트가 명부에 없어도 활성 멤버가 있으면 그룹은 남는다(멤버 증발 금지)',
      h.includes('bot-group') && h.includes('유령 소속 워커'));
check('그 그룹 헤더는 루트 id 로 폴백한다(이름을 지어내지 않는다)', h.includes('z-gone'));
// 같은 사슬이라도 전원 퇴근이면 서지 않는다 — 판정이 "루트 부재" 가 아니라 "활동" 임을 박제.
renderBots([], 1, {}, [{bot_id:'z', title:'유령상사', role:'exec', state:'checkout',
  state_label:'퇴근', state_emoji:'⬜', color:'', root:'z-gone', is_root:false,
  active:false, icon_uri:''}]);
check('루트 부재 + 활성 0 은 숨긴다(판정 기준은 활동)',
      !els['bots-grid'].innerHTML.includes('bot-group') &&
      els['bots-grid'].innerHTML.includes('bot-idle'));

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
        # Issue547 — 이 픽스처는 **루트 관계 축**(Issue402) 전용 모양이다. 홈 카드는 이제 prj 조직
        #   (group)으로 묶이므로, 여기서는 group 을 벗겨 **구 payload 폴백 경로**(root 그룹핑)를
        #   검증한다. group 축 자체는 test_fbot_bots.py 17) 이 python·소스로 박제한다.
        for _m in payload["bots_roster"]:
            _m.pop("group", None); _m.pop("group_head", None)
        payload["__groups"] = len({m.get("group") or m["root"] for m in payload["bots_roster"]})
        # prj3#Issue611: 화면에 서는 그룹은 **활성 봇을 가진 루트**뿐이다(사용자 지시
        #   2026-09-10). 전건 수(__groups)는 접힘·명부 검증에 계속 쓰이므로 둘 다 둔다.
        _act = {b["bot_id"] for b in payload["bots"]}
        payload["__activeGroups"] = len({m.get("group") or m["root"] for m in payload["bots_roster"]
                                         if m["bot_id"] in _act})
        ko = json.load(open(os.path.join(REPO, "data", "locales", "ko.json"),
                            encoding="utf-8"))
        src = server.HUB_HTML
        js = ("const I18N = " + json.dumps(ko, ensure_ascii=False) + ";\n"
              + "const P = " + json.dumps(payload, ensure_ascii=False) + ";\n"
              + JS_SHIM
              + _grab_line(src, "const BOT_RECENT_SEC") + "\n"
              # Issue546 — 퇴근 칩 상한·펼침 집합도 renderBots 가 참조한다
              + _grab_line(src, "const BOT_CHIP_MAX") + "\n"
              + _grab_line(src, "const openBotRest") + "\n"
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
