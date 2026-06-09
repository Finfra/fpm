#!/bin/bash
# fpm-hub-session-topic.sh — UserPromptSubmit hook: 세션 카드 제목을 현재 작업(프롬프트)으로 갱신
#
# ⚠️ 글로벌 SCAR 변경 가드 (Issue46): 본 hook 은 모든 프로젝트가 공유. cwd ≠ ~/.claude
#   면 즉시 수정 금지 → ~/.claude/Issue.md 이슈 등록 후 처리. 설계 SSOT:
#   ~/_git/___pm/_doc_arch/hub_htm.md. 절차: ~/.claude/rules/global-scar-change-rules.md
#
# Issue127: hub(http://127.0.0.1:9876/hub) 활성 세션 카드가 일반 claude 세션을 모두
# "claude · win {N}" fallback 으로 동일 표시함 — register body 에 label(제목) 데이터
# 부재 + window_index 무의미가 근본 원인. 매 프롬프트 입력 시 그 프롬프트 요약을 카드
# 제목(live_label)으로 register 하여 세션별 실제 작업을 구분 표시.
#
# 동작:
#   1. stdin JSON 에서 session_id + cwd + prompt + pid 추출
#   2. prompt 첫 줄 ~50자 요약(제어문자 제거, 슬래시 커맨드 보존, truncate +…)
#   3. healthz 200 확인 (서버 미기동 → silent exit 0, UserPromptSubmit 비블로킹)
#   4. POST /session/register?cwd=<abs> body={sid, content_type:"live", pid, label, capabilities}
#   5. fire-and-forget (--max-time 2, 백그라운드) — 프롬프트 처리 지연 방지
#
# 서버측: live_label 우선 카드 렌더(server.py:1965)·register 마다 갱신(server.py:3920).
# fpm-hub-session-register.sh(SessionStart) 와 병행 — 첫 프롬프트 전까지만 win fallback.

input=$(cat)

# stdin JSON 에서 session_id·cwd·prompt·pid 추출 + prompt 요약(label) 동시 산출.
# 요약: 첫 비어있지 않은 줄 → 제어문자 제거 → 50자 truncate(+…). 슬래시 커맨드는 첫 줄에
#   그대로 보존됨(별도 처리 불필요).
read -r SID CWD PID_JSON <<< "$(printf '%s' "$input" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('session_id', ''), d.get('cwd', ''), d.get('pid', ''))
except Exception:
    print('', '', '')
")"

LABEL=$(printf '%s' "$input" | python3 -c "
import sys, json, re
try:
    d = json.load(sys.stdin)
    p = d.get('prompt', '') or ''
except Exception:
    p = ''
# Issue127 후속: UserPromptSubmit prompt 는 사용자 raw 입력 앞에 IDE/시스템 래퍼를
#   prepend 함(<ide_opened_file>·<ide_selection>·<task-notification>·<system-reminder> 등).
#   전처리 없으면 '첫 줄'이 래퍼 태그를 잡아 label 이 오염됨 → 블록 제거 후 첫 실제 줄 추출.
WRAP = ['ide_opened_file','ide_selection','task-notification','system-reminder',
        'command-message','command-name','command-args','command-contents',
        'local-command-stdout','local-command-stderr','user-prompt-submit-hook']
for tag in WRAP:
    p = re.sub(r'<%s\b[^>]*>.*?</%s>' % (tag, tag), ' ', p, flags=re.DOTALL | re.IGNORECASE)
# 잔여 단독/열린/닫힌 태그(한 줄짜리) 제거 — 카드 제목에 < > 노출 방지
p = re.sub(r'</?[a-zA-Z][\w-]*(?:\s[^>]*)?/?>', ' ', p)
# 첫 비어있지 않은 줄 (래퍼 제거 후 = 실제 사용자 작업)
line = ''
for ln in p.splitlines():
    if ln.strip():
        line = ln.strip()
        break
# 제어문자(탭·개행 등) → 공백, 연속 공백 압축
line = re.sub(r'[\x00-\x1f\x7f]+', ' ', line)
line = re.sub(r'\s+', ' ', line).strip()
# 50자 truncate
if len(line) > 50:
    line = line[:50].rstrip() + '…'
print(line)
")

[ -z "$SID" ] && exit 0
[ -z "$LABEL" ] && exit 0   # 빈 프롬프트(첨부만 등) → 갱신 생략, 기존 label 보존

# pid: JSON 값이 있고 정수면 사용, 아니면 훅 부모 pid(=claude 세션) fallback
PID="$PID_JSON"
case "$PID" in ''|*[!0-9]*) PID="$PPID" ;; esac
[ -z "$CWD" ] && CWD="$PWD"
case "$CWD" in /*) ;; *) exit 0 ;; esac   # 절대경로만

SERVER_PORT="${HTM_SERVER_PORT:-9876}"
HEALTH_URL="http://127.0.0.1:${SERVER_PORT}/healthz"

health=$(curl -s -o /dev/null -w "%{http_code}" --max-time 2 "$HEALTH_URL" 2>/dev/null)
[ "$health" = "200" ] || exit 0

CWD_ENC=$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))" "$CWD")
REG_URL="http://127.0.0.1:${SERVER_PORT}/session/register?cwd=${CWD_ENC}"

BODY=$(python3 -c "
import json, sys
sid, label, pid = sys.argv[1], sys.argv[2], sys.argv[3]
caps = {'source': 'prompt', 'kind': 'live'}
body = {'sid': sid, 'content_type': 'live', 'label': label, 'capabilities': caps}
try:
    body['pid'] = int(pid)   # Issue122: 서버 계약 pid(int) — live 카드 dedup·liveness
except (ValueError, TypeError):
    pass
print(json.dumps(body))
" "$SID" "$LABEL" "$PID")

curl -s --max-time 2 \
  -X POST "$REG_URL" \
  -H "Content-Type: application/json" \
  -d "$BODY" \
  >/dev/null 2>&1 &

exit 0
