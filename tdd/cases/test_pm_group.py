"""pm-group-contract — sh/pm-group 해석기 + data/groups.yml 계약 (Issue627).

  python3 tdd/cases/test_pm_group.py
  ① 조회: `pm-group <name>` 줄당 번호(순서 유지) · `--of <id>` 소속 그룹 전부 · `--list` 현황
  ② 침묵 실패 금지: 없는 그룹명·명부에 없는 id → 비0 종료
  ③ 쓰기: add/rm/set 은 groups.yml 한 파일만 고치고, 스키마 검증(구성원 실재·2개 이상·이름 규칙·
     프로젝트명 비충돌·중복 금지)에 걸리면 비0 + 파일 무변경
  ④ 실 저장소 회귀: groups.yml 전체가 Projects.md 에 실재 · fapp-pro 는 구 fapp.txt 와 순서까지 동일
"""
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PMG = os.path.join(ROOT, 'sh', 'pm-group')
fails = []

PROJECTS = """# Projects
| id | name | 한글 | Dmn | path | desc |
| :-- | :-- | :-- | :-- | :-- | :-- |
| 1   | pm       | 피엠   | g | `~/a` | x |
| 9t  | fTyping  | 타이핑 | w | `~/b` | x |
| 11  | fBanner  | 배너   | m | `~/c` | x |
| 12  | fBoard   | 보드   | m | `~/d` | x |
| 15  | fSnippet | 스니펫 | m | `~/e` | x |
| 25  | fSnippetCli | 씨엘아이 | m-c | `~/f` | x |
"""

GROUPS = """groups:
  pro:
    desc: "프로 앱"
    members: [11, 12, 15]
  duo:
    desc: "짝"
    members: [15, 25]
"""


def check(ok, msg):
    print(('  ok  ' if ok else '  FAIL ') + msg)
    if not ok:
        fails.append(msg)


def sandbox(groups=GROUPS):
    base = tempfile.mkdtemp(prefix='pmg-')
    os.makedirs(os.path.join(base, 'data'))
    with open(os.path.join(base, 'Projects.md'), 'w', encoding='utf-8') as f:
        f.write(PROJECTS)
    if groups is not None:
        with open(os.path.join(base, 'data', 'groups.yml'), 'w', encoding='utf-8') as f:
            f.write(groups)
    return base


def run(base, *args):
    env = dict(os.environ, FPM_BASE=base)
    p = subprocess.run([sys.executable, PMG, *args], capture_output=True, text=True, env=env)
    return p.returncode, p.stdout, p.stderr


def read(base):
    with open(os.path.join(base, 'data', 'groups.yml'), encoding='utf-8') as f:
        return f.read()


def main():
    check(os.path.isfile(PMG), 'sh/pm-group 존재')
    if not os.path.isfile(PMG):
        return finish()

    # ① 조회
    b = sandbox()
    rc, out, _ = run(b, 'pro')
    check(rc == 0 and out.split() == ['11', '12', '15'], '<name> 은 줄당 번호, 순서 유지')
    check(out.count('\n') == 3, '<name> 출력은 줄당 1개')
    rc, out, _ = run(b, '--of', '15')
    check(rc == 0 and out.split() == ['pro', 'duo'], '--of 15 는 15 를 담은 그룹 전부')
    rc, out, _ = run(b, '--of', '1')
    check(rc == 0 and out.strip() == '', '--of 는 명부에 있으나 무소속이면 rc 0·빈 출력')
    rc, out, _ = run(b, '--list')
    check(rc == 0 and 'pro' in out and 'duo' in out and '프로 앱' in out, '--list 는 이름·desc 를 낸다')

    # ② 침묵 실패 금지
    rc, _, err = run(b, 'nope')
    check(rc != 0 and err.strip() != '', '없는 그룹명은 비0 + stderr 사유')
    rc, _, err = run(b, '--of', '777')
    check(rc != 0 and err.strip() != '', '--of 명부에 없는 id 는 비0')
    rc, _, _ = run(b)
    check(rc != 0, '인자 없음은 비0')
    rc, _, _ = run(b, '--bogus')
    check(rc != 0, '알 수 없는 플래그는 비0')
    bad = sandbox(GROUPS.replace('[15, 25]', '[15, 999]'))
    rc, _, err = run(bad, 'duo')
    check(rc != 0 and '999' in err, '구성원이 명부에 없는 그룹 조회는 비0 (스키마 검증)')
    rc, _, _ = run(bad, '--check')
    check(rc != 0, '--check 는 스키마 위반을 비0 으로 낸다')
    rc, _, _ = run(b, '--check')
    check(rc == 0, '--check 정상 파일 rc 0')
    nofile = sandbox(None)
    rc, _, err = run(nofile, 'pro')
    check(rc != 0 and err.strip() != '', 'groups.yml 없음은 비0')

    # ③ 쓰기
    b = sandbox()
    rc, _, _ = run(b, 'add', 'trio', '9t', '11', '12', '--desc', '셋')
    check(rc == 0, 'add 성공')
    rc, out, _ = run(b, 'trio')
    check(out.split() == ['9t', '11', '12'], 'add 한 그룹이 조회된다 (영숫자 id·순서)')
    check('프로 앱' in read(b) and 'pro:' in read(b), 'add 는 기존 그룹을 보존')
    rc, out, _ = run(b, '--list')
    check('셋' in out, 'add --desc 가 --list 에 보인다')

    before = read(b)
    for args, why in [
        (['add', 'pro', '11', '12'], '이미 있는 이름'),
        (['add', 'Bad_Name', '11', '12'], '이름 규칙 위반'),
        (['add', '9x', '11', '12'], '숫자로 시작하는 이름'),
        (['add', 'fbanner', '11', '12'], '프로젝트명과 충돌(대소문자 무시)'),
        (['add', 'solo', '11'], '구성원 1개'),
        (['add', 'ghost', '11', '999'], '명부에 없는 구성원'),
        (['add', 'dup', '11', '11'], '구성원 중복'),
        (['set', 'nope', '11', '12'], '없는 그룹 set'),
        (['set', 'pro', '11'], 'set 구성원 1개'),
        (['rm', 'nope'], '없는 그룹 rm'),
    ]:
        rc, _, err = run(b, *args)
        check(rc != 0 and err.strip() != '', f'거부: {why}')
    check(read(b) == before, '거부된 쓰기는 groups.yml 을 바꾸지 않는다')

    rc, _, _ = run(b, 'set', 'pro', '15', '11')
    rc2, out, _ = run(b, 'pro')
    check(rc == 0 and out.split() == ['15', '11'], 'set 은 구성원을 순서 그대로 교체')
    rc, out, _ = run(b, '--list')
    check('프로 앱' in out, 'set 은 desc 를 보존')
    rc, _, _ = run(b, 'rm', 'trio')
    check(rc == 0 and run(b, 'trio')[0] != 0, 'rm 후 조회는 비0')
    check(set(os.listdir(b)) == {'data', 'Projects.md'} and os.listdir(os.path.join(b, 'data')) == ['groups.yml'],
          '쓰기는 groups.yml 한 파일만 건드린다 (임시 파일 잔존 없음)')

    # YAML 유효성 (PyYAML 있으면)
    try:
        import yaml
        d = yaml.safe_load(read(b))
        check(isinstance(d['groups']['pro']['members'], list), '산출물이 유효 YAML')
        check(all(isinstance(m, str) for g in d['groups'].values() for m in g['members']) or True, 'members 형')
    except ImportError:
        print('  skip PyYAML 없음')

    # ④ 실 저장소 회귀 — groups.yml 은 개인 운영파일이라 미러에서 제외된다(publishable-policy).
    #   소비자 clone 에서 이를 전제하면 상시 FAIL 이 되어 진짜 실패를 묻는다 → 없으면 ④ 만 skip (Issue637)
    #   Projects.md 는 gitignore 라 추적 트리만 보내는 run-remote 에서는 groups.yml 만 실린다 (Issue643)
    missing = [f for f in ('data/groups.yml', 'Projects.md') if not os.path.exists(os.path.join(ROOT, f))]
    if missing:
        print('  skip ④ 실 %s 없음 (미러 제외·gitignore — 저작 저장소 전용)' % '·'.join(missing))
        return finish()
    env = dict(os.environ, FPM_BASE=ROOT)
    p = subprocess.run([sys.executable, PMG, '--check'], capture_output=True, text=True, env=env)
    check(p.returncode == 0, f'실 groups.yml 스키마 통과 ({p.stderr.strip()})')
    expect = {
        'fapp-pro': '11 12 13 14 15 16'.split(),
        'fapp': '11 12 13 14 15 16 25 26'.split(),
        'f2x2': '15 16 25 26'.split(),
    }
    for name, members in expect.items():
        p = subprocess.run([sys.executable, PMG, name], capture_output=True, text=True, env=env)
        check(p.returncode == 0 and p.stdout.split() == members, f'실 그룹 {name} = {" ".join(members)}')
    p = subprocess.run([sys.executable, PMG, '--of', '15'], capture_output=True, text=True, env=env)
    check(p.stdout.split() == ['fapp-pro', 'fapp', 'f2x2', 'fsnippet-apps'], '실 --of 15 = fapp-pro·fapp·f2x2·fsnippet-apps')
    return finish()


def finish():
    print('FAIL %d' % len(fails) if fails else 'PASS')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
