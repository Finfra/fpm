#!/usr/bin/env python3
"""Issue.md → Issue_map.htm 생성기 (issue-map 스킬 본체).

Issue.md 의 이슈·depends·상태를 파싱해 mermaid 그래프를 만들고,
mmdc 로 SVG 선렌더한 뒤 자립형 HTML 문서로 조립한다.
외부 서버·네트워크 의존 없이 파일 하나로 열람 가능한 산출물을 만드는 것이 목적.

⚠️ 글로벌 SCAR 변경 가드 (Issue46): 본 스크립트는 모든 프로젝트가 공유.
  cwd ≠ ~/.claude 면 즉시 수정 금지 → ~/.claude/Issue.md 이슈 등록 후 처리.
  절차: ~/.claude/rules/global-scar-change-rules.md

사용 (nPTiR 루트 = Issue.md 위치에서 실행 — 경로는 플러그인 번들/글로벌 2단계 해석, Issue316):
    python3 "${CLAUDE_PLUGIN_ROOT:-$HOME/.claude}/skills/{fpm-issue-map|issue-map}/build_issue_map.py"
        [--check] [--all] [--deadlock] [--no-cross] [--out Issue_map.htm]
"""

import argparse
import functools
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
from datetime import date
from pathlib import Path

# ── 섹션 → 표시·색상 매핑 ────────────────────────────────────────────────
SECTIONS = {
    "✅ 완료": ("완료", "done"),
    "🚧 진행중": ("진행중", "prog"),
    "📕 중요": ("📕 중요", "imp"),
    "📙 일반": ("📙 일반", "norm"),
    "📗 선택": ("📗 선택", "opt"),
    "⏸️ 보류": ("⏸️ 보류", "held"),
    "🚫 취소": ("🚫 취소", "held"),
}
DONE_SECTIONS = {"✅ 완료"}
# 맵에서 제외하는 섹션 (Issue259). 이슈맵은 "지금 무엇을 할 수 있고 무엇이 막혀 있는가"를
# 보는 도구라 보류·취소 이슈가 노드로 남으면 활성 흐름의 시야를 흐린다.
# 단, 활성 이슈가 선행으로 가리키는 경우만 유령 노드로 남긴다 (아래 split_excluded).
EXCLUDED_SECTIONS = {"⏸️ 보류", "🚫 취소"}

CLASS_DEFS = """    classDef done fill:#d8ecd8,stroke:#5a9a5a,color:#1a1a1a
    classDef prog fill:#cfe6f5,stroke:#4a90c4,color:#1a1a1a
    classDef imp fill:#f6d5d5,stroke:#c06a6a,color:#1a1a1a
    classDef norm fill:#d9e8f5,stroke:#6f9dc4,color:#1a1a1a
    classDef opt fill:#e8e8e8,stroke:#9a9a9a,color:#1a1a1a
    classDef held fill:#ededed,stroke:#9a9a9a,color:#5a5a5a,stroke-dasharray:5 4
    classDef ext fill:#fdf0dc,stroke:#c08a3e,color:#1a1a1a,stroke-dasharray:5 4
    classDef extdone fill:#e4f0e0,stroke:#6f9a5a,color:#1a1a1a,stroke-dasharray:5 4
    classDef extunk fill:#eeeeee,stroke:#9a9a9a,color:#5a5a5a,stroke-dasharray:2 3"""

EDGE_GO = "#2f8a2f"     # 선행 완료 → 착수 가능
EDGE_BLOCK = "#c0392b"  # 선행 미완료 → 차단
EDGE_REF = "#9a9a9a"    # 참조 관계 · 미확인 (차단 판정 불가)
EDGE_HELD = "#8a7ab0"   # 선행이 보류·취소 → 차단이나 자동 해제 없음 (Issue259)

# ── 타 프로젝트 연동 (Issue252) ──────────────────────────────────────────
# prj 번호 → 경로 SSOT. 파일 하나당 경로 1줄(ex: projects/1 = "~/_git/___pm").
PROJECTS_DIR = Path.home() / "_git" / "___pm" / "projects"
MAX_HOPS = 3        # 교착 탐색: prj 경계를 넘는 최대 홉 (opus-4-8 루프 상한 준수)
MAX_PROJECTS = 20   # 교착 탐색: 열어 볼 프로젝트 상한


# ── 파싱 ────────────────────────────────────────────────────────────────
def parse_dep_token(tok: str):
    """`* depends:` 의 쉼표 조각 1개 → ('local', None, 'Issue3') | ('ext', 'prj1', 'Issue286') | None.

    실측된 표기 편차를 모두 흡수한다 (Issue252, prj3 22건 기준):
        prj1#Issue286 / ___pm#Issue99 / ~/.claude#Issue28 / `___pm#Issue66`
        prj1 ___pm#Issue98(혼합) / prj1#Issue269 (완료 — …)(주석 동반)
    괄호 주석은 위치 무관하게 제거한다 — 뒤가 아니라 중간에 오는 사례가 있어
    기존의 '끝 괄호만 제거' 로는 토큰이 통째로 안 잡혔다.
    """
    t = re.sub(r"\([^)]*\)", " ", tok.replace("`", "")).strip()
    if not t:
        return None
    m = re.match(r"^(?P<ref>[^#\s][^#]*?)\s*#\s*(?P<iid>Issue[\w_]+)", t)
    if m:
        # 'prj1 ___pm' 처럼 두 표기를 겹쳐 쓴 경우 마지막 토큰이 실제 참조 대상
        return ("ext", m.group("ref").split()[-1], m.group("iid"))
    m = re.match(r"^(Issue[\w_]+)", t)
    return ("local", None, m.group(1)) if m else None


def parse_issue_md(path: Path):
    """Issue.md → {id: {...}} 순서 보존 dict."""
    issues, section = {}, None
    current = None
    for line in path.read_text().splitlines():
        m_sec = re.match(r"^#\s+(.+?)\s*$", line)
        if m_sec and m_sec.group(1) in SECTIONS:
            section, current = m_sec.group(1), None
            continue
        m_iss = re.match(r"^(#{2,3})\s+(Issue[\w_]+)\s*:\s*(.+?)\s*$", line)
        if m_iss and section:
            iid, title = m_iss.group(2), m_iss.group(3)
            title = re.sub(r"\s*\((등록|해결|완료)[^)]*\)\s*", "", title).strip()
            title = title.replace("✅", "").strip()
            current = {
                "id": iid,
                "title": title,
                "section": section,
                "done": section in DONE_SECTIONS or line.rstrip().endswith("✅"),
                "depends": [],
                "ext": [],          # [(ref, IssueID)] — 타 프로젝트 선행 (Issue252)
                "trigger": None,
                "note": None,
                "commit": None,
                "ghost": False,     # 제외 섹션이지만 활성 선행이라 남긴 노드 (Issue259)
                "sub": "_" in iid,
            }
            issues[iid] = current
            continue
        if current is None:
            continue
        m_dep = re.match(r"^\*\s+depends\s*:\s*(.+?)\s*$", line)
        if m_dep:
            for d in m_dep.group(1).split(","):
                parsed = parse_dep_token(d)
                if not parsed:
                    continue
                kind, ref, iid = parsed
                if kind == "local":
                    current["depends"].append(iid)
                else:                       # 타 prj 는 버리지 않고 보존 (Issue252)
                    current["ext"].append((ref, iid))
            continue
        m_trg = re.match(r"^\*\s+trigger\s*:\s*(.+?)\s*$", line)
        if m_trg:
            current["trigger"] = m_trg.group(1).strip()
            continue
        m_st = re.match(r"^\*\s+status\s*:\s*(.+?)\s*$", line)
        if m_st:
            current["note"] = m_st.group(1).strip()
            continue
        m_cm = re.match(r"^\s*-\s+commit\s*:\s*(.+?)\s*$", line)
        if m_cm and not current["commit"]:
            current["commit"] = m_cm.group(1).strip()
    # 서브 이슈(IssueN_M)는 depends 미선언 시 부모 이슈를 암묵 선행으로 연결
    for iid, iss in issues.items():
        if iss["sub"] and not iss["depends"]:
            parent = iid.rsplit("_", 1)[0]
            if parent in issues:
                iss["depends"].append(parent)
    return issues


def split_excluded(issues):
    """⏸️ 보류 · 🚫 취소 이슈를 맵에서 제거 (Issue259). → 유령으로 남긴 id 집합.

    통째로 지우면 활성 이슈가 그 이슈에 `* depends:` 를 걸고 있을 때
    화살표가 소리 없이 사라져 '차단 중' 이라는 사실이 맵에서 실종된다.
    그래서 **활성 이슈의 선행으로 참조된 것만** 유령 노드(회색 점선)로 남기고,
    나머지는 노드·표 양쪽에서 제거한다. 유령은 그래프에만 있고 표에는 안 나온다.
    """
    excluded = {k for k, v in issues.items() if v["section"] in EXCLUDED_SECTIONS}
    if not excluded:
        return frozenset()
    # 참조자가 이미 완료면 그 화살표는 볼 이유가 없다 — 미완료 후행만 유령을 살린다
    ghosts = {d for k, v in issues.items() if k not in excluded and not v["done"]
              for d in v["depends"] if d in excluded}
    for iid in excluded - ghosts:
        del issues[iid]
    for iid in ghosts:
        iss = issues[iid]
        iss["ghost"] = True
        # 유령의 선행은 그릴 이유가 없다 — 제외 이슈끼리의 사슬은 맵의 관심사가 아니다
        iss["depends"], iss["ext"] = [], []
    return frozenset(ghosts)


# ── 타 프로젝트 해석·교착 진단 (Issue252) ───────────────────────────────
class CrossResolver:
    """타 prj 선행의 경로·상태를 해석하고 prj 를 가로지르는 순환 대기를 찾는다.

    해석 불가(경로 없음·이슈 없음)는 조용히 넘기지 않고 '미확인' 으로 남겨
    보고서에 그대로 드러낸다 — 못 읽은 것을 '차단 아님' 으로 오인하면
    이슈맵이 거짓 안전 신호를 주기 때문이다.
    """

    def __init__(self, root: Path, enabled=True):
        self.root = root.resolve()
        self.enabled = enabled
        self.projects = self._load_projects()
        self._issues = {}                       # {경로str: {id: issue}} 파싱 캐시
        self.unresolved = []                    # [(ref, iid, 사유)]

    @staticmethod
    def _load_projects():
        """{'prj1': Path, '___pm': Path, '.claude': Path, '~/.claude': Path, …}"""
        out = {}
        if not PROJECTS_DIR.is_dir():
            return out
        for f in sorted(PROJECTS_DIR.iterdir()):
            if not f.is_file() or not f.name.isdigit():
                continue
            try:
                raw = f.read_text().strip()
            except OSError:
                continue
            if not raw:
                continue
            p = Path(os.path.expanduser(raw))
            out.setdefault(f"prj{f.name}", p)
            out.setdefault(p.name, p)           # basename 별칭 (___pm · .claude · ___common)
            out.setdefault(raw, p)              # 원문 별칭 (~/.claude)
        return out

    def resolve(self, ref: str):
        """참조 표기 → 프로젝트 경로. 미등록이면 None."""
        if not self.enabled:
            return None
        ref = ref.strip().rstrip(":")
        return self.projects.get(ref) or self.projects.get(ref.lstrip("~/"))

    def prj_label(self, path: Path):
        """경로 → 'prj3' 표기(역방향). 매핑에 없으면 폴더명."""
        for k, v in self.projects.items():
            if k.startswith("prj") and v.resolve() == path.resolve():
                return k
        return path.name

    def issues_of(self, path: Path):
        """대상 프로젝트 Issue.md 파싱 (프로젝트당 1회)."""
        key = str(path.resolve())
        if key not in self._issues:
            f = path / "Issue.md"
            self._issues[key] = parse_issue_md(f) if f.exists() else {}
        return self._issues[key]

    def status(self, ref: str, iid: str):
        """외부 선행 1건의 상태. ok=False 면 '미확인'(차단 판정 불가)."""
        path = self.resolve(ref)
        if path is None:
            self.unresolved.append((ref, iid, "prj 매핑 없음"))
            return {"ok": False, "reason": f"prj 매핑 없음 ({ref})", "done": False,
                    "path": None, "title": "", "section": ""}
        if not (path / "Issue.md").exists():
            self.unresolved.append((ref, iid, f"Issue.md 없음 ({path})"))
            return {"ok": False, "reason": f"Issue.md 없음 ({path})", "done": False,
                    "path": path, "title": "", "section": ""}
        iss = self.issues_of(path).get(iid)
        if iss is None:
            self.unresolved.append((ref, iid, "대상 Issue.md 에 해당 이슈 없음"))
            return {"ok": False, "reason": "대상 Issue.md 에 해당 이슈 없음",
                    "done": False, "path": path, "title": "", "section": ""}
        return {"ok": True, "reason": "", "done": iss["done"], "path": path,
                "title": iss["title"], "section": SECTIONS[iss["section"]][0]}

    # ── 교착(순환 대기) 진단 ────────────────────────────────────────────
    def deadlocks(self, issues):
        """로컬+외부를 합친 대기 그래프에서 순환을 찾는다 → [[표기, …], …].

        노드 = (프로젝트 경로str, 이슈 id). 간선 = '기다린다' 방향(후행 → 선행).
        순환이 있으면 서로가 서로의 완료를 기다리므로 아무도 진행할 수 없다 = 교착.
        탐색은 홉·프로젝트 상한으로 끊는다(무한 탐색 금지).
        """
        cycles, seen_cycle = [], set()
        opened = set()

        def label(node):
            p, iid = node
            return iid if p == str(self.root) else f"{self.prj_label(Path(p))}#{iid}"

        def issues_at(pstr):
            return issues if pstr == str(self.root) else self.issues_of(Path(pstr))

        def walk(node, stack, hops):
            if node in stack:                       # 되돌아옴 = 순환
                cyc = stack[stack.index(node):] + [node]
                key = frozenset(cyc)
                if key not in seen_cycle:
                    seen_cycle.add(key)
                    cycles.append([label(n) for n in cyc])
                return
            if hops > MAX_HOPS or len(opened) > MAX_PROJECTS:
                return
            pstr, iid = node
            iss = issues_at(pstr).get(iid)
            if iss is None or iss["done"]:          # 완료된 선행은 아무도 안 막는다
                return
            stack = stack + [node]
            for dep in iss["depends"]:
                walk((pstr, dep), stack, hops)
            for ref, dep_iid in iss["ext"]:
                target = self.resolve(ref)
                if target is None or not (target / "Issue.md").exists():
                    continue                        # 미확인은 unresolved 로 별도 보고
                opened.add(str(target.resolve()))
                walk((str(target.resolve()), dep_iid), stack, hops + 1)

        if not self.enabled:
            return []
        for iid, iss in issues.items():
            if not iss["done"] and (iss["ext"] or iss["depends"]):
                walk((str(self.root), iid), [], 0)
        return cycles


def load_stage_map(root: Path):
    """선택 파일 data/issue_stage_map.json → {stage: [issue id]}. 없으면 {}."""
    p = root / "data" / "issue_stage_map.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception as e:
        print(f"⚠️  stage map 파싱 실패({p}): {e} — 단계 그룹 없이 진행", file=sys.stderr)
        return {}


# ── mermaid 생성 ────────────────────────────────────────────────────────
def esc(s):
    # 백틱 제거: 라벨 선두 백틱은 mermaid 가 markdown-string("`...`") 으로 오인해
    #            "Lexical error / Unrecognized text" 로 렌더가 통째 실패한다 (Issue247).
    #            다이어그램에서 코드체 표기는 의미가 없으므로 전량 제거가 안전.
    return s.replace('"', "'").replace("|", "/").replace("`", "")


def node_line(iss):
    if iss["ghost"]:                      # 보류·취소 선행 (Issue259)
        icon = SECTIONS[iss['section']][0]
    else:
        icon = "✅" if iss["done"] else ""
    # 헤더 아이콘 겹침 방지 — 이모지를 inline-block span 에 담아 id 와 간격 고정
    #   (글리프 실폭이 달라도 일정, projects-map 과 동일 방식)
    mark = (f'<span style="display:inline-block;margin-left:0.3em">{icon}</span>'
            if icon else "")
    label = f"{iss['id']}{mark}<br>{esc(iss['title'])[:42]}"
    return f'    {iss["id"]}["{label}"]'


def settled(issues):
    """정리 완료 = 자신도 완료 + 후행도 전부 완료(또는 후행 없음).

    더 볼 것이 없는 노드라 그래프에서 제외해 잔여 작업만 남긴다.
    (표에는 그대로 남으므로 정보 손실 없음)
    """
    out = set()
    for iid, iss in issues.items():
        if not iss["done"]:
            continue
        succ = [o for o in issues.values() if iid in o["depends"]]
        if all(s["done"] for s in succ):
            out.add(iid)
    return out


def linked_ids(issues, hidden=frozenset()):
    """가시 노드끼리 실제로 이어진 edge 의 양끝 id 집합 (Issue247).

    고립 노드(화살표가 하나도 안 붙은 이슈)는 의존 관계도에 기여하지 않으므로
    그래프에서 빼고 '진행 전 이슈' 목록으로 돌린다.
    """
    visible = {k for k in issues if k not in hidden}
    linked = set()
    for iid in visible:
        for dep in issues[iid]["depends"]:
            if dep in visible:
                linked.add(iid)
                linked.add(dep)
        if issues[iid]["ext"]:      # 타 prj 선행도 연결이다 (Issue252)
            linked.add(iid)
    return linked


def ext_node_id(ref, iid):
    """'prj1', 'Issue286' → 'EXT_prj1_Issue286' (mermaid id 에 '#'·'~'·'.' 불가)."""
    return "EXT_" + re.sub(r"[^0-9A-Za-z_]", "_", f"{ref}_{iid}")


@functools.lru_cache(maxsize=None)
def repo_github_issues_url(path_str: str):
    """path 의 git remote origin 이 github 저장소면 Issues 탭 URL, 아니면 None (Issue274).

    private repo 여부까지는 로컬에서 판정 불가 — remote 가 github 형식이면 시도하고,
    존재 자체를 알 수 없는 경우(remote 없음·git 아님)만 확실히 None 으로 비운다.
    """
    try:
        r = subprocess.run(["git", "-C", path_str, "remote", "get-url", "origin"],
                           capture_output=True, text=True, timeout=3)
    except Exception:
        return None
    if r.returncode != 0:
        return None
    m = re.search(r"github\.com[:/]+([^/\s]+)/([^/\s]+?)(?:\.git)?/?$", r.stdout.strip())
    return f"https://github.com/{m.group(1)}/{m.group(2)}/issues" if m else None


def click_target(path):
    """카드 클릭 목적지 (Issue274) — Issue.md 로컬 파일 열기 우선, 없으면 GitHub Issues,
    remote 도 없으면(비공개·미설정) None → 클릭 비활성(에러 없이 graceful)."""
    if path is None:
        return None
    issue_md = path / "Issue.md"
    if issue_md.exists():
        return "file://" + urllib.parse.quote(str(issue_md))
    return repo_github_issues_url(str(path))


def build_graph_mmd(issues, stage_map, hidden=frozenset(), resolver=None):
    lines = ["flowchart TD"]
    visible = {k: v for k, v in issues.items() if k not in hidden}
    grouped = set()
    for stage, ids in stage_map.items():
        members = [i for i in ids if i in visible]
        if not members:
            continue
        lines.append(f'    subgraph SG_{abs(hash(stage)) % 10**6}["{esc(stage)}"]')
        for iid in members:
            lines.append("    " + node_line(visible[iid]))
            grouped.add(iid)
        lines.append("    end")
    for iid, iss in visible.items():
        if iid not in grouped:
            lines.append(node_line(iss))

    def edge_label(iss, dep=None):
        # 화살표 라벨은 60자에서 끊는다 — 전문은 '전이 트리거' 표에 그대로 남는다
        trg = esc(iss["trigger"]) if iss["trigger"] else ""
        trg = trg[:60] + "…" if len(trg) > 60 else trg
        # 선행이 보류·취소면 그 사실을 화살표에 박는다 — 노드만 회색이면
        # "왜 안 풀리는지" 가 안 보인다 (Issue259)
        if dep is not None and dep["ghost"]:
            held = SECTIONS[dep["section"]][0]
            trg = f"{held} · {trg}" if trg else f"{held} — 자동 해제 없음"
        return f'|"{trg}"|' if trg else ""

    edges, styles = [], {"go": [], "block": [], "unknown": [], "held": []}
    ext_nodes = {}                     # {node_id: (라벨, 완료 여부, 확인 가능 여부, 대상 경로)}
    idx = 0
    for iid, iss in visible.items():
        for dep in iss["depends"]:
            if dep not in visible:
                continue
            edges.append(f"    {dep} -->{edge_label(iss, issues[dep])} {iid}")
            if issues[dep]["ghost"]:
                styles["held"].append(idx)
            else:
                styles["go" if issues[dep]["done"] else "block"].append(idx)
            idx += 1
        # 타 prj 선행 — 점선 테두리 노드로 그래프에 편입 (Issue252)
        if resolver is None or not resolver.enabled:
            continue
        for ref, dep_iid in iss["ext"]:
            st = resolver.status(ref, dep_iid)
            nid = ext_node_id(ref, dep_iid)
            ext_nodes[nid] = (f"{ref}#{dep_iid}", st["done"], st["ok"], st["path"])
            edges.append(f"    {nid} -->{edge_label(iss)} {iid}")
            styles["go" if st["done"] else ("block" if st["ok"] else "unknown")].append(idx)
            idx += 1
    for nid, (label, done, ok, _path) in ext_nodes.items():
        mark = " ✅" if done else ("" if ok else " ⚠️")
        lines.append(f'    {nid}["{esc(label)}{mark}<br>타 프로젝트"]')

    # 카드 클릭 동작 (Issue274) — 이모지(완료 ✅ · 보류/취소 마크) 미출력 카드만 대상.
    # Issue.md 로컬 파일 열기 우선 → 없으면 GitHub Issues → 그것도 없으면 클릭 비활성.
    clicks = []
    local_root = resolver.root if resolver is not None else None
    for iid, iss in visible.items():
        if iss["done"] or iss["ghost"]:
            continue
        url = click_target(local_root)
        if url:
            clicks.append(f'    click {iid} "{url}" "_blank"')
    for nid, (_label, done, ok, path) in ext_nodes.items():
        if done or not ok:                 # ✅ 완료 · ⚠️ 미확인은 이미 이모지로 상태 표시됨
            continue
        url = click_target(path)
        if url:
            clicks.append(f'    click {nid} "{url}" "_blank"')

    lines.append("")
    lines.extend(edges)
    lines.append("")
    lines.append(CLASS_DEFS)
    for iid, iss in visible.items():
        lines.append(f'    class {iid} {"held" if iss["ghost"] else SECTIONS[iss["section"]][1]}')
    for nid, (_, done, ok, _path) in ext_nodes.items():
        lines.append(f'    class {nid} {"extdone" if done else ("ext" if ok else "extunk")}')
    if clicks:
        lines.append("")
        lines.extend(clicks)
    if styles["go"]:
        lines.append(f'    linkStyle {",".join(map(str, styles["go"]))} '
                     f"stroke:{EDGE_GO},stroke-width:2.5px,color:#1f6b1f")
    if styles["block"]:
        lines.append(f'    linkStyle {",".join(map(str, styles["block"]))} '
                     f"stroke:{EDGE_BLOCK},stroke-width:2px,color:#8f2a1f")
    if styles["unknown"]:               # 미확인 외부 선행 — 차단 여부 판정 불가
        lines.append(f'    linkStyle {",".join(map(str, styles["unknown"]))} '
                     f"stroke:{EDGE_REF},stroke-width:2px,stroke-dasharray:5 4,color:#6a6a6a")
    if styles["held"]:                  # 보류·취소 선행 — 대기해도 자동으로 안 풀림
        lines.append(f'    linkStyle {",".join(map(str, styles["held"]))} '
                     f"stroke:{EDGE_HELD},stroke-width:2px,stroke-dasharray:5 4,color:#6a5a80")
    return "\n".join(lines) + "\n"


# ── SVG 렌더 ────────────────────────────────────────────────────────────
def render_svg(mmd_text: str, workdir: Path, name: str) -> str:
    if not shutil.which("mmdc"):
        raise RuntimeError("mmdc 미설치 — `npm i -g @mermaid-js/mermaid-cli` 후 재실행")
    src, dst = workdir / f"{name}.mmd", workdir / f"{name}.svg"
    src.write_text(mmd_text)
    # securityLevel 기본값(strict)은 click href 를 무시한다 — 카드 클릭(Issue274)이
    # 실제 <a> 링크로 렌더되려면 loose 필요. 이 그래프는 신뢰된 로컬 산출물이라 위험 없음.
    cfg = workdir / "mermaid.config.json"
    if not cfg.exists():
        cfg.write_text(json.dumps({"securityLevel": "loose"}))
    env = dict(os.environ)
    if "PUPPETEER_EXECUTABLE_PATH" not in env:
        chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        if Path(chrome).exists():
            env["PUPPETEER_EXECUTABLE_PATH"] = chrome  # puppeteer 내장 Chrome 부재 대비
    r = subprocess.run(["mmdc", "-i", str(src), "-o", str(dst), "-b", "transparent",
                       "-c", str(cfg)],
                       capture_output=True, text=True, env=env)
    if r.returncode != 0 or not dst.exists():
        raise RuntimeError(f"mmdc 렌더 실패 ({name}):\n{r.stderr.strip()[-800:]}")
    s = dst.read_text()
    s = s[s.index("<svg"):]
    return fit_svg(s)


def fit_svg(s: str) -> str:
    """svg 여는 태그의 style 을 '병합'해 자연 크기 이상으로 확대되지 않게 한다 (Issue251).

    mmdc 산출물은 이미 자기 style(`max-width: NNNpx`)을 갖고 있다. 여기에 style 을
    덧붙이면 같은 속성이 2개인 태그가 되고, 브라우저는 앞의 것만 채택하므로
    mermaid 가 계산한 자연 폭 상한이 통째로 사라진다 → 노드 2~3개짜리 그래프가
    컨테이너 폭(960px)까지 확대되어 글자가 거대해진다. 덧붙이지 말고 재작성할 것.
    """
    head_end = s.index(">")
    head, body = s[:head_end], s[head_end:]
    m = re.search(r"max-width:\s*([\d.]+)px", head)
    cap = f"min(100%, {m.group(1)}px)" if m else "100%"
    head = re.sub(r'\s(?:style|width)="[^"]*"', "", head)   # 기존 style·고정 폭 제거
    head = head.replace(
        "<svg",
        f'<svg style="max-width:{cap};height:auto;display:block;margin:0 auto"', 1)
    return head + body


# ── HTML 조립 ───────────────────────────────────────────────────────────
def status_text(iss, issues, resolver=None):
    if iss["done"]:
        return "✅ 완료" + (f" ({iss['commit']})" if iss["commit"] else "")
    if iss["note"]:
        return iss["note"]
    # 보류·취소 선행은 '기다리면 풀리는 차단' 이 아니므로 상태 문구에 그 사실을 남긴다 (Issue259)
    blockers = [f"{d} {SECTIONS[issues[d]['section']][0]}" if issues[d]["ghost"] else d
                for d in iss["depends"] if d in issues and not issues[d]["done"]]
    unknown = []
    cross = resolver is not None and resolver.enabled     # --no-cross 면 기존 동작 유지
    for ref, dep_iid in (iss["ext"] if cross else []):    # 타 prj 선행도 차단 요인 (Issue252)
        st = resolver.status(ref, dep_iid)
        if st["ok"] and not st["done"]:
            blockers.append(f"{ref}#{dep_iid}")
        elif not st["ok"]:
            unknown.append(f"{ref}#{dep_iid}")
    if blockers:
        return f"⛔ 차단 ({', '.join(blockers)})"
    # 못 읽은 외부 선행을 '착수 가능' 으로 부르면 거짓 안전 신호가 된다
    return f"⚠️ 미확인 대기 ({', '.join(unknown)})" if unknown else "착수 가능"


def build_cross_section(issues, resolver, cycles):
    """타 프로젝트 연동 표 + 교착 진단 (Issue252)."""
    if resolver is None or not resolver.enabled:
        return ("<!-- ISSUE-MAP:CROSS:START -->\n"
                "<h2>타 프로젝트 연동</h2>\n<blockquote><p><code>--no-cross</code> 로 실행되어 "
                "타 프로젝트 선행을 조회하지 않았습니다.</p></blockquote>\n"
                "<!-- ISSUE-MAP:CROSS:END -->")

    rows, blocked, unknown = [], 0, 0
    for iss in issues.values():
        for ref, dep_iid in iss["ext"]:
            st = resolver.status(ref, dep_iid)
            if st["done"]:
                verdict, cls = "✅ 완료 — 착수 가능", ""
            elif st["ok"]:
                verdict, cls = "⛔ 대기 — 차단", ' class="blk"'
                blocked += 1
            else:
                verdict, cls = f"⚠️ 미확인 — {st['reason']}", ' class="unk"'
                unknown += 1
            rows.append(
                "  <tr{cls}><td>{me}</td><td>{tgt}</td><td>{path}</td>"
                "<td>{sec}</td><td>{v}</td></tr>".format(
                    cls=cls, me=iss["id"], tgt=html.escape(f"{ref}#{dep_iid}"),
                    path=html.escape(str(st["path"]) if st["path"] else "&mdash;"),
                    sec=html.escape(st["section"] or "&mdash;"),
                    v=html.escape(verdict)))
    table = "\n".join(rows) or "  <tr><td colspan='5'>타 프로젝트 선행 없음</td></tr>"

    if cycles:
        items = "\n".join(f"  <li><code>{html.escape(' → '.join(c))}</code></li>" for c in cycles)
        verdict_html = (
            f'<blockquote class="bad"><p><strong>🔴 교착 {len(cycles)}건 검출</strong> &mdash; '
            "아래 사슬은 서로의 완료를 기다리므로 <strong>어느 쪽도 스스로 풀리지 않습니다</strong>. "
            "한쪽 의존을 끊거나 이슈를 분할해 순환을 깨야 합니다.</p>\n"
            f"<ul>\n{items}\n</ul></blockquote>")
    elif unknown:
        verdict_html = (
            f'<blockquote><p><strong>🟡 교착 미검출 · 미확인 {unknown}건</strong> &mdash; '
            "순환 대기는 없습니다. 다만 위 ⚠️ 행은 대상 <code>Issue.md</code> 를 읽지 못해 "
            "<strong>차단 여부를 판정하지 못했습니다</strong>(교착 아님이 증명된 것은 아님). "
            "표기 오타 또는 미등록 prj 를 먼저 교정하십시오.</p></blockquote>")
    else:
        verdict_html = (
            f'<blockquote class="ok"><p><strong>🟢 교착 없음</strong> &mdash; '
            f"타 prj 선행 {len(rows)}건 전부 해석되었고 순환 대기가 없습니다. "
            f"대기 중 {blocked}건은 <strong>단순 대기</strong>이며, 선행이 완료되면 자동으로 풀립니다."
            "</p></blockquote>")

    return f"""<!-- ISSUE-MAP:CROSS:START -->
<h2>타 프로젝트 연동</h2>
<div class="wrap">
<table>
  <tr><th>이 prj 이슈</th><th>타 prj 선행</th><th>대상 경로</th><th>대상 섹션</th><th>판정</th></tr>
{table}
</table>
</div>
<p>다른 프로젝트의 <code>Issue.md</code> 를 직접 열어 상태를 확인한 결과입니다(경로 SSOT: <code>~/_git/___pm/projects/&#123;번호&#125;</code>). 관계도에서는 점선 테두리 노드로 그려집니다.</p>

<h3>교착(순환 대기) 진단</h3>
{verdict_html}
<!-- ISSUE-MAP:CROSS:END -->"""


def build_html(issues, svg_graph, svg_critical, preserved_notes, root: Path,
               hidden=frozenset(), isolated=frozenset(), has_graph=True,
               resolver=None, cycles=()):
    def graph_cell(iid):                                   # Issue247: 3값 표기
        if iid in hidden:
            return "정리 완료"
        if iid in isolated:
            return "미연결"
        return "표시"

    # Issue250: 표에는 '그래프 연동분 ∪ 미완료 전량'만 남긴다.
    # 그래프와 무관한 과거 완료 이슈를 매번 수백 행씩 다시 그릴 이유가 없다.
    # Issue259: 유령(보류·취소 선행)은 그래프에만 남기고 표·집계에서는 뺀다.
    active = {k: v for k, v in issues.items() if not v["ghost"]}
    in_graph = {k for k in issues if k not in hidden and k not in isolated}
    listed = [i for i in active.values()
              if not i["done"] or i["id"] in in_graph]
    dropped = len(active) - len(listed)

    def dep_cell(i):     # 로컬 + 타 prj 선행을 한 칸에 (Issue252)
        parts = list(i["depends"]) + [f"{r}#{d}" for r, d in i["ext"]]
        return html.escape(", ".join(parts)) if parts else "&mdash;"

    rows = "\n".join(
        "  <tr><td>{id}</td><td>{title}</td><td class='sec'>{sec}</td>"
        "<td>{dep}</td><td>{st}</td><td>{gr}</td></tr>".format(
            id=i["id"], title=html.escape(i["title"]),
            sec=SECTIONS[i["section"]][0],
            dep=dep_cell(i),
            st=html.escape(status_text(i, issues, resolver)),
            gr=graph_cell(i["id"]))
        for i in listed) or "  <tr><td colspan='6'>남은 이슈 없음</td></tr>"
    hidden_note = (
        f"<p>완료 {dropped}건은 그래프와 무관하여 생략했습니다"
        f"(잔여 작업과 그래프 연동분만 표시). 전량 표시는 <code>--all</code> 옵션.</p>"
        if dropped else "")

    trg = [i for i in listed if i["trigger"]]
    trg_rows = "\n".join(
        "  <tr><td>{src} &rarr; {dst}</td><td>{t}</td><td>{st}</td></tr>".format(
            src=dep_cell(i), dst=i["id"],
            t=html.escape(i["trigger"]),
            st=html.escape(status_text(i, issues, resolver)))
        for i in trg) or "  <tr><td colspan='3'>등록된 트리거 없음</td></tr>"

    total = len(active)
    done = sum(1 for i in active.values() if i["done"])
    notes = preserved_notes or (
        "<ul>\n  <li>메모 없음 &mdash; 이 구간은 수기 편집분이 보존됩니다."
        " 재생성해도 지워지지 않습니다.</li>\n</ul>")

    # ── 조건부 섹션 (Issue247) ───────────────────────────────────────────
    # edge 가 하나도 없으면 의존 관계도·임계 경로는 보여줄 것이 없으므로 통째 생략.
    graph_section = f"""<h2>전체 의존 관계</h2>
<!-- ISSUE-MAP:GRAPH:START -->
<figure>
{svg_graph}
<figcaption>노드 색은 <code>Issue.md</code> 섹션(완료 · 중요 · 일반 · 선택), 화살표 색은 선행 이슈 완료 여부로 결정됩니다. 그래프에는 <strong>서로 이어진 이슈만</strong> 그려집니다 &mdash; 자신도 후행도 모두 완료된 이슈, 그리고 <code>depends</code> 연결이 없는 이슈는 아래 표로 빠집니다. <strong>보류 · 취소 이슈는 맵에서 제외</strong>되며, 활성 이슈가 선행으로 걸고 있는 경우에만 회색 점선 노드로 남습니다.</figcaption>
</figure>
<!-- ISSUE-MAP:GRAPH:END -->

<h2>임계 경로</h2>
<!-- ISSUE-MAP:CRITICAL:START -->
<figure>
{svg_critical}
<figcaption>미완료 이슈 중 의존 사슬이 가장 긴 경로. 중간 하나가 막히면 뒤 전체가 정지합니다.</figcaption>
</figure>
<!-- ISSUE-MAP:CRITICAL:END -->
""" if has_graph else """<!-- ISSUE-MAP:GRAPH:START -->
<blockquote><p><code>depends</code> 로 이어진 이슈가 없어 의존 관계도·임계 경로를 생략했습니다. 아래 &ldquo;진행 전 이슈&rdquo; 목록이 남은 작업 전부입니다.</p></blockquote>
<!-- ISSUE-MAP:GRAPH:END -->
"""

    pending = [i for i in active.values()
               if not i["done"] and (i["id"] in isolated or not has_graph)]
    pending_rows = "\n".join(
        "  <tr><td>{id}</td><td>{title}</td><td class='sec'>{sec}</td><td>{st}</td></tr>".format(
            id=i["id"], title=html.escape(i["title"]),
            sec=SECTIONS[i["section"]][0],
            st=html.escape(status_text(i, issues, resolver)))
        for i in pending) or "  <tr><td colspan='4'>없음 &mdash; 미완료 이슈가 모두 의존 관계도 안에 있습니다</td></tr>"

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(root.name)} Issue Map</title>
<meta name="description" content="Issue.md 기반 이슈 의존 관계도 (issue-map 스킬 자동 생성)">
<meta name="generator" content="issue-map skill / build_issue_map.py">
<meta name="source" content="Issue.md">
<meta name="updated" content="{date.today().isoformat()}">
<style>
  :root {{ color-scheme: light dark; }}
  * {{ box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Apple SD Gothic Neo", "Segoe UI", sans-serif;
    max-width: 960px; margin: 0 auto; padding: 2rem 1.2rem 4rem; line-height: 1.7;
    background: #fff; color: #1a1a1a; }}
  header {{ position: sticky; top: 0; z-index: 100; display: flex; align-items: center;
    justify-content: space-between; gap: 1rem; flex-wrap: wrap;
    margin: -2rem calc(50% - 50vw) 1.5rem; padding: 0.9rem 1.4rem;
    background: hsl(238,45%,80%); color: #1a1a1a; }}
  header h1 {{ margin: 0; font-size: 1.15rem; flex: 1 1 auto; min-width: 0; text-align: center;
    padding: 0; background: none; border: none; }}
  header .header-actions {{ display: flex; align-items: center; gap: 0.5rem; flex: 0 0 auto; }}
  header .proj-badge, header .sess-link, header .hub-link, header button {{
    display: inline-flex; align-items: center; line-height: 1; color: #1a1a1a;
    text-decoration: none; cursor: pointer; white-space: nowrap; background: rgba(0,0,0,0.08);
    border: 1px solid rgba(0,0,0,0.15); padding: 0.2rem 0.6rem; border-radius: 6px; font-size: 0.85rem; }}
  header .copy-link, header .close-btn {{ justify-content: center; padding: 0.2rem 0.5rem; }}
  header .close-btn:hover {{ background: rgba(200,0,0,0.18); }}
  header .proj-badge:hover, header .sess-link:hover, header .hub-link:hover, header button:hover {{
    background: rgba(0,0,0,0.16); text-decoration: underline; }}
  .meta {{ font-size: 0.85rem; opacity: 0.7; margin-bottom: 1.6rem;
    padding: 0.45rem 0.95rem 0.6rem; background: rgba(127,127,127,0.07);
    border-left: 5px solid hsl(205,75%,42%); border-radius: 0 0 6px 6px; }}
  h2 {{ margin-top: 2.4rem; padding-bottom: 0.3rem; border-bottom: 2px solid rgba(127,127,127,0.35); font-size: 1.2rem; }}
  h3 {{ margin-top: 1.6rem; font-size: 1rem; }}
  table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; font-size: 0.9rem; }}
  th, td {{ border: 1px solid rgba(127,127,127,0.35); padding: 0.4rem 0.55rem; text-align: left; vertical-align: top; }}
  th {{ background: rgba(127,127,127,0.12); }}
  code {{ background: rgba(127,127,127,0.15); padding: 0.1rem 0.35rem; border-radius: 4px; font-size: 0.88em; }}
  .wrap {{ overflow-x: auto; }}
  figure {{ margin: 1.4rem 0; overflow-x: auto; }}
  figcaption {{ font-size: 0.85rem; opacity: 0.75; margin-top: 0.5rem; }}
  blockquote {{ margin: 1rem 0; padding: 0.6rem 1rem; border-left: 4px solid hsl(42,60%,55%);
    background: rgba(200,160,60,0.12); }}
  blockquote.ok {{ border-left-color: {EDGE_GO}; background: rgba(47,138,47,0.12); }}
  blockquote.bad {{ border-left-color: {EDGE_BLOCK}; background: rgba(192,57,43,0.13); }}
  tr.blk td {{ background: rgba(192,57,43,0.08); }}
  tr.unk td {{ background: rgba(127,127,127,0.10); }}
  ul {{ padding-left: 1.3rem; }}
  a {{ color: hsl(205,75%,42%); }}
  .edge-legend {{ display: flex; flex-wrap: wrap; gap: 0.4rem 1.4rem; font-size: 0.87rem; margin: 0.4rem 0 1.4rem; }}
  .edge-legend span::before {{ content: "\\2192  "; font-weight: 700; }}
  .eg-go::before {{ color: {EDGE_GO}; }}
  .eg-block::before {{ color: {EDGE_BLOCK}; }}
  .eg-ref::before {{ color: {EDGE_REF}; }}
  .sec {{ white-space: nowrap; font-weight: 600; }}
  footer {{ margin-top: 3rem; padding-top: 1rem; border-top: 1px solid rgba(127,127,127,0.3);
    font-size: 0.85rem; opacity: 0.75; }}
  @media (prefers-color-scheme: dark) {{
    body {{ background: #16181c; color: #e6e6e6; }}
    a {{ color: hsl(205,80%,68%); }}
    blockquote {{ background: rgba(200,160,60,0.14); }}
    .meta {{ background: rgba(255,255,255,0.04); border-left-color: hsl(205,80%,62%); }}
  }}
</style>
</head>
<body>

<header>
  <a class="hub-link" href="/hub" target="fpm-hub" title="통합 모니터링 Hub"><img src="/fpm-icon.png" alt="Hub" style="height:1.2em;vertical-align:-0.25em;"></a>
  <h1>{html.escape(root.name)} Issue Map</h1>
  <nav class="header-actions">
    <a class="proj-badge" href="#" title="클릭 → VSCode 로 {html.escape(root.name)} 열기"
       onclick="event.preventDefault();fetch('/open-project',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{cwd:'{html.escape(str(root))}'}})}}).then(function(r){{return r.json();}}).then(function(j){{if(j&&j.error)alert('VSCode 열기 실패: '+j.error);}}).catch(function(){{alert('hub 서버 미응답 — VSCode 열기 실패');}});">📁 {html.escape(root.name)}</a>
    <button type="button" class="close-btn" title="이 문서 탭 닫기" onclick="window.close()">✕</button>
  </nav>
</header>
<div class="meta">이슈 {total}건 · 완료 {done}건 · 기준 자료 <code>Issue.md</code> · 갱신 {date.today().isoformat()}</div>

<blockquote>
<p>이 문서는 <code>Issue.md</code> 를 파싱해 <strong>issue-map 스킬이 자동 생성</strong>합니다. 직접 편집한 내용은 다음 재생성 때 사라지므로, 수기 메모는 문서 하단 &ldquo;메모&rdquo; 구간에만 작성하십시오(그 구간은 보존됩니다).</p>
<p>다이어그램은 SVG 로 선렌더되어 파일 안에 들어 있으므로, 서버나 네트워크 없이 파일 하나로 열람됩니다.</p>
</blockquote>

<h3>화살표 — 착수 가능 여부</h3>
<div class="edge-legend">
  <span class="eg-go"><strong>녹색</strong>: 선행 이슈 완료 → 후행 <strong>착수 가능</strong></span>
  <span class="eg-block"><strong>빨강</strong>: 선행 미완료 → 후행 <strong>차단</strong></span>
  <span class="eg-ref"><strong>회색 점선</strong>: 타 프로젝트 선행을 <strong>확인하지 못함</strong> (차단 여부 미판정)</span>
</div>
<p style="font-size:0.87rem;opacity:0.8;margin-top:-0.8rem">점선 테두리 노드는 <strong>다른 프로젝트의 이슈</strong>입니다. 상태는 그 프로젝트 <code>Issue.md</code> 를 직접 읽어 판정합니다.</p>

{graph_section}
{build_cross_section(issues, resolver, cycles)}

<h2>진행 전 이슈</h2>
<!-- ISSUE-MAP:PENDING:START -->
<div class="wrap">
<table>
  <tr><th>번호</th><th>제목</th><th>섹션</th><th>상태</th></tr>
{pending_rows}
</table>
</div>
<p><code>depends</code> 연결이 없어 의존 관계도에 그리지 않은 미완료 이슈입니다. 선행이 있다면 <code>* depends:</code> 와 전이 조건 <code>* trigger:</code> 를 이슈에 적어 두면 위 관계도에 편입됩니다.</p>
<!-- ISSUE-MAP:PENDING:END -->

<h2>전이 트리거</h2>
<!-- ISSUE-MAP:TRIGGER:START -->
<div class="wrap">
<table>
  <tr><th>전이</th><th>트리거 조건</th><th>현재 상태</th></tr>
{trg_rows}
</table>
</div>
<!-- ISSUE-MAP:TRIGGER:END -->

<h2>이슈 목록</h2>
<!-- ISSUE-MAP:TABLE:START -->
<div class="wrap">
<table>
  <tr><th>번호</th><th>제목</th><th>섹션</th><th>depends</th><th>상태</th><th>그래프</th></tr>
{rows}
</table>
</div>
{hidden_note}
<!-- ISSUE-MAP:TABLE:END -->

<h2>메모 (수기 편집 구간 · 재생성 시 보존)</h2>
<!-- ISSUE-MAP:NOTES:START -->
{notes}
<!-- ISSUE-MAP:NOTES:END -->

<footer>
  <p>생성: <code>build_issue_map.py</code> (issue-map 스킬 — 글로벌 SCAR / fpm-core 번들) · 기준: <code>Issue.md</code></p>
</footer>

</body>
</html>
"""


def longest_chain(issues):
    """미완료 이슈 기준 최장 의존 사슬 → [id...]."""
    memo = {}

    def walk(iid):
        if iid in memo:
            return memo[iid]
        memo[iid] = [iid]  # 순환 방지용 선점
        best = []
        for other in issues.values():
            if iid in other["depends"] and not other["done"]:
                cand = walk(other["id"])
                if len(cand) > len(best):
                    best = cand
        memo[iid] = [iid] + best
        return memo[iid]

    # 유령(보류·취소 선행)은 사슬 머리로 세지 않는다 — 임계 경로가 왜곡된다 (Issue259)
    chains = [walk(i["id"]) for i in issues.values() if not i["done"] and not i["ghost"]]
    return max(chains, key=len) if chains else []


def build_critical_mmd(issues):
    chain = longest_chain(issues)
    if len(chain) < 2:
        return 'flowchart LR\n    A["임계 경로 없음 — 미완료 의존 사슬 부재"]\n'
    lines = ["flowchart LR"]
    for i, iid in enumerate(chain):
        lines.append(f'    {iid}["{iid}"]')
    for a, b in zip(chain, chain[1:]):
        lines.append(f"    {a} --> {b}")
    lines.append(f'    linkStyle {",".join(str(i) for i in range(len(chain) - 1))} '
                 f"stroke:{EDGE_BLOCK},stroke-width:2px")
    return "\n".join(lines) + "\n"


def extract_notes(path: Path):
    if not path.exists():
        return None
    m = re.search(r"<!-- ISSUE-MAP:NOTES:START -->\n?(.*?)\n?<!-- ISSUE-MAP:NOTES:END -->",
                  path.read_text(), re.S)
    return m.group(1).strip() if m else None


def demote_self_refs(issues, resolver):
    """자기 프로젝트를 가리키는 외부 표기는 로컬 의존으로 강등 (Issue252).

    prj3 `Issue.md` 안의 `~/.claude#Issue28` 처럼 자기 자신을 prj 표기로 쓴 사례가
    실재한다. 그대로 두면 같은 프로젝트가 '타 prj' 로 잡혀 가짜 외부 노드가 생긴다.
    """
    for iss in issues.values():
        keep = []
        for ref, iid in iss["ext"]:
            p = resolver.resolve(ref)
            if p is not None and p.resolve() == resolver.root and iid in issues:
                if iid not in iss["depends"]:
                    iss["depends"].append(iid)
            else:
                keep.append((ref, iid))
        iss["ext"] = keep


def print_deadlock_report(issues, resolver, cycles):
    """--deadlock: 교착 진단만 콘솔 출력 (파일 미생성)."""
    ext_rows = [(i["id"], ref, iid) for i in issues.values() for ref, iid in i["ext"]]
    print(f"타 prj 선행 {len(ext_rows)}건 / 열어 본 프로젝트 {len(resolver._issues)}개")
    blocked = unknown = 0
    for me, ref, iid in ext_rows:
        st = resolver.status(ref, iid)
        if st["done"]:
            mark = "✅ 완료 — 착수 가능"
        elif st["ok"]:
            mark, blocked = f"⛔ 대기 ({st['section']})", blocked + 1
        else:
            mark, unknown = f"⚠️ 미확인 — {st['reason']}", unknown + 1
        print(f"  {me:<12} → {ref}#{iid:<12} {mark}")
    print()
    if cycles:
        print(f"🔴 교착 {len(cycles)}건 — 서로 기다려 스스로 풀리지 않음:")
        for c in cycles:
            print("   " + " → ".join(c))
    elif unknown:
        print(f"🟡 순환 대기 없음 · 미확인 {unknown}건 — 차단 여부 미판정 "
              "(교착 아님이 증명된 것은 아님). 표기 오타·미등록 prj 교정 필요")
    else:
        print(f"🟢 교착 없음 — 순환 대기 0건. 대기 {blocked}건은 단순 대기이며 "
              "선행 완료 시 자동 해제")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="Issue_map.htm")
    ap.add_argument("--issue", default="Issue.md")
    ap.add_argument("--check", action="store_true", help="파싱 결과만 출력 (파일 미생성)")
    ap.add_argument("--all", action="store_true",
                    help="정리 완료 노드(완료 + 후행도 전부 완료)까지 그래프에 표시")
    ap.add_argument("--no-cross", action="store_true",
                    help="타 프로젝트 선행을 조회하지 않음 (오프라인·속도 우선)")
    ap.add_argument("--deadlock", action="store_true",
                    help="교착(순환 대기) 진단만 출력 (파일 미생성)")
    args = ap.parse_args()

    root = Path.cwd()
    issue_md = root / args.issue
    if not issue_md.exists():
        sys.exit(f"❌ {issue_md} 없음 — nPTiR 루트에서 실행할 것")

    issues = parse_issue_md(issue_md)
    if not issues:
        sys.exit("❌ 이슈 파싱 결과 0건 — Issue.md 형식 확인 필요")
    ghosts = split_excluded(issues)         # ⏸️ 보류 · 🚫 취소 제외 (Issue259)
    stage_map = load_stage_map(root)

    # 타 프로젝트 연동 (Issue252)
    resolver = CrossResolver(root, enabled=not args.no_cross)
    demote_self_refs(issues, resolver)
    cycles = resolver.deadlocks(issues)

    if args.deadlock:
        print_deadlock_report(issues, resolver, cycles)
        return

    hidden = frozenset() if args.all else settled(issues)
    # Issue247: 연결된 노드만 그래프. --all 은 진단용 탈출구라 고립 노드도 남긴다.
    linked = linked_ids(issues, hidden)
    isolated = (frozenset() if args.all
                else frozenset(k for k in issues if k not in hidden and k not in linked))
    graph_hidden = hidden | isolated
    has_graph = bool(linked)

    if args.check:
        for i in issues.values():
            if i["ghost"]:
                mark = " [표 제외: 보류·취소 — 활성 선행이라 유령 노드로 존치]"
            elif i["id"] in hidden:
                mark = " [그래프 제외: 정리 완료]"
            elif i["id"] in isolated:
                mark = " [그래프 제외: 미연결 → 진행 전 이슈]"
            else:
                mark = ""
            ext = [f"{r}#{d}" for r, d in i["ext"]]
            print(f"{i['id']:<10} {SECTIONS[i['section']][0]:<8} "
                  f"depends={i['depends'] or '-'} ext={ext or '-'} "
                  f"trigger={i['trigger'] or '-'}{mark}")
        print(f"\n총 {len(issues) - len(ghosts)}건 / 완료 {sum(1 for i in issues.values() if i['done'])}건"
              f" / 그래프 표시 {len(issues) - len(graph_hidden)}건"
              f" / 미연결 {len(isolated)}건"
              f" / 타 prj 선행 {sum(len(i['ext']) for i in issues.values())}건"
              + (f" / 보류·취소 유령 {len(ghosts)}건" if ghosts else ""))
        print("임계 경로:", " → ".join(longest_chain(issues)) or "없음")
        if not has_graph:
            print("⚠️ depends 연결 0건 — 의존 관계도·임계 경로 생략, 진행 전 이슈 목록만 렌더")
        print()
        print_deadlock_report(issues, resolver, cycles)
        return

    svg_graph = svg_crit = ""
    if has_graph:                      # edge 0 이면 mmdc 를 아예 타지 않는다
        with tempfile.TemporaryDirectory() as td:
            wd = Path(td)
            svg_graph = render_svg(
                build_graph_mmd(issues, stage_map, graph_hidden, resolver), wd, "graph")
            svg_crit = render_svg(build_critical_mmd(issues), wd, "critical")

    out = root / args.out
    html_text = build_html(issues, svg_graph, svg_crit, extract_notes(out), root,
                           hidden, isolated, has_graph, resolver, cycles)
    out.write_text(html_text)
    shown = len(issues) - len(graph_hidden)
    n_ext = sum(len(i["ext"]) for i in issues.values())
    print(f"✅ {out} 생성 ({out.stat().st_size / 1024:.1f} KB, 이슈 {len(issues) - len(ghosts)}건"
          + (f", 그래프 {shown}건 표시" if has_graph else ", 그래프 생략(depends 연결 0건)")
          + (f" / 미연결 {len(isolated)}건은 진행 전 이슈 목록" if isolated else "")
          + (f" / 정리 완료 {len(hidden)}건 숨김" if hidden else "")
          + (f" / 보류·취소 유령 {len(ghosts)}건" if ghosts else "")
          + (f" / 타 prj 선행 {n_ext}건" if n_ext else "") + ")")
    if cycles:
        print(f"🔴 교착 {len(cycles)}건 검출 — 상세는 `--deadlock`:")
        for c in cycles:
            print("   " + " → ".join(c))
    elif resolver.unresolved:
        print(f"⚠️ 타 prj 선행 {len(set(resolver.unresolved))}건 미확인 — 차단 여부 미판정 "
              "(`--deadlock` 로 상세 확인)")


if __name__ == "__main__":
    main()
