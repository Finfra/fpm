#!/usr/bin/env python3
# test_state_isolation_issue518.py — Issue518 회귀 테스트
#
# ⚠️ 글로벌 SCAR 아님 (___pm 프로젝트 소유). server.py 의 `_migrate_legacy_state()` 가
#   «격리»(FPM_TMP_ROOT 명시)와 «구 경로 → 현행 경로 1회 이행»을 구분하는지 검증한다.
#
#   배경: 이관은 구동 중인 hub 가 자기 pid 를 잃지 않게 하려는 것인데, 판정이 «STATE_DIR 이
#   구 경로와 다른가» 뿐이라 테스트·격리용 FPM_TMP_ROOT 를 쓰면 그 조건이 곧바로 성립했다.
#   그 결과 운영 hub 의 pid·tokens.json·server.log 가 샌드박스로 **move** 됐다(실발생).
#
# 실행: python3 services/hub/test_state_isolation_issue518.py
"""_migrate_legacy_state() 격리 가드 단위 테스트."""
import os
import shutil
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


def _seed(legacy):
    """구 경로에 운영 상태 파일 3종을 심는다."""
    os.makedirs(legacy, exist_ok=True)
    for name, body in (("pid", "4242"), ("tokens.json", "{}"), ("server.log", "run")):
        with open(os.path.join(legacy, name), "w", encoding="utf-8") as f:
            f.write(body)


def main():
    sandbox = tempfile.mkdtemp(prefix="issue518-")
    legacy = os.path.join(sandbox, "legacy-state")
    state = os.path.join(sandbox, "iso-state")

    # 실 경로를 건드리지 않도록 STATE_DIR·구 경로 목록을 모두 샌드박스로 대체한다.
    orig_state, orig_dirs = server.STATE_DIR, server._legacy_state_dirs
    orig_env = os.environ.get("FPM_TMP_ROOT")
    server.STATE_DIR = state
    server._legacy_state_dirs = lambda: [legacy]
    try:
        # --- 1. 격리 실행 — FPM_TMP_ROOT 가 명시되면 한 파일도 옮기지 않는다 ---
        _seed(legacy)
        os.environ["FPM_TMP_ROOT"] = sandbox
        server._migrate_legacy_state()
        check("격리: 구 경로 파일 3종이 그대로 남는다",
              sorted(os.listdir(legacy)) == ["pid", "server.log", "tokens.json"])
        check("격리: 샌드박스 STATE_DIR 로 끌어오지 않는다", not os.path.exists(state))

        # --- 2. 평시 실행 — 본래 의도(구 경로 → 현행 경로 이행)는 그대로 산다 ---
        os.environ.pop("FPM_TMP_ROOT", None)
        server._migrate_legacy_state()
        check("평시: 구 경로가 비워진다", os.listdir(legacy) == [])
        check("평시: 현행 STATE_DIR 로 3종이 이관된다",
              sorted(os.listdir(state)) == ["pid", "server.log", "tokens.json"])

        # --- 3. 빈 문자열은 «명시» 가 아니다 — 평시로 취급한다 ---
        shutil.rmtree(state)
        _seed(legacy)
        os.environ["FPM_TMP_ROOT"] = "   "
        server._migrate_legacy_state()
        check("공백 문자열: 격리로 보지 않고 이관한다",
              os.path.isfile(os.path.join(state, "pid")))
    finally:
        server.STATE_DIR, server._legacy_state_dirs = orig_state, orig_dirs
        if orig_env is None:
            os.environ.pop("FPM_TMP_ROOT", None)
        else:
            os.environ["FPM_TMP_ROOT"] = orig_env
        shutil.rmtree(sandbox, ignore_errors=True)

    print(f"\n  PASS={PASS} FAIL={FAIL}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
