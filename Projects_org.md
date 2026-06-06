---
title: Project Registry (Example)
description: Example project number→path mapping. install.sh가 Projects.md 부재 시 본 파일을 복사함.
date: 2026-06-06
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

## setting Script

`projects/` 폴더에 번호→경로 파일을 생성하는 스크립트. 자신의 경로로 교체할 것.

```zsh
cd ~/_git/fpm/projects && rm -f *
echo "~"                          > 0
echo "~/_git/fpm/"                > 1
echo "~/Documents/notes"          > 2
echo "~/.claude"                  > 3
echo "~/_git/myproj-web"          > 11
echo "~/_git/myproj-cli"          > 51
echo "~/work/client-a"            > 81
```

### 📋 프로젝트

| id  | 프로젝트명  | 한국어명칭 | Domain | 경로                | 설명               | 이모지 | color   |
| :-- | :---------- | :--------- | :----- | :------------------ | :----------------- | :----- | :------ |
| 0   | home        | 홈         | g      | `~`                 | 홈 디렉토리        | 😸      | #f3d2c9 |
| 1   | pm          | 피엠       | g      | `~/_git/fpm`        | fpm 저장소 자신    | 🗓️🎯     | #ffffdd |
| 2   | notes       | 노트       | g      | `~/Documents/notes` | 지식 베이스        | 💜      | #cfedd9 |
| 3   | claude      | 클로드     | g      | `~/.claude`         | Claude Code 설정   | 🧠      | #f0d5cc |
| 11  | myproj-web  | 웹앱       | w      | `~/_git/myproj-web` | 예시 웹 프로젝트   | 🌐      | #c5e8f4 |
| 51  | myproj-cli  | 씨엘아이   | g(cli) | `~/_git/myproj-cli` | 예시 CLI 도구      | ⌨️      | #d1ddeb |
| 81  | client-a    | 클라이언트A | g      | `~/work/client-a`   | 예시 외주 작업     | 💻      | #d4c9e3 |

> 한국어명칭은 macOS `say` 음성 안내용 (선택).
> `peacock.color`는 각 프로젝트 `.vscode/settings.json`에 반영 (`/peacock-sync`).

# Reference

* Domain 컬럼: `g`(global), `w`(web), `m`(macOS), `g(cli)` 등 — `Harness.md` 참조
