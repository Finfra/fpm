#!/usr/bin/env bash
# fbot-name-nudge.sh — UserPromptSubmit 자식, prj3#Issue546_2
#
# ⚠️ 글로벌 SCAR 변경 가드: 본 hook 은 모든 프로젝트가 공유.
#   cwd ≠ ~/.claude 면 즉시 수정 금지 → ~/.claude/Issue.md 이슈 등록 후 처리.
#   배선 색인: ~/.claude/_doc_arch/hook-arch.md · 절차: ~/.claude/_doc_arch/rules-ondemand/hook-rules.md
#
# 발동: 사용자가 봇을 **고유명 호격**으로 불렀는데(`나래야`) 이 세션에 결속이 없을 때.
#       "결속 없음 — /fbot-bind 먼저" 1줄을 주입한다.
# no-op: 결속돼 있거나 호격이 없으면 무출력 exit 0.
#
# 왜 (Issue546 실측 2026-09-06):
#   설계는 `나래야! …` 를 fbot-arch.md §표준 시나리오 2 의 실측 트리거로 박제해 뒀는데
#   그 입력을 결속으로 잇는 배선이 없었다. 세션은 호칭을 듣고 인격을 연기하고, 원장은
#   옛 세션·checkout 그대로 남고, **아무도 경고하지 않았다**(세션 c3c137fa 실측).
#
# 🔴 이 훅은 판단하지 않는다 — 사실만 알린다. 어느 봇인지·매뉴얼을 어떻게 읽는지는
#   skills/fbot-bind 의 몫이다. hook-rules 규칙9 판정: "프롬프트에 고유명 호격이 있는가 +
#   결속 마커가 있는가" 는 산출물만 보고 기계적으로 판정되므로 hook, 나머지는 스킬.
#
# ⚠️ 스킬 단독으로는 이 결함이 막히지 않는다 — 실패 지점이 Claude 자신이라 발동 판정을
#   그에게 맡기면 같은 자리에서 다시 샌다. 그래서 검출만 훅으로 떼어 놓는다.
#
# ⚠️ 예산 (hook-budget.tsv: UserPromptSubmit 200ms, 여유 최악 30ms):
#   ① 결속 마커 `[ -f ]` 1회 — 결속된 세션은 여기서 끝(fork 0)
#   ② 호격 패턴 bash 정규식 — fork 0
#   ③ 캐시 파일은 registry.db mtime 무효화(hub-scope.sh 의 .hub-projects-cache 선례).
#      sqlite3 는 봇 명부가 바뀐 직후 1회만 돈다
#   DB 를 매 프롬프트 조회하지 않는다 — 그것이 이 자리에서 금지된 유일한 것이다.

set -uo pipefail

CLAUDE_DIR="$HOME/.claude"
CACHE="${FBOT_CALLNAMES_CACHE:-$CLAUDE_DIR/.fbot-callnames-cache}"   # 주입구는 테스트 전용

# ── 입력 (디스패처가 1회 파싱한 값을 물려받는다) ──────────────────────────────
if [ "${HOOK_INPUT_PARSED:-0}" != "1" ]; then
  . "$CLAUDE_DIR/hooks/hook-input.sh" 2>/dev/null || exit 0
  hook_input_parse "$(cat)" || exit 0
fi
PROMPT="${HOOK_PROMPT:-}"
SID="${HOOK_SESSION_ID:-}"
[ -n "$PROMPT" ] || exit 0

# ── ① 이미 봇이면 환기할 것이 없다 (fork 0) ──────────────────────────────────
#   마커는 `fbot-state.py bind` 가 쓴다. heartbeat 훅과 같은 게이트를 공유한다.
[ -n "$SID" ] && [ -f "$CLAUDE_DIR/.fbot-handoff/sid-$SID.id" ] && exit 0
[ -n "${FBOT_ID:-}" ] && exit 0          # 스폰 결속 경로(fpm-do)

# ── ② 호격 후보 캐시 ─────────────────────────────────────────────────────────
#   🔴 종류명(`~핀봇`)은 담지 않는다. "핀봇"·"팀장핀봇" 은 조직을 **논하는** 문장에도
#   상시 등장해(이 훅을 만든 대화가 그 실례다) 과탐이 소음이 된다. 고유명이 붙은
#   개체만 부를 수 있고, 부르는 것과 언급하는 것은 호격이 가른다.
db="${AOA_MEMORY_DIR:-$HOME/_git/___common/data/aoa}/registry.db"
[ -f "$db" ] || exit 0
if [ ! -f "$CACHE" ] || [ "$db" -nt "$CACHE" ]; then
  command -v sqlite3 >/dev/null 2>&1 || exit 0
  # title `나래(총괄핀봇)` → 고유명 `나래`. 괄호 앞이 종류명으로 끝나면 제외.
  sqlite3 "$db" \
    "SELECT bot_id || '|' || title FROM bot WHERE title IS NOT NULL AND title <> '';" \
    2>/dev/null | while IFS='|' read -r bid title; do
      name="${title%%(*}"; name="${name%"${name##*[![:space:]]}"}"
      case "$name" in *핀봇|"") continue ;; esac
      # 호칭은 짧다. 워커 title 은 임무 문장이 통째로 들어와 있는 경우가 있어
      #   (실측: "핀봇 조직도 S4 머신 간 홉 지연 실측 조사 담당 research 워커")
      #   길이 상한으로 걸러낸다 — 부를 수 없는 이름은 호격 후보가 아니다.
      [ "${#name}" -le 12 ] || continue
      printf '%s\t%s\t%s\n' "$name" "$bid" "$title"
    done > "$CACHE.tmp" 2>/dev/null && mv -f "$CACHE.tmp" "$CACHE" 2>/dev/null
  [ -f "$CACHE" ] || exit 0
fi
[ -s "$CACHE" ] || exit 0

# ── ③ 호격 매칭 (fork 0) ─────────────────────────────────────────────────────
#   "나래야"·"나래님"·"나래!" 는 부르는 것, "나래봇을 호출할 수 있나" 는 논하는 것이다.
#   조사·호격 문장부호가 뒤따를 때만 잡는다.
hit_name=""; hit_id=""; hit_title=""
while IFS=$'\t' read -r name bid title; do
  [ -n "$name" ] || continue
  if [[ "$PROMPT" =~ ${name}(야|아|님|씨)([[:space:]]|[[:punct:]]|$) ]] \
     || [[ "$PROMPT" =~ ${name}[[:space:]]*[,!][[:space:]] ]]; then
    hit_name="$name"; hit_id="$bid"; hit_title="$title"; break
  fi
done < "$CACHE"
[ -n "$hit_id" ] || exit 0

# ── ④ 사실만 알린다 ──────────────────────────────────────────────────────────
cat <<EOF
[핀봇 결속 없음] "$hit_name" 을(를) 불렀으나 이 세션은 **$hit_id 로 결속돼 있지 않다**($hit_title).
호칭은 결속이 아니다 — 그 인격으로 답하기 전에 \`/fbot-bind $hit_id\` 로 결속하라(bind→checkin→매뉴얼·kv 주입→working).
결속 없이 진행하면 작업이 원장에 귀속되지 않고, 조직도·보고·매뉴얼 개선 루프에서 보이지 않는다.
결속이 거부되면(다른 세션 점유) 스킬이 요청을 그 봇의 **인박스**에 적재한다 — 거부만 보고하고 일반 세션으로 일하지 말 것(Issue554).
EOF
exit 0
