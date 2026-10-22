#!/bin/bash
# test_launcher_check_issue653.sh — Issue653 회귀 테스트 (설치·clear 경로의 런처 충돌 안내 + 새 쉘 시작 검사)
#
# 묻는 것: *"clear→재설치 뒤에도 쉘을 열 때 경고가 새지 않고, 새면 판정에서 잡히는가."*
#   ① sh/fpm-launcher-check.sh — 런처 이름(v vn vw z zn za zw)과 겹치는 alias 만 알리고, 무관한 alias·없는 파일은 무시, 항상 rc 0
#   ② install.sh 가 ① 을 부른다 (설치 시점에 한 번 알림)
#   ③ shell_startup_warn (clear 페이로드·복구 페이로드 공용) — 가짜 쉘이 stderr 에 fpm 경고를 내면 «zsh:N» 으로 잡고, 조용하면 빈 문자열
#   ④ 두 페이로드의 shell_startup_warn 본문이 같다 (복사본이 갈라지지 않음)
#   ⑤ clear 페이로드는 shell_startup 을 FPMT 로 보고하고, 복구 페이로드는 판정(BAD)에 넣는다
#
# 격리: 임시 dotfile · 가짜 zsh/bash. 실행: bash scripts/test_launcher_check_issue653.sh
set -u

REPO="$(cd "$(dirname "$0")/.." && pwd)"
SB="$(mktemp -d "${TMPDIR:-/tmp}/launcher-check.XXXXXX")"
trap 'rm -rf "$SB"' EXIT
PASS=0; FAIL=0
ok()   { PASS=$((PASS + 1)); echo "  ok   $1"; }
fail() { FAIL=$((FAIL + 1)); echo "  FAIL $1"; }
check() { if [ "$2" = "$3" ]; then ok "$1"; else fail "$1 (want='$3' got='$2')"; fi; }
has()  { if printf '%s' "$2" | grep -qF -- "$3"; then ok "$1"; else fail "$1 (없음: '$3')"; fi; }
hasnt(){ if printf '%s' "$2" | grep -qF -- "$3"; then fail "$1 (있으면 안 됨: '$3')"; else ok "$1"; fi; }

CHK="$REPO/sh/fpm-launcher-check.sh"

echo "① 런처 충돌 안내"
printf 'alias ll="ls -l"\nalias v=vscode\n  alias zn="zed -n"\nalias vx=true\n# alias z=commented\n' > "$SB/a.sh"
printf 'export PATH=$PATH\n' > "$SB/b.sh"
out="$(bash "$CHK" "$SB/a.sh" "$SB/b.sh" "$SB/없는파일" 2>&1)"; rc=$?
check "rc 0 (설치를 막지 않는다)" "$rc" "0"
has   "v 충돌 보고(줄 번호 포함)" "$out" "a.sh:2:alias v=vscode"
has   "들여쓴 zn 충돌 보고" "$out" "a.sh:3:"
hasnt "무관한 vx 는 보고 안 함" "$out" "alias vx"
hasnt "주석 처리된 z 는 보고 안 함" "$out" "commented"
hasnt "ll 은 보고 안 함" "$out" "alias ll"
out="$(bash "$CHK" "$SB/b.sh" 2>&1)"; check "충돌 없으면 무출력" "$out" ""
HOME="$SB/home" bash "$CHK" >/dev/null 2>&1; check "인자 없이 + 홈에 dotfile 없음 → rc 0" "$?" "0"

echo "② install.sh 연결"
has "install.sh 가 fpm-launcher-check.sh 를 호출" "$(cat "$REPO/sh/install.sh")" "fpm-launcher-check.sh"

echo "③ shell_startup_warn"
fn() { sed -n '/^shell_startup_warn() {/,/^}/p' "$1"; }
fn "$REPO/scripts/os-test-payload.sh" > "$SB/fn.sh"
[ -s "$SB/fn.sh" ] && ok "payload 에 shell_startup_warn 존재" || fail "payload 에 shell_startup_warn 없음"
REALBASH="$(command -v bash)"   # PATH 를 바꾸면 가짜 bash 가 먼저 잡히므로 실물 경로를 고정
mkdir -p "$SB/noisy" "$SB/quiet"
for s in zsh bash; do
  printf '#!/bin/sh\necho "⚠️  fpm: alias v 이 이미 있어" >&2\necho "⚠️  fpm: alias z 이 이미 있어" >&2\necho stdout-noise\n' > "$SB/noisy/$s"
  printf '#!/bin/sh\necho "can not change option: zle" >&2\n' > "$SB/quiet/$s"
done
chmod +x "$SB/noisy/"* "$SB/quiet/"*
n="$(PATH="$SB/noisy:/usr/bin:/bin" "$REALBASH" -c ". '$SB/fn.sh'; shell_startup_warn")"
check "경고 2줄 → zsh:2,bash:2" "$n" "zsh:2,bash:2"
q="$(PATH="$SB/quiet:/usr/bin:/bin" "$REALBASH" -c ". '$SB/fn.sh'; shell_startup_warn")"
check "fpm 무관한 stderr 만 → 빈 문자열" "$q" ""

echo "④ 두 페이로드의 본문 동일"
fn "$REPO/scripts/os-test-restore-payload.sh" > "$SB/fn2.sh"
if cmp -s "$SB/fn.sh" "$SB/fn2.sh"; then ok "shell_startup_warn 본문 일치"; else fail "payload 와 restore-payload 의 shell_startup_warn 이 다르다"; fi

echo "⑤ 보고·판정 연결"
has "clear 페이로드가 shell_startup 을 FPMT 로 보고" "$(cat "$REPO/scripts/os-test-payload.sh")" 't "shell_startup='
has "복구 페이로드가 새 쉘 경고를 BAD 에 넣는다" "$(cat "$REPO/scripts/os-test-restore-payload.sh")" '새 쉘 시작 경고'

echo
echo "결과: PASS $PASS / FAIL $FAIL"
[ "$FAIL" -eq 0 ]
