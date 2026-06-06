---
name: issue-manager
description: "이슈 등록, ID 생성, 이동 및 종결 처리를 자동화합니다."
title: issue-manager
date: 2026-03-27
---

# Issue Manager Skill (이슈 관리 스킬)

`Issue.md` 파일을 파싱하여 이슈의 수명 주기를 관리합니다.

## 사용법

```bash
# 이슈 등록 (Register)
python3 .agent/skills/issue-manager/scripts/issue-manager.py register \
  --title "새로운 기능 추가" \
  --type normal \
  --file "Issue.md" \
  --purpose "목적" \
  --detail "- 상세"

# 서브 이슈 등록
python3 .agent/skills/issue-manager/scripts/issue-manager.py register \
  --title "세부 구현 사항" \
  --type normal \
  --parent-id "Issue392"

# 이슈 종결 (Close)
python3 .agent/skills/issue-manager/scripts/issue-manager.py close \
  --id "Issue387" \
  --hash "a1b2c3d" \
  --file "Issue.md"

# Save Point 업데이트
python3 .agent/skills/issue-manager/scripts/issue-manager.py savepoint \
  --hash "a1b2c3d" \
  --msg "Close Issue387" \
  --file "Issue.md"
```

## 기능

* **HWM 관리 (Self-Healing)**: 불일치 시 자동 보정
* **섹션 관리**: 타입별 섹션에 이슈 추가
* **종결 처리**: 서브 이슈는 제자리 완료, 부모 이슈는 전체 블록 이동
