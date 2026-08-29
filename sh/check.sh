#!/usr/bin/env bash
# check.sh — fpm 설치 점검 (읽기 전용, 멱등)
#
# sh/install.sh 가 배치한 흔적을 검사하여 설치 상태를 진단함. 아무것도 변경하지 않음.
# install.sh / uninstall.sh 와 동일하게 data/install_manifest.sh(SSOT) 를 source 하므로,
# 마커·경로·운영파일 목록·SCAR 타깃이 설치 측과 항상 일치(drift 없음).
#
# 검사 항목:
#   [셸]  1. sh/fpm.sh 부트스트랩 파일 존재
#         2. rc(zshrc/bashrc) 에 fpm 마커 블록 + FPM_BASE export
#         3. ~/.info/__pmBasePath.txt → <repo>/projects 일치
#         4. projects/ 스캐폴드 (필수 인덱스)
#         5. 운영 필수 파일 (FPM_ORG_FILES) + 요구 섹션 결손 (FPM_ORG_SECTIONS, Issue407)
#         5-2. 프로젝트 맵 산출물 (FPM_PROJECTS_MAP_OUT, Issue407)
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
# shellcheck disable=SC1090  # 런타임 동적 경로(매니페스트 유래) — 정적 추적 불가, 의도적
if (source "$FUNC_FILE" >/dev/null 2>&1 && command -v cdf >/dev/null 2>&1); then
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
fpm_is_authoring() {
    local _c
    for _c in "${FPM_SCAR_COMMANDS[@]}"; do
        [[ -f "$HOME/.claude/commands/${_c}.md" ]] && return 0
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
    [[ -n "$_active" && -f "$_active/.fpm-integrity.json" ]] && INTEGRITY_SRC="$_active"
fi
# 폴백: ① 마켓 클론(플러그인 미설치 소비자) ② repo 번들(저작 머신)
if [[ -z "$INTEGRITY_SRC" ]]; then
    for _cand in \
        "$HOME/.claude/plugins/marketplaces/$FPM_MKT_NAME/$FPM_PLUGIN_NAME" \
        "$REPO_DIR/$FPM_PLUGIN_SRC_REL_REPO"
    do
        [[ -f "${_cand%/}/.fpm-integrity.json" ]] && { INTEGRITY_SRC="${_cand%/}"; break; }
    done
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
        actual[os.path.relpath(full, root)] = sha256(full)

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
    if [[ "$_int_rc" -eq 0 ]]; then
        ok "무결성 일치: fpm-core ${_ver} — ${_cnt}개 파일 sha256 전건 일치 ($INTEGRITY_SRC)"
    else
        fail "무결성 불일치: fpm-core ${_ver} — 아래 파일의 내용이 발행본과 다르다 (번호가 같아도 내용이 다른 ②형)"
        printf '%s\n' "$_int_out" | awk -F'\t' '$1=="CHANGED"{print "      변조/구버전: "$2} $1=="MISSING"{print "      누락: "$2}'
        printf '      → 복구: claude plugin update %s  (또는 마켓 재발행)\n' "$FPM_PLUGIN_NAME"
    fi
    # EXTRA 는 소비자 로컬 추가물일 수 있어 FAIL 로 올리지 않는다(거짓 경고 억제 — prj3#Issue452 교훈)
    _extra_n="$(printf '%s' "$_int_out" | awk -F'\t' '$1=="COUNT"{print $5}')"
    [[ "${_extra_n:-0}" -gt 0 ]] && warn "매니페스트에 없는 파일 ${_extra_n}건(설치본 추가물 — 로컬 편집 가능성)"
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
