#!/usr/bin/env python3
"""test_tagcheck_block_touched_issue584.py — tagcheck ②(동시성) 판정 회귀 (Issue584)

prj3#Issue793 의 `sh/test-precommit-tagcheck.py` 를 prj1 짝 `scripts/precommit-tagcheck.py` 로 이식한 것 —
2원 구조라 **케이스를 같게 유지**한다(한쪽만 고치면 조용히 갈라진다). `issue-tx.py` 는 prj3 공유본을 쓴다.

② 를 «staged Issue.md 의 추가 줄에 번호 문자열이 있는가» 에서
«staged Issue.md 에서 그 번호의 블록이 바뀌었는가» 로 바꾼 것을 격리 repo 로 검증한다.

  ⓐ 인접 섹션 이동 — diff 가 섹션 헤더 이동으로 정렬돼 `## IssueN` 줄이 추가 줄에 안 잡힌다
  ⓑ 블록 안 문구만 고친 커밋 — 추가 줄에 번호 문자열이 없다
  ⓒ 분업 커밋(작업자는 Issue.md 무수정) — `issue-tx commit --issues N` 의 선언(`ISSUE_TX_ISSUES`)을 인정
  + 회귀: 무관 번호·미등록 번호·Issue.md 미스테이징·인과 인용
  + prj3#Issue949: 서브 번호 `N_M` 이 헤딩 없이 부모 블록 본문 항목 `- N_M` 으로만 있을 때의 ①·② 와 거부 안내

⚠️ 픽스처 번호는 `I + '10'` 처럼 조립한다 — 맨 문자열이면 이 파일 자체가 tagcheck 에 «새 태그» 로
잡힌다(prj3 debug_TECH 2026.09.19 계측 함정). 케이스마다 새 repo 를 파고, 단언 직전에 staged 건수를
함께 본다 — 0 이면 검사가 돌지 않은 «통과» 라 그 케이스는 무효다.

실행: python3 scripts/test_tagcheck_block_touched_issue584.py
"""
import os
import shutil
import stat
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CHK = os.path.join(HERE, 'precommit-tagcheck.py')
TX = os.path.expanduser('~/.claude/sh/issue-tx.py')
I = 'Issue'
PASS = FAIL = 0


def issue_md(sections):
    """sections: [(헤더, [(번호, [본문 줄…])…])…] → Issue.md 텍스트"""
    out = ['# Issue Management', '']
    for head, blocks in sections:
        out += [f'# {head}', '']
        for num, body in blocks:
            out += [f'## {I}{num}: 제목{num} (등록: 2026-09-29)', *body, '']
    return '\n'.join(out) + '\n'


def run(tmp, *args, env=None):
    e = {k: v for k, v in os.environ.items() if k not in ('ISSUE_TX_ISSUES', 'GIT_INDEX_FILE', 'SKIP_TAGCHECK')}
    e.update(env or {})
    return subprocess.run(args, cwd=tmp, capture_output=True, text=True, env=e)


def case(name, head_issue, idx_issue, files, want, stage_issue=True, env=None, archive=None, err_has=()):
    """HEAD 에 head_issue·빈 코드 파일을 커밋하고, idx_issue·files 를 스테이징한 뒤 검사기를 돌린다.

    archive: 워킹트리 `_doc_work/issue_OLD.md` 내용(검사기는 아카이브를 index 가 아니라 워킹트리에서 읽는다)
    err_has: stderr 에 모두 들어 있어야 하는 문자열(거부 안내 문구 검증)
    """
    global PASS, FAIL
    tmp = tempfile.mkdtemp(prefix='tagcheck-')
    try:
        run(tmp, 'git', 'init', '-q')
        run(tmp, 'git', 'config', 'user.email', 't@t')
        run(tmp, 'git', 'config', 'user.name', 't')
        with open(f'{tmp}/Issue.md', 'w', encoding='utf-8') as f:
            f.write(head_issue)
        for path in files:
            with open(f'{tmp}/{path}', 'w', encoding='utf-8') as f:
                f.write('# 빈 파일\n')
        run(tmp, 'git', 'add', 'Issue.md', *files)
        run(tmp, 'git', 'commit', '-q', '-m', 'base')
        if stage_issue:
            with open(f'{tmp}/Issue.md', 'w', encoding='utf-8') as f:
                f.write(idx_issue)
            run(tmp, 'git', 'add', 'Issue.md')
        for path, text in files.items():
            with open(f'{tmp}/{path}', 'w', encoding='utf-8') as f:
                f.write(text)
            run(tmp, 'git', 'add', path)
        if archive is not None:
            os.makedirs(f'{tmp}/_doc_work', exist_ok=True)
            with open(f'{tmp}/_doc_work/issue_OLD.md', 'w', encoding='utf-8') as f:
                f.write(archive)
        staged = [p for p in run(tmp, 'git', 'diff', '--cached', '--name-only').stdout.splitlines() if p]
        r = run(tmp, sys.executable, CHK, env=env)
        missing = [s for s in err_has if s not in r.stderr]
        ok = bool(staged) and r.returncode == want and not missing
        if ok:
            PASS += 1
            print(f'  ok   {name}')
        else:
            FAIL += 1
            print(f'  FAIL {name} (want rc={want} got rc={r.returncode} staged={len(staged)}'
                  + (f' stderr 누락={missing}' if missing else '') + ')')
            if r.stderr.strip():
                print('       ' + r.stderr.strip().replace('\n', '\n       '))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


print('[test_tagcheck_block_touched_issue584]')

B10 = ['* 목적: 열', '* 상세:', '    - 첫 줄']
B11 = ['* 목적: 열하나']
B12 = ['* 목적: 열둘']
BASE = issue_md([('🚧 진행중', [(11, B11)]), ('📕 중요', [(10, B10), (12, B12)])])
CODE10 = {'code.sh': f'# 주석 ({I}10)\necho hi\n'}

# ⓐ 인접 섹션 이동 — 블록 본문은 그대로, 📕 → 🚧 로만 옮긴다
case('ⓐ 인접 섹션 이동만 한 번호의 태그는 통과',
     BASE, issue_md([('🚧 진행중', [(11, B11), (10, B10)]), ('📕 중요', [(12, B12)])]),
     CODE10, 0)

# ⓑ 블록 안 문구만 고친다 — 추가 줄에 번호 문자열이 없다
case('ⓑ 블록 문구만 고친 번호의 태그는 통과',
     BASE, issue_md([('🚧 진행중', [(11, B11)]), ('📕 중요', [(10, B10 + ['    - **m4** 진행']), (12, B12)])]),
     CODE10, 0)

# 회귀 — 이번 커밋이 다루지 않은 번호는 여전히 거부
case('회귀: 다른 블록만 바뀐 커밋의 태그는 거부',
     BASE, issue_md([('🚧 진행중', [(11, B11 + ['    - 진행'])]), ('📕 중요', [(10, B10), (12, B12)])]),
     CODE10, 1)

case('회귀: 같은 섹션 안 순서만 바꾼 net-zero 는 다룬 것이 아님',
     BASE, issue_md([('🚧 진행중', [(11, B11)]), ('📕 중요', [(12, B12), (10, B10)])]),
     {'code.sh': f'# ({I}12)\n'}, 1)

case('회귀: 미등록 번호는 거부',
     BASE, issue_md([('🚧 진행중', [(11, B11)]), ('📕 중요', [(10, B10 + ['    - x']), (12, B12)])]),
     {'code.sh': f'# ({I}99)\n'}, 1)

case('회귀: Issue.md 를 스테이징하지 않은 커밋의 태그는 거부',
     BASE, BASE, CODE10, 1, stage_issue=False)

case('회귀: 추가 줄에 번호를 적은 종전 방식도 통과',
     BASE, issue_md([('🚧 진행중', [(11, B11)]), ('📕 중요', [(10, B10 + [f'    - {I}10 진행']), (12, B12)])]),
     CODE10, 0)

case('회귀: 바뀐 블록이 인용하는 번호(인과 인용)는 통과',
     BASE, issue_md([('🚧 진행중', [(11, B11)]), ('📕 중요', [(10, B10 + [f'    - 원인은 {I}12']), (12, B12)])]),
     {'code.sh': f'# ({I}12)\n'}, 0)

case('회귀: 새로 등록한 블록의 번호는 통과',
     BASE, issue_md([('🚧 진행중', [(11, B11)]), ('📕 중요', [(10, B10), (12, B12), (13, ['* 목적: 새'])])]),
     {'code.sh': f'# ({I}13)\n'}, 0)

# ⓒ 분업 커밋 — 작업자는 Issue.md 를 스테이징하지 않는다. `issue-tx commit --issues N` 의 선언을 인정한다
case('ⓒ Issue.md 무스테이징 + 선언(ISSUE_TX_ISSUES) 번호의 태그는 통과',
     BASE, BASE, CODE10, 0, stage_issue=False, env={'ISSUE_TX_ISSUES': '10'})

case('ⓒ 선언이 여럿(쉼표)이어도 각 번호를 인정',
     BASE, BASE, {'code.sh': f'# ({I}10) ({I}12)\n'}, 0, stage_issue=False, env={'ISSUE_TX_ISSUES': '11,10,12'})

CITE = issue_md([('🚧 진행중', [(11, B11 + [f'    - 원인은 {I}12'])]), ('📕 중요', [(10, B10), (12, B12)])])
case('ⓒ 선언한 블록이 인용하는 번호(인과 인용)도 통과',
     CITE, CITE, {'code.sh': f'# ({I}12)\n'}, 0, stage_issue=False, env={'ISSUE_TX_ISSUES': 'Issue11'})

case('ⓒ 회귀: 선언과 다른 번호의 태그는 거부',
     BASE, BASE, CODE10, 1, stage_issue=False, env={'ISSUE_TX_ISSUES': '11'})

case('ⓒ 회귀: 없는 번호 선언은 ① 로 거부',
     BASE, BASE, {'code.sh': f'# ({I}99)\n'}, 1, stage_issue=False, env={'ISSUE_TX_ISSUES': '99'})


# prj3#Issue949 — 서브 번호 `N_M` 이 `### IssueN_M:` 헤딩 없이 부모 `## IssueN:` 블록 본문 항목 `- N_M …` 으로만
#   존재하는 형태(부모 블록이 서브 목록을 품는다). ① 실존은 부모 블록(아카이브 포함) 안 항목까지 인정하고,
#   ② 동시성은 부모 번호가 블록 변경·선언으로 열려 있으면 인정한다. 항목이 다른 블록에 있거나 없으면 계속 거부.
SUB = '    - 10_3 서브 항목 (헤딩 없음)'
B10S = B10 + [SUB]
BASE_S = issue_md([('🚧 진행중', [(11, B11)]), ('📕 중요', [(10, B10S), (12, B12)])])
TOUCH10_S = issue_md([('🚧 진행중', [(11, B11)]), ('📕 중요', [(10, B10S + ['    - 진행']), (12, B12)])])

case('949 ① 부모 블록 본문 항목만 있는 N_M — 부모 블록이 같은 커밋에서 바뀌면 통과',
     BASE_S, TOUCH10_S, {'code.sh': f'# ({I}10_3)\n'}, 0)

case('949 회귀: 부모 블록에 항목이 없는 N_M 은 거부',
     BASE_S, TOUCH10_S, {'code.sh': f'# ({I}10_7)\n'}, 1)

case('949 회귀: 다른 이슈 블록에 적힌 `- N_M` 은 부모 항목이 아니다',
     issue_md([('🚧 진행중', [(11, B11)]), ('📕 중요', [(10, B10), (12, B12 + ['    - 10_7 엉뚱한 자리'])])]),
     issue_md([('🚧 진행중', [(11, B11)]), ('📕 중요', [(10, B10 + ['    - 진행']), (12, B12 + ['    - 10_7 엉뚱한 자리'])])]),
     {'code.sh': f'# ({I}10_7)\n'}, 1)

case('949 회귀: 접두만 같은 항목(- 10_10)은 10_1 의 실존 근거가 아니다',
     issue_md([('📕 중요', [(10, B10 + ['    - 10_10 열번째'])])]),
     issue_md([('📕 중요', [(10, B10 + ['    - 10_10 열번째', '    - 진행'])])]),
     {'code.sh': f'# ({I}10_1)\n'}, 1)

case('949 ③ 부모 선언(ISSUE_TX_ISSUES=10) 이면 Issue.md 무스테이징이어도 본문 항목 N_M 통과',
     BASE_S, BASE_S, {'code.sh': f'# ({I}10_3)\n'}, 0, stage_issue=False, env={'ISSUE_TX_ISSUES': '10'})

case('949 회귀: 부모 미변경·미선언이면 본문 항목 N_M 도 ② 로 거부',
     BASE_S, BASE_S, {'code.sh': f'# ({I}10_3)\n'}, 1, stage_issue=False)

case('949 회귀: 다른 번호 선언은 본문 항목 N_M 을 열지 않는다',
     BASE_S, BASE_S, {'code.sh': f'# ({I}10_3)\n'}, 1, stage_issue=False, env={'ISSUE_TX_ISSUES': '11'})

case('949 회귀: 인과 인용으로 열린 부모 번호는 서브 항목까지 열지 않는다(부모는 블록 변경·선언만)',
     BASE_S,
     issue_md([('🚧 진행중', [(11, B11 + [f'    - 원인은 {I}10'])]), ('📕 중요', [(10, B10S), (12, B12)])]),
     {'code.sh': f'# ({I}10_3)\n'}, 1)

SUBH = ['', f'### {I}10_4: 서브 제목 (등록: 2026-10-05)', '* 목적: 서브']
case('949 회귀: ### 서브 헤딩은 기존대로 — 부모 블록만 바뀌면 거부',
     issue_md([('📕 중요', [(10, B10 + SUBH)])]),
     issue_md([('📕 중요', [(10, B10 + ['    - 진행'] + SUBH)])]),
     {'code.sh': f'# ({I}10_4)\n'}, 1)

case('949 회귀: ### 서브 헤딩 블록을 고치면 통과(기존 경로)',
     issue_md([('📕 중요', [(10, B10 + SUBH)])]),
     issue_md([('📕 중요', [(10, B10 + SUBH + ['    - 서브 진행'])])]),
     {'code.sh': f'# ({I}10_4)\n'}, 0)

ARCH = issue_md([('✅ 완료', [(20, ['* 목적: 옛', '* 상세:', '    - 20_2 옛 서브 항목'])])])
case('949 ⑤ 아카이브 부모 블록의 본문 항목도 실존 인정(아카이브는 ② 면제 — prj3#Issue649 규약)',
     BASE, BASE, {'code.sh': f'# ({I}20_2)\n'}, 0, stage_issue=False, archive=ARCH)

case('949 회귀: 아카이브 부모 블록에 없는 서브 번호는 거부',
     BASE, BASE, {'code.sh': f'# ({I}20_5)\n'}, 1, stage_issue=False, archive=ARCH)

case('949 회귀: `# ` 섹션 헤더 뒤 항목은 직전 이슈 블록 소속이 아니다',
     issue_md([('📕 중요', [(10, B10)])]) + '# 📜 참고\n\n    - 10_7 참고 항목\n',
     issue_md([('📕 중요', [(10, B10 + ['    - 진행'])])]) + '# 📜 참고\n\n    - 10_7 참고 항목\n',
     {'code.sh': f'# ({I}10_7)\n'}, 1)

case('949 회귀: live 본문 항목은 아카이브에도 있어도 ② 를 건너뛰지 않는다(아카이브 면제보다 먼저)',
     BASE_S, BASE_S, {'code.sh': f'# ({I}10_3)\n'}, 1, stage_issue=False,
     archive=issue_md([('✅ 완료', [(10, ['* 목적: 옛', '    - 10_3 옛 서브 항목'])])]))

case('949 ④ 거부 안내에 부모 번호·prjX# 접두·### 서브 헤딩 등록 안내가 있다',
     BASE_S, TOUCH10_S, {'code.sh': f'# ({I}10_7)\n'}, 1,
     err_has=('부모 번호', 'prjX#', f'### {I}N_M:'))


def e2e(name, cmd, want):
    """pre-commit 에 검사기를 배선한 격리 repo 에서 실제 커밋 경로(issue-tx commit / 맨 git commit)를 돌린다."""
    global PASS, FAIL
    tmp = tempfile.mkdtemp(prefix='tagcheck-e2e-')
    try:
        run(tmp, 'git', 'init', '-q')
        run(tmp, 'git', 'config', 'user.email', 't@t')
        run(tmp, 'git', 'config', 'user.name', 't')
        with open(f'{tmp}/Issue.md', 'w', encoding='utf-8') as f:
            f.write(BASE)
        with open(f'{tmp}/code.sh', 'w', encoding='utf-8') as f:
            f.write('# 빈 파일\n')
        run(tmp, 'git', 'add', 'Issue.md', 'code.sh')
        run(tmp, 'git', 'commit', '-q', '-m', 'base')
        hook = f'{tmp}/.git/hooks/pre-commit'
        with open(hook, 'w', encoding='utf-8') as f:
            f.write(f'#!/bin/sh\nexec {sys.executable} {CHK}\n')
        os.chmod(hook, os.stat(hook).st_mode | stat.S_IEXEC)
        with open(f'{tmp}/code.sh', 'w', encoding='utf-8') as f:
            f.write(CODE10['code.sh'])
        pre = run(tmp, 'git', 'rev-parse', 'HEAD').stdout.strip()
        r = run(tmp, *cmd)
        post = run(tmp, 'git', 'rev-parse', 'HEAD').stdout.strip()
        got = 0 if post != pre else 1
        if got == want:
            PASS += 1
            print(f'  ok   {name}')
        else:
            FAIL += 1
            print(f'  FAIL {name} (want {"커밋" if want == 0 else "거부"} got rc={r.returncode} HEAD 이동={post != pre})')
            out = (r.stdout + r.stderr).strip()
            if out:
                print('       ' + out.replace('\n', '\n       '))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


e2e('ⓒ e2e: issue-tx commit --issues 10 (Issue.md 무변경) 은 커밋된다',
    [sys.executable, TX, '--file', 'Issue.md', 'commit', '--issues', '10', '-m', 'work', 'code.sh'], 0)
e2e('ⓒ e2e: 선언 없는 맨 git commit 은 여전히 거부',
    ['sh', '-c', 'git add code.sh && git commit -q -m work'], 1)
e2e('ⓒ e2e: 다른 번호를 선언한 issue-tx commit 은 거부',
    [sys.executable, TX, '--file', 'Issue.md', 'commit', '--issues', '11', '-m', 'work', 'code.sh'], 1)

print(f'\n결과: PASS {PASS} / FAIL {FAIL}')
sys.exit(1 if FAIL else 0)
