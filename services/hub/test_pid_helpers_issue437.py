#!/usr/bin/env python3
# test_pid_helpers_issue437.py — Issue437 회귀 테스트
#
# ⚠️ 글로벌 SCAR 아님 (___pm 프로젝트 소유). 프로세스 생존 판정·종료의 **1지점**
#   (_pid_alive · _pid_kill)이 플랫폼과 무관하게 같은 계약을 지키는지 본다.
#
# 배경 (jpc1 실측 2026-08-31): Windows 의 `os.kill(pid, 0)` 은 0 이 유효한 signal 이
#   아니라 TerminateProcess 경로로 넘어가 **살아 있든 죽었든** `OSError: [WinError 87]`
#   을 낸다. 종전 `_pid_alive` 는 그것을 `except Exception` 으로 삼켜 전 프로세스를
#   "죽었다" 로 판정했고, `already_running()` 은 삼키지도 않아 **stale pid 파일 하나로
#   hub 기동 자체가 불가능**했다. 그 상태로 실제 발견됐다.
#
# 여기서 검사하는 것은 *"Windows 코드가 맞나"* 가 아니라 **계약**이다 —
#   살아 있으면 True, 없으면 False, 쓰레기 입력은 예외 없이 False.
#   플랫폼 분기 자체는 그 플랫폼에서 tdd `core:process-mgmt` 가 실행으로 확인한다.
#
# 실행: python3 services/hub/test_pid_helpers_issue437.py
"""server.py 프로세스 헬퍼 (Issue437) 단위 테스트."""
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server  # noqa: E402

PASS = 0
FAIL = 0


def check(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {label}")
    else:
        FAIL += 1
        print(f"  ❌ {label}")


print("[1] _pid_alive 계약")
check(server._pid_alive(os.getpid()) is True, "자기 자신은 살아 있다")
# 커널이 절대 배정하지 않는 범위. 혹시 실재하면 판정을 건너뛴다(거짓 실패 방지).
ghost = 4000000
try:
    os.kill(ghost, 0)
    print("  · skip: 유령 pid 가 실재한다")
except Exception:
    check(server._pid_alive(ghost) is False, "존재하지 않는 pid 는 False")
check(server._pid_alive(0) is False, "pid 0 은 False")
check(server._pid_alive(-1) is False, "음수 pid 는 False")
check(server._pid_alive("nope") is False, "숫자 아닌 입력은 예외 없이 False")
check(server._pid_alive(None) is False, "None 은 예외 없이 False")

print("[2] _pid_kill 계약 — 실제 자식으로")
p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
time.sleep(1)
check(server._pid_alive(p.pid) is True, "띄운 자식이 살아 있다고 판정된다")
check(server._pid_kill(p.pid, force=True) is True, "_pid_kill(force) 가 성공을 보고한다")
# ⚠️ 생존 확인 **전에** wait 로 좀비를 수거한다. POSIX 는 부모가 거두기 전까지 죽은
#   자식의 pid 를 유지하고 `os.kill(pid, 0)` 도 성공하므로, 순서를 바꾸면 헬퍼가
#   멀쩡한데 테스트만 실패한다(실제로 그렇게 한 번 틀렸다). hub 의 실사용 대상은
#   자기 자식이 아니라 남의 프로세스라 이 함정이 없다.
try:
    p.wait(timeout=5)
except Exception:
    pass
for _ in range(30):
    if not server._pid_alive(p.pid):
        break
    time.sleep(0.1)
check(server._pid_alive(p.pid) is False, "종료 후 살아 있지 않다고 판정된다")
check(server._pid_kill(0) is False, "pid 0 종료 요청은 False (자기 프로세스 그룹 오살 차단)")

print("[3] already_running — stale pid 파일이 기동을 막지 않는다")
# ⚠️ 이 이슈의 핵심 증상이다. 죽은 pid 가 적힌 파일이 있으면 0 을 반환하고
#   그 파일을 **정리**해야 한다. 종전 Windows 에서는 예외가 전파돼 둘 다 못 했다.
orig = server.PID_FILE
tmp = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".pidtest.issue437")
try:
    server.PID_FILE = tmp
    with open(tmp, "w") as f:
        f.write(str(ghost))
    check(server.already_running() == 0, "죽은 pid 파일 → 0 (기동 허용)")
    check(not os.path.exists(tmp), "죽은 pid 파일은 정리된다")

    with open(tmp, "w") as f:
        f.write("garbage")
    check(server.already_running() == 0, "깨진 pid 파일 → 0")

    with open(tmp, "w") as f:
        f.write(str(os.getpid()))
    check(server.already_running() == os.getpid(), "살아 있는 pid 파일 → 그 pid (이중 기동 차단)")
finally:
    server.PID_FILE = orig
    if os.path.exists(tmp):
        os.remove(tmp)

print(f"\n결과: PASS {PASS} / FAIL {FAIL}")
sys.exit(1 if FAIL else 0)
