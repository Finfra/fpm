---
name: CLAUDE
---

# 사용 환경

* Claude Code CLI 환경
* 프로젝트 관리: 각 프로젝트 루트의 `Issue.md` + `_doc_work/` 폴더 기반

## 선호하는 스타일

* `~/.claude/rules/language-rules.md` 참조

## 변경 사항 탐지

* `~/.claude/rules/change-detect-rules.md` 참조 — "업데이트 확인" 등 변경 탐지 요청 시 log+status+diff 3종 병렬 실행 규칙

# 모델 운영

* Opus 4.7(설계·복잡추론) / Sonnet 4.6(구현·반복) / Haiku 4.5(subagent) — Blueprint+Execute 패턴 권장

# 파일 생성

* Markdown: `rules/md-rules.md` / Mermaid: `skills/mermaid-diagram/mermaid-rules.md` (스킬 실행 시 로드)
* 네이밍: `rules/naming-rules.md` (`.agent/` 폴더 사용 금지)

## nPTiR (상세: `rules/nptir-rules.md`)

* 루트: 가장 가까운 `Issue.md` 위치
* needs → `_doc_arch/{주제}.md` / Plan → `_doc_work/plan/{주제}_plan.md` / Task → `_doc_work/tasks/{주제}_task.md` / issue → Issue.md / Report → `_doc_work/report/{주제}_issue{번호}_report.md`
* 트리거: "계획 세워줘" → plan 생성 / "태스크 만들어줘" → task 생성 / "report 만들어줘" → report 생성
* **명시적 요청 없이 plan/task/report 자동 생성 금지**

## _doc_work/refs/ 참고 자료 (상세: `rules/refs-rules.md`)

* `_doc_work/refs/` 폴더·파일 생성 시 반드시 `_doc_work/refs.md` 인덱스에 등록
* 등록 형식: `* {제목} : _doc_work/refs/{파일명}.md`
* 인덱스 섹션: `# obsidian docs` (볼트 자료) / `# refs` (외부 수집 자료)

## _doc_arch/ 영속 설계 문서 (`/design-doc` 커맨드)

* 용도: 이슈 종결 후에도 유지되는 아키텍처·정책·규칙의 설계 SSOT
* 상세 규칙: `_doc_arch/doc-design-rules.md` (커맨드 실행 시 로드)

## superpowers ↔ nPTiR 연동

* superpowers 스킬의 nPTiR 단계별 브리지 규칙
* 트리거: `/needs` (R1 라우팅), `/sp-plan` (B경로 단축) (실행 시 규칙 자동 로드)
* `/sp-plan` vs `/gstack-plan`: 경량·컨텍스트 여유 부족 → `/sp-plan`, 4종 리뷰·대형 설계 → `/gstack-plan`

# Info

## 약자

* SCAR: Skill/Command/Agent/Rule
* nPTiR: needs/Plan/Task/issue/Report [Issue.md, _doc_work/{plan,tasks,report}]

## 정보 파일 저장 규칙 (목록: `rules/info-files.md`)

* feedback 저장 시: memory 파일 + `learning_log.md` 한 줄 append (`* YYYY-MM-DD: {규칙}`)
* reference 저장 시: memory 파일 + `knowledge_base.md` 한 줄 append (`* YYYY-MM-DD [{출처}]: {내용}`)
