---
name: issue-g
description: 모든 프로젝트 공통 이슈 관리 규칙
date: 2026-04-04
enforcement: |
  [`hooks/rule-guard.sh`](../hooks/rule-guard.sh) 가 검출해 경고하는 것은 셋이다: `Issue.md` 편집 시 **`* depends:` 토큰 문법**(F5-7)·**산문 절 길이 초과**(규칙9, Issue342), 그리고 `_doc_work/{plan,report}/*.md` 편집 시 **규칙2 산출물 필드 결손**(Issue411 — 이슈도 frontmatter 도 그 파일을 안 가리키면 경고). 나머지 조항(섹션 이동·완료 순서·`(!)` 마커 진입 조건·`trigger` 기재)은 **집행 수단 없음** — 사람·Claude 의 준수에 의존한다. 예외로 규칙10 의 **낡은 blob 커밋**(스테이징 뒤 HEAD 이동)은 git pre-commit 의 `issue-tx precommit` 이 **거부**한다(Issue752)
classification: |
  `Issue.md` 섹션·필드 **포맷 규약**. issue-map 등 소비처가 이 형식을 전제
---

> ⚠️ **글로벌 SCAR** — 모든 프로젝트 공유. 즉흥 수정 금지(cwd ≠ `~/.claude/` 면 `Issue.md` 등록 후 처리) · [절차](global-scar-change-rules.md)

> 🔒 **집행: advisory (일부 조항만)**
> 📚 **분류: 사실**

> 📖 **상세 조건부** — `depends` 토큰 문법·`(!)` 마커·`trigger`/`status` 필드·산문 절 길이 상한·포맷 예시: [issue-detail.md](../_doc_arch/rules-ondemand/issue-detail.md)

이슈는 프로젝트 루트 `Issue.md` 에서 **통합 관리**한다(하위 레포에 별도 이슈 파일 두지 않음). 양식·예제 SSOT 는 `___pm/data/template/Issue.md` — 작성 시 Read.

# 규칙

- 규칙0 (프로세스): 착수 시 `🚧 진행중`, 완료 시 `✅ 완료` 로 옮긴다. **`✅ 완료` 삽입 위치는 헤더 바로 아래**(완료 시각 역순) — 번호 순 append 금지
- 규칙1 (언어): 제목·목적·상세·결과는 **한국어**(기술 용어 제외)
- 규칙2 (포맷): 붙여쓰기 번호(Issue1) · `* 목적`·`* 상세`·`* 구현 명세`(로직·검증 포함). plan/task 가 있으면 `* plan:`·`* task:` 를 `* 목적:` 바로 아래에 **백틱 경로**로(Issue.md 기준 상대경로 — 소비처가 파싱하므로 링크 금지). 선행이 있으면 같은 자리에 `* depends:` — 같은 prj `Issue<M>` · 다른 prj `prj<N>#Issue<M>` · 혼합은 쉼표 나열(`issue-closer-g` 가 후행 알림, `/fpm-do --auto-deps` 가 선행 위임)
- 규칙3 (커밋): 완료 이슈는 커밋 해시 기록(여럿은 쉼표)
- 규칙4 (정리): 이슈 등록 시 `이슈후보` 섹션의 중복 항목 삭제
- 규칙5 (이슈후보): `🌱 이슈후보` 는 번호 없는 `1. 항목명` 리스트. 번호는 `📕📙📗` 로 옮길 때 발급
- 규칙6 (서브 이슈): 복잡한 기능은 `Issue1_2` 형식 서브 이슈로 부모 바로 아래 배치. 서브 완료는 표시만 하고 부모 종결 때 함께 이동
- 규칙7 (서브 동기화): 서브 이슈는 활성·완료 무관 항상 메인 이슈 하위
- 규칙8 (결정사항 = 링크 표): `🤔 결정사항` 에는 **결정 한 줄 + 정본 링크**(워크스페이스 루트 상대 링크 + `"절 이름"`) 표만 둔다. 근거·이력은 정본(`_doc_arch/` 해당 절, 없으면 `_doc_arch/decisions.md`)이 소유 — 표 밖 산문·중첩 불릿·하위 절 금지. 철회되면 행을 빼고 정본에 철회를 남긴다
- 규칙10 (동시편집, Issue664): 공유 `Issue.md` 는 동시에 고쳐진다고 전제하고 번호·스테이징·블록 이동을 [`sh/issue-tx.py`](../sh/issue-tx.py) 로 한다 — 설계 [issue-concurrency.md](../_doc_arch/issue-concurrency.md)
    - 번호는 `alloc`(HWM+1 을 눈으로 세지 않는다) · 커밋은 `issue-tx.py commit --issues <내 이슈> -m … [내 파일…]` — 맨 `git add Issue.md`·`git commit` 은 타 세션 미커밋분·스테이징분을 쓸어담는다(Issue754)
    - 커밋이 거부됐다가 다시 할 때는 처음부터 다시 — 그 사이 남이 커밋했으면 낡은 blob 이 그 커밋을 되돌린다(pre-commit 이 거부하지만 기대지 않는다, Issue752)
    - 블록 끝은 «다음 `## Issue` 또는 다음 `# ` 섹션 헤더» — 손으로 옮기면 섹션 헤더를 끌고 간다 → `move`
    - 조회는 `find <키워드>`(이슈 목록 한 줄씩)·`show <N>`(블록 전문, 없으면 `issue_OLD.md`) — grep·sed 를 여러 번 부르지 않는다. 완료 섹션이 불어나면 `archive`(최근 10건 유지) (Issue779_6)
    - ⚠️ «한 세션만 만진다»·«착수 전 mtime 점검» 은 해법이 아니다

# Issue.md 기본 섹션

```
Issue Management, 🤔 결정사항, 🌱 이슈후보, 🚧 진행중, 📕 중요, 📙 일반, 📗 선택, ✅ 완료, ⏸️ 보류, 🚫 취소, 📜 참고
```

프로젝트별로 완료 섹션명이 다를 수 있다(ex) `🏁 완료-해결순`) — 프로젝트 rules 가 오버라이드.
