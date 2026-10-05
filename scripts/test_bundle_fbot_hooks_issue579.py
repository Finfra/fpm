#!/usr/bin/env python3
# test_bundle_fbot_hooks_issue579.py — Issue579 회귀 테스트 (tdd playlist `bundle-fbot-hooks-wired`)
#
# prj3#Issue739 M1-3 이 훅 2종(`fbot-agent-map.sh` — PreToolUse Agent·SubagentStart·SubagentStop,
# `fbot-sendmessage-record.sh` — PostToolUse SendMessage)을 만들었다. prj3 settings.json 에는 배선됐지만
# 번들·플러그인 hooks.json 에 없으면 플러그인 설치 머신에서는 SendMessage 로 넘긴 지시가 원장에 안 남는다.
#
# 무엇을 지키나
#   1. 번들 사본 = prj3 원본(md5)
#   2. 플러그인 hooks.json 배선 = prj3 settings.json 배선(이벤트·matcher·async·timeout) — 기대값을 settings.json
#      에서 **파생**한다(두 곳에 적으면 또 갈라진다)
#   3. data/scar-manifest.yml hooks[] 선언(+ Issue561 에서 반입한 lib 3종) · 인벤토리 점검 무결
#   4. prj3 테스트 2종을 **번들 사본 대상으로** 실행해 통과
#
# 실행: python3 scripts/test_bundle_fbot_hooks_issue579.py
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
B = os.path.join(REPO, "plugins", "fpm-core", "hooks")
LIVE = os.path.expanduser("~/.claude/hooks")
NEW = ("fbot-agent-map.sh", "fbot-sendmessage-record.sh")
PASS = FAIL = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  ok   {name}")
    else:
        FAIL += 1; print(f"  FAIL {name}")


def md5(p):
    return hashlib.md5(open(p, "rb").read()).hexdigest() if os.path.exists(p) else None


def wiring(hooks, name, root):
    """{(event, matcher, async, timeout)} — 이 훅 이름을 부르는 배선만."""
    out = set()
    for ev, blocks in (hooks or {}).items():
        for b in blocks:
            for h in b.get("hooks", []):
                c = h.get("command", "")
                if c.endswith("/" + name) and c.startswith(root):
                    out.add((ev, b.get("matcher"), bool(h.get("async")), h.get("timeout")))
    return out


print("[1] 번들 사본 = prj3 원본")
for n in NEW:
    check(f"{n} 번들 존재·md5 일치", md5(os.path.join(B, n)) is not None and md5(os.path.join(B, n)) == md5(os.path.join(LIVE, n)))

print("[2] 플러그인 hooks.json 배선 = prj3 settings.json 배선(파생)")
live_set = json.load(open(os.path.expanduser("~/.claude/settings.json"))).get("hooks", {})
plug = json.load(open(os.path.join(B, "hooks.json"))).get("hooks", {})
for n in NEW:
    want = wiring(live_set, n, "~/.claude/hooks")
    got = wiring(plug, n, "${CLAUDE_PLUGIN_ROOT}/hooks")
    check(f"{n}: 기대 배선 {len(want)}건이 있다(공허 비교 방지)", len(want) >= 1)
    check(f"{n}: 플러그인 배선 = prj3 배선 {sorted(want, key=str)}", got == want)

print("[3] 인벤토리 선언·점검")
man = open(os.path.join(REPO, "data", "scar-manifest.yml"), encoding="utf-8").read()
for n in NEW + ("lib/decision-question.py", "lib/session-end.py", "lib/shcmd.py"):
    check(f"scar-manifest.yml hooks[] 에 {n}", f"        - {n}" in man)
r = subprocess.run(["bash", os.path.join(REPO, "sh", "scar-hooks-check.sh")], capture_output=True, text=True)
out = r.stdout + r.stderr
check("점검: 캐시(__pycache__)는 어느 깊이든 인벤토리 대상이 아니다", "__pycache__" not in out)
check("점검: 이번 대상의 미선언·번들부재 0", not any(x in out for x in ("미선언: fbot-agent-map", "미선언: fbot-sendmessage", "미선언: lib/",
                                                      "없음: fbot-agent-map", "없음: fbot-sendmessage")))

print("[4] prj3 테스트 2종을 번들 사본 대상으로")
for t in ("test-fbot-agent-map.py", "test-fbot-sendmessage-record.py"):
    with tempfile.TemporaryDirectory() as d:
        for f in os.listdir(B):                       # 번들 훅·lib 를 한 폴더로 — 테스트의 HERE 가 이 폴더다
            if f != "__pycache__":
                os.symlink(os.path.join(B, f), os.path.join(d, f))
        shutil.copy(os.path.join(LIVE, t), os.path.join(d, t))
        rr = subprocess.run([sys.executable, os.path.join(d, t)], capture_output=True, text=True, timeout=300)
        tail = (rr.stdout.strip().splitlines() or [""])[-1]
        check(f"{t} (번들 사본) 통과 — {tail[:60]}", rr.returncode == 0)

print(f"\n결과: PASS {PASS} / FAIL {FAIL}")
sys.exit(1 if FAIL else 0)
