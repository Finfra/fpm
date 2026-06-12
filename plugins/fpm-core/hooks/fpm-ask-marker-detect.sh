#!/bin/bash
# fpm-ask-marker-detect.sh — Stop hook (Issue43, 2026-05-19)
#
# ⚠️ 글로벌 SCAR 변경 가드 (Issue46): 본 hook 은 모든 프로젝트가 공유. cwd ≠ ~/.claude
#   면 즉시 수정 금지 → ~/.claude/Issue.md 이슈 등록 후 처리. 설계 SSOT:
#   ~/.claude/_doc_arch/hub-mode-arch.md (Mode D). 절차:
#   ~/.claude/rules/global-scar-change-rules.md
#
# 동작:
#   - .hub-mode-active 플래그 없음 → exit 0
#   - 플래그 있음 + 직전 assistant 응답에 v1 sentinel 쌍 BEGIN/END 마커 발견
#     → 마커 JSON 파싱·검증 → server healthz/register → form HTML 생성 지시를
#       Stop hook `decision: "block"` reason 으로 주입하여 다음 turn 에서 Claude
#       가 form HTML 작성·Firefox open·inbox polling 수행
#   - 마커 미발견 → exit 0 (평시 무동작)
#
# 마커 schema (Issue48 v1 sentinel 강화 — code fence 노출 false-positive 회피):
#   <!-- htm-form:auto:v1:BEGIN
#   { "title": "...", "questions": [
#       {"question": "Q1", "header": "h1", "type": "freetext", "placeholder": "..."},
#       {"question": "Q2", "type": "select", "multiSelect": false,
#        "options": [{"label": "A", "description": "..."}, ...]}
#   ] }
#   htm-form:auto:v1:END -->
#
# 본 hook 은 hooks/fpm-ask-intercept.sh (PreToolUse AskUserQuestion) 와 동일 인프라
# 재사용 (server inbox + bash polling, cwd_hash 격리, OUT_DIR 규칙).
#
# 이력:
#   - Issue43 (2026-05-19): 초기 도입. 단일 라인 sentinel `htm-form:auto`
#   - Issue48 (2026-05-19): code fence 노출 false-positive 회귀 fix.
#     BEGIN/END 쌍 sentinel 로 강화. 구 sentinel 매칭 제거 (backward compat 없음)

set -u

FLAG_MODE="$HOME/.claude/.hub-mode-active"
if [ ! -f "$FLAG_MODE" ]; then
  exit 0
fi

input=$(cat)

# Stop hook 입력 schema: transcript_path / session_id / cwd
transcript_path=$(printf '%s' "$input" | python3 -c "
import sys, json
try:
    print(json.load(sys.stdin).get('transcript_path',''))
except Exception:
    pass" 2>/dev/null)

cwd=$(printf '%s' "$input" | python3 -c "
import sys, json
try:
    print(json.load(sys.stdin).get('cwd',''))
except Exception:
    pass" 2>/dev/null)

session_id=$(printf '%s' "$input" | python3 -c "
import sys, json
try:
    print(json.load(sys.stdin).get('session_id',''))
except Exception:
    pass" 2>/dev/null)

# 무한 루프 방지: stop_hook_active true 면 즉시 exit
stop_hook_active=$(printf '%s' "$input" | python3 -c "
import sys, json
try:
    print(json.load(sys.stdin).get('stop_hook_active', False))
except Exception:
    pass" 2>/dev/null)
if [ "$stop_hook_active" = "True" ] || [ "$stop_hook_active" = "true" ]; then
  exit 0
fi

if [ -z "$transcript_path" ] || [ ! -f "$transcript_path" ]; then
  exit 0
fi

# transcript 에서 마지막 assistant 메시지의 text content 추출
marker_block=$(TRANSCRIPT_PATH="$transcript_path" python3 <<'PYEOF' 2>/dev/null
import json, os, re, sys

path = os.environ.get('TRANSCRIPT_PATH', '')
if not path or not os.path.exists(path):
    sys.exit(0)

# transcript_path 는 JSONL. 각 라인이 message event.
# 마지막 assistant text 부분만 모음.
last_assistant_text = []
try:
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except Exception:
                continue
            # Claude Code transcript JSONL 형식 (관찰): {"type":"assistant","message":{"content":[{"type":"text","text":"..."}, ...]}}
            if ev.get('type') == 'assistant':
                msg = ev.get('message', {})
                content = msg.get('content', [])
                if isinstance(content, list):
                    txt = []
                    for c in content:
                        if isinstance(c, dict) and c.get('type') == 'text':
                            txt.append(c.get('text', ''))
                    if txt:
                        last_assistant_text = txt
            elif ev.get('type') == 'user':
                # user turn 시작 시 직전 assistant 응답 리셋 (이번 stop event 는
                # 가장 최근 assistant turn 만 검사)
                pass
except Exception:
    sys.exit(0)

if not last_assistant_text:
    sys.exit(0)

joined = '\n'.join(last_assistant_text)

# 마커 패턴 (Issue48 v1 sentinel 쌍): <!-- htm-form:auto:v1:BEGIN\n...\nhtm-form:auto:v1:END -->
# code fence 내부 예시 노출 회피를 위해 BEGIN/END 쌍 필수 (non-greedy DOTALL)
m = re.search(
    r'<!--\s*htm-form:auto:v1:BEGIN\s*\n(.*?)\n\s*htm-form:auto:v1:END\s*-->',
    joined,
    re.DOTALL,
)
if not m:
    sys.exit(0)

print(m.group(1).strip())
PYEOF
)

if [ -z "$marker_block" ]; then
  exit 0
fi

# 마커 JSON 파싱 + schema 검증
marker_validated=$(MARKER_JSON="$marker_block" python3 <<'PYEOF' 2>/dev/null
import json, os, sys

raw = os.environ.get('MARKER_JSON', '')
try:
    obj = json.loads(raw)
except Exception as e:
    print(json.dumps({"error": f"JSON parse fail: {e}"}, ensure_ascii=False))
    sys.exit(0)

if not isinstance(obj, dict):
    print(json.dumps({"error": "marker root must be object"}, ensure_ascii=False))
    sys.exit(0)

qs = obj.get('questions')
if not isinstance(qs, list) or len(qs) == 0:
    print(json.dumps({"error": "questions[] required and non-empty"}, ensure_ascii=False))
    sys.exit(0)

for i, q in enumerate(qs):
    if not isinstance(q, dict):
        print(json.dumps({"error": f"questions[{i}] must be object"}, ensure_ascii=False))
        sys.exit(0)
    if not q.get('question'):
        print(json.dumps({"error": f"questions[{i}].question required"}, ensure_ascii=False))
        sys.exit(0)
    qtype = q.get('type', 'select')
    if qtype not in ('freetext', 'select'):
        print(json.dumps({"error": f"questions[{i}].type must be 'freetext' or 'select'"}, ensure_ascii=False))
        sys.exit(0)
    if qtype == 'select':
        opts = q.get('options')
        if not isinstance(opts, list) or len(opts) < 1:
            print(json.dumps({"error": f"questions[{i}].options required for select type"}, ensure_ascii=False))
            sys.exit(0)

print(json.dumps({"ok": True, "data": obj}, ensure_ascii=False))
PYEOF
)

validation_error=$(printf '%s' "$marker_validated" | python3 -c "
import sys, json
try:
    print(json.load(sys.stdin).get('error',''))
except Exception:
    pass" 2>/dev/null)

if [ -n "$validation_error" ]; then
  VALIDATION_ERR="$validation_error" python3 <<'PYEOF'
import json, os
err = os.environ.get('VALIDATION_ERR', '')
reason = (
    "## htm-form:auto 마커 schema 위반 (Issue43)\n\n"
    f"에러: {err}\n\n"
    "마커 JSON 을 schema 에 맞게 수정 후 응답 재작성. schema 명세: commands/fpm-hub.md 'Mode D 자동 폼 마커' 섹션."
)
print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
PYEOF
  exit 0
fi

# SID / project meta 산정 (intercept hook 동일 로직)
SID="$session_id"
if [ -z "$SID" ] && [ -n "$cwd" ]; then
  SID=$(CWD_VAL="$cwd" python3 -c "
import hashlib, os
cwd = os.environ.get('CWD_VAL', '')
print(hashlib.md5(cwd.encode('utf-8')).hexdigest()[:12] if cwd else 'unknown')")
fi
SID=$(printf '%s' "$SID" | tr -c 'A-Za-z0-9-' '-' | cut -c1-32)

# Issue157: 색 = peacock.color 실색 (.vscode/settings.json walk-up → Projects.md → hsl 해시 fallback)
# name = peacock 찾은 프로젝트 루트 basename (z_htm 등 하위폴더 보정)
read -r PROJECT_NAME PROJECT_COLOR <<< "$(CWD_VAL="$cwd" python3 <<'PYEOF'
import hashlib, os, re
cwd = os.environ.get('CWD_VAL', '')
root = ''
hexcol = ''
d = cwd
while d and d != '/':
    p = os.path.join(d, '.vscode', 'settings.json')
    if os.path.isfile(p):
        try:
            m = re.search(r'"peacock\.color"\s*:\s*"(#[0-9A-Fa-f]{3,8})"', open(p, encoding='utf-8').read())
            if m:
                hexcol = m.group(1); root = d; break
        except Exception:
            pass
    d = os.path.dirname(d)
if not hexcol:
    bt = chr(96)
    try:
        for line in open(os.path.expanduser('~/_git/___pm/Projects.md'), encoding='utf-8'):
            cells = [c.strip().strip(bt) for c in line.split('|')]
            paths = [c for c in cells if c.startswith('~/') or c.startswith('/')]
            hexes = [c for c in cells if re.fullmatch(r'#[0-9A-Fa-f]{3,8}', c)]
            if paths and hexes:
                ph = os.path.expanduser(paths[0]).rstrip('/')
                if (cwd == ph or cwd.startswith(ph + '/')) and len(ph) > len(root or ''):
                    root = ph; hexcol = hexes[-1]
    except Exception:
        pass
def _hex_to_hsl(hx):
    hx = hx.lstrip('#')
    if len(hx) == 3:
        hx = ''.join(c*2 for c in hx)
    r = int(hx[0:2],16)/255.0; g = int(hx[2:4],16)/255.0; b = int(hx[4:6],16)/255.0
    mx = max(r,g,b); mn = min(r,g,b); l = (mx+mn)/2.0; dlt = mx-mn
    if dlt == 0:
        return 0.0, 0.0, l
    s = dlt/(2-mx-mn) if l > 0.5 else dlt/(mx+mn)
    if mx == r: h = ((g-b)/dlt) % 6
    elif mx == g: h = (b-r)/dlt + 2
    else: h = (r-g)/dlt + 4
    return h*60, s, l
if hexcol:
    h, s, l = _hex_to_hsl(hexcol)
else:
    hsh = hashlib.md5(cwd.encode('utf-8')).hexdigest()[:8] if cwd else ''
    if hsh:
        h = int(hsh[:4], 16) % 360; s = 0.55; l = 0.85
    else:
        h = 220; s = 0.30; l = 0.85
# Issue157: 가독성 보장 — 너무 밝은 peacock(>82%)는 darken, 채도 클램프. hue(프로젝트 정체성) 유지.
if l > 0.82: l = 0.80
if s > 0.72: s = 0.72
if s < 0.40: s = 0.45
color = 'hsl(%d,%d%%,%d%%)' % (round(h), round(s*100), round(l*100))
name = os.path.basename(root or cwd) or cwd or 'unknown'
print(name.replace(' ', '_'), color.replace(' ', ''))
PYEOF
)"

# OUT_DIR
if [ -n "$cwd" ] && [ -d "$cwd/_doc_work/z_htm" ]; then
  OUT_DIR="$cwd/_doc_work/z_htm"
elif [ -n "$cwd" ]; then
  sub_found=$(find "$cwd" -mindepth 3 -maxdepth 3 -type d -path "*/_doc_work/z_htm" 2>/dev/null | head -1)
  if [ -n "$sub_found" ]; then
    OUT_DIR="$sub_found"
  else
    OUT_DIR="/tmp/___pm"
    mkdir -p "$OUT_DIR"
  fi
else
  OUT_DIR="/tmp/___pm"
  mkdir -p "$OUT_DIR"
fi

# Server healthz + register
SERVER_PORT="${HTM_SERVER_PORT:-9876}"
HEALTH_URL="http://127.0.0.1:${SERVER_PORT}/healthz"
SERVER_TOKEN=""
CWD_HASH=""
INBOX_DIR=""

health=$(curl -s -o /dev/null -w "%{http_code}" --max-time 2 "$HEALTH_URL" 2>/dev/null)
if [ "$health" = "200" ] && [ -n "$cwd" ]; then
  cwd_enc=$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))" "$cwd")
  reg=$(curl -s --max-time 5 -X POST "http://127.0.0.1:${SERVER_PORT}/register?cwd=${cwd_enc}" 2>/dev/null)
  SERVER_TOKEN=$(printf '%s' "$reg" | python3 -c "
import json,sys
try: print(json.load(sys.stdin).get('token',''))
except: pass" 2>/dev/null)
  CWD_HASH=$(printf '%s' "$reg" | python3 -c "
import json,sys
try: print(json.load(sys.stdin).get('cwd_hash',''))
except: pass" 2>/dev/null)
  if [ -n "$SERVER_TOKEN" ] && [ -n "$CWD_HASH" ]; then
    INBOX_DIR="/tmp/___pm/claude-htm-inbox/${CWD_HASH}"
  fi
fi

if [ -z "$SERVER_TOKEN" ] || [ -z "$CWD_HASH" ] || [ -z "$INBOX_DIR" ]; then
  python3 <<PYEOF
import json
reason = (
    "## htm-form:auto 마커 감지됨 — server 미가용\n\n"
    f"healthz={'$health'} / register 실패. form 자동 회수 단일 경로 (Issue45) 라 fallback 없음.\n\n"
    "### 조치 (사용자 선택)\n"
    "1. `/dashboard-server start` 실행 후 응답 재작성 → 마커 재처리\n"
    "2. `..hub stop` 입력 → hub 모드 해제, 일반 채팅으로 회답 받기"
)
print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
PYEOF
  exit 0
fi

# decision: block + reason 에 form HTML 생성 지시 주입
MARKER_DATA=$(printf '%s' "$marker_validated" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    print(json.dumps(d.get('data', {}), ensure_ascii=False))
except Exception:
    print('{}')")

# Issue130: browser_focus + default_browser 토글 (Issue128 확장)
HUB_SETTING_FILE="$HOME/_git/___pm/data/hub_setting.yml"
# default_browser: firefox(기본)/chrome/edge/safari, 미지원 값은 .app 절대 경로로 해석
_db=$(grep -E '^[[:space:]]*default_browser:' "$HUB_SETTING_FILE" 2>/dev/null | head -1 | sed -E 's/^[^:]*:[[:space:]]*//; s/[[:space:]]*#.*$//; s/[[:space:]]*$//; s/^"//; s/"$//')
case "$_db" in
  ""|firefox|Firefox) _app="Firefox" ;;
  chrome|Chrome)      _app="Google Chrome" ;;
  edge|Edge)          _app="Microsoft Edge" ;;
  safari|Safari)      _app="Safari" ;;
  *)                  _app="$_db" ;;
esac
# browser_focus: false(기본)=백그라운드 open(-g, 포커스 미탈취), true=foreground
if grep -qE '^[[:space:]]*browser_focus:[[:space:]]*true' "$HUB_SETTING_FILE" 2>/dev/null; then
  HTM_OPEN_CMD="open -a \"$_app\""
else
  HTM_OPEN_CMD="open -g -a \"$_app\""
fi

QUESTIONS_JSON="$MARKER_DATA" \
  OUT_DIR="$OUT_DIR" \
  SID="$SID" \
  HTM_OPEN_CMD="$HTM_OPEN_CMD" \
  PROJECT_NAME="$PROJECT_NAME" \
  PROJECT_COLOR="$PROJECT_COLOR" \
  SERVER_PORT="$SERVER_PORT" \
  SERVER_TOKEN="$SERVER_TOKEN" \
  CWD_HASH="$CWD_HASH" \
  INBOX_DIR="$INBOX_DIR" \
  PROJECT_CWD="$cwd" \
  python3 <<'PYEOF'
import json, os, urllib.parse, shlex

marker_data = os.environ.get('QUESTIONS_JSON', '{}')
out_dir = os.environ.get('OUT_DIR', '/tmp/___pm')
sid = os.environ.get('SID', '')
project_name = os.environ.get('PROJECT_NAME', 'unknown')
project_color = os.environ.get('PROJECT_COLOR', 'hsl(220,30%,90%)')
server_port = os.environ.get('SERVER_PORT', '9876')
server_token = os.environ.get('SERVER_TOKEN', '')
cwd_hash = os.environ.get('CWD_HASH', '')
inbox_dir = os.environ.get('INBOX_DIR', '')
cwd = os.environ.get('PROJECT_CWD', '')
open_cmd = os.environ.get('HTM_OPEN_CMD', 'open -g -a Firefox')
cwd_q = urllib.parse.quote(cwd) if cwd else ''
# Issue157: 헤더 버튼(open-project/open-session)용 프로젝트 루트 — cwd 가 _doc_work/z_htm 하위면 보정
project_root = cwd.split('/_doc_work/')[0] if cwd and '/_doc_work/' in cwd else cwd

ask_path = f"{out_dir}/hub_htm_<YYYYMMDD_HHMMSS>_c_<주제>.htm"  # 날짜시간=`date +%Y%m%d_%H%M%S`, 주제=핵심 10자 내외 kebab, mode c=auto 폼(Mode D, doc-register 제외)
path_note = "프로젝트 로컬 (_doc_work/z_htm/)" if not out_dir.startswith('/tmp') else "/tmp/___pm fallback"
answer_url = f"http://127.0.0.1:{server_port}/answer?cwd={cwd_q}&token={server_token}&sid={sid}"

# Issue90 — inbox 세션 격리. 같은 cwd 두 세션이 같은 inbox 를 공유해 poll 이 다른 세션
# 폼 응답을 회수하던 결함의 수정. 2중 방어:
#   1) sid 서브폴더: /answer URL 에 &sid 전달 → 서버가 inbox/{cwd_hash}/{sid}/ 에 write
#      (서버 갱신 후 기계적 격리). poll 이 자기 sid 서브폴더를 우선 탐색.
#   2) 첫 질문 시그니처(HTM_Q1) grep: 서버 미갱신(flat write) 또는 sid 비고유(session_id
#      부재 → cwd-md5 fallback) 시의 가드. JSON 이스케이프 문자(" \) 전까지 첫 줄 사용.
def _q1_sig(qtext):
    s = (qtext or '').split('\n')[0]
    for ch in ('"', '\\'):
        s = s.split(ch)[0]
    return s.strip()
try:
    _md0 = json.loads(marker_data)
    _qs0 = _md0.get('questions', []) if isinstance(_md0, dict) else []
    q1_sig = _q1_sig(_qs0[0].get('question', '')) if _qs0 else ''
except Exception:
    q1_sig = ''
q1_quoted = shlex.quote(q1_sig) if q1_sig else "''"
sid_quoted = shlex.quote(sid) if sid else "''"

# Issue68: 폼 JS 템플릿 SSOT — hooks/fpm-ask-form-template.js 단일 출처에서 읽어 placeholder 치환
# Issue132: {OPEN_PROJECT_URL}+{PROJECT_CWD_JSON} 치환 (Mode D 는 submit-session-btn 없음 → dead code, literal leak 방지용)
open_project_url = f"http://127.0.0.1:{server_port}/open-project"
form_js = (open(os.path.join(os.environ.get('CLAUDE_PLUGIN_ROOT', os.path.expanduser('~/.claude')), 'hooks/fpm-ask-form-template.js'), encoding='utf-8').read()
           .replace('{ANSWER_URL}', answer_url)
           .replace('{OPEN_PROJECT_URL}', open_project_url)
           .replace('{PROJECT_CWD_JSON}', json.dumps(cwd)))

# Issue132/157: CANONICAL 헤더 블록 — a/b/c/D 통일. 헤더 밖 비클릭 div 금지(Issue88/157)
project_header_guide = (
    "### ⚠️ CANONICAL 헤더 블록 (Issue132/157) — verbatim 복붙. 즉흥 재작성·헤더 밖 div 금지\n"
    "폼 `<body>` 최상단에 아래 `<header>` 그대로 삽입 (`{질문제목}` 만 치환). "
    "배지·세션·Hub·닫기 4개 모두 `<header>` 안 동일 행 — 헤더 밖 비클릭 `<div>` 절대 금지(Issue88/157):\n"
    "```html\n"
    "<header>\n"
    "  <h1>{질문제목}</h1>\n"
    "  <nav class=\"header-actions\">\n"
    "    <a class=\"proj-badge\" href=\"#\" title=\"클릭 → VSCode 로 __PNAME__ 열기\"\n"
    "       onclick=\"event.preventDefault();fetch('http://127.0.0.1:__SPORT__/open-project',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cwd:'__ROOT__'})}).then(function(r){return r.json();}).then(function(j){if(j&&j.error)alert('VSCode 열기 실패: '+j.error);}).catch(function(){alert('hub 서버 미응답 — VSCode 열기 실패');});\">📁 __PNAME__</a>\n"
    "    <a class=\"sess-link\" href=\"#\" title=\"클릭 → 이 문서를 만든 세션 탭으로 포커스\"\n"
    "       onclick=\"event.preventDefault();fetch('http://127.0.0.1:__SPORT__/open-session',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cwd:'__ROOT__',sid:'__SID__'})}).then(function(r){return r.json();}).then(function(j){if(j&&j.error)alert('세션 열기 실패: '+j.error);}).catch(function(){alert('hub 서버 미응답 — 세션 열기 실패');});\">🆚 세션</a>\n"
    "    <a class=\"hub-link\" href=\"http://127.0.0.1:__SPORT__/hub\" target=\"_blank\" title=\"통합 모니터링 Hub\">🎯📊</a>\n"
    "    <button type=\"button\" onclick=\"window.close()\">닫기 ✕</button>\n"
    "  </nav>\n"
    "</header>\n"
    "```\n"
    "```css\n"
    "header { position: sticky; top: 0; z-index: 100; display: flex; align-items: center;\n"
    "  justify-content: space-between; gap: 1rem; flex-wrap: wrap; padding: 0.9rem 1.4rem;\n"
    "  background: __PCOLOR__; color: #1a1a1a; }\n"
    "header h1 { margin: 0; font-size: 1.15rem; flex: 1 1 auto; min-width: 0; }\n"
    "header .header-actions { display: flex; align-items: center; gap: 0.5rem; flex: 0 0 auto; }\n"
    "header .proj-badge, header .sess-link, header .hub-link, header button { color: #1a1a1a; text-decoration: none;\n"
    "  cursor: pointer; white-space: nowrap; background: rgba(0,0,0,0.08);\n"
    "  border: 1px solid rgba(0,0,0,0.15); padding: 0.2rem 0.6rem; border-radius: 6px; font-size: 0.85rem; }\n"
    "header .proj-badge:hover, header .sess-link:hover, header .hub-link:hover, header button:hover {\n"
    "  background: rgba(0,0,0,0.16); text-decoration: underline; }\n"
    "```\n"
    "- `<title>` prefix: `\"__PNAME__ — <질문제목>\"`. 색=peacock 실색(Issue58/157), 글자 #1a1a1a — 흰 글자 금지(파스텔 위 invisible).\n"
).replace("__PNAME__", project_name).replace("__PCOLOR__", project_color).replace("__ROOT__", project_root).replace("__SID__", sid).replace("__SPORT__", server_port)

reason = (
    "## htm-form:auto 마커 감지 — Mode D 자동 폼 회수 (Issue43)\n\n"
    "직전 응답 본문에 `<!-- htm-form:auto -->` 마커 발견. AskUserQuestion 호출 없이 사용자 자유 응답을 form 으로 회수합니다.\n\n"
    "### 마커 데이터 (검증 통과 JSON)\n```json\n" + marker_data + "\n```\n\n"
    + project_header_guide
    + f"\n### form 자동 회수 (___pm htm-server port {server_port}, cwd_hash `{cwd_hash}`)\n\n"
    "**1. HTML form 생성** (file:// 으로 띄움):\n"
    "   - 각 `questions[]` 항목을 `<fieldset class=\"q-card\" data-question=\"...\">` 카드로 렌더\n"
    "   - `type: \"freetext\"` → `<textarea class=\"q-textarea\" placeholder=\"{placeholder}\" rows=\"4\">` 만 표시\n"
    "   - `type: \"select\"` + `multiSelect: false` → radio 그룹\n"
    "   - `type: \"select\"` + `multiSelect: true` → checkbox 그룹\n"
    "   - select 카드는 '기타 (직접 입력)' `<input type=\"text\" class=\"q-other\">` 추가\n"
    "   - **`<button id=\"submit-btn\">전송</button>`** + `<button onclick=\"window.close()\">닫기 ✕</button>`\n"
    "   - `<div id=\"status\">` 전송 결과 표시\n"
    "   - JavaScript (SSOT: `hooks/fpm-ask-form-template.js`, Issue68 — `{ANSWER_URL}` 치환 완료본. 아래 블록을 그대로 `<script>` 에 삽입. Mode D 는 submit-close-btn 없음 → 템플릿이 null-safe 처리):\n"
    "```js\n" + form_js + "```\n\n"
    "**2. 저장 + Firefox open**:\n"
    "   ```bash\n"
    f"  # path: {ask_path} ({path_note})\n"
    f"   {open_cmd} \"file://<절대경로>\"\n"
    "   ```\n\n"
    "**3. 채팅 안내** (caveman 압축, 다음 모두 포함):\n"
    "   1. 한 줄 헤드라인: '마커 감지. 자동 폼 열림. \"전송\" 클릭 → 회수 대기.'\n"
    "   2. 각 질문 텍스트 (압축 금지)\n"
    f"  3. 저장 경로: `📁 {ask_path}`\n"
    "   4. 답변 방법: '폼 사용. 브라우저 부재 시 채팅 자유 텍스트 가능.'\n\n"
    "**4. 답변 polling** (Bash):\n"
    "   ```bash\n"
    f"  HTM_Q1={q1_quoted} HTM_SID={sid_quoted} timeout 600 sh -c '\n"
    "    while :; do\n"
    "      for d in \"$HTM_SID\" \"\"; do\n"
    f"        for f in {inbox_dir}/$d/*.json; do\n"
    "          [ -e \"$f\" ] || continue\n"
    "          grep -qF \"$HTM_Q1\" \"$f\" 2>/dev/null && { printf \"%s\\n\" \"$f\"; exit 0; }\n"
    "        done\n"
    "      done\n"
    "      sleep 2\n"
    "    done'\n"
    "   ```\n"
    f"   - inbox: `{inbox_dir}` — Issue90 sid 격리: `$HTM_SID` 서브폴더 우선 탐색 → flat fallback, 양쪽 첫 질문 시그니처 `HTM_Q1` 매칭\n"
    "   - 위 명령은 본 폼 응답 json **하나만** 출력. 다른 세션 폼 json 은 sid 서브폴더 분리 또는 `HTM_Q1` 미포함으로 skip(미접촉)\n"
    "   - 파일 발견 → Read → JSON 파싱 → `rm` 삭제 → answers 추출 후 흐름 재개\n"
    "   - 타임아웃 10분 시 사용자 채팅 응답 안내\n\n"
    "### 중복 방지\n"
    "form HTML 생성·polling 완료 후 응답 본문에 마커 다시 작성 금지 (재트리거됨). 결과 보고 텍스트만 작성."
)

print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
PYEOF

exit 0
