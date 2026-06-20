#!/bin/bash
# fpm-ask-intercept.sh — PreToolUse hook (matcher: AskUserQuestion)
#
# ⚠️ 글로벌 SCAR 변경 가드 (Issue46): 본 hook 은 모든 프로젝트가 공유. cwd ≠ ~/.claude
#   면 즉시 수정 금지 → ~/.claude/Issue.md 이슈 등록 후 처리. 설계 SSOT:
#   ~/.claude/_doc_arch/hub-mode-arch.md. 절차: ~/.claude/rules/global-scar-change-rules.md
#
# Issue45 (2026-05-19): Mode A paste-back 제거. ___pm htm-server (port 9876) 가
#   상시 운영되는 환경을 전제로 form 자동 회수 단일 경로로 단순화.
#   서버 down 시 fail-loud — paste-back fallback 없음.
#
# 동작:
#   - .hub-mode-active 플래그 없음           → 통과 (exit 0)
#   - 플래그 있음 + healthz 200 + /register OK → deny + form 자동 회수 지시 주입
#   - 플래그 있음 + 서버 실패                 → deny + 서버 재시작 안내 + 종료 옵션 제시
#   - Mode C(Live Dashboard) 는 본 hook 영향 받지 않음 (별도 dashboard agent)
#
# Issue126 (2026-06-03): b모드 명시 트리거 `..ask` 신설. `..ask` 는 fpm-hub-trigger.sh 에서
#   .hub-mode-active 플래그를 touch 하므로, 본 hook 은 트리거 종류(자동 모드 / `..show` / `..ask`)와
#   무관하게 동일 form 자동 회수 경로를 재사용함 (플래그 기반 단일 진입 — 별도 분기 불필요).
#   Issue133 (2026-06-03): a모드 render 트리거 `..hub`→`..show` rename (토글 `..hub stop` 등은 보존).
#
# 이전 이력:
#   - Issue37: ___pm 서버 의존 분리, Mode A paste-back 도입
#   - Issue38: 서버 healthz 기반 Mode B 자동 회수 추가 (옵셔널)
#   - Issue45: Mode A 제거, 서버 가정 단일화

set -u

FLAG_MODE="$HOME/.claude/.hub-mode-active"

if [ ! -f "$FLAG_MODE" ]; then
  exit 0
fi

input=$(cat)

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

# 질문 JSON 추출
questions_json=$(printf '%s' "$input" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    qs = d.get('tool_input', {}).get('questions', [])
    print(json.dumps(qs, ensure_ascii=False))
except Exception:
    print('[]')
" 2>/dev/null)

if [ "$questions_json" = "[]" ] || [ -z "$questions_json" ]; then
  exit 0
fi

# Issue45: ___pm htm-server 가용성 판정 (가정: 항상 가용)
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

# Issue45: 서버 실패 시 fail-loud — paste-back fallback 없음
if [ -z "$SERVER_TOKEN" ] || [ -z "$CWD_HASH" ] || [ -z "$INBOX_DIR" ]; then
  python3 <<PYEOF
import json
reason = (
    "## hub Mode 활성이나 ___pm htm-server 미가용\n\n"
    f"healthz={'200' if '$health' == '200' else '$health'} / register 실패. "
    "Mode A paste-back fallback 은 Issue45(2026-05-19) 에서 제거됨. "
    "form 자동 회수 단일 경로만 지원.\n\n"
    "### 조치 (사용자 선택)\n"
    "1. **서버 시작 후 재시도**: \`/dashboard-server start\` 실행 → 본 질문 재호출\n"
    "2. **hub 모드 해제**: \`..hub stop\` 입력 → AskUserQuestion 채팅 UI 로 정상 복귀\n\n"
    "### 채팅 응답 의무\n"
    "Claude 는 본 deny 를 받으면 사용자에게 위 두 옵션을 명확히 제시하고 입력 대기. "
    "임의로 작업 계속 시도 금지."
)
print(json.dumps({"hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": reason
}}, ensure_ascii=False))
PYEOF
  exit 0
fi

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
  _focus="true"; HTM_OPEN_CMD="open -a \"$_app\""
else
  _focus="false"; HTM_OPEN_CMD="open -g -a \"$_app\""
fi
# Issue162: browser_tab_reuse=true & 재사용 가능 브라우저(chrome/edge/safari) → 탭 재사용 helper 로 치환.
#   match=:9876 origin → /hub 대시보드 + htm-doc?path=… 모든 hub URL 단일 탭. file:// 등 미매칭은 새 탭(폴백 동등).
_reuse=$(grep -E '^[[:space:]]*browser_tab_reuse:' "$HUB_SETTING_FILE" 2>/dev/null | head -1 | sed -E 's/^[^:]*:[[:space:]]*//; s/[[:space:]]*#.*$//; s/[[:space:]]*$//')
_helper="$HOME/_git/___pm/plugins/fpm-core/hooks/fpm-browser-open.sh"
case "$_app" in "Google Chrome"|"Microsoft Edge"|"Safari") _reusable=1 ;; *) _reusable=0 ;; esac
if [ "$_reuse" = "true" ] && [ "$_reusable" = "1" ] && [ -f "$_helper" ]; then
  HTM_OPEN_CMD="bash \"$_helper\" -a \"$_app\" -f \"$_focus\" -r true -m http://127.0.0.1:9876"
fi

QUESTIONS_JSON="$questions_json" \
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

questions_json = os.environ.get('QUESTIONS_JSON', '[]')
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

ask_path = f"{out_dir}/hub_htm_<YYYYMMDD_HHMMSS>_b_<주제>.htm"  # 날짜시간=`date +%Y%m%d_%H%M%S`, 주제=질문 핵심 10자 내외 kebab, mode b=ask 폼
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
    _qs0 = json.loads(questions_json)
    q1_sig = _q1_sig(_qs0[0].get('question', '')) if _qs0 else ''
except Exception:
    q1_sig = ''
q1_quoted = shlex.quote(q1_sig) if q1_sig else "''"
sid_quoted = shlex.quote(sid) if sid else "''"

# Issue68: 폼 JS 템플릿 SSOT — hooks/fpm-ask-form-template.js 단일 출처에서 읽어 placeholder 치환
# Issue132: {OPEN_PROJECT_URL} + {PROJECT_CWD_JSON} 치환 (전송 후 해당 세션으로 버튼)
open_project_url = f"http://127.0.0.1:{server_port}/open-project"
form_js = (open(os.path.join(os.environ.get('CLAUDE_PLUGIN_ROOT', os.path.expanduser('~/.claude')), 'hooks/fpm-ask-form-template.js'), encoding='utf-8').read()
           .replace('{ANSWER_URL}', answer_url)
           .replace('{OPEN_PROJECT_URL}', open_project_url)
           .replace('{PROJECT_CWD_JSON}', json.dumps(cwd)))

# Issue143: 짝 a모드(..show 렌더) 페이지 탐색 → b 폼에 iframe+링크 임베드.
# a(Claude Write, cwd z_htm)와 b(hook, OUT_DIR fallback /tmp)가 서로 다른 폴더일 수 있어
# 후보 폴더(OUT_DIR + cwd z_htm + /tmp/___pm) 합집합에서 hub_htm_*_a_*.htm 중 mtime 최신 1개를 페어로 본다.
import glob as _glob, re as _re, html as _htmlmod
_cand_dirs = []
for _d in (out_dir, (os.path.join(cwd, '_doc_work', 'z_htm') if cwd else ''), '/tmp/___pm'):
    if _d and os.path.isdir(_d) and _d not in _cand_dirs:
        _cand_dirs.append(_d)
_a_files = []
for _d in _cand_dirs:
    _a_files += [f for f in _glob.glob(os.path.join(_d, 'hub_htm_*_a_*.htm')) if os.path.isfile(f)]
a_pair = max(_a_files, key=lambda f: os.path.getmtime(f)) if _a_files else ''
if a_pair:
    a_title = os.path.basename(a_pair)
    try:
        with open(a_pair, encoding='utf-8') as _fh:
            _m = _re.search(r'<title>(.*?)</title>', _fh.read(4000), _re.S)
        if _m and _m.group(1).strip():
            a_title = _m.group(1).strip()
            for _pre in (f'{project_name} — ', f'{project_name} - '):
                if a_title.startswith(_pre):
                    a_title = a_title[len(_pre):]
    except Exception:
        pass
    _t = _htmlmod.escape(a_title)
    _p = _htmlmod.escape(f'http://127.0.0.1:{server_port}/htm-doc?path=' + a_pair)  # Issue: http origin 폼에서 file:// iframe 차단 회귀 → hub 서버 경유
    _snippet = (
        '<details class="show-pair" open style="margin:1rem 1.5rem;border:1px solid #c9b8e0;border-radius:10px;overflow:hidden;">\n'
        '  <summary style="cursor:pointer;padding:0.6rem 1rem;background:hsl(273,30%,92%);color:#4a2d6b;font-weight:600;">'
        f'🔗 관련 ..show 페이지: {_t} '
        f'<a href="{_p}" target="_blank" style="margin-left:0.5rem;font-weight:400;">새 탭 ↗</a></summary>\n'
        f'  <iframe src="{_p}" style="width:100%;height:55vh;border:0;border-top:1px solid #c9b8e0;"></iframe>\n'
        '</details>'
    )
    show_embed_section = (
        "\n### 🔗 관련 ..show(a모드) 페이지 임베드 (Issue143)\n"
        f"직전 ..show 렌더(`{os.path.basename(a_pair)}`)를 폼에서 바로 확인하도록, 본문 `<main>` 최상단(질문 카드 앞)에 아래 스니펫을 그대로 삽입:\n"
        "```html\n" + _snippet + "\n```\n"
    )
else:
    show_embed_section = (
        "\n### 🔗 관련 ..show(a모드) 페이지 임베드 (Issue143)\n"
        "직전 ..show(a모드) 페이지 없음 — 임베드 스니펫 생략(무해).\n"
    )

# Issue132/157: CANONICAL 헤더 블록 — a(..show)/b(ask)/c(board) 통일. verbatim 복붙.
#   헤더 밖 비클릭 `<div>📁 name</div>` 금지(Issue88/157, "클릭 안되는 문자" 재발 원인).
#   색 = peacock 실색(Issue58/157), 글자 #1a1a1a. 세션=🖥, Hub=🎯 단독.
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
    "    <a class=\"hub-link\" href=\"http://127.0.0.1:__SPORT__/hub\" target=\"_blank\" title=\"통합 모니터링 Hub\"><img src=\"/fpm-icon.png\" alt=\"Hub\" style=\"height:1.2em;vertical-align:-0.25em;\"></a>\n"
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
    "- `<title>` 도 `\"__PNAME__ — <질문제목>\"` 형식으로 prefix. 색=peacock 실색(Issue58/157), 글자 #1a1a1a — 흰 글자(#fff) 금지(파스텔 배경 위 invisible).\n"
    "- 불변식: 배지 정적 `<span>` 금지(Issue103) → 순서 `📁`→`🖥`→`🎯`→`닫기 ✕` → 넷 모두 헤더 안 동일 행 → flex+space-between+wrap.\n"
).replace("__PNAME__", project_name).replace("__PCOLOR__", project_color).replace("__ROOT__", project_root).replace("__SID__", sid).replace("__SPORT__", server_port)

reason = (
    "## AskUserQuestion 가로채기 — HTML form 자동 회수 (Issue45 단일 경로)\n\n"
    "`.hub-mode-active` 플래그 활성 + ___pm htm-server 가용. "
    "AskUserQuestion 도구 호출 차단됨. 사용자가 채팅이 아닌 Firefox HTML 폼으로 답변하도록 다음 절차를 따르세요.\n\n"
    "### 질문 데이터 (인라인 JSON)\n```json\n" + questions_json + "\n```\n\n"
    + project_header_guide
    + show_embed_section
    + f"\n### form 자동 회수 (___pm htm-server port {server_port}, cwd_hash `{cwd_hash}`)\n\n"
    "폼 \"전송\" 클릭 → 서버 inbox 로 직접 POST → Claude bash polling 회수. 사용자 paste 액션 불필요.\n\n"
    "**1. HTML form 생성** (file:// 으로 띄움):\n"
    "   - 각 question 을 `<fieldset class=\"q-card\" data-question=\"...\">` 카드로 표시\n"
    "   - `multiSelect: false` → radio, `multiSelect: true` → checkbox\n"
    "   - '기타 (직접 입력)' `<input type=\"text\" class=\"q-other\">` 추가\n"
    "   - **자유 텍스트 보조 입력 (Issue43)**: 옵션 외 자유 응답 필요 시 동일 카드에 `<textarea class=\"q-textarea\" placeholder=\"...\">` 추가 — collectAnswers 가 textarea 값을 answers 에 합산\n"
    "   - **`<button id=\"submit-btn\">전송</button>`** (주 액션)\n"
    "   - **`<button id=\"submit-close-btn\">전송 후 닫기</button>`** (Issue57 — POST 성공 시 자동 `window.close()`)\n"
    "   - **`<button id=\"submit-session-btn\">전송 후 해당 세션으로</button>`** (Issue132 — POST 성공 시 `/open-project` 로 VSCode 세션 포커스 후 `window.close()`)\n"
    "   - `<button onclick=\"window.close()\">닫기 ✕</button>`\n"
    "   - `<div id=\"status\">` (전송 결과 표시 영역)\n"
    "   - JavaScript (SSOT: `hooks/fpm-ask-form-template.js`, Issue68 — `{ANSWER_URL}` 치환 완료본. 아래 블록을 그대로 `<script>` 에 삽입):\n"
    "```js\n" + form_js + "```\n\n"
    "**2. 저장 + Firefox open**:\n"
    "   ```bash\n"
    f"  # path: {ask_path} ({path_note})\n"
    f"   {open_cmd} \"file://<절대경로>\"\n"
    "   ```\n\n"
    "**3. 채팅 안내** (Issue40/Issue60 fallback 의무 — caveman 압축이되 다음 모두 포함):\n"
    "   1. 한 줄 헤드라인: '질문 폼 열림. \"전송\" 클릭 → 자동 회수 대기.'\n"
    "   2. 질문 텍스트 (압축 금지)\n"
    "   3. 옵션 라벨 + 1줄 desc (≤4개: 전부 bullet, 5개+: 라벨만 압축)\n"
    f"  4. 저장 경로: `📁 {ask_path}`\n"
    "   5. 답변 방법: '폼 사용. 브라우저 부재 시 채팅에 A/B/번호/자유 텍스트 입력 가능.'\n"
    "   (사유: 브라우저 표시 안 됐을 가능성(Firefox 강제 종료·hidden·미설치·원격 SSH·다른 데스크톱) 항상 가정 — **채팅 fallback 텍스트가 1차 채널**, 폼은 보조. 채팅만 읽어도 질문·옵션 파악 + 답변 가능해야 함. Issue60)\n\n"
    "**4. 답변 polling (Bash, 본 turn 종료 전 실행)**:\n"
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
    "   - 발견 시 Read → JSON 파싱 → answers 추출 → `rm` 삭제 → AskUserQuestion answers 형식으로 흐름 재개\n"
    "   - **타임아웃 10분 (Issue61)**. 시간 초과 시 사용자에게 다음 양식으로 채팅 답변 부탁:\n"
    "     ```\n"
    "     ⚠️ 폼 '전송' 버튼은 더 이상 회수 안 됨 (Claude polling 만료). 채팅에 JSON paste 부탁:\n"
    "     [{\"question\":\"Q1 텍스트\",\"answers\":[\"선택값1\"]}, {\"question\":\"Q2 텍스트\",\"answers\":[\"선택값2\"]}]\n"
    "     (간소화 허용: 'Q1: A, Q2: B' 자유 텍스트도 OK)\n"
    "     ```\n\n"
    "**5. 흐름 재개**: 받은 answers 로 원래 작업 계속\n\n"
    "### 해제\n"
    "사용자 `..hub stop`/`..hub off` → 모드 플래그 해제."
)

out = {
    "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason
    }
}
print(json.dumps(out, ensure_ascii=False))
PYEOF

exit 0
