#!/usr/bin/env python3
# test_mq_table_layout_issue656.py — Issue656 회귀 테스트
#
# ⚠️ 글로벌 SCAR 아님 (___pm 프로젝트 소유). `/mq` 큐 표의 **내용 열 가독성**을 검증한다.
#   증상: 나머지 열이 전부 nowrap 이라 표가 가로로 넘치고, sticky «처리» 열이 내용 열 오른쪽을
#   덮어 본문이 잘려 보였다. 지키는 것은 다음 셋이다:
#     ① 내용 열은 최소 폭(min-width)을 갖고 안쪽에서 줄바꿈된다(overflow-wrap:anywhere)
#     ② 폭을 먹는 상태·출처 열은 접힌다(nowrap 해제) — Issue498·500·501 의 `<br>`·2줄 접기는 보존
#     ③ (Issue657 로 계약 변경) 좁은 창에서도 카드형으로 바뀌지 않는다 — 내용은 끝까지 «열».
#        폭이 모자라면 표 영역만 가로 스크롤하고 처리 열 sticky 는 유지된다
#
# 실행: python3 plugins/fpm-core/services/hub/test_mq_table_layout_issue656.py
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server  # noqa: E402

HTML = server._MQ_PAGE_HTML
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


def rule(selector):
    """`selector{...}` 본문 — 미디어 쿼리 밖(첫 출현) 기준. 없으면 ''."""
    m = re.search(re.escape(selector) + r"\{([^}]*)\}", HTML)
    return m.group(1) if m else ""


def media_block(query):
    """`@media(<query>){ ... }` 중괄호 균형 본문."""
    i = HTML.find("@media(" + query + ")")
    if i < 0:
        return ""
    j = HTML.find("{", i)
    depth, k = 0, j
    while k < len(HTML):
        depth += HTML[k] == "{"
        depth -= HTML[k] == "}"
        if depth == 0:
            return HTML[j + 1:k]
        k += 1
    return ""


print("① 내용 열")
msg = rule("td.msg")
check("td.msg width:100% 유지(Issue501)", "width:100%" in msg)
check("td.msg min-width 확보", re.search(r"min-width:\s*\d+(\.\d+)?rem", msg) is not None)
check("td.msg overflow-wrap:anywhere", "overflow-wrap:anywhere" in msg)
check("큐 표는 고정 레이아웃(내용 최소 폭 합으로 넘치지 않음)", "table-layout:fixed" in rule("table.mqq"))
check("처리 열 폭이 못 박혀 있다", "width:" in rule("table.mqq th:nth-child(6)"))
check("승인 줄 본문 span 이 줄어든다(min-width:0)", "ul.needli>span{min-width:0" in HTML.replace(" ", ""))

print("② 상태·출처 열")
check("td.srcq nowrap 해제", "nowrap" not in rule("td.srcq"))
check("td.stty nowrap 해제", "nowrap" not in rule("td.stty"))
check("srcCell 의 <br> 분절 보존", '<br><span class="from">' in HTML)
check("td.id2 nowrap 보존(Issue498)", "nowrap" in rule("td.id2"))
check("td.due2 nowrap 보존(Issue500)", "nowrap" in rule("td.due2"))

print("③ 좁은 창 — 카드형 금지·표 형태 유지 (Issue657)")
check("큐 표에 식별 클래스 mqq", '<table class="mqq"><thead>' in HTML)
check("1180px 카드 미디어 쿼리 철회", media_block("max-width:1180px") == "")
for q in ("max-width:1200px", "max-width:1010px"):
    blk = media_block(q)
    check(f"{q} 블록은 열 폭·sticky 만 — 카드(grid·block 전환) 없음",
          blk != "" and "display:grid" not in blk.replace(" ", "") and "display:block" not in blk.replace(" ", "")
          and "grid-area" not in blk)
check("스크롤 구간(≤1010px)은 처리 열 sticky 해제 — 내용 열 끝을 덮지 않는다",
      "position:static" in media_block("max-width:1010px"))
check("어떤 규칙도 큐 행을 grid·block 카드로 바꾸지 않는다",
      "table.mqqtbodytr{display:grid" not in HTML.replace(" ", "")
      and "table.mqq,table.mqqtbody{display:block}" not in HTML.replace(" ", ""))
check("내용 열 grid-area(msg) 이동 없음", "grid-area:msg" not in HTML.replace(" ", ""))
check("표 영역만 가로 스크롤 — 래퍼 .mqwrap overflow-x:auto", "overflow-x:auto" in rule(".mqwrap"))
check("표 래퍼가 큐 표를 감싼다", '<div class="mqwrap"><table class="mqq">' in HTML)
check("표 최소 폭 확보(내용 열이 아래로 떨어지지 않게)", re.search(r"min-width:\s*\d+(\.\d+)?rem", rule("table.mqq")) is not None)
check("처리 열 sticky 유지", "position:sticky" in rule("th:last-child,td:last-child"))
check("스케줄·잡 표(table.jobs)는 건드리지 않는다", "table.jobs" not in media_block("max-width:600px"))

print(f"\n{PASS} pass / {FAIL} fail")
sys.exit(1 if FAIL else 0)
