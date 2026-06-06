---
name: change-detect-rules
description: 파일/SCAR 변경 사항 탐지 요청 시 staged·unstaged·commit을 모두 커버하는 3종 병렬 실행 규칙
date: 2026-04-13
---

# 적용 트리거

사용자가 **변경 사항 탐지** 유형 요청을 했을 때 발동:

* "업데이트 확인해줘", "뭐 바뀌었어", "최근 변경"
* "SCAR 업데이트 확인", "/xxx 확인해줘"
* "커밋할 거 있나", "지금 상태 어때"
* 그 외 파일·디렉토리의 현재 변경 상태를 묻는 모든 질의

# 핵심 규칙

변경 탐지 시 반드시 **3종을 단일 메시지 내 병렬**로 실행함. 순차 실행·일부 생략 금지.

```bash
git log --oneline -<N> -- <paths>   # A. 커밋된 이력
git status --short -- <paths>       # B. staged + unstaged + untracked 요약
git diff HEAD -- <paths>            # C. staged + unstaged 실제 내용
```

* `<N>`: 관심 범위에 맞춰 10~30 권장
* `<paths>`: 사용자가 지정한 경로/글롭. 불명확하면 먼저 Glob으로 후보 수집

# 왜 이 조합인가 (Git 인덱스 메커니즘)

Git은 3개 영역을 구분하여 변경을 관리함:

| 비교 쌍                  | 의미         | status 코드 (1열·2열)       |
| :----------------------- | :----------- | :-------------------------- |
| HEAD tree ↔ index        | staged       | `M_`, `A_`, `D_` (1열)      |
| index ↔ working tree     | unstaged     | `_M`, `_D` (2열)            |
| working tree ∉ index     | untracked    | `??`                        |

**각 커맨드의 커버리지:**

| 커맨드              | commit | staged | unstaged | untracked |
| :------------------ | :----: | :----: | :------: | :-------: |
| `git log`           |   ✅   |   ❌   |    ❌    |    ❌     |
| `git status --short`|   ❌   |   ✅   |    ✅    |    ✅     |
| `git diff`          |   ❌   |   ❌   |    ✅    |    ❌     |
| `git diff --cached` |   ❌   |   ✅   |    ❌    |    ❌     |
| **`git diff HEAD`** |   ❌   |   ✅   |    ✅    |    ❌     |

→ `log` + `status --short` + `diff HEAD` 조합이 **모든 4개 영역을 커버**함.

**주의**: `git diff`만 쓰면 staged 변경을 놓침. 반드시 `git diff HEAD`를 써야 staged + unstaged 양쪽을 잡음.

# 보고 규칙

변경 사항 발견 시 **영역을 명확히 구분**해서 제시함:

* **커밋된 변경** (최근 N개): 커밋 해시 + 메시지 + 파일
* **Staged 변경**: 파일 목록 + 주요 diff
* **Unstaged 변경**: 파일 목록 + 주요 diff
* **Untracked 파일**: 목록만

# 금지 사항

* ❌ 세션 시작 시 주어지는 git status 스냅샷 맹신 ("snapshot in time, will not update" 경고 있음)
* ❌ `git log`만 실행하고 "변경 없음"으로 단정
* ❌ `git diff` 단독 사용 (staged 누락)
* ❌ 3종 순차 실행 (의존성 없음 → 병렬 필수)

# 배경

2026-04-13 사용자가 `~/.claude`에서 "/md* 등의 SCAR 업데이트 확인" 요청 시, `git log`만 실행하여 커밋된 `md-rule-apply-scope.md` 1건만 보고함. 실제로는 `rules/md-rules.md`, `skills/md-rule-apply/SKILL.md`, `commands/md-add.md` 3개 파일이 unstaged 상태였음. 사용자가 직접 지적할 때까지 누락. 이 룰은 같은 실수 재발 방지를 위함.
