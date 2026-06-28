#!/usr/bin/env python3
"""parse_issuemd.py — Issue.md → 구조화 이슈 리스트 (Issue233 T6)

Issue.md 의 상태머신 포맷을 파싱하여 이슈별 dict 리스트로 변환한다.
브리지(gh-sync) push/pull 의 입력. 관용적 파서 — 누락 필드는 skip, 파싱
불가 헤더는 경고 후 제외(silent 금지).

출력 dict 스키마(이슈 1건):
  {
    "num": 233,                    # Issue 번호 (int)
    "title": "[강화...] ...",       # 헤더 제목 (번호·메타 제거)
    "section": "🚧 진행중",          # 소속 섹션 (H1 헤더 텍스트, 이모지 포함)
    "state": "open",               # open(미완) | closed(✅ 완료/🚫 취소)
    "gh": 12,                      # 매핑된 GH issue 번호 (없으면 None)
    "fields": {"목적": "...", ...}, # * key: 값 불릿 (depends/plan/arch 등)
    "body_raw": "...",             # 헤더 다음~다음 이슈 전까지 원문 (gh body 용)
    "meta": "등록: 2026-06-28",      # 헤더 괄호 메타 원문
  }

설계 SSOT: _doc_work/plan/gh-issue-bridge_plan.md
"""
import re
import sys
import json

# H1 섹션 헤더: "# 🚧 진행중" 등 (Issue Management/결정사항 등 비-이슈 섹션 포함)
_SECTION_RE = re.compile(r"^#\s+(.*\S)\s*$")
# 이슈 헤더: "## Issue233: 제목 (등록: ...)" / "## Issue233_2: ..." (서브이슈)
_ISSUE_RE = re.compile(r"^##\s+Issue(\d+)(?:_\d+)?:\s*(.*?)\s*(?:\(([^)]*)\))?\s*✅?\s*$")
# 인라인 필드 불릿: "* 목적: ..." (1단계 불릿만)
_FIELD_RE = re.compile(r"^\*\s+([^:]+?):\s*(.*)$")
# gh 매핑 불릿: "* gh: #12" 또는 "* gh: 12"
_GH_RE = re.compile(r"^\*\s+gh:\s*#?(\d+)\s*$")

# 완료/종료로 간주할 섹션 (state=closed)
_CLOSED_SECTIONS = ("✅", "🚫")


def _state_for_section(section: str) -> str:
    """섹션 이모지로 open/closed 판정."""
    for marker in _CLOSED_SECTIONS:
        if section.startswith(marker):
            return "closed"
    return "open"


def parse(text: str, warn=None):
    """Issue.md 텍스트 → 이슈 dict 리스트. warn: 경고 콜백(메시지)."""
    if warn is None:
        warn = lambda m: print(f"[parse_issuemd] WARN: {m}", file=sys.stderr)

    issues = []
    cur_section = None
    cur = None
    body_lines = []

    def _flush():
        nonlocal cur, body_lines
        if cur is not None:
            cur["body_raw"] = "\n".join(body_lines).strip()
            issues.append(cur)
        cur = None
        body_lines = []

    for line in text.splitlines():
        sec = _SECTION_RE.match(line)
        if sec and not line.startswith("##"):
            _flush()
            cur_section = sec.group(1)
            continue

        iss = _ISSUE_RE.match(line)
        if iss:
            _flush()
            if cur_section is None:
                warn(f"섹션 밖 이슈 헤더 — skip: {line[:60]}")
                continue
            num = int(iss.group(1))
            title = iss.group(2).strip()
            meta = (iss.group(3) or "").strip()
            cur = {
                "num": num,
                "title": title,
                "section": cur_section,
                "state": _state_for_section(cur_section),
                "gh": None,
                "fields": {},
                "body_raw": "",
                "meta": meta,
            }
            continue

        if cur is not None:
            body_lines.append(line)
            ghm = _GH_RE.match(line)
            if ghm:
                cur["gh"] = int(ghm.group(1))
                continue
            fm = _FIELD_RE.match(line)
            if fm:
                key = fm.group(1).strip()
                val = fm.group(2).strip()
                # 첫 등장 우선 (중복 키는 무시)
                cur["fields"].setdefault(key, val)

    _flush()
    return issues


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Issue.md → JSON 이슈 리스트")
    ap.add_argument("path", nargs="?", default="Issue.md", help="Issue.md 경로")
    ap.add_argument("--section", help="특정 섹션만 필터")
    ap.add_argument("--mapped", action="store_true", help="gh 매핑 있는 이슈만")
    ap.add_argument("--unmapped", action="store_true", help="gh 매핑 없는 이슈만")
    args = ap.parse_args()

    with open(args.path, encoding="utf-8") as f:
        issues = parse(f.read())

    if args.section:
        issues = [i for i in issues if i["section"] == args.section]
    if args.mapped:
        issues = [i for i in issues if i["gh"] is not None]
    if args.unmapped:
        issues = [i for i in issues if i["gh"] is None]

    json.dump(issues, sys.stdout, ensure_ascii=False, indent=2)
    print()


if __name__ == "__main__":
    main()
