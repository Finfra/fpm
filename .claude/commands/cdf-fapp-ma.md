---
title: "CDF-FAPP-MA: ma에서 fApp tmux 세션 관리"
description: "fApp 인덱스를 변환한 뒤 /cdf-ma로 위임하여 ma에서 실행"
date: 2026-03-28
---

인자: $ARGUMENTS

# 전처리: fApp 1-based 인덱스 → 실제 프로젝트 번호 변환

`/cdf-fapp`과 동일한 전처리 수행 후, `/cdf-ma`에 위임.

`data/fapp.txt`를 읽어 fApp 목록을 로드한 뒤, `$ARGUMENTS` 내 숫자 토큰을 1-based fApp 인덱스로 해석하여 실제 프로젝트 번호로 변환함.

* 인자 없으면 → 전체 fApp 프로젝트 번호를 인자로 설정
* 숫자 토큰 N (1~fApp 개수) → `fapp.txt`의 N번째 줄 값으로 치환
* 그 외 토큰 (`---`, CMD 등)은 그대로 유지

변환 후 인자 맨 앞에 `:fapp`를 붙여 `/cdf-ma`에 전달.
ex) `1 2 --- ls` → `/cdf-ma :fapp 11 12 --- ls`



# Opus 4.7 실행 제약

공통 제약은 [`~/.claude/rules/opus-4-7-execution-rules.md`](~/.claude/rules/opus-4-7-execution-rules.md) 참조. 이 커맨드 특화 제약:

* (해당 없음 — 추후 운영 중 식별되면 추가)
