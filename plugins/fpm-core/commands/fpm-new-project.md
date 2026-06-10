---
name: fpm-new-project
description: 프로젝트 타입별 초기화 (스킬 wrapper)
date: 2026-04-11
---

Read the skill file at `$HOME/_git/___pm/.claude/skills/new-project/SKILL.md` and follow its instructions with the following arguments: $ARGUMENTS

If no arguments are provided, display the usage and stop:

```
Usage: /new-project <프로젝트명> <타입> [경로]

타입:
  1  일반 프로젝트
  2  웹 프로젝트
  3  macOS 앱 (fApp)
  4  macOS 오픈소스 (fappCli)

옵션:
  경로  프로젝트 생성 위치 (기본: ~/_git/<프로젝트명>)

예시:
  /new-project myTool 1
  /new-project myWeb 2
  /new-project myApp 3
  /new-project myLib 4
  /new-project myTool 1 ~/projects/myTool
```

---

# Opus 4.7 실행 제약

공통 제약은 [`~/.claude/rules/opus-4-7-execution-rules.md`](../rules/opus-4-7-execution-rules.md) 참조.

요지:
* 단계별 종료 조건을 명시, 무한 루프 금지
* 외부 명령 실패 시 재시도 1회, 2회 실패 시 사용자 보고
* 파일 삭제·git push·외부 시스템 변경은 사용자 승인 후 수행
* 애매 표현 금지, 조건문으로 해석
