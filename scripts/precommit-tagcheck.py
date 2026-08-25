#!/usr/bin/env python3
"""precommit-tagcheck.py — staged 변경의 새 `Issue{N}` 태그 정합 검사 (Issue325)

pre-commit hook 본체. 설치는 `scripts/install-precommit-tagcheck.sh`.

배경(Issue324 사고): digest 참조 필터가 코드 주석의 `(Issue{N})` 을 공개 스위치로
승격시켰다. 태그는 자유 텍스트이고 검증 지점이 없었으므로, 번호 하나를 잘못 적은 것만으로
사설 이슈가 공개 digest 에 실렸다. 여기서 두 조건을 기계 검증한다.

  ① 실존   : `Issue.md` 에 `## Issue{N}:` 헤딩이 존재
  ② 동시성 : 같은 커밋의 staged `Issue.md` 변경분에도 그 번호가 등장
             (= 이번 작업이 실제로 다룬 이슈)

"새 태그" 판정은 파일별 (staged 내용의 번호 집합) − (HEAD 내용의 번호 집합) 이다.
줄 이동·리포맷으로 기존 번호가 added line 에 다시 등장하는 경우를 오탐하지 않기 위함.

exit: 0=통과(또는 검사 대상 없음), 1=위반(커밋 거부)
"""
import re
import subprocess
import sys

# ⚠️ **cross-prj 접두는 로컬 이슈가 아니다** (prj3#Issue436 배포 라운드에서 실발생).
# `prj3#Issue436`·`prj5#Issue70` 은 **타 prj 이슈 참조**라 이 repo 의 Issue.md 에 있을 리 없다.
# 접두 없이 매칭하면 정식 표기(SCAR cross-project reference format)를 쓸 때마다 커밋이 막히고,
# 그때마다 SKIP_TAGCHECK 로 우회하게 되어 검사 자체가 무력해진다 — L37 이 예고한 그 구멍이다.
# `(?<!#)` 로 `#` 뒤를 배제하고, prj 접두 토큰도 함께 배제한다.
TAG_RE = re.compile(r'(?<![#\w])(?<!prj)Issue(\d+(?:_\d+)+|\d+)\b')
HEADING_RE = re.compile(r'^## Issue(\d+(?:_\d+)+|\d+)\s*:', re.M)

# 이력 서술 문맥 — 과거 이슈 번호를 자유롭게 인용하는 것이 정상이므로 검사 제외.
EXCLUDE_EXACT = {'Issue.md', 'Issue_public.md', 'Issue_map.htm'}
# `plugins/` 는 위와 이유가 다르다 (Issue364). 번들(`plugins/fpm-core`)은 **동기 산출물**이라
# 대부분의 파일에 원본이 따로 있고(prj3 `~/.claude/{hooks,commands,agents,skills}` · prj1 자신의
# `services/hub`·`data/locales`), 태그를 실제로 저작하는 곳은 그 원본이다. 원본은 이 검사를
# 그대로 받는다. 번들 사본에서 차단해 봐야 **고칠 수 있는 곳이 여기가 아니므로** 조치로
# 이어지지 않고, 동기 커밋만 구조적으로 막힌다(Issue362 에서 SKIP_TAGCHECK 3회 실발생).
#
# ⚠️ 이 제외로 닫히지 **않는** 구멍 2개 — 둘 다 Issue365 로 분리:
#   1. 번들 태그는 여전히 digest 참조 코퍼스(`fpm-issue-digest.sh` git grep)에 남는다. 번들이
#      들고 온 prj3 번호가 prj1 번호와 충돌하면 엉뚱한 prj1 이슈가 공개 digest 에 실린다.
#      뿌리는 bare `IssueN` 이 prj 소속을 표현하지 못한다는 것이라, 경로 제외로는 못 고친다.
#   2. 라이브 대응이 없는 **번들 전용 파일**(`vscode-ext/`·`CLAUDE.md`·`hooks/fpm-browser-open.sh`
#      등 12개)은 prj1 에서 직접 저작되는데 `fpm-bundle-sync.sh --check` 도 대상이 아니다
#      (`sync_file()` 이 `[ -f "$src" ]` 로 조기 반환). 이들은 이제 어느 검사도 받지 않는다.
EXCLUDE_PREFIX = ('_doc_work/', '_doc_arch/', '_doc_base/', 'plugins/')


def git(*args, allow_fail=False):
    r = subprocess.run(['git', *args], capture_output=True)
    if r.returncode != 0 and not allow_fail:
        return None
    return r.stdout.decode('utf-8', 'replace')


def blob(rev, path):
    """rev:path 내용. 없거나 바이너리면 None."""
    r = subprocess.run(['git', 'show', f'{rev}:{path}'], capture_output=True)
    if r.returncode != 0:
        return None
    if b'\0' in r.stdout[:8000]:
        return None
    return r.stdout.decode('utf-8', 'replace')


def is_checked(path):
    if path in EXCLUDE_EXACT:
        return False
    return not path.startswith(EXCLUDE_PREFIX)


def main():
    staged = git('diff', '--cached', '--name-only', '--diff-filter=ACMR')
    if staged is None:
        return 0  # git 상태 이상 — 게이트가 커밋을 막지 않는다
    paths = [p for p in staged.splitlines() if p.strip()]
    if not paths:
        return 0

    # ── ① 실존 판정 소스: index 의 Issue.md (staged 면 그 내용, 아니면 HEAD 와 동일) ──
    #    index 에 없으면(미추적) 워킹트리 파일로 대체.
    issue_src = blob('', 'Issue.md')
    if issue_src is None:
        try:
            root = (git('rev-parse', '--show-toplevel') or '').strip()
            with open(f'{root}/Issue.md', encoding='utf-8') as f:
                issue_src = f.read()
        except OSError:
            print('⚠️ [tagcheck] Issue.md 를 읽지 못함 — 검사 skip', file=sys.stderr)
            return 0
    existing = set(HEADING_RE.findall(issue_src))

    # ── ② 동시성 판정 소스: staged Issue.md diff 의 추가 줄 ──
    touched = set()
    if 'Issue.md' in paths:
        d = git('diff', '--cached', '-U0', '--', 'Issue.md') or ''
        for line in d.splitlines():
            if line.startswith('+') and not line.startswith('+++'):
                touched.update(TAG_RE.findall(line))

    # 인과 인용 허용: 이번 커밋이 다룬 이슈의 **본문이 언급하는 번호**도 정당한 태그다.
    # (ex: Issue325 를 고치며 원인이 된 Issue324 를 코드 주석에 인용) 이슈 본문에 근거가
    # 적혀 있으므로 추적 가능하다. Issue324 사고 유형(작업 중인 이슈와 무관한 번호를
    # 복붙)은 그 번호가 어느 블록에도 없으므로 여전히 걸린다.
    if touched:
        blocks = {}
        cur = None
        for line in issue_src.splitlines():
            m = HEADING_RE.match(line + '\n')
            if m:
                cur = m.group(1)
                blocks[cur] = []
            elif cur:
                blocks[cur].append(line)
        for num in list(touched):
            for line in blocks.get(num, []):
                touched.update(TAG_RE.findall(line))

    # ── 파일별 신규 태그 수집 ──
    violations = []  # (path, lineno, num, reason)
    for path in paths:
        if not is_checked(path):
            continue
        new_text = blob('', path)      # index(staged) 내용
        if new_text is None:           # 바이너리·읽기 실패 → 검사 대상 아님
            continue
        old_text = blob('HEAD', path) or ''   # 신규 파일이면 HEAD 없음 → 전부 신규 태그
        new_nums = set(TAG_RE.findall(new_text))
        old_nums = set(TAG_RE.findall(old_text))
        fresh = new_nums - old_nums
        if not fresh:
            continue
        for lineno, line in enumerate(new_text.splitlines(), 1):
            for num in TAG_RE.findall(line):
                if num not in fresh:
                    continue
                if num not in existing:
                    violations.append((path, lineno, num,
                                       f'Issue.md 에 `## Issue{num}:` 헤딩이 없음 (오타·미등록 번호)'))
                elif num not in touched:
                    violations.append((path, lineno, num,
                                       'Issue.md 변경분에 이 번호가 없음 (이번 커밋이 다루는 이슈가 아님)'))

    if not violations:
        return 0

    print('❌ [tagcheck] Issue 태그 정합 위반 — 커밋 거부 (Issue325)', file=sys.stderr)
    seen = set()
    for path, lineno, num, reason in violations:
        key = (path, num)
        if key in seen:
            continue
        seen.add(key)
        print(f'   {path}:{lineno}  Issue{num} — {reason}', file=sys.stderr)
    print('   해소: (a) 번호를 실제 작업 이슈로 교정  또는', file=sys.stderr)
    print('        (b) 해당 이슈를 Issue.md 에 등록/갱신해 같은 커밋에 포함  또는', file=sys.stderr)
    print('        (c) 의도적 예외면 SKIP_TAGCHECK=1 git commit …', file=sys.stderr)
    print('   왜: 코드 주석의 (IssueN) 은 공개 digest 반출 스위치다 — 오타 1건이 사설 이슈를 공개한다',
          file=sys.stderr)
    return 1


if __name__ == '__main__':
    sys.exit(main())
