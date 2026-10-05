#!/usr/bin/env python3
# test_hub_rescan_dsstore.py — /hub-rescan `.DS_Store` 회귀 테스트
#
# ⚠️ 글로벌 SCAR 아님 (___pm 프로젝트 소유). `projects/` 에 번호 파일이 아닌
#   항목(Finder 가 만드는 바이너리 `.DS_Store`·텍스트 `.frecency`)이 섞여도
#   /hub-rescan 이 죽지 않고, 프로젝트 목록 판정이 한 함수로 통일됐는지 검증한다.
#
# 실행: python3 services/hub/test_hub_rescan_dsstore.py
"""server.py `_registered_project_dirs()` 회귀 테스트.

재현 조건: `projects/.DS_Store`(바이너리, 0x80 포함)가 존재한다. 종전 코드는
`projects/` 의 모든 파일을 UTF-8 로 읽고 `except OSError` 만 잡아
`UnicodeDecodeError` 가 핸들러 밖으로 새어 `/hub-rescan` 이 빈 응답으로 끊겼다
(브라우저 «Failed to fetch»).
"""
import os
import sys
import tempfile
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


class _FakeHandler(server.Handler):
    def __init__(self):
        self.client_address = ("127.0.0.1", 0)
        self.responses = []

    def _send_json(self, status, body):
        self.responses.append((status, body))


# --- 격리 픽스처 ---
_TMP = tempfile.mkdtemp(prefix="___pm-dsstore-")
server.HTM_REGISTRY = os.path.join(_TMP, "htm-registry.json")
server.HTM_CLEARED = os.path.join(_TMP, "htm-cleared.json")
server.DASH_REGISTRY = os.path.join(_TMP, "dash-registry.json")
server.DASH_CLEARED = os.path.join(_TMP, "dash-cleared.json")
server.HUB_SETTING_FILE = os.path.join(_TMP, "hub_setting.yml")  # 부재 → 기본값
server.REPO_ROOT = _TMP
PROJ_DIR = os.path.join(_TMP, "projects")
os.makedirs(PROJ_DIR, exist_ok=True)

PROJ_A = os.path.join(_TMP, "proj-a")
PROJ_B = os.path.join(_TMP, "proj-b")
for d in (PROJ_A, PROJ_B):
    os.makedirs(os.path.join(d, "_doc_work", "htm"), exist_ok=True)
with open(os.path.join(PROJ_DIR, "7"), "w", encoding="utf-8") as f:
    f.write(PROJ_A + "\n")
with open(os.path.join(PROJ_DIR, "9a"), "w", encoding="utf-8") as f:   # 접미 문자 번호
    f.write(PROJ_B + "\n")
# Finder 가 만드는 바이너리 — 실측 파일과 같은 0x80 바이트 포함
with open(os.path.join(PROJ_DIR, ".DS_Store"), "wb") as f:
    f.write(b"\x00\x00\x00\x01Bud1" + b"\x80" * 64)
# 번호 파일이 아닌 텍스트 — 경로처럼 보여도 프로젝트로 읽으면 안 된다
with open(os.path.join(PROJ_DIR, ".frecency"), "w", encoding="utf-8") as f:
    f.write(PROJ_A + "\n")

HTM = os.path.join(PROJ_A, "_doc_work", "htm", "hub_htm_20260101_000000_a.htm")
with open(HTM, "w", encoding="utf-8") as f:
    f.write("<html><head><title>a</title></head><body>x</body></html>")

server.projects.clear()


# ============================================================
# A. _registered_project_dirs — 비번호 항목 무시
# ============================================================
print("--- A: _registered_project_dirs ---")
try:
    dirs = server._registered_project_dirs()
    raised = None
except Exception as e:  # noqa: BLE001 — 회귀 검출용
    dirs, raised = [], e
check(f"A1: .DS_Store 가 있어도 예외 없음 ({type(raised).__name__ if raised else 'ok'})",
      raised is None)
check("A2: 번호 파일(7·9a) 경로가 모두 포함됨",
      PROJ_A in dirs and PROJ_B in dirs)
check("A3: 비번호 파일(.frecency)은 후보가 되지 않음 — 중복 없음",
      dirs.count(PROJ_A) == 1)

# ============================================================
# B. /hub-rescan — 200 응답 + 수거
# ============================================================
print("--- B: /hub-rescan ---")
_fh = _FakeHandler()
try:
    _fh._handle_hub_rescan(_up("/hub-rescan"))
    raised = None
except Exception as e:  # noqa: BLE001
    raised = e
check("B1: 핸들러가 예외로 끊기지 않음", raised is None)
check("B2: 응답 200", bool(_fh.responses) and _fh.responses[0][0] == 200)
paths = {e.get("path") for e in server.load_registry(server.HTM_REGISTRY)}
check("B3: proj-a htm 이 registry 에 수거됨", HTM in paths)


import shutil  # noqa: E402
shutil.rmtree(_TMP, ignore_errors=True)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(0 if FAIL == 0 else 1)
