#!/usr/bin/env bash
# test-aoa-mq-spawn-limits.sh — aoa_mq_spawn 몸체 수명 상한·구조화 출력 (prj3#Issue979_2)
#
# ⚠️ 글로벌 SCAR 변경 가드 (prj3#Issue46): cwd ≠ ~/.claude 면 즉시 수정 금지 → Issue.md 이슈 등록 후 처리.
#
# 왜: 자동 기동 `nohup claude -p &` 에 timeout·--max-turns 가 없었고 결과는 텍스트 로그 append 뿐이었다.
#   → timeout(gtimeout 부재 시 명시 실패) + --max-turns + --output-format json, is_error·num_turns·
#     total_cost_usd 를 항목 진행 메모(progress)에 남긴다.
# 실 claude 를 띄우지 않는다(AOA_MQ_CLAUDE_BIN = 가짜).
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
T=$(mktemp -d "${TMPDIR:-/tmp}/aoa-mq-spawn.XXXXXX"); T=$(cd "$T" && pwd)
trap 'rm -rf "$T"' EXIT
export AOA_MQ_DIR="$T/mq" AOA_MQ_LOCK_WAIT=3
export SELECTION_POLICY="$T/no-selection.yml" AOA_MEMORY_DIR="$T/no-aoa"
mkdir -p "$AOA_MQ_DIR/queue" "$AOA_MQ_DIR/queue_done" "$T/cwd"
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); printf '  ✅ %s\n' "$1"; }
bad() { FAIL=$((FAIL+1)); printf '  ❌ %s\n' "$1"; }
chk() { if eval "$2"; then ok "$1"; else bad "$1 — ${3:-}"; fi; }

# 가짜 claude — argv 기록 · FAKE_MODE: json(JSON 1줄 출력) | hang(오래 잠든다 + pid 기록)
cat > "$T/fake-claude" <<'SH'
#!/bin/bash
[ "${1:-}" = "--version" ] && { echo "fake 0.0"; exit 0; }
printf '%s\n' "$*" > "$FAKE_ARGV"
case "${FAKE_MODE:-json}" in
  json) printf '{"type":"result","is_error":false,"num_turns":7,"total_cost_usd":0.1234,"result":"ok"}\n' ;;
  err)  printf '{"type":"result","is_error":true,"num_turns":3,"total_cost_usd":0.05,"result":"boom"}\n'; exit 1 ;;
  hang) echo $$ > "$FAKE_PID"; exec sleep 60 ;;
esac
SH
chmod +x "$T/fake-claude"

mkitem() { printf '{ "id": "%s", "kind": "reminder", "msg": "t", "status": "in_progress" }\n' "$1" > "$AOA_MQ_DIR/queue/$1.json"; }
prog() { jq -r '.progress // empty' "$AOA_MQ_DIR/queue/$1.json"; }
run_spawn() { # $1=id [env...] — lib 을 source 해 aoa_mq_spawn 직접 호출
  local id="$1"; shift
  ( export AOA_MQ_CLAUDE_BIN="$T/fake-claude" FAKE_ARGV="$T/argv.$id" FAKE_PID="$T/pid.$id"
    for kv in "$@"; do export "$kv"; done
    . "$HERE/aoa-mq-lib.sh"
    aoa_mq_claude_bin
    aoa_mq_spawn "$T/cwd" "$id" "프롬프트" "$T/exec.$id.log" )
}

echo "▶ argv — --max-turns · --output-format json"
mkitem A1; run_spawn A1 FAKE_MODE=json; rc=$?; sleep 3
chk "spawn rc 0" '[ $rc -eq 0 ]' "rc=$rc"
chk "--max-turns N 포함" 'grep -Eq -- "--max-turns [0-9]+" "$T/argv.A1"' "$(cat "$T/argv.A1" 2>&1)"
chk "--output-format json 포함" 'grep -q -- "--output-format json" "$T/argv.A1"'
chk "프롬프트는 -p 인자로 유지" 'grep -q -- "-p 프롬프트" "$T/argv.A1"'

echo "▶ 결과 기록 — is_error·num_turns·total_cost_usd 를 진행 메모에"
chk "progress 에 num_turns=7" 'prog A1 | grep -q "num_turns=7"' "$(prog A1)"
chk "progress 에 total_cost_usd=0.1234" 'prog A1 | grep -q "total_cost_usd=0.1234"' "$(prog A1)"
chk "progress 에 is_error=false" 'prog A1 | grep -q "is_error=false"' "$(prog A1)"
mkitem A2; run_spawn A2 FAKE_MODE=err; sleep 3
chk "오류 몸체 → is_error=true · rc=1 기록" 'prog A2 | grep -q "is_error=true" && prog A2 | grep -q "rc=1"' "$(prog A2)"

echo "▶ 수명 상한 — timeout 초과 시 몸체 kill"
mkitem A3; run_spawn A3 FAKE_MODE=hang AOA_MQ_SPAWN_TIMEOUT=2; rc=$?; sleep 1
chk "spawn 은 즉시 반환(rc 0)" '[ $rc -eq 0 ]' "rc=$rc"
pid=$(cat "$T/pid.A3" 2>/dev/null)
chk "hang 몸체 기동됨" '[ -n "$pid" ] && kill -0 "$pid" 2>/dev/null' "pid=$pid"
sleep 5
chk "마감(2s) 뒤 몸체 종료" '! kill -0 "$pid" 2>/dev/null' "pid=$pid 생존"
sleep 2
chk "timeout 사실이 progress 에 기록(rc=124)" 'prog A3 | grep -q "rc=124"' "$(prog A3)"

echo "▶ timeout 부재 → 명시 실패(기동 안 함)"
mkitem A4; rm -f "$T/argv.A4"
run_spawn A4 FAKE_MODE=json AOA_MQ_TIMEOUT_BIN=/nonexistent/timeout 2>"$T/err.A4"; rc=$?; sleep 1
chk "rc≠0" '[ $rc -ne 0 ]' "rc=$rc"
chk "claude 미기동" '[ ! -e "$T/argv.A4" ]'
chk "stderr 에 timeout 부재 사유" 'grep -qi "timeout" "$T/err.A4"' "$(cat "$T/err.A4")"

echo; echo "결과: PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
