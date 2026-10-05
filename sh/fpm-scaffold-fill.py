#!/usr/bin/env python3
"""fpm-scaffold-fill — pm-new 스캐폴드의 «내용 채움» 집행자 (Issue499).

왜 있나
------
`data/template/` 은 **양식**만 준다. 종전에는 그 양식을 프로젝트 값으로 바꾸는 일이
`pm/SKILL.md` 산문에만 적혀 있었고 — 심지어 `Harness.md` 는 *"동일 타입의 기존
프로젝트에서 **자동** 수집하여 초기 채움"* 이라고 **하지 않는 일을 한다고** 적고 있었다 —
집행자(세션)가 기억해서 손으로 하거나 하지 않았다. 그 결과 2026-09-19 전수 실측에서
미치환 플레이스홀더가 **12개 prj**, prj1 것이 그대로 박힌 `Project Mananger` 가 **6개 prj**
에 남아 있었다.

⇒ *"문서가 «한다» 고 적었으면 집행자를 밝힌다"* 는 원칙에 따라, 그 집행을 여기로 옮긴다.

무엇을 하나
----------
1. **토큰 치환** — `{{프로젝트명}}`·`{{설명}}`·`{{날짜}}`·`{{prj}}` 를 실제 값으로.
   대상은 docs 전체다(`Issue.md`·`Harness.md`·`CLAUDE.md`·`PROMPTS.md`·`noteForHuman.md`).
   ⚠️ 종전 스킬은 `CLAUDE.md`·`PROMPTS.md`·`vscode.json`·`zed.json` 만 치환하고
      `Issue.md`·`Harness.md` 는 `cp` 였다 — 오염이 정확히 그 둘에서 나왔다.
2. **Harness global layer 채움** — `data/harness-defaults.yml` 의 타입별 기본값.
3. **검증(`--check`)** — 미치환 플레이스홀더·빈 global layer 를 보고. 쓰지 않는다.

사용
----
    sh/fpm-scaffold-fill.py <repo> --name <프로젝트명> --type general|web|mac \
                            [--desc <설명>] [--prj <번호>] [--force]
    sh/fpm-scaffold-fill.py <repo> --check      # 감사(읽기 전용)
    sh/fpm-scaffold-fill.py --check-all         # 등록 프로젝트 전수 감사(읽기 전용)

exit: 0=정상/오염 없음 · 1=오염 발견(--check) · 2=인자 오류
"""
import argparse
import datetime
import os
import re
import sys
from pathlib import Path

DOC_FILES = ['Issue.md', 'Harness.md', 'CLAUDE.md', 'PROMPTS.md', 'noteForHuman.md']

# 오염 탐지 패턴 — 「치환됐어야 하는데 남은 것」만 본다.
#   ⚠️ `{주제}`·`{N}` 같은 **양식 안내**는 오염이 아니다(사람이 쓸 때 채우는 자리).
#   그래서 토큰명을 열거로 고정한다 — 정규식 `\{[^}]+\}` 로 뭉뚱그리면 견본이 전부 걸린다.
TOKENS = ['프로젝트명', '설명', '날짜', 'prj', 'domain_suffix']
STALE_RE = re.compile(r'\{\{(' + '|'.join(TOKENS) + r')\}\}')
# prj1 고유값이 템플릿을 타고 번진 흔적. **오타 철자 하나만** 본다 —
#   올바른 "Project Manager" 는 prj1 자신의 정당한 제목이라 구분이 안 되고,
#   오타 `Mananger` 는 «prj1 템플릿을 복사했다» 는 명확한 지문이다.
LEAK_RE = re.compile(r'Project Mananger')

# 산문 속 «언급» 을 오염으로 세지 않는다 — 코드펜스·백틱 안의 토큰은 설명이다.
#   (prj1 Issue.md 가 `{{날짜}}`·`{{prj}}` 를 이슈 본문에서 인용한다)
FENCE_RE = re.compile(r'```.*?```', re.S)
CODESPAN_RE = re.compile(r'`[^`\n]*`')


def strip_code(text):
    return CODESPAN_RE.sub('', FENCE_RE.sub('', text))

# 구 템플릿(2026-03~09)의 단일 중괄호 플레이스홀더 — 신규 토큰 규약 이전 세대다.
#   이것들이 남아 있으면 그 repo 는 «구 템플릿을 복사한 뒤 아무도 채우지 않은» 상태다.
LEGACY_PATTERNS = [
    (re.compile(r'\{git-hash\}'), '{git-hash}'),
    (re.compile(r'^\s*-\s*\{git-hash\}\s+\{date\}', re.M), '{git-hash} {date}'),
    (re.compile(r'\{결론 한 줄'), '{결론 한 줄 …}'),
    (re.compile(r'^\|\s*\{결론', re.M), '결정사항 예시 행'),
]
# 가짜 «완료» 이슈 — 형식이 올바라서 눈에 안 띄고, 사람도 도구도 실적으로 읽는다.
#   `Issue HWM: 0` 과 어긋나 첫 이슈 등록에서 번호까지 충돌한다.
#   ⚠️ 견본의 **원문 그대로**만 잡는다. `^## Issue1:.*✅` 같은 느슨한 식은 실제 이슈
#      (진짜 Issue1 을 완료한 프로젝트)를 오탐한다 — 견본 문구는 아무도 안 고치므로
#      리터럴 대조가 오히려 정확하다.
FAKE_DONE_RE = re.compile(
    r'^##\s+Issue\{#\}:\s*\{제목\}|^##\s+Issue1:\s*기능 설명.*abc1234', re.M)

SECTIONS = [('Skills', 'skills'), ('Commands', 'commands'),
            ('Agents', 'agents'), ('Rules', 'rules')]


def load_defaults(pm_base, ptype):
    import yaml
    f = Path(pm_base) / 'data' / 'harness-defaults.yml'
    if not f.exists():
        return None
    data = yaml.safe_load(f.read_text()) or {}
    return data.get(ptype)


def substitute(repo, name, desc, date, prj):
    """토큰 치환. 치환한 파일 수를 돌려준다."""
    mapping = {
        '{{프로젝트명}}': name,
        '{{설명}}': desc,
        '{{날짜}}': date,
        '{{prj}}': str(prj) if prj is not None else '',
    }
    n = 0
    for fname in DOC_FILES:
        p = Path(repo) / fname
        if not p.exists():
            continue
        s = orig = p.read_text()
        for k, v in mapping.items():
            if v:                      # 빈 값으로 덮어써서 토큰을 «지워» 버리지 않는다
                s = s.replace(k, v)
        if s != orig:
            p.write_text(s)
            n += 1
    return n


def fill_harness(repo, defaults, force=False):
    """global Layer 4절을 기본값으로 채운다. 이미 내용이 있으면 건드리지 않는다(멱등)."""
    p = Path(repo) / 'Harness.md'
    if not p.exists() or not defaults:
        return 0
    lines = p.read_text().splitlines()
    try:
        g_start = next(i for i, l in enumerate(lines) if l.strip() == '# global Layer')
    except StopIteration:
        return 0
    try:
        g_end = next(i for i in range(g_start + 1, len(lines))
                     if lines[i].startswith('# ') and lines[i].strip() != '# global Layer')
    except StopIteration:
        g_end = len(lines)

    filled = 0
    for title, key in SECTIONS:
        items = defaults.get(key) or []
        if not items:
            continue
        try:
            h = next(i for i in range(g_start, g_end) if lines[i].strip() == f'## {title}')
        except StopIteration:
            continue
        nxt = next((i for i in range(h + 1, g_end) if lines[i].startswith('## ')), g_end)
        body = [l for l in lines[h + 1:nxt] if l.strip()]
        if body and not force:
            continue                    # 이미 채워져 있다 — 덮어쓰지 않는다
        block = [''] + [f'* {it}' for it in items] + ['']
        lines[h + 1:nxt] = block
        g_end += len(block) - (nxt - h - 1)
        filled += 1
    if filled:
        p.write_text('\n'.join(lines) + '\n')
    return filled


def audit(repo, label):
    """오염 감사 — 미치환 토큰·prj1 값 누출·빈 global layer. (읽기 전용)"""
    findings = []
    for fname in DOC_FILES:
        p = Path(repo) / fname
        if not p.exists():
            continue
        s = strip_code(p.read_text())
        stale = sorted(set(STALE_RE.findall(s)))
        if stale:
            shown = ' · '.join('{{%s}}' % t for t in stale)
            findings.append(f'{fname}: 미치환 토큰 {shown}')
        if LEAK_RE.search(s):
            findings.append(f'{fname}: prj1 값 누출 "Project Mananger"')
        for rx, tag in LEGACY_PATTERNS:   # ⚠️ 변수명 label 금지 — 인자 label 을 가린다
            if rx.search(s):
                findings.append(f'{fname}: 구 템플릿 플레이스홀더 {tag}')
                break
        if fname == 'Issue.md' and FAKE_DONE_RE.search(s):
            findings.append('Issue.md: 가짜 완료 이슈(견본이 ✅ 로 남아 실적처럼 읽힌다)')
    h = Path(repo) / 'Harness.md'
    if h.exists():
        t = h.read_text()
        if '# global Layer' in t:
            seg = t.split('# global Layer', 1)[1].split('\n# ', 1)[0]
            if not re.search(r'^\s*[-*]\s+\S', seg, re.M):
                findings.append('Harness.md: global Layer 가 빈 골격')
    if findings:
        print(f'  🚨 {label}')
        for f in findings:
            print(f'       - {f}')
    return len(findings)


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument('repo', nargs='?')
    ap.add_argument('--name')
    ap.add_argument('--desc', default='')
    ap.add_argument('--type', dest='ptype', choices=['general', 'web', 'mac'])
    ap.add_argument('--prj')
    ap.add_argument('--date')
    ap.add_argument('--check', action='store_true')
    ap.add_argument('--check-all', action='store_true')
    ap.add_argument('--force', action='store_true')
    a = ap.parse_args()

    self_dir = Path(__file__).resolve().parent
    pm_base = os.environ.get('FPM_BASE') or str(self_dir.parent)

    if a.check_all:
        print('[scaffold] 등록 프로젝트 전수 감사 (읽기 전용)')
        bad = 0
        pdir = Path(pm_base) / 'projects'
        for f in sorted(pdir.iterdir(), key=lambda x: (len(x.name), x.name)) if pdir.is_dir() else []:
            try:
                path = f.read_text().strip()
            except Exception:
                continue
            path = os.path.expanduser(path)
            if not path or not os.path.isdir(path):
                continue
            if audit(path, f'{f.name} {path.replace(os.path.expanduser("~"), "~")}'):
                bad += 1
        print(f'[scaffold] 오염 {bad} 개 프로젝트')
        return 1 if bad else 0

    if not a.repo:
        ap.error('repo 경로가 필요하다 (또는 --check-all)')
    repo = os.path.expanduser(a.repo)
    if not os.path.isdir(repo):
        print(f'[scaffold] 경로 없음: {repo}', file=sys.stderr)
        return 2

    if a.check:
        print(f'[scaffold] {repo}')
        n = audit(repo, repo)
        if not n:
            print('  ✅ 미치환 토큰·값 누출·빈 global layer 없음')
        return 1 if n else 0

    if not a.name or not a.ptype:
        ap.error('--name 과 --type 이 필요하다 (치환 모드)')
    date = a.date or datetime.date.today().strftime('%Y.%m.%d')
    subbed = substitute(repo, a.name, a.desc, date, a.prj)
    filled = fill_harness(repo, load_defaults(pm_base, a.ptype), force=a.force)
    print(f'[scaffold] 치환 {subbed} 파일 · Harness global layer {filled} 절 채움')
    n = audit(repo, repo)
    if n:
        print('[scaffold] ⚠️ 잔존 오염이 있다 — 위 항목을 손으로 채울 것')
        return 1
    print('[scaffold] ✅ 잔존 오염 0')
    return 0


if __name__ == '__main__':
    sys.exit(main())
