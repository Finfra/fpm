---
title: Project Registry (Example)
description: Example project number→path mapping. install.sh가 Projects.md 부재 시 본 파일을 복사함.
date: 2026.07.29
---

# Info

> 본 파일은 **예제 템플릿**. 실제 운영 파일 `Projects.md`는 개인 경로를 담아 `.gitignore` 처리됨.
> `install.sh` 실행 시 `Projects.md`가 없으면 본 파일이 복사됨. 복사 후 자신의 프로젝트로 교체할 것.

## 번호 대역 규칙

번호 대역은 자유롭게 정의. 아래는 예시 분류.

| 대역   | 타입 | 설명             |
| :----- | :--- | :--------------- |
| 0~10   | 일반 | System / 공통    |
| 11~30  | 앱   | 데스크톱 앱      |
| 41~59  | 일반 | CLI / 라이브러리 |
| 60~99  | 일반 | 작업 / 외주      |
| 100~   | 일반 | 외부 / 학습      |

## id 문법

id 는 정수 또는 **접미 id**를 취한다. 접미 id 는 그 프로젝트가 앞 정수 프로젝트의 **하위 자산**임을 번호만으로 드러낸다.

```
<정수>[<소문자 1글자>[<정수>]]      정본 regex: ^[0-9]+(?:[a-z][0-9]*)?$
```

| 형태           | 예시         | 의미                                      |
| :------------- | :----------- | :---------------------------------------- |
| 정수           | `9`, `15`    | 최상위 프로젝트                           |
| 정수+문자      | `9a`, `9b`   | 해당 정수 프로젝트의 하위                 |
| 정수+문자+정수 | `9a1`, `9a2` | 하위의 하위 (문자 26개 소진 시 무한 확장) |

* **하이픈(`9-5`)은 쓸 수 없다** — `cdf` 의 범위 문법(`11-16`)에 영구 예약되어 있다.
* **점(`9.5`)도 쓰지 않는다** — 정규식 메타문자라 grep 계열에서 오탐이 나고 이스케이프 의무가 생긴다.
* 접미 id 행은 부모 행 **바로 아래**에 두어 표만 봐도 소속이 드러나게 한다.
* 상세·소비처 규약: [`_doc_arch/project-id-scheme.md`](_doc_arch/project-id-scheme.md)

### 📋 프로젝트

| id   | 프로젝트명  | 한국어명칭  | Dmn    | 경로                         | 설명              | 이모지 | color   |
| :--- | :---------- | :---------- | :----- | :--------------------------- | :---------------- | :----- | :------ |
| 0    | home        | 홈          | g      | `~`                          | 홈 디렉토리       | 😸      | #f3d2c9 |
| 1    | pm          | 피엠        | g      | `~/_git/fpm`                 | fpm 저장소 자신   | 🗓️🎯     | #ffffdd |
| 2    | notes       | 노트        | g      | `~/Documents/notes`          | 지식 베이스       | 💜      | #cfedd9 |
| 3    | claude      | 클로드      | g      | `~/.claude`                  | Claude Code 설정  | 🧠      | #f0d5cc |
| 11   | myproj-web  | 웹앱        | w      | `~/_git/myproj-web`          | 예시 웹 프로젝트  | 🌐      | #c5e8f4 |
| 51   | myproj-cli  | 씨엘아이    | g-c    | `~/_git/myproj-cli`          | 예시 CLI 도구     | ⌨️      | #d1ddeb |
| 51a  | myproj-docs | 씨엘아이 독 | g-c    | `~/_git/myproj-cli/_doc_base`| 예시 하위 자산    | ⌨️📜     | #dde5ee |
| 81   | client-a    | 클라이언트A | g      | `~/work/client-a`            | 예시 외주 작업    | 💻      | #d4c9e3 |

> Dmn == Domain (`g`:global, `w`:web, `m`:macOS, `v`:unity, `d`:dashboard, `g-c`/`m-c`:CLI 변형)
> 포함(하위 자산) 관계

```
51 ⊃ 51a
```

> 한국어명칭은 macOS `say` 음성 안내용 (선택).
> `peacock.color`는 각 프로젝트 `.vscode/settings.json`에 반영 (`/peacock-sync`).

### setting Script

SSOT는 위 "📋 프로젝트" 표. 아래 스크립트가 표의 id→경로 매핑을 `projects/` 폴더에 1줄 파일로 풀어씀. 표 변경 시 함께 갱신할 것. 운영 환경에서는 `scripts/setup-projects.sh`로 분리 권장.

```zsh
cd ~/_git/fpm/projects && rm -f *
echo "~"                             > 0
echo "~/_git/fpm/"                   > 1
echo "~/Documents/notes"             > 2
echo "~/.claude"                     > 3
echo "~/_git/myproj-web"             > 11
echo "~/_git/myproj-cli"             > 51
echo "~/_git/myproj-cli/_doc_base"   > 51a
echo "~/work/client-a"               > 81
```

# Project Map

* `Projects_map.htm` 생성기가 파싱하는 소스. 문법·완전성·토글 규칙은 [`_doc_arch/projects-map-design.md`](_doc_arch/projects-map-design.md) 참조. 경로·이모지·색은 위 표가 SSOT — 이 트리는 계층만 표현한다.
* **이 트리는 목적 지향이다.** 루트는 *하려는 일*(수익·산출 활동)이고, 자식은 *그것을 하기 위해 필요한 것*이다.

> ⚠️ **편집 시 맹점** — 손대다 보면 자꾸 구조 지향(번호 대역·플랫폼·언어별 묶음)으로 되돌아간다. 노드를 옮기기 전에 매번 **"이건 부모를 하기 위해 필요한가?"** 를 묻는다.

## Main Map
- Goal: 목표 목록
  - 제품 개발
    - "제품"
  - 외주
    - "외주"
## Sub Map
### 제품
- 11. 🌐 myproj-web
  - 51. ⌨️ myproj-cli
    - 51a. ⌨️📜 myproj-docs : 예시 하위 자산
### 외주
- 81. 💻 client-a
### Infra
- 1. 🗓️🎯 pm
  - 3. 🧠 claude
  - 2. 💜 notes

> 트리에 없는 등록 프로젝트는 생성기가 `미할당` 으로 자동 편입한다.

# Reference

* Domain 컬럼: `g`(global), `w`(web), `m`(macOS), `g-c`(CLI) 등 — `Harness.md` 참조
