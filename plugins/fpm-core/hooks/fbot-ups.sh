#!/usr/bin/env bash
# fbot-ups.sh — UserPromptSubmit 의 fbot 3종을 **한 프로세스**에 모은다 (prj3#Issue594)
#
# 왜 합치는가 (실측 근거):
#   fbot-heartbeat 27ms · fbot-name-nudge 35ms · fbot-inbox-nudge 28ms — 각 비용의 대부분이
#   **bash 기동 + 스크립트 파싱**이지 로직이 아니다. dispatcher 는 자식마다 `bash <script>` 를
#   새로 띄우므로 fork 3회가 곧 3중 지출이다. 한 프로세스에서 subshell source 로 돌리면
#   fork 3 → 1, 파싱 3 → 1 이 된다(subshell 은 ~1ms, bash 기동은 ~8ms).
#
# 왜 안전한가 (게이트가 상호 배타):
#   heartbeat  — FBOT_ID 있거나 `sid-<SID>.id` 마커 있을 때만 (봇 세션)
#   name-nudge — 마커 있으면 즉시 exit · FBOT_ID 있으면 exit (비봇 세션 전용)
#   inbox-nudge— 마커 있어야 진행 (봇 세션)
#   → 한 세션에서 실제로 일하는 것은 최대 2개다. 순서 의존도 없다(각자 독립 판정).
#
# ⚠️ `( . script )` 로 **subshell source** 한다 — 자식들이 `exit 0` 로 끝내는데
#    그대로 source 하면 이 래퍼까지 죽는다. subshell 이면 그 안에서만 끝난다.
# ⚠️ stdin 은 자식마다 새로 먹인다. 단 dispatcher 경유 시 HOOK_INPUT_PARSED=1 이라
#    재파싱은 일어나지 않는다(비용 0).
# @wraps: fbot-heartbeat.sh fbot-name-nudge.sh fbot-inbox-nudge.sh fbot-chief-nudge.sh
#   ↑ hook-counts.py 가 읽는 **명시 선언**이다. 이 줄이 없으면 감싸인 자식들이 orphan 으로
#     오판된다(배선은 래퍼 하나뿐이므로 CHILDREN 파싱만으로는 안 보인다).

set -uo pipefail

_H="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd)"
[ -n "$_H" ] || exit 0

input="$(cat)"

for _s in fbot-heartbeat fbot-name-nudge fbot-inbox-nudge fbot-chief-nudge; do
  [ -f "$_H/$_s.sh" ] || continue          # 배관 미완 = 조용히 건너뜀 (fail-soft)
  printf '%s' "$input" | ( . "$_H/$_s.sh" ) || true   # 한 자식의 실패가 나머지를 막지 않는다
done
exit 0
