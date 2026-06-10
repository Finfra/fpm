---
name: fpm-show
description: 요청 결과를 HTML 문서로 렌더링하여 Firefox에 표시 (hub a모드 render 트리거). Issue133 — 구 `/hub`/`..hub` render 의 새 이름. 우산 토글·Q&A 회수 동작은 commands/fpm-hub.md SSOT.
date: 2026-06-03
---

> ⚠️ **글로벌 SCAR 변경 가드 (Issue46)**: 본 커맨드는 모든 프로젝트가 공유. cwd ≠ `~/.claude/` 면 즉시 수정 금지 → `~/.claude/Issue.md` 이슈 등록 후 처리. 영속 설계 SSOT: `~/.claude/_doc_arch/hub-mode-arch.md`. 절차: `~/.claude/rules/global-scar-change-rules.md`

# /show — HTML 결과 렌더 (hub a모드, Issue133)

요청을 처리한 결과를 완전한 HTML 문서로 작성하여 Firefox 로 자동 표시함. hub 우산 기능의 **a모드(단방향 렌더)** 명시 트리거.

* **이름 분리 배경 (Issue133)**: a모드 render 트리거가 우산명 `hub`(시스템·기능 전체, 토글 `..hub on|off|start|stop`)와 같은 단어라 충돌·혼동 → render 액션을 `..show`/`/show` 로 분리. b=`..ask`·c=`..board` 와 운율 통일.
* **하위호환**: 구 `/hub <요청>`·`..hub <요청>`(단독, 렌더 의도)는 한시적 deprecated alias — 동작은 동일하되 채팅 응답 끝에 `..show` 안내 1줄 첨부.
* **우산 토글은 `hub` 유지**: `..hub on|off|start|stop` · `/hub on|off|start|stop` 토글, c모드 별칭 `..hub dash` 는 변경 없음.

## 사용

```
/show {요청 내용}
```

자연어 트리거 `..show {요청}` 와 동일. 명시적 슬래시(`/show`) 사용 시 더 안정적.

## 동작 SSOT

렌더 절차(저장 경로 규약·CANONICAL 헤더 블록·본문 HTML 작성 규칙·다이어그램 우선 렌더·Q&A form 자동 회수·CORS/보안·파일 경로 규칙)는 **`commands/fpm-hub.md` 가 단일 출처**. 본 커맨드는 a모드 render 진입점 이름만 제공하며, 처리 본문은 `fpm-hub.md` 와 완전 동일.

* 트리거 감지·플래그 touch·컨텍스트 주입: `hooks/fpm-hub-trigger.sh` (UserPromptSubmit) — `..show`/`/show` primary, `..hub`/`/hub`(bare) deprecated alias
* 렌더 동작 명세: [`commands/fpm-hub.md`](fpm-hub.md)
* 영속 설계 SSOT: [`_doc_arch/hub-mode-arch.md`](../_doc_arch/hub-mode-arch.md)
