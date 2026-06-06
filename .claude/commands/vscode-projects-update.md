---
title: "VSCode Projects Update: Project Manager name 동기화"
description: "Projects.md의 id/경로를 기준으로 VSCode Project Manager의 projects.json name을 {id}.{현재이름} 형식으로 업데이트함"
date: 2026-03-29
---

# 작업 설명

`~/_git/___pm/Projects.md`의 프로젝트 테이블을 참조하여
`~/Library/Application Support/Code/User/globalStorage/alefragnani.project-manager/projects.json`의
각 항목 `name`을 `{id}.{현재이름}` 형식으로 업데이트한다.

# 규칙

* id는 Projects.md 테이블의 `id` 컬럼 값 사용
* 매핑 기준: `rootPath` ↔ Projects.md의 `경로` 컬럼 (절대경로 비교)
* id가 한 자리(0~9)이면 앞에 `0`을 붙여 두 자리로 표기 (ex: `1` → `01`)
* `현재이름`은 projects.json에 현재 등록된 `name` 값 유지 (Projects.md 이름으로 덮어쓰지 않음)
* Projects.md에 매핑되는 경로가 없는 항목은 name 변경하지 않고 그대로 유지

# 절차

1. `~/_git/___pm/Projects.md` 읽기 — 테이블에서 `id`와 `경로` 추출
2. projects.json 읽기
3. 각 항목의 `rootPath`를 Projects.md 경로와 비교하여 `id` 결정
    - `~` 는 `/Users/nowage`로 치환하여 비교
4. `name`을 `{zero-padded id}.{현재 name에서 기존 id prefix 제거 후 원본명}` 형식으로 교체
    - 이미 `숫자.이름` 형식이면 숫자 부분만 교체
    - 형식이 없는 경우 `{id}.{현재name}` 으로 설정
5. projects.json 저장



# Opus 4.7 실행 제약

공통 제약은 [`~/.claude/rules/opus-4-7-execution-rules.md`](~/.claude/rules/opus-4-7-execution-rules.md) 참조. 이 커맨드 특화 제약:

* (해당 없음 — 추후 운영 중 식별되면 추가)
