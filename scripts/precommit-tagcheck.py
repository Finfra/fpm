#!/usr/bin/env python3
"""precommit-tagcheck.py — staged 변경의 새 `Issue{N}` 태그 정합 검사 (Issue325)

pre-commit hook 본체. 설치는 `scripts/install-precommit-tagcheck.sh`.

배경(Issue324 사고): digest 참조 필터가 코드 주석의 `(Issue{N})` 을 공개 스위치로
승격시켰다. 태그는 자유 텍스트이고 검증 지점이 없었으므로, 번호 하나를 잘못 적은 것만으로
사설 이슈가 공개 digest 에 실렸다. 여기서 두 조건을 기계 검증한다.

  ① 실존   : `Issue.md` 에 `## Issue{N}:` 헤딩이 존재
             (아카이브 `_doc_work/issue_OLD.md` 의 헤딩도 «실존했던 번호» 로 인정 — prj3#Issue649)
             서브 번호 `N_M` 은 `### IssueN_M:` 헤딩 또는 부모 `## IssueN:` 블록 본문 항목 `- N_M …`
             (아카이브 포함 — prj3#Issue949)
  ② 동시성 : 같은 커밋의 staged `Issue.md` 에서 그 번호의 블록(소속 섹션·본문)이 HEAD 와 다름
             (= 이번 작업이 실제로 다룬 이슈 — Issue584 에서 «diff 추가 줄에 번호 등장» 을 대체)
             또는 `issue-tx commit --issues N` 이 넘긴 선언 `ISSUE_TX_ISSUES` 에 그 번호가 있음
             (prj3#Issue793 ⓒ 와 같은 판정 — 2원 구조)
             본문 항목으로만 있는 `N_M` 은 부모 번호의 블록 변경·선언으로도 인정 (prj3#Issue949)

"새 태그" 판정은 파일별 (staged 내용의 번호 집합) − (HEAD 내용의 번호 집합) 이다.
줄 이동·리포맷으로 기존 번호가 added line 에 다시 등장하는 경우를 오탐하지 않기 위함.

exit: 0=통과(또는 검사 대상 없음), 1=위반(커밋 거부)
"""
import os
import re
import subprocess
import sys

# ⚠️ **cross-prj 접두는 로컬 이슈가 아니다** (prj3#Issue436 배포 라운드에서 실발생).
# `prj3#Issue436`·`prj5#Issue70` 은 **타 prj 이슈 참조**라 이 repo 의 Issue.md 에 있을 리 없다.
# 접두 없이 매칭하면 정식 표기(SCAR cross-project reference format)를 쓸 때마다 커밋이 막히고,
# 그때마다 SKIP_TAGCHECK 로 우회하게 되어 검사 자체가 무력해진다 — L37 이 예고한 그 구멍이다.
# `(?<!#)` 로 `#` 뒤를 배제하고, prj 접두 토큰도 함께 배제한다.
TAG_RE = re.compile(r'(?<![#\w])(?<!prj)Issue(\d+(?:_\d+)+|\d+)\b')
# Issue474: 서브이슈 헤딩은 `### IssueN_M:` 형태다(issue-g 규칙6·7 — 부모 하위 배치).
#   `##` 만 보면 TAG_RE 가 인식한 서브이슈 태그의 대응 헤딩을 못 찾아 정상 등록분도 거부된다.
HEADING_RE = re.compile(r'^#{2,3} Issue(\d+(?:_\d+)+|\d+)\s*:', re.M)
# prj3#Issue949: 서브 번호는 헤딩 없이 부모 블록의 **본문 항목**(`    - 751_10 …`)으로만 존재하기도 한다.
#   헤딩만 보면 그 인용이 «미등록 번호» 로 거부돼 부모 번호로 교정하게 되는데, 그건 정보 손실이다.
#   항목 번호가 **그 블록 헤딩 번호의 하위**(`N_…`)일 때만 인정한다 — 다른 블록에 적힌 `- N_M` 은 근거가 아니다.
ITEM_RE = re.compile(r'^\s*- (\d+(?:_\d+)+)\b')

# prj3#Issue649: 실존 판정에 **아카이브**도 넣는다. 종결 이슈는 `Issue.md` 가 길어지면
# `_doc_work/issue_OLD.md` 로 이관되는데, 글로벌 SCAR 헤더의 표준 가드 상용구가 인용하는
# `Issue46` 이 바로 그렇게 이관된 번호다. 아카이브를 안 보면 그 상용구를 그대로 쓴 **신규 파일이
# 100% 거부**된다 — 기존 파일은 헤더를 안 건드리면 조용하지만 신규 파일은 전 라인이 "새 태그"다.
# 파일명이 repo 마다 갈려 있으므로(prj1 `Issue_OLD.md` · prj3 `issue_OLD.md`) **대소문자 무시**로
# 찾는다. index 가 아니라 **워킹트리**를 읽는다 — 아카이브는 이 커밋이 다루는 대상이 아니다.
ARCHIVE_DIR = '_doc_work'
ARCHIVE_NAME = 'issue_old.md'   # 소문자 비교용
_archive_cache = None


def archived_nums(root):
    """아카이브 이슈 파일의 헤딩 번호 + 부모 블록 본문 항목 서브 번호 집합 (없으면 빈 집합).
    최초 호출 때 1회만 읽는다."""
    global _archive_cache
    if _archive_cache is not None:
        return _archive_cache
    _archive_cache = set()
    try:
        names = os.listdir(f'{root}/{ARCHIVE_DIR}')
    except OSError:
        return _archive_cache
    for name in names:
        if name.lower() != ARCHIVE_NAME:
            continue
        try:
            with open(f'{root}/{ARCHIVE_DIR}/{name}', encoding='utf-8') as f:
                text = f.read()
        except OSError:
            continue
        _archive_cache.update(HEADING_RE.findall(text))
        _archive_cache.update(listed_subs(text))   # prj3#Issue949
    return _archive_cache


def parent_nums(num):
    """`N_M_K` → ['N_M', 'N'] — 가까운 조상부터. 서브가 아니면 빈 목록."""
    parts = num.split('_')
    return ['_'.join(parts[:i]) for i in range(len(parts) - 1, 0, -1)]


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
EXCLUDE_PREFIX = ('_doc_work/', '_doc_arch/', '_doc_base/', 'plugins/', 'projects/-', 'data/route/')
# `projects/-`·`data/route/` (prj3#Issue935 · 2원 구조 동기): prj3 의 Claude 프로젝트 memory 와 `/route` 학습 이력은
#    타 prj·과거 번호 인용이 정상인 이력 기록이다. prj1 에는 두 경로가 없어 무해하고, `projects/{번호}`(경로 SSOT)는
#    접두 `-` 가 없으므로 계속 검사한다.

# Issue566: `plugins/` 와 **같은 이유**의 두 번째 동기 목적지 — `mcp/<유닛>/`(prj3 `~/.claude/mcp/<유닛>`
#   사본, `scripts/fpm-bundle-sync.sh` `sync_mcp_unit`). 제외가 번들에만 걸려 있어 prj3 사본을 싣는
#   동기 커밋이 prj3 번호로 구조적으로 막혔다(2026-09-28 Issue566 커밋 실발생). 유닛 목록은 여기
#   적지 않고 동기 스크립트의 선언에서 읽는다 — 두 곳에 두면 유닛이 늘 때 또 갈라진다.
#   prj1 이 직접 저작하는 `mcp/server.py`(fpm MCP)는 유닛 디렉토리 밖이라 계속 검사받는다.
SYNC_SCRIPT = os.path.join('scripts', 'fpm-bundle-sync.sh')
SYNC_MCP_RE = re.compile(r'^sync_mcp_unit\s+([A-Za-z0-9_.-]+)\s*$', re.M)
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_sync_prefix_cache = None


def sync_mcp_units(root):
    """동기 스크립트가 선언한 mcp 유닛 이름 목록 (스크립트 부재·판독 실패면 빈 목록)."""
    try:
        with open(os.path.join(root, SYNC_SCRIPT), encoding='utf-8') as f:
            return SYNC_MCP_RE.findall(f.read())
    except OSError:
        return []


# Issue591: 세 번째 동기 목적지 — flat_file 배포 사본(`sh/scar-flatfile-sync.sh` 가 prj3 룰·커맨드를
#   복사). 같은 이유로 제외한다. 경로는 scar-manifest.yml `payloads.flat_file.src_rel_repo` 에서 읽는다
#   (동기 스크립트도 같은 키를 읽는다 — 목록을 여기 두면 갈라진다).
SCAR_MANIFEST = os.path.join('data', 'scar-manifest.yml')


def flatfile_prefix(root):
    """flat_file 사본 경로 접두(끝 `/` 포함). 매니페스트 부재·판독 실패면 None."""
    try:
        with open(os.path.join(root, SCAR_MANIFEST), encoding='utf-8') as f:
            lines = f.read().splitlines()
    except OSError:
        return None
    in_flat = False
    for l in lines:
        if re.match(r'^  flat_file:\s*$', l):
            in_flat = True
        elif in_flat and re.match(r'^  \S', l):
            break
        elif in_flat:
            m = re.match(r'^    src_rel_repo:\s*([^\s#]+)', l)
            if m:
                return m.group(1).strip('"\'').rstrip('/') + '/'
    return None


def sync_prefixes():
    global _sync_prefix_cache
    if _sync_prefix_cache is None:
        flat = flatfile_prefix(REPO_ROOT)
        _sync_prefix_cache = tuple(f'mcp/{u}/' for u in sync_mcp_units(REPO_ROOT)) + ((flat,) if flat else ())
    return _sync_prefix_cache


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


SECTION_RE = re.compile(r'^# ')


def issue_blocks(text):
    """Issue.md → {번호: (소속 `# ` 섹션 헤더, 헤딩 포함 블록 본문)}.

    블록 끝은 다음 이슈 헤딩 또는 다음 `# ` 섹션 헤더(issue-g 규칙10). 끝의 빈 줄은 떼어
    블록 사이 공백 차이를 변경으로 치지 않는다. 섹션을 함께 담는 것은 본문이 그대로인 섹션 이동(ⓐ)도
    «바뀐 블록» 으로 보기 위함이다.
    """
    blocks = {}
    section = ''
    cur = None
    for line in text.splitlines():
        m = HEADING_RE.match(line + '\n')
        if m:
            cur = m.group(1)
            blocks[cur] = [section, [line]]
        elif SECTION_RE.match(line):
            section = line.strip()
            cur = None
        elif cur:
            blocks[cur][1].append(line)
    return {n: (s, '\n'.join(body).rstrip()) for n, (s, body) in blocks.items()}


def listed_subs(text):
    """부모 블록 본문 항목 `- N_M …` 으로 존재하는 서브 번호 집합 (prj3#Issue949).

    블록 경계는 `issue_blocks` 와 같다(다음 이슈 헤딩 또는 `# ` 섹션). 항목 번호가 그 블록 헤딩
    번호의 하위(손자 이하 포함)일 때만 담는다 — `## IssueN:` 블록의 `- N_M`·`- N_M_K` ·
    `### IssueN_M:` 블록의 `- N_M_K`. 코드 펜스는 구분하지 않는다(`HEADING_RE` 와 같은 한계).
    """
    out = set()
    cur = None
    for line in text.splitlines():
        m = HEADING_RE.match(line + '\n')
        if m:
            cur = m.group(1)
        elif SECTION_RE.match(line):
            cur = None
        elif cur:
            m = ITEM_RE.match(line)
            if m and m.group(1).startswith(cur + '_'):
                out.add(m.group(1))
    return out


def is_checked(path):
    if path in EXCLUDE_EXACT:
        return False
    return not path.startswith(EXCLUDE_PREFIX + sync_prefixes())


def main():
    staged = git('diff', '--cached', '--name-only', '--diff-filter=ACMR')
    if staged is None:
        return 0  # git 상태 이상 — 게이트가 커밋을 막지 않는다
    paths = [p for p in staged.splitlines() if p.strip()]
    if not paths:
        return 0

    # ── ① 실존 판정 소스: index 의 Issue.md (staged 면 그 내용, 아니면 HEAD 와 동일) ──
    #    index 에 없으면(미추적) 워킹트리 파일로 대체.
    root = (git('rev-parse', '--show-toplevel') or '').strip()
    issue_src = blob('', 'Issue.md')
    if issue_src is None:
        try:
            with open(f'{root}/Issue.md', encoding='utf-8') as f:
                issue_src = f.read()
        except OSError:
            print('⚠️ [tagcheck] Issue.md 를 읽지 못함 — 검사 skip', file=sys.stderr)
            return 0
    existing = set(HEADING_RE.findall(issue_src))
    listed = listed_subs(issue_src) - existing   # 헤딩 없이 부모 본문 항목으로만 있는 서브 (prj3#Issue949)

    # ── ② 동시성 판정: staged Issue.md 에서 그 번호의 **블록이 바뀌었는가** (Issue584 · prj3#Issue793 짝) ──
    #    종전 «diff 추가 줄에 번호 문자열이 있는가» 는 세 군데서 틀렸다 — ⓐ 인접 섹션 이동은 diff 가
    #    섹션 헤더 이동으로 정렬돼 `## IssueN` 줄이 추가 줄에 안 잡히고 ⓑ 블록 안 문구만 고치면 추가 줄에
    #    번호가 없으며, 반대로 같은 섹션 안 순서만 바꾼 net-zero 는 헤더 줄이 다시 나타나 통과했다.
    #    diff 모양이 아니라 HEAD·index 두 벌의 블록(소속 섹션 + 본문)을 직접 비교한다.
    touched = set()
    idx_blocks = issue_blocks(issue_src)
    if 'Issue.md' in paths:
        head_blocks = issue_blocks(blob('HEAD', 'Issue.md') or '')
        touched = {n for n in idx_blocks if idx_blocks[n] != head_blocks.get(n)}

    # ⓒ 선언 인정 (prj3#Issue793 결정): 조정자·작업자 분업에서 작업자 커밋은 Issue.md 를 아예 스테이징하지
    #    않아 «블록 변경» 으로는 다룬 이슈를 알 수 없다. `issue-tx commit --issues N`(prj3 공유본)이 넘기는
    #    선언(`ISSUE_TX_ISSUES`)을 이번 커밋이 다룬 이슈로 인정한다. ① 실존 검사는 그대로라 없는 번호 선언은
    #    걸린다. «진행중 섹션 인정» 은 오타 여과 폭이 넓어 기각 — 선언은 커밋마다 명시한 번호만 연다.
    for tok in re.split(r'[,\s]+', os.environ.get('ISSUE_TX_ISSUES', '').strip()):
        m = re.fullmatch(r'(?:Issue)?(\d+(?:_\d+)*)', tok)
        if m:
            touched.add(m.group(1))

    # prj3#Issue949: 본문 항목 서브는 자기 블록이 없어 그 변경은 부모 블록 변경으로 나타난다 — 부모 번호가
    #   **블록 변경·선언** 으로 열려 있으면 인정한다. 아래 인과 인용으로 늘어난 번호는 넣지 않는다
    #   (부모 번호를 인용만 한 블록이 그 서브 목록 전체를 여는 전이 확장을 막는다).
    direct = set(touched)

    # 인과 인용 허용: 이번 커밋이 다룬 이슈의 **본문이 언급하는 번호**도 정당한 태그다.
    # (ex: Issue325 를 고치며 원인이 된 Issue324 를 코드 주석에 인용) 이슈 본문에 근거가
    # 적혀 있으므로 추적 가능하다. Issue324 사고 유형(작업 중인 이슈와 무관한 번호를
    # 복붙)은 그 번호가 어느 블록에도 없으므로 여전히 걸린다.
    if touched:
        for num in list(touched):
            if num in idx_blocks:      # 선언 번호는 블록이 없을 수 있다(없는 번호 → ① 이 거부)
                touched.update(TAG_RE.findall(idx_blocks[num][1]))

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
                    # prj3#Issue649: 아카이브로 이관된 번호는 «실존했던» 번호다. 동시성(②)은 요구하지
                    # 않는다 — 종결·이관된 이슈가 `Issue.md` 로 되돌아올 일이 없으므로, 요구하면
                    # 그 번호를 인용한 신규 파일은 영구히 커밋할 수 없다.
                    # prj3#Issue949: 부모 블록 본문 항목 — ② 는 자기 또는 부모 번호. 아카이브 면제보다
                    #   먼저 본다(live 항목은 live 이슈라 ② 를 건너뛰면 안 된다)
                    if num in listed:
                        if num not in touched and not direct.intersection(parent_nums(num)):
                            violations.append((path, lineno, num,
                                               'Issue.md 변경분·선언에 이 번호도 부모 번호도 없음 '
                                               '(이번 커밋이 다루는 이슈가 아님)'))
                        continue
                    if num in archived_nums(root):
                        continue
                    if parent_nums(num):
                        reason = (f'Issue.md 에 `### Issue{num}:` 헤딩도, 부모 블록 본문 항목 '
                                  f'`- {num}` 도 없음 (오타·미등록 번호)')
                    else:
                        reason = f'Issue.md 에 `## Issue{num}:` 헤딩이 없음 (오타·미등록 번호)'
                    violations.append((path, lineno, num, reason))
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
    # prj3#Issue949: 서브 번호·타 prj 참조의 고칠 표기를 안내한다 — 안내가 없으면 부모 번호로 뭉개거나
    #   SKIP_TAGCHECK 로 우회하게 된다.
    print('   해소: (a) 번호를 실제 작업 이슈로 교정 — 서브 번호(IssueN_M)면 부모 번호 IssueN 으로  또는', file=sys.stderr)
    print('        (b) 해당 이슈를 Issue.md 에 등록/갱신해 같은 커밋에 포함(issue-tx commit --issues N 선언도 인정 — 등록된 번호에 한해)'
          ' — 서브 이슈면 `### IssueN_M:` 헤딩으로 등록하거나 부모 블록 본문에 `- N_M` 항목  또는', file=sys.stderr)
    print('        (c) 타 prj 이슈 참조면 `prjX#IssueN` 접두 — cross-prj 참조는 이 검사 대상이 아님  또는',
          file=sys.stderr)
    print('        (d) 의도적 예외면 SKIP_TAGCHECK=1 git commit …', file=sys.stderr)
    print('   왜: 코드 주석의 (IssueN) 은 공개 digest 반출 스위치다 — 오타 1건이 사설 이슈를 공개한다',
          file=sys.stderr)
    return 1


if __name__ == '__main__':
    sys.exit(main())
