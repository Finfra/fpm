#!/bin/bash
# hub-doc-register.sh — PostToolUse hook (matcher: Write)
#
# ⚠️ 글로벌 SCAR 변경 가드 (Issue46): 본 hook 은 모든 프로젝트가 공유. cwd ≠ ~/.claude
#   면 즉시 수정 금지 → ~/.claude/Issue.md 이슈 등록 후 처리. 설계 SSOT:
#   ~/.claude/_doc_arch/hub-mode-arch.md. 절차: ~/.claude/rules/global-scar-change-rules.md
#
# Issue73: hub 본문 HTML 산출물을 ___pm htm-server hub registry 에 자동 등록.
# hub 커맨드 step 7(수동 POST /register-doc) 누락 시 hub 미노출 사각지대 보강.
# Issue80: B모드 ask 폼(mode b)도 등록 대상에 포함 (Mode D auto=mode c 만 제외).
# 파일명 규약: hub_htm_<YYYYMMDD_HHMMSS>_<mode>_<주제>.htm (mode a=렌더, b=ask, c=auto)
#
# 동작:
#   1. tool_input.file_path + cwd 추출
#   2. */_doc_work/z_htm/hub_htm_*_*.hub 매칭 (Mode D auto = _c_ 만 제외, a/b 포함)
#   3. healthz 200 → <title> 추출 → POST /register-doc
#   4. 비매칭/서버 미실행/curl 실패 → silent exit 0 (fail-soft, hub 본 기능 차단 금지)

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

# Issue73/Issue80: 본문(mode a) + B모드 ask(mode b) 폼 등록. Mode D auto(mode c) 만 transient 로 제외.
case "$FP" in
  */_doc_work/z_htm/hub_htm_*_c_*.htm) exit 0 ;;
  */_doc_work/z_htm/hub_htm_*_*.htm)   ;;
  *) exit 0 ;;
esac

[ -z "$CWD" ] && exit 0

# file_path 가 상대경로면 cwd 기준으로 절대화
case "$FP" in
  /*) FP_ABS="$FP" ;;
  *)  FP_ABS="${CWD%/}/$FP" ;;
esac
[ -f "$FP_ABS" ] || exit 0

SERVER_PORT="${HTM_SERVER_PORT:-9876}"
HEALTH_URL="http://127.0.0.1:${SERVER_PORT}/healthz"

health=$(curl -s -o /dev/null -w "%{http_code}" --max-time 2 "$HEALTH_URL" 2>/dev/null)
[ "$health" = "200" ] || exit 0

# <title> 추출 (실패 시 파일명 fallback)
BODY=$(FP_ABS="$FP_ABS" CWD="$CWD" python3 -c "
import os, re, json
fp = os.environ['FP_ABS']
cwd = os.environ['CWD']
title = ''
try:
    with open(fp, encoding='utf-8', errors='ignore') as f:
        m = re.search(r'<title[^>]*>(.*?)</title>', f.read(), re.S | re.I)
        if m:
            title = re.sub(r'\s+', ' ', m.group(1)).strip()[:200]
except Exception:
    pass
if not title:
    title = os.path.basename(fp)
print(json.dumps({'type': 'htm', 'path': fp, 'cwd': cwd, 'title': title}))
" 2>/dev/null)

[ -z "$BODY" ] && exit 0

curl -s --max-time 3 -X POST "http://127.0.0.1:${SERVER_PORT}/register-doc" \
  -H 'Content-Type: application/json' \
  -d "$BODY" >/dev/null 2>&1

exit 0
