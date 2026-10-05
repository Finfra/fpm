"""identity-collect-contract — sh/fpm-identity-collect 인수 계약 (prj6#Issue21 착수 조건 7 · Issue589).

  python3 tdd/cases/test_identity_collect.py
  ① 알 수 없는 플래그는 파일을 쓰기 전에 rc 2 로 거부 (Identity.md 미생성)
  ② --json 은 파일을 쓰지 않고 stdout 에 {"<id>": {필드: 값}} JSON 1개 — handles·now pass-through
  ③ 쓰기 모드 Identity.md 표에 now 열 (값 없으면 빈 칸)
  ④ --check 는 블록 리스트(`- item`) frontmatter 를 «무시» 1줄로 알린다
"""
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
COLLECT = os.path.join(ROOT, 'sh', 'fpm-identity-collect')
fails = []


def check(ok, msg):
    print(('  ok  ' if ok else '  FAIL ') + msg)
    if not ok:
        fails.append(msg)


def run(args, base):
    env = dict(os.environ, FPM_BASE=base)
    p = subprocess.run([sys.executable, COLLECT, *args], capture_output=True, text=True, env=env)
    return p.returncode, p.stdout, p.stderr


def sandbox():
    """Projects.md·CLAUDE.md 를 가진 임시 FPM_BASE — 실 Identity.md 를 건드리지 않는다."""
    base = tempfile.mkdtemp(prefix='idc-')
    os.makedirs(os.path.join(base, 'sh'))
    os.symlink(os.path.join(ROOT, 'sh', 'fpm-projects-sync'), os.path.join(base, 'sh', 'fpm-projects-sync'))
    proj = os.path.join(base, 'p1')
    os.makedirs(proj)
    with open(os.path.join(proj, 'CLAUDE.md'), 'w', encoding='utf-8') as f:
        f.write('---\nidentity: 테스트\nnot: 아님\ngoal_parent: G\nlifetime: perpetual\n'
                'outcome: 성과\nstatus: active\nhandles: [가, 나]\nnow: [Issue1 진행]\n---\n')
    proj2 = os.path.join(base, 'p2')
    os.makedirs(proj2)
    with open(os.path.join(proj2, 'CLAUDE.md'), 'w', encoding='utf-8') as f:
        f.write('---\nidentity: 둘째\nnot: 아님\ngoal_parent: G\nlifetime: perpetual\n'
                'outcome: 성과\nstatus: active\nhandles:\n  - 가\n  - 나\n---\n')
    with open(os.path.join(base, 'Projects.md'), 'w', encoding='utf-8') as f:
        f.write('# Projects\n\n| id | 프로젝트명 | 한국어명칭 | Dmn | 경로 | 설명 | tdd | license | 이모지 | color |\n'
                '| :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- |\n'
                f'| 1 | one | 하나 | g | `{proj}` | d | ➖ | — | 1️⃣ | #fff |\n'
                f'| 2 | two | 둘 | g | `{proj2}` | d | ➖ | — | 2️⃣ | #fff |\n')
    return base


base = sandbox()
out_md = os.path.join(base, 'Identity.md')

rc, _, _ = run(['--bogus'], base)
check(rc == 2, f'알 수 없는 플래그 rc=2 (실제 {rc})')
check(not os.path.exists(out_md), '알 수 없는 플래그가 Identity.md 를 쓰지 않음')

rc, out, err = run(['--json'], base)
check(rc == 0, f'--json rc=0 (실제 {rc}) {err.strip()[:120]}')
check(not os.path.exists(out_md), '--json 이 파일을 쓰지 않음')
try:
    data = json.loads(out)
except ValueError:
    data = {}
    check(False, f'--json stdout 이 JSON 이 아님: {out[:80]!r}')
p1 = data.get('1', {})
check(p1.get('handles') == '[가, 나]', f"handles pass-through: {p1.get('handles')!r}")
check(p1.get('now') == '[Issue1 진행]', f"now pass-through: {p1.get('now')!r}")
check(p1.get('identity') == '테스트', 'REQUIRED 필드 유지')

rc, _, _ = run(['--md-only'], base)
text = open(out_md, encoding='utf-8').read() if os.path.exists(out_md) else ''
hdr = next((l for l in text.splitlines() if l.startswith('| id')), '')
check('now' in hdr, f'Identity.md 표 헤더에 now 열: {hdr[:80]}')
row1 = next((l for l in text.splitlines() if l.startswith('| 1 ')), '')
row2 = next((l for l in text.splitlines() if l.startswith('| 2 ')), '')
check('Issue1' in row1, f'prj1 행에 now 값: {row1[:80]}')
check('미기재' not in row2.split('|')[-3], 'now 값 없으면 경고 문자열이 아니라 빈 칸')

rc, out, _ = run(['--check'], base)
check('블록 리스트' in out and 'prj2' in out, f'--check 가 블록 리스트 무시 1줄: {out.strip()[:120]}')

print('PASS' if not fails else f'FAIL {len(fails)}')
sys.exit(1 if fails else 0)
