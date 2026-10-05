---
name: graphify-prune
description: graphify-out/GRAPH_REPORT.md 를 100줄 이내 GRAPH_REPORT.brief.md 로 압축. 토큰 절감.
date: 2026.09.20
---

# 개요

`graphify-out/GRAPH_REPORT.md` 에서 신호만 추려 `graphify-out/GRAPH_REPORT.brief.md` (≤100줄) 로 생성.

인자: 없음.

> 🔑 **압축 로직은 [`~/.claude/hooks/graphify-brief-refresh.sh`](~/.claude/hooks/graphify-brief-refresh.sh) 단일 지점**이다 (prj3#Issue646 · prj1#Issue508).
> 본 커맨드는 그 스크립트를 **호출만** 한다 — 로직을 여기에 다시 적으면 문서와 실행체가 갈린다.

# ⚠️ 이 커맨드는 «보조»다 — 압축은 자동이다 (Issue508)

prj1 `.git/hooks/post-commit` 에 [`graphify-post-commit-patch.sh`](~/.claude/hooks/graphify-post-commit-patch.sh) 가 부착돼 있어(prj3#Issue648 rollout, 2026-09-20 실측 확인) **커밋마다 `trap EXIT` 으로 재압축**이 붙는다. [`graphify-autoupdate.sh`](~/.claude/hooks/graphify-autoupdate.sh)(Stop hook)도 같은 스크립트를 잇는다.

* 수동 실행이 필요한 경우는 **즉시성**뿐이다 — 커밋·세션 종료를 기다리지 않고 지금 brief 를 최신으로 만들 때
* 종전에는 이 커맨드가 **유일한 갱신 경로**였고, 그래서 아무도 돌리지 않아 prj1 brief 가 2026-06-12 에 멈춘 채 3.2배(2,948 vs 9,006 노드) 벌어졌다(Issue508). 수동 단계는 결국 안 돌아간다

# 실행

```bash
bash ~/.claude/hooks/graphify-brief-refresh.sh            # stale 일 때만 재압축 (아니면 무비용 no-op)
bash ~/.claude/hooks/graphify-brief-refresh.sh --force    # 신선해도 재압축
bash ~/.claude/hooks/graphify-brief-refresh.sh --check    # 판정만: 0=fresh · 1=stale · 2=대상 아님
bash ~/.claude/hooks/graphify-brief-refresh.sh --dir <repo>
```

* 스크립트가 줄 수·섹션 수를 **자체 검증**하고 `원본줄 → 압축줄 (섹션 N개)` 한 줄을 출력한다. 별도 검증 단계 불요
* `GRAPH_REPORT.md` 부재 → `rc=2` 로 조용히 종료 (graphify 프로젝트 아님)
* 무과금 — 결정론적 텍스트 추출이며 LLM 호출이 없다

# 보존·제거 섹션

## 보존 (축약 포함)

* `# Graph Report ...` 헤더 + **원본 mtime·압축 시각** 주석 (신선도 판정 근거를 파일 안에 남긴다)
* `## Corpus Check` — 전체
* `## Summary` — 전체
* `## Community Hubs (Navigation)` — 상위 **15개** 항목만
* `## God Nodes ...` — 상위 **10개** 항목만 (원본 그대로)
* `## Surprising Connections ...` — 상위 **5개** 블록만

## 제거

* `## Hyperedges`
* `## Communities` (개별 커뮤니티 상세 — 노이즈 큼)
* `## Knowledge Gaps` (isolated/thin 나열)
* `## Suggested Questions`

# 주의

* **단일 파일 생성**만 수행. 원본 `GRAPH_REPORT.md` 는 수정 금지
* `graphify-out/` 의 다른 자산(`graph.json`, `cache/` 등) 건드리지 말 것
* 보존 섹션·상한을 바꾸려면 **글로벌 스크립트를 고치고**(prj3 이슈 등록 경유) 본 문서의 위 목록을 맞춘다 — [절차](~/.claude/rules/global-scar-change-rules.md)
* ⚠️ `graphify hook install` 을 다시 돌리면 post-commit 패치가 지워진다 → [`graphify-post-commit-patch.sh`](~/.claude/hooks/graphify-post-commit-patch.sh) 로 재부착

# Opus 4.8 실행 제약

공통 제약은 [`~/.claude/rules/opus-4-8-execution-rules.md`](~/.claude/rules/opus-4-8-execution-rules.md) 참조. 본 커맨드 특화:

* 스크립트 1회 실행 후 rc 로 판정. 실패 시 재시도 1회, 2회 실패면 보고
* 성공 기준: `--check` 가 `rc=0`(fresh) 을 반환
