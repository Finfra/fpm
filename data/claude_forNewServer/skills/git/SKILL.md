---
title: git
description: Git 작업(status, add, commit, push) 및 checkpoint 검증을 수행합니다.
---

# Git Skill (Git 작업 스킬)

이 스킬은 Git 워크플로우를 단순화하고 자동화합니다. 단순한 명령어 실행뿐만 아니라, **checkpoint(이슈 파일의 최신 커밋 해시 기록)** 검증 로직을 포함하여 안전한 푸시를 보장합니다.

## 안전 가드 (Safety Guard)

이 스킬이 지켜야 할 것은 **인덱스 무결성**(아래 절)과 **checkpoint 검증**이다. git 은 로컬 저장소 작업이므로 서버 접근 정보를 요구하지 않는다.

> ⚠️ **제거 이력 (Issue336)**: 과거 이 자리에 `[ -f "data/finfra-server-access.md" ] || exit 1` 가드가 있었다. 그 파일을 가진 프로젝트는 **social·finfraHome 둘뿐**이라 나머지 60여 프로젝트에서 스킬이 항상 즉시 종료됐다. 커밋 이력 추적 결과 `2c9254b Sync: sync-claude-ma` 대량 동기화로 유입된 것이며 git 스킬 고유의 설계가 아니었다. 해당 가드는 실제로 Cafe24 서버에 접속하는 [`curl`](../curl/SKILL.md)·[`ssh`](../ssh/SKILL.md)·[`cdn`](../cdn/SKILL.md)·[`mysql`](../mysql/SKILL.md) 4종에만 유효하며 그쪽은 그대로 둔다.

## 인덱스 무결성 (Issue287)

FUSE·네트워크 마운트 repo 는 인덱스가 조용히 축소될 수 있다. push 전 아래 1줄로 확인:

```bash
[ "$(git ls-files | wc -l)" -ge "$(git ls-tree -r HEAD --name-only | wc -l)" ] || echo "🚨 인덱스가 HEAD 트리보다 작음 — 인덱스 유실 의심"
```

* 예방(FUSE repo): `git config core.fsmonitor false` 고정. `git -c core.fsmonitor=...` 호출별 토글 금지
* 탐지 자동화: PostToolUse hook [`git-tree-shrink-guard.sh`](../../hooks/git-tree-shrink-guard.sh) 가 commit/push 직후 트리 급감을 경고
* 복구 절차: [`_doc_arch/rules-ondemand/git-index-integrity-rules.md`](../../_doc_arch/rules-ondemand/git-index-integrity-rules.md)

## 필수 조건 (Prerequisites)
- `git` 명령어가 설치되어 있어야 함.
- 프로젝트 루트에 `Issue.md` 파일이 존재해야 함 (checkpoint 검증용).

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

# 4. 푸시 (checkpoint 검증 포함)
sh ~/.claude/skills/git/scripts/git_wrapper.sh push

# 5. 일괄 처리 (Auto: Status -> Add -> Commit -> Push)
sh ~/.claude/skills/git/scripts/git_wrapper.sh auto "메시지 내용"
```

## 기능 (Features)
- **Status**: `git status` 실행.
- **Add**: `git add` 실행 (인자 없으면 `.` 사용).
- **Commit**: `git commit -m` 실행. 메시지 없으면 에러 또는 `-v` 모드 진입.
- **Push**:
    - `Issue.md`에 기록된 마지막 checkpoint(Commit Hash)가 현재 HEAD와 일치하는지 확인.
    - 일치하지 않으면 경고 메시지 출력 (강제 푸시 옵션 없음, 사용자가 직접 해결 권장).
    - 검증 통과 시 `git push` 실행.
