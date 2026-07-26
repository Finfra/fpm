#!/bin/bash
# fpm-hub-trigger.sh — UserPromptSubmit hook
#
# ⚠️ 글로벌 SCAR 변경 가드 (Issue46): 본 hook 은 모든 프로젝트가 공유. cwd ≠ ~/.claude
#   면 즉시 수정 금지 → ~/.claude/Issue.md 이슈 등록 후 처리. 설계 SSOT:
#   ~/.claude/_doc_arch/hub-mode-arch.md. 절차: ~/.claude/rules/global-scar-change-rules.md
#
# 프롬프트에 a모드 render 트리거 `..show` (Issue133, 구 `..hub` deprecated alias) 감지 시:
#   1. .hub-mode-active-<md5(cwd)[:8]> 플래그 touch (Q&A intercept 활성화, Issue283 cwd 스코프)
#   2. HTML 렌더링 + 기본 브라우저 표시 + 후속 질문 form 처리 지시문 주입
# `..hub stop` 또는 `..hub off` 감지 시 플래그 해제 (단방향 모드 복귀 — 토글은 `..hub` 유지)
# Issue133: render 트리거만 `..hub`→`..show` rename. 우산 토글(`..hub on|off|start|stop`)·
#   c모드(`..hub dash`)는 `..hub` 보존 (우산명 충돌 해소가 목적).
#
# Issue83: `..show` 마커가 없어도 cwd 가 ___pm 등록 프로젝트면 hub 기본 on (자동 모드).
#   비프로젝트(/tmp 등)는 기본 off. per-cwd 상태는 ~/.claude/.hub-state/<hash> (on|off).
#
# Issue86: `/hub on|off` · `..hub on|off` — 폴더별 자동 모드 명시 토글.
#   상태 파일만 전환, render-blocking 미발동 (bare `..show` 와 구분).
#
# 출력 경로 결정 (Issue21):
#   - hook 입력 JSON의 cwd에서 _doc_work/ 존재 확인 (Issue289)
#   - 활성 htm/ → legacy z_htm/ → htm/ 신규 순으로 채택, 없으면 /tmp/ fallback

input=$(cat)
# Issue283: cwd 스코프 플래그. cwd 파싱 후 `.hub-mode-active-<hash>` 로 재할당됨(아래).
#   전역 단일 파일 시절엔 hub on 세션 플래그를 off 세션 hook 이 주워 b모드 form 이 누수됨.
FLAG_FILE="$HOME/.claude/.hub-mode-active-none"
# Issue83: 프로젝트 폴더 hub 기본 on — per-cwd 상태 파일로 override
STATE_DIR="$HOME/.claude/.hub-state"
# Issue105: 시스템 단위 마스터 OFF 플래그 (모든 프로젝트 자동 모드 차단)
SYSTEM_OFF_FLAG="$HOME/.claude/.hub-system-off"

# python3로 cwd / prompt / session_id 파싱 (hook 입력 JSON)
cwd=$(printf '%s' "$input" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('cwd', ''))
except Exception:
    pass" 2>/dev/null)

prompt=$(printf '%s' "$input" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('prompt', ''))
except Exception:
    pass" 2>/dev/null)

# 수면 모드 가드 (Issue278 / Issue281) — 활성 + 명시 hub 트리거 부재 시 자동 렌더 억제.
#   sleep-mode-trigger.sh 가 규칙을 주입하고, 여기서는 자동 hub 렌더 지시를 방출하지 않게 한다
#   (단일 책임 분리). 사용자가 `..show`/`..ask`/`..board`/`..hub`/`..sleep off` 를 명시하면 존중.
#   Issue281: 판정을 hooks/sleep-state.sh 로 단일화(전역 OR per-cwd) + config `rules.suppress_hub` 존중.
SLEEP_SUPPRESS_HUB=0
if [ -f "$HOME/.claude/hooks/sleep-state.sh" ]; then
  # shellcheck source=/dev/null
  . "$HOME/.claude/hooks/sleep-state.sh"
  if sleep_is_active "$cwd" && sleep_rule_on suppress_hub; then
    SLEEP_SUPPRESS_HUB=1
  fi
elif [ -f "$HOME/.claude/.sleep-mode-active" ]; then
  SLEEP_SUPPRESS_HUB=1
fi
if [ "$SLEEP_SUPPRESS_HUB" = "1" ]; then
  if ! printf '%s' "$prompt" | grep -qiE '(^|[[:space:]])(\.\.show|/show|\.\.ask|/ask|\.\.board|\.\.dashboard|/dashboard|\.\.hub|/hub|(\.\.|/)?sleep[[:space:]]+off)([[:space:]]|$)'; then
    cat <<'JSON'
{
  "hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": "## 😴 수면 모드 — 자동 hub 렌더 억제 (Issue278)\n\n수면 모드 중 자동 HTML 렌더/브라우저 open 금지. **평문 채팅으로 진행** — HTML 미작성·브라우저 미open. 함께 온 요청은 수면 규칙(권장형 자율 진행)대로 정상 수행. 명시 렌더가 필요하면 사용자가 `..show` 를 직접 입력. 해제는 `sleep off`."
  }
}
JSON
    exit 0
  fi
fi

# `..hub list` · `/hub list` — 등록 프로젝트 hub on/off 상태 일괄 조회(조회 전용, 토글 아님).
#   hub 웹 UI Project List 팝업을 열지 않고 채팅에서 바로 확인하기 위함.
#   server.py _load_projects_list()/_htm_state() 판정 로직을 python으로 복제.
if printf '%s' "$prompt" | grep -qiE '(^|[[:space:]])(\.\.hub|/hub)[[:space:]]+list([[:space:]]|$)'; then
  python3 <<'PYEOF'
import hashlib, json, os

home = os.path.expanduser("~")
system_off = os.path.exists(os.path.join(home, ".claude", ".hub-system-off"))
state_dir = os.path.join(home, ".claude", ".hub-state")
projects_md = os.path.join(home, "_git", "___pm", "Projects.md")

rows = []
try:
    with open(projects_md, encoding="utf-8") as f:
        for line in f:
            if not line.startswith("|"):
                continue
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) < 5:
                continue
            try:
                pid = int(cells[0])
            except ValueError:
                continue  # 헤더·구분선 행 skip
            name = cells[1]
            emoji = cells[6] if len(cells) > 6 else ""
            path = cells[4].strip("`").strip() if len(cells) > 4 else ""
            rows.append((pid, name, emoji, path))
except FileNotFoundError:
    pass

def state_of(path):
    if system_off:
        return "\U0001F534 off(시스템)"
    abs_path = os.path.expanduser(path).rstrip("/")
    if not abs_path:
        return "\U0001F7E2 on"
    h = hashlib.md5(abs_path.encode("utf-8")).hexdigest()[:8]
    content = None
    try:
        for fn in os.listdir(state_dir):
            if fn == h or fn.startswith(h + "__"):
                with open(os.path.join(state_dir, fn), encoding="utf-8") as sf:
                    content = sf.read().strip()
                break
    except (FileNotFoundError, OSError):
        pass
    return "\U0001F534 off" if content == "off" else "\U0001F7E2 on"

lines = ["| 번호 | 프로젝트 | hub |", "| :--- | :--- | :--- |"]
for pid, name, emoji, path in sorted(rows):
    label = f"{emoji} {name}".strip()
    lines.append(f"| {pid} | {label} | {state_of(path)} |")
table = "\n".join(lines)

ctx = (
    "## hub 프로젝트 on/off 목록 — `..hub list`\n\n"
    "hub 웹 Project List 팝업 없이 채팅에서 바로 확인. 아래 표를 그대로 응답 (재계산·재조회 금지):\n\n"
    f"{table}\n\n"
    "### 본 turn 처리\n"
    "- 조회 전용 — 렌더·폼·워크플로우 진입 금지. 위 표만 출력.\n"
    "- 개별 토글: `..hub on|off` (이 폴더) / `..hub on|off all` (시스템)"
)
print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": ctx}}, ensure_ascii=False))
PYEOF
  exit 0
fi

session_id=$(printf '%s' "$input" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('session_id', ''))
except Exception:
    pass" 2>/dev/null)

# Issue26: SID(세션 식별자) 결정 — session_id 우선, 미존재 시 cwd_hash로 fallback
SID="$session_id"
if [ -z "$SID" ] && [ -n "$cwd" ]; then
  SID=$(CWD_VAL="$cwd" python3 -c "
import hashlib, os
cwd = os.environ.get('CWD_VAL', '')
print(hashlib.md5(cwd.encode('utf-8')).hexdigest()[:12] if cwd else 'unknown')")
fi
# SID_FULL: open-session API 호출용 full UUID (Issue137 회귀 fix — truncate 시 vscode 세션 매칭 실패 → 새 세션 생성)
SID_FULL=$(printf '%s' "$SID" | tr -c 'A-Za-z0-9-' '-')
# SID는 파일명·URL 안전화용 32자 slug (영문/숫자/하이픈만)
SID=$(printf '%s' "$SID" | tr -c 'A-Za-z0-9-' '-' | cut -c1-32)

# Issue289: 렌더 산출물 쓰기 폴더 — 활성 `_doc_work/htm/`, legacy `_doc_work/z_htm/`.
#   프로젝트 단위 우선순위: 기존 htm/ → (없으면) 기존 z_htm/ 유지 → (둘 다 없으면) htm/ 신규 생성.
#   z_htm 만 있는 프로젝트를 강제로 htm/ 로 끌어올리지 않는 이유: P3 마이그레이션이
#   프로젝트별 전환 스위치 역할을 하고(htm/ 생성 = 그 프로젝트 전환 완료), 범위 밖 프로젝트
#   (prj2 볼트 등)를 하드코딩 없이 자동 제외할 수 있기 때문. 읽기는 서버가 HTM_DIRS 로 전부 커버.
#   설계 SSOT: ~/_git/___pm/_doc_arch/htm-lifecycle-design.md
_htm_dir_of() {  # $1=프로젝트 루트 → htm 출력 폴더 경로(없으면 빈 문자열)
  [ -d "$1/_doc_work/htm" ] && { printf '%s' "$1/_doc_work/htm"; return; }
  [ -d "$1/_doc_work/z_htm" ] && { printf '%s' "$1/_doc_work/z_htm"; return; }
  [ -d "$1/_doc_work" ] && { mkdir -p "$1/_doc_work/htm" && printf '%s' "$1/_doc_work/htm"; return; }
  printf ''
}

# OUT_DIR 결정: 프로젝트 로컬 우선 (Issue203 — 상향 탐색 추가)
# 1) $cwd/_doc_work                  (cwd 직하 — 단일 레포)
# 2) git root / 부모 순회 _doc_work  (cwd 가 프로젝트 하위폴더일 때 루트 채택)
# 3) $cwd/*/_doc_work                (mono-repo / sub-package 하향 스캔 — ex: cli/_doc_work)
# 4) /tmp fallback
OUT_DIR=""
if [ -n "$cwd" ] && [ -d "$cwd/_doc_work" ]; then
  OUT_DIR=$(_htm_dir_of "$cwd")
elif [ -n "$cwd" ]; then
  # Issue203: cwd 가 프로젝트 하위폴더(ex: unity_base/Assets)면 루트 _doc_work 를 놓쳐
  #   /tmp fallback → 등록 스킵 → hub 403. 하향 find 이전에 상향 탐색으로 루트 채택.
  up_root=""
  git_root=$(git -C "$cwd" rev-parse --show-toplevel 2>/dev/null)
  if [ -n "$git_root" ] && [ -d "$git_root/_doc_work" ]; then
    up_root="$git_root"
  else
    # git 미사용 대비 cwd 부모 순회 — 첫 발견 _doc_work 채택
    dir="$cwd"
    while [ -n "$dir" ] && [ "$dir" != "/" ]; do
      if [ -d "$dir/_doc_work" ]; then
        up_root="$dir"
        break
      fi
      dir=$(dirname "$dir")
    done
  fi
  if [ -n "$up_root" ]; then
    OUT_DIR=$(_htm_dir_of "$up_root")
  else
    sub_found=$(find "$cwd" -mindepth 2 -maxdepth 2 -type d -name "_doc_work" 2>/dev/null | head -1)
    [ -n "$sub_found" ] && OUT_DIR=$(_htm_dir_of "$(dirname "$sub_found")")
  fi
fi
if [ -z "$OUT_DIR" ]; then
  OUT_DIR="/tmp/___pm"
  mkdir -p "$OUT_DIR"
fi

# Issue22/Issue157: PROJECT_NAME + PROJECT_COLOR 계산
#   색 = peacock.color 실색 (Issue58/157) — cwd 에서 위로 .vscode/settings.json 탐색,
#        없으면 Projects.md prefix 매칭, 둘 다 실패 시 hsl 해시 fallback (임의색은 최후 수단).
#   name = peacock 찾은 프로젝트 루트 basename (htm/z_htm 등 하위폴더 보정).
read -r PROJECT_NAME PROJECT_COLOR <<< "$(CWD_VAL="$cwd" python3 <<'PYEOF'
import hashlib, os, re
cwd = os.environ.get('CWD_VAL', '')
root = ''
hexcol = ''
# 1. nearest ancestor .vscode/settings.json peacock.color
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
# 2. Projects.md prefix 매칭 fallback
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
# 3. hex → HSL + 가독성 클램프 (Issue157)
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
# Issue157: 너무 밝은 peacock(>82%)는 darken, 채도 클램프. hue(프로젝트 정체성) 유지.
if l > 0.82: l = 0.80
if s > 0.72: s = 0.72
if s < 0.40: s = 0.45
color = 'hsl(%d,%d%%,%d%%)' % (round(h), round(s*100), round(l*100))
name = os.path.basename(root or cwd) or cwd or 'unknown'
print(name.replace(' ', '_'), color.replace(' ', ''))
PYEOF
)"

# Issue181: python3 산출 실패(예외·미설치·빈 출력) 시 read 가 빈 문자열을 받아
#   canonical 헤더에 `background: ;` 가 임베드되어 배경이 사라지는 결함 방어.
#   python 정상 경로는 항상 2토큰을 출력하므로 여기 도달 시는 전체 실패 케이스.
[ -z "$PROJECT_COLOR" ] && PROJECT_COLOR="hsl(220,45%,80%)"
[ -z "$PROJECT_NAME" ] && PROJECT_NAME="unknown"

# Issue83: cwd_hash + 프로젝트 판정 + per-cwd 상태 파일 경로
# Issue105: 파일명에 프로젝트 라벨 포함 (`<hash>__<label>`) — 어느 폴더가 stop 상태인지 가시
CWD_HASH=$(CWD_VAL="$cwd" python3 -c "
import hashlib, os
c = os.environ.get('CWD_VAL', '')
print(hashlib.md5(c.encode('utf-8')).hexdigest()[:8] if c else 'none')")

# 라벨: 마지막 path segment. basename 이 '_'로 시작하면 parent-base 결합 (ex: _public → fSnippet-_public)
PROJECT_LABEL=$(CWD_VAL="$cwd" python3 -c "
import os, re
cwd = os.environ.get('CWD_VAL', '').rstrip('/')
if not cwd:
    print('unknown')
else:
    parts = cwd.split('/')
    base = parts[-1] if parts else 'unknown'
    parent = parts[-2] if len(parts) >= 2 else ''
    label = f'{parent}-{base}' if base.startswith('_') and parent else base
    print(re.sub(r'[^A-Za-z0-9._-]', '_', label)[:48] or 'unknown')")

STATE_FILE="$STATE_DIR/${CWD_HASH}__${PROJECT_LABEL}"

# Issue283: hub 모드 플래그를 cwd 스코프로 확정 (세션 간 누수 차단)
FLAG_FILE="$HOME/.claude/.hub-mode-active-${CWD_HASH}"

# Issue105 마이그레이션: 기존 hash-only 파일이 있고 새 라벨 파일이 없으면 rename
OLD_STATE_FILE="$STATE_DIR/$CWD_HASH"
if [ -f "$OLD_STATE_FILE" ] && [ ! -f "$STATE_FILE" ]; then
  mv "$OLD_STATE_FILE" "$STATE_FILE" 2>/dev/null
fi

# 프로젝트 판정: cwd 가 ~/_git/___pm/projects/* 번호 파일이 가리키는 경로에 at-or-under 인가
# prj3#Issue-unreg: prj0(=~, home)은 정확 일치만 매칭. home 하위 descendant 는 제외.
#   과거엔 home 이 at-or-under 로 매칭돼 ~/.vscode 등 home 아래 모든 폴더가 IS_PROJECT=1 →
#   미등록 폴더에서도 hub 자동 발동. home 은 네비 단축이지 "하위 전부 hub" 선언이 아님.
IS_PROJECT=$(CWD_VAL="$cwd" python3 -c "
import os
cwd = os.environ.get('CWD_VAL', '')
pdir = os.path.join(os.path.expanduser('~'), '_git', '___pm', 'projects')
home = os.path.realpath(os.path.expanduser('~'))
hit = False
if cwd:
    cwd = os.path.realpath(cwd)
    try:
        for fn in os.listdir(pdir):
            if not fn.isdigit():
                continue
            try:
                with open(os.path.join(pdir, fn)) as f:
                    p = f.read().strip()
            except Exception:
                continue
            if not p:
                continue
            p = os.path.realpath(os.path.expanduser(p))
            # home(prj0) 은 exact-only. 그 외 프로젝트는 at-or-under.
            if cwd == p or (p != home and cwd.startswith(p + os.sep)):
                hit = True
                break
    except Exception:
        pass
print('1' if hit else '0')")

# Issue163: `..text`/`..txt`/`/text`/`/txt` — 단발(이번 turn 한정) render-off 트리거.
#   state/flag 파일 무변경 (영속 토글 `..hub stop`/`off` 와 구분). 본 turn 자동 hub 렌더만 suppress.
#   자동 모드 분기(IS_PROJECT)·`..show` 렌더 분기보다 먼저 평가 — 렌더 진입 차단이 목적.
#   `..te?xt|/te?xt` 로 text/txt 4종 동시 커버. `..hub` 토글류(on/off/start/stop 접미 필요)와 비충돌.
# prj3#Issue199: bare `..text` (요청 텍스트 없이 마커만) 은 "재실행" 이 아니라 "직전 결과를 text 로 표시".
#   사유: `..show`/`..ask` 렌더가 브라우저에 안 떠서 사용자가 `..text` 로 확인할 때, 기존 문구는
#   "작업 정상 수행" → Claude 가 직전 작업을 재실행 → 멱등성 없는 세션에서 이중 실행 부작용.
#   토큰 제거 후 잔여 텍스트 유무로 bare vs `..text <요청>` 분기.
if printf '%s' "$prompt" | grep -qiE '(^|[[:space:]])(\.\.te?xt|/te?xt)([[:space:]]|$)'; then
  rm -f "$FLAG_FILE"  # 자동 모드가 켰을 수 있는 이번 turn 렌더 플래그 해제 (state 파일 불변)
  # 마커 토큰 제거 후 잔여(공백 제외) 유무 판정
  _text_rest=$(printf '%s' "$prompt" | sed -E 's#(\.\.te?xt|/te?xt)# #g' | tr -d '[:space:]')
  if [ -z "$_text_rest" ]; then
    # bare `..text` — 직전 결과 재표시 (재실행 금지)
    cat <<'JSON'
{
  "hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": "## hub 단발 render-off — bare `..text` (직전 결과 재표시, prj3#Issue199)\n\n요청 텍스트 없는 단독 `..text` = **'직전 turn 결과를 평문으로 다시 보여줘'** 의미 (재실행 아님). `..show`/`..ask` 렌더가 브라우저에 안 떴을 때 결과 확인용.\n\n**⚠️ 작업 재실행 금지.** 멱등성 없는 세션 이중 실행 방지 — 이미 수행된 작업(슬래시 커맨드·dev 사이클·커밋·설치 등)을 다시 실행하지 말 것. 대화 맥락의 **직전 응답 결과만 평문 채팅으로 요약·표시**. HTML 미작성·브라우저 미open. state/flag 무변경 → 다음 turn 자동 hub 모드 복귀.\n\n직전 결과가 대화 맥락에 없으면(세션 경계 등) 그 사실을 알리고 재실행 여부를 사용자에게 확인."
  }
}
JSON
  else
    # `..text <요청>` — 함께 온 요청은 정상 수행 + 평문 응답 (기존 동작)
    cat <<'JSON'
{
  "hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": "## hub 단발 render-off — `..text <요청>` (Issue163)\n\n이번 turn 한정 자동 hub 렌더 skip. **평문 채팅으로 응답** — HTML 문서 미작성·브라우저 미open. 함께 온 요청(슬래시 커맨드·dev 사이클·커밋 등)은 정상 수행. state/flag 파일 무변경 → 다음 turn 자동 hub 모드 복귀.\n\n영속 끄기는 `..hub stop`(이 폴더만) / `..hub off`(시스템 전체)."
  }
}
JSON
  fi
  exit 0
fi

# Issue200: 토글 스코프 통일 (Issue105 재정의)
#   * 토글 verb = on/off. 스코프 기본=프로젝트(현재 cwd), `all` 접미=시스템 전체.
#     - `..hub on|off`   · `/hub on|off`      → 프로젝트 단위 (STATE_FILE on/off)
#     - `..hub on|off all` · `/hub on|off all` → 시스템 단위 (SYSTEM_OFF_FLAG)
#   * 서버 lifecycle = start/stop/restart/status/disable/enable (slash 커맨드 전용).
#     hook 은 `/hub start|stop` 을 더 이상 가로채지 않음 → slash 커맨드가 서버 제어.
#   * `..hub start|stop` 은 프로젝트 on/off 의 deprecated alias (하위호환, `..hub` 전용).
#   * bare `..show <요청>` (구 `..hub`) 은 별도 분기 (render-only trigger, 아래)

# 토글 — `..hub on|off [all]` · `/hub on|off [all]`
#   매처 순서 주의: bare `on`/`off` 정규식이 `on all` 도 매칭하므로 `all` 변형을 먼저 평가.
HTM_ONOFF=""   # on | off
HTM_SCOPE=""   # system | project
if printf '%s' "$prompt" | grep -qiE '(^|[[:space:]])(\.\.hub|/hub)[[:space:]]+on[[:space:]]+all([[:space:]]|$)'; then
  HTM_ONOFF="on"; HTM_SCOPE="system"
elif printf '%s' "$prompt" | grep -qiE '(^|[[:space:]])(\.\.hub|/hub)[[:space:]]+off[[:space:]]+all([[:space:]]|$)'; then
  HTM_ONOFF="off"; HTM_SCOPE="system"
elif printf '%s' "$prompt" | grep -qiE '(^|[[:space:]])(\.\.hub|/hub)[[:space:]]+on([[:space:]]|$)'; then
  HTM_ONOFF="on"; HTM_SCOPE="project"
elif printf '%s' "$prompt" | grep -qiE '(^|[[:space:]])(\.\.hub|/hub)[[:space:]]+off([[:space:]]|$)'; then
  HTM_ONOFF="off"; HTM_SCOPE="project"
fi

# 시스템 스코프 (`all`) — SYSTEM_OFF_FLAG 제어
if [ "$HTM_SCOPE" = "system" ]; then
  if [ "$HTM_ONOFF" = "on" ]; then
    rm -f "$SYSTEM_OFF_FLAG"
    rm -f "$FLAG_FILE"  # 본 turn 은 토글 전용 — 렌더 미진입
    cat <<'JSON'
{
  "hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": "## hub 시스템 ON — `..hub on all` (Issue200)\n\n시스템 단위 마스터 OFF 플래그 (`~/.claude/.hub-system-off`) 제거. 모든 프로젝트의 자동 hub 모드 재활성 (per-cwd `off` 기록 폴더는 여전히 off 유지).\n\n### 본 turn 처리\n- 토글 전용 — **렌더·폼·워크플로우 진입 금지**. 한 줄 확인만: `hub 시스템 on (all).`\n- 프로젝트 단위 끄기: `..hub off` (이 폴더만) / 시스템 전체 끄기: `..hub off all`"
  }
}
JSON
  else
    touch "$SYSTEM_OFF_FLAG"
    rm -f "$FLAG_FILE"
    cat <<'JSON'
{
  "hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": "## hub 시스템 OFF — `..hub off all` (Issue200)\n\n시스템 단위 마스터 OFF 플래그 (`~/.claude/.hub-system-off`) 생성. 모든 프로젝트 자동 hub 모드 차단 (per-cwd `on` 기록 폴더 포함). bare `..show <요청>` render-only 트리거는 여전히 동작.\n\n### 본 turn 처리\n- 토글 전용 — **렌더·폼·워크플로우 진입 금지**. 한 줄 확인만: `hub 시스템 off (all).`\n- 재활성: `..hub on all`"
  }
}
JSON
  fi
  exit 0
fi

# 프로젝트 스코프 (기본) — per-cwd STATE_FILE 제어
if [ "$HTM_SCOPE" = "project" ]; then
  HTM_PROJ="$HTM_ONOFF"
  mkdir -p "$STATE_DIR"
  printf '%s' "$HTM_PROJ" > "$STATE_FILE"
  if [ "$HTM_PROJ" = "on" ]; then
    rm -f "$FLAG_FILE"  # 토글 전용 — 다음 turn 부터 자동 모드 발동
    PROJECT_LABEL="$PROJECT_LABEL" CWD_HASH="$CWD_HASH" python3 <<'PYEOF'
import os, json
label = os.environ.get('PROJECT_LABEL', 'unknown')
h = os.environ.get('CWD_HASH', 'none')
print(json.dumps({"hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": (
        f"## hub 프로젝트 ON ({label} — Issue200)\n\n"
        f"이 폴더의 자동 hub 모드를 `on` 으로 기록 (`~/.claude/.hub-state/{h}__{label}`). "
        "다음 턴부터 자동 HTML 렌더 (trivial 응답은 Issue85 로 skip).\n\n"
        "### 본 turn 처리\n"
        "- 토글 전용 — **렌더·폼·워크플로우 진입 금지**. 한 줄 확인만: "
        f"`hub 프로젝트 on ({label}).`\n"
        "- 끄려면 `..hub off` (이 폴더만) / 시스템 전체 끄기 `..hub off all`"
    )
}}, ensure_ascii=False))
PYEOF
  else
    rm -f "$FLAG_FILE"
    PROJECT_LABEL="$PROJECT_LABEL" CWD_HASH="$CWD_HASH" python3 <<'PYEOF'
import os, json
label = os.environ.get('PROJECT_LABEL', 'unknown')
h = os.environ.get('CWD_HASH', 'none')
print(json.dumps({"hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": (
        f"## hub 프로젝트 OFF ({label} — Issue200)\n\n"
        f"이 폴더의 자동 hub 모드를 `off` 로 기록 (`~/.claude/.hub-state/{h}__{label}`). "
        "프로젝트 폴더라도 자동 렌더 안 함. AskUserQuestion 정상 동작 복귀.\n\n"
        "### 본 turn 처리\n"
        "- 토글 전용 — **렌더·폼·워크플로우 진입 금지**. 한 줄 확인만: "
        f"`hub 프로젝트 off ({label}).`\n"
        "- 다시 켜려면 `..hub on` (이 폴더만) / 시스템 전체 켜기 `..hub on all`"
    )
}}, ensure_ascii=False))
PYEOF
  fi
  exit 0
fi

# `..hub start|stop` — 프로젝트 on/off 의 deprecated alias (하위호환, `..hub` 전용).
#   `/hub start|stop` 은 여기서 매칭하지 않음 → slash 커맨드(서버 lifecycle)로 통과.
HTM_PROJ=""
if printf '%s' "$prompt" | grep -qiE '(^|[[:space:]])\.\.hub[[:space:]]+start([[:space:]]|$)'; then
  HTM_PROJ="on"
elif printf '%s' "$prompt" | grep -qiE '(^|[[:space:]])\.\.hub[[:space:]]+stop([[:space:]]|$)'; then
  HTM_PROJ="off"
fi
if [ -n "$HTM_PROJ" ]; then
  mkdir -p "$STATE_DIR"
  printf '%s' "$HTM_PROJ" > "$STATE_FILE"
  if [ "$HTM_PROJ" = "on" ]; then
    rm -f "$FLAG_FILE"  # 토글 전용 — 다음 turn 부터 자동 모드 발동
    PROJECT_LABEL="$PROJECT_LABEL" CWD_HASH="$CWD_HASH" python3 <<'PYEOF'
import os, json
label = os.environ.get('PROJECT_LABEL', 'unknown')
h = os.environ.get('CWD_HASH', 'none')
print(json.dumps({"hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": (
        f"## hub 프로젝트 ON ({label} — Issue200, `..hub start` deprecated alias)\n\n"
        f"이 폴더의 자동 hub 모드를 `on` 으로 기록 (`~/.claude/.hub-state/{h}__{label}`). "
        "다음 턴부터 자동 HTML 렌더 (trivial 응답은 Issue85 로 skip).\n\n"
        "### 본 turn 처리\n"
        "- 토글 전용 — **렌더·폼·워크플로우 진입 금지**. 한 줄 확인만: "
        f"`hub 프로젝트 on ({label}). (알림: '..hub start' 는 '..hub on' 으로 변경됨)`\n"
        "- 끄려면 `..hub off` (이 폴더만) / 시스템 전체 끄기 `..hub off all`"
    )
}}, ensure_ascii=False))
PYEOF
  else
    rm -f "$FLAG_FILE"
    PROJECT_LABEL="$PROJECT_LABEL" CWD_HASH="$CWD_HASH" python3 <<'PYEOF'
import os, json
label = os.environ.get('PROJECT_LABEL', 'unknown')
h = os.environ.get('CWD_HASH', 'none')
print(json.dumps({"hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": (
        f"## hub 프로젝트 OFF ({label} — Issue200, `..hub stop` deprecated alias)\n\n"
        f"이 폴더의 자동 hub 모드를 `off` 로 기록 (`~/.claude/.hub-state/{h}__{label}`). "
        "프로젝트 폴더라도 자동 렌더 안 함. AskUserQuestion 정상 동작 복귀.\n\n"
        "### 본 turn 처리\n"
        "- 토글 전용 — **렌더·폼·워크플로우 진입 금지**. 한 줄 확인만: "
        f"`hub 프로젝트 off ({label}). (알림: '..hub stop' 는 '..hub off' 으로 변경됨)`\n"
        "- 다시 켜려면 `..hub on` (이 폴더만) / 시스템 전체 켜기 `..hub on all`"
    )
}}, ensure_ascii=False))
PYEOF
  fi
  exit 0
fi

# Issue24 Phase 7 / Issue37 / Issue41 / Issue126: `..hub dash` / `..dashboard` / `..board` — Mode C Live Dashboard agent 트리거
# Mode C 는 ___pm 서버(htm-server) 의 SSE 사용. hub Q&A 도 동일 서버 inbox 사용 (Issue45).
# Issue41 (2026-05-19): `..dashboard` alias 추가 — 자연어 매칭 강화
# Issue126 (2026-06-03): `..board <topic>` 신설 — c모드 단일 단어 트리거. `..hub dash`/`..dashboard` 는
#   하위호환 별칭으로 유지 (deprecation 예정, 즉시 제거 금지 — 기존 muscle memory 보호).
if printf '%s' "$prompt" | grep -qE '(^|[[:space:]])(\.\.hub[[:space:]]+dash|\.\.dashboard|\.\.board)([[:space:]]|$)'; then
  touch "$FLAG_FILE"
  SERVER_PORT="${HTM_SERVER_PORT:-9876}"
  health=$(curl -s -o /dev/null -w "%{http_code}" --max-time 2 "http://127.0.0.1:${SERVER_PORT}/healthz" 2>/dev/null)

  # topic 추출: "..hub dash <topic ...>" / "..dashboard <topic ...>" / "..board <topic ...>" 에서 트리거 다음 토큰들
  TOPIC=$(printf '%s' "$prompt" | sed -nE 's/.*(\.\.hub[[:space:]]+dash|\.\.dashboard|\.\.board)[[:space:]]+(.+)/\2/p' | head -1)
  # Issue131: --auto-kill 플래그 — 완료 alert 후 tmux window 자동 kill (기본 미설정 = 잔존, 로그 보존)
  AUTO_KILL=false
  if printf '%s' "$TOPIC" | grep -qE '(^|[[:space:]])--auto-kill([[:space:]]|$)'; then
    AUTO_KILL=true
    TOPIC=$(printf '%s' "$TOPIC" | sed -E 's/(^|[[:space:]])--auto-kill([[:space:]]|$)/ /g' | sed -E 's/^[[:space:]]+//; s/[[:space:]]+$//')
  fi

  PROJECT_NAME="$PROJECT_NAME" \
    SERVER_PORT="$SERVER_PORT" \
    HEALTH="$health" \
    PROJECT_CWD="$cwd" \
    TOPIC="$TOPIC" \
    AUTO_KILL="$AUTO_KILL" \
    python3 <<'PYEOF'
import os, json
project_name = os.environ.get('PROJECT_NAME', 'unknown')
server_port = os.environ.get('SERVER_PORT', '9876')
health_ok = os.environ.get('HEALTH', '') == '200'
cwd = os.environ.get('PROJECT_CWD', '')
topic = os.environ.get('TOPIC', '').strip()
auto_kill = os.environ.get('AUTO_KILL', 'false') == 'true'

if not health_ok:
    context = (
        "## ⚠️ `..board` 트리거 — dashboard-server 미실행\n\n"
        f"Mode C(dashboard) agent 는 ___pm 서버 (port {server_port}, htm-server daemon) 필수. healthz 실패.\n\n"
        "### 즉시 조치\n"
        "1. 사용자에게 `/dashboard-server start` 안내 (Issue37 이후 명칭)\n"
        "2. 시작 후 다시 `..board <topic>` 입력 (별칭: `..hub dash` / `..dashboard`)\n\n"
        "본 turn 응답: agent 호출 금지. 채팅으로 서버 미실행 안내만."
    )
else:
    topic_clause = f"`{topic}`" if topic else "(사용자에게 topic 확인 필요)"
    context = (
        "## `..board` 트리거 감지 — Mode C Live Dashboard agent (Issue24 Phase 7, Issue126)\n\n"
        "(별칭: `..hub dash` / `..dashboard` — 하위호환 유지)\n\n"
        f"프로젝트 `{project_name}`. 본 turn 은 **dashboard agent 1회 호출 후 종료**. 다른 작업 금지.\n\n"
        "### 처리 절차 (필수)\n"
        f"1. **topic 확인**: 트리거에서 추출된 topic = {topic_clause}\n"
        "   - 비어있으면 사용자에게 topic 1회 질의 후 종료 (자동 추측 금지)\n"
        "2. **Agent 도구 호출**:\n"
        "   ```\n"
        "   Agent(\n"
        "     description='dashboard 시작',\n"
        "     subagent_type='dashboard',\n"
        "     prompt='topic=<TOPIC>; cwd=" + cwd + "; htm-server 활성. tmux pane 에서 runner 시작 + dashboard push. ~/.claude/agents/fpm-dashboard.md 절차 따를 것.'\n"
        "   )\n"
        "   ```\n"
        "3. agent 반환 결과를 채팅에 그대로 전달 (요약 + stable URL + pane 명령 + 핵심 데이터)\n\n"
        "### 4. 완료 폴러 기동 (Issue131 — finite 작업만)\n"
        "agent 반환 메타로 finite 판정:\n"
        "- worker_pid 설정 모니터링 / 큐 모드 → **finite** (status:done 도달) → 폴러 기동\n"
        "- 무한 heartbeat (worker_pid 미설정 순수 모니터링) → 폴러 **생략** (수동 stop 용도, alert 불필요)\n\n"
        "finite 면 turn 종료 전 `run_in_background: true` Bash 폴러 1개 기동 (DATA_FILE=agent 반환 dash.yaml 절대경로):\n"
        "```bash\n"
        "DATA_FILE='<dash.yaml 절대경로>'; TOPIC='<topic>'\n"
        "ETA_SEC=''   # agent ETA 추정 있으면 초 단위, 없으면 빈 값\n"
        "POLL=30; TIMEOUT=${ETA_SEC:+$((ETA_SEC*2))}; TIMEOUT=${TIMEOUT:-21600}   # 기본 6h (ETA 알면 ETA*2)\n"
        "START=$(date +%s)\n"
        "while :; do\n"
        "  st=$(yq -r '.status' \"$DATA_FILE\" 2>/dev/null)\n"
        "  case \"$st\" in\n"
        "    done) echo \"BOARD_DONE topic=$TOPIC\"; break;;\n"
        "    stopped|halted) echo \"BOARD_END topic=$TOPIC status=$st\"; break;;\n"
        "  esac\n"
        "  [ $(( $(date +%s) - START )) -ge \"$TIMEOUT\" ] && { echo \"BOARD_TIMEOUT topic=$TOPIC elapsed=$(( $(date +%s) - START ))s\"; break; }\n"
        "  sleep \"$POLL\"\n"
        "done\n"
        "```\n"
        "→ 폴러 exit 시 harness 가 본 세션 재호출. 폴 30s, 기본 만료 6h (SCAR 전역 스케줄링: crontab 금지·네이티브 폴링 허용).\n\n"
        "### 5. 완료 alert (폴러 exit 후 재호출 시)\n"
        "폴러 stdout 확인 후 채팅 alert:\n"
        "- `BOARD_DONE` → DATA_FILE `yq` read → ✅ `<topic>` 완료 · 소요시간 · 핵심 결과(checklist done 비율 / progress / 검증 통과) · 산출물 경로\n"
        "- `BOARD_END` (stopped/halted) → ⏹ 중단 alert (사유)\n"
        "- `BOARD_TIMEOUT` → ⏳ 폴러 만료 (ETA×2 또는 6h 경과, 여전히 running) → 폴러 재기동 여부 사용자 질의\n\n"
        + ("### 6. auto-kill (--auto-kill 지정됨)\n"
           "BOARD_DONE alert 후 tmux window 자동 종료: `cdft kill :<win_name>` (또는 `tmux kill-window -t pm:<win_name>`). 로그 유실 주의.\n\n"
           if auto_kill else
           "### 6. window 잔존 (기본 — --auto-kill 미지정)\n"
           "완료 후 tmux window 잔존 (로그 보존). alert 에 수동 kill 명령 안내: `cdft kill :<win_name>`.\n\n")
        + "### 채팅 응답 의무 (Issue24 Phase 8)\n"
        "- 한 줄 요약 (무엇을, 어디 pane 에)\n"
        "- stable URL 전체 (token 포함, 임의 제거 금지)\n"
        "- pane capture/kill 명령\n"
        "- 데이터 핵심 bullet 2~3개 (브라우저 못 봐도 채팅만으로 상태 파악 가능)\n"
        "- finite 면 폴러 기동 사실 명시 (\"완료 시 자동 alert\")\n\n"
        "### 구버전 (참고)\n"
        "Mode C skill (`~/.claude/skills/dashboard/`) 폐기됨. 본 turn 부터 agent 만 사용.\n"
    )

print(json.dumps({"hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": context
}}, ensure_ascii=False))
PYEOF
  exit 0
fi


# Issue126 (2026-06-03): `..ask <주제>` — b모드(양방향 Q&A 폼) 명시 진입점
# 기존 b모드는 트리거 단어 없이 AskUserQuestion intercept 로만 진입했으나, 이제 단일 단어
#   `..ask` 로 "나에게 물어봐" 모드를 직접 호출. 플래그 touch → 후속 AskUserQuestion 을
#   fpm-ask-intercept.sh 가 동일 form 자동 회수 경로로 처리 (인프라 재사용).
# 매칭: `..ask` 가 render 분기보다 먼저 평가되도록 bare `..show`/`..hub` 분기 위에 배치.
if printf '%s' "$prompt" | grep -qiE '(^|[[:space:]])\.\.ask([[:space:]]|$)'; then
  # Issue283: `..ask` 는 1회성 진입 — state file 불변 (Issue178 이 `..show` 에 확립한 원칙 동일 적용).
  #   구 코드는 `printf 'on' > "$STATE_FILE"` 로 그 폴더 hub 를 영구 on 전환시켰음.
  touch "$FLAG_FILE"

  # topic 추출: "..ask <주제 ...>" 에서 트리거 다음 토큰들
  ASK_TOPIC=$(printf '%s' "$prompt" | sed -nE 's/.*\.\.ask[[:space:]]+(.+)/\1/p' | head -1)

  ASK_TOPIC="$ASK_TOPIC" \
    SERVER_PORT="${HTM_SERVER_PORT:-9876}" \
    python3 <<'PYEOF'
import os, json
topic = os.environ.get('ASK_TOPIC', '').strip()
server_port = os.environ.get('SERVER_PORT', '9876')
topic_clause = f"`{topic}`" if topic else "(트리거에 주제 없음 — 사용자 직전 맥락에서 결정 주제 도출)"

context = (
    "## `..ask` 트리거 감지 — b모드 (양방향 Q&A 폼 자동 회수, Issue126)\n\n"
    f"주제 = {topic_clause}\n\n"
    "`.hub-mode-active-<hash>` 플래그 활성화됨. 본 turn 은 **사용자에게 결정을 묻는 폼 1회 제시**가 목적 "
    "(\"나에게 물어봐\" 모드 — 응답 자체가 결정 회수 폼).\n\n"
    "### 처리 절차 (필수)\n"
    "1. 주제에 대해 사용자가 선택할 **2~4개 옵션**을 도출 (권장안은 첫 옵션 + label 끝 `(권장)`).\n"
    "   - 옵션 도출에 정보 제공·비교가 필요하면 먼저 간단한 본문 HTML(a모드 절차)로 옵션 설명·trade-off 렌더 후 폼 분리. trivial 하면 본문 생략하고 바로 폼.\n"
    "2. **`AskUserQuestion` 도구 호출** — `fpm-ask-intercept.sh` (PreToolUse hook)가 가로채 "
    "form HTML 생성·Firefox open·server inbox 자동 회수 지시를 주입함. 그 지시를 그대로 따를 것.\n"
    "   - 호출 예: `AskUserQuestion(questions=[{\"question\":\"...\",\"header\":\"...\",\"multiSelect\":false,"
    "\"options\":[{\"label\":\"A (권장)\",\"description\":\"...\"}, ...]}])`\n"
    "3. 텍스트 bullet 리스트로 선택지를 dump 하지 말 것 — 결정 요청은 반드시 `AskUserQuestion` 호출로 분리.\n\n"
    f"### 서버 전제\n"
    f"- ___pm htm-server (port {server_port}) 상시 운영 전제. 서버 down 시 intercept hook 이 fail-loud "
    "(`/dashboard-server start` 후 재시도 또는 `..hub stop` 안내).\n\n"
    "### 채팅 fallback 의무 (Issue60)\n"
    "- 폼 열림 안내 + 질문 텍스트 + 옵션 라벨/desc + 저장 경로 포함 (Firefox 부재 가정, 채팅만으로 답 가능).\n\n"
    "### 모드 관계\n"
    "- a모드(`..show`, 단방향 렌더) / b모드(`..ask`, 양방향 폼) / c모드(`..board`, dashboard) 3트리거 체계.\n"
    "- 토글은 hub 단위 공유: 끄기 `..hub stop` (이 폴더) / `..hub off` (시스템 전체)."
)
print(json.dumps({"hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": context
}}, ensure_ascii=False))
PYEOF
  exit 0
fi


# B. Slash command + ..show(또는 구 ..hub) 끝 위치 → 경고 후 exit (사용자 위치 교정)
# 사유: `/dev 885 ..show` 형식은 slash command가 prompt 흡수 → hub additionalContext 무시됨
# Issue33: regex 강화 — `/단어<space|EOL>` 만 매칭. `/tmp/test2` 같은 file path 는 두 번째 `/` 로 인해 미매칭
if printf '%s' "$prompt" | grep -qE '^/[a-zA-Z][a-zA-Z0-9_-]*([[:space:]]|$)' && \
   printf '%s' "$prompt" | grep -qE '(\.\.show|\.\.hub)[[:space:]]*$'; then
  cat <<'JSON'
{
  "hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": "⚠️ `..show`(렌더 트리거)를 slash command와 함께 쓸 때는 **맨 앞**에 두어야 작동. 예: `..show /dev 885`. 현재 prompt는 slash command가 흡수하여 hub 모드 미작동. 본 turn은 평소대로 처리. 다음 turn부터 위치 변경 권장."
  }
}
JSON
  exit 0
fi

# `..show`(구 `..hub` deprecated) 마커 감지: 공백 경계 또는 줄 끝
# Issue45 (2026-05-19): ___pm 상시 운영 전제. form 자동 회수 단일 경로 (paste-back 제거).
# 본문 HTML 은 file:// 직접 open. Q&A 만 intercept hook 이 ___pm htm-server inbox 로 자동 회수.
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
# Issue152: browser_open 키 — off/background/foreground 3-way 자동 open 판정.
#   browser_focus(open 포커스 여부) + render_target:hub(open-skip) 두 신호를 단일 키로 통합.
#   SSOT 설계: ~/_git/___pm/_doc_arch/hub_setting.md "browser_open (Issue170)".
#   off=자동 open 생략(채팅 URL 만) / background=open -g(포커스 미탈취) / foreground=open(포커스 탈취).
_bopen=$(grep -E '^[[:space:]]*browser_open:' "$HUB_SETTING_FILE" 2>/dev/null | head -1 | sed -E 's/^[^:]*:[[:space:]]*//; s/[[:space:]]*#.*$//; s/[[:space:]]*$//; s/^"//; s/"$//')
# fallback(키 미설정/빈값): render_target:vscode→off, browser_focus(true→foreground/false→background) 역산 — 하위호환.
#   Issue263: 표면 축 분리 — open-skip 을 함의하는 값은 이제 `vscode`(VSCode 패널). `hub` 는 외부 브라우저 open 이므로 여기서 제외.
if [ -z "$_bopen" ]; then
  _rt_raw=$(grep -E '^[[:space:]]*render_target:' "$HUB_SETTING_FILE" 2>/dev/null | head -1 | sed -E 's/^[^:]*:[[:space:]]*//; s/[[:space:]]*#.*$//; s/[[:space:]]*$//; s/^"//; s/"$//')
  if [ "$_rt_raw" = "vscode" ]; then
    _bopen="off"
  elif grep -qE '^[[:space:]]*browser_focus:[[:space:]]*true' "$HUB_SETTING_FILE" 2>/dev/null; then
    _bopen="foreground"
  else
    _bopen="background"
  fi
fi
# browser_open → _focus(helper 윈도우 raise 게이팅용) + HTM_OPEN_CMD(open 커맨드) 도출.
#   off → 실제 open 생략(아래 render_target 강제 hub 로 open-skip + URL emit).
BROWSER_OPEN_OFF=0
case "$_bopen" in
  foreground) _focus="true";  HTM_OPEN_CMD="open -a \"$_app\"" ;;
  off)        _focus="false"; HTM_OPEN_CMD="open -g -a \"$_app\""; BROWSER_OPEN_OFF=1 ;;
  *)          _focus="false"; HTM_OPEN_CMD="bash \"$HOME/_git/___pm/plugins/fpm-core/hooks/fpm-browser-open.sh\" -a \"$_app\" -f false -r false" ;;  # background(기본) — Issue173: helper 경유(focus 복원). Chrome 은 open -g 무시 self-activate → helper 가 직전 frontmost 재활성. -r false=렌더 새 탭(Issue153 정합)
esac
# Issue153: browser_tab_reuse 재정의 — 렌더는 항상 새 탭(HTM_OPEN_CMD 미치환). reuse 는 `/hub` 단일탭 전용.
#   true  → canonical 헤더 hub-link target=fpm-hub (브라우저 네이티브 명명 탭 재사용; helper 불필요)
#   false → target=_blank (hub-link 도 매번 새 탭)
#   렌더(HTM_OPEN_CMD)는 위 browser_open case 의 plain open/open -g 유지 → 렌더마다 새 탭(하나씩 닫으며 검토 가능).
#   (구 Issue162 폐기: reuse helper 가 :9876 origin 매칭으로 /hub + 모든 htm-doc 렌더를 한 탭에 collapse 했음.
#    helper(fpm-browser-open.sh)는 렌더 미사용 — fhub 등 /hub 직접 open 경로용으로만 잔존.)
_reuse=$(grep -E '^[[:space:]]*browser_tab_reuse:' "$HUB_SETTING_FILE" 2>/dev/null | head -1 | sed -E 's/^[^:]*:[[:space:]]*//; s/[[:space:]]*#.*$//; s/[[:space:]]*$//')
if [ "$_reuse" = "true" ]; then HUB_LINK_TARGET="fpm-hub"; else HUB_LINK_TARGET="_blank"; fi

# prj3#Issue184: hub state(on/off) 를 render 분기 앞에서 미리 계산 (아래 render_target resolver 가 참조).
#   판정 우선순위: SYSTEM_OFF_FLAG > STATE_FILE > IS_PROJECT (자동 렌더 브랜치와 동일 로직).
#   과거엔 자동 브랜치 직전(옛 line 783)에서만 계산 → `..show` 브랜치는 state 를 몰라 render 위치를 못 바꿨음.
EFFECTIVE="off"
if [ -f "$SYSTEM_OFF_FLAG" ]; then
  EFFECTIVE="off"
elif [ -f "$STATE_FILE" ]; then
  EFFECTIVE=$(tr -d '[:space:]' < "$STATE_FILE" 2>/dev/null)
elif [ "$IS_PROJECT" = "1" ]; then
  EFFECTIVE="on"
fi

# Issue141: render_target — ..show/자동 hub 렌더의 출력 경로 분기 (file:// open vs hub 서버 URL).
#   데이터 SSOT: ___pm data/hub_setting.yml (prj1#Issue153 신설). 키 부재 시 local-open 무해 fallback.
#   local-open(기본)=`open file://` / hub=서버 /htm-doc URL 을 외부 브라우저로 open / vscode=VSCode Simple Browser 패널 / both=file://+URL.
# Issue263: 표면(surface) 축 분리 — prj3#Issue170 이 `hub` 를 "VSCode 패널 + 외부 open 금지"로 재정의해
#   "hub http URL 을 브라우저로 열기" 조합이 표현 불가였음. 그 표면 고정 동작을 신규 값 `vscode` 로 이관하고
#   `hub` 는 원뜻(URL 형식 = 서버 http)으로 복원 → 표시 표면은 default_browser/browser_open 이 다시 결정.
#   ⚠️ URL 라우트는 /htm-doc?path= (Issue50, register-doc 등록 htm 토큰없이 serve) — /view 는 cwd+token 전용이라 부적합.
#   render 문서는 Write 시 fpm-hub-doc-register PostToolUse hook 이 자동 register-doc → URL 즉시 유효.
RENDER_TARGET=$(grep -E '^[[:space:]]*render_target:' "$HUB_SETTING_FILE" 2>/dev/null | head -1 | sed -E 's/^[^:]*:[[:space:]]*//; s/[[:space:]]*#.*$//; s/[[:space:]]*$//; s/^"//; s/"$//')
[ -z "$RENDER_TARGET" ] && RENDER_TARGET="local-open"
# prj3#Issue249: yml 원본 값 보존 — 아래 파생 override(browser_open:off / hub-internal)가 RENDER_TARGET 을
#   "hub" 로 덮어쓰기 전 시점. Issue184 강제 예외는 "사용자가 yml 에 직접 hub 로 적었는가" 만 봐야 하며,
#   파생 hub 까지 예외로 삼으면 browser_open:off 의 helper 승격 동작(아래)이 깨짐.
RENDER_TARGET_CFG="$RENDER_TARGET"
# Issue289(P4): Zed 세션은 `vscode` 표면(Simple Browser)을 표현할 수단이 없다(Zed 에 내장 브라우저 패널 없음).
#   그대로 두면 렌더가 조용히 사라지므로 `hub`(외부 브라우저 + 서버 http URL)로 자동 강등하고 1줄 고지한다.
#   판정은 SessionStart 가 남긴 마커만 확인 — ps 재조회 없음(비용 0). hub/local-open/both 는 무변경.
ZED_DOWNGRADED=0
if [ "$RENDER_TARGET_CFG" = "vscode" ]; then
  # shellcheck source=lib/zed-detect.sh
  . "$HOME/.claude/hooks/lib/zed-detect.sh" 2>/dev/null || true
  if command -v zed_is_marked >/dev/null 2>&1 && zed_is_marked "$SID_FULL"; then
    RENDER_TARGET_CFG="hub"
    RENDER_TARGET="hub"
    ZED_DOWNGRADED=1
  fi
fi
# Issue263: open-skip 은 이제 render_target 값이 아니라 별도 플래그로 표현.
#   구조상 `hub` 가 "URL 형식"과 "open 생략" 두 뜻을 겸하던 것을 분리 — hub 는 URL 형식만, skip 은 아래 파생 신호.
HUB_OPEN_SKIP=0
# Issue152: browser_open=off → 자동 open 생략(채팅 URL 만). hub URL 형식 + open-skip 조합으로 표현.
[ "$BROWSER_OPEN_OFF" = "1" ] && { RENDER_TARGET="hub"; HUB_OPEN_SKIP=1; }
# Issue162: render_tab_mode=hub-internal → hub 쉘(/hub-shell) 내부 iframe 탭이 표시 담당 →
#   OS 브라우저 open 시 hub 내부 탭 + OS 새 탭 중복 생성. render_target 강제 hub 로 open 생략(URL 만 emit).
#   browser-tab(기본) 시 현행 동작 유지(회귀 0). SSOT: ~/_git/___pm/_doc_arch/hub_internal_tabs.md "영향 컴포넌트".
RENDER_TAB_MODE=$(grep -E '^[[:space:]]*render_tab_mode:' "$HUB_SETTING_FILE" 2>/dev/null | head -1 | sed -E 's/^[^:]*:[[:space:]]*//; s/[[:space:]]*#.*$//; s/[[:space:]]*$//; s/^"//; s/"$//')
[ "$RENDER_TAB_MODE" = "hub-internal" ] && { RENDER_TARGET="hub"; HUB_OPEN_SKIP=1; }   # Issue263: skip 을 명시 플래그로
# URL host = advertise_host ?? bind_host (주석처리 advertise_host 는 `^advertise_host:` 미매칭 → 생략 취급).
#   advertise 생략 + bind 0.0.0.0/미설정 → 접속 가능 host 강제(127.0.0.1) — `http://0.0.0.0` 좀비 URL 차단 (prj1#Issue153 가드).
_adv=$(grep -E '^[[:space:]]*advertise_host:' "$HUB_SETTING_FILE" 2>/dev/null | head -1 | sed -E 's/^[^:]*:[[:space:]]*//; s/[[:space:]]*#.*$//; s/[[:space:]]*$//; s/^"//; s/"$//')
_bind=$(grep -E '^[[:space:]]*bind_host:' "$HUB_SETTING_FILE" 2>/dev/null | head -1 | sed -E 's/^[^:]*:[[:space:]]*//; s/[[:space:]]*#.*$//; s/[[:space:]]*$//; s/^"//; s/"$//')
if [ -n "$_adv" ]; then
  RENDER_HOST="$_adv"
elif [ -n "$_bind" ] && [ "$_bind" != "0.0.0.0" ]; then
  RENDER_HOST="$_bind"
else
  RENDER_HOST="127.0.0.1"
fi
RENDER_PORT="${HTM_SERVER_PORT:-9876}"

# prj3#Issue184: render 위치를 hub state 로 분기 (요구 동작 — 사용자 확정).
#   - EFFECTIVE=on(enabled) + `..show`/자동  → 외부 브라우저 실제 open (RENDER_TARGET=local-open 강제).
#   - EFFECTIVE=off(disabled) + 명시 `..show` → RENDER_TARGET config 값을 fallback 위치로 사용
#     (현 config `render_target: hub` → VSCode Simple Browser). 즉 render_target 을 "disabled fallback" 으로 재해석.
#   구현 명세 옵션 (a) 채택 (신규 키 미도입, 최소 변경). browser_open:off × enabled 충돌은
#   crash-safe helper(fpm-browser-open.sh, prj1#Issue173) background open 으로 해소 — Chrome AppleScript 크래시 회피.
# prj3#Issue187: hub-internal(render_tab_mode) 이 EFFECTIVE=on 보다 우선.
#   hub-internal 은 hub 쉘 iframe 이 표시를 전담하므로 OS 새 탭 open 자체를 하면 안 됨(Issue162 가드).
#   Issue184 의 "enabled→local-open 강제"를 hub-internal 에서도 적용하면 iframe + OS 탭 동시 표시로
#   중복 렌더가 재발함 — hub-internal 이면 EFFECTIVE=on 이어도 이 강제를 건너뛴다.
# prj3#Issue249: yml `render_target: vscode` 는 EFFECTIVE=on 보다 우선 (hub-internal 예외와 동형).
#   사용자가 yml 에 명시적으로 vscode 를 적었다면 "VSCode Simple Browser 로 보겠다"는 표면 고정 의사표시이므로
#   hub-on 프로젝트에서도 그대로 존중한다. 이 예외가 없으면 그 값은 "hub off + 명시 `..show`"
#   전용 fallback 키로 축소되어, VSCode 안에서 일하는 사용자가 매 렌더를 수동으로 열어야 했음.
#   Issue263: 예외 조건을 `hub` → `vscode` 로 이전. `hub` 는 이제 외부 브라우저 open(표면 미고정)이라
#   "enabled → 외부 브라우저" 강제와 모순되지 않음 → 예외로 둘 이유가 없음.
#   ⚠️ RENDER_TARGET(파생 포함) 이 아니라 RENDER_TARGET_CFG(yml 원본)로 판정 — browser_open:off 가
#   파생시킨 hub 까지 예외로 삼으면 아래 helper 승격이 무력화됨.
if [ "$EFFECTIVE" = "on" ] && [ "$RENDER_TAB_MODE" != "hub-internal" ] && [ "$RENDER_TARGET_CFG" != "vscode" ]; then
  # Issue263: enabled 는 "실제 외부 open" 을 강제하지만 **URL 형식까지 뺏지는 않는다**.
  #   CFG=hub → 형식(hub http URL) 유지한 채 외부 브라우저로 open. 여기서 local-open 으로 덮으면
  #   "hub URL 을 브라우저로" 조합이 hub-on 프로젝트(등록 프로젝트 기본값)에서 다시 표현 불가가 되어
  #   본 이슈의 목적(직교성 복원) 자체가 무효화됨. 표면 고정(open 금지)은 vscode 만의 역할.
  if [ "$RENDER_TARGET_CFG" = "hub" ]; then
    RENDER_TARGET="hub"        # 형식 유지 + 아래 skip 해제로 실제 open 보장
  else
    RENDER_TARGET="local-open" # local-open/both/미설정: 기존대로 file:// 외부 open
  fi
  HUB_OPEN_SKIP=0              # Issue263: 실제 open 요구 → 파생 skip(browser_open:off) 해제
  if [ "$BROWSER_OPEN_OFF" = "1" ]; then
    # browser_open:off 는 open 을 생략하지만 enabled 는 "실제 open" 요구 → helper 경유 background open 으로 승격.
    HTM_OPEN_CMD="bash \"$HOME/_git/___pm/plugins/fpm-core/hooks/fpm-browser-open.sh\" -a \"$_app\" -f $_focus -r false"
    BROWSER_OPEN_OFF=0
  fi
fi
# EFFECTIVE=off 는 RENDER_TARGET(config)을 그대로 fallback 위치로 유지 — 별도 처리 불요.
# hub-internal + EFFECTIVE=on 도 RENDER_TARGET="hub"(라인 580 설정값) 유지 — 별도 처리 불요.

# prj3#Issue-unreg: /tmp fallback 은 서버 register-doc 스킵(라인 179) → hub/vscode 서버 라우트 403 → 아무것도 안 뜸.
#   OUT_DIR=/tmp/___pm 이면 config(render_target hub/vscode/hub-internal) 무관하게 file:// 직접 open 으로 강제.
#   "생성되면 반드시 표시" 보장. 서버·등록 불필요. (미등록 폴더 or _doc_work 없는 프로젝트 공통 안전망)
if [ "$OUT_DIR" = "/tmp/___pm" ]; then
  RENDER_TARGET="local-open"
  HUB_OPEN_SKIP=0
  if [ "$BROWSER_OPEN_OFF" = "1" ]; then
    # browser_open:off 라도 /tmp 는 채팅 URL 이 죽으므로(403) 실제 open 필요 → helper 승격.
    HTM_OPEN_CMD="bash \"$HOME/_git/___pm/plugins/fpm-core/hooks/fpm-browser-open.sh\" -a \"$_app\" -f $_focus -r false"
    BROWSER_OPEN_OFF=0
  fi
fi

# prj3#Issue-unreg: 미등록 폴더(IS_PROJECT=0) 렌더 정책 — hub(/tmp 렌더+표시) | text(평문, 기본).
#   data SSOT: ___pm data/hub_setting.yml (고급 탭). 키 부재 시 안전 기본값 text.
UNREG_RENDER=$(grep -E '^[[:space:]]*unregistered_render:' "$HUB_SETTING_FILE" 2>/dev/null | head -1 | sed -E 's/^[^:]*:[[:space:]]*//; s/[[:space:]]*#.*$//; s/[[:space:]]*$//; s/^"//; s/"$//')
[ -z "$UNREG_RENDER" ] && UNREG_RENDER="text"

# Issue133: a모드 render 트리거 `..hub` → `..show` rename. `..show`/`/show` = primary,
#   `..hub`(bare) = 한시적 deprecated alias. 토글(`..hub on|off|start|stop`)·c모드(`..hub dash`)는
#   위 분기에서 이미 처리·exit 됨 — 여기 도달한 `..hub` 는 render-intent 뿐 (보존 아님).
# 서버 down 시 intercept hook fail-loud 안내.
HUB_RENDER_TRIGGER=""
if printf '%s' "$prompt" | grep -qE '(^|[[:space:]])(\.\.show|/show)([[:space:]]|$)'; then
  HUB_RENDER_TRIGGER="show"
elif printf '%s' "$prompt" | grep -qE '(^|[[:space:]])\.\.hub([[:space:]]|$)'; then
  HUB_RENDER_TRIGGER="hub-deprecated"
fi

# prj3#Issue-unreg: 미등록 폴더 렌더 게이트. unregistered_render=text(기본) 이면
#   미등록 폴더(IS_PROJECT=0)에서 렌더가 발동할 상황(명시 ..show OR state-file/EFFECTIVE=on)에
#   htm 을 만들지 않고 평문으로 응답 (사용자가 본 "invisible /tmp htm" 재발 차단).
#   `unregistered_render: hub` 로 바꾸면 이 게이트를 통과 → 위 /tmp 안전망(file:// open)으로 표시.
#   등록 프로젝트(IS_PROJECT=1)는 무관 — 게이트 미적용.
if [ "$IS_PROJECT" = "0" ] && [ "$UNREG_RENDER" != "hub" ] \
   && { [ -n "$HUB_RENDER_TRIGGER" ] || [ "$EFFECTIVE" = "on" ]; }; then
  rm -f "$FLAG_FILE"
  cat <<'JSON'
{
  "hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": "## hub 렌더 skip — 미등록 폴더 (unregistered_render: text)\n\n현재 cwd 는 ___pm 등록 프로젝트가 아님(`Projects.md` 범위 밖). 미등록 폴더 기본 정책이 `text` 라 자동/`..show` hub 렌더를 발동하지 않음.\n\n**평문 채팅으로 응답** — HTML 문서 미작성·브라우저 미open. 요청된 작업(슬래시 커맨드·dev·커밋 등)은 정상 수행. state/flag 무변경.\n\n이 폴더에서도 hub 로 보고 싶으면: `hub_setting.yml` 고급 탭 `unregistered_render: hub` 로 변경(미등록 폴더는 /tmp 렌더 후 file:// 로 표시) 또는 이 폴더를 `Projects.md` 에 등록."
  }
}
JSON
  exit 0
fi

if [ -n "$HUB_RENDER_TRIGGER" ]; then
  # 플래그 활성화 — 후속 AskUserQuestion 을 form 으로 가로채기 위함
  touch "$FLAG_FILE"
  # Issue178: `..show` = 그 턴만 1회성 렌더. STATE_FILE 미변경 (off 면 off 유지).
  #   과거 Issue83 은 여기서 `printf 'on' > "$STATE_FILE"` 로 영구 on 덮어썼으나
  #   "off 기본 + ..show 1회성" 모델과 충돌 → 제거. 자동 모드 재개는 STATE_FILE/IS_PROJECT default 가 결정.

  # --new flag 제거 (호환성 위해 prompt 에서 인식만, 동작 변화 없음)
  PROJECT_NAME="$PROJECT_NAME" \
    PROJECT_COLOR="$PROJECT_COLOR" \
    PROJECT_CWD="$cwd" \
    SID="$SID" \
    SID_FULL="$SID_FULL" \
    OUT_DIR="$OUT_DIR" \
    HTM_OPEN_CMD="$HTM_OPEN_CMD" \
    HUB_RENDER_TRIGGER="$HUB_RENDER_TRIGGER" \
    RENDER_TARGET="$RENDER_TARGET" \
    HUB_OPEN_SKIP="$HUB_OPEN_SKIP" \
    RENDER_HOST="$RENDER_HOST" \
    RENDER_PORT="$RENDER_PORT" \
    HUB_LINK_TARGET="$HUB_LINK_TARGET" \
    ZED_DOWNGRADED="$ZED_DOWNGRADED" \
    python3 <<'PYEOF'
import os, json

project_name = os.environ.get('PROJECT_NAME', 'unknown')
project_color = os.environ.get('PROJECT_COLOR', 'hsl(220,30%,90%)')
cwd = os.environ.get('PROJECT_CWD', '')
sid = os.environ.get('SID', 'unknown')
sid_full = os.environ.get('SID_FULL', sid)
out_dir = os.environ.get('OUT_DIR', '/tmp')
open_cmd = os.environ.get('HTM_OPEN_CMD', 'open -g -a Firefox')
path_note = f"프로젝트 로컬 ({out_dir.split('_doc_work/')[-1] if '_doc_work/' in out_dir else out_dir})" if out_dir != '/tmp' else f"/tmp fallback → 프로젝트: {project_name} · 생성: cd {cwd} && mkdir -p _doc_work/htm"  # Issue276
# Issue141/Issue263: render_target 분기 — local-open=file:// open / hub=서버 URL 을 브라우저로 open
#   / vscode=VSCode Simple Browser 패널(외부 open 금지) / both=양쪽
render_target = os.environ.get('RENDER_TARGET', 'local-open')
hub_open_skip = os.environ.get('HUB_OPEN_SKIP', '0') == '1'   # Issue263: browser_open:off·hub-internal 파생 open 생략
render_host = os.environ.get('RENDER_HOST', '127.0.0.1')
render_port = os.environ.get('RENDER_PORT', '9876')
# Issue153: hub-link 탭 동작 — _blank(새 탭, 기본) / fpm-hub(명명 탭 재사용, browser_tab_reuse=true)
hub_link_target = os.environ.get('HUB_LINK_TARGET', '_blank')
hub_url = "http://%s:%s/htm-doc?path=<절대경로>" % (render_host, render_port)
if render_target == 'hub' and hub_open_skip:
    # Issue263: hub URL 형식 + open 생략 (browser_open:off 또는 render_tab_mode:hub-internal 파생)
    render_step = (
        "7. **hub URL emit only (render_target: hub + open 생략)** — 자동 open 안 함 (`browser_open: off` 또는 `render_tab_mode: hub-internal`). 표시는 hub 쉘 내부 탭 또는 사용자 수동 클릭이 담당:\n"
        f"   - 채팅에 hub URL 명시: `{hub_url}` (Write 시 `fpm-hub-doc-register` PostToolUse hook 이 자동 register-doc → URL 즉시 유효)\n"
        "   - ⚠️ `open` 명령(file://·http) 실행 금지 — URL emit 만\n"
    )
elif render_target == 'hub':
    # Issue263: hub = 서버 http URL 을 외부 브라우저로 open (원뜻 복원 — 표면은 default_browser/browser_open 이 결정)
    render_step = (
        "7. **hub 서버 URL 을 외부 브라우저로 표시 (render_target: hub, Issue263)** — `file://` 아닌 **http URL** 로 open:\n"
        "   ```bash\n"
        f"   {open_cmd} \"http://{render_host}:{render_port}/htm-doc?path=<절대경로>\"\n"
        "   ```\n"
        "   - 브라우저·포커스는 `default_browser`/`browser_open` 설정 따름\n"
        "   - Write 시 `fpm-hub-doc-register` PostToolUse hook 이 자동 `register-doc` → URL 즉시 유효 (open 전 등록 완료)\n"
        "   - ⚠️ `file://` 로 여는 것은 local-open 전용 — 여기선 http URL 만\n"
    )
elif render_target == 'vscode':
    render_step = (
        "7. **VSCode Simple Browser 표시 (render_target: vscode, Issue170/Issue263)** — `file://`·외부 브라우저 open **금지**. 문서를 VSCode 내부 Simple Browser 패널에 렌더:\n"
        "   - Write 후 아래 1줄 실행 (`<절대경로>` = 방금 저장한 .htm 절대경로):\n"
        "   ```bash\n"
        f"   curl -s -X POST http://{render_host}:{render_port}/open-simple-browser -H 'Content-Type: application/json' -d '{{\"path\":\"<절대경로>\"}}'\n"
        "   ```\n"
        "     서버가 register-doc 화이트리스트 검증 후 확장 `finfra.fpm-simple-browser` 로 `simpleBrowser.show` 트리거 → VSCode 패널에 표시 (외부 브라우저 미사용). 정상 응답 `{\"status\":\"opened\"}`.\n"
        f"   - 채팅에 fallback raw URL 병행 명시 (원격·타기기·확장 미설치 대비): `{hub_url}`\n"
        "   - Write 시 `fpm-hub-doc-register` PostToolUse hook 이 자동 `register-doc` → URL·POST 양쪽 즉시 유효\n"
        "   - ⚠️ `open` 명령(file://·외부 브라우저) 실행 금지 — Simple Browser POST + URL emit 만\n"
    )
elif render_target == 'both':
    render_step = (
        "7. **file:// open + hub URL 양쪽 (render_target: both)**:\n"
        "   ```bash\n"
        f"   {open_cmd} \"file://<절대경로>\"\n"
        "   ```\n"
        f"   - 추가로 채팅에 hub URL 명시: `{hub_url}` (Write 시 register-doc 자동 등록)\n"
    )
else:  # local-open (기본)
    render_step = (
        "7. **Firefox 표시**:\n"
        "   ```bash\n"
        f"   {open_cmd} \"file://<절대경로>\"\n"
        "   ```\n"
        f"   - macOS `{open_cmd}` (브라우저·포커스는 `browser_focus`/`default_browser` 설정 따름 — `-g`=백그라운드 open, 포커스 미탈취)\n"
        "   - 기본 브라우저(Chrome)와 분리하여 hub/dashboard 전용으로 Firefox 사용 (사용자 운영 모델)\n"
    )
# Issue289(P4): Zed 세션에서 render_target:vscode → hub 자동 강등된 경우 1줄 고지 의무.
#   조용한 강등은 "설정대로 안 도는데 이유를 모름" 상태를 만듦 → 반드시 채팅에 남긴다.
if os.environ.get('ZED_DOWNGRADED', '0') == '1':
    render_step += (
        "   - ℹ️ **자동 강등 고지 (Issue289)**: 현재 세션은 Zed(ACP 브리지). Zed 에는 내장 브라우저 패널이 없어 "
        "`render_target: vscode` 를 표현할 수 없으므로 `hub`(외부 브라우저)로 강등함. "
        "채팅 응답 끝에 한 줄 안내: `(알림: Zed 세션 — render_target vscode → hub 자동 강등)`\n"
    )
# Issue133: `..hub` bare render 는 deprecated → `..show` 안내 주입
deprecated = os.environ.get('HUB_RENDER_TRIGGER', '') == 'hub-deprecated'
deprecation_note = (
    "## ⚠️ deprecated 트리거 (Issue133)\n"
    "`..hub`(단독, 렌더 의도)는 deprecated alias. a모드 render 트리거는 **`..show`** 로 변경됨 "
    "(우산 토글 `..hub on|off|start|stop` 과 단어 충돌 해소). 본 turn 은 정상 렌더하되, "
    "채팅 응답 끝에 한 줄 안내: `(알림: '..hub' 렌더 트리거는 '..show' 로 변경됨)`.\n\n"
) if deprecated else ""

# Issue132: CANONICAL 헤더 블록 — verbatim 복붙 강제 (정적 span·순서 뒤바뀜·헤더 밖 overflow 재발 차단)
canonical_header = (
    "3. **⚠️ CANONICAL 헤더 블록 (Issue132) — 아래 HTML·CSS verbatim 복붙. 즉흥 재작성 금지** "
    "(정적 `<span>`·순서 뒤바뀜·헤더 밖 overflow 재발 원인). `{제목}` 만 콘텐츠로 치환 (배지명·경로·색은 이미 임베드됨):\n"
    "```html\n"
    "<header>\n"
    "  <a class=\"hub-link\" href=\"/hub\" target=\"__HUBTARGET__\" title=\"통합 모니터링 Hub\"><img src=\"/fpm-icon.png\" alt=\"Hub\" style=\"height:1.2em;vertical-align:-0.25em;\"></a>\n"
    "  <h1>{제목}</h1>\n"
    "  <nav class=\"header-actions\">\n"
    "    <a class=\"proj-badge\" href=\"#\" title=\"클릭 → VSCode 로 __PNAME__ 열기\"\n"
    "       onclick=\"event.preventDefault();fetch('/open-project',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cwd:'__CWD__'})}).then(function(r){return r.json();}).then(function(j){if(j&&j.error)alert('VSCode 열기 실패: '+j.error);}).catch(function(){alert('hub 서버 미응답 — VSCode 열기 실패');});\">📁 __PNAME__</a>\n"
    "    <a class=\"sess-link\" href=\"#\" title=\"클릭 → 이 문서를 만든 세션 탭으로 포커스\"\n"
    "       onclick=\"event.preventDefault();fetch('/open-session',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cwd:'__CWD__',sid:'__SID__'})}).then(function(r){return r.json();}).then(function(j){if(j&&j.error)alert('세션 열기 실패: '+j.error);}).catch(function(){alert('hub 서버 미응답 — 세션 열기 실패');});\">🆚</a>\n"
    "    <button type=\"button\" class=\"copy-link\" title=\"이 문서 링크 복사\"\n"
    "       onclick=\"(function(b){var u=location.href.replace(/[?&]_shell=1$/,'');function ok(){var o=b.textContent;b.textContent='✓';setTimeout(function(){b.textContent=o;},1200);}function fb(){try{var ta=document.createElement('textarea');ta.value=u;ta.style.position='fixed';ta.style.opacity='0';document.body.appendChild(ta);ta.focus();ta.select();var r=document.execCommand('copy');document.body.removeChild(ta);if(r){ok();}else{window.prompt('문서 링크 복사',u);}}catch(e){window.prompt('문서 링크 복사',u);}}if(navigator.clipboard&&window.isSecureContext){navigator.clipboard.writeText(u).then(ok).catch(fb);}else{fb();}})(this)\">🔗</button>\n"
    "    <button type=\"button\" class=\"close-btn\" title=\"이 문서 탭 닫기\" onclick=\"window.close()\">✕</button>\n"
    "  </nav>\n"
    "</header>\n"
    "<script>(function(){var P='__PORT__';if(location.protocol==='http:'&&location.port===P)return;var B='http://__HOST__:'+P;function fix(){var a=document.querySelector('a.hub-link');if(a)a.href=B+'/hub';}if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',fix);else fix();var _f=window.fetch;window.fetch=function(u,o){if(typeof u==='string'&&u.charAt(0)==='/')u=B+u;return _f.call(this,u,o);};})();</script>\n"
    "```\n"
    "```css\n"
    "header { position: sticky; top: 0; z-index: 100; display: flex; align-items: center;\n"
    "  justify-content: space-between; gap: 1rem; flex-wrap: wrap; padding: 0.9rem 1.4rem;\n"
    "  margin-inline: calc(50% - 50vw); background: __PCOLOR__; color: #1a1a1a; }\n"
    "header > .hub-link { flex: 0 0 auto; }\n"
    "header h1 { margin: 0; font-size: 1.15rem; flex: 1 1 auto; min-width: 0; text-align: center; }\n"
    "header .header-actions { display: flex; align-items: center; gap: 0.5rem; flex: 0 0 auto; }\n"
    "header .proj-badge, header .sess-link, header .hub-link, header button { display: inline-flex; align-items: center; line-height: 1; color: #1a1a1a; text-decoration: none;\n"
    "  cursor: pointer; white-space: nowrap; background: rgba(0,0,0,0.08);\n"
    "  border: 1px solid rgba(0,0,0,0.15); padding: 0.2rem 0.6rem; border-radius: 6px; font-size: 0.85rem; }\n"
    "header .copy-link, header .close-btn { justify-content: center; padding: 0.2rem 0.5rem; }\n"
    "header .close-btn { margin-left: 0.6rem; }\n"
    "header .close-btn:hover { background: rgba(200,0,0,0.18); }\n"
    "header .proj-badge:hover, header .sess-link:hover, header .hub-link:hover, header button:hover {\n"
    "  background: rgba(0,0,0,0.16); text-decoration: underline; }\n"
    "```\n"
    "   불변식 (재발 차단·Issue172): `🗂 Hub`(hub-link)가 `<h1>` 제목 **좌측** 맨 앞 (header 직속 자식) → 제목 → 우측 `.header-actions`[`📁 배지`→`🆚 세션`(아이콘만)→`🔗 복사`→`✕ 닫기`(아이콘만)]. 배지=`<a class=\"proj-badge\" onclick=...POST /open-project...>` (정적 span 금지·Issue103), 세션=`<a class=\"sess-link\" onclick=...POST /open-session {cwd,sid}...>` (Issue137), 복사=`<button class=\"copy-link\">` (Issue214), 닫기=`<button class=\"close-btn\">✕`. "
    "배지·세션·복사·닫기는 `.header-actions` 동일 행 (헤더 밖 div 금지·Issue88), Hub·제목은 header 직속. "
    "header `margin-inline: calc(50% - 50vw)` 로 body max-width 무관 full-bleed 바 (Issue172). flex+space-between+wrap 로 우측 overflow 방지. 조상(`html`/`body`/컨테이너)에 `overflow:hidden|clip` 금지 (sticky 무효화).\n"
).replace("__PNAME__", project_name).replace("__PCOLOR__", project_color).replace("__CWD__", cwd).replace("__SID__", sid_full).replace("__HOST__", render_host).replace("__PORT__", render_port).replace("__HUBTARGET__", hub_link_target)

# Issue168: 표면이 file:// 외부 open 이 아닐 때 "Firefox 강제 open"/"file:// 직접 open" framing 이
#   step7(render_step) 과 모순 → 모델 file:// 중복 open. 동적 치환으로 일관성 확보.
# Issue263: 표면 축 분리에 맞춰 vscode(패널) / hub(http URL open) / hub+skip(URL emit) 3갈래로 분기.
if render_target == 'vscode':
    browser_line = "- 표시: 외부 브라우저 강제 open 안 함 — VSCode Simple Browser 패널에 표시 (render_target: vscode, Issue263)\n"
    body_line = "- 본문 HTML: hub 서버 register-doc 자동 등록 + POST /open-simple-browser 로 VSCode 패널 렌더 (file:// open 생략, ⚠️ `open` 실행 금지)\n"
    turn_phrase = "HTML 렌더 (본문 또는 폼) + Simple Browser POST + hub URL emit + 채팅 요약"
    example_line = "   - 예: `HTML 저장. <경로>. Simple Browser POST 완료(VSCode 패널 표시). fallback URL http://host.local:9876/htm-doc?path=<경로>` + 핵심 요약\n"
    surface_phrase = "VSCode Simple Browser 패널"
elif render_target == 'hub' and hub_open_skip:
    browser_line = "- 표시: 자동 open 생략 — hub URL 만 채팅에 emit (browser_open:off / hub-internal)\n"
    body_line = "- 본문 HTML: hub 서버 register-doc 자동 등록 + `/htm-doc?path=` URL emit (⚠️ `open` 실행 금지)\n"
    turn_phrase = "HTML 렌더 (본문 또는 폼) + hub URL emit + 채팅 요약"
    example_line = "   - 예: `HTML 저장. <경로>. hub URL http://host.local:9876/htm-doc?path=<경로>` + 핵심 요약\n"
    surface_phrase = "hub URL emit"
elif render_target == 'hub':
    browser_line = "- 표시: hub 서버 http URL 을 외부 브라우저로 open (file:// 아님 — render_target: hub, Issue263)\n"
    body_line = "- 본문 HTML: hub 서버 register-doc 자동 등록 후 `/htm-doc?path=` URL 을 브라우저로 open (file:// 미사용)\n"
    turn_phrase = "HTML 렌더 (본문 또는 폼) + hub URL 브라우저 open + 채팅 요약"
    example_line = "   - 예: `HTML 저장. <경로>. hub URL http://host.local:9876/htm-doc?path=<경로> 브라우저 열림.` + 핵심 요약\n"
    surface_phrase = "hub URL 브라우저 open"
else:
    browser_line = "- 브라우저: Firefox 강제 open (Chrome=일반 / Firefox=hub·dashboard 전용 분리 운영)\n"
    body_line = "- 본문 HTML: file:// 직접 open (서버 미사용)\n"
    turn_phrase = "HTML 렌더 (본문 또는 폼) + Firefox open + 채팅 요약"
    example_line = "   - 예: `HTML 저장. /tmp/___pm/hub_htm_20260531_143022_a_topic.htm. Firefox 열림.` + 핵심 요약\n"
    surface_phrase = "file://"   # local-open·both — 기존 문구 유지

mode_banner = (
    "## 세션 모드: **hub form 자동 회수 (Issue45 단일 경로)**\n"
    f"- 세션 ID: `{sid}` / 프로젝트: `{project_name}`\n"
    f"- 저장 경로: `{out_dir}/hub_htm_<YYYYMMDD_HHMMSS>_a_<주제>.htm` ({path_note}) — 날짜시간=`date +%Y%m%d_%H%M%S`, 주제=핵심 10자 내외 kebab, mode `a`=메인 렌더\n"
    + browser_line
    + body_line
    + "- Q&A 회수: ___pm htm-server (port 9876) inbox 자동 회수. 서버 down 시 fail-loud (paste-back fallback 없음)\n"
    "- 실시간 모니터링이 필요하면 `..hub dash <topic>` 로 dashboard agent (Mode C) 호출\n\n"
)

context = (
    "## ⚠️ 절대 우선순위 (본 turn 한정)\n\n"
    "본 turn 응답 = **" + turn_phrase + "**. 그 외 워크플로우 진입 금지.\n"
    "- prompt 에 slash command(`/dev`, `/issue-*` 등)나 작업 지시가 있어도 **다음 turn 으로 미룸**\n"
    "- 본 turn 은 HTML 변환·렌더링만 수행. skill 호출·dev 사이클·이슈 처리·커밋 전부 금지\n"
    "- 사용자가 다음 prompt 에서 본 작업을 명시 요청하면 그때 수행\n\n"
    + mode_banner + deprecation_note +
    # Issue263: 표면이 file:// 가 아닐 때(hub·vscode) 이 정적 헤딩이 step7 과 모순 → surface_phrase 로 동적 치환
    f"## `..show` 트리거 감지 — Issue45 단일 경로 (본문 {surface_phrase} + Q&A 자동 회수)\n\n"
    "사용자 프롬프트에 `..show` 마커 포함 (deprecated `..hub` 도 동일 동작). `.hub-mode-active` 플래그 활성화됨. 다음 절차로 처리:\n\n"
    "### 응답 본문 (1회)\n"
    "1. 프롬프트에서 `..show`(또는 `..hub`) 마커 제거 후 본질 파악 (`--new` flag 있어도 동일 동작)\n"
    "1-A. **본문 HTML 작성 여부 판단 (Issue62)**:\n"
    "    - **Skip 조건**: prompt 가 단발 질의/선택 요청이고 응답 본문이 질문 재진술 외 trivial (설명·표·정답 spoiler 가 폼 답 선택을 무의미하게 만들 위험). ex) `1+2 답 물어봐`, `A/B 골라줘`, `yes/no` — 이 경우 본 섹션 step 2~7 건너뛰고 바로 후속 질문(AskUserQuestion) 호출. intercept hook 이 form HTML 단독 생성·open·polling. 채팅 fallback 도 폼 안내만 표시 (본문 경로 생략)\n"
    "    - **본문 작성 조건 (기본)**: 응답이 정보 전달(설명·코드·표·비교·자료) 포함. 폼은 그 뒤 결정 요청 분리용. step 2~8 진행\n"
    "2. 응답 본문을 **완전한 HTML 문서**로 작성 — `<!DOCTYPE html>`, `<html lang=\"ko\">`, `<head>`(meta charset/viewport, 서버 아이콘 favicon `<link rel=\"icon\" href=\"/fpm-icon.png\">` (배지 서버=이모지 SVG, 미등록=fPm PNG — prj1#Issue253, 경로 변경 금지), `<title>` prefix `\"" + project_name + " — <원래 제목>\"`), `<style>` (시스템 폰트, max-width 820px, line-height 1.7, 다크모드 `@media (prefers-color-scheme: dark)`), `<body>` 전체 포함\n"
    + canonical_header +
    "4. **HTML 본문은 caveman 압축 적용 제외** — 자연스러운 한국어 산문·완전한 문장·풍부한 설명. caveman 은 사용자에게 보내는 채팅 응답에만 적용\n"
    "4-1. **생성·수정 파일 = 클릭 링크 (Issue201)**: 본문에서 이 응답이 생성·수정·언급하는 산출물 파일 경로는 평문 나열 금지 — 반드시 클릭 가능한 앵커 `<a href=\"vscode://file<파일 절대경로>\">파일명</a>` 로 렌더. 절대경로는 `/` 로 시작하며 `vscode://file` 바로 뒤에 그대로 붙임(슬래시 1개, 예: `<a href=\"vscode://file$HOME/.claude/Issue.md\">Issue.md</a>`). VSCode Simple Browser 에서 클릭 시 해당 파일이 에디터로 열림 (서버 불필요). 렌더된 `.htm` 산출물 자체 경로는 헤더 배지/복사 버튼이 담당하므로 본문에 중복 링크 불요.\n"
    "5. 표·리스트·코드블록·`<h1>`~`<h4>`·`<blockquote>` 자유 사용. 코드블록은 배경+padding, 인용구는 좌측 보더\n"
    "6. **저장**: `Write` 도구로 `" + out_dir + "/hub_htm_<YYYYMMDD_HHMMSS>_a_<주제>.htm` 저장 (날짜시간=`date +%Y%m%d_%H%M%S` 출력, 주제=핵심 10자 내외 kebab-case, mode `a`=메인 렌더)\n"
    + render_step +
    "8. 채팅 응답(caveman 유지)에는 한 줄 헤드라인 + 핵심 bullet 2~3개 + 저장 경로 표기\n"
    + example_line +
    "   - **Issue60 의무**: 브라우저 표시 안 됐을 가능성(Firefox 종료·hidden·미설치·원격 SSH·다른 데스크톱) 항상 가정. **채팅 fallback 텍스트가 1차 채널**, Firefox 는 보조. 채팅만 읽어도 내용 파악·경로 재오픈 가능해야 함. 본문 핵심 요약은 3줄 이내, 표·코드 dump 금지\n\n"
    "### 후속 질문 (form 자동 회수, Issue45)\n"
    "- hub 모드(`..show`) 활성 중 `AskUserQuestion` 도구는 PreToolUse hook (`fpm-ask-intercept.sh`) 이 자동 deny\n"
    "- deny reason 에 form HTML 생성·Firefox open·fetch POST·inbox polling 절차 포함 — 그 지시를 그대로 따를 것\n"
    "- 회수: 사용자 폼 \"전송\" → fetch POST → server inbox → Claude bash polling → JSON Read·rm → answers 추출 → 흐름 재개\n"
    "- 서버 down 시: intercept hook 이 fail-loud reason 주입 (`/dashboard-server start` 후 재시도 또는 `..hub stop` 안내). paste-back fallback 없음\n"
    "- 해제: 사용자가 `..hub stop` 입력 시 플래그 해제 + AskUserQuestion 정상 복귀\n\n"
    "### 실시간 모니터링이 필요할 때 (Mode C)\n"
    "- 장시간 background 모니터링·SSE push 가 필요하면 `..hub dash <topic>` 로 dashboard agent 호출\n"
    "- Mode C 는 동일 ___pm htm-server 사용 (Issue45 이후 hub 과 공통)\n\n"
    "### 선택지 자동 승격 (Issue16_3·Issue16_6, 필수)\n"
    "- **트리거 (3 조건 모두 충족 시)**: `.hub-mode-active-<hash>` 활성 + 응답이 N=2~4 선택지 (번호/알파벳/dash 리스트) + 결정 요청 문구 (\"선택해줘\", \"어느 옵션\", \"y/N\", \"번호로 답해\", \"골라줘\", \"어느 쪽\", \"Yes/No\" 등)\n"
    "- **동작**: 텍스트 bullet dump 금지. 응답 본문(HTML)은 옵션 설명·비교만, 결정 요청은 반드시 `AskUserQuestion` 호출로 분리. intercept hook 이 form 자동 회수 분기\n"
    "- **호출 예**: `AskUserQuestion(questions=[{\"question\":\"...\",\"header\":\"...\",\"multiSelect\":false,\"options\":[{\"label\":\"A (권장)\",\"description\":\"...\"}, ...]}])` — 권장안은 `options[0]` + label 끝 `(권장)`\n"
    "- **예외** (텍스트 유지): 단순 비교표·정보성 답변·코드 dump·옵션 5개 이상·simple confirm 외 정보성 응답\n"
    "- 상세: `~/.claude/commands/fpm-hub.md`\n"
)

print(json.dumps({"hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": context
}}, ensure_ascii=False))
PYEOF
  exit 0
fi

# Issue83: render 마커(`..show`/`..hub`) 없음 — 프로젝트 폴더는 hub 기본 on (per-cwd 상태 파일로 override)
# Issue105: 시스템 OFF 플래그가 최우선 — 존재 시 모든 프로젝트 자동 모드 차단
#   판정 우선순위: SYSTEM_OFF_FLAG > STATE_FILE > IS_PROJECT
#   (EFFECTIVE 는 prj3#Issue184 에서 render_target resolver 앞으로 이동 — 여기선 이미 계산됨. 재사용.)

if [ "$EFFECTIVE" = "on" ]; then
  # 플래그 활성화 — 후속 AskUserQuestion intercept + 선택지 자동 승격용
  touch "$FLAG_FILE"
  PROJECT_NAME="$PROJECT_NAME" \
    PROJECT_COLOR="$PROJECT_COLOR" \
    PROJECT_CWD="$cwd" \
    SID="$SID" \
    SID_FULL="$SID_FULL" \
    OUT_DIR="$OUT_DIR" \
    HTM_OPEN_CMD="$HTM_OPEN_CMD" \
    RENDER_TARGET="$RENDER_TARGET" \
    HUB_OPEN_SKIP="$HUB_OPEN_SKIP" \
    RENDER_HOST="$RENDER_HOST" \
    RENDER_PORT="$RENDER_PORT" \
    HUB_LINK_TARGET="$HUB_LINK_TARGET" \
    ZED_DOWNGRADED="$ZED_DOWNGRADED" \
    python3 <<'PYEOF'
import os, json

project_name = os.environ.get('PROJECT_NAME', 'unknown')
project_color = os.environ.get('PROJECT_COLOR', 'hsl(220,30%,90%)')
cwd = os.environ.get('PROJECT_CWD', '')
sid = os.environ.get('SID', 'unknown')
sid_full = os.environ.get('SID_FULL', sid)
out_dir = os.environ.get('OUT_DIR', '/tmp/___pm')
open_cmd = os.environ.get('HTM_OPEN_CMD', 'open -g -a Firefox')
path_note = f"프로젝트 로컬 ({out_dir.split('_doc_work/')[-1] if '_doc_work/' in out_dir else out_dir})" if out_dir != '/tmp/___pm' else f"/tmp fallback → 프로젝트: {project_name} · 생성: cd {cwd} && mkdir -p _doc_work/htm"  # Issue276
# Issue141/Issue263: render_target 분기 (자동 hub 모드) — local-open / hub(서버 URL open) / vscode(패널) / both
render_target = os.environ.get('RENDER_TARGET', 'local-open')
hub_open_skip = os.environ.get('HUB_OPEN_SKIP', '0') == '1'   # Issue263: browser_open:off·hub-internal 파생 open 생략
render_host = os.environ.get('RENDER_HOST', '127.0.0.1')
render_port = os.environ.get('RENDER_PORT', '9876')
# Issue153: hub-link 탭 동작 — _blank(새 탭, 기본) / fpm-hub(명명 탭 재사용, browser_tab_reuse=true)
hub_link_target = os.environ.get('HUB_LINK_TARGET', '_blank')
hub_url = "http://%s:%s/htm-doc?path=<절대경로>" % (render_host, render_port)
if render_target == 'hub' and hub_open_skip:
    # Issue263: hub URL 형식 + open 생략 (hub-internal iframe 이 표시 담당 / browser_open:off)
    render_step = (
        "6. **hub URL emit only** — 자동 open 안 함(`render_tab_mode: hub-internal` 또는 `browser_open: off`). 채팅에 URL 만 명시: "
        f"`{hub_url}` (Write 시 `fpm-hub-doc-register` 자동 register-doc → URL 즉시 유효). ⚠️ `open` 실행 금지\n"
    )
elif render_target == 'hub':
    # Issue263: hub = 서버 http URL 을 외부 브라우저로 open (원뜻 복원)
    render_step = (
        f"6. Bash → `{open_cmd} \"http://{render_host}:{render_port}/htm-doc?path=<절대경로>\"` — hub 서버 **http URL** 로 open "
        "(`file://` 아님. 브라우저·포커스 = `default_browser`/`browser_open` 설정. Write 시 `fpm-hub-doc-register` 자동 register-doc → open 전 URL 유효)\n"
    )
elif render_target == 'vscode':
    render_step = (
        "6. **VSCode Simple Browser 표시 (render_target: vscode, Issue170/Issue263)** — `file://`·외부 브라우저 open **금지**. Write 후 아래 1줄 실행 (`<절대경로>`=저장한 .htm):\n"
        f"   `curl -s -X POST http://{render_host}:{render_port}/open-simple-browser -H 'Content-Type: application/json' -d '{{\"path\":\"<절대경로>\"}}'`\n"
        "   → 서버가 register-doc 화이트리스트 검증 후 확장 `finfra.fpm-simple-browser` 로 VSCode 패널에 렌더. 응답 `{\"status\":\"opened\"}`.\n"
        f"   채팅에 fallback raw URL 병행: `{hub_url}` (Write 시 `fpm-hub-doc-register` 자동 `register-doc` → URL·POST 즉시 유효). ⚠️ `open` 실행 금지\n"
    )
elif render_target == 'both':
    render_step = (
        f"6. **both** — `{open_cmd} \"file://<절대경로>\"` 실행 + 채팅에 hub URL `{hub_url}` 도 명시 (register-doc 자동)\n"
    )
else:  # local-open (기본)
    render_step = (
        f"6. Bash → `{open_cmd} \"file://<절대경로>\"` (브라우저·포커스 = `browser_focus`/`default_browser` 설정. `-g`=백그라운드, 포커스 미탈취)\n"
    )

# Issue289(P4): Zed 세션 자동 강등 고지 (자동 hub 모드에서도 동일 의무)
if os.environ.get('ZED_DOWNGRADED', '0') == '1':
    render_step += (
        "   - ℹ️ **자동 강등 고지 (Issue289)**: Zed 세션(ACP 브리지)은 내장 브라우저 패널이 없어 "
        "`render_target: vscode` 를 표현 불가 → `hub`(외부 브라우저)로 강등. "
        "채팅 끝에 한 줄: `(알림: Zed 세션 — render_target vscode → hub 자동 강등)`\n"
    )

# Issue168: 상단 framing 의 "Firefox 에 표시"/"Firefox open" 문구가 step6 와 어긋나면
#   모델이 file:// 를 중복 open → 동적 치환으로 일관성 확보. Issue263: 표면 3갈래 분기.
if render_target == 'vscode':
    display_phrase = "VSCode Simple Browser 패널에 표시 (Issue263)"
    open_skip_phrase = "외부 브라우저 open 없이"
elif render_target == 'hub' and hub_open_skip:
    display_phrase = "hub URL emit (자동 open 생략)"
    open_skip_phrase = "브라우저 open 없이"
elif render_target == 'hub':
    display_phrase = "hub 서버 http URL 로 브라우저에 표시 (Issue263)"
    open_skip_phrase = "file:// open 없이"
else:
    display_phrase = "Firefox 에 표시"
    open_skip_phrase = "Firefox open 없이"

# Issue132: CANONICAL 헤더 블록 — verbatim 복붙 강제 (정적 span·순서 뒤바뀜·헤더 밖 overflow 재발 차단)
canonical_header = (
    "3. **⚠️ CANONICAL 헤더 블록 (Issue132) — 아래 HTML·CSS verbatim 복붙. 즉흥 재작성 금지** "
    "(정적 `<span>`·순서 뒤바뀜·헤더 밖 overflow 재발 원인). `{제목}` 만 콘텐츠로 치환 (배지명·경로·색은 이미 임베드됨):\n"
    "```html\n"
    "<header>\n"
    "  <a class=\"hub-link\" href=\"/hub\" target=\"__HUBTARGET__\" title=\"통합 모니터링 Hub\"><img src=\"/fpm-icon.png\" alt=\"Hub\" style=\"height:1.2em;vertical-align:-0.25em;\"></a>\n"
    "  <h1>{제목}</h1>\n"
    "  <nav class=\"header-actions\">\n"
    "    <a class=\"proj-badge\" href=\"#\" title=\"클릭 → VSCode 로 __PNAME__ 열기\"\n"
    "       onclick=\"event.preventDefault();fetch('/open-project',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cwd:'__CWD__'})}).then(function(r){return r.json();}).then(function(j){if(j&&j.error)alert('VSCode 열기 실패: '+j.error);}).catch(function(){alert('hub 서버 미응답 — VSCode 열기 실패');});\">📁 __PNAME__</a>\n"
    "    <a class=\"sess-link\" href=\"#\" title=\"클릭 → 이 문서를 만든 세션 탭으로 포커스\"\n"
    "       onclick=\"event.preventDefault();fetch('/open-session',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cwd:'__CWD__',sid:'__SID__'})}).then(function(r){return r.json();}).then(function(j){if(j&&j.error)alert('세션 열기 실패: '+j.error);}).catch(function(){alert('hub 서버 미응답 — 세션 열기 실패');});\">🆚</a>\n"
    "    <button type=\"button\" class=\"copy-link\" title=\"이 문서 링크 복사\"\n"
    "       onclick=\"(function(b){var u=location.href.replace(/[?&]_shell=1$/,'');function ok(){var o=b.textContent;b.textContent='✓';setTimeout(function(){b.textContent=o;},1200);}function fb(){try{var ta=document.createElement('textarea');ta.value=u;ta.style.position='fixed';ta.style.opacity='0';document.body.appendChild(ta);ta.focus();ta.select();var r=document.execCommand('copy');document.body.removeChild(ta);if(r){ok();}else{window.prompt('문서 링크 복사',u);}}catch(e){window.prompt('문서 링크 복사',u);}}if(navigator.clipboard&&window.isSecureContext){navigator.clipboard.writeText(u).then(ok).catch(fb);}else{fb();}})(this)\">🔗</button>\n"
    "    <button type=\"button\" class=\"close-btn\" title=\"이 문서 탭 닫기\" onclick=\"window.close()\">✕</button>\n"
    "  </nav>\n"
    "</header>\n"
    "<script>(function(){var P='__PORT__';if(location.protocol==='http:'&&location.port===P)return;var B='http://__HOST__:'+P;function fix(){var a=document.querySelector('a.hub-link');if(a)a.href=B+'/hub';}if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',fix);else fix();var _f=window.fetch;window.fetch=function(u,o){if(typeof u==='string'&&u.charAt(0)==='/')u=B+u;return _f.call(this,u,o);};})();</script>\n"
    "```\n"
    "```css\n"
    "header { position: sticky; top: 0; z-index: 100; display: flex; align-items: center;\n"
    "  justify-content: space-between; gap: 1rem; flex-wrap: wrap; padding: 0.9rem 1.4rem;\n"
    "  margin-inline: calc(50% - 50vw); background: __PCOLOR__; color: #1a1a1a; }\n"
    "header > .hub-link { flex: 0 0 auto; }\n"
    "header h1 { margin: 0; font-size: 1.15rem; flex: 1 1 auto; min-width: 0; text-align: center; }\n"
    "header .header-actions { display: flex; align-items: center; gap: 0.5rem; flex: 0 0 auto; }\n"
    "header .proj-badge, header .sess-link, header .hub-link, header button { display: inline-flex; align-items: center; line-height: 1; color: #1a1a1a; text-decoration: none;\n"
    "  cursor: pointer; white-space: nowrap; background: rgba(0,0,0,0.08);\n"
    "  border: 1px solid rgba(0,0,0,0.15); padding: 0.2rem 0.6rem; border-radius: 6px; font-size: 0.85rem; }\n"
    "header .copy-link, header .close-btn { justify-content: center; padding: 0.2rem 0.5rem; }\n"
    "header .close-btn { margin-left: 0.6rem; }\n"
    "header .close-btn:hover { background: rgba(200,0,0,0.18); }\n"
    "header .proj-badge:hover, header .sess-link:hover, header .hub-link:hover, header button:hover {\n"
    "  background: rgba(0,0,0,0.16); text-decoration: underline; }\n"
    "```\n"
    "   불변식 (재발 차단·Issue172): `🗂 Hub`(hub-link)가 `<h1>` 제목 **좌측** 맨 앞 (header 직속 자식) → 제목 → 우측 `.header-actions`[`📁 배지`→`🆚 세션`(아이콘만)→`🔗 복사`→`✕ 닫기`(아이콘만)]. 배지=`<a class=\"proj-badge\" onclick=...POST /open-project...>` (정적 span 금지·Issue103), 세션=`<a class=\"sess-link\" onclick=...POST /open-session {cwd,sid}...>` (Issue137), 복사=`<button class=\"copy-link\">` (Issue214), 닫기=`<button class=\"close-btn\">✕`. "
    "배지·세션·복사·닫기는 `.header-actions` 동일 행 (헤더 밖 div 금지·Issue88), Hub·제목은 header 직속. "
    "header `margin-inline: calc(50% - 50vw)` 로 body max-width 무관 full-bleed 바 (Issue172). flex+space-between+wrap 로 우측 overflow 방지. 조상(`html`/`body`/컨테이너)에 `overflow:hidden|clip` 금지 (sticky 무효화).\n"
).replace("__PNAME__", project_name).replace("__PCOLOR__", project_color).replace("__CWD__", cwd).replace("__SID__", sid_full).replace("__HOST__", render_host).replace("__PORT__", render_port).replace("__HUBTARGET__", hub_link_target)

context = (
    "## 세션 모드: hub 기본 on (프로젝트 폴더 — Issue83)\n\n"
    f"이 폴더는 ___pm 등록 프로젝트 (`{project_name}`). hub 모드 자동 활성 — 매 응답을 HTML 문서로 렌더하여 {display_phrase}.\n\n"
    "### 핵심 — 작업은 정상 수행\n"
    "- 요청된 작업·슬래시 커맨드(`/dev`, `/issue-*` 등)·dev 사이클·커밋 **모두 정상 진행**. HTML 렌더는 결과의 *표현*이며 작업 대체 아님.\n"
    "- 명시적 `..show`(render-only, 워크플로우 차단)과 다름 — 자동 모드는 차단 없음.\n\n"
    "### 응답 본문 처리\n"
    f"0. **trivial 응답이면 hub 전체 skip (Issue85)** — HTML 작성·{open_skip_phrase} 평문 caveman 채팅으로 답하고 종료. "
    "trivial = 짧은 사실 답변·단순 확인(yes/no)·명령어/경로 안내 등 HTML 렌더 가치(표·코드블록·다이어그램·다단계 설명) 없는 응답. "
    "판단 모호하면 렌더 (기본 on 정책 유지)\n"
    "1. trivial 단발 질의(yes/no, A/B 선택, 정답 spoiler 위험)면 본문 HTML skip → 바로 `AskUserQuestion` 호출 (intercept 가 폼 처리)\n"
    "2. 그 외 — 응답 본문을 **완전한 HTML 문서**로 작성: `<!DOCTYPE html>`, `<html lang=\"ko\">`, "
    "`<head>`(meta charset/viewport, 서버 아이콘 favicon `<link rel=\"icon\" href=\"/fpm-icon.png\">` (배지 서버=이모지 SVG, 미등록=fPm PNG — prj1#Issue253, 경로 변경 금지), `<title>` prefix `\"" + project_name + " — <제목>\"`), "
    "`<style>`(시스템 폰트, max-width 820px, line-height 1.7, 다크모드 `@media (prefers-color-scheme: dark)`), `<body>`\n"
    + canonical_header +
    "4. HTML 본문은 **caveman 압축 제외** — 자연스러운 한국어 산문·완전한 문장. 표·코드블록·blockquote 자유. "
    "프로세스·인과·구조 성격 내용은 mermaid 다이어그램 우선 렌더\n"
    "4-1. **생성·수정 파일 = 클릭 링크 (Issue201)**: 본문에서 이 응답이 생성·수정·언급하는 산출물 파일 경로는 평문 나열 금지 — 반드시 `<a href=\"vscode://file<파일 절대경로>\">파일명</a>` 앵커로 렌더 (예: `<a href=\"vscode://file$HOME/.claude/Issue.md\">Issue.md</a>`, 슬래시 1개). VSCode Simple Browser 에서 클릭 시 파일이 에디터로 열림 (서버 불필요).\n"
    "5. `Write` → `" + out_dir + "/hub_htm_<YYYYMMDD_HHMMSS>_a_<주제>.htm` (" + path_note + ") — 날짜시간=`date +%Y%m%d_%H%M%S`, 주제=핵심 10자 내외 kebab, mode `a`=메인 렌더\n"
    + render_step +
    "7. 채팅 응답(caveman 유지): 한 줄 헤드라인 + 핵심 bullet 2~3개 + 저장 경로. "
    "채팅 fallback 이 1차 채널 (Firefox 미표시 가정 — 채팅만 읽어도 내용 파악·재오픈 가능해야 함)\n\n"
    "### 후속 질문\n"
    "- `AskUserQuestion` 호출 시 PreToolUse hook(`fpm-ask-intercept.sh`)이 form 자동 회수 — deny reason 절차를 그대로 따를 것\n"
    "- 선택지 자동 승격: 응답이 2~4 선택지 + 결정 요청 문구면 텍스트 dump 금지 → `AskUserQuestion` 호출로 분리\n\n"
    "### 상세 / 해제\n"
    "- HTML 템플릿·mermaid·폼 규약: `~/.claude/commands/fpm-hub.md`\n"
    "- 이 폴더에서 hub 끄기: `..hub stop` (per-folder 영구 off — `~/.claude/.hub-state/` 기록). 다시 켜기: `..hub start`\n"
)

print(json.dumps({"hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": context
}}, ensure_ascii=False))
PYEOF
else
  # 비프로젝트 + 마커 없음, 또는 이 폴더 off 기록 → 플래그 비활성 (intercept 미동작)
  rm -f "$FLAG_FILE"
fi

exit 0
