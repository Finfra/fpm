---
name: gh-sync
description: Issue.md ↔ GitHub Issues 옵트인 양방향 브리지 (status/push/pull). 로컬 Issue.md SSOT, GH 미러
date: 2026-06-28
---

# /gh-sync — Issue.md ↔ GitHub Issues 브리지

로컬 `Issue.md`(SSOT)와 GitHub Issues 를 옵트인으로 동기. 기본은 비활성(`data/gh-sync.yml` `enabled: false`) — 1인 우선 워크플로 유지. 팀·외부 기여 시만 활성화.

설계 SSOT: `_doc_work/plan/gh-issue-bridge_plan.md` · 이슈: Issue233(T6)

# 사용법

```bash
scripts/gh-sync.sh [status|push [--apply]|pull]
```

| 서브커맨드 | 동작 |
| :--------- | :--- |
| `status` | 설정(enabled/repo/conflict) + 동기 대상·매핑 현황 출력 |
| `push` | 로컬 → GH (기본 **dry-run** — 생성/수정 미리보기). `--apply` 시 개인정보 가드(`fpm-guard.sh`) 통과 후 실제 `gh issue create/edit` + 생성 번호를 Issue.md `* gh: #M` 역기록 |
| `pull` | GH → 로컬 (read-only `gh issue list` → **local-wins** 충돌만 표시, 자동 병합 없음) |

# 활성화 절차

1. `data/gh-sync.yml` 에서 `enabled: true` + `repo: "owner/name"`(비우면 git origin 추론)
2. `/gh-sync status` 로 대상 확인
3. `/gh-sync push` (dry-run) 검토 → `/gh-sync push --apply` (실제 반영)
4. `* gh: #M` 매핑 역기록분을 검토 후 직접 커밋

# 불변식

* **enabled:false → push/pull no-op** (gate). 실수 push 방지
* **push --apply 전 개인정보 가드** (`guard_before_push: true`) — `fpm-guard.sh` non-zero exit 시 중단. LLM 우회 금지
* **pull 은 working tree 미변경** — 충돌은 manual 표시만, 자동 커밋·병합 금지
* **로컬 SSOT** — 충돌 기본 `conflict: local`(Issue.md 우선)

# 필드 매핑

| Issue.md | GitHub Issue |
| :------- | :----------- |
| `## Issue{N}: {제목}` | title `[#{N}] {제목}` |
| 소속 섹션 (📕/📙/📗/🚧) | label (`label_map`) |
| 🚧 진행중 / ✅ 완료 | state open / closed |
| `* 목적:`·`* 상세:`·`* 구현 명세:` | body (마커 `<!-- fpm:issue:{N} -->` 포함) |
| `* gh: #M` | 매핑 키 (양방향 식별) |

# 제외 대상

`data/gh-sync.yml` `exclude_sections` (기본: 🌱 이슈후보·🚫 취소·⏸️ 보류·📜 참고) + 완료 208건은 미매핑 시 push 제외(active+매핑된 것만 대상).

# 구성 요소

* `scripts/gh-sync.sh` — 진입점 wrapper
* `scripts/gh-sync/parse_issuemd.py` — Issue.md → 구조화 dict
* `scripts/gh-sync/map.py` — dict ↔ GH payload 변환
* `scripts/gh-sync/engine.py` — status/push/pull 엔진 + writeback
* `data/gh-sync.yml` — 옵트인 토글·매핑 설정

# Opus 4.8 실행 제약

* `push --apply` 는 사용자 동의 후에만. 기본 dry-run 우선.
* gh API 실패 1회 재시도 → 2회 실패 시 보고·중단.
* pull 충돌 자동 병합 금지 — 사용자 수동 반영.
