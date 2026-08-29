#!/usr/bin/env bash
# fbot-agent-bind.sh — PreToolUse(`Agent`) 배선, Issue449
#
# ⚠️ 글로벌 SCAR 변경 가드 (Issue46): 본 hook 은 모든 프로젝트가 공유.
#   cwd ≠ ~/.claude 면 즉시 수정 금지 → ~/.claude/Issue.md 이슈 등록 후 처리.
#   배선 색인: ~/.claude/_doc_arch/hook-arch.md · 절차: ~/.claude/_doc_arch/rules-ondemand/hook-rules.md
#
# 발동: Agent 도구 호출 직전, **그 스폰이 핀봇 스폰일 때만**.
#       tool_input 에서 bot_id 를 뽑아 레지스트리에 실재하면 `fbot-state.py bind` 를 부른다.
# no-op: Agent 스폰이 아니거나(matcher 가 이미 거른다) 페이로드에 `fbot-` 문자열이 없으면
#        jq 를 부르기 전에 bash 문자열 비교로 즉시 exit 0 (규칙3 — 싼 판정부터).
#
# 왜 이 자리인가 (Issue449 실측 2026-08-26, probe 3회):
#   ① **SessionStart 계열은 Agent 스폰에서 발화하지 않는다** — 후보 ⓐ 는 실측으로 탈락했다.
#      probe 를 dispatch-sessionstart.sh 에 걸고 Agent 3개를 스폰했으나 이벤트 0건.
#   ② **Agent 의 session_id 는 부모(메인) 세션과 같다** — 스폰하는 쪽이 이미 자식의
#      session_id 를 알고 있다. 근거: 트랜스크립트 `2fbaef6d….jsonl` 은 sidechain 항목이
#      0건인 **메인 대화**인데, 서로 다른 agent_id 4개가 전부 그 session_id 를 보고했다.
#   ③ 따라서 결속 1줄을 **프롬프트에 붙일 필요조차 없다**. 훅이 직접 bind 하면 되고,
#      LLM 이 그 줄을 실행하는지에 의존하지 않는다. 후보 ⓑ("스폰 측 책임")의 가장 강한 형태다.
#
# ⚠️ NULL 의 의미를 흐리지 않는다 (Issue448 계승): `--tmux-target` 은 **건드리지 않는다**.
#   Agent 는 pane 이 원래 없다. "결속 실패" 와 "pane 없는 실행 형태" 는 다른 사건이다.
#   여기서 빈 pane 값을 쓰면 Issue445 의 `unknown` 판정이 fail-open 에서 fail-wrong 이 된다.
#
# ⚠️ 스폰을 막지 않는다. 미등록 bot_id 는 stderr 경고 + 로그만 남기고 exit 0 한다 —
#   채용 가부 판정은 인사핀봇 게이트(F3)의 몫이지 이 훅의 몫이 아니다. 판정 지점을
#   둘로 늘리면 갈라진다(규칙5).
#
# 출력 없음 — permissionDecision·updatedInput 을 쓰지 않으므로 배선은 `async`.

set -uo pipefail

input=$(cat)

# ── ① 무비용 가드: 페이로드에 `fbot-` 이 없으면 핀봇 스폰이 아니다 (fork 0회) ──────
case "$input" in
  *fbot-*) ;;
  *) exit 0 ;;
esac

# 형제 hook 경로 (Issue460 — Issue451 과 같은 결함이 남아 있던 자리)
#   소비자는 SCAR 를 **플러그인**으로 받으므로 `~/.claude/hooks` 가 존재하지 않는다.
#   훅 자체는 플러그인 경로에서 정상 발화하는데(env·매뉴얼 주입까지 성공) 그 안에서
#   부르는 헬퍼만 `~/.claude/hooks` 를 가리켜 **조용히 실패**했다 — fg1 실측:
#   `SID`·`FBOT_ID` 는 정상 도착하는데 `bind`·`transition` 이 안 먹어 결속·전이가 0.
#   자기 위치가 곧 형제들의 위치다. 개발 머신(prj3)에서도 같은 값이 나온다.
_HOOKS_SELF="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
STATE_PY="$_HOOKS_SELF/fbot-state.py"
[ -f "$STATE_PY" ] || exit 0             # 상태 헬퍼 부재 = 배관 미완 → 조용히 no-op

command -v jq >/dev/null 2>&1 || exit 0  # jq 부재는 fail-soft (스폰을 막지 않는다)

sid=$(printf '%s' "$input" | jq -r '.session_id // empty' 2>/dev/null)
[ -n "$sid" ] || exit 0

# ── ② bot_id 후보 추출 ────────────────────────────────────────────────────────
#   1순위: tool_input.name — 핀봇 스폰은 Agent 이름을 bot_id 로 준다(SendMessage 주소와 일치).
#   2순위: 프롬프트 본문의 첫 `fbot-…` 토큰 — 스폰 프롬프트가 자기 정체를 밝히는 자리다.
#   ⚠️ 추출은 후보를 만들 뿐이다. **실재 판정은 레지스트리가 한다**(아래 ③).
cands=$(printf '%s' "$input" | jq -r '
    [ (.tool_input.name // empty),
      ((.tool_input.prompt // "") | [scan("fbot-[A-Za-z0-9_-]+")] | .[]) ]
    | map(select(startswith("fbot-"))) | unique | .[]
  ' 2>/dev/null)
[ -n "$cands" ] || exit 0

LOG="$HOME/.claude/.fbot-handoff/agent-bind.log"
mkdir -p "$(dirname "$LOG")" 2>/dev/null

# ── ③ 레지스트리 실재 확인 후 결속 ─────────────────────────────────────────────
#   후보가 여러 개면 **실재하는 첫 1건만** 결속한다. 한 스폰은 한 봇이다 —
#   여러 건을 결속하면 그 자체가 오귀속이다.
bound=""
while IFS= read -r cand; do
  [ -n "$cand" ] || continue
  if python3 "$STATE_PY" get --bot-id "$cand" >/dev/null 2>&1; then
    if python3 "$STATE_PY" bind --bot-id "$cand" --session-id "$sid" >/dev/null 2>&1; then
      bound="$cand"
      printf '%s bind ok bot=%s sid=%s\n' "$(date +%Y-%m-%dT%H:%M:%S)" "$cand" "$sid" >> "$LOG"
        # ── ④ 출근 전이 (2026-08-26, hub 모니터링 실측) ─────────────────────────
        #   결속만으로는 부족하다. hub 는 **`checkout` 이 아닌 봇**만 활성으로 세므로
        #   (`_collect_bots()`), bind 만 하고 상태를 두면 Agent 봇은 **일하는 중에도
        #   hub 에 보이지 않는다** — 실측으로 확인된 모니터링 공백의 원인이다.
        #   tmux `-p` 위임 봇은 SessionStart 훅이 출근시키지만 Agent 세션에는 그 훅이
        #   오지 않는다(Issue449 probe 실측 0건). 그 자리를 여기서 메운다.
        # ⚠️ `checkin` 까지만 올린다 — `checkin→working` 의 계약상 사유는 "매뉴얼+봇별
        #   상태 로드 완료" 인데 본 훅은 그것을 하지 않는다. 거짓 상태를 만들지 않는다.
        # ⚠️ 이미 활성이면 전이가 **정상 거부**된다(TRANSITIONS 표) — fail-soft.
        if python3 "$STATE_PY" transition --bot-id "$cand" --to checkin >/dev/null 2>&1; then
          printf '%s checkin ok bot=%s\n' "$(date +%Y-%m-%dT%H:%M:%S)" "$cand" >> "$LOG"
        else
          printf '%s checkin skip bot=%s (이미 활성이거나 전이 불가)\n' \
            "$(date +%Y-%m-%dT%H:%M:%S)" "$cand" >> "$LOG"
        fi
    else
      printf '%s bind FAIL bot=%s sid=%s\n' "$(date +%Y-%m-%dT%H:%M:%S)" "$cand" "$sid" >> "$LOG"
    fi
    break
  fi
done <<< "$cands"

if [ -z "$bound" ]; then
  # 미등록 — 채용 게이트를 안 탄 스폰일 수 있다. 막지는 않되 흔적은 남긴다(fail-loud 로그).
  printf '%s unregistered cand=[%s] sid=%s\n' \
    "$(date +%Y-%m-%dT%H:%M:%S)" "$(printf '%s' "$cands" | tr '\n' ' ')" "$sid" >> "$LOG"
fi

exit 0
