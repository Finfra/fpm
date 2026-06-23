# install_manifest.sh — fpm 설치 아티팩트 SSOT (sourceable)
#
# install.sh(생성) 와 check.sh(검증) 가 **공통 source** 하는 단일 진실 원본.
# 두 스크립트가 마커·경로·운영파일 목록·SCAR 타깃을 각자 하드코딩하면 drift(한쪽만
# 갱신 → 설치/점검 불일치)가 발생하므로, 변경되는 모든 값을 여기 한 곳에 모은다.
# uninstall.sh 도 마커·basepath 를 본 파일에서 가져온다.
#
# 규약:
#   - 순수 bash sourceable. yq 등 외부 의존 없음 (installer 무의존 유지).
#   - bash 3.2(macOS 기본) 호환. 배열·${VAR:-default} 만 사용.
#   - 경로는 의미별 기준점 명시: *_REL_HOME = $HOME 기준 / *_REL_REPO = repo 기준.
#   - 값만 정의. 로직(생성·검증)은 소비 측(install.sh / check.sh / uninstall.sh)이 담당.

# ── [셸] rc 블록 마커 (install: rc 삽입 가드 / check: 존재 확인 / uninstall: 제거 범위) ──
FPM_MARKER="# >>> fpm functions >>>"
FPM_MARKER_END="# <<< fpm functions <<<"

# ── [셸] FPM_BASE 베이스경로 기록 파일 ($HOME 기준 상대) ──
FPM_BASEPATH_REL_HOME=".info/__pmBasePath.txt"

# ── [셸] 부트스트랩 source 대상 (repo 기준 상대) ──
FPM_BOOTSTRAP_REL_REPO="sh/fpm.sh"

# ── [셸] projects/ 스캐폴드 — 필수 존재 인덱스 (check 가 검증) ──
#   생성 시 0=$HOME, 1=$REPO_DIR 내용은 install.sh 가 채움(내용은 환경 의존이라 코드에).
FPM_SCAFFOLD_INDEXES=(0 1)

# ── [셸] 운영 필수 파일 (real:org, repo 기준) ──
#   install: org 존재 + real 부재 시 org→real 복사 (멱등, 기존 보존)
#   check  : real 존재 확인 (부재 시 WARN — _org 예제로 배치 안내)
FPM_ORG_FILES=(
    "Servers.md:Servers_org.md"
    "Projects.md:Projects_org.md"
    "data/hub_setting.yml:data/hub_setting_org.yml"
)

# ── [SCAR] fpm-core 플러그인 (prj20 집약 마켓 경유) ──
#   install  : marketplace add(중복 update) → plugin install(중복 skip)
#   check    : marketplace 등록 + plugin 설치 확인
#   uninstall: plugin uninstall (marketplace 는 공유 — 제거 금지)
FPM_MKT_NAME="f-claude-plugins"
FPM_MKT_REF_DEFAULT="https://github.com/finfra/f-claude-plugins"  # env FPM_MKT_REF 로 override
FPM_PLUGIN_NAME="fpm-core"

# ── [SCAR] fpm-core 번들 SCAR 인벤토리 (선언적 SSOT — drift 가드) ──
#   plugin.json 은 개별 SCAR 를 열거하지 않음(Claude Code 가 디렉토리 자동 탐색)므로,
#   "fpm-core 가 무엇을 ship 하는가" 의 단일 진실 원본은 본 배열뿐이다.
#   check.sh 가 아래 선언 ↔ 실제 파일(plugins/fpm-core/{commands,skills,agents}/)을
#   양방향 diff: 선언했는데 파일 없음 / 파일 있는데 선언 누락 둘 다 FAIL.
#   SCAR 추가·삭제·rename 시 본 배열을 함께 갱신해야 drift 가 안 생긴다.
#   파일 규약: commands/<name>.md · skills/<name>/SKILL.md · agents/<name>.md
FPM_PLUGIN_SRC_REL_REPO="plugins/fpm-core"   # repo 기준 플러그인 소스 디렉토리

FPM_SCAR_COMMANDS=(
    fpm-cdf
    fpm-board
    fpm-board-server
    fpm-hub
    fpm-hub-server
    fpm-new-project
    fpm-pm-del
    fpm-pm-do
    fpm-pm-new
    fpm-pm-query
    fpm-pm-update
    fpm-show
)
FPM_SCAR_SKILLS=(
    fpm-cdf
    fpm-pm
    fpm-pm-do
)
FPM_SCAR_AGENTS=(
    fpm-board
)
