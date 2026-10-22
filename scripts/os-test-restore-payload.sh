#!/usr/bin/env bash
# os-test-restore-payload.sh — OS 테스트(zero-base clear) 후 복귀 · 긴급 복구 원격 페이로드 (Issue652)
#
# 묻는 것: *"clear 이전 상태(prj3 ~/.claude · prj1 ~/_git/fpm)로 돌아왔는가."*
#   clear 페이로드(os-test-payload.sh)는 비우기만 한다. 복귀가 없으면 서버가 테스트 상태로 남는다
#   (2026-10-18 macOS 소비자 clear test → 10-21 긴급 복구).
#
# 사용: ssh <host> 'bash -s -- [--stamp S] [--dry-run]' < os-test-restore-payload.sh   (Windows: Git Bash -l -s)
#   인자 없음  = plan — 읽기 전용. 스탬프별 복구 후보 표만 낸다 (rc 2). 어느 쌍이 «원본» 인지는 사람이 고른다
#   --stamp S  = 복원. 입력: ~/claude-backup-[*-]S.tar.gz · ~/fpm-local-S.tar.gz(없으면 ~/_git/fpm.bak-*S)
#   --dry-run  = 아무것도 쓰지 않고 «복원할 건수» 만 센다
#
# 정책 (파일 단위) — 지우지 않는다. 덮기 전에 현재본을 ~/fpm-restore-safety-<시각>/ 에 보관한다
#   설정 파일 …………… 없거나 내용이 다르면 백업본으로 복원
#   volatile ………… 없을 때만 복원 (projects·session-env·history.jsonl·telemetry 등 — 지금 값이 더 새롭다)
#   .credentials.json … 없을 때만 복원 (지금 로그인이 백업의 옛 토큰보다 새롭다)
#   .git ……………… 디렉토리째 없을 때만 복원 (파일 단위로 섞으면 객체·ref 가 어긋난다)
#   fpm ………………… detached → main 복귀(clean 일 때) + 로컬 untracked/ignored 파일 복원
#
# 출력: `FPMT key=value` 줄. exit: 0 복귀 확인 · 1 복귀했으나 판정 FAIL · 2 plan(복원 안 함) · 3 대상 백업 없음
# 호스트명·경로를 하드코딩하지 않는다 — 공개 미러로 나간다.
set -uo pipefail

STAMP=""; DRY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --stamp)   STAMP="${2:-}"; shift 2 || break ;;
    --dry-run) DRY=1; shift ;;
    *) echo "FPMT restore_args=FAIL(알 수 없는 인자: $1)"; exit 2 ;;
  esac
done

CL="$HOME/.claude"; FPM="$HOME/_git/fpm"
T_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/os-restore.XXXXXX")"
trap 'rm -rf "$T_ROOT"' EXIT
SAFE=""
t() { echo "FPMT $*"; }
case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) OS=windows ;; Darwin) OS=macos ;; *) OS=linux ;; esac

# 백업 tar 경로 — 신 이름 claude-backup-<stamp> · 구 이름 claude-backup-637-<stamp> 둘 다
find_backup() { local f; for f in "$HOME/claude-backup-$1.tar.gz" "$HOME"/claude-backup-*-"$1".tar.gz; do [ -f "$f" ] && { echo "$f"; return 0; }; done; return 1; }
find_bak()    { local d; for d in "$HOME/_git/fpm.bak-$1" "$HOME"/_git/fpm.bak-*-"$1"; do [ -d "$d" ] && { echo "$d"; return 0; }; done; return 1; }
all_stamps()  { local f s; for f in "$HOME"/claude-backup-*.tar.gz; do [ -f "$f" ] || continue; s="${f##*-}"; echo "${s%.tar.gz}"; done | sort -u; }

# 정책 판정 — 상대경로(.claude 기준) → config | volatile | cred | git
policy_of() {
  case "$1" in
    .credentials.json) echo cred ;;
    .git/*) echo git ;;
    projects/*|session-env/*|file-history/*|telemetry/*|sessions/*|cache/*|shell-snapshots/*|backups/*|state/*|tasks/*|ide/*|teams/*|chrome/*|openclaw-plugins/*) echo volatile ;;
    history.jsonl|.last-cleanup|.last-update-result.json|.hub-active|plugins/.last_inuse_sweep|.DS_Store) echo volatile ;;
    *) echo config ;;
  esac
}

# 새 대화형 쉘이 조용히 뜨는가 (Issue653) — fpm 블록이 stderr 에 경고·오류를 내면 쉘을 열 때마다 보인다.
# 구 dotfile 의 alias v/z 와 fpm 런처가 겹쳐 «⚠️ fpm: alias …» 가 새 쉘마다 떴다. 출력: 경고가 난 쉘만 "zsh:2,bash:1" (없으면 빈 문자열)
shell_startup_warn() {
  local sh n out="" T=""
  command -v timeout >/dev/null 2>&1 && T="timeout 30"
  for sh in zsh bash; do
    command -v "$sh" >/dev/null 2>&1 || continue
    n=$($T "$sh" -ic true 2>&1 >/dev/null </dev/null | grep -c 'fpm')
    [ "${n:-0}" -gt 0 ] && out="${out:+$out,}$sh:$n"
  done
  printf '%s' "$out"
}

mk_safe() { [ -n "$SAFE" ] || { SAFE="$HOME/fpm-restore-safety-$(date +%Y.%m.%d_%H%M%S)"; mkdir -p "$SAFE"; }; }
same() {   # 두 경로가 같은 내용인가 (심볼릭 링크는 대상 문자열 비교)
  if [ -L "$1" ] || [ -L "$2" ]; then [ -L "$1" ] && [ -L "$2" ] && [ "$(readlink "$1")" = "$(readlink "$2")" ]; else cmp -s "$1" "$2"; fi
}

# 한 트리(src root)를 dst root 로 정책 적용. $1=src $2=dst $3=safety 하위 이름 $4=policy 함수(claude|flat)
# 전역 카운터: N_MISSING N_DIFFERS N_RESTORED N_SKIPPED
apply_tree() {
  local src="$1" dst="$2" tag="$3" mode="$4" p rel pol s d git_present=0
  [ "$mode" = claude ] && [ -d "$dst/.git" ] && git_present=1
  while IFS= read -r -d '' p; do
    rel="${p#./}"; s="$src/$rel"; d="$dst/$rel"
    if [ "$mode" = claude ]; then pol="$(policy_of "$rel")"; else pol=config; fi
    if [ ! -e "$d" ] && [ ! -L "$d" ]; then
      if [ "$pol" = git ] && [ "$git_present" = 1 ]; then continue; fi      # .git 은 있으면 통째로 건드리지 않음
      N_MISSING=$((N_MISSING + 1))
    else
      same "$s" "$d" && continue
      if [ "$pol" != config ]; then N_SKIPPED=$((N_SKIPPED + 1)); continue; fi
      N_DIFFERS=$((N_DIFFERS + 1))
      if [ "$DRY" = 0 ]; then mk_safe; mkdir -p "$SAFE/$tag/$(dirname "$rel")"; cp -a "$d" "$SAFE/$tag/$rel"; fi
    fi
    if [ "$DRY" = 0 ]; then
      mkdir -p "$(dirname "$d")"; [ -L "$d" ] && rm -f "$d"
      cp -a "$s" "$d" 2>/dev/null || cp -p "$s" "$d"
    fi
    N_RESTORED=$((N_RESTORED + 1))
  done < <(cd "$src" && find . \( -type f -o -type l \) -print0)
}
reset_counts() { N_MISSING=0; N_DIFFERS=0; N_RESTORED=0; N_SKIPPED=0; }

extract_backup() {  # $1=tar → $T_ROOT/cl/.claude
  mkdir -p "$T_ROOT/cl"; tar -xzf "$1" -C "$T_ROOT/cl" 2>/dev/null; [ -d "$T_ROOT/cl/.claude" ]
}

# ── plan ────────────────────────────────────────────────────────────────────────────
if [ -z "$STAMP" ]; then
  t "restore_plan host=$(hostname) os=$OS"
  n=0
  for s in $(all_stamps); do
    n=$((n + 1)); bk="$(find_backup "$s")"; bd="$(find_bak "$s" || true)"
    lt=no; [ -f "$HOME/fpm-local-$s.tar.gz" ] && lt=yes
    rm -rf "$T_ROOT/cl"; reset_counts; DRY=1
    if extract_backup "$bk"; then apply_tree "$T_ROOT/cl/.claude" "$CL" claude claude; fi
    t "plan stamp=$s files_missing=$N_MISSING files_differs=$N_DIFFERS skipped_volatile=$N_SKIPPED fpm_bak=$([ -n "$bd" ] && echo yes || echo no) fpm_local_tar=$lt"
  done
  [ "$n" -eq 0 ] && t "plan none — ~/claude-backup-*.tar.gz 가 없다 (복구할 clear 기록이 없음)"
  t "plan next=복원하려면 --stamp <위 스탬프> (여럿이면 사람이 「원본」 쌍을 고른다 — 가장 이른 스탬프가 clear 이전 상태인 경우가 많다)"
  exit 2
fi

# ── restore ─────────────────────────────────────────────────────────────────────────
BK="$(find_backup "$STAMP")" || { t "restore_verdict=FAIL(백업 없음: claude-backup-*$STAMP.tar.gz)"; exit 3; }
BAKD="$(find_bak "$STAMP" || true)"; LTAR="$HOME/fpm-local-$STAMP.tar.gz"
t "restore_plan stamp=$STAMP dry_run=$DRY backup=$BK fpm_bak=${BAKD:-none} fpm_local_tar=$([ -f "$LTAR" ] && echo yes || echo no) os=$OS"

# 1) prj3 ~/.claude
extract_backup "$BK" || { t "restore_verdict=FAIL(백업 tar 해제 실패: $BK)"; exit 1; }
reset_counts; apply_tree "$T_ROOT/cl/.claude" "$CL" claude claude
t "restore_claude missing=$N_MISSING differs=$N_DIFFERS restored=$N_RESTORED skipped_volatile=$N_SKIPPED"
C_RESTORED=$N_RESTORED

# 2) prj1 ~/_git/fpm
F_RESTORED=0; F_BRANCH="n/a"; F_ISSUE=""
if [ -d "$FPM/.git" ]; then
  F_BRANCH="$(git -C "$FPM" branch --show-current 2>/dev/null)"
  if [ -z "$F_BRANCH" ]; then
    if git -C "$FPM" rev-parse --verify -q refs/heads/main >/dev/null; then target_cmd=(switch main)
    elif git -C "$FPM" rev-parse --verify -q refs/remotes/origin/main >/dev/null; then target_cmd=(switch -c main --track origin/main)
    else target_cmd=(); fi
    if [ "${#target_cmd[@]}" -eq 0 ]; then F_ISSUE="main 으로 갈 ref 없음"
    elif [ -n "$(git -C "$FPM" status --porcelain --untracked-files=no 2>/dev/null)" ]; then F_ISSUE="추적 파일 변경이 있어 브랜치 전환 보류"
    elif [ "$DRY" = 1 ]; then F_BRANCH="(would: git ${target_cmd[*]})"
    else git -C "$FPM" -c advice.detachedHead=false "${target_cmd[@]}" >/dev/null 2>&1; F_BRANCH="$(git -C "$FPM" branch --show-current)"; fi
  fi
  # 로컬 파일 원천 — tar 우선, 없으면 .bak 의 untracked+ignored
  SRC=""
  if [ -f "$LTAR" ]; then mkdir -p "$T_ROOT/fl" && tar -xzf "$LTAR" -C "$T_ROOT/fl" 2>/dev/null && SRC="$T_ROOT/fl"
  elif [ -n "$BAKD" ] && [ -d "$BAKD/.git" ]; then
    mkdir -p "$T_ROOT/fl"
    git -C "$BAKD" ls-files -o -z 2>/dev/null | tr '\0' '\n' \
      | grep -vE '(^|/)(\.DS_Store|__pycache__|node_modules)(/|$)|^tdd/results/|^\.git/' \
      | while IFS= read -r f; do [ -e "$BAKD/$f" ] && { mkdir -p "$T_ROOT/fl/$(dirname "$f")"; cp -a "$BAKD/$f" "$T_ROOT/fl/$f"; }; done
    SRC="$T_ROOT/fl"
  fi
  if [ -n "$SRC" ]; then reset_counts; apply_tree "$SRC" "$FPM" fpm flat; F_RESTORED=$N_RESTORED
    t "restore_fpm branch=${F_BRANCH:-?} local_missing=$N_MISSING local_differs=$N_DIFFERS restored=$N_RESTORED source=$([ -f "$LTAR" ] && echo tar || echo bak)"
  else
    t "restore_fpm branch=${F_BRANCH:-?} restored=0 source=none(fpm-local tar·.bak 둘 다 없음)"
  fi
else
  t "restore_fpm skip(~/_git/fpm 이 git clone 이 아니다)"
fi
[ -n "$F_ISSUE" ] && t "restore_fpm_warn=$F_ISSUE"

# 3) 외부 서비스 — clear 가 세웠다가 못 되살린 gateway 가 있으면 기동 (없는 서비스는 만들지 않는다)
SVC=none
case "$OS" in
  linux)   if systemctl --user cat openclaw-gateway >/dev/null 2>&1; then
             if systemctl --user is-active --quiet openclaw-gateway; then SVC=active
             elif [ "$DRY" = 1 ]; then SVC="inactive(would start)"
             else systemctl --user start openclaw-gateway >/dev/null 2>&1; systemctl --user is-active --quiet openclaw-gateway && SVC=started || SVC=inactive; fi
           fi ;;
  macos)   PL="$HOME/Library/LaunchAgents/ai.openclaw.gateway.plist"
           if [ -f "$PL" ]; then
             if launchctl list 2>/dev/null | awk '$3=="ai.openclaw.gateway" && $1!="-" {f=1} END{exit !f}'; then SVC=active
             elif [ "$DRY" = 1 ]; then SVC="inactive(would start)"
             else launchctl bootstrap "gui/$(id -u)" "$PL" >/dev/null 2>&1; sleep 2
                  launchctl list 2>/dev/null | awk '$3=="ai.openclaw.gateway" && $1!="-" {f=1} END{exit !f}' && SVC=started || SVC=inactive; fi
           fi ;;
esac
t "restore_ext_svc=$SVC"

# 4) 판정 — 복원 후 재측정 (dry-run 은 건수만)
if [ "$DRY" = 1 ]; then
  t "restore_verdict=DRY(would_restore=$((C_RESTORED + F_RESTORED)))"; exit 0
fi
rm -rf "$T_ROOT/cl2"; mkdir -p "$T_ROOT/cl2"
tar -xzf "$BK" -C "$T_ROOT/cl2" 2>/dev/null
DRY=1; reset_counts; apply_tree "$T_ROOT/cl2/.claude" "$CL" claude claude; RES_C=$((N_MISSING + N_DIFFERS))
RES_F=0
if [ -n "${SRC:-}" ]; then reset_counts; apply_tree "$SRC" "$FPM" fpm flat; RES_F=$((N_MISSING + N_DIFFERS)); fi
BAD=""
SW="$(shell_startup_warn)"; [ -z "$SW" ] || BAD="$BAD 새 쉘 시작 경고($SW);"
[ "$RES_C" -eq 0 ] || BAD="$BAD ~/.claude 잔여 $RES_C건;"
[ "$RES_F" -eq 0 ] || BAD="$BAD fpm 로컬 잔여 $RES_F건;"
[ -d "$FPM/.git" ] && [ -z "$(git -C "$FPM" branch --show-current 2>/dev/null)" ] && BAD="$BAD fpm 이 아직 detached;"
case "$SVC" in inactive*) BAD="$BAD gateway 비활성;" ;; esac

# 정보성(판정 불포함) — hub·로그인
HUB="$(curl -s -o /dev/null -m 3 -w '%{http_code}' http://127.0.0.1:9876/healthz 2>/dev/null || echo 000)"
if [ "${OSTEST_SKIP_AUTH:-0}" = 1 ] || ! command -v claude >/dev/null 2>&1; then AUTH=skip
else AUTH="$(claude auth status 2>/dev/null | grep -o '"loggedIn": *[a-z]*' | awk '{print $2}')"; fi
t "restore_info hub_healthz=$HUB logged_in=${AUTH:-?} shell_startup=${SW:-ok} safety=${SAFE:-none}"

# restored= 는 이번 실행에서 실제로 쓴 건수 (두 번째 실행 = 0 이 멱등 증거)
t "restore_summary restored=$((C_RESTORED + F_RESTORED))"
if [ -z "$BAD" ]; then t "restore_verdict=ok"; exit 0; else t "restore_verdict=FAIL($BAD)"; exit 1; fi
