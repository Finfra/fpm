#!/usr/bin/env bash
# aoa-mq-lock.sh — 큐 쓰기 상호배제 락 라이브러리 (source 전용, 배선 없음), prj3#Issue643
#
# ⚠️ 글로벌 SCAR 변경 가드 (prj3#Issue46): 본 라이브러리는 aoa-mq 를 쓰는 모든 프로젝트가 공유.
#   cwd ≠ ~/.claude 면 즉시 수정 금지 → ~/.claude/Issue.md 이슈 등록 후 처리.
#   설계 SSOT: ~/.claude/_doc_arch/aoa-mq.md · 절차: ~/.claude/rules/global-scar-change-rules.md
#
# 왜 뽑았나 (Issue643):
#   큐 JSON 을 **짧게 고치고 빠지는** 쓰기 주체가 둘이 됐다 — `--reschedule`(due_ts)과
#   `aoa-mq-progress.sh`(진행 3종). 둘이 각자 락을 구현하면 고아 락 판정·탈취 임계가 갈려
#   *"한쪽은 기다리고 한쪽은 탈취하는"* 상태가 된다(Issue633 이 정확히 그 부류였다).
#
# 경계 — tick 은 이 라이브러리를 쓰지 않는다:
#   tick 은 락의 **보유자**다(잡고 수 초~수십 초 일한다). 여기 있는 것은 **침입자용**이다
#   (잡고 즉시 빠진다). 대기 상한·실패 시 동작이 달라 한 함수로 합치면 어느 한쪽이 틀어진다.
#   공유되는 것은 **락 파일 규약**(.tick.lock mkdir + .tick.lock.pid 형제 파일)이지 코드가 아니다.
#
# 계약:
#   호출 전 `MQ_DIR` 이 정의돼 있어야 한다. `die()` 가 있으면 그것을 쓰고, 없으면 자체 정의한다.
#   aoa_mq_lock_acquire [최대대기초]   — 기본 10초. 실패 시 die
#   aoa_mq_lock_release                — 자기가 건 PID 일 때만 해제 (남의 락을 풀지 않는다)
#   AOA_MQ_LOCK_HELD=1 이면 acquire 는 **즉시 성공 반환**(재진입 — tick 의 위임 호출)

command -v die >/dev/null 2>&1 || die() { echo "aoa-mq-lock ERROR: $*" >&2; exit 1; }

# mtime 조회 — BSD(/usr/bin/stat -f) 절대경로 우선 → GNU(-c) fallback → 0.
#   ⚠️ PATH 의 stat 이 coreutils 면 `-f` 가 --file-system 이라 `File: "…"` 같은 **비숫자**를
#   뱉는다. 그대로 산술 확장에 넣으면 set -u 아래서 죽는다(2026-08-16 실측). 절대경로 + 숫자 검증 두 겹.
aoa_mq_mtime_of() {
  local m
  m=$(/usr/bin/stat -f %m "$1" 2>/dev/null) || m=""
  case "$m" in ''|*[!0-9]*) m=$(stat -c %Y "$1" 2>/dev/null) || m="" ;; esac
  case "$m" in ''|*[!0-9]*) m=0 ;; esac
  printf '%s' "$m"
}

# 락 보유 PID — 없거나 락보다 오래된 pid 파일이면 "모름"(빈 값)
#   pid 를 락 디렉토리 **밖** 형제 파일에 두는 이유는 tick 주석과 같다 — mkdir 이 원자적인
#   것이지 그 안에 파일을 쓰는 것까지 원자적이지는 않다.
aoa_mq_lock_owner_pid() {
  local pid lockm
  [ -f "$MQ_DIR/.tick.lock.pid" ] || return 0
  lockm=$(aoa_mq_mtime_of "$MQ_DIR/.tick.lock")
  [ "$(aoa_mq_mtime_of "$MQ_DIR/.tick.lock.pid")" -lt "$lockm" ] && return 0
  pid=$(cat "$MQ_DIR/.tick.lock.pid" 2>/dev/null)
  case "$pid" in ''|*[!0-9]*) return 0 ;; esac
  printf '%s' "$pid"
}

aoa_mq_lock_release() {
  [ "$(cat "$MQ_DIR/.tick.lock.pid" 2>/dev/null)" = "$$" ] && rm -f "$MQ_DIR/.tick.lock.pid"
  rmdir "$MQ_DIR/.tick.lock" 2>/dev/null
  return 0
}

aoa_mq_lock_acquire() { # $1=최대 대기(초, 기본 10)
  # 호출자가 이미 락을 쥔 경우(tick 의 위임 호출) — 재진입 허용
  [ -n "${AOA_MQ_LOCK_HELD:-}" ] && return 0

  local maxw="${1:-10}" waited=0 stale owner age
  stale=$(grep -E "^[[:space:]]*lock_stale_mins:" "$MQ_DIR/policy.yml" 2>/dev/null | head -1 \
      | sed -E 's/^[^:]*:[[:space:]]*//; s/[[:space:]]*#.*$//; s/[[:space:]]*$//')
  case "${stale:-}" in ''|*[!0-9]*) stale=30 ;; esac

  while ! mkdir "$MQ_DIR/.tick.lock" 2>/dev/null; do
    age=$(( ( $(date +%s) - $(aoa_mq_mtime_of "$MQ_DIR/.tick.lock") ) / 60 ))
    owner=$(aoa_mq_lock_owner_pid)
    # 고아(보유 PID 가 죽음)면 나이와 무관하게 즉시 탈취 (Issue633).
    # 나이 탈취는 *생사를 모르거나 살아는 있으나 멎은* 경우의 폴백으로 남긴다.
    if [ -n "$owner" ] && ! kill -0 "$owner" 2>/dev/null; then
      rm -rf "$MQ_DIR/.tick.lock" 2>/dev/null; rm -f "$MQ_DIR/.tick.lock.pid"
    elif [ "$age" -ge "$stale" ]; then
      rm -rf "$MQ_DIR/.tick.lock" 2>/dev/null; rm -f "$MQ_DIR/.tick.lock.pid"
    fi
    waited=$((waited+1))
    [ "$waited" -gt "$maxw" ] && die "tick 진행 중(lock ${age}m) — ${maxw}초 대기 후 포기. 잠시 뒤 재시도"
    sleep 1
  done
  printf '%s' "$$" > "$MQ_DIR/.tick.lock.pid"
  trap 'aoa_mq_lock_release; exit 143' TERM
  trap 'aoa_mq_lock_release; exit 130' INT
  trap aoa_mq_lock_release EXIT
  return 0
}
