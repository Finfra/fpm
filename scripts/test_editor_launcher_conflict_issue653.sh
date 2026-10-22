#!/bin/bash
# test_editor_launcher_conflict_issue653.sh — Issue653 회귀 테스트 (sh/fpm_editors.sh 런처 충돌 처리)
#
# 묻는 것: *"사용자가 이미 v/z alias 를 갖고 있으면 쉘을 열 때마다 경고하지 않고 조용히 사용자 정의를 존중하는가."*
#   jma 는 구 dotfile 에 `alias v=vscode` · zsh 플러그인 `z` alias 가 있어 fpm 을 source 할 때마다
#   «⚠️ fpm: alias 'v' 이 이미 있어 …» 두 줄이 새 쉘마다 떴다 (jm4 는 alias 가 없어 함수로 정의됨).
#   ① 충돌 시 stderr 무출력, 기존 alias 는 그대로, 충돌 없는 런처(vn·zn…)는 정상 정의
#   ② FPM_EDITORS_VERBOSE=1 이면 경고를 낸다 (진단 경로는 남긴다)
#   ③ 충돌이 없으면 v/z 는 함수로 정의되고 무출력 (jm4 동작 불변)
#
# 격리: 실물 sh/fpm_editors.sh 를 임시 FPM_BASE(editor.yml 복사본)로 source. zsh·bash 양쪽.
# 실행: bash scripts/test_editor_launcher_conflict_issue653.sh
set -u

REPO="$(cd "$(dirname "$0")/.." && pwd)"
SB="$(mktemp -d "${TMPDIR:-/tmp}/ed-conflict.XXXXXX")"
trap 'rm -rf "$SB"' EXIT
PASS=0; FAIL=0
ok()   { PASS=$((PASS + 1)); echo "  ok   $1"; }
fail() { FAIL=$((FAIL + 1)); echo "  FAIL $1"; }
check() { if [ "$2" = "$3" ]; then ok "$1"; else fail "$1 (want='$3' got='$2')"; fi; }
has()  { if printf '%s' "$2" | grep -qF -- "$3"; then ok "$1"; else fail "$1 (없음: '$3')"; fi; }

mkdir -p "$SB/base/data" "$SB/base/sh"
cp "$REPO/data/editor.yml" "$SB/base/data/editor.yml"
cp "$REPO/sh/fpm_editors.sh" "$SB/base/sh/fpm_editors.sh"

# $1=쉘 $2=사전 설정(alias 정의) $3=추가 env → "stderr|||진단" 출력
run_shell() {
  local sh="$1" pre="$2" envs="$3"
  env LC_ALL=C LANG=C FPM_BASE="$SB/base" $envs "$sh" -c "
    $pre
    source \"\$FPM_BASE/sh/fpm_editors.sh\" 2>\"$SB/err\"
    {
      echo \"v_is_alias=\$(alias v >/dev/null 2>&1 && echo yes || echo no)\"
      echo \"z_is_alias=\$(alias z >/dev/null 2>&1 && echo yes || echo no)\"
      for f in v z vn vw zn za zw; do
        if type \$f 2>/dev/null | grep -q function; then echo \"\$f=function\"; else echo \"\$f=other\"; fi
      done
    } > \"$SB/diag\""
  echo "STDERR=$(cat "$SB/err")"
  cat "$SB/diag"
}

for SH in zsh bash; do
  command -v "$SH" >/dev/null 2>&1 || { echo "skip $SH (없음)"; continue; }
  echo "[$SH] 충돌 — 사용자가 v·z alias 를 이미 가짐"
  out="$(run_shell "$SH" "alias v=vscode; alias z='zshz 2>&1'" "")"
  check "$SH 충돌: stderr 무출력" "$(printf '%s\n' "$out" | grep '^STDERR=' )" "STDERR="
  has   "$SH 충돌: 사용자 v alias 유지" "$out" "v_is_alias=yes"
  has   "$SH 충돌: 사용자 z alias 유지" "$out" "z_is_alias=yes"
  has   "$SH 충돌: 충돌 없는 vn 은 함수로 정의" "$out" "vn=function"
  has   "$SH 충돌: 충돌 없는 zn 은 함수로 정의" "$out" "zn=function"

  echo "[$SH] 진단 — FPM_EDITORS_VERBOSE=1"
  out="$(run_shell "$SH" "alias v=vscode" "FPM_EDITORS_VERBOSE=1")"
  has   "$SH verbose: 경고 노출" "$out" "alias 'v'"

  echo "[$SH] 무충돌 — jm4 동작 불변"
  out="$(run_shell "$SH" ":" "")"
  check "$SH 무충돌: stderr 무출력" "$(printf '%s\n' "$out" | grep '^STDERR=' )" "STDERR="
  has   "$SH 무충돌: v 함수" "$out" "v=function"
  has   "$SH 무충돌: z 함수" "$out" "z=function"
done

echo
echo "PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
