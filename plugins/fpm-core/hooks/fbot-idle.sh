#!/usr/bin/env bash
# fbot-idle.sh — 턴 종료 시 결속 봇을 수신대기(waiting_input)로 (dispatch-stop.sh 의 자식), prj3#Issue554
#
# ⚠️ 글로벌 SCAR 변경 가드 (prj1#Issue46): 본 hook 은 모든 프로젝트가 공유.
#   cwd ≠ ~/.claude 면 즉시 수정 금지 → ~/.claude/Issue.md 이슈 등록 후 처리.
#   배선 색인: ~/.claude/_doc_arch/hook-arch.md · 절차: ~/.claude/_doc_arch/rules-ondemand/hook-rules.md
#   설계 SSOT: ~/.claude/_doc_arch/fbot-manager-design.md "§유휴는 사망이 아니다"
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

_SID="${CLAUDE_CODE_SESSION_ID:-${HOOK_SESSION_ID:-}}"
[ -n "$_SID" ] || exit 0
[ -f "$HOME/.claude/.fbot-handoff/sid-$_SID.id" ] || exit 0     # ← 무비용 게이트

_HOOKS_SELF="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
STATE_PY="$_HOOKS_SELF/fbot-state.py"
[ -f "$STATE_PY" ] || exit 0
python3 "$STATE_PY" idle --session-id "$_SID" >/dev/null 2>&1 || true   # fail-soft — 턴 종료를 막지 않는다
exit 0
