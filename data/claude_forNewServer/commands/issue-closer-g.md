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
4. 감지된 이슈 번호 및 내용을 사용자에게 보여주고 확인 요청

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

> **report는 선택 사항** — 단순·중간 복잡도 이슈는 report 없이 종결 가능. `* 구현 명세` 기록만으로 충분. report가 필요한 경우: 복잡 이슈, 설계 결정 보존 필요, 사용자 명시 요청. 상세: [`_doc_arch/nptir-triage-design.md`](../\_doc\_design/nptir-triage-design.md)

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
2. `# ✅ 완료` 섹션에 이슈 블록 추가
3. 제목에 해결일자 + 커밋 해시 + ✅ 마크 추가

### 4. 문서 커밋

```bash
git add Issue.md
git commit -m "Docs: Close Issue[번호] [제목] (Hash: [hash])"
```

---

# Opus 4.7 실행 제약

공통 제약은 [`~/.claude/rules/opus-4-7-execution-rules.md`](../rules/opus-4-7-execution-rules.md) 참조.

요지:
* 단계별 종료 조건을 명시, 무한 루프 금지
* 외부 명령 실패 시 재시도 1회, 2회 실패 시 사용자 보고
* 파일 삭제·git push·외부 시스템 변경은 사용자 승인 후 수행
* 애매 표현 금지, 조건문으로 해석
