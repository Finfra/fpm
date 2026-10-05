---
name: issue-fix-g
description: "프로젝트 범용 이슈 해결 공통 절차 (Fix -> Verify -> Doc -> Close). issue-fix-m, issue-fix-w에서 참조"
date: 2026-03-30
---

# /issue-fix-g - 이슈 해결 (공통)

이슈를 분석하고, 구현하고, 검증한 뒤 종결하는 전체 흐름.
이 문서는 `/issue-fix-m`, `/issue-fix-w`의 공통 절차를 정의.

## 절차

### 0. 진입 가드 — `(!)` 약식 이슈 착수 차단 (필수, Issue268)

구현에 들어가기 **전에** 대상 이슈 제목을 확인함:

```bash
grep -n "^#\{2,3\} Issue{번호}:" Issue.md
```

제목에 **`(!)` 마커가 있으면 그 이슈는 착수 불가 상태**임 — `(!)` 는 "해결책이 아직 정해지지 않았다"는 표식이므로 고칠 대상이 아님. 아래대로 처리하고 **구현으로 넘어가지 않음**:

1. 즉시 중단하고 사용자에게 보고: "Issue{번호}는 `(!)` 약식 이슈(해결책 미정)라 fix 대상이 아님. 승격이 선행되어야 함"
2. 승격 절차 안내 — `(!)` 마커 제거 + `* 상세`·`* 구현 명세` 작성 (번호·이력 유지, 재등록 없음)
3. 승격 시점에 통상 Q1/Q2 triage 를 적용하여 등급 판정 + 등급에 맞는 산출물(plan/task/report) 준비
4. 승격이 끝난 뒤 본 커맨드를 다시 호출

* **`/dev` 경유 호출도 예외 없음** — 비대화 자동 진행 원칙은 "모호한 선택을 기본값으로 결정"하는 것이지 착수 금지를 우회하는 근거가 아님. 여기서 사이클을 멈추고 승격 필요를 보고할 것
* **본 가드가 `(!)` 오용을 잡는 실질적 강제 지점**임. 등록 측 가드(`issue-reg-g` 0-1)를 통과해 잘못 붙은 마커도 여기서 한 번 더 걸림
* 마커가 **없으면** 무조건 통과 — 아래 1단계로 진행
* 설계 근거: `_doc_arch/lightweight-issue.md` 「의미」 2항(fix 게이트) · `rules/issue-g.md` 규칙2 예외 조항

### 1. 문제 분석

- 이슈 원인 분석
- 관련 파일 파악 (프로젝트 구조에 맞게)
- 플랫폼별 이슈 카테고리 분류 (각 `-m`/`-w` 커맨드 참조)
- **TDD 룰 로드** (Issue694·695): [`tdd-playlist-rules.md`](../_doc_arch/rules-ondemand/tdd-playlist-rules.md) 를 **Read** 한다 — 재생목록 유무와 무관하게 «TDD 기본 적용» 판정(2단계)에 쓴다
- **TDD 재생목록 확인** (Issue694): 작업 대상 repo 에 `tdd/playlist.md` 가 있으면 목록을 먼저 본다 — 이번 변경이 건드리는 행과 그 실행 열을 정한다. 없으면 건너뜀(새로 만들지 않음)
- **실행 머신 판정** (Issue771): `bash ~/.claude/sh/fapp-test-host.sh for "$(git rev-parse --show-toplevel)"` — `jma`·`jm4` 면 fApp 이다. red·green 을 그 머신에서 보고(절차 [`/issue-closer-m`](issue-closer-m.md) «TDD 실행 머신»), 종결 게이트도 같은 지점을 읽는다

### 2. 구현

- **TDD 기본 적용** (Issue695): 테스트로 검증할 수 있는 코드 변경이면 `superpowers:test-driven-development` 를 호출하고 **실패하는 테스트를 먼저** 쓴다 — red 를 확인한 뒤 구현한다. 적용 대상·예외 표는 [`tdd-playlist-rules.md`](../_doc_arch/rules-ondemand/tdd-playlist-rules.md) «TDD 기본 적용» 이 SSOT. 예외(문서·설정·시각 UI·spike)면 `* 구현 명세` 에 *"TDD 해당 없음: {사유}"* 한 줄. **재생목록 frontmatter 에 `tdd_mode: tiered` 인 시범 repo** 는 같은 룰의 «중요도별 강도» 표를 따른다(Issue779_10)
- **버그 수정이면 재현 목표 먼저**: 재생목록이 있으면 고칠 버그의 재현 목표를 한 줄 추가한 뒤 재현 테스트(red)를 쓴다. 재생목록 = **무엇을**, `superpowers:test-driven-development` = **어떻게**
- **기능 추가면 성질 행 추가** (Issue694): 재생목록이 있고 새 성질이 검증 가능하면 행을 추가한다. 검증 불가능한 성질은 적지 않는다
- 코드 수정 (green 까지 → refactor)
- **구현 루프 외주** (prj3#Issue779_9): 📗·📙 이슈이고 테스트 러너가 있으면 red 테스트를 쓴 뒤 **구현·green 반복은 [codex-patcher](../agents/codex-patcher.md) 에 맡긴다**(격리 worktree → patch). 메인은 patch 와 red→green 증거만 검토해 적용한다 — 편집·실행 반복이 codex 쿼터로 간다. 📕·출고 직전·2원 구조 변경은 직접 진행. 파일 3개 이상 기계적 변경(이름·경로·형식)은 [codex-migrator](../agents/codex-migrator.md). 표: [outer-agent.md](../_doc_arch/outer-agent.md) §11
- 커밋 메시지: `Fix: Issue[번호] [제목]`

### 3. 검증

- **red→green 증거** (Issue695): TDD 를 적용했으면 red 실행 결과와 green 실행 결과를 `* 구현 명세` 에 한 줄로 남긴다 — 형식은 룰 «red→green 증거»
- **재생목록 행 실행** (Issue694): 재생목록이 있으면 1단계에서 정한 행의 실행 열(또는 `tdd/run.sh` 등 러너)을 돌린다

> 플랫폼별 검증 방법은 각 `-m`/`-w` 커맨드에서 정의.

### 4. 문서화

- **필수**: `* 구현 명세` 섹션에 변경 내용 기술 (어떤 파일의 어떤 로직을 어떻게 변경했는지)
- **선택**: 아키텍처·구조 변경 시 관련 문서 업데이트
- **report 생성 시**: `_doc_work/report/{주제}_issue{번호}_report.md` 규칙 준수
    - `{주제}`: Issue.md의 `* plan:` / `* task:` 경로에서 주제명 추출, 없으면 이슈 제목 기반으로 결정
    - `{번호}`: 현재 이슈 번호 (ex: `Issue5` → `5`)

### 5. 이슈 종결

```bash
/issue-closer-{m|w}
```

## 병렬 디스패치 (다중 버그·다중 도메인)

2개 이상의 **독립** 문제를 동시 수정할 때 `superpowers:dispatching-parallel-agents`를 호출함. 단일 버그·순차 의존 작업에는 적용하지 않음.

### 적용 조건

* 3개 이상의 테스트 파일이 독립적으로 실패
* 다수 서브시스템이 서로 영향을 주지 않고 각자 고장
* 문제 간 공유 상태 없음 (한쪽 수정이 다른 쪽에 영향 없음)

### 절차

1. 이슈가 이미 `# 🚧 진행중`에 등록되었는지 확인 (필수 전제)
2. 문제를 도메인별로 **독립 작업 단위**로 분할
3. `superpowers:dispatching-parallel-agents` 호출 — 각 단위를 에이전트 1에 배당
    - 로컬 에이전트 활용 가능: `code-explorer`(원인 탐색), `silent-failure-hunter`(에러 삼킴), `code-reviewer`(구현 리뷰)
4. 병렬 실행 결과 통합 — 충돌 여부 수동 확인
5. 기존 3단계(구현 / 검증 / 문서화) 진행

### 종료 조건

* 병렬 에이전트 전원 완료 + 결과 통합 검증 통과
* 하나라도 실패 시 즉시 중단, 사용자 보고

상세 규칙: [`~/_git/___pm/_doc_arch/sp-nptir-rules.md`](~/_git/___pm/_doc_arch/sp-nptir-rules.md) 참조.

---

# Opus 4.8 실행 제약

공통 제약은 [`~/.claude/rules/opus-4-8-execution-rules.md`](../rules/opus-4-8-execution-rules.md) 참조.

요지:
* 단계별 종료 조건을 명시, 무한 루프 금지
* 외부 명령 실패 시 재시도 1회, 2회 실패 시 사용자 보고
* 파일 삭제·git push·외부 시스템 변경은 사용자 승인 후 수행
* 애매 표현 금지, 조건문으로 해석

# 레이어링 설계 참조

본 커맨드는 SCAR 3-tier 레이어링의 L1(글로벌) 레이어. 도메인 분기(L2: `/issue-fix-m`, `/issue-fix-w`)와 Skill ↔ Command 짝 구조는 [`~/_git/___pm/_doc_arch/scar-layering-design.md`](~/_git/___pm/_doc_arch/scar-layering-design.md) 참조.
