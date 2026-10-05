---
name: graphify-rules
description: ___pm graphify 규칙 — 정본은 글로벌 graphify-rules, 여기는 프로젝트 고유 사항만
date: 2026.08.15
---

> **정본은 글로벌 [`~/.claude/rules/graphify-rules.md`](.claude/rules/graphify-rules.md)** — 상시 로드된다.
> 대원칙(토큰 폭탄 회피)·graphify-first 트리거·`graphify-out/` Read 허용표·예외 3종·갱신 규칙은 전부 거기가 SSOT다. 여기 복제하지 않는다(중복 로드 비용).

# ___pm 고유 사항

* 보조 커맨드: [`/graphify-prune`](.claude/commands/graphify-prune.md) (리포트 압축 — **보조다. 압축은 post-commit 자동**, Issue508) · [`/gq <질문>`](.claude/commands/gq.md) (query 래퍼)
* brief 신선도가 의심되면 `bash ~/.claude/hooks/graphify-brief-refresh.sh --check` (0=fresh · 1=stale). 압축 로직·판정 기준은 그 스크립트가 단일 지점이다
* 스캐폴드 표준(신규·기존 프로젝트에 배선을 붙이는 절차)은 [graphify-priority-setup.md](_doc_arch/graphify-priority-setup.md)
* 프로젝트 [`CLAUDE.md`](CLAUDE.md) 의 graphify 절은 본 파일을 거쳐 글로벌 정본에 위임한다
