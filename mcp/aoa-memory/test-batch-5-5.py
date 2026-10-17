#!/usr/bin/env python3
"""test-batch-5-5.py — API 배치 경로가 5.5 세대 응답(adaptive thinking 기본 on)을 견딘다

⚠️ 글로벌 SCAR 변경 가드 (Issue46): cwd ≠ ~/.claude 면 즉시 수정 금지 → Issue.md 등록 후 처리.

무엇을 지키나 — Sonnet·Opus 5.5 는 thinking 을 끌 수 없고(adaptive 기본) thinking 이 `max_tokens` 를
함께 쓴다. 그래서 ① 요청 한도가 1024 처럼 작으면 본문이 잘리고 ② 응답 `content[0]` 이 thinking
block 일 수 있어 `content[0]["text"]` 는 KeyError 로 저장 전체가 롤백된다(2026-10-10 점검 — 5.5 이행).

실행: python3 mcp/aoa-memory/test-batch-5-5.py
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
    os.environ["AOA_MEMORY_DIR"] = tempfile.mkdtemp(prefix="aoa-batch55-")
    sys.path.insert(0, HERE)
    import worker as W   # noqa: E402

    print("\n[요청 한도 — thinking 몫을 남긴다]")
    lim = getattr(W, "LLM_BATCH_MAX_TOKENS", None)
    check("LLM_BATCH_MAX_TOKENS 상수 존재", lim is not None)
    check("한도 ≥ 4096", isinstance(lim, int) and lim >= 4096, lim)

    print("\n[본문 추출 — thinking block 이 앞에 와도 text 만 모은다]")
    fn = getattr(W, "message_text", None)
    check("message_text 존재", callable(fn))
    if callable(fn):
        msg = {"content": [{"type": "thinking", "thinking": "", "signature": "x"},
                           {"type": "text", "text": "요약 A"},
                           {"type": "text", "text": "요약 B"}]}
        check("thinking 선행 → text 결합", fn(msg) == "요약 A\n요약 B", fn(msg))
        check("text 단독", fn({"content": [{"type": "text", "text": "only"}]}) == "only")
        check("text 없음 → 빈 문자열", fn({"content": [{"type": "thinking", "thinking": ""}]}) == "")

    print(f"\n결과: {PASS} pass / {FAIL} fail")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
