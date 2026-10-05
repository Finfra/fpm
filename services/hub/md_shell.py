"""md_shell — hub md-first 셸 렌더 단일 템플릿 모듈 (Issue353_1 M1, arch A안).

Claude 는 `.md` 저장까지만 담당하고, 표장(chrome)은 이 모듈이 책임진다:
고정 셸(HTML 스켈레톤 + CSS) + 클라이언트 렌더 파이프라인(marked → DOMPurify
→ mermaid/highlight → 상대 이미지 `/htm-res` 재작성).

⚠️ **셸 1벌 원칙 (arch v1.3)**: M2 라이브 셸은 본 모듈의 `SHELL_CSS`·`RENDER_JS`
를 그대로 재사용해야 한다(같은 셸 + 폴러). 템플릿을 복제하면 스타일 드리프트
(본 설계가 치료하는 질병)가 서버 안에서 재발한다.

보안 불변식 (arch "보안·프라이버시 불변식"):
* md 원문은 `<script type="application/json">` JSON 문자열로만 페이지에 실린다
  (`<` → `\\u003c` 이스케이프) — 저작 내용이 serve 시점 DOM 태그가 될 수 없다.
* 런타임 DOM 삽입 전 DOMPurify allowlist sanitize — 인라인 HTML 은 마크다운
  산출 태그 집합으로 강제 축소(script/iframe/이벤트 핸들러 소멸).
* CSP: 인라인 <script> 는 응답별 nonce 필수 + 외부 스크립트는 jsdelivr 핀 호스트만.
  서버 셸/shim 이 아닌 주입 스크립트는 nonce 부재로 실행 불가(2중 방어).
* CDN 실패 시 graceful degradation — 원문 md 를 <pre> 평문 노출(fail-soft).

mermaid 는 이 모듈의 `CDN_MERMAID`·`MERMAID_JS` 가 **단일 출처**다(Issue569) —
server.py `MERMAID_RUNTIME`(htm 경로)도 이 둘로 조립한다. 코드펜스 ```mermaid →
렌더 후 `<pre class="mermaid">` 승격 + `hubMermaid.run()`(파싱 선검사·라벨 보정·
원문 폴백, startOnLoad race 없음). 버전은 여기 한 곳에서만 올린다.
"""
import html
import json
import re
import secrets

# 핀 고정 CDN — mermaid 는 server.py MERMAID_RUNTIME 도 이 값을 쓴다(Issue569 단일 출처)
CDN_MARKED = "https://cdn.jsdelivr.net/npm/marked@12.0.2/lib/marked.umd.min.js"
CDN_PURIFY = "https://cdn.jsdelivr.net/npm/dompurify@3.1.6/dist/purify.min.js"
# Issue569: 정확 버전으로 고정한다. 종전 `mermaid@11` 은 부동 major 태그라 jsDelivr 가
#   조용히 최신 11.x 를 내려줬고, 11.6.0 의 edge-ID 문법(`e1@-->`)이 라벨 속 `x@` 를
#   가로채 멀쩡하던 다이어그램이 통째로 오류 박스가 됐다(10.9.1·11.4.1 OK / 11.6.0+ ERR
#   실측). 11.17.2 = 고정 시점 서빙본이라 오늘 동작 변화는 없다. 올릴 때는
#   test_mermaid_heal_issue569.js 와 실 브라우저 대조를 함께 돌린다.
CDN_MERMAID = "https://cdn.jsdelivr.net/npm/mermaid@11.17.2/dist/mermaid.min.js"
CDN_HLJS = "https://cdn.jsdelivr.net/npm/@highlightjs/cdn-assets@11.9.0/highlight.min.js"
CDN_HLJS_CSS = "https://cdn.jsdelivr.net/npm/@highlightjs/cdn-assets@11.9.0/styles/github.min.css"
CDN_HLJS_CSS_DARK = "https://cdn.jsdelivr.net/npm/@highlightjs/cdn-assets@11.9.0/styles/github-dark.min.css"

# DOMPurify `ALLOWED_URI_REGEXP` (JS 리터럴 본문 — 감싸는 `/…/i` 는 RENDER_JS 가 붙임).
#
# dompurify@3.1.6 기본값은 `(f|ht)tps?|mailto|tel|callto|sms|cid|xmpp` 만 허용해
# `vscode://file/<절대경로>` href 를 통째로 제거한다(텍스트만 남음) — 2026-08-05 CDN 실측.
# htm 경로에는 없던 Issue201(파일 클릭 → VSCode 열기) 회귀라 **`vscode` 하나만** 덧댄다.
# ⚠️ `javascript:`·`data:` 는 절대 추가하지 말 것 — 링크 클릭 XSS 경로가 열린다
# (CSP 가 인라인 script 를 막아도 `javascript:` href 는 별개 실행면이다).
ALLOWED_URI_REGEXP = (
    r"^(?:(?:(?:f|ht)tps?|mailto|tel|callto|sms|cid|xmpp|vscode):"
    r"|[^a-z]|[a-z+.\-]+(?:[^a-z+.\-:]|$))"
)


_FRONTMATTER_RE = re.compile(r"\A---[ \t]*\n(.*?)\n---[ \t]*\n?", re.DOTALL)


def split_frontmatter(md_text: str) -> tuple:
    """YAML frontmatter 를 본문에서 분리해 `(meta, body)` 로 반환.

    marked 는 frontmatter 를 모른다 — 떼지 않으면 `---` 이 `<hr>` 로, `title: …` 이
    setext 헤딩으로 렌더되어 본문 맨 앞에 메타가 그대로 노출된다(2026-08-05 실측).
    파서는 md-rules 가 쓰는 평평한 `key: value` 만 다룬다(중첩·리스트 불요).
    """
    m = _FRONTMATTER_RE.match(md_text)
    if not m:
        return {}, md_text
    meta = {}
    for line in m.group(1).splitlines():
        kv = re.match(r"([A-Za-z0-9_-]+):\s*(.*)$", line.strip())
        if kv:
            meta[kv.group(1)] = kv.group(2).strip().strip("\"'")
    return meta, md_text[m.end():]


def make_nonce() -> str:
    """응답별 CSP nonce."""
    return secrets.token_urlsafe(16)


def csp_header(nonce: str) -> str:
    """md 셸 응답용 Content-Security-Policy 값.

    script 는 nonce + jsdelivr 만 — 저작 md 에서 유래한 어떤 스크립트도
    (sanitize 를 뚫었다 가정해도) nonce 부재로 실행되지 않는다.
    img `*` 는 htm 문서와 동등한 표현력 유지(외부 이미지 허용) — 스크립트 실행면이 아님.
    """
    return (
        "default-src 'none'; "
        f"script-src 'nonce-{nonce}' https://cdn.jsdelivr.net; "
        "style-src 'unsafe-inline' https://cdn.jsdelivr.net; "
        "img-src * data: blob:; "
        "font-src https://cdn.jsdelivr.net data:; "
        "connect-src 'self'; "
        "base-uri 'none'; form-action 'self'; frame-ancestors *"
    )


# hub 문서 공통 look — _normalize_hub_body_css(전체 폭·표 넘침 차단)와 정합.
# 라이브 셸(M2)이 그대로 재사용한다.
SHELL_CSS = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body { font: 15px/1.65 -apple-system, system-ui, 'Apple SD Gothic Neo', sans-serif;
  margin: 0; padding: 0 1.4rem 3rem; color: #24292f; background: #ffffff; }
#md-root { max-width: 100%; }
h1, h2, h3, h4 { line-height: 1.3; margin: 1.6em 0 .6em; }
h1 { font-size: 1.55rem; border-bottom: 1px solid #d8dee4; padding-bottom: .3em; }
h2 { font-size: 1.3rem; border-bottom: 1px solid #e8ecef; padding-bottom: .25em; }
h3 { font-size: 1.12rem; }
a { color: #0969da; text-decoration: none; }
a:hover { text-decoration: underline; }
code { background: #f0f1f3; padding: .15em .4em; border-radius: 4px;
  font: .88em ui-monospace, 'SF Mono', Menlo, monospace; }
pre { background: #f6f8fa; border: 1px solid #e4e8ec; border-radius: 8px;
  padding: .9rem 1rem; overflow-x: auto; }
pre code { background: transparent; padding: 0; font-size: .86rem; }
pre.mermaid { background: transparent; border: none; text-align: center; }
table { border-collapse: collapse; margin: 1em 0; display: block;
  max-width: 100%; overflow-x: auto; }
th, td { border: 1px solid #d8dee4; padding: .35em .7em; }
th { background: #f6f8fa; }
blockquote { margin: 1em 0; padding: .2em 1em; border-left: 4px solid #d8dee4;
  color: #57606a; }
img { max-width: 100%; }
hr { border: none; border-top: 1px solid #d8dee4; margin: 1.6em 0; }
#md-fallback { white-space: pre-wrap; }
@media (prefers-color-scheme: dark) {
  body { color: #d7dde3; background: #1b1f24; }
  h1 { border-color: #333b45; } h2 { border-color: #2a323b; }
  a { color: #539bf5; }
  code { background: #2a313a; }
  pre { background: #22272e; border-color: #333b45; }
  th { background: #22272e; } th, td { border-color: #333b45; }
  blockquote { border-color: #333b45; color: #8b949e; }
  hr { border-color: #333b45; }
}
"""

# Issue569: hub mermaid 안전 렌더 — md 셸(RENDER_JS)과 htm 런타임(server.MERMAID_RUNTIME)이
#   **같은 한 벌**을 싣는다. 전역 window.hubMermaid = {quoteLabels, plan, run}.
#   저작 원문을 mermaid.run() 에 그대로 넘기면 라벨 글자 하나로 다이어그램 전체가
#   «Syntax error» 박스가 된다(prj3#Issue183·733, 본 이슈 — 세 번째). 그래서 파싱을 먼저 보고
#     ① 통과 → 원문 그대로 렌더 (유효한 다이어그램은 절대 건드리지 않는다)
#     ② 실패 → flowchart/graph 의 따옴표 없는 라벨을 "…" 로 감싼 보정본이 파싱되면 그것으로
#     ③ 그래도 실패 → 오류 박스 대신 원문 코드블록 + 오류 첫 줄
#   판정은 테스트가 파서 대역으로 돌릴 수 있게 DOM 과 분리한 순수 함수(plan)다.
#   ⚠️ 인라인 JS 0줄이 설계인 sh/fpm-htm-mermaid-normalize.py(file://·VSCode preview)는
#   이 보정을 실을 수 없다 — 서빙 경로(md 셸·htm)만 덮는다.
MERMAID_JS = r"""
(function () {
  'use strict';
  if (window.hubMermaid) return;

  // 여는 괄호 → 닫는 괄호. 긴 것부터 맞춰야 `((원))` 이 `(` 로 잘려 모양이 바뀌지 않는다
  var SHAPES = [['(((', ')))'], ['((', '))'], ['([', '])'], ['[[', ']]'], ['[(', ')]'],
    ['{{', '}}'], ['[', ']'], ['(', ')'], ['{', '}']];
  var ID = /^[A-Za-z0-9_]+/;
  // 라벨이 아닌 값(색·URL·클래스명)을 싣는 줄은 보정하지 않는다
  var SKIP_LINE = /^(%%|classDef\b|class\b|style\b|linkStyle\b|click\b)/;

  function isFlowchart(src) {
    var lines = src.split('\n');
    for (var i = 0; i < lines.length; i++) {
      var t = lines[i].trim();
      if (!t || t.indexOf('%%') === 0) continue;
      return /^(flowchart|graph)\b/.test(t);
    }
    return false;
  }

  // 한 줄에서 따옴표 없는 노드 라벨 `ID<열기>…<닫기>` 와 edge 라벨 `|…|` 를 "…" 로 감싼다.
  // 이미 따옴표인 구간은 통째로 건너뛰고, 라벨 안에 " 가 있으면(감쌀 수 없음) 그대로 둔다
  function quoteLine(line) {
    var out = '', i = 0, n = line.length;
    while (i < n) {
      var c = line.charAt(i);
      if (c === '"') {
        var q = line.indexOf('"', i + 1);
        if (q < 0) return out + line.slice(i);
        out += line.slice(i, q + 1); i = q + 1; continue;
      }
      if (c === '|') {
        var p = line.indexOf('|', i + 1);
        var lab = p > i ? line.slice(i + 1, p) : '';
        if (lab.trim() && lab.indexOf('"') < 0) { out += '|"' + lab + '"|'; i = p + 1; continue; }
        out += c; i++; continue;
      }
      var m = ID.exec(line.slice(i));
      // 앞 글자가 ID 문자·@ 면 노드 ID 의 시작이 아니다 (`e1@-->` 의 e1 등)
      if (m && !/[A-Za-z0-9_@]/.test(line.charAt(i - 1))) {
        var end = i + m[0].length, sh = null;
        for (var k = 0; k < SHAPES.length; k++) {
          if (line.substr(end, SHAPES[k][0].length) === SHAPES[k][0]) { sh = SHAPES[k]; break; }
        }
        var from = sh ? end + sh[0].length : -1;
        var to = sh && line.charAt(from) !== '"' ? line.indexOf(sh[1], from) : -1;
        var label = to > from ? line.slice(from, to) : '';
        if (label.trim() && label.indexOf('"') < 0) {
          out += line.slice(i, from) + '"' + label + '"' + sh[1];
          i = to + sh[1].length; continue;
        }
        out += m[0]; i = end; continue;
      }
      out += c; i++;
    }
    return out;
  }

  function quoteLabels(src) {
    if (!isFlowchart(src)) return src;
    return src.split('\n').map(function (line) {
      return SKIP_LINE.test(line.trim()) ? line : quoteLine(line);
    }).join('\n');
  }

  function firstLine(e) {
    return String((e && e.message) || e || 'parse error').split('\n')[0];
  }

  // 파서 결과를 «오류 첫 줄 | null» 로 정규화 — 동기 throw·reject·false(suppressErrors) 모두
  function tryParse(parse, text) {
    try {
      return Promise.resolve(parse(text)).then(function (r) {
        return r === false ? 'parse error' : null;
      }, firstLine);
    } catch (e) { return Promise.resolve(firstLine(e)); }
  }

  // 판정 — keep(원문) · heal(보정본) · fallback(원문 표시 + err)
  function plan(src, parse) {
    return tryParse(parse, src).then(function (err) {
      if (!err) return { mode: 'keep', text: src };
      var healed = quoteLabels(src);
      if (healed === src) return { mode: 'fallback', text: src, err: err };
      return tryParse(parse, healed).then(function (err2) {
        return err2 ? { mode: 'fallback', text: src, err: err } : { mode: 'heal', text: healed };
      });
    });
  }

  function dedent(s) {
    var lines = s.replace(/^\n+/, '').split('\n'), min = null;
    lines.forEach(function (l) {
      if (!l.trim()) return;
      var w = /^[ \t]*/.exec(l)[0].length;
      if (min === null || w < min) min = w;
    });
    if (min) lines = lines.map(function (l) { return l.slice(min); });
    return lines.join('\n').trim();
  }

  // mermaid.run 이 읽는 것과 같은 원문 — innerHTML 의 엔티티를 풀되 <br> 은 글자로 남긴다
  function srcOf(el) {
    var ta = document.createElement('textarea');
    ta.innerHTML = el.innerHTML.replace(/<br\s*\/?>/gi, '&lt;br/&gt;');
    return dedent(ta.value);
  }

  function showSource(el, text, err) {
    var box = document.createElement('div');
    box.className = 'mermaid-fallback';
    var note = document.createElement('div');
    note.className = 'mermaid-fallback-note';
    note.style.cssText = 'font-size:.82rem;color:#bf8700;margin:.3rem 0';
    note.textContent = '⚠ mermaid 구문 오류 — 원문을 표시합니다 · ' + err;
    var pre = document.createElement('pre');
    var code = document.createElement('code');
    code.textContent = text;
    pre.appendChild(code);
    box.appendChild(note);
    box.appendChild(pre);
    el.replaceWith(box);
  }

  // Issue245: 테마는 OS prefers-color-scheme 가 아니라 실제 페이지 배경 luminance 로
  function darkBg() {
    try {
      var c = getComputedStyle(document.body).backgroundColor || '';
      var m = c.match(/[0-9.]+/g);
      if (!m) return false;
      if (m.length > 3 && parseFloat(m[3]) === 0) return false;
      return (0.299 * +m[0] + 0.587 * +m[1] + 0.114 * +m[2]) < 128;
    } catch (e) { return false; }
  }

  function runOnce(root) {
    var mm = window.mermaid;
    if (!mm) return;
    try {
      mm.initialize({ startOnLoad: false, theme: darkBg() ? 'dark' : 'neutral' });
    } catch (e) { console.error('mermaid initialize failed', e); }
    // 노드는 호출 시점에 한 번만 잡는다 — 라이브 뷰는 블록마다 run() 을 부른다
    var nodes = [].filter.call((root || document).querySelectorAll('.mermaid'), function (el) {
      return !el.hasAttribute('data-processed') && !el.hasAttribute('data-hub-mmd');
    });
    if (!nodes.length) return;
    nodes.forEach(function (el) { el.setAttribute('data-hub-mmd', '1'); });
    if (typeof mm.parse !== 'function') return mm.run({ nodes: nodes });
    return Promise.all(nodes.map(function (el) {
      return plan(srcOf(el), function (t) { return mm.parse(t); }).then(function (r) {
        if (r.mode === 'fallback') { showSource(el, r.text, r.err); return null; }
        if (r.mode === 'heal') { el.textContent = r.text; el.setAttribute('data-hub-mmd', 'healed'); }
        return el;
      });
    })).then(function (els) {
      var ok = els.filter(Boolean);
      if (ok.length) return mm.run({ nodes: ok });
    });
  }

  // 호출을 직렬화한다 — 겹친 run 이 같은 노드를 두 번 그리거나 id 가 부딪히지 않게
  var chain = Promise.resolve();
  function run(root) {
    chain = chain.then(function () { return runOnce(root); })
      .catch(function (e) { console.error('mermaid run failed', e); });
    return chain;
  }

  window.hubMermaid = { quoteLabels: quoteLabels, plan: plan, run: run };
})();
"""

# md → DOM 렌더 파이프라인. 전역 window.hubRenderMd(el, mdText, docAbs) 1개 노출 —
# M1 아카이브 셸은 1회 호출, M2 라이브 셸은 완결 블록 append 시마다 호출한다.
RENDER_JS = """
(function () {
  'use strict';
  var ALLOWED_TAGS = ['p','h1','h2','h3','h4','h5','h6','ul','ol','li','pre','code',
    'table','thead','tbody','tr','th','td','blockquote','strong','b','em','i','del',
    'hr','br','a','img','span','div','sup','sub','input','details','summary'];
  var ALLOWED_ATTR = ['href','src','alt','title','class','type','checked','disabled',
    'align','start','colspan','rowspan'];
  // 기본 스킴 + vscode (Issue201 파일 링크). javascript:·data: 는 비허용 유지.
  var ALLOWED_URI_REGEXP = /__ALLOWED_URI_REGEXP__/i;

  // 상대 이미지 → /htm-res 재작성 (server._rewrite_relative_imgs 와 동일 규칙:
  // data:/http(s):/루트(/)·프로토콜 상대(//)는 미변경, 클라 렌더라 서버 재작성이
  // 못 보는 md 유래 <img> 를 여기서 흡수)
  function rewriteImgs(root, docAbs) {
    if (!docAbs) return;
    var docQ = encodeURIComponent(docAbs);
    root.querySelectorAll('img[src]').forEach(function (img) {
      var src = img.getAttribute('src') || '';
      var low = src.toLowerCase();
      if (!src || /^(data:|https?:|\\/\\/|\\/)/.test(low)) return;
      if (low.indexOf('file:') === 0) {
        try {
          var p = new URL(src);
          if (p.hostname && p.hostname !== 'localhost') return;
          img.setAttribute('src', '/htm-res?doc=' + docQ + '&abs='
            + encodeURIComponent(decodeURIComponent(p.pathname)));
        } catch (e) { /* 원형 유지 */ }
        return;
      }
      img.setAttribute('src', '/htm-res?doc=' + docQ + '&rel=' + encodeURIComponent(src));
    });
  }

  // ```mermaid 코드펜스 → <pre class="mermaid"> 승격 (Issue256 서버 규칙의 클라 판)
  function promoteMermaid(root) {
    var found = false;
    root.querySelectorAll('pre > code.language-mermaid').forEach(function (code) {
      var pre = code.parentElement;
      var holder = document.createElement('pre');
      holder.className = 'mermaid';
      holder.textContent = code.textContent;
      pre.replaceWith(holder);
      found = true;
    });
    return found;
  }

  window.hubRenderMd = function (el, mdText, docAbs) {
    // graceful degradation — CDN 실패 시 원문 평문 노출 (fail-soft)
    if (!window.marked || !window.DOMPurify) {
      var pre = document.createElement('pre');
      pre.id = 'md-fallback';
      pre.textContent = mdText;
      el.appendChild(pre);
      return;
    }
    var raw = window.marked.parse(mdText, { gfm: true, breaks: false });
    var clean = window.DOMPurify.sanitize(raw, {
      ALLOWED_TAGS: ALLOWED_TAGS, ALLOWED_ATTR: ALLOWED_ATTR,
      ALLOW_DATA_ATTR: false, ALLOWED_URI_REGEXP: ALLOWED_URI_REGEXP
    });
    var frag = document.createElement('div');
    frag.innerHTML = clean;
    rewriteImgs(frag, docAbs);
    var hasMermaid = promoteMermaid(frag);
    el.appendChild(frag);
    if (window.hljs) {
      el.querySelectorAll('pre code[class*="language-"]').forEach(function (b) {
        try { window.hljs.highlightElement(b); } catch (e) { /* no-op */ }
      });
    }
    // 공용 MERMAID_JS(Issue569) — 파싱 선검사·라벨 보정·원문 폴백
    if (hasMermaid && window.hubMermaid) window.hubMermaid.run();
  };
})();
"""

# 정규식은 파이썬 상수가 단일 출처 — 테스트가 같은 값을 `re` 로 직접 검증한다
# (JS 리터럴에 하드코딩하면 테스트와 실제 주입값이 갈릴 수 있다).
RENDER_JS = RENDER_JS.replace("__ALLOWED_URI_REGEXP__", ALLOWED_URI_REGEXP)
# 같은 <script nonce> 안에서 hubRenderMd 보다 먼저 정의되게 앞에 붙인다
RENDER_JS = MERMAID_JS + RENDER_JS


# Issue542: 세션 버튼 에디터 메타 — 아이콘(/editor-icon/<ed>.png)이 404 면 emoji 로 폴백
_EDITOR_META = {"vscode": ("VSCode", "\U0001F19A"), "zed": ("Zed", "\U0001F169")}

# Issue542: 헤더 클릭 바인딩. md/라이브 셸 CSP 는 `script-src 'nonce-…'` 라 인라인 onclick·
#   onerror 가 **차단**된다(종전 🆚 세션·📁 배지가 무동작이던 원인) → nonce 스크립트로 붙인다.
#   ⚠️ 본문에 `<` 를 쓰지 말 것 — 테스트가 `<script nonce>…open-session` 한 덩어리로 찾는다.
HEADER_JS = """(function(){
var h=document.querySelector('header');if(!h)return;
function post(u,b){return fetch(u,{method:'POST',headers:{'Content-Type':'application/json'},
body:JSON.stringify(b)}).then(function(r){return r.json().then(function(j){
if(!r.ok)throw new Error(j.error||('HTTP '+r.status));return j;});});}
var pb=h.querySelector('.proj-badge[data-cwd]');
if(pb)pb.addEventListener('click',function(e){e.preventDefault();
post('/open-project',{cwd:pb.dataset.cwd}).then(function(j){if(j.uri)window.location.href=j.uri;})
.catch(function(err){alert('프로젝트 열기 실패: '+err.message);});});
var sl=h.querySelector('.sess-link[data-sid]');if(!sl)return;
var ico=sl.querySelector('img.sess-ico');
function fb(){if(ico&&ico.parentNode){ico.replaceWith(document.createTextNode(ico.dataset.fallback||''));ico=null;}}
if(ico){ico.addEventListener('error',fb);if(ico.complete&&ico.naturalWidth===0)fb();}
sl.addEventListener('click',function(e){e.preventDefault();
post('/open-session',{cwd:sl.dataset.cwd,sid:sl.dataset.sid}).then(function(j){
if(j.uri){if(j.folder_uri){try{window.open(j.folder_uri);}catch(_){}}window.location.href=j.uri;}})
.catch(function(err){alert('세션 이동 실패: '+err.message);});});
})();"""


def render_header(title: str, proj_cwd: str, proj_label: str, sid: str = "",
                  editor: str = "vscode", can_open: bool = True) -> str:
    """canonical hub 헤더 마크업 (`_synthesize_hub_header` 와 동일 구조·클래스).

    htm 경로는 저작 문서에 헤더가 없을 때 서버가 첫 `<h1>` 을 승격해 합성하지만,
    md 셸은 serve 시점 본문이 비어 있어(클라이언트가 렌더) 그 방식을 쓸 수 없다 —
    셸이 헤더를 직접 갖는다. 클래스는 shim 계약(`.header-actions`·`.hub-link`·
    `.sess-link`·`.close-btn`)을 그대로 지켜 COPY_LINK/SID_COPY/HUB_LINK/CLOSE
    shim 이 htm 문서와 동일하게 동작한다. CSS 는 서버가 `HUB_HEADER_CSS` 를 주입.

    Issue542: 세션 버튼은 `editor`·`can_open`(서버 `_session_open_mode` 판정)으로 갈린다 —
    열 수 있으면 [아이콘 열기], 없으면(zed·terminal) [아이콘]만이고 클릭은 앱 포커스.
    클릭 동작은 인라인 핸들러가 아니라 `HEADER_JS`(nonce)가 `data-*` 를 읽어 붙인다.
    """
    label = html.escape(proj_label or "project")
    cwd_esc = html.escape(proj_cwd or "")
    sess = ""
    if sid:
        sid_esc = html.escape(sid)
        ed = editor if editor in _EDITOR_META else "vscode"
        ed_name, ed_emoji = _EDITOR_META[ed]
        tip = (f"{ed_name} 에서 이 세션 열기" if can_open
               else f"{ed_name} 앱으로 이동 (세션 직접 열기 미지원)")
        text = " 열기" if can_open else ""
        sess = (
            f'    <a class="sess-link" href="#" title="{tip}" data-sid="{sid_esc}" '
            f'data-cwd="{cwd_esc}" data-editor="{ed}" data-open="{1 if can_open else 0}">'
            f'<img class="sess-ico" src="/editor-icon/{ed}.png" alt="{ed_name}" '
            f'data-fallback="{ed_emoji}" style="height:1.1em;vertical-align:-0.2em;">'
            f"{text}</a>\n"
        )
    return (
        "<header>\n"
        '  <a class="hub-link" href="/hub" target="fpm-hub" title="통합 모니터링 Hub">'
        '<img src="/fpm-icon.png" alt="Hub" style="height:1.2em;vertical-align:-0.25em;"></a>\n'
        f"  <h1>{html.escape(title or 'hub md doc')}</h1>\n"
        '  <nav class="header-actions">\n'
        f'    <a class="proj-badge" href="#" title="클릭 → 에디터로 {label} 열기" '
        f'data-cwd="{cwd_esc}">\U0001F4C1 {label}</a>\n'
        f"{sess}"
        '    <button type="button" class="close-btn" title="이 문서 탭 닫기" '
        'onclick="window.close()">✕</button>\n'
        "  </nav>\n"
        "</header>"
    )


LIVE_CSS = """
#live-status { display: flex; align-items: center; gap: .6rem; flex-wrap: wrap;
  padding: .5rem 0 .2rem; color: #57606a; font-size: .85rem; }
#live-dot { width: .6rem; height: .6rem; border-radius: 50%; background: #57606a;
  flex: 0 0 auto; }
#live-dot.on { background: #1a7f37; animation: livepulse 1.4s ease-in-out infinite; }
#live-dot.err { background: #cf222e; animation: none; }
@keyframes livepulse { 0%,100% { opacity: 1 } 50% { opacity: .25 } }
.turn { border: 1px solid #d8dee4; border-radius: 10px; margin: 1rem 0;
  overflow: hidden; }
.turn-head { background: #f6f8fa; padding: .55rem .9rem; font-size: .9rem;
  display: flex; gap: .5rem; align-items: baseline; }
.turn-head .q { font-weight: 600; overflow-wrap: anywhere; }
.turn-head .n { color: #57606a; font-size: .8rem; flex: 0 0 auto; }
.turn-body { padding: .2rem 1rem 1rem; }
.turn.latest { border-color: #0969da; box-shadow: 0 0 0 1px rgba(9,105,218,.18); }
.turn.folded .turn-body { display: none; }
.turn.folded .turn-head { cursor: pointer; }
.act { display: inline-flex; align-items: center; gap: .35rem; font-size: .82rem;
  color: #57606a; background: #f0f1f3; border-radius: 999px;
  padding: .1rem .6rem; margin: .15rem .3rem .15rem 0; }
.pending { color: #57606a; white-space: pre-wrap; opacity: .75;
  border-left: 3px solid #d8dee4; padding-left: .7rem; margin: .5rem 0; }
.unit { margin: .5rem 0; }
.unit-head { cursor: pointer; user-select: none; font-size: .82rem; color: #57606a;
  display: flex; gap: .45rem; align-items: center; }
.unit-head::before { content: "▾"; width: .8rem; flex: 0 0 auto; }
.unit.folded > .unit-head::before { content: "▸"; }
.unit.folded > .unit-body { display: none; }
.unit.log > .unit-body { border-left: 2px solid #d8dee4; padding-left: .7rem; }
.doc-inline { border-left: 3px solid #0969da; padding: .2rem 0 .2rem .9rem; margin: .7rem 0; }
.doc-inline .doc-link { font-size: .82rem; color: #0969da; text-decoration: none; }
#form-slot { margin: .8rem 0 0; }
.form-card { border: 2px solid #bf8700; border-radius: 10px; overflow: hidden;
  background: #fff8e5; }
.form-card > .fc-head { padding: .5rem .9rem; font-size: .9rem; font-weight: 600;
  color: #7a5c00; display: flex; gap: .5rem; align-items: center; }
.form-card iframe { width: 100%; border: 0; display: block; background: #fff; }
@media (prefers-color-scheme: dark) {
  .form-card { border-color: #9e6a03; background: #2b2410; }
  .form-card > .fc-head { color: #e3b341; }
  .form-card iframe { background: #1b1f24; }
}
@media (prefers-color-scheme: dark) {
  #live-status { color: #8b949e; }
  .turn { border-color: #333b45; } .turn-head { background: #22272e; }
  .turn.latest { border-color: #539bf5; }
  .act { background: #2a313a; color: #adbac7; }
  .pending { border-color: #333b45; color: #8b949e; }
  .doc-inline { border-color: #539bf5; } .doc-inline .doc-link { color: #539bf5; }
  .unit-head { color: #8b949e; } .unit.log > .unit-body { border-color: #333b45; }
}
"""

# 메일박스 폴러 + 증분 append 렌더. `hubRenderMd` 를 그대로 쓴다 —
# 아카이브 셸과 라이브 셸이 같은 렌더 경로를 공유해야 표현이 갈리지 않는다.
#
# ⚠️ 이 문자열은 **브라우저로 전송된다** — 설계 이력·결정 배경은 여기(파이썬 주석)에
# 적고 JS 본문에는 넣지 않는다.
#
# 미완결 꼬리 프리뷰는 두지 않는다(Issue357): 메일박스가 **완결 블록만** 내보내므로
# "생성 중인 절반짜리 블록"이 클라이언트에 도착하지 않는다 — 표시할 대상 자체가 없다.
# tail 이 완결 라인까지만 커서를 전진시키는 구조라 그 정보는 서버에도 없으며, 되살리려면
# 메일박스가 미완결 꼬리를 별도 kind 로 내보내는 설계부터 필요하다.
LIVE_JS = """
(function () {
  'use strict';
  var CFG = JSON.parse(document.getElementById('live-cfg').textContent);
  var root = document.getElementById('live-root');
  var dot = document.getElementById('live-dot');
  var stat = document.getElementById('live-text');
  var since = 0, epoch = '', curTurn = null;
  var timer = null, errCount = 0;
  var FAST = 1000, SLOW = 5000, HIDDEN = 15000;

  var degraded = false;   // 강등되면 상태·폴링을 되살리지 않는다(아래 가드가 유일 출구)

  function setStatus(cls, text) {
    // 강등 이후 도착하는 정상 경로 갱신이 강등 문구를 덮지 않게 한다 —
    // 사용자가 "왜 멈췄는지" 읽을 수 있어야 하고, 되살아난 것처럼 보여도 안 된다
    if (degraded && cls !== 'err') return;
    dot.className = cls;
    stat.textContent = text;
  }

  function fmtTs(ts) {
    // 블록이 실어 온 원본 시각(JSONL timestamp)이 1순위다. 현재 시각으로 찍으면
    // 재동기화 때 과거 블록이 전부 같은 초로 보여, 시각이 서로 다른 기록이
    // «방금 한꺼번에 쏟아진 중복» 으로 읽힌다.
    var d = ts ? new Date(ts) : null;
    if (!d || isNaN(d.getTime())) d = new Date();
    return d.toLocaleTimeString();
  }

  function newTurn(question, ts) {
    [].forEach.call(root.querySelectorAll('.turn'), function (t) {
      t.classList.remove('latest');
      t.classList.add('folded');
    });
    var d = document.createElement('div');
    d.className = 'turn latest';
    var head = document.createElement('div');
    head.className = 'turn-head';
    var q = document.createElement('span');
    q.className = 'q';
    q.textContent = question || '(진행 중)';
    var n = document.createElement('span');
    n.className = 'n';
    n.textContent = fmtTs(ts);
    head.appendChild(q); head.appendChild(n);
    head.addEventListener('click', function () { d.classList.toggle('folded'); });
    var body = document.createElement('div');
    body.className = 'turn-body';
    d.appendChild(head); d.appendChild(body);
    root.appendChild(d);
    curTurn = body;
    return body;
  }

  function body(ts) { return curTurn || newTurn('', ts); }

  function unit(tb, cls, folded) {
    var u = document.createElement('div');
    u.className = 'unit ' + cls + (folded ? ' folded' : '');
    var h = document.createElement('div');
    h.className = 'unit-head';
    var c = document.createElement('div');
    c.className = 'unit-body';
    h.addEventListener('click', function (e) {
      if (e.target && e.target.tagName === 'A') return;
      u.classList.toggle('folded');
    });
    u.appendChild(h); u.appendChild(c);
    tb.appendChild(u);
    return {u: u, h: h, c: c};
  }

  // 텍스트·도구 칩이 이어지는 구간을 로그 단위 하나로 묶는다. 문서가 나온 턴에서는 접힌 채 시작한다
  function logBody(ts) {
    var tb = body(ts);
    if (!tb._log) {
      tb._log = unit(tb, 'log', !!tb._hasDoc);
      tb._log.n = 0;
    }
    tb._log.n += 1;
    tb._log.h.textContent = '로그 · ' + tb._log.n;
    return tb._log.c;
  }

  function applyBlock(b) {
    if (b.kind === 'turn') { newTurn(b.text, b.ts); return; }
    if (b.kind === 'doc') { applyDoc(b); return; }
    if (b.kind === 'activity') {
      var a = document.createElement('span');
      a.className = 'act';
      a.textContent = '\\u26a1 ' + b.text;
      logBody(b.ts).appendChild(a);
      // 활동 칩도 DOM 을 늘린다 — 도구 호출이 많은 턴에서는 텍스트 블록보다
      // 이쪽이 훨씬 자주 오므로 여기서도 열화를 본다(텍스트에서만 보면 늦게 잡힌다)
      checkDegrade(0);
      return;
    }
    // 완결 블록만 도착하므로 append 렌더 (매 poll 전체 재파싱 금지)
    var holder = document.createElement('div');
    logBody(b.ts).appendChild(holder);
    var t0 = (window.performance && performance.now) ? performance.now() : 0;
    window.hubRenderMd(holder, b.text, '');
    if (t0) checkDegrade(performance.now() - t0);
  }

  // 세션이 만든 hub 문서 — 새 탭 대신 이 창 안에 펼친다
  function applyDoc(b) {
    var tb = body(b.ts);
    // 문서가 이 턴의 본문이다 — 앞선 로그 단위는 접고, 뒤에 오는 로그도 접힌 채 시작한다
    tb._hasDoc = true;
    tb._log = null;
    [].forEach.call(tb.querySelectorAll('.unit.log'), function (u) { u.classList.add('folded'); });
    var d = unit(tb, 'doc doc-inline', false);
    var link = document.createElement('a');
    link.className = 'doc-link';
    link.href = '/md-doc?path=' + encodeURIComponent(b.text);
    link.target = '_blank';
    link.textContent = '\\ud83d\\udcc4 ' + b.text.split('/').pop();
    d.h.appendChild(link);
    var holder = document.createElement('div');
    d.c.appendChild(holder);
    // Write 기록은 파일이 실제로 써지기 전에 도착할 수 있다 — 짧게 몇 번 다시 묻는다
    var tries = 0;
    function load() {
      tries += 1;
      fetch(CFG.docRaw + encodeURIComponent(b.text), { cache: 'no-store' })
        .then(function (r) { return r.ok ? r.json() : null; })
        .catch(function () { return null; })
        .then(function (j) {
          if (j && typeof j.md === 'string') { show(j); return; }
          if (tries < 6) { setTimeout(load, 1500); return; }
          holder.textContent = '(문서를 불러오지 못함 — 위 링크로 열기)';
        });
    }
    function show(j) {
      var md = j.md.replace(/^---\\r?\\n[\\s\\S]*?\\r?\\n---\\r?\\n/, '');
      var stick = atBottom();
      var t0 = (window.performance && performance.now) ? performance.now() : 0;
      window.hubRenderMd(holder, md, j.path || b.text);
      if (t0) checkDegrade(performance.now() - t0);
      if (stick) toBottom();
    }
    load();
  }

  // 시간순(아래가 최신)이므로, 사용자가 맨 아래를 보고 있을 때만 새 내용을 따라간다
  function atBottom() {
    var de = document.documentElement;
    if (!de) return false;
    return (window.innerHeight + window.scrollY) >= de.scrollHeight - 120;
  }
  function toBottom() {
    var de = document.documentElement;
    if (de && window.scrollTo) window.scrollTo(0, de.scrollHeight);
  }

  function reset() {
    root.innerHTML = '';
    since = 0; curTurn = null;
  }

  function schedule() {
    if (timer) clearTimeout(timer);
    if (degraded) return;   // 강등 후에는 다시 폴링하지 않는다
    var d = document.hidden ? HIDDEN : (errCount ? SLOW : FAST);
    timer = setTimeout(poll, d);
  }

  // 미응답 폼 — 라이브 뷰 상단에 카드로 띄운다. "클릭이 곧 응답"
  // 멱등은 서버 inbox 1회 소비가 유일한 중재자다(터미널·타 탭에서 먼저 답하면
  // 다음 poll 에서 pending_form 이 사라져 카드가 자동으로 닫힌다).
  var slot = document.getElementById('form-slot');
  var shownForm = '';
  function applyForm(pf) {
    var key = pf ? pf.form_ts : '';
    if (key === shownForm) return;
    shownForm = key;
    slot.innerHTML = '';
    if (!pf) return;
    var card = document.createElement('div');
    card.className = 'form-card';
    var head = document.createElement('div');
    head.className = 'fc-head';
    head.textContent = '\\u2753 ' + (pf.title || '응답 대기 중인 질문');
    var f = document.createElement('iframe');
    f.src = pf.url;
    f.setAttribute('title', '질문 폼');
    f.style.height = '420px';
    card.appendChild(head); card.appendChild(f);
    slot.appendChild(card);
  }

  function poll() {
    var url = CFG.mail + '&since=' + since + (epoch ? '&epoch=' + encodeURIComponent(epoch) : '')
      + '&form=' + encodeURIComponent(shownForm);
    fetch(url, { cache: 'no-store' }).then(function (r) {
      if (r.status === 304) {
        // 폼이 떠 있는 동안은 304 여도 '응답 대기' 를 유지한다 — 사용자가 지금
        // 해야 할 일이 있다는 신호를 폴링 상태 문구가 덮어써서는 안 된다
        errCount = 0;
        setStatus('on', shownForm ? '응답 대기' : '대기 중');
        return null;
      }
      if (r.status === 205) {
        return r.json().then(function (j) {
          epoch = j.epoch || ''; reset();
          setStatus('on', '재동기화');
          return null;
        });
      }
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    }).then(function (j) {
      errCount = 0;
      if (j) {
        epoch = j.epoch || epoch;
        var stick = since === 0 || atBottom();
        (j.blocks || []).forEach(applyBlock);
        if (stick && (j.blocks || []).length) toBottom();
        since = j.max_seq || since;
        applyForm(j.pending_form || null);
        setStatus('on', j.pending_form ? '응답 대기'
          : (j.turn_active ? '수신 중' : '대기 중'));
      }
    }).catch(function (e) {
      errCount++;
      setStatus('err', '서버 미응답 — 재시도 중 (' + errCount + ')');
    }).then(schedule);
  }

  // 열화 감지 → 자동 강등 (display: 'auto' 일 때만)
  //   live    = 라이브 상시 — 강등하지 않는다(사용자가 명시 선택했으므로 존중)
  //   archive = 애초에 라이브 뷰를 쓰지 않는 모드 — 이 셸이 열릴 일 자체가 드물다
  //   auto    = 라이브로 시작하되 브라우저가 열화를 보고하면 archive 로 물러난다
  // 라이브 뷰는 append-only 라 장시간 켜 두면 DOM 이 단조 증가한다. 브라우저가
  // 실제로 느려지기 시작하면 스스로 물러나는 편이 낫다 — 강등은 "이 탭은 더 이상
  // 자라지 않고, 이후 턴은 아카이브 문서로 본다"는 뜻이며 데이터 유실은 없다
  // (진실은 transcript 파일이고 아카이브 md 는 별도 생성된다).
  function checkDegrade(renderMs) {
    if (degraded || CFG.display !== 'auto') return;
    var nodes = document.getElementsByTagName('*').length;
    var heapPct = 0;
    try {
      var m = window.performance && window.performance.memory;
      if (m && m.jsHeapSizeLimit) heapPct = 100 * m.usedJSHeapSize / m.jsHeapSizeLimit;
    } catch (e) { /* 비크로미움 — 노드 수·렌더 시간만으로 판정 */ }
    var why = null;
    if (nodes > CFG.degrade.nodes) why = 'DOM 노드 ' + nodes;
    else if (renderMs > CFG.degrade.renderMs) why = '렌더 ' + Math.round(renderMs) + 'ms';
    else if (heapPct > CFG.degrade.heapPct) why = '힙 ' + Math.round(heapPct) + '%';
    if (!why) return;
    degraded = true;
    if (timer) clearTimeout(timer);
    // 서버에 강등 사실을 알린다 — 훅이 다음 턴부터 archive 경로로 열도록(Issue356_1).
    // 실패해도 무시한다: 이 탭의 강등 자체는 이미 성립했고, 통보는 부가 최적화다.
    try {
      fetch(CFG.degradeReport, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({sid: CFG.sid, reason: why})
      }).catch(function () {});
    } catch (e) { /* no-op */ }
    setStatus('err', '표시 강등 — ' + why + ' · 이후 턴은 아카이브 문서로 열립니다');
    var note = document.createElement('div');
    note.className = 'pending';
    note.textContent = '라이브 갱신을 중지했습니다(' + why + '). '
      + '새로고침하면 최신 상태로 다시 시작합니다.';
    root.insertBefore(note, root.firstChild);
  }

  document.addEventListener('visibilitychange', function () {
    if (!document.hidden && !degraded) poll();
  });
  // 창이 닫히면 서버에 알린다 — 다음 문서가 이 창을 믿고 탭을 건너뛰지 않게
  window.addEventListener('pagehide', function () {
    try { navigator.sendBeacon(CFG.bye, ''); } catch (e) {}
  });
  setStatus('on', '연결 중');
  poll();
})();
"""


def render_live_shell(title: str, proj_cwd: str, proj_label: str, sid: str,
                      cwd_hash: str, token: str, nonce: str,
                      display: str = "auto", degrade: dict = None,
                      editor: str = "vscode", can_open: bool = True) -> bytes:
    """Issue353_2 M2-c: 라이브 뷰 셸 — 아카이브 셸과 **동일한 CSS·렌더 파이프라인**.

    `SHELL_CSS` 와 `RENDER_JS`(`window.hubRenderMd`)를 그대로 재사용하고 라이브 전용
    CSS·폴러만 덧댄다. 셸을 2벌로 만들면 스타일 드리프트가 서버 안에서 재발한다.
    """
    t = html.escape(title or "라이브 세션")
    header = render_header(title, proj_cwd, proj_label, sid, editor, can_open)
    degrade = degrade or {}
    cfg = json.dumps({
        "mail": f"/s/{cwd_hash}/{sid}/mail?token={token}",
        "degradeReport": f"/s/{cwd_hash}/{sid}/degrade?token={token}",
        # Issue532: 인라인 문서 원문(/md-doc 화이트리스트 동일) · 닫힘 beacon
        "docRaw": "/md-doc?raw=1&path=",
        "bye": f"/s/{cwd_hash}/{sid}/bye?token={token}",
        "sid": sid,
        "display": display,
        "degrade": {
            "nodes": int(degrade.get("nodes", 12000)),
            "renderMs": int(degrade.get("render_ms", 400)),
            "heapPct": int(degrade.get("heap_pct", 85)),
        },
    }).replace("<", "\\u003c")
    page = f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{t}</title>
<link rel="stylesheet" href="{CDN_HLJS_CSS}" media="(prefers-color-scheme: light)">
<link rel="stylesheet" href="{CDN_HLJS_CSS_DARK}" media="(prefers-color-scheme: dark)">
<style>{SHELL_CSS}{LIVE_CSS}</style>
</head>
<body>
{header}
<div id="live-status"><span id="live-dot"></span><span id="live-text">연결 중</span></div>
<div id="form-slot"></div>
<div id="live-root"></div>
<script type="application/json" id="live-cfg">{cfg}</script>
<script src="{CDN_MARKED}"></script>
<script src="{CDN_PURIFY}"></script>
<script src="{CDN_HLJS}"></script>
<script src="{CDN_MERMAID}"></script>
<script nonce="{nonce}">{RENDER_JS}</script>
<script nonce="{nonce}">{HEADER_JS}</script>
<script nonce="{nonce}">{LIVE_JS}</script>
</body>
</html>"""
    return page.encode("utf-8")


def render_md_shell(md_text: str, title: str, doc_abs: str, nonce: str,
                    proj_cwd: str = "", proj_label: str = "",
                    editor: str = "vscode", can_open: bool = True) -> bytes:
    """md 아카이브 문서용 완성 셸 HTML.

    md 원문은 JSON 문자열(`<` 이스케이프)로만 실린다 — serve 시점 마크업 불가침.
    frontmatter 는 본문에서 분리한다(marked 가 YAML 을 모르므로 떼지 않으면
    `title: …` 이 본문 첫 헤딩으로 렌더된다). `title`/`sid` 는 헤더 재료로 쓴다.
    """
    meta, body_md = split_frontmatter(md_text)
    title = title or meta.get("title") or meta.get("name") or "hub md doc"
    md_json = json.dumps(body_md)
    # JSON 문자열이 </script> 로 스크립트 블록을 깨지 못하게 < 를 전부 이스케이프
    md_json = md_json.replace("<", "\\u003c")
    t = html.escape(title)
    doc_json = json.dumps(doc_abs).replace("<", "\\u003c")
    header = render_header(title, proj_cwd, proj_label, meta.get("sid", ""), editor, can_open)
    page = f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{t}</title>
<link rel="stylesheet" href="{CDN_HLJS_CSS}" media="(prefers-color-scheme: light)">
<link rel="stylesheet" href="{CDN_HLJS_CSS_DARK}" media="(prefers-color-scheme: dark)">
<style>{SHELL_CSS}</style>
</head>
<body>
{header}
<div id="md-root"></div>
<script type="application/json" id="md-src">{md_json}</script>
<script type="application/json" id="md-meta">{doc_json}</script>
<script src="{CDN_MARKED}"></script>
<script src="{CDN_PURIFY}"></script>
<script src="{CDN_HLJS}"></script>
<script src="{CDN_MERMAID}"></script>
<script nonce="{nonce}">{RENDER_JS}</script>
<script nonce="{nonce}">{HEADER_JS}</script>
<script nonce="{nonce}">
(function () {{
  var md = JSON.parse(document.getElementById('md-src').textContent);
  var docAbs = JSON.parse(document.getElementById('md-meta').textContent);
  window.hubRenderMd(document.getElementById('md-root'), md, docAbs);
}})();
</script>
</body>
</html>"""
    return page.encode("utf-8")
