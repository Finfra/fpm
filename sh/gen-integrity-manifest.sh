#!/usr/bin/env bash
# gen-integrity-manifest.sh — fpm-core 번들 무결성 매니페스트 생성기 (prj3#Issue457)
#
# 문제: 소비자 머신에 **버전 정합 방어가 전 구간에 없다**. 특히 ②형 —
#   "같은 번호, 다른 내용" — 은 번호 비교로 **원리적으로 탐지 불가**하다.
#   `plugin update` 가 버전이 같아 갱신을 건너뛰므로 영원히 구버전에 머문다
#   (fg1 실측 2026-08-28: 마켓 0.5.5 이름표에 8/23 내용물).
#
# 해법: 파일별 sha256 을 번들 **안에** 담는다. 번들 안이라 publish 의 rsync 미러에
#   자동으로 따라가고, 소비자는 설치본 실물과 대조하면 번호와 무관하게 내용 차이를 본다.
#
# 🔴 설계 제약 (사용자 지정 2026-08-28) — prj20 마켓은 **7개 플러그인 공유**이고 각자
#   버전이 다르다. 그래서:
#     ⑴ 검증 단위는 **fpm-core 하나**로 한정한다
#     ⑵ 검증 자산은 **fpm-core 번들 내부**에 둔다 — prj20 공유 영역
#        (.claude-plugin/marketplace.json·타 플러그인)에 로직을 넣으면 다른 6개
#        프로젝트에 부작용이 간다
#     ⑶ 마켓 전체 버전·타 플러그인 버전은 판정 근거로 쓰지 않는다
#   본 스크립트는 `plugins/fpm-core/` 밖을 **읽지도 쓰지도 않는다**.
#
# 사용: bash sh/gen-integrity-manifest.sh [--check] [--bundle <dir>]
#         (기본)   생성·기록. publish 직전에 부른다
#         --check  기록하지 않고 현재 번들과 기존 매니페스트를 대조 (drift 검사)
# exit: 0=성공/일치, 1=실패/불일치

set -euo pipefail

die() { printf 'gen-integrity-manifest: %s\n' "$*" >&2; exit 1; }

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
BUNDLE="${REPO_DIR}/plugins/fpm-core"
MODE="write"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --check)  MODE="check"; shift ;;
        --bundle) BUNDLE="$2"; shift 2 ;;
        -h|--help) echo "usage: sh/gen-integrity-manifest.sh [--check] [--bundle <dir>]"; exit 0 ;;
        *) die "알 수 없는 인자: $1" ;;
    esac
done

[[ -d "$BUNDLE" ]] || die "번들 디렉토리 부재: $BUNDLE"
MANIFEST="${BUNDLE}/.fpm-integrity.json"

# 파서 무의존 원칙 (scar-manifest.yml 규약) — python3 만 쓴다.
PY="$(command -v python3)" || die "python3 미발견"

"$PY" - "$BUNDLE" "$MANIFEST" "$MODE" "$REPO_DIR" <<'PYEOF'
import hashlib, json, os, subprocess, sys, datetime

bundle, manifest, mode, repo = sys.argv[1:5]

# 제외 규약
#   ① 자기 자신 — 해시를 담은 파일을 해시할 수 없다(순환)
#   ② VCS 잔재·OS 부산물 — 배포물이 아니다
#   ③ 런타임 산출물 — 소비자 머신에서 **정상적으로 달라지는** 것들이다.
#      번들 안에 이런 것이 들어오면 정상 설치도 영구 불일치가 된다(prj3#Issue452 와 같은 함정).
EXCLUDE_NAMES = {'.fpm-integrity.json', '.DS_Store'}
EXCLUDE_DIRS  = {'.git', '__pycache__', 'node_modules', '.pytest_cache'}
EXCLUDE_SUFFIX = ('.pyc', '.pyo', '.log', '.tmp')

# 🔴 **git 미추적 파일은 담지 않는다** (2026-08-29 fg1 실측으로 발견)
#   발행은 rsync(작업트리 미러) → git commit 이다. 즉 **추적된 것만 마켓에 실린다**.
#   저작 머신 작업트리에만 있는 빌드 산출물(ex: vscode-ext/*.vsix — 하위 .gitignore 로
#   의도적 제외)을 해시에 담으면, 정상 설치본이 영구 REMOVED 로 잡힌다.
#   거짓 경고는 진짜 경고를 묻는다 — prj3#Issue452 가 정확히 그 실패였다.
#   ⚠️ write 모드에서만 적용한다. check 모드의 대상(설치본 캐시)은 git repo 가 아니다.
#   ⚠️ 근사임을 명시한다 — 실제 배송 집합은 **마켓(prj20) 추적 파일**이고 여기서 쓰는 것은
#      **소스(prj1) 추적 파일**이다. 한쪽에만 추적되는 파일(ex: prj1 미추적인데 마켓엔
#      커밋된 README)은 해시에서 빠진다. 방향은 **과소 포함**이라 거짓 경고를 만들지 않고
#      검사 범위만 좁아진다 — 거짓 FAIL 보다 과소 검사가 안전하다는 판단. 🚧 정밀화 여지
def tracked_set():
    try:
        r = subprocess.run(['git', '-C', bundle, 'ls-files', '-z'],
                           capture_output=True, timeout=30)
        if r.returncode != 0:
            return None
        names = [n.decode() for n in r.stdout.split(b'\x00') if n]
        return set(names) or None
    except Exception:
        return None

TRACKED = tracked_set() if mode == 'write' else None

def walk():
    for root, dirs, files in os.walk(bundle):
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDE_DIRS)
        for f in sorted(files):
            if f in EXCLUDE_NAMES or f.endswith(EXCLUDE_SUFFIX):
                continue
            full = os.path.join(root, f)
            if os.path.islink(full) or not os.path.isfile(full):
                continue
            rel = os.path.relpath(full, bundle)
            if TRACKED is not None and rel not in TRACKED:
                continue
            yield rel, full

def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()

files = {rel: sha256(full) for rel, full in walk()}

# 버전은 번들 자신의 plugin.json 에서 읽는다 — 마켓 전체 버전은 근거로 쓰지 않는다(제약 ⑶)
try:
    ver = json.load(open(os.path.join(bundle, '.claude-plugin', 'plugin.json')))['version']
except Exception:
    ver = 'unknown'

def git_sha():
    try:
        return subprocess.run(['git', '-C', repo, 'rev-parse', 'HEAD'],
                              capture_output=True, text=True, timeout=10).stdout.strip() or 'unknown'
    except Exception:
        return 'unknown'

if mode == 'check':
    if not os.path.exists(manifest):
        print('MISSING: %s — 아직 생성된 적 없다' % manifest); sys.exit(1)
    old = json.load(open(manifest))
    of = old.get('files', {})
    added   = sorted(set(files) - set(of))
    removed = sorted(set(of) - set(files))
    changed = sorted(k for k in set(files) & set(of) if files[k] != of[k])
    if not (added or removed or changed):
        print('OK: 번들 %d 파일 매니페스트 일치 (version=%s)' % (len(files), old.get('version')))
        sys.exit(0)
    for k in changed: print('CHANGED: %s' % k)
    for k in added:   print('ADDED  : %s' % k)
    for k in removed: print('REMOVED: %s' % k)
    print('불일치 %d건 (changed=%d added=%d removed=%d)'
          % (len(changed)+len(added)+len(removed), len(changed), len(added), len(removed)))
    sys.exit(1)

doc = {
    'schema_version': 1,
    'plugin': 'fpm-core',
    'version': ver,
    'git_sha': git_sha(),
    'generated_at': datetime.datetime.now(datetime.timezone.utc)
                        .replace(microsecond=0).isoformat().replace('+00:00', 'Z'),
    'algorithm': 'sha256',
    'file_count': len(files),
    'files': files,
}
with open(manifest, 'w') as fh:
    json.dump(doc, fh, ensure_ascii=False, indent=2, sort_keys=False)
    fh.write('\n')
print('written: %s (%d files, version=%s)' % (manifest, len(files), ver))
PYEOF
