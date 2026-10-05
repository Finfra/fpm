---
name: issue-closer-g
description: "프로젝트 범용 이슈 종결 공통 절차 (TDD 종결 게이트 -> Hash 확보 -> 완료 이동 -> Doc 커밋). issue-closer-m, issue-closer-w에서 참조"
date: 2026-03-30
---

> ⚠️ **글로벌 SCAR 변경 가드** (Issue46)
>
> 본 커맨드는 모든 프로젝트가 공유. 즉흥 수정 금지.
>
> * cwd ≠ `~/.claude/` → 즉시 수정 금지, `~/.claude/Issue.md` 이슈 등록 후 별도 세션에서 처리
> * 절차: `~/.claude/rules/global-scar-change-rules.md`

# /issue-closer-g - 이슈 종결 처리 (공통)

해결된 이슈를 `Issue.md`에서 완료 상태로 변경하고 커밋 해시를 기록함.
이 문서는 `/issue-closer-m`, `/issue-closer-w`의 공통 절차를 정의.

## 호출 방식

- `/issue-closer-{m|w}` — 현재 작업 컨텍스트 자동 분석 후 종결
- `/issue-closer-{m|w} Issue[번호]` — 지정 이슈 직접 종결

---

## 절차

### 0. 작업 컨텍스트 자동 감지 (파라미터 없을 때만)

1. `git status`, `git log -5 --oneline`으로 최근 작업 파악
2. `Issue.md`의 `# 🚧 진행중` 섹션에서 관련 이슈 탐색
3. 이슈 미등록 시 git diff/log 기반으로 자동 등록 후 종결
4. 감지된 이슈 번호 및 내용을 보고 후 종결 진행

### 0-1. TDD 종결 게이트 (Issue771)

종결 전에 **이 이슈가 건드린 항목의 테스트가 green 인지** 확인한다. `/issue-fix` 를 안 거친 종결도 여기서 걸린다. 적용 대상·예외 표 SSOT 는 [`tdd-playlist-rules.md`](../_doc_arch/rules-ondemand/tdd-playlist-rules.md) «TDD 기본 적용» — 종결 전에 **Read** 한다.

**① 범위 — 중요도 3등급**

| 등급                 | 판정 신호 (하나라도 해당)                                                                                                                                                                            | 종결 전 실행 범위                                                                                                                    |
| :------------------- | :--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | :----------------------------------------------------------------------------------------------------------------------------------- |
| **전체**             | 제목 `[Regression]` · 원 섹션 `📕 중요` · 공유 계층의 **계약** 변경(여러 prj 가 소비하는 hook·`sh/`·lib·cliApp REST 의 입출력·판정·스키마가 바뀜) · 출고 직전(버전 bump 동반 · main merge·태그 직전) | 해당 항목 + 재생목록 전 ✅ 행(러너 `tdd/run.sh` 등)                                                                                  |
| **해당 항목** (기본) | 위에 안 걸리는 테스트 가능한 코드 변경 — 러너 없는 repo 도 포함(최소 재현 스크립트 `python3 -c`·`bash -c` 로)                                                                                        | 이 이슈가 건드린 재생목록 행 + 이번에 추가한 재현·신규 테스트                                                                        |
| **해당 없음**        | 변경이 룰 예외 표(문서·설정·md·시각 UI·spike)에만 해당                                                                                                                                               | 룰 예외 표의 «대신 하는 검증»(건드린 재생목록 행 실행 · 링크·경로 실존 · 캡처 대조) + `* 구현 명세` 에 *"TDD 해당 없음: {사유}"* 1줄 |

* **«해당 항목» 은 최소선이다** — 중요도가 낮아도 테스트 가능한 코드 변경이면 건너뛰지 않는다. 낮은 등급이 줄이는 것은 *범위*(전 행 → 건드린 행)지 실행 여부가 아니다
* 신호 판정이 **갈리면** 위 등급을 고른다 — 과실행 비용은 분 단위, 누락 비용은 회귀다. 신호가 **없는** 것은 갈림이 아니다(아래 원 섹션 부재 등)
* 버전 bump 없는 `release/*` 브랜치 위 작업은 출고 신호가 아니다 — prj3 처럼 상시 `release/*` 에서 일하는 repo 에서 전 종결이 «전체» 로 쏠린다
* 원 섹션 확인 — 🚧 로 옮겨진 뒤라 지금 섹션으로는 모른다. 등록 커밋에서 본다:
  ```bash
  N=<번호>; C=$(git log --format=%h -S "## Issue$N:" -- Issue.md | tail -1)
  if [ -n "$C" ]; then git show "$C:Issue.md" | awk -v n="## Issue$N:" '/^# /{s=$0} index($0,n)==1{print s; exit}'
  else echo "(등록 미커밋 — 원 섹션 알 수 없음)"; fi
  ```
  - 결과가 `🚧 진행중`·`✅ 완료`(등록과 이동을 한 커밋에서 함)이거나 미커밋이면 **원 섹션 신호 없음** — 나머지 신호로 판정한다
  - 등록 뒤 승격(📙 → 📕)은 이 명령이 못 잡는다(가장 오래된 커밋만 본다). 본문·세션 맥락에 승격 흔적이 있으면 그것을 따른다
  - ⚠️ `C` 가 빈 채로 `git show ":Issue.md"` 를 부르면 **인덱스 판**을 읽어 엉뚱한 섹션이 나온다 — 가드를 빼지 않는다

**② 실행 머신 — 판정 단일 지점**

```bash
HOST=$(bash ~/.claude/sh/fapp-test-host.sh for "$(git rev-parse --show-toplevel)")   # jma | jm4 | local
```

* `local` → 지금 머신에서 실행
* `jma`·`jm4` → fApp 이다. [`/issue-closer-m`](issue-closer-m.md) «TDD 실행 머신» 절차로 돌린다 — 별칭 `/issue-closer` 로 들어와도 같다
* rc≠0(Projects.md 부재·표 파싱 실패·상태 손상) → 머신을 추측으로 고르지 않고 보고한다. 모드 전환은 [`/fapp-host`](fapp-host.md)
* **red 와 green 은 같은 머신에서 본다** — 다른 머신의 red·green 은 서로 다른 환경의 증거라 짝이 안 된다. 증거 줄에 머신을 적는 이유다

**③ 증거 — 없으면 지금 만든다**

| 이슈에 남은 것                | 할 일                                                                                                                                            |
| :---------------------------- | :----------------------------------------------------------------------------------------------------------------------------------------------- |
| `* TDD: red … → green …` 있음 | ①의 범위를 ②의 머신에서 **다시 green 확인** — 수정 뒤 다른 커밋이 끼었을 수 있다. 증거의 머신이 ②와 다르면(수정 뒤 모드 전환) red 부터 다시 본다 |
| green 만 있고 red 없음        | **사후 red** (아래 절차)                                                                                                                         |
| 테스트 자체가 없음            | 해당 항목 테스트를 지금 쓴다(`superpowers:test-driven-development`) → 커밋 → 사후 red → HEAD green                                               |

사후 red 절차 — 수정 직전 트리에 이번 테스트만 얹어 돌린다:

```bash
N=<번호>; F=$(git log --format=%h --grep="Issue$N\b" | tail -1)   # 첫 수정 커밋 (중간 커밋의 부모는 반쯤 고쳐진 트리)
T=$(mktemp -d); git worktree add --detach "$T" "$F^"
git diff --name-only "$F^" HEAD -- <테스트 경로…> | while read -r f; do mkdir -p "$T/$(dirname "$f")"; git show "HEAD:$f" > "$T/$f"; done
( cd "$T" && <테스트 실행 명령> )        # red 여야 한다
git worktree remove --force "$T"          # 얹은 파일 때문에 --force 가 필요하다
```

* red 는 **기대한 단언**으로 실패해야 한다 — import 오류·gitignore 자산 부재(worktree 엔 xcconfig·서명·캐시가 없다)로 난 실패는 red 가 아니다
* 테스트가 절대경로(`$HOME/.claude/...`)로 라이브 트리를 돌면 worktree 로는 red 를 못 본다 — 대상 루트를 env 로 받게 테스트를 고치거나, 사유를 적고 변이 red(수정 hunk 만 되돌린 사본에서 red)로 대신한다
* 사후 red 가 **안 나오면**(수정 전에도 green) 그 테스트는 이 버그를 잡지 못한다 — 테스트를 고친다. 종결 근거로 쓰지 않는다
* 리팩터(동작 불변)는 사후 red 대상이 아니다 — 수정 전·후 **모두 green** 이 계약이다. 증거 줄에 `리팩터: 전 green → 후 green` 으로 적는다

기록·차단:

* 결과는 `* 구현 명세` 에 1줄: `* TDD(종결): {등급} · {머신} — red {…} → green {…}`
* **green 을 못 보면 종결하지 않는다** — 🚧 에 두고 사유를 보고한다. 머신 불가(jma 화면 잠김·ssh 불통·잠금 점유)도 같다. 사용자가 명시로 생략을 지시했을 때만 `* TDD(종결): 생략 — 사용자 지시 ({사유})` 를 남기고 진행
* **기존 실패**는 차단 사유가 아니다 — 조건 둘: ① 이 변경과 무관(변경 파일이 그 테스트의 대상·배선에 없음. 애매하면 수정 전 트리에서도 같은 실패인지 돌려 본다) ② 추적 이슈가 있음(없으면 지금 등록). 증거 줄에 `기존 실패: <행 id> (Issue<M>)` 로 적는다. «전체» 등급이 무관한 만성 실패 하나에 영구히 막히지 않게 하는 조항이지, 실패를 덮는 조항이 아니다
* 이 단계에서 쓴 테스트는 코드다 — 4단계 문서 커밋이 아니라 `Test(Issue<N>): …` 커밋으로 따로 싣고 1단계 해시 목록에 넣는다
* 재생목록이 있으면 새 테스트 행을 올리고 상태 열을 갱신한다(룰 «절차»)

### 1. 커밋 해시 확보

```bash
# 최근 관련 커밋의 short hash 획득
COMMIT_HASH=$(git log -1 --format="%h")
```

- 다수 커밋인 경우 모두 기록: `(commit: hash1, hash2)`

### 2. 이슈 내용 업데이트

- `* 구현 명세` 섹션에 변경 로직 상세 기술
- 이슈 제목에 `(해결: YYYY-MM-DD, commit: [hash]) ✅` 추가
- 커밋 해시는 제목에만 기록 (본문 중복 금지)

> **report는 선택 사항** — 단순·중간 복잡도 이슈는 report 없이 종결 가능. `* 구현 명세` 기록만으로 충분. report가 필요한 경우: 복잡 이슈, 설계 결정 보존 필요, 사용자 명시 요청. 상세: [`~/_git/___pm/_doc_arch/nptir-triage.md`](~/_git/___pm/_doc_arch/nptir-triage.md)

### 2-1. 서브 이슈 내용 보존 (필수)

**🚫 서브 이슈 본문 축약/삭제 금지** — 서브 이슈(`Issue{N}_{M}`)를 완료 섹션으로 이동할 때, 본문(목적, 상세, 구현 명세, 검증)을 제목 한 줄로 축약하거나 삭제해서는 안 됨. 원본 내용을 그대로 유지하여 이동해야 함.

- 메인 이슈에 요약이 있더라도 서브 이슈 본문은 독립적으로 보존
- 제목에 `(해결: YYYY-MM-DD) ✅` 추가만 허용, 본문 변경 금지

### 3. 이슈 종결

프로젝트에 `issue-manager` 스크립트가 있으면 활용:
```bash
python3 .claude/skills/issue-manager/scripts/issue-manager.py close \
  --id "Issue[번호]" --hash "[commit-hash]" --file "Issue.md"
```

스크립트가 없으면 `Edit` 도구로 직접 처리:
1. `# 🚧 진행중` (또는 원래 섹션)에서 이슈 블록 제거
2. `# ✅ 완료` 섹션 **헤더 바로 아래(최상단)**에 이슈 블록 추가 — **최신 완료 이슈가 위로**, 즉 역시간순(newest first). 기존 완료 이슈들 뒤에 append 금지
3. 제목에 해결일자 + 커밋 해시 + ✅ 마크 추가

> **정렬 규칙**: `✅ 완료` 섹션은 **완료 시각 역순**으로 유지함. 가장 최근에 종결한 이슈가 항상 섹션 최상단에 위치. 이슈 번호 오름차순 정렬 금지 (이슈 번호 != 완료 순서). 사용자가 최근 작업을 빠르게 확인하기 위함.

### 3-1. 후행 이슈 진행 가능 알림 (`depends` 역참조 스캔)

종결한 이슈를 같은 prj 내 선행으로 참조하는 **후행 이슈**를 스캔하여 진행 가능 신호를 띄움 (규칙: `rules/issue-g.md # 규칙2`).

**처리**:

1. `Issue.md`에서 종결 이슈를 `depends`로 참조하는 후행 이슈 검색:
   ```bash
   # 종결 이슈가 IssueN 일 때, 같은 prj 내 depends 역참조 스캔
   grep -nE "^\* depends:.*\bIssue<N>\b" Issue.md
   ```
   (prj 접두 없는 `Issue<N>` 만 같은 prj 후행으로 판정. `prj<X>#Issue<N>` 는 다른 prj 참조이므로 제외)
2. 발견된 후행 이슈별로 잔여 선행(`depends`의 다른 항목) 완료 여부 확인
3. **알림 출력** (Edit 아님, 응답에 기록):
   - 잔여 선행이 모두 완료됨 → `선행 Issue<N> 해결 — 후행 Issue<M> 진행 가능 (depends 충족)`
   - 잔여 선행이 남음 → `선행 Issue<N> 해결 — 후행 Issue<M> 는 Issue<K> 미완료로 대기`
4. 후행 이슈가 없으면 본 단계 skip (출력 없음)

> **알림만, 자동 착수 금지**: 본 단계는 사용자에게 후행 진행 가능 사실을 *알리기만* 함. 후행 이슈 구현으로 자동 진행하지 않음 (사용자가 명시 지시 시에만 착수).

### 3-2. Issue_map.htm 자동 갱신 (존재 시, Issue253)

`Issue.md` 와 같은 디렉토리에 `Issue_map.htm` 산출물이 있으면 방금 종결한 이슈를 반영해 재생성함. 없는 프로젝트는 스킵(무비용 no-op) — `issue-map` 스킬을 안 쓰는 프로젝트에 부작용 없음.

```bash
# 생성기 경로: 플러그인 번들 → 글로벌 2단계 해석 (Issue316)
if [ -f Issue_map.htm ]; then
  for c in "${CLAUDE_PLUGIN_ROOT:-/nonexistent}/skills/fpm-issue-map/build_issue_map.py" \
           "$HOME/.claude/skills/issue-map/build_issue_map.py"; do
    [ -f "$c" ] && { python3 "$c"; break; }
  done
fi
```

* 산출물은 git 미추적(`skills/issue-map/SKILL.md` "산출물 파일명·git 정책") — 본 단계는 파일만 갱신하고 커밋 대상에 포함하지 않음
* `mmdc` 미설치 등으로 생성 실패해도 기존 `Issue_map.htm` 은 훼손되지 않음(fail-loud, 부분 산출물 미사용) — 실패 시 원인 1줄 보고 후 이슈 종결 자체는 계속 진행 (본 단계 실패가 종결을 막지 않음)

### 4. 문서 커밋

```bash
python3 ~/.claude/sh/issue-tx.py commit --issues [번호] -m "Docs: Close Issue[번호] [제목] (Hash: [hash])" [함께 올릴 문서…]
```

* `commit` 은 임시 인덱스로 내 블록(+ 지정 파일)만 커밋한다 — 공유 인덱스에 타 세션이 올려 둔 스테이징분을 싣지 않는다(Issue754). 맨 `git commit` 은 쓰지 않음
* **rc 4 는 재커밋하지 않는다** — 커밋은 이미 성립했고 공유 인덱스 동기만 실패한 것이다. 출력된 복구 명령만 실행한다(Issue766 · 정본 [issue-concurrency.md](../_doc_arch/issue-concurrency.md))

* ⚠️ **`git add Issue.md` 를 쓰지 않음** (Issue664 · `rules/issue-g.md` 규칙10) — 파일 단위 스테이징이 타 세션 미커밋분을 쓸어담음
* 블록을 완료 섹션으로 옮길 때도 손편집 대신 도구를 씀 — 블록 끝은 «다음 `## Issue` **또는** 다음 `# ` 섹션 헤더» 이고, 손으로 잡으면 섹션 헤더를 끌고 감:

```bash
python3 ~/.claude/sh/issue-tx.py move [번호] --to "✅ 완료"   # 완료 섹션 최상단(규칙0 newest first)
```

---

# Opus 4.8 실행 제약

공통 제약은 [`~/.claude/rules/opus-4-8-execution-rules.md`](../rules/opus-4-8-execution-rules.md) 참조.

요지:
* 단계별 종료 조건을 명시, 무한 루프 금지
* 외부 명령 실패 시 재시도 1회, 2회 실패 시 사용자 보고
* 파일 삭제·git push·외부 시스템 변경은 사용자 승인 후 수행
* 애매 표현 금지, 조건문으로 해석

# 레이어링 설계 참조

본 커맨드는 SCAR 3-tier 레이어링의 L1(글로벌) 레이어. 도메인 분기(L2: `/issue-closer-m`, `/issue-closer-w`)와 Skill ↔ Command 짝 구조는 [`~/_git/___pm/_doc_arch/scar-layering-design.md`](~/_git/___pm/_doc_arch/scar-layering-design.md) 참조.
