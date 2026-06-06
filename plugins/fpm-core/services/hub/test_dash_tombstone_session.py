#!/usr/bin/env python3
# test_dash_tombstone_session.py — Issue95 회귀 테스트 (live-session 부활 채널)
#
# ⚠️ 글로벌 SCAR 아님 (___pm 프로젝트 소유). server.py 의 dashboard tombstone
#   (DASH_CLEARED) 권위가 'live session' 렌더/복원/clear 경로까지 적용되는지 검증.
#
# 실행: python3 services/hub/test_dash_tombstone_session.py
"""Issue95: dashboard 삭제 후 자동 부활 — feed 채널은 선행 커밋(bc9c7b7/958f01c)에서
막았으나 'live session'(sessions dict ← sessions.json ← load_sessions) 채널은
DASH_CLEARED tombstone 을 전혀 참조하지 않아 부활이 계속됨.

검증 대상:
  A. _collect_live_sessions — tombstone 된 dashboard 세션은 pid 생존이어도 미노출
  B. _collect_live_sessions — tombstone 안 된 dashboard 세션은 정상 노출 (회귀 가드)
  C. load_sessions — 복원 시 tombstone 된 dashboard 세션 제외
  D. _handle_clear_done — registry 정리 시 대응 live session(sid) 동반 제거
"""
import json
import os
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


# --- 격리 픽스처: 임시 state dir + registry 파일로 server 전역 교체 ---
_TMP = tempfile.mkdtemp(prefix="___pm-issue95-")
server.DASH_CLEARED = os.path.join(_TMP, "dash-cleared.json")
server.DASH_REGISTRY = os.path.join(_TMP, "dash-registry.json")
server.SESSIONS_FILE = os.path.join(_TMP, "sessions.json")
server.HOOK_FEED_FILE = os.path.join(_TMP, "hook-feed.json")

ALIVE = os.getpid()        # 자기 자신 → _pid_alive True
CWD = os.path.join(_TMP, "proj")
os.makedirs(os.path.join(CWD, "_doc_work", "z_htm"), exist_ok=True)
H = server.cwd_hash(CWD)

# tombstone 대상 dash 파일 (디스크 존재 — clear-done 의 isfile 게이트 충족)
CLEARED_DASH = os.path.join(CWD, "_doc_work", "z_htm", "jm1-monitor.dash.yaml")
with open(CLEARED_DASH, "w") as f:
    f.write("title: jm1-monitor\nstatus: running\n")
LIVE_DASH = os.path.join(CWD, "_doc_work", "z_htm", "active-build.dash.yaml")
with open(LIVE_DASH, "w") as f:
    f.write("title: active-build\nstatus: running\n")


def _reset_world():
    server.projects.clear()
    server.sessions.clear()
    server.projects[H] = {"cwd": CWD, "token": "tok", "name": "proj",
                          "color": "#ccc", "registered_at": 0}


def _dash_session(dash_path, title, pid=ALIVE, status="running"):
    return {
        "mode": "C", "content_type": "dashboard",
        "content": json.dumps({"title": title, "status": status,
                               "pid": pid, "dash_path": dash_path}),
        "created": time.time(), "updated": time.time(),
    }


def _titles(live):
    return {s.get("title") for s in live}


# ============================================================
# A. _collect_live_sessions — tombstone 된 세션 미노출
# ============================================================
print("--- A: _collect_live_sessions tombstone 게이트 ---")
_reset_world()
server.sessions[(H, "sid-cleared")] = _dash_session(CLEARED_DASH, "jm1-monitor")
server.save_registry(server.DASH_CLEARED, [CLEARED_DASH])

_stub = object.__new__(server.Handler)
live = server.Handler._collect_live_sessions(_stub)
check("A1: tombstone 된 dashboard 세션은 pid 생존이어도 live 목록 제외",
      "jm1-monitor" not in _titles(live))

# ============================================================
# B. 회귀 가드 — tombstone 안 된 세션은 정상 노출
# ============================================================
print("--- B: 비-tombstone 세션 정상 노출 (회귀 가드) ---")
_reset_world()
server.sessions[(H, "sid-live")] = _dash_session(LIVE_DASH, "active-build")
server.save_registry(server.DASH_CLEARED, [CLEARED_DASH])  # 다른 path 만 tombstone

_stub = object.__new__(server.Handler)
live = server.Handler._collect_live_sessions(_stub)
check("B1: tombstone 안 된 dashboard 세션(pid 생존+신선)은 정상 노출",
      "active-build" in _titles(live))

# ============================================================
# C. load_sessions — 복원 시 tombstone 세션 제외
# ============================================================
print("--- C: load_sessions tombstone 필터 ---")
_reset_world()
snap = {
    f"{H}|sid-cleared": _dash_session(CLEARED_DASH, "jm1-monitor"),
    f"{H}|sid-live": _dash_session(LIVE_DASH, "active-build"),
}
with open(server.SESSIONS_FILE, "w", encoding="utf-8") as f:
    json.dump(snap, f)
server.save_registry(server.DASH_CLEARED, [CLEARED_DASH])
server.sessions.clear()
server.load_sessions()
check("C1: load_sessions 복원 시 tombstone 세션 제외",
      (H, "sid-cleared") not in server.sessions)
check("C2: load_sessions 정상 세션은 복원",
      (H, "sid-live") in server.sessions)

# ============================================================
# D. _handle_clear_done — registry 정리 시 live session 동반 제거
# ============================================================
print("--- D: clear-done 가 대응 세션(sid) 동반 제거 ---")


class _FakeHandler(server.Handler):
    def __init__(self):
        self.client_address = ("127.0.0.1", 0)
        self.responses = []

    def _send_json(self, status, body):
        self.responses.append((status, body))


_reset_world()
# stale(죽은 pid) dashboard — clearable. registry+session 동일 sid.
DEAD = 9999997
stale_dash = os.path.join(CWD, "_doc_work", "z_htm", "stale-x.dash.yaml")
with open(stale_dash, "w") as f:
    f.write("title: stale-x\nstatus: running\npid: %d\n" % DEAD)
server.save_registry(server.DASH_REGISTRY, [
    {"path": stale_dash, "cwd": CWD, "title": "stale-x", "sid": "sid-stale",
     "registered_at": 0},
])
server.sessions[(H, "sid-stale")] = _dash_session(stale_dash, "stale-x",
                                                   pid=DEAD)
server.save_registry(server.DASH_CLEARED, [])

_fh = _FakeHandler()
_fh._handle_clear_done(_up("/clear-done"))
check("D1: clear-done 응답 200",
      _fh.responses and _fh.responses[0][0] == 200)
check("D2: clear-done 후 대응 live session(sid) 제거됨",
      (H, "sid-stale") not in server.sessions)


# --- 정리 ---
import shutil  # noqa: E402
shutil.rmtree(_TMP, ignore_errors=True)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(0 if FAIL == 0 else 1)
