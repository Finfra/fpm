#!/usr/bin/env bash
# fbot-agent-map.sh — PreToolUse(Agent)·SubagentStart·SubagentStop hook, prj3#Issue739 M1-3
#
# ⚠️ 글로벌 SCAR 변경 가드 (Issue46): 본 hook 은 모든 프로젝트가 공유.
#   cwd ≠ ~/.claude 면 즉시 수정 금지 → ~/.claude/Issue.md 이슈 등록 후 처리.
#   배선 색인: ~/.claude/_doc_arch/hook-arch.md · 절차: ~/.claude/_doc_arch/rules-ondemand/hook-rules.md
#
# 왜 (M1-1 실측, 설계 fbot-org §이슈 축 연동 결정 2): 서브에이전트 안의 도구 호출은 stdin 에 `agent_id` 를 주지만
#   그 id 가 **어느 봇인지**는 `PreToolUse(Agent)` 의 `tool_input.name` 에만 있다. `SubagentStart` 는 이름 없이
#   `agent_id`·`agent_type` 만 준다. 백그라운드 스폰은 PostToolUse `async_launched` 의 `agentId` 로 이미 잇지만
#   (fbot-agent-done.sh → `agent-<id>.bot`), **포그라운드는 잇는 자리가 없었다** — 그 봇의 SendMessage 가 송신자 미상이 된다.
#   두 이벤트를 **한 스크립트**가 받아 자기 상태 파일(`agentq-<sid>.tsv`)로 잇는다(hook-rules 규칙8 — 자기 상태 파일 예외).
#
# 발동:
#   PreToolUse(Agent) — 대기 1줄 `<epoch>\t<agent_type>\t<name>\t<bg>` 적재(비핀봇도 센다 — 병렬 스폰 오매핑 방지)
#   SubagentStart     — 같은 세션·같은 타입의 미만료(120초) 대기가 **정확히 1건**이면 소비하고, 포그라운드 핀봇(`fbot-*`)이면
#                       `agentfg-<agent_id>.bot` = bot_id. 2건+ 는 고르지 않는다(whois 1:N 원칙)
#                       ⚠️ 마커 이름을 `agent-<id>.bot` 과 가른다 — 그것은 SubagentStop 퇴근 집행 신호라 포그라운드에 쓰면 두 번 퇴근한다
#   SubagentStop      — 자기 마커 `agentfg-<agent_id>.bot` 을 걷는다(+ 2시간 넘은 고아 정리)
# no-op: 다른 이벤트·도구 · session_id·agent_id 없음 · 대기 파일 없음 (fork 0회 — 문자열 판정만)
#
# 출력 없음 — 스폰·도구를 막지 않는다. 실패는 조용히 exit 0(fail-soft).
set -uo pipefail

input=$(cat)
HD="${FBOT_HANDOFF_DIR:-$HOME/.claude/.fbot-handoff}"
TTL=120

_get() {   # 최상위·중첩 무관 첫 문자열 값 — 이스케이프된 본문(\"k\")은 맞지 않는다
  [[ "$input" =~ \"$1\"[[:space:]]*:[[:space:]]*\"([^\"]*)\" ]] && printf '%s' "${BASH_REMATCH[1]}"
}
_safe() { [[ "$1" =~ ^[A-Za-z0-9_.-]+$ ]]; }
_now() { printf '%s' "${EPOCHSECONDS:-$(date +%s)}"; }

ev=$(_get hook_event_name)   # 본문(last_assistant_message 등)의 같은 단어에 속지 않게 키 값으로 가른다
case "$ev" in
  PreToolUse)
    [[ "$input" =~ \"tool_name\"[[:space:]]*:[[:space:]]*\"Agent\" ]] || exit 0
    # prj3#Issue849 — 형제 agent-model-guard.sh 가 거부할 호출은 대기열에 올리지 않는다(남으면 같은 타입 재호출이
    #   «2건+ 는 고르지 않는다» 에 걸려 매핑을 잃는다). 판정은 같은 라이브러리 — fable 문자열이 없으면 fork 0
    if [[ "$input" == *'"fable"'* ]] && . "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/agent-model-verdict.sh" 2>/dev/null \
       && agent_model_verdict "$input" >/dev/null; then
      exit 0
    fi
    sid=$(_get session_id); _safe "$sid" || exit 0
    typ=$(_get subagent_type); [ -n "$typ" ] || typ="general-purpose"
    name=$(_get name); _safe "$name" || name="-"
    bg=0; [[ "$input" =~ \"run_in_background\"[[:space:]]*:[[:space:]]*(true|\"[Tt]rue\") ]] && bg=1
    mkdir -p "$HD" 2>/dev/null || exit 0
    printf '%s\t%s\t%s\t%s\n' "$(_now)" "$typ" "$name" "$bg" >> "$HD/agentq-$sid.tsv"
    exit 0 ;;
  SubagentStart)
    sid=$(_get session_id); aid=$(_get agent_id); typ=$(_get agent_type)
    _safe "$sid" && _safe "$aid" || exit 0
    q="$HD/agentq-$sid.tsv"; [ -f "$q" ] || exit 0
    lock="$q.lock"; for _i in 1 2 3 4 5 6 7 8 9 10; do mkdir "$lock" 2>/dev/null && break; sleep 0.02; done
    now=$(_now); keep=(); hit=(); n=0
    while IFS=$'\t' read -r ts t nm b; do
      [ -n "${ts:-}" ] || continue
      (( now - ts > TTL )) && continue                     # 만료는 버린다
      if [ "$t" = "${typ:-general-purpose}" ]; then hit+=("$ts"$'\t'"$t"$'\t'"$nm"$'\t'"$b"); n=$((n + 1))
      else keep+=("$ts"$'\t'"$t"$'\t'"$nm"$'\t'"$b"); fi
    done < "$q"
    if [ "$n" -eq 1 ]; then
      IFS=$'\t' read -r _ts _t nm b <<< "${hit[0]}"
      if [ "$b" = "0" ] && [[ "$nm" == fbot-* ]]; then printf '%s\n' "$nm" > "$HD/agentfg-$aid.bot"; fi
    else
      keep+=("${hit[@]+"${hit[@]}"}")                         # 0건·2건+ — 고르지 않고 남긴다(만료가 정리)
    fi
    if [ "${#keep[@]}" -gt 0 ]; then printf '%s\n' "${keep[@]}" > "$q.tmp" && mv "$q.tmp" "$q"; else rm -f "$q"; fi
    rmdir "$lock" 2>/dev/null
    exit 0 ;;
  SubagentStop)
    aid=$(_get agent_id); _safe "$aid" || exit 0
    rm -f "$HD/agentfg-$aid.bot" 2>/dev/null
    find "$HD" -maxdepth 1 \( -name 'agentfg-*.bot' -o -name 'agentq-*.tsv' \) -mmin +120 -delete 2>/dev/null
    exit 0 ;;
esac
exit 0
