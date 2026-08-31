---
title: fbot-recruit
description: "리크루팅핀봇(fbot-recruit) 판단 계층 — 직능(role) 신설·아카이브·부활. agents/skills 우선 승격, 없을 때만 웹 검색. 사람 승인([컨펌]) 전 카탈로그 등재 금지"
date: 2026.08.31
---

> ⚠️ **글로벌 SCAR 변경 가드** (Issue46)
>
> 본 스킬은 모든 프로젝트가 공유. 즉흥 수정 금지.
>
> * cwd ≠ `~/.claude/` → 즉시 수정 금지, `~/.claude/Issue.md` 이슈 등록 후 별도 세션에서 처리
> * 영속 설계 SSOT: [`_doc_arch/fbot-arch.md`](../../_doc_arch/fbot-arch.md) §조직(4종)·§직능 카탈로그·§표준 시나리오 2
> * 절차: `~/.claude/rules/global-scar-change-rules.md`

# 목적

**직능(role) 축의 판단 계층.** role 등록 절차 5단계 중 LLM 판단이 필요한 ⓪①②③을 수행하고, 결정론 집행(④⑤·아카이브·부활)은 [`hooks/fbot-recruit.py`](../../hooks/fbot-recruit.py) 에 위임한다. 개체(bot 테이블)는 인사핀봇 소관 — **직능을 만드는 것이 리크루팅, 개체를 앉히는 것이 배치**다.

# 트리거

* `/fbot-recruit` · "새 직능 만들어줘" · "N핀봇이 필요해" (카탈로그에 없는 role)
* **§표준 시나리오 2** — 인사핀봇이 "role 자체가 없음" 분기에서 호출
* "안 쓰는 직능 정리해줘" (아카이브) · "그 직능 다시 살려줘" (부활)

# 절차 — role 신설 (⓪→⑤ 순서 고정, 건너뛰기 금지)

| 단계 | 동작 | 완료 기준 |
| :--- | :--- | :--- |
| ⓪ 중복 검사 | `hooks/fbot-recruit.py list` 로 카탈로그 조회 → 요청 임무와 **겹치는 role 이 있으면 거부**하고 그 role 을 안내 | 겹침 없음 확인 |
| ① 재료 수집 | `~/.claude/agents/*.md`·`~/.claude/skills/*/SKILL.md` 에서 유사 역할 탐색. **발견 시 승격 후보로 확정하고 웹 검색을 하지 않는다.** 미발견 시에만 WebSearch 로 역할 정의 조사 | 재료 출처 1개 확정 (agents 승격 / 웹 검색) |
| ② 매뉴얼 초안 | `data/fbot/manuals/{role}.md` 작성 — [F5 형식](../../_doc_arch/fbot-arch.md): frontmatter(`completion`·`revisions`) + 본문 5절(임무·작업 절차·워크플로우 어댑터·경계/금지·완료 판정) · **900자 상한** | 파일 존재 + 형식 준수 |
| ③ 사람 승인 | `/mq-send --due +0d` 로 `[컨펌]` 등록 — 재료 출처·매뉴얼 경로·제안 도형/색 포함. **ACK 전 ④ 진입 금지** | 사용자 ACK |
| ④⑤ 등재+아이콘 | `hooks/fbot-recruit.py register --role R --shape S --base '#hex' --label L --tags 't1\|t2'` 1회 호출 | exit 0 + JSON 의 `icon.created` |

* 완료 후 호출자(인사핀봇·세션)에 복귀 보고 — §표준 시나리오 2 는 이 시점에 시나리오 1 의 2단계 ⓑ(`hire`)로 합류한다
* 도형은 [fbot-icon](../fbot-icon/SKILL.md) 어휘 내에서 미사용·저사용 도형 우선. 어휘 고갈 시 생성기 `SHAPES` 확장이 선행(recruit=magnet 선례)

# 절차 — 아카이브·부활

* **판정 재료는 registry 다** — `hooks/fbot-state.py list` 로 그 role 의 살아 있는 개체(career != terminated·leave)가 0 인지, 마지막 배치가 언제인지 확인한다. 카탈로그만 보고 판정하지 않는다
* 집행: `hooks/fbot-recruit.py archive --apply --role R` (1건씩 — 직능 일괄 아카이브 없음) / 부활: `revive --role R`
* 효과·보존·제외(상비 4종)는 계약 §직능 카탈로그 표가 정본

# 경계·금지 (계약 §조직 축 분리)

* `bot` 테이블 접근 금지 — 개체 조작이 필요하면 인사핀봇(`fbot-hr-gate.py`)에 넘긴다
* `catalog.yml` 직접 Edit 금지 — 훅 경유만 (카탈로그 쓰기 단일 지점)
* 웹 검색을 ①의 기존 자산 조회보다 먼저 실행 금지 — 실행하면 계약 위반
* 사람 승인(③) 없이 ④ 호출 금지 — mq `[컨펌]` ACK 는 사람 전용(봇 auto-ack 금지)

# 검증

`python3 ~/.claude/hooks/test-fbot-recruit.py` — 카탈로그 등재·아카이브·부활·HR 연동 10 케이스
