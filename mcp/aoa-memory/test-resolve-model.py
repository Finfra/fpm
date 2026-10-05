#!/usr/bin/env python3
"""test-resolve-model.py — consolidation 모델 해석이 별칭(sonnet 등)을 받는다 (prj3#Issue850)

⚠️ 글로벌 SCAR 변경 가드 (Issue46): cwd ≠ ~/.claude 면 즉시 수정 금지 → Issue.md 등록 후 처리.

무엇을 지키나 — 학습 3단 티어(관찰 haiku · 정리 sonnet · 결정 opus)의 «정리» 가 consolidation 이다.
정책에는 **별칭만** 적는다(claude-model-rules «버전 고정» — 별칭은 settings `env`
`ANTHROPIC_DEFAULT_<TIER>_MODEL` 한 곳에서 버전으로 풀린다). Batch API 는 별칭을 받지 않으므로
worker 가 그 env 로 풀어야 하고, 풀 수 없으면 조용히 별칭을 보내지 말고 fail-loud 로 멈춘다.
키 우선순위: env `AOA_MEMORY_MODEL` > `consolidation_model`(종전 키) > `learn_consolidate_model`(3단 키).

실행: python3 mcp/aoa-memory/test-resolve-model.py
"""
import os
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


def main():
    tmp = tempfile.mkdtemp(prefix="aoa-resolve-")
    os.environ["AOA_MEMORY_DIR"] = tmp
    os.environ.pop("AOA_MEMORY_MODEL", None)
    for k in ("OPUS", "SONNET", "HAIKU"):
        os.environ.pop(f"ANTHROPIC_DEFAULT_{k}_MODEL", None)
    sys.path.insert(0, HERE)
    import worker as W   # noqa: E402

    print("\n[전체 ID 는 그대로]")
    check("consolidation_model 에 전체 ID", W.resolve_model({"consolidation_model": "sonnet-vfake"}) == "sonnet-vfake")

    print("\n[별칭 → env 로 버전 해석]")
    os.environ["ANTHROPIC_DEFAULT_SONNET_MODEL"] = "sonnet-vfake"
    check("sonnet 별칭이 env 로 풀린다", W.resolve_model({"learn_consolidate_model": "sonnet"}) == "sonnet-vfake")
    check("대문자 별칭도 같은 env", W.resolve_model({"learn_consolidate_model": "Sonnet"}) == "sonnet-vfake")

    print("\n[키 우선순위]")
    check("consolidation_model(종전 키)이 learn_consolidate_model 을 이긴다",
          W.resolve_model({"consolidation_model": "x-fake", "learn_consolidate_model": "sonnet"}) == "x-fake")
    os.environ["AOA_MEMORY_MODEL"] = "env-fake"
    check("env AOA_MEMORY_MODEL 이 전부를 이긴다",
          W.resolve_model({"consolidation_model": "x-fake"}) == "env-fake")
    os.environ.pop("AOA_MEMORY_MODEL")

    print("\n[fail-loud]")
    os.environ.pop("ANTHROPIC_DEFAULT_SONNET_MODEL")
    try:
        W.resolve_model({"learn_consolidate_model": "sonnet"})
        check("별칭인데 env 가 없으면 예외", False, "예외 없음")
    except RuntimeError as e:
        check("별칭인데 env 가 없으면 예외 — env 이름을 알려준다", "ANTHROPIC_DEFAULT_SONNET_MODEL" in str(e), str(e))
    try:
        W.resolve_model({})
        check("미지정은 예외(종전 계약 유지)", False, "예외 없음")
    except RuntimeError:
        check("미지정은 예외(종전 계약 유지)", True)

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
