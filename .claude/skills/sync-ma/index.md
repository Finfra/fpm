---
title: sync-ma
description: "jm4 → ma 동기화 통합 스킬. target 인자(claude/bin/pm/finfraHome/fapp/all)로 대상 선택. 글로벌 sync 스킬의 5-Phase 절차를 ma 설정으로 실행"
date: 2026-04-02
---

jm4(로컬)의 프로젝트를 ma에 동기화하는 통합 스킬.
글로벌 스킬 `~/.claude/skills/sync/index.md`의 공통 절차(Phase 1~5)를 따름.

# 인자

`$ARGUMENTS`로 동기화 대상을 지정. 이름 또는 Project ID 모두 사용 가능:

| 인자         | Project IDs | 대상                                                | 설명                                 |
| :----------- | :---------- | :-------------------------------------------------- | :----------------------------------- |
| `claude`     | 3           | ~/.claude                                           | SCAR 설정 동기화                     |
| `bin`        | -           | ~/.bin                                              | 유틸리티 스크립트 동기화             |
| `pm`         | 1           | ~/_git/___pm                                        | 프로젝트 관리 저장소 동기화          |
| `finfraHome` | 10          | ~/_git/__all/finfraHome                             | finfra.kr 홈페이지 동기화            |
| `fapp`       | 11~16       | fApp 6개 프로젝트                                   | macOS 앱 프로젝트 일괄 동기화        |
| `public`     | 25, 26      | fSnippet/_public, fWarrange/_public                 | _public 프로젝트 rsync 전용 동기화   |
| `cyberTech`  | 81          | /Users/nowage/work/work-cyberTech                   | 사이버 테크 외주 프로젝트 동기화     |
| `all`        | -           | claude → bin → pm → finfraHome → fapp → public 순차 | 전체 동기화                          |
| (생략)       | -           | Usage출력                                           | 기본값                               |

ex) `/sync-ma pm`, `/sync-ma 1`, `/sync-ma 10` 모두 유효

# ma 고정 설정

| 파라미터       | 값                 |
| :------------- | :----------------- |
| `target_host`  | `nowage@ma`       |
| `target_agent` | `sma`              |
| `local_host`   | `nowage@jm4.local` |

# 대상별 설정

## claude

| 항목            | 값                                                                   |
| :-------------- | :------------------------------------------------------------------- |
| `sync_type`     | `git-local`                                                          |
| `paths`         | `~/.claude`                                                          |
| `commit_msg`    | `Sync: sync-claude-ma`                                               |
| `rsync_exclude` | `--exclude='projects/' --exclude='debug/' --exclude='file-history/'` |

Phase 절차:
* Phase 1: 로컬 git commit (push 없음)
* Phase 2: sma로 ma commit 후 `git pull nowage@jm4.local:~/.claude`
* Phase 3: 스킵 (remote 없음)
* Phase 4: rsync (추가 exclude 적용)
* Phase 5: 결과 요약

## bin

| 항목            | 값                  |
| :-------------- | :------------------ |
| `sync_type`     | `git-local`         |
| `paths`         | `~/.bin`            |
| `commit_msg`    | `Sync: sync-bin-ma` |
| `rsync_exclude` | (없음)              |

Phase 절차:
* Phase 1: 로컬 git commit (push 없음)
* Phase 2: sma로 ma commit 후 `git pull nowage@jm4.local:~/.bin`
* Phase 3: 스킵 (remote 없음)
* Phase 4: rsync
* Phase 5: 결과 요약

## pm

| 항목            | 값                              |
| :-------------- | :------------------------------ |
| `sync_type`     | `git-remote`                    |
| `paths`         | `~/_git/___pm`                  |
| `commit_msg`    | `Sync: sync-pm-ma`              |
| `rsync_exclude` | `--exclude='projects/'`         |

Phase 절차:
* Phase 1: 로컬 git commit + push
* Phase 2: sma로 ma commit + pull
* Phase 3: 로컬 git pull
* Phase 4: rsync
* Phase 5: 결과 요약

## fapp

| 항목            | 값                                     |
| :-------------- | :------------------------------------- |
| `sync_type`     | `git-multi`                            |
| `paths`         | `fapp_load_projects` + `fapp_get_path` |
| `commit_msg`    | `Sync: sync-fapp-ma`                   |
| `rsync_exclude` | (없음)                                 |
| 헬퍼            | `source ~/.bin/fapp-helper.sh`         |

Phase 절차:
* Phase 1: 로컬 git commit + push (6개 병렬)
* Phase 2: sma로 ma commit + pull (6개 순차)
* Phase 3: 로컬 git pull (6개 병렬)
* Phase 4: rsync (6개 순차)
* Phase 5: 프로젝트별 결과 요약

## cyberTech

| 항목            | 값                                        |
| :-------------- | :---------------------------------------- |
| `sync_type`     | `git-local`                               |
| `paths`         | `/Users/nowage/work/work-cyberTech`       |
| `commit_msg`    | `Sync: sync-cyberTech-ma`                 |
| `rsync_exclude` | (없음)                                    |

Phase 절차:
* Phase 1: 로컬 git commit (push 없음 — remote 미설정)
* Phase 2: sma로 ma commit 후 `git pull nowage@jm4.local:/Users/nowage/work/work-cyberTech`
* Phase 3: 스킵 (remote 없음)
* Phase 4: rsync
* Phase 5: 결과 요약

## public

| 항목            | 값                                                                  |
| :-------------- | :------------------------------------------------------------------ |
| `sync_type`     | `rsync-only`                                                        |
| `paths`         | `~/_git/__all/fSnippet/_public`, `~/_git/__all/fWarrange/_public`   |

Phase 절차:
* Phase 1~3: 스킵 (git 미사용)
* Phase 4: rsync (`--exclude='.git'`)
* Phase 5: 프로젝트별 결과 요약

# all 실행 순서

`all` (또는 인자 생략) 시 아래 순서로 순차 실행:

1. `claude` 실행
2. `bin` 실행
3. `pm` 실행
4. `finfraHome` 실행
5. `fapp` 실행
6. `public` 실행


최종 출력:

| 대상       | 상태  |
| :--------- | :---- |
| claude     | ✅/❌ |
| bin        | ✅/❌ |
| pm         | ✅/❌ |
| finfraHome | ✅/❌ |
| fapp       | ✅/❌ |
| public     | ✅/❌ |



# Opus 4.7 실행 제약

공통 제약은 [`~/.claude/rules/opus-4-7-execution-rules.md`](~/.claude/rules/opus-4-7-execution-rules.md) 참조. 이 skill 특화 제약:

* (해당 없음 — 추후 운영 중 식별되면 추가)
