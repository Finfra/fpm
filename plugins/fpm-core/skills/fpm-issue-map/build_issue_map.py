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
        [--check] [--json] [--all] [--deadlock] [--no-cross] [--fbot] [--out Issue_map.htm]

    --fbot: 핀봇 배분 원장(registry.db, 읽기 전용)을 이슈 노드에 조인해 담당 봇 배지를 얹는다
            (옵트인 — Issue740). 산출물 앵커: 노드 id="issue-<N>" · 표 행 id="issue-<N>-row"
            · 딥링크 Issue_map.htm#issue=<N> 수신 시 선택·스크롤·강조
"""

import argparse
import base64
import copy
import functools
import html
import importlib.util
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
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
# «⏸️ 보류 포함» 토글 (Issue974) — 보류만 켜서 볼 수 있다. 취소는 토글 대상이 아니다
HELD_SECTION = "⏸️ 보류"
HELD_TOGGLE_EXCLUDED = EXCLUDED_SECTIONS - {HELD_SECTION}

CLASS_DEFS = """    classDef done fill:#d8ecd8,stroke:#5a9a5a,color:#1a1a1a
    classDef prog fill:#cfe6f5,stroke:#4a90c4,color:#1a1a1a
    classDef imp fill:#f6d5d5,stroke:#c06a6a,color:#1a1a1a
    classDef norm fill:#d9e8f5,stroke:#6f9dc4,color:#1a1a1a
    classDef opt fill:#e8e8e8,stroke:#9a9a9a,color:#1a1a1a
    classDef held fill:#ededed,stroke:#9a9a9a,color:#5a5a5a,stroke-dasharray:5 4
    classDef ext fill:#fdf0dc,stroke:#c08a3e,color:#1a1a1a,stroke-dasharray:5 4
    classDef extdone fill:#e4f0e0,stroke:#6f9a5a,color:#1a1a1a,stroke-dasharray:5 4
    classDef extunk fill:#eeeeee,stroke:#9a9a9a,color:#5a5a5a,stroke-dasharray:2 3
    classDef iso fill:#f5f5f7,stroke:#c8c8d0,color:#8c8c96"""

EDGE_GO = "#2f8a2f"     # 선행 완료 → 착수 가능
EDGE_BLOCK = "#c0392b"  # 선행 미완료 → 차단
EDGE_REF = "#9a9a9a"    # 참조 관계 · 미확인 (차단 판정 불가)
EDGE_HELD = "#8a7ab0"   # 선행이 보류·취소 → 차단이나 자동 해제 없음 (Issue259)

# ── 타 프로젝트 연동 (Issue252) ──────────────────────────────────────────
# prj 번호 → 경로 SSOT = projects 레지스트리 디렉토리. 파일 하나당 경로 1줄
# (ex: projects/1 = 대상 prj 루트 경로). 위치는 하드코딩하지 않는다 (Issue436_3):
# ~/.info/__pmBasePath.txt 의 1줄이 projects 디렉토리 절대경로 **그 자체**다.
# 추가 join 절대 금지(`/projects` 를 덧붙이면 projects/projects 파손 → cross-prj 전멸).
# fpm MCP server.py `_base_dir()` 와 동일 규약. 부재 시 개인 경로 폴백 금지.
PM_BASE_FILE = Path.home() / ".info" / "__pmBasePath.txt"
MAX_HOPS = 3        # 교착 탐색: prj 경계를 넘는 최대 홉 (opus-4-8 루프 상한 준수)
MAX_PROJECTS = 20   # 교착 탐색: 열어 볼 프로젝트 상한


def resolve_projects_dir():
    """projects 레지스트리 디렉토리 resolver — 파일 값을 그대로 쓴다 (Issue436_3).

    부재·빈 값·디렉토리 아님 → None. 호출측(CrossResolver)이 cross-prj 조회만
    스킵하고 로컬 단일 prj 렌더는 정상 진행한다.
    """
    if not PM_BASE_FILE.is_file():
        return None
    raw = PM_BASE_FILE.read_text().strip()
    if not raw:
        return None
    p = Path(os.path.expanduser(os.path.expandvars(raw)))
    return p if p.is_dir() else None


# ── 파싱 ────────────────────────────────────────────────────────────────
# `* depends:` 에서 파싱 불가여도 정상인 토큰 — 선행 없음을 밝히는 표기 (Issue343 P1)
DEP_NULL_TOKENS = {"없음", "-", "n/a", "none", "na"}
# 규약상 유효한 prj 참조 (rules/issue-g.md 규칙2) — 이름 표기는 위반 (Issue343 P2)
PRJ_REF_RE = re.compile(r"^prj[0-9]+[a-z]?$")


def split_deps(s: str):
    """`* depends:` 값을 **괄호 밖 쉼표**로만 자른다.

    ⚠️ 종전 `s.split(",")` 은 괄호 **안쪽** 쉼표까지 분리자로 봤다. 실측(2026-08-16):

        * depends: prj5#Issue66 (완료 — `bdc1fb7`, `0a232ff`)

    이 한 줄이 두 조각으로 갈려 뒤쪽 `` `0a232ff`) `` 가 파싱 실패로 경고에 올랐다.
    커밋 해시를 **둘 이상** 적은 완료 주석에서만 나타나므로 오래 안 보였다
    (해시 1개짜리는 멀쩡하다). 경고만 나고 앞 조각은 정상 파싱돼 **의존 자체는
    그려졌지만**, 매 실행 거짓 경고가 쌓이면 진짜 위반을 가린다(Issue343 취지).

    `parse_dep_token` 이 괄호를 지우긴 하나 그건 **자른 뒤**라 늦다 — 자르는 단계에서
    괄호 깊이를 봐야 한다.
    """
    out, buf, depth = [], [], 0
    for ch in s:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            out.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    out.append("".join(buf))
    return [x for x in out if x.strip()]


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


# Issue390 — `issue-g.md` 기본 섹션 중 **의도적으로 그래프 대상이 아닌** 것들.
#   여기에 이슈 헤더가 있어도 경고하지 않는다 — 빼는 것이 규약이지 사고가 아니다.
NON_GRAPH_SECTIONS = ("Issue Management", "🤔 결정사항", "🌱 이슈후보", "📜 참고")


def _norm_section(head: str) -> str:
    """섹션 헤더 비교 키 — **이모지·공백·기호를 걷어낸다** (Issue390).

    `🔥 진행 중` · `🚧 진행중` 이 둘 다 `진행중` 이 되어 같은 섹션으로 인식된다.
    로컬 오버라이드를 인정하되(그 프로젝트의 규약은 그 프로젝트가 정한다) 맵은 그리게 하려는 것이다.
    """
    return re.sub(r"[^\w가-힣]", "", head)


_SECTION_KEYS = None


def _match_section(head: str):
    """정규화 키로 맞춘다. 정확 일치 → 접두 일치 순. 못 맞추면 None.

    접두 일치를 남겨 두는 이유: `✅ 완료 (아카이브 — Issue1~250)` 처럼 부기가 붙는다.
    """
    global _SECTION_KEYS
    if _SECTION_KEYS is None:
        _SECTION_KEYS = [(_norm_section(k), k) for k in SECTIONS]
    nk = _norm_section(head)
    if not nk:
        return None
    for key, orig in _SECTION_KEYS:
        if nk == key:
            return orig
    for key, orig in _SECTION_KEYS:
        if nk.startswith(key):
            return orig
    return None


def parse_issue_md(path: Path, warn: list | None = None, lenient: bool = False,
                   quiet: bool = False, archive: bool = False):
    """Issue.md → {id: {...}} 순서 보존 dict.

    warn 을 주면 `* depends:` 규약 위반을 (kind, 이슈ID, 원문토큰) 으로 수집한다 (Issue343).
    타 프로젝트 조회(CrossResolver)는 warn 을 주지 않는다 — 남의 repo 위반을
    여기서 보고하면 소음이고, 그 repo 의 이슈맵이 자기 것을 보고해야 한다.
    """
    issues, section = {}, None
    current = None
    # Issue368: lenient 는 **타 prj 조회 전용** 관용 모드다. 남의 repo 포맷을 강제할 수 없고,
    #   실재하는 이슈를 "없음" 으로 판정하는 편이 규약 이탈을 눈감는 것보다 나쁘다.
    #   자기 Issue.md 파싱(lenient=False)은 종전 그대로 엄격 — 회귀 없음.
    #   ① 섹션 접두 일치: 아카이브는 `# ✅ 완료 (아카이브 — Issue1~250)` 처럼 괄호 부기가 붙는다
    #   ② 구분자 관용: prj42 는 `## Issue308. 제목` 처럼 콜론 대신 마침표를 쓴다
    iss_re = (r"^(#{2,3})\s+(Issue[\w_]+)\s*[:.]\s*(.+?)\s*$" if lenient
              else r"^(#{2,3})\s+(Issue[\w_]+)\s*:\s*(.+?)\s*$")
    # Issue390 — 미지 섹션에서 **조용히 사라지던** 이슈를 센다. 아래 경고의 근거다.
    unknown_head, unknown_hits = None, {}
    for line in path.read_text().splitlines():
        m_sec = re.match(r"^#\s+(.+?)\s*$", line)
        if m_sec:
            head = m_sec.group(1)
            if head in SECTIONS:
                section, current, unknown_head = head, None, None
                continue
            # Issue390 — **이모지·공백을 무시하고** 맞춰 본다. 로컬 오버라이드 프로젝트가
            #   `# 🔥 진행 중` 처럼 쓰면 접두 일치로는 안 잡힌다(`🚧 진행중` 의 접두가 아니다).
            #   실측(m2slide, 2026-08-11): 그 섹션의 이슈가 **총계에서 통째로 빠지고 경고도 없었다**.
            hit = _match_section(head)
            if hit:
                section, current, unknown_head = hit, None, None
                continue
            # Issue672 — **아카이브 파일에서는 미지 섹션을 완료로 받는다.** 아카이브는
            #   정의상 완료분이고, 실제 운용 헤더는 `# 📦 2026-09-11 아카이브 — 완료 131건`
            #   처럼 SECTIONS 와 접두조차 안 맞게 갈렸다(실측: 684건 중 443건이 조용히 샜다).
            #   SECTIONS 에 `📦` 를 박지 않는 이유 — 그러면 **활성 Issue.md 에서도** 유효
            #   섹션이 되고, 다음에 아카이브 헤더 문구가 또 바뀌면 같은 결함이 재발한다.
            #   «파일이 아카이브인가» 로 가르는 편이 관례 드리프트에 강하다.
            if archive and head not in NON_GRAPH_SECTIONS:
                section, current, unknown_head = "✅ 완료", None, None
                continue
            # 여기까지 왔으면 우리가 모르는 섹션이다. `section=None` 이라 이 구간의 이슈는
            # 버려진다 — 버리는 것 자체는 맞지만 **말은 해야 한다**(아래 경고).
            section, current, unknown_head = None, None, head
            continue
        if (unknown_head and unknown_head not in NON_GRAPH_SECTIONS
                and re.match(r"^#{2,3}\s+Issue[\w_]+\s*[:.]", line)):
            unknown_hits[unknown_head] = unknown_hits.get(unknown_head, 0) + 1
            continue
        m_iss = re.match(iss_re, line)
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
            for d in split_deps(m_dep.group(1)):
                parsed = parse_dep_token(d)
                if not parsed:
                    # Issue343 P1: 조용히 버리면 그 의존이 지도에서 통째로 사라진다.
                    # 없는 화살표는 눈에 띄지 않으므로 파싱 실패를 반드시 드러낸다.
                    raw = d.strip()
                    # 판정은 **정규화 후**에 한다 — `(없음)` 은 규약이 허용하는 표기인데
                    # 괄호가 먼저 제거돼 빈 토큰이 되므로, 원문으로 대조하면 오탐이다.
                    norm = re.sub(r"\([^)]*\)", " ", raw.replace("`", "")).strip()
                    # norm 이 비면 토큰 전체가 괄호 부기였다는 뜻 — `(없음)` 이 그 형태다
                    if warn is not None and raw and norm and norm.lower() not in DEP_NULL_TOKENS:
                        warn.append(("unparsed", current["id"], raw))
                    continue
                kind, ref, iid = parsed
                if kind == "local":
                    current["depends"].append(iid)
                else:                       # 타 prj 는 버리지 않고 보존 (Issue252)
                    # Issue343 P2: 이름 표기(`fSnippet#`)는 파싱은 되나 레지스트리에
                    # 없어 cross-prj 조회가 실패한다 → 링크가 조용히 끊긴다.
                    # 자동 해석은 하지 않는다 — 이름은 바뀌고 중복되므로 추측이 더 위험하다.
                    if warn is not None and not PRJ_REF_RE.match(ref):
                        warn.append(("named_ref", current["id"], d.strip()))
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
    # Issue390 — **조용히 버리지 않는다.** 정규화로도 못 맞춘 섹션에 이슈 헤더가 있었으면
    #   그 개수를 알린다. 종전에는 총계에서 빠진 채 맵이 정상처럼 그려졌다(m2slide 실측).
    #   quiet 는 아카이브 보충(Issue606) 전용 — 아카이브의 섹션 관례는 활성 Issue.md 와
    #   다르고 사용자가 고칠 대상도 아니라서, 그 경로에서만 침묵한다.
    if unknown_hits and not quiet:
        for head, n in unknown_hits.items():
            sys.stderr.write(
                "⚠️ 모르는 섹션 '# %s' 안의 이슈 %d건을 건너뛴다 — 맵에 안 나온다\n"
                "   아는 섹션: %s\n"
                "   이모지·공백은 무시하고 맞춘다. 그래도 안 맞으면 섹션명을 바꾸거나\n"
                "   build_issue_map.py 의 SECTIONS 에 추가한다\n"
                % (head, n, " · ".join(SECTIONS)))

    return issues


def parked(iss):
    """보류·취소로 멈춘 노드인가 — 유령(Issue259) 또는 «보류 포함» 변형의 보류 이슈(Issue974).

    둘 다 «기다려도 자동으로 안 풀리는» 선행이라 표시(⏸️·회색 점선·보류 색 화살표)가 같다.
    표·집계 제외는 유령만이다 — 그건 `ghost` 를 직접 본다.
    """
    return iss["ghost"] or iss.get("held", False)


def split_excluded(issues, excluded_sections=EXCLUDED_SECTIONS):
    """⏸️ 보류 · 🚫 취소 이슈를 맵에서 제거 (Issue259). → 유령으로 남긴 id 집합.

    Issue974: «보류 포함» 변형은 `excluded_sections=HELD_TOGGLE_EXCLUDED` 로 부른다 —
    보류 이슈는 정식 노드(`held=True`)로 남고 선행(로컬·타 prj)도 그대로 그린다.

    통째로 지우면 활성 이슈가 그 이슈에 `* depends:` 를 걸고 있을 때
    화살표가 소리 없이 사라져 '차단 중' 이라는 사실이 맵에서 실종된다.
    그래서 **활성 이슈의 선행으로 참조된 것만** 유령 노드(회색 점선)로 남기고,
    나머지는 노드·표 양쪽에서 제거한다. 유령은 그래프에만 있고 표에는 안 나온다.
    """
    for v in issues.values():
        if v["section"] == HELD_SECTION and HELD_SECTION not in excluded_sections:
            v["held"] = True
    excluded = {k for k, v in issues.items() if v["section"] in excluded_sections}
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
        self.projects_dir = resolve_projects_dir() if enabled else None
        if enabled and self.projects_dir is None:
            print(f"⚠️ projects 레지스트리 없음({PM_BASE_FILE} 부재·무효) — "
                  "cross-prj 조회 스킵, 로컬 이슈만 렌더", file=sys.stderr)
        self.projects = self._load_projects(self.projects_dir)
        self._issues = {}                       # {경로str: {id: issue}} 파싱 캐시
        self.unresolved = []                    # [(ref, iid, 사유)]

    @staticmethod
    def _load_projects(projects_dir):
        """{'prj1': Path, '___pm': Path, '.claude': Path, '~/.claude': Path, …}"""
        out = {}
        if projects_dir is None:
            return out
        for f in sorted(projects_dir.iterdir()):
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

    # Issue368: 완료분을 옮겨 두는 아카이브 파일명 (대소문자 관례가 repo 마다 갈린다).
    #   활성 Issue.md 에서 못 찾았다고 "이슈 없음" 으로 단정하면, 아카이브를 운영하는
    #   프로젝트(prj1·prj3 등)의 선행이 전부 미확인으로 떨어진다 — 실측 2건이 그 사례.
    ARCHIVES = ("_doc_work/issue_OLD.md", "_doc_work/Issue_OLD.md")

    def issues_of(self, path: Path):
        """대상 프로젝트 Issue.md + 아카이브 파싱 (프로젝트당 1회).

        활성이 우선이고 아카이브는 **없는 키만** 채운다 — 같은 번호가 양쪽에 있으면
        활성이 현재 상태다.
        """
        key = str(path.resolve())
        if key not in self._issues:
            f = path / "Issue.md"
            merged = parse_issue_md(f, lenient=True) if f.exists() else {}
            for rel in self.ARCHIVES:
                a = path / rel
                if not a.exists():
                    continue
                # Issue672: archive=True 로 `📦` 계열 섹션까지 받고, quiet 로 «고칠 수 없는»
                #   경고를 남의 repo 빌드에서 띄우지 않는다 — 판정과 침묵은 별개 축이라 둘 다 건다
                for iid, iss in parse_issue_md(a, lenient=True, quiet=True,
                                               archive=True).items():
                    merged.setdefault(iid, iss)
            self._issues[key] = merged
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


# ── fbot 오버레이 (Issue740 — Issue725 M2) ──────────────────────────────
# 담당의 SSOT 는 배분 원장이다(fbot-org.md §이슈 축 연동 결정 1). Issue.md 에 담당을 쓰지 않고,
# 여기서 `job.kind='fbot_dispatch'` 를 **읽기 전용**으로 조인해 노드에 배지를 얹는다.
# 옵트인인 이유(결정 3): Issue_map.htm 은 커밋·공유 산출물이라 봇 명부가 새면 안 된다.
FBOT_DISPATCH_KIND = "fbot_dispatch"
# 시간 창 — hub server.py `FBOT_RECENT_SECS`(prj3#Issue556)·fbot-org `IDLE_DAYS` 와 같은 3일.
#   세 뷰가 한 데이터를 보므로(결정 3) 창도 같아야 한 화면에서 보인 배분이 다른 화면에서 안 사라진다
FBOT_RECENT_SECS = 3 * 86400
# 「아직 안 끝난」 배분 — hub `_FBOT_LIVE_STATUS` 와 동일. 기간과 무관하게 싣는다
FBOT_LIVE_STATUS = ("open", "blocked", "logged", "deferred")
# 배분 사인 — hub `_FBOT_FLOW_SIGN`(prj3#Issue538 s4) 사본. 완료와 취소·회수는 다른 기호다
FBOT_SIGN = {"done": "✓", "open": "⏳", "blocked": "⛔", "reaped": "⌇",
             "cancelled": "✕", "logged": "▪", "deferred": "⏸"}
FBOT_BADGE_MAX = 2          # 노드 하나에 그리는 배지 상한. 넘으면 `+k`
FBOT_ICON_MAX = 16 * 1024   # 아이콘 data URI 인라인 상한 — 초과·부재는 색 점으로 폴백(hub 와 동일)


def _fbot_state_mod():
    """`hooks/fbot-state.py` 로드 — 원장 경로 해석(`aoa_dir()`)을 **복제하지 않는다**.

    정본(`~/.claude/skills/issue-map/`)·prj1 번들(`plugins/fpm-core/skills/fpm-issue-map/`) 모두
    두 단계 위에 `hooks/fbot-state.py` 가 있다. 부재·로드 실패는 None — 오버레이만 빠진다.
    """
    path = Path(__file__).resolve().parents[2] / "hooks" / "fbot-state.py"
    if not path.is_file():
        return None
    try:
        spec = importlib.util.spec_from_file_location("fbot_state_for_issue_map", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


def project_number(root: Path):
    """root → prj 번호(int). projects 레지스트리에 없으면 None — 호출측은 cwd 대조로 폴백한다."""
    try:
        rr = root.resolve()
        for k, p in CrossResolver._load_projects(resolve_projects_dir()).items():
            if k.startswith("prj") and k[3:].isdigit() and p.resolve() == rr:
                return int(k[3:])
    except OSError:
        pass
    return None


def _prj_int(v):
    """`payload.prj` 값(10 · "10" · "prj10") → int. 해석 불가면 None."""
    if isinstance(v, bool) or v in (None, ""):
        return None
    if isinstance(v, int):
        return v
    m = re.fullmatch(r"\s*(?:prj)?(\d+)\s*", str(v), re.I)
    return int(m.group(1)) if m else None


def _dispatch_ref(text, prj_field):
    """배분 식별자 → (prj|None, 'IssueN', 접두 명시 여부) | None.

    * **선두 식별자만** 본다 — topic 배분은 `Issue21 … → Issue22 …` 처럼 뒤에 다른 이슈를 언급한다.
      주제는 선두다. (fbot-state `norm_issue` 는 **마지막** 토큰을 쓰는데, 그건 중복 기록 판정용이다)
    * 숫자만 적힌 배분(`718`)도 이슈다. 단 `4:3 전환` 같은 문장 선두 숫자는 아니다 — 전체가 숫자일 때만
    * `prj<N>#` 접두가 `payload.prj` 보다 **우선**한다. `payload.prj` 는 fbot-lead 가 cwd 로 해소한
      **작업 위치**라서(`resolve_prj(cwd)`), prj5 의 이슈를 prj15 에서 수행한 배분은 prj=15 로 적힌다
      (실측 2026-09-28 — `prj5#Issue99 TDD 라운드…` 가 prj 15·16·25·26 으로 4건). 이슈의 주인은 접두다
    """
    t = str(text or "").replace("`", "").strip()
    if not t:
        return None
    prefix = None
    m = re.match(r"prj(\d+)\s*#\s*", t, re.I)
    if m:
        prefix, t = int(m.group(1)), t[m.end():]
    m = re.match(r"issue[_-]?(\d+(?:_\d+)*)(?![0-9A-Za-z_])", t, re.I)
    if m:
        num = m.group(1)
    elif re.fullmatch(r"\d+(?:_\d+)*", t):
        num = t
    else:
        return None
    prj = prefix if prefix is not None else _prj_int(prj_field)
    return prj, f"Issue{num}", prefix is not None


def dispatch_issue_ref(text, prj_field=None):
    """배분 `payload.issue`(+`payload.prj`) → (prj|None, 'IssueN') | None. 규칙은 `_dispatch_ref`."""
    r = _dispatch_ref(text, prj_field)
    return (r[0], r[1]) if r else None


def match_dispatches(rows, issue_ids, root: Path, my_prj):
    """배분 행 × 이 맵의 이슈 → {IssueN: [row…]} (입력 순서 보존).

    같은 번호는 prj 마다 있다(Issue47 이 여러 prj 에 있다) — **prj 가 맞아야** 붙인다.
      ① 배분의 prj(접두 > 필드)와 이 맵의 prj 를 둘 다 알면 → 같을 때만
      ② 접두를 명시했는데 이 맵의 prj 를 모르면 → 붙이지 않는다(다른 prj 이슈일 수 있다)
      ③ 그 밖(배분 prj 미상 · 맵 prj 미상) → `payload.cwd` 가 이 맵 root 와 같을 때만
    """
    root_r = os.path.realpath(str(root))
    out = {}
    for r in rows:
        pl = r.get("payload") or {}
        ref = _dispatch_ref(pl.get("issue"), pl.get("prj"))
        if not ref:
            continue
        prj, iid, explicit = ref
        if iid not in issue_ids:
            continue
        if prj is not None and my_prj is not None:
            if prj != my_prj:
                continue
        elif explicit:
            continue
        else:
            cwd = pl.get("cwd")
            if not cwd or os.path.realpath(os.path.expanduser(str(cwd))) != root_r:
                continue
        out.setdefault(iid, []).append(r)
    return out


def _fbot_icon_uri(fbot_root: Path, icon_rel: str) -> str:
    """봇 아이콘 SVG → data URI (hub `_fbot_icon_data_uri` 와 같은 규약). 실패는 전부 ""."""
    if not icon_rel or not isinstance(icon_rel, str):
        return ""
    base = os.path.realpath(fbot_root / "data" / "fbot" / "icons")
    path = os.path.realpath(fbot_root / icon_rel)
    if not (path == base or path.startswith(base + os.sep)):     # 경로 탈출 차단
        return ""
    try:
        if os.path.getsize(path) > FBOT_ICON_MAX:
            return ""
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError:
        return ""
    return "data:image/svg+xml;base64," + base64.b64encode(raw).decode("ascii")


def _css_rgb(color: str) -> str:
    """`#RRGGBB` → `rgb(r,g,b)`. mermaid 라벨은 `#\\w+;` 를 엔티티로 해석해 `#AE615C;` 가 깨진다."""
    m = re.fullmatch(r"\s*#?([0-9A-Fa-f]{6})\s*", color or "")
    if not m:
        return "rgb(111,111,120)"
    h = m.group(1)
    return "rgb(%d,%d,%d)" % (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def load_fbot_overlay(root: Path, issue_ids, now=None) -> dict:
    """원장 읽기 전용 조인 → {ok, reason, db, window_secs, issues: {IssueN: [badge…]}}.

    실패(모듈·DB 부재·읽기 오류)는 **예외가 아니라 ok=False** 다 — 오버레이만 빠지고 맵은 선다.
    badge = {worker, owner, status, sign, created_at, dispatch_id, role, color, icon_uri}.
    """
    fail = lambda why: {"ok": False, "reason": why, "db": None,           # noqa: E731
                        "window_secs": FBOT_RECENT_SECS, "issues": {}}
    mod = _fbot_state_mod()
    if mod is None or not hasattr(mod, "aoa_dir"):
        return fail("hooks/fbot-state.py 없음·로드 실패 — 원장 경로 해석 불가")
    db = Path(mod.aoa_dir()) / "registry.db"
    if not db.is_file():
        return fail(f"원장 없음 ({db})")
    now = int(now if now is not None else time.time())
    try:
        con = sqlite3.connect("file:" + urllib.parse.quote(str(db)) + "?mode=ro",
                              uri=True, timeout=3)
        con.row_factory = sqlite3.Row
        try:
            marks = ",".join("?" * len(FBOT_LIVE_STATUS))
            cur = con.execute(
                f"SELECT * FROM job WHERE kind=? AND (status IN ({marks}) OR created_at >= ?)"
                " ORDER BY created_at DESC",
                (FBOT_DISPATCH_KIND, *FBOT_LIVE_STATUS, now - FBOT_RECENT_SECS))
            rows = []
            for r in cur.fetchall():
                keys = r.keys()
                # 계약을 어긴 행 1건(payload 비JSON·created_at 비정수)은 **그 행만** 건너뛴다 —
                #   한 줄 때문에 오버레이 전체나 맵 생성이 죽으면 안 된다
                try:
                    pl = json.loads(r["payload"] or "{}")
                    created = int(r["created_at"] or 0)
                except (TypeError, ValueError):
                    continue
                if not isinstance(pl, dict):
                    continue
                owner = (r["owner_id"] if "owner_id" in keys else None) or r["owner"] or ""
                rows.append({"id": r["id"], "status": r["status"] or "", "owner": owner,
                             "created_at": created, "payload": pl})
            matched = match_dispatches(rows, set(issue_ids), root, project_number(root))
            workers = {r["payload"].get("worker_bot_id") for rs in matched.values() for r in rs}
            workers.discard(None)
            bots = {}
            if workers:
                try:
                    q = ",".join("?" * len(workers))
                    for b in con.execute(f"SELECT bot_id, role, icon, color FROM bot"
                                         f" WHERE bot_id IN ({q})", tuple(workers)):
                        bots[b["bot_id"]] = dict(b)
                except sqlite3.Error:
                    pass                            # bot 표 부재 — 아이콘·색 없이 배지만
        finally:
            con.close()
    except (sqlite3.Error, IndexError) as e:     # IndexError — 구 스키마에 owner 등 열 부재
        return fail(f"원장 읽기 실패 ({db}: {e})")

    fbot_root = Path(os.environ.get("FBOT_ROOT") or Path(__file__).resolve().parents[2])
    issues = {}
    for iid, rs in matched.items():
        # 워커당 1개 — 열린 배분 우선, 그다음 최신. 같은 워커를 두 번 그리면 배분 2회로 읽힌다
        best = {}
        for r in rs:
            w = r["payload"].get("worker_bot_id") or ""
            cur = best.get(w)
            key = (r["status"] in FBOT_LIVE_STATUS, r["created_at"])
            if cur is None or key > (cur["status"] in FBOT_LIVE_STATUS, cur["created_at"]):
                best[w] = r
        badges = []
        for w, r in best.items():
            b = bots.get(w) or {}
            role = b.get("role") or r["payload"].get("role") or ""
            icon = (_fbot_icon_uri(fbot_root, b.get("icon") or "")
                    or (_fbot_icon_uri(fbot_root, f"data/fbot/icons/{role}.svg") if role else ""))
            badges.append({"worker": w, "owner": r["owner"], "status": r["status"],
                           "sign": FBOT_SIGN.get(r["status"], "?"),
                           "created_at": r["created_at"], "dispatch_id": r["id"],
                           "role": role, "color": b.get("color") or "", "icon_uri": icon})
        badges.sort(key=lambda x: (x["status"] in FBOT_LIVE_STATUS, x["created_at"]),
                    reverse=True)
        issues[iid] = badges
    return {"ok": True, "reason": "", "db": str(db), "window_secs": FBOT_RECENT_SECS,
            "issues": issues}


def _bot_short(bot_id: str) -> str:
    return re.sub(r"^fbot-", "", bot_id or "") or "(미상)"


def fbot_badge_label(badges) -> str:
    """mermaid 노드 라벨용 배지 HTML — 속성은 홑따옴표(라벨 자체가 겹따옴표로 싸인다)."""
    parts = []
    for b in badges[:FBOT_BADGE_MAX]:
        # quote=False — `&#x27;` 의 `#x27;` 도 mermaid 가 엔티티로 오해한다
        name = esc(html.escape(_bot_short(b["worker"]), quote=False))
        if b["icon_uri"]:
            # <img> 를 쓰지 않는다 — mermaid 는 라벨 속 img 에 width:100%·display:flex 를 강제해
            #   아이콘이 라벨 폭만큼 커지고 노드 크기도 그 기준으로 잡힌다(2026-09-28 mmdc 11.6 실측)
            mark = (f"<span style='display:inline-block;width:14px;height:14px;"
                    f"vertical-align:-2px;margin-right:2px;"
                    f"background:url({b['icon_uri']}) center/contain no-repeat'></span>")
        else:
            mark = f"<span style='color:{_css_rgb(b['color'])}'>●</span>"
        parts.append(f"<span class='fbot-badge' style='display:inline-block;font-size:0.82em;"
                     f"padding:0 4px;border-radius:4px;background:rgba(127,127,127,0.16)'>"
                     f"{mark}{name} {b['sign']}</span>")
    more = len(badges) - FBOT_BADGE_MAX
    return " ".join(parts) + (f" +{more}" if more > 0 else "")


def fbot_cell(badges) -> str:
    """표 셀용 — 담당 봇 · 사인 · 배분자(누가 시켰나) · 상대시각.

    표는 **전체 bot_id** 를 쓴다(노드 라벨만 폭 때문에 `fbot-` 를 뗀다) — 봇 카드·원장 조회의 키다.
    """
    if not badges:
        return "&mdash;"
    now = time.time()

    def rel(ts):
        d = int(now - ts) if ts else -1
        if d < 0:
            return ""
        if d < 3600:
            return f"{max(d // 60, 0)}분 전"
        if d < 86400:
            return f"{d // 3600}시간 전"
        return f"{d // 86400}일 전"

    return "<br>".join(
        "{sign} {w} <small>&larr; {o}{t}</small>".format(
            sign=html.escape(b["sign"]), w=html.escape(b["worker"] or "(미상)"),
            o=html.escape(b["owner"] or "(미상)"),
            t=(" · " + rel(b["created_at"])) if rel(b["created_at"]) else "")
        for b in badges)


def anchor_svg_nodes(svg: str, with_id: bool = True, id_prefix: str = "") -> str:
    """mermaid 노드 `<g id="flowchart-IssueN-k">` 에 앵커를 단다 (Issue740 딥링크 수신 계약).

    with_id=True(전체 관계도): id 를 안정 id `issue-<N>` 로 바꾸고 `data-issue` 부착.
    with_id=False(임계 경로): `data-issue` 만 — 같은 이슈가 두 그림에 있어 id 가 겹치면 안 된다.
    mermaid 산출 id 의 순번(k)은 그래프가 바뀌면 흔들린다 — 그래서 외부 링크 키로 못 쓴다.
    id_prefix: «보류 포함» 변형은 `held-` — 두 변형이 한 문서에 있어 id 가 겹치면 안 된다(Issue974).
    """
    def rep(m):
        n = m.group(1)[len("Issue"):]
        return (f'id="{id_prefix}issue-{n}"' if with_id else m.group(0)) + f' data-issue="{n}"'
    return re.sub(r'id="flowchart-(Issue[0-9A-Za-z_]+?)-\d+"', rep, svg)


# 딥링크 착지 강조 (Issue740). mermaid 노드 도형은 인라인 `!important` 로 칠해져 stroke 를
#   덮어쓸 수 없다 — 그래서 도형이 아니라 <g> 에 filter(발광)를 건다.
ANCHOR_CSS = """  @keyframes issue-pulse { 0%, 100% { filter: drop-shadow(0 0 3px #e67e22); }
    50% { filter: drop-shadow(0 0 12px #e67e22); } }
  g.issue-sel { filter: drop-shadow(0 0 5px #e67e22); animation: issue-pulse 1.1s ease-in-out 3; }
  tr.issue-sel td { background: rgba(230,126,34,0.20) !important; }
  tr[data-issue] td:first-child a { color: inherit; text-decoration: none; }
  tr[data-issue] td:first-child a:hover { text-decoration: underline; }
  .fbot-note { font-size: 0.87rem; opacity: 0.85; margin-top: -0.6rem; }"""

# 확대 상자 (Issue828). 배율 1 = SVG 자연 폭(`data-natural-w`). «맞춤» 은 fit_svg 가 준 원래 style 로
#   되돌린다 — inline style 을 지우면 Issue251 캡까지 사라져 작은 그래프가 과확대된다.
ZOOM_CSS = """  .zoom-box { border: 1px solid rgba(127,127,127,0.28); border-radius: 6px; }
  .zoom-bar { display: flex; flex-wrap: wrap; align-items: center; gap: 0.35rem; padding: 0.3rem 0.5rem;
    border-bottom: 1px solid rgba(127,127,127,0.2); font-size: 0.85rem; }
  .zoom-bar button { cursor: pointer; min-width: 2rem; padding: 0.1rem 0.5rem; font: inherit; color: inherit;
    border: 1px solid rgba(127,127,127,0.4); border-radius: 5px; background: rgba(127,127,127,0.08); }
  .zoom-bar button:hover { background: rgba(127,127,127,0.2); }
  .zoom-pct { min-width: 3.2rem; text-align: center; opacity: 0.8; font-variant-numeric: tabular-nums; }
  .zoom-hint { margin-left: auto; opacity: 0.6; font-size: 0.78rem; }
  .zoom-vp { overflow: auto; max-height: 75vh; cursor: grab; }
  .zoom-vp.dragging { cursor: grabbing; user-select: none; }
  .zoom-box:fullscreen { background: #fff; display: flex; flex-direction: column; }
  .zoom-box:fullscreen .zoom-vp { max-height: none; flex: 1 1 auto; }"""

ZOOM_JS = """<script>
(function () {
  var STEP = 1.25, MIN = 0.05, MAX = 4;
  function svgOf(box) { return box.querySelector('.zoom-vp svg'); }
  function nat(svg) {
    var w = parseFloat(svg.getAttribute('data-natural-w'));
    if (!w && svg.viewBox && svg.viewBox.baseVal) w = svg.viewBox.baseVal.width;
    return w || svg.getBoundingClientRect().width || 1;
  }
  function cur(box) { var svg = svgOf(box); return svg.getBoundingClientRect().width / nat(svg); }
  function label(box) {
    var p = box.querySelector('.zoom-pct');
    if (p) p.textContent = Math.round(cur(box) * 100) + '%';
  }
  function setScale(box, s, cx, cy) {
    var vp = box.querySelector('.zoom-vp'), svg = svgOf(box);
    s = Math.max(MIN, Math.min(MAX, s));
    var r = vp.getBoundingClientRect();
    if (cx == null) { cx = r.left + vp.clientWidth / 2; cy = r.top + vp.clientHeight / 2; }
    var ox = cx - r.left, oy = cy - r.top;
    var px = vp.scrollLeft + ox, py = vp.scrollTop + oy;
    var oldW = svg.getBoundingClientRect().width || 1;
    svg.style.maxWidth = 'none';
    svg.style.width = (nat(svg) * s) + 'px';
    var k = svg.getBoundingClientRect().width / oldW;
    vp.scrollLeft = px * k - ox;
    vp.scrollTop = py * k - oy;
    label(box);
  }
  function fit(box) { svgOf(box).setAttribute('style', box.__orig || ''); label(box); }
  function init(box) {
    var vp = box.querySelector('.zoom-vp'), svg = svgOf(box);
    if (!vp || !svg) return;
    box.__orig = svg.getAttribute('style') || '';
    var full = box.querySelector('[data-zoom="full"]');
    if (full && !(document.fullscreenEnabled && box.requestFullscreen)) full.style.display = 'none';
    box.querySelector('.zoom-bar').addEventListener('click', function (e) {
      var b = e.target.closest ? e.target.closest('[data-zoom]') : null;
      if (!b) return;
      var a = b.getAttribute('data-zoom');
      if (a === 'in') setScale(box, cur(box) * STEP);
      else if (a === 'out') setScale(box, cur(box) / STEP);
      else if (a === '1') setScale(box, 1);
      else if (a === 'fit') fit(box);
      else if (a === 'full') {
        if (document.fullscreenElement) document.exitFullscreen();
        else { var p = box.requestFullscreen(); if (p && p.catch) p.catch(function () {}); }
      }
    });
    // Ctrl/⌘+휠 = 커서 기준 확대(트랙패드 핀치도 ctrlKey 휠로 온다). 휠 단독은 페이지 스크롤 그대로
    vp.addEventListener('wheel', function (e) {
      if (!(e.ctrlKey || e.metaKey)) return;
      e.preventDefault();
      // 마우스 휠 한 칸(deltaY≈100)이 한 번에 1/e 로 튀지 않게 한 이벤트의 폭을 ±40 으로 자른다(×0.67~×1.49)
      var dy = Math.max(-40, Math.min(40, e.deltaY));
      setScale(box, cur(box) * Math.exp(-dy * 0.01), e.clientX, e.clientY);
    }, {passive: false});
    // 드래그 이동 — 3px 넘게 움직여야 드래그. 드래그 끝의 click 은 삼켜 노드 링크가 잘못 열리지 않게
    var d = null;
    vp.addEventListener('pointerdown', function (e) {
      if (e.button !== 0) return;
      d = {x: e.clientX, y: e.clientY, sl: vp.scrollLeft, st: vp.scrollTop, on: false, id: e.pointerId};
    });
    vp.addEventListener('pointermove', function (e) {
      if (!d) return;
      var dx = e.clientX - d.x, dy = e.clientY - d.y;
      if (!d.on && Math.abs(dx) + Math.abs(dy) > 3) {
        d.on = true; vp.classList.add('dragging');
        try { vp.setPointerCapture(d.id); } catch (err) {}
      }
      if (d.on) { vp.scrollLeft = d.sl - dx; vp.scrollTop = d.st - dy; }
    });
    function end() {
      if (d && d.on) { box.__dragged = true; setTimeout(function () { box.__dragged = false; }, 0); }
      vp.classList.remove('dragging'); d = null;
    }
    vp.addEventListener('pointerup', end);
    vp.addEventListener('pointercancel', end);
    vp.addEventListener('click', function (e) {
      if (box.__dragged) { e.preventDefault(); e.stopPropagation(); box.__dragged = false; }
    }, true);
    label(box);
  }
  var boxes = document.querySelectorAll('.zoom-box');
  for (var i = 0; i < boxes.length; i++) init(boxes[i]);
  window.addEventListener('resize', function () { for (var j = 0; j < boxes.length; j++) label(boxes[j]); });
  // 딥링크 착지 훅 — 대상이 확대 상자 안이고 1:1 미만이면 1:1 로(노드 글자 판독)
  window.__issueMapZoom = function (t) {
    var box = t && t.closest ? t.closest('.zoom-box') : null;
    if (box && cur(box) < 0.999) setScale(box, 1);
  };
})();
</script>"""


# «⏸️ 보류 포함» 토글 (Issue974). 기본 = 미포함. 선택값은 localStorage 에 저장 — 저장소가 막힌
#   환경(사생활 모드·file:// 정책)에서도 throw 하지 않고 기본값으로 렌더한다. 키는 프로젝트 공통이다
#   (hub 가 같은 origin 으로 모든 prj 맵을 서빙 — 한 번 켜면 다른 prj 맵에서도 켜진 채로 열린다).
#   숨겨 둔 변형의 확대 상자는 배율 표시가 0% 라 전환 직후 resize 로 다시 잰다(ZOOM_JS 가 듣는다).
HELD_TOGGLE_JS = """<script>
(function () {
  var KEY = 'issueMap.includeHeld';
  var btn = document.querySelector('header .held-toggle');
  function load() { try { return window.localStorage.getItem(KEY) === '1'; } catch (e) { return false; } }
  function save(on) { try { window.localStorage.setItem(KEY, on ? '1' : '0'); } catch (e) {} }
  function apply(on) {
    var vs = document.querySelectorAll('.im-v[data-variant]');
    for (var i = 0; i < vs.length; i++) vs[i].hidden = (vs[i].getAttribute('data-variant') === 'held') ? !on : on;
    document.documentElement.setAttribute('data-held', on ? '1' : '0');
    if (btn) {
      btn.setAttribute('aria-pressed', on ? 'true' : 'false');
      btn.textContent = on ? '⏸️ 보류 포함' : '⏸️ 보류 미포함';
    }
    try { window.dispatchEvent(new Event('resize')); } catch (e) {}
  }
  if (!btn || btn.disabled || !document.querySelector('.im-v[data-variant="held"]')) return;
  if (load()) apply(true);
  btn.addEventListener('click', function () {
    var on = btn.getAttribute('aria-pressed') !== 'true';
    apply(on);
    save(on);
    if (window.__issueMapLand) window.__issueMapLand();
  });
})();
</script>"""


# 딥링크 수신 계약 (Issue740 · fbot-org.md §이슈 축 연동 결정 3 교차 링크):
#   `Issue_map.htm#issue=<N>` — N 은 `740` · `Issue740` · `prj3#Issue740`(인코딩 포함) · `740_2`.
#   같은 data-issue 를 가진 요소(관계도 노드·임계 경로 노드·표 행)를 전부 선택 표시하고,
#   노드(`issue-<N>`)가 있으면 노드로, 없으면(정리 완료로 그래프 밖) 표 행으로 스크롤한다.
DEEPLINK_JS = """<script>
(function () {
  function norm(v) {
    try { v = decodeURIComponent(v || ''); } catch (e) { v = v || ''; }
    v = v.trim().replace(/^prj\\d+#/i, '').replace(/^issue/i, '');
    return /^[0-9A-Za-z_]+$/.test(v) ? v : '';
  }
  function land() {
    var m = /[#&]issue=([^&]+)/.exec(location.hash || '');
    if (!m) return;
    var n = norm(m[1]);
    if (!n) return;
    var old = document.querySelectorAll('.issue-sel');
    for (var i = 0; i < old.length; i++) old[i].classList.remove('issue-sel');
    var hits = document.querySelectorAll('[data-issue="' + n + '"]');
    for (var j = 0; j < hits.length; j++) hits[j].classList.add('issue-sel');
    // Issue974: «보류 포함» 변형이 보이면 그쪽 앵커(`held-` 접두)를 찾는다
    var pre = document.documentElement.getAttribute('data-held') === '1' ? 'held-' : '';
    var t = document.getElementById(pre + 'issue-' + n) || document.getElementById(pre + 'issue-' + n + '-row');
    // Issue828: 노드가 확대 상자 안이면 글자를 읽을 수 있는 배율(1:1)로 키운 뒤 스크롤한다
    if (t && window.__issueMapZoom) window.__issueMapZoom(t);
    if (t) t.scrollIntoView({behavior: 'smooth', block: 'center', inline: 'center'});
    else if (window.console) console.warn('issue-map: #issue=' + n + ' 에 해당하는 노드·행 없음');
  }
  window.addEventListener('hashchange', land);
  window.__issueMapLand = land;
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', land);
  else land();
})();
</script>"""


# ── mermaid 생성 ────────────────────────────────────────────────────────
def esc(s):
    # 백틱 제거: 라벨 선두 백틱은 mermaid 가 markdown-string("`...`") 으로 오인해
    #            "Lexical error / Unrecognized text" 로 렌더가 통째 실패한다 (Issue247).
    #            다이어그램에서 코드체 표기는 의미가 없으므로 전량 제거가 안전.
    return s.replace('"', "'").replace("|", "/").replace("`", "")


def node_line(iss, badges=None):
    if parked(iss):                       # 보류·취소 선행 (Issue259) · 보류 포함 (Issue974)
        icon = SECTIONS[iss['section']][0]
    else:
        icon = "✅" if iss["done"] else ""
    # 헤더 아이콘 겹침 방지 — 이모지를 inline-block span 에 담아 id 와 간격 고정
    #   (글리프 실폭이 달라도 일정, projects-map 과 동일 방식)
    mark = (f'<span style="display:inline-block;margin-left:0.3em">{icon}</span>'
            if icon else "")
    label = f"{iss['id']}{mark}<br>{esc(iss['title'])[:42]}"
    if badges:                            # --fbot 담당 봇 배지 (Issue740)
        label += "<br>" + fbot_badge_label(badges)
    return f'    {iss["id"]}["{label}"]'


def merge_archived_deps(issues, root):
    """활성 이슈가 `depends` 로 가리키는데 활성 `Issue.md` 에 없는 선행을 아카이브에서 보충.

    Issue368 은 아카이브 병합을 **타 prj 조회 경로**(`CrossResolver.issues_of`)에만 넣었다.
    자기 프로젝트 파싱은 활성 `Issue.md` 만 읽으므로, 아카이브를 운영하는 repo 에서는
    활성 이슈의 `depends` 가 허공을 가리켜 **간선이 통째로 사라진다**
    (prj3 실측 1건 — 후행은 활성에 남고 선행만 `_doc_work/issue_OLD.md` 로 이동해 소실).

    전량 병합이 아니라 **참조된 선행만** 끌어온다 — 표·집계를 아카이브로 부풀리지 않는다.
    같은 파일을 가리키는 대소문자 후보는 `resolve()` 로 1회만 읽는다.
    """
    missing = {d for i in issues.values() for d in i["depends"] if d not in issues}
    if not missing:
        return set()
    pulled, seen = set(), set()
    for rel in CrossResolver.ARCHIVES:
        if not missing:
            break
        a = root / rel
        if not a.exists():
            continue
        try:                               # 대소문자만 다른 같은 파일 (case-insensitive FS).
            st = a.stat()                  #   resolve() 는 입력 대소문자를 보존해 못 잡는다
            key = (st.st_dev, st.st_ino)   #   — inode 로 봐야 1회만 읽는다
        except OSError:
            continue
        if key in seen:
            continue
        seen.add(key)
        # 아카이브의 섹션 관례(`# 📦 … 아카이브`)는 활성 Issue.md 와 다르다 — 여기서 나오는
        # 미지 섹션 경고는 사용자가 고칠 것이 아니므로 삼킨다(warn 미전달 + 전용 sink).
        for iid, iss in parse_issue_md(a, lenient=True, quiet=True,
                                       archive=True).items():
            if iid in missing:
                issues[iid] = iss
                pulled.add(iid)
                missing.discard(iid)
    return pulled


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


def build_graph_mmd(issues, stage_map, hidden=frozenset(), resolver=None,
                    isolated=frozenset(), fbot=None):
    lines = ["flowchart TD"]
    visible = {k: v for k, v in issues.items() if k not in hidden}
    fb = (fbot or {}).get("issues") or {}          # --fbot 배지 (Issue740) — 없으면 종전과 동일
    grouped = set()
    for stage, ids in stage_map.items():
        members = [i for i in ids if i in visible]
        if not members:
            continue
        lines.append(f'    subgraph SG_{abs(hash(stage)) % 10**6}["{esc(stage)}"]')
        for iid in members:
            lines.append("    " + node_line(visible[iid], fb.get(iid)))
            grouped.add(iid)
        lines.append("    end")
    for iid, iss in visible.items():
        if iid not in grouped:
            lines.append(node_line(iss, fb.get(iid)))

    def edge_label(iss, dep=None):
        # 화살표 라벨은 60자에서 끊는다 — 전문은 '전이 트리거' 표에 그대로 남는다
        trg = esc(iss["trigger"]) if iss["trigger"] else ""
        trg = trg[:60] + "…" if len(trg) > 60 else trg
        # 선행이 보류·취소면 그 사실을 화살표에 박는다 — 노드만 회색이면
        # "왜 안 풀리는지" 가 안 보인다 (Issue259)
        if dep is not None and parked(dep):
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
            if parked(issues[dep]):
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
        if iss["done"] or parked(iss):
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
    # Issue606: 고립 노드(다른 잔여와 `depends` 로 안 엮인 이슈)는 그래프에서 빼지 않고
    #   흐린 class 로 남긴다 — 엮인 것과 독립인 것을 한 화면에서 구분하기 위함.
    for iid, iss in visible.items():
        cls = ("held" if parked(iss)
               else "iso" if iid in isolated
               else SECTIONS[iss["section"]][1])
        lines.append(f'    class {iid} {cls}')
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
def resolve_mmdc() -> list:
    """mmdc 실행자 해석 (Issue317).

    전역 설치(mmdc) 우선. 없으면 npx 경유로 자동 대체 — 전역 npm prefix 가
    /usr 인 환경(sudo 필요)에서 소비자가 설치 없이 실행할 수 있게 한다.
    둘 다 없을 때만 fail-loud.
    """
    if shutil.which("mmdc"):
        return ["mmdc"]
    if shutil.which("npx"):
        print("[issue-map] mmdc 미설치 → npx 경유 실행 "
              "(첫 실행은 패키지 다운로드로 수 분 소요 가능)", file=sys.stderr)
        return ["npx", "-y", "@mermaid-js/mermaid-cli"]
    raise RuntimeError(
        "mmdc·npx 모두 없음 — `npm i -g @mermaid-js/mermaid-cli` 또는 node/npx 설치 후 재실행")


def render_svg(mmd_text: str, workdir: Path, name: str) -> str:
    runner = resolve_mmdc()
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
    # npx 첫 실행은 패키지 다운로드가 붙으므로 넉넉히 (Issue317)
    r = subprocess.run(runner + ["-i", str(src), "-o", str(dst), "-b", "transparent",
                       "-c", str(cfg)],
                       capture_output=True, text=True, env=env, timeout=600)
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
    # Issue828: 자연 폭을 남긴다 — 확대 상자가 배율(1:1 = 자연 폭)을 계산하는 기준이다.
    #   max-width 가 없으면 viewBox 폭으로 대신한다.
    vb = re.search(r'viewBox="\s*[-\d.]+[\s,]+[-\d.]+[\s,]+([\d.]+)', head)
    natural = m.group(1) if m else (vb.group(1) if vb else "")
    head = re.sub(r'\s(?:style|width|data-natural-w)="[^"]*"', "", head)   # 기존 style·고정 폭 제거
    nat_attr = f' data-natural-w="{natural}"' if natural else ""
    head = head.replace(
        "<svg",
        f'<svg{nat_attr} style="max-width:{cap};height:auto;display:block;margin:0 auto"', 1)
    return head + body


def zoom_box(svg: str) -> str:
    """Issue828: SVG 를 확대 상자(도구 막대 + 스크롤 뷰포트)로 감싼다.

    넓은 그래프는 `fit_svg` 캡 때문에 화면 폭으로 눌려 글자를 못 읽는다. 캡은 작은 그래프의
    과확대 방지(Issue251)라 유지하고, 사용자가 필요할 때 키우는 수단을 붙인다. 동작은 `ZOOM_JS`."""
    return (
        '<div class="zoom-box">\n'
        '<div class="zoom-bar" role="toolbar" aria-label="관계도 확대">'
        '<button type="button" data-zoom="out" title="축소">－</button>'
        '<span class="zoom-pct" aria-live="polite"></span>'
        '<button type="button" data-zoom="in" title="확대">＋</button>'
        '<button type="button" data-zoom="fit" title="화면 폭에 맞춤">맞춤</button>'
        '<button type="button" data-zoom="1" title="원래 크기(글자 판독)">1:1</button>'
        '<button type="button" data-zoom="full" title="전체 화면">⛶</button>'
        '<span class="zoom-hint">드래그로 이동 · Ctrl/⌘+휠(핀치)로 확대</span>'
        '</div>\n'
        f'<div class="zoom-vp">\n{svg}\n</div>\n'
        '</div>'
    )


# ── HTML 조립 ───────────────────────────────────────────────────────────
def blocking_of(iss, issues, resolver=None):
    """미해소 선행 판정의 **단일 지점** (Issue436_3) — status_text(HTML)·emit_json(--json) 공용.

    반환 (local, ext_blocked, unknown):
        local        미완료 로컬 선행 id 목록
        ext_blocked  미완료로 확인된 타 prj 선행 ("prj1#IssueN")
        unknown      확인 실패한 타 prj 선행 — '착수 가능' 으로 부르면 거짓 안전 신호
    """
    local = [d for d in iss["depends"] if d in issues and not issues[d]["done"]]
    ext_blocked, unknown = [], []
    cross = resolver is not None and resolver.enabled     # --no-cross 면 기존 동작 유지
    for ref, dep_iid in (iss["ext"] if cross else []):    # 타 prj 선행도 차단 요인 (Issue252)
        st = resolver.status(ref, dep_iid)
        if st["ok"] and not st["done"]:
            ext_blocked.append(f"{ref}#{dep_iid}")
        elif not st["ok"]:
            unknown.append(f"{ref}#{dep_iid}")
    return local, ext_blocked, unknown


def status_text(iss, issues, resolver=None):
    if iss["done"]:
        return "✅ 완료" + (f" ({iss['commit']})" if iss["commit"] else "")
    if iss["note"]:
        return iss["note"]
    local, ext_blocked, unknown = blocking_of(iss, issues, resolver)
    # 보류·취소 선행은 '기다리면 풀리는 차단' 이 아니므로 상태 문구에 그 사실을 남긴다 (Issue259)
    blockers = [f"{d} {SECTIONS[issues[d]['section']][0]}" if parked(issues[d]) else d
                for d in local] + ext_blocked
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

    # 경로 SSOT 문구는 resolver 값 기반 동적 출력 (Issue436_3 — 개인 경로 하드코딩 금지)
    ssot_html = (f"<code>{html.escape(str(resolver.projects_dir))}/&#123;번호&#125;</code>"
                 if resolver.projects_dir
                 else f"<code>{html.escape(str(PM_BASE_FILE))}</code> 미설정 — cross-prj 미조회")

    return f"""<!-- ISSUE-MAP:CROSS:START -->
<h2>타 프로젝트 연동</h2>
<div class="wrap">
<table>
  <tr><th>이 prj 이슈</th><th>타 prj 선행</th><th>대상 경로</th><th>대상 섹션</th><th>판정</th></tr>
{table}
</table>
</div>
<p>다른 프로젝트의 <code>Issue.md</code> 를 직접 열어 상태를 확인한 결과입니다(경로 SSOT: {ssot_html}). 관계도에서는 점선 테두리 노드로 그려집니다.</p>

<h3>교착(순환 대기) 진단</h3>
{verdict_html}
<!-- ISSUE-MAP:CROSS:END -->"""


def build_variant(issues, svg_graph, svg_critical, hidden=frozenset(), isolated=frozenset(),
                  has_graph=True, resolver=None, cycles=(), has_edges=True, fbot=None,
                  held_mode=False):
    """한 변형(기본 / «⏸️ 보류 포함» — Issue974)의 (meta 문구, 본문 HTML).

    본문 = 관계도·임계 경로·타 prj 연동·진행 전·트리거·이슈 목록. 두 변형이 한 문서에 들어가므로
    포함 변형은 앵커 id 에 `held-` 접두를 달고 `ISSUE-MAP:*` 마커를 뺀다 — 마커는 hub 가
    파싱하는 계약이라 기본 변형 1벌만 둔다(`_issue_map_has_graph` 판정 불변).
    """
    # Issue740 — fbot=None 이면 오버레이 미요청(표 열·범례 모두 종전과 동일)
    fb_on = bool(fbot and fbot.get("ok"))
    fb = (fbot or {}).get("issues") or {}
    pfx = "held-" if held_mode else ""

    def graph_cell(iid):                                   # Issue247: 3값 표기
        if iid in hidden:
            return "정리 완료"
        if iid in isolated:
            return "미연결(흐림)"                          # Issue606: 그래프에 흐리게 존치
        return "표시"

    # Issue250: 표에는 '그래프 연동분 ∪ 미완료 전량'만 남긴다.
    # 그래프와 무관한 과거 완료 이슈를 매번 수백 행씩 다시 그릴 이유가 없다.
    # Issue259: 유령(보류·취소 선행)은 그래프에만 남기고 표·집계에서는 뺀다.
    active = {k: v for k, v in issues.items() if not v["ghost"]}
    in_graph = {k for k in issues if k not in hidden}   # Issue606: isolated 도 그래프에 존치
    listed = [i for i in active.values()
              if not i["done"] or i["id"] in in_graph]
    dropped = len(active) - len(listed)

    def dep_cell(i):     # 로컬 + 타 prj 선행을 한 칸에 (Issue252)
        parts = list(i["depends"]) + [f"{r}#{d}" for r, d in i["ext"]]
        return html.escape(", ".join(parts)) if parts else "&mdash;"

    # Issue740 — 표 행 앵커 `issue-<N>-row`(노드가 `issue-<N>` 을 가진다 — id 는 문서에서 유일)
    #   + 번호 칸 자체가 딥링크(`#issue=<N>`)라 복사해 공유할 수 있다
    rows = "\n".join(
        "  <tr id=\"{pfx}issue-{n}-row\" data-issue=\"{n}\"><td><a href=\"#issue={n}\">{id}</a></td>"
        "<td>{title}</td><td class='sec'>{sec}</td>"
        "<td>{dep}</td><td>{st}</td><td>{gr}</td>{fbc}</tr>".format(
            n=html.escape(i["id"][len("Issue"):]), pfx=pfx,
            id=i["id"], title=html.escape(i["title"]),
            sec=SECTIONS[i["section"]][0],
            dep=dep_cell(i),
            st=html.escape(status_text(i, issues, resolver)),
            gr=graph_cell(i["id"]),
            fbc=(f"<td>{fbot_cell(fb.get(i['id']))}</td>" if fb_on else ""))
        for i in listed) or (f"  <tr><td colspan='{7 if fb_on else 6}'>남은 이슈 없음</td></tr>")
    fb_th = "<th>담당(fbot)</th>" if fb_on else ""
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
    n_held = sum(1 for i in active.values() if i.get("held"))

    # ── 조건부 섹션 (Issue247) ───────────────────────────────────────────
    # edge 가 하나도 없으면 의존 관계도·임계 경로는 보여줄 것이 없으므로 통째 생략.
    # Issue606: 관계도는 **노드 기준**, 임계 경로는 **간선 기준**으로 갈랐다.
    #   간선 0 이라고 관계도를 통째 생략하면 잔여 이슈가 있어도 hub 아이콘이 사라진다
    #   (server.py `_issue_map_has_graph` 는 이 블록 안의 `<svg` 유무로 판정한다).
    critical_section = f"""
<h2>임계 경로</h2>
<!-- ISSUE-MAP:CRITICAL:START -->
<figure>
{zoom_box(svg_critical)}
<figcaption>미완료 이슈 중 의존 사슬이 가장 긴 경로. 중간 하나가 막히면 뒤 전체가 정지합니다.</figcaption>
</figure>
<!-- ISSUE-MAP:CRITICAL:END -->
""" if has_edges else """
<h2>임계 경로</h2>
<!-- ISSUE-MAP:CRITICAL:START -->
<blockquote><p><code>depends</code> 로 이어진 이슈가 없어 임계 경로를 생략했습니다 &mdash; 남은 이슈가 서로 독립이라 순서 제약이 없습니다.</p></blockquote>
<!-- ISSUE-MAP:CRITICAL:END -->
"""
    excl_note = (
        "<strong>⏸️ 보류 이슈를 포함</strong>해 회색 점선 노드로 그립니다(타 프로젝트 선행 포함). "
        "<strong>취소 이슈는 제외</strong>되며, 활성 이슈가 선행으로 걸고 있는 경우에만 회색 점선 노드로 남습니다."
        if held_mode else
        "<strong>보류 · 취소 이슈는 맵에서 제외</strong>되며, 활성 이슈가 선행으로 걸고 있는 경우에만 "
        "회색 점선 노드로 남습니다. 보류 이슈는 상단 <strong>⏸️ 보류</strong> 토글로 켜서 볼 수 있습니다.")
    graph_section = f"""<h2>전체 의존 관계</h2>
<!-- ISSUE-MAP:GRAPH:START -->
<figure>
{zoom_box(svg_graph)}
<figcaption>노드 색은 <code>Issue.md</code> 섹션(완료 · 중요 · 일반 · 선택), 화살표 색은 선행 이슈 완료 여부로 결정됩니다. <strong>다른 잔여 이슈와 <code>depends</code> 로 엮이지 않은 독립 이슈는 흐린 회색</strong>으로 그려집니다 &mdash; 그래프에서 빠지지는 않습니다. 자신도 후행도 모두 완료된 이슈만 표로 빠집니다. {excl_note}</figcaption>
</figure>
<!-- ISSUE-MAP:GRAPH:END -->
{critical_section}""" if has_graph else """<!-- ISSUE-MAP:GRAPH:START -->
<blockquote><p>남은 이슈가 없어 의존 관계도·임계 경로를 생략했습니다.</p></blockquote>
<!-- ISSUE-MAP:GRAPH:END -->
"""

    # Issue606: 흐리게라도 그래프에 있으므로 '진행 전 이슈' 는 독립 이슈의 **평문 목록**
    #   역할만 남는다 (상태·섹션을 표로 훑는 용도). 그래프 부재 시에는 전량이 여기 온다.
    pending = [i for i in active.values()
               if not i["done"] and (i["id"] in isolated or not has_graph)]
    pending_rows = "\n".join(
        "  <tr><td>{id}</td><td>{title}</td><td class='sec'>{sec}</td><td>{st}</td></tr>".format(
            id=i["id"], title=html.escape(i["title"]),
            sec=SECTIONS[i["section"]][0],
            st=html.escape(status_text(i, issues, resolver)))
        for i in pending) or "  <tr><td colspan='4'>없음 &mdash; 미완료 이슈가 모두 의존 관계도 안에 있습니다</td></tr>"

    meta = (f"이슈 {total}건 · 완료 {done}건"
            + (f" · ⏸️ 보류 {n_held}건 포함" if held_mode else ""))
    body = f"""{graph_section}
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
  <tr><th>번호</th><th>제목</th><th>섹션</th><th>depends</th><th>상태</th><th>그래프</th>{fb_th}</tr>
{rows}
</table>
</div>
{hidden_note}
<!-- ISSUE-MAP:TABLE:END -->
"""
    if held_mode:
        body = re.sub(r"<!-- ISSUE-MAP:[A-Z]+:(?:START|END) -->\n?", "", body)
    return meta, body


def build_html(base, held, preserved_notes, root: Path, fbot=None):
    """문서 조립 — base·held = `build_variant` 의 (meta, 본문). held=None 이면 보류 이슈 0건(Issue974).

    기본 변형이 먼저 온다(무 JS·hub 파서가 보는 쪽). 포함 변형은 `hidden` 으로 실어 두고
    헤더 토글(`HELD_TOGGLE_JS`)이 localStorage 값에 따라 전환한다.
    """
    fb_on = bool(fbot and fbot.get("ok"))
    if fb_on:
        fbot_note = (
            '<p class="fbot-note">노드 아래 배지 = <strong>담당 봇</strong>(원장 <code>fbot_dispatch</code> '
            f'읽기 전용 조인 · 열린 배분 + 최근 {FBOT_RECENT_SECS // 86400}일). '
            "사인 ⏳ 수행중 · ✓ 완료 · ⛔ 차단 · ⌇ 회수(완료 미상) · ✕ 취소 · ▪ 사후 기록 · ⏸ 보류. "
            "표의 <strong>담당(fbot)</strong> 열에 배분자(&larr;)를 함께 적습니다.</p>")
    elif fbot is not None:
        fbot_note = (f'<p class="fbot-note">fbot 오버레이 생략 &mdash; '
                     f'{html.escape(fbot.get("reason") or "")}</p>')
    else:
        fbot_note = ""
    notes = preserved_notes or (
        "<ul>\n  <li>메모 없음 &mdash; 이 구간은 수기 편집분이 보존됩니다."
        " 재생성해도 지워지지 않습니다.</li>\n</ul>")
    base_meta, base_body = base
    meta_spans = f'<span class="im-v" data-variant="base">{base_meta}</span>'
    bodies = f'<div class="im-v im-body" data-variant="base">\n{base_body}\n</div><!-- /im-body -->'
    if held is not None:
        meta_spans += f'<span class="im-v" data-variant="held" hidden>{held[0]}</span>'
        bodies += (f'\n<div class="im-v im-body" data-variant="held" hidden>\n{held[1]}'
                   '\n</div><!-- /im-body -->')
        toggle_btn = ('<button type="button" class="held-toggle" aria-pressed="false" '
                      'title="⏸️ 보류 이슈를 관계도·표에 포함할지 전환 (선택값은 이 브라우저에 저장)">'
                      '⏸️ 보류 미포함</button>')
    else:
        toggle_btn = ('<button type="button" class="held-toggle" aria-pressed="false" disabled '
                      'title="보류 이슈 없음">⏸️ 보류 없음</button>')
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
  .im-v[hidden] {{ display: none !important; }}
  header button.held-toggle[aria-pressed="true"] {{ background: rgba(138,122,176,0.35); border-color: {EDGE_HELD}; }}
  header button.held-toggle:disabled {{ opacity: 0.45; cursor: default; text-decoration: none; }}
  footer {{ margin-top: 3rem; padding-top: 1rem; border-top: 1px solid rgba(127,127,127,0.3);
    font-size: 0.85rem; opacity: 0.75; }}
{ANCHOR_CSS}
{ZOOM_CSS}
  @media (prefers-color-scheme: dark) {{
    body {{ background: #16181c; color: #e6e6e6; }}
    .zoom-box:fullscreen {{ background: #16181c; }}
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
    {toggle_btn}
    <button type="button" class="close-btn" title="이 문서 탭 닫기" onclick="window.close()">✕</button>
  </nav>
</header>
<div class="meta">{meta_spans} · 기준 자료 <code>Issue.md</code> · 갱신 {date.today().isoformat()}</div>

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
{fbot_note}

{bodies}

<h2>메모 (수기 편집 구간 · 재생성 시 보존)</h2>
<!-- ISSUE-MAP:NOTES:START -->
{notes}
<!-- ISSUE-MAP:NOTES:END -->

<footer>
  <p>생성: <code>build_issue_map.py</code> (issue-map 스킬 — 글로벌 SCAR / fpm-core 번들) · 기준: <code>Issue.md</code></p>
</footer>

{HELD_TOGGLE_JS}
{ZOOM_JS}
{DEEPLINK_JS}
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
    chains = [walk(i["id"]) for i in issues.values() if not i["done"] and not parked(i)]
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


def emit_json(issues, resolver, root: Path, fbot=None) -> None:
    """--json: 파싱·판정 결과를 기계 소비용 JSON 으로 stdout 출력 (Issue436_3).

    htm 미생성·mmdc 미호출 — 빠르고 무의존. 판정은 blocking_of(status_text 와
    동일 지점) 재사용만 한다 — 소비처(fbot-lead)가 착수 가능을 재판정하지 않는다.
    경고류는 전부 stderr 로 나가므로 stdout 은 항상 순수 JSON 1건이다.
    """
    out_issues = []
    for iss in issues.values():
        local, ext_blocked, unknown = blocking_of(iss, issues, resolver)
        if iss["done"]:
            state = "done"
        elif iss["ghost"]:                     # 보류·취소 유령 — 기다려도 자동 해제 없음
            state = "held"
        elif local or ext_blocked:
            state = "blocked"
        elif unknown:                          # 미확인은 '착수 가능' 이 아니다 (거짓 안전 신호 금지)
            state = "unknown"
        else:
            state = "startable"
        out_issues.append({
            "id": iss["id"],
            "title": iss["title"],
            "section": iss["section"],
            "state": state,
            "depends": list(iss["depends"]) + [f"{r}#{d}" for r, d in iss["ext"]],
            "blocked_by": local + ext_blocked + unknown,
            "startable": state == "startable",
        })
    cross = []
    if resolver is not None and resolver.enabled:
        for iss in issues.values():
            for ref, dep_iid in iss["ext"]:
                st = resolver.status(ref, dep_iid)
                cross.append({
                    "ref": f"{ref}#{dep_iid}",
                    "status": ("done" if st["done"]
                               else ("blocked" if st["ok"] else "unknown")),
                })
    doc = {"root": str(root), "generated": int(time.time()),
           "issues": out_issues, "cross": cross}
    # Issue740 — `--fbot` 일 때만 `fbot` 키를 **추가**한다. 소비처 fbot-lead `load_issue_map()` 은
    #   `--fbot` 없이 부르므로 기존 4키 스키마는 바이트 단위로 그대로다. icon_uri(수백 B base64)는
    #   기계 소비에 쓸모가 없어 뺀다
    if fbot is not None:
        doc["fbot"] = {
            "ok": fbot["ok"], "reason": fbot["reason"], "db": fbot["db"],
            "window_secs": fbot["window_secs"],
            "issues": {iid: [{k: v for k, v in b.items() if k != "icon_uri"} for b in bs]
                       for iid, bs in fbot["issues"].items()},
        }
    print(json.dumps(doc, ensure_ascii=False))


def print_dep_warnings(warn: list) -> None:
    """`* depends:` 규약 위반을 stderr 로 보고 (Issue343).

    stderr 인 이유: 이 스크립트의 stdout 은 요약이고, 경고는 파이프로 흘려도
    사라지면 안 되는 신호다. 자동 교정은 하지 않는다 — 규약 위반의 해석은 사람 몫.
    """
    if not warn:
        return
    bad = [w for w in warn if w[0] == "unparsed"]
    named = [w for w in warn if w[0] == "named_ref"]
    if bad:
        print(f"\n⚠️ depends 파싱 실패 {len(bad)}건 — 이 의존은 지도에 그려지지 않았다:",
              file=sys.stderr)
        for _, iid, raw in bad:
            print(f"   {iid:<12} {raw!r}", file=sys.stderr)
    if named:
        print(f"\n⚠️ prj 이름 표기 {len(named)}건 — `prj<번호>#Issue<N>` 로 고칠 것 "
              "(이름은 레지스트리에 없어 cross-prj 조회가 실패한다):", file=sys.stderr)
        for _, iid, raw in named:
            print(f"   {iid:<12} {raw!r}", file=sys.stderr)
    print("   규약: rules/issue-g.md 규칙2 `depends` 토큰 문법\n", file=sys.stderr)


def render_variant(issues, stage_map, hidden, isolated, has_graph, has_edges,
                   resolver, cycles, fbot, wd: Path, held_mode=False):
    """한 변형의 SVG 렌더 + 본문 조립 → `build_variant` 의 (meta, 본문) (Issue974).

    «보류 포함» 변형은 mermaid SVG id(`my-svg`)를 바꾼다 — 같은 id 가 두 번 나오면 포함 변형의
    화살촉 `marker-end="url(#my-svg_…)"` 가 **숨겨진** 기본 변형의 marker 를 가리켜 사라진다.
    """
    svg_graph = svg_crit = ""
    tag = "-held" if held_mode else ""
    pfx = "held-" if held_mode else ""

    def fix(svg):
        return svg.replace("my-svg", "my-svg-held") if held_mode else svg

    if has_graph:                      # 노드 0 이면 mmdc 를 아예 타지 않는다
        # Issue740 — 관계도 노드에 안정 id `issue-<N>`, 임계 경로엔 data-issue 만(id 중복 방지)
        svg_graph = anchor_svg_nodes(fix(render_svg(
            build_graph_mmd(issues, stage_map, hidden, resolver, isolated, fbot),
            wd, "graph" + tag)), id_prefix=pfx)
        svg_crit = (anchor_svg_nodes(fix(render_svg(build_critical_mmd(issues), wd,
                                                    "critical" + tag)), with_id=False)
                    if has_edges else "")
    return build_variant(issues, svg_graph, svg_crit, hidden, isolated, has_graph,
                         resolver, cycles, has_edges, fbot, held_mode=held_mode)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="Issue_map.htm")
    ap.add_argument("--issue", default="Issue.md")
    ap.add_argument("--check", action="store_true", help="파싱 결과만 출력 (파일 미생성)")
    ap.add_argument("--json", dest="as_json", action="store_true",
                    help="파싱·판정 결과를 JSON 으로 stdout 출력 (htm 미생성·mmdc 미호출)")
    ap.add_argument("--all", action="store_true",
                    help="정리 완료 노드(완료 + 후행도 전부 완료)까지 그래프에 표시")
    ap.add_argument("--no-cross", action="store_true",
                    help="타 프로젝트 선행을 조회하지 않음 (오프라인·속도 우선)")
    ap.add_argument("--deadlock", action="store_true",
                    help="교착(순환 대기) 진단만 출력 (파일 미생성)")
    ap.add_argument("--fbot", action="store_true",
                    help="핀봇 배분 원장을 읽기 전용 조인해 담당 봇 배지 표시 (옵트인, Issue740)")
    args = ap.parse_args()

    root = Path.cwd()
    issue_md = root / args.issue
    if not issue_md.exists():
        sys.exit(f"❌ {issue_md} 없음 — nPTiR 루트에서 실행할 것")

    dep_warn: list = []
    issues = parse_issue_md(issue_md, warn=dep_warn)
    if not issues:
        sys.exit("❌ 이슈 파싱 결과 0건 — Issue.md 형식 확인 필요")
    pulled = merge_archived_deps(issues, root)   # Issue606: 아카이브로 옮겨진 선행 보충
    # Issue974: «⏸️ 보류 포함» 변형은 제외 전 사본에서 만든다 — split_excluded 가 지우고 비운다
    issues_held = (copy.deepcopy(issues)
                   if any(i["section"] == HELD_SECTION for i in issues.values()) else None)
    ghosts = split_excluded(issues)         # ⏸️ 보류 · 🚫 취소 제외 (Issue259)
    stage_map = load_stage_map(root)

    # 타 프로젝트 연동 (Issue252)
    resolver = CrossResolver(root, enabled=not args.no_cross)
    demote_self_refs(issues, resolver)
    cycles = resolver.deadlocks(issues)

    # Issue740 — 옵트인 오버레이. 실패는 **오류 exit 가 아니다** — 1줄 안내 후 오버레이만 뺀다
    fbot = None
    if args.fbot:
        fbot = load_fbot_overlay(root, set(issues))
        if not fbot["ok"]:
            print(f"ℹ️ fbot 오버레이 생략 — {fbot['reason']} · 나머지 출력은 정상",
                  file=sys.stderr)

    if args.as_json:                        # Issue436_3 — 기계 출력, htm 경로 완전 미진입
        emit_json(issues, resolver, root, fbot)
        print_dep_warnings(dep_warn)
        return

    if args.deadlock:
        print_deadlock_report(issues, resolver, cycles)
        print_dep_warnings(dep_warn)
        return

    hidden = frozenset() if args.all else settled(issues)
    # Issue606: 고립 노드를 그래프에서 **빼지 않는다** — 흐린 class 로 남긴다.
    #   구 동작(Issue247)은 간선 0 이면 그래프를 통째로 생략했고, 그 결과
    #   잔여 이슈가 있는 프로젝트에서도 hub 이슈맵 아이콘이 사라졌다.
    linked = linked_ids(issues, hidden)
    isolated = frozenset(k for k in issues if k not in hidden and k not in linked)
    graph_hidden = hidden
    has_graph = bool(set(issues) - graph_hidden)   # 노드가 하나라도 있으면 렌더
    has_edges = bool(linked)                       # 임계 경로는 간선이 있어야 의미

    if args.check:
        for i in issues.values():
            if i["ghost"]:
                mark = " [표 제외: 보류·취소 — 활성 선행이라 유령 노드로 존치]"
            elif i["id"] in hidden:
                mark = " [그래프 제외: 정리 완료]"
            elif i["id"] in isolated:
                mark = " [그래프: 미연결 → 흐림 표시]"
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
        if fbot and fbot["ok"]:
            for iid, bs in fbot["issues"].items():
                print(f"fbot 배지 {iid:<10} " + " · ".join(
                    f"{b['sign']} {b['worker']} ← {b['owner']}" for b in bs))
        if not has_edges:
            print("ℹ️ depends 연결 0건 — 임계 경로만 생략, 관계도는 흐린 노드로 렌더")
        if not has_graph:
            print("⚠️ 남은 노드 0건 — 관계도 생략")
        print()
        print_deadlock_report(issues, resolver, cycles)
        print_dep_warnings(dep_warn)
        return

    # Issue606(A): 잔여 이슈가 하나도 없으면 볼 것이 없다 — 맵을 만들지 않고
    #   이미 있던 산출물은 지운다. hub 아이콘은 파일 존재로 판정하므로 함께 사라진다.
    #   `--all` 은 진단용 탈출구라 이 게이트를 우회한다.
    out = root / args.out
    remaining = [i for i in issues.values() if not i["done"] and not i["ghost"]]
    if not remaining and not args.all:
        if out.exists():
            out.unlink()
            print(f"🧹 {out} 제거 — 잔여 이슈 0건 (전량 완료). 재생성은 `--all`")
        else:
            print("ℹ️ 잔여 이슈 0건 (전량 완료) — 맵을 생성하지 않았습니다. 전량 표시는 `--all`")
        print_dep_warnings(dep_warn)
        return

    with tempfile.TemporaryDirectory() as td:
        wd = Path(td)
        base = render_variant(issues, stage_map, hidden, isolated, has_graph, has_edges,
                              resolver, cycles, fbot, wd)
        held = None
        if issues_held is not None:        # Issue974 — 보류 이슈가 있을 때만 두 번째 렌더
            split_excluded(issues_held, HELD_TOGGLE_EXCLUDED)   # 아카이브 선행은 사본 전에 보충됨
            demote_self_refs(issues_held, resolver)
            h_hidden = frozenset() if args.all else settled(issues_held)
            h_linked = linked_ids(issues_held, h_hidden)
            h_isolated = frozenset(k for k in issues_held
                                   if k not in h_hidden and k not in h_linked)
            h_fbot = load_fbot_overlay(root, set(issues_held)) if args.fbot else None
            held = render_variant(issues_held, stage_map, h_hidden, h_isolated,
                                  bool(set(issues_held) - h_hidden), bool(h_linked),
                                  resolver, resolver.deadlocks(issues_held), h_fbot, wd,
                                  held_mode=True)

    html_text = build_html(base, held, extract_notes(out), root, fbot)
    out.write_text(html_text)
    shown = len(issues) - len(graph_hidden)
    n_ext = sum(len(i["ext"]) for i in issues.values())
    print(f"✅ {out} 생성 ({out.stat().st_size / 1024:.1f} KB, 이슈 {len(issues) - len(ghosts)}건"
          + (f", 그래프 {shown}건 표시" if has_graph else ", 그래프 생략(남은 노드 0건)")
          + (f" / 미연결 {len(isolated)}건 흐림" if isolated else "")
          + ("" if has_edges else " / 간선 0건 → 임계 경로 생략")
          + (f" / 아카이브 선행 {len(pulled)}건 보충" if pulled else "")
          + (f" / 정리 완료 {len(hidden)}건 숨김" if hidden else "")
          + (f" / 보류·취소 유령 {len(ghosts)}건" if ghosts else "")
          + (f" / 타 prj 선행 {n_ext}건" if n_ext else "")
          + (f" / fbot 배지 {len(fbot['issues'])}건" if fbot and fbot["ok"] else "")
          + (f" / ⏸️ 보류 포함 토글 {sum(1 for i in issues_held.values() if i.get('held'))}건"
             if issues_held is not None else "") + ")")
    if cycles:
        print(f"🔴 교착 {len(cycles)}건 검출 — 상세는 `--deadlock`:")
        for c in cycles:
            print("   " + " → ".join(c))
    elif resolver.unresolved:
        print(f"⚠️ 타 prj 선행 {len(set(resolver.unresolved))}건 미확인 — 차단 여부 미판정 "
              "(`--deadlock` 로 상세 확인)")
    print_dep_warnings(dep_warn)


if __name__ == "__main__":
    main()
