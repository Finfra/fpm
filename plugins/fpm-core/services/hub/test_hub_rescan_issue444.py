#!/usr/bin/env python3
# test_hub_rescan_issue444.py — Issue444 회귀 테스트
#
# ⚠️ 글로벌 SCAR 아님 (___pm 프로젝트 소유). /hub-rescan 이 활성 세션(runtime
#   `projects`)에만 의존하지 않고, 등록 프로젝트 SSOT(`projects/{번호}`)도
#   스캔 대상에 포함하는지 검증한다.
#
# 실행: python3 services/hub/test_hub_rescan_issue444.py
"""server.py `/hub-rescan` (Issue444) 회귀 테스트.

재현 조건: htm 문서가 존재하는 프로젝트인데 그 프로젝트에 **활성 세션이 없어**
런타임 `projects` 딕셔너리에 등록돼 있지 않다. 종전 코드는 `snap = projects.items()`
만 순회해 이런 프로젝트를 rescan 후보에서 완전히 빠뜨렸다(파일은 있고 tombstone
도 아닌데 영구 미등록). 수정 후에는 `_registered_project_dirs()`(projects/ SSOT)가
합류해 세션 유무와 무관하게 스캔된다.
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
_TMP = tempfile.mkdtemp(prefix="___pm-issue444-")
server.HTM_REGISTRY = os.path.join(_TMP, "htm-registry.json")
server.HTM_CLEARED = os.path.join(_TMP, "htm-cleared.json")
server.DASH_REGISTRY = os.path.join(_TMP, "dash-registry.json")
server.DASH_CLEARED = os.path.join(_TMP, "dash-cleared.json")
server.HUB_SETTING_FILE = os.path.join(_TMP, "hub_setting.yml")  # 부재 → 기본값

# 등록 프로젝트 SSOT — projects/999 파일 1개
server.REPO_ROOT = _TMP
os.makedirs(os.path.join(_TMP, "projects"), exist_ok=True)

ORPHAN_PROJ = os.path.join(_TMP, "orphan-proj")  # 세션 없는 등록 프로젝트
os.makedirs(os.path.join(ORPHAN_PROJ, "_doc_work", "htm"), exist_ok=True)
with open(os.path.join(_TMP, "projects", "999"), "w", encoding="utf-8") as f:
    f.write(ORPHAN_PROJ + "\n")

ORPHAN_HTM = os.path.join(ORPHAN_PROJ, "_doc_work", "htm",
                          "hub_htm_20260101_000000_orphan.htm")
with open(ORPHAN_HTM, "w", encoding="utf-8") as f:
    f.write("<html><head><title>orphan</title></head><body>x</body></html>")

server.projects.clear()  # 활성 세션 0건 — orphan-proj 는 runtime projects 에 없음


# ============================================================
# A. _registered_project_dirs — SSOT 전수 읽기
# ============================================================
print("--- A: _registered_project_dirs ---")
dirs = server._registered_project_dirs()
check("A1: projects/999 의 경로(orphan-proj)가 후보에 포함됨",
      ORPHAN_PROJ in dirs)

# ============================================================
# B. /hub-rescan — 세션 없는 등록 프로젝트의 htm 을 수거
# ============================================================
print("--- B: /hub-rescan 세션 무관 수거 ---")
_fh = _FakeHandler()
_fh._handle_hub_rescan(_up("/hub-rescan"))
check("B1: 응답 200", _fh.responses and _fh.responses[0][0] == 200)
added = _fh.responses[0][1].get("added", {}) if _fh.responses else {}
check("B2: htm 1건 수거 (added.htm >= 1)", added.get("htm", 0) >= 1)

entries = server.load_registry(server.HTM_REGISTRY)
paths = {e.get("path") for e in entries}
check("B3: registry 에 orphan htm 경로가 실제로 저장됨", ORPHAN_HTM in paths)

# ============================================================
# C. 회귀 가드 — HTM_CLEARED tombstone 은 여전히 부활하지 않음
# ============================================================
print("--- C: tombstone 은 rescan 으로 부활하지 않음 (회귀 가드) ---")
server.save_registry(server.HTM_REGISTRY, [])
server.save_registry(server.HTM_CLEARED, [ORPHAN_HTM])

_fh2 = _FakeHandler()
_fh2._handle_hub_rescan(_up("/hub-rescan"))
entries2 = server.load_registry(server.HTM_REGISTRY)
paths2 = {e.get("path") for e in entries2}
check("C1: tombstone 처리된 경로는 rescan 으로도 등록되지 않음",
      ORPHAN_HTM not in paths2)


# --- 정리 ---
import shutil  # noqa: E402
shutil.rmtree(_TMP, ignore_errors=True)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(0 if FAIL == 0 else 1)
