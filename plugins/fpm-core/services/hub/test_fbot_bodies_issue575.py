#!/usr/bin/env python3
# test_fbot_bodies_issue575.py — hub 핀봇 카드·타임라인에 관리직 몸체 표시 (Issue575, prj3#Issue757 T15 ⑦)
#
# ⚠️ 글로벌 SCAR 아님 (___pm 프로젝트 소유).
# 왜: prj3#Issue757 T15 — 관리직(총괄·팀장)은 지휘 흐름마다 몸체가 하나씩 뜬다(원장 `fbot_body`). 봇 행은
#   몸체들의 사영이라 카드의 «세션» 칸은 최근 몸체 하나만 보여 준다 — 몇 개의 몸체가 어떤 흐름을 쥐고 있는지
#   화면에서 안 보인다. 판정(살아 있는 몸체 = open · lease 유효)은 prj3 `open_bodies` 와 같은 조건을 읽기만 한다.
#
# 실행: python3 plugins/fpm-core/services/hub/test_fbot_bodies_issue575.py
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server  # noqa: E402

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  ok   {name}")
    else:
        FAIL += 1; print(f"  FAIL {name} {str(detail)[:200]}")


def _grab_line(src, prefix):
    for line in src.splitlines():
        if line.strip().startswith(prefix):
            return line.strip()
    raise AssertionError(f"상수 미발견: {prefix}")


def _grab_js(src, name):
    i = src.index("function " + name + "(")
    j = src.index("{", src.index(")", i))
    depth = 0
    for k in range(j, len(src)):
        if src[k] == "{":
            depth += 1
        elif src[k] == "}":
            depth -= 1
            if depth == 0:
                return src[i:k + 1]
    raise AssertionError(f"함수 끝 미발견: {name}")


def main():
    now = 1_000_000
    print("[A] 원장 → 살아 있는 몸체 (open · lease 유효, 최근 순)")
    fn = getattr(server, "_fbot_bodies", None)
    check("_fbot_bodies 존재", callable(fn))
    if callable(fn):
        con = sqlite3.connect(":memory:")
        con.execute("CREATE TABLE job(id TEXT, kind TEXT, status TEXT, payload TEXT, owner TEXT, lease_until INT, created_at INT)")
        rows = [("b1", "fbot_body", "open", {"session_id": "sess-aaaa1111", "flow": "fbotdisp-1-aa", "state": "working", "started_at": now - 300}, "L1", now + 600),
                ("b2", "fbot_body", "open", {"session_id": "sess-bbbb2222", "flow": "fbotreq-2-bb", "state": "waiting_input", "started_at": now - 100}, "L1", now + 600),
                ("b3", "fbot_body", "open", {"session_id": "sess-cccc3333", "flow": "x", "state": "working", "started_at": now - 50}, "L1", now - 1),
                ("b4", "fbot_body", "closed", {"session_id": "sess-dddd4444", "flow": "y", "started_at": now - 40}, "L1", now + 600),
                ("b5", "fbot_body", "open", {"session_id": "sess-eeee5555", "flow": "z", "started_at": now - 30}, "C1", now + 600),
                ("e1", "fbot_event", "done", {"type": "x"}, "L1", None)]
        for r in rows:
            con.execute("INSERT INTO job VALUES (?,?,?,?,?,?,?)", (r[0], r[1], r[2], json.dumps(r[3]), r[4], r[5], now))
        got = fn(con, now)
        l1 = got.get("L1") or []
        check("🔑 L1 살아 있는 몸체 2 (만료·closed 제외)", [b.get("flow") for b in l1] == ["fbotreq-2-bb", "fbotdisp-1-aa"], l1)
        check("세션은 앞 8자 · 상태 싣기", l1 and l1[0].get("session") == "sess-bbb" and l1[0].get("state") == "waiting_input", l1)
        check("봇별로 가른다(C1 1)", len(got.get("C1") or []) == 1, got)
        check("fbot_body 테이블 행 없음 → 빈 dict", fn(sqlite3.connect(":memory:"), now) == {})

    print("\n[B] payload — 봇에 bodies · 이벤트에 몸체 도장 통과")
    full = {"nodes": [{"bot_id": "L1", "title": "팀장", "role": "lead", "state": "working", "root": "L1", "nonexec": True},
                      {"bot_id": "W1", "title": "워커", "role": "developer", "state": "working", "root": "W1"}],
            "dispatch": []}
    bodies = {"L1": [{"session": "sess-bbb", "flow": "fbotreq-2-bb", "state": "waiting_input", "started_at": now - 100},
                     {"session": "sess-aaa", "flow": "fbotdisp-1-aa", "state": "working", "started_at": now - 300}]}
    ev = {"id": "ev1", "kind": "fbot_event", "status": "done", "owner": "L1", "created_at": now - 10,
          "payload": json.dumps({"type": "reply:done", "detail": "답함", "ref": "r1", "by_session": "sess-bbbb2222", "by_flow": "fbotreq-2-bb"})}
    try:
        d = server._fbot_board_payload(full, {"available": True, "seats": []}, inbox={}, escal={}, now=now,
                                       extra_jobs=[ev], bodies=bodies)
    except TypeError as e:
        d = {}
        check(f"_fbot_board_payload(bodies=) 수용 ({e})", False)
    bots = d.get("bots") or {}
    if d:
        check("🔑 L1.bodies 2 · W1.bodies []", len(bots.get("L1", {}).get("bodies") or []) == 2 and bots.get("W1", {}).get("bodies") == [])
        jp = ((d.get("jobs") or {}).get("ev1") or {}).get("payload") or {}
        check("🔑 이벤트 job payload 에 by_session·by_flow", jp.get("by_session") == "sess-bbbb2222" and jp.get("by_flow") == "fbotreq-2-bb", jp)
        e0 = next((x for x in d.get("events") or [] if x.get("id") == "ev1"), {})
        check("이벤트 스트림에도 by_session", e0.get("by_session") == "sess-bbbb2222", e0)

    print("\n[C] 카드·타임라인 JS (node 실행)")
    src = server._FBOT_BOARD_JS
    node = shutil.which("node")
    if not node or not d:
        print("  skip node 미설치 또는 payload 실패 — 실행 검증 생략")
    else:
        body = _grab_js(src, "seatCardInner")
        tl = _grab_js(src, "timelineHtml")
        one = dict(bots)
        one["L2"] = dict(bots["L1"], bot_id="L2", bodies=bots["L1"]["bodies"][:1])
        js = (_grab_line(src, "const esc") + "\n" + _grab_line(src, "const EVICON") + "\n"
              + "const ago=()=>'';const questionsHtml=()=>'';const directingHtml=()=>'';\n"
              + "const state={data:{bots:" + json.dumps(one) + ",jobs:" + json.dumps(d.get("jobs") or {})
              + ",timeline:" + json.dumps({"L1": ["ev1"], "W1": ["ev1"]}) + "}};\n"
              + tl + "\n" + body + "\n"
              + "const out={L1:seatCardInner({bot_id:'L1',role:'lead',addr:'3/ops-lead-1',reports_to:'hq/hq-lead-1'}),"
                "L2:seatCardInner({bot_id:'L2',role:'lead',addr:'3/ops-lead-1',reports_to:'hq/hq-lead-1'}),"
                "TW:timelineHtml('W1'),TL:timelineHtml('L1')};process.stdout.write(JSON.stringify(out));")
        r = subprocess.run([node, "-e", js], capture_output=True, text=True)
        try:
            h = json.loads(r.stdout)
        except ValueError:
            h = {}
            check(f"node 실행 ({r.stderr.strip()[:200]})", False)
        if h:
            check("🔑 몸체 2 이상이면 카드에 «몸체 2» 와 흐름", "몸체 2" in h["L1"] and "fbotreq-2-bb" in h["L1"] and "fbotdisp-1-aa" in h["L1"], h["L1"][:300])
            check("몸체 1이면 몸체 줄 없음(종전 카드)", "몸체 1" not in h["L2"] and "fb-bodies" not in h["L2"])
            check("🔑 관리직 타임라인은 몸체 표지(세션 앞 8자)", "sess-bbb" in h["TL"], h["TL"][:300])
            check("관리직 아닌 봇 타임라인은 표지 없음", "sess-bbb" not in h["TW"], h["TW"][:300])

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
