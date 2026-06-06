#!/usr/bin/env bash
# dashboard-supervisor.test.sh — worker_busy / worker_ready / detect_sentinel 회귀 픽스처
#
# ⚠️ 글로벌 SCAR 변경 가드 (Issue46): 본 테스트는 모든 프로젝트가 공유. cwd ≠ ~/.claude
#   면 즉시 수정 금지 → ~/.claude/Issue.md 이슈 등록 후 처리. 설계 SSOT:
#   ~/.claude/_doc_arch/dashboard.md. 절차: ~/.claude/rules/global-scar-change-rules.md
#
# 회귀 차단 — (1) busy-detection: idle 샘플('✻ Cogitated for Ns')이 busy 로 판정되거나,
#   장기 Bash 대기('Waiting…'·'shell still running')가 idle 로 판정되면 실패.
#   ⏵⏵(Issue93)→✻(Issue98 D4)→장기Bash(Issue101 D6) busy 판정 회귀 패턴 차단.
#   (2) detect_sentinel: Issue100 파일 sentinel + Issue102 WAITING 질문 파싱 —
#   .done/.waiting/.withdrawn 폴링·.done 우선순위·.waiting 의 'WAITING\t<질문>' 파싱.
# 실행: bash ~/.claude/agents/dashboard-supervisor.test.sh

set -uo pipefail
SELFDIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

# supervisor.sh 를 SELFTEST 모드로 source — 함수만 로드, main loop 미진입.
export SUPERVISOR_SELFTEST=1
export OUT_DIR="/tmp/sv-selftest"
export QUEUE_FILE="$OUT_DIR/queue.yaml"
export TOPIC="selftest"
mkdir -p "$OUT_DIR"
: > "$QUEUE_FILE"
# shellcheck source=/dev/null
source "$SELFDIR/dashboard-supervisor.sh"

PASS=0; FAIL=0
ok() { PASS=$((PASS + 1)); printf '  ok   %s\n' "$1"; }
ng() { FAIL=$((FAIL + 1)); printf '  FAIL %s\n' "$1"; }

# ── worker_busy: idle 코퍼스 — 전부 idle 판정 의무 (Issue98 D4 핵심) ──
echo "[worker_busy] idle 코퍼스 (busy 오판 시 no-sentinel escalation 영구 차단)"
IDLE_COGITATED='✻ Cogitated for 17s
╭──────────────────╮
│ ❯                │
╰──────────────────╯
  ⏵⏵ bypass permissions on (shift+tab to cycle)'
IDLE_COMPACTING='✻ Compacting conversation…
╭──────────────────╮
│ ❯                │
╰──────────────────╯'
IDLE_PLAIN='╭──────────────────╮
│ ❯ 무엇을 도와드릴까요?  │
╰──────────────────╯
  ⏵⏵ bypass permissions on (shift+tab to cycle)'
for name in IDLE_COGITATED IDLE_COMPACTING IDLE_PLAIN; do
  if worker_busy "${!name}"; then ng "$name → busy 오판 (idle 이어야 함)"; else ok "$name → idle"; fi
done

# ── worker_busy: busy 코퍼스 — 전부 busy 판정 의무 ──
echo "[worker_busy] busy 코퍼스"
BUSY_ESC='✻ Working… (esc to interrupt)
  ↓ 2.1k tokens'
BUSY_KR='작업 중… (esc 로 중단)'
BUSY_RUN='Running… tokens·1.2k'
# Issue101 D6: 장기 Bash 대기 — 입력창 박스가 보여도 busy 여야 한다. sleep 150 류 정상
#   장기 작업을 idle 로 오판해 조기 no-sentinel 실패하던 버그. ✻ 글리프는 단독 매칭
#   금지(D4 회귀) — 'Waiting…'·'shell still running' 동반 토큰으로만 busy 판정.
BUSY_WAITING='⏺ Bash(mkdir -p /tmp/dash-test7 && sleep 150)
  ⎿ Waiting…
╭──────────────────╮
│ ❯                │
╰──────────────────╯
  ✻ Crunched for 15s · 1 shell still running
  ⏵⏵ bypass permissions on (shift+tab to cycle)'
BUSY_SHELL='✻ Crunching…
╭──────────────────╮
│ ❯                │
╰──────────────────╯
  2 shells still running
  ⏵⏵ bypass permissions on (shift+tab to cycle)'
for name in BUSY_ESC BUSY_KR BUSY_RUN BUSY_WAITING BUSY_SHELL; do
  if worker_busy "${!name}"; then ok "$name → busy"; else ng "$name → idle 오판 (busy 이어야 함)"; fi
done

# ── worker_ready (Issue96 D1) ──
echo "[worker_ready] claude TUI 부팅 레이스"
BOOT_WELCOME='   Welcome to Claude Code
   Loading workspace…'
if worker_ready "$IDLE_PLAIN"; then ok "ready TUI → ready"; else ng "ready TUI → 미감지 (디스패치 영구 보류)"; fi
if worker_ready "$BOOT_WELCOME"; then ng "부팅 화면 → ready 오판 (Enter 유실 위험)"; else ok "부팅 화면 → 아직"; fi

# ── detect_sentinel: 파일 기반 sentinel (Issue100 D5) ──
echo "[detect_sentinel] 파일 기반 sentinel"
TAB=$'\t'
check() { # check <desc> <expected> <actual>
  if [ "$2" = "$3" ]; then ok "$1"; else ng "$1 (기대 [$2] 실제 [$3])"; fi
}
sd="$SENTINEL_DIR"
mkdir -p "$sd"
rm -f "$sd"/* 2>/dev/null
printf 'DONE\t0\tmarkerA committed\n' > "$sd/$TOPIC.a.done"
check "DONE rc=0 + result" "DONE 0${TAB}markerA committed" "$(detect_sentinel a)"
printf 'DONE\t2\t실패 사유\n'         > "$sd/$TOPIC.b.done"
check "DONE rc=2"          "DONE 2${TAB}실패 사유"          "$(detect_sentinel b)"
printf 'DONE\t0\t\n'                 > "$sd/$TOPIC.c.done"
check "result 없음"        "DONE 0${TAB}"                   "$(detect_sentinel c)"
check "sentinel 없음"      ""                               "$(detect_sentinel z)"
: > "$sd/$TOPIC.d.done"
check "빈 .done → 미완료"  ""                               "$(detect_sentinel d)"
: > "$sd/$TOPIC.w.waiting"
check "WAITING 질문 없음"   "WAITING${TAB}"                  "$(detect_sentinel w)"
printf 'WAITING\t색상을 무엇으로 할까요?\n' > "$sd/$TOPIC.q.waiting"
check "WAITING 질문 파싱"   "WAITING${TAB}색상을 무엇으로 할까요?" "$(detect_sentinel q)"
: > "$sd/$TOPIC.x.withdrawn"
check "WITHDRAWN 파일"     "WITHDRAWN"                      "$(detect_sentinel x)"
printf 'DONE\t0\tresumed\n' > "$sd/$TOPIC.w.done"
check "done > waiting 우선" "DONE 0${TAB}resumed"           "$(detect_sentinel w)"
rm -f "$sd"/* 2>/dev/null

echo
echo "결과: PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ] || exit 1
