#!/usr/bin/env python3
# test_token_redact.py — Issue394 회귀 테스트
#
# ⚠️ 글로벌 SCAR 아님 (___pm 프로젝트 소유). 서버가 프로젝트 폴더로 내보내는
#   텍스트에서 hub 토큰이 지워지는지를 고정한다. 유일하게 살아 있던 유입 경로가
#   턴 아카이브(`_write_turn_archive`)였고, 그 길목의 그물이 `redact_tokens()` 다.
#
# 실행: python3 services/hub/test_token_redact.py
"""server.py 토큰 레닥션 (Issue394) 단위 테스트."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server  # noqa: E402

PASS = 0
FAIL = 0

# 테스트 전용 더미 — 실제 발급 토큰을 쓰지 않는다(값이 리포지토리에 남는 것 자체가 본 이슈다)
FAKE = "0123456789abcdef0123456789abcdef"
FAKE2 = "fedcba9876543210fedcba9876543210"


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok   {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}")


def has_hex(s):
    """32자 hex 가 통째로 남아 있는지 — 레닥션 실패의 유일한 판정 기준."""
    return FAKE in s or FAKE2 in s


print("== 문맥 규칙 (token=<32hex>) ==")
u = f"http://127.0.0.1:9876/s/6a047432/abc/live?token={FAKE}"
check("쿼리스트링 token= 마스킹", not has_hex(server.redact_tokens(u)))
check("URL 나머지는 보존", "/s/6a047432/abc/live" in server.redact_tokens(u))

check("JS 대입 const TOKEN = \"..\"",
      not has_hex(server.redact_tokens(f'const TOKEN = "{FAKE}";')))
check("shell export TOKEN=\"..\"",
      not has_hex(server.redact_tokens(f'export TOKEN="{FAKE}"')))
check("yaml token: ..", not has_hex(server.redact_tokens(f"token: {FAKE}")))
check("대소문자 무관(TOKEN=)", not has_hex(server.redact_tokens(f"TOKEN={FAKE}")))

multi = f"a token={FAKE} b token={FAKE2} c"
red = server.redact_tokens(multi)
check("한 문서에 여러 건이면 전부", not has_hex(red))
check("여러 건 마스킹 후에도 주변 텍스트 유지", red.startswith("a ") and red.endswith(" c"))

print("== 값 대조 (문맥 없이 맨 hex 로 적힌 경우) ==")
with server.projects_lock:
    saved = dict(server.projects)
    server.projects.clear()
    server.projects["deadbeef"] = {"cwd": "/tmp/x", "token": FAKE}
try:
    check("등록된 토큰은 문맥 없어도 마스킹",
          not has_hex(server.redact_tokens(f"값은 {FAKE} 입니다")))
    check("미등록 hex 는 문맥 없으면 보존(오탐 방지)",
          FAKE2 in server.redact_tokens(f"md5 는 {FAKE2} 다"))
finally:
    with server.projects_lock:
        server.projects.clear()
        server.projects.update(saved)

print("== 경계 ==")
check("빈 문자열", server.redact_tokens("") == "")
check("None 안전", server.redact_tokens(None) is None)
check("토큰 없는 본문은 무변경",
      server.redact_tokens("커밋 `abc1234` 로 반영했습니다.")
      == "커밋 `abc1234` 로 반영했습니다.")
check("40자 git 해시는 무관",
      "a" * 40 in server.redact_tokens("hash " + "a" * 40))

print(f"\nPASS {PASS} / FAIL {FAIL}")
sys.exit(1 if FAIL else 0)
