#!/usr/bin/env python3
# test_sched_log_run_issue581.py — /sched-log 회차 절단 (Issue581 C · prj3#Issue780 경계 표식 소비)
#
# ⚠️ 글로벌 SCAR 아님 (___pm 프로젝트 소유).
# 왜: Issue580 의 `/sched-log?job=<잡>&run=<pid>` 는 누적 로그 끝부분을 보이며 «회차 구분 불가» 라고만 했다 —
#   과거 회차를 누르면 이후 회차 출력이 보였다. prj3#Issue780(dd29ac10)이 schedule-run.sh 에 회차 경계
#   (시작 `── <ISO> <이벤트> <잡> pid=<pid> ──` · 끝 `── rc=<rc> <dur>s ──`)를 넣었으므로 그 pid 구간만 자른다.
# 지키는 것: 경계 있음/없음 혼재 · 정확한 pid 일치(10 ≠ 100 ≠ 1000) · 끝 경계 없는 회차(강제 종료) ·
#   회전된 `.1` 로그 · **거짓 절단 금지**(경계 없는 옛 회차는 종전처럼 «구분 불가»).
#
# 실행: python3 plugins/fpm-core/services/hub/test_sched_log_run_issue581.py
import os
import sys
import tempfile

SANDBOX = tempfile.mkdtemp(prefix="sched581-")
os.environ["SCHEDULE_SH"] = os.path.join(SANDBOX, "hooks", "schedule.sh")   # import 시점에 굳는다
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server  # noqa: E402

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  ok   {name}")
    else:
        FAIL += 1; print(f"  FAIL {name}" + (f"\n       {detail[:400]}" if detail else ""))


LOG = os.path.join(SANDBOX, "data", "schedule", "log")
os.makedirs(LOG)


def put(name, text):
    with open(os.path.join(LOG, name), "w", encoding="utf-8") as fh:
        fh.write(text)


S = lambda ts, ev, job, pid: f"── {ts} {ev} {job} pid={pid} ──\n"
E = lambda rc, s: f"── rc={rc} {s}s ──\n"
put("cut.out", "옛 출력(경계 도입 전)\n" + S("2026-09-28T09:00:01", "t-0900", "cut", 100) + "회차100 줄1\n회차100 줄2\n" + E(0, 3)
    + S("2026-09-28T10:00:01", "t-1000", "cut", 1000) + "회차1000 줄\n" + E(1, 2))
put("cut.err", S("2026-09-28T09:00:01", "t-0900", "cut", 100) + "경고100\n" + E(0, 3)
    + S("2026-09-28T10:00:01", "t-1000", "cut", 1000) + "오류1000\n" + E(1, 2))
put("killed.out", S("2026-09-28T09:00:01", "t-0900", "killed", 500) + "회차500 도중\n"
    + S("2026-09-28T10:00:01", "t-1000", "killed", 600) + "회차600 줄\n" + E(0, 1))
put("rot.out", S("2026-09-28T10:00:01", "t-1000", "rot", 900) + "회차900 줄\n" + E(0, 1))
put("rot.out.1", S("2026-09-27T10:00:01", "t-1000", "rot", 800) + "회차800 줄(회전됨)\n" + E(0, 1))

job = lambda n: {"name": n, "log": None, "steps": [{"kind": "sh", "run": "x"}]}
run = lambda j, pid, ts, rc="0": {"ts": ts, "event": "t", "job": j, "rc": rc, "detail": f"3s pid={pid}"}
DATA = {"ok": True, "jobs": [job("cut"), job("killed"), job("rot")],
        "runs": [run("cut", 1000, "2026-09-28T10:00:03", "1"), run("cut", 100, "2026-09-28T09:00:04"),
                 run("cut", 42, "2026-09-27T09:00:04"),                       # 경계 도입 전 회차 — 로그에 경계 없음
                 run("killed", 600, "2026-09-28T10:00:02"), run("killed", 500, "2026-09-28T09:00:02"),
                 run("rot", 900, "2026-09-28T10:00:02"), run("rot", 800, "2026-09-27T10:00:02")]}
M = server._sched_log_md

print("[A] 절단 함수 — pid 정확 일치")
sl = getattr(server, "_sched_log_run_slice", None)
if not sl:
    check("_sched_log_run_slice 존재", False)
else:
    lines = open(os.path.join(LOG, "cut.out"), encoding="utf-8").read().splitlines()
    r = sl(lines, "100")
    check("pid=100 구간 = 시작 경계~끝 경계", r and r[0] == lines[1:5] and r[1] is True, str(r))
    check("pid=10 은 100·1000 에 걸리지 않는다", sl(lines, "10") is None)
    r = sl(lines, "1000")
    check("pid=1000 구간", r and "회차1000 줄" in r[0] and "회차100 줄1" not in r[0])

print("[B] 과거 회차 — 그 회차만")
md, _ = M("cut", DATA, run="100")
check("이 회차 출력이 보인다(stdout·stderr)", "회차100 줄1" in md and "경고100" in md, md)
check("다른 회차·경계 전 출력은 안 보인다", "회차1000" not in md and "오류1000" not in md and "옛 출력" not in md, md)
check("«경계로 잘랐다» 안내 · «구분 불가» 없음", "경계로 잘랐다" in md and "회차 구분 불가" not in md, md)

print("[C] 최신 회차")
md, _ = M("cut", DATA, run="1000")
check("최신 회차만", "회차1000 줄" in md and "오류1000" in md and "회차100 줄1" not in md, md)

print("[D] 끝 경계 없는 회차(강제 종료·실행 중)")
md, _ = M("killed", DATA, run="500")
check("다음 회차 시작 전까지만", "회차500 도중" in md and "회차600" not in md, md)
check("끝 경계 없음을 알린다", "끝 경계 없음" in md, md)

print("[E] 회전된 로그")
md, _ = M("rot", DATA, run="800")
check("회전된 `.1` 에서 찾는다", "회차800 줄(회전됨)" in md and "회차900" not in md, md)
check("회전 로그에서 왔음을 알린다", "rot.out.1" in md, md)

print("[F] 거짓 절단 금지")
md, _ = M("cut", DATA, run="42")
check("경계 없는 옛 회차 → «회차 구분 불가» 유지(자르지 않음)", "회차 구분 불가" in md and "경계로 잘랐다" not in md, md)
md, _ = M("cut", DATA)
check("run 없음 + 경계 있는 로그 → 거짓 «표식 없음» 안내를 하지 않는다", "경계 표식이 없어" not in md, md)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
