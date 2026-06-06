---
name: issue-closer
title: issue-closer
description: "이슈 종결 및 문서 업데이트 (Hash 확보 -> 완료 이동 -> Doc 커밋)"
date: 2026-03-28
---

> 글로벌 `/issue-closer-g` 커맨드가 있습니다. 본 로컬 커맨드는 ___pm 프로젝트 특화 절차 적용 후 필요 시 `-g` 버전에 위임합니다.
> gStack v1.0.0 연동 규칙: `~/.claude/rules/gstack-nptir-rules.md`

**역할**: 해결된 이슈의 변경사항을 커밋하고, `Issue.md`에서 '완료' 상태로 변경하며, **Commit Hash**를 기록합니다.

# 사전 준비

헬퍼 함수 로드:
```bash
source ~/.bin/issue-helper.sh
```

# 워크플로우 단계

## 0. 자동 이슈 탐지 (파라미터 없이 호출 시)

파라미터 없이 호출된 경우, 다음 순서로 대상 이슈를 자동 결정합니다:

1. **현재 대화 맥락 분석**: 이번 대화에서 작업한 내용(수정한 파일, 구현한 기능)을 파악
2. **`Issue.md` 진행중 섹션 확인**: `🚧 진행중` 섹션에 등록된 이슈가 있으면 해당 이슈를 대상으로 사용
3. **이슈 미등록 시 자동 등록**:
   - `git --no-pager diff`와 `git --no-pager status`로 변경사항 분석
   - 변경 내용을 요약하여 새 이슈를 `Issue.md`에 등록 (HWM 자동 증가)
     ```bash
     NEXT_ID=$(issue_next_id)
     issue_update_hwm ${NEXT_ID#Issue}
     ```
   - 등록 즉시 완료 처리로 진행
4. **사용자 확인**: 탐지된/생성된 이슈 번호와 내용을 사용자에게 보여주고 확인 후 진행

## 1. 기능 구현 커밋

* `git --no-pager status`와 `git --no-pager diff`로 변경사항 확인
* 변경된 파일을 스테이징하고 커밋 생성
* 커밋 메시지 형식: `Type(Scope): 이슈 설명`
* 커밋 후 해시 확보:
  ```bash
  COMMIT_HASH=$(git log -1 --format="%h")
  ```

## 2. Issue.md 업데이트

변수 준비:
```bash
ISSUE_ID="Issue1"  # 대상 이슈 ID
CLOSE_DATE=$(issue_get_current_date)
NEW_HEADER="$ISSUE_ID: [제목] (등록: YYYY-MM-DD, 해결: $CLOSE_DATE, commit: $COMMIT_HASH) ✅"
```

이슈 이동 및 업데이트:
```bash
# 현재 섹션에서 제거하고 완료 섹션에 추가
# (섹션 간 이동은 직접 편집으로 처리)

# 제목에 커밋 해시 및 완료 표시 추가
issue_append_to_entry "$ISSUE_ID" "(해결: $CLOSE_DATE, commit: $COMMIT_HASH) ✅"

# 구현 명세 섹션 추가 (수동)
```

## 3. 문서 변경 사항 저장

```bash
git add Issue.md
git commit -m "Docs: Close $ISSUE_ID (Hash: $COMMIT_HASH)"
```

## 4. 완료 알림

```bash
say 'Complished'
```



# Opus 4.7 실행 제약

공통 제약은 [`~/.claude/rules/opus-4-7-execution-rules.md`](~/.claude/rules/opus-4-7-execution-rules.md) 참조. 이 커맨드 특화 제약:

* (해당 없음 — 추후 운영 중 식별되면 추가)
