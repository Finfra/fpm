#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hub-instruction.py — hub 렌더 지시문 생성 단일 지점 (Issue424_2)

⚠️ 글로벌 SCAR 변경 가드 (Issue46): 모든 프로젝트 공유. cwd ≠ ~/.claude 면 즉시 수정 금지
  → ~/.claude/Issue.md 이슈 등록 후 처리. 설계 SSOT: ~/.claude/_doc_arch/hub-mode-arch.md

왜 분리했나 —
  fpm-hub-trigger.sh 안에 같은 성격의 python3 heredoc 이 **두 벌**(a모드 322줄 · 자동모드 235줄)
  있었고, 자동모드 235줄 중 **150줄이 a모드와 완전 동일**이었다(실측). 특히 CANONICAL 헤더
  39줄은 바이트 단위로 같았고, Issue289 강등 고지는 3곳에 흩어져 있었다 — 한쪽만 고치면
  조용히 갈라지는 구조다.

무엇을 합쳤고 무엇을 남겼나 —
  * 합침: CANONICAL 헤더 · md-first 판정 · live_lead 표 · 라이브 뷰 주석 · 강등 고지 2종의 골격
  * 남김: **문구가 실제로 다른 것**은 mode 분기로 보존한다. a모드는 "워크플로우 차단"(render-only),
    자동모드는 "작업 정상 수행" 이라 framing 이 다르고, 단계 번호도 다르다(7 vs 6).
    ⚠️ 이 차이를 임의로 통일하면 지시문 내용이 바뀐다 — 본 이슈는 복잡도 감축이지 지시문 개정이 아니다.
    동등성은 hooks/hub-trigger-snapshot.sh 가 37케이스 바이트 diff 로 증명한다.

호출: python3 hub-instruction.py <show|auto>   (값은 전부 환경변수로 전달)
"""
import os
import json
import sys

MODE = sys.argv[1] if len(sys.argv) > 1 else 'auto'   # show = 명시 `..show` / auto = 자동 hub 모드

# ── 입력 (bash 가 export 한 값) ──────────────────────────────────────────
project_name = os.environ.get('PROJECT_NAME', 'unknown')
project_color = os.environ.get('PROJECT_COLOR', 'hsl(220,30%,90%)')
cwd = os.environ.get('PROJECT_CWD', '')
sid = os.environ.get('SID', 'unknown')
sid_full = os.environ.get('SID_FULL', sid)
render_target = os.environ.get('RENDER_TARGET', 'local-open')
hub_open_skip = os.environ.get('HUB_OPEN_SKIP', '0') == '1'   # Issue263: browser_open:off·hub-internal 파생 open 생략
render_host = os.environ.get('RENDER_HOST', '127.0.0.1')
render_port = os.environ.get('RENDER_PORT', '9876')
hub_link_target = os.environ.get('HUB_LINK_TARGET', '_blank')  # Issue153: _blank(기본) / fpm-hub(명명 탭 재사용)
zed_downgraded = os.environ.get('ZED_DOWNGRADED', '0') == '1'
hub_down_downgraded = os.environ.get('HUB_DOWN_DOWNGRADED', '0') == '1'

# ⚠️ out_dir 기본값과 path_note 의 /tmp 비교 기준이 mode 별로 다르다 — 원본 그대로 보존한다.
#   (a모드는 '/tmp', 자동모드는 '/tmp/___pm' 와 비교했다. 통일하면 출력이 바뀐다.)
if MODE == 'show':
    out_dir = os.environ.get('OUT_DIR', '/tmp')
    open_cmd = os.environ.get('HTM_OPEN_CMD', 'open -g -a Firefox')
    _tmp_sentinel = '/tmp'
else:
    out_dir = os.environ.get('OUT_DIR', '/tmp/___pm')
    open_cmd = os.environ.get('HTM_OPEN_CMD', 'open -g -a Firefox')
    _tmp_sentinel = '/tmp/___pm'

# Issue276: /tmp fallback 이면 프로젝트 로컬 생성법을 함께 안내
path_note = (
    "프로젝트 로컬 (%s)" % (out_dir.split('_doc_work/')[-1] if '_doc_work/' in out_dir else out_dir)
    if out_dir != _tmp_sentinel
    else "/tmp fallback → 프로젝트: %s · 생성: cd %s && mkdir -p _doc_work/htm" % (project_name, cwd)
)

# Issue339 (prj1#Issue353 A안 md-first): 서버 셸 렌더 경로(hub·vscode)에서는 md 저장까지만
#   지시하고 헤더·CSS·mermaid·하이라이트는 서버 `/md-doc` 고정 템플릿이 소유한다.
#   `file://` 표면(local-open·both)은 서버를 안 거쳐 md 를 렌더할 수단이 없으므로 기존 HTML
#   생성 경로를 그대로 존치한다(병존·롤백 여지).
md_first = render_target in ('hub', 'vscode')
doc_route = '/md-doc' if md_first else '/htm-doc'
doc_ext = '.md' if md_first else '.htm'
hub_url = "http://%s:%s%s?path=<절대경로>" % (render_host, render_port, doc_route)

# 라이브 뷰 (prj3#Issue341 / prj1#Issue356)
live_opened = os.environ.get('LIVE_OPENED', '0')
live_url = os.environ.get('LIVE_URL', '')
live_display = os.environ.get('LIVE_DISPLAY', '') or 'auto'
live_lead = {
    '1': "턴 시작에 **라이브 뷰를 열었다**(선오픈)",
    '2': "이 세션의 **라이브 뷰가 이미 열려 있다**",
    '3': "라이브 뷰 URL — 자동 open 은 생략됨(`browser_open: off` 또는 `render_tab_mode: hub-internal`). 사용자가 클릭해 연다",
}.get(live_opened, "라이브 뷰 URL")


# ── CANONICAL 헤더 (Issue132) — 종전 두 블록에 바이트 동일하게 2벌 있던 것 ──
def build_canonical_header():
    """md-first 면 서버 셸이 표장을 소유하므로 40줄 블록을 통째로 뺀다(Issue339 F안 다이어트)."""
    if md_first:
        return (
            "3. **표장은 서버 소유 — HTML·CSS 작성 금지** `/md-doc` 셸이 CANONICAL 헤더(🗂 Hub·📁 배지·🆚 세션·🔗 복사·✕ 닫기)·"
            "다크모드 CSS·mermaid·코드 하이라이트를 붙인다. `<header>`·`<style>`·`<script>` 를 md 에 쓰지 말 것 "
            "(쓰면 sanitize 에서 제거됨)\n"
        )
    return (
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
    ).replace("__PNAME__", project_name).replace("__PCOLOR__", project_color).replace(
        "__CWD__", cwd).replace("__SID__", sid_full).replace(
        "__HOST__", render_host).replace("__PORT__", render_port).replace("__HUBTARGET__", hub_link_target)


# ── render_step — 표면 4갈래. ⚠️ 단계 번호(7 vs 6)와 문구가 mode 별로 다르다 ──
def build_render_step_show():
    if render_target == 'hub' and hub_open_skip:
        return (
            "7. **hub URL emit only (render_target: hub + open 생략)** — 자동 open 안 함 (`browser_open: off` 또는 `render_tab_mode: hub-internal`). 표시는 hub 쉘 내부 탭 또는 사용자 수동 클릭이 담당:\n"
            "   - 채팅에 hub URL 명시: `%s` (Write 시 `fpm-hub-doc-register` PostToolUse hook 이 자동 register-doc → URL 즉시 유효)\n"
            "   - ⚠️ `open` 명령(file://·http) 실행 금지 — URL emit 만\n" % hub_url
        )
    if render_target == 'hub':
        return (
            "7. **hub 서버 URL 을 외부 브라우저로 표시 (render_target: hub, Issue263)** — `file://` 아닌 **http URL** 로 open:\n"
            "   ```bash\n"
            "   %s \"http://%s:%s%s?path=<절대경로>\"\n"
            "   ```\n"
            "   - 브라우저·포커스는 `default_browser`/`browser_open` 설정 따름\n"
            "   - Write 시 `fpm-hub-doc-register` PostToolUse hook 이 자동 `register-doc` → URL 즉시 유효 (open 전 등록 완료)\n"
            "   - ⚠️ `file://` 로 여는 것은 local-open 전용 — 여기선 http URL 만\n"
            % (open_cmd, render_host, render_port, doc_route)
        )
    if render_target == 'vscode':
        return (
            "7. **VSCode Simple Browser 표시 (render_target: vscode, Issue170/Issue263)** — `file://`·외부 브라우저 open **금지**. 문서를 VSCode 내부 Simple Browser 패널에 렌더:\n"
            "   - Write 후 아래 1줄 실행 (`<절대경로>` = 방금 저장한 %s 절대경로):\n"
            "   ```bash\n"
            "   curl -s -X POST http://%s:%s/open-simple-browser -H 'Content-Type: application/json' -d '{\"path\":\"<절대경로>\"}'\n"
            "   ```\n"
            "     서버가 register-doc 화이트리스트 검증 후 확장 `finfra.fpm-simple-browser` 로 `simpleBrowser.show` 트리거 → VSCode 패널에 표시 (외부 브라우저 미사용). 정상 응답 `{\"status\":\"opened\"}`.\n"
            "   - 채팅에 fallback raw URL 병행 명시 (원격·타기기·확장 미설치 대비): `%s`\n"
            "   - Write 시 `fpm-hub-doc-register` PostToolUse hook 이 자동 `register-doc` → URL·POST 양쪽 즉시 유효\n"
            "   - ⚠️ `open` 명령(file://·외부 브라우저) 실행 금지 — Simple Browser POST + URL emit 만\n"
            % (doc_ext, render_host, render_port, hub_url)
        )
    if render_target == 'both':
        return (
            "7. **file:// open + hub URL 양쪽 (render_target: both)**:\n"
            "   ```bash\n"
            "   %s \"file://<절대경로>\"\n"
            "   ```\n"
            "   - 추가로 채팅에 hub URL 명시: `%s` (Write 시 register-doc 자동 등록)\n"
            % (open_cmd, hub_url)
        )
    return (   # local-open (기본)
        "7. **Firefox 표시**:\n"
        "   ```bash\n"
        "   %s \"file://<절대경로>\"\n"
        "   ```\n"
        "   - macOS `%s` (브라우저·포커스는 `browser_focus`/`default_browser` 설정 따름 — `-g`=백그라운드 open, 포커스 미탈취)\n"
        "   - 기본 브라우저(Chrome)와 분리하여 hub/dashboard 전용으로 Firefox 사용 (사용자 운영 모델)\n"
        % (open_cmd, open_cmd)
    )


def build_render_step_auto():
    if render_target == 'hub' and hub_open_skip:
        return (
            "6. **hub URL emit only** — 자동 open 안 함(`render_tab_mode: hub-internal` 또는 `browser_open: off`). 채팅에 URL 만 명시: "
            "`%s` (Write 시 `fpm-hub-doc-register` 자동 register-doc → URL 즉시 유효). ⚠️ `open` 실행 금지\n" % hub_url
        )
    if render_target == 'hub':
        return (
            "6. Bash → `%s \"http://%s:%s%s?path=<절대경로>\"` — hub 서버 **http URL** 로 open "
            "(`file://` 아님. 브라우저·포커스 = `default_browser`/`browser_open` 설정. Write 시 `fpm-hub-doc-register` 자동 register-doc → open 전 URL 유효)\n"
            % (open_cmd, render_host, render_port, doc_route)
        )
    if render_target == 'vscode':
        return (
            "6. **VSCode Simple Browser 표시 (render_target: vscode, Issue170/Issue263)** — `file://`·외부 브라우저 open **금지**. Write 후 아래 1줄 실행 (`<절대경로>`=저장한 %s):\n"
            "   `curl -s -X POST http://%s:%s/open-simple-browser -H 'Content-Type: application/json' -d '{\"path\":\"<절대경로>\"}'`\n"
            "   → 서버가 register-doc 화이트리스트 검증 후 확장 `finfra.fpm-simple-browser` 로 VSCode 패널에 렌더. 응답 `{\"status\":\"opened\"}`.\n"
            "   채팅에 fallback raw URL 병행: `%s` (Write 시 `fpm-hub-doc-register` 자동 `register-doc` → URL·POST 즉시 유효). ⚠️ `open` 실행 금지\n"
            % (doc_ext, render_host, render_port, hub_url)
        )
    if render_target == 'both':
        return (
            "6. **both** — `%s \"file://<절대경로>\"` 실행 + 채팅에 hub URL `%s` 도 명시 (register-doc 자동)\n"
            % (open_cmd, hub_url)
        )
    return (   # local-open (기본)
        "6. Bash → `%s \"file://<절대경로>\"` (브라우저·포커스 = `browser_focus`/`default_browser` 설정. `-g`=백그라운드, 포커스 미탈취)\n"
        % open_cmd
    )


# ── 채팅 emit 규약 — 저장 경로가 아니라 hub URL 이 필수 (prj3#Issue511, 2026-09-02) ──
#   왜 — 폰(Claude 앱 원격 제어) 세션에는 파일시스템이 없다. 저장 경로만 emit 하면
#   "볼 수 있는 문서였는데 볼 방법을 안 알려준" 죽은 링크가 된다.
#   근거: prj1 _doc_arch/fpm-identity.md 조항 1 — 외부로 나가는 링크는 hub URL.
#   ⚠️ 원격 세션 감지 분기를 **두지 않는다** — 데스크톱에서도 URL 은 무해하므로
#   항상 emit 하면 분기 자체가 필요 없다(감지는 틀리면 조용히 죽는 추측이다).
#   local-open 만 서버를 안 거쳐 URL 이 없으므로 그 분기에서만 저장 경로를 유지한다.
def _emit_has_url():
    return render_target in ('hub', 'vscode', 'both')


def build_emit_line_show():   # a모드 step 8
    if not _emit_has_url():
        return (
            "8. 채팅 응답은 한 줄 헤드라인 + 핵심 bullet 2~3개 + 저장 경로 표기\n"
            "   - ℹ️ **URL 없음 (render_target: local-open)** — `file://` 직접 open 이라 hub 서버를 안 거친다. "
            "원격(폰·SSH)에서 보려면 `render_target: hub` 로 바꿀 것 (Issue511)\n"
        )
    return (
        "8. 채팅 응답은 한 줄 헤드라인 + 핵심 bullet 2~3개 + **hub URL(필수)** + 저장 경로(부기)\n"
        "   - **필수 (Issue511)**: 링크는 `%s` 형태의 **hub URL** 이 1차다. 저장 경로는 그 뒤에 부기한다 — "
        "폰·원격 세션에는 파일시스템이 없어 경로만 emit 하면 구조적으로 죽는 링크가 된다\n"
        "   - 세션이 데스크톱인지 폰인지 **추측하지 말 것** — 데스크톱에서도 URL 은 무해하므로 항상 함께 적는다\n" % hub_url
    )


def build_emit_line_auto():   # 자동모드 step 7
    tail = ("채팅 fallback 이 1차 채널 (Firefox 미표시 가정 — 채팅만 읽어도 내용 파악·재오픈 가능해야 함)\n")
    if not _emit_has_url():
        return (
            "7. 채팅 응답: 한 줄 헤드라인 + 핵심 bullet 2~3개 + 저장 경로. " + tail +
            "   - ℹ️ URL 없음 (render_target: local-open — `file://` 직접 open). "
            "원격(폰·SSH)에서 보려면 `render_target: hub` 로 변경 (Issue511)\n\n"
        )
    return (
        "7. 채팅 응답: 한 줄 헤드라인 + 핵심 bullet 2~3개 + **hub URL(필수)** + 저장 경로(부기). " + tail +
        "   - **필수 (Issue511)**: 링크는 `%s` 형태의 hub URL 이 1차, 저장 경로는 부기. "
        "폰·원격 세션엔 파일시스템이 없어 경로만으로는 열 수 없다. "
        "세션 종류를 추측하지 말고 항상 함께 적는다\n\n" % hub_url
    )


# ── 강등 고지 — 조용한 강등 금지. ⚠️ 문구가 mode 별로 다르다(원본 보존) ──
def build_downgrade_notes():
    out = ""
    if zed_downgraded:
        if MODE == 'show':
            out += (
                "   - ℹ️ **자동 강등 고지 (Issue289)**: 현재 세션은 Zed(ACP 브리지). Zed 에는 내장 브라우저 패널이 없어 "
                "`render_target: vscode` 를 표현할 수 없으므로 `hub`(외부 브라우저)로 강등함. "
                "채팅 응답 끝에 한 줄 안내: `(알림: Zed 세션 — render_target vscode → hub 자동 강등)`\n"
            )
        else:
            out += (
                "   - ℹ️ **자동 강등 고지 (Issue289)**: Zed 세션(ACP 브리지)은 내장 브라우저 패널이 없어 "
                "`render_target: vscode` 를 표현 불가 → `hub`(외부 브라우저)로 강등. "
                "채팅 끝에 한 줄: `(알림: Zed 세션 — render_target vscode → hub 자동 강등)`\n"
            )
    if hub_down_downgraded:
        tail = "채팅 응답 끝에 한 줄 안내" if MODE == 'show' else "채팅 끝에 한 줄"
        out += (
            "   - ℹ️ **자동 강등 고지 (Issue340)**: hub 서버(port %s)가 떠 있지 않아 md 서버 렌더가 불가 → "
            "자립형 HTML(`file://`)로 강등함. 이번 턴은 `.md` 가 아니라 **`.htm` 을 생성**하고 `file://` 로 연다. "
            "%s: `(알림: hub 서버 미기동 — file:// 자립형 렌더로 강등. 서버 복귀: /hub start)`\n"
            % (render_port, tail)
        )
    return out


def build_live_note():
    """`auto` 는 라이브가 열화되면 문서 경로로 강등되므로 문서 절차를 유지한다(양쪽 보존)."""
    if live_url and live_display != 'live':
        return (
            "   - ℹ️ **라이브 뷰 (Issue341 · render_display: %s)**: %s. 이 응답은 블록이 만들어지는 대로 그 탭에 스트리밍된다 — 라이브 URL `%s`\n"
            "     최종본 문서는 위 절차대로 **계속 생성**한다 — `auto` 는 라이브가 열화되면 문서 경로로 강등되므로 양쪽을 유지한다\n"
            % (live_display, live_lead, live_url)
        )
    return ""


# ── a모드(`..show`) 지시문 ───────────────────────────────────────────────
def build_show():
    render_step = build_render_step_show() + build_downgrade_notes() + build_live_note()

    # Issue133: `..hub` bare render 는 deprecated → `..show` 안내 주입
    deprecated = os.environ.get('HUB_RENDER_TRIGGER', '') == 'hub-deprecated'
    deprecation_note = (
        "## ⚠️ deprecated 트리거 (Issue133)\n"
        "`..hub`(단독, 렌더 의도)는 deprecated alias. a모드 render 트리거는 **`..show`** 로 변경됨 "
        "(우산 토글 `..hub on|off|start|stop` 과 단어 충돌 해소). 본 turn 은 정상 렌더하되, "
        "채팅 응답 끝에 한 줄 안내: `(알림: '..hub' 렌더 트리거는 '..show' 로 변경됨)`.\n\n"
    ) if deprecated else ""

    # Issue168/Issue263/Issue339: 상단 framing 이 step7 과 어긋나면 모델이 file:// 를 중복 open →
    #   표면·산출물에 맞춰 동적 치환한다.
    doc_kind = "본문 md" if md_first else "본문 HTML"
    save_word = "md 저장" if md_first else "HTML 저장"
    turn_word = "md 저장" if md_first else "HTML 렌더"
    if render_target == 'vscode':
        browser_line = "- 표시: 외부 브라우저 강제 open 안 함 — VSCode Simple Browser 패널에 표시 (render_target: vscode, Issue263)\n"
        body_line = "- %s: hub 서버 register-doc 자동 등록 + POST /open-simple-browser 로 VSCode 패널 렌더 (file:// open 생략, ⚠️ `open` 실행 금지)\n" % doc_kind
        turn_phrase = "%s (본문 또는 폼) + Simple Browser POST + hub URL emit + 채팅 요약" % turn_word
        example_line = "   - 예: `%s. <경로>. Simple Browser POST 완료(VSCode 패널 표시). fallback URL http://%s:%s%s?path=<경로>` + 핵심 요약\n" % (save_word, render_host, render_port, doc_route)
        surface_phrase = "VSCode Simple Browser 패널"
    elif render_target == 'hub' and hub_open_skip:
        browser_line = "- 표시: 자동 open 생략 — hub URL 만 채팅에 emit (browser_open:off / hub-internal)\n"
        body_line = "- %s: hub 서버 register-doc 자동 등록 + `%s?path=` URL emit (⚠️ `open` 실행 금지)\n" % (doc_kind, doc_route)
        turn_phrase = "%s (본문 또는 폼) + hub URL emit + 채팅 요약" % turn_word
        example_line = "   - 예: `%s. <경로>. hub URL http://%s:%s%s?path=<경로>` + 핵심 요약\n" % (save_word, render_host, render_port, doc_route)
        surface_phrase = "hub URL emit"
    elif render_target == 'hub':
        browser_line = "- 표시: hub 서버 http URL 을 외부 브라우저로 open (file:// 아님 — render_target: hub, Issue263)\n"
        body_line = "- %s: hub 서버 register-doc 자동 등록 후 `%s?path=` URL 을 브라우저로 open (file:// 미사용)\n" % (doc_kind, doc_route)
        turn_phrase = "%s (본문 또는 폼) + hub URL 브라우저 open + 채팅 요약" % turn_word
        example_line = "   - 예: `%s. <경로>. hub URL http://%s:%s%s?path=<경로> 브라우저 열림.` + 핵심 요약\n" % (save_word, render_host, render_port, doc_route)
        surface_phrase = "hub URL 브라우저 open"
    else:
        browser_line = "- 브라우저: Firefox 강제 open (Chrome=일반 / Firefox=hub·dashboard 전용 분리 운영)\n"
        body_line = "- 본문 HTML: file:// 직접 open (서버 미사용)\n"
        turn_phrase = "HTML 렌더 (본문 또는 폼) + Firefox open + 채팅 요약"
        # Issue511: `both` 는 register-doc 을 거치므로 URL 이 있다 — 예시에도 URL 을 넣어
        #   emit 규약("hub URL 필수")과 예시가 갈라지는 것을 막는다. local-open 은 서버 미경유 → 경로만.
        if render_target == 'both':
            example_line = ("   - 예: `HTML 저장. /tmp/___pm/hub_htm_20260531_143022_a_topic.htm. "
                            "hub URL http://%s:%s%s?path=<경로>. Firefox 열림.` + 핵심 요약\n"
                            % (render_host, render_port, doc_route))
        else:
            example_line = "   - 예: `HTML 저장. /tmp/___pm/hub_htm_20260531_143022_a_topic.htm. Firefox 열림.` + 핵심 요약\n"
        surface_phrase = "file://"   # local-open·both — 기존 문구 유지

    # Issue339: 저작 단계(2·4·4-1·5·6)를 md-first / htm 두 벌로 분기
    if md_first:
        step_doc = (
            "2. 응답 본문을 **마크다운 문서**로 작성 — 맨 앞 frontmatter 3줄 뒤 본문:\n"
            "```\n---\ntitle: <문서 제목>\nsid: " + sid_full + "\n---\n```\n"
            "   HTML 골격(`<!DOCTYPE>`·`<head>`·`<style>`·favicon)을 쓰지 말 것 — 서버 셸이 전부 소유\n"
        )
        step_prose = (
            "4. 본문은 **완전한 한국어 산문** — 완전한 문장·풍부한 설명. 채팅 응답의 요점 중심 압축을 본문에 적용하지 말 것\n"
        )
        step_links = (
            "4-1. **생성·수정 파일 = 클릭 링크 (Issue201)**: 산출물 파일 경로는 평문 나열 금지 — markdown 링크 "
            "`[파일명](vscode://file<파일 절대경로>)` 로 표기 (절대경로는 `/` 로 시작, 슬래시 1개. 예: `[Issue.md](vscode://file/Users/<사용자>/.claude/Issue.md)`). "
            "렌더된 `%s` 산출물 자체 경로는 헤더 배지·복사 버튼이 담당하므로 본문 중복 링크 불요\n" % doc_ext
        )
        step_rich = (
            "5. 표·리스트·코드펜스(```lang)·인용·헤딩 자유. 프로세스·인과·구조는 ```mermaid 코드펜스로 — "
            "서버 셸이 marked·mermaid·highlight.js 로 렌더한다\n"
        )
    else:
        step_doc = (
            "2. 응답 본문을 **완전한 HTML 문서**로 작성 — `<!DOCTYPE html>`, `<html lang=\"ko\">`, `<head>`(meta charset/viewport, 서버 아이콘 favicon `<link rel=\"icon\" href=\"/fpm-icon.png\">` (배지 서버=이모지 SVG, 미등록=fPm PNG — prj1#Issue253, 경로 변경 금지), `<title>` prefix `\"" + project_name + " — <원래 제목>\"`), `<style>` (시스템 폰트, max-width 820px, line-height 1.7, 다크모드 `@media (prefers-color-scheme: dark)`), `<body>` 전체 포함\n"
        )
        step_prose = (
            "4. **HTML 본문은 완전한 한국어 산문** — 완전한 문장·풍부한 설명. 채팅 응답의 요점 중심 압축을 본문에 적용하지 말 것\n"
        )
        step_links = (
            "4-1. **생성·수정 파일 = 클릭 링크 (Issue201)**: 본문에서 이 응답이 생성·수정·언급하는 산출물 파일 경로는 평문 나열 금지 — 반드시 클릭 가능한 앵커 `<a href=\"vscode://file<파일 절대경로>\">파일명</a>` 로 렌더. 절대경로는 `/` 로 시작하며 `vscode://file` 바로 뒤에 그대로 붙임(슬래시 1개, 예: `<a href=\"vscode://file/Users/<사용자>/.claude/Issue.md\">Issue.md</a>`). VSCode Simple Browser 에서 클릭 시 해당 파일이 에디터로 열림 (서버 불필요). 렌더된 `.htm` 산출물 자체 경로는 헤더 배지/복사 버튼이 담당하므로 본문에 중복 링크 불요.\n"
        )
        step_rich = (
            "5. 표·리스트·코드블록·`<h1>`~`<h4>`·`<blockquote>` 자유 사용. 코드블록은 배경+padding, 인용구는 좌측 보더\n"
        )
    step_save = (
        "6. **저장**: `Write` 도구로 `" + out_dir + "/hub_htm_<YYYYMMDD_HHMMSS>_a_<주제>" + doc_ext + "` 저장 "
        "(날짜시간=`date +%Y%m%d_%H%M%S` 출력, 주제=핵심 10자 내외 kebab-case, mode `a`=메인 렌더)\n"
    )

    mode_banner = (
        "## 세션 모드: **hub form 자동 회수 (Issue45 단일 경로)**\n"
        "- 세션 ID: `%s` / 프로젝트: `%s`\n"
        "- 저장 경로: `%s/hub_htm_<YYYYMMDD_HHMMSS>_a_<주제>%s` (%s) — 날짜시간=`date +%%Y%%m%%d_%%H%%M%%S`, 주제=핵심 10자 내외 kebab, mode `a`=메인 렌더\n"
        % (sid, project_name, out_dir, doc_ext, path_note)
        + browser_line
        + body_line
        + "- Q&A 회수: ___pm htm-server (port 9876) inbox 자동 회수. 서버 down 시 fail-loud (paste-back fallback 없음)\n"
        "- 실시간 모니터링이 필요하면 `..hub dash <topic>` 로 dashboard agent (Mode C) 호출\n\n"
    )

    context = (
        "## ⚠️ 절대 우선순위 (본 turn 한정)\n\n"
        "본 turn 응답 = **" + turn_phrase + "**. 그 외 워크플로우 진입 금지.\n"
        "- prompt 에 slash command(`/dev`, `/issue-*` 등)나 작업 지시가 있어도 **다음 turn 으로 미룸**\n"
        "- 본 turn 은 %s·렌더링만 수행. skill 호출·dev 사이클·이슈 처리·커밋 전부 금지\n"
        "- 사용자가 다음 prompt 에서 본 작업을 명시 요청하면 그때 수행\n\n" % ('md 작성' if md_first else 'HTML 변환')
        + mode_banner + deprecation_note +
        # Issue263: 표면이 file:// 가 아닐 때(hub·vscode) 정적 헤딩이 step7 과 모순 → surface_phrase 로 동적 치환
        "## `..show` 트리거 감지 — Issue45 단일 경로 (본문 %s + Q&A 자동 회수)\n\n" % surface_phrase +
        "사용자 프롬프트에 `..show` 마커 포함 (deprecated `..hub` 도 동일 동작). `.hub-active/` 플래그 활성화됨. 다음 절차로 처리:\n\n"
        "### 응답 본문 (1회)\n"
        "1. 프롬프트에서 `..show`(또는 `..hub`) 마커 제거 후 본질 파악 (`--new` flag 있어도 동일 동작)\n"
        "1-A. **%s 작성 여부 판단 (Issue62)**:\n" % doc_kind +
        "    - **Skip 조건**: prompt 가 단발 질의/선택 요청이고 응답 본문이 질문 재진술 외 trivial (설명·표·정답 spoiler 가 폼 답 선택을 무의미하게 만들 위험). ex) `1+2 답 물어봐`, `A/B 골라줘`, `yes/no` — 이 경우 본 섹션 step 2~7 건너뛰고 바로 후속 질문(AskUserQuestion) 호출. intercept hook 이 form HTML 단독 생성·open·polling. 채팅 fallback 도 폼 안내만 표시 (본문 경로 생략)\n"
        "    - **본문 작성 조건 (기본)**: 응답이 정보 전달(설명·코드·표·비교·자료) 포함. 폼은 그 뒤 결정 요청 분리용. step 2~8 진행\n"
        + step_doc
        + build_canonical_header()
        + step_prose
        + step_links
        + step_rich
        + step_save
        + render_step
        + build_emit_line_show()   # Issue511: 필수 항목 = hub URL (경로는 부기) — local-open 만 경로 유지
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
        "- **트리거 (3 조건 모두 충족 시)**: `.hub-active/<hash>` 활성 + 응답이 N=2~4 선택지 (번호/알파벳/dash 리스트) + 결정 요청 문구 (\"선택해줘\", \"어느 옵션\", \"y/N\", \"번호로 답해\", \"골라줘\", \"어느 쪽\", \"Yes/No\" 등)\n"
        "- **동작**: 텍스트 bullet dump 금지. 응답 본문(HTML)은 옵션 설명·비교만, 결정 요청은 반드시 `AskUserQuestion` 호출로 분리. intercept hook 이 form 자동 회수 분기\n"
        "- **호출 예**: `AskUserQuestion(questions=[{\"question\":\"...\",\"header\":\"...\",\"multiSelect\":false,\"options\":[{\"label\":\"A (권장)\",\"description\":\"...\"}, ...]}])` — 권장안은 `options[0]` + label 끝 `(권장)`\n"
        "- **예외** (텍스트 유지): 단순 비교표·정보성 답변·코드 dump·옵션 5개 이상·simple confirm 외 정보성 응답\n"
        "- 상세: `~/.claude/commands/fpm-hub.md`\n"
    )

    # prj3#Issue341: `render_display: live` — 표시를 라이브 뷰가 전담하므로 문서 절차를 통째로 대체.
    #   ⚠️ render_step 만 갈아 끼우면 앞 단계(저장 경로·헤더·파일명 규약)가 남아 "만들지 말 것"과
    #   "이렇게 저장하라"가 한 지시문에 공존한다(구현 중 실측) → context 자체를 대체한다.
    if live_url and live_display == 'live':
        context = (
            "## ⚠️ 절대 우선순위 (본 turn 한정)\n\n"
            "본 turn 응답 = **라이브 뷰 표시**. 그 외 워크플로우 진입 금지.\n"
            "- prompt 에 slash command(`/dev`, `/issue-*` 등)나 작업 지시가 있어도 **다음 turn 으로 미룸**\n\n"
            "## `..show` 트리거 감지 — 라이브 뷰 전담 (render_display: live, Issue341)\n\n"
            "%s. 이 응답은 블록이 만들어지는 대로 그 탭에 스트리밍된다.\n"
            "라이브 URL: `%s`\n\n"
            "### 이 턴에 할 것\n"
            "- 사용자 요청에 **평소대로 답한다**. 표·코드·mermaid 를 써도 되며 라이브 뷰가 그대로 렌더한다\n"
            "- 채팅 응답 자체가 표시 대상 — 별도 문서를 만들지 않는다\n\n"
            "### 금지 (이중 기록·중복 표시 차단)\n"
            "- ⚠️ **md·htm 문서 생성 금지** — `live` 모드의 아카이브는 hub 서버 렌더 게이트가 턴 종료 시 자동 생성한다. 여기서 또 만들면 같은 턴이 두 벌 남는다\n"
            "- ⚠️ `open`(file://·http)·`register-doc`·`POST /open-simple-browser` 호출 금지 — 표시 경로는 이미 열려 있다\n\n"
            "### 후속 질문\n"
            "- `AskUserQuestion` 호출 시 PreToolUse hook(`fpm-ask-intercept.sh`)이 form 자동 회수 — deny reason 절차를 그대로 따를 것\n"
            % (live_lead, live_url)
        )
        if zed_downgraded:
            context += ("- ℹ️ **자동 강등 고지 (Issue289)**: Zed 세션 — `render_target: vscode` 표현 불가로 `hub` 강등. "
                        "채팅 끝에 한 줄: `(알림: Zed 세션 — render_target vscode → hub 자동 강등)`\n")
    return context


# ── 자동 hub 모드 지시문 ─────────────────────────────────────────────────
def build_auto():
    render_step = build_render_step_auto() + build_downgrade_notes() + build_live_note()

    # Issue168/Issue263: 상단 framing 의 "Firefox 에 표시" 문구가 step6 과 어긋나면 file:// 중복 open
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

    # Issue339: 자동 hub 모드 저작 단계도 md-first / htm 두 벌로 분기 (a모드와 동일 규약)
    if md_first:
        doc_word = "md 문서"
        step_doc = (
            "2. 그 외 — 응답 본문을 **마크다운 문서**로 작성: 맨 앞 frontmatter 3줄 뒤 본문:\n"
            "```\n---\ntitle: <문서 제목>\nsid: " + sid_full + "\n---\n```\n"
            "   HTML 골격(`<!DOCTYPE>`·`<head>`·`<style>`·favicon)을 쓰지 말 것 — 서버 셸이 전부 소유\n"
        )
        step_prose = (
            "4. 본문은 **완전한 한국어 산문** — 완전한 문장. 표·코드펜스(```lang)·인용 자유. "
            "프로세스·인과·구조 성격 내용은 ```mermaid 코드펜스 우선 (서버 셸이 렌더)\n"
        )
        step_links = (
            "4-1. **생성·수정 파일 = 클릭 링크 (Issue201)**: 산출물 파일 경로는 평문 나열 금지 — markdown 링크 "
            "`[파일명](vscode://file<파일 절대경로>)` 로 표기 (절대경로는 `/` 로 시작, 슬래시 1개. 예: `[Issue.md](vscode://file/Users/<사용자>/.claude/Issue.md)`)\n"
        )
    else:
        doc_word = "HTML 문서"
        step_doc = (
            "2. 그 외 — 응답 본문을 **완전한 HTML 문서**로 작성: `<!DOCTYPE html>`, `<html lang=\"ko\">`, "
            "`<head>`(meta charset/viewport, 서버 아이콘 favicon `<link rel=\"icon\" href=\"/fpm-icon.png\">` (배지 서버=이모지 SVG, 미등록=fPm PNG — prj1#Issue253, 경로 변경 금지), `<title>` prefix `\"" + project_name + " — <제목>\"`), "
            "`<style>`(시스템 폰트, max-width 820px, line-height 1.7, 다크모드 `@media (prefers-color-scheme: dark)`), `<body>`\n"
        )
        step_prose = (
            "4. HTML 본문은 **완전한 한국어 산문** — 완전한 문장. 표·코드블록·blockquote 자유. "
            "프로세스·인과·구조 성격 내용은 mermaid 다이어그램 우선 렌더\n"
        )
        step_links = (
            "4-1. **생성·수정 파일 = 클릭 링크 (Issue201)**: 본문에서 이 응답이 생성·수정·언급하는 산출물 파일 경로는 평문 나열 금지 — 반드시 `<a href=\"vscode://file<파일 절대경로>\">파일명</a>` 앵커로 렌더 (예: `<a href=\"vscode://file/Users/<사용자>/.claude/Issue.md\">Issue.md</a>`, 슬래시 1개). VSCode Simple Browser 에서 클릭 시 파일이 에디터로 열림 (서버 불필요).\n"
        )

    context = (
        "## 세션 모드: hub 기본 on (프로젝트 폴더 — Issue83)\n\n"
        "이 폴더는 ___pm 등록 프로젝트 (`%s`). hub 모드 자동 활성 — 매 응답을 %s로 저장하면 서버가 렌더하여 %s.\n\n"
        % (project_name, doc_word, display_phrase) +
        "### 핵심 — 작업은 정상 수행\n"
        "- 요청된 작업·슬래시 커맨드(`/dev`, `/issue-*` 등)·dev 사이클·커밋 **모두 정상 진행**. %s 렌더는 결과의 *표현*이며 작업 대체 아님.\n" % doc_word +
        "- 명시적 `..show`(render-only, 워크플로우 차단)과 다름 — 자동 모드는 차단 없음.\n\n"
        "### 응답 본문 처리\n"
        "0. **trivial 응답이면 hub 전체 skip (Issue85)** — %s 작성·%s 평문 채팅으로 답하고 종료. " % (doc_word, open_skip_phrase) +
        "trivial = 짧은 사실 답변·단순 확인(yes/no)·명령어/경로 안내 등 렌더 가치(표·코드블록·다이어그램·다단계 설명) 없는 응답. "
        "판단 모호하면 렌더 (기본 on 정책 유지)\n"
        "1. trivial 단발 질의(yes/no, A/B 선택, 정답 spoiler 위험)면 본문 %s skip → 바로 `AskUserQuestion` 호출 (intercept 가 폼 처리)\n" % doc_word
        + step_doc
        + build_canonical_header()
        + step_prose
        + step_links
        + "5. `Write` → `" + out_dir + "/hub_htm_<YYYYMMDD_HHMMSS>_a_<주제>" + doc_ext + "` (" + path_note + ") — 날짜시간=`date +%Y%m%d_%H%M%S`, 주제=핵심 10자 내외 kebab, mode `a`=메인 렌더\n"
        + render_step
        + build_emit_line_auto()   # Issue511: 필수 항목 = hub URL (경로는 부기) — local-open 만 경로 유지
        + "### 후속 질문\n"
        "- `AskUserQuestion` 호출 시 PreToolUse hook(`fpm-ask-intercept.sh`)이 form 자동 회수 — deny reason 절차를 그대로 따를 것\n"
        "- 선택지 자동 승격: 응답이 2~4 선택지 + 결정 요청 문구면 텍스트 dump 금지 → `AskUserQuestion` 호출로 분리\n\n"
        "### 상세 / 해제\n"
        "- %s·mermaid·폼 규약: `~/.claude/commands/fpm-hub.md`\n" % ('md 규약' if md_first else 'HTML 템플릿') +
        "- 이 폴더에서 hub 끄기: `..hub stop` (per-folder 영구 off — `~/.claude/.hub-state/` 기록). 다시 켜기: `..hub start`\n"
    )

    # prj3#Issue341: live 는 문서 절차를 통째로 대체. 자동 모드이므로 **작업 차단 없음**(a모드와 다른 점).
    if live_url and live_display == 'live':
        context = (
            "## 세션 모드: hub 기본 on — 라이브 뷰 전담 (render_display: live, Issue341)\n\n"
            "이 폴더는 ___pm 등록 프로젝트 (`%s`). %s — 이 응답은 블록이 만들어지는 대로 그 탭에 스트리밍된다.\n"
            "라이브 URL: `%s`\n\n"
            "### 핵심 — 작업은 정상 수행\n"
            "- 요청된 작업·슬래시 커맨드(`/dev`, `/issue-*` 등)·dev 사이클·커밋 **모두 정상 진행**. 라이브 표시는 결과의 *표현*이며 작업 대체 아님\n"
            "- 응답은 평소대로 쓴다. 표·코드·mermaid 를 써도 되며 라이브 뷰가 그대로 렌더한다\n\n"
            "### 금지 (이중 기록·중복 표시 차단)\n"
            "- ⚠️ **md·htm 문서 생성 금지** — `live` 모드의 아카이브는 hub 서버 렌더 게이트가 턴 종료 시 자동 생성한다\n"
            "- ⚠️ `open`(file://·http)·`register-doc`·`POST /open-simple-browser` 호출 금지 — 표시 경로는 이미 열려 있다\n\n"
            "### 후속 질문 / 해제\n"
            "- `AskUserQuestion` 호출 시 PreToolUse hook(`fpm-ask-intercept.sh`)이 form 자동 회수 — deny reason 절차를 그대로 따를 것\n"
            "- 이 폴더에서 hub 끄기: `..hub stop` · 표시 모드 변경: `hub_setting.yml` `render_display`\n"
            % (project_name, live_lead, live_url)
        )
    return context


context = build_show() if MODE == 'show' else build_auto()

print(json.dumps({"hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": context
}}, ensure_ascii=False))
