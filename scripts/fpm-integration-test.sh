#!/usr/bin/env bash
# fpm-integration-test.sh — fpm 배포 파이프라인 통합 스모크 (Issue330)
#
# 검증 대상은 저장소 "안" 이 아니라 저장소 "사이" 다:
#   ① ___pm/plugins/fpm-core  →  ② fpm 미러(Finfra/fpm)  →  ④ 소비자 셸(~/_git/fpm)
#                             →  ③ prj20 마켓(f-claude-plugins)  →  ⑤ 소비자 SCAR(claude plugin)
#
# 배경: v0.2.1 배포에서 버전 문자열은 전부 일치했으나 prj20 vendored 사본이 원본과
#       54개 파일 상이했다. 버전 체계가 서로 달라(0.9.1 vs 0.2.1) 번호 비교로는
#       탐지 불가였다. 따라서 내용 diff 를 1급 판정으로 둔다.
#
# 원칙: 읽기 전용. 불일치를 고치지 않고 해소 명령만 출력한다.
# 사용: bash scripts/fpm-integration-test.sh [--host <ssh-host>] [--quiet]
# 종료: 전부 PASS=0 / FAIL 1건 이상=1 (SKIP 은 0 유지)

set -uo pipefail

PM_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MIRROR="${FPM_MIRROR:-$HOME/_git/__all/fpm}"
MKT="${FPM_MARKETPLACE:-$HOME/_git/__all/f-claude-plugins}"
SRC="$PM_ROOT/plugins/fpm-core"
DST="$MKT/fpm-core"

HOST=""
QUIET=0
while [ $# -gt 0 ]; do
  case "$1" in
    --host)  HOST="${2:-}"; shift 2 ;;
    --quiet) QUIET=1; shift ;;
    -h|--help) sed -n '2,20p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "알 수 없는 인자: $1" >&2; exit 2 ;;
  esac
done

FAILED=0
pass() { printf '[%s] %-32s \033[32mPASS\033[0m  %s\n' "$1" "$2" "${3:-}"; }
skip() { printf '[%s] %-32s \033[33mSKIP\033[0m  %s\n' "$1" "$2" "${3:-}"; }
fail() {
  FAILED=$((FAILED+1))
  printf '[%s] %-32s \033[31mFAIL\033[0m  %s\n' "$1" "$2" "${3:-}"
  [ -n "${4:-}" ] && printf '     → 해소: %s\n' "$4"
  return 0
}

# 소비자 머신에서 명령 실행 — zsh -lc 는 .zshrc 를 읽지 않으므로(zsh 는 대화형일 때만
# .zshrc 로드) -ic 를 쓰고, claude 가 사는 ~/.local/bin 을 PATH 에 명시한다.
rexec() { ssh -o ConnectTimeout=8 -o BatchMode=yes "$HOST" "export PATH=\$HOME/.local/bin:\$PATH; $1" 2>/dev/null; }

[ $QUIET -eq 0 ] && {
  echo "fpm 배포 파이프라인 통합테스트 (Issue330)"
  echo "  원본   : $PM_ROOT"
  echo "  미러   : $MIRROR"
  echo "  마켓   : $MKT"
  [ -n "$HOST" ] && echo "  소비자 : $HOST"
  echo "────────────────────────────────────────────────────────────"
}

# ── T1. VERSION 3자 일치 ──────────────────────────────────────────
V_PM="$(cat "$PM_ROOT/VERSION" 2>/dev/null || echo '?')"
V_MIRROR="$(git -C "$MIRROR" show HEAD:VERSION 2>/dev/null || echo '?')"
V_MKT="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['version'])" \
          "$DST/.claude-plugin/plugin.json" 2>/dev/null || echo '?')"
if [ "$V_PM" = "$V_MIRROR" ] && [ "$V_PM" = "$V_MKT" ] && [ "$V_PM" != '?' ]; then
  pass T1 "VERSION 3자 일치" "($V_PM)"
else
  fail T1 "VERSION 3자 일치" "pm=$V_PM mirror=$V_MIRROR mkt=$V_MKT" \
       "bash scripts/fpm-sync.sh deploy <ver> --with-marketplace"
fi

# ── T2. prj20 vendored 내용 정합 (핵심 — 이번 사고 지점) ──────────
# 제외 2종만 허용:
#   .DS_Store              macOS 부산물, 항상 상이
#   .claude-plugin/plugin.json  publish 가 버전을 주입하므로 정상적으로 상이
# 제외를 늘릴수록 본 검사가 무력해진다. 추가 시 반드시 여기에 사유를 남길 것.
if [ -d "$SRC" ] && [ -d "$DST" ]; then
  DIFFS="$(diff -rq "$SRC" "$DST" 2>/dev/null \
           | grep -v -e '\.DS_Store' -e '\.claude-plugin/plugin\.json' || true)"
  N="$(printf '%s' "$DIFFS" | grep -c . || true)"
  if [ "$N" -eq 0 ]; then
    pass T2 "prj20 vendored 내용 정합"
  else
    fail T2 "prj20 vendored 내용 정합" "$N 파일 상이" \
         "bash scripts/fpm-sync.sh publish --push"
    [ $QUIET -eq 0 ] && printf '%s\n' "$DIFFS" | head -5 | sed 's/^/       /'
  fi
else
  skip T2 "prj20 vendored 내용 정합" "경로 부재 ($DST)"
fi

# ── T3. 미러 미push 없음 ──────────────────────────────────────────
if git -C "$MIRROR" rev-parse --git-dir >/dev/null 2>&1; then
  git -C "$MIRROR" fetch -q origin 2>/dev/null
  AHEAD="$(git -C "$MIRROR" rev-list --count origin/main..HEAD 2>/dev/null || echo '?')"
  if [ "$AHEAD" = "0" ]; then
    pass T3 "미러 push 완료"
  else
    fail T3 "미러 push 완료" "ahead=$AHEAD" "git -C $MIRROR push"
  fi
else
  skip T3 "미러 push 완료" "git repo 아님"
fi

# ── T4. prj20 미push 없음 ─────────────────────────────────────────
if git -C "$MKT" rev-parse --git-dir >/dev/null 2>&1; then
  git -C "$MKT" fetch -q origin 2>/dev/null
  AHEAD="$(git -C "$MKT" rev-list --count origin/main..HEAD 2>/dev/null || echo '?')"
  if [ "$AHEAD" = "0" ]; then
    pass T4 "prj20 push 완료"
  else
    fail T4 "prj20 push 완료" "ahead=$AHEAD" "git -C $MKT push"
  fi
else
  skip T4 "prj20 push 완료" "git repo 아님"
fi

# ── T5. 마켓 매니페스트 validate ──────────────────────────────────
if command -v claude >/dev/null 2>&1; then
  if claude plugin validate "$MKT" >/dev/null 2>&1; then
    pass T5 "claude plugin validate"
  else
    fail T5 "claude plugin validate" "검증 실패" "claude plugin validate $MKT"
  fi
else
  skip T5 "claude plugin validate" "claude CLI 부재"
fi

# ── T6. Issue_public digest freshness ─────────────────────────────
if [ -x "$PM_ROOT/scripts/fpm-issue-digest.sh" ]; then
  if bash "$PM_ROOT/scripts/fpm-issue-digest.sh" --check >/dev/null 2>&1; then
    pass T6 "Issue_public digest 최신"
  else
    fail T6 "Issue_public digest 최신" "Issue.md 와 불일치" \
         "bash scripts/fpm-issue-digest.sh && git commit"
  fi
else
  skip T6 "Issue_public digest 최신" "헬퍼 부재"
fi

# ── T7. 번들 drift (prj3 라이브 → ___pm) ──────────────────────────
if [ -x "$PM_ROOT/scripts/fpm-bundle-sync.sh" ]; then
  if bash "$PM_ROOT/scripts/fpm-bundle-sync.sh" --check >/dev/null 2>&1; then
    pass T7 "번들 drift 없음"
  else
    fail T7 "번들 drift 없음" "라이브 SCAR 미반영" \
         "bash scripts/fpm-bundle-sync.sh (또는 deploy 가 자동 수행)"
  fi
else
  skip T7 "번들 drift 없음" "헬퍼 부재"
fi

# ── T8~T10. 소비자 구간 (옵션) ────────────────────────────────────
if [ -z "$HOST" ]; then
  [ $QUIET -eq 0 ] && {
    echo "────────────────────────────────────────────────────────────"
    echo "소비자 검사 생략 — 실행하려면 --host <ssh-host>"
  }
else
  [ $QUIET -eq 0 ] && echo "────────────────────────────────────────────────────────────"
  if ! rexec 'echo ok' | grep -q ok; then
    skip T8 "소비자 셸 VERSION"    "호스트 미응답 ($HOST)"
    skip T9 "소비자 projects 인덱스" "호스트 미응답 ($HOST)"
    skip T10 "소비자 SCAR 정합"     "호스트 미응답 ($HOST)"
  else
    # T8 — 소비자 셸 계층 버전
    RV="$(rexec 'cat ~/_git/fpm/VERSION' | tr -d '[:space:]')"
    if [ "$RV" = "$V_PM" ]; then
      pass T8 "소비자 셸 VERSION" "($RV)"
    else
      fail T8 "소비자 셸 VERSION" "consumer=$RV expected=$V_PM" \
           "ssh $HOST 'git -C ~/_git/fpm pull --ff-only'  (분기 시 재클론 — _doc_arch/fpm-consumer-install.md)"
    fi

    # T9 — projects 인덱스 수 (install.sh 는 0·1 만 만든다. fpm-projects-sync 미실행 탐지)
    # ⚠️ 기준은 소비자 자신의 Projects.md 다. Projects.md 는 머신마다 다르므로
    #    jm4 의 projects/ 개수와 비교하면 정상 상태를 오판한다 (실측: jma 27 vs jm4 44).
    RN="$(rexec 'ls ~/_git/fpm/projects 2>/dev/null | wc -l' | tr -d '[:space:]')"
    EN="$(rexec 'grep -cE "^\| *[0-9]+[a-z]? *\|" ~/_git/fpm/Projects.md' | tr -d '[:space:]')"
    if [ -n "$RN" ] && [ "$RN" = "$EN" ]; then
      pass T9 "소비자 projects 인덱스" "($RN)"
    else
      fail T9 "소비자 projects 인덱스" "consumer=$RN expected=$EN" \
           "ssh $HOST 'cd ~/_git/fpm && FPM_BASE=\$HOME/_git/fpm python3 sh/fpm-projects-sync'"
    fi

    # T10 — SCAR 계층: 버전 + 마켓 한정자 정합
    PL="$(rexec 'claude plugin list 2>/dev/null')"
    if [ -z "$PL" ]; then
      skip T10 "소비자 SCAR 정합" "claude CLI 부재 또는 플러그인 없음"
    else
      PV="$(printf '%s' "$PL" | grep -A1 'fpm-core@' | grep -o '[0-9]\+\.[0-9]\+\.[0-9]\+' | head -1)"
      if ! printf '%s' "$PL" | grep -q 'fpm-core@f-claude-plugins'; then
        fail T10 "소비자 SCAR 정합" "폐기 마켓에서 설치됨" \
             "ssh $HOST 'claude plugin uninstall fpm-core@<old> && claude plugin install fpm-core@f-claude-plugins --scope user'"
      elif [ "$PV" = "$V_PM" ]; then
        pass T10 "소비자 SCAR 정합" "($PV)"
      else
        fail T10 "소비자 SCAR 정합" "plugin=$PV expected=$V_PM" \
             "ssh $HOST 'claude plugin update fpm-core@f-claude-plugins'  (@마켓 한정자 필수)"
      fi
    fi
  fi
fi

echo "────────────────────────────────────────────────────────────"
if [ $FAILED -eq 0 ]; then
  echo "✅ 통합테스트 통과"
  exit 0
else
  echo "❌ 통합테스트 실패 — $FAILED 건"
  exit 1
fi
