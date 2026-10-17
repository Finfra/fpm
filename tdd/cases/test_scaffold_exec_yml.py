"""scaffold-exec-yml — fpm-scaffold-fill.py 의 mac 타입 data/exec.yml 초기 생성 계약 (Issue614).

  python3 tdd/cases/test_scaffold_exec_yml.py
  ① mac 타입 → <repo>/data/exec.yml 생성 · prj·status·host·sync 값 + build/run/test/release 빈 값
  ② general·web 타입 → 미생성
  ③ 재실행·기존 파일 → 덮어쓰지 않음(멱등, 사용자 편집 보존)
  ④ 공개 repo(origin 이 github 등 원격) → .git/info/exclude 에 data/exec.yml 등재
"""
import os
import subprocess
import sys
import tempfile

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FILL = os.path.join(ROOT, 'sh', 'fpm-scaffold-fill.py')
fails = []


def check(ok, msg):
    print(('  ok  ' if ok else '  FAIL ') + msg)
    if not ok:
        fails.append(msg)


def scaffold(repo, ptype, prj='99', extra=()):
    p = subprocess.run([sys.executable, FILL, repo, '--name', 'fTest', '--type', ptype,
                        '--prj', prj, *extra], capture_output=True, text=True,
                       env=dict(os.environ, FPM_BASE=ROOT))
    return p.returncode, p.stdout + p.stderr


with tempfile.TemporaryDirectory() as t:
    mac = os.path.join(t, 'mac')
    os.makedirs(mac)
    rc, out = scaffold(mac, 'mac')
    f = os.path.join(mac, 'data', 'exec.yml')
    check(os.path.isfile(f), '① mac: data/exec.yml 생성')
    if os.path.isfile(f):
        d = yaml.safe_load(open(f)) or {}
        check(d.get('prj') == 99, '① prj == 99')
        check(d.get('status') == 'draft', '① status == draft')
        check(d.get('host') == 'jma', '① host == jma')
        check('sync' in d and d['sync'] is None, '① sync == null')
        for k in ('build', 'run', 'test', 'release'):
            check(not d.get(k), f'① {k} 비움(fail-loud)')

    for ty in ('general', 'web'):
        r = os.path.join(t, ty)
        os.makedirs(r)
        scaffold(r, ty)
        check(not os.path.exists(os.path.join(r, 'data', 'exec.yml')), f'② {ty}: 미생성')

    open(f, 'a').write('# edited\n')
    before = open(f).read()
    scaffold(mac, 'mac')
    check(open(f).read() == before, '③ 재실행 무변경(멱등)')

    pub = os.path.join(t, 'pub')
    os.makedirs(pub)
    subprocess.run(['git', 'init', '-q', pub], check=True)
    subprocess.run(['git', '-C', pub, 'remote', 'add', 'origin', 'https://github.com/x/y.git'], check=True)
    scaffold(pub, 'mac')
    ex = os.path.join(pub, '.git', 'info', 'exclude')
    check(os.path.isfile(ex) and 'data/exec.yml' in open(ex).read(), '④ 공개 repo: .git/info/exclude 등재')

if fails:
    print(f'\nFAIL {len(fails)}건')
    sys.exit(1)
print('\nALL OK')
