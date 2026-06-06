---
name: peacock-sync
description: "Projects.md peacock.color ↔ 각 프로젝트 .vscode/settings.json 동기화"
date: 2026-04-14
---

# 개요

`Projects.md`의 `peacock.color` 컬럼과 각 프로젝트 `.vscode/settings.json`의 `"peacock.color"` 값을 동기화한다.

인자: `$ARGUMENTS`

* `vscode` — .vscode/settings.json → Projects.md 방향으로 업데이트
* `pm`     — Projects.md → .vscode/settings.json 방향으로 업데이트
* (없음)   — 양쪽 값을 비교하여 차이점만 출력 (dry-run)

# 절차

## 1. 프로젝트 목록 수집

`~/_git/___pm/Projects.md` 테이블에서 `id`, `프로젝트명`, `경로`, `peacock.color` 추출.
`~` → `/Users/nowage` 치환하여 절대경로로 변환.

## 2. 각 프로젝트 .vscode/settings.json에서 peacock.color 읽기

```python
import re, os

HOME = os.path.expanduser('~')

def read_vscode_color(proj_path):
    f = f'{proj_path}/.vscode/settings.json'
    if not os.path.exists(f):
        return None
    raw = open(f).read()
    m = re.search(r'"peacock\.color"\s*:\s*"([^"]+)"', raw)
    return m.group(1) if m else None
```

## 3. 방향별 처리

### 인자 없음 (diff)

각 프로젝트별로 두 값을 비교하여 표 형태로 출력:
* `✓` 일치
* `←` vscode 값이 다름 (vscode → pm 방향으로 바꿔야 함)
* `→` pm 값이 다름 (pm → vscode 방향으로 바꿔야 함)
* `-` .vscode/settings.json 없음

### 인자 `vscode`

`.vscode/settings.json`에 값이 있는 프로젝트만 `Projects.md` 업데이트:

```python
pm = re.sub(
    r'(\|\s*' + str(pid) + r'\s*\|(?:[^|]*\|){5})\s*#[0-9a-fA-F]{6}\s*(\|)',
    lambda mx: mx.group(1) + ' ' + vscode_color + '      ' + mx.group(2),
    pm
)
```

업데이트 후 `python3 ~/.bin/update-iterm-bg` 실행.

### 인자 `pm`

`Projects.md`에 값이 있는 프로젝트의 `.vscode/settings.json` 업데이트:

```python
new_raw = re.sub(
    r'("peacock\.color"\s*:\s*")([^"]+)(")',
    lambda mx: mx.group(1) + pm_color + mx.group(3),
    raw
)
```

`.vscode/settings.json`이 없는 프로젝트는 건너뜀.
업데이트 후 `python3 ~/.bin/update-iterm-bg` 실행.

## 4. 결과 출력

변경된 항목 수 및 목록을 출력한다.



# Opus 4.7 실행 제약

공통 제약은 [`~/.claude/rules/opus-4-7-execution-rules.md`](~/.claude/rules/opus-4-7-execution-rules.md) 참조. 이 커맨드 특화 제약:

* (해당 없음 — 추후 운영 중 식별되면 추가)
