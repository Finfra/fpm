#!/usr/bin/env bash
# hub-context.sh — hub 렌더 컨텍스트 계산 (Issue424_2)
#
# ⚠️ 글로벌 SCAR 변경 가드 (Issue46): 모든 프로젝트 공유. cwd ≠ ~/.claude 면 즉시 수정 금지
#   → ~/.claude/Issue.md 이슈 등록 후 처리. 설계 SSOT: ~/.claude/_doc_arch/hub-mode-arch.md
#
# 왜 분리했나 —
#   fpm-hub-trigger.sh 는 "트리거 분기"와 "컨텍스트 계산"이 뒤섞여 1,700줄이었다. 분기는
#   각자 early-exit 하는 독립 조각이라 읽기 쉬운데, 그 사이사이에 낀 계산 코드가 흐름을 끊었다.
#   계산부만 걷어내면 진입점에는 **무엇이 어떤 순서로 판정되는가**만 남는다.
#
# ⚠️ source 전용 — 서브셸로 부르면 안 된다.
#   여기서 정하는 값(SID·OUT_DIR·STATE_FILE·RENDER_TARGET·LIVE_* …)은 전부 호출자의 전역이어야
#   한다. bash 함수는 local 선언이 없으면 전역에 쓰므로 `. hub-context.sh` 후 함수를 부르면 된다.
#   ⚠️ `$(hub_ctx_...)` 형태(커맨드 치환)로 부르면 서브셸이라 값이 사라진다.
#
# ⚠️ 호출 순서가 곧 의존성이다 — identity → surface → (렌더 트리거 감지) → live_preopen.
#   surface 는 identity 가 source 한 hub-scope.sh 의 hub_effective() 를 쓰고,
#   live_preopen 은 진입점이 정한 HUB_RENDER_TRIGGER 를 본다.
#
# ⚠️ 함수 본문을 들여쓰지 않은 것은 실수가 아니다 — 안에 `<<'PYEOF'` heredoc 이 있어
#   종료 마커가 행 맨 앞에 있어야 한다. 들여쓰면 heredoc 이 파일 끝까지 먹는다(실측).

# ── ① 신원·경로 — SID · OUT_DIR · 프로젝트 이름/색 · cwd 해시/라벨 · 상태 파일 · IS_PROJECT ──
hub_ctx_identity() {
session_id="${_hookjson_session_id-}"   # Issue305_3: 위 단일 파싱에서 확보 (재spawn 제거)

# Issue26: SID(세션 식별자) 결정 — session_id 우선, 미존재 시 cwd_hash로 fallback
SID="$session_id"
if [ -z "$SID" ] && [ -n "$cwd" ]; then
  SID=$(CWD_VAL="$cwd" python3 -c "
import hashlib, os
cwd = os.environ.get('CWD_VAL', '')
print(hashlib.md5(cwd.encode('utf-8')).hexdigest()[:12] if cwd else 'unknown')")
fi
# SID_FULL: open-session API 호출용 full UUID (Issue137 회귀 fix — truncate 시 vscode 세션 매칭 실패 → 새 세션 생성)
# SID는 파일명·URL 안전화용 32자 slug (영문/숫자/하이픈만)
# Issue714: session_id 는 UUID 라 치환할 문자가 없다 — 그때는 tr·cut(3 fork, ~8ms)을 건너뛴다.
#   허용 외 문자가 하나라도 있으면 종전 경로 그대로(tr 는 **바이트** 단위라 비-ASCII 에서
#   bash 문자 단위 치환과 결과가 갈린다 — 의미를 옮기지 않고 경로만 나눈다).
case "$SID" in
  *[!A-Za-z0-9-]*)
    SID_FULL=$(printf '%s' "$SID" | tr -c 'A-Za-z0-9-' '-')
    SID=$(printf '%s' "$SID" | tr -c 'A-Za-z0-9-' '-' | cut -c1-32)
    ;;
  *)
    SID_FULL="$SID"
    SID="${SID:0:32}"
    ;;
esac

# OUT_DIR 결정 — 판정 단일 지점 lib/out-dir.sh 에 위임 (prj3#Issue802)
#   종전엔 `_htm_dir_of` + 상향 탐색(Issue203/289/714)이 여기 있었고 ask-common.sh 는 상향 탐색 없는
#   사본을 따로 들고 있어 프로젝트 하위 폴더 cwd 에서 두 판정이 갈렸다. 정의는 이제 out-dir.sh 하나다.
#   자기 옆의 lib/ 에서 찾는다 — 번들(플러그인) 설치본은 ~/.claude/hooks/lib 가 없다(prj3#Issue545)
. "${BASH_SOURCE[0]%/*}/out-dir.sh"
out_dir_resolve "$cwd"

# Issue22/Issue157: PROJECT_NAME + PROJECT_COLOR 계산
#   색 = peacock.color 실색 (Issue58/157) — cwd 에서 위로 .vscode/settings.json 탐색,
#        없으면 Projects.md prefix 매칭, 둘 다 실패 시 hsl 해시 fallback (임의색은 최후 수단).
#   name = peacock 찾은 프로젝트 루트 basename (htm/z_htm 등 하위폴더 보정).
# prj3#Issue594 성능: 이 python3 는 **매 프롬프트 고정 지출**(실측 ~25ms)이었다. 입력은 cwd 와
#   두 원천 파일(.vscode/settings.json · Projects.md)뿐이라 결과가 거의 안 바뀐다 →
#   원천 mtime 이 캐시보다 새로울 때만 다시 뽑는다. 캐시 손상·부재는 그냥 재계산(fail-soft).
_HUBCTX_CACHE_DIR="${TMPDIR:-/tmp}/___pm/hubctx"
# Issue714: cwd 의 md5 는 여기(캐시 키)와 아래 CWD_HASH 가 **같은 입력**(cwd 원문)이다 —
#   한 번만 계산해 둘이 나눠 쓴다(종전 2회). `md5 -q -s` 는 `printf | md5 -q` 와 같은 다이제스트다.
_HUBCTX_MD5=""
# prj3#Issue921 — sleep-state.sh 가 같은 원문을 이미 해시했으면 재사용(fpm-hub-trigger 1턴 md5 2 → 1회)
if [ -n "${_CWD_MD5-}" ] && [ "${_CWD_MD5_FOR-}" = "$cwd" ]; then
  _HUBCTX_MD5="$_CWD_MD5"
elif command -v md5 >/dev/null 2>&1; then
  _HUBCTX_MD5=$(md5 -q -s "$cwd" 2>/dev/null)
else
  _HUBCTX_MD5=$(printf '%s' "$cwd" | md5sum 2>/dev/null | cut -d' ' -f1)
fi
_HUBCTX_KEY="$_HUBCTX_MD5"
_HUBCTX_CACHE="$_HUBCTX_CACHE_DIR/${_HUBCTX_KEY:-none}"
_HUBCTX_SRC="$HOME/_git/___pm/Projects.md"
# Issue714: `find -newer`(원천마다 fork) → 내장 `-nt`. 캐시가 원천보다 **엄격히 새로울 때만** 신선 —
#   원천 부재는 신선(종전 find 무출력과 같다). 초 단위 비교인 bash(3.2)에서 같은 초의 갱신은
#   stale 쪽으로 기운다(재계산 1회 — 안전 방향).
_hubctx_fresh() {
  [ -s "$_HUBCTX_CACHE" ] || return 1
  if [ -e "$_HUBCTX_SRC" ]; then
    [ "$_HUBCTX_CACHE" -nt "$_HUBCTX_SRC" ] || return 1
  fi
  # cwd 위쪽 .vscode/settings.json 이 캐시보다 새로우면 무효 — peacock 색이 우선 원천이다
  _d="$cwd"
  while [ "$_d" != "/" ] && [ -n "$_d" ]; do
    if [ -f "$_d/.vscode/settings.json" ]; then
      [ "$_HUBCTX_CACHE" -nt "$_d/.vscode/settings.json" ] || return 1
      break
    fi
    [ "${_d%/*}" = "$_d" ] && break   # 상대경로 무진행 가드
    _d="${_d%/*}"   # Issue714: dirname fork 대신 파라미터 확장("/a" → "" 도 루프 조건이 끊는다)
  done
  return 0
}
if _hubctx_fresh; then
  read -r PROJECT_NAME PROJECT_COLOR < "$_HUBCTX_CACHE"
else
read -r PROJECT_NAME PROJECT_COLOR <<< "$(CWD_VAL="$cwd" python3 <<'PYEOF'
import hashlib, os, re
cwd = os.environ.get('CWD_VAL', '')
root = ''
hexcol = ''
# Issue309: 색상·이름 판정은 Projects.md(정본) 단일 소스.
#   종전 1순위였던 'cwd 조상의 .vscode/settings.json 재탐색'은 방향이 거꾸로였다.
#   올바른 흐름은 .vscode 가 바뀔 때 Projects.md 를 갱신하는 것(vscode-peacock-sync.sh)이고,
#   조회는 Projects.md 만 본다. 역방향(Projects.md -> 각 프로젝트 .vscode 적용)은
#   자동화하지 않으며 사용자가 명시 요청할 때만 수행한다.
#   부수 효과로 오귀속도 사라진다 — 자체 .vscode 가 없는 하위 프로젝트가 조상을 타고
#   올라가 홈(~/.vscode)의 색을 집어 이름까지 'nowage' 로 뒤집히던 문제(fSnippet 실측).
# 1. Projects.md prefix 매칭 (정본)
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
# 2. hex → HSL + 가독성 클램프 (Issue157). 미등록 프로젝트는 hsl 해시 폴백
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
  # 캐시 기록 — 실패해도 동작에 영향 없음
  mkdir -p "$_HUBCTX_CACHE_DIR" 2>/dev/null &&     printf '%s %s\n' "$PROJECT_NAME" "$PROJECT_COLOR" > "$_HUBCTX_CACHE" 2>/dev/null || true
fi

# Issue181: python3 산출 실패(예외·미설치·빈 출력) 시 read 가 빈 문자열을 받아
#   canonical 헤더에 `background: ;` 가 임베드되어 배경이 사라지는 결함 방어.
#   python 정상 경로는 항상 2토큰을 출력하므로 여기 도달 시는 전체 실패 케이스.
[ -z "$PROJECT_COLOR" ] && PROJECT_COLOR="hsl(220,45%,80%)"
[ -z "$PROJECT_NAME" ] && PROJECT_NAME="unknown"

# Issue83: cwd_hash + 프로젝트 판정 + per-cwd 상태 파일 경로
# Issue105: 파일명에 프로젝트 라벨 포함 (`<hash>__<label>`) — 어느 폴더가 stop 상태인지 가시
# Issue305_3: CWD_HASH·PROJECT_LABEL 은 python3 2회(~40ms)를 고정 지출했다.
#   ASCII 경로는 bash + md5(1~2ms)로 처리하고, 비-ASCII 는 문자 단위 치환 의미가
#   달라지므로(한글 1자 → `_` 1개) 기존 python3 경로를 그대로 탄다.
#   ⚠️ 해시는 cwd **원문**(rstrip 없음), 라벨은 rstrip 후 — sleep-state.sh 와 규칙이
#   다르므로 공유하지 않고 여기서 hub 의미 그대로 복제한다. 파일명이 곧 상태라 1바이트도 달라지면 안 된다.
CWD_HASH=""
PROJECT_LABEL=""
case "$cwd" in
  *[!A-Za-z0-9._/-]*|"") ;;
  *)
    # Issue714: 위 캐시 키에서 이미 계산한 cwd md5 를 쓴다(같은 입력 — 재계산 fork 제거)
    _h="$_HUBCTX_MD5"
    if [ -n "$_h" ]; then
      CWD_HASH="${_h:0:8}"
      _c="${cwd%/}"
      _base="${_c##*/}"; _rest="${_c%/*}"; _parent="${_rest##*/}"
      case "$_base" in
        _*) [ -n "$_parent" ] && _label="$_parent-$_base" || _label="$_base" ;;
        *)  _label="$_base" ;;
      esac
      _san=""
      for ((_i = 0; _i < ${#_label}; _i++)); do
        _ch="${_label:_i:1}"
        case "$_ch" in
          [A-Za-z0-9._-]) _san="$_san$_ch" ;;
          *) _san="${_san}_" ;;
        esac
      done
      _san="${_san:0:48}"
      [ -z "$_san" ] && _san="unknown"
      PROJECT_LABEL="$_san"
    fi
    ;;
esac
if [ -z "$CWD_HASH" ]; then
  CWD_HASH=$(CWD_VAL="$cwd" python3 -c "
import hashlib, os
c = os.environ.get('CWD_VAL', '')
print(hashlib.md5(c.encode('utf-8')).hexdigest()[:8] if c else 'none')")
fi
if [ -z "$PROJECT_LABEL" ]; then
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
fi

STATE_FILE="$STATE_DIR/${CWD_HASH}__${PROJECT_LABEL}"

# Issue283: hub 모드 플래그를 cwd 스코프로 확정 (세션 간 누수 차단)
# 2026-09-05: 루트 산재 → `.hub-active/` 디렉토리. 여기가 **쓰기 경로**라 touch 전에
#   디렉토리를 보장한다 — 없으면 touch 가 rc=1 로 조용히 실패하고 b모드가 안 뜬다.
FLAG_FILE="$HOME/.claude/.hub-active/${CWD_HASH}"
[ -d "$HOME/.claude/.hub-active" ] || mkdir -p "$HOME/.claude/.hub-active" 2>/dev/null   # Issue714: 있으면 fork 없음

# Issue105 마이그레이션: 기존 hash-only 파일이 있고 새 라벨 파일이 없으면 rename
OLD_STATE_FILE="$STATE_DIR/$CWD_HASH"
if [ -f "$OLD_STATE_FILE" ] && [ ! -f "$STATE_FILE" ]; then
  mv "$OLD_STATE_FILE" "$STATE_FILE" 2>/dev/null
fi

# 프로젝트 판정 — 판정 단일 지점 hub-scope.sh 에 위임 (규칙5, Issue322/F4-7⑤)
#   ⚠️ 종전엔 hub_is_project() 와 **문자 그대로 동일한 python3 33줄**을 여기에 복제하고 있었다.
#   같은 판정이 두 곳에 있으면 반드시 갈라지므로 source 로 접었다. hub-state.js(JS 3중 구현)는
#   같은 커밋에서 제거 — 판정 구현은 이제 hub-scope.sh 하나다.
#   해시는 위에서 이미 계산했으므로 캐시 쌍으로 넘겨 프로세스 순증을 0 으로 유지한다.
. "$HOME/.claude/hooks/hub-scope.sh"
export HUB_CWD_HASH="$CWD_HASH" HUB_CWD_HASH_FOR="$cwd"
IS_PROJECT=$(hub_is_project "$cwd")
# Issue366: 판정 결과를 **여기서** 캐시 쌍으로 되돌려 놓는다.
#   hub-scope.sh 의 프로세스 내 캐시(HUB_IS_PROJ)는 Issue362 에서 넣었지만 한 번도 적중한
#   적이 없다 — 위 `$(...)` 가 서브셸이라 함수가 채운 변수가 부모로 올라오지 못하기 때문이다.
#   ("측정을 안 해서 몰랐다"가 아니라 **구조적으로 작동 불가**였다.) export 해 두면
#   아래 L863 `EFFECTIVE=$(hub_effective "$cwd")` 의 서브셸이 이 값을 상속해 재판정을 건너뛴다.
export HUB_IS_PROJ="$IS_PROJECT" HUB_IS_PROJ_FOR="$cwd"
}

# ── ② 렌더 표면 해소 — 설정 로드 · 브라우저 커맨드 · EFFECTIVE · RENDER_TARGET · 강등 3종 ──
#   (Zed 표현불가 · hub 서버 미생존 · /tmp fallback → 각각 표면을 강등하고 고지 플래그를 세운다)
hub_ctx_surface() {
# prj3#Issue877: hub_cfg·browser_open 판정 단일 지점. source 시점에 hub_setting.yml 을 awk 로 1회 파싱한다.
# prj3#Issue921 — identity 에서 여기로 옮겼다. 설정을 읽는 것은 표면 계산뿐이라, hub off·트리거 없음으로
#   표면 전에 끝나는 턴(fpm-hub-trigger 조기 종료)은 awk 를 띄우지 않는다
. "${BASH_SOURCE[0]%/*}/hub-browser.sh"
# Issue130: browser_focus + default_browser 토글 (Issue128 확장)
# Issue424_2: 값은 그대로 prj1 SSOT. env override 를 허용하는 이유는 **검증 가능성**이다 —
#   표면(local-open·hub·vscode·both)별 지시문 동등성을 증명하려면 설정을 갈아 끼우며 돌려야 하는데,
#   prj1 의 실 yml 을 고치는 것은 타 repo 부작용이라 불가하다. env 미설정 시 동작은 종전과 동일.
HUB_SETTING_FILE="${HUB_SETTING_FILE:-$HOME/_git/___pm/data/hub_setting.yml}"

hub_browser_resolve
# Issue153: browser_tab_reuse 재정의 — 렌더는 항상 새 탭(HTM_OPEN_CMD 미치환). reuse 는 `/hub` 단일탭 전용.
#   true  → canonical 헤더 hub-link target=fpm-hub (브라우저 네이티브 명명 탭 재사용; helper 불필요)
#   false → target=_blank (hub-link 도 매번 새 탭)
#   렌더(HTM_OPEN_CMD)는 위 browser_open case 의 plain open/open -g 유지 → 렌더마다 새 탭(하나씩 닫으며 검토 가능).
#   (구 Issue162 폐기: reuse helper 가 :9876 origin 매칭으로 /hub + 모든 htm-doc 렌더를 한 탭에 collapse 했음.
#    helper(fpm-browser-open.sh)는 렌더 미사용 — fhub 등 /hub 직접 open 경로용으로만 잔존.)
_reuse=$(hub_cfg browser_tab_reuse)
if [ "$_reuse" = "true" ]; then HUB_LINK_TARGET="fpm-hub"; else HUB_LINK_TARGET="_blank"; fi

# prj3#Issue184: hub state(on/off) 를 render 분기 앞에서 미리 계산 (아래 render_target resolver 가 참조).
#   판정 우선순위: SYSTEM_OFF_FLAG > STATE_FILE > IS_PROJECT (자동 렌더 브랜치와 동일 로직).
#   과거엔 자동 브랜치 직전(옛 line 783)에서만 계산 → `..show` 브랜치는 state 를 몰라 render 위치를 못 바꿨음.
# 판정 단일 지점 위임 (규칙5, Issue322/F4-7⑤) — 우선순위 SYSTEM_OFF > state 파일 > IS_PROJECT
#   는 hub_effective() 안에 있다. 여기서 다시 쓰지 않는다.
#   ⚠️ state 파일 값은 `on`/`off` 뿐이므로(위 토글 분기가 HTM_ONOFF 만 기록) 종전의 raw 읽기와
#   hub_effective() 의 on 정규화는 **결과 동등**하다 — 전 프로젝트 state 파일 6건 실측으로 확인.
EFFECTIVE=$(hub_effective "$cwd")

# Issue141: render_target — ..show/자동 hub 렌더의 출력 경로 분기 (file:// open vs hub 서버 URL).
#   데이터 SSOT: ___pm data/hub_setting.yml (prj1#Issue153 신설). 키 부재 시 local-open 무해 fallback.
#   local-open(기본)=`open file://` / hub=서버 /htm-doc URL 을 외부 브라우저로 open / vscode=VSCode Simple Browser 패널 / both=file://+URL.
# Issue263: 표면(surface) 축 분리 — prj3#Issue170 이 `hub` 를 "VSCode 패널 + 외부 open 금지"로 재정의해
#   "hub http URL 을 브라우저로 열기" 조합이 표현 불가였음. 그 표면 고정 동작을 신규 값 `vscode` 로 이관하고
#   `hub` 는 원뜻(URL 형식 = 서버 http)으로 복원 → 표시 표면은 default_browser/browser_open 이 다시 결정.
#   ⚠️ URL 라우트는 /htm-doc?path= (Issue50, register-doc 등록 htm 토큰없이 serve) — /view 는 cwd+token 전용이라 부적합.
#   render 문서는 Write 시 fpm-hub-doc-register PostToolUse hook 이 자동 register-doc → URL 즉시 유효.
RENDER_TARGET=$(hub_cfg render_target)
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
RENDER_TAB_MODE=$(hub_cfg render_tab_mode)
[ "$RENDER_TAB_MODE" = "hub-internal" ] && { RENDER_TARGET="hub"; HUB_OPEN_SKIP=1; }   # Issue263: skip 을 명시 플래그로
# URL host = advertise_host ?? bind_host (주석처리 advertise_host 는 `^advertise_host:` 미매칭 → 생략 취급).
#   advertise 생략 + bind 0.0.0.0/미설정 → 접속 가능 host 강제(127.0.0.1) — `http://0.0.0.0` 좀비 URL 차단 (prj1#Issue153 가드).
_adv=$(hub_cfg advertise_host)
_bind=$(hub_cfg bind_host)
if [ -n "$_adv" ]; then
  RENDER_HOST="$_adv"
elif [ -n "$_bind" ] && [ "$_bind" != "0.0.0.0" ]; then
  RENDER_HOST="$_bind"
else
  RENDER_HOST="127.0.0.1"
fi
RENDER_PORT="${HTM_SERVER_PORT:-9876}"

# prj3#Issue340 (prj1#Issue355): hub 서버 미생존 → local-open 자동 강등.
#   md-first(Issue339)가 켜지는 hub·vscode 표면은 서버 `/md-doc` 셸이 표장(헤더·CSS·mermaid)을
#   소유하므로, 서버가 없으면 `.md` 파일만 남고 표시 경로가 통째로 사라진다. 사용자는 서버를
#   의도적으로 죽여 놓고 작업하는 경우가 많다 — **서버 유무가 렌더 경험을 바꾸면 안 된다**.
#   → 자립형 htm 경로(`file://`, Issue213 이 canonical 헤더 CSS 를 <head> 에 주입해 서버 없이 완결)로 강등.
#   판정은 bash 내장 /dev/tcp 포트 리슨 — **프로세스 기동 0회**(UserPromptSubmit 은 차단성 hook, 예산 50ms).
#   Zed 강등(Issue289 P4, 위)과 동형 패턴: 표현 불가한 표면은 강등하고 채팅에 1줄 고지(조용한 강등 금지).
#   ⚠️ RENDER_TARGET 만 바꾸면 아래 Issue184 블록이 CFG=hub 를 보고 되돌린다 → _CFG 도 함께 강등해야 한다.
HUB_DOWN_DOWNGRADED=0
if [ "$RENDER_TARGET_CFG" = "hub" ] || [ "$RENDER_TARGET_CFG" = "vscode" ]; then
  # 판정 host: 서버는 로컬 프로세스이므로 bind_host 기준. advertise_host(원격 표시용 이름)는 쓰지 않는다.
  #   ⚠️ bind_host 는 단일 값 **또는 리스트** `[127.0.0.1, 192.168.0.17, ...]` 다(멀티소켓 bind).
  #   그대로 쓰면 `[127.0.0.1,` 로 probe 해 살아있는 서버를 죽었다고 오판한다(구현 중 실측) → 토큰화 후 순회.
  #   루프백을 먼저 본다 — 정상 운영이면 첫 시도에서 끝나고, 죽었으면 ECONNREFUSED 가 즉시라 순회도 무비용.
  # Issue714: `tr -d '[]' | tr ',' ' '`(2 fork) → 파라미터 확장. 같은 치환이다
  _pb="${_bind//[\[\]]/}"; _probe_hosts="127.0.0.1 ${_pb//,/ }"
  _alive=0
  for _h in $_probe_hosts; do
    [ -z "$_h" ] && continue
    [ "$_h" = "0.0.0.0" ] && _h="127.0.0.1"
    # prj3#Issue921 — `( : </dev/tcp/… )` 는 프로브마다 서브셸 fork 였다(부하 시 UPS 임계 경로 fpm-hub-trigger 의 몫).
    #   내장 `:` 에 붙인 리다이렉션은 현재 셸에서 열고 닫는다 — fork 0 · 실패해도 셸은 계속(bash 3.2·5 실측)
    if { : 3<>"/dev/tcp/$_h/$RENDER_PORT"; } 2>/dev/null; then _alive=1; break; fi
  done
  if [ "$_alive" = "0" ]; then
    RENDER_TARGET="local-open"
    RENDER_TARGET_CFG="local-open"
    RENDER_TAB_MODE=""   # hub-internal 무효 — hub 쉘 iframe 도 서버가 있어야 뜬다
    HUB_OPEN_SKIP=0      # 죽은 URL 만 emit 하면 아무것도 안 보임 → 실제 file:// open 필요
    HUB_DOWN_DOWNGRADED=1
    if [ "$BROWSER_OPEN_OFF" = "1" ]; then
      # browser_open:off 라도 서버 다운이면 채팅 URL 이 죽으므로 실제 open 필요 → helper 승격(/tmp 블록과 동형).
      HTM_OPEN_CMD="bash \"$HOME/_git/___pm/plugins/fpm-core/hooks/fpm-browser-open.sh\" -a \"$_app\" -f $_focus -r false"
      BROWSER_OPEN_OFF=0
    fi
  fi
fi

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
UNREG_RENDER=$(hub_cfg unregistered_render)
[ -z "$UNREG_RENDER" ] && UNREG_RENDER="text"
}

# ── ③ 라이브 뷰 턴 시작 선오픈 — 세션당 1회, 마커 캐시 ──
hub_ctx_live_preopen() {
# prj3#Issue341 (prj1#Issue356): 턴 시작 라이브 뷰 선오픈 — Early Flush 완성.
#   prj1 이 만든 라이브 스트리밍(메일박스 pull + `/s/{h}/{sid}/live` 셸)은 재료만 있고
#   **부르는 쪽이 없었다**(현행 훅에 `/live` 0건 — Issue356 실측). 그래서 사용자에게는 여전히
#   "턴 끝에 완성본이 한 번에" 뜬다. 여기서 응답 생성 **전에** 라이브 뷰를 열어 첫 페인트를 당긴다.
#
#   설계 결정:
#   * URL 은 **서버가 조립**한다(`GET /live-url`, prj1#Issue356_1). 훅이 `tokens.json` 을 직접
#     파싱하면 상태 파일 포맷에 결합되어, 포맷이 바뀌는 순간 훅이 조용히 깨진다.
#   * **세션당 1회**만 연다. 라이브 URL 은 세션 내내 같은 값이라 매 턴 open 하면 브라우저가 탭을
#     계속 쌓는다. 마커에 URL·display 를 캐시해 2턴째부터는 curl 조차 돌지 않는다(추가 비용 0).
#     사용자가 탭을 닫으면 그 세션에서는 다시 열리지 않는다 — 매 턴 탭 폭증보다 이쪽이 낫다는 판단.
#     지시문에 URL 을 항상 실어 보내므로 클릭으로 복귀 가능.
#   * 서버 미기동이면 위 Issue340 강등이 이미 끝나 있다(`HUB_DOWN_DOWNGRADED=1`) → 진입 자체를
#     건너뛴다. 라이브 뷰는 서버 셸이라 서버 없이는 성립하지 않는다(강등 규약 우선).
#   * 대상 표면은 `hub` 뿐 — `vscode` 는 Simple Browser 가 **path 화이트리스트**로만 열려
#     (`POST /open-simple-browser`) 파일이 아닌 라이브 URL 을 그 경로로 못 연다.
#     `local-open`·`both` 는 애초에 서버를 안 거친다. 두 표면은 지시문 URL 안내로만 남긴다.
LIVE_OPENED=0     # 0=안 엶 / 1=이번 턴에 엶 / 2=이미 열려 있음(마커) / 3=open 생략(URL emit only)
LIVE_URL=""
LIVE_DISPLAY=""
#   * prj1#Issue532: 선오픈은 **`..show` 턴에만** 한다. 자동 모드(`EFFECTIVE=on`)에서 턴 시작에
#     열면 문서가 없는 턴에도 탭이 생기고, LLM 이 여는 md 문서 탭과 겹쳐 탭이 두 배가 됐다.
#     자동 모드의 세션 창은 첫 문서가 나올 때 opener(`fpm-browser-open.sh` → 서버 `/live-route`)가
#     연다 — 그 창이 문서를 인라인으로 보여주므로 창은 세션당 하나다.
if [ "$HUB_DOWN_DOWNGRADED" = "0" ] && [ "$RENDER_TARGET_CFG" = "hub" ] \
   && [ "$HUB_RENDER_TRIGGER" = "show" ]; then
  _live_marker="/tmp/___pm/hub-live/${SID_FULL}.live"
  if [ -f "$_live_marker" ]; then
    # 캐시 히트 — read 는 bash 내장이라 프로세스 0회. `live` 는 강등되지 않는 값이고(Issue356_1)
    #   `auto` 는 강등돼도 md 지시가 유지되므로, display 재조회 없이 캐시로 충분하다.
    read -r LIVE_URL LIVE_DISPLAY < "$_live_marker" 2>/dev/null || true
    [ -n "$LIVE_URL" ] && LIVE_OPENED=2
  else
    _live_json=$(curl -s --max-time 1 -G \
        --data-urlencode "cwd=$cwd" --data-urlencode "sid=$SID_FULL" \
        "http://$RENDER_HOST:$RENDER_PORT/live-url" 2>/dev/null)
    # ready=false → transcript 미생성(세션 첫 턴). 빈 뷰를 띄우지 않고 다음 턴에 재시도한다.
    case "$_live_json" in
      *'"ready": true'*|*'"ready":true'*)
        LIVE_URL=$(printf '%s' "$_live_json" | sed -n 's/.*"url"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')
        LIVE_DISPLAY=$(printf '%s' "$_live_json" | sed -n 's/.*"display"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')
        ;;
    esac
    # display=archive = "라이브 안 씀"(설정 명시 or 브라우저가 보고한 열화 강등) → 현행 문서 경로 그대로
    if [ -n "$LIVE_URL" ] && [ "$LIVE_DISPLAY" != "archive" ]; then
      if [ "$HUB_OPEN_SKIP" = "1" ] || [ "$BROWSER_OPEN_OFF" = "1" ]; then
        LIVE_OPENED=3    # open 금지 표면(hub-internal·browser_open:off) — URL 만 안내, 마커도 남기지 않음
      else
        mkdir -p "${_live_marker%/*}" 2>/dev/null
        printf '%s %s\n' "$LIVE_URL" "$LIVE_DISPLAY" > "$_live_marker" 2>/dev/null
        # 백그라운드 open — 훅은 기다리지 않는다(차단 비용 0)
        ( eval "$HTM_OPEN_CMD \"\$LIVE_URL\"" ) >/dev/null 2>&1 &
        LIVE_OPENED=1
      fi
    else
      LIVE_URL=""      # 열지도 안내하지도 않는다 — archive/조회실패는 현행 경로가 전담
      LIVE_DISPLAY=""
    fi
  fi
fi
}
