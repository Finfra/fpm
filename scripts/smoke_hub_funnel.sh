#!/usr/bin/env bash
# smoke_hub_funnel.sh — hub-internal 렌더 funnel 스모크 (Issue211 Phase 5 B-2)
#
# ⚠️ 글로벌 SCAR 아님 (___pm 프로젝트 소유). 비-hermetic: 실행 중인 hub 서버
#   (render_tab_mode=hub-internal)에 curl 로 HTTP 동작을 검증한다. release-check 에
#   편입하지 않음(라이브 서버·설정 의존). 수동 B-2 의 funnel 부분을 반자동화.
#
# 검증(Issue213/194/201/202/209 계열 — hub-internal standalone /hub 단일 쉘 funnel):
#   1. 루트 / (top-level)        → 302 /hub-shell
#   2. standalone /hub (document) → 302 /hub-shell  (Issue213 핵심)
#   3. /hub?_shell=1 (iframe)     → 200 raw (중첩 쉘·redirect loop 없음)
#   4. /hub-shell                 → 200
#
# 사용: bash scripts/smoke_hub_funnel.sh [BASE_URL]   (기본 http://127.0.0.1:9876)
# exit: 0=PASS, 1=FAIL, 2=서버 미기동(스킵)
set -uo pipefail
B="${1:-http://127.0.0.1:9876}"

curl -s -o /dev/null --max-time 3 "$B/healthz" || { echo "⏭️  hub 서버 미기동($B) — 스모크 스킵"; exit 2; }

PASS=0; FAIL=0
code() { curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$@"; }
loc()  { curl -s -o /dev/null -w '%{redirect_url}' --max-time 5 "$@"; }
chk()  { if [ "$2" = "$3" ]; then printf '  PASS %s (%s)\n' "$1" "$2"; PASS=$((PASS+1)); else printf '  FAIL %s (기대 %s, 실제 %s)\n' "$1" "$3" "$2"; FAIL=$((FAIL+1)); fi }

echo "═══ hub-internal funnel 스모크 ($B) ═══"
chk "루트 / → 302"               "$(code -H 'Sec-Fetch-Dest: document' "$B/")"          302
chk "루트 / → /hub-shell"        "$(loc  -H 'Sec-Fetch-Dest: document' "$B/")"          "$B/hub-shell"
chk "standalone /hub → 302"      "$(code -H 'Sec-Fetch-Dest: document' "$B/hub")"       302
chk "standalone /hub → /hub-shell" "$(loc -H 'Sec-Fetch-Dest: document' "$B/hub")"      "$B/hub-shell"
chk "/hub?_shell=1 iframe → 200" "$(code -H 'Sec-Fetch-Dest: iframe' "$B/hub?_shell=1")" 200
chk "/hub-shell → 200"           "$(code "$B/hub-shell")"                               200

echo "──────────────────────────────────────"
printf 'PASS=%d FAIL=%d\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
