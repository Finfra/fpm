#!/usr/bin/env python3
# test_fbot_inbox_badge.py — 보드 «미종결·인박스» 배지 → 목록 연결 회귀 테스트
#
# ⚠️ 글로벌 SCAR 아님 (___pm 프로젝트 소유).
# 왜: 배지가 숫자만 보이고 목록으로 이어지지 않았다(2026-09-27 사용자 질의). 인박스 수는 서버가
#   `open + result IS NULL` 로 세는데 그 행이 payload 에 없어 화면이 같은 기준의 목록을 만들 수 없었다.
#   수와 목록이 다른 기준이면 «인박스 3» 옆에 2건만 보이는 식으로 조용히 갈린다.
#
# 실행: python3 services/hub/test_fbot_inbox_badge.py
import os
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


def main():
    print("[payload — 인박스 목록이 수와 같은 기준으로 실린다]")
    full = {"nodes": [{"bot_id": "narae", "title": "나래(총괄핀봇)", "role": "chief", "state": "working"}], "edges": []}
    items = [
        {"id": "r1", "owner": "narae", "payload": '{"from_session":"sess-a","body":"첫 요청"}', "created_at": 100},
        {"id": "r2", "owner": "narae", "payload": '{"from":"fbot-lead-cg","body":"둘째","escalated_at":200}', "created_at": 150},
    ]
    try:
        d = server._fbot_board_payload(full, {}, inbox={"narae": 2}, inbox_items=items, now=1000)
    except TypeError as e:
        d = {}; print(f"       ({e})")
    inbox = d.get("inbox") if isinstance(d, dict) else None
    check("payload 에 inbox 배열", isinstance(inbox, list))
    inbox = inbox or []
    check("건수 = summary.inbox_open", len(inbox) == (d.get("summary") or {}).get("inbox_open", -1))
    r1 = next((x for x in inbox if x.get("id") == "r1"), {})
    check("owner·owner_title", r1.get("owner") == "narae" and r1.get("owner_title") == "나래(총괄핀봇)")
    check("보낸 이 — from 없으면 from_session", r1.get("from") == "sess-a")
    check("요지 body", r1.get("body") == "첫 요청")
    r2 = next((x for x in inbox if x.get("id") == "r2"), {})
    check("에스컬 표시", r2.get("escalated") is True and r1.get("escalated") is False)
    check("오래된 요청이 먼저", [x.get("id") for x in inbox] == ["r1", "r2"])
    d0 = server._fbot_board_payload(full, {}, now=1000)
    check("인박스 없으면 빈 배열(키는 유지)", d0.get("inbox") == [])

    print("\n[화면 — 배지가 목록으로 이어진다]")
    src = open(server.__file__, encoding="utf-8").read()
    # Issue571 — 배지 HTML 은 summaryHtml 의 go(key,…) 한 곳에서 나온다. data-go 버튼이 실제로 나오는지는
    #   test_fbot_chip_panel_issue571.py 가 서빙 JS 를 node 로 실행해 판정한다(여기는 배선만)
    check("미종결 배지 클릭 대상(data-go=unsettled)", 'go("unsettled"' in src and 'data-go="${k}"' in src)
    check("인박스 배지 클릭 대상(data-go=inbox)", 'go("inbox"' in src)
    check("인박스 패널 = 공용 목록 패널(Issue571)", 'id="fb-chip-panel"' in src and 'if(key==="inbox")' in src)
    check("미종결 배너로 스크롤", ".fm-warn.fm-open" in src and "scrollIntoView" in src)
    # 실측(2026-09-27 ego-browser): behavior:"smooth" 는 2초가 지나도 0px — 즉시 스크롤은 3360px 이동
    check("미종결 스크롤은 즉시(smooth 금지 — 환경에 따라 안 움직인다)",
          'scrollIntoView({behavior:"smooth"' not in src and 'w.scrollIntoView({block:"start"})' in src)
    # 요약 바는 SSE·폴링마다 다시 그려진다(실측 5초 1회) — 같은 내용이면 버튼을 교체하지 않는다
    check("요약 바는 내용이 바뀔 때만 다시 그린다", 'if(state._sumHtml!==html){ el("fb-summary").innerHTML=html; state._sumHtml=html; }' in src)

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
