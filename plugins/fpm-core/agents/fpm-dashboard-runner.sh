#!/usr/bin/env bash
# fpm-dashboard-runner.sh — tmux 기반 dashboard data 갱신 daemon
#
# ⚠️ 글로벌 SCAR 변경 가드 (Issue46): 본 runner는 모든 프로젝트가 공유. cwd ≠ ~/.claude
#   면 즉시 수정 금지 → ~/.claude/Issue.md 이슈 등록 후 처리. 설계 SSOT:
#   ~/.claude/_doc_arch/dashboard.md, ~/_git/___pm/_doc_arch/hub_dashboard_tmux_design.md
#   절차: ~/.claude/rules/global-scar-change-rules.md
#
# tmux pane에서 실행됨. data 파일을 주기 갱신 (HTTP 없음, 파일 기반).
#
# 환경변수 (필수):
#   DATA_FILE      data 파일 절대경로 (.dash.yaml)
#   INTERVAL       loop 주기 초 (기본 5)
#   TOPIC          dashboard 주제 식별자
#   WIN_NAME       tmux window name (e.g. _scenario1)
#
# 동작:
#   1) data 파일에 pid 기록 + status='running'
#   2) trap TERM/INT/HUP → status='stopped' 마킹 후 cleanup (worker_pid 종료) + exit
#   3) SIGUSR1 처리 → sleep 중단 (즉시 갱신)
#   4) loop: data read → dynamic_eval 스크립트 실행 → 결과 위젯 갱신 → write → sleep INTERVAL
#   5) worker_pid 감시 → 사망 시 status='done' → exit
#   6) 부모 프로세스 감시 → orphan 시 exit
#
# 종료:
#   - SIGTERM/INT/HUP (cleanup trap) → graceful
#   - worker_pid 사망 감지 → status='done' → exit
#   - 부모 프로세스 사망 → orphan check → exit (status 유지)

set -uo pipefail

# board_policy.yml 로더 (Issue152) — 운영 상수 SSOT. 우선순위: env VAR > board_policy.yml > 인자 기본값.
BOARD_POLICY="${BOARD_POLICY:-${FPM_BASE:-$HOME/_git/___pm}/data/board_policy.yml}"
_bp() {  # _bp <key> <default>
  local v
  v=$(grep -E "^$1:[[:space:]]" "$BOARD_POLICY" 2>/dev/null | head -1 \
      | sed -E "s/^[^:]*:[[:space:]]*//; s/[[:space:]]*#.*$//; s/[[:space:]]*$//") || true
  printf '%s' "${v:-$2}"
}

INTERVAL="${INTERVAL:-$(_bp interval_default 5)}"
: "${DATA_FILE:?DATA_FILE required}"
: "${TOPIC:?TOPIC required}"
: "${WIN_NAME:?WIN_NAME required}"

MY_PID=$$
ORIG_PPID=$PPID

# YAML 파일 판정
is_yaml() {
  case "$DATA_FILE" in *.yaml|*.yml) return 0 ;; *) return 1 ;; esac
}

# YAML/JSON read → JSON 문자열
read_data() {
  if is_yaml; then
    python3 -c "import yaml,sys,json; print(json.dumps(yaml.safe_load(open(sys.argv[1])) or {}))" "$DATA_FILE"
  else
    cat "$DATA_FILE"
  fi
}

# JSON 문자열 → YAML/JSON write
write_data() {
  local json="$1"
  if is_yaml; then
    echo "$json" | python3 -c "import yaml,json,sys; print(yaml.dump(json.load(sys.stdin), allow_unicode=True, sort_keys=False))" > "$DATA_FILE"
  else
    echo "$json" > "$DATA_FILE"
  fi
}

# status 필드 갱신
mark_status() {
  local status="$1"
  local data
  data=$(read_data)
  data=$(echo "$data" | python3 -c "import json,sys; d=json.load(sys.stdin); d['status']='$status'; print(json.dumps(d))")
  write_data "$data"
}

# worker_pid 종료
kill_worker() {
  local wpid
  wpid=$(read_data | python3 -c "import json,sys; print(json.load(sys.stdin).get('worker_pid', ''))" 2>/dev/null || echo "")
  if [[ -n "$wpid" ]] && kill -0 "$wpid" 2>/dev/null; then
    kill -TERM "$wpid" 2>/dev/null || true
    sleep 0.5
    kill -KILL "$wpid" 2>/dev/null || true
  fi
}

# cleanup trap handler
cleanup() {
  kill_worker
  mark_status stopped
  exit 0
}

# SIGUSR1 handler (sleep 중단)
refresh_signal() {
  [[ -n "$SLEEP_PID" ]] && kill "$SLEEP_PID" 2>/dev/null || true
}

trap cleanup TERM INT HUP
trap refresh_signal USR1

# Startup: PID 기록
echo "[runner] PID=$MY_PID start at $(date -Iseconds)"
{
  data=$(read_data)
  data=$(echo "$data" | python3 -c "import json,sys; d=json.load(sys.stdin); d['pid']=$MY_PID; d['status']='running'; print(json.dumps(d))")
  write_data "$data"
}

SLEEP_PID=

# Main loop
while true; do
  # Orphan check: 부모 프로세스 생존 확인
  if ! kill -0 "$ORIG_PPID" 2>/dev/null; then
    echo "[runner] parent dead, exit"
    mark_status stopped
    exit 0
  fi

  # Read data
  data=$(read_data)

  # Process dynamic_eval widgets + merge back (Issue119)
  #   data 를 argv 로 전달 — `echo|python3 <<heredoc` 는 heredoc 이 pipe stdin 을 덮어
  #   sys.stdin 이 빈 채로 json.load 가 실패하던 근본 결함을 제거. eval→치환→전체 dump 단일 블록.
  merged=$(python3 - "$data" << 'PYTHON' 2>/dev/null
import json, sys, subprocess
try:
  d = json.loads(sys.argv[1])
  widgets = d.get('widgets', [])
  for w in widgets:
    if isinstance(w, dict) and 'dynamic_eval' in w and w['dynamic_eval']:
      try:
        result = subprocess.run(w['dynamic_eval'], shell=True, capture_output=True, text=True, timeout=10)
        w['value'] = result.stdout.strip() if result.returncode == 0 else f"Error: {result.stderr}"
      except Exception as e:
        w['value'] = str(e)
  d['widgets'] = widgets
  print(json.dumps(d))
except:
  pass
PYTHON
)
  # merge 성공 시에만 data 갱신 (실패 시 직전 data 보존)
  if [[ -n "$merged" ]]; then
    data="$merged"
  fi

  # Write updated data
  write_data "$data"

  # Check worker completion
  wpid=$(echo "$data" | python3 -c "import json,sys; print(json.load(sys.stdin).get('worker_pid', ''))" 2>/dev/null || echo "")
  if [[ -n "$wpid" ]] && ! kill -0 "$wpid" 2>/dev/null; then
    mark_status done
    exit 0
  fi

  # Sleep with interruptible wait
  sleep "$INTERVAL" &
  SLEEP_PID=$!
  wait "$SLEEP_PID" 2>/dev/null || true
  SLEEP_PID=
done
