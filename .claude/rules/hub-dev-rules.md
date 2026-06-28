---
name: hub-dev-rules
description: hub 서버(services/hub/**) 코드 편집 시 같은 응답에서 /hub restart 자동 실행 강제
date: 2026-06-28
---

# 목적

hub 서버(`services/hub/server.py` 등 `services/hub/**`)는 ___pm 이 lifecycle 책임을 지는
상시 daemon(port 9876)이다. 코드를 고쳐도 **재시작 전까지는 구 코드가 계속 서빙**되어
변경이 반영되지 않는다. 과거 이 누락으로 "수정했는데 동작 그대로" 혼란이 반복됐다.

본 룰은 hook 없이 **Claude 행동 규칙**으로 자동 재시작을 강제한다.

# 적용 트리거

다음 파일을 Edit/Write/MultiEdit 로 **편집한 응답에서** 발동:

* `services/hub/server.py`
* `services/hub/spa_*.py`, `services/hub/validators.py`, `services/hub/i18n.py`
* 그 외 `services/hub/**` 의 서버 런타임 소스 (`test_*.py` 제외)

# 강제 동작 (같은 응답 내, 순서 고정)

1. **구문 검사**: `python3 -c "import ast; ast.parse(open('services/hub/server.py').read())"`
   (편집 파일 기준). 실패 시 재시작 중단·사용자 보고.
2. **재시작**: `/hub restart` 절차 실행 (`~/_git/___pm/.claude/commands/hub.md` restart 블록 —
   pidfile ∪ 포트 9876 listener 합집합 kill → 재기동 → pidfile 자가 보정).
3. **검증**: `healthz` 의 `uptime` 이 한 자릿수(새 프로세스)이고 pidfile == 실제 listener 인지 확인.
   불일치 시 사용자 보고.
4. 채팅에 "hub 재시작 완료 (pid=…, uptime=…)" 1줄 명시.

# 한계 (정직 고지)

* 본 룰은 **Claude 가 편집한 경우만** 커버한다. 사용자가 에디터에서 `services/hub/**` 를
  직접 고치면 Claude 가 관여하지 않으므로 자동 재시작이 걸리지 않는다.
  이 경우는 사용자가 직접 `/hub restart` 하거나, 필요 시 git post-commit hook 으로 보강한다.
* test 파일(`test_*.py`) 편집은 서버 런타임에 영향 없으므로 재시작 트리거 제외.

# 예외 (재시작 생략)

* 주석·문서 문자열만 바꾼 cosmetic 편집이 명백할 때 — 단, 모호하면 재시작(기본 on).
* 같은 응답에서 이미 1회 재시작했으면 추가 편집이 있어도 마지막에 1회만.

# 자가 점검 (응답 마무리 전)

* "이 응답에서 `services/hub/**` 런타임 소스를 고쳤는데 `/hub restart` 를 돌렸는가?"
  → No 면 룰 위반, 즉시 실행.

# 참조

* hub lifecycle 명령: `~/_git/___pm/.claude/commands/hub.md`
* 설계 SSOT: `~/_git/___pm/_doc_arch/hub_htm.md`
