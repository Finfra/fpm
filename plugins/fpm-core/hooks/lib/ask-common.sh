#!/usr/bin/env bash
# ask-common.sh — fpm-ask-{intercept,marker-detect}.sh 공용 컨텍스트 (Issue424_2 ③)
#
# ⚠️ 글로벌 SCAR 변경 가드 (Issue46): 모든 프로젝트 공유. cwd ≠ ~/.claude 면 즉시 수정 금지
#   → ~/.claude/Issue.md 이슈 등록 후 처리. 설계 SSOT: ~/.claude/_doc_arch/hub-mode-arch.md
#
# 왜 분리했나 —
#   intercept(PreToolUse)와 marker-detect(Stop)는 같은 `..ask` 폼 기능의 앞뒤인데 이벤트가
#   달라 배선을 합칠 수 없다(이슈 명세). 대신 양쪽에 **문자 그대로 복제**돼 있던 컨텍스트
#   계산 5블록(SID·프로젝트 이름/색·OUT_DIR·서버 등록·브라우저 커맨드)을 여기로 접었다.
#   같은 판정이 두 곳에 있으면 반드시 갈라진다 — Issue359(ask-say 분리 시절 판정 복제가
#   갈라짐)와 같은 병의 예방이다.
#
# ⚠️ source 전용 — 값(SID·PROJECT_NAME·OUT_DIR·SERVER_TOKEN …)을 호출자 전역에 남긴다.
#   `$(...)` 커맨드 치환으로 부르면 서브셸이라 전부 증발한다.
#
# ⚠️ 함수 본문을 들여쓰지 않은 이유 — 내부 `<<'PYEOF'` heredoc 의 종료 마커는 행 맨 앞이어야
#   한다. 들여쓰면 heredoc 이 파일 끝까지 먹는다(hub-context.sh 구현에서 실측).
#
# 📌 알려진 divergence (고치지 않고 기록만) — 프로젝트 이름/색 산출이 fpm-hub-trigger.sh
#   (Issue309: Projects.md 단일 소스)와 달리 여기는 **구판 .vscode walk-up 우선**이다.
#   Issue309 는 hub-trigger 만 고쳤고 ask 2종은 소급하지 않았다. 본 추출은 동등성이 계약이라
#   그대로 옮긴다 — 통일은 별도 이슈로(동작 변경이므로 스냅샷이 깨지는 것이 정상인 작업).

# ── SID — session_id 우선, 부재 시 cwd md5 12자 (파일명·URL 안전화 32자) ──
#   입력: $1=session_id $2=cwd → 출력변수: SID
ask_ctx_sid() {
SID="$1"
if [ -z "$SID" ] && [ -n "$2" ]; then
  SID=$(CWD_VAL="$2" python3 -c "
import hashlib, os
cwd = os.environ.get('CWD_VAL', '')
print(hashlib.md5(cwd.encode('utf-8')).hexdigest()[:12] if cwd else 'unknown')")
fi
SID=$(printf '%s' "$SID" | tr -c 'A-Za-z0-9-' '-' | cut -c1-32)
}

# ── 프로젝트 이름·색 (Issue157) — .vscode walk-up → Projects.md → hsl 해시 fallback ──
#   입력: $1=cwd → 출력변수: PROJECT_NAME PROJECT_COLOR
ask_ctx_project_meta() {
read -r PROJECT_NAME PROJECT_COLOR <<< "$(CWD_VAL="$1" python3 <<'PYEOF'
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
}

# ── OUT_DIR (Issue289) — 활성 htm/ → legacy z_htm/ → htm/ 신규 → /tmp fallback ──
#   입력: $1=cwd → 출력변수: OUT_DIR
_htm_dir_of() {  # $1=프로젝트 루트 → htm 출력 폴더 경로(없으면 빈 문자열)
  [ -d "$1/_doc_work/htm" ] && { printf '%s' "$1/_doc_work/htm"; return; }
  [ -d "$1/_doc_work/z_htm" ] && { printf '%s' "$1/_doc_work/z_htm"; return; }
  [ -d "$1/_doc_work" ] && { mkdir -p "$1/_doc_work/htm" && printf '%s' "$1/_doc_work/htm"; return; }
  printf ''
}
ask_ctx_out_dir() {
OUT_DIR=""
if [ -n "$1" ] && [ -d "$1/_doc_work" ]; then
  OUT_DIR=$(_htm_dir_of "$1")
elif [ -n "$1" ]; then
  sub_found=$(find "$1" -mindepth 2 -maxdepth 2 -type d -name "_doc_work" 2>/dev/null | head -1)
  [ -n "$sub_found" ] && OUT_DIR=$(_htm_dir_of "$(dirname "$sub_found")")
fi
if [ -z "$OUT_DIR" ]; then
  OUT_DIR="/tmp/___pm"
  mkdir -p "$OUT_DIR"
fi
}

# ── 서버 healthz + register (Issue45) ────────────────────────────────────
#   입력: $1=cwd → 출력변수: SERVER_PORT health SERVER_TOKEN CWD_HASH INBOX_DIR
#   실패 시 SERVER_TOKEN/CWD_HASH/INBOX_DIR 빈값 — fail-loud 분기는 호출자 소관
ask_ctx_server() {
SERVER_PORT="${HTM_SERVER_PORT:-9876}"
HEALTH_URL="http://127.0.0.1:${SERVER_PORT}/healthz"
SERVER_TOKEN=""
CWD_HASH=""
INBOX_DIR=""
health=$(curl -s -o /dev/null -w "%{http_code}" --max-time 2 "$HEALTH_URL" 2>/dev/null)
if [ "$health" = "200" ] && [ -n "$1" ]; then
  cwd_enc=$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))" "$1")
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
}

# ── 브라우저 open 커맨드 (Issue130/173) — default_browser + browser_focus ──
#   출력변수: _app _focus HTM_OPEN_CMD  (HUB_SETTING_FILE 도 여기서 정한다)
ask_ctx_browser() {
HUB_SETTING_FILE="${HUB_SETTING_FILE:-$HOME/_git/___pm/data/hub_setting.yml}"
# default_browser: firefox(기본)/chrome/edge/safari/ego, 미지원 값은 .app 절대 경로로 해석 (ego=ego lite, Issue533)
_db=$(grep -E '^[[:space:]]*default_browser:' "$HUB_SETTING_FILE" 2>/dev/null | head -1 | sed -E 's/^[^:]*:[[:space:]]*//; s/[[:space:]]*#.*$//; s/[[:space:]]*$//; s/^"//; s/"$//')
case "$_db" in
  ""|firefox|Firefox) _app="Firefox" ;;
  chrome|Chrome)      _app="Google Chrome" ;;
  edge|Edge)          _app="Microsoft Edge" ;;
  safari|Safari)      _app="Safari" ;;
  ego|Ego|"ego lite") _app="ego lite" ;;   # Issue533: 자동화 엔진 ego-browser 와 같은 앱. AppleScript 탭 제어 없음 → firefox 와 동일 open 폴백
  *)                  _app="$_db" ;;
esac
# browser_focus: false(기본)=백그라운드 open(-g, 포커스 미탈취), true=foreground
if grep -qE '^[[:space:]]*browser_focus:[[:space:]]*true' "$HUB_SETTING_FILE" 2>/dev/null; then
  HTM_OPEN_CMD="open -a \"$_app\""; _focus="true"
else
  HTM_OPEN_CMD="bash \"$HOME/_git/___pm/plugins/fpm-core/hooks/fpm-browser-open.sh\" -a \"$_app\" -f false -r false"; _focus="false"  # Issue173: helper 경유(focus 복원). Chrome open -g self-activate 방지. -r false=폼 새 탭(Issue153)
fi
}
