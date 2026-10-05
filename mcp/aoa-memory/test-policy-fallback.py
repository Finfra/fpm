#!/usr/bin/env python3
"""test-policy-fallback.py — aoa-memory 정책 로더도 prj3 정본으로 폴백한다 (prj3#Issue757 · Issue626 · Issue755 관측)

⚠️ 글로벌 SCAR 변경 가드 (Issue46): cwd ≠ ~/.claude 면 즉시 수정 금지 → Issue.md 등록 후 처리.

무엇을 지키나 — «정책 수치의 정본은 prj3»(Issue626). fbot 계열 로더 5곳은 `aoa_dir()` → prj3 `policy.yml` →
`policy_org.yml` 순으로 찾는데, aoa-memory 로더만 `aoa_dir()` 하나를 보고 없으면 코드 기본값으로 떨어졌다.
그래서 운영 aoa 폴더에 그림자 사본(prj1 `fbot-bootstrap.sh` 생성, 미추적)이 생기면 prj3 정본이 가려지고,
사본을 걷으면 aoa-memory 값이 조용히 바뀐다(`lease_ttl_secs` 720 → 300). 순서는 fbot 계열과 같아야 한다:
  ① `aoa_dir()/policy.yml`(테스트 픽스처가 계속 이긴다) ② prj3 `~/.claude/data/aoa/policy.yml` ③ `policy_org.yml` ④ 기본값

HOME·AOA_MEMORY_DIR 을 임시 폴더로 돌려 subprocess 로 격리 실행한다. 실행: python3 mcp/aoa-memory/test-policy-fallback.py
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  ok   {name}")
    else:
        FAIL += 1; print(f"  FAIL {name} {str(detail)[:200]}")


def lease(home, aoa):
    code = f"import sys; sys.path.insert(0, {HERE!r}); import policy as P; print(P.load()['lease_ttl_secs'])"
    o = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                       env=dict(os.environ, HOME=home, AOA_MEMORY_DIR=aoa), timeout=20)
    return (o.stdout.strip() or o.stderr.strip()[-200:])


def main():
    tmp = tempfile.mkdtemp(prefix="aoa-policy-")
    home = os.path.join(tmp, "home"); p3 = os.path.join(home, ".claude", "data", "aoa"); os.makedirs(p3)
    aoa = os.path.join(tmp, "aoa"); os.makedirs(aoa)
    check("아무 정책도 없으면 기본값(300)", lease(home, aoa) == "300", lease(home, aoa))
    open(os.path.join(p3, "policy_org.yml"), "w").write("lease_ttl_secs: 222\n")
    check("③ prj3 policy_org.yml 폴백", lease(home, aoa) == "222", lease(home, aoa))
    open(os.path.join(p3, "policy.yml"), "w").write("lease_ttl_secs: 720\n")
    check("🔑 ② aoa 폴더에 사본이 없으면 prj3 정본(720)", lease(home, aoa) == "720", lease(home, aoa))
    open(os.path.join(aoa, "policy.yml"), "w").write("lease_ttl_secs: 111\n")
    check("① aoa 폴더 policy 가 있으면 그것(테스트 픽스처 우선 — fbot 계열과 같은 순서)", lease(home, aoa) == "111", lease(home, aoa))
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
