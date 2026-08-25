---
name: issue-reg-g
description: "프로젝트 범용 이슈 등록 공통 절차 (HWM 확인 -> ID 발급 -> 파일 업데이트). issue-reg-m, issue-reg-w에서 참조"
date: 2026-03-30
---

# /issue-reg-g - 이슈 등록 (공통)

새로운 이슈를 `Issue.md`에 등록함. **등록 및 계획만 수행** — 사용자 확인 없이 구현으로 넘어가지 않음.
이 문서는 `/issue-reg-m`, `/issue-reg-w`의 공통 절차를 정의.

## 절차

### 0. 분석 및 triage 판정 (필수)

- 관련 파일 확인 (프로젝트 구조에 맞게)
- 프로젝트 규칙 대조 (`.claude/rules/` 등)
- 구체적 구현 계획 수립 (모호한 표현 금지)
- **복잡도 triage 판정** (규칙: `_doc_arch/rules-ondemand/nptir-rules.md # 이슈 복잡도 triage`):
    - Q1: 변경 파일 3개 이하 + 방법 자명 → 단순 (plan/task 생성 금지, 사용자 요청 시만 예외)
    - Q1 No + Q2 No (후속 영향 없음) → 중간 (plan 권장, 사용자에게 확인)
    - Q1 No + Q2 Yes (후속 영향 있음) → 복잡 (plan+task 필수)
- **`/dev` 경유 호출 시**: "사용자에게 확인" 단계 생략. 중간 판정은 **단순으로 자동 처리** (plan 미생성). 결정 사항을 응답에 한 줄 기록. (근거: `~/.claude/skills/dev-g/SKILL.md` 비대화 자동 진행 원칙)

#### 0-1. `(!)` 약식 마커 부착 판정 (Issue268)

triage(복잡도)와 **별개 축**인 스펙 완성도를 판정함. 아래 한 문장으로 결정:

> **"지금 이 이슈를 고칠 수 있는가?"**

| 답 | 등록 형식 | 후속 |
| :--- | :--- | :--- |
| 고칠 수 있다 (해결책 확정) | **정식 등록** — `* 상세`·`* 구현 명세` 필수 | 위 triage 등급대로 진행. `단순`이면 plan/task/report 만 생략 |
| 아직 못 고친다 (해결책 미정) | **`(!)` 약식 등록** — `* 목적`만 필수 | issue-map 노드로만 존재. **fix 착수 금지**, 해결책이 정해지면 승격 |

* ⚠️ **금지**: 구현 방법이 이미 확정된 사안에 `(!)` 부착. "변경 파일이 적다"·"방법이 자명하다"는 `(!)` 의 근거가 **아니며** plan/task/report 를 생략할 근거일 뿐임 (그것은 triage `단순`의 역할)
* ⚠️ **금지**: 조사·분석으로 확보한 근거를 `(!)` 형식에 맞추려고 본문에서 폐기하는 것. 근거가 있으면 정식 등록 대상임
* 마커를 붙였다면 그 이슈는 이 커맨드 종료 시점에 **착수 불가 상태**임. `/issue-fix` 로 이어가지 말 것 (`/dev` 자동 진행도 여기서 멈춤)
* 상세 규약: `rules/issue-g.md` 규칙2 예외 조항 · 설계 근거: `_doc_arch/lightweight-issue-design.md`

### 1. 프로세스 규칙 검증

- 제목/내용 한국어 작성 (전문 용어 예외)
- `* 목적`, `* 상세` 섹션 포함
- 상세 서브 불렛 4칸 들여쓰기
- 플랫폼별 이슈 카테고리 분류 (각 `-m`/`-w` 커맨드 참조)

### 2. HWM 확인

#### 2-0. 서브 이슈 판정 (필수 선행)

신규 이슈 등록 전, 다음 조건 중 하나라도 해당하면 **서브 이슈**로 판정:

* 사용자 요청에 "서브이슈", "sub-issue" 단어가 명시됨
* 사용자가 `Issue{N}_{M}` 형식의 ID를 직접 지시함 (ex: "Issue27_3 추가해줘")
* 신규 이슈 내용이 기존 부모 이슈의 세부 항목으로 명확히 종속됨 (사용자 확인 필요)
    - **`/dev` 경유 호출 시**: 사용자 확인 생략. **일반 이슈로 자동 처리** (HWM +1). 결정 사항을 응답에 한 줄 기록. (근거: `~/.claude/skills/dev-g/SKILL.md` 비대화 자동 진행 원칙)

**판정 결과별 분기**:

| 판정 | ID 발급 | HWM 처리 |
| :--- | :------ | :------- |
| **서브 이슈** | 부모 ID 재사용 → `Issue{부모N}_{M}` (M = 기존 서브 이슈 max + 1) | **불변** (HWM 증가 금지) |
| **일반 이슈** | HWM + 1 → `Issue{N+1}` | HWM = N+1 로 갱신 |

**근거**: `~/.claude/skills/issue-g/SKILL.md` "HWM은 부모 이슈 번호만 증가 (서브 이슈는 HWM에 미반영)" 규칙. 위반 시 메인 이슈 번호 gap 누적 → 추적 혼란.

#### 2-1. HWM 확인 (일반 이슈인 경우만)

프로젝트에 `issue-hwm` 스크립트가 있으면 활용:
```bash
python3 .claude/skills/issue-hwm/scripts/issue-hwm.py sync --file "Issue.md"
```

스크립트가 없으면 `Issue.md`를 직접 읽어 현재 가장 높은 **메인 이슈 번호**(`^## Issue(\d+):` 패턴)를 파악하고 +1로 새 ID 결정. 서브 이슈 패턴(`^### Issue\d+_\d+:`)은 HWM 계산 대상에서 제외.

### 3. 이슈 등록

> **`issue-g` 스킬 참조** → 이슈 등록 형식 및 HWM 업데이트

프로젝트에 `issue-manager` 스크립트가 있으면 활용:
```bash
python3 .claude/skills/issue-manager/scripts/issue-manager.py register \
  --title "[제목]" \
  --type normal \
  --purpose "목적 한 줄" \
  --detail "- 상세 1\n- 상세 2" \
  --file "Issue.md"
```

스크립트가 없으면 `Edit` 도구로 직접 `Issue.md` 편집.

### 3-1. plan/task 파일 연결 (있을 경우)

`_doc_work/plan/` 에서(plan·task 동거) 이 이슈와 관련된 파일을 Glob으로 탐색:

```
_doc_work/plan/{주제}_plan.md
_doc_work/plan/{주제}_task.md
```

파일 발견 시:
1. Issue.md 해당 이슈 항목에 `* plan:`, `* task:` 경로 필드 추가 (`* 목적:` 바로 아래)
2. 발견된 plan/task 파일의 frontmatter `issue: TBD` → `issue: Issue[번호]`로 업데이트

### 3-2. 선행/후행 이슈 연결 (`depends` 자동 추가)

신규 이슈가 같은 prj 내 **선행 이슈에 종속**되면 `* depends:` 필드를 자동 추가함 (규칙: `rules/issue-g.md # 규칙2`).

**판정 조건** (하나라도 해당 시 선행 이슈 존재로 판정):

* 사용자 요청에 "Issue<M> 끝나고", "Issue<M> 다음", "선행 Issue<M>", "Issue<M> 완료 후" 등 순서 표현이 명시됨
* 신규 이슈 구현이 기존 미완료 이슈의 산출물(코드·API·파일)을 전제로 함

**처리**:

1. 선행 이슈 번호(들)를 식별
2. 신규(후행) 이슈 항목 `* 목적:` 바로 아래(plan/task 필드와 동일 위치)에 `* depends: Issue<M>[, Issue<M2>]` 추가
3. 같은 prj/다른 prj 혼합 시 한 줄에 쉼표 나열 (prj 접두 유무로 구분)
4. **`* trigger:` 전이 조건 동반 기입** (Issue248) — 아래 3-3 참조

> **`/dev` 경유 호출 시**: 순서 표현이 명시적일 때만 자동 추가. 모호하면 `depends` 미추가 + 응답에 한 줄 기록. (근거: `~/.claude/skills/dev-g/SKILL.md` 비대화 자동 진행 원칙)

### 3-3. 전이 조건 (`trigger`) 기입 — `depends` 와 한 쌍 (Issue248)

`* depends:` 를 추가했다면 **무엇이 충족돼야 이 이슈가 열리는지**를 `* trigger:` 로 같은 위치에 적음 (규칙: `rules/issue-g.md # 규칙8`).

`depends` 는 *연결이 있다*만 말하고, `trigger` 는 *그 연결이 풀리는 조건*을 말함. 후자가 비면 차단 해제 판정을 매번 이슈 본문에서 재추론해야 하고, 선행이 끝났는데 후행이 방치되는 사고가 남.

**처리**:

1. 사용자 요청·선행 이슈의 완료 조건에서 전이 조건을 **추론**. ex) 선행이 "API 신설"이면 → `선행 API 엔드포인트 배포 완료`
2. 추론 근거가 약하면 사용자에게 1회 질의 (대화형 호출 시)
3. `* depends:` 바로 아래에 `* trigger: {조건}` 추가

**작성 기준**: 제3자가 **관측·판정 가능**한 사실로 씀.

| 판정 | 예시 |
| :--- | :--- |
| ✅ 좋음 | `* trigger: prj1#Issue286 ✅ 완료 + commit hash 기록` |
| ✅ 좋음 | `* trigger: PR #1982 merge 완료` |
| ❌ 나쁨 | `* trigger: 준비되면` (판정 주체·시점 불명) |

> **`/dev` 경유 호출 시**: 근거가 명시적일 때만 기입. 모호하면 미기입 + 응답에 한 줄 기록 (3-2 `depends` 원칙과 동일).

### 4. 이슈 내용 보강

`Issue.md` 열람 후 `* 목적:` 및 `* 상세:` 항목을 Edit 도구로 구체적으로 작성. 빈칸 금지.

### 5. Git 저장

```bash
git add Issue.md
git commit -m "Docs: Issue[번호] 등록 — [제목]"
```

### 5-1. Issue_map.htm 자동 갱신 (존재 시, Issue264)

`Issue.md` 와 같은 디렉토리에 `Issue_map.htm` 산출물이 있으면 방금 등록한 이슈를 반영해 재생성함. 없는 프로젝트는 스킵(무비용 no-op) — `issue-map` 스킬을 안 쓰는 프로젝트에 부작용 없음.

```bash
# 생성기 경로: 플러그인 번들 → 글로벌 2단계 해석 (Issue316)
if [ -f Issue_map.htm ]; then
  for c in "${CLAUDE_PLUGIN_ROOT:-/nonexistent}/skills/fpm-issue-map/build_issue_map.py" \
           "$HOME/.claude/skills/issue-map/build_issue_map.py"; do
    [ -f "$c" ] && { python3 "$c"; break; }
  done
fi
```

* 등록은 **새 노드·새 화살표가 추가되는** 이벤트라 종결보다 지도 변화가 큼. 갱신이 없으면 방금 만든 의존 체인이 지도에 안 보여 "타 prj 의존 미지원" 같은 오인을 유발함 (Issue264 배경)
* 산출물은 git 미추적(`skills/issue-map/SKILL.md` "산출물 파일명·git 정책") — 본 단계는 파일만 갱신하고 위 5단계 커밋 대상에 포함하지 않음
* 생성 실패해도 기존 `Issue_map.htm` 은 훼손되지 않음(fail-loud, 부분 산출물 미사용) — 실패 시 원인 1줄 보고 후 등록 자체는 완료로 처리 (본 단계 실패가 등록을 막지 않음)

> 🚨 **등록 완료 후 즉시 작업 종료** — `/issue-fix-{m|w}`로 자동 진행 금지

---

# Opus 4.8 실행 제약

공통 제약은 [`~/.claude/rules/opus-4-8-execution-rules.md`](../rules/opus-4-8-execution-rules.md) 참조.

요지:
* 단계별 종료 조건을 명시, 무한 루프 금지
* 외부 명령 실패 시 재시도 1회, 2회 실패 시 사용자 보고
* 파일 삭제·git push·외부 시스템 변경은 사용자 승인 후 수행
* 애매 표현 금지, 조건문으로 해석

# 레이어링 설계 참조

본 커맨드는 SCAR 3-tier 레이어링의 L1(글로벌) 레이어. 도메인 분기(L2: `/issue-reg-m`, `/issue-reg-w`)와 Skill ↔ Command 짝 구조는 [`~/_git/___pm/_doc_arch/scar-layering-design.md`](~/_git/___pm/_doc_arch/scar-layering-design.md) 참조.
