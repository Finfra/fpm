---
name: gq
description: graphify query 래퍼. 질문을 넘기면 상위 결과만 반환 (Claude가 직접 grep/Read 하지 않도록 유도).
date: 2026-04-24
---

# 개요

`graphify query` 의 얇은 래퍼. 인자로 자연어 질문을 넘기면 graphify CLI 가 그래프를 순회해 **상위 5개** 결과를 반환한다. Claude가 이 결과만으로 답하면 대용량 Read 없이 컨텍스트 확보 가능.

인자: `$ARGUMENTS` — 자연어 질문 (공백 포함 가능, 인용부호 불필요)

# 절차

## 1. graphify 가용성 확인

```bash
command -v graphify >/dev/null || { echo "ERROR: graphify CLI 미설치. pip install graphifyy 필요"; exit 1; }
[ -f graphify-out/graph.json ] || { echo "ERROR: graphify-out/graph.json 없음. graphify update . 실행 필요"; exit 1; }
```

## 2. query 실행

```bash
Q="$ARGUMENTS"
[ -z "$Q" ] && { echo "사용법: /gq <질문>"; exit 1; }

# top 5로 제한 (graphify 옵션 지원 시)
graphify query "$Q" --top 5 2>/dev/null \
  || graphify query "$Q" | head -50
```

`--top` 옵션 비지원 버전 대비 `| head -50` fallback.

## 3. 결과 해석

* 결과가 비어 있으면: "그래프에 해당 질문에 맞는 노드·엣지 없음. 질문을 단순화하거나 `graphify explain <개념>` 시도 권장."
* 결과가 있으면: Claude는 **이 결과만으로** 사용자에게 답한다. 추가 Read 전에 결과로 충분한지 먼저 판단.

# 관련 커맨드

* `graphify path "<A>" "<B>"` — 두 개념 간 연결 경로
* `graphify explain "<개념>"` — 단일 개념 설명 (이웃 노드 요약)
* `/graphify-prune` — GRAPH_REPORT 압축본 생성

# 규칙 참조

`.claude/rules/graphify-rules.md` 준수. 특히 "코드/아키텍처 질문엔 grep 대신 graphify query 우선" 규칙의 실행 진입점이 본 커맨드.

# Opus 4.7 실행 제약

공통 제약은 [`~/.claude/rules/opus-4-7-execution-rules.md`](~/.claude/rules/opus-4-7-execution-rules.md) 참조. 본 커맨드 특화:

* 결과를 Claude가 다시 파일로 저장하지 말 것 (대화 내 표시만)
* 결과가 50줄 초과 시 `head -50` 으로 추가 제한
