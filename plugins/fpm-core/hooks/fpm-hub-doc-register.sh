#!/bin/bash
# fpm-hub-doc-register.sh — PostToolUse hook (matcher: Write)
#
# ⚠️ 글로벌 SCAR 변경 가드 (Issue46): 본 hook 은 모든 프로젝트가 공유. cwd ≠ ~/.claude
#   면 즉시 수정 금지 → ~/.claude/Issue.md 이슈 등록 후 처리. 설계 SSOT:
#   ~/.claude/_doc_arch/hub-mode-arch.md. 절차: ~/.claude/rules/global-scar-change-rules.md
#
# Issue73: hub 본문 HTML 산출물을 ___pm htm-server hub registry 에 자동 등록.
# hub 커맨드 step 7(수동 POST /register-doc) 누락 시 hub 미노출 사각지대 보강.
# Issue80: B모드 ask 폼(mode b)도 등록 대상에 포함 (Mode D auto=mode c 만 제외).
# 파일명 규약: hub_htm_<YYYYMMDD_HHMMSS>_<mode>_<주제>.htm (mode a=렌더, b=ask, c=auto)
#
# 동작:
#   1. tool_input.file_path + cwd 추출
#   2. */_doc_work/{htm,z_done/htm,z_htm}/hub_htm_*_*.htm 매칭 (Mode D auto = _c_ 만 제외, a/b 포함)
#   3. healthz 200 → <title> 추출 → POST /register-doc
#   4. 비매칭/서버 미실행/curl 실패 → silent exit 0 (fail-soft, hub 본 기능 차단 금지)

input=$(cat)

read -r FP CWD <<< "$(printf '%s' "$input" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    fp = d.get('tool_input', {}).get('file_path', '')
    cwd = d.get('cwd', '')
    print(fp, cwd)
except Exception:
    print('', '')
")"

# Issue73/Issue80: 본문(mode a) + B모드 ask(mode b) 폼 등록. Mode D auto(mode c) 만 transient 로 제외.
# Issue158: htm 폴더에 hub_htm_ 비표준(dotted/하이픈-날짜) 파일명 Write 감지 시 경고 — 등록 훅 미매칭 403 재발 차단.
# Issue289: 매칭 폴더를 활성 `htm/` + 아카이브 `z_done/htm/` + legacy `z_htm/` 로 확장.
#   z_done/htm 도 매칭하는 이유 — 아카이브 폴더에 직접 Write 되는 경우(복구·수동 배치)에도
#   등록이 끊기지 않게. legacy z_htm 은 P3 마이그레이션 완료 후 P4 에서 제거.
# Issue339 (prj1#Issue353 A안 md-first): 산출물이 `.md` 인 경로도 동일 규약으로 등록한다.
#   서버 `_htm_output_stem` 이 `hub_htm_*.{htm,md}` 를 함께 인식하므로 확장자만 넓히면 된다.
#   (`/md-doc` 는 registry 화이트리스트를 그대로 쓰므로 미등록이면 403 — 여기가 유일한 등록 경로)
case "$FP" in
  */_doc_work/htm/hub_htm_*_c_*.htm|*/_doc_work/z_done/htm/hub_htm_*_c_*.htm|*/_doc_work/z_htm/hub_htm_*_c_*.htm) exit 0 ;;
  */_doc_work/htm/hub_htm_*_c_*.md|*/_doc_work/z_done/htm/hub_htm_*_c_*.md|*/_doc_work/z_htm/hub_htm_*_c_*.md) exit 0 ;;
  */_doc_work/htm/hub_htm_*_*.htm|*/_doc_work/z_done/htm/hub_htm_*_*.htm|*/_doc_work/z_htm/hub_htm_*_*.htm)   ;;
  */_doc_work/htm/hub_htm_*_*.md|*/_doc_work/z_done/htm/hub_htm_*_*.md|*/_doc_work/z_htm/hub_htm_*_*.md)   ;;
  */_doc_work/htm/*.htm|*/_doc_work/z_done/htm/*.htm|*/_doc_work/z_htm/*.htm|*/_doc_work/htm/*.md|*/_doc_work/z_done/htm/*.md|*/_doc_work/z_htm/*.md)
    echo "⚠️ Issue158: '$FP' 가 표준 파일명 규약 미준수. hub 산출물은 반드시 hub_htm_<YYYYMMDD_HHMMSS>_<mode>_<주제>.{htm,md} (언더스코어, date +%Y%m%d_%H%M%S) 사용. dotted/하이픈-날짜 파일은 등록 훅 미매칭 → /htm-doc·/md-doc 403 dead link. 파일명 재작성 권장." >&2
    exit 2 ;;
  *) exit 0 ;;
esac

[ -z "$CWD" ] && exit 0

# file_path 가 상대경로면 cwd 기준으로 절대화
case "$FP" in
  /*) FP_ABS="$FP" ;;
  *)  FP_ABS="${CWD%/}/$FP" ;;
esac
[ -f "$FP_ABS" ] || exit 0

# Issue339: 아래 두 후처리(아이콘 data-URL 치환·헤더 CSS 자체완결 주입)는 **HTML 산출물 전용**이다.
#   md 산출물은 표장을 서버 `/md-doc` 셸이 소유하므로 파일 본문을 건드릴 이유가 없고,
#   건드리면 저작 md 에 HTML 이 섞여 sanitize 대상이 된다 → md 면 후처리를 통째 건너뛴다.
case "$FP_ABS" in *.md) IS_MD=1 ;; *) IS_MD=0 ;; esac

# Issue174: Hub 아이콘 self-contain — 저장된 .htm 의 host-relative `/fpm-icon.png` 참조를
#   인라인 data-URL 로 치환. http <img> 는 VSCode Simple Browser webview CSP 가 차단해 깨지므로
#   (Issue173), data-URL(자기완결)로 바꿔 어떤 뷰어서도 렌더되게 함. data-URL 은 hooks/assets/
#   fpm-icon.dataurl(작은 webp, ~2KB) 에 1회 저장 — canonical 헤더 문자열은 짧은 `/fpm-icon.png`
#   유지하여 매 프롬프트 주입 컨텍스트 bloat 0. server 상태 무관(healthz gate 이전 실행).
ICON_DATAURL_FILE="$(dirname "$0")/assets/fpm-icon.dataurl"
if [ "$IS_MD" = "0" ] && [ -f "$ICON_DATAURL_FILE" ]; then
  FP_ABS="$FP_ABS" ICON_DATAURL_FILE="$ICON_DATAURL_FILE" python3 - <<'PYICON' 2>/dev/null || true
import os, re
fp = os.environ["FP_ABS"]
durl = open(os.environ["ICON_DATAURL_FILE"], encoding="utf-8").read().strip()
with open(fp, encoding="utf-8") as f:
    html = f.read()
# b모드 템플릿은 절대 URL(`http://127.0.0.1:9876/fpm-icon.png`)로, a모드는 host-relative(`/fpm-icon.png`)로
# 아이콘을 참조한다. 순수 문자열 replace 는 절대형에서 host:port prefix 를 남겨 `http://...:9876data:...`
# (깨진 URL)을 만든다. 선행 http(s)://host:port 를 함께 삼키는 정규식으로 두 형태 모두 data-URL 로 치환.
_ICON_REF = re.compile(r'(?:https?://[^/\s"\'<>]+)?/fpm-icon\.png')
if _ICON_REF.search(html):
    html = _ICON_REF.sub(lambda m: durl, html)
    with open(fp, "w", encoding="utf-8") as f:
        f.write(html)
PYICON
fi

# Issue213: local-open(file://) 헤더 CSS 자체완결 — a모드 `..show` htm 을 `file://` 로 직접 열면
#   serve-time 헤더 CSS 정규화(prj1 server.py `_normalize_hub_header_css`, `/htm-doc` http 전용)를
#   우회해 헤더가 무스타일 body flow 로 흘러 sticky 바·중앙 제목·chip 버튼이 사라진다.
#   원인: a모드 Claude 가 `<style>` 손작성 시 `header{}` 규칙을 자주 누락(관측 5중 3). Write 직후
#   여기서 canonical 헤더 CSS 를 `<head>` 에 주입해 서버 없이 file:// 로도 자체 완결시킨다.
#   serve-time 과 동일 로직(멱등): `<header>` 있고 `header{` 규칙 없을 때만 주입, 있으면 no-op(저작본 존중).
#   같은 파일이 나중에 /htm-doc 로 서빙돼도 serve-time 은 우리가 넣은 `header{` 보고 no-op → 이중 주입 안전.
#   ⚠️ 동기 필요: 아래 HUB_HEADER_CSS 는 prj1 `services/hub/server.py` `HUB_HEADER_CSS` 정본과 동일
#      문자열 유지 필수 (정본 변경 시 여기도 갱신). healthz gate 이전 실행이라 서버 상태 무관.
if [ "$IS_MD" = "0" ]; then
FP_ABS="$FP_ABS" python3 - <<'PYHDR' 2>/dev/null || true
import os, re
fp = os.environ["FP_ABS"]
# prj1 services/hub/server.py HUB_HEADER_CSS 정본과 동일 (Issue213). 변경 시 양쪽 동기.
HUB_HEADER_CSS = (
    '<style id="hub-header-normalized">'
    'header { position: sticky; top: 0; z-index: 100; display: flex; align-items: center;'
    '  justify-content: space-between; gap: 1rem; flex-wrap: wrap; padding: 0.9rem 1.4rem;'
    '  margin-inline: calc(50% - 50vw); background: hsl(238,45%,80%); color: #1a1a1a; }'
    'header > .hub-link { flex: 0 0 auto; }'
    'header h1 { margin: 0; font-size: 1.15rem; flex: 1 1 auto; min-width: 0; text-align: center; }'
    'header .header-actions { display: flex; align-items: center; gap: 0.5rem; flex: 0 0 auto; }'
    'header .proj-badge, header .sess-link, header .hub-link, header button {'
    '  display: inline-flex; align-items: center; line-height: 1; color: #1a1a1a;'
    '  text-decoration: none; cursor: pointer; white-space: nowrap; background: rgba(0,0,0,0.08);'
    '  border: 1px solid rgba(0,0,0,0.15); padding: 0.2rem 0.6rem; border-radius: 6px; font-size: 0.85rem; }'
    'header .copy-link, header .close-btn { justify-content: center; padding: 0.2rem 0.5rem; }'
    'header .close-btn { margin-left: 0.6rem; }'
    'header .close-btn:hover { background: rgba(200,0,0,0.18); }'
    'header .proj-badge:hover, header .sess-link:hover, header .hub-link:hover, header button:hover {'
    '  background: rgba(0,0,0,0.16); text-decoration: underline; }'
    '</style>'
)
try:
    with open(fp, encoding="utf-8") as f:
        html = f.read()
except Exception:
    raise SystemExit(0)
# <header> 엘리먼트가 있고, 그것을 스타일하는 header{} 규칙이 없을 때만 주입 (serve-time 동일).
if not re.search(r'<header\b', html, re.I):
    raise SystemExit(0)
if re.search(r'header\s*\{', html, re.I):
    raise SystemExit(0)
low = html.lower()
idx = low.rfind('</head>')
if idx < 0:
    idx = low.find('<body')
new = HUB_HEADER_CSS + html if idx < 0 else html[:idx] + HUB_HEADER_CSS + html[idx:]
with open(fp, "w", encoding="utf-8") as f:
    f.write(new)
PYHDR
fi

SERVER_PORT="${HTM_SERVER_PORT:-9876}"
HEALTH_URL="http://127.0.0.1:${SERVER_PORT}/healthz"

health=$(curl -s -o /dev/null -w "%{http_code}" --max-time 2 "$HEALTH_URL" 2>/dev/null)
[ "$health" = "200" ] || exit 0

# 제목 추출 (실패 시 파일명 fallback) — htm 은 <title>, md 는 frontmatter title/name → 첫 헤딩.
# Issue339: 추출 규칙은 prj1 server.py `_extract_html_title` 의 md 분기와 동일하게 맞춘다
#   (양쪽이 갈라지면 hub 카드 제목과 문서 제목이 서로 다른 값을 보인다).
BODY=$(FP_ABS="$FP_ABS" CWD="$CWD" python3 -c "
import os, re, json
fp = os.environ['FP_ABS']
cwd = os.environ['CWD']
title = ''
try:
    with open(fp, encoding='utf-8', errors='ignore') as f:
        head = f.read(8192) if fp.endswith('.md') else f.read()
    if fp.endswith('.md'):
        fm = re.match(r'(?s)\A---\n(.*?)\n---', head)
        if fm:
            kv = re.search(r'(?m)^(?:title|name):\s*[\"\']?([^\"\'\n]+)', fm.group(1))
            if kv:
                title = kv.group(1).strip()[:200]
        if not title:
            h = re.search(r'(?m)^#{1,6}\s+(.+)\$', head)
            if h:
                title = h.group(1).strip()[:200]
    else:
        m = re.search(r'<title[^>]*>(.*?)</title>', head, re.S | re.I)
        if m:
            title = re.sub(r'\s+', ' ', m.group(1)).strip()[:200]
except Exception:
    pass
if not title:
    title = os.path.basename(fp)
print(json.dumps({'type': 'htm', 'path': fp, 'cwd': cwd, 'title': title}))
" 2>/dev/null)

[ -z "$BODY" ] && exit 0

curl -s --max-time 3 -X POST "http://127.0.0.1:${SERVER_PORT}/register-doc" \
  -H 'Content-Type: application/json' \
  -d "$BODY" >/dev/null 2>&1

exit 0
