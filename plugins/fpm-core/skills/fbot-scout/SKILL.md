---
title: fbot-scout
description: "발굴핀봇(fbot-scout) 판단 계층 — 직능(role) 신설·아카이브·부활. agents/skills 우선 승격, 없을 때만 웹 검색. 승인(로컬 승격=총괄 전결 · 외부 유입=사람 `[컨펌] [H:보안]`) 전 카탈로그 등재 금지"
date: 2026.08.31
---

> ⚠️ **글로벌 SCAR 변경 가드** (Issue46)
>
> 본 스킬은 모든 프로젝트가 공유. 즉흥 수정 금지.
>
> * cwd ≠ `~/.claude/` → 즉시 수정 금지, `~/.claude/Issue.md` 이슈 등록 후 별도 세션에서 처리
> * 영속 설계 SSOT: [`_doc_arch/fbot-arch.md`](../../_doc_arch/fbot-arch.md) §조직(4종)·§직능 카탈로그·§표준 시나리오 2
> * 절차: `~/.claude/rules/global-scar-change-rules.md`

# 목적

**직능(role) 축의 판단 계층.** role 등록 절차 5단계 중 LLM 판단이 필요한 ⓪①②③을 수행하고, 결정론 집행(④⑤·아카이브·부활)은 [`hooks/fbot-scout.py`](../../hooks/fbot-scout.py) 에 위임한다. 개체(bot 테이블)는 인사핀봇 소관 — **직능을 만드는 것이 발굴, 개체를 앉히는 것이 배치**다.

# 트리거

* `/fbot-scout` · "새 직능 만들어줘" · "N핀봇이 필요해" (카탈로그에 없는 role)
* **§표준 시나리오 2** — 인사핀봇이 "role 자체가 없음" 분기에서 호출
* "안 쓰는 직능 정리해줘" (아카이브) · "그 직능 다시 살려줘" (부활)

# 절차 — role 신설 (⓪→⑤ 순서 고정, 건너뛰기 금지)

| 단계 | 동작 | 완료 기준 |
| :--- | :--- | :--- |
| ⓪ 중복 검사 | `hooks/fbot-scout.py list` 로 카탈로그 조회 → 요청 임무와 **겹치는 role 이 있으면 거부**하고 그 role 을 안내 | 겹침 없음 확인 |
| ① 재료 수집 | **3-lane 하청** — 아래 §① 참조. L1·L2 병렬 → 빈손일 때만 L3 | 재료 출처 **0개 이상** 확정 (0개 = `native`) |
| ② 매뉴얼 초안 | `data/fbot/manuals/{role}.md` 작성 — [F5 형식](../../_doc_arch/fbot-arch.md): frontmatter(`completion`·`revisions`) + 본문 5절(임무·작업 절차·워크플로우 어댑터·경계/금지·완료 판정) · **900자 상한** | 파일 존재 + 형식 준수 |
| ③ 승인 | **외부 자산 유입**이면 사람 — `/mq-send --due +0d` 로 `[컨펌] [H:보안]` 등록. **로컬 승격·`native`** 면 총괄 전결(C 등급) — **나를 배분한 팀장에게** 올리고(`fbot-inbox.py defer --body '<③ 필수 기재>'` — 배분 체인 상향. 총괄은 팀장과만 대화하므로 발굴핀봇의 총괄 직통 발신은 거부된다, prj3#Issue757), 팀장이 총괄 인박스(`--kind role`)로 전달하고 총괄이 `fbot-state.py decide` 로 기록. 아래 §③ 필수 기재. **승인 전 ④ 진입 금지** | 사용자 ACK 또는 총괄 decide 기록 |
| ④⑤ 등재+아이콘 | `hooks/fbot-scout.py register --role R --shape S --base '#hex' --label L --tags 't1\|t2' --origin '<출처>'` 1회 호출 | exit 0 + JSON 의 `icon.created` |

* ⓪ Jev 후보 (shadow, prj3#Issue863_16) — 겹침 판정이 갈릴 때 `python3 ~/.claude/hooks/lib/selection.py judge --kind scout.role_dup --text "<요청 임무>" --static <role|none> --options '<JSON>'`
    - `--options` = 활성 직능 `{"<role>":"<label — 임무 한 줄>",…,"none":"겹침 없음"}`. «Jev 후보: <role> (p)» 는 **표시만** — 거부는 위 대조와 총괄이 정한다

# ① 재료 수집 — 3-lane 하청 (prj3#Issue589)

**탐색은 결과만 필요하다 → Agent 하청이 맞다.** 세션이 직접 훑으면 후보 파일 덤프가 발굴 컨텍스트를 오염시킨다(계층 스택 판정 한 줄: *"결과만 필요하면 Agent"*).

| lane | 재료원 | 하청 | 기동 |
| :--- | :--- | :--- | :--- |
| L1 | `~/.claude/agents/`·`~/.claude/skills/` | `Explore`(위치) → 후보 확정 후 `general-purpose`(전문 독해) | 항상·병렬 |
| L2 | 플러그인 — `plugins/installed_plugins.json`·`plugin-catalog-cache.json`(로컬) | `Explore` | 항상·병렬 |
| L3 | 외부 공개 자산 — WebSearch | `general-purpose` | **L1·L2 빈손일 때만** |

* 🔴 **L3 를 L1·L2 와 병렬로 띄우지 않는다** — 계약 *"웹 검색은 폴백이지 기본이 아니다"*. 병렬 기동은 "먼저 도는" 것과 비용·계약상 같다
* 🔴 **하청 프롬프트·`name` 에 `fbot-` 토큰을 쓰지 않는다. 한글 호칭만.** 훅이 프롬프트를 `fbot-…` 로 훑기 때문이다 — 부모를 언급하는 순간 하청이 부모에 결속돼 **부모가 강제 퇴근당한다**(Issue589 실측). 집행 겹은 `subagent_type` 가드([fbot-agent-bind.sh](../../hooks/fbot-agent-bind.sh))가 맡지만 규범도 함께 지킨다
* **L2 는 신설 재료원**이다 — 마켓플레이스에 맞는 자산이 있어도 종전 계약은 그것을 못 봤다. 미설치 자산 조회도 로컬 캐시로 되므로 L3 가 아니다
* **출처는 복수여도 된다** — `crosscheck` 는 agy 스킬 4종이 원본이다. 하나만 적으면 drift 판정의 `max(mtime)` 이 어긋나 나머지 변경을 놓친다
* **전부 빈손이면 `native`** — 재료 부재는 실패가 아니다. ①은 fail 지점이 아니며 fail-loud 는 ⓪(중복)·③(승인 부재) 둘뿐이다

# ③ 승인 요청 필수 기재 — 등급은 [decision-authority](../../_doc_arch/decision-authority.md) (prj3#Issue756)

L3 가 외부 agent 를 찾아 **설치까지 하려면** 그것은 외부 코드 유입이다. 종전 ③은 *"조직 계약 변경"* 단일 승인이라, 유입이 얹히면 **성격이 다른 두 승인이 한 ACK 에 묶인다** — 사용자가 role 타당성만 보고 코드를 통과시킨다.

* 로컬 승격·`native`: 재료 출처 · 매뉴얼 경로 · 제안 도형/색
* **외부 자산 추가 4종**: ⓐ 출처 URL ⓑ 원문 라이선스 ⓒ 설치 경로 ⓓ **설치 없이 진행 가능 여부**
* 발굴핀봇은 `~/.claude/agents/` 에 **직접 쓰지 않는다** — ACK 후에만 설치한다. 미설치로 가면 `origin=web:{url}` 이며 drift 검출을 포기하는 대신 유입이 없다

* 완료 후 호출자(인사핀봇·세션)에 복귀 보고 — §표준 시나리오 2 는 이 시점에 시나리오 1 의 2단계 ⓑ(`hire`)로 합류한다
* 도형은 [fbot-icon](../fbot-icon/SKILL.md) 어휘 내에서 미사용·저사용 도형 우선. 어휘 고갈 시 생성기 `SHAPES` 확장이 선행(scout=magnet 선례)

# 절차 — 아카이브·부활

* **판정 재료는 registry 다** — `hooks/fbot-state.py list` 로 그 role 의 살아 있는 개체(career != terminated·leave)가 0 인지, 마지막 배치가 언제인지 확인한다. 카탈로그만 보고 판정하지 않는다
* 집행: `hooks/fbot-scout.py archive --apply --role R` (1건씩 — 직능 일괄 아카이브 없음) / 부활: `revive --role R`
* 효과·보존·제외(상비 4종)는 계약 §직능 카탈로그 표가 정본

# 절차 — 재분류 (도구 판정, prj3#Issue636)

배분·채용이 **전건 0** 인 role 을 만나면 먼저 *"봇이 아니라 도구였던 것 아닌가"* 를 묻는다. 판정 한 줄은 계약과 같다 — **이름(기록·책임 귀속)이 필요하면 핀봇, 결과만 필요하면 Agent**.

* 집행: `hooks/fbot-scout.py set-kind --role R --kind tool` (되돌리기는 `--kind bot` — 필드 제거 1줄)
* **엔트리를 지우지 않는다** — 지우면 *"왜 봇이 아닌가"* 의 근거가 사라져 **같은 승격이 다시 올라온다**. 표시가 다음 발굴에게 하는 답이다
* 아카이브와 **다른 축**이다 — 아카이브는 HR 배치를 거부하지만 재분류는 **아무것도 거부하지 않는다**(봇 경유 조건 3종: 동시 다발·장기 실행·2회 실패 에스컬레이션)
* ⓐ 와 같은 **승인(③) 게이트**를 탄다(등급은 ③ 표 — 로컬 승격 C·외부 유입 H) — 역할 카탈로그 변경이다. 근거·신호 기대 분기는 [`fbot-agent.md`](../../_doc_arch/fbot-agent.md) §A 재분류 절이 정본

# 경계·금지 (계약 §조직 축 분리)

* `bot` 테이블 접근 금지 — 개체 조작이 필요하면 인사핀봇(`fbot-hr-gate.py`)에 넘긴다
* `catalog.yml` 직접 Edit 금지 — 훅 경유만 (카탈로그 쓰기 단일 지점)
* 웹 검색(L3)을 L1·L2 보다 먼저·병렬 실행 금지 — 실행하면 계약 위반
* 하청 프롬프트에 `fbot-` 토큰 사용 금지 — 부모 오결속(Issue589)
* 승인(③) 없이 ④ 호출 금지 — 로컬 승격은 총괄 `decide` 기록, 외부 유입은 사람 ACK. mq `[컨펌]` ACK 는 사람 전용(봇 auto-ack 금지)

# 검증

`python3 ~/.claude/hooks/test-fbot-scout.py` — 카탈로그 등재·아카이브·부활·재분류(`kind`)·HR 연동 36 케이스
