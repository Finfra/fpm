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
#   - .hub-mode-active-<hash> 플래그 없음 or effective=off → 통과 (exit 0) [Issue283]
#   - 플래그 있음 + healthz 200 + /register OK → deny + form 자동 회수 지시 주입
#   - 플래그 있음 + 서버 실패                 → deny + 서버 재시작 안내 + 종료 옵션 제시
#   - Mode C(Live Dashboard) 는 본 hook 영향 받지 않음 (별도 dashboard agent)
#
# Issue126 (2026-06-03): b모드 명시 트리거 `..ask` 신설. `..ask` 는 fpm-hub-trigger.sh 에서
#   .hub-mode-active-<hash> 플래그를 touch 하므로, 본 hook 은 트리거 종류(자동 모드 / `..show` / `..ask`)와
#   무관하게 동일 form 자동 회수 경로를 재사용함 (플래그 기반 단일 진입 — 별도 분기 불필요).
#   Issue133 (2026-06-03): a모드 render 트리거 `..hub`→`..show` rename (토글 `..hub stop` 등은 보존).
#
# 이전 이력:
#   - Issue37: ___pm 서버 의존 분리, Mode A paste-back 도입
#   - Issue38: 서버 healthz 기반 Mode B 자동 회수 추가 (옵셔널)
#   - Issue45: Mode A 제거, 서버 가정 단일화

set -u

. "$HOME/.claude/hooks/hub-scope.sh"
. "$HOME/.claude/hooks/lib/ask-common.sh"   # Issue424_2: 공용 컨텍스트 5블록 (SID·이름/색·OUT_DIR·서버·브라우저)

input=$(cat)

# Issue360_4: cwd·session_id 파싱을 판정 단일 지점 hook-input.sh 로 위임(jq 1회, 3.7ms).
#   종전엔 python3 를 cwd·session_id 각각 기동해 no-op 경로에서만 프로세스 2개를 태웠다.
. "$HOME/.claude/hooks/hook-input.sh"
hook_input_parse "$input"
cwd="$HOOK_CWD"

# Issue283: cwd 스코프 플래그 + effective 재판정 2중 게이트.
#   (1) 플래그는 `.hub-mode-active-<md5(cwd)[:8]>` — 타 세션(hub on 프로젝트)이 켠 플래그를 주워
#       off 프로젝트에서 form 이 뜨던 누수 차단.
#   (2) 플래그가 stale 하게 남아도 SYSTEM_OFF > .hub-state/<hash> > IS_PROJECT 판정이 off 면 통과.
#
# Issue360_4: 게이트 **양쪽 분기를 한 hook 이 소유**한다. on → 폼 인터셉트(아래 본문),
#   off → "응답 대기" 음성(_ask_say). 종전엔 off 분기가 fpm-ask-say.sh 라는 별도 배선이라
#   같은 판정식이 두 파일에 복제돼 있었고, 그 복제가 갈라진 것이 Issue359 의 원인이었다.
#   합쳐 두면 갈라짐이 구조적으로 불가능하다(hook-rules 규칙5 — 판정은 단일 지점에서).
_ask_say() {
  # project-name.sh·hook-say.sh 의 프로젝트 판정은 둘 다 PWD 기준이다. stdin 으로 받은 cwd 가
  # 있으면 그쪽으로 맞춰 준다 — 이름과 카테고리 오버라이드가 같은 기준으로 해석되게.
  [ -n "$cwd" ] && [ -d "$cwd" ] && cd "$cwd" 2>/dev/null
  # 수면 모드·카테고리 off 게이트는 hook-say.sh 가 자체 처리한다.
  "$HOME/.claude/hooks/hook-say.sh" waiting_ask "$("$HOME/.bin/project-name.sh" 2>/dev/null)에서 응답 대기"
  exit 0
}

FLAG_MODE=$(hub_flag_file "$cwd")
if [ ! -f "$FLAG_MODE" ]; then
  _ask_say
fi
if [ "$(hub_effective "$cwd")" = "off" ]; then
  _ask_say
fi

# Issue360_4: 위 hook_input_parse 가 이미 뽑아 둔 값을 재사용(python3 재기동 제거).
session_id="$HOOK_SESSION_ID"

ask_ctx_sid "$session_id" "$cwd"

# Issue157: 이름·색 산출 — ask-common.sh (구판 .vscode walk-up. hub-trigger 와의 divergence 는 lib 헤더 참조)
ask_ctx_project_meta "$cwd"

# OUT_DIR (Issue289) — ask-common.sh (활성 htm/ → z_htm/ → 신규 → /tmp)
ask_ctx_out_dir "$cwd"

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

# Issue45: ___pm htm-server 가용성 판정 — ask-common.sh (실패 시 아래 fail-loud)
ask_ctx_server "$cwd"

# Issue45: 서버 실패 시 fail-loud — paste-back fallback 없음
if [ -z "$SERVER_TOKEN" ] || [ -z "$CWD_HASH" ] || [ -z "$INBOX_DIR" ]; then
  # Issue424_2: 구분자 인용 + env 주입 — 미인용 heredoc 은 백틱이 명령 치환으로 실행되는
  #   취약 패턴이다(marker-detect 에서 실발생 — 이스케이프 누락 시 안내 명령어가 증발).
  #   여기는 이스케이프로 버티고 있었지만 같은 병의 예방 차원에서 패턴 자체를 없앤다.
  HEALTH="$health" python3 <<'PYEOF'
import json, os
health = os.environ.get('HEALTH', '')
reason = (
    "## hub Mode 활성이나 ___pm htm-server 미가용\n\n"
    f"healthz={'200' if health == '200' else health} / register 실패. "
    "Mode A paste-back fallback 은 Issue45(2026-05-19) 에서 제거됨. "
    "form 자동 회수 단일 경로만 지원.\n\n"
    "### 조치 (사용자 선택)\n"
    "1. **서버 시작 후 재시도**: `/dashboard-server start` 실행 → 본 질문 재호출\n"
    "2. **hub 모드 해제**: `..hub stop` 입력 → AskUserQuestion 채팅 UI 로 정상 복귀\n\n"
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

# Issue130/173: 브라우저 open 커맨드 — ask-common.sh
ask_ctx_browser

# Issue172: b모드 폼도 hub 서버 경유(:9876)로 open — file:// 직접 open 폐기.
#   원인(이미지1): file:// 은 register-doc 미경유 → 원격/타기기 단절 + /tmp 경로.
#   폼 Write 시 fpm-hub-doc-register(Issue80) 가 mode b 도 자동 register-doc → /htm-doc?path= 즉시 유효.
#   → 폼을 :9876 /htm-doc URL 로 open (아래 hub_doc_url).
# Issue153/171 정합: 렌더(..show·..ask)는 항상 새 탭 — reuse helper 미사용(렌더 plain open/open -g).
#   browser_tab_reuse 는 hub-link target 분기에만 사용 (true→fpm-hub 명명탭 재사용 / false→_blank 새 탭).
#   (구 Issue172 reuse helper 경로 제거: /hub + 모든 htm-doc 폼을 한 탭에 collapse 했음 — hub-trigger Issue153 와 동일 폐기.)
_reuse=$(grep -E '^[[:space:]]*browser_tab_reuse:' "$HUB_SETTING_FILE" 2>/dev/null | head -1 | sed -E 's/^[^:]*:[[:space:]]*//; s/[[:space:]]*#.*$//; s/[[:space:]]*$//')
if [ "$_reuse" = "true" ]; then HUB_LINK_TARGET="fpm-hub"; else HUB_LINK_TARGET="_blank"; fi
# render URL host = advertise_host ?? bind_host(≠0.0.0.0) ?? 127.0.0.1 (hub-trigger 와 동일 산출)
_adv=$(grep -E '^[[:space:]]*advertise_host:' "$HUB_SETTING_FILE" 2>/dev/null | head -1 | sed -E 's/^[^:]*:[[:space:]]*//; s/[[:space:]]*#.*$//; s/[[:space:]]*$//; s/^"//; s/"$//')
_bind=$(grep -E '^[[:space:]]*bind_host:' "$HUB_SETTING_FILE" 2>/dev/null | head -1 | sed -E 's/^[^:]*:[[:space:]]*//; s/[[:space:]]*#.*$//; s/[[:space:]]*$//; s/^"//; s/"$//')
if [ -n "$_adv" ]; then RENDER_HOST="$_adv"
elif [ -n "$_bind" ] && [ "$_bind" != "0.0.0.0" ]; then RENDER_HOST="$_bind"
else RENDER_HOST="127.0.0.1"; fi

# Issue180: render_target 인지 — 폼(b모드)도 본문(fpm-hub-trigger.sh a모드)과 동일 표면 사용.
#   과거엔 폼이 render_target 무관 항상 외부 `open` 지시 → 본문(Simple Browser 패널)과 표면 불일치(이중 지시).
# prj3#Issue269: 값 매핑을 prj1#Issue295(축 분리) 기준으로 갱신.
#   Issue295 이전엔 `hub` 자체가 "외부 open 금지 + Simple Browser" 를 뜻해 hub→패널이 옳았으나,
#   이후 `render_target` 은 URL 형식 × 표면 2축으로 분리됨 → 패널 표면은 `vscode` 값이 전담.
#   vscode → POST /open-simple-browser (VSCode 패널, 외부 open 금지) / hub|local-open|both → 외부 open.
#   a모드(fpm-hub-trigger.sh)는 이미 RENDER_TARGET_CFG = vscode 로 판정 중 — 본 갱신으로 a/b 표면 재일치.
RENDER_TARGET=$(grep -E '^[[:space:]]*render_target:' "$HUB_SETTING_FILE" 2>/dev/null | head -1 | sed -E 's/^[^:]*:[[:space:]]*//; s/[[:space:]]*#.*$//; s/[[:space:]]*$//; s/^"//; s/"$//')
[ -z "$RENDER_TARGET" ] && RENDER_TARGET="local-open"

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
  RENDER_HOST="$RENDER_HOST" \
  RENDER_TARGET="$RENDER_TARGET" \
  HUB_LINK_TARGET="$HUB_LINK_TARGET" \
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
# Issue157: 헤더 버튼(open-project/open-session)용 프로젝트 루트 — cwd 가 _doc_work/* 하위면 보정
project_root = cwd.split('/_doc_work/')[0] if cwd and '/_doc_work/' in cwd else cwd

ask_path = f"{out_dir}/hub_htm_<YYYYMMDD_HHMMSS>_b_<주제>.htm"  # 날짜시간=`date +%Y%m%d_%H%M%S`, 주제=질문 핵심 10자 내외 kebab, mode b=ask 폼
path_note = (f"프로젝트 로컬 (_doc_work/{out_dir.split('_doc_work/')[-1]}/)" if '_doc_work/' in out_dir else f"프로젝트 로컬 ({out_dir})") if not out_dir.startswith('/tmp') else f"/tmp/___pm fallback → 프로젝트: {project_name} · 생성: cd {cwd} && mkdir -p _doc_work/htm"  # Issue276
# Issue172: 폼 open URL = hub 서버 /htm-doc?path=<절대경로> (:9876 register-doc 경유). file:// 폐기.
render_host = os.environ.get('RENDER_HOST', '127.0.0.1')
hub_doc_url = f"http://{render_host}:{server_port}/htm-doc?path=<절대경로>"
# Issue180: 폼 표면 지시를 render_target 에 맞춰 본문(fpm-hub-trigger.sh)과 통일 (이중 지시 제거).
# prj3#Issue269: 판정값 hub → vscode (prj1#Issue295 축 분리 반영 — 패널 표면은 vscode 전담).
#   vscode → POST /open-simple-browser (VSCode 패널, 외부 open 금지) / hub|local-open|both → 외부 open 유지.
render_target = os.environ.get('RENDER_TARGET', 'local-open')
if render_target == 'vscode':
    open_step_2 = (
        "**2. 저장 + VSCode Simple Browser 표시 (render_target: vscode, Issue170/180/269)** — `file://`·외부 브라우저 open **금지**:\n"
        "   - 먼저 `Write` 로 폼 저장 → `fpm-hub-doc-register` PostToolUse hook 이 자동 `register-doc` (mode b 포함, Issue80) → `/htm-doc?path=` 즉시 유효.\n"
        "   - 그 다음 아래 1줄 실행 (`<절대경로>`=저장한 폼 .htm). 본문 렌더와 동일 단일 표면(VSCode 패널)로 통일 — 외부 브라우저 open 금지 (Issue180 이중 표면 제거):\n"
        "   ```bash\n"
        f"  # path: {ask_path} ({path_note})\n"
        f"   curl -s -X POST http://{render_host}:{server_port}/open-simple-browser -H 'Content-Type: application/json' -d '{{\"path\":\"<절대경로>\"}}'\n"
        "   ```\n"
        f"   - 채팅에 fallback raw URL 병행 명시: `{hub_doc_url}`. ⚠️ `open` 실행 금지 (외부 브라우저 표면 이중 방지).\n\n"
    )
else:
    open_step_2 = (
        "**2. 저장 + hub 서버 경유 open (Issue172 — file:// 폐기 / Issue153 — 렌더 새 탭)**:\n"
        "   - 먼저 `Write` 로 폼 저장 → `fpm-hub-doc-register` PostToolUse hook 이 자동 `register-doc` (mode b 포함, Issue80) → `/htm-doc?path=` 즉시 유효.\n"
        "   - 그 다음 **hub URL** 로 open (file:// 금지 — :9876 register-doc 경유로 원격/타기기 표시 가능). 렌더 폼은 매번 새 탭(Issue153 — 하나씩 닫으며 검토). `/hub` 모니터링만 헤더 hub-link 명명탭(fpm-hub) 재사용:\n"
        "   ```bash\n"
        f"  # path: {ask_path} ({path_note})\n"
        f"   {open_cmd} \"{hub_doc_url}\"\n"
        "   ```\n"
        f"   - `<절대경로>` 를 실제 저장 경로로 치환. 최종 open 대상은 `{hub_doc_url}` (file:// 아님).\n\n"
    )
# Issue153/171: hub-link target — browser_tab_reuse=true → fpm-hub 명명탭 재사용 / false → _blank
hub_link_target = os.environ.get('HUB_LINK_TARGET', '_blank')
# Issue208: same-origin 상대경로 — 외부 기기(tailnet)에서 폼 열어도 POST 가 페이지 host 로 회귀.
# file:// 직접 열람만 폼 JS 의 AB(={LOOPBACK_BASE}) fallback 사용.
answer_url = f"/answer?cwd={cwd_q}&token={server_token}&sid={sid}"
loopback_base = f"http://127.0.0.1:{server_port}"

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
form_js = (open(os.path.expanduser('~/.claude/hooks/fpm-ask-form-template.js'), encoding='utf-8').read()
           .replace('{ANSWER_URL}', answer_url)
           .replace('{LOOPBACK_BASE}', loopback_base)
           .replace('{OPEN_PROJECT_URL}', open_project_url)
           .replace('{PROJECT_CWD_JSON}', json.dumps(cwd)))

# Issue143: 짝 a모드(..show 렌더) 페이지 탐색 → b 폼에 iframe+링크 임베드.
# a(Claude Write, cwd htm 폴더)와 b(hook, OUT_DIR fallback /tmp)가 서로 다른 폴더일 수 있어
# 후보 폴더(OUT_DIR + cwd 활성 htm/ + /tmp/___pm) 합집합에서 mtime 최신 1개를 페어로 본다.
# Issue289 는 아카이브(z_done/htm·legacy z_htm)까지 후보에 넣었으나 2026-08-09 되돌린다 —
#   "직전 ..show" 라는 의미상 아카이브는 페어가 아니고, 일괄 이동으로 mtime 이 동률이라
#   max() 결과가 비결정적이었다. 실발생: ___common 폼이 6/26 화석(z_done, 게다가 clear
#   tombstone)을 집어 iframe 이 영구 403 dead link. 아카이브 문서의 링크 유지는 서버
#   self-heal 소관이지 페어 선택 소관이 아니다.
# 같은 사고의 결함 3종을 함께 막는다:
#   1) 확장자 — a모드 산출이 md-first(Issue353_1)로 바뀐 뒤에도 glob 이 .htm 만 봐서 활성
#      페어를 영구히 못 찾고 매번 아카이브로 폴백했다 → .md/.html 포함, 링크는 확장자별 셸.
#   2) 나이 가드 — mtime 이 PAIR_MAX_AGE(기본 3600s) 이내인 것만 "직전"으로 인정.
#   3) 접근성 검증 — 고른 파일이 htm-registry 미등록이거나 htm-cleared tombstone 이면 뺀다.
#      서버는 화이트리스트 모델이라 링크해봐야 403 이다. registry 파일을 못 읽으면 검증 skip(fail-soft).
import glob as _glob, re as _re, html as _htmlmod, json as _json, time as _time
_cand_dirs = []
for _d in [out_dir] + ([os.path.join(cwd, '_doc_work', 'htm')] if cwd else []) + ['/tmp/___pm']:
    if _d and os.path.isdir(_d) and _d not in _cand_dirs:
        _cand_dirs.append(_d)
try:
    _pair_max_age = float(os.environ.get('PAIR_MAX_AGE', '3600'))
except ValueError:
    _pair_max_age = 3600.0
_now = _time.time()
_a_files = []
for _d in _cand_dirs:
    for _ext in ('htm', 'html', 'md'):
        _a_files += [f for f in _glob.glob(os.path.join(_d, f'hub_htm_*_a_*.{_ext}'))
                     if os.path.isfile(f) and (_now - os.path.getmtime(f)) <= _pair_max_age]
_reg_dir = os.path.expanduser('~/_git/___pm/data/hub')
def _hub_paths(_name, _key):
    """registry/tombstone json → realpath set. 읽기 실패 시 None(=검증 불가)."""
    try:
        with open(os.path.join(_reg_dir, _name), encoding='utf-8') as _fh:
            _rows = _json.load(_fh)
    except Exception:
        return None
    if _key:
        return {os.path.realpath(r.get(_key) or '')
                for r in _rows if isinstance(r, dict) and r.get(_key)}
    return {os.path.realpath(p) for p in _rows if isinstance(p, str)}
_reg_paths = _hub_paths('htm-registry.json', 'path')
_cleared_paths = _hub_paths('htm-cleared.json', None) or set()
def _servable(_f):
    _rp = os.path.realpath(_f)
    if _rp in _cleared_paths:
        return False              # 사용자가 clear → 서버가 self-heal 도 거부(403)
    return True if _reg_paths is None else _rp in _reg_paths
_a_files = [f for f in _a_files if _servable(f)]
a_pair = max(_a_files, key=lambda f: os.path.getmtime(f)) if _a_files else ''
if a_pair:
    _is_md = a_pair.endswith('.md')
    a_title = os.path.basename(a_pair)
    try:
        with open(a_pair, encoding='utf-8') as _fh:
            _head = _fh.read(4000)
        if _is_md:   # md-first 산출엔 <title> 이 없다 — frontmatter title/name → 첫 H1 순
            _m = (_re.search(r'^title:\s*(.+)$', _head, _re.M)
                  or _re.search(r'^name:\s*(.+)$', _head, _re.M)
                  or _re.search(r'^#\s+(.+)$', _head, _re.M))
            _cap = _m.group(1).strip().strip('"\'') if _m else ''
        else:
            _m = _re.search(r'<title>(.*?)</title>', _head, _re.S)
            _cap = _m.group(1).strip() if _m else ''
        if _cap:
            a_title = _cap
            for _pre in (f'{project_name} — ', f'{project_name} - '):
                if a_title.startswith(_pre):
                    a_title = a_title[len(_pre):]
    except Exception:
        pass
    _t = _htmlmod.escape(a_title)
    _shell = 'md-doc' if _is_md else 'htm-doc'
    _p = _htmlmod.escape(f'http://{render_host}:{server_port}/{_shell}?path=' + a_pair)  # Issue: http origin 폼에서 file:// iframe 차단 회귀 → hub 서버 경유
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
    "    <a class=\"hub-link\" href=\"http://127.0.0.1:__SPORT__/hub\" onclick=\"if(location.protocol!=='file:'){event.preventDefault();window.open('/hub','_blank');}\" target=\"__HUBTARGET__\" title=\"통합 모니터링 Hub\"><img src=\"http://127.0.0.1:__SPORT__/fpm-icon.png\" alt=\"Hub\" style=\"height:1.2em;vertical-align:-0.25em;\"></a>\n"
    "    <button type=\"button\" onclick=\"window.close()\">닫기 ✕</button>\n"
    "  </nav>\n"
    "</header>\n"
    "```\n"
    "```css\n"
    "header { position: sticky; top: 0; z-index: 100; display: flex; align-items: center;\n"
    "  justify-content: space-between; gap: 1rem; flex-wrap: wrap; padding: 0.9rem 1.4rem;\n"
    "  background: __PCOLOR__; color: #1a1a1a; }\n"
    "header h1 { margin: 0; font-size: 1.15rem; flex: 1 1 auto; min-width: 0; text-align: center; }\n"
    "header .header-actions { display: flex; align-items: center; gap: 0.5rem; flex: 0 0 auto; }\n"
    "header .proj-badge, header .sess-link, header .hub-link, header button { color: #1a1a1a; text-decoration: none;\n"
    "  cursor: pointer; white-space: nowrap; background: rgba(0,0,0,0.08);\n"
    "  border: 1px solid rgba(0,0,0,0.15); padding: 0.2rem 0.6rem; border-radius: 6px; font-size: 0.85rem; }\n"
    "header .proj-badge:hover, header .sess-link:hover, header .hub-link:hover, header button:hover {\n"
    "  background: rgba(0,0,0,0.16); text-decoration: underline; }\n"
    "```\n"
    "- `<title>` 도 `\"__PNAME__ — <질문제목>\"` 형식으로 prefix. 색=peacock 실색(Issue58/157), 글자 #1a1a1a — 흰 글자(#fff) 금지(파스텔 배경 위 invisible).\n"
    "- 불변식: 배지 정적 `<span>` 금지(Issue103) → 순서 `📁`→`🖥`→`🎯`→`닫기 ✕` → 넷 모두 헤더 안 동일 행 → flex+space-between+wrap.\n"
).replace("__PNAME__", project_name).replace("__PCOLOR__", project_color).replace("__ROOT__", project_root).replace("__SID__", sid).replace("__SPORT__", server_port).replace("__HUBTARGET__", hub_link_target)

reason = (
    "## AskUserQuestion 가로채기 — HTML form 자동 회수 (Issue45 단일 경로)\n\n"
    "`.hub-mode-active-<hash>` 플래그 활성(effective=on) + ___pm htm-server 가용. "
    "AskUserQuestion 도구 호출 차단됨. 사용자가 채팅이 아닌 Firefox HTML 폼으로 답변하도록 다음 절차를 따르세요.\n\n"
    "### 질문 데이터 (인라인 JSON)\n```json\n" + questions_json + "\n```\n\n"
    + project_header_guide
    + show_embed_section
    + f"\n### form 자동 회수 (___pm htm-server port {server_port}, cwd_hash `{cwd_hash}`)\n\n"
    "폼 \"전송\" 클릭 → 서버 inbox 로 직접 POST → Claude bash polling 회수. 사용자 paste 액션 불필요.\n\n"
    "**1. HTML form 생성** (:9876 hub URL 로 띄움 — Issue172):\n"
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
    + open_step_2 +
    "**3. 채팅 안내** (Issue40/Issue60 fallback 의무 — 요점 중심이되 다음 모두 포함):\n"
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
