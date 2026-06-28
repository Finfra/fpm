#!/usr/bin/env python3
"""emit.py — SCAR 항목 → Cursor·Codex·Gemini 포맷 생성 (Issue234 T7)

scan.py 의 항목 리스트를 받아 타깃 포맷 파일을 출력 디렉토리에 생성.
단방향 export — fpm-core 불변, 출력 디렉토리만 쓴다.

타깃:
  codex  → {out}/AGENTS.md        (단일 concat)
  gemini → {out}/GEMINI.md        (AGENTS.md 동일 본문)
  cursor → {out}/.cursor/rules/{name}.mdc  (항목별 frontmatter+body)

설계 SSOT: _doc_work/plan/scar-crosstool-export_plan.md
"""
import os
import sys

_HEADER = """# fPm SCAR (cross-tool export)

fPm(Finfra Project Manager) 의 SCAR(Skill/Command/Agent/Rule) 자산을 타 AI 코딩 툴용으로
export 한 파일입니다. 원본 SSOT 는 fpm-core 플러그인(Claude Code 포맷)이며, 본 파일은
단방향 미러입니다 — 편집은 원본(fpm-core)에서 하세요.

생성: scripts/scar-export.sh (Issue234 T7)

---
"""


def _concat_body(items, full=False):
    out = [_HEADER]
    by_kind = {}
    for i in items:
        by_kind.setdefault(i["kind"], []).append(i)
    kind_title = {"command": "Commands", "skill": "Skills", "agent": "Agents"}
    for kind in ("command", "skill", "agent"):
        group = by_kind.get(kind, [])
        if not group:
            continue
        out.append(f"\n# {kind_title[kind]}\n")
        for i in group:
            out.append(f"## {i['name']}\n")
            if i["description"]:
                out.append(f"{i['description']}\n")
            if full and i["body"]:
                out.append(f"\n{i['body']}\n")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def emit_codex(items, out_dir, full=False):
    path = os.path.join(out_dir, "AGENTS.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(_concat_body(items, full=full))
    return [path]


def emit_gemini(items, out_dir, full=False):
    path = os.path.join(out_dir, "GEMINI.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(_concat_body(items, full=full))
    return [path]


def _yaml_escape(s):
    """description 의 콜론·따옴표 안전화 → 큰따옴표 래핑."""
    s = (s or "").replace('"', "'")
    return f'"{s}"'


def emit_cursor(items, out_dir, full=True):
    rules_dir = os.path.join(out_dir, ".cursor", "rules")
    os.makedirs(rules_dir, exist_ok=True)
    # 이름 충돌 사전 탐지 — 같은 name 이 2개 이상 kind 에 있으면 kind 접미사로 분리
    from collections import Counter
    name_counts = Counter(i["name"] for i in items)
    written = []
    for i in items:
        name = i["name"]
        safe = "".join(c if (c.isalnum() or c in "-_") else "-" for c in name)
        if name_counts[name] > 1:
            safe = f"{safe}-{i['kind']}"  # 충돌 → kind 접미사 (fpm-cdf-command vs fpm-cdf-skill)
        path = os.path.join(rules_dir, f"{safe}.mdc")
        fm = [
            "---",
            f"description: {_yaml_escape(i['description'])}",
            "globs: []",
            "alwaysApply: false",
            f"# fpm-kind: {i['kind']}",
            f"# fpm-source: {i['source']}",
            "---",
            "",
        ]
        body = i["body"] if full else (i["description"] or "")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(fm) + f"# {name}\n\n{body}\n")
        written.append(path)
    return written


EMITTERS = {"codex": emit_codex, "gemini": emit_gemini, "cursor": emit_cursor}


if __name__ == "__main__":
    import argparse
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from scan import scan

    ap = argparse.ArgumentParser(description="SCAR export emitter")
    ap.add_argument("--target", default="all",
                    choices=["codex", "gemini", "cursor", "all"])
    ap.add_argument("--out", default="_export", help="출력 디렉토리")
    ap.add_argument("--full", action="store_true", help="본문 전체 포함(기본 description)")
    args = ap.parse_args()

    items = scan()
    os.makedirs(args.out, exist_ok=True)
    targets = list(EMITTERS) if args.target == "all" else [args.target]
    total = []
    for t in targets:
        full = args.full or (t == "cursor")
        written = EMITTERS[t](items, args.out, full=full)
        total += written
        print(f"[scar-export] {t}: {len(written)} 파일")
    print(f"[scar-export] 총 {len(total)} 파일 → {args.out} (항목 {len(items)})")
