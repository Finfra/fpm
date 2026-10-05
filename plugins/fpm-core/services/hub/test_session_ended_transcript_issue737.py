#!/usr/bin/env python3
# test_session_ended_transcript_issue737.py — prj3#Issue737 회귀 테스트
#
# ⚠️ 글로벌 SCAR 아님 (___pm 프로젝트 소유). 설계 SSOT 는 prj3 `_doc_arch/hub-mode-arch.md`.
#
# 왜 — 2026-09-27 21:18 사용자가 hub 의 prj13 세션 링크 `/s/7d7cc557/ec180913-…` 을 열었으나
#   «초기 로드 중… / 대기 중…» 에서 멈췄다. 그 세션은 21:17:49 `session_end` 로 sessions 에서 prune 됐고
#   `/data` 는 404 `session not registered` 만 냈다 — 세션이 **끝났다는 사실**도, 디스크에 남은
#   transcript(`~/.claude/projects/<enc>/<sid>.jsonl`)도 보여주지 않았다. pm-do `-p` 몸체는 수 분 만에
#   끝나므로 봇 세션 링크는 거의 항상 이 상태로 열린다.
#
# 검증 대상:
#   A. sessions 에 없고 transcript 가 디스크에 있으면 200 + ended=True + 종료 배너 + transcript
#   B. transcript 도 없으면 종전대로 404 `session not registered` (회귀 가드)
#   C. sessions 에 살아 있는 엔트리가 있으면 종전 경로 그대로(ended 키 없음)
#   D. SPA 셸이 `ended` 를 상태 문구로 고정한다(문자열 계약)
#
# 실행: python3 services/hub/test_session_ended_transcript_issue737.py
import json
import os
import sys
import tempfile
from urllib.parse import urlparse as _up

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server  # noqa: E402

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok   {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}{(' — ' + detail) if detail else ''}")


class _FakeHandler(server.Handler):
    def __init__(self):
        self.client_address = ("127.0.0.1", 0)
        self.responses = []

    def _send_json(self, status, body):
        self.responses.append((status, body))


_TMP = tempfile.mkdtemp(prefix="___pm-issue737-")
server.SESSIONS_FILE = os.path.join(_TMP, "sessions.json")
server.PROJECTS_BASE = os.path.join(_TMP, "projects")
server.DASH_REGISTRY = os.path.join(_TMP, "dash-registry.json")
CWD = os.path.join(_TMP, "fGoogleSheet")
os.makedirs(CWD, exist_ok=True)
H = server.cwd_hash(CWD)
TOKEN = "tok737"
SID_ENDED = "ec180913-ended-0000-0000-000000000737"
SID_GONE = "00000000-gone-0000-0000-000000000737"
SID_LIVE = "11111111-live-0000-0000-000000000737"

server.projects.clear()
server.sessions.clear()
server.projects[H] = {"cwd": CWD, "token": TOKEN, "name": "fGoogleSheet"}
server._sid_path_cache.clear()

# transcript 픽스처 — Claude Code projects 디렉토리 인코딩 규칙(비영숫자 → '-')
import re
enc = re.sub(r"[^a-zA-Z0-9]", "-", CWD)
os.makedirs(os.path.join(server.PROJECTS_BASE, enc), exist_ok=True)
with open(os.path.join(server.PROJECTS_BASE, enc, f"{SID_ENDED}.jsonl"), "w", encoding="utf-8") as f:
    f.write(json.dumps({"type": "user", "message": {"role": "user", "content": "Issue58 진행"}}) + "\n")
    f.write(json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "text", "text": "**Issue58 완료** — push 는 사용자 몫"}]}}) + "\n")


def _get(sid):
    fh = _FakeHandler()
    fh._handle_session_get(_up(f"/s/{H}/{sid}/data?token={TOKEN}"))
    return fh.responses[-1]


print("--- A: 종료 세션(sessions 부재·transcript 존재) ---")
st, body = _get(SID_ENDED)
check("A1: 404 가 아니라 200", st == 200, f"status={st} body={body}")
check("A2: ended=True 로 종료를 알린다", body.get("ended") is True)
check("A3: ended_at 이 있다(transcript mtime)", isinstance(body.get("ended_at"), (int, float)) and body.get("ended_at") > 0)
check("A4: mode A / content_type response (SPA 가 그대로 렌더)", body.get("mode") == "A" and body.get("content_type") == "response")
check("A5: 본문에 종료 배너", "세션 종료" in (body.get("content") or ""))
check("A6: 본문에 transcript(마지막 assistant 텍스트)", "push 는 사용자 몫" in (body.get("content") or ""))
check("A7: GC 불가(죽일 대상이 없다)", body.get("can_gc") is False)

print("--- B: transcript 도 없으면 종전 404 ---")
st, body = _get(SID_GONE)
check("B1: 404", st == 404, f"status={st}")
check("B2: 종전 오류 문구 유지", body.get("error") == "session not registered")

print("--- C: 살아 있는 엔트리는 종전 경로(회귀 가드) ---")
server.sessions[(H, SID_LIVE)] = {"content_type": "response", "content": "<p>live</p>", "mode": "A",
                                  "updated": 1, "capabilities": {}, "live_pid": os.getpid()}
st, body = _get(SID_LIVE)
check("C1: 200", st == 200)
check("C2: ended 키 없음", "ended" not in body)
check("C3: content 그대로", body.get("content") == "<p>live</p>")

print("--- D: SPA 셸 문자열 계약 ---")
src = open(server.__file__, encoding="utf-8").read()
check("D1: reload() 가 d.ended 를 본다", "d.ended" in src)
check("D2: 종료 상태 문구가 있다", "세션 종료됨" in src)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
