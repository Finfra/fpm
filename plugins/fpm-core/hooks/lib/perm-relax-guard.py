#!/usr/bin/env python3
"""perm-relax-guard.py — 조직 선언(중앙 층)에서 권한 모드를 «완화»하는 편집인지 판정 (prj3#Issue859_2).

⚠️ 글로벌 SCAR 변경 가드 (Issue46): cwd ≠ ~/.claude 면 즉시 수정 금지 → Issue.md 등록 후 처리.

stdin = PreToolUse payload(JSON). 완화 = `permission_mode: bypass` 출현이 늘거나 `permission_mode: floor` 출현이 줄어드는 편집.
(자리를 통째 지우는 것도 floor 출현이 줄어 걸린다 — 완화는 사람 결정, 설계 fbot-org.md §선언 확장.)
Edit·MultiEdit 은 old/new 조각의 출현 수 비교, Write 는 기존 파일 전체 대비 비교. 완화면 rc 1 + stderr 사유, 아니면 rc 0.
판정 불가(JSON 오류·파일 읽기 실패)는 통과 — 가드가 일반 편집을 막는 피해가 더 크다(fail-open).
"""
import json
import os
import re
import sys

_KEY = r"""['"]?permission_mode['"]?\s*:\s*['"]?"""  # 따옴표 키·콜론 앞 공백·값 따옴표 변형 (Issue901)
_BY = re.compile(_KEY + r"bypass\b", re.I)
_FL = re.compile(_KEY + r"floor\b", re.I)


def _delta(old, new):
    return len(_BY.findall(new)) - len(_BY.findall(old)), len(_FL.findall(new)) - len(_FL.findall(old))


def main():
    try:
        d = json.load(sys.stdin)
    except ValueError:
        return 0
    ti = d.get("tool_input") or {}
    tool = d.get("tool_name", "")
    pairs = []
    if tool == "Edit":
        pairs = [(ti.get("old_string", ""), ti.get("new_string", ""))]
    elif tool == "MultiEdit":
        pairs = [(e.get("old_string", ""), e.get("new_string", "")) for e in ti.get("edits", [])]
    elif tool == "Write":
        try:
            with open(os.path.expanduser(ti.get("file_path", "")), encoding="utf-8") as fh:
                old = fh.read()
        except OSError:
            old = ""
        pairs = [(old, ti.get("content", ""))]
    for old, new in pairs:
        by, fl = _delta(old, new)
        if by > 0:
            print("권한 모드 `bypass` 지정 — 완화는 사람 결정(H:보안)", file=sys.stderr)
            return 1
        if fl < 0:
            print("권한 모드 `floor` 소거 — 완화는 사람 결정(H:보안)", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
