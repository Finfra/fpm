#!/usr/bin/env python3
"""map.py — 파싱 이슈 dict ↔ GitHub Issue payload 변환 (Issue233 T6)

parse_issuemd.py 의 이슈 dict 를 GitHub Issue payload(title/body/labels/state)로,
그리고 그 역으로 변환한다. 필드 매핑표는 gh-sync.yml 의 label_map 을 따른다.

매핑표(plan SSOT):
  ## Issue{N}: {제목}      → title  "[#{N}] {제목}"
  소속 섹션 (label_map)    → labels
  open/closed             → state
  목적·상세·구현명세 본문    → body (마커로 라운드트립 경계 표시)

body 마커: GH body 에 `<!-- fpm:issue:{N} -->` 를 심어 역방향(pull) 식별.

설계 SSOT: _doc_work/plan/gh-issue-bridge_plan.md
"""
import re

_BODY_MARKER = "<!-- fpm:issue:{num} -->"
_BODY_MARKER_RE = re.compile(r"<!--\s*fpm:issue:(\d+)\s*-->")


def to_gh_payload(issue: dict, label_map: dict) -> dict:
    """이슈 dict → GH payload {title, body, labels, state}."""
    num = issue["num"]
    title = f"[#{num}] {issue['title']}".strip()

    labels = []
    sec = issue.get("section", "")
    if sec in label_map:
        labels.append(label_map[sec])

    state = "closed" if issue.get("state") == "closed" else "open"

    # body: 마커 + 원문 본문(헤더 제외). 라운드트립 경계 보존.
    marker = _BODY_MARKER.format(num=num)
    body_raw = issue.get("body_raw", "").strip()
    body = f"{marker}\n\n{body_raw}" if body_raw else marker

    return {"title": title, "body": body, "labels": labels, "state": state}


def gh_to_summary(gh_issue: dict) -> dict:
    """GH issue(JSON from `gh issue view --json`) → 비교용 요약 dict.

    pull(역방향)에서 로컬과 diff 하기 위한 정규화. 마커로 로컬 Issue 번호 회수.
    """
    body = gh_issue.get("body") or ""
    m = _BODY_MARKER_RE.search(body)
    local_num = int(m.group(1)) if m else None

    title = gh_issue.get("title") or ""
    tm = re.match(r"\[#(\d+)\]\s*(.*)", title)
    title_clean = tm.group(2).strip() if tm else title.strip()
    if local_num is None and tm:
        local_num = int(tm.group(1))

    return {
        "gh_num": gh_issue.get("number"),
        "local_num": local_num,
        "title": title_clean,
        "state": (gh_issue.get("state") or "open").lower(),
        "labels": [l.get("name") for l in gh_issue.get("labels", []) if isinstance(l, dict)],
        "body": body,
    }


def diff_local_remote(local: dict, remote: dict) -> list:
    """로컬 이슈 dict vs GH 요약 dict 비교 → 차이 필드 리스트.

    local-wins 정책에서 'GH 가 로컬과 다른' 항목만 보고(pull dry-run 표시용).
    """
    diffs = []
    if local["title"] != remote["title"]:
        diffs.append(("title", local["title"], remote["title"]))
    l_state = "closed" if local.get("state") == "closed" else "open"
    if l_state != remote["state"]:
        diffs.append(("state", l_state, remote["state"]))
    return diffs


if __name__ == "__main__":
    import sys, json, argparse
    sys.path.insert(0, __file__.rsplit("/", 1)[0])
    from parse_issuemd import parse

    ap = argparse.ArgumentParser(description="이슈 → GH payload 변환 미리보기")
    ap.add_argument("path", nargs="?", default="Issue.md")
    ap.add_argument("--num", type=int, help="특정 이슈 번호만")
    args = ap.parse_args()

    # 간이 label_map (gh-sync.yml 미로딩 시 fallback)
    label_map = {
        "📕 중요": "priority:high",
        "📙 일반": "priority:normal",
        "📗 선택": "priority:low",
        "🚧 진행중": "status:in-progress",
    }
    with open(args.path, encoding="utf-8") as f:
        issues = parse(f.read())
    if args.num:
        issues = [i for i in issues if i["num"] == args.num]
    out = [to_gh_payload(i, label_map) for i in issues]
    json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
    print()
