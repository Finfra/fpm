#!/usr/bin/env python3
# test_dash_stale_issue403.py — Issue403 회귀 테스트
#
# ⚠️ 글로벌 SCAR 아님 (___pm 프로젝트 소유). server.py 의 dash 실효 status 판정
#   (_effective_dash_status / _dash_stale_limit / _is_clearable_status)을 검증한다.
#
# 왜 이 테스트가 필요한가 — `status: running` 인데 pid·worker_pid 가 둘 다 비정수인
#   dash 는 종전에 **무조건 running 유지**로 빠졌고, running 은 _is_clearable_status 가
#   False 라 hub "정리" 버튼으로도 지워지지 않았다. 한 번도 가동된 적 없는 템플릿이
#   하루 반 동안 "돌고 있다" 로 박제된 실사고(2026-08-26)가 근거다.
#   반대 방향(살아 있는 보드의 오강등)이 더 위험하므로 무회귀도 함께 박제한다.
#
# 실행: python3 services/hub/test_dash_stale_issue403.py
"""dash running 박제 강등(Issue403) 단위 테스트."""
import os
import sys
import tempfile
import time

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


eff = server.Handler._effective_dash_status
limit = server.Handler._dash_stale_limit
clearable = server.Handler._is_clearable_status
GRACE = server.DASH_STATUS_NONE_GRACE_SEC
MULT = server.DASH_RUNNING_STALE_INTERVALS


def main():
    print("== _dash_stale_limit — 임계는 보드 주기에서 나온다 (Issue403 ⓐ) ==")

    # 1) 고정 상수 금지 — 10초 보드와 5분 보드의 임계가 달라야 한다.
    check("주기가 다르면 임계도 다르다", limit(300) != limit(10))
    check("300초 보드 임계 = interval*배수", limit(300) == 300.0 * MULT)
    check("interval 부재 → 기존 grace 준용", limit(None) == float(GRACE))
    check("interval 비수치 → grace 준용", limit("abc") == float(GRACE))
    check("interval 0·음수 → grace 준용",
          limit(0) == float(GRACE) and limit(-5) == float(GRACE))
    # 오강등 방지(ⓒ) — 초고빈도 보드가 스케줄 지연만으로 죽은 것으로 뒤집히면 안 된다.
    check("초고빈도 보드는 grace 아래로 내려가지 않는다", limit(1) >= float(GRACE))
    check("임계는 주기에 대해 단조 증가", limit(10) <= limit(60) <= limit(600))

    print("\n== _effective_dash_status — pid 검증 불가 경로 (Issue403 ⓐⓑ) ==")
    now = time.time()

    # 2) 실사고 재현 — 한 번도 가동된 적 없는 템플릿(pid None · worker_pid 키 없음).
    #    prj3 fbot-board-init.sh 가 쓰는 형태 그대로다.
    frozen = {"status": "running", "pid": None, "interval": 10,
              "mtime_ts": now - 129600}          # 36시간 정체
    check("정체된 running(pid 검증 불가) → stale", eff(frozen) == "stale")
    # ⓑ: 별도 분기 없이 "정리" 버튼이 먹어야 한다 (prj1#Issue83 비대칭 재발 금지).
    check("강등 결과는 정리 대상", clearable(eff(frozen)) is True)
    check("강등 전 raw status 는 정리 불가였다(회귀 근거)",
          clearable("running") is False)

    # 3) worker_pid 키 자체가 없는 순수 모니터링 계약(prj3 board.md, prj3#Issue142)도 같은 경로.
    check("worker_pid 키 부재도 동일 강등",
          eff({"status": "running", "pid": None, "interval": 10,
               "mtime_ts": now - 3600}) == "stale")
    # null 명시(worker_pid: None)도 비정수라 같은 취급.
    check("worker_pid None 명시도 동일 강등",
          eff({"status": "running", "pid": None, "worker_pid": None,
               "interval": 10, "mtime_ts": now - 3600}) == "stale")

    print("\n== 오강등 금지 — 살아 있는 보드는 건드리지 않는다 (Issue403 ⓒ) ==")

    # 4) 갱신 중인 순수 모니터링 보드 — runner 가 매 주기 write 하므로 mtime 이 전진한다.
    check("방금 갱신된 running 유지",
          eff({"status": "running", "pid": None, "interval": 10,
               "mtime_ts": now - 5}) == "running")
    # 경계 — 임계 직전은 유지, 임계 직후만 강등.
    lim10 = limit(10)
    check("임계 직전은 running 유지",
          eff({"status": "running", "pid": None, "interval": 10,
               "mtime_ts": now - (lim10 - 5)}) == "running")
    check("임계 직후는 stale",
          eff({"status": "running", "pid": None, "interval": 10,
               "mtime_ts": now - (lim10 + 5)}) == "stale")
    # 느린 보드(5분 주기)가 고정 상수 임계에 걸려 오강등되면 안 된다 — 이것이
    #   "고정 상수 금지" 의 실질 이유다. grace(120s)만 썼다면 여기서 stale 이 된다.
    check("5분 주기 보드는 10분 정체로 강등되지 않는다",
          eff({"status": "running", "pid": None, "interval": 300,
               "mtime_ts": now - 600}) == "running")

    # 5) mtime 을 아예 못 읽는 경우는 판정 근거가 없다 → 기존 동작(running 유지).
    check("mtime_ts 부재는 강등하지 않음",
          eff({"status": "running", "pid": None, "interval": 10}) == "running")
    check("mtime_ts 0(등록 경로 파일 소실 합성값)도 강등하지 않음",
          eff({"status": "running", "pid": None, "interval": 10,
               "mtime_ts": 0}) == "running")

    print("\n== 무회귀 — pid 보유 보드(prj1#Issue58)·status 부재(prj1#Issue60) ==")

    # 6) pid 가 살아 있으면 mtime 이 아무리 정체돼도 running 이다. 판정원은 pid 다.
    check("살아있는 pid + mtime 정체 → running 유지",
          eff({"status": "running", "pid": os.getpid(), "interval": 10,
               "mtime_ts": now - 999999}) == "running")
    check("살아있는 worker_pid 폴백도 running 유지",
          eff({"status": "running", "pid": None, "worker_pid": os.getpid(),
               "interval": 10, "mtime_ts": now - 999999}) == "running")
    # 죽은 pid 는 mtime 과 무관하게 stale (prj1#Issue58 원래 계약).
    dead = 2 ** 22 - 1          # 존재 가능성이 사실상 없는 pid
    while server._pid_alive(dead):
        dead -= 1
    check("죽은 pid → mtime 신선해도 stale",
          eff({"status": "running", "pid": dead, "interval": 10,
               "mtime_ts": now}) == "stale")

    # 7) status 부재 경로(prj1#Issue60)는 그대로다.
    check("status 부재 + grace 경과 → stale",
          eff({"status": None, "mtime_ts": now - GRACE - 10}) == "stale")
    check("status 부재 + grace 이내 → None 유지",
          eff({"status": None, "mtime_ts": now - 5}) is None)
    # 종료 상태는 손대지 않는다.
    for s in ("done", "stopped", "missing", "ALL-DONE"):
        check(f"종료 상태 {s} 는 불변",
              eff({"status": s, "pid": None, "mtime_ts": now - 999999}) == s)

    print("\n== interval 파싱 배선 — 판정이 값을 실제로 받는가 ==")

    # 8) 임계 산출의 입력은 dash 파일의 `interval` 이다. 파서가 이 키를 흘리면
    #    _effective_dash_status 는 항상 grace 로 폴백해 느린 보드를 오강등한다.
    y = server.Handler._parse_dash_yaml(
        "title: bots\nstatus: running\npid: null\ninterval: 10\n")
    check("yaml 파서가 interval 추출", y.get("interval") == 10)
    check("yaml 파서가 pid null 을 None 으로", y.get("pid") is None)
    y2 = server.Handler._parse_dash_yaml("title: t\nstatus: running\n")
    check("interval 부재 yaml 은 None", y2.get("interval") is None)

    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "x.dash.yaml")
        with open(p, "w", encoding="utf-8") as f:
            f.write("title: bots\nstatus: running\npid: null\ninterval: 10\n")
        os.utime(p, (now - 129600, now - 129600))
        h = server.Handler.__new__(server.Handler)
        e = h._read_dash_file(p)
        check("_read_dash_file 이 interval 을 실어 준다", e.get("interval") == 10)
        check("파일 → 판정 왕복이 stale 로 이어진다", eff(e) == "stale")

        pj = os.path.join(tmp, "y.dash.json")
        with open(pj, "w", encoding="utf-8") as f:
            f.write('{"title":"t","status":"running","pid":null,"interval":300}')
        os.utime(pj, (now - 600, now - 600))
        ej = h._read_dash_file(pj)
        check("json 경로도 interval 을 실어 준다", ej.get("interval") == 300)
        check("json 느린 보드 10분 정체는 running 유지", eff(ej) == "running")

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
