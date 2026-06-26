#!/usr/bin/env bash
# release-check.sh — fpm 공개 배포 전 통합 검증 게이트 (Issue211, 영역 A~E 자동분)
#
# 단일 진입점. 3 스테이지를 묶어 자동 검증 영역을 일괄 실행한다:
#   [1] 단위/회귀 (B·C·D): services/hub/test_*.py 전수 (allowlist·control·tombstone·
#       feed·i18n·settings 등) — exit code 집계
#   [2] 공개 게이트 (E):    scripts/test_publish_gates.sh (guard·dir-gate·sanitize·
#       secret-scan 양/음성 + 정책 일관성)
#   [3] 샌드박스 설치 (A):  임시 HOME(mktemp)에서 install→check→uninstall→check.
#       실 ~/.zshrc·~/.info·~/.claude 미오염. SCAR 는 --no-scar(실환경 위험 회피).
#   [4] 공개 미러 (A-4·E-4): scripts/test_mirror_install.sh — forward dry-run 재현
#       (git archive→sanitize→exclude→gates) + 미러 사본 install + org 복원.
#
# 설계 SSOT: _doc_arch/fpm-release-test.md / plan: _doc_work/plan/fpm-release-test_plan.md
#
# 사용: bash sh/release-check.sh            전체 (1+2+3)
#       bash sh/release-check.sh --no-sandbox  스테이지3 생략 (단위+게이트만)
#       bash sh/release-check.sh --quiet       서브 출력 숨김, 스테이지 요약만
# exit: 0=자동 영역 전부 PASS(WARN/SKIP 허용), 1=하나 이상 FAIL
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"

SANDBOX=1; QUIET=0
for a in "$@"; do
    case "$a" in
        --no-sandbox) SANDBOX=0 ;;
        --quiet|-q)   QUIET=1 ;;
        -h|--help) echo "usage: sh/release-check.sh [--no-sandbox] [--quiet]"; exit 0 ;;
        *) echo "[fpm] 알 수 없는 인자: $a (무시)" >&2 ;;
    esac
done

STAGE_FAIL=0
hr()  { printf '════════════════════════════════════════\n'; }
run() { if [ "$QUIET" -eq 1 ]; then "$@" >/dev/null 2>&1; else "$@"; fi; }

# ── 스테이지 1: 단위/회귀 (B·C·D) ────────────────────────────────
hr; echo "[1/3] 단위·회귀 테스트 (services/hub/test_*.py)"; hr
unit_fail=0
for t in "$REPO"/services/hub/test_*.py; do
    [ -f "$t" ] || continue
    name="$(basename "$t")"
    if run env python3 "$t"; then
        [ "$QUIET" -eq 1 ] && printf '  PASS %s\n' "$name"
    else
        printf '  \033[31mFAIL\033[0m %s\n' "$name"; unit_fail=$((unit_fail+1))
    fi
done
[ "$unit_fail" -eq 0 ] && echo "→ 스테이지1 PASS" || { echo "→ 스테이지1 FAIL ($unit_fail)"; STAGE_FAIL=$((STAGE_FAIL+1)); }

# ── 스테이지 2: 공개 게이트 (E) ──────────────────────────────────
hr; echo "[2/3] 공개 게이트 (scripts/test_publish_gates.sh)"; hr
if run bash "$REPO/scripts/test_publish_gates.sh"; then
    echo "→ 스테이지2 PASS"
else
    echo "→ 스테이지2 FAIL"; STAGE_FAIL=$((STAGE_FAIL+1))
fi

# ── 스테이지 3: 샌드박스 설치/제거 (A) ───────────────────────────
if [ "$SANDBOX" -eq 1 ]; then
    hr; echo "[3/4] 샌드박스 install→check→uninstall→check (--no-scar)"; hr
    SBX="$(mktemp -d)"
    trap 'rm -rf "$SBX"' EXIT
    sb_fail=0
    # 격리 HOME. install.sh 가 $HOME/.zshrc·$HOME/.info 에만 쓰도록 제한.
    sb() { run env HOME="$SBX" bash "$1" "${@:2}"; }

    MARKER="# >>> fpm functions >>>"

    : > "$SBX/.zshrc"   # install 이 append 할 rc 시드
    if sb "$REPO/sh/install.sh" --no-scar; then echo "  install PASS"; else echo "  install FAIL"; sb_fail=$((sb_fail+1)); fi
    if sb "$REPO/sh/check.sh" --no-scar; then echo "  check(설치후) PASS"; else echo "  check(설치후) FAIL"; sb_fail=$((sb_fail+1)); fi

    # A-1: 멱등 재실행 — 2번째 install 후 rc 마커 정확히 1개
    if sb "$REPO/sh/install.sh" --no-scar; then echo "  install(멱등 2회차) PASS"; else echo "  install(멱등 2회차) FAIL"; sb_fail=$((sb_fail+1)); fi
    mc="$(grep -cF "$MARKER" "$SBX/.zshrc" 2>/dev/null || echo 0)"
    if [ "$mc" -eq 1 ]; then echo "  멱등: rc 마커 1개 유지 PASS"; else echo "  멱등: rc 마커 ${mc}개(기대 1) FAIL"; sb_fail=$((sb_fail+1)); fi

    if sb "$REPO/sh/uninstall.sh"; then echo "  uninstall PASS"; else echo "  uninstall FAIL"; sb_fail=$((sb_fail+1)); fi
    # 제거 후: check 셸 항목은 FAIL 이 정상 → exit 1 기대. 0 이면 흔적 잔존.
    if sb "$REPO/sh/check.sh" --no-scar; then
        echo "  check(제거후) 예상밖 PASS — 흔적 잔존 의심"; sb_fail=$((sb_fail+1))
    else
        echo "  check(제거후) FAIL=정상(흔적 0 수렴)"
    fi

    # A-1: claude CLI 부재 → SCAR graceful skip, exit 0 (셸은 정상 설치).
    #   claude 가 있는 디렉토리만 PATH 에서 제거(나머지 도구 보존). 없으면 케이스 자연 충족.
    claude_bin="$(command -v claude 2>/dev/null || true)"
    SBX2="$(mktemp -d)"; : > "$SBX2/.zshrc"
    if [ -n "$claude_bin" ]; then
        cdir="$(dirname "$claude_bin")"
        noclaude_path="$(printf '%s' "$PATH" | tr ':' '\n' | grep -vxF "$cdir" | paste -sd ':' -)"
    else
        noclaude_path="$PATH"
    fi
    if run env HOME="$SBX2" PATH="$noclaude_path" bash "$REPO/sh/install.sh"; then
        echo "  claude부재 → SCAR skip + exit0 PASS"
    else
        echo "  claude부재 exit≠0 FAIL"; sb_fail=$((sb_fail+1))
    fi
    rm -rf "$SBX2"

    # A-1: 매니페스트 손상 → fail-loud exit 1. install.sh 복사본 + 매니페스트 부재 temp repo.
    BROKEN="$(mktemp -d)"; mkdir -p "$BROKEN/sh"; cp "$REPO/sh/install.sh" "$BROKEN/sh/"
    rc=0; run env HOME="$SBX" bash "$BROKEN/sh/install.sh" --no-scar || rc=$?
    if [ "$rc" -eq 1 ]; then echo "  매니페스트 손상 → exit1 fail-loud PASS"; else echo "  매니페스트 손상 exit=${rc}(기대 1) FAIL"; sb_fail=$((sb_fail+1)); fi
    rm -rf "$BROKEN"

    [ "$sb_fail" -eq 0 ] && echo "→ 스테이지3 PASS" || { echo "→ 스테이지3 FAIL ($sb_fail)"; STAGE_FAIL=$((STAGE_FAIL+1)); }

    # ── 스테이지 4: 공개 미러 dry-run + 설치 (A-4·E-4) ───────────
    hr; echo "[4/4] 공개 미러 dry-run + install (scripts/test_mirror_install.sh)"; hr
    if run bash "$REPO/scripts/test_mirror_install.sh"; then
        echo "→ 스테이지4 PASS"
    else
        echo "→ 스테이지4 FAIL"; STAGE_FAIL=$((STAGE_FAIL+1))
    fi
else
    hr; echo "[3-4/4] 샌드박스·미러 생략 (--no-sandbox)"; hr
fi

# ── 요약 ─────────────────────────────────────────────────────────
hr
if [ "$STAGE_FAIL" -eq 0 ]; then
    echo "✅ release-check: 자동 영역 전부 PASS"
else
    echo "🚨 release-check: $STAGE_FAIL 스테이지 FAIL"
fi
[ "$STAGE_FAIL" -eq 0 ]
