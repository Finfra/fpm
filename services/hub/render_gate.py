"""render_gate — 적응형 렌더 게이트 규칙 엔진 (Issue353_3 M3, arch G안).

모든 턴을 일률 렌더하던 정책을 폐지하고, **서버가 메일박스 블록을 실측해** 이번 턴이
임계를 넘는지 기계 판정한다. 판정 주체가 LLM 이 아니라 서버라는 점이 핵심이다 —
"산출물만 보고 기계적으로 판정되는가"에 해당하므로 지시문(LLM 자율 판정)이 아니라
코드가 집행한다. 지시문 판정은 드리프트하지만 규칙 엔진은 하지 않는다.

# 임계 사다리 (`auto_render`)

| 단계 | 키 | 렌더 대상 | 생략 |
| :-- | :--- | :--- | :--- |
| 0 | `always` | 모든 턴 | 없음(`..text` 단발만) |
| 1 | `short` | 짧은 답부터 전부 | 단답·확인·완료보고 1~3줄 |
| 2 | `page` | 한 페이지(≈40줄) 초과 또는 리치 요소 포함 | 한 페이지 이내 평문 |
| 3 | `doc` | 이번 턴에 문서 산출물을 실제 만든 경우만 | 채팅-only 전부 |

# 표시 모드별 효과 (arch 1.2 — 탭 선오픈 충돌 해소)

* `live-tab`: 라이브 뷰는 **상시 표시**다. 게이트는 턴 종료 시 **아카이브 md 를
  만들지 말지**만 정한다.
* `browser-tab`: 턴 시작에 일괄 오픈하지 않고, **임계 초과를 감지한 시점에** 연다.
  선오픈해 놓고 나중에 "생략"하는 모순이 생기지 않는다.

판정은 순수 함수다 — 입력은 블록 목록과 설정뿐이고 부작용이 없어 그대로 테스트된다.
"""
import re

LEVELS = ("always", "short", "page", "doc")

# ── 표시 모드 (`render_display`) — Issue356_1 ────────────────────────────
#
# ⚠️ `render_tab_mode` 와 **다른 축**이다. 그쪽은 "어디에 여는가"(OS 새 탭 / hub 내부
# iframe 탭), 이쪽은 "무엇을 보여주는가"(라이브 스트림 / 턴별 아카이브)를 정한다.
# 초기 구현이 양쪽에 `browser-tab` 이라는 같은 값을 두어 설정 파일 독자가 같은 것으로
# 오해했고, 실제로도 값별 동작 차이가 없어 사실상 "자동 강등 on/off" 스위치였다.
# 값을 개명해 문자열 충돌을 없애고 각 값이 실제로 다른 동작을 하게 한다.
DISPLAY_MODES = ("live", "archive", "auto")

# 구 값 → 신 값 (1버전 하위호환). 설정 파일을 고치지 않은 사용자를 깨뜨리지 않는다.
_DISPLAY_ALIASES = {
    "live-tab": "live",
    "browser-tab": "archive",
}


def normalize_display(value: str) -> tuple:
    """`render_display` 값 정규화. `(모드, 경고문구)` 반환.

    경고문구는 구 값을 썼을 때만 비어 있지 않다 — 호출측이 로그로 남겨
    사용자가 설정을 갱신하도록 유도한다(조용한 매핑은 이행을 영원히 미룬다).
    """
    v = (value or "").strip()
    if v in DISPLAY_MODES:
        return v, ""
    if v in _DISPLAY_ALIASES:
        new = _DISPLAY_ALIASES[v]
        return new, (f"render_display: '{v}' 는 구 값입니다 — '{new}' 로 바꾸십시오"
                     f" (render_tab_mode 와의 이름 충돌 해소, Issue356_1)")
    if v:
        return "auto", (f"render_display: 알 수 없는 값 '{v}' — 'auto' 로 폴백"
                        f" (가능한 값: {', '.join(DISPLAY_MODES)})")
    return "auto", ""

# `page` 단계의 "한 페이지" 기준 — 산문 40줄
PAGE_LINES = 40
# `short` 단계의 단답 기준 — 3줄 이하
SHORT_LINES = 3

_RICH_PATTERNS = (
    ("table", re.compile(r"^\s*\|.+\|\s*$", re.MULTILINE)),
    ("code", re.compile(r"^\s*```", re.MULTILINE)),
    ("mermaid", re.compile(r"^\s*```\s*mermaid", re.MULTILINE | re.IGNORECASE)),
    ("image", re.compile(r"!\[[^\]]*\]\([^)]+\)")),
    ("heading", re.compile(r"^\s{0,3}#{1,6}\s+\S", re.MULTILINE)),
)
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+\S", re.MULTILINE)


def measure(blocks) -> dict:
    """메일박스 블록 목록에서 판정 재료를 실측한다.

    `text` 블록만 본다 — 활동(activity)·턴 마커는 응답 분량이 아니다.
    """
    texts = [b.get("text", "") for b in blocks if b.get("kind") == "text"]
    joined = "\n\n".join(texts)
    lines = [ln for ln in joined.splitlines() if ln.strip()]
    rich = {name: bool(pat.search(joined)) for name, pat in _RICH_PATTERNS}
    # mermaid 는 code 의 부분집합이라 code 판정에 흡수되지 않도록 별도 유지
    list_items = len(_LIST_ITEM.findall(joined))
    rich["list3"] = list_items >= 3
    return {
        "text_blocks": len(texts),
        "lines": len(lines),
        "chars": len(joined),
        "rich": rich,
        "has_rich": any(rich.values()),
        "list_items": list_items,
    }


def decide(blocks, level: str = "page", created_docs: int = 0,
           override: str = "") -> dict:
    """렌더/아카이브 여부를 판정한다.

    Args:
        blocks: 메일박스 블록 목록(이번 턴 범위)
        level: `auto_render` 단계
        created_docs: 이번 턴에 생성·갱신된 문서 산출물 개수(`doc` 단계 재료)
        override: `show`(강제 렌더) · `text`(강제 생략) · 빈 문자열(설정 따름)

    Returns:
        `{render, reason, level, metrics}` — `render` 가 최종 판정.
    """
    m = measure(blocks)
    if override == "show":
        return {"render": True, "reason": "사용자 오버라이드(..show)",
                "level": level, "metrics": m}
    if override == "text":
        return {"render": False, "reason": "사용자 오버라이드(..text)",
                "level": level, "metrics": m}
    if level not in LEVELS:
        level = "page"
    if level == "always":
        return {"render": True, "reason": "always — 모든 턴 렌더",
                "level": level, "metrics": m}
    if level == "doc":
        ok = created_docs > 0
        return {"render": ok,
                "reason": (f"doc — 문서 산출물 {created_docs}건"
                           if ok else "doc — 이번 턴 문서 산출물 없음"),
                "level": level, "metrics": m}
    if level == "short":
        # 단답·확인만 생략. 리치 요소가 있으면 짧아도 렌더한다(표 3줄이 평문 3줄보다 값지다)
        if m["lines"] <= SHORT_LINES and not m["has_rich"]:
            return {"render": False,
                    "reason": f"short — 단답 {m['lines']}줄",
                    "level": level, "metrics": m}
        return {"render": True, "reason": f"short — {m['lines']}줄",
                "level": level, "metrics": m}
    # page
    if m["lines"] > PAGE_LINES:
        return {"render": True, "reason": f"page — {m['lines']}줄(>{PAGE_LINES})",
                "level": level, "metrics": m}
    if m["has_rich"]:
        kinds = ", ".join(k for k, v in m["rich"].items() if v)
        return {"render": True, "reason": f"page — 리치 요소({kinds})",
                "level": level, "metrics": m}
    return {"render": False,
            "reason": f"page — 평문 {m['lines']}줄 · 리치 요소 없음",
            "level": level, "metrics": m}
