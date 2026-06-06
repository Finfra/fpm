---
title: fpm — 프로젝트 매니저
description: 번호 인덱스로 프로젝트 디렉토리·서버에 빠르게 접근하고, 작업을 HTML 허브로 시각화하는 셸+Claude Code 통합 시스템
date: 2026-06-06
---

# fpm

번호 인덱스로 프로젝트 디렉토리(`cdf`)와 SSH 서버(`sshf`)에 빠르게 접근하는 zsh 함수군 + 작업을 HTML 로 렌더링하는 **hub** 서버 + Claude Code SCAR(Skills/Commands/Agents/Rules) 모음.

> 듀얼 라이선스: 개인·비영리 무료 / 기업 유료. [LICENSE](LICENSE) · [COMMERCIAL.md](COMMERCIAL.md)

## 핵심 기능

* **cdf** — 프로젝트 번호로 즉시 `cd`, 복수 지정 시 iTerm2 분할
* **sshf** — `Servers.md` 의 id/name/alias 로 SSH 접속, 복수 지정 시 분할
* **hub** — 매 작업 응답을 HTML 문서로 렌더하여 브라우저에 표시, 멀티 프로젝트 대시보드·양방향 Q&A 폼 제공 (`services/hub/`)
* **SCAR** — 프로젝트 관리용 Claude Code 커맨드/스킬/에이전트/룰

## 설치

```bash
git clone https://github.com/<you>/fpm.git ~/_git/fpm
cd ~/_git/fpm
bash install.sh
source ~/.zshrc
```

자세한 설정은 [INSTALL.md](INSTALL.md) 참조.

## 사용 예

```bash
cdf            # 전체 프로젝트 목록
cdf 11         # projects/11 경로로 cd
cdf 11 12 13   # 첫 번째 cd, 나머지 iTerm2 수평 분할
cdff 14        # Finder 에서 열기
cdfc 2         # 경로를 클립보드에 복사
cdfv 0 1 2     # VS Code 로 열기 (복수)

sshf           # 서버 목록
sshf 3         # id=3 서버 접속
sshf 1 2 3     # 다중 서버 → iTerm2 분할
```

## 구조

| 경로 | 설명 |
| :--- | :--- |
| `shell/fpm-functions.zsh` | cdf·sshf 셸 함수군 (설치 페이로드) |
| `projects/` | 번호→경로 매핑 (개인 — gitignore, install 이 스캐폴드) |
| `Projects_org.md` / `Servers_org.md` | 운영 필수 파일 예제 (install 이 실파일 배치) |
| `services/hub/` | hub HTTP+SSE 서버 (Python stdlib) |
| `.claude/` | Claude Code SCAR |
| `mcp/` | MCP 서버 (hub/pm 기능 노출) |
| `keyboard-maestro/` | Keyboard Maestro 매크로 + 안내 |

## Keyboard Maestro 연동 (선택)

| 매크로 | 설명 |
| :--- | :--- |
| `iterm - input num for broadcast input` | iTerm2 다중 패널 동시 입력 → cdf 로 각 디렉토리 이동 |
| `ff_cdf` | Finder/iTerm 이동, 그 외 경로 붙여넣기 |

상세: [keyboard-maestro/README.md](keyboard-maestro/README.md)

## 라이선스

[PolyForm Noncommercial 1.0.0](LICENSE) — 개인·비영리 무료. 기업·상업적 사용은 [상용 라이선스](COMMERCIAL.md) 필요.
