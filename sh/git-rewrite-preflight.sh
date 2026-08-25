#!/usr/bin/env bash
# git-rewrite-preflight.sh — 이력 재작성(filter-repo·BFG·rebase -i) 착수 게이트 (Issue395)
#
# 2026-08-17 00:02 실발생: 한 세션이 `git filter-repo --force` 를 돌려 **다른 세션의
# 스테이징된 산출물 3건을 말없이 삭제**했다. filter-repo 는 reflog 를 만료시키고 remote 를
# 제거하므로 통상의 복구 경로(reflog·ORIG_HEAD)가 **동시에** 사라진다. 그중 위임 지시서는
# 미추적이라 git 으로 복구할 수 없었고, 세션 컨텍스트에서 축자 재작성해 겨우 건졌다.
#
# 왜 룰이 아니라 스크립트인가:
#   *"착수 전에 다른 세션 활동을 확인한다"* 는 **판단**이라 새어나간다. 실제 사고에서도
#   `git status` 를 출력은 했으나 **검사하지 않고** --force 로 진행했다. 보이는 것과
#   차단되는 것은 다르다. 그래서 판정을 사람에게서 떼어내 rc 로 만든다.
#
# 검사(전부 fail-loud, 하나라도 걸리면 rc=1):
#   1. git repo 인가
#   2. 작업트리 clean 인가 — **미추적 포함**. filter-repo 는 미추적을 보호하지 않는다
#   3. 이 repo 를 cwd 로 하는 Claude 세션이 둘 이상 최근 활동했는가 (동시 세션)
#   4. 백업 — `git bundle --all` + reflog/status/stash 스냅샷. **실행 직전에** 뜬다
#
# 4번의 타이밍이 핵심이다. 이번 사고 때 Desktop 전체 백업(456M·1409커밋)이 있었는데도
# 유실분을 못 건졌다 — 백업 시점이 그 파일들이 **생기기 전**이었기 때문이다.
# "백업이 있다"가 아니라 "이 순간의 백업이 있다"여야 안전망이 된다.
#
# 사용:
#   bash sh/git-rewrite-preflight.sh                 # 현재 repo 점검
#   bash sh/git-rewrite-preflight.sh --repo <dir>
#   bash sh/git-rewrite-preflight.sh --force         # 차단 무시(사유를 로그에 남김)
#   bash sh/git-rewrite-preflight.sh --no-backup     # 백업 생략(비권장)
#
# rc: 0 = 착수 가능(GO) · 1 = 차단(NO-GO) · 2 = 사용법 오류
set -uo pipefail

REPO=""
BACKUP_DIR=""
FORCE=0
DO_BACKUP=1
# 동시 세션 판정 창(초). 트랜스크립트가 이 시간 안에 갱신됐으면 "활동 중"으로 본다.
ACTIVE_WINDOW=${FPM_REWRITE_ACTIVE_WINDOW:-600}

while [ $# -gt 0 ]; do
  case "$1" in
    --repo)       REPO="${2:-}"; shift 2 ;;
    --backup-dir) BACKUP_DIR="${2:-}"; shift 2 ;;
    --force)      FORCE=1; shift ;;
    --no-backup)  DO_BACKUP=0; shift ;;
    -h|--help)    sed -n '2,30p' "$0"; exit 2 ;;
    *)            echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

FAIL=0
note() { printf '  %s\n' "$*"; }
ok()   { printf '  \033[32mok\033[0m   %s\n' "$*"; }
bad()  { printf '  \033[31mFAIL\033[0m %s\n' "$*"; FAIL=$((FAIL+1)); }
warn() { printf '  \033[33mwarn\033[0m %s\n' "$*"; }

# mtime(epoch). ⚠️ 이 머신은 macOS 인데 PATH 에 GNU coreutils `stat` 이 앞선다 —
# BSD 문법 `stat -f %m` 을 주면 GNU 는 그것을 *파일시스템 조회*로 읽어 마운트 경로를
# 뱉는다. 실패가 아니라 **엉뚱한 성공**이라 `||` fallback 이 안 걸리고, 그 문자열이
# 산술식에 들어가 unbound variable 로 터진다. 그래서 결과를 숫자로 **검증**한다.
_mtime() {
  local m
  m=$(stat -c %Y "$1" 2>/dev/null) || m=""
  case "$m" in (''|*[!0-9]*) m=$(stat -f %m "$1" 2>/dev/null) || m="" ;; esac
  case "$m" in (''|*[!0-9]*) m=0 ;; esac
  printf '%s' "$m"
}

# ISO8601 — BSD date 는 `-Iseconds` 를 모른다. 포맷을 직접 준다
_now_iso() { date +%Y-%m-%dT%H:%M:%S%z; }

# ── 1. repo 확인 ──────────────────────────────────────────────────────────
[ -n "$REPO" ] || REPO="$PWD"
if ! ROOT=$(git -C "$REPO" rev-parse --show-toplevel 2>/dev/null); then
  echo "⛔ git repo 가 아님: $REPO" >&2
  exit 1
fi
echo "== git 이력 재작성 preflight — $ROOT"
echo

echo "[1/4] repo"
ok "toplevel = $ROOT"
BRANCH=$(git -C "$ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')
note "branch = $BRANCH · HEAD = $(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo '?')"

# ── 2. 작업트리 clean (미추적 포함) ───────────────────────────────────────
echo
echo "[2/4] 작업트리"
DIRTY=$(git -C "$ROOT" status --porcelain 2>/dev/null)
if [ -z "$DIRTY" ]; then
  ok "clean — 추적/미추적 변경 0건"
else
  N=$(printf '%s\n' "$DIRTY" | grep -c .)
  bad "clean 아님 — $N 건. 이력 재작성은 이것들을 **말없이 지운다**"
  printf '%s\n' "$DIRTY" | head -20 | sed 's/^/       /'
  [ "$N" -gt 20 ] && note "     … 외 $((N-20))건"
  note "     해소: 커밋하거나 stash. 미추적 인계 문서는 **커밋**이 정답이다(stash 는 filter-repo 가 보호하지 않는다)"
fi

# ── 3. 동시 세션 ──────────────────────────────────────────────────────────
echo
echo "[3/4] 동시 세션"
# Claude Code 트랜스크립트 경로 규약: cwd 의 '/' 와 '_' 를 각각 '-' 로 치환한 slug
SLUG=$(printf '%s' "$ROOT" | tr '/_' '--')
TDIR="$HOME/.claude/projects/$SLUG"
if [ ! -d "$TDIR" ]; then
  warn "트랜스크립트 폴더 없음 ($TDIR) — 동시 세션 판정 불가"
  note "     판정을 못 했다는 뜻이지 안전하다는 뜻이 아니다. 수동 확인 필요"
else
  NOW=$(date +%s)
  ACTIVE=0
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    M=$(_mtime "$f")
    AGE=$((NOW - M))
    if [ "$AGE" -le "$ACTIVE_WINDOW" ]; then
      ACTIVE=$((ACTIVE+1))
      note "     활동중: $(basename "$f" .jsonl) (${AGE}s 전)"
    fi
  done <<EOF
$(find "$TDIR" -maxdepth 1 -name '*.jsonl' 2>/dev/null)
EOF
  if [ "$ACTIVE" -le 1 ]; then
    ok "최근 ${ACTIVE_WINDOW}s 내 활동 세션 ${ACTIVE}개 (자기 자신뿐)"
  else
    bad "최근 ${ACTIVE_WINDOW}s 내 활동 세션 ${ACTIVE}개 — **다른 세션이 이 repo 에서 작업 중**"
    note "     실행하면 그쪽 미커밋 산출물이 사라진다. 먼저 알리고 합의할 것"
  fi
fi

# ── 4. 백업 (실행 직전 시점) ──────────────────────────────────────────────
echo
echo "[4/4] 백업"
if [ "$DO_BACKUP" = 0 ]; then
  warn "--no-backup — 건너뜀. 되돌릴 수단이 없다"
else
  # ⚠️ 기본 백업 경로는 **repo 밖**이다. repo 안에 두면 이번 실행이 만든 백업이
  # 다음 실행의 [2/4] 미추적 검사에 걸려 스스로를 차단한다(gitignore 로 가리면
  # 이번엔 백업이 filter-repo 뒤 정리 대상에 섞인다). 어느 쪽도 안전망이 아니다.
  # `/tmp` 도 피한다 — Issue392·394 가 "상태가 /tmp 에 있어 우연히 사라진다"로 물린 자리다.
  [ -n "$BACKUP_DIR" ] || BACKUP_DIR="$HOME/.cache/fpm/git-rewrite/$(basename "$ROOT")"
  TS=$(date +%Y%m%d_%H%M%S)
  if ! mkdir -p "$BACKUP_DIR" 2>/dev/null; then
    bad "백업 폴더 생성 실패: $BACKUP_DIR"
  else
    BUNDLE="$BACKUP_DIR/pre-rewrite_${TS}.bundle"
    if git -C "$ROOT" bundle create "$BUNDLE" --all >/dev/null 2>&1; then
      ok "bundle (전 ref) → $BUNDLE  [$(du -h "$BUNDLE" 2>/dev/null | cut -f1)]"
      note "     복구: git clone $BUNDLE <복구경로>"
    else
      bad "git bundle 실패 — 되돌릴 수단 없이 진행하게 된다"
    fi
    SNAP="$BACKUP_DIR/pre-rewrite_${TS}.snapshot.txt"
    {
      echo "# git 이력 재작성 직전 스냅샷 — $(_now_iso)"
      echo "# repo: $ROOT  branch: $BRANCH"
      echo; echo "## status --porcelain"; git -C "$ROOT" status --porcelain
      echo; echo "## stash list";         git -C "$ROOT" stash list
      echo; echo "## reflog -30";         git -C "$ROOT" reflog -30
      echo; echo "## remote -v";          git -C "$ROOT" remote -v
      echo; echo "## show-ref";           git -C "$ROOT" show-ref
    } > "$SNAP" 2>&1
    ok "스냅샷(status·stash·reflog·remote·refs) → $SNAP"
    note "     reflog·remote 는 filter-repo 가 **지우는** 것들이라 사후에는 못 읽는다"
    # 미추적(비ignore) 파일이 남아 있으면 tar 로도 뜬다 — git 이 보호하지 않는 유일한 부류
    UNTRACKED=$(git -C "$ROOT" ls-files --others --exclude-standard)
    if [ -n "$UNTRACKED" ]; then
      TAR="$BACKUP_DIR/pre-rewrite_${TS}.untracked.tar.gz"
      if printf '%s\n' "$UNTRACKED" | tar -czf "$TAR" -C "$ROOT" -T - 2>/dev/null; then
        ok "미추적 $(printf '%s\n' "$UNTRACKED" | grep -c .)건 → $TAR"
      else
        bad "미추적 tar 실패 — 이 부류가 바로 Issue395 에서 복구 불가였던 것이다"
      fi
    fi
  fi
fi

# ── 판정 ──────────────────────────────────────────────────────────────────
echo
if [ "$FAIL" -eq 0 ]; then
  echo "✅ GO — 차단 사유 0건. 이력 재작성 착수 가능"
  exit 0
fi
if [ "$FORCE" = 1 ]; then
  echo "⚠️  NO-GO ${FAIL}건이나 --force 지정 — 강행한다"
  echo "    강행 기록: $(_now_iso) rc-override by $USER (사유는 Issue.md 에 남길 것)"
  exit 0
fi
echo "⛔ NO-GO — 차단 사유 ${FAIL}건. 해소 후 재실행하라"
echo "   판정을 무시하려면 --force (그 순간 Issue395 재발 책임은 실행자에게 있다)"
exit 1
