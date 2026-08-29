---
title: fbot-icon
description: "핀봇(fbot) 아이콘 카탈로그 관리 + 결정론 SVG 생성기 — 종류(role)별 동형 도형·개체별 색. role 등록 절차 ⑤단계와 hub 렌더가 소비"
date: 2026.08.26
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

python3 "$G" gen --role exec --bot-id fbot-exec-narae --json   # 생성 결과(경로·개체색)를 JSON 으로
python3 "$G" sync-registry                          # 레지스트리 icon/color 드리프트 조회 (dry-run)
python3 "$G" sync-registry --apply                  # 드리프트 봇에 개체 아이콘 생성 + DB 갱신
python3 "$G" sync-registry --apply --force          # 사람이 손본 아이콘까지 덮어쓴다(기본은 보호)
python3 "$G" audit                                  # 전 봇 개체색 실측 + 동색 검출 (충돌 0 이면 exit 0)
```

* `--json`: 소비처(HR 게이트)가 **색·경로를 물어보는** 경로. 색 계산·경로 규약을 복제하면
  그 순간 판정이 둘로 갈라지므로, 채용 배선은 이 출력만 읽는다
* `sync-registry`: 레지스트리 `bot.icon`/`bot.color` 를 아이콘 자산과 맞춘다. 판정은
  *"icon 이 비었거나 color 가 개체색과 다르면 대상"*. 멱등이며 `--apply` 없이는
  아무것도 쓰지 않는다. `--apply` 는 **사람이 손본 아이콘을 건너뛴다**(아래 규약 참조)
* `audit`: *"충돌 0"* 을 주장이 아니라 **세어서 보여주는** 검증구. 봇별 배정색·고유색 수·
  팔레트 여유를 출력하고, 동색이 있으면 exit≠0

# 규약

* **동형 원칙**: 도형은 role 이 소유한다 — 같은 role 의 모든 개체는 같은 도형, 색만 다르다
* **결정론 색 (Issue440 개정)**: 개체 색은 **64색 팔레트의 슬롯**이다 — `md5(bot_id)` 로 기본
  슬롯을 잡고, **먼저 등록된 봇이 이미 쓴 슬롯**은 결정론 probe(홀수 step — 64와 서로소라
  전수 순회)로 비켜간다. `bot` 레코드가 append-only 라 앞선 prefix 가 바뀌지 않으므로
  **한 번 배정된 색은 이후 채용이 늘어도 변하지 않는다**(재현성 계약 유지)
    - 팔레트: OKLCH 격자 → sRGB 게이멋 + 흰 도형 대비 ≥ 3:1(WCAG 1.4.11) 필터 → CIEDE2000
      farthest-point sampling 64색. **팔레트 내 임의 2색 최소 ΔE2000 = 9.71**
    - ⚠️ `PALETTE` **재정렬 금지** — 순서가 바뀌면 전 봇의 색이 바뀐다. 확장은 **끝에만**
    - 봇 > 64(팔레트 포화)면 중복이 다시 나온다 — `audit` 이 검출한다. 그때가 팔레트 확장 시점
* **인간 수정 보호**: 기존 `.svg` 는 `--force` 없이 덮어쓰지 않는다 — 사람이 손본 아이콘이 재생성으로 증발하는 것을 차단
    - `sync-registry --apply` 도 예외가 아니다: 기존 파일이 **현재 DB 색으로 이 생성기가 뽑았을
      바이트와 동일**할 때만 기계 생성물로 보고 재생성한다. 다르면 손댄 흔적이므로 **SVG 도 DB
      색도 건드리지 않고** 건너뛰며 경고한다(파일만 남기고 색을 바꾸면 카드 dot 과 아이콘이
      갈라져 오히려 조용한 드리프트가 된다). 덮으려면 `--force`
* **fail-loud**: 카탈로그 미등재 role 로 `gen` 호출 시 즉시 실패(자동 등재 금지 — 등재는 `add-role` 명시 호출만)
* **부트스트랩 자동**: 카탈로그 **부재 시 표준 7종으로 자동 초기화**(제시 없이도 동작 — `init` 은 선택). 기존 카탈로그가 있으면 절대 덮지 않는다 — fail-loud 는 미등재 role 에만, 부트스트랩에는 적용하지 않음
* 도형 어휘(초기 7종): star(중역)·shield(인사)·hexagon(작업)·triangle(설계)·grid(기획)·check(QA)·magnifier(리서치) — 확장은 `add-role --shape` 로
* **채용이 아이콘을 만든다** (Issue438 ③): [`hooks/fbot-hr-gate.py`](../../hooks/fbot-hr-gate.py) `hire` 가
  `gen --json` 을 호출해 개체 아이콘을 생성하고 그 **경로·개체색을 레지스트리에 기록**한다.
  이 배선이 없던 기간에 등록된 봇은 `icon` 이 NULL 이고 `color` 에 role 기본색이 들어가
  같은 role 봇이 전부 동색이었다(실측 13봇 중 12건) — 복구는 `sync-registry --apply`
* 아이콘 생성 실패는 **채용을 막지 않는다** — 아이콘은 표시 품질이지 채용 판정 요소가 아니다.
  다만 조용히 넘기지 않고 `hire` 출력의 `warning` 필드로 알린다
* ~~⚠️ **개체색 충돌 가능** 🚧~~ **✅ 해소**(Issue440, 2026-08-26) — 구 `md5 % 360` hue 는 실측
  13봇에서 이미 완전 동색 1쌍(minΔE2000 **0.00**)이었다. 팔레트+probe 전환 후 실측 13봇
  minΔE2000 **10.14**, 20봇 몬테카를로 400회 **최악 9.71 · 동색 0.0%**(구방식 40.0%).
  기각한 대안: hue+명도·채도 2축 변주(동색 5.2%) · role 대역 분할(18.0%) — 순수 해시라
  **보장**이 안 된다. 팔레트 64슬롯을 넘기면 다시 중복이 가능하다(그 전까지는 구조적 0)

# 완료 조건

1. `gen` 이 오류 없이 종료하고 산출 SVG 경로를 출력
2. 산출 SVG 가 `<svg` 로 시작하는 유효 파일(외부 리소스 참조 0)
3. 같은 인자 재실행 시 기존 파일 보호(`skip`) 또는 `--force` 시 동일 바이트 재생성(결정론)
4. `sync-registry` 를 `--apply` 후 재실행하면 *"드리프트 없음"* (멱등)
5. `audit` 이 *"충돌 0 ✅"* + exit 0 (개체색 유일성)

# 참조

* 계약: [`_doc_arch/fbot-arch.md`](../../_doc_arch/fbot-arch.md) §직능 카탈로그·등록 절차 / §레지스트리 스키마(icon·color) / §hub 주입(badge 우선 — 커스텀 SVG 위젯은 s7)
* 선례: [`commands/generate-icon.md`](../../commands/generate-icon.md)(AppIcon — 스코프 다름: 앱 아이콘 vs 봇 아이콘)
