#!/usr/bin/env python3
# test_live_pid_promote.py — Issue397 회귀 테스트
#
# ⚠️ 글로벌 SCAR 아님 (___pm 프로젝트 소유). 죽은·소실 live_pid 를
#   gc_meta.shell_pid(등록 pid 의 부모)로 승격하는 방어선을 검증한다:
#   - _claude_proc_like: claude 세션 프로세스 판정 (오승격 게이트)
#   - _try_promote_live_pid: 승격 성공/실패/1회 가드(promote_tried)
#
# 배경: 훅이 단명 wrapper pid 를 등록하면(prj3#428) live_pid 가 pop 되고
#   세션이 LIVE_TTL 강등으로 카드에서 사라졌다(prj9a 실측). ps 는 자기 자신
#   (파이썬 테스트 프로세스)을 비-claude 표본으로 쓰고, claude 판정은
#   _claude_proc_like 를 monkeypatch 하여 실제 claude 프로세스 없이 검증한다.
#
# 실행: python3 services/hub/test_live_pid_promote.py
"""server.py live_pid 승격 (Issue397) 단위 테스트."""
import os
import sys

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


ME = os.getpid()          # 살아있는 비-claude 프로세스 (python3)
DEAD = 99999999           # 존재하지 않는 pid

# --- _claude_proc_like: 판정 게이트 (순수 ps) ---
print("_claude_proc_like")
check("살아있는 python3 은 비-claude", server._claude_proc_like(ME) is False)
check("죽은 pid 는 False", server._claude_proc_like(DEAD) is False)
check("비정수 입력은 False", server._claude_proc_like("abc") is False)
check("None 은 False", server._claude_proc_like(None) is False)

# --- _try_promote_live_pid: 승격 로직 (claude 판정은 monkeypatch) ---
print("_try_promote_live_pid")
_orig = server._claude_proc_like

# 1) 성공 경로: shell_pid 생존 + claude 판정 True → live_pid 교체
server._claude_proc_like = lambda pid: True
entry = {"content_type": "live", "live_pid": DEAD,
         "gc_meta": {"for_pid": DEAD, "shell_pid": ME}}
with server.sessions_lock:
    server.sessions[("testh397", "sid-a")] = entry
got = server._try_promote_live_pid("testh397", "sid-a", entry)
check("승격 성공 → 새 pid 반환", got == ME)
check("entry.live_pid 교체", entry["live_pid"] == ME)
check("gc_meta.for_pid 동기", entry["gc_meta"]["for_pid"] == ME)
check("promote_tried 마킹", entry["gc_meta"]["promote_tried"] is True)

# 2) 1회 가드: 같은 entry 재시도는 즉시 None (ps 재실행 없음)
got2 = server._try_promote_live_pid("testh397", "sid-a", entry)
check("재시도는 None (1회 가드)", got2 is None)

# 3) 실패 경로: shell_pid 사망 → None + promote_tried 마킹
entry_dead = {"content_type": "live",
              "gc_meta": {"for_pid": DEAD, "shell_pid": DEAD}}
with server.sessions_lock:
    server.sessions[("testh397", "sid-b")] = entry_dead
check("shell_pid 사망 → None",
      server._try_promote_live_pid("testh397", "sid-b", entry_dead) is None)
check("실패도 promote_tried 마킹", entry_dead["gc_meta"]["promote_tried"] is True)

# 4) 오승격 게이트: shell_pid 생존이지만 비-claude(extension host 등) → None
server._claude_proc_like = _orig
entry_host = {"content_type": "live",
              "gc_meta": {"for_pid": DEAD, "shell_pid": ME}}
with server.sessions_lock:
    server.sessions[("testh397", "sid-c")] = entry_host
check("비-claude 부모는 승격 거부 (오승격 차단)",
      server._try_promote_live_pid("testh397", "sid-c", entry_host) is None)

# 5) gc_meta 부재 → None (예외 없이)
check("gc_meta 없음 → None",
      server._try_promote_live_pid("testh397", "sid-d", {"content_type": "live"}) is None)

# 정리
with server.sessions_lock:
    for s in ("sid-a", "sid-b", "sid-c"):
        server.sessions.pop(("testh397", s), None)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
