---
name: naming-rules
description: 스킬, 룰, 커맨드 등 Claude 관련 파일명과 폴더명에 대한 네이밍 컨벤션
date: 2026-03-26
enforcement: |
  [`hooks/rule-guard.sh`](../hooks/rule-guard.sh) 가 `.claude/` 하위 파일명의 `_` 를 검출해 경고한다(F4-5, 정보 파일 4종·`_doc_*` 예외). `_doc_arch/*-design.md` 를 편집하면 어느 repo 든 rename 시점을 알린다(c15, Issue730). 파일 생성 자체를 막지는 못한다
classification: |
  `_` vs `-`·날짜 형식 **컨벤션**. 사용자 선호이자 기존 자산과의 정합 기준
---

> ⚠️ **글로벌 SCAR** — 모든 프로젝트 공유. 즉흥 수정 금지(cwd ≠ `~/.claude/` 면 `Issue.md` 등록 후 처리) · [절차](global-scar-change-rules.md)

> 🔒 **집행: advisory**
> 📚 **분류: 사실**

# 파일·폴더 이름

* `.claude/` 하위 파일·폴더·커맨드·스킬 이름은 `_` 대신 `-` (ex) `web-design.md` · `issue-manager/` · `/issue-fix` · `skill: "wp-post"`)
* 예외: 정보 파일 4종(`past_prompts.md`·`knowledge_base.md`·`learning_log.md`·`instincts.md` — hook·memory 배선이 이름을 참조, [info-files.md](info-files.md)) · `_doc_*` 폴더 · 외부 도구가 강제하는 컨벤션
* 리네임하면 참조 경로도 함께 갱신 — [rename 절차](../_doc_arch/rules-ondemand/rename-reference-rules.md)

# 날짜 — 기본 `YYYY.MM.DD` (2026-07-28 사용자 지정)

* 새 문서·폴더의 **파일명과 frontmatter `date:`** 모두 점 구분(ex) `2026.07.28_meeting.md` · `2026.07.28/`). YAML 은 이 값을 문자열로 읽는다
* 기존 `YYYY-MM-DD` 는 소급 수정 의무 없음(다시 손댈 때 정리) · 폴더에 다른 형식이 정착해 있으면 그 형식(ex) `capture/{YYYYMMDD}_{SEQ}/`) · 기계 생성 타임스탬프 파일명은 대상 아님

# `_doc_arch/` 파일명에 `-design` 접미사 금지 (Issue707)

* 폴더가 이미 설계 폴더라 접미사는 반복이고 공통편·하위편 정렬을 뒤집는다(ex) `outer-agent.md` 가 `outer-agent-codex.md` 위여야 한다). `-arch`·`-usage` 처럼 **문서 종류를 가르는** 접미사는 대상 아님
* 신규에 적용. 타 repo 기존 `-design.md` 는 그 문서를 손대는 시점에 rename 절차로 — 일괄 rename 은 하지 않는다(Issue730). rule-guard c15 가 시점을 알린다

# 도메인 접미사

`-g` global · `-m` macOS 앱 · `-w` web · `-v` game/Unity(정의만 🚧). 판정·사례: [scar-layering-design.md](~/_git/___pm/_doc_arch/scar-layering-design.md)
