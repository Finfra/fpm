#!/usr/bin/env python3
"""Projects.md → Projects_map.htm 생성기.

설계 SSOT: _doc_arch/projects-map-design.md
표(### 📋 프로젝트) = 속성(id·경로·이모지·색) SSOT.
트리(# 프로젝트 트리) = 계층(소속) SSOT.
외부 의존 없음(표준 라이브러리만). Mermaid/mmdc 비의존 — 순수 HTML 트리.
"""

import argparse
import html
import os
import re
import sys
import urllib.parse
from pathlib import Path

MISC_LABEL = "미분류"

TABLE_ROW_RE = re.compile(
    r"^\|\s*(\d+)\s*\|([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)\|\s*$"
)
TREE_NODE_RE = re.compile(r"^(?P<indent>\s*)-\s+(?P<rest>.+?)\s*$")
ID_NODE_RE = re.compile(r"^(?P<id>\d+)\.\s+(?P<emoji>\S+)\s+(?P<name>.+)$")


def find_root(explicit):
    if explicit:
        return Path(explicit).resolve()
    # .claude/skills/projects-map/build_projects_map.py -> root = parents[3]
    return Path(__file__).resolve().parents[3]


def read_toggle(root):
    setting_path = root / "data" / "projects_map_setting.yml"
    if not setting_path.exists():
        return True
    for line in setting_path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\s*enabled\s*:\s*(true|false)\s*(#.*)?$", line, re.IGNORECASE)
        if m:
            return m.group(1).lower() == "true"
    return True


def parse_table(md_text):
    """id -> {name, path, emoji, color}"""
    table = {}
    in_table = False
    for line in md_text.splitlines():
        if line.strip().startswith("### 📋 프로젝트"):
            in_table = True
            continue
        if in_table:
            if line.strip().startswith("# ") or (
                line.strip() and not line.strip().startswith("|") and not line.strip().startswith(">")
            ):
                # left the table section (next heading or prose)
                if not line.strip().startswith("|"):
                    in_table = False
                    continue
            m = TABLE_ROW_RE.match(line)
            if m:
                pid = m.group(1).strip()
                name = m.group(2).strip()
                path = m.group(5).strip().strip("`")
                emoji = m.group(7).strip()
                color = m.group(8).strip()
                table[pid] = {"name": name, "path": path, "emoji": emoji, "color": color}
    return table


def parse_tree(md_text):
    """returns list of root nodes: {id?, label, children:[]}"""
    lines = md_text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.strip() == "# 프로젝트 트리":
            start = i
            break
    if start is None:
        return []
    # find fenced code block after heading
    fence_start = None
    for i in range(start, len(lines)):
        if lines[i].strip().startswith("```"):
            fence_start = i + 1
            break
        if i > start and lines[i].strip().startswith("# "):
            return []  # no fence before next heading
    if fence_start is None:
        return []
    fence_end = None
    for i in range(fence_start, len(lines)):
        if lines[i].strip().startswith("```"):
            fence_end = i
            break
    if fence_end is None:
        return []

    roots = []
    stack = []  # list of (depth, node)
    for raw in lines[fence_start:fence_end]:
        if not raw.strip():
            continue
        m = TREE_NODE_RE.match(raw)
        if not m:
            continue
        indent = len(m.group("indent"))
        depth = indent // 2
        rest = m.group("rest")
        idm = ID_NODE_RE.match(rest)
        if idm:
            node = {"id": idm.group("id"), "label": idm.group("name"), "children": []}
        else:
            node = {"id": None, "label": rest, "children": []}
        while stack and stack[-1][0] >= depth:
            stack.pop()
        if stack:
            stack[-1][1]["children"].append(node)
        else:
            roots.append(node)
        stack.append((depth, node))
    return roots


def collect_tree_ids(nodes):
    ids = set()
    for n in nodes:
        if n["id"]:
            ids.add(n["id"])
        ids |= collect_tree_ids(n["children"])
    return ids


def enforce_completeness(roots, table):
    tree_ids = collect_tree_ids(roots)
    missing = sorted((set(table.keys()) - tree_ids), key=int)
    if missing:
        misc = {"id": None, "label": MISC_LABEL, "children": []}
        for pid in missing:
            misc["children"].append({"id": pid, "label": table[pid]["name"], "children": []})
        roots.append(misc)
    return missing


def render_node(node, table, depth=0):
    if node["id"] is None:
        inner = "".join(render_node(c, table, depth + 1) for c in node["children"])
        return (
            f'<details open><summary>{html.escape(node["label"])}</summary>'
            f"<ul>{inner}</ul></details>"
        )

    pid = node["id"]
    meta = table.get(pid)
    if meta is None:
        return f'<li class="dead">{html.escape(pid)}. {html.escape(node["label"])} (표에 없음)</li>'

    path = os.path.expanduser(meta["path"])
    exists = os.path.exists(path)
    quoted = urllib.parse.quote(path, safe="/")
    file_href = "file://" + quoted
    vscode_href = "vscode://file" + quoted
    emoji = html.escape(meta["emoji"])
    name = html.escape(meta["name"])
    color = meta["color"] or "#dddddd"
    swatch = f'<span class="swatch" style="background:{html.escape(color)}"></span>'

    if exists:
        main_link = f'<a class="node-link" href="{file_href}">{emoji} {name}</a>'
    else:
        main_link = (
            f'<span class="node-link dead" title="경로 없음: {html.escape(path)}">'
            f"{emoji} {name}</span>"
        )

    children_html = "".join(render_node(c, table, depth + 1) for c in node["children"])
    children_block = f"<ul>{children_html}</ul>" if children_html else ""

    return (
        f'<li data-name="{html.escape(meta["name"].lower())}">'
        f"{swatch}{main_link} "
        f'<span class="id-tag">#{html.escape(pid)}</span> '
        f'<a class="mini-link" href="{vscode_href}" title="VSCode 로 열기">🆚</a> '
        f'<button type="button" class="copy-btn" data-copy="cdf {html.escape(pid)}" '
        f'title="cdf {html.escape(pid)} 복사">📋</button>'
        f"{children_block}</li>"
    )


HTML_HEAD = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Projects_map</title>
<style>
  :root { color-scheme: light dark; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    max-width: 900px; margin: 2rem auto; padding: 0 1rem; line-height: 1.6; }
  h1 { font-size: 1.4rem; }
  .meta { color: #777; font-size: 0.85rem; margin-bottom: 1rem; }
  input#filter { width: 100%; box-sizing: border-box; padding: 0.5rem; font-size: 1rem;
    margin-bottom: 1rem; }
  ul { list-style: none; padding-left: 1.2rem; }
  details { margin: 0.2rem 0; }
  summary { cursor: pointer; font-weight: 600; }
  li { margin: 0.15rem 0; }
  .swatch { display: inline-block; width: 0.7em; height: 0.7em; border-radius: 2px;
    margin-right: 0.3em; vertical-align: middle; }
  .node-link { text-decoration: none; }
  .node-link:hover { text-decoration: underline; }
  .node-link.dead { color: #999; text-decoration: line-through; cursor: not-allowed; }
  .id-tag { color: #999; font-size: 0.8em; }
  .mini-link, .copy-btn { font-size: 0.8em; text-decoration: none; border: none;
    background: none; cursor: pointer; opacity: 0.6; }
  .mini-link:hover, .copy-btn:hover { opacity: 1; }
  li.hidden { display: none; }
  #notes { margin-top: 2rem; padding-top: 1rem; border-top: 1px solid #ccc; }
  @media (prefers-color-scheme: dark) {
    body { background: #1e1e1e; color: #ddd; }
    #notes { border-top-color: #444; }
  }
</style>
</head>
<body>
<h1>Projects_map</h1>
"""

HTML_TAIL_SCRIPT = """
<script>
document.getElementById('filter').addEventListener('input', function (e) {
  var q = e.target.value.trim().toLowerCase();
  document.querySelectorAll('li[data-name]').forEach(function (li) {
    var name = li.getAttribute('data-name');
    li.classList.toggle('hidden', q.length > 0 && name.indexOf(q) === -1);
  });
});
document.querySelectorAll('.copy-btn').forEach(function (btn) {
  btn.addEventListener('click', function () {
    var text = btn.getAttribute('data-copy');
    function ok() {
      var o = btn.textContent;
      btn.textContent = '✓';
      setTimeout(function () { btn.textContent = o; }, 1000);
    }
    try {
      var ta = document.createElement('textarea');
      ta.value = text;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.focus();
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
      ok();
    } catch (e) {
      window.prompt('복사할 명령', text);
    }
  });
});
</script>
</body>
</html>
"""

DEFAULT_NOTES = "\n(여기에 수기 메모를 남기세요 — 재생성 시 이 구간만 보존됩니다)\n"


def extract_existing_notes(out_path):
    if not out_path.exists():
        return None
    text = out_path.read_text(encoding="utf-8")
    m = re.search(
        r"<!-- PROJECTS-MAP:NOTES -->(.*?)<!-- /PROJECTS-MAP:NOTES -->", text, re.DOTALL
    )
    if m:
        return m.group(1)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=None, help="___pm 루트 경로 (기본: 스크립트 위치 기준 자동)")
    ap.add_argument("--projects", default=None, help="Projects.md 경로 (기본: {root}/Projects.md)")
    ap.add_argument("--out", default=None, help="출력 경로 (기본: {root}/Projects_map.htm)")
    args = ap.parse_args()

    root = find_root(args.root)
    projects_path = Path(args.projects) if args.projects else root / "Projects.md"
    out_path = Path(args.out) if args.out else root / "Projects_map.htm"

    if not read_toggle(root):
        print("projects_map_setting.yml enabled=false — 생성 스킵(no-op)")
        return 0

    if not projects_path.exists():
        print(f"Projects.md 없음: {projects_path}", file=sys.stderr)
        return 1

    md_text = projects_path.read_text(encoding="utf-8")
    table = parse_table(md_text)
    roots = parse_tree(md_text)
    if not roots:
        print("# 프로젝트 트리 섹션(fenced code block)을 찾지 못함", file=sys.stderr)
        return 1

    missing = enforce_completeness(roots, table)

    tree_html = "<ul>" + "".join(render_node(n, table) for n in roots) + "</ul>"

    existing_notes = extract_existing_notes(out_path)
    notes_body = existing_notes if existing_notes is not None else DEFAULT_NOTES

    body = [
        HTML_HEAD,
        f'<div class="meta">프로젝트 {len(table)}건'
        + (f" · 미분류 편입 {len(missing)}건" if missing else "")
        + "</div>",
        '<input id="filter" type="text" placeholder="프로젝트명 필터…">',
        "<!-- PROJECTS-MAP:TREE -->",
        tree_html,
        "<!-- /PROJECTS-MAP:TREE -->",
        '<div id="notes">',
        "<!-- PROJECTS-MAP:NOTES -->",
        notes_body,
        "<!-- /PROJECTS-MAP:NOTES -->",
        "</div>",
        HTML_TAIL_SCRIPT,
    ]
    out_path.write_text("\n".join(body), encoding="utf-8")

    print(f"Projects_map.htm 생성 완료 — 프로젝트 {len(table)}건, 미분류 편입 {len(missing)}건")
    if missing:
        print(f"  미분류 id: {', '.join(missing)}")
    print(f"  출력: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
