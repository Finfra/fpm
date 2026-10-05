---
name: graphify-prune
description: graphify-out/GRAPH_REPORT.md 를 100줄 이내 GRAPH_REPORT.brief.md 로 압축. 토큰 절감.
date: 2026-04-24
---

# 개요

`graphify-out/GRAPH_REPORT.md` (보통 300+줄) 에서 신호만 추려 `graphify-out/GRAPH_REPORT.brief.md` (≤100줄) 로 생성.

인자: 없음.

# 보존·제거 섹션

## 보존 (축약 포함)

* `# Graph Report ...` 헤더 + 생성 시각 주석 추가
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

# 절차

## 1. 사전 조건 확인

```bash
REPORT=graphify-out/GRAPH_REPORT.md
[ -f "$REPORT" ] || { echo "ERROR: $REPORT 없음"; exit 1; }
ORIG_LINES=$(wc -l < "$REPORT")
```

## 2. 압축 스크립트 실행

```python
import re, datetime, pathlib

src = pathlib.Path('graphify-out/GRAPH_REPORT.md').read_text()
today = datetime.date.today().isoformat()

# 헤더(첫 줄) + 생성주석
lines = src.splitlines()
header = lines[0]
out = [header, f'> Pruned: {today} (by /graphify-prune)', '']

# `## ` 섹션 분할
parts = re.split(r'^(## .+)$', src, flags=re.M)
# parts = [preamble, '## Corpus Check', body, '## Summary', body, ...]

keep_prefixes = (
    'Corpus Check',
    'Summary',
    'Community Hubs',
    'God Nodes',
    'Surprising Connections',
)

i = 1
while i < len(parts):
    title = parts[i][3:].strip()
    body = parts[i+1] if i+1 < len(parts) else ''
    matched = next((p for p in keep_prefixes if title.startswith(p)), None)
    if matched:
        # 축약 규칙
        if matched == 'Community Hubs':
            head, *rest = body.splitlines()
            items = [l for l in rest if l.lstrip().startswith('- ')][:15]
            body = '\n'.join([head] + items) + '\n'
        elif matched == 'Surprising Connections':
            head, *rest = body.splitlines()
            new = [head]
            count = 0
            for l in rest:
                if l.lstrip().startswith('- '):
                    count += 1
                    if count > 5:
                        break
                new.append(l)
            body = '\n'.join(new) + '\n'
        out.append(parts[i])
        out.append(body.rstrip())
        out.append('')
    i += 2

pathlib.Path('graphify-out/GRAPH_REPORT.brief.md').write_text('\n'.join(out).rstrip() + '\n')
print('OK')
```

## 3. 검증

```bash
BRIEF=graphify-out/GRAPH_REPORT.brief.md
NEW_LINES=$(wc -l < "$BRIEF")
SECTIONS=$(grep -c '^## ' "$BRIEF")
echo "원본: ${ORIG_LINES}줄 → 압축: ${NEW_LINES}줄 (섹션 ${SECTIONS}개)"
[ "$NEW_LINES" -le 120 ] || echo "WARN: 120줄 초과 — 상한 재검토 필요"
[ "$SECTIONS" -ge 4 ] && [ "$SECTIONS" -le 6 ] || echo "WARN: 섹션 수 비정상"
```

## 4. 보고

* 생성 파일 경로, 원본/압축 라인 수, 섹션 수 한 줄 요약
* 이후 Claude는 `GRAPH_REPORT.md` 대신 `GRAPH_REPORT.brief.md` 를 우선 참조 (`.claude/rules/graphify-rules.md` 준수)

# 주의

* 본 커맨드는 **단일 파일 생성** 만 수행. 원본 `GRAPH_REPORT.md` 는 수정 금지
* `graphify-out/` 의 다른 자산(`graph.json`, `cache/` 등) 건드리지 말 것
* 정기 재실행이 필요하면 post-commit hook 또는 수동 실행

# Opus 4.7 실행 제약

공통 제약은 [`~/.claude/rules/opus-4-7-execution-rules.md`](~/.claude/rules/opus-4-7-execution-rules.md) 참조. 본 커맨드 특화:

* Python 의존(표준 라이브러리만). 외부 패키지 설치 금지
* 성공 기준: brief 파일 생성 + 줄 수·섹션 수 모두 범위 내
