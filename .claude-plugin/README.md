---
name: README
description: fpm SCAR Marketplace 구성
date: 2026-06-06
---

# fpm SCAR Marketplace

fpm 의 핵심 SCAR(Skills/Commands/Agents/Hooks)를 [Claude Code Plugin Marketplace](https://docs.claude.com/en/docs/claude-code/plugins) 구조로 배포한다. 핵심 가치는 **hub/dashboard 구동에 필요한 글로벌 SCAR 를 플러그인으로 번들·자동 설치**하는 것 — `/plugin install` 만으로 hub HTML 렌더·양방향 Q&A·Live Dashboard 가 동작한다.

# 설치 (사용자)

```
/plugin marketplace add Finfra/fpm
/plugin install fpm-core@fpm
```

# 구조

```
.claude-plugin/
├── marketplace.json     # 마켓플레이스 정의 (plugins[].source → ./plugins/fpm-core)
└── README.md            # 본 파일
plugins/fpm-core/
├── .claude-plugin/plugin.json   # 플러그인 매니페스트
├── commands/   (9)  hub · dashboard · dashboard-server · pm-{new,del,update,query,do} · cdf
├── skills/     (2)  pm · cdf
├── agents/          dashboard + runner/supervisor/queue-runner
├── hooks/           hooks.json + hub/dashboard hook 9종 + ask-form-template.js
├── services/hub/    server.py (hub/dashboard 백엔드)
└── CLAUDE.md        # 플러그인 사용 가이드
```

# 배포 SCAR 셀렉션 (결정 B = 로컬 핵심 큐레이션)

hub/dashboard 구동 스택 + pm/cdf 핵심만 선별. 개인 환경 의존(ma 동기화, fApp 사설 경로)은 제외.

| 분류     | 포함                                                              | 제외                                |
| :------- | :--------------------------------------------------------------- | :---------------------------------- |
| Commands | `hub`, `dashboard`, `dashboard-server`, `pm-*`, `cdf`            | `cdf-fapp*`, `fapp-*`, `*-ma`, `sync-ma` |
| Skills   | `pm`, `cdf`                                                      | `fapp`, `sync-ma`, `cdf-fapp*`      |
| Agents   | `dashboard` (+ runner 5종)                                       | `fapp-*`, `fpm-sync`                |
| Hooks    | `hub-trigger`, `ask-intercept`, `board-notify`, `hub-session-*` 등 9종 | caveman·save-prompt 등 무관분  |

# 경로 일반화

플러그인 내부 스크립트는 설치 위치(`${CLAUDE_PLUGIN_ROOT}`)를 참조하도록 일반화됨:

* hub 서버 기동: `${CLAUDE_PLUGIN_ROOT}/services/hub/server.py`
* form 템플릿 읽기: `${CLAUDE_PLUGIN_ROOT}/hooks/ask-form-template.js`
* 프로젝트 매핑: `FPM_PROJECTS_MD` 환경 변수 (없으면 무색 graceful)

# 주의 — 이중 등록

플러그인 enable 시 `hooks/hooks.json` 의 hook 이 사용자 설정에 자동 병합된다. 동일 hook 을 글로벌 `~/.claude/settings.json` 에 이미 등록한 환경(원작자)은 hook 이 2번 실행되므로 둘 중 하나만 활성할 것.

# 라이선스

PolyForm Noncommercial 1.0.0 (개인·비영리 무료) + 기업 상용 별도(`COMMERCIAL.md`). 듀얼 라이선스.
