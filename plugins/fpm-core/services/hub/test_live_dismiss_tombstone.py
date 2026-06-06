#!/usr/bin/env python3
# test_live_dismiss_tombstone.py — Issue135 회귀 테스트 (live 카드 dismiss 부활 차단)
#
# ⚠️ 글로벌 SCAR 아님 (___pm 프로젝트 소유). live(claude) 세션 수동 dismiss 가
#   tombstone(LIVE_DISMISSED)으로 재등록 부활을 차단하는지 검증.
#
# 실행: python3 services/hub/test_live_dismiss_tombstone.py
"""Issue135: dismiss 는 sessions.pop 만 해, 살아있는 claude native 프로세스의
재등록(register/heartbeat)으로 카드가 부활했다(Issue132 후속 결함). dismiss 시
(h|sid) tombstone 기록 + collect 표시 제외 + TTL 만료 자동 해제를 검증.

검증 대상:
  A. _collect_live_sessions — tombstone 된 live 세션은 pid 생존이어도 미노출
  B. _collect_live_sessions — tombstone 안 된 live 세션은 정상 노출 (회귀 가드)
  C. TTL 만료 tombstone 은 무효 → 세션 재노출 + 만료분 lazy purge
  D. _handle_session_dismiss — tombstone 기록 + 재등록(부활)분 collect 제외 (E2E)
"""
import json  # noqa: F401  (픽스처 호환)
import os
import shutil
import sys
import tempfile
import time
from urllib.parse import urlparse as _up

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


# --- 격리 픽스처: 임시 state dir 로 server 전역 교체 ---
_TMP = tempfile.mkdtemp(prefix="___pm-issue135-")
server.LIVE_DISMISSED = os.path.join(_TMP, "live-dismissed.json")
server.SESSIONS_FILE = os.path.join(_TMP, "sessions.json")

ALIVE = os.getpid()        # 자기 자신 → _pid_alive True (live_pid 게이트 통과)
CWD = os.path.join(_TMP, "proj")
os.makedirs(CWD, exist_ok=True)
H = server.cwd_hash(CWD)


def _reset_world():
    server.projects.clear()
    server.sessions.clear()
    server.projects[H] = {"cwd": CWD, "token": "tok", "name": "proj",
                          "color": "#ccc", "registered_at": 0}
    if os.path.exists(server.LIVE_DISMISSED):
        os.remove(server.LIVE_DISMISSED)


def _live_session(pid=ALIVE, label="작업중"):
    now = time.time()
    return {"mode": "A", "content_type": "live", "content": "",
            "capabilities": {"source": "prompt", "kind": "live"},
            "created": now, "updated": now,
            "live_pid": pid, "live_label": label}


def _sids(live):
    return {s.get("sid") for s in live}


# ============================================================
# A. tombstone 된 live 세션 미노출 (회귀 가드 포함)
# ============================================================
print("--- A: _collect_live_sessions dismiss tombstone 게이트 ---")
_reset_world()
# 다른 live_pid (Issue99 dedup 은 동일 (h, live_pid) 를 1개로 합침 — 실제 세션도 각기 다른 pid)
server.sessions[(H, "sid-keep")] = _live_session(pid=os.getpid())
server.sessions[(H, "sid-dismiss")] = _live_session(pid=os.getppid())
server._live_dismiss_add(H, "sid-dismiss")

_stub = object.__new__(server.Handler)
live = server.Handler._collect_live_sessions(_stub)
check("A1: tombstone 된 live 세션은 pid 생존이어도 제외",
      "sid-dismiss" not in _sids(live))
check("A2: 동일 프로젝트 비-tombstone 세션은 정상 노출",
      "sid-keep" in _sids(live))

# ============================================================
# B. tombstone 없으면 정상 노출 (순수 회귀 가드)
# ============================================================
print("--- B: 비-tombstone live 세션 정상 노출 ---")
_reset_world()
server.sessions[(H, "sid-live")] = _live_session()
_stub = object.__new__(server.Handler)
live = server.Handler._collect_live_sessions(_stub)
check("B1: tombstone 파일 없으면 live 세션 노출",
      "sid-live" in _sids(live))

# ============================================================
# C. TTL 만료 tombstone 무효 + lazy purge
# ============================================================
print("--- C: TTL 만료 tombstone 자동 해제 ---")
_reset_world()
server.sessions[(H, "sid-expired")] = _live_session()
# TTL 초과한 과거 ts 직접 주입
server._save_live_dismissed(
    {f"{H}|sid-expired": time.time() - server.LIVE_DISMISS_TTL - 10})
_stub = object.__new__(server.Handler)
live = server.Handler._collect_live_sessions(_stub)
check("C1: TTL 만료 tombstone 은 무효 → 세션 재노출",
      "sid-expired" in _sids(live))
check("C2: 만료분 lazy purge — _load_live_dismissed 에서 제거",
      f"{H}|sid-expired" not in server._load_live_dismissed())

# ============================================================
# D. _handle_session_dismiss E2E — 기록 + 재등록 부활 차단
# ============================================================
print("--- D: dismiss 핸들러 E2E (기록 + 부활 차단) ---")


class _FakeHandler(server.Handler):
    def __init__(self):
        self.client_address = ("127.0.0.1", 0)
        self.responses = []

    def _send_json(self, status, body):
        self.responses.append((status, body))


_reset_world()
server.sessions[(H, "sid-e2e")] = _live_session()
_fh = _FakeHandler()
_fh._handle_session_dismiss(_up(f"/session/dismiss?cwd={CWD}&token=tok&sid=sid-e2e"))
check("D1: dismiss 응답 200 + pruned",
      bool(_fh.responses) and _fh.responses[0][0] == 200
      and _fh.responses[0][1].get("pruned"))
check("D2: dismiss 후 tombstone 기록됨",
      f"{H}|sid-e2e" in server._load_live_dismissed())

# 재등록(부활) 시뮬: 같은 sid 로 sessions 재생성해도 collect 제외돼야
server.sessions[(H, "sid-e2e")] = _live_session()
_stub = object.__new__(server.Handler)
live = server.Handler._collect_live_sessions(_stub)
check("D3: 재등록(heartbeat 부활)분도 tombstone 으로 collect 제외",
      "sid-e2e" not in _sids(live))


# --- 정리 ---
shutil.rmtree(_TMP, ignore_errors=True)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(0 if FAIL == 0 else 1)
