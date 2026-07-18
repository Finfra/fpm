#!/usr/bin/env python3
"""fpm-htm-mermaid-normalize — hub a모드 htm 의 mermaid 런타임을 canonical 형태로 정규화.

prj3 Issue244: hub a모드 htm 은 Claude 가 매 렌더 손으로 저작하므로 `commands/fpm-hub.md`
  의 UMD 2줄 규정을 반복 이탈했다(Issue82 → Issue190 산문 강화 후에도 2026-07-18 하루 2건
  재발). 서버측 정규화(`services/hub/server.py::_normalize_mermaid_runtime`)는 hub 서빙
  경로만 덮으므로 `file://`·VSCode preview 로 여는 순간 이탈이 그대로 노출된다.
  본 스크립트는 **쓰기 시점**에 디스크 파일 자체를 정규화하여, 저작 준수 여부와 무관하게
  산출물이 항상 canonical 이 되게 한다.

canonical = 인라인 JS 0줄 + 외부 UMD 1줄:

    <script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>

  mermaid@11 UMD 는 `startOnLoad` 기본 true + `window.addEventListener("load", contentLoaded)`
  훅을 번들에 내장하므로 초기화 코드가 불필요하다(dist 실측). 인라인이 0줄이면 인라인
  `<script>` 를 차단하는 CSP(VSCode HTML preview: `script-src https:` — `'unsafe-inline'`
  없음)에서도 렌더되어 file:// · VSCode preview · hub 서빙 3경로 전부를 만족한다.

사용:
    fpm-htm-mermaid-normalize.py <file.htm> [...]      # in-place 정규화
    fpm-htm-mermaid-normalize.py --check <file.htm>    # 변경 필요 여부만 판정(rc=1 이면 이탈)

exit code: 0 = 정상(또는 변경 완료) / 1 = --check 에서 이탈 검출 / 2 = 사용법·IO 오류
"""

import html as _html
import re
import sys

# canonical 런타임 — 인라인 0줄. 이탈 시 이 1줄로 치환된다.
CANONICAL_RUNTIME = (
    b'<script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>'
)

_SCRIPT_RE = re.compile(rb"<script\b[^>]*>.*?</script>", re.IGNORECASE | re.DOTALL)
_BODY_END_RE = re.compile(rb"</body\s*>", re.IGNORECASE)
_COMMENT_RE = re.compile(rb"<!--.*?-->", re.DOTALL)

# 첫 유의미 라인이 아래 키워드일 때만 mermaid 코드블록으로 판정 — 일반 코드블록 오탐 억제.
_MERMAID_KEYWORDS = (
    "sequenceDiagram", "classDiagram", "stateDiagram-v2", "stateDiagram",
    "erDiagram", "flowchart", "graph", "journey", "gantt", "pie",
    "gitGraph", "mindmap", "timeline", "quadrantChart", "requirementDiagram",
    "C4Context", "sankey-beta", "xychart-beta", "block-beta",
)
_CODEBLOCK_RE = re.compile(
    rb"<pre\b[^>]*>\s*<code\b[^>]*>(.*?)</code>\s*</pre>", re.IGNORECASE | re.DOTALL
)


def looks_like_mermaid(inner_text):
    for line in inner_text.splitlines():
        t = line.strip()
        if not t or t.startswith("%%"):  # 공백·directive/comment 스킵
            continue
        first = t.split(None, 1)[0]
        return any(first == k or first.startswith(k) for k in _MERMAID_KEYWORDS)
    return False


def rewrite_codeblocks(body):
    r"""`<pre><code>` 로 저작된 mermaid 코드펜스를 `<pre class="mermaid">` 로 재작성.

    엔티티(`&gt;`·`&lt;`)는 유지 — 브라우저 textContent 가 `-->`·`<` 로 복원해 mermaid 가
    올바로 파싱한다. 단 라벨 줄바꿈 의도의 리터럴 `\n` 은 `&lt;br/&gt;` 로 치환한다.
    """
    def _sub(m):
        inner = m.group(1)
        text = _html.unescape(inner.decode("utf-8", "replace"))
        if not looks_like_mermaid(text):
            return m.group(0)
        return b'<pre class="mermaid">' + inner.replace(rb"\n", b"&lt;br/&gt;") + b"</pre>"

    return _CODEBLOCK_RE.sub(_sub, body)


def normalize(body):
    """mermaid 블록이 있으면 저작 런타임을 걷어내고 canonical 1줄로 치환."""
    body = rewrite_codeblocks(body)
    if b'class="mermaid"' not in body:
        return body  # 다이어그램 없는 문서 — 손대지 않음

    # 기존 mermaid 관련 <script>(esm/umd·버전·인라인 init 무관) 일괄 제거.
    # HTML 주석은 먼저 마스킹한다 — 주석·산문 안의 리터럴 `<script>` 문자열이
    # `_SCRIPT_RE` 에 걸리면 주석 시작부터 뒤쪽 실제 `</script>` 까지가 한 매치로
    # 잡혀 그 구간 본문이 통째로 삭제된다(실측 검출).
    comments = []

    def _mask(m):
        comments.append(m.group(0))
        return b"\x00FPMC%d\x00" % (len(comments) - 1)

    body = _COMMENT_RE.sub(_mask, body)
    body = _SCRIPT_RE.sub(
        lambda m: b"" if b"mermaid" in m.group(0).lower() else m.group(0), body
    )
    for i, c in enumerate(comments):
        body = body.replace(b"\x00FPMC%d\x00" % i, c)

    # 삽입 지점 직전 공백을 rstrip 후 재구성 — 제거된 <script> 자리의 잔여 개행이
    # 매 실행마다 누적되어 멱등성이 깨지는 것을 막는다(정규화 결과가 fixed point).
    m = _BODY_END_RE.search(body)
    if m:
        head = body[: m.start()].rstrip()
        return head + b"\n" + CANONICAL_RUNTIME + b"\n" + body[m.start():]
    return body.rstrip() + b"\n" + CANONICAL_RUNTIME + b"\n"


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    check_only = "--check" in argv[1:]
    if not args:
        print(__doc__.split("사용:")[1].strip(), file=sys.stderr)
        return 2

    deviated = False
    for path in args:
        try:
            with open(path, "rb") as f:
                before = f.read()
        except OSError as e:
            print(f"read failed: {path}: {e}", file=sys.stderr)
            return 2

        after = normalize(before)
        if after == before:
            continue
        deviated = True
        if check_only:
            print(f"deviation: {path}", file=sys.stderr)
            continue
        try:
            with open(path, "wb") as f:
                f.write(after)
        except OSError as e:
            print(f"write failed: {path}: {e}", file=sys.stderr)
            return 2
        print(f"normalized: {path}", file=sys.stderr)

    return 1 if (check_only and deviated) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
