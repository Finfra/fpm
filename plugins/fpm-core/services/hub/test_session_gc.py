#!/usr/bin/env python3
# test_session_gc.py — Issue280 회귀 테스트
#
# ⚠️ 글로벌 SCAR 아님 (___pm 프로젝트 소유). 세션 GC(세션·터미널 pane 강제 종료)의
#   순수 로직(_gc_plan 단계 계획, _gc_guard pid 재사용/자기보호 가드)과
#   register 시점 컨테이너 메타 캡처(_capture_gc_meta)를 검증한다.
#   실제 kill 은 수행하지 않음 (_gc_execute 는 순수 헬퍼 경유로 간접 검증).
#
# 실행: python3 services/hub/test_session_gc.py
"""server.py 세션 GC (Issue280) 단위 테스트."""
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


# --- _gc_plan: escalation 단계 계획 (순수) ---
print("_gc_plan")
full = {"live_pid": 100,
        "gc_meta": {"for_pid": 100, "shell_pid": 90, "shell_cmd": "-zsh",
                    "tmux_pane": "%7"}}
plan = server._gc_plan(full)
check("full meta → 3단계", len(plan) == 3)
check("순서: tmux → claude → shell",
      [s["kind"] for s in plan] == ["tmux-kill-pane", "kill-claude", "kill-shell"])
check("tmux 단계 target 전달", plan[0]["target"] == "%7")
check("shell 단계 expect_cmd 전달", plan[2]["expect_cmd"] == "-zsh")

only_pid = {"live_pid": 100}
plan = server._gc_plan(only_pid)
check("live_pid 만 → kill-claude 1단계",
      [s["kind"] for s in plan] == ["kill-claude"] and plan[0]["pid"] == 100)

shell_only = {"live_pid": None,
              "gc_meta": {"for_pid": 100, "shell_pid": 90, "shell_cmd": "-zsh",
                          "tmux_pane": None}}
plan = server._gc_plan(shell_only)
check("claude 사후(live_pid None) → shell 단계만",
      [s["kind"] for s in plan] == ["kill-shell"])

check("빈 entry → 계획 없음", server._gc_plan({}) == [])
check("gc_meta None 허용", server._gc_plan({"gc_meta": None}) == [])

# --- _gc_guard: kill 직전 가드 (순수) ---
print("_gc_guard")
SRV = 55555
check("pid 0 차단", server._gc_guard("kill-claude", 0, None, "claude", SRV) is not None)
check("pid 1 차단", server._gc_guard("kill-claude", 1, None, "claude", SRV) is not None)
check("hub 자신 차단", server._gc_guard("kill-claude", SRV, None, "claude", SRV) is not None)
check("claude comm 통과", server._gc_guard("kill-claude", 100, None, "claude", SRV) is None)
check("절대경로 claude 통과",
      server._gc_guard("kill-claude", 100, None, "/usr/local/bin/claude", SRV) is None)
check("node 통과 (npm 설치 claude)",
      server._gc_guard("kill-claude", 100, None, "node", SRV) is None)
check("무관 프로세스 차단 (pid 재사용)",
      server._gc_guard("kill-claude", 100, None, "vim", SRV) is not None)
check("comm None 차단", server._gc_guard("kill-claude", 100, None, None, SRV) is not None)
check("shell comm 일치 통과",
      server._gc_guard("kill-shell", 90, "-zsh", "-zsh", SRV) is None)
check("shell comm 불일치 차단 (pid 재사용)",
      server._gc_guard("kill-shell", 90, "-zsh", "python3", SRV) is not None)
check("shell expect_cmd 미캡처 시 통과 (가드 완화)",
      server._gc_guard("kill-shell", 90, None, "python3", SRV) is None)

# --- _capture_gc_meta: register 시점 실캡처 (현재 테스트 프로세스 대상) ---
print("_capture_gc_meta")
me = os.getpid()
meta = server._capture_gc_meta(me)
check("for_pid 기록", meta["for_pid"] == me)
check("shell_pid = 실제 부모", meta["shell_pid"] == os.getppid())
check("shell_cmd 캡처됨", bool(meta["shell_cmd"]))
check("tmux_pane 키 존재 (None 허용)", "tmux_pane" in meta)

# --- _tmux_pane_for_pids ---
print("_tmux_pane_for_pids")
check("빈 후보 집합 → None", server._tmux_pane_for_pids(set()) is None)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
