---
title: "FAPP-PULL: fApp 프로젝트 일괄 commit 및 pull"
description: "fApp 프로젝트 일괄 commit 및 pull 커맨드"
date: 2026-03-29
---

인자: $ARGUMENTS

# 실행 지시

먼저 헬퍼 함수 로드:
```bash
source ~/.bin/fapp-helper.sh
```

## Step 1: 각 프로젝트에서 순차적으로 commit + pull

```bash
NUMS=($(fapp_load_projects))

for num in "${NUMS[@]}"; do
  path=$(fapp_get_path "$num")
  project_name=$(basename "$path")
  cd "$path"

  echo "=== ${project_name} ==="

  # 변경사항 commit
  if [ -n "$(git status --porcelain)" ]; then
    git add -A
    git commit -m "Update: pull 전 로컬 변경사항 커밋"
    echo "${project_name}: 커밋 완료"
  else
    echo "${project_name}: 커밋할 변경사항 없음"
  fi

  # pull
  git pull 2>&1
  echo "=== ${project_name} pull 완료 ==="
done

say "fApp pull complete"
```

# 주의사항
* fApp 목록은 `data/fapp.txt`에서 읽음 (스킬 fapp 참조)
* 순차 실행 (충돌 발생 시 해당 프로젝트에서 중단)
* 변경사항이 있으면 자동으로 commit 후 pull



# Opus 4.7 실행 제약

공통 제약은 [`~/.claude/rules/opus-4-7-execution-rules.md`](~/.claude/rules/opus-4-7-execution-rules.md) 참조. 이 커맨드 특화 제약:

* (해당 없음 — 추후 운영 중 식별되면 추가)
