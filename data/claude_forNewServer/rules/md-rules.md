---
name: md-rules
description: 모든 마크다운 파일에 적용되는 Frontmatter, Outline, Bullet, Table 규칙
date: 2026-03-26
---

# Frontmatter (필수)
* 마크다운 파일 생성 시 반드시 YAML Frontmatter 포함할 것
* **필드 규칙**: `name`과 `title` 중 하나만 사용 (동시 사용 금지)
    - `name` 필드 값은 **항상 파일명과 동일**해야 함 (확장자 제외)
    - `.claude/skills/` 이하: **`title` 사용** — 파일명(`index`, `SKILL` 등)이 스킬명을 표현 못하므로 실제 스킬명을 명시
    - `.claude/` 이하 (skills 제외): **무조건 `name` 사용** (commands, rules, agents 등)
    - 그 외 폴더: 문서 제목이 파일명과 **다를 때만 `title` 사용** (같으면 `name` 사용)

* `.claude/skills/` 하위 Frontmatter 형식:
```yaml
  ---
  title: 스킬명
  description: 스킬 설명
  date: YYYY-MM-DD
  ---
```
예시: `index.md` (my-skill 스킬) → `title: my-skill`

* `.claude/` 하위 Frontmatter 형식 (skills 제외):
```yaml
  ---
  name: {파일명}
  description: 문서 설명
  date: YYYY-MM-DD
  ---
```
예시: `my-rule.md` → `name: my-rule`

* 일반 마크다운 Frontmatter 형식:
```yaml
  ---
  name: {파일명}
  description: 문서 설명
  date: YYYY-MM-DD
  ---
```
또는 제목이 파일명과 다를 때:
```yaml
  ---
  title: 문서의 실제 제목
  description: 문서 설명
  date: YYYY-MM-DD
  ---
```

* Obsidian 볼트(`~/_doc`) 내 문서는 `tags` 필드도 필수
* **`type` 필드 (선택)**: 문서 용도 표시. 도구·렌더러가 이 값을 보고 처리 방식을 분기함
    - `type: ppt` — 슬라이드(PPT)용 마크다운. H1마다 슬라이드 분리. 본문에 H1 다수 허용
        - Outline 규칙 적용 제외 (H1 다수가 정상)
        - "본문 H1 금지" 규칙 적용 제외
    - `type: doc` (기본) — 일반 문서. 단일 H1 + 계층 구조
    - 그 외 값은 도구별 확장용
* Frontmatter의 `name` 또는 `title`이 문서 제목이므로 본문에 `# 제목` H1 헤더 별도 추가 금지 (단, `type: ppt`는 예외)
* `description`이 있으면 본문 첫 줄 설명 문장 중복 작성 금지
* **Frontmatter 적용 제외**: 파일 내 H1이 다수 존재하여 각 섹션의 헤더로 쓰이는 경우
    - 이 경우 Frontmatter 없이 첫 H1을 문서 제목 겸 최상위 섹션으로 사용
    - ex) 이슈 트래커, 할일 목록처럼 `# 섹션A`, `# 섹션B` 구조가 반복되는 파일
    - 단, `type: ppt`는 frontmatter를 유지하면서 본문 H1 다수를 허용함

# Outline (구조)
**[규칙 목적]** H1 하나가 문서 제목 역할을 하면 그 아래 모든 섹션이 H2↑로 밀려나
개요 번호가 불필요하게 증가하는 부작용이 생김. 이를 방지하기 위한 규칙임.

**[적용 범위]** 단일 H1이 문서 제목 역할을 하는 일반 문서에만 적용.
파일 전체에 H1이 다수 존재하여 각각 독립 섹션 헤더로 쓰이는 파일(이슈 트래커, 칸반 보드, `type: ppt` 등)은 적용 제외.

* Frontmatter 바로 아래에 위치해야 함
* Frontmatter `title`과 중복되는 H1 제목만 금지 (본문 구조에서 H1 사용은 허용)
* 개요의 시작은 가급적 H1(`#`)으로 시작 (임시 파일 등 문맥상 불필요한 경우 예외)
* 헤더 레벨 건너뛰기 금지 — Tree 구조(상속관계) 유지 필수
    - H1 아래는 H2, H2 아래는 H3 (ex: `#` → `###` ❌, `#` → `##` ✅)
    - 최상위가 H2로 시작하면 전체를 한 단계씩 올려 H1부터 시작하도록 재구성
* Bad: `## aa` → `### aa-1` (H2에서 시작, H3으로 분기)
* Good: `# aa` → `## aa-1` (H1에서 시작, H2로 분기)
* Bad: `# aa` → `### aa-1` (H1에서 H3으로 건너뜀)
* Good: `# aa` → `## aa-1` (H1에서 H2로 연속)

# Bullet
```markdown
# 내용
* 내용
    - 내용
    - 내용
* 내용
```
* 1단계: `*` 사용, 2단계 이하: `-` 사용

# Table
* 모든 셀을 열의 최대 너비에 맞춰 공백 패딩 정렬
* 기존 테이블의 내용(값, 순서)은 수정하지 않음 (정렬만 적용)
  ```markdown
  | x      | xx    |
  | :----- | ----- |
  | 1      | 11    |
  ```
