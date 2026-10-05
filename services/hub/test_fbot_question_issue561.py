#!/usr/bin/env python3
# test_fbot_question_issue561.py — 핀봇 질문 상향 중계 hub 답변 창구 (Issue561, prj3#Issue749 추적)
#
# ⚠️ 글로벌 SCAR 아님 (___pm 프로젝트 소유).
# 왜: 봇이 사람·팀장에게 물을 것이 생기면 prj3 `fbot-inbox.py` 가 `kind=question` 요청을 적재하고 그 배분을
#   `blocked(question)` 으로 세운다. 답할 자리는 의뢰 세션(다음 턴 넛지)뿐이라, 그 세션이 유휴면 워커는
#   답이 올 때까지 멈춘다. hub 보드에서 바로 답할 수 있어야 한다.
#   또 prj3 계약상 질문은 `owner=묻는 봇` 이고 **인박스 집계에서 제외**인데, hub 집계는 이를 빼지 않아
#   묻는 봇 카드에 자기 질문이 «인박스 open» 으로 셈해졌다.
#
# 판정은 서빙 JS 원문을 뽑아 node 로 실행한다(Issue402·560·571 과 같은 방식). 픽스처 payload 는 서버 순수
#   함수 `_fbot_inbox_counts`(in-memory sqlite)·`_fbot_board_payload` 가 만든다.
#
# 실행: python3 plugins/fpm-core/services/hub/test_fbot_question_issue561.py
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


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  ok   {name}")
    else:
        FAIL += 1; print(f"  FAIL {name}")


def _grab_line(src, prefix):
    for line in src.splitlines():
        if line.strip().startswith(prefix):
            return line.strip()
    raise AssertionError(f"상수 미발견: {prefix}")


def _grab_js(src, name):
    """`function <name>(` 부터 짝 맞는 `}` 까지 — 서빙 원문 그대로."""
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


NOW = 1_000_000
QID = "fbotreq-999900-abcdef12"


def _db():
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE job (id TEXT, store TEXT, kind TEXT, status TEXT, payload TEXT, result TEXT,"
                " attempts INT, owner TEXT, lease_until INT, blocked_since INT, created_at INT)")

    def req(rid, owner, pl, status="open", result=None, ts=NOW - 100):
        con.execute("INSERT INTO job VALUES (?,?,?,?,?,?,0,?,NULL,NULL,?)",
                    (rid, "fbot", "fbot_request", status, json.dumps(pl, ensure_ascii=False), result, owner, ts))
    req("r1", "L1", {"from": "sess-a", "body": "보통 요청", "kind": "ask"})
    # 팀원 W1 → 팀장 L1 질문(prj3#Issue757 개정 — to_lead). owner = 묻는 봇
    req(QID, "W1", {"kind": "question", "from": "W1", "body": "어느 쪽으로 갈까? 1) 사과 2) 배",
                    "options": ["사과", "배"], "to_bot": "L1", "to_lead": "L1", "to_session": None,
                    "task": "Issue9", "dispatch": "d-9", "escalated_at": 123}, ts=NOW - 300)
    # 관리직 M1 → 의뢰 세션(사람) 질문. 그 세션에 결속된 봇이 없다 → 보드 안에 받는 봇이 없다
    req("fbotreq-999901-00000002", "M1", {"kind": "question", "from": "M1", "body": "<b>배포</b> 할까?",
                                           "options": [], "to_bot": None, "to_lead": None,
                                           "to_session": "sess-human-1234"}, ts=NOW - 200)
    # 이미 답한 질문 — 어디에도 나오지 않는다
    req("fbotreq-999902-00000003", "W1", {"kind": "question", "body": "끝난 질문", "to_bot": "L1"},
        result="done: 사과", ts=NOW - 900)
    return con


def _payload(c):
    def n(bid, role, state="working"):
        return {"bot_id": bid, "title": bid + " 핀봇", "role": role, "state": state, "root": bid}
    full = {"nodes": [n("W1", "worker"), n("L1", "lead", "checkout"), n("M1", "chief")], "dispatch": []}
    return server._fbot_board_payload(full, {"available": True, "seats": []}, inbox=c["inbox"], escal=c["escal"],
                                      now=NOW, inbox_items=c["items"], question_items=c.get("questions"))


def main():
    print("[A] 집계 — 질문은 인박스가 아니다 (prj3 계약: owner=묻는 봇 · 인박스 집계 제외)")
    c = server._fbot_inbox_counts(_db())
    check("인박스 수는 보통 요청만(L1 1) — 묻는 봇 W1·M1 이 자기 질문을 인박스로 세지 않는다", c["inbox"] == {"L1": 1})
    check("에스컬 수에도 질문이 섞이지 않는다", c["escal"] == {})
    check("인박스 목록 = 보통 요청만", [x["id"] for x in c["items"]] == ["r1"])
    qs = c.get("questions")
    check("미답 질문을 따로 낸다(답한 질문 제외, 오래된 순)",
          isinstance(qs, list) and [x["id"] for x in qs] == [QID, "fbotreq-999901-00000002"])

    print("\n[B] 페이로드 — 묻는 봇·받는 봇 양쪽에 싣는다")
    d = _payload(c)
    w1, l1, m1 = d["bots"]["W1"], d["bots"]["L1"], d["bots"]["M1"]
    check("W1 카드 인박스 0 (자기 질문 미집계)", w1.get("inbox_open") == 0)
    aw = w1.get("asking") or []
    check("묻는 봇 W1.asking = 그 질문", [q.get("id") for q in aw] == [QID])
    q = aw[0] if aw else {}
    check("질문 본문·선택지·작업·배분을 싣는다",
          q.get("options") == ["사과", "배"] and "사과" in (q.get("body") or "") and q.get("task") == "Issue9"
          and q.get("dispatch") == "d-9")
    check("받는 쪽 표시명 = 팀장 title", q.get("to_title") == "L1 핀봇")
    check("받는 봇이 보드에 있으면 묻는 봇 카드에서는 답하지 않는다(중복 창구 금지)", q.get("answer_here") is False)
    check("받는 봇 L1.questions = 그 질문", [x.get("id") for x in (l1.get("questions") or [])] == [QID])
    am = m1.get("asking") or []
    check("관리직 M1 질문(받는 봇 없음) → 묻는 봇 카드에서 답한다", am and am[0].get("answer_here") is True)
    check("받는 봇이 없으면 받는 쪽 = 의뢰 세션 앞 8자리", am and "sess-hum" in (am[0].get("to_title") or ""))
    check("요약 questions = 미답 질문 수(2)", d["summary"].get("questions") == 2)
    # 리뷰 LOW-2 — 묻는 봇·받는 봇 모두 보드에 없는 질문은 어느 카드에도 안 보인다. 배지 수가 화면과 어긋나면 안 된다
    ghost = dict(c, questions=list(c["questions"]) + [{"id": "fbotreq-999903-00000004", "owner": "GONE",
             "payload": json.dumps({"kind": "question", "body": "유령", "to_bot": "ALSO_GONE"}), "created_at": NOW}])
    check("보드에 안 보이는 질문은 요약 수에 넣지 않는다(배지 = 화면)", _payload(ghost)["summary"].get("questions") == 2)

    print("\n[C] 서빙 JS — 칩·답변 폼(node 실행)")
    src = server._FBOT_BOARD_JS
    check("카드 본문이 질문 칸을 그린다", "questionsHtml(b)" in _grab_js(src, "seatCardInner") if "function seatCardInner(" in src else False)
    check("답변은 /fbot-inbox-reply 로 보낸다", '"/fbot-inbox-reply"' in src)
    node = shutil.which("node")
    if not node:
        print("  skip node 미설치 — questionsHtml 실행 검증 생략")
    else:
        try:
            js = (_grab_line(src, "const esc") + "\n" + _grab_js(src, "questionRow") + "\n"
                  + _grab_js(src, "questionsHtml") + "\n")
        except (ValueError, AssertionError) as ex:
            js = None
            check(f"questionRow·questionsHtml 서빙 원문 존재 ({ex})", False)
        if js:
            js += "const d=" + json.dumps(d, ensure_ascii=False) + ";\n" + r"""
console.log(JSON.stringify({w1:questionsHtml(d.bots.W1), l1:questionsHtml(d.bots.L1), m1:questionsHtml(d.bots.M1),
  none:questionsHtml({asking:[],questions:[]})}));
"""
            with tempfile.TemporaryDirectory() as tmp:
                p = os.path.join(tmp, "q.js")
                with open(p, "w", encoding="utf-8") as f:
                    f.write(js)
                r = subprocess.run([node, p], capture_output=True, text=True)
            try:
                o = json.loads(r.stdout.strip().splitlines()[-1])
            except Exception:
                o = None
                check("questionsHtml node 실행: " + (r.stderr or "")[:300], False)
            if o:
                w, l, m = o["w1"], o["l1"], o["m1"]
                check("묻는 봇 카드: «❓ 질문 대기» 칩", "❓ 질문 대기" in w)
                check("묻는 봇 카드(받는 봇 있음): 답변 버튼 없음 + 받는 쪽 안내", "fb-qsend" not in w and "L1 핀봇" in w)
                check("받는 봇 카드: «받은 질문» 칸", "받은 질문" in l)
                check("선택지마다 버튼(data-q·data-opt)",
                      l.count("fb-qopt") == 2 and f'data-q="{QID}"' in l and 'data-opt="사과"' in l and 'data-opt="배"' in l)
                check("자유 입력 + «답하기»", "fb-qmsg" in l and "fb-qsend" in l and "답하기" in l)
                check("받는 봇 없는 질문은 묻는 봇 카드에서 답한다", "fb-qsend" in m and "❓ 질문 대기" in m)
                check("본문은 이스케이프한다", "<b>배포</b>" not in m and "&lt;b&gt;" in m)
                check("질문 없으면 칸을 그리지 않는다", o["none"] == "")

    print("\n[D] /fbot-inbox-reply 명령 조립 — 판정은 prj3 reply 가 한다(얇은 래퍼)")
    f = getattr(server, "_fbot_inbox_reply_cmd", None)
    if not f:
        check("_fbot_inbox_reply_cmd 존재", False)
    else:
        cmd, err = f("/x/fbot-inbox.py", {"id": QID, "body": " 사과 "})
        check("정상 → reply --id --status done --body --by hub:board",
              err is None and cmd[1:] == ["/x/fbot-inbox.py", "reply", "--id", QID, "--status", "done",
                                          "--body", "사과", "--by", "hub:board"])
        check("id 형식 밖 → 거부(임의 인자 주입 차단)", f("/x/fbot-inbox.py", {"id": "--status", "body": "x"})[0] is None)
        check("빈 답 → 거부", f("/x/fbot-inbox.py", {"id": QID, "body": "  "})[0] is None)
        check("과대 답(4000자 초과) → 거부", f("/x/fbot-inbox.py", {"id": QID, "body": "x" * 4001})[0] is None)
        try:
            bad = [f("/x/fbot-inbox.py", b)[0] for b in (["x"], "str", 5, None)]
            check("dict 아닌 JSON 본문 → 예외 없이 거부(리뷰 LOW-1)", bad == [None, None, None, None])
        except Exception as ex:
            check(f"dict 아닌 JSON 본문 → 예외 없이 거부(리뷰 LOW-1) — {type(ex).__name__}", False)
    check("POST 라우트 배선", 'parsed.path == "/fbot-inbox-reply"' in open(server.__file__, encoding="utf-8").read())

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
