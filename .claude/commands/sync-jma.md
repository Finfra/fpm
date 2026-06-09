---
name: sync-jma
description: "jm4 ↔ jma 양방향 rsync 동기화 (git 미사용). prj 4, 9, 11~16, 25, 26, 91, 93 을 jma 에서 개발하기 위한 파일 동기화. target(social/data/fapp/public/ollamaClaude/dashboardPoc/all 또는 prj id) + direction(push/pull) 인자"
date: 2026-06-08
---

jm4(로컬) ↔ jma 간 **rsync 전용** 동기화 커맨드. prj 4, 9, 11~16, 25, 26, 91, 93 을 jma 에서 개발하기 위함.
글로벌 `~/.claude/skills/sync/index.md` 의 `rsync-only` 유형(Phase 1~3 git 스킵, Phase 4 rsync 만)을 따름.

> **git 미사용**: 본 커맨드는 commit/push/pull 을 하지 않음. 순수 파일 동기화. git 동기화가 필요하면 `/sync-ma` 사용.
> **rsync 는 병합 없음**: last-write-wins. 방향(`push`/`pull`)을 명시적으로 지정해야 함. 양방향 자동 동시 실행 안 함.

# 사용법

```
/sync-jma <target> <direction> [--dry-run] [--delete]
```

* `<target>`: `social` | `data` | `fapp` | `public` | `ollamaClaude` | `dashboardPoc` | `all` | prj id (`4`, `9`, `11`~`16`, `25`, `26`, `91`, `93`)
* `<direction>`: `push`(jm4→jma) | `pull`(jma→jm4) — **필수**. 생략 시 usage 출력 후 중단
* `--dry-run`: rsync `-n` 추가. 전송 없이 변경 목록만 출력 (방향 위험 점검용 — 첫 실행 권장)
* `--delete`: rsync `--delete` 추가. 대상에 있고 원본에 없는 파일 삭제(완전 미러). **기본 미적용** — 사용 시 사용자 확인 필수

ex) `/sync-jma all push --dry-run` / `/sync-jma fapp push` / `/sync-jma 15 pull`

# 고정 설정

| 파라미터       | 값                |
| :------------- | :---------------- |
| `target_host`  | `jma` (ssh alias) |
| `sync_type`    | `rsync-only`      |
| `local_host`   | `jm4`             |

# 대상 정의

| target   | prj    | 경로                                                                                  | rsync_exclude (공통 외 추가) |
| :------- | :----- | :------------------------------------------------------------------------------------ | :--------------------------- |
| `social` | 4      | `~/_git/__all/social`                                                                  | `--exclude='.playwright-mcp'` (browser 캐시 4.8M 비전송) |
| `data`   | 9      | `~/Documents/finfra/fSnippetData`                                                      | (없음)                       |
| `fapp`   | 11~16  | `~/_git/__all/{fBanner,fBoard,fGoogleSheet,fQRGen,fSnippet,fWarrange}`                 | fSnippet·fWarrange 는 `--exclude='_public'` (public 타깃이 별도 소유) |
| `public` | 25, 26 | `~/_git/__all/fSnippet/_public`, `~/_git/__all/fWarrange/_public`                      | (없음)                       |
| `ollamaClaude` | 91 | `~/_git/__all/ollamaClaude`                                                          | (없음)                       |
| `dashboardPoc` | 93 | `~/_git/__all/dashboardPoc`                                                          | `--exclude='node_modules'` (184M, npm install 재생성) |
| `all`    | -      | social → data → fapp(_public 제외) → public → ollamaClaude → dashboardPoc 순차          | 위 각 항목 적용              |

> **중첩 주의**: prj 25·26(`_public`)은 prj 15·16 의 서브디렉토리. `fapp` 은 `--exclude='_public'` 로 _public 을 건너뛰고, `public` 타깃이 _public 을 단독 처리 → 이중 전송·충돌 없음.

# 공통 rsync 옵션

* 항상 적용: `-avz --exclude='.git' --exclude='.DS_Store'`
* `.git` 은 모든 깊이에서 제외 (각 repo 의 git 메타 비전송)
* `--dry-run` 지정 시 `-n` 추가
* `--delete` 지정 시 `--delete` 추가 (기본 미적용)

# 실행 절차

## 1. 인자 파싱 + 검증

* `direction` 없으면 → 위 "사용법" 출력 후 중단 (방향 미지정 위험)
* `target` 이 prj id 면 → 해당 단일 경로로 매핑
* `--delete` 있으면 → 실행 전 사용자에게 "완전 미러(대상 삭제 포함) 진행?" 확인

## 2. jma 도달 확인

```bash
ssh -o ConnectTimeout=5 jma 'echo OK' || { echo "jma 미응답 — 중단"; exit 1; }
```

## 3. rsync 실행 (방향별)

`push` (jm4 → jma):

```bash
rsync -avz --exclude='.git' --exclude='.DS_Store' $EXTRA "$path/" "jma:$path/"
```

`pull` (jma → jm4):

```bash
rsync -avz --exclude='.git' --exclude='.DS_Store' $EXTRA "jma:$path/" "$path/"
```

* `$path` 는 `$HOME` 절대경로로 전개 (jm4·jma HOME 동일: `$HOME`)
* `$EXTRA` = `--exclude='_public'`(fapp 의 fSnippet·fWarrange) + `--exclude='.playwright-mcp'`(social) + `--exclude='node_modules'`(dashboardPoc) + `-n`(dry-run) + `--delete`(옵션) 조합
* `all` 은 social → data → fapp 6개 → public 2개 → ollamaClaude → dashboardPoc 순차 실행

## 4. 결과 요약

대상 경로별:
* prj 번호·이름·경로
* 방향 (push/pull)
* rsync 전송 파일 수·총 크기 (rsync stats 말미)
* dry-run 여부

# 안전 규칙

* `direction` 필수 — 기본값 없음 (오방향 덮어쓰기 차단)
* 첫 실행·방향 전환 시 `--dry-run` 우선 권장
* `--delete` 는 사용자 확인 후에만
* git 동기화 필요 시 → `/sync-ma` (본 커맨드는 git 미관여)
