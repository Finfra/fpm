#!/usr/bin/env python3
"""scan.py — fpm-core SCAR 스캔 → 항목 리스트 (Issue234 T7)

fpm-core 번들의 commands·skills·agents 를 스캔하여 frontmatter(name/description)
+ 본문을 추출한다. export emitter 의 입력.

항목 dict 스키마:
  {"kind": "command|skill|agent", "name": "...", "description": "...",
   "body": "...", "source": "plugins/fpm-core/..."}

설계 SSOT: _doc_work/plan/scar-crosstool-export_plan.md
"""
import os
import re
import sys
import json

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
_FPMCORE = os.path.join(_ROOT, "plugins", "fpm-core")

_FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.S)


def _parse_frontmatter(text):
    """md 텍스트 → (meta dict, body). frontmatter 없으면 ({}, text)."""
    m = _FM_RE.match(text)
    if not m:
        return {}, text.strip()
    raw, body = m.group(1), m.group(2)
    meta = {}
    for line in raw.splitlines():
        fm = re.match(r"^(\w[\w-]*):\s*(.*)$", line)
        if fm:
            key = fm.group(1).strip()
            val = fm.group(2).strip().strip('"').strip("'")
            meta[key] = val
    return meta, body.strip()


def _scan_md_dir(kind, dirpath):
    items = []
    if not os.path.isdir(dirpath):
        return items
    for fn in sorted(os.listdir(dirpath)):
        if not fn.endswith(".md"):
            continue
        path = os.path.join(dirpath, fn)
        with open(path, encoding="utf-8") as f:
            meta, body = _parse_frontmatter(f.read())
        name = meta.get("name") or meta.get("title") or fn[:-3]
        items.append({
            "kind": kind,
            "name": name,
            "description": meta.get("description", ""),
            "body": body,
            "source": os.path.relpath(path, _ROOT),
        })
    return items


def _scan_skills(dirpath):
    """skills/ 는 디렉토리별 SKILL.md|index.md."""
    items = []
    if not os.path.isdir(dirpath):
        return items
    for sd in sorted(os.listdir(dirpath)):
        sub = os.path.join(dirpath, sd)
        if not os.path.isdir(sub):
            continue
        src = None
        for cand in ("SKILL.md", "index.md"):
            p = os.path.join(sub, cand)
            if os.path.exists(p):
                src = p
                break
        if not src:
            continue
        with open(src, encoding="utf-8") as f:
            meta, body = _parse_frontmatter(f.read())
        name = meta.get("title") or meta.get("name") or sd
        items.append({
            "kind": "skill",
            "name": name,
            "description": meta.get("description", ""),
            "body": body,
            "source": os.path.relpath(src, _ROOT),
        })
    return items


def scan():
    items = []
    items += _scan_md_dir("command", os.path.join(_FPMCORE, "commands"))
    items += _scan_skills(os.path.join(_FPMCORE, "skills"))
    items += _scan_md_dir("agent", os.path.join(_FPMCORE, "agents"))
    return items


if __name__ == "__main__":
    items = scan()
    # 본문 길이만 요약(JSON 과대 방지)
    if "--summary" in sys.argv:
        from collections import Counter
        print("총 항목:", len(items))
        print("kind:", dict(Counter(i["kind"] for i in items)))
        for i in items:
            print(f"  [{i['kind']}] {i['name']}: {i['description'][:50]}")
    else:
        json.dump(items, sys.stdout, ensure_ascii=False, indent=2)
        print()
