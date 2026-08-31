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

        print("\n== prj3#Issue496 — 노드 3종 표기(prj·아이콘·개체색) ==")
        # ⓐ prj 배지 — NULL 은 "전역"(빈칸이면 미설정과 구별 불가). R1 만 prj=1 이다.
        _lines = {l.split("[", 1)[0].strip(): l for l in mmd.splitlines()
                  if '["' in l and not l.strip().startswith("subgraph")}
        check("prj 실측치는 prjN 로 라벨에 실린다", "prj1" in _lines.get("B_R1", ""))
        check("prj NULL 은 전역으로 표기", "전역" in _lines.get("B_R2", ""))
        # ⓑ 아이콘 — 개체 아이콘(R1) + role 폴백(B1: exec.svg). 속성은 홑따옴표여야
        #   한다 — 라벨이 mermaid 쌍따옴표 문자열 안에 들어가므로.
        check("개체 아이콘 <img> data URI 인라인",
              "<img src='data:image/svg+xml;base64," in _lines.get("B_R1", ""))
        check("개체 아이콘 부재 시 role 아이콘 폴백(B1→exec.svg)",
              "<img src='data:image/svg+xml;base64," in _lines.get("B_B1", ""))
        check("아이콘 img 에 쌍따옴표 없음(mermaid 문자열 파괴 금지)",
              '<img src="' not in mmd)
        check("role 아이콘도 없으면 img 를 만들지 않는다(C2·research)",
              "<img" not in _lines.get("B_C2", ""))
        # 고아는 명부 밖 — prj 축 자체가 없다.
        check("고아 노드에는 prj 표기 없음", "전역" not in _lines.get("B_GHOSTBOT", ""))
        # ⓒ 개체색 — 위 "개체색 재사용(새 색 체계 금지)" 이 검증한다(fill:#964E9B).
        # 라벨 안전화 — 따옴표·대괄호·백틱이 그대로 나가면 노드가 통째로 사라진다.
        lab = server._fbot_mmd_label('a"b[c]`d|e<f>')
        check("라벨 안전화", all(c not in lab for c in '"[]`|<>'))
        check("노드 id 는 영숫자·언더스코어", server._fbot_mmd_id("B_", "a-b.c") == "B_a_b_c")
        check("어두운 개체색 위 글자는 흰색", server._fbot_text_on("#111111") == "#ffffff")
        check("밝은 개체색 위 글자는 검정", server._fbot_text_on("#eeeeee") == "#111111")
        check("색 없으면 검정 폴백", server._fbot_text_on("") == "#111111")

        print("\n== _render_fbot_map — 페이지 ==")
        # prj3#Issue488: 기본 화면은 활성만이라 퇴근 봇·종료 배분이 걸러진다.
        #   이 절은 "전부 그렸을 때" 를 검증하므로 전체+기록 보기로 렌더한다(prj1#Issue454).
        page = server.Handler._render_fbot_map(d, True, True).decode("utf-8")
        check("canonical <header> 합성", "<header>" in page)
        check("mermaid 블록", '<pre class="mermaid">' in page)
        check("mermaid 소스는 HTML 이스케이프(브라우저 textContent 가 복원)",
              "--&gt;" in page and "&lt;br/&gt;" in page)
        check("런타임 <script> 를 저작하지 않는다(서버 표준 주입에 맡김)",
              "mermaid.min.js" not in page)
        # prj3#Issue494: 명부·원장은 roster 탭으로 분리 — "표는 전수" 원칙은 그대로다.
        rpage = server.Handler._render_fbot_map(d, True, True, "roster").decode("utf-8")
        check("map 탭에는 표가 없다(관계 구조 전용)", "<h2>명부</h2>" not in page)
        check("명부 표는 roster 탭에(다이어그램 실패해도 읽힌다)", "<h2>명부</h2>" in rpage)
        check("배분 원장 표는 roster 탭에", "<h2>배분 원장</h2>" in rpage)
        # prj3#Issue488: 전체 보기에서는 칩이 `&all=1` 을 실어 나른다(칩 이동으로 표시
        #   범위가 풀리면 안 되므로). 칩의 계약은 "root 를 담은 링크" 이므로 접두로 본다.
        check("루트 필터 칩", 'href="/fbot-map?root=R1' in page)
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
        check("mermaid 에도 배분 화살표가 선다", "R1" in server._fbot_map_mermaid(after))

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
# 대상 4종(`_fbot_filter_active`·`_fbot_cycles`·`_fbot_deadlocks`·`_fbot_flow_mermaid`)은
#   dict 를 받는 순수 함수라 DB 픽스처 없이 **판정 자체**를 정밀하게 세울 수 있다.
def _n488(bid, state="checkin", orphan=False, root=None):
    return {"bot_id": bid, "title": bid, "role": "exec", "state": state,
            "state_label": server.FBOT_STATE_LABEL.get(state, state),
            "state_emoji": "🟢", "career": "", "color": "", "prj": None,
            "current_task": "", "parent": "", "root": root or bid,
            "sessions": 0, "orphan": orphan, "session_id": "", "tmux_target": "",
            "icon_uri": ""}


#   ⚠️ 픽스처의 이슈 값은 `ISS-*` 로 둔다 — `IssueN` 으로 쓰면 tagcheck(prj3#Issue325)가
#     실제 이슈 참조로 읽어 커밋을 막는다. 여기서는 원장에 실리는 **문자열 값**일 뿐이다.
def _e488(src, dst, status="open", issue="ISS-A", ago_h=0.0):
    return {"src": src, "dst": dst, "issue": issue, "role": "exec",
            "status": status, "ts": int(time.time() - ago_h * 3600)}


def _d488(nodes, dispatch, hires=None):
    return {"error": "", "nodes": nodes, "hires": hires or [], "dispatch": dispatch,
            "roots": [n["bot_id"] for n in nodes if n["root"] == n["bot_id"]],
            "root_filter": "", "unknown_root": False}


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
    disp = [_e488("MGR", "BUSY", issue="OPEN1"),          # 열린 배분 — 대상은 퇴근
            _e488("MGR", "GONE", status="done", issue="OLD1")]
    d = _d488(nodes, disp)
    v = server._fbot_filter_active(d)
    ids = {n["bot_id"] for n in v["nodes"]}
    check("퇴근 봇은 기본 화면에서 빠진다", "GONE" not in ids)
    check("활성 봇은 남는다", "LIVE" in ids and "MGR" in ids)
    check("열린 배분의 대상은 퇴근했어도 남는다(교착을 가리키므로)", "BUSY" in ids)
    check("종료된 배분은 화면에서 빠진다",
          [e["issue"] for e in v["dispatch"]] == ["OPEN1"])
    check("원본 data 는 손대지 않는다(표시 계층 필터)",
          len(d["nodes"]) == 4 and len(d["dispatch"]) == 2)
    check("칩 목록(roots)은 거르지 않는다", v["roots"] == d["roots"])

    print("\n== prj3#Issue488 ⓑ 배분 흐름 그래프 ==")
    dl = server._fbot_deadlocks(d)
    flow = server._fbot_flow_mermaid(d, dl)
    check("흐름 그래프가 선다", flow.startswith("flowchart LR"))
    check("조직도와 노드 id 접두가 다르다(같은 페이지 충돌 방지)",
          "F_MGR" in flow and "B_MGR" not in flow)
    check("배분 라벨에 이슈가 실린다", "OPEN1" in flow)
    check("교착 엣지는 굵은 빨강", "stroke:#c62828,stroke-width:3px" in flow)
    check("배분이 없으면 빈 문자열", server._fbot_flow_mermaid(_d488([], [])) == "")

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
    check("전체 보기 토글 링크", 'href="/fbot-map?all=1"' in page)
    check("배분 흐름 섹션", "<h2>배분 흐름</h2>" in page)
    # prj1#Issue451: 명부는 **항상 전수**다(퇴역 보존처) — "활성만" 은 그래프에만 적용된다.
    #   그래서 페이지 전체 부재가 아니라 mermaid 블록 부재 + 명부 행 존재를 본다.
    _mm = page[page.index('<pre class="mermaid">'):]
    check("기본은 활성만 — 그래프에 퇴근 봇 없음", "GONE" not in _mm)
    # prj3#Issue494: 명부는 roster 탭 — 전수 보존 검증도 그 탭에서.
    _rp = server.Handler._render_fbot_map(d, False, False, "roster").decode("utf-8")
    check("퇴근 봇도 명부에는 남는다(전수 보존)", ">GONE<" in _rp)
    page_all = server.Handler._render_fbot_map(d, True).decode("utf-8")
    check("전체 보기에서 퇴근 봇이 돌아온다", "B_GONE" in page_all)
    check("전체 보기 토글은 활성으로 되돌린다", 'href="/fbot-map"' in page_all)
    _healthy = server.Handler._render_fbot_map(
        _d488([_n488("M"), _n488("W", root="M")],
              [_e488("M", "W")])).decode("utf-8")
    check("교착이 없으면 배너도 없다(⛔·⏳ 양쪽)",
          _BANNER not in _healthy and _SOFT not in _healthy)

    print("\n== prj3#Issue488 — 빈 다이어그램 회귀 (2026-09-01 실발생) ==")
    # 활성 0 + 열린 배분 0 → 그릴 것이 없다. 이때 빈 <pre class="mermaid"></pre> 를 내면
    #   런타임이 파싱에 실패해 페이지 한복판에 **"Syntax Error" 폭탄 그림**을 띄운다.
    #   `?root=fbot-hr`·`?root=fbot-exec-narae` 에서 실제로 그렇게 깨졌다.
    dead_only = _d488([_n488("M", state="checkout"),
                       _n488("W", state="checkout", root="M")],
                      [_e488("M", "W", status="done")])
    p = server.Handler._render_fbot_map(dead_only).decode("utf-8")
    check("활성 0이어도 빈 mermaid 블록을 만들지 않는다",
          '<pre class="mermaid"></pre>' not in p)
    check("대신 비어 있는 이유와 다음 행동을 적는다",
          "활성인 핀봇이 없습니다" in p and "전체 보기" in p)
    check("전체 보기로 넘기면 조직도가 그려진다",
          '<pre class="mermaid">flowchart' in
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

    # ⓑ 원클릭 종결 — job_id 가 있을 때만 버튼. 집행은 taskmgr cancel 경유.
    e = _e488("MGR", "W1", ago_h=2)
    e["job_id"] = "job-XYZ"
    d5 = _d488([_n488("MGR"), _n488("W1", state="checkout", root="MGR")], [e])
    p5 = server.Handler._render_fbot_map(d5).decode("utf-8")
    check("종결 버튼은 job_id 가 있을 때만",
          'data-job="job-XYZ"' in p5 and "fm-close-btn" in p5
          and "data-job" not in page)
    check("집행 경로 고지 — taskmgr cancel 경유(원장 직접 UPDATE 금지)",
          "fbot-taskmgr.py cancel" in p5)
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
    disp = [_e488("MGR", "W1", issue="ISS-OPEN")]
    d = _d488(nodes, disp)
    pmap = server.Handler._render_fbot_map(d).decode("utf-8")
    prost = server.Handler._render_fbot_map(d, False, False, "roster").decode("utf-8")

    check("기본(map) 탭은 관계 구조 전용 — 표 없음",
          "<h2>명부</h2>" not in pmap and "<h2>배분 원장</h2>" not in pmap)
    check("map 탭에 mermaid 가 선다", '<pre class="mermaid">' in pmap)
    check("roster 탭에 명부·원장 표", "<h2>명부</h2>" in prost and "<h2>배분 원장</h2>" in prost)
    check("roster 탭에는 mermaid 가 없다", '<pre class="mermaid">' not in prost)
    check("탭 nav 가 양 탭에 선다",
          'class="fm-tabs"' in pmap and 'class="fm-tabs"' in prost)
    check("roster 링크는 ?tab=roster", 'href="/fbot-map?tab=roster"' in pmap)
    check("map 링크는 tab 쿼리 생략(기본값 계약)", 'href="/fbot-map"' in prost)
    check("현재 탭에 on 표식",
          '<a class="fm-tab on" href="/fbot-map">조직도</a>' in pmap
          and 'fm-tab on" href="/fbot-map?tab=roster"' in prost)

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
// prj1#Issue449: 24h 초과·무기록 퇴근은 칩이 아니라 "외 N개" 로 접힌다.
check('24h 초과·무기록은 접힘(칩은 최근 1개뿐)',
      (h.match(/class="bot-chip["\s]/g)||[]).length === 1 &&
      h.includes('bot-rest-more'));
check('24h 초과여도 툴팁에 마지막 실행을 남긴다(정보 손실 금지)',
      h.includes('마지막 실행'));
// 접힘 이후 '마지막 실행' 툴팁은 살아남은 최근 칩(1개)에만 존재한다.
check('last_seen 없는 퇴근 봇은 툴팁도 만들지 않는다',
      (h.match(/마지막 실행/g)||[]).length === 1);

// prj1#Issue449: 무기록 퇴근 멤버는 이름 대신 접힘 수로 남는다 — 그룹 증발 금지는 유지.
check('루트가 명부에 없어도 그룹은 남는다(멤버 증발 금지)',
      (renderBots([], 1, {}, [{bot_id:'z', title:'유령상사', role:'exec', state:'checkout',
        state_label:'퇴근', state_emoji:'⬜', color:'', root:'z', is_root:false,
        active:false, icon_uri:''}]),
       els['bots-grid'].innerHTML.includes('bot-group') &&
       els['bots-grid'].innerHTML.includes('bot-rest-more')));

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
