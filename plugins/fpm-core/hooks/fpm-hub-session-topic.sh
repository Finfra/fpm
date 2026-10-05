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
# F2-1: 파싱 단일 지점(jq 기반, hooks/hook-input.sh). 디스패처가 미리 파싱했으면 비용 0.
# shellcheck source=/dev/null
. "$HOME/.claude/hooks/hook-input.sh"
hook_input_parse "$input"
SID="$HOOK_SESSION_ID"
CWD="$HOOK_CWD"
PID_JSON="$HOOK_PID"

# prj3#Issue594 — 게이트가 비용보다 먼저다. 종전에는 SID 가 비어도 python3 로 라벨을 먼저 뽑았다
#   (매 프롬프트 ~25ms 고정 지출, UserPromptSubmit 예산 200ms 의 12%).
[ -z "$SID" ] && exit 0

# prj3#Issue594 — fast path: 프롬프트에 태그(`<`)가 없으면 python3 없이 bash 로 끝낸다.
#   실제 프롬프트 대다수가 평문이고, python3 기동(~25ms)이 이 hook 최대 비용이었다.
#   ⚠️ 결과는 python3 경로와 **같아야 한다** — 첫 비어있지 않은 줄 · 제어문자 제거 ·
#      공백 정규화 · 50자 절단(넘으면 `…`). 태그가 하나라도 있으면 그대로 python3 로 넘긴다
#      (WRAP 블록 제거는 다중행 DOTALL 이라 bash 로 옮기면 의미가 달라진다).
LABEL=""
case "$HOOK_PROMPT" in
  *"<"*) ;;                                  # 태그 있음 → 아래 python3 경로
  *)
    _line=""
    while IFS= read -r _ln || [ -n "$_ln" ]; do
      _t="${_ln#"${_ln%%[![:space:]]*}"}"; _t="${_t%"${_t##*[![:space:]]}"}"
      [ -n "$_t" ] && { _line="$_t"; break; }
    done <<< "$HOOK_PROMPT"
    # ⚠️ tr 은 바이트 단위다 — `[:space:]` 를 로케일 상태로 쓰면 한글 UTF-8 이 깨진다
    #    (실측: "안정성" → "안� �성"). LC_ALL=C + 명시 문자셋으로 고정한다.
    #    python3 경로는 제어문자를 **공백으로 치환**한 뒤 \s+ 를 압축한다 — `tr -d` 로 지우면
    #    "탭\t섞임" 이 "탭섞임" 이 되어 결과가 갈린다(실측). 한 번의 tr -s 로 치환+압축을 함께.
    _line=$(printf '%s' "$_line" | LC_ALL=C tr -s '\000-\037\177 ' ' ')
    _line="${_line#"${_line%%[![:space:]]*}"}"; _line="${_line%"${_line##*[![:space:]]}"}"
    if [ "${#_line}" -gt 50 ]; then
      _line="${_line:0:50}"
      _line="${_line%"${_line##*[![:space:]]}"}…"
    fi
    LABEL="$_line"
    ;;
esac
[ -n "$LABEL" ] || \
LABEL=$(HOOK_PROMPT="$HOOK_PROMPT" python3 -c "
import os, re
# F2-1: JSON 재파싱 대신 이미 뽑아둔 prompt 를 env 로 받는다(python3 기동 1회 절약)
p = os.environ.get('HOOK_PROMPT', '') or ''
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
[ -z "$LABEL" ] && exit 0   # 빈 프롬프트(첨부만 등) → 갱신 생략, 기존 label 보존

# prj3#Issue428: $PPID 직등록 금지 — 단명 wrapper pid 가 live_pid 를 덮어써 세션이
#   hub 카드에서 사라졌다(prj9a 실측). lib 단일 지점으로 생존 확인 + claude 승격.
# shellcheck source=lib/claude-pid.sh
# prj3#Issue545 — 번들(플러그인) 설치본은 ~/.claude/hooks/lib 가 없다. 자기 옆의 lib/ 로 폴백한다
FPM_LIB_DIR="$HOME/.claude/hooks/lib"
[ -d "$FPM_LIB_DIR" ] || FPM_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd)/lib"
. "$FPM_LIB_DIR/claude-pid.sh"
PID=$(fpm_resolve_claude_pid "$PID_JSON" "$PPID")
[ -z "$CWD" ] && exit 0   # Issue179: PWD fallback 제거 — hook 컨텍스트 PWD 는 frontmost 반영 위험(세션 오귀속), doc-register.sh:43 표준 정합
case "$CWD" in /*) ;; *) exit 0 ;; esac   # 절대경로만

SERVER_PORT="${HTM_SERVER_PORT:-9876}"
HEALTH_URL="http://127.0.0.1:${SERVER_PORT}/healthz"

health=$(curl -s -o /dev/null -w "%{http_code}" --max-time 2 "$HEALTH_URL" 2>/dev/null)
[ "$health" = "200" ] || exit 0

# prj3#Issue594 — urlencode 하나로 python3(~25ms)를 띄우던 것을 bash 로.
#   ⚠️ LC_ALL=C 필수 — 없으면 한글 경로에서 코드포인트를 바이트로 오인해 잘못된 %XX 를 만든다
#      (실측: /tmp/한글 → %D55C%AE00, 정답 %ED%95%9C%EA%B8%80). percent-encoding 은 바이트 단위다.
#   fpm-hub-session-model.sh 의 같은 블록과 **동일 로직**이다(quote() 5케이스 동치 검증분).
CWD_ENC=$(LC_ALL=C; _s="$CWD"; _o=""; _i=0
  while [ "$_i" -lt "${#_s}" ]; do
    _c="${_s:$_i:1}"
    case "$_c" in
      [A-Za-z0-9._~/-]) _o="$_o$_c" ;;
      *) _o="$_o$(printf '%%%02X' "'$_c")" ;;
    esac
    _i=$((_i+1))
  done
  printf '%s' "$_o")
REG_URL="http://127.0.0.1:${SERVER_PORT}/session/register?cwd=${CWD_ENC}"

# Issue179: 매 프롬프트 재등록도 출처 신호(entrypoint)를 함께 전송.
#   SessionStart(register.sh)가 보낸 entrypoint caps 를 이 훅의 caps 가 서버 merge
#   (caps or 기존)에서 매 턴 덮어써 origin 이 항상 terminal 로 회귀하던 버그(Issue177 회귀) 차단.
ENTRY="${CLAUDE_CODE_ENTRYPOINT:-}"

# Issue217(prj1#Issue273): 현재 세션 모델 — transcript jsonl 마지막 assistant .message.model.
#   hub 활성세션 카드 신호등 이모지(🟣opus/🔵sonnet/🟢haiku/🟠fable) producer.
#   SessionStart(register.sh)는 첫 응답 전이라 model 미상 → 매 프롬프트 이 훅이 갱신.
TRANSCRIPT="$HOOK_TRANSCRIPT"   # F2-1: 재파싱 제거 (hook-input.sh 가 이미 추출)
MODEL=""
if [ -n "$TRANSCRIPT" ] && [ -f "$TRANSCRIPT" ]; then
  MODEL=$(tail -n 400 "$TRANSCRIPT" 2>/dev/null | python3 -c "
import sys, json
last = ''
for line in sys.stdin:
    try:
        m = (json.loads(line).get('message') or {}).get('model')
        if m:
            last = m
    except Exception:
        pass
print(last)
" 2>/dev/null)
fi

# Issue313: Zed 신호 재전송 — 마커 조회(`[ -f ]` 1회)만 하므로 ps 재조회 없이 무비용.
#   SessionStart 1회 등록에만 실리던 caps.editor 가 이 훅의 재등록에서 지워지는 회귀 차단.
EDITOR_SIG=""
if [ "$ENTRY" != "claude-vscode" ]; then
  # shellcheck source=lib/zed-detect.sh
  . "$FPM_LIB_DIR/zed-detect.sh" 2>/dev/null || true
  if command -v zed_is_marked >/dev/null 2>&1 && zed_is_marked "$SID"; then
    EDITOR_SIG="zed"
  fi
fi

BODY=$(python3 -c "
import json, sys
sid, label, pid, entry, model, editor = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5], sys.argv[6]
caps = {'source': 'prompt', 'kind': 'live'}
if entry:
    caps['entrypoint'] = entry   # Issue179: 출처 배지용 (claude-vscode|cli|...)
if model:
    caps['model'] = model        # Issue217: 카드 모델 신호등 이모지 (prj1#Issue273)
if editor:
    caps['editor'] = editor      # Issue313: 서버 _origin_from_caps 가 origin=zed 로 소비
body = {'sid': sid, 'content_type': 'live', 'label': label, 'capabilities': caps}
try:
    body['pid'] = int(pid)   # Issue122: 서버 계약 pid(int) — live 카드 dedup·liveness
except (ValueError, TypeError):
    pass
print(json.dumps(body))
" "$SID" "$LABEL" "$PID" "$ENTRY" "$MODEL" "$EDITOR_SIG")

curl -s --max-time 2 \
  -X POST "$REG_URL" \
  -H "Content-Type: application/json" \
  -d "$BODY" \
  >/dev/null 2>&1 &

exit 0
