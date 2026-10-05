#!/usr/bin/env python3
# test_fbot_decisions_issue570.py — 조직도 「승인 필요 액션」에서 컨펌할 수 없음 (Issue570)
#
# ⚠️ 글로벌 SCAR 아님 (___pm 프로젝트 소유).
# 왜: 사용자가 봇 상세의 「승인 필요 액션」 칸을 결정 대기 목록으로 읽었는데 누를 것이 없었고,
#   옆의 「에스컬 8」 은 8건 전부 이미 수락(result.status=accepted)된 요청이었다(2026-09-28 실측).
#   인박스 수는 `result IS NULL` 로 거르는데 에스컬 수·요청 problem 은 거르지 않아 같은 요청을
#   두 판정이 다르게 셌다. 정본은 prj3 fbot-inbox.py — 미처리 = open ∧ result IS NULL.
#
# 실행: python3 plugins/fpm-core/services/hub/test_fbot_decisions_issue570.py
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server  # noqa: E402

PASS = FAIL = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  ok   {name}")
    else:
        FAIL += 1; print(f"  FAIL {name}")


ACC = json.dumps({"status": "accepted", "body": "수령", "by": "narae", "at": 300})
FULL = {"nodes": [{"bot_id": "narae", "title": "나래(총괄핀봇)", "role": "chief", "state": "working", "core": True},
                  {"bot_id": "lead-cg", "title": "cg 팀장핀봇", "role": "lead", "state": "checkout"}], "edges": []}


def _req(rid, owner, esc, result=None, status="open", ts=100):
    pl = {"from": "sess-a", "body": rid}
    if esc:
        pl["escalated_at"] = 200
    return {"id": rid, "kind": "fbot_request", "status": status, "owner": owner,
            "payload": json.dumps(pl), "result": result, "created_at": ts}


def t_escalation():
    print("[① 에스컬 = escalated_at ∧ 미수락 — 인박스와 같은 기준]")
    xs = [_req("r-esc", "narae", True), _req("r-acc", "narae", True, ACC), _req("r-new", "narae", False)]
    d = server._fbot_board_payload(FULL, {}, extra_jobs=xs, now=1000)
    J = d["jobs"]
    check("수락 전 에스컬 요청은 문제", J["r-esc"]["problem"] is True)
    check("수락된 요청은 escalated_at 이 남아도 문제 아님", J["r-acc"]["problem"] is False)
    why = {x["id"]: x["why"] for x in d["bots"]["narae"]["work"]["deferred"]}
    check("미룬 일(📥 미수락)에 수락 전 에스컬만", why.get("r-esc") == "unaccepted" and "r-acc" not in why)

    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE job (id TEXT, kind TEXT, status TEXT, owner TEXT, payload TEXT, result TEXT, created_at INT)")
    rows = xs + [_req("r-done", "narae", True, ACC, status="done"), _req("r-cg", "lead-cg", True)]
    con.executemany("INSERT INTO job VALUES (?,?,?,?,?,?,?)",
                    [(r["id"], r["kind"], r["status"], r["owner"], r["payload"], r["result"], r["created_at"]) for r in rows])
    try:
        c = server._fbot_inbox_counts(con)
    except AttributeError as e:
        c = {}; print(f"       ({e})")
    check("집계 — 인박스 = open ∧ 미수락", (c.get("inbox") or {}).get("narae") == 2)
    check("집계 — 에스컬 = 인박스 중 escalated_at (수락분 제외)", (c.get("escal") or {}).get("narae") == 1)
    check("집계 — 다른 봇은 따로 센다", (c.get("escal") or {}).get("lead-cg") == 1)
    check("집계 — 목록 행도 같은 기준", sorted(x["id"] for x in c.get("items") or []) == ["r-cg", "r-esc", "r-new"])


def t_decisions():
    print("\n[② 사람 결정 대기 — 그 봇이 올린 mq [컨펌]]")
    mq = [
        {"id": "m1", "status": "pending", "source": "narae@___common", "message": "[컨펌] [H:배포] 출고할지", "due_ts": 500},
        {"id": "m2", "status": "in_progress", "source": "narae@___common", "message": "[컨펌] [H:공개] 재발행", "result": "배포 확인"},
        {"id": "m3", "status": "pending", "source": "narae@___common", "message": "리마인드 — 결정 아님"},
        {"id": "m4", "status": "pending", "source": "claude@___pm", "message": "[컨펌] [H:비용] 봇 아님"},
        {"id": "m5", "status": "pending", "source": "lead-cg@___cg", "message": "[컨펌] [H:브랜드] 아이콘"},
        {"id": "m6", "status": "pending", "source": "narae-x@___common", "message": "[컨펌] [H:계정] 접두 오매칭"},
    ]
    try:
        d = server._fbot_board_payload(FULL, {}, mq_items=mq, now=1000)
    except TypeError as e:
        d = {"bots": {"narae": {}, "lead-cg": {}}, "summary": {}}; print(f"       ({e})")
    dn = d["bots"]["narae"].get("decisions")
    check("봇마다 decisions 배열", isinstance(dn, list) and isinstance(d["bots"]["lead-cg"].get("decisions"), list))
    dn = dn or []
    check("[컨펌] ∧ source=<bot_id>@ 만 — 비결정·비봇·접두 오매칭 제외", [x["id"] for x in dn] == ["m1", "m2"])
    m1 = dn[0] if dn else {}
    check("행 필드 — id·message·status·due_ts", m1.get("message", "").startswith("[컨펌]") and m1.get("status") == "pending" and m1.get("due_ts") == 500)
    check("결과가 적힌 항목은 has_result — [진행] 을 내지 않는 근거", (dn[1] if len(dn) > 1 else {}).get("has_result") is True and m1.get("has_result") is False)
    check("다른 봇 결정은 그 봇에", [x["id"] for x in d["bots"]["lead-cg"].get("decisions") or []] == ["m5"])
    check("summary.decisions = 봇 결정 합계", (d.get("summary") or {}).get("decisions") == 3)
    d0 = server._fbot_board_payload(FULL, {}, now=1000)
    check("mq 가 없으면 빈 배열", d0["bots"]["narae"].get("decisions") == [])


def t_screen():
    print("\n[③ 화면 — 결정 대기는 여기서 답하고, 관리 요청은 따로]")
    # 조직도 화면 JS 로 한정한다 — /mq 페이지에도 /mq-ack·/mq-doc 가 있어 파일 전체로 보면 거저 통과한다
    src = server._FBOT_BOARD_JS
    check("「사람 결정 대기」 칸", "사람 결정 대기" in src and "fb-decide" in src)
    check("빈 상태를 말한다", "이 봇이 기다리는 사람 결정 없음" in src)
    check("처리는 /mq-ack 계약 그대로(새 종결 경로 없음)", '"aoa-mq-ack:"+' in src and 'fetch("/mq-ack"' in src)
    check("문서로 보기 링크", '"/mq-doc?id="+encodeURIComponent(' in src)
    check("옛 제목 「승인 필요 액션」 제거 — 결정 대기 목록으로 오독됨", "<b>승인 필요 액션</b>" not in src)
    check("관리 요청 칸 새 이름", "관리 요청 올리기" in src)
    check("결정 대기 배지", "결정 ${b.decisions.length}" in src or "결정 ${(b.decisions||[]).length}" in src)


def t_open_requests_survive_cap():
    print("\n[④ 열린 요청은 이벤트 물량에 밀려 잘리지 않는다]")
    # 실측(2026-09-28): 7일 창 400건 상한에 이벤트 1,780건이 몰려 09:41 이전 요청이 전부 잘렸다 →
    #   나래의 열린 요청 18건이 「받은 일 0」 으로 보였다. 열린 요청은 기간·상한과 무관하게 실어야 한다
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE job (id TEXT, kind TEXT, status TEXT, owner TEXT, payload TEXT, result TEXT, created_at INT)")
    now = 10_000_000
    rows = [("ev%d" % i, "fbot_event", "logged", "narae", "{}", None, now - i) for i in range(450)]
    rows += [("req-old", "fbot_request", "open", "narae", '{"body":"오래된 열린 요청"}', ACC, now - 5 * 86400),
             ("req-ancient", "fbot_request", "open", "narae", '{"body":"창 밖 열린 요청"}', None, now - 30 * 86400),
             ("req-done", "fbot_request", "done", "narae", "{}", ACC, now - 5 * 86400)]
    con.executemany("INSERT INTO job VALUES (?,?,?,?,?,?,?)", rows)
    try:
        xs = server._fbot_extra_jobs(con, now)
    except AttributeError as e:
        xs = []; print(f"       ({e})")
    ids = [x["id"] for x in xs]
    check("상한 밖 열린 요청도 실린다", "req-old" in ids)
    check("7일 창 밖이어도 열린 요청은 실린다", "req-ancient" in ids)
    check("종결 요청은 창·상한을 따른다(잘림)", "req-done" not in ids)
    check("중복 없음", len(ids) == len(set(ids)))
    check("result 컬럼을 싣는다 — 에스컬 판정 재료", next((x for x in xs if x["id"] == "req-old"), {}).get("result") == ACC)


def main():
    t_escalation()
    t_decisions()
    t_open_requests_survive_cap()
    t_screen()
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
