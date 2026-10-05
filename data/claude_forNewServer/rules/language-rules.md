---
name: language-rules
description: 답변 시 사용할 언어, 문체, 표현, 전문성 관련 규칙
enforcement: |
  최종 답이 영어면 [`hooks/lang-guard.sh`](../hooks/lang-guard.sh)(Stop)가 `decision: block` 으로 한국어 재작성을 되돌리고, 컨텍스트 압축·재개 직후 [`hooks/lang-anchor.sh`](../hooks/lang-anchor.sh)(SessionStart)가 언어를 재고정한다(Issue747 — 산출물만 보는 기계 판정이라 [hook-rules](../_doc_arch/rules-ondemand/hook-rules.md) 규칙9 충족). 줄임체·`ex)` 표기·한자 규정 등 **문체·표기는 여전히 집행 수단 없음**.
classification: |
  언어·문체는 사용자 **선호**(주어진 조건). 응답 언어 집행은 Issue747 실발생 — 압축 요약이 영어라 재개 뒤 영어 응답이 5~15% → 약 80% 로 번져 사용자가 두 번 지적
---

> ⚠️ **글로벌 SCAR** — 모든 프로젝트 공유. 즉흥 수정 금지(cwd ≠ `~/.claude/` 면 `Issue.md` 등록 후 처리) · [절차](global-scar-change-rules.md)

> 🔒 **집행: enforce(응답 언어) · passive(문체·표기)**
> 📚 **분류: 사실 + 관측된 실패**

# 언어·문체

* 한국어로 답한다 — 전문 용어·코드는 원문, 코드 주석은 한국어
* 높임말 대신 줄임체(ex) "~합니다" → "~함"). 별도 요청 없으면 요점 중심·목록으로 간결하게
* 예시는 `ex) ` ("예를 들어," 금지) · 불확실한 정보는 `(검증 필요)`
* 전문적이고 깊이 있게 (AI/DevOps/CS)

# 한자 (Issue314)

* 한자어는 **한글 표기**가 기본. 부득이하면 **한국 정자**만 — 일본 신자체(`状態`)·중국 간체(`状态`) 금지
* 범위는 채팅·문서뿐 아니라 **도구 호출 파라미터**(Bash `description`·커밋 메시지·HTML `<title>`)까지 — 실발생 자리가 Bash `description` 이었다. 발견 즉시 한글로 고치고 같은 응답의 다른 표현도 점검

# 파일·경로 참조 — markdown 링크 1방식

* `[표시명](상대경로)` 로 통일한다 — 백틱 코드 span 금지·혼용 금지. 채팅 응답과 문서 본문 모두. 라인은 `[file.ts:42](path#L42)`
* **href 는 워크스페이스 루트부터의 전체 상대경로** — basename 만 넣으면 죽은 링크다(VSCode 채팅 webview 클릭 무반응). 표시명만 basename 으로 줄여도 된다
* 예외: `Issue.md` 의 `* plan:`·`* task:` 필드는 백틱(기계 파싱 — [issue-g.md](issue-g.md)) · 볼트(`~/_doc`) 파일은 hub `/ob` 브리지([ob-link-rules.md](../_doc_arch/rules-ondemand/ob-link-rules.md))
* 사용자에게 **경로를 답으로 요구**할 때는 `~/` 표기 권장 1줄을 붙인다 — Zed Agent Panel 이 `/` 로 시작하는 입력을 슬래시 커맨드로 오인해 **전송을 취소**하고 에이전트에는 신호가 없다(Issue39 · [debug_TECH.md](../../_git/___pm/_doc_work/debug_TECH.md) 2026-08-06)

리터럴 지시(종료 조건·횟수 명시)는 [opus-4-8-execution-rules.md](opus-4-8-execution-rules.md) 「공통 실행 제약」
