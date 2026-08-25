---
title: fbot-icon
description: "핀봇(fbot) 아이콘 카탈로그 관리 + 결정론 SVG 생성기 — 종류(role)별 동형 도형·개체별 색. role 등록 절차 ⑤단계와 hub 렌더가 소비"
date: 2026.08.23
---

> ⚠️ **글로벌 SCAR 변경 가드** (Issue46)
>
> 본 스킬은 모든 프로젝트가 공유. 즉흥 수정 금지.
>
> * cwd ≠ `~/.claude/` → 즉시 수정 금지, `~/.claude/Issue.md` 이슈 등록 후 별도 세션에서 처리
> * 영속 설계 SSOT: [`_doc_arch/fbot-arch.md`](../../_doc_arch/fbot-arch.md) §직능 카탈로그·§레지스트리 스키마(아이콘)
> * 절차: `~/.claude/rules/global-scar-change-rules.md`

# 목적

핀봇 아이콘의 **일관성 규약을 코드로 집행**한다 — 종류(role)별 **동형 도형**(같은 직능은 같은 모양), 개체별 **색 구분**(bot_id 에서 결정론 유도). 카탈로그가 role→도형·기본색·특징 태그를 관리하고, 생성기는 카탈로그에 없는 role 을 거부한다(fail-loud — 미등록 role 채용 불가 계약과 동형).

# 트리거

* `/fbot-icon` · "핀봇 아이콘 만들어줘" · "아이콘 카탈로그 보여줘"
* **role 등록 절차 ⑤단계** ([fbot-arch](../../_doc_arch/fbot-arch.md) §직능 카탈로그) — 신규 role 등재 시 아이콘 초안 자동 생성
* s6 hub 보드 렌더 준비 — 개체 아이콘 일괄 생성

# 자원·경로

| 자원 | 경로 |
| :--- | :--- |
| 카탈로그 (사람 편집 가능) | `~/.claude/data/fbot/icons/catalog.yml` |
| role 기본 아이콘 | `~/.claude/data/fbot/icons/{role}.svg` |
| 개체 아이콘 | `~/.claude/data/fbot/icons/{bot_id}.svg` |
| 생성기 | [`scripts/fbot-icon-gen.py`](scripts/fbot-icon-gen.py) (Python 표준 lib 만 — 무의존·무과금·결정론) |

# 사용법

```bash
G=~/.claude/skills/fbot-icon/scripts/fbot-icon-gen.py

python3 "$G" list                                  # 카탈로그 조회 (부재 시 표준 7종 자동 초기화)
python3 "$G" gen --all                             # 전 role 기본 아이콘 일괄 생성
python3 "$G" gen --role exec                       # role 기본 아이콘 1종
python3 "$G" gen --role exec --bot-id fbot-exec-narae   # 개체 아이콘 (색 = bot_id 결정론 유도)
python3 "$G" add-role qa2 --shape check --base "#3A8A8A" --label "QA2핀봇" --tags "검증"  # role 등재
```

# 규약

* **동형 원칙**: 도형은 role 이 소유한다 — 같은 role 의 모든 개체는 같은 도형, 색만 다르다
* **결정론 색**: 개체 색은 `md5(bot_id)` → HSL(hue) 유도. 같은 bot_id 는 언제나 같은 색(재현성)
* **인간 수정 보호**: 기존 `.svg` 는 `--force` 없이 덮어쓰지 않는다 — 사람이 손본 아이콘이 재생성으로 증발하는 것을 차단
* **fail-loud**: 카탈로그 미등재 role 로 `gen` 호출 시 즉시 실패(자동 등재 금지 — 등재는 `add-role` 명시 호출만)
* **부트스트랩 자동**: 카탈로그 **부재 시 표준 7종으로 자동 초기화**(제시 없이도 동작 — `init` 은 선택). 기존 카탈로그가 있으면 절대 덮지 않는다 — fail-loud 는 미등재 role 에만, 부트스트랩에는 적용하지 않음
* 도형 어휘(초기 7종): star(중역)·shield(인사)·hexagon(작업)·triangle(설계)·grid(기획)·check(QA)·magnifier(리서치) — 확장은 `add-role --shape` 로

# 완료 조건

1. `gen` 이 오류 없이 종료하고 산출 SVG 경로를 출력
2. 산출 SVG 가 `<svg` 로 시작하는 유효 파일(외부 리소스 참조 0)
3. 같은 인자 재실행 시 기존 파일 보호(`skip`) 또는 `--force` 시 동일 바이트 재생성(결정론)

# 참조

* 계약: [`_doc_arch/fbot-arch.md`](../../_doc_arch/fbot-arch.md) §직능 카탈로그·등록 절차 / §레지스트리 스키마(icon·color) / §hub 주입(badge 우선 — 커스텀 SVG 위젯은 s7)
* 선례: [`commands/generate-icon.md`](../../commands/generate-icon.md)(AppIcon — 스코프 다름: 앱 아이콘 vs 봇 아이콘)
