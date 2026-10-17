#!/usr/bin/env python3
# test_fbot_ledger_details_issue629.py — Issue629 회귀 테스트 (fbot-map «미종결 원장» 배너 접기)
#
# 명제: 미종결 원장은 건마다 <details> 한 줄 제목(상태 칩·발신→수신·본문 첫 줄 80자·경과)만 보이고,
#   본문 전문·«원장 종결» 버튼은 펼친 안쪽에만 있다. 폴링 갱신(location.reload) 뒤에도 펼침 상태는 job id 로 유지된다.
#
# 실행: python3 plugins/fpm-core/services/hub/test_fbot_ledger_details_issue629.py
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server  # noqa: E402

PASS = 0
FAIL = 0
SRC = open(server.__file__, encoding="utf-8").read()


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok   {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}")


BODY = "첫 줄 지시문 " + "가" * 120 + "\n둘째 줄 <b>본문</b>\n셋째 줄"
fn = getattr(server, "_fbot_ledger_details", None)
check("헬퍼 _fbot_ledger_details 존재", callable(fn))
if fn:
    h = fn("미종결", "팀장A", "워커B", BODY, " · 2.0시간 경과", "job-1", "대상 퇴근",
           close_btn='<button class="fm-close-btn" data-job="job-1">원장 종결</button>')
    m = re.search(r"<summary>(.*?)</summary>", h, re.S)
    summ = m.group(1) if m else ""
    plain = re.sub(r"<[^>]+>", "", summ)
    check("<details data-job> 로 감싼다", h.startswith("<details") and 'data-job="job-1"' in h)
    check("details 는 기본 접힘(open 속성 없음)", " open" not in h.split(">", 1)[0])
    check("summary 에 칩·발신→수신·경과", "미종결" in plain and "팀장A" in plain and "워커B" in plain
          and "→" in plain and "2.0시간 경과" in plain)
    check("summary 의 본문 요지는 80자 이하 한 줄", "둘째 줄" not in summ and "\n" not in summ
          and len(plain) < 80 + 60)
    check("summary 안에 종결 버튼 없음", "fm-close-btn" not in summ)
    body_part = h.split("</summary>", 1)[1]
    check("본문 전문은 details 안(summary 밖)·pre-wrap", "둘째 줄" in body_part and "셋째 줄" in body_part
          and "pre-wrap" in h.split("<summary>", 1)[0] + body_part)
    check("본문 HTML 이스케이프", "<b>본문</b>" not in h and "&lt;b&gt;" in h)
    check("종결 버튼은 펼친 본문 안", "fm-close-btn" in body_part)
    h2 = fn("하위 보류", "A", "B", "", "", "", "")
    check("본문·job id 없어도 렌더(버튼 없음)", "<details" in h2 and "fm-close-btn" not in h2)

# 배너 사용처: 미종결 원장 <ul> 의 li 직접 작성 대신 헬퍼 사용
seg = SRC[SRC.index("if dl[\"soft_count\"]:"):SRC.index("if data[\"unknown_root\"]:")]
check("미종결 배너가 헬퍼를 사용", seg.count("_fbot_ledger_details(") >= 3)
check("열림 상태 유지 스크립트(sessionStorage·job id)", "fmOpenLedgers" in SRC and "sessionStorage" in SRC
      and "details.fm-led" in SRC)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
