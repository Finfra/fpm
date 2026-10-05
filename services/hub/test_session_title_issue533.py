#!/usr/bin/env python3
# test_session_title_issue533.py — Issue533 회귀 테스트
#
# ⚠️ 글로벌 SCAR 아님 (___pm 프로젝트 소유). VSCode 채팅 rename(custom-title)이
#   hub 세션 카드 제목에 반영되는지 검증한다.
#
# 배경: rename 은 JSONL 에 custom-title 로 남지만 Claude Code 가 매 턴 그 직후
#   ai-title 을 다시 append 한다. 역방향 스캔이 처음 만난 ai-title 을 채택하던
#   _session_ai_title 은 rename 을 영원히 가렸다.
#
# 실행: python3 plugins/fpm-core/services/hub/test_session_title_issue533.py
"""server.py 세션 제목 우선순위 (Issue533) 단위 테스트."""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server  # noqa: E402

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


def _ai(t):
    return {"type": "ai-title", "aiTitle": t, "sessionId": "s"}


def _custom(t):
    return {"type": "custom-title", "customTitle": t, "sessionId": "s"}


def _user(i):
    return {"type": "user", "message": {"content": f"prompt {i}"}}


def title_of(records):
    """레코드 배열로 임시 JSONL 을 만들고 _session_ai_title 결과를 반환."""
    tmp = tempfile.mkdtemp()
    sid = f"t{abs(hash(json.dumps(records))) % 10**9}"
    path = os.path.join(tmp, f"{sid}.jsonl")
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with server._sid_path_cache_lock:
        server._sid_path_cache[sid] = path
    return server._session_ai_title("", sid)


print("Issue533 세션 제목 우선순위")

# rename 없음 → ai-title
check("rename 없으면 aiTitle", title_of([_user(1), _ai("자동 제목"), _user(2)]) == "자동 제목")

# 실측 배치: custom-title 뒤에 ai-title 이 재append 된다
recs = [_user(1), _ai("자동 제목"), _user(2), _custom("바꾼 이름"), _custom("바꾼 이름"), _user(3)]
for i in range(4, 8):
    recs += [_custom("바꾼 이름"), _ai("자동 제목"), _user(i)]
check("rename 후 ai-title 재append 돼도 customTitle", title_of(recs) == "바꾼 이름")

# 재rename → 최신 customTitle
recs2 = recs + [_custom("두 번째 이름"), _ai("자동 제목"), _user(9)]
check("재rename 시 최신 customTitle", title_of(recs2) == "두 번째 이름")

print(f"\nPASS {PASS} / FAIL {FAIL}")
sys.exit(1 if FAIL else 0)
