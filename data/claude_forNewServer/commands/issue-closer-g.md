---
name: issue-closer-g
description: "프로젝트 범용 이슈 종결 공통 절차 (Hash 확보 -> 완료 이동 -> Doc 커밋). issue-closer-m, issue-closer-w에서 참조"
date: 2026-03-30
---

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

> **report는 선택 사항** — 단순·중간 복잡도 이슈는 report 없이 종결 가능. `* 구현 명세` 기록만으로 충분. report가 필요한 경우: 복잡 이슈, 설계 결정 보존 필요, 사용자 명시 요청. 상세: [`~/_git/___pm/_doc_arch/nptir-triage-design.md`](~/_git/___pm/_doc_arch/nptir-triage-design.md)

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
git add Issue.md
git commit -m "Docs: Close Issue[번호] [제목] (Hash: [hash])"
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
