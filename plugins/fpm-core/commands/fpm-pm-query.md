---
name: fpm-pm-query
description: 등록된 프로젝트 정보 조회·검색 (전체 목록/상세/타입 필터/검색)
date: 2026-04-11
---

skill: "pm" (action: query)

# 실행 절차

인자: `$ARGUMENTS`

## 1. 인자 분기

* `help` → Usage 출력 후 종료
* (없음) → 전체 목록 모드
* 숫자 → 상세 조회 모드
* `general` / `web` / `mac` → 타입 필터 모드
* 그 외 문자열 → 검색 모드

## 2. 전체 목록 모드 (인자 없음)

1. `___pm/Projects.md` > `## 번호 대역 규칙` 테이블을 Read하여 출력
2. `cdf` (인자 없이) 실행하여 현재 등록된 프로젝트 목록 표시
3. 대역별 빈 번호 목록 표시 (`projects/` 폴더의 파일명과 대역 범위 비교)

## 3. 상세 조회 모드 (번호 지정)

`Projects.md` 테이블에서 해당 번호의 행을 조회하여 출력:

```
[{번호}] {프로젝트명}
  타입:    {타입} ({도메인서픽스})
  경로:    {경로}
  설명:    {설명}
  이모지:  {이모지}
  컬러:    {peacock.color}
  SCAR:    {Harness.md 내 해당 프로젝트 엔트리 요약}
```

## 4. 타입 필터 모드 (`general` / `web` / `mac`)

`Projects.md` 테이블에서 Domain 컬럼 기준으로 필터링:
* `general` → Domain이 `g`, `g(cli)`, `g(Exe)`인 프로젝트
* `web` → Domain이 `w`인 프로젝트
* `mac` → Domain이 `m`인 프로젝트

해당 타입의 프로젝트만 테이블 형식으로 출력.

## 5. 검색 모드 (문자열)

`Projects.md` 테이블에서 프로젝트명·경로 컬럼을 대소문자 무관 부분 매칭 후 결과 테이블 출력.

## 6. Usage (help)

```
Usage: /pm-query [대상]

대상:
  (생략)    전체 프로젝트 목록 + 빈 번호
  번호      해당 프로젝트 상세 조회 (ex: /pm-query 15)
  타입      타입별 필터 (ex: /pm-query mac)
  검색어    프로젝트명·경로 부분 매칭 (ex: /pm-query fSn)
  help      이 도움말 표시

예시:
  /pm-query
  /pm-query 15
  /pm-query mac
  /pm-query fSnippet
```

> 이 커맨드는 조회 전용이므로 pm-history.md에 기록하지 않음.

---

# Opus 4.7 실행 제약

공통 제약은 [`~/.claude/rules/opus-4-7-execution-rules.md`](../rules/opus-4-7-execution-rules.md) 참조.

요지:
* 단계별 종료 조건을 명시, 무한 루프 금지
* 외부 명령 실패 시 재시도 1회, 2회 실패 시 사용자 보고
* 파일 삭제·git push·외부 시스템 변경은 사용자 승인 후 수행
* 애매 표현 금지, 조건문으로 해석
