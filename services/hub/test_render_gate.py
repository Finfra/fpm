#!/usr/bin/env python3
# test_render_gate.py — Issue353_3 M3 회귀 테스트
#
# ⚠️ 글로벌 SCAR 아님 (___pm 프로젝트 소유). 적응형 렌더 게이트(G안)의
#   기계 판정 규칙을 검증한다 — 판정 주체가 LLM 이 아니라 서버임을 코드로 고정.
#
# 실행: python3 services/hub/test_render_gate.py
"""render_gate.py (M3 서버 규칙 엔진) 단위 테스트."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render_gate as rg  # noqa: E402

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


def blocks(*texts, activities=0):
    out = [{"kind": "text", "text": t} for t in texts]
    out += [{"kind": "activity", "text": "Bash"} for _ in range(activities)]
    return out


SHORT = blocks("완료했습니다.")
CONFIRM = blocks("네, 맞습니다.\n커밋 `abc1234` 로 반영했습니다.")
TABLE = blocks("결과는 아래와 같습니다.\n\n| 항목 | 값 |\n| :--- | :--- |\n| a | 1 |")
CODE = blocks("이렇게 고쳤습니다.\n\n```python\ndef f():\n    return 1\n```")
MERMAID = blocks("흐름입니다.\n\n```mermaid\nflowchart LR\n  A --> B\n```")
LIST3 = blocks("정리하면:\n\n* 첫째 항목\n* 둘째 항목\n* 셋째 항목")
LONG = blocks("\n".join(f"{i}번째 설명 문장입니다." for i in range(50)))
PLAIN_MID = blocks("\n".join(f"{i}번째 문장." for i in range(10)))

# --- measure: 활동 블록은 분량에 포함하지 않는다 ---
m = rg.measure(blocks("한 줄", activities=30))
check("measure: activity 는 분량 계산 제외", m["lines"] == 1 and m["text_blocks"] == 1)
m = rg.measure(TABLE)
check("measure: 표 감지", m["rich"]["table"])
m = rg.measure(MERMAID)
check("measure: mermaid 는 code 와 별개로 감지",
      m["rich"]["mermaid"] and m["rich"]["code"])
m = rg.measure(LIST3)
check("measure: 목록 3항 이상 감지", m["rich"]["list3"] and m["list_items"] == 3)

# --- always ---
check("always: 단답도 렌더", rg.decide(SHORT, "always")["render"])
check("always: 빈 응답도 렌더", rg.decide([], "always")["render"])

# --- short ---
check("short: 1줄 단답 생략", rg.decide(SHORT, "short")["render"] is False)
check("short: 2줄 확인 응답 생략", rg.decide(CONFIRM, "short")["render"] is False)
check("short: 짧아도 표가 있으면 렌더", rg.decide(TABLE, "short")["render"])
check("short: 4줄 이상은 렌더", rg.decide(PLAIN_MID, "short")["render"])

# --- page (기본) ---
check("page: 단답 생략", rg.decide(SHORT, "page")["render"] is False)
check("page: 중간 길이 평문 생략", rg.decide(PLAIN_MID, "page")["render"] is False)
check("page: 40줄 초과 렌더", rg.decide(LONG, "page")["render"])
check("page: 표 포함 렌더", rg.decide(TABLE, "page")["render"])
check("page: 코드펜스 포함 렌더", rg.decide(CODE, "page")["render"])
check("page: mermaid 포함 렌더", rg.decide(MERMAID, "page")["render"])
check("page: 목록 3항 이상 렌더", rg.decide(LIST3, "page")["render"])
r = rg.decide(TABLE, "page")
check("page: 사유에 판정 근거 명시", "리치" in r["reason"] and "table" in r["reason"])

# --- doc ---
check("doc: 문서 산출 없으면 장문이어도 생략",
      rg.decide(LONG, "doc", created_docs=0)["render"] is False)
check("doc: 문서 산출 있으면 단답이어도 렌더",
      rg.decide(SHORT, "doc", created_docs=1)["render"])

# --- 오버라이드 (사용자 우선) ---
check("..show 는 doc 단계 생략을 뒤집음",
      rg.decide(SHORT, "doc", created_docs=0, override="show")["render"])
check("..text 는 always 렌더를 뒤집음",
      rg.decide(LONG, "always", override="text")["render"] is False)
check("오버라이드 사유 기록",
      "오버라이드" in rg.decide(SHORT, "page", override="show")["reason"])

# --- 방어 ---
check("알 수 없는 단계는 page 로 폴백",
      rg.decide(SHORT, "무슨단계")["level"] == "page")
check("빈 블록 목록도 안전", rg.decide([], "page")["render"] is False)
check("판정 결과에 metrics 동봉", "metrics" in rg.decide(TABLE, "page"))

# --- Issue356_1: render_display 정규화 (render_tab_mode 와의 이름 충돌 해소) ---
check("신 값 live 통과", rg.normalize_display("live") == ("live", ""))
check("신 값 archive 통과", rg.normalize_display("archive") == ("archive", ""))
check("신 값 auto 통과", rg.normalize_display("auto") == ("auto", ""))

m, w = rg.normalize_display("live-tab")
check("구 값 live-tab → live 매핑", m == "live" and w)
check("구 값 매핑 시 경고 문구 제공 (조용한 매핑 금지)", "구 값" in w and "live" in w)
m, w = rg.normalize_display("browser-tab")
check("구 값 browser-tab → archive 매핑", m == "archive" and w)

m, w = rg.normalize_display("hub-internal")
check("타 축(render_tab_mode) 값이 섞여 들어오면 auto 폴백 + 경고",
      m == "auto" and "알 수 없는 값" in w)
check("빈 값은 경고 없이 auto", rg.normalize_display("") == ("auto", ""))
check("None 도 안전", rg.normalize_display(None) == ("auto", ""))
check("DISPLAY_MODES 에 구 값이 남아 있지 않음",
      "live-tab" not in rg.DISPLAY_MODES and "browser-tab" not in rg.DISPLAY_MODES)

print()
print(f"PASS={PASS} FAIL={FAIL}")
sys.exit(1 if FAIL else 0)
