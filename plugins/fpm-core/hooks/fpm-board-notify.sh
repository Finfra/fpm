#!/bin/bash
# fpm-board-notify.sh — PostToolUse hook (matcher: Edit|Write|MultiEdit)
#
# ⚠️ 글로벌 SCAR 변경 가드 (Issue46): 본 hook 은 모든 프로젝트가 공유. cwd ≠ ~/.claude
#   면 즉시 수정 금지 → ~/.claude/Issue.md 이슈 등록 후 처리. 설계 SSOT:
#   ~/.claude/_doc_arch/dashboard.md. 절차: ~/.claude/rules/global-scar-change-rules.md
#
# Issue15: ___pm 단일 공유 htm-server 모델
# Claude가 dashboard data 파일(YAML/JSON)을 수정하면
# 단일 daemon에 /notify POST → SSE broadcast → 브라우저 dashboard 자동 갱신.
#
# 동작:
#   1. tool_input.file_path + cwd 추출
#   2. dashboard data 패턴 매칭 (*.htm.yaml, *.htm.json, _doc_work/z_htm/*.yaml|json, *.dash.yaml|json)
#   3. healthz 200 → /register?cwd=...로 token 회수 → /notify POST
#   4. 비매칭/서버 미실행 → silent exit 0

input=$(cat)

read -r FP CWD <<< "$(printf '%s' "$input" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    fp = d.get('tool_input', {}).get('file_path', '')
    cwd = d.get('cwd', '')
    print(fp, cwd)
except Exception:
    print('', '')
")"

case "$FP" in
  # Issue28 Phase 4: Mode C dashboard data 파일만 매칭. 세션 응답 본문은 /session/update 직접 호출 (별도 hook 불필요)
  *.htm.yaml|*.htm.yml|*.htm.json) ;;
  *.dash.yaml|*.dash.yml|*.dash.json) ;;
  */_doc_work/z_htm/*.yaml|*/_doc_work/z_htm/*.yml|*/_doc_work/z_htm/*.json) ;;
  *) exit 0 ;;
esac

[ -z "$CWD" ] && exit 0

SERVER_PORT="${HTM_SERVER_PORT:-9876}"
HEALTH_URL="http://127.0.0.1:${SERVER_PORT}/healthz"

health=$(curl -s -o /dev/null -w "%{http_code}" --max-time 2 "$HEALTH_URL" 2>/dev/null)
[ "$health" = "200" ] || exit 0

CWD_ENC=$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))" "$CWD")
REG_URL="http://127.0.0.1:${SERVER_PORT}/register?cwd=${CWD_ENC}"
TOKEN=$(curl -s --max-time 3 -X POST "$REG_URL" 2>/dev/null | python3 -c "
import json,sys
try: print(json.load(sys.stdin).get('token',''))
except: pass" 2>/dev/null)

[ -z "$TOKEN" ] && exit 0

NOTIFY_URL="http://127.0.0.1:${SERVER_PORT}/notify?cwd=${CWD_ENC}&token=${TOKEN}"
curl -s --max-time 2 \
  -X POST "$NOTIFY_URL" \
  -H "Content-Type: application/json" \
  -d "{\"file\":\"${FP}\",\"event\":\"data_changed\"}" \
  >/dev/null 2>&1

exit 0
