---
name: graphify-rules
description: graphify 토큰 최소화 규칙. Claude가 graphify-out/ 참조 시 1차 기준.
date: 2026-04-24
---

# 대원칙

`graphify-out/` 은 토큰 폭탄. Claude의 `Read` 툴로 대용량 산출물을 직접 읽지 말고 **bash 경유 발췌** 또는 **graphify CLI** 만 사용한다.

# 결정 트리

## 1. 질문 유형별 분기

* **코드/아키텍처/"X와 Y 관계"** 질문
    - `graphify query "<질문>"` (bash) 우선. 일반 grep 금지
    - 두 개념 연결 탐색: `graphify path "<A>" "<B>"`
    - 개념 설명: `graphify explain "<개념>"`
* **단순 파일 위치** 질문
    - Grep 툴 사용 OK (graphify 경유 불필요)
* **graphify 무관 질문**
    - 평소대로 처리

## 2. graphify-out/ Read 허용표

| 파일                             | Claude 직접 Read | 비고                                     |
| :------------------------------- | :--------------- | :--------------------------------------- |
| `GRAPH_REPORT.brief.md` (≤100줄) | ✅ 허용          | 존재 시 최우선                           |
| `GRAPH_REPORT.md` (300+줄)       | ❌ 금지          | bash 발췌만 허용 (아래 3항 참조)         |
| `graph.json` (수백KB)            | ❌ 절대 금지     | 236KB. CLI로만 접근                      |
| `graph.html`                     | ❌ 절대 금지     | 사람용 시각화                            |
| `cache/*`                        | ❌ 금지          | graphify 내부 캐시                       |
| `manifest.json` / `cost.json`    | ❌ 원칙상 불필요 | 메타/로그                                |
| `wiki/index.md`                  | ✅ 허용          | 네비게이션 시작점 (≤80줄)                |
| `wiki/{community}.md`            | ✅ 허용          | 주제별 딥다이브 1~2개만. 일괄 Read 금지 |

## 3. GRAPH_REPORT.md 부분 발췌가 필요할 때

Read 툴로 전체 로딩 금지. bash 경유 섹션 추출만:

* Community Hubs만: `sed -n '/^## Community Hubs/,/^## /p' graphify-out/GRAPH_REPORT.md | head -50`
* God Nodes만: `sed -n '/^## God Nodes/,/^## /p' graphify-out/GRAPH_REPORT.md`
* Surprising Connections만: `sed -n '/^## Surprising Connections/,/^## /p' graphify-out/GRAPH_REPORT.md | head -30`
* Summary만: `sed -n '/^## Summary/,/^## /p' graphify-out/GRAPH_REPORT.md`

# 업데이트 규칙

* 파일 수정 후: `graphify update .` 실행 (AST-only, 무비용). post-commit hook 설치되어 있으면 자동
* 전체 재빌드는 비용 큼 → `--update` 증분 플래그 필수

# 보조 도구 (프로젝트)

* `/graphify-prune` — `GRAPH_REPORT.md` → `GRAPH_REPORT.brief.md` (100줄 이내) 생성
* `/gq <질문>` — `graphify query` 래퍼. 상위 결과만 반환

# CLAUDE.md 위임 관계

프로젝트 `CLAUDE.md` 의 "graphify" 블록은 이 규칙에 위임한다. graphify 관련 모든 판단은 본 파일을 1차 기준으로 삼는다.

# Opus 4.7 실행 제약

공통 제약은 [`~/.claude/rules/opus-4-7-execution-rules.md`](~/.claude/rules/opus-4-7-execution-rules.md) 참조. 본 규칙 특화:

* 본 규칙을 어기는 대용량 Read가 의심되는 상황(>300줄 graphify-out/ 파일 로딩)에서 **즉시 중단** 후 bash 경유로 전환
* `wiki/*` 전체를 한 번에 Read 하지 말 것. `wiki/index.md` 로 먼저 네비게이션 후 필요한 1~2개 커뮤니티 파일만 선별 Read
