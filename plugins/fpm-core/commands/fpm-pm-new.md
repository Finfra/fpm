---
name: fpm-pm-new
description: 프로젝트 타입별 초기화 (general/web/mac). pm 스킬 기반.
date: 2026-04-11
---

skill: "pm" (action: new)

# 실행 절차

인자: `$ARGUMENTS`

지원 형식:
* **형식 A**: `<타입> <프로젝트번호> <대상>` — 명시형
* **형식 B**: `<대상>` — 단일 인자, 타입·번호 자동 추론

## 0. 인자 검증

* 인자 없음 → Usage + 번호 대역 규칙 + `cdf` 현황 출력 후 종료
* **인자 1개**: 형식 B로 처리 (자동 추론)
    - 대상이 절대/상대 경로면 그대로 사용, 프로젝트명만 입력 시 `~/_git/__all/{프로젝트명}`
    - 타입 자동 추론: `*.xcodeproj`/`Package.swift` → `mac`, `package.json`/`tsconfig.json` → `web`, 그 외 → `general`
    - 폴더 미존재 → `general` 신규 생성으로 처리
    - 번호 자동 할당: `Projects.md` 번호 대역 규칙에서 타입 매핑(`mac`→맥 대역, `web`/`general`→일반 대역 중 설명과 맞는 대역) 후 빈 번호 중 최소값
    - 추론 결과(`타입`/`번호`/`대상`)를 출력하고 **사용자 컨펌** 후 진행
* **인자 3개**: 형식 A로 처리
    - 타입: `general` / `web` / `mac` 중 하나
    - 프로젝트번호: 숫자, `projects/{번호}` 파일이 이미 존재하면 에러
    - 대상: 폴더 경로 또는 프로젝트명 (프로젝트명 시 `~/_git/__all/{프로젝트명}`)
* 추론 규칙·번호 자동 할당 상세는 pm 스킬의 `# pm-new 자동 추론 (형식 B)` 참조

### 0-1. 기존 프로젝트 흡수 (adopt 모드)

대상 폴더가 기존 프로젝트(`.git`, `CLAUDE.md`, `Issue.md`, 소스 보유)인 경우:

* **adopt 모드** 진입: pm 스킬의 `# 기존 프로젝트 흡수 (adopt) 모드` 참조
* **멱등 규칙**: 다음 단계들(1-1·1-3·1-4·1-8·1-14)은 기존 파일 보존 — 덮어쓰지 않음
    - 1-1: `.git` 이미 존재 시 스킵 (git init 제외)
    - 1-3: `CLAUDE.md` 이미 존재 시 보존 (템플릿 덮어쓰기 금지)
    - 1-4: `Issue.md` 이미 존재 시 보존 (커스텀 내용 유지)
    - 1-8: `.vscode/settings.json` 이미 존재 시 기존 peacock 색·설정 존중 (상세 아래)
    - 1-14: 기존 git repo 면 신규 initial commit 보류, 기존 커밋 이력 유지
* `.vscode/settings.json` 양방향 동기화:
    - 기존 파일에 peacock 색이 있으면 → 기존 색 채택 (Projects.md와 일치 확인)
    - 기존 peacock 색 없으면 → 신규 색 지정 (단계 1-8 자동 선택)
    - `/peacock-sync` 드라이런으로 색·경로 동기화 검증 추가 (선택 사항)

### 0-2. 경로 정규화 (필수)

`projects/{번호}` 및 `Projects.md` 기록 직전에 `$HOME` 접두사를 `~`로 치환:

* 입력 경로가 `$HOME` (=`/Users/{user}`) 으로 시작 → `~`로 치환 후 저장
    - ex) `$HOME/work/AgenticCoding_lec` → `~/work/AgenticCoding_lec`
    - ex) `$HOME/_git/__all/foo` → `~/_git/__all/foo`
* 입력 경로가 `$HOME` 외부 (ex: `/Volumes/...`, `/opt/...`, `/tmp/...`) → 그대로 저장
* 이미 `~`로 시작 → 그대로 저장
* 상대 경로(`./foo`, `foo`) → `realpath`로 절대 변환 후 위 규칙 재적용
* **이유**: `Projects.md` 일관성 유지 + 사용자 변경(머신 마이그레이션 등) 시 경로 갱신 불필요

구현 (zsh):
```sh
# 정규화 함수
normalize_path() {
    local p="$1"
    # 절대 경로로 변환 (상대 → 절대)
    [[ "$p" != /* && "$p" != ~* ]] && p="$(realpath "$p" 2>/dev/null || echo "$p")"
    # ~ 확장된 형태도 다시 ~로 축약
    [[ "$p" == "$HOME"* ]] && p="~${p#$HOME}"
    echo "$p"
}
```

위 정규화는 `projects/{번호}` 기록 (1-12) 및 `Projects.md` 테이블 행 추가 (1-13) 양쪽에 적용.

## 1. 전체 프로젝트 공통 생성

| #    | 항목                    | 소스/동작                                                                 |
| :--- | :---------------------- | :------------------------------------------------------------------------ |
| 1-1  | `git init`              | `.git` 미존재 시만 실행 (폴더 없으면 생성). 기존 repo이면 스킵             |
| 1-2  | `.gitignore`            | 템플릿: `___pm/data/template/gitignore`. 이미 존재 시 diff 후 누락분 추가 |
| 1-3  | `CLAUDE.md`             | 미존재 시만 생성 (기존 커스텀 보존). 템플릿: 프로젝트명·타입 반영          |
| 1-4  | `Issue.md`              | 미존재 시만 생성 (기존 커스텀 보존). 템플릿: `___pm/data/template/Issue.md` |
| 1-5  | `noteForHuman.md`       | 템플릿: `___pm/data/template/noteForHuman.md`                             |
| 1-6  | `PROMPTS.md`            | 템플릿: `___pm/data/template/PROMPTS.md`. date 치환                       |
| 1-7  | `Harness.md`            | 템플릿: `___pm/data/template/Harness.md` + 타입별 global layer 자동 채움  |
| 1-8  | `.vscode/settings.json` | 기존 파일 있으면 기존 peacock 색 존중 (양방향 동기화). 없으면 신규 색 지정. `/peacock-sync` dry-run 검증 권장 |
| 1-9  | `.claude/`              | `settings.json` 기본 구조 생성 (미존재 시)                                |
| 1-10 | `_doc_work/`            | 서브폴더 포함 생성: `tasks/`, `report/`, `plan/`, `history/`, `z_done/` (미존재 시) |
| 1-11 | `_doc_arch/`            | 서브폴더 포함 생성: `z_old/` (미존재 시)                                  |
| 1-12 | `projects/{번호}` 등록  | **정규화 후** `___pm/projects/{번호}` 파일에 경로 기록 (`$HOME` → `~` 치환 필수. 0-2 참조). 기존 pm에 이미 등록된 번호 중복 금지 |
| 1-13 | `Projects.md` 업데이트  | 테이블 행 + setting Script echo 라인 추가                                 |
| 1-14 | initial commit          | 신규 git repo 인 경우만 수행 (기존 repo이면 스킵, 커밋 이력 유지)          |
| 1-15 | `___pm/Harness.md` 등록 | 생성된 스킬·커맨드를 `___pm/Harness.md`의 해당 레이어에 기록              |
| 1-16 | `pm-history.md` 기록    | `_doc_work/pm-history.md`에 실행 이력 append                              |

## 2. 웹 프로젝트 추가 (타입=web)

| #   | 항목                      | 소스/동작                                                                         |
| :-- | :------------------------ | :-------------------------------------------------------------------------------- |
| 2-1 | `.gitignore` 웹 항목 추가 | `node_modules/`, `.next/`, `.nuxt/`, `.env`, `.env.local`, `coverage/`, `.turbo/` |
| 2-2 | `package.json`            | 프로젝트명 반영한 기본 생성 (`npm init -y` 기반)                                  |
| 2-3 | `tsconfig.json`           | TypeScript 기본 설정                                                              |
| 2-4 | `.env.example`            | 환경변수 예시 파일 (빈 템플릿)                                                    |
| 2-5 | `public/`                 | 빈 폴더 생성                                                                      |
| 2-6 | `src/`                    | 빈 폴더 생성                                                                      |
| 2-7 | `src/components/`         | 빈 폴더 생성                                                                      |

## 3. macOS 앱 추가 (타입=mac)

| #   | 항목                         | 소스/동작                                                                                            |
| :-- | :--------------------------- | :--------------------------------------------------------------------------------------------------- |
| 3-1 | `.gitignore` Xcode 항목 추가 | `DerivedData/`, `xcuserdata/`, `*.xcarchive`, `*.dSYM`, `*.ipa`, `Package.resolved`, `*.playground/` |
| 3-2 | `_public/`                   | 빈 폴더 생성                                                                                        |
| 3-3 | `_tool/`                     | 빈 폴더 생성                                                                                        |
| 3-4 | `capture/`                   | 빈 폴더 생성                                                                                        |
| 3-5 | `capture_/`                  | 빈 폴더 생성                                                                                        |
| 3-6 | `lib/`                       | 빈 폴더 생성                                                                                        |
| 3-7 | `z_test/`                    | 빈 폴더 생성                                                                                        |
| 3-8 | `logs/`                      | 빈 폴더 생성                                                                                        |
| 3-9 | `_doc_work/_release/`        | 빈 폴더 생성                                                                                        |
| 3-10| `_doc_arch/define/`          | 빈 폴더 생성                                                                                        |

## Harness.md global layer 자동 채움

pm 스킬의 SKILL.md 참조:
1. 동일 타입 기존 프로젝트에서 SCAR 수집
2. 수집 불가 시 폴백 기본값 사용
3. Skills/Commands/Agents/Rules 섹션별 채움

## vscode.json 컬러·이모지 선택

pm 스킬의 SKILL.md 참조:
1. 기존 프로젝트 사용 현황 수집
2. 타입별 컬러 톤 가이드 적용
3. 중복 불가 (컬러 + 이모지 모두)

### adopt 모드에서의 peacock 동기화

기존 프로젝트 흡수(adopt 모드) 시:
1. `.vscode/settings.json` 이미 존재 → 기존 peacock 색·이모지 존중 (Projects.md 등록색과 일치 확인)
2. 기존 peacock 정의 없음 → 신규 색 선택 (위 1~3 규칙 따름)
3. `/peacock-sync` 드라이런으로 색·경로·Projects.md 동기화 상태 검증 (선택 사항)

## Usage (인자 없을 때)

```
Usage:
  /pm-new <타입> <프로젝트번호> <대상>   (형식 A: 명시)
  /pm-new <대상>                          (형식 B: 자동 추론)

타입:
  general  일반 프로젝트
  web      웹 프로젝트
  mac      macOS 앱 (fApp/fappCli)

대상:
  폴더 경로 또는 프로젝트명 (프로젝트명만 입력 시 ~/_git/__all/<프로젝트명>)

자동 추론 (형식 B):
  타입  대상 폴더 내용으로 추론 (xcodeproj→mac, package.json→web, 그 외→general)
  번호  Projects.md 번호 대역에서 추론된 타입의 빈 번호 자동 할당
  컨펌  추론 결과를 보여주고 사용자 승인 후 진행

예시:
  /pm-new general 42 myTool
  /pm-new web 10 myWeb
  /pm-new mac 17 myApp
  /pm-new ~/_git/__all/myTool          # 형식 B
  /pm-new myTool                        # 형식 B (~/_git/__all/myTool)
```

이후 번호 대역 규칙 (`Projects.md` > `## 번호 대역 규칙`)과 `cdf` 현황 출력.

---

# Opus 4.7 실행 제약

공통 제약은 [`~/.claude/rules/opus-4-7-execution-rules.md`](../rules/opus-4-7-execution-rules.md) 참조.

요지:
* 단계별 종료 조건을 명시, 무한 루프 금지
* 외부 명령 실패 시 재시도 1회, 2회 실패 시 사용자 보고
* 파일 삭제·git push·외부 시스템 변경은 사용자 승인 후 수행
* 애매 표현 금지, 조건문으로 해석
