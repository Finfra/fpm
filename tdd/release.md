---
title: fpm 미러 배포 재생목록
description: prj8 fpm 공개 미러의 출고 검증 선언 — 미러는 prj1 저작본을 받는 수신측이라 자체 출고 게이트를 두지 않는다 (prj3#Issue741 · 글로벌 release-test-rules)
date: 2026.09.27
gate: none
reason: 공개 미러(수신 전용) — 코드는 prj1 forward 로만 도착하고 태그·마켓 publish 도 prj1 do_deploy 가 한다. 출고 검증은 prj1 tdd/release.md R1·R2 소관
---

# 무엇을 지키나

이 저장소는 prj1(`~/_git/___pm`)이 `scripts/fpm-sync.sh` forward 로 채우는 **공개 미러**다. 사용자에게 나가는 산출물(GitHub 공개 repo·마켓 플러그인·태그)은 모두 prj1 의 출고 절차가 만든다. 그래서 이 저장소는 자체 출고 게이트를 두지 않고, 그 판단 근거를 여기 남긴다.

* 출고 검증 정본: prj1 `tdd/release.md` (저작 쪽 — 이 미러로는 반출되지 않는다)
* 이 파일은 **미러 소유**다 — prj1 `data/publishable-policy.yml` exclude `/tdd/release.md` 로 forward `--delete` 에서 보호된다(`README_ko.md`·`LICENSE` 와 같은 취급)

# 재판정 조건

아래 중 하나가 생기면 `gate` 를 다시 판정한다.

* 이 저장소에서 직접 태그·릴리스를 만드는 경로가 생긴다
* prj1 을 거치지 않고 이 저장소에 코드가 들어오는 경로(외부 PR 직접 병합 등)가 생긴다
