#!/usr/bin/env bash
# dispatch-sessionstart.sh — SessionStart 이벤트 단일 진입점, Issue436_3
#
# ⚠️ 글로벌 SCAR 변경 가드 (Issue46): 본 hook 은 모든 프로젝트가 공유.
#   cwd ≠ ~/.claude 면 즉시 수정 금지 → ~/.claude/Issue.md 이슈 등록 후 처리.
#   배선 색인: ~/.claude/_doc_arch/hook-arch.md · 절차: ~/.claude/_doc_arch/rules-ondemand/hook-rules.md
#
# 발동: 매 SessionStart. 자식 hook 을 **병렬** 실행하고 출력을 하나의 JSON 으로 병합한다.
# no-op: 자식이 전부 무출력이면 아무 것도 출력하지 않는다(exit 0).
#
# 왜 dispatch 인가 (Issue424 와 같은 이유) — 이벤트마다 settings.json 에 개별 배선이 쌓이면
#   사용자가 손대지 못하는 JSON 이 된다. SessionStart 도 자식이 3건이 되는 시점에 묶는다.
#   되돌리려면 아래 CHILDREN 을 settings.json 으로 도로 펴면 된다(스크립트는 그대로다).
#
# UserPromptSubmit dispatch 와 같은 점 — **출력을 병합한다**. SessionStart 는 Stop 과 달리
#   additionalContext 주입 이벤트라, 자식 둘이 각자 JSON 을 뱉으면 파서가 깨진다.
# 다른 점 — hook-input.sh 를 source 하지 않는다. SessionStart 자식 중 HOOK_* 를 소비하는
#   것이 없어 jq 파싱(≈4ms)이 순수 비용이다. 소비자가 생기면 그때 붙인다.
#   exit 2 특례도 두지 않는다 — SessionStart 에는 차단 규약이 없다.

set -u

HOOKS_DIR="$HOME/.claude/hooks"

input=$(cat)

TMPD=$(mktemp -d "${TMPDIR:-/tmp}/ssdispatch.XXXXXX") || exit 0
trap 'rm -rf "$TMPD"' EXIT

# 출력 병합 순서를 고정하기 위해 인덱스를 파일명에 박는다(완료 순서와 무관).
# ⚠️ 병렬이므로 자식 간 순서 의존 금지(hook-rules 규칙8). 셋 다 서로의 산출물을 읽지 않는다.
# ⚠️ 아래 배열 안의 주석에 **닫는 괄호를 쓰지 말 것** — hook-counts.py 의 CHILDREN 파싱이
#    비탐욕 정규식이라 첫 괄호에서 끊기고, 그 뒤 자식이 전부 orphan 으로 오판된다.
CHILDREN=(
  "0|$HOOKS_DIR/fpm-hub-session-register.sh"   # hub live 카드 등록 — 서버 미기동 시 무시
  "1|$HOOKS_DIR/pm-do-safety-context.sh"       # 위임 세션 안전 지시 — Issue351
  "2|$HOOKS_DIR/fbot-checkin.sh"               # 핀봇 출근: 매뉴얼·kv 복원 — Issue436_3
)

for spec in "${CHILDREN[@]}"; do
  idx="${spec%%|*}"; script="${spec#*|}"
  [ -f "$script" ] || continue
  {
    printf '%s' "$input" | bash "$script" > "$TMPD/$idx.out" 2>/dev/null
  } &
done
wait

# --- 결과 회수 (배선 순서대로) ---
outs=()
for spec in "${CHILDREN[@]}"; do
  idx="${spec%%|*}"
  out=$(cat "$TMPD/$idx.out" 2>/dev/null || true)
  [ -n "$out" ] && outs+=("$out")
done

[ "${#outs[@]}" -eq 0 ] && exit 0

# --- 출력 병합: 여러 JSON 의 additionalContext 를 하나로 합친다 ---
ctx=""
for o in "${outs[@]}"; do
  piece=$(printf '%s' "$o" | jq -r '.hookSpecificOutput.additionalContext // .additionalContext // empty' 2>/dev/null)
  [ -z "$piece" ] && piece="$o"      # JSON 이 아니거나 필드가 없으면 원문을 그대로 컨텍스트로
  [ -z "$piece" ] && continue
  if [ -z "$ctx" ]; then ctx="$piece"; else ctx="$ctx

$piece"; fi
done

[ -z "$ctx" ] && exit 0

merged=$(CTX="$ctx" jq -n --arg ev SessionStart \
  '{hookSpecificOutput: {hookEventName: $ev, additionalContext: env.CTX}}' 2>/dev/null)

if [ -n "$merged" ]; then
  printf '%s\n' "$merged"
else
  printf '%s\n' "$ctx"   # jq 부재·인코딩 실패 시에도 컨텍스트를 잃지 않는다(fail-soft)
fi

exit 0
