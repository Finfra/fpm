---
title: git
description: Git 작업(status, add, commit, push) 및 Save Point 검증을 수행합니다.
---

# Git Skill (Git 작업 스킬)

이 스킬은 Git 워크플로우를 단순화하고 자동화합니다. 단순한 명령어 실행뿐만 아니라, **Save Point(이슈 파일의 최신 커밋 해시 기록)** 검증 로직을 포함하여 안전한 푸시를 보장합니다.

## 안전 가드 (Safety Guard)

이 스킬을 실행하기 전, 반드시 현재 프로젝트 루트에 `data/finfra-server-access.md`가 존재하는지 확인합니다:

```bash
[ -f "data/finfra-server-access.md" ] || { echo "❌ data/finfra-server-access.md 없음 — Cafe24 서버 접근 정보가 없는 프로젝트입니다. 실행을 취소합니다."; exit 1; }
```

파일이 없으면 즉시 중단하고 사용자에게 알립니다.

## 필수 조건 (Prerequisites)
- `git` 명령어가 설치되어 있어야 함.
- 프로젝트 루트에 `Issue.md` 파일이 존재해야 함 (Save Point 검증용).

## 사용법 (Usage)

`scripts` 디렉토리의 `git_wrapper.sh`를 실행하여 Git 작업을 수행합니다.

```bash
# 도움말 표시
sh ~/.claude/skills/git/scripts/git_wrapper.sh help

# 1. 상태 확인
sh ~/.claude/skills/git/scripts/git_wrapper.sh status

# 2. 변경사항 스테이징 (기본: git add .)
sh ~/.claude/skills/git/scripts/git_wrapper.sh add [파일경로]

# 3. 커밋
sh ~/.claude/skills/git/scripts/git_wrapper.sh commit "메시지 내용"

# 4. 푸시 (Save Point 검증 포함)
sh ~/.claude/skills/git/scripts/git_wrapper.sh push

# 5. 일괄 처리 (Auto: Status -> Add -> Commit -> Push)
sh ~/.claude/skills/git/scripts/git_wrapper.sh auto "메시지 내용"
```

## 기능 (Features)
- **Status**: `git status` 실행.
- **Add**: `git add` 실행 (인자 없으면 `.` 사용).
- **Commit**: `git commit -m` 실행. 메시지 없으면 에러 또는 `-v` 모드 진입.
- **Push**:
    - `Issue.md`에 기록된 마지막 Save Point(Commit Hash)가 현재 HEAD와 일치하는지 확인.
    - 일치하지 않으면 경고 메시지 출력 (강제 푸시 옵션 없음, 사용자가 직접 해결 권장).
    - 검증 통과 시 `git push` 실행.
