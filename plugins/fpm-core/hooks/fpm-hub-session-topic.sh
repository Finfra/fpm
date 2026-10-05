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
#   3. 포트 리슨 확인 (서버 미기동 → silent exit 0, UserPromptSubmit 비블로킹)
#   4. POST /session/register?cwd=<abs> body={sid, content_type:"live", pid, label, capabilities}
#   5. fire-and-forget (--max-time 2, 백그라운드) — healthz 200 확인도 여기서(Issue803)
#
# 서버측: live_label 우선 카드 렌더(server.py:1965)·register 마다 갱신(server.py:3920).
# fpm-hub-session-register.sh(SessionStart) 와 병행 — 첫 프롬프트 전까지만 win fallback.

# Issue714: bash 내장 읽기 — cat fork+exec(2.6ms) 제거. 청크 단위라 큰 프롬프트도 안전
input=$(< /dev/stdin)

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
[ -z "$CWD" ] && exit 0   # Issue179: PWD fallback 제거 — hook 컨텍스트 PWD 는 frontmost 반영 위험(세션 오귀속), doc-register.sh:43 표준 정합
case "$CWD" in /*) ;; *) exit 0 ;; esac   # 절대경로만

SERVER_PORT="${HTM_SERVER_PORT:-9876}"
HEALTH_URL="http://127.0.0.1:${SERVER_PORT}/healthz"

# Issue714 — 서버가 안 떠 있으면 아무것도 할 일이 없다. 종전에는 라벨(tr)·pid 체인(ps 최대 20회)을
#   다 계산한 **뒤에** healthz 를 봤다 — 서버 down 턴마다 ~45ms 를 버렸다(hook-smoke no-op 이 정확히
#   이 경로). 포트 리슨 여부는 bash 내장 /dev/tcp 로 exec 없이(서브셸 1회) 먼저 본다(hub-context.sh Issue340 과
#   같은 판정). 리슨 중이면 아래 healthz 200 확인은 그대로 한다 — 판정 결과는 종전과 같다.
{ : 3<>"/dev/tcp/127.0.0.1/$SERVER_PORT"; } 2>/dev/null || exit 0   # prj3#Issue921 — 서브셸 fork 없는 프로브

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
#   Issue714: 서버 리슨 확인(/dev/tcp) 뒤로 옮겼다 — pid 는 POST 본문에만 쓰인다.
#   여전히 **동기**로 센다(백그라운드로 미루면 hook 부모 체인이 먼저 죽어 Issue428 이 재발한다).
#   Issue803: 세션별 캐시 — 2번째 프롬프트부터 체인(ps 4~5회) 대신 캐시 pid 검증(ps 1회).
#     `$(…)` 가 아니라 현재 셸에서 불러 _FPM_PID 를 읽는다(캐시 적중 여부와 무관하게 결과 동등).
# shellcheck source=lib/claude-pid.sh
# prj3#Issue545 — 번들(플러그인) 설치본은 ~/.claude/hooks/lib 가 없다. 자기 옆의 lib/ 로 폴백한다
FPM_LIB_DIR="$HOME/.claude/hooks/lib"
[ -d "$FPM_LIB_DIR" ] || FPM_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd)/lib"
. "$FPM_LIB_DIR/claude-pid.sh"
fpm_claude_pid_cached_into "$SID" "$PID_JSON" "$PPID"
PID="$_FPM_PID"

# prj3#Issue594 — urlencode 하나로 python3(~25ms)를 띄우던 것을 bash 로.
#   ⚠️ LC_ALL=C 필수 — 없으면 한글 경로에서 코드포인트를 바이트로 오인해 잘못된 %XX 를 만든다
#      (실측: /tmp/한글 → %D55C%AE00, 정답 %ED%95%9C%EA%B8%80). percent-encoding 은 바이트 단위다.
#   fpm-hub-session-model.sh 의 같은 블록과 **동일 로직**이다(quote() 5케이스 동치 검증분).
CWD_ENC=$(LC_ALL=C; _s="$CWD"; _o=""; _i=0
  while [ "$_i" -lt "${#_s}" ]; do
    _c="${_s:$_i:1}"
    # Issue794: 패턴 앞 `(` 필수 — 3.2 는 `$(…)` 안 case 의 `)` 를 치환 끝으로 읽어 파싱 실패(hook 무동작)
    case "$_c" in
      ([A-Za-z0-9._~/-]) _o="$_o$_c" ;;
      # Issue794: 3.2 의 printf %d 는 0x80+ 바이트를 음수로 부호 확장한다(%FFFFFFFFFFFFFFED) — & 255 로 바이트값을 되찾는다
      (*) printf -v _n '%d' "'$_c"; printf -v _c '%%%02X' $((_n & 255)); _o="$_o$_c" ;;
    esac
    _i=$((_i+1))
  done
  printf '%s' "$_o")
REG_URL="http://127.0.0.1:${SERVER_PORT}/session/register?cwd=${CWD_ENC}"

# Issue179: 매 프롬프트 재등록도 출처 신호(entrypoint)를 함께 전송.
#   SessionStart(register.sh)가 보낸 entrypoint caps 를 이 훅의 caps 가 서버 merge
#   (caps or 기존)에서 매 턴 덮어써 origin 이 항상 terminal 로 회귀하던 버그(Issue177 회귀) 차단.
ENTRY="${CLAUDE_CODE_ENTRYPOINT:-}"

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

# Issue217(prj1#Issue273): 현재 세션 모델 — transcript jsonl 마지막 assistant .message.model.
#   hub 활성세션 카드 신호등 이모지(🟣opus/🔵sonnet/🟢haiku/🟠fable) producer.
#   SessionStart(register.sh)는 첫 응답 전이라 model 미상 → 매 프롬프트 이 훅이 갱신.
# Issue803: model 추출과 BODY 조립을 **jq 1회**로 — 종전 python3 2회(~20ms × 2)가 발동 경로 최대 비용.
#   판정은 종전 python 과 같다: 줄마다 JSON 객체 → .message 가 객체 → .model 이 비지 않은 문자열이면
#   갱신(마지막 값). 깨진 줄·비객체는 건너뛴다. pid 는 정수일 때만 싣는다(Issue122 서버 계약 int).
#   ⚠️ 차이는 표현뿐 — jq 는 비ASCII 를 UTF-8 그대로 싣고 python json.dumps 는 \uXXXX 로 싣는다.
#      서버는 JSON 으로 파싱하므로 받는 값은 같다(test-session-topic-fire.sh A 가 파싱 후 대조).
#   jq 부재(번들 설치본 등)면 python3 1회로 같은 일을 한다.
TRANSCRIPT="$HOOK_TRANSCRIPT"   # F2-1: 재파싱 제거 (hook-input.sh 가 이미 추출)
[ -n "$TRANSCRIPT" ] && [ -f "$TRANSCRIPT" ] || TRANSCRIPT=/dev/null
BODY=""
if command -v jq >/dev/null 2>&1; then
  BODY=$(tail -n 400 "$TRANSCRIPT" 2>/dev/null | jq -cRn \
    --arg sid "$SID" --arg label "$LABEL" --arg pid "$PID" \
    --arg entry "$ENTRY" --arg editor "$EDITOR_SIG" '
    (reduce (inputs | (try fromjson catch null) | objects | .message | objects | .model
             | select(type == "string" and . != "")) as $m (""; $m)) as $model
    | {sid: $sid, content_type: "live", label: $label,
       capabilities: ({source: "prompt", kind: "live"}
         + (if $entry  != "" then {entrypoint: $entry} else {} end)    # Issue179: 출처 배지용
         + (if $model  != "" then {model: $model}      else {} end)    # Issue217: 모델 신호등
         + (if $editor != "" then {editor: $editor}    else {} end))}  # Issue313: origin=zed
      + (if ($pid | test("^[0-9]+$")) then {pid: ($pid | tonumber)} else {} end)
  ' 2>/dev/null)
fi
[ -n "$BODY" ] || BODY=$(tail -n 400 "$TRANSCRIPT" 2>/dev/null | python3 -c "
import json, sys
sid, label, pid, entry, editor = sys.argv[1:6]
model = ''
for line in sys.stdin.buffer:   # bytes — 깨진 UTF-8 줄도 try 안에서 건너뛴다
    try:
        m = (json.loads(line).get('message') or {}).get('model')
        if m:
            model = m
    except Exception:
        pass
caps = {'source': 'prompt', 'kind': 'live'}
if entry:
    caps['entrypoint'] = entry
if model:
    caps['model'] = model
if editor:
    caps['editor'] = editor
body = {'sid': sid, 'content_type': 'live', 'label': label, 'capabilities': caps}
try:
    body['pid'] = int(pid)
except (ValueError, TypeError):
    pass
print(json.dumps(body))
" "$SID" "$LABEL" "$PID" "$ENTRY" "$EDITOR_SIG" 2>/dev/null)
[ -n "$BODY" ] || exit 0

# Issue803: healthz 200 확인까지 POST 와 함께 백그라운드로 — 종전엔 healthz 를 동기로 기다렸다
#   (--max-time 2, 서버가 느리면 프롬프트가 그만큼 멈춘다). 판정은 같다: 200 일 때만 POST.
#   리슨 여부는 위 /dev/tcp 가 이미 동기로 걸렀다. pid·본문은 위에서 동기로 확정했다(Issue428).
( health=$(curl -s -o /dev/null -w "%{http_code}" --max-time 2 "$HEALTH_URL" 2>/dev/null)
  [ "$health" = "200" ] || exit 0
  curl -s --max-time 2 \
    -X POST "$REG_URL" \
    -H "Content-Type: application/json" \
    -d "$BODY"
) >/dev/null 2>&1 &

exit 0
