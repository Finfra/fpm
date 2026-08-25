#!/usr/bin/env bash
# dispatch-sessionend.sh — SessionEnd 이벤트 단일 진입점, Issue436_3
#
# ⚠️ 글로벌 SCAR 변경 가드 (Issue46): 본 hook 은 모든 프로젝트가 공유.
#   cwd ≠ ~/.claude 면 즉시 수정 금지 → ~/.claude/Issue.md 이슈 등록 후 처리.
#   배선 색인: ~/.claude/_doc_arch/hook-arch.md · 절차: ~/.claude/_doc_arch/rules-ondemand/hook-rules.md
#
# 발동: 매 SessionEnd(세션 종료 시 1회). 자식을 **병렬** 실행한다.
# 출력 병합 없음 — SessionEnd 는 컨텍스트 주입 이벤트가 아니다(부작용 전용). exit 0 고정.
#
# 왜 여기인가 (fbot 퇴근 — 계약 F2 정정, 2026-08-24 실측):
#   Stop 은 **턴 종료마다** 돈다 — 퇴근을 Stop 에 걸면 매 턴 checkout 이 찍혀 상태 기계가 오염된다.
#   퇴근의 의미(세션 종료)와 일치하는 이벤트는 SessionEnd 다. 크래시로 SessionEnd 가
#   안 뜨는 경우는 lease 만료 → reap 강제 퇴근이 잡는다(계약 §상태 기계 — 그래서 lease 가 있다).
# ⚠️ 배열 주석에 닫는 괄호 금지 — hook-counts.py CHILDREN 파싱 규약.

set -u

HOOKS_DIR="$HOME/.claude/hooks"

input=$(cat)

CHILDREN=(
  "0|$HOOKS_DIR/fpm-hub-session-end.sh"   # hub live 카드 정리 — 기존 단독 배선을 dispatch 로 흡수
  "1|$HOOKS_DIR/fbot-checkout.sh"         # 핀봇 퇴근: kv 저장·작업 기록·state=checkout — Issue436_3
)

for spec in "${CHILDREN[@]}"; do
  script="${spec#*|}"
  [ -f "$script" ] || continue
  printf '%s' "$input" | bash "$script" >/dev/null 2>&1 &
done
wait

exit 0
