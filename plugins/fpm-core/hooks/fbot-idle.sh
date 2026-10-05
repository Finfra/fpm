#!/usr/bin/env bash
# fbot-idle.sh — 턴 종료 시 결속 봇을 수신대기(waiting_input)로 (dispatch-stop.sh 의 자식), prj3#Issue554
#
# ⚠️ 글로벌 SCAR 변경 가드 (prj1#Issue46): 본 hook 은 모든 프로젝트가 공유.
#   cwd ≠ ~/.claude 면 즉시 수정 금지 → ~/.claude/Issue.md 이슈 등록 후 처리.
#   배선 색인: ~/.claude/_doc_arch/hook-arch.md · 절차: ~/.claude/_doc_arch/rules-ondemand/hook-rules.md
#   설계 SSOT: ~/.claude/_doc_arch/fbot-manager.md "§유휴는 사망이 아니다"
#
# 발동: 이 세션에 결속된 봇이 있을 때(결속 마커 존재) 매 Stop. `working → waiting_input` 전이 +
#   `.hb` 스탬프 제거(다음 프롬프트의 heartbeat 가 스로틀 없이 즉시 돌아 `working` 으로 복귀한다).
# no-op: 결속 마커 부재(= 일반 세션) → 첫 블록 exit 0, fork 0회. 헬퍼 부재도 조용히 exit 0.
#
# 왜 (2026-09-06 실측, Issue554):
#   결속 세션이 사용자 입력을 기다리는 7분 동안 도구 호출이 없어 heartbeat 가 0회 → lease(300초)
#   만료 → 타 세션이 `dead` 로 좌석을 가져갔다. 세션은 살아 있었다. lease 는 **생존** 신호라
#   유휴를 표현할 수 없다 — 상태 축(waiting_input)이 그것을 말한다. 선점 판정은 이 상태를 보고
#   `idle`(인계 허용·기록)로 답하고, reap 은 idle TTL 만큼 더 기다린다.
#
# 규칙8 (독립성): 다른 자식의 산출물을 읽지 않는다. 마커 파일과 DB 만 본다.
#
# 응답 defer (prj3#Issue736, 2026-09-27) — **pm-do 가 띄운 `-p` 몸체**(FPM_SESSION_ORIGIN=pm-do)는 응답 1회 뒤
#   종료되고 pane 은 zsh 로 돌아간다. 사용자 응답을 기다리는 말로 끝나도 그 세션에 닿을 사람이 없다(prj13 실발생).
#   그래서 이 게이트에서만 마지막 assistant 텍스트를 **그 일을 받은 매니저**(기원 요청 발신자·배분자 → 부모 → 총괄, Issue791)의 인박스로
#   올린다 — 판정·적재는 fbot-inbox.py `defer` 단일 지점. 사람이 띄운 결속 세션은 종전 그대로(사람이 pane 을 본다).

_SID="${CLAUDE_CODE_SESSION_ID:-${HOOK_SESSION_ID:-}}"
[ -n "$_SID" ] || exit 0
[ -f "$HOME/.claude/.fbot-handoff/sid-$_SID.id" ] || exit 0     # ← 무비용 게이트

_HOOKS_SELF="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"

# prj3#Issue951 — `-p` 몸체의 미완 백그라운드 판정(lib/session-end.py `stop_verdict`). **결속 몸체는 여기가 유일한 판정 자리**다 —
#   pm-do-bg-guard.sh 는 결속 마커가 있으면 물러난다(게이트 상호 배타 · 규칙8 «순서가 필요하면 합친다»). 두 훅이 따로 판정하면
#   nonexec 조회·transcript 읽기가 갈려 «가드는 안 막았는데 여기선 block 으로 보고 인계를 건너뜀» 이 생긴다(리뷰 M1 재현).
#   stdin 은 이 분기에서만 읽는다(일반 세션 fork 0회 유지). 헬퍼 확인보다 앞이다 — 헬퍼가 없어도 block 은 낸다.
#   block   — Stop 훅 출력 JSON 을 여기서 내고 끝낸다. 턴이 이어지므로 수신대기 전이도 인계도 하지 않는다
#   abandon — 되돌린 뒤에도 끝냈다. 작업은 프로세스와 함께 죽는다 → 즉시 incomplete 보고 + 퇴근 기록(SessionEnd 를 기다리지 않는다
#             — 실측에서 이 경로의 SessionEnd 퇴근 기록이 남지 않았다)
#   비실행 관리직(총괄·팀장)은 판정하지 않는다 — fbot-org `nonexec` 단일 지점(대기 루프만 죽는다)
_IN=""; _BGV="ok"; _BGREST=""
_PMDO=0; [ "${FPM_SESSION_ORIGIN:-}" = "pm-do" ] && _PMDO=1   # 게이트 판정은 한 번 — 아래 두 분기가 같은 값을 쓴다
if [ "$_PMDO" = 1 ]; then
  _IN=$(< /dev/stdin)
  _LIB="$_HOOKS_SELF/lib/session-end.py"
  _NX="false"
  [ -n "${FBOT_ID:-}" ] && [ -f "$_HOOKS_SELF/fbot-org.py" ] \
    && _NX="$(python3 "$_HOOKS_SELF/fbot-org.py" nonexec --bot-id "$FBOT_ID" 2>/dev/null)"
  if [ -f "$_LIB" ] && [ "$_NX" != "true" ]; then
    _V="$(printf '%s' "$_IN" | python3 "$_LIB" stop-verdict --sh 2>/dev/null)" || _V="ok"
    _NL=$'\n'                       # bash 3.2 — 큰따옴표 안 패턴에 $'…' 를 직접 쓰지 않는다
    _BGV="${_V%%"$_NL"*}"
    [ "$_V" = "$_BGV" ] || _BGREST="${_V#*"$_NL"}"
  fi
  if [ "$_BGV" = "block" ]; then
    [ -n "$_BGREST" ] && printf '%s\n' "$_BGREST"   # 판정한 그 결과를 그대로 — 다시 판정하지 않는다
    exit 0
  fi
fi

STATE_PY="$_HOOKS_SELF/fbot-state.py"
[ -f "$STATE_PY" ] || exit 0

python3 "$STATE_PY" idle --session-id "$_SID" >/dev/null 2>&1 || true   # fail-soft — 턴 종료를 막지 않는다

# prj3#Issue736 — 응답 받을 사람이 없는 몸체(pm-do `-p`)만.
if [ "$_PMDO" = 1 ]; then
  INBOX_PY="$_HOOKS_SELF/fbot-inbox.py"
  if [ -f "$INBOX_PY" ]; then
    _TR="${HOOK_TRANSCRIPT:-}"
    if [ -z "$_TR" ]; then
      _TR="$(printf '%s' "$_IN" | python3 -c 'import sys,json
try: print(json.load(sys.stdin).get("transcript_path") or "")
except Exception: print("")' 2>/dev/null)"
    fi
    _DEFER_EXTRA=()
    [ "$_BGV" = "abandon" ] && _DEFER_EXTRA=(--status incomplete --note "$_BGREST")
    _LOGD="$HOME/.claude/data/fbot/logs"; mkdir -p "$_LOGD" 2>/dev/null
    { printf '[%s] sid=%s bot=%s%s\n' "$(date '+%F %T')" "$_SID" "${FBOT_ID:-?}" "${_DEFER_EXTRA:+ bg=abandon}"
      python3 "$INBOX_PY" defer --from-bot "${FBOT_ID:-}" --from-session "$_SID" --transcript "$_TR" "${_DEFER_EXTRA[@]}"
    } >>"$_LOGD/defer.log" 2>&1 || true   # fail-soft — 인계 실패가 턴 종료를 막지 않는다. 사유는 로그에 남는다
  fi
  # prj3#Issue951 C — 포기 경로는 여기서 퇴근을 적는다(판정·기록은 fbot-checkout.sh 그대로 — at_stop 표지로 SessionEnd 중복 기록 방지)
  if [ "$_BGV" = "abandon" ] && [ -f "$_HOOKS_SELF/fbot-checkout.sh" ]; then
    printf '%s' "$_IN" | FBOT_CHECKOUT_AT_STOP=1 CLAUDE_CODE_SESSION_ID="$_SID" bash "$_HOOKS_SELF/fbot-checkout.sh" \
      >/dev/null 2>&1 || true
  fi
fi
exit 0
