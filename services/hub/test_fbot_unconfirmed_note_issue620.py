#!/usr/bin/env python3
# test_fbot_unconfirmed_note_issue620.py — Issue620 회귀 테스트 (핀봇 조직도 ⛔ 사유 표기)
#
# 명제: 원장이 `blocked(unconfirmed)` 로 올린 배분은 보드가 **원장의 사유를 그대로** 보여 준다.
#   prj3#Issue968 이후 sweep 은 `payload.blocked_by='unconfirmed'` + `payload.unconfirmed.reason` 을 적는데,
#   보드는 사유를 버리고 모든 blocked 를 «⏸ 선행대기» 로 그렸다 — 매니저가 무엇을 확정할지 화면에서 안 보였다.
#   판정은 바꾸지 않는다(문구만) — 다른 blocked(질문·워커 사망 등)는 종전 분류(gate)를 유지한다.
#
# 실행: python3 plugins/fpm-core/services/hub/test_fbot_unconfirmed_note_issue620.py
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server  # noqa: E402

PASS = 0
FAIL = 0
SRC = open(server.__file__, encoding="utf-8").read()
REASON = "증거 세션 없음 — 배분 뒤 몸체 미기동"


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok   {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}")


def fixture_con():
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE job(id TEXT PRIMARY KEY, store TEXT, kind TEXT, status TEXT, payload TEXT,"
                " result TEXT, attempts INT, owner TEXT, lease_until INT, blocked_since INT, created_at INT)")
    rows = [
        ("d-unconf", "blocked", {"worker_bot_id": "fbot-w1", "issue": "Issue25",
                                  "blocked_by": "unconfirmed",
                                  "unconfirmed": {"reason": REASON, "at": 1000, "session_job_id": None}}),
        ("d-question", "blocked", {"worker_bot_id": "fbot-w2", "issue": "Issue26", "blocked_by": "question"}),
        ("d-open", "open", {"worker_bot_id": "fbot-w3", "issue": "Issue27"}),
    ]
    for i, (jid, st, pl) in enumerate(rows):
        con.execute("INSERT INTO job(id, kind, status, payload, owner, created_at) VALUES (?,?,?,?,?,?)",
                    (jid, "fbot_dispatch", st, json.dumps(pl, ensure_ascii=False), "fbot-lead", 900 + i))
    return con


print("▶ ① 원장 → 엣지: blocked_by·사유를 싣는다")
edges = server._fbot_dispatch_edges(fixture_con())
by = {e["job_id"]: e for e in edges}
check("unconfirmed 엣지 blocked_by", by["d-unconf"].get("blocked_by") == "unconfirmed")
check("unconfirmed 엣지 block_reason = 원장 사유", by["d-unconf"].get("block_reason") == REASON)
check("question 엣지 blocked_by", by["d-question"].get("blocked_by") == "question")
check("open 엣지 blocked_by 없음", not by["d-open"].get("blocked_by"))

print("▶ ② 사유 문구 단일 지점 _fbot_block_note")
note = getattr(server, "_fbot_block_note", None)
check("_fbot_block_note 존재", callable(note))
if callable(note):
    n1 = note(by["d-unconf"])
    check(f"unconfirmed → «완료 미확인» + 사유 ({n1})", "완료 미확인" in n1 and REASON in n1)
    check("open → 빈 문구", note(by["d-open"]) == "")
    check("question blocked → 비지 않음(종류 표기)", note(by["d-question"]) != "")

print("▶ ③ 미룬 일 분류: unconfirmed 는 «선행대기»(gate) 가 아니다")
jobs = {e["job_id"]: {"id": e["job_id"], "kind": "dispatch", "status": e["status"], "owner": e["src"],
                      "dst": e["dst"], "issue": e["issue"], "ts": e["ts"], "recent": True, "problem": False,
                      "blocked_by": e.get("blocked_by") or ""} for e in edges}
bots = {b: {} for b in ("fbot-lead", "fbot-w1", "fbot-w2", "fbot-w3")}
server._fbot_board_work(bots, jobs, set())
w1 = bots["fbot-w1"]["work"]["deferred"]; w2 = bots["fbot-w2"]["work"]["deferred"]
check(f"w1 why = unconfirmed ({w1})", w1 == [{"id": "d-unconf", "why": "unconfirmed"}])
check(f"w2 why = gate 유지 ({w2})", w2 == [{"id": "d-question", "why": "gate"}])
check("w3 open = doing", bots["fbot-w3"]["work"]["doing"] == ["d-open"])

print("▶ ④ 그래프 툴팁(full)에 사유 — org·flow 둘 다")
nodes = [{"bot_id": b, "title": b, "role": "worker", "state": "checkout", "root": "fbot-lead", "prj": 1}
         for b in bots]
for kind in ("org", "flow"):
    els = server._fbot_graph_elements({"nodes": nodes, "hires": [], "dispatch": edges}, None, kind)
    fe = [x["data"] for x in els["edges"] if x["data"].get("job") == "d-unconf"]
    check(f"{kind} 엣지 full 에 사유", bool(fe) and REASON in fe[0].get("full", ""))

print("▶ ⑤ 보드 페이로드·화면: jobs·엣지에 note, JS 가 사유를 그린다")
check("WHY 에 unconfirmed 라벨", 'unconfirmed:["⛔","완료 미확인"]' in SRC)
check("jobBox 에 사유 행", "<dt>사유</dt>" in SRC)
check("jobRow 툴팁에 note", "j.note" in SRC)

print(f"결과: PASS={PASS} FAIL={FAIL}")
sys.exit(1 if FAIL else 0)
