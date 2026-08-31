#!/usr/bin/env bash
# check.sh — fpm 설치 점검 (읽기 전용, 멱등)
#
# sh/install.sh 가 배치한 흔적을 검사하여 설치 상태를 진단함. 아무것도 변경하지 않음.
# install.sh / uninstall.sh 와 동일하게 data/install_manifest.sh(SSOT) 를 source 하므로,
# 마커·경로·운영파일 목록·SCAR 타깃이 설치 측과 항상 일치(drift 없음).
#
# 검사 항목:
#   [셸]  1. sh/fpm.sh 부트스트랩 파일 존재
#         1-2. 설치본 브랜치 = main (Issue410, advisory)
#         2. rc(zshrc/bashrc) 에 fpm 마커 블록 + FPM_BASE export
#         3. ~/.info/__pmBasePath.txt → <repo>/projects 일치
#         4. projects/ 스캐폴드 (필수 인덱스)
#         5. 운영 필수 파일 (FPM_ORG_FILES) + 요구 섹션 결손 (FPM_ORG_SECTIONS, Issue407)
#         5-2. 프로젝트 맵 산출물 (FPM_PROJECTS_MAP_OUT, Issue407)
#         12-2. 번들 hooks 사본 ↔ prj3 원본 (Issue412 — scar-hooks-check.sh 위임)
#         6. cdf 함수 로드 여부 (sh/fpm.sh source)
#   [SCAR] 7. claude CLI 존재
#          8. marketplace 등록 (FPM_MKT_NAME)
#          9. 플러그인 설치 (FPM_PLUGIN_NAME)
#         10. SCAR 인벤토리 drift — 선언(FPM_SCAR_*) ↔ 소스 파일 양방향 대조
#
# 사용: bash sh/check.sh            전체 점검 (셸 + SCAR)
#       bash sh/check.sh --no-scar  SCAR 점검 생략 (셸만)
#       bash sh/check.sh --quiet    PASS 항목 숨김, FAIL/WARN 만 출력
#
# 종료코드: 0=전부 PASS(WARN 허용) / 1=하나 이상 FAIL
set -uo pipefail

# 스크립트는 sh/ 하위 → repo 루트는 한 단계 위.
# ${BASH_SOURCE[0]:-$0}: bash 실행 시 BASH_SOURCE, zsh/sh source 시 미설정이라 $0 fallback
# (set -u 하에서 미설정 참조 시 'parameter not set' crash 방지). 본 스크립트는 `bash` 실행 전용.
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"

# ── 아티팩트 SSOT 로드 (install/check 공통) ───────────────────
MANIFEST="$REPO_DIR/data/install_manifest.sh"
if [[ ! -f "$MANIFEST" ]]; then
    printf '\033[31m[fpm]\033[0m 🚨 매니페스트 없음: %s — 점검 불가 (저장소 손상?)\n' "$MANIFEST" >&2
    exit 1
fi
# shellcheck source=data/install_manifest.sh
source "$MANIFEST"

# 매니페스트 값 → 로컬 파생 (install.sh 와 동일 기준점)
BASEPATH_FILE="$HOME/$FPM_BASEPATH_REL_HOME"
FUNC_FILE="$REPO_DIR/$FPM_BOOTSTRAP_REL_REPO"
MARKER="$FPM_MARKER"
# FPM_MKT_NAME / FPM_PLUGIN_NAME / FPM_ORG_FILES / FPM_SCAFFOLD_INDEXES 는 매니페스트가 제공

# ── 인자 ──────────────────────────────────────────────────────
CHECK_SCAR=1
QUIET=0
for arg in "$@"; do
    case "$arg" in
        --no-scar) CHECK_SCAR=0 ;;
        --quiet|-q) QUIET=1 ;;
        -h|--help)
            echo "usage: sh/check.sh [--no-scar] [--quiet]"
            echo "  --no-scar : SCAR(fpm-core 플러그인) 점검 생략 — 셸만"
            echo "  --quiet   : PASS 항목 숨김, FAIL/WARN 만 출력"
            exit 0 ;;
        *) printf '\033[33m[fpm]\033[0m 알 수 없는 인자: %s (무시)\n' "$arg" ;;
    esac
done

# ── 결과 카운터 + 출력 헬퍼 ───────────────────────────────────
PASS_N=0; WARN_N=0; FAIL_N=0
ok()   { PASS_N=$((PASS_N+1)); [[ "$QUIET" -eq 1 ]] || printf '  \033[32m✅ PASS\033[0m  %s\n' "$1"; }
warn() { WARN_N=$((WARN_N+1)); printf '  \033[33m⚠️  WARN\033[0m  %s\n' "$1"; }
fail() { FAIL_N=$((FAIL_N+1)); printf '  \033[31m❌ FAIL\033[0m  %s\n' "$1"; }
sec()  { printf '\n\033[36m%s\033[0m\n' "$1"; }

# ── [셸] 1. 부트스트랩 파일 ───────────────────────────────────
sec "── 셸 설치 ──"
if [[ -f "$FUNC_FILE" ]]; then
    ok "부트스트랩 존재: $FPM_BOOTSTRAP_REL_REPO"
else
    fail "부트스트랩 없음: $FUNC_FILE (sh/install.sh 재실행 필요)"
fi

# ── 1-2. 소비자 브랜치 (Issue410, advisory) ────────────────────
#   설치본($FPM_BASE)이 main 이 아니면 `git pull --ff-only` 가 배포를 받지 못한다.
#   실측(2026-08-29 fg1): develop 체크아웃 상태로 남아 VERSION 이 0.6.3 에 정체 —
#   배포는 정상 완료됐는데 소비자에게만 도달하지 않아 원인 추적이 어려웠다.
#   집행 등급 **advisory** — check.sh 는 읽기 전용 진단이라 차단 수단이 없다.
#   enforce 짝은 저작 머신 쪽 `do_forward` 의 F5-0 DST 브랜치 가드다(scripts/fpm-sync.sh).
if [[ -d "$REPO_DIR/.git" ]]; then
    cur_br="$(git -C "$REPO_DIR" symbolic-ref --short HEAD 2>/dev/null || true)"
    if [[ "$cur_br" == "main" ]]; then
        ok "설치본 브랜치: main"
    elif [[ -z "$cur_br" ]]; then
        warn "설치본이 detached HEAD — 배포 pull 불가. 조치: git -C $REPO_DIR switch main"
    else
        warn "설치본 브랜치가 '$cur_br' — 배포는 main 으로만 나간다(pull --ff-only 실패). 조치: git -C $REPO_DIR switch main"
    fi
else
    warn "설치본이 git repo 가 아님: $REPO_DIR — 배포 pull 경로 없음(tarball 설치?)"
fi

# ── 2. rc 블록 + FPM_BASE export ──────────────────────────────
RC_FOUND=0
for RC in "$HOME/.zshrc" "$HOME/.bashrc"; do
    name="$(basename "$RC")"
    [[ -f "$RC" ]] || continue
    if grep -qF "$MARKER" "$RC" 2>/dev/null; then
        RC_FOUND=1
        rc_base="$(grep -F 'export FPM_BASE=' "$RC" 2>/dev/null | tail -1 | sed -E 's/.*export FPM_BASE="?([^"]*)"?.*/\1/')"
        if [[ "$rc_base" == "$REPO_DIR" ]]; then
            ok "$name: fpm 블록 + FPM_BASE=$REPO_DIR"
        else
            warn "$name: fpm 블록 있으나 FPM_BASE='$rc_base' ≠ repo($REPO_DIR)"
        fi
    fi
done
[[ "$RC_FOUND" -eq 0 ]] && fail "rc(zshrc/bashrc) 에 fpm 마커 블록 없음 — sh/install.sh 재실행"

# ── 3. __pmBasePath.txt ───────────────────────────────────────
if [[ -f "$BASEPATH_FILE" ]]; then
    bp="$(cat "$BASEPATH_FILE" 2>/dev/null)"
    if [[ "$bp" == "$REPO_DIR/projects" ]]; then
        ok "베이스 경로 기록 일치: $BASEPATH_FILE"
    else
        warn "베이스 경로 불일치: '$bp' ≠ '$REPO_DIR/projects'"
    fi
else
    fail "베이스 경로 파일 없음: $BASEPATH_FILE"
fi

# ── 4. projects/ 스캐폴드 ─────────────────────────────────────
if [[ -d "$REPO_DIR/projects" ]]; then
    n="$(find "$REPO_DIR/projects" -maxdepth 1 -type f 2>/dev/null | wc -l | tr -d ' ')"
    missing=""
    for idx in "${FPM_SCAFFOLD_INDEXES[@]}"; do
        [[ -f "$REPO_DIR/projects/$idx" ]] || missing="$missing $idx"
    done
    if [[ -z "$missing" ]]; then
        ok "projects/ 스캐폴드 OK (필수 인덱스 ${FPM_SCAFFOLD_INDEXES[*]} 존재, 총 ${n}개)"
    else
        warn "projects/ 존재하나 필수 인덱스 누락:$missing (총 ${n}개)"
    fi
else
    fail "projects/ 디렉토리 없음"
fi

# ── 5. 운영 필수 파일 (매니페스트 FPM_ORG_FILES — install.sh 와 동일 SSOT) ──
for pair in "${FPM_ORG_FILES[@]}"; do
    real="${pair%%:*}"
    if [[ -f "$REPO_DIR/$real" ]]; then
        ok "운영 파일 존재: $real"
    else
        warn "운영 파일 없음: $real (sh/install.sh 가 ${pair##*:} 예제로 배치)"
    fi
done

# ── 5-2. org 요구 섹션 결손 (Issue407) ────────────────────────
#   파일은 있는데 섹션만 없는 상태는 존재 검사로 안 잡힌다. 구버전 org 로 설치된 사본이
#   여기 걸린다(실측 fg1: Projects.md 는 있으나 `# Project Map` 부재 → 맵 빌더 rc=1).
if declare -p FPM_ORG_SECTIONS >/dev/null 2>&1; then
    for triple in "${FPM_ORG_SECTIONS[@]}"; do
        real="${triple%%:*}"; rest="${triple#*:}"; heads="${rest#*:}"
        [[ -f "$REPO_DIR/$real" ]] || continue
        found=0
        IFS='|' read -r -a _heads <<< "$heads"
        for h in "${_heads[@]}"; do
            if grep -qxF -- "$h" "$REPO_DIR/$real"; then found=1; break; fi
        done
        if [[ "$found" -eq 1 ]]; then
            ok "요구 섹션 존재: $real ← '${heads%%|*}'"
        else
            warn "요구 섹션 없음: $real 에 '${heads%%|*}' 부재 — sh/install.sh 재실행 시 ${rest%%:*} 에서 이식"
        fi
    done
fi

# ── 5-3. 프로젝트 맵 산출물 (Issue407) ────────────────────────
#   gitignore 재생성물이라 부재가 곧 고장은 아니지만, 소스가 성립하는데도 없으면
#   빌더 실패를 의심할 자리다(hub 는 실패를 조용히 삼킨다).
if [[ -n "${FPM_PROJECTS_MAP_OUT:-}" ]]; then
    if [[ -f "$REPO_DIR/$FPM_PROJECTS_MAP_OUT" ]]; then
        ok "프로젝트 맵 산출물 존재: $FPM_PROJECTS_MAP_OUT"
    else
        warn "프로젝트 맵 산출물 없음: $FPM_PROJECTS_MAP_OUT (sh/install.sh 재실행 또는 python3 $FPM_PROJECTS_MAP_BUILDER)"
    fi
fi

# ── 6. cdf 함수 로드 여부 (현재 셸) ───────────────────────────
# check.sh 는 bash 서브셸 → 부모 셸 함수 미상속. fpm.sh 직접 source 후 확인.
# ⚠️ 판정은 **결과(cdf 가 정의됐는가)** 로 한다 — source 의 rc 로 판정하지 않는다.
#    fpm.sh 말미는 `[ -f … ] && . …` 형태라 마지막 test 가 거짓이면(선택 파일 부재)
#    로드는 정상인데 rc=1 이 된다. 종전 `source … && command -v cdf` 는 그 rc 에 단락돼
#    cdf 를 확인조차 못 하고 WARN 을 냈다 (Issue438 — prj3#Issue477 의 "rc 아닌 출력 기준" 과 같은 교훈).
# shellcheck disable=SC1090  # 런타임 동적 경로(매니페스트 유래) — 정적 추적 불가, 의도적
if ( source "$FUNC_FILE" >/dev/null 2>&1; command -v cdf >/dev/null 2>&1 ); then
    ok "cdf 함수 로드 가능 ($FPM_BOOTSTRAP_REL_REPO source)"
else
    warn "cdf 함수 로드 실패 — $FPM_BOOTSTRAP_REL_REPO source 후에도 미정의 (셸 재시작 확인)"
fi

# ── [SCAR] 7~9 ────────────────────────────────────────────────
if [[ "$CHECK_SCAR" -eq 1 ]]; then
    sec "── SCAR (fpm-core 플러그인) ──"
    if ! command -v claude >/dev/null 2>&1; then
        warn "claude CLI 미발견 → SCAR 미설치(셸-only 정상 시나리오). 점검 생략"
    else
        ok "claude CLI 존재: $(command -v claude)"
        # 8) marketplace
        if claude plugin marketplace list 2>/dev/null | grep -qF "$FPM_MKT_NAME"; then
            ok "marketplace 등록: $FPM_MKT_NAME"
        else
            fail "marketplace 미등록: $FPM_MKT_NAME (sh/install.sh 재실행)"
        fi
        # 9) plugin — Issue391: 저작 머신에서는 미설치가 **정상**이므로 FAIL 로 보지 않는다.
        #   저작 머신(jm4)은 `~/.claude` 에 라이브 SCAR 원본을 두고 그것을 직접 쓴다.
        #   여기에 fpm-core 를 설치하면 같은 SCAR 가 이중 등록된다(방증: 타 플러그인도 전부 disabled).
        #   판정 신호는 **`~/.claude/commands/` 의 라이브 SCAR 존재 하나뿐**이다 —
        #   플러그인은 `~/.claude/plugins/{cache,data,marketplaces}/` 로 경로가 분리되므로 섞이지 않는다.
        #   ⚠️ `REPO_DIR == $FPM_BASE` 를 조건에 넣지 말 것: REPO_DIR 은 스크립트 자기 위치라
        #      소비자 머신에서도 항상 참이라 판별력이 0이다(2026-08-17 실측).
        authoring=0
        for _c in "${FPM_SCAR_COMMANDS[@]}"; do
            [[ -f "$HOME/.claude/commands/${_c}.md" ]] && { authoring=1; break; }
        done
        if claude plugin list 2>/dev/null | grep -qF "$FPM_PLUGIN_NAME"; then
            if [[ "$authoring" -eq 1 ]]; then
                warn "플러그인 설치됨: $FPM_PLUGIN_NAME — 그런데 ~/.claude 에 라이브 SCAR 도 있다(이중 등록 의심)"
            else
                ok "플러그인 설치: $FPM_PLUGIN_NAME"
            fi
        elif [[ "$authoring" -eq 1 ]]; then
            ok "플러그인 미설치: $FPM_PLUGIN_NAME — 저작 머신(~/.claude 라이브 SCAR 보유)이므로 정상"
        else
            fail "플러그인 미설치: $FPM_PLUGIN_NAME (claude plugin install)"
        fi
    fi

    # ── 10. SCAR 인벤토리 drift (선언 ↔ 실제 파일 양방향) ──────────
    #   claude CLI 무관 — repo 의 플러그인 소스를 매니페스트 선언과 대조하는 무결성 점검.
    #   plugins/fpm-core/ 부재(셸-only 배포)면 skip.
    sec "── SCAR 인벤토리 drift (선언 ↔ 소스 파일) ──"
    PLUGIN_SRC="$REPO_DIR/$FPM_PLUGIN_SRC_REL_REPO"
    if [[ ! -d "$PLUGIN_SRC" ]]; then
        warn "플러그인 소스 없음: $FPM_PLUGIN_SRC_REL_REPO (셸-only 배포 — drift 점검 생략)"
    else
        # 선언 → 파일 (declared but missing) + 파일 → 선언 (present but undeclared)
        # 3 카테고리: commands/<n>.md · skills/<n>/SKILL.md · agents/<n>.md
        drift_check() {
            local label="$1" subdir="$2" pathfmt="$3"; shift 3
            local declared=("$@") name f actual_missing="" undeclared="" base
            # forward: 선언했는데 파일 없음
            for name in "${declared[@]}"; do
                f="$PLUGIN_SRC/$subdir/${pathfmt/\{n\}/$name}"
                [[ -e "$f" ]] || actual_missing="$actual_missing $name"
            done
            # reverse: 파일 있는데 선언 누락
            if [[ "$subdir" == "skills" ]]; then
                for d in "$PLUGIN_SRC/skills"/*/; do
                    [[ -d "$d" ]] || continue
                    base="$(basename "$d")"
                    printf ' %s ' "${declared[*]}" | grep -qF " $base " || undeclared="$undeclared $base"
                done
            else
                for f in "$PLUGIN_SRC/$subdir"/*.md; do
                    [[ -e "$f" ]] || continue
                    base="$(basename "$f" .md)"
                    printf ' %s ' "${declared[*]}" | grep -qF " $base " || undeclared="$undeclared $base"
                done
            fi
            if [[ -z "$actual_missing" && -z "$undeclared" ]]; then
                ok "$label: 선언 ${#declared[@]}개 ↔ 소스 일치"
            else
                [[ -n "$actual_missing" ]] && fail "$label: 선언했으나 소스 파일 없음 →$actual_missing (파일 삭제/rename? 매니페스트 갱신)"
                [[ -n "$undeclared" ]] && fail "$label: 소스에 있으나 매니페스트 미선언 →$undeclared (FPM_SCAR_${label} 에 추가)"
            fi
        }
        drift_check "COMMANDS" "commands" "{n}.md"        "${FPM_SCAR_COMMANDS[@]}"
        drift_check "SKILLS"   "skills"   "{n}/SKILL.md"  "${FPM_SCAR_SKILLS[@]}"
        drift_check "AGENTS"   "agents"   "{n}.md"        "${FPM_SCAR_AGENTS[@]}"
    fi
else
    sec "── SCAR 점검 생략 (--no-scar) ──"
fi

# ── 10b. hook 이중 등록 가드 (Issue241) ───────────────────────────────────────
#   배경: fpm hook 은 두 경로로 등록됨 — (a) ~/.claude/settings.json 수동 블록(원작자 환경),
#   (b) fpm-core 플러그인 hooks/hooks.json(배포 표준). Claude Code 는 두 소스를 dedup 없이
#   합집합 머지하므로 둘 다 활성이면 동일 hook 이 한 이벤트에 2회 실행됨(알림 중복·HTML 2회 렌더).
#   claude CLI·repo 무관 — 설치 상태 파일(settings.json/installed_plugins.json)을 직독하는 진단.
sec "── hook 이중 등록 가드 ──"
SETTINGS_FILE="$HOME/.claude/settings.json"
INSTALLED_FILE="$HOME/.claude/plugins/installed_plugins.json"
manual_hooks=0
if [[ -f "$SETTINGS_FILE" ]]; then
    #   ⚠️ fpm- 뿐 아니라 fbot- 도 센다 (prj3#Issue453) — 핀봇 훅(출근·퇴근·heartbeat·
    #      Agent 결속)이 플러그인 hooks.json 으로 배선되면서 settings.json 수동 블록과
    #      이중 발화할 수 있는 대상이 되었다. 원 가드는 fpm- 만 봐서 이 4종을 못 잡았다.
    manual_hooks="$(grep -cE '\.claude/hooks/(fpm|fbot)-' "$SETTINGS_FILE" 2>/dev/null || true)"
    manual_hooks="${manual_hooks:-0}"
fi
plugin_active=0
if [[ -f "$INSTALLED_FILE" ]] && grep -qF "\"$FPM_PLUGIN_NAME@" "$INSTALLED_FILE" 2>/dev/null; then
    plugin_active=1
fi
if [[ "$manual_hooks" -gt 0 && "$plugin_active" -eq 1 ]]; then
    fail "hook 이중 등록: settings.json 수동 fpm/fbot hook ${manual_hooks}개 + $FPM_PLUGIN_NAME 플러그인 동시 활성 → 동일 hook 2회 실행. 한쪽만 유지 (플러그인 단일화 권장: settings.json 의 fpm hook 블록 삭제)"
elif [[ "$manual_hooks" -gt 0 ]]; then
    ok "hook 단일 등록: settings.json 수동 ${manual_hooks}개 (플러그인 미설치 — 이중 등록 없음)"
elif [[ "$plugin_active" -eq 1 ]]; then
    ok "hook 단일 등록: $FPM_PLUGIN_NAME 플러그인 (수동 settings 블록 없음 — 이중 등록 없음)"
else
    warn "fpm hook 미등록: settings.json 수동 블록·$FPM_PLUGIN_NAME 플러그인 모두 없음 (hub/dashboard hook 비활성)"
fi

# ── 저작 머신 판별 (prj3#Issue452) — 항목 11·12 공용 ────────────────────────────
#   왜 필요한가 (2026-08-28 fg1 실측): 항목 11·12 는 **저작 머신 전용 검사**인데
#   소비자에서도 돌아 FAIL 2건을 영구히 냈다. 거짓 경고는 진짜 경고를 묻는다.
#     * 11 — 소비자는 `_doc_arch/` 가 publishable policy 의 exclude 라 **애초에 못 받는다**.
#            선언에는 있고 디스크엔 없으니 구조적으로 FAIL 이다(자산 집합이 경로별로 다름)
#     * 12 — prj3 **원본**과 대조하는데 소비자에는 원본이 없다. `~/.claude` 는 설치본이라
#            표류로 잡히는 것이 당연하다
#   판정 신호는 항목 9(Issue391)와 같다 — `~/.claude/commands/` 의 라이브 SCAR 존재 하나뿐.
#   ⚠️ `REPO_DIR == $FPM_BASE` 는 판별력 0(소비자에서도 참) — 조건에 넣지 말 것.
#   🔴 조건이 **둘**이다 (2026-08-29 실측으로 추가) — 머신만 보면 부족하다.
#      저작 머신에서 **미러 repo**(`~/_git/__all/fpm`)를 대상으로 돌리면 머신 판별은 참인데
#      대상은 sanitize 파생물이라 항목 11·12·13 이 **거짓 FAIL 3건**을 냈다(실측).
#      "저작 머신인가" 와 "이 repo 가 정본인가" 는 별개 축이므로 둘 다 본다.
#      정본 신호는 `_doc_arch/` — publishable exclude 라 미러·소비자에는 **구조적으로 없다**.
#      (`REPO_DIR == $FPM_BASE` 는 여전히 금지 — 소비자에서도 참이라 판별력 0)
fpm_is_authoring() {
    [[ -d "$REPO_DIR/_doc_arch" ]] || return 1     # 이 repo 가 정본인가
    local _c
    for _c in "${FPM_SCAR_COMMANDS[@]}"; do
        [[ -f "$HOME/.claude/commands/${_c}.md" ]] && return 0   # 이 머신이 저작 머신인가
    done
    return 1
}

# ── 11. flat_file 페이로드 drift (선언 ↔ 디스크 양방향, Issue240_3) ─────────
#   원격 ~/.claude 플랫파일 배포 인벤토리(FPM_FLATFILE_FILES) ↔ 실제 소스 디렉토리 대조.
#   claude CLI 무관·--no-scar 무관(repo 무결성). 소스 디렉토리 부재면 skip.
if [[ -n "${FPM_FLATFILE_SRC_REL_REPO:-}" && ${#FPM_FLATFILE_FILES[@]} -gt 0 ]] && fpm_is_authoring; then
    sec "── flat_file 페이로드 drift (선언 ↔ 디스크) ──"
    FF_SRC="$REPO_DIR/$FPM_FLATFILE_SRC_REL_REPO"
    if [[ ! -d "$FF_SRC" ]]; then
        warn "flat_file 소스 없음: $FPM_FLATFILE_SRC_REL_REPO (배포 소스 미보유 — drift 점검 생략)"
    else
        ff_missing="" ff_undecl=""
        # forward: 선언했는데 디스크 없음
        for rel in "${FPM_FLATFILE_FILES[@]}"; do
            [[ -e "$FF_SRC/$rel" ]] || ff_missing="$ff_missing $rel"
        done
        # reverse: 디스크에 있는데 선언 누락
        declared_blob=" ${FPM_FLATFILE_FILES[*]} "
        while IFS= read -r rel; do
            printf '%s' "$declared_blob" | grep -qF " $rel " || ff_undecl="$ff_undecl $rel"
        done < <(cd "$FF_SRC" && find . -type f | sed 's|^\./||' | sort)
        if [[ -z "$ff_missing" && -z "$ff_undecl" ]]; then
            ok "flat_file: 선언 ${#FPM_FLATFILE_FILES[@]}개 ↔ 디스크 일치"
        else
            [[ -n "$ff_missing" ]] && fail "flat_file: 선언했으나 디스크 없음 →$ff_missing (삭제/rename? scar-manifest.yml 갱신 후 gen 재실행)"
            [[ -n "$ff_undecl" ]] && fail "flat_file: 디스크에 있으나 yml 미선언 →$ff_undecl (scar-manifest.yml payloads.flat_file.files 에 추가 후 gen 재실행)"
        fi
    fi
fi

# ── 12. flat_file 사본 ↔ prj3 원본 drift (Issue388) ───────────
#   항목11 은 **선언 ↔ 사본**만 본다. 사본은 prj3(~/.claude) 글로벌 SCAR 의 복사물이므로
#   원본이 바뀌면 사본은 조용히 늙는데, 매니페스트와 사본이 같이 늙으면 항목11 은 서로
#   일치해서 PASS 를 낸다 — 원본을 보는 눈이 없었던 것이 표류를 몇 달 방치한 원인이다.
#   (2026-08-16 실측: 29개 중 원본과 일치한 것은 1개, 10개는 원본에 그 경로가 없었음)
#   판정은 sh/scar-flatfile-sync.sh --check 에 위임한다 — 사본 재생성과 판정 로직이
#   갈라지면 "검사는 통과하는데 재생성하면 바뀌는" 상태가 다시 생긴다.
if [[ -x "$REPO_DIR/sh/scar-flatfile-sync.sh" ]] && fpm_is_authoring; then
    sec "── flat_file 사본 ↔ prj3 원본 drift ──"
    if [[ ! -d "$HOME/.claude" ]]; then
        warn "prj3 원본 없음: ~/.claude (이 머신은 SCAR 원본 미보유 — 사본 표류 점검 생략)"
    elif ff_out="$(bash "$REPO_DIR/sh/scar-flatfile-sync.sh" --check 2>&1)"; then
        ok "flat_file 사본: prj3 원본과 일치"
    else
        fail "flat_file 사본이 prj3 원본과 표류 — 해소: sh/scar-flatfile-sync.sh"
        printf '%s\n' "$ff_out" | sed 's/^/        /'
    fi
fi

# ── 12-2. 번들 hooks 사본 ↔ prj3 원본 drift (Issue412) ────────
#   항목 12 의 hooks 판(flat_file 이 아니라 plugin 페이로드). 왜 별도인가:
#   `scar:` 인벤토리는 commands·skills·agents 만 열거했고 파일 규약(`<name>.md`)이 달라
#   hooks 는 **애초에 대조 대상이 아니었다**. 그 사이 구멍이 셋 있었다 —
#     ① 번들에서 훅이 사라져도 무신호(bundle-sync 는 번들 디렉토리를 순회하므로)
#     ② 미선언 훅(인벤토리 SSOT 결손)
#     ③ prj3 에 원본이 없는 훅이 "번들 전용" 인지 "폐기된 훅의 잔재" 인지 판정 근거 부재
#   판정은 sh/scar-hooks-check.sh 에 위임한다 — 항목 12 와 같은 구조(검사 로직을
#   check.sh 에 복제하면 매니페스트 파싱이 두 벌이 되어 갈라진다).
if [[ -x "$REPO_DIR/sh/scar-hooks-check.sh" ]] && fpm_is_authoring; then
    sec "── 번들 hooks 사본 ↔ prj3 원본 drift ──"
    if hk_out="$(bash "$REPO_DIR/sh/scar-hooks-check.sh" --quiet 2>&1)"; then
        ok "번들 hooks: 선언 ↔ 디스크 ↔ prj3 원본 일치"
    else
        fail "번들 hooks 표류 — 상세·조치는 아래"
        printf '%s\n' "$hk_out" | sed 's/^/        /'
    fi
fi

# ── 에디터 어댑터·런처 (Issue327) ─────────────────────────────
if [[ -f "$REPO_DIR/sh/fpm_editors.sh" ]]; then
    ok "sh/fpm_editors.sh 존재"
    grep -q 'fpm_editors.sh' "$REPO_DIR/sh/fpm.sh" \
        && ok "fpm.sh 가 fpm_editors.sh 를 source" \
        || fail "fpm.sh 에 fpm_editors.sh source 라인 없음 → 런처(v/z) 미정의"
    [[ -f "$REPO_DIR/data/editor.yml" ]] \
        && ok "data/editor.yml 존재" \
        || fail "data/editor.yml 없음 (data/editor_org.yml 복사 필요)"
    # CLI 해석 — enabled_editors 각각. 미설치 에디터는 WARN(환경 의존)
    _ed_list=$(grep -E '^[[:space:]]*enabled_editors[[:space:]]*:' "$REPO_DIR/data/editor.yml" 2>/dev/null \
        | sed -E 's/^[^:]*:[[:space:]]*//; s/[[:space:]]*#.*$//' | tr ',' ' ')
    for _ed in ${_ed_list:-vscode}; do
        if ( export FPM_BASE="$REPO_DIR"; . "$REPO_DIR/sh/fpm_editors.sh" >/dev/null 2>&1; _fpm_editor_bin "$_ed" >/dev/null 2>&1 ); then
            ok "에디터 CLI 해석: $_ed"
        else
            warn "에디터 CLI 미발견: $_ed (미설치이거나 data/editor.yml 의 bin_${_ed} 지정 필요)"
        fi
    done
    # 개인 dotfile 잔존 가드 — alias 가 남아 있으면 fpm 함수를 가림
    if grep -qE "^[[:space:]]*alias[[:space:]]+(v|z|zn|za|zw)=" "$HOME/.zsh_aliases" 2>/dev/null; then
        warn "~/.zsh_aliases 에 v/z 계열 alias 잔존 — fpm 런처를 가림. 제거 권장(Issue327)"
    fi
else
    fail "sh/fpm_editors.sh 없음 — 경로 런처(v/z) 미제공"
fi

# ── 13. 설치본 무결성 대조 (prj3#Issue457) ────────────────────────────────────
#   왜 필요한가 (fg1 실측 2026-08-28): 어긋남 ②형 — **"같은 번호, 다른 내용"** —
#   은 번호 비교로 **원리적으로 탐지 불가**하다. `plugin update` 가 버전이 같아 갱신을
#   건너뛰므로 소비자는 영원히 구버전에 머문다. 실제로 마켓 `0.5.5` 이름표 아래
#   8/23 내용물이 있었고(hooks md5 불일치·파일 부재) 어떤 경고도 나지 않았다.
#
#   해법은 **내용 해시 대조**뿐이다. 번들 안의 `.fpm-integrity.json`(생성:
#   sh/gen-integrity-manifest.sh, publish 직전)과 설치본 실물 sha256 을 비교한다.
#
#   🔴 검사 범위는 **fpm-core 하나**다 — prj20 마켓은 7개 플러그인 공유이고 각자 버전이
#      다르다. 매니페스트가 fpm-core 번들 **안**에 있고 그 안의 상대경로만 열거하므로
#      타 플러그인(fBanner·fBoard 등)은 **구조적으로 검사 대상이 아니다**.
sec "── 설치본 무결성 (fpm-core 내용 해시) ──"
INTEGRITY_SRC=""
INTEGRITY_KIND=""
# 🔴 활성 설치본은 **installed_plugins.json 의 installPath** 가 정본이다 (2026-08-29 fg1 실측).
#   캐시에는 구버전 디렉토리가 그대로 쌓인다(fg1: 0.3.6·0.4.0·0.5.6·0.5.7 4개 공존).
#   glob 순회로 첫 매치를 잡으면 **활성본이 아닌 것**을 검사해 엉뚱한 FAIL 을 낸다 —
#   실제로 0.5.7 이 활성인데 0.5.6 을 집어 거짓 불일치를 냈다.
_installed_json="$HOME/.claude/plugins/installed_plugins.json"
if [[ -f "$_installed_json" ]]; then
    _active="$(python3 -c '
import json,sys
try:
    d=json.load(open(sys.argv[1]))
except Exception:
    sys.exit(0)
for k,v in (d.get("plugins") or {}).items():
    if k.split("@")[0]==sys.argv[2]:
        for e in (v if isinstance(v,list) else [v]):
            p=e.get("installPath")
            if p: print(p); sys.exit(0)
' "$_installed_json" "$FPM_PLUGIN_NAME" 2>/dev/null || true)"
    [[ -n "$_active" && -f "$_active/.fpm-integrity.json" ]] && { INTEGRITY_SRC="$_active"; INTEGRITY_KIND="installed"; }
fi
# 폴백: ① 마켓 클론(플러그인 미설치 소비자) ② repo 번들(저작 머신)
#   ⚠️ 대상이 무엇인지를 **기록**한다 (Issue413 ②) — 세 후보는 검사의 **의미가 다르다**.
#      installed·market 은 "발행본과 같은가"(무결성)를 묻지만, repo 번들은 설치본이 아니라
#      **발행 대기 소스**다. 저작 머신에는 설치본이 아예 없다(항목 14 가 "플러그인 미등록"
#      으로 이미 판정한다). 검사 대상이 없는 곳에서 무결성 FAIL 을 내는 것이 상시 FAIL 의
#      절반이었다 — 나머지 절반은 아래 "발행 대기" 판정이 담당한다.
if [[ -z "$INTEGRITY_SRC" ]]; then
    _mkt_clone="$HOME/.claude/plugins/marketplaces/$FPM_MKT_NAME/$FPM_PLUGIN_NAME"
    if [[ -f "$_mkt_clone/.fpm-integrity.json" ]]; then
        INTEGRITY_SRC="$_mkt_clone"; INTEGRITY_KIND="market"
    elif [[ -f "$REPO_DIR/$FPM_PLUGIN_SRC_REL_REPO/.fpm-integrity.json" ]]; then
        INTEGRITY_SRC="$REPO_DIR/$FPM_PLUGIN_SRC_REL_REPO"; INTEGRITY_KIND="bundle"
    fi
fi

if [[ -z "$INTEGRITY_SRC" ]]; then
    warn "무결성 매니페스트 부재(.fpm-integrity.json) — 구버전 설치본이거나 미발행. 'sh/gen-integrity-manifest.sh' 후 재발행 필요"
else
    _int_out="$(python3 - "$INTEGRITY_SRC" <<'PYEOF'
import hashlib, json, os, sys
root = sys.argv[1]
man = json.load(open(os.path.join(root, '.fpm-integrity.json')))
EXCLUDE_NAMES = {'.fpm-integrity.json', '.DS_Store'}
EXCLUDE_DIRS  = {'.git', '__pycache__', 'node_modules', '.pytest_cache'}
EXCLUDE_SUFFIX = ('.pyc', '.pyo', '.log', '.tmp')

def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for c in iter(lambda: fh.read(1 << 20), b''):
            h.update(c)
    return h.hexdigest()

actual = {}
for r, dirs, files in os.walk(root):
    dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
    for f in files:
        if f in EXCLUDE_NAMES or f.endswith(EXCLUDE_SUFFIX):
            continue
        full = os.path.join(r, f)
        if os.path.islink(full) or not os.path.isfile(full):
            continue
        # ⚠️ Windows 는 os.sep 이 '\\' 라 relpath 가 `agents\\x.md` 를 낸다. 매니페스트 키는
        #    항상 '/' 이므로 정규화하지 않으면 **전건이 missing + 전건이 extra** 로 잡힌다
        #    (jpc1 실측 2026-08-31: 누락 10 + 매니페스트에 없는 파일 108). 설계 W3 의 또 다른 발현.
        actual[os.path.relpath(full, root).replace(os.sep, '/')] = sha256(full)

exp = man.get('files', {})
changed = sorted(k for k in set(exp) & set(actual) if exp[k] != actual[k])
missing = sorted(set(exp) - set(actual))
extra   = sorted(set(actual) - set(exp))
bad = len(changed) + len(missing)
print('VERSION\t%s\t%s' % (man.get('version', '?'), (man.get('git_sha') or '?')[:8]))
print('COUNT\t%d\t%d\t%d\t%d' % (len(exp), len(changed), len(missing), len(extra)))
for k in changed[:10]: print('CHANGED\t%s' % k)
for k in missing[:10]: print('MISSING\t%s' % k)
for k in extra[:5]:    print('EXTRA\t%s' % k)
sys.exit(1 if bad else 0)
PYEOF
)" && _int_rc=0 || _int_rc=$?
    _ver="$(printf '%s' "$_int_out" | awk -F'\t' '$1=="VERSION"{print $2" ("$3")"}')"
    _cnt="$(printf '%s' "$_int_out" | awk -F'\t' '$1=="COUNT"{print $2}')"
    # ── 발행 대기 판정 (Issue413 ③) ───────────────────────────────────────────
    #   repo 번들에서 매니페스트보다 **버전이 앞선** 것은 표류가 아니라 **정상적인 미발행**
    #   상태다. `forward` 의 자동 patch bump 가 커밋마다 번들 plugin.json 을 갱신하므로,
    #   발행 직후 아무 커밋이나 하면 즉시 이 상태가 된다 — 그것을 FAIL 로 내면 항목 13 은
    #   **상시 FAIL** 이 되고, 상시 FAIL 은 진짜 표류를 묻는다(이 검사가 존재하는 이유를
    #   무력화한다). 2026-08-29 실측 루프: 0.6.6 발행 → 커밋 → 0.6.7 bump → FAIL →
    #   0.6.7 발행 → 커밋 → 0.6.8 … 수렴하지 않았다.
    #   ⚠️ **버전이 같은데 내용이 다른 것(②형)은 여전히 FAIL 이다** — 그것만이 진짜 표류다.
    _bundle_ver=""
    if [[ "$INTEGRITY_KIND" == "bundle" ]]; then
        _bundle_ver="$(python3 -c 'import json,sys
try: print(json.load(open(sys.argv[1]))["version"])
except Exception: pass' "$INTEGRITY_SRC/.claude-plugin/plugin.json" 2>/dev/null || true)"
    fi
    _man_ver="$(printf '%s' "$_int_out" | awk -F'\t' '$1=="VERSION"{print $2}')"
    # 버전 bump 로만 달라지는 파일 — 번들 안에서 write_version_files 가 건드리는 유일한 대상
    _verfile=".claude-plugin/plugin.json"
    #   EXTRA(매니페스트에 없는 파일)도 저작 번들에서는 **미발행 신규 파일**이다 —
    #   소비자에서의 "로컬 추가물" 과 의미가 다르므로 대상별로 나눠 센다.
    _real_diff="$(printf '%s' "$_int_out" \
        | awk -F'\t' -v vf="$_verfile" '($1=="CHANGED" && $2!=vf) || $1=="MISSING"{print $2}')"
    #   ⚠️ 단, 생성기는 **git 미추적 파일을 의도적으로 제외**한다(발행은 추적분만 실린다 —
    #      ex: `vscode-ext/*.vsix` 빌드 산출물). 그것까지 미발행으로 세면 저작 머신에서
    #      영구 경고가 되고, 영구 경고는 진짜 경고를 묻는다. 추적분만 미발행으로 센다.
    if [[ "$INTEGRITY_KIND" == "bundle" ]]; then
        _extra_list="$(printf '%s' "$_int_out" | awk -F'\t' '$1=="EXTRA"{print $2}')"
        if [[ -n "$_extra_list" ]]; then
            _extra_tracked=""
            while IFS= read -r _e; do
                [[ -n "$_e" ]] || continue
                git -C "$INTEGRITY_SRC" ls-files --error-unmatch -- "$_e" >/dev/null 2>&1 \
                    && _extra_tracked="${_extra_tracked}${_extra_tracked:+
}$_e"
            done <<< "$_extra_list"
            [[ -n "$_extra_tracked" ]] && _real_diff="$(printf '%s\n%s' "$_real_diff" "$_extra_tracked" | grep . || true)"
        fi
    fi

    if [[ "$_int_rc" -eq 0 ]]; then
        ok "무결성 일치: fpm-core ${_ver} — ${_cnt}개 파일 sha256 전건 일치 ($INTEGRITY_SRC)"
    elif [[ "$INTEGRITY_KIND" == "bundle" && -n "$_bundle_ver" && -n "$_man_ver" \
            && "$_bundle_ver" != "$_man_ver" && -z "$_real_diff" ]]; then
        ok "발행 대기: 번들 v${_bundle_ver} > 발행본 v${_man_ver} — 미발행 1건(버전 bump). 내용 표류 없음"
    elif [[ "$INTEGRITY_KIND" == "bundle" && -n "$_bundle_ver" && -n "$_man_ver" \
            && "$_bundle_ver" != "$_man_ver" ]]; then
        _n_unpub="$(printf '%s\n' "$_real_diff" | grep -c . || true)"
        warn "발행 대기: 번들 v${_bundle_ver} > 발행본 v${_man_ver} — 미발행 ${_n_unpub}건(아래). 발행: sh/publish-scar.sh 또는 fpm-sync.sh deploy --with-marketplace"
        printf '%s\n' "$_real_diff" | sed 's/^/      미발행: /'
    else
        fail "무결성 불일치: fpm-core ${_ver} — 아래 파일의 내용이 발행본과 다르다 (번호가 같아도 내용이 다른 ②형)"
        printf '%s\n' "$_int_out" | awk -F'\t' '$1=="CHANGED"{print "      변조/구버전: "$2} $1=="MISSING"{print "      누락: "$2}'
        if [[ "$INTEGRITY_KIND" == "bundle" ]]; then
            printf '      → 저작 머신 번들이다. 버전이 같은데 내용이 다르다 = 매니페스트 미갱신.\n'
            printf '        복구: sh/gen-integrity-manifest.sh 후 커밋(발행 직전 재생성이 정상 경로)\n'
        else
            printf '      → 복구: claude plugin update %s  (또는 마켓 재발행)\n' "$FPM_PLUGIN_NAME"
        fi
    fi
    # EXTRA 는 소비자 로컬 추가물일 수 있어 FAIL 로 올리지 않는다(거짓 경고 억제 — prj3#Issue452 교훈)
    #   저작 번들에서는 위 "발행 대기" 판정이 이미 미발행분으로 합산해 보고했으므로 중복 경고하지 않는다.
    _extra_n="$(printf '%s' "$_int_out" | awk -F'\t' '$1=="COUNT"{print $5}')"
    if [[ "${_extra_n:-0}" -gt 0 && "$INTEGRITY_KIND" != "bundle" ]]; then
        warn "매니페스트에 없는 파일 ${_extra_n}건(설치본 추가물 — 로컬 편집 가능성)"
    fi
fi

# ── 14. 실행본 출처 (prj3#Issue461) ───────────────────────────────────────────
#   왜 필요한가 (fg1 실측 2026-08-29): fg1 은 **봇 카드를 모르는 구버전 hub** 를 오래
#   돌리고 있었고 아무도 몰랐다. 원인은 브랜치였다 — `develop` 체크아웃인데 그 기능은
#   `main` 에만 있었다. 그런데 *"지금 여기서 무엇이 도는가"* 를 묻는 수단이 없어
#   브랜치 대조·payload 실측·플러그인 캐시 grep 을 **각각** 돌려야 했다.
#   검증 환경에서 버전을 모르면 "작동한다" 는 판정도 무효다.
#
#   항목 13 과의 분담: 13 은 **내용 해시**(같은 번호 다른 내용)를, 14 는 **출처**(어느
#   repo·브랜치·커밋에서 왔나)를 본다. 13 이 통과해도 브랜치가 엉뚱하면 소용없다.
#
#   ⚠️ 자동 갱신하지 않는다 — 검증 환경은 **의도한 버전을 고정해 두는 것**도 정당한
#      상태다. 필요한 것은 "무엇이 도는지 안다" 이지 "항상 최신이다" 가 아니다.
sec "── 실행본 출처 (repo·hub·플러그인) ──"

# ① repo 브랜치·HEAD — 오늘 문제의 진원지
if git -C "$REPO_DIR" rev-parse --git-dir >/dev/null 2>&1; then
    _br="$(git -C "$REPO_DIR" rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')"
    _head="$(git -C "$REPO_DIR" rev-parse --short HEAD 2>/dev/null || echo '?')"
    _dirty=""
    [[ -n "$(git -C "$REPO_DIR" status --porcelain 2>/dev/null | head -1)" ]] && _dirty=" · 작업트리 변경 있음"
    # origin 대비 위치. fetch 는 하지 않는다(네트워크 비용·오프라인 대비) — 마지막 fetch 기준.
    _lr="$(git -C "$REPO_DIR" rev-list --left-right --count "HEAD...origin/$_br" 2>/dev/null || true)"
    if [[ -n "$_lr" ]]; then
        _ahead="${_lr%%	*}"; _behind="${_lr##*	}"
        if [[ "$_behind" != "0" ]]; then
            warn "repo: $_br @ $_head — origin/$_br 보다 $_behind 커밋 뒤짐 (마지막 fetch 기준)$_dirty"
        else
            ok "repo: $_br @ $_head (ahead $_ahead)$_dirty"
        fi
    else
        warn "repo: $_br @ $_head — origin/$_br 미확인(원격 추적 없음 또는 미fetch)$_dirty"
    fi
else
    warn "repo: git 저장소가 아님 ($REPO_DIR) — 출처 판정 불가"
fi

# ② hub 서버 실행본 — 이 repo 것을 돌리는가
#   hub 는 플러그인 캐시가 아니라 **repo 파일을 직접 실행**한다. 즉 같은 저장소인데
#   훅과 반영 시점이 다르다. 그 차이가 오늘 오진의 원인이었으므로 명시적으로 본다.
# ⚠️ pgrep 을 쓰지 않는다 — macOS 의 BSD pgrep 은 `-a` 를 지원하지 않아 **PID 만** 낸다
#   (2026-08-29 jm4 실측: 매칭은 되는데 커맨드라인이 빈 문자열이라 경로 판정이 통째로 빗나갔다).
#   `ps -eo pid,command` 는 macOS·Linux 양쪽에서 같은 형태로 나온다.
_hub_line="$(ps -eo pid,command 2>/dev/null | grep 'services/hub/server\.py' | grep -v grep | head -1 || true)"
if [[ -z "$_hub_line" ]]; then
    ok "hub 서버: 미기동 (실행본 판정 대상 아님)"
else
    _hub_path="$(printf '%s' "$_hub_line" | grep -o '[^ ]*services/hub/server\.py' | head -1)"
    # 상대경로로 떠 있으면(cwd 기준 실행) 절대경로를 알 수 없다 — 그 사실을 그대로 말한다.
    case "$_hub_path" in
        /*) if [[ "$_hub_path" == "$REPO_DIR"/* ]]; then
                ok "hub 서버: 이 repo 실행본 ($_hub_path)"
            else
                warn "hub 서버: **다른 경로** 실행본 ($_hub_path) — 이 repo($REPO_DIR) 수정은 반영되지 않는다"
            fi ;;
        *)  warn "hub 서버: 상대경로로 기동돼 실행본 경로 불명 ($_hub_path) — 절대경로로 재기동 권장" ;;
    esac
fi

# ③④ 플러그인 활성본 + 마켓 소스와의 출처 대조
#   installed_plugins.json 에 gitCommitSha 가 있다. 마켓 clone 의 HEAD 와 비교하면
#   "캐시가 마켓보다 낡음" 을 **번호가 같아도** 잡는다 — plugin update 가 건너뛴 경우다.
_ip="$HOME/.claude/plugins/installed_plugins.json"
_mkt_dir="$HOME/.claude/plugins/marketplaces/$FPM_MKT_NAME"
if [[ ! -f "$_ip" ]]; then
    if fpm_is_authoring; then
        ok "플러그인: 미설치 (저작 머신 — 라이브 SCAR 를 직접 쓴다)"
    else
        warn "플러그인: installed_plugins.json 없음 — SCAR 미설치이거나 경로 변경"
    fi
else
    _pv="$(python3 - "$_ip" "$FPM_PLUGIN_NAME" "$FPM_MKT_NAME" <<'PYEOF' 2>/dev/null || true
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    sys.exit(0)
key = "%s@%s" % (sys.argv[2], sys.argv[3])
e = (d.get("plugins", {}).get(key) or [None])[0]
if e:
    print("%s\t%s\t%s" % (e.get("version", "?"), e.get("installPath", "?"), (e.get("gitCommitSha") or "")[:7]))
PYEOF
)"
    if [[ -z "$_pv" ]]; then
        if fpm_is_authoring; then
            # 저작 머신은 ~/.claude 라이브 SCAR 가 정본이다 — 플러그인 설치가 오히려 이례.
            ok "플러그인: $FPM_PLUGIN_NAME 미등록 (저작 머신 — 라이브 SCAR 가 정본)"
        else
            warn "플러그인: $FPM_PLUGIN_NAME@$FPM_MKT_NAME 등록 없음 — 소비자 머신인데 SCAR 가 없다"
        fi
    else
        _ver="${_pv%%	*}"; _rest="${_pv#*	}"
        _path="${_rest%%	*}"; _sha="${_rest##*	}"
        if [[ -d "$_path" ]]; then
            ok "플러그인: $_ver @ ${_sha:-sha없음} ($_path)"
        else
            fail "플러그인: installPath 부재 — $_path (등록 $_ver, 실물 없음)"
        fi
        # 마켓 소스 HEAD 와 대조 — 여기가 fail-loud 지점
        if [[ -n "$_sha" ]] && git -C "$_mkt_dir" rev-parse --git-dir >/dev/null 2>&1; then
            _mkt_head="$(git -C "$_mkt_dir" rev-parse --short HEAD 2>/dev/null || echo '')"
            if [[ -z "$_mkt_head" ]]; then
                warn "마켓 소스: HEAD 확인 불가 ($_mkt_dir)"
            elif [[ "$_mkt_head" == "$_sha"* || "$_sha" == "$_mkt_head"* ]]; then
                ok "마켓 소스 ↔ 활성 캐시: 동일 커밋 ($_mkt_head)"
            else
                # ⚠️ 방향을 단정하지 않는다 — 캐시가 뒤처진 경우가 흔하지만 마켓 clone 이
                #   뒤처진 경우도 실재한다(2026-08-29 검증 중 실측). 단정하면 반대 상황에서 오도한다.
                warn "마켓 소스($_mkt_head) ↔ 활성 캐시($_sha) **불일치** — 캐시가 뒤처졌으면 \`claude plugin update $FPM_PLUGIN_NAME@$FPM_MKT_NAME\`, 마켓이 뒤처졌으면 \`git -C $_mkt_dir pull\`"
            fi
        fi
    fi
fi

# ── 항목 15: 크로스플랫폼 이식성 (Issue429) ──────────────────────
#   왜 검사가 필요한가 — 2026-08-30 하루에 "jm4 에서만 되는" 함정이 셋 나왔다:
#     prj3#Issue475 nvm PATH · prj3#Issue476 BSD date · Issue428 홈 절대경로.
#   셋 다 **조용히 실패**했다(각각 "미설치"·"시간이 안 됐나"·"큐가 좀 늦네" 로 보임).
#   더 나쁜 것은 **규칙이 이미 있었는데 한 곳만 누락**된 경우다 — aoa-mq-enqueue.sh 는
#   "BSD 우선, GNU fallback" 을 주석까지 달고 지켰는데 aoa-mq-tick.sh 만 빠져 있었다.
#   사람의 주의력이 아니라 **검사**가 그것을 잡아야 한다.
printf '\n\033[1m[15] 크로스플랫폼 이식성\033[0m\n'
# ⚠️ 경로 기준은 REPO_DIR(자기 위치, 33행) 이다 — $FPM_BASE 는 rc 가 export 하므로
#    비대화 셸·타 머신에서 미정의일 수 있다. 실제로 fg1 에서 unbound variable 이 나
#    빈 경로로 검색해 **거짓 PASS** 를 냈다(2026-08-30). 이 파일이 검사하는 원칙 2
#    (자기 위치 기준)를 검사 자신이 어긴 셈이다.

# 15-1. BSD 전용 date 에 GNU fallback 이 있는가
_xp_bad=0
while IFS= read -r _f; do
    [[ -f "$_f" ]] || continue
    _bsd=$(grep -cE 'date -j|date -v|DATE" -j|DATE" -v' "$_f" 2>/dev/null || echo 0)
    [[ "$_bsd" -eq 0 ]] && continue
    _gnu=$(grep -cE 'date -d|DATE" -d' "$_f" 2>/dev/null || echo 0)
    if [[ "$_gnu" -eq 0 ]]; then
        fail "BSD 전용 date 에 GNU fallback 없음: ${_f#$REPO_DIR/} — Linux 에서 실패하고 그 실패가 0/빈값으로 둔갑한다"
        _xp_bad=$((_xp_bad+1))
    fi
done < <(grep -rlE 'date -j|date -v|DATE" -j|DATE" -v' --include="*.sh" "$REPO_DIR/scripts" "$REPO_DIR/sh" "$REPO_DIR/mcp" 2>/dev/null)
[[ "$_xp_bad" -eq 0 ]] && ok "BSD date 사용처 전부 GNU fallback 보유"

# 15-2. 배포되는 코드가 홈 절대경로로 짝을 찾는가
#   소비자 머신의 ~/.claude 는 **플러그인 설치본**이라 repo 구조가 없다.
#   자기 위치(REPO_ROOT/__file__) 기준으로 찾아야 한다 — prj3#Issue460·Issue428 처방.
_xp_home=$(grep -rnE 'expanduser\("~/\.claude/(mcp|scripts|sh)/|"\$HOME/\.claude/(mcp|scripts|sh)/' \
    --include="*.py" --include="*.sh" "$REPO_DIR/services" "$REPO_DIR/scripts" "$REPO_DIR/sh" 2>/dev/null \
    | grep -viE 'REPO_ROOT|fallback|후보|candidate|_resolve_' | wc -l | tr -d ' ')
if [[ "${_xp_home:-0}" -gt 0 ]]; then
    warn "홈 절대경로로 실행체를 찾는 지점 ${_xp_home}건 — 소비자 머신엔 그 경로가 없다(자기 위치 기준으로 바꿀 것)"
else
    ok "실행체 경로 해석: 홈 하드코딩 없음"
fi

# 15-3. 이 머신에서 실제로 도는가 (판정이 아니라 실행)
if [[ -f "$REPO_DIR/mcp/aoa-mq/aoa-mq-tick.sh" ]]; then
    _xp_epoch=$(bash -c '
        DATE=/bin/date
        "$DATE" -j -f "%Y-%m-%dT%H:%M:%S" "2026-01-02T03:04:05" +%s 2>/dev/null \
          || "$DATE" -d "2026-01-02T03:04:05" +%s 2>/dev/null || echo 0')
    if [[ "${_xp_epoch:-0}" -gt 0 ]]; then
        ok "date 파싱 실측 통과 ($(uname -s), epoch=$_xp_epoch)"
    else
        fail "date 파싱이 이 OS 에서 실패 — 예약 큐의 due 판정이 서지 않는다"
    fi
fi

# ── 요약 ──────────────────────────────────────────────────────
printf '\n────────────────────────────────────────────\n'
printf '결과: \033[32mPASS %d\033[0m / \033[33mWARN %d\033[0m / \033[31mFAIL %d\033[0m\n' "$PASS_N" "$WARN_N" "$FAIL_N"
if [[ "$FAIL_N" -gt 0 ]]; then
    printf '\033[31m❌ 설치 불완전 — 위 FAIL 항목 확인 후 sh/install.sh 재실행\033[0m\n'
    printf '────────────────────────────────────────────\n'
    exit 1
else
    if [[ "$WARN_N" -gt 0 ]]; then
        printf '\033[33m✅ 핵심 설치 정상 (WARN 항목은 선택/환경 의존)\033[0m\n'
    else
        printf '\033[32m✅ 설치 정상 — 전 항목 PASS\033[0m\n'
    fi
    printf '────────────────────────────────────────────\n'
    exit 0
fi
