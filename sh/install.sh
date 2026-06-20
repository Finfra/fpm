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
# 사용: bash sh/install.sh              (또는 ./sh/install.sh) — 셸 + SCAR 설치 (기본)
#       bash sh/install.sh --clean     클린 재설치 — sh/uninstall.sh 로 기존 흔적 백업·제거 후 설치
#       bash sh/install.sh --no-scar   SCAR 설치 생략 (셸 부트스트랩만)
#       bash sh/install.sh --local [경로]  폐쇄망(air-gapped): GitHub 대신 미리 받아둔
#                                          f-claude-plugins 로컬 사본을 마켓 소스로 사용 (Issue186)
#       bash sh/install.sh --with-scar [하위호환 no-op] SCAR 기본 ON 이므로 불필요
set -euo pipefail

# 스크립트는 sh/ 하위 → repo 루트는 한 단계 위.
# ${BASH_SOURCE[0]:-$0}: bash 실행 시 BASH_SOURCE, zsh/sh source 시 미설정이라 $0 fallback
# (set -u 하에서 미설정 참조 시 'parameter not set' crash 방지). 본 스크립트는 `bash` 실행 전용.
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"

info()  { printf '\033[36m[fpm]\033[0m %s\n' "$1"; }
warn()  { printf '\033[33m[fpm]\033[0m %s\n' "$1"; }
err()   { printf '\033[31m[fpm]\033[0m %s\n' "$1" >&2; }

# ── 아티팩트 SSOT 로드 (install/check 공통) ───────────────────
MANIFEST="$REPO_DIR/data/install_manifest.sh"
if [[ ! -f "$MANIFEST" ]]; then
    err "🚨 매니페스트 없음: $MANIFEST — 설치 중단 (저장소 손상?)"; exit 1
fi
# shellcheck source=data/install_manifest.sh
source "$MANIFEST"

# 매니페스트 값 → 로컬 파생 (기준점 적용)
BASEPATH_FILE="$HOME/$FPM_BASEPATH_REL_HOME"
INFO_DIR="$(dirname "$BASEPATH_FILE")"
FUNC_FILE="$REPO_DIR/$FPM_BOOTSTRAP_REL_REPO"
MARKER="$FPM_MARKER"
MARKER_END="$FPM_MARKER_END"

# fpm-core SCAR 설치 타깃 — env FPM_MKT_REF 또는 --local <경로> 로 override (기본은 매니페스트)
# 우선순위: --local CLI > env FPM_MKT_REF > 매니페스트 기본(GitHub). --local 해석은 인자 파싱 이후.
FPM_MKT_REF="${FPM_MKT_REF:-$FPM_MKT_REF_DEFAULT}"  # github url 또는 로컬경로
FPM_PLUGIN="${FPM_PLUGIN_NAME}@${FPM_MKT_NAME}"

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
LOCAL_MKT=""         # --local <경로> 지정 시 채워짐. "AUTO" = 인자 없이 --local (관례 후보 탐색)
# 값 동반 플래그(--local) 지원 위해 while+shift 사용 (기존 for-arg 로는 다음 인자 소비 불가).
while [[ $# -gt 0 ]]; do
    case "$1" in
        --clean) CLEAN=1 ;;
        --no-scar) WITH_SCAR=0 ;;
        --with-scar) : ;;   # 하위호환 no-op (SCAR 기본 ON 이므로 불필요)
        --local=*) LOCAL_MKT="${1#--local=}" ;;
        --local)
            # 다음 인자가 플래그(-)가 아니면 경로로 소비, 아니면 AUTO(관례 후보 탐색)
            if [[ $# -ge 2 && "${2:0:1}" != "-" ]]; then
                LOCAL_MKT="$2"; shift
            else
                LOCAL_MKT="AUTO"
            fi ;;
        -h|--help)
            echo "usage: sh/install.sh [--clean] [--no-scar] [--local [경로]]"
            echo "  --clean       : sh/uninstall.sh 로 기존 fpm 흔적 백업·제거 후 설치 (클린 재설치)"
            echo "  --no-scar     : fpm-core 플러그인(SCAR) 설치 생략 — 셸 부트스트랩만"
            echo "  --local [경로] : 폐쇄망(air-gapped) — GitHub 대신 미리 받아둔 f-claude-plugins"
            echo "                  로컬 사본을 마켓 소스로 사용. 경로 생략 시 관례 위치 자동 탐색."
            echo "  --with-scar   : [하위호환 no-op] SCAR 는 기본 설치됨"
            echo ""
            echo "  기본 동작: 셸 + fpm-core 플러그인(hub/dashboard 등 SCAR)을"
            echo "             prj20 마켓($FPM_MKT_NAME) 경유로 설치 (멱등)."
            echo "             claude CLI 부재 시 SCAR 만 건너뜀(셸 설치는 정상, exit 0)."
            echo "             env FPM_MKT_REF 로 마켓 소스(github url/로컬경로) override"
            exit 0 ;;
        *) warn "알 수 없는 인자: $1 (무시)" ;;
    esac
    shift
done

# ── 0-1. --local 해석 (폐쇄망 마켓 소스) ──────────────────────
# 지정 경로(또는 관례 후보) 에서 marketplace.json 존재를 확인한 뒤 FPM_MKT_REF 로 채택.
# env FPM_MKT_REF 보다 CLI --local 이 우선.
if [[ -n "$LOCAL_MKT" ]]; then
    if [[ "$LOCAL_MKT" == "AUTO" ]]; then
        # 관례 후보 순회 — 첫 marketplace.json 보유 디렉토리 채택
        declare -a LOCAL_CANDIDATES=(
            "$REPO_DIR/../f-claude-plugins"
            "$HOME/_git/__all/f-claude-plugins"
            "$HOME/_git/f-claude-plugins"
            "./f-claude-plugins"
        )
        FOUND=""
        for cand in "${LOCAL_CANDIDATES[@]}"; do
            if [[ -f "$cand/.claude-plugin/marketplace.json" || -f "$cand/marketplace.json" ]]; then
                FOUND="$cand"; break
            fi
        done
        if [[ -z "$FOUND" ]]; then
            err "🚨 --local: 관례 위치에서 f-claude-plugins 로컬 사본을 못 찾음."
            err "   폐쇄망 설치 전 먼저 받아두세요:"
            err "     git clone $FPM_MKT_REF_DEFAULT  (인터넷 가능 머신에서)"
            err "   후보 경로: ${LOCAL_CANDIDATES[*]}"
            err "   또는 경로 명시: bash sh/install.sh --local /path/to/f-claude-plugins"
            exit 1
        fi
        LOCAL_MKT="$FOUND"
    fi
    # 경로 정규화 + marketplace.json 검증 (fail-loud)
    LOCAL_MKT="$(cd "$LOCAL_MKT" 2>/dev/null && pwd || true)"
    if [[ -z "$LOCAL_MKT" ]]; then
        err "🚨 --local: 지정 경로가 디렉토리가 아님 — 폐쇄망 설치 중단"; exit 1
    fi
    if [[ ! -f "$LOCAL_MKT/.claude-plugin/marketplace.json" && ! -f "$LOCAL_MKT/marketplace.json" ]]; then
        err "🚨 --local: '$LOCAL_MKT' 에 marketplace.json 없음 (f-claude-plugins 사본 아님?) — 설치 중단"; exit 1
    fi
    FPM_MKT_REF="$LOCAL_MKT"
    info "폐쇄망 마켓 소스 채택(--local): $FPM_MKT_REF"
fi

# --clean: 설치 전 백업+제거 (sh/uninstall.sh 위임)
if [[ "$CLEAN" -eq 1 ]]; then
    if [[ -f "$REPO_DIR/sh/uninstall.sh" ]]; then
        info "--clean: sh/uninstall.sh 로 기존 흔적 백업 후 제거"
        bash "$REPO_DIR/sh/uninstall.sh"
        echo ""
        info "클린 제거 완료 — 신규 설치 진행"
    else
        warn "--clean 지정됐으나 sh/uninstall.sh 없음 — 백업 없이 설치 진행 (멱등 재설치)"
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
# 매니페스트 FPM_ORG_FILES (real:org) 순회 — check.sh 와 동일 SSOT
for pair in "${FPM_ORG_FILES[@]}"; do
    place_org "${pair%%:*}" "${pair##*:}"
done

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
  (생략하려면 bash sh/install.sh --no-scar)

[선택] Keyboard Maestro 매크로:  keyboard-maestro/README.md

제거:  bash sh/uninstall.sh        (셸 흔적 백업 후 제거)
클린 재설치:  bash sh/install.sh --clean
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
