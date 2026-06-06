---
name: toc
description: "마크다운 파일의 목차(TOC)를 자동으로 생성하고 업데이트합니다."
title: toc
date: 2026-03-27
---

# TOC Generator Skill (목차 생성 스킬)

마크다운 파일에 대한 목차(Table of Contents)를 자동으로 생성합니다.

## 사용법

```bash
python3 .agent/skills/toc/scripts/toc.py --file [파일경로] [--apply]
```

* `--file`: 마크다운 파일 경로
* `--apply`: 지정 시 파일을 직접 수정. 생략 시 stdout 출력.

## 로직

1. `## 📋 목차` 헤더를 찾습니다.
2. 문서의 모든 `H1` (`# 제목`) 헤더를 수집합니다.
3. `1. [제목](#앵커)` 형식의 목록을 생성합니다.
