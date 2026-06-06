---
name: save-point-update
description: "Issue.md의 Save Point 섹션을 업데이트합니다."
title: save-point-update
date: 2026-03-27
---

# Save Point Update Skill

`Issue.md` 파일의 'Save Point' 섹션에 새로운 커밋 해시와 메시지를 추가합니다.

## 사용법

```bash
python3 .agent/skills/save-point-update/scripts/save-point.py \
  --hash "a1b2c3d" \
  --msg "Docs: Close Issue 568" \
  --file "Issue.md"
```

## 옵션

* `--hash`: (필수) 커밋 해시
* `--msg`: (선택) 설명 메시지 (기본값: "Update")
* `--file`: (선택) 대상 파일 경로 (기본값: "Issue.md")
