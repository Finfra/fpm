---
title: pm
description: 프로젝트 관리 스킬 (생성·삭제·업데이트·조회). pm-new, pm-del, pm-update, pm-query 커맨드의 공통 로직.
date: 2026-04-11
---

# 개요

프로젝트 관리(생성·삭제·업데이트·조회)를 위한 공통 스킬.
각 커맨드(`pm-new`, `pm-del`, `pm-update`, `pm-query`)가 action wrapper로 이 스킬을 호출함.

> 이 스킬은 `___pm` 프로젝트 로컬 스킬. `___pm` 컨텍스트에서 실행됨.

# SSOT 참조

| 항목           | 원본 (SSOT)                               | 용도                         |
| :------------- | :---------------------------------------- | :--------------------------- |
| `Issue.md`     | `___pm/data/template/Issue.md`            | 이슈 템플릿                 |
| 번호 대역 규칙 | `___pm/Projects.md` > `## 번호 대역 규칙` | 프로젝트 번호 할당 기준     |
| 템플릿 파일    | `___pm/data/template/`                    | 프로젝트 초기화 템플릿      |

# 등록 게이트 — `pm-new` · `adopt` 공통 (Issue476)

**명부에 넣기 전에 묻는 자리다.** 단계가 하나씩 늘어나므로 **체인으로 못 박는다** — 뒤에 오는 작업이 기존 단계 본문을 헤집지 않게 하기 위함이다.

| 단계 | 무엇을 묻나 | 집행체 | 등급 | 실패 시 |
| :--- | :--- | :--- | :--- | :--- |
| **G-A** | *"이게 내 프로젝트인가"* | [`sh/fpm-registry-gate`](sh/fpm-registry-gate) (결정적) | **확인**(차단 아님) | 사용자에게 1회 확인 후 진행 여부 결정 |
| **G-B** | *"아이덴티티가 있는가"* | 아래 "L1 아이덴티티 기재" 절 | 필수 | 모르는 필드는 **비워 둔다**(추측 금지) |
| **G-C** | *"조직 인스턴스가 필요한가"* | [`sh/fpm-registry-gate`](sh/fpm-registry-gate) `gate_org` + 아래 "G-C" 절 | **선택**(차단·확인 아님) | `skip` 이면 그냥 넘어간다 — 조직 기능 미도입 환경이 정상이다 |

## 확장 지점 규약 — 새 단계를 더할 때

1. **위 표에 행을 하나 더하고, 그 단계의 절을 하나 추가한다.** 기존 단계의 절차 본문은 고치지 않는다
2. **결정적 판정은 [`sh/fpm-registry-gate`](sh/fpm-registry-gate) 에 check 함수로 더한다.** `gate_<이름>()` 을 만들고 말미 호출 목록에 한 줄 추가하면 끝이다 — 출력 형식 `GATE <이름> <ok|warn|skip> <메시지>` 와 rc 규약(0=통과 · 2=사람 확인 · 1=오류)은 그대로 쓴다
3. **사람이 판단해야 하는 것만 스킬 절차에 남긴다.** 스크립트는 "무엇이 사실인가" 를 답하고, 스킬은 "그래서 등록할까" 를 묻는다
4. 판정에 쓰는 **값**은 [`data/registry-gate.yml`](data/registry-gate.yml) 에 둔다 — 코드에 계정·이메일을 박지 않는다

## G-A — 저작자 판정

```bash
bash sh/fpm-registry-gate <대상경로>     # rc: 0=통과 · 2=사용자 확인 필요
```

* **판정 한 줄**: *"내 커밋이 0건이고 origin 이 upstream 이면 등록하지 않는다."* — **둘 다** 여야 한다
* rc=2 면 **경고 후 사용자 확인**이다. 차단하지 않는다 — 협업·인수·학습용 포크처럼 의도적 등록도 있다
* ⚠️ **경로 기준(`~/_git/_open/` 하위 제외)으로 잡지 말 것.** 그것은 관례일 뿐이라 보관소 **밖**에 둔 남의 repo 를 못 잡는다. 실제 사고(prj17)도 보관소 안에 있었지만, 규칙이 막은 게 아니라 **우연히 하나만 샜다**
* 왜 AND 인가 — 실측(2026-09-05)에서 `origin` 만 봤으면 오판할 자리가 실재했다: prj35 `fSnippetWinv-basic` 은 origin 이 `ahjoeNam`(외부)이지만 **내 커밋 20건**인 협업 프로젝트다. 반대로 커밋만 봤으면 fork 후 손대지 않은 남의 repo 를 놓친다
* 기존 명부 **전수 점검은 하지 않는다** — prj6#Issue7 이 미할당 25건을 이미 훑었고 나온 것은 prj17 하나다. 나머지는 손댈 때 이 게이트에 걸린다

## G-C — 조직 인스턴스 (prj3#Issue538)

**등록된 프로젝트에 조직(부서·자리)을 세운다.** 자리는 개체와 독립이므로 봇을 한 명도
앉히지 않아도 조직도가 선다 — 오히려 그 상태의 공석이 *"무엇이 없는가"* 를 말한다.

```bash
# 게이트 출력에서 org 행을 본다
bash sh/fpm-registry-gate <대상경로>
#   GATE org ok   … → 아래 절차 진행
#   GATE org skip … → 조직 기능 미도입. 그냥 넘어간다(등록은 정상 완료)
```

| 단계 | 무엇을 | 비고 |
| :--- | :--- | :--- |
| 1 | `~/.claude/data/fbot/org/{번호}.yml` 생성 | `extends: _template/{타입}.yml` · `prj`·`title`·`machine` 기재 |
| 2 | 해소 확인 | `python3 ~/.claude/hooks/fbot-org.py resolve --prj {번호}` |
| 3 | **PM 개체 배치는 묻는다** | 아래 |

* **타입 → 템플릿**: `general`(자리 4) · `web`(7) · `mac`(6). 타입은 "# 프로젝트 타입" 절의 판정을 그대로 쓴다
* 🔴 **PM 개체를 자동으로 앉히지 않는다.** 조직도 도구 조사(Organimi)가 경고한 함정이 *"모든 노드에 사람이 붙어야 하는 플랫폼은 공석마다 플레이스홀더 계정을 만들게 되어 headcount 가 바뀔 때마다 수작업이 늘어난다"* 였다. 자리는 선언으로 충분하고, 개체는 **일이 생길 때** 인사핀봇이 앉힌다
* 사람에게 물을 것: *"prj{N} 에 PM핀봇 개체를 지금 배치할까요? (아니오 = 공석으로 두고 배분이 생길 때 채용)"*
* 배치하기로 했으면 — `fbot-hr-gate.py hire` 로 채용 후 `fbot-org.py bind --bot-id … --seat-id ops-taskmgr-1 --prj {N} --apply`

### `pm-del` 짝 — 조직도 함께 접는다

프로젝트를 명부에서 뺄 때 조직 선언만 남으면 **감사기가 고아로 잡는다**(`check_org` ②).

* `org/{번호}.yml` 을 `org/z_done/` 으로 이동(삭제하지 않는다 — 되살릴 때 재작성 비용이 크다)
* 그 조직에 결속된 개체가 있으면 `fbot-hr-gate.py archive` 로 **휴직** 처리. 해고가 아니다 — 프로젝트가 되살아날 수 있다


# 프로젝트 타입

| 타입 | 파라미터값 | 도메인 서픽스 | Domain 레이어            |
| :--- | :--------- | :------------ | :----------------------- |
| 1    | `general`  | (없음)        | (없음) — dev-g 직접 참조 |
| 2    | `web`      | w             | `-w` (dev-w, issue-w 등) |
| 3    | `mac`      | m             | `-m` (dev-m, issue-m 등) |

# 번호 대역 규칙

> SSOT: `Projects.md` > `## 번호 대역 규칙` — 실행 시 Read하여 최신 정보 사용할 것.

# 핵심 파일 경로

```
___pm/
├── projects/              # 번호 파일 (각 파일에 경로 한 줄)
├── Projects.md            # 프로젝트 테이블 + 번호 대역 + setting Script
├── Harness.md             # SCAR 관리
├── _doc_work/
│   └── pm_history/        # 실행 이력 (실행당 파일 1개)
└── data/template/         # 프로젝트 초기화 템플릿
    ├── CLAUDE.md
    ├── gitignore
    ├── Harness.md
    ├── Issue.md
    ├── noteForHuman.md
    ├── PROMPTS.md
    ├── vscode.json
    └── zed.json   # Issue327 — enabled_editors 에 zed 포함 시만 사용
```

## 템플릿 토큰 치환 (필수) — **docs 전체가 대상** (Issue499)

> 🔒 **집행: 스크립트** — [`sh/fpm-scaffold-fill.py`](../../../sh/fpm-scaffold-fill.py) 가 치환과 Harness 채움을 **실제로 수행**한다. 템플릿 복사 직후 1회 실행하고, 출력의 `✅ 잔존 오염 0` 을 확인한다.
>
> ```bash
> sh/fpm-scaffold-fill.py <repo> --name <프로젝트명> --desc "<설명>" --type general|web|mac --prj <번호>
> sh/fpm-scaffold-fill.py <repo> --check      # 감사만 (읽기 전용)
> sh/fpm-scaffold-fill.py --check-all         # 등록 프로젝트 전수 감사
> ```
>
> ⚠️ **종전에는 `CLAUDE.md`·`PROMPTS.md`·`vscode.json`·`zed.json` 만 치환하고 `Issue.md`·`Harness.md`·`noteForHuman.md` 는 `cp` 였다.** 오염이 정확히 그 둘에서 나왔다 — 2026-09-19 전수 실측에서 미치환 `{git-hash}` **12개 prj** · prj1 값 누출 `Project Mananger` **6개 prj** · 빈 global layer **7개 prj**. **치환 대상 목록을 사람이 기억하는 구조**가 원인이므로 목록을 스크립트 상수(`DOC_FILES`)로 옮겼다.

`data/template/*` 복사 시 아래 토큰을 `Projects.md` 행 값으로 치환한다. 프로젝트 시작 컨텍스트(목적·구조)를 담아 첫 세션이 곧바로 작업 가능하게 함. 대상 파일: **`Issue.md`·`Harness.md`·`CLAUDE.md`·`PROMPTS.md`·`noteForHuman.md`**.

| 토큰            | 치환 값 (Projects.md 컬럼)      |
| :-------------- | :------------------------------ |
| `{{프로젝트명}}` | `프로젝트명` (영문 id name)     |
| `{{설명}}`       | `설명` 컬럼 전문                |
| `{{날짜}}`       | 생성일 `YYYY.MM.DD`             |
| `{{prj}}`        | 발급 번호 (`id`)                |
| `{{goal_parent}}`| `Projects.md` `# Project Map` 트리의 **부모 노드명** |
| `{{lifetime}}`   | `finite` / `perpetual` — 아래 판정표 |

* 프로젝트 성격이 파악되면 `## 목적`·`## 폴더 구조`·`## 불변식` 섹션을 실제 내용으로 보강 (generic stub 방치 금지).

## L1 아이덴티티 기재 (Issue472 — 조항 3 필수)

**아이덴티티 없이 프로젝트를 만들지 않는다.** prj6 [oracle-identity.md](~/_git/___oracle/_doc_arch/oracle-identity.md) 조항 3 이 2026-09-03 재개정되며 아이덴티티가 **필수**로, 청사진이 **선택**으로 바뀌었다. 스키마 정본은 prj6 [project-identity-scheme.md](~/_git/___oracle/_doc_arch/project-identity-scheme.md).

### 두 경로 — prj6 는 관문이 아니다

| 경로 | 언제 | L1 값의 원천 |
| :--- | :--- | :--- |
| **A — prj6 경유** | 만들기 **전에** 정해야 할 것이 있을 때 | prj6 청사진(`blueprint/2.draft/`)에서 옮겨 적는다 |
| **B — prj1 직접** | 만들면서 정할 수 있을 때 | `pm-new` 가 아는 것만 채우고, 나머지는 그 prj 가 **nPTiR 진행 중에** 채운다 |

* 판정 한 줄: *"만들기 전에 정해야 할 것이 있으면 A, 만들면서 정할 수 있으면 B"* — **둘 다 정상 경로다**
* 경로 A 로 왔으면 청사진의 값을 그대로 옮긴다. 값이 나중에 달라지면 **L1 이 옳고 청사진은 이력이므로 고치지 않는다**

### `pm-new` 가 채우는 것 / 사람이 쓰는 것

| 자동 (토큰 치환) | 사람이 쓴다 (빈칸으로 둔다) |
| :--- | :--- |
| `prj` — 발급 번호 | `identity` — 지금 무엇인가 |
| `status: active` | `not` — 무엇이 아닌가 |
| `goal_parent` — 부모를 정하고 만드므로(조항 2) | `outcome` — 기대 성과 |
| `lifetime` — 아래 판정으로 대개 자명 | `deadline` — 판정 시점 |

* 🔑 **모르는 필드는 추측해서 채우지 않는다. 비워 둔다.** `Identity.md` 에 `⚠️ 미기재` 로 노출되는 편이 낫다 — **틀린 값은 빈 값보다 나쁘다.** 한 번 박히면 아무도 다시 안 읽고, 집계표에서 채워진 것처럼 보여 **미기재 신호 자체가 죽는다**
* `lifetime` 만은 자명하면 채운다 — 비면 일몰 판정이 원리적으로 불가능해진다

| `lifetime` | 대상 |
| :--- | :--- |
| `finite` | 외주·컨설팅(prj81·82·85) · 논문(prj9a) · 강의 자료(prj65~67) — **산출물 납품으로 끝나는 것** |
| `perpetual` | 제품(fApp) · 인프라(prj1·3·5·6) · 라이브러리 — **살아 있는 동안 목표를 갈아 끼우는 것** |

* 생성 후 `sh/fpm-identity-collect` 를 실행해 [Identity.md](../../../Identity.md) 에 새 prj 가 나타나는지 확인한다

# 타입별 기본값 (Harness.md global layer)

> 🔑 **SSOT 는 [`data/harness-defaults.yml`](../../../data/harness-defaults.yml)** 이다 (Issue499). `fpm-scaffold-fill.py` 가 그 파일을 읽어 채운다 — **아래 목록은 사람이 읽는 사본**이므로 값을 늘릴 때는 yml 을 고치고 여기를 맞춘다. 종전에는 이 산문이 유일한 자리였고, 읽어 줄 코드가 없어 «자동 채움» 이라는 템플릿 문구가 4개월간 거짓이었다.

아래는 그 파일의 현재 값이다:

## general
```
Skills: dev-g, issue-g, capture-g
Commands: /issue-reg-g, /issue-fix-g, /issue-closer-g
```

## web
```
Skills: dev-g, dev-w, issue-g, issue-w, capture-g, capture-w
Commands: /issue-reg-w, /issue-fix-w, /issue-closer-w
```

## mac
```
Skills: dev-g, dev-m, issue-g, issue-m, capture-g, capture-m, deploy-m, version-manager-m
Commands: /issue-reg-m, /issue-fix-m, /issue-closer-m
```

**필수 초기화**:

* **VERSION 파일**: 신규 mac 프로젝트 생성 시 git root에 `VERSION` 파일을 생성하고 `0.0.1` 기록. `~/.claude/rules/version-manager-rules.md` SSOT 원칙 준수 — xcodeproj/Info.plist/Formula.rb는 이 파일을 참조
* **기존 fApp 보강**: `pm-update` 실행 시 VERSION 파일이 없으면 현재 `MARKETING_VERSION` 또는 `0.0.1` 값으로 생성

# .gitignore 케이스 무결성 검증 (필수)

> 적용/skip 판정·표준 블록 정책 SSOT: [`_doc_arch/gitignore-policy.md`](../../../_doc_arch/gitignore-policy.md). 요지(**Issue497 개정**) — docs(`.claude/`·`CLAUDE.md`·`Issue.md`·`_doc_arch/`·`_doc_work/`·`noteForHuman.md`)는 **명시 선언 기반**이다. `.claude/doc-base.yml` 의 `docs: track|ignore` 를 따르고 **미선언이면 «추적»**(안전측 = 유실 방지). 구 규정의 *"미추적 프로젝트면 로컬전용 ignore"* 는 **폐기** — 갓 만든 repo 는 당연히 미추적이라 신규 프로젝트가 예외 없이 버전이력·백업 0 으로 태어났다. **이미 git 추적 중이면 special reason 으로 skip** 은 유지.

`.gitignore` 템플릿(`data/template/gitignore`)에 적힌 폴더 패턴은 실제 생성 폴더명과 **대소문자 완전 일치**해야 함. macOS HFS+ 기본은 case-insensitive지만 APFS·Linux·git 인덱스는 case-sensitive — 한쪽이 다르면 `.gitignore` 매칭이 조용히 실패함.

## pm-new 실행 시

`.gitignore` 복사 후 다음 검증을 수행하고 불일치 발견 시 즉시 수정:

```sh
# 템플릿이 명시한 프로젝트 폴더 패턴 (현행 표준)
# 에디터 폴더는 data/editor.yml 의 enabled_editors 종속 (Issue327).
#   .zed/ 는 ~/.gitignore_global 에서 전역 ignore 되므로 프로젝트 .gitignore 필수 아님.
EXPECTED_DIRS=(_doc_work _doc_arch .claude .vscode)

# 신규 프로젝트의 .gitignore에서 위 패턴이 정확한 케이스로 등장하는지 확인
for dir in "${EXPECTED_DIRS[@]}"; do
    grep -qx "$dir/\?" "$PROJECT_ROOT/.gitignore" || \
        echo "WARN: $dir 패턴이 .gitignore에 없거나 케이스 불일치"
done
```

## pm-update 실행 시 (마이그레이션)

기존 프로젝트의 `.gitignore`를 스캔하여 다음 알려진 오타를 자동 정정:

| 오타 패턴      | 정정 후         | 도입 시점                                           |
| :------------- | :-------------- | :-------------------------------------------------- |
| `_doc_Design`  | `_doc_arch`   | 템플릿 초기 커밋(305e543, 2026-04-15)에 포함된 오타 — 2026-05-08 정정 |

발견 시 사용자 컨펌 후 in-place 수정. history 파일 `# 변경 내역` 섹션에 기록.

# Harness.md global layer 채움 절차

> 🔒 **집행: `sh/fpm-scaffold-fill.py`** (Issue499). 아래 1·2 는 **사람이 더 정확한 목록을 넣고 싶을 때의 선택 경로**이고, 아무것도 하지 않아도 3 이 자동으로 적용된다. *"자동 수집한다"* 고만 적고 집행자를 밝히지 않던 종전 문구가 이 이슈의 원인이었다.

1. (선택) 동일 타입의 기존 프로젝트 탐색 (ex: 맥 → `~/_git/` 하위 fApp 프로젝트들)
2. (선택) 해당 프로젝트의 `Harness.md` 또는 `.claude/` 구조에서 global SCAR 목록 수집
3. **기본**: `data/harness-defaults.yml` 의 타입별 값을 스크립트가 채운다. 이미 내용이 있으면 덮어쓰지 않는다(멱등 — `--force` 로만 덮어쓴다)

채움 규칙:
* **global Layer > Skills**: General(`-g`) + 해당 Domain(`-m` 또는 `-w`) 스킬만 기재
* **global Layer > Commands**: 해당 도메인의 커맨드만 기재
* **global Layer > Agents, Rules**: 동일 타입 프로젝트에서 수집
* **local Layer**: 빈 상태로 생성

# graphify 스캐폴드 배선 (Issue508 이월)

`graphify-out/` 이 있는 프로젝트는 [`_doc_arch/graphify-priority-setup.md`](../../../_doc_arch/graphify-priority-setup.md) 의 표준 설정을 적용한다. 그 문서는 *"본 문서를 `pm-new` 적용 단계에서 참조하도록 링크 추가 의무"* 를 적어 두었으나 **이 스킬에 `graphify` 문자열이 0건이었다** — 약속만 있고 집행이 없던 자리다(Issue508 실측).

* 핵심은 **brief 를 1회 만드는 것이 아니라 갱신 경로를 붙이는 것**이다:
    ```bash
    bash ~/.claude/hooks/graphify-post-commit-patch.sh <repo>            # 커밋마다 재압축 부착
    bash ~/.claude/hooks/graphify-brief-refresh.sh --dir <repo>          # 지금 1회 압축
    bash ~/.claude/hooks/graphify-brief-refresh.sh --dir <repo> --check  # rc=0 이어야 한다
    ```
* 미부착 상태는 커밋 한 번으로 brief 가 낡고, 그 낡은 요약이 **최우선 진입점으로 읽힌다**

# vscode.json 컬러·이모지 선택 로직

1. `~/_git/` 하위 프로젝트들의 `.vscode/settings.json`에서 사용중인 `peacock.color` + 이모지 수집
2. 기존 사용 현황과 **타입별 컬러 톤** 참고하여 선택:
    - 일반: 중성/회색 계열
    - 웹: 파랑/청록 계열
    - 맥: 난색 계열
    - ⚠️ **톤은 색상(Hue) 힌트일 뿐 «연하게» 라는 뜻이 아니다 (Issue494)**. 관례를 *저채도* 로 읽어 온 것이 포화의 실제 원인이다 — 남아 있는 공간은 **채도가 높은 쪽**에 있다(여유 색 167개의 S 중앙값 65.1% vs 등록 52색 54.5%)
3. **거리 가드 — 기존 색과 충분히 떨어질 것 (필수 · Issue494)**: 등록 전 색과의 최소 거리가 **40 이상**(하한 30). 척도는 녹색 민감도 가중 유클리드 `sqrt((2ΔR)² + (4ΔG)² + (3ΔB)²)`
    - 검증·후보 탐색은 [`sh/fpm-peacock-audit.py`](../../../sh/fpm-peacock-audit.py) 가 한다. **눈대중 금지** — 최소 거리 11.3 쌍(prj26 ↔ prj42a)이 눈으로는 안 잡혔다
    ```bash
    sh/fpm-peacock-audit.py                 # 현황 (중앙값·최소·가드 이탈)
    sh/fpm-peacock-audit.py --headroom 40   # 거리 40 이상 배정 가능 색 목록
    ```
    - ⚠️ **«거리 규칙은 성립하지 않는다» 던 종전 기재는 범위를 잘못 잡은 것이다.** 기존 자산 전체에 소급하면 118쌍이 먼저 위반이라 성립하지 않지만, **신규 배정에만** 걸면 현행 명도 가드 안에서도 거리 40 이상 색이 **95개** 남아 있다(2026-09-20 실측). 소급과 신규를 나누면 규칙이 선다
4. **명도 가드 — 파스텔만 (필수)**: 고른 색은 아래 둘을 **모두** 만족해야 함
    - HSL 명도 `L >= 80%` (권장 구간 85~92%. 등록 51건의 중앙값 L 87.1% — 2026.09.18 전수 실측)
    - 상대 휘도 `lum >= 78%` (`0.2126R + 0.7152G + 0.0722B`, 채널 0~1 정규화)
    - ⚠️ **채도(S)는 기준이 아님** — `#fee4e9`(L 94.5% · S 92.9%)처럼 충분히 밝으면 S 가 높아도 연하게 보임. S 로 거르면 정상 파스텔이 탈락함
    - 눈대중·짐작 금지. 아래 스니펫으로 **수치 검증한 뒤** 확정함
5. 이모지는 프로젝트 성격을 표현 (1~2개, 의미 있는 조합)
6. 기존 프로젝트와 중복 불가 (컬러 + 이모지 모두)

## 컬러 명도 검증 스니펫

```bash
python3 -c "import colorsys,sys
h=sys.argv[1].lstrip('#'); r,g,b=[int(h[i:i+2],16)/255 for i in (0,2,4)]
L=colorsys.rgb_to_hls(r,g,b)[1]; lum=0.2126*r+0.7152*g+0.0722*b
print(f'L={L*100:.1f}% lum={lum*100:.1f}% ->', 'OK' if L>=0.80 and lum>=0.78 else 'REJECT (너무 진함)')" '#fee4e9'
```

* 가드는 **신규 배정에만** 적용됨. 기존 등록 색의 소급 교체 의무는 없음 (2026.09.18 전수 재측정 — 이탈 **3건**: prj9 `#42b883` L 49.0%·lum 60.8% / prj65 `#fc8099` L 74.5%·lum 61.2% / prj9a `#92dab6` L 71.4%·lum 78.5%. 종전 기재는 2건으로 prj9a 가 빠져 있었다)
* 도입 계기: prj83(MultiAIAgent) 최초 배정색을 사용자가 `#fee4e9` 로 직접 교체 (2026-09-18). 종전 규칙은 색 *계열*만 정하고 명도 하한이 없어 세션마다 진한 색이 섞여 나왔음

## ✅ 재검토 결과 — 명도 가드는 **그대로 둔다** (Issue494 종결, 2026-09-20)

아래 «재검토 대상» 예고는 실측으로 닫혔다. **확장할 축은 채도 하나이고 명도는 건드릴 필요가 없다.**

| 측정 (2026-09-20 · 등록 52색) | 값 |
| :--- | ---: |
| 현행 가드(L≥80·lum≥78) 안에서 거리 **30** 이상 배정 가능 | **167색** |
| 같은 가드에서 거리 **40** 이상 | **95색** |
| 빈 팔레트로 다시 짤 때 거리 **50** 이상 | **76색** (등록 52개를 덮고도 남는다) |

* 🔑 **«고를 색이 남아 있지 않다» 는 전제가 틀렸다.** 색 공간이 아니라 **배정 습관**이 좁았다 — 관례를 저채도로 읽어 한 대역만 써 왔다
* ⇒ 명도 축을 내리는 설계(전경색 임계 재보정 동반)는 **불필요**하다. 부작용이 큰 축을 건드리지 않고 목표(중앙값 40·최소 30)를 초과 달성할 수 있다
* 남은 것은 **기존 52색의 전수 재배정**뿐이며, 산출물이 각 repo 소유라 별도로 분리했다(Issue510 — 산출물이 각 repo 소유라 승인 선행)

## ⚠️ 이 가드의 위상 — prj83 사건의 원인 대응이 **아니다** (Issue494, 2026-09-18 교정)

가드를 도입한 커밋 `04fd6a8` 의 메시지는 *"최초 배정색이 너무 진해"* 라고 적었으나, prj6 전수 실측으로 그 서술이 **추정이었음**이 확인됐다.

| 색 | L | S | lum | 가드 판정 |
| :--- | ---: | ---: | ---: | :--- |
| prj83 최초 배정값 `#c9d9e3` | 83.9% | 31.7% | 84.0% | **OK — 통과** |
| 사용자 조정값 `#fee4e9` | 94.5% | 92.9% | 91.7% | OK |

* **가드가 먼저 있었어도 같은 일이 벌어졌다** — 배정값은 기준을 넘는 파스텔이었다. 진하지 않았다
* 실제 원인은 **색 공간 포화**다. 등록 51색의 최근접 거리 중앙값이 18.0 에 불과했고, 배정값의 최근접 거리 33.0 은 오히려 중앙값보다 컸는데도 구분이 안 됐다. 대응은 [Issue494](Issue.md) 가 소유한다
* ✅ **재검토 완료 (2026-09-20)**: B안의 «확대» 는 **채도 축으로 충분**했고 `L >= 80%` 하한과 충돌하지 않는다 — 위 「재검토 결과」 절 참조. 전경색 반전 규칙(`readable_fg` 임계 0.5)도 손대지 않는다
* 진한 색을 막는 것 자체는 현행 UI 제약(상단 바 배경) 아래에서 타당하므로 **가드는 철회하지 않는다** — 바로잡는 것은 *"무엇을 막는 장치인가"* 라는 위상뿐이다

## window.title 포맷 (SSOT)

`.vscode/settings.json`의 `window.title`은 다음 단일 포맷으로 고정:

```jsonc
"window.title": "{이모지} ${rootName}${separator}${activeEditorShort}"
```

* `{이모지}`: `Projects.md` 이모지 컬럼 값 (1~2개). 템플릿 `data/template/vscode.json`의 `{{emoji}}` 토큰이 이 값으로 치환됨
* `${rootName}`·`${separator}`·`${activeEditorShort}`: VSCode 네이티브 변수 — `$` 유지, 치환 금지
* 참조 예: `~/_doc/.vscode/settings.json` (`🪨📝 ${rootName}...`)
* **주의**: 토큰은 `{{emoji}}` (mustache 스타일, `{{#color}}`와 일관). `${{emoji}}` 형태 금지 — 치환 후 `$` 가 잔존함

# 실행 이력 기록

모든 pm 커맨드(`pm-new`, `pm-del`, `pm-update`) 완료 후 `_doc_work/pm_history/` 폴더에 실행 단위 파일 생성.
`pm-query`는 조회 전용이므로 기록하지 않음.

> **상세 스키마는 `_doc_arch/Harness/plans/pm-skill-plan.md` 참조.** 본 문서는 요약만 기재.

## 파일명

```
{YYYY-MM-DD}-{id}-{action}-{번호}-{프로젝트명}.md
```

* `{id}`: 날짜별 일련번호. 매일 `1`부터 시작하며, 동일 날짜에 기존 파일이 있으면 최대 id + 1

## 필수 Frontmatter

```yaml
---
name: {파일명}
description: pm {action} - {프로젝트명} ({타입})
date: {YYYY-MM-DD}
action: {new|del|update}
project_id: {번호}
project_name: {프로젝트명}
type: {general|web|mac}
status: {success|partial|failed|cancelled}
---
```

## 본문 필수 섹션

모든 action 공통:

* `# 실행 정보` — 커맨드, 액션, 실행 시각, 사용자 컨펌, 결과
* `# 프로젝트` — 번호/이름/타입/Domain/경로
* `# 변경 내역` — action별 하위 섹션
* `# Git` — 커밋 해시 (해당되면)
* `# 비고` — 경고/예외/특이사항

## action별 하위 섹션 (변경 내역)

| action | 필수 하위 섹션                                              |
| :----- | :---------------------------------------------------------- |
| new    | 호출 형식(A/B), 추론 결과(B만), 생성된 파일, 생성된 폴더, 레지스트리 업데이트 |
| del    | 모드(backup/keep), 백업(backup만), 레지스트리 정리          |
| update | 실행 옵션, 사전 진단(Diff), 컨펌 결과, 추가됨/업데이트됨/스킵됨, 레지스트리 업데이트 |

> **금지**: 한 줄 요약만 적는 빈약한 형식. 변경 내역은 항상 항목별 리스트로 명시.

# ___pm/Harness.md 등록 절차

프로젝트 생성/변경 후, `___pm/Harness.md`에 SCAR 정보를 등록/업데이트함.

등록 내용:
```markdown
# {프로젝트명}
## main
* dev
* issue
    - /issue-reg-{suffix}
    - /issue-fix-{suffix}
    - /issue-closer-{suffix}
* capture
```

`{suffix}`는 타입별 도메인 서픽스 (일반→g, 웹→w, 맥→m).

# pm-new 자동 추론 (형식 B)

`/pm-new <대상>` (단일 인자) 호출 시 타입·번호 자동 할당:

## 타입 추론 (대상 폴더 내용)

| 우선순위 | 시그널                                              | 결과    |
| :------- | :-------------------------------------------------- | :------ |
| 1        | `*.xcodeproj`, `*.xcworkspace`, `Package.swift`     | `mac`   |
| 2        | `package.json`, `tsconfig.json`, `next.config.*`, `vite.config.*` | `web`   |
| 3        | (위 시그널 없음 또는 폴더 미존재)                   | `general` |

## 번호 자동 할당

1. `Projects.md` > `## 번호 대역 규칙`을 Read
2. 타입 → 대역 매핑 (대역표의 `타입` 컬럼은 `일반`/`맥` 2종만 구분):
    - `mac` → `맥` 대역 (현재 11~40)
    - `web` / `general` → `일반` 대역. 대역 `설명`과 프로젝트 성격을 맞춰 선택:
        + 외부/학습 웹앱 성격 → 최상단 `100~` 대역 우선
        + 내부 제작 웹·앱 → `60~79`
        + 외주 제작 → `80~99`
        + CLI → `51~59`
        + Video → `41~50`
        + 그 외 일반 → `0~10`(시스템) 등 남은 빈 번호
3. 매핑된 대역에서 비어 있는 가장 작은 번호 선택
4. 모든 대역이 가득 → 에러 + 사용자에게 대역 확장 요청

## 컨펌

추론 결과(`타입`/`번호`/`경로`)를 출력하고 **반드시 사용자 승인**. 거절 시 형식 A로 재시도 안내.

# 기존 프로젝트 흡수 (adopt) 모드

이미 개발 중인 프로젝트(자체 `.git`·`CLAUDE.md`·`Issue.md`·소스 보유)를 pm에 편입할 때 사용. `pm-new`의 무손상 변형 — 기존 파일·이력을 **절대 덮어쓰지 않고** 누락분만 보강함.

## 발동 조건

대상 폴더에 다음 중 하나라도 존재하면 adopt 모드로 전환 (template 신규 생성 금지):

* `.git/` (이미 git repo)
* `CLAUDE.md` / `Issue.md` / `README.md` (자체 문서 보유)
* 소스 디렉토리·파일 (빈 폴더가 아님)

## 멱등 처리 매트릭스

| 항목                    | 존재 시                                              | 부재 시                          |
| :---------------------- | :-------------------------------------------------- | :------------------------------- |
| `git init`              | **스킵** (기존 repo 유지)                           | 실행                             |
| `.gitignore`            | diff 후 nPTiR 누락 패턴만 추가 (덮어쓰기 금지)      | 템플릿 복사                      |
| `CLAUDE.md`             | **보존**. 글로벌 참조(`~/.claude/CLAUDE.md`) 한 줄 없으면 상단에만 추가 | 템플릿 생성 |
| `Issue.md`              | **보존** (커스텀 이슈 트래커 가능성)                | 템플릿 생성                      |
| `noteForHuman.md`       | 보존                                                | 템플릿 생성                      |
| `PROMPTS.md`            | 보존                                                | 템플릿 생성                      |
| `Harness.md`            | 보존                                                | 템플릿 + global layer 자동 채움  |
| `_doc_work/{plan,tasks,report,z_done,z_done/htm,htm}`, `_doc_arch` | 없는 서브폴더만 생성   | 전체 생성                        |
| `_doc_base`             | 없으면 생성                                         | 생성                             |
| `.claude/doc-base.yml`  | **보존** (기존 선언 존중)                           | 템플릿 복사 후 2축 값 확정 (Issue497) |
| `.vscode/settings.json` | **peacock 동기화** (아래 절차)                      | 템플릿 컬러·이모지 자동 선택     |
| `.zed/settings.json`    | `sh/fpm-projects-sync` 가 단방향 생성 (역방향 없음) | `enabled_editors` 에 zed 포함 시 |
| initial commit          | **스킵**. 변경분만 별도 커밋(사용자 컨펌)           | initial commit                   |

* nPTiR 산출물·로컬 문서가 `.gitignore` 정책상 ignore 대상이면 `.gitkeep` 불필요 — 폴더만 생성
* **`_doc_base` 무조건 생성 (사용자 지시, 2026-07-23)**: 구 규정은 원천 자료 필요 시만 생성하는 *선택 폴더*였으나, 신규·adopt 모두 항상 생성한다. gitignore 는 **명시 선언 기반** (Issue477 — 구 origin 기반 폐기): `.claude/doc-base.yml` 의 `tracking: allow|deny` 를 따르고, **미선언이면 `deny`(ignore·untrack)** 로 적용한다 — 새로 만드는 것은 닫힌 채 시작한다. 기존 repo 검사에서는 미선언이 위반이 아니다(적용 기본값 ≠ 검사 기본값). 판정 SSOT: [`_doc_arch/gitignore-policy.md`](../../../_doc_arch/gitignore-policy.md) "# `_doc_base/` 예외 — 명시 선언 규칙" · 검사: `sh/doc-base-check.sh`
* **docs 6항목은 기본값이 반대다 (Issue497)**: 같은 `.claude/doc-base.yml` 의 `docs: track|ignore` 로 선언하고 **미선언이면 «추적»** 이다. `_doc_base` 의 위험은 *유출*이라 닫은 채 시작하지만 docs 의 위험은 *유실*이라 연 채 시작한다 — 두 기본값을 같게 두면 한쪽은 반드시 틀린다. `pm-new` 는 신규 프로젝트의 `doc-base.yml` 에 **두 키를 함께** 쓰고(`tracking:`·`docs:`), `docs: ignore` 를 택한 경우에만 `data/template/gitignore` 의 주석 처리된 docs 블록을 해제한다
    - 검증: 초기 커밋 직후 `bash sh/doc-base-check.sh <repo>` 가 `docs` 축까지 ✅ 인지 확인한다. prj7(cg) 은 이 확인이 없어 **`.gitignore` 1개만 추적한 채** 태어났다(Issue497 발단)
* **`htm` 필수 사유 (Issue289 — 구 `z_htm`)**: hub 렌더(`..show`/`..ask` 등)는 `$cwd/_doc_work/htm/` 존재 시 거기 저장하고, 그때만 register 훅(`fpm-hub-doc-register`)이 hub registry 에 자동 등록한다. 부재 시 `/tmp/___pm` fallback → 등록 스킵 → `/htm-doc` 403 dead link. 따라서 신규·adopt 프로젝트는 `htm` 을 함께 생성한다 (pm 스킬은 fpm 컨텍스트 전용이라 가드 자동 충족 — 글로벌 wrapper·nptir-rules 는 `[ -d ~/_git/___pm ] || command -v fpm` 가드로 비-fpm 환경 제외). 아카이브 대상은 `z_done/htm/` 이며 legacy `z_htm/` 은 읽기만 지원. 수명주기 SSOT: `_doc_arch/htm-lifecycle-design.md`

## 에디터 폴더 조건화 (Issue327)

`.vscode/`·`.zed/` 는 **`data/editor.yml` 의 `enabled_editors` 에 포함된 에디터만** 만든다.
Zed 만 쓰는 프로젝트에 빈 `.vscode/` 를 만들지 말 것.

* 색·이모지 실제 반영은 `sh/fpm-projects-sync` 가 담당 — pm 은 템플릿 배치까지만
* Zed 는 `window.title` 대응 키가 없어 **이모지 미표시**가 정상 (능력 매트릭스 `title_emoji` 미지원)
* ⚠️ Zed 는 신뢰하지 않은 워크트리의 프로젝트 설정을 무시한다(Restricted Mode) — 파일을 써도
  사용자가 그 프로젝트를 1회 신뢰하기 전까지 색이 보이지 않음
* 설계 SSOT: `_doc_arch/editor-abstraction-design.md`

## .vscode/settings.json peacock 동기화 (필수 — 누락 빈발 지점)

adopt 시 `.vscode/settings.json` peacock 색과 `Projects.md` peacock.color가 **불일치**하면 조용히 깨짐. 다음 순서로 reconcile:

1. 대상 `.vscode/settings.json`에서 `"peacock.color"` 읽기
2. 분기:
    - **기존 색 존재 + 사용자가 신규 색 미지정** → 기존 색을 `Projects.md`에 채택 (vscode → pm). 개발자가 쓰던 색 존중
    - **사용자가 신규 색 지정** → `Projects.md` 색을 `.vscode/settings.json`에 반영 (pm → vscode). `peacock.color` + `workbench.colorCustomizations` surface 색군 + `window.title` 이모지 라인 모두 일관 갱신
    - **양쪽 부재** → 템플릿 컬러·이모지 자동 선택 (기존 `# vscode.json 컬러·이모지 선택 로직`)
3. 채택 색은 기존 프로젝트와 **중복 불가** (peacock-sync diff로 검증)
4. `window.title` 없거나 포맷 불일치면 `# window.title 포맷 (SSOT)` 기준으로 추가·정정
5. 완료 후 `/peacock-sync`(인자 없음)로 전체 일치 여부 dry-run 검증

## 종료 조건

누락분 보강 완료 + projects/{번호}·Projects.md 등록 + peacock 양방향 일치 확인 + history 기록. 기존 파일 변경 0건이면 commit 생략.

# pm-del 모드

| 모드     | 폴더 처리        | 레지스트리 정리 | 용도                                  |
| :------- | :--------------- | :-------------- | :------------------------------------ |
| `backup` | `~/_git/z_backup/`로 mv | O        | 기본. 폐기·중단 프로젝트 백업         |
| `done`   | `~/_git/z_done/`로 mv   | O        | 정상 완료된 프로젝트 보관             |
| `keep`   | 그대로 유지      | O               | 관리 체계에서만 빼고 소스는 보존      |

* 셋 다 사용자 컨펌 필수
* mv 대상 디렉토리(`z_backup/`, `z_done/`)는 없으면 자동 생성
* 동일 이름 충돌 시 `_{YYYYMMDD}_{N}` 서픽스 부여
* history 파일 frontmatter `mode` 필드:
    - `backup` → `# 변경 내역 > ## 백업` 섹션
    - `done`   → `# 변경 내역 > ## 완료 이동` 섹션
    - `keep`   → `# 변경 내역 > ## 폴더 보존` 섹션

# Action 라우팅

이 스킬은 action 파라미터에 따라 동작이 분기됨:

| action   | 동작                   | 상세 계획 문서                |
| :------- | :--------------------- | :---------------------------- |
| `new`    | 프로젝트 생성          | `pm-new-command-plan.md`      |
| `del`    | 프로젝트 제거 (백업)   | `pm-del-command-plan.md`      |
| `update` | 프로젝트 갱신          | `pm-update-command-plan.md`   |
| `query`  | 프로젝트 조회          | `pm-query-command-plan.md`    |

각 action의 상세 절차는 해당 커맨드 파일에서 정의됨.



# Opus 4.7 실행 제약

공통 제약은 [`~/.claude/rules/opus-4-7-execution-rules.md`](~/.claude/rules/opus-4-7-execution-rules.md) 참조. 이 skill 특화 제약:

* (해당 없음 — 추후 운영 중 식별되면 추가)
