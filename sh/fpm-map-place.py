#!/usr/bin/env python3
# fpm-map-place.py — `Projects.md` `# Project Map` 트리에 신규 프로젝트 노드를 **한 곳에만** 넣는다 (Issue626)
#
# 트리 위치 = 무엇에 기대어 있는가(엔진·데이터를 물려받는 기반 prj) · `goal_parent` = 무엇을 위해 있는가(목적
# 축 그룹). 둘은 갈려도 정상이다(prj6 `project-identity-scheme.md` `goal_parent` 절). 기반 prj 가 있으면 그
# 항목 아래에만, 없으면 `goal_parent` 그룹 아래에만 둔다 — 사본을 두지 않는다.
#
# 사용: sh/fpm-map-place.py --id 9t --text "🎮⌨️ fTyping : fSnippet 홍보 게임" --under 25 [--dry-run] [--file Projects.md]
#   --under <id>     프로젝트 항목 아래(하위 끝, 들여쓰기 +2)
#   --under <그룹>   `### <그룹>` 서브맵 끝(들여쓰기 0) 또는 맵 안 그룹 노드(`- App 개발`) 하위 끝
# exit: 0=삽입(또는 dry-run) · 1=부모 없음·모호·입력 오류 · 2=이미 맵에 있는 id(단일 배치 위반)
import argparse
import os
import re
import sys

ID_RE = re.compile(r"^[0-9]+[A-Za-z]*$")
ITEM_RE = re.compile(r"^(\s*)-\s+@?([0-9]+[A-Za-z]*)\.\s")
LIST_RE = re.compile(r"^(\s*)-\s")


def default_file():
    base = os.environ.get("FPM_BASE") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "Projects.md")


def map_range(lines):
    """`# Project Map` 본문 구간 [start, end) — 다음 최상위 `# ` 헤더 전까지."""
    start = next((i for i, l in enumerate(lines) if l.rstrip() == "# Project Map"), None)
    if start is None:
        return None
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("# ")), len(lines))
    return start + 1, end


def subtree_end(lines, i, end):
    """노드 i 의 하위(더 깊게 들여쓴 연속 항목) 다음 행 번호."""
    n = len(LIST_RE.match(lines[i]).group(1))
    k = i + 1
    while k < end:
        m = LIST_RE.match(lines[k])
        if not m or len(m.group(1)) <= n:
            break
        k += 1
    return k, n + 2


def resolve(lines, s, e, under):
    """부모 → (삽입 행, 들여쓰기) 또는 에러 메시지."""
    if ID_RE.match(under):
        hits = [i for i in range(s, e) if (m := ITEM_RE.match(lines[i])) and m.group(2) == under]
        what = f"프로젝트 {under}"
    else:
        hits = [i for i in range(s, e)
                if lines[i].strip() == f"### {under}"
                or (LIST_RE.match(lines[i]) and lines[i].strip() == f"- {under}")]
        what = f"그룹 «{under}»"
    if not hits:
        return None, f"부모 없음: {what} 가 # Project Map 에 없다"
    if len(hits) > 1:
        return None, (f"부모 모호: {what} 가 {len(hits)}곳({', '.join(f'L{h + 1}' for h in hits)})에 있다"
                      " — 다중 부모 노드 아래는 자동 배치하지 않는다. 위치를 사람이 정한다")
    i = hits[0]
    if lines[i].startswith("###"):
        k = next((j for j in range(i + 1, e) if lines[j].startswith("#")), e)
        items = [j for j in range(i + 1, k) if LIST_RE.match(lines[j])]
        return ((items[-1] + 1) if items else i + 1, 0), None
    return subtree_end(lines, i, e), None


def main():
    ap = argparse.ArgumentParser(description="Project Map 트리에 노드 1줄을 한 곳에만 넣는다 (Issue626)")
    ap.add_argument("--id", required=True, help="프로젝트 id (ex) 9t)")
    ap.add_argument("--text", required=True, help="id 뒤 표기 (ex) '🎮⌨️ fTyping : fSnippet 홍보 게임')")
    ap.add_argument("--under", required=True, help="부모 — 프로젝트 id 또는 그룹명")
    ap.add_argument("--file", default=default_file())
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    if not ID_RE.match(a.id):
        print(f"입력 오류: id 형식 아님 «{a.id}»", file=sys.stderr)
        return 1
    with open(a.file, encoding="utf-8") as f:
        text = f.read()
    lines = text.split("\n")
    rng = map_range(lines)
    if rng is None:
        print("입력 오류: # Project Map 섹션 없음", file=sys.stderr)
        return 1
    s, e = rng

    dup = [i for i in range(s, e) if (m := ITEM_RE.match(lines[i])) and m.group(2) == a.id]
    if dup:
        print(f"단일 배치 위반: {a.id} 가 이미 맵에 있다({', '.join(f'L{i + 1}' for i in dup)}) — 사본을 두지 않는다",
              file=sys.stderr)
        return 2

    at, err = resolve(lines, s, e, a.under)
    if err:
        print(err, file=sys.stderr)
        return 1
    pos, indent = at
    line = f"{' ' * indent}- {a.id}. {a.text}"
    print(f"{'(dry-run) ' if a.dry_run else ''}L{pos + 1} 삽입 (부모 «{a.under}»): {line}")
    if a.dry_run:
        return 0
    lines.insert(pos, line)
    with open(a.file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
