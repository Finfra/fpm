#!/bin/bash
# fpm-hub-session-register.sh — SessionStart hook: claude 세션을 hub live 카드로 등록
#
# ⚠️ 글로벌 SCAR 변경 가드 (Issue46): 본 hook 은 모든 프로젝트가 공유. cwd ≠ ~/.claude
#   면 즉시 수정 금지 → ~/.claude/Issue.md 이슈 등록 후 처리. 설계 SSOT:
#   ~/_git/___pm/_doc_arch/hub_htm.md. 절차: ~/.claude/rules/global-scar-change-rules.md
#
# Issue121: hub 📡 활성 세션 카드는 Mode C dashboard 세션만 노출했음. 일반 claude
# 세션(예: tmux pm window 1)을 per-window live 카드로 노출하려면 SessionStart 시점에
# sid + cwd 를 ___pm hub /session/register (content_type=live) 로 등록해야 함.
# hook-feed 는 cwd 단위(sid 없음)라 동일 cwd 다중 window 구분 불가 → sid 등록 필요.
#
# 동작:
#   1. stdin JSON 에서 session_id + cwd + source 추출
#   2. healthz 200 확인 (서버 미기동 → silent exit 0, SessionStart 비블로킹)
#   3. POST /session/register?cwd=<abs> body={sid, content_type:"live", capabilities:{...}}
#   4. fire-and-forget (--max-time 2, 백그라운드) — Claude Code 시작 지연 방지
#
# 서버측 content_type=live liveness 게이트·카드 렌더는 prj1 ___pm#Issue98 소관.
# 본 훅의 POST 는 서버가 live 를 아직 무시해도 무해 (sid entry 등록만 수행).

input=$(cat)

# Issue122: pid 추출 — stdin JSON 의 pid 필드(존재 시) 우선, 없으면 $PPID(훅 부모=claude).
# pid 는 서버(Issue99) live 카드 dedup·liveness(사망 즉시 prune) 권위 신호 — content_type=live 필수.
read -r SID CWD SRC PID_JSON <<< "$(printf '%s' "$input" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('session_id', ''), d.get('cwd', ''), d.get('source', ''), d.get('pid', ''))
except Exception:
    print('', '', '', '')
")"

[ -z "$SID" ] && exit 0

# prj1#Issue341→prj3#Issue428: pid 산출(생존 확인 + 부모 체인 claude 승격)은
#   lib/claude-pid.sh 단일 지점. topic.sh·model.sh 재등록 경로와 판정 공유.
# shellcheck source=lib/claude-pid.sh
. "$HOME/.claude/hooks/lib/claude-pid.sh"
PID=$(fpm_resolve_claude_pid "$PID_JSON" "$PPID")

[ -z "$CWD" ] && exit 0   # Issue179: PWD fallback 제거 — hook 컨텍스트 PWD 는 frontmost 반영 위험(세션 오귀속), doc-register.sh:43 표준 정합
case "$CWD" in /*) ;; *) exit 0 ;; esac   # 절대경로만

SERVER_PORT="${HTM_SERVER_PORT:-9876}"
HEALTH_URL="http://127.0.0.1:${SERVER_PORT}/healthz"

health=$(curl -s -o /dev/null -w "%{http_code}" --max-time 2 "$HEALTH_URL" 2>/dev/null)
[ "$health" = "200" ] || exit 0

# tmux window index (가능 시) — 동일 cwd 다중 window 구분용 (Issue122 T3)
# $TMUX 가 훅 env 로 전파되면 정확. 미전파여도 단일 client 면 display-message 가 fallback 으로 동작.
TMUX_WIN=$(tmux display-message -p '#{window_index}' 2>/dev/null)

CWD_ENC=$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))" "$CWD")
REG_URL="http://127.0.0.1:${SERVER_PORT}/session/register?cwd=${CWD_ENC}"

# Issue177: 세션 출처 신호 — Claude Code 가 세팅하는 CLAUDE_CODE_ENTRYPOINT
#   (VSCode 확장=claude-vscode, 터미널 CLI=cli). 훅 subprocess env 로 전파됨.
#   서버가 capabilities.entrypoint 로 hub 카드 출처 배지(🆚/⌨️)를 분기.
ENTRY="${CLAUDE_CODE_ENTRYPOINT:-}"

# Issue289(P3g): Zed 출처 판정 — Zed 는 ACP 브리지로 붙어 entrypoint 가 `sdk-ts` 로만 보이고
#   ~/.claude/ide/*.lock 도 남기지 않는다. 결정적 신호는 부모 프로세스 체인뿐이므로
#   **세션 등록 시 1회만** ps 로 조사하고, 결과를 caps.editor + 마커 파일에 캐시한다.
#   서버(prj1#Issue327 e5f82bd)가 capabilities.editor=="zed" 를 origin=zed 로 소비해
#   배지·클릭·포커스 게이트를 3값 분기한다. 매 렌더의 재조회는 fpm-hub-trigger 가 마커로 회피.
EDITOR_SIG=""
if [ "$ENTRY" != "claude-vscode" ]; then
  # shellcheck source=lib/zed-detect.sh
  . "$HOME/.claude/hooks/lib/zed-detect.sh" 2>/dev/null || true
  if command -v zed_detect_by_proc >/dev/null 2>&1 && zed_detect_by_proc "$PID"; then
    EDITOR_SIG="zed"
    zed_mark "$SID"
  elif command -v zed_is_marked >/dev/null 2>&1 && zed_is_marked "$SID"; then
    # Issue313: ps 조상 체인 판정 실패 폴백 — resume·재등록으로 체인이 끊긴 경우
    #   이전에 기록해 둔 마커로 복구한다(파일 존재 확인 1회, 무비용).
    EDITOR_SIG="zed"
  fi
fi

# Issue342(S3): 기동자 신호 — 세션을 띄운 주체가 심는 env FPM_SESSION_ORIGIN.
#   ⚠️ CLAUDE_CODE_ENTRYPOINT(위 ENTRY)와 축이 다르다 — 저쪽은 "어느 에디터",
#   이쪽은 "누가 띄웠나"(pm-do 위임·board runner·사람). 서버는 caps.launched_by 로 받는다.
#   미설정이면 아예 안 보낸다. manual 로 단정하지 않는 이유는 배선 누락과 수동 기동이
#   구분되지 않게 되기 때문이다(서버도 미상을 빈 문자열로 남긴다).
case "${FPM_SESSION_ORIGIN:-}" in
  pm-do|board|manual|ide) LAUNCHED_BY="$FPM_SESSION_ORIGIN" ;;
  *)                      LAUNCHED_BY="" ;;
esac

# Issue221(보너스): resume 세션 model 선탐색 — SessionStart(source=resume/compact) 시점엔
#   transcript 에 이미 assistant .message.model 존재 → dot 을 첫 응답 前 즉시 표시.
#   신규(source=startup) 세션은 transcript 비어 MODEL='' → 무해(기존 동작 유지, Stop 훅이 채움).
TRANSCRIPT=$(printf '%s' "$input" | python3 -c "
import sys, json
try:
    print(json.load(sys.stdin).get('transcript_path', '') or '')
except Exception:
    print('')
")
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

BODY=$(python3 -c "
import json, sys
sid, src, win, pid, entry, model, editor, launched_by = sys.argv[1:9]
caps = {'tmux_window': win, 'source': src, 'kind': 'live'}
if entry:
    caps['entrypoint'] = entry   # Issue177: 출처 배지용 (claude-vscode|cli|...)
if model:
    caps['model'] = model        # Issue221: resume 세션 모델 신호등 즉시 표시
if editor:
    caps['editor'] = editor      # Issue289: 서버 _origin_from_caps 가 origin=zed 로 소비
if launched_by:
    caps['launched_by'] = launched_by   # Issue342 S3: 기동자(pm-do|board|manual|ide)
body = {'sid': sid, 'content_type': 'live', 'capabilities': caps}
try:
    body['pid'] = int(pid)   # Issue122: 서버 계약 pid(int) 필수
except (ValueError, TypeError):
    pass
print(json.dumps(body))
" "$SID" "$SRC" "$TMUX_WIN" "$PID" "$ENTRY" "$MODEL" "$EDITOR_SIG" "$LAUNCHED_BY")

curl -s --max-time 2 \
  -X POST "$REG_URL" \
  -H "Content-Type: application/json" \
  -d "$BODY" \
  >/dev/null 2>&1 &

exit 0
