---
name: git-status
description: 등록된 모든 프로젝트의 git checkout 상태(브랜치·원격 차이·작업트리·중단된 merge/rebase)를 한 표로 조회. 읽기 전용·네트워크 미접속.
date: 2026.08.17
---

# 용도

`projects/` 에 등록된 프로젝트 전체가 **지금 어느 브랜치에 체크아웃돼 있고 작업트리가 깨끗한가**를 한 화면에 모은다. 프로젝트를 40개 넘게 오가면 다음이 조용히 쌓이는데, 개별 repo 에 들어가 보지 않으면 드러나지 않는다.

* 딴 브랜치(`feat/...`·`docs/...`)에 체크아웃된 채 방치 → 다음 작업이 엉뚱한 브랜치에 얹힘
* 미커밋 변경·untracked 잔여물이 남은 repo
* **중단된 merge·rebase·cherry-pick** (충돌 해결 도중 세션이 끊긴 자리)
* push 안 된 로컬 커밋(ahead) — 다른 머신(ma·fg1)에서 그 작업이 안 보인다

# 호출

```
/git-status [번호|범위...] [--dirty] [--md]
```

| 인자 | 동작 |
| :--- | :--- |
| 없음 · `all` | 등록된 전체 프로젝트 (43건 기준 약 5초) |
| `1 3 11-16` | 번호·범위 지정 (`a-b` 는 전개) |
| `--dirty` | **변경·이상 있는 프로젝트만** — clean·제외 행을 숨김 |
| `--md` | markdown 표로 출력 (문서 붙여넣기·hub 렌더용) |
| `--no-color` | ANSI 색 제거 (파이프 시 자동 적용) |

# 실행

구현은 [sh/fpm-git-status.sh](sh/fpm-git-status.sh) 단일 스크립트다. **인자를 그대로 넘겨 1회 실행하고 출력을 그대로 보고**한다 — Claude 가 프로젝트별로 `git status` 를 반복 호출하지 않는다(43 repo × 4콜 = 토큰·시간 낭비).

```bash
bash "$HOME/_git/___pm/sh/fpm-git-status.sh" $ARGUMENTS
```

* `FPM_BASE` 가 설정돼 있으면 그 인덱스를, 없으면 스크립트 자기 repo 의 `projects/` 를 쓴다 (설치 위치 무관)
* 스크립트가 자체 요약 줄(`총 N건 · ✅ clean · ✏️ 변경 · ⚠️ 주의 · — 제외`)을 출력하므로 **집계를 다시 세지 않는다**

# 출력 읽는 법

```
prj  이름               브랜치                     원격         변경      비고
5    common             feat/aoa-mq-kind-digest    no-upstream  ~6 ?1     stash 1
9    <private-project-2>       main                       ^29          ~5 ?7     stash 1
41   videoMaker         main                       ^44 v2       ~1 ?8
900  ...                main                       no-upstream  !1 ?1     merge 중단
```

| 칸 | 표기 | 의미 |
| :--- | :--- | :--- |
| 브랜치 | `main` · `develop` | 체크아웃된 브랜치 |
| 브랜치 | `detached@d92135f` | **detached HEAD** — 커밋해도 브랜치에 안 남음 (⚠️ 주의 등급) |
| 원격 | `=` | upstream 과 동일 |
| 원격 | `^29` · `v2` | `^`=ahead(push 안 된 로컬 커밋) · `v`=behind |
| 원격 | `no-upstream` | 추적 브랜치 없음 (로컬 전용 브랜치이거나 `-u` 미설정) |
| 변경 | `clean` | 작업트리 깨끗 |
| 변경 | `+n ~n ?n` | `+`staged · `~`unstaged · `?`untracked 건수 |
| 변경 | `!n` | **충돌 파일** n건 (⚠️ 주의 등급) |
| 비고 | `merge 중단` · `rebase 중단` · `cherry-pick 중단` · `bisect 중` | 진행 중이던 작업이 남아 있음 |
| 비고 | `stash n` | stash 보유 건수 |
| 비고 | `상위 repo=…` | 프로젝트 경로가 repo 루트가 아님 → 표시된 상태는 **상위 repo 전체**의 것 |
| 비고 | `git repo 아님` · `경로 부재` · `인덱스 파일 없음` | 조회 제외 행 |

색: 🟢 clean · 🟡 변경 있음 · 🔴 주의(detached·충돌·중단된 merge/rebase) · 회색 제외.

# 읽기 전용 보장

본 커맨드는 **어떤 repo 도 변경하지 않는다.**

* 실행하는 git 하위명령은 `rev-parse` · `status --porcelain` · `rev-list` · `stash list` 뿐
* **fetch 하지 않는다** → `^`/`v` 는 **로컬 ref 기준**이다. 원격 실태와 정확히 맞춰야 하면 사용자가 해당 repo 에서 fetch 후 재실행 (43 repo 일괄 fetch 는 네트워크 부작용이라 커맨드에 넣지 않음)
* `-c core.fsmonitor=false` 로 호출 — FUSE·네트워크 마운트 repo 의 인덱스 손상 회피 (글로벌 룰 `~/.claude/_doc_arch/rules-ondemand/git-index-integrity-rules.md` — 워크스페이스 밖이라 링크 대신 경로 표기)

정리 작업(브랜치 전환·커밋·push·stash pop)은 **본 커맨드의 일이 아니다.** 조회 결과를 보고 사용자가 지시한다.

# 실행 제약 (Opus 4.8)

* 스크립트 실행 **1회**. 실패 시 원인(경로·권한) 보고 후 대기 — 프로젝트별 개별 `git` 호출로 우회하지 않는다
* 대상 프로젝트 최대 60개(전체 등록 규모). 초과 시 번호 범위로 분할
* 출력 행이 40행을 넘으면 `--dirty` 를 함께 제안 (조치가 필요한 행만 남음)

# 연관

* 인덱스 SSOT: [Projects.md](Projects.md) → `projects/{번호}` (동기화 `sh/fpm-projects-sync`)
* 이력 재작성 착수 게이트(작업트리 clean 검사): [sh/git-rewrite-preflight.sh](sh/git-rewrite-preflight.sh)
* 프로젝트 폴더 무결성 검사: [/pm-check](.claude/commands/pm-check.md)
