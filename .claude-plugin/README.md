---
name: README
description: fpm SCAR Marketplace 구성 (스캐폴드)
date: 2026-06-06
---

# fpm SCAR Marketplace (스캐폴드)

fpm 의 `.claude/` Skills/Commands/Agents/Rules 를 [Claude Code Plugin Marketplace](https://docs.claude.com/en/docs/claude-code/plugins) 구조로 배포한다.

> 상태: **설계 단계 스캐폴드**. `marketplace.json` 은 최소 형태.

# 설치 (사용자)

```
/plugin marketplace add <you>/fpm
/plugin install fpm-core@fpm
```

# 배포 대상 SCAR (결정 B = 프로젝트 로컬 핵심 셀렉션)

`.claude/` 하위에서 **일반 사용자에게 유효한** SCAR 만 선별. 개인 환경 의존(ma 동기화, fApp 사설 경로 등)은 제외.

| 분류 | 포함 후보 | 제외 |
| :--- | :--- | :--- |
| Commands | `pm-*`, `cdf`, `hub`, `dashboard-server` | `cdf-fapp*`, `fapp-*-ma`, `sync-ma` |
| Skills | `pm`, `cdf`, `hub` | `sync-ma`, `cdf-fapp*` |
| Agents | (검토 후 선별) | 사설 머신 의존 |
| Rules | 범용 룰 | 개인 경로 하드코딩 룰 |

# TODO

* [TODO] 배포 SCAR 최종 셀렉션 확정
* [TODO] 하드코딩 경로(`/Users/nowage/`, `~/_git/___pm`, `nowage@host`) 일반화 또는 제외
* [TODO] plugin 디렉토리 구조 분리 (현재 source `./` 전체 → 선별 디렉토리)
* [FIXME] hub 커맨드의 cwd 임베드 → 설치 시점 동적 치환 방식 검토
