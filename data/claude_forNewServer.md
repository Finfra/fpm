---
name: claude_forNewServer
description: 고객 서버 ~/.claude 구축 가이드 — nPTiR·SCAR 글로벌 하네스 설치·사용법 및 진행 현황
date: 2026-04-28
---

# 개요

`data/claude_forNewServer/` 디렉토리를 새 서버의 `~/.claude`에 복사하면
nPTiR (needs/Plan/Task/issue/Report) + SCAR (Skills/Commands/Agents/Rules) 글로벌 하네스가
즉시 활성화됨.

* ___pm 프로젝트 없음
* fApp / Obsidian / 개인 정보 / macOS 앱(-m) 도메인 제외
* 글로벌 General(g) + 웹(w) 레이어만 포함 (서버 환경 기준)

# 포함 목록

| 경로                                | 역할                                  |
| :---------------------------------- | :------------------------------------ |
| `CLAUDE.md`                         | 글로벌 설정 (nPTiR·SCAR 진입점)       |
| `Harness.md`                        | 글로벌 SCAR 인덱스                    |
| `rules/language-rules.md`           | 언어·문체 규칙                        |
| `rules/md-rules.md`                 | 마크다운 작성 규칙                    |
| `rules/naming-rules.md`             | 파일·폴더 네이밍 규칙                 |
| `rules/nptir-rules.md`              | nPTiR 워크플로우 전체 규칙            |
| `rules/issue-g.md`                  | 이슈 관리 공통 규칙                   |
| `rules/refs-rules.md`               | _doc_work/refs/ 참고자료 관리 규칙    |
| `rules/change-detect-rules.md`      | 변경 탐지 3종 병렬 규칙               |
| `rules/info-files.md`               | 정보 파일 저장 규칙                   |
| `rules/opus-4-7-execution-rules.md` | Opus 4.7 실행 제약                    |
| `commands/issue-reg-g.md`           | 이슈 등록 (General)                   |
| `commands/issue-fix-g.md`           | 이슈 해결 (General)                   |
| `commands/issue-closer-g.md`        | 이슈 종결 (General)                   |
| `commands/needs.md`                 | nPTiR 진입 (needs 단계)               |
| `commands/design-doc.md`            | 설계 문서 관리 (_doc_arch/)         |
| `commands/new-project.md`           | 프로젝트 초기화                       |
| `commands/md-add.md`                | 마크다운 파일 생성                    |
| `commands/gstack-plan.md`           | gstack × nPTiR 계획                   |
| `commands/gstack-report.md`         | gstack × nPTiR 보고서                 |
| `commands/gstack-retro-report.md`   | gstack × nPTiR 회고                   |
| `skills/issue-g/SKILL.md`           | 이슈 워크플로우 글로벌 스킬           |
| `skills/dev-g/SKILL.md`             | 개발 주기 글로벌 스킬                 |
| `skills/dev-w/SKILL.md`             | 웹 개발 특화 스킬                     |
| `skills/issue-w/SKILL.md`           | 이슈 워크플로우 (웹 도메인)           |
| `skills/doc-work-archive/SKILL.md`  | _doc_work z_done 아카이브 스킬        |
| `skills/git/SKILL.md`               | git 작업 스킬                         |
| `skills/gstack/SKILL.md`            | gstack 스킬                           |

# 설치 방법

## 전제 조건

* 대상 서버에 Claude Code CLI 설치 완료
* `~/.claude/` 디렉토리 없거나 비어있어야 함 (또는 백업 후 진행)

## rsync 설치 명령 (jm4 → 원격 서버)

```bash
# 원격 서버 주소 및 사용자명 변수 설정
TARGET_HOST="user@server.example.com"
SRC="/Users/nowage/_git/___pm/data/claude_forNewServer/"

# dry-run 먼저 확인
rsync -avzn --progress \
  "$SRC" \
  "${TARGET_HOST}:~/.claude/"

# 확인 후 실제 실행
rsync -avz --progress \
  "$SRC" \
  "${TARGET_HOST}:~/.claude/"
```

## 로컬 서버 설치 (동일 머신)

```bash
SRC="/Users/nowage/_git/___pm/data/claude_forNewServer/"
DEST="~/.claude/"

# dry-run
rsync -avzn "$SRC" "$DEST"

# 실제 실행
rsync -avz "$SRC" "$DEST"
```

## 설치 후 확인

```bash
# 설치 확인
ls ~/.claude/rules/ ~/.claude/commands/ ~/.claude/skills/

# CLAUDE.md 로드 확인
cat ~/.claude/CLAUDE.md
```

# 사용법

## 새 프로젝트 시작

```
/new-project
```

* `Issue.md`, `CLAUDE.md`, `noteForHuman.md`, `PROMPTS.md`, `Harness.md` 생성
* `_doc_work/{plan,tasks,report,z_done}/`, `_doc_arch/`, `.claude/` 폴더 생성

## 이슈 기반 개발 주기

```
/dev        ← 자동 모드 (Issue.md 기반)
/dev [N]    ← 이슈후보 N번 즉시 진행
```

내부 흐름: `/issue-reg` → `/issue-fix` → `/issue-closer`

## nPTiR 진입

```
/needs {주제}    ← 탐색 단계 (brainstorming or writing-plans 라우팅)
/sp-plan         ← 계획 단계 단축 진입
```

## 이슈 직접 관리

```
/issue-reg-g     ← General 이슈 등록
/issue-fix-g     ← General 이슈 해결
/issue-closer-g  ← General 이슈 종결
```

## 설계 문서 관리

```
/design-doc      ← _doc_arch/ 영속 설계 문서 생성·관리
```

# 진행 현황 (Issue13)

## 완료
- [x] Issue13 등록 (2026-04-28)
- [x] data/claude_forNewServer.md 생성 (이 파일)
- [x] CLAUDE.md (서버용 적응 — 개인정보·___pm·fApp 제거)
- [x] rules/ 복사 완료 (9개 rules + info-files.md 서버용 재작성)
- [x] commands/ 복사 완료 (issue-*-g, needs, design-doc, new-project 등 10개, new-project 서버용 재작성)
- [x] skills/ 복사 완료 (issue-g, dev-g, dev-w, issue-w, doc-work-archive, git, gstack — -m 도메인 제외)

## 진행 중
- [ ] Harness.md (글로벌 전용)

## 미착수
- [ ] 테스트 검증 (rsync dry-run)
- [ ] 커밋 및 Issue13 종결
