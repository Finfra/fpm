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

> ⚠️ **본 표는 사람이 읽는 사본이다.** 기계 SSOT 는 [`scar-manifest.yml`](scar-manifest.yml) `payloads.flat_file.files[]` 이고, 실제 파일은 [`sh/scar-flatfile-sync.sh`](../sh/scar-flatfile-sync.sh) 가 prj3 원본에서 재생성한다. 목록을 손으로 고치지 말고 yml 을 고친 뒤 스크립트를 돌린다 (Issue388).

| 경로                                             | 역할                                  |
| :----------------------------------------------- | :------------------------------------ |
| `CLAUDE.md`                                      | 글로벌 설정 (nPTiR·SCAR 진입점)       |
| `Harness.md`                                     | 글로벌 SCAR 인덱스                    |
| `rules/language-rules.md`                        | 언어·문체 규칙                        |
| `rules/naming-rules.md`                          | 파일·폴더 네이밍 규칙                 |
| `rules/issue-g.md`                               | 이슈 관리 공통 규칙                   |
| `rules/info-files.md`                            | 정보 파일 저장 규칙                   |
| `rules/opus-4-8-execution-rules.md`              | Opus 4.8 실행 제약                    |
| `_doc_arch/rules-ondemand/md-rules.md`           | 마크다운 작성 규칙 (조건부 로드)      |
| `_doc_arch/rules-ondemand/nptir-rules.md`        | nPTiR 워크플로우 규칙 (조건부 로드)   |
| `_doc_arch/rules-ondemand/refs-rules.md`         | _doc_work/refs/ 관리 (조건부 로드)    |
| `_doc_arch/rules-ondemand/change-detect-rules.md`| 변경 탐지 3종 병렬 (조건부 로드)      |
| `commands/issue-reg-g.md`                        | 이슈 등록 (General)                   |
| `commands/issue-fix-g.md`                        | 이슈 해결 (General)                   |
| `commands/issue-closer-g.md`                     | 이슈 종결 (General)                   |
| `commands/needs.md`                              | nPTiR 진입 (needs 단계)               |
| `commands/design-doc.md`                         | 설계 문서 관리 (_doc_arch/)           |
| `commands/md-add.md`                             | 마크다운 파일 생성                    |
| `skills/issue-g/SKILL.md`                        | 이슈 워크플로우 글로벌 스킬           |
| `skills/dev-g/SKILL.md`                          | 개발 주기 글로벌 스킬                 |
| `skills/dev-w/SKILL.md`                          | 웹 개발 특화 스킬                     |
| `skills/issue-w/SKILL.md`                        | 이슈 워크플로우 (웹 도메인)           |
| `skills/doc-work-archive/SKILL.md`               | _doc_work z_done 아카이브 스킬        |
| `skills/git/SKILL.md`                            | git 작업 스킬                         |
| `skills/git/scripts/git_wrapper.sh`              | git 스킬 래퍼 스크립트                |

## 2026-08-16 목록 변경 (Issue388)

원본(prj3)이 움직였는데 사본이 따라가지 않아 몇 달치 표류가 쌓여 있었다. 실측 29개 중 원본과 일치한 것은 1개뿐이었다.

| 변경 | 대상 | 사유 |
| :--- | :--- | :--- |
| **경로 이동** | `rules/{md,nptir,refs,change-detect}-rules.md` → `_doc_arch/rules-ondemand/` | 조건부 로드 룰로 재편(prj3). 상시 로드 비용 절감 |
| **개명** | `rules/opus-4-7-execution-rules.md` → `opus-4-8-execution-rules.md` | 모델 세대 갱신 |
| **제거** | `commands/gstack-{plan,report,retro-report}.md` · `skills/gstack/SKILL.md` | prj3 원본에서 폐기됨 — 사본에만 잔존하던 유령 |
| **제거** | `commands/new-project.md` | prj3 원본에서 폐기 (`fpm-pm-new` 계열로 대체) |
| **추가** | `skills/git/scripts/git_wrapper.sh` | 이미 배포되고 있었으나 표에서 누락돼 있던 항목 |

⚠️ `_doc_arch/rules-ondemand/` 는 `protect[]` 의 `_doc_arch/` 에 걸리므로 **`protect_exceptions[]` 예외가 없으면 배포에서 조용히 빠진다.** 그러면 함께 나가는 `CLAUDE.md` 의 조건부 로드 표가 전부 죽은 링크가 된다.

# 설치 방법

## 전제 조건

* 대상 서버에 Claude Code CLI 설치 완료
* `~/.claude/` 디렉토리 없거나 비어있어야 함 (또는 백업 후 진행)

## rsync 설치 명령 (jm4 → 원격 서버)

> ⚠️ **`--delete` 필수 (Issue240)**: `--delete` 없이 rsync 하면 소스에서 rename·삭제된
> SCAR 파일이 원격 `~/.claude/` 에 orphan 으로 **잔존**한다("파일을 지우지 못하는 현상").
> 반드시 `--delete` + `--exclude`(대상 서버 사용자 데이터 보존) 를 함께 쓴다.
> 페이로드 파일 목록·보존 패턴의 SSOT 는 [`data/scar-manifest.yml`](scar-manifest.yml)
> `payloads.flat_file` 이다. (자동화는 `remote.sh`(to-be) 가 본 yml 을 직접 소비)

```bash
# 원격 서버 주소 및 사용자명 변수 설정
TARGET_HOST="user@server.example.com"
SRC="$HOME/_git/___pm/data/claude_forNewServer/"

# ⚠️ 순서 중요 — rsync 는 먼저 매칭되는 규칙이 이긴다. include 를 exclude 앞에 둔다.
#   scar-manifest.yml payloads.flat_file.protect_exceptions[] 에 해당 (Issue388).
#   빠뜨리면 조건부 로드 룰 4종이 조용히 배포되지 않고 CLAUDE.md 참조가 죽는다.
INCL=(--include '_doc_arch/' --include '_doc_arch/rules-ondemand/' \
      --include '_doc_arch/rules-ondemand/**')

# 보존 대상(대상 서버 사용자 데이터) — scar-manifest.yml payloads.flat_file.protect 와 동일
EXCL=(--exclude 'Issue.md' --exclude 'projects/' --exclude '_doc_work/' \
      --exclude '_doc_arch/' --exclude 'settings.json' --exclude 'settings.local.json' \
      --exclude 'memory/' --exclude '*.local.*')

# dry-run 먼저 확인 (--delete 로 지워질 orphan 까지 미리 표시)
rsync -avzn --delete "${INCL[@]}" "${EXCL[@]}" --progress \
  "$SRC" \
  "${TARGET_HOST}:~/.claude/"

# 확인 후 실제 실행
rsync -avz --delete "${INCL[@]}" "${EXCL[@]}" --progress \
  "$SRC" \
  "${TARGET_HOST}:~/.claude/"
```

## 로컬 서버 설치 (동일 머신)

```bash
SRC="$HOME/_git/___pm/data/claude_forNewServer/"
DEST="$HOME/.claude/"
INCL=(--include '_doc_arch/' --include '_doc_arch/rules-ondemand/' \
      --include '_doc_arch/rules-ondemand/**')
EXCL=(--exclude 'Issue.md' --exclude 'projects/' --exclude '_doc_work/' \
      --exclude '_doc_arch/' --exclude 'settings.json' --exclude 'settings.local.json' \
      --exclude 'memory/' --exclude '*.local.*')

# dry-run
rsync -avzn --delete "${INCL[@]}" "${EXCL[@]}" "$SRC" "$DEST"

# 실제 실행
rsync -avz --delete "${INCL[@]}" "${EXCL[@]}" "$SRC" "$DEST"
```

> 🚨 **jm4 에서 로컬 설치를 실행하지 말 것** — `DEST` 가 곧 prj3 원본(`~/.claude`)이다. 사본을 원본에 되쓰면 단방향 원칙이 깨지고, `--delete` 가 사본에 없는 원본 파일을 지운다. 이 절은 **원본을 보유하지 않은 다른 머신** 전용이다 (Issue388).

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
