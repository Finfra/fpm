#!/usr/bin/env python3
# test_session_dup_issue282.py — Issue282 회귀 테스트 (세션 cwd 드리프트 중복 카드)
#
# ⚠️ 글로벌 SCAR 아님 (___pm 프로젝트 소유). hook 이 세션 현재 cwd 를 보내므로
#   cd 드리프트 시 동일 세션이 다른 cwd_hash 로 재등록돼 카드 2장이 되던 결함 검증.
#
# 실행: python3 services/hub/test_session_dup_issue282.py
"""Issue282 검증 대상:
  A. _collect_live_sessions — 동일 live_pid 가 다른 cwd_hash 아래 2개여도 freshest 1장만
  B. 다른 pid 의 정상 세션은 각자 노출 (회귀 가드)
  C. _handle_session_register sid-sticky — 같은 sid 의 서브폴더 재등록이 기존 key 를
     재사용하고 projects 등록을 오염시키지 않음
  D. _project_emoji — 서브폴더 cwd 도 _resolve_project_root prefix fallback 으로 이모지 유지
"""
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


# --- 격리 픽스처: 임시 state dir·Projects.md 로 server 전역 교체 ---
_TMP = tempfile.mkdtemp(prefix="___pm-issue282-")
server.SESSIONS_FILE = os.path.join(_TMP, "sessions.json")
server.TOKENS_FILE = os.path.join(_TMP, "tokens.json")
server.LIVE_DISMISSED = os.path.join(_TMP, "live-dismissed.json")
server.INBOX_ROOT = os.path.join(_TMP, "inbox")

ROOT = os.path.join(_TMP, "proj")
SUB = os.path.join(ROOT, "Projects", "Examples")
os.makedirs(SUB, exist_ok=True)
H_ROOT = server.cwd_hash(ROOT)
H_SUB = server.cwd_hash(SUB)
ALIVE = os.getpid()
ALIVE2 = os.getppid()

# Projects.md 픽스처 (cells: id|name|?|domain|path|desc|emoji|color)
server.PROJECTS_MD = os.path.join(_TMP, "Projects.md")
with open(server.PROJECTS_MD, "w", encoding="utf-8") as f:
    f.write("| No | Name | S | Domain | Path | Desc | Emoji | Color |\n")
    f.write("| 1 | testproj | - | g | %s | 테스트 | 🎮 | #aabbcc |\n" % ROOT)
server._projects_list_cache = []
server._projects_list_cache_mtime = 0.0
server._projects_emoji_cache = {}
server._projects_emoji_cache_mtime = 0.0


def _reset_world():
    server.projects.clear()
    server.sessions.clear()
    if os.path.exists(server.LIVE_DISMISSED):
        os.remove(server.LIVE_DISMISSED)


def _live_session(pid=ALIVE, label="작업중", updated=None):
    now = time.time()
    return {"mode": "A", "content_type": "live", "content": "",
            "capabilities": {"source": "prompt", "kind": "live"},
            "created": now, "updated": updated if updated is not None else now,
            "live_pid": pid, "live_label": label}


def _proj(cwd, h):
    return {"cwd": cwd, "token": "tok-" + h, "name": os.path.basename(cwd),
            "color": "#ccc", "registered_at": 0}


# ============================================================
# A. 전역 pid dedup — cwd_hash 가 갈라져도 freshest 1장만
# ============================================================
print("--- A: 동일 live_pid 크로스-hash dedup ---")
_reset_world()
server.projects[H_ROOT] = _proj(ROOT, H_ROOT)
server.projects[H_SUB] = _proj(SUB, H_SUB)
now = time.time()
server.sessions[(H_ROOT, "sid-x")] = _live_session(updated=now - 10)
server.sessions[(H_SUB, "sid-x")] = _live_session(updated=now)

_stub = object.__new__(server.Handler)
live = server.Handler._collect_live_sessions(_stub)
cards = [s for s in live if s.get("sid") == "sid-x"]
check("A1: 동일 pid 세션은 hash 무관 1장만 노출", len(cards) == 1)
check("A2: freshest(최근 updated) 쪽이 생존", cards and cards[0]["cwd_hash"] == H_SUB)

# ============================================================
# B. 다른 pid 세션은 각자 노출 (회귀 가드)
# ============================================================
print("--- B: 상이 pid 정상 노출 ---")
_reset_world()
server.projects[H_ROOT] = _proj(ROOT, H_ROOT)
server.projects[H_SUB] = _proj(SUB, H_SUB)
server.sessions[(H_ROOT, "sid-1")] = _live_session(pid=ALIVE)
server.sessions[(H_SUB, "sid-2")] = _live_session(pid=ALIVE2)
_stub = object.__new__(server.Handler)
live = server.Handler._collect_live_sessions(_stub)
sids = {s.get("sid") for s in live}
check("B1: 서로 다른 pid 두 세션 모두 노출", {"sid-1", "sid-2"} <= sids)

# ============================================================
# C. sid-sticky register — 서브폴더 재등록이 기존 key 재사용
# ============================================================
print("--- C: /session/register sid-sticky ---")


class _FakeHandler(server.Handler):
    def __init__(self, body):
        self.client_address = ("127.0.0.1", 0)
        self.responses = []
        self._body = body

    def _read_json_body(self, max_bytes=1024 * 1024):
        return self._body, None

    def _send_json(self, status, body):
        self.responses.append((status, body))


_reset_world()
# 1차 등록: 프로젝트 루트에서
fh1 = _FakeHandler({"sid": "sid-sticky", "content_type": "live", "pid": ALIVE,
                    "label": "작업중"})
fh1._handle_session_register(_up(f"/session/register?cwd={ROOT}"))
check("C1: 1차 등록 200 + 루트 hash",
      fh1.responses and fh1.responses[0][0] == 200
      and fh1.responses[0][1].get("cwd_hash") == H_ROOT)

# 2차 등록(heartbeat): cd 드리프트로 서브폴더 cwd 전송
fh2 = _FakeHandler({"sid": "sid-sticky", "content_type": "live", "pid": ALIVE,
                    "label": "작업중"})
fh2._handle_session_register(_up(f"/session/register?cwd={SUB}"))
check("C2: 서브폴더 재등록이 기존 루트 hash 로 remap",
      fh2.responses and fh2.responses[0][0] == 200
      and fh2.responses[0][1].get("cwd_hash") == H_ROOT)
check("C3: 서브폴더 hash 아래 신규 entry 미생성",
      (H_SUB, "sid-sticky") not in server.sessions
      and (H_ROOT, "sid-sticky") in server.sessions)
check("C4: projects 등록 미오염 (루트 1건, cwd 원형 유지)",
      len(server.projects) == 1
      and server.projects.get(H_ROOT, {}).get("cwd") == ROOT)

_stub = object.__new__(server.Handler)
live = server.Handler._collect_live_sessions(_stub)
check("C5: collect 결과도 카드 1장", len([s for s in live if s.get("sid") == "sid-sticky"]) == 1)

# ============================================================
# D. _project_emoji prefix fallback
# ============================================================
print("--- D: _project_emoji 서브폴더 fallback ---")
check("D1: 루트 exact 매칭", server._project_emoji(ROOT) == "🎮")
check("D2: 서브폴더 prefix fallback", server._project_emoji(SUB) == "🎮")
check("D3: 미등록 경로는 빈 문자열", server._project_emoji("/tmp/issue282-none") == "")

shutil.rmtree(_TMP, ignore_errors=True)
print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
