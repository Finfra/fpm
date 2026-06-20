#!/usr/bin/env bash
# install.sh — fpm 설치 스크립트 (멱등)
#
# 동작:
#   1. <repo>/sh/fpm.sh 부트스트랩을 ~/.zshrc 에서 source (FPM_BASE export + 마커 가드 — 중복 방지)
#   2. ~/.info/__pmBasePath.txt 생성 → <repo>/projects
#   3. projects/ 스캐폴드 (없으면 생성)
#   4. 운영 필수 파일 배치: Servers.md / Projects.md / data/hub_setting.yml 부재 시 *_org 예제 복사
#   5. hub 서버 안내 출력
#   6. [기본 ON] fpm-core Claude Code 플러그인(SCAR) 을 prj20 마켓 경유 설치 (Issue181)
#      claude CLI 부재 시 경고만 하고 건너뜀(graceful skip — 셸 설치는 정상 완료, exit 0).
#      --no-scar 로 옵트아웃 가능.
#
# 사용: bash install.sh              (또는 ./install.sh) — 셸 + SCAR 설치 (기본)
#       bash install.sh --clean     클린 재설치 — uninstall.sh 로 기존 흔적 백업·제거 후 설치
#       bash install.sh --no-scar   SCAR 설치 생략 (셸 부트스트랩만)
#       bash install.sh --with-scar [하위호환 no-op] SCAR 기본 ON 이므로 불필요
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INFO_DIR="$HOME/.info"
BASEPATH_FILE="$INFO_DIR/__pmBasePath.txt"
FUNC_FILE="$REPO_DIR/sh/fpm.sh"
MARKER="# >>> fpm functions >>>"
MARKER_END="# <<< fpm functions <<<"

# fpm-core SCAR 설치 타깃 (prj20 집약 마켓 f-claude-plugins) — env 로 override 가능
FPM_MKT_REF="${FPM_MKT_REF:-https://github.com/finfra/f-claude-plugins}"  # github url 또는 로컬경로
FPM_MKT_NAME="f-claude-plugins"   # marketplace.json name
FPM_PLUGIN="fpm-core@${FPM_MKT_NAME}"

info()  { printf '\033[36m[fpm]\033[0m %s\n' "$1"; }
warn()  { printf '\033[33m[fpm]\033[0m %s\n' "$1"; }
err()   { printf '\033[31m[fpm]\033[0m %s\n' "$1" >&2; }

# ── SCAR(fpm-core 플러그인) 설치 — 멱등 ───────────────────────
# marketplace add(중복 시 update) → plugin install(이미 설치 시 skip).
# claude CLI 부재 시 fail-loud + 수동 안내 후 비치명 반환(셸 설치는 이미 완료).
install_scar() {
    # claude CLI 부재 = 셸-only 유저 정상 시나리오 → benign skip(SCAR_SKIPPED), exit 0 유지.
    # 네트워크·권한 등 실제 설치 실패만 SCAR_FAILED(exit 2)로 구분.
    if ! command -v claude >/dev/null 2>&1; then
        warn "──────────────────────────────────────────────"
        warn "ℹ️  'claude' CLI 미발견 → fpm-core 플러그인(SCAR) 설치 건너뜀."
        warn "   (셸 설치는 정상 완료. SCAR 가 필요하면 Claude Code 설치 후 재실행)"
        warn ""
        warn "   수동 설치:"
        warn "     claude plugin marketplace add $FPM_MKT_REF --scope user"
        warn "     claude plugin install $FPM_PLUGIN --scope user"
        warn "──────────────────────────────────────────────"
        SCAR_SKIPPED=1
        return 0
    fi

    # 1) marketplace 등록 (멱등: 이미 있으면 update)
    if claude plugin marketplace list 2>/dev/null | grep -qF "$FPM_MKT_NAME"; then
        info "marketplace '$FPM_MKT_NAME' 이미 등록 — update"
        claude plugin marketplace update "$FPM_MKT_NAME" >/dev/null 2>&1 \
            || warn "marketplace update 실패 (기존 등록 유지) — 계속 진행"
    else
        info "marketplace 등록: $FPM_MKT_REF"
        if ! claude plugin marketplace add "$FPM_MKT_REF" --scope user; then
            err "🚨 marketplace add 실패: $FPM_MKT_REF — SCAR 설치 중단"
            SCAR_FAILED=1
            return 0
        fi
    fi

    # 2) 플러그인 설치 (멱등: 이미 설치 시 skip)
    if claude plugin list 2>/dev/null | grep -qF "fpm-core"; then
        info "플러그인 'fpm-core' 이미 설치 — skip"
    else
        info "플러그인 설치: $FPM_PLUGIN"
        if ! claude plugin install "$FPM_PLUGIN" --scope user; then
            err "🚨 plugin install 실패: $FPM_PLUGIN — 수동 확인 필요"
            SCAR_FAILED=1
            return 0
        fi
    fi
    info "fpm-core SCAR 설치 완료 (claude 재시작 후 적용)"
}

# ── 0. 인자 파싱 ──────────────────────────────────────────────
CLEAN=0
WITH_SCAR=1          # 기본 ON (Issue181 후속 — SCAR 가 fpm 주목적). --no-scar 로 끔
SCAR_FAILED=0
SCAR_SKIPPED=0
for arg in "$@"; do
    case "$arg" in
        --clean) CLEAN=1 ;;
        --no-scar) WITH_SCAR=0 ;;
        --with-scar) : ;;   # 하위호환 no-op (SCAR 기본 ON 이므로 불필요)
        -h|--help)
            echo "usage: install.sh [--clean] [--no-scar]"
            echo "  --clean     : uninstall.sh 로 기존 fpm 흔적 백업·제거 후 설치 (클린 재설치)"
            echo "  --no-scar   : fpm-core 플러그인(SCAR) 설치 생략 — 셸 부트스트랩만"
            echo "  --with-scar : [하위호환 no-op] SCAR 는 기본 설치됨"
            echo ""
            echo "  기본 동작: 셸 + fpm-core 플러그인(hub/dashboard 등 SCAR)을"
            echo "             prj20 마켓($FPM_MKT_NAME) 경유로 설치 (멱등)."
            echo "             claude CLI 부재 시 SCAR 만 건너뜀(셸 설치는 정상, exit 0)."
            echo "             env FPM_MKT_REF 로 마켓 소스(github url/로컬경로) override"
            exit 0 ;;
        *) warn "알 수 없는 인자: $arg (무시)" ;;
    esac
done

# --clean: 설치 전 백업+제거 (uninstall.sh 위임)
if [[ "$CLEAN" -eq 1 ]]; then
    if [[ -f "$REPO_DIR/uninstall.sh" ]]; then
        info "--clean: uninstall.sh 로 기존 흔적 백업 후 제거"
        bash "$REPO_DIR/uninstall.sh"
        echo ""
        info "클린 제거 완료 — 신규 설치 진행"
    else
        warn "--clean 지정됐으나 uninstall.sh 없음 — 백업 없이 설치 진행 (멱등 재설치)"
    fi
fi

# ── 1. fpm.sh 부트스트랩 source 라인 추가 (멱등, zsh + bash 양쪽) ──
# FPM_BASE 명시 export 후 sh/fpm.sh source (fpm.sh 헤더 권장 로드 규약).
# fpm.sh 가 FPM_BASE 미설정 시 자기 위치로 self-detect 하나, 외부 소비자(KM·cron)
# 캐시 정합성을 위해 install 단계에서 명시 export.
# 대상 rc : 로그인 셸($SHELL) rc 는 없어도 생성, 반대편 rc 는 존재 시에만 추가
#   → 평소 zsh / 스크립트 bash 이중 사용까지 커버. fpm.sh 가 셸을 분기하므로
#     동일 source 라인이 zsh·bash 양쪽에서 동작.
if [[ ! -f "$FUNC_FILE" ]]; then
    warn "부트스트랩 파일 없음: $FUNC_FILE"; exit 1
fi

# 대상 rc 수집 (빈 배열 미발생 — bash 3.2 set -u 안전)
declare -a RC_FILES=()
LOGIN_SHELL="$(basename "${SHELL:-}")"
if [[ "$LOGIN_SHELL" == "bash" ]]; then
    RC_FILES+=("$HOME/.bashrc")
    [[ -f "$HOME/.zshrc" ]] && RC_FILES+=("$HOME/.zshrc")
else
    # zsh 또는 미상 → zsh 우선
    RC_FILES+=("$HOME/.zshrc")
    [[ -f "$HOME/.bashrc" ]] && RC_FILES+=("$HOME/.bashrc")
fi

for RC in "${RC_FILES[@]}"; do
    rc_name="$(basename "$RC")"
    if grep -qF "$MARKER" "$RC" 2>/dev/null; then
        info "$rc_name 에 이미 fpm 블록 존재 — skip"
    else
        {
            echo ""
            echo "$MARKER"
            echo "export FPM_BASE=\"$REPO_DIR\""
            echo "source \"$FUNC_FILE\""
            echo "$MARKER_END"
        } >> "$RC"
        info "$rc_name 에 fpm 부트스트랩 source 추가 (FPM_BASE=$REPO_DIR)"
    fi
done

# ── 2. __pmBasePath.txt 생성 ──────────────────────────────────
mkdir -p "$INFO_DIR"
echo "$REPO_DIR/projects" > "$BASEPATH_FILE"
info "베이스 경로 기록: $BASEPATH_FILE → $REPO_DIR/projects"

# ── 3. projects/ 스캐폴드 ─────────────────────────────────────
if [[ ! -d "$REPO_DIR/projects" ]]; then
    mkdir -p "$REPO_DIR/projects"
    echo "\$HOME"           > "$REPO_DIR/projects/0"
    echo "$REPO_DIR"        > "$REPO_DIR/projects/1"
    info "projects/ 스캐폴드 생성 (0=home, 1=repo). Projects.md 참고하여 추가하세요."
fi

# ── 4. 운영 필수 파일 배치 (_org → 실파일) ────────────────────
place_org() {
    local real="$1" org="$2"
    if [[ -f "$REPO_DIR/$real" ]]; then
        info "$real 이미 존재 — 보존"
    elif [[ -f "$REPO_DIR/$org" ]]; then
        cp "$REPO_DIR/$org" "$REPO_DIR/$real"
        info "$org → $real 배치 (자신의 정보로 교체하세요)"
    fi
}
place_org "Servers.md"  "Servers_org.md"
place_org "Projects.md" "Projects_org.md"
place_org "data/hub_setting.yml" "data/hub_setting_org.yml"

# ── 5. 안내 ──────────────────────────────────────────────────
cat <<EOF

────────────────────────────────────────────
✅ fpm 설치 완료

다음 단계:
  1) 셸 재시작 (또는 zsh: source ~/.zshrc  /  bash: source ~/.bashrc)
  2) Projects.md / Servers.md 를 자신의 환경으로 편집
  3) ~/.ssh/config 의 # favorite 섹션에 sshf 대상 Host alias 정의
  4) cdf          → 프로젝트 목록 확인
     sshf         → 서버 목록 확인

[선택] hub 서버 (HTML 렌더 + 대시보드, Python 3):
  cd "$REPO_DIR/services/hub" && python3 server.py
  → http://127.0.0.1:9876/hub

fpm-core 플러그인(SCAR — hub/dashboard 등): 기본 설치됨
  (생략하려면 bash install.sh --no-scar)

[선택] Keyboard Maestro 매크로:  keyboard-maestro/README.md

제거:  bash uninstall.sh        (셸 흔적 백업 후 제거)
클린 재설치:  bash install.sh --clean
────────────────────────────────────────────
EOF

# ── 6. SCAR(fpm-core 플러그인) 설치 (기본 ON, --no-scar 로 생략) ──
if [[ "$WITH_SCAR" -eq 1 ]]; then
    echo ""
    info "fpm-core 플러그인(SCAR) 설치 시작 (생략하려면 --no-scar)"
    install_scar
    if [[ "$SCAR_FAILED" -eq 1 ]]; then
        # 실제 설치 실패(네트워크·권한 등) — fail-loud
        warn "SCAR 설치 실패 — 위 안내 참고 (셸 설치는 정상 완료)"
        exit 2
    elif [[ "$SCAR_SKIPPED" -eq 1 ]]; then
        # claude CLI 부재 — benign skip, exit 0 유지
        info "SCAR 는 건너뛰었으나 셸 설치는 정상 완료"
    fi
fi
