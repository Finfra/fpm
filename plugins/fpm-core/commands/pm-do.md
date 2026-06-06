---
name: pm-do
description: 다른 prj로 명령 위임 후 완료 시까지 동기 블로킹. 의존성(* depends:) 자동 해결 지원
date: 2026-05-16
---

skill: "pm-do"

# 사용법

```
/pm-do <prj번호> "<명령>"
/pm-do --auto-deps [IssueN]
/pm-do --no-wait <prj번호> "<명령>"
/pm-do --status <prj번호>
```

# 인자: $ARGUMENTS

# 처리 흐름

1. 인자 파싱 (위 4가지 형태 중 하나)
2. `--auto-deps` 모드: 현재 prj의 `Issue.md`에서 지정 이슈의 `* depends:` 필드 파싱 → 각 dep를 순차 재귀 위임
3. 그 외: `~/_git/___pm/projects/<prj번호>` lookup → 경로 P
4. `Projects.md`에서 Domain 자동 판정 → suffix(`-g`/`-w`/`-m`) 결정
5. 명령 변환: `이슈N 해결` → `/issue-fix{suffix} N` (스킬의 `resolve_cmd` 규칙)
6. 사용자 컨펌: 위임 계획(대상 prj, 명령, 타임아웃) 출력 후 진행 승인
7. tmux 위임: cdf로 윈도우 확보 → Claude 띄움(필요 시) → 명령 전달
8. `--no-wait` 아니면 폴링: 60초 간격, 30분 타임아웃
9. 완료 hash 회수 → stdout 보고

# 상세

스킬 본문(`~/.claude/skills/pm-do/SKILL.md`) 참조. 슬래시 커맨드는 인자 라우팅만 담당.

# 예시

```
/pm-do 15 "이슈3 해결"
  → prj15(fSnippet) 윈도우에서 /issue-fix-m 3 실행 후 hash 회수

/pm-do --auto-deps Issue5
  → 현재 prj의 Issue5의 * depends 파싱
  → "prj15#Issue3, prj25#Issue7" 발견
  → 각각 순차 위임·완료 대기

/pm-do --no-wait 25 "/build"
  → prj25에 /build 명령만 전달 후 즉시 리턴

/pm-do --status 15
  → pm:fapp 윈도우 capture 출력
```

# Opus 4.7 실행 제약

* 재귀 위임 depth 상한 3
* 폴링 횟수 = 타임아웃/간격 (기본 30회)
* 첫 위임 직전 사용자 컨펌 1회 + `--auto-deps` 다건 시 일괄 1회
