---
name: Issue_public
description: "fpm 공개용 이슈 근거 요약 — Issue.md 에서 제목·목적·구현 명세만 추출한 파생본"
generator: scripts/fpm-issue-digest.sh
source_sha: 8068d0a42ee3e19e34e143886d7b108dae2cf6dd41974fa1f56c6113ca578eeb
---

# 안내

본 문서는 자동 생성 파생본이다. 원본 이슈 트래커(`Issue.md`)는 개인정보가 포함되어 공개하지
않으며, 여기에는 **코드 변경의 근거를 이해하는 데 필요한 필드만** 추출되어 있다.

* 포함: 이슈 제목 · `목적` · `구현 명세` · `depends`
* 제외: 상세 · Walkthrough · 진행 결과 · 커밋 해시 · plan/task 경로

소스 코드 주석의 `(Issue{N})` 참조는 아래 항목에서 찾을 수 있다. 직접 편집하지 말 것 —
`scripts/fpm-issue-digest.sh` 가 덮어쓴다.

# 이슈 근거

## Issue362: plugins/fpm-core 번들 표류 16건 — forward 가 막혀 있다
* 목적: `fpm-sync` forward 가 *"plugins/fpm-core 가 라이브와 표류"* 로 **중단**된 상태다(로그 2026-08-09 15:13). 배포판이 라이브보다 뒤처져 있어, 번들을 쓰는 소비자는 구버전 동작을 만난다. 특히 `skills/fpm-pm-do` 는 안전 지시 주입·원본 지시 보존 개정이 미반영이라 **위임 세션의 안전 문구가 끊긴다**.
* depends: 없음
* 구현 명세:
    - 절차는 [`_doc_arch/fpm-sync-deploy.md`](_doc_arch/fpm-sync-deploy.md) — `scripts/fpm-bundle-sync.sh` 실행 → 테스트 → 커밋 → forward 재시도
    - ⚠️ 불변식 준수: **forward/deploy 는 ___pm 콘텐츠 읽기 전용**(버전 파일 3종 bump 제외) · `rsync --delete` 금지 · push 명시 동의
    - 표류 16건이 **한 덩어리로 오래 쌓인 것**이라, sync 전 각 항목이 의도된 라이브 변경인지 확인할 것. 특히 `services/hub` 7파일은 fpm-pm-do 와 무관한 별개 축이다
    - 검증: `--check` 재실행 0건 · `fpm-sync` forward 정상 진행 · `skills/fpm-pm-do/SKILL.md` diff 0

## Issue359: 좀비 킬러가 활성 세션까지 전멸시킴 — origin·상태 필터 부재 ✅
* 목적: 🧟 좀비 킬러 버튼 1회 클릭으로 **live 세션 41개 전부(35 표시 → 0)** 가 사라졌다. Zed 뿐 아니라 작업 중이던 터미널 세션 14개까지 SIGTERM 됐다. 파괴적 동작인데 되돌릴 수 없다.
* depends: Issue360 (그 리퍼가 자동으로 도는 것이 이 버튼의 대체재)
* 구현 명세:
    - **방침 (2026-08-07 사용자 결정)**: 버튼을 없애지 않는다. 좀비 킬러는 **내부적으로 계속 써야 하는 기능**이고, 전에 정상 동작하던 것이 Zed 유입으로 깨진 것이므로 **원인을 잡아 안정화**한다. 기능 자체를 제거하는 것은 앞으로 같은 문제를 용인하는 것과 같다. 버튼 제거는 안정화가 끝나 내부 사용에 지장이 없어진 다음의 일이다
    - **근본 원인 (확정)**: "title 없음" 판정이 `live_label` **단독**이었다. 그러나 카드 제목은 [server.py:4927](services/hub/server.py#L4927) 에서 **3단 폴백**으로 정해진다 — ① `ai-title`(JSONL `aiTitle`, **VSCode 확장 전용**) ② `live_label` ③ `_session_first_prompt`(첫 프롬프트 발췌, Issue328 이 Zed·터미널용으로 추가). Zed·터미널 세션은 ①이 영구히 없고 ②도 안 실려 와 **③으로만 제목을 얻는다** → 화면에 제목이 멀쩡히 떠 있어도 좀비 킬러에겐 **구조적으로 항상 빈 세션**이었다. VSCode 세션도 SessionStart 훅이 label 을 생략하면(Issue121 주석이 명시) 동일하게 걸렸다
    - 즉 Issue127(ai-title)·Issue328(first-prompt)로 **제목 소스가 늘어날 때 좀비 판정만 갱신되지 않아 낡은 것**이다. "잘 되던 기능"이 맞다
    - **조치**: 제목 3단 판정을 [`_live_session_title`](services/hub/server.py#L1397) 로 추출해 **카드 렌더와 좀비 판정이 같은 함수를 공유**하게 했다(판정 단일 지점). 제목 소스가 또 늘어도 한 곳만 고치면 양쪽이 따라온다
    - **관측 보강**: 응답·로그에 `kept_count`·`kept[]`(보존 내역) 추가. `kept=0` 이면 판정이 또 낡았다는 신호라 조용한 전멸 대신 즉시 드러난다
    - **검증(2026-08-07)**: 수정 후 dry 판정 — 작업 중 세션 **7개 전부 보존**(vscode 5·zed 1·terminal 1), 타깃은 제목 없는 zed 세션 **1개**뿐. 원래 의도(프롬프트 전 빈 좀비만 제거)가 정확히 복원됨
    - 잔여 — **origin 오분류(별건)**: VSCode 확장 세션이 `capabilities.editor` 미전송으로 `terminal` 로 잡히는 사례가 있다. 이번 판정 수정과 무관하게 동작하나(제목 기준이라 origin 무관) 카드 표기·클릭 동작이 어긋나므로 별도 확인 필요

## Issue360: Zed 스레드 닫힘 직접 신호(`thread-archived`)로 orphan 판정 교체 ✅
* 목적: Issue331 리퍼가 **기동 이후 단 1건도 잡지 못했다**(로그에 `started` 만 있고 `reaped` 0건). 유일한 판정 `bridge-dead` 가 원리적으로 발동할 수 없는 구조라, Zed live 세션·claude 프로세스가 무한 누적된다. 판정 축을 **Zed 가 직접 기록한 스레드 닫힘 사실**로 교체한다.
* depends: Issue331 (그 판정 축 교체), Issue357 (idle-ttl 철회로 비어 버린 자리를 메움)
* 구현 명세:
    - `_zed_orphan_reason` 에 판정 축 **`thread-archived`** 추가. `bridge-dead` 는 창 종료 케이스를 잡으므로 **유지**
    - 판정: sid 가 `sidebar_threads` 의 `agent_id='claude-acp' AND archived=1` 집합에 속하면 orphan. `archived=0` 은 **절대 건드리지 않는다** — 유휴 스레드 오살(Issue357)의 재발 경로를 구조적으로 차단
    - **왜 안전한가**: idle-ttl 은 "열림/닫힘"을 heartbeat 로 *추측*했으나, `archived` 는 Zed 가 닫는 순간 *기록한 사실*이다. 사용자가 아카이브된 스레드를 다시 열면 `session/load` 로 새 프로세스가 뜨므로 복구 불가 상태(Issue357 의 `Session not found`)가 되지 않는다
    - db 접근: 읽기 전용 URI(`mode=ro`) + `busy_timeout`, 릴리즈 채널 glob(`db/*/db.sqlite`), mtime 캐시로 재조회 억제. db 부재·조회 실패·테이블 없음은 **fail-soft(판정 skip)** — 기존 동작 유지
    - 검증: 리퍼 1주기 후 `reaped>0` 로그 + `archived=0` 세션이 하나도 죽지 않음을 실측

## Issue361: hub 카드 🗺️ 아이콘 오표시 — depends 완료 판정에 `✅ 완료` 섹션 축 누락 ✅
* 목적: 실제로는 관계도가 비어 있는 프로젝트 카드에 이슈맵 아이콘이 떠, 열면 "의존 관계도 생략" 안내만 나온다. 사용자 지적(prj1·prj58 오표시, prj9a 정상) 기준으로 판정을 맵 빌더와 일치시킨다
* 구현 명세:
    - `_ISSUE_DONE_SECTIONS = {"✅ 완료"}` 를 `_ISSUE_EXCLUDED_SECTIONS` 옆으로 올려 **단일 상수**로 통합. 하단 중복 정의 제거(주석도 낡아 있었음)
    - `_issue_md_has_depends()` 에 `section_done` 추적 추가 → `current_done = section_done or 헤더 끝 ✅`
    - 검증(실제 함수 import): prj58 `True → False` · prj9a `True` 유지(미완료 depends 5건) · prj1 `True` 유지
    - 원인 B 는 코드 버그가 아니므로 prj1 맵 재생성으로 해소(생략 문구 0 · 간선 14). 판정↔맵 stale 의 **구조적** 불일치는 별건 → 아래 이슈후보 등록

## Issue356: hub 라이브 표시 계층 실배선 — Early Flush 완성 ✅
* 목적: Issue353 이 만든 라이브 스트리밍(메일박스 pull·라이브 셸)이 **실사용 경로에 연결되지 않아** 사용자에게는 여전히 "턴 끝에 완성본이 한 번에 뜨는" 것으로 보인다. 턴 시작 시점에 셸을 열어 첫 페인트를 앞당기는 C안 본래 UX 를 실제로 성립시킨다
* depends: Issue353 (완료 — 라이브 셸·메일박스·게이트가 전제)
* 구현 명세:
    - 실행은 서브 2건 — 356_1(prj1 서버·설정) → **prj3#Issue341**(훅 선오픈, depends: prj1#Issue356_1). Issue353 과 같은 단방향 순서 고정(서버가 먼저, 훅이 그것을 부른다)
    - 검증: `..show` 1회에 **턴 시작 3초 이내** 라이브 뷰가 뜨고 블록이 도착하는 대로 갱신 + 턴 종료 시 게이트 판정대로 아카이브 생성

## Issue356_1: prj1 — render_display 정리 + 라이브 진입점 제공 ✅
* 목적: 훅이 라이브 뷰를 열 수 있도록 서버·설정 쪽 계약을 먼저 확정한다. 값 이름 충돌을 없애고, 값마다 실제로 다른 동작을 하게 만든다
* depends: Issue356
* 구현 명세:
    - `hub_setting.yml` 키 주석 갱신 + `md_shell.render_live_shell` cfg·`_handle_session_live` 반영
    - 회귀 테스트: 구 값 하위호환 매핑 · 값별 분기 · 진입점 응답(200/401)

## Issue357: Issue353 M2 잔여 정리 — 죽은 코드·미배선·체크리스트 정정 ✅
* 목적: Issue353 종결 검증에서 드러난 잔여를 닫는다. 기능은 동작하나 **완료 선언의 근거가 부정확**한 상태를 바로잡는 것이 핵심
* depends: 없음 (Issue356 과 독립 — 파일은 겹치나 작업 성격이 달라 선행 처리)
* 구현 명세:
    - 죽은 코드 제거 시 **미완결 꼬리 프리뷰를 살릴지 먼저 판정** — 블록 단위 도착 특성상 관측되지 않았다는 실측이 있으므로 기본은 폐기(취소 사유로 기록)
    - `gc()` 는 mail poll 경로 또는 기존 세션 GC 주기에 배선(둘 다 이미 존재 — 신규 타이머 금지)
    - 검증: 죽은 심볼 grep 0건 · `gc()` 호출 경로 1개 이상 · task/arch/report 3문서 진술 일치

## Issue355: hub 서버 다운 시 렌더 자동 강등 — 서버 유무로 사용자 경험이 갈리지 않게 ✅
* 목적: `render_target: hub`(md-first) 에서 hub 서버가 죽어 있으면 렌더 결과를 볼 수단이 사라진다. 사용자는 **의도적으로 서버를 죽여 놓고 작업하는 경우가 많다** — 서버 작동 유무가 사용자 경험을 바꾸면 안 된다. Issue353 이 남긴 마지막 잔여(D안 "잔여는 폴백 규약뿐")를 닫는다.
* depends: 없음 (Issue353 완료 후속)
* 구현 명세:
    - 본 이슈는 **규약 확정 + arch 반영** 담당. hook 구현은 prj3#Issue340
    - [stable_performance_arch.md](_doc_arch/stable_performance_arch.md) D안 "fail-soft 강등 체인" 을 구현 완료 상태로 갱신하고 판정 방식·고지 문구를 명문화
    - 강등 규약: 서버 미생존 → `render_target`·`render_target_cfg` 를 `local-open` 으로, `render_tab_mode: hub-internal` 은 중립화, `browser_open: off` 는 helper 승격(죽은 URL 만 남기면 아무것도 안 보임 — `/tmp` fallback 블록과 동형)
    - 판정: bash 내장 `/dev/tcp` 포트 리슨 확인 (프로세스 기동 0회 — `UserPromptSubmit` 은 차단성 hook, 예산 50ms). 대상 host 는 `bind_host`(미설정·`0.0.0.0` 이면 `127.0.0.1`) — `advertise_host` 아님
    - 검증: 서버 stop 상태에서 렌더 1회 → `.htm` 생성 + `file://` open + 고지 1줄 / 서버 start 상태에서 렌더 1회 → 기존 md 경로 무변경

## Issue353: hub 렌더 안정성·성능 개선 — md-first + 메일박스 pull 스트리밍 ✅
* 목적: `..show`/자동 hub 렌더가 `..text` 대비 수 배 느리고(LLM 수기 HTML 생성) 렌더·등록·표시 각층에서 반복 파손되는 구조를 근본 개선 — 콘텐츠(md)/표장(서버 셸) 분리 + transcript tail 메일박스 pull 스트리밍
* 구현 명세:
    - 서브 이슈 완료 순서 고정: 353_1 → 353_2 → 353_3 (depends 체인). 각 서브 완료 시 task 체크박스 `- [v]` + 커밋 해시 동기

## Issue353_1: M0 스모크 검증 + M1 A안 md-first ✅
* 목적: 설계 전제 실측 고정(transcript append 타이밍·Zed ACP 동일성) + `/md-doc` 셸 렌더로 LLM HTML 수기 생성 폐지 — hub 응답 시간 `..text` 대비 1.3배 이내
* 구현 명세:
    - `services/hub/server.py` 에 `GET /md-doc?path=` 추가 — `_inject_before_body_end`·`_normalize_mermaid_runtime` 재사용, disk-scan 파일명 패턴 md 반영(Issue311 재발 방지)

## Issue353_2: M2 E+C 스트리밍 표시 계층 — 메일박스 pull ✅
* 목적: transcript tail → 세션별 메일박스(seq·epoch) → `?since=` 커서 pull → 완결 블록 append 점진 렌더. 첫 페인트(셸+활동 신호) 턴 시작 3초 이내
* depends: Issue353_1
* 구현 명세:
    - 종합 판정 ①~⑤ (task M2 말미 — 원격 tailscale 경로 B 실동작 포함) 전부 통과 후 종결

## Issue353_3: M3 G안 서버 게이트 + 아카이브 자동화 ✅
* 목적: `auto_render: always|short|page|doc` 임계를 서버 규칙 엔진이 메일박스 실측으로 기계 판정(LLM 판정 폐기) + Stop 시점 최종본 md 아카이브 자동 생성
* depends: Issue353_2
* 구현 명세:
    - 판정 시나리오 3종(단답 0건/표 포함 생성/오버라이드) 확인 후 종결

## Issue352: hub registry 자동 만료 + hub OFF 배지 ✅
* 목적: `htm-registry.json` 에 만료 정책이 없어 hub 문서 목록이 무한 누적됐다. `..hub off` 를 해도 목록은 그대로라 "꺼도 옛날 게 남아 있다"로 관측됐다. 만료를 서버가 갖게 하고, off 상태는 가리는 대신 배지로 정직하게 표시한다.
* 구현 명세:
    - `_prune_htm_registry()`: mtime 최신순 상위 keep 보존 → 나머지는 age 이내만 보존 → 그 외 제거. 정책값은 [`htm-lifecycle-design.md`](_doc_arch/htm-lifecycle-design.md) SSOT 승계(**keep 20 / age 7일**), `hub_setting.yml` 키(`htm_registry_keep`·`htm_registry_age_days`)로 조정 가능(둘 다 `0`=비활성)
    - ⚠️ **tombstone(`HTM_CLEARED`) 미기록** — `clear` 는 사용자의 명시적 삭제 의도라 부활을 차단하지만 자동 만료는 의도가 아니다. 남기면 무한 성장 + 영구 복구 불가. 파일 보존이라 `/hub-rescan` 으로 복구 가능
    - 호출은 `_collect_htm_docs()` 단일 지점 + **TTL 60초 가드**(hub 5초 polling)
    - hub 헤더 배지 `⏸ N/M hub OFF`(전역이면 `system`). 소스는 `_hub_off_stats()` — collect 의 `projects` 는 dash-registry 기반이라 dashboard 보유 프로젝트만 담겨(실측 0건) 배지 소스로 쓸 수 없었음
    - `_htm_state_entries()` TTL 2초 캐시로 `.hub-state` 스캔 1회화, 토글 직후 무효화

## Issue351: noteForHuman.md `ToProcess` 섹션 전 프로젝트 표준화 ✅
* 목적: 정리 전 초기 메모를 아무 데나 흘리지 않고 한곳에 쌓기 위한 `# ToProcess` 섹션을 **모든 프로젝트의 `noteForHuman.md` 공통 규약**으로 도입한다. prj1·prj3 은 선반영했고, 목차 표가 없는 나머지 40개가 남았다.
* 구현 명세:
    - 목차 표가 **없는** 프로젝트는 목차 표를 새로 만들지 않는다. `# 개요` 블록 직후·첫 정식 H1 섹션 **앞**에 `# ToProcess` 섹션만 삽입한다:
        ```markdown
        # ToProcess

## Issue350: 공개 미러에 사설 프로젝트명 잔존 — exclude 파일은 sanitize 가 닿지 않는다
* 목적: 공개 미러 `fpm` 의 `Harness.md`·`Harness_ko.md` 에 사설 프로젝트명 **`<private-project-5>`** 가 섹션 헤더(`# <private-project-5>`)로 남아 있다. 이 문자열은 `publishable-policy.yml` 의 sanitize 대상이라 *"공개되면 안 된다"* 고 이미 판정된 값이다. 개별 문자열보다 **왜 sanitize 가 못 잡았는가** 가 본질이다.
* 구현 명세:
    - 1단계 **전수 실측** — 미러 전체에 sanitize `from` 리터럴이 몇 건 남았는지 센다. `Harness.md` 외에 같은 사연을 가진 exclude 고아가 더 있는지 먼저 본다
    - 2단계 **HEAD 정화** — 미러 쪽 `Harness.md`·`Harness_ko.md` 에서 해당 절을 제거·치환. ⚠️ 이 파일들은 미러 소유(forward 가 안 덮음)라 **fpm 에서 직접 고쳐야** 한다
    - 3단계 **재발 차단(핵심)** — exclude 파일이라도 **미러에 실재하면** 검사 대상에 넣는다. ex) forward 말미에 *미러 전체* 대상 secret-scan 을 1회 돌려 sanitize `from` 리터럴이 발견되면 fail-loud. 현행 `fpm-secret-scan.sh` 는 스냅샷(TMP)만 본다
    - 4단계 이력 제거 여부는 **사용자 판단** — force push 는 협업자 clone 을 깨뜨린다. 노출값이 프로젝트 코드명 1개뿐이라 비용 대비 실익을 함께 검토할 것

## Issue348: 배포본 test_issue_map.py 가 자기 검증을 건너뜀 — 경로 기준 어긋남
* 목적: `plugins/fpm-core/services/hub/test_issue_map.py` 가 **배포본 생성기를 찾지 못해** 그 절반의 검증을 통째로 건너뛴다. 이 테스트의 존재 이유가 *"원본·배포본 양쪽을 같은 픽스처로 돌린다"*(파일 주석 250~251행)인데, 정작 배포본 쪽이 비어 있다.
* depends: Issue343
* 구현 명세:
    - 경로를 파일 위치에 의존하지 않게 잡을 것. ex) `parents[2]` 대신 repo 루트를 `git rev-parse --show-toplevel` 또는 `_BIM_PATHS` 를 **두 후보 모두 절대경로 탐색**으로 바꾸기
    - ⚠️ 이 파일은 **2원 사본**이다 — 원본(`services/hub/`)과 배포본(`plugins/fpm-core/services/hub/`) 을 **같은 커밋**에 고칠 것. 한쪽만 고치면 `bundle-sync --check` 가 표류로 잡는다
    - 고친 뒤 **양쪽 위치에서 각각 실행**해 둘 다 통과하는지 확인 (한 위치에서만 돌리면 이 결함이 그대로 재발한다)

## Issue349: fpm-sanitize 가 정상 상태에서 forward 를 조용히 죽임 + fail-loud 무력화 ✅
* 목적: `scripts/fpm-sanitize.sh` 말미의 파이프라인 하나가 **서로 다른 두 결함**을 동시에 만들고 있었다. Issue342 의 승인된 forward sync 가 여기서 막혀 발견됐다.
* 구현 명세:
    - 파이프라인 → **here-doc `while`** 로 전환. 서브셸이 사라져 ②가 진짜 중단이 되고, 빈 입력도 무해해져 ①이 사라진다
    - `if [ -n "$_P3_HITS" ]` 로 감싸 빈 경우를 명시적으로 건너뛴다

## Issue342: 배포 파이프라인 잔여 5건 — 태그 자동화·인벤토리·provenance·sanitize 단사·세션 origin ✅
* 목적: prj3#Issue322(SCAR 감사 v1.0.3 후속) 진행 중 **실행 파이프라인·서버 코드 변경이 필요해 분리**된 항목들. 문서·규약은 그 이슈에서 확정했고, 여기서는 코드를 건드린다. 검증 없이 커밋하면 배포가 깨지는 성격이라 별도 이슈로 뗐다.
* depends: prj3#Issue322
* 구현 명세:
    - 착수 전 **각 항목의 선행 조건을 먼저 실측**할 것 — Issue322 에서 T6·T7·F3-3·F3-4·M6 이 *"이미 되어 있음"* 으로 판정된 전례가 있다. 보고서 기술을 그대로 믿지 말 것
    - 배포 스크립트 변경은 **dry-run 선행**(`opus-4-8-execution-rules` §7). fSnippet·fWarrange 양쪽 `deploy.sh` 가 대상
    - P2 는 착수 시 **기존 미러와의 diff 규모를 먼저 측정**하고 사용자 승인을 받을 것

## Issue346: 배포 스크립트 2건 — 릴리스 태그 생성 배선 + deploy-state 인벤토리 ✅
* 목적: Issue342 의 **F5-4·F5-5** 를 실물 범위로 분리한다. 둘 다 배포 스크립트 한 파일을 고치는 작업이고 대상 repo·dry-run 검증면이 같아 한 이슈로 묶는다. Issue342 안에 두면 그 이슈가 종결될 때 함께 사라진다.
* depends: Issue342

## Issue343: 이슈맵 depends 파서 fail-loud + 규약 정합 — 조용한 의존 유실 차단 ✅
* 목적: prj3#Issue322 에서 `* depends:` 토큰 문법을 확정(괄호 부기 허용·**prj 이름 표기 금지**)했다. 그런데 실측해 보니 **파서가 규약 위반 토큰을 조용히 버리고 있었다** — 경고 없이 `None` 을 반환해 그 의존이 이슈맵에서 **통째로 사라진다**. 규약을 정한 것만으로는 이 유실이 안 잡히므로 파서 쪽을 고친다.
* depends: prj3#Issue322
* 구현 명세:
    - **P1. `None` fail-loud** — `parse_dep_token()` 이 `None` 을 낼 때 **원문 토큰을 수집**해 빌드 종료 시 `⚠️ depends 파싱 실패 N건` 과 목록을 stderr·요약에 출력. ⚠️ 예외: `없음`·`-`·빈 문자열은 정상 no-op 이므로 세지 않는다
    - **P2. prj 이름 표기 경고** — `('ext', ref, …)` 의 `ref` 가 `^prj[0-9]+[a-z]?$` 가 아니면 경고. 자동 해석은 **하지 않는다**(이름은 바뀌고 중복되므로 추측이 오히려 위험 — 규약이 번호를 요구하는 이유가 그것이다)
    - **P3. 테스트 보강** — `services/hub/test_issue_map.py`(249줄, depends 케이스 28건)에 위 실측 8케이스를 회귀 픽스처로 추가
    - **P4.** `services/hub/server.py`(11,448줄) ↔ `plugins/fpm-core/services/hub/server.py`(11,410줄) **38줄 차이** 원인 확인 — 배포 시점 차이면 정상, 미동기면 동기화

## Issue344: prj1 백업 사각지대 — gitignored 원천자료가 host 미러에 안 담김 ✅
* 목적: prj3#Issue322 의 **X2**(prj1 백업 경로 확보)로 host bare mirror 를 신설해 커밋 1229개가 단일 지점이던 위험은 해소했다. 그러나 그 백업은 **git 추적 파일만** 커버한다 — `_doc_base/`·`projects/`·`Projects.md` 등 **로컬 전용 gitignore 대상은 어디에도 백업되지 않는다**. X2 완료 시점에 한계로 명시되며 "별도 경로 필요 시 후속 이슈" 로 남긴 항목이다.
* depends: prj3#Issue322
* 구현 명세:
    - 1단계 **실측 선행** — 미추적 대상의 실제 용량·파일 수를 먼저 잰다(`git ls-files --others --ignored --exclude-standard | wc -l`). 크기에 따라 수단이 갈린다
    - 2단계 수단 선택: ① host 로 `rsync` 하는 별도 경로(추적분 백업과 같은 목적지, git 아님) ② `_doc_base/` 만 별도 private repo ③ Time Machine 존치 + 문서화만
    - ⚠️ **prj1 밖 자산에 손대지 않는다** — 다른 프로젝트의 `_doc_base/` 백업은 본 이슈 범위가 아니다(공통 정책이 필요하면 별도 이슈)
    - 백업 경로를 만들었으면 **복구 리허설 1회**를 X2 와 같은 수준으로 수행하고 결과를 기록

## Issue341: hub 📡 활성 세션 전멸 — 세션 등록 pid 가 단기 wrapper ✅
* 목적: host `http://host:9876/hub-shell` 의 📡 활성 세션이 항상 비어 있음. `sessions.json` 엔 4건 등록돼 있는데 `/boards` 의 `live_sessions=[]`.
* 구현 명세:
    - hook(근본): 죽은 pid 면 `$PPID` 로 대체 후 부모 체인 10단계까지 올라가 claude 세션 프로세스로 승격. 판정은 `comm` basename(`claude`/`claude-code`) + args 의 claude `cli.js`
    - ⚠️ args 에 `claude` 문자열만 보고 판정하면 `zsh -c source ~/.claude/...` 가 오탐(실측) → comm 우선
    - 훅 원본은 prj3(`~/.claude/hooks/`) — 번들(`plugins/fpm-core/hooks/`)은 `fpm-bundle-sync.sh` 가 라이브에서 덮어쓰므로 번들만 고치면 배포 시 되돌아간다(실측). prj3 커밋 `<commit>`
    - 배포 부수 수정: `scripts/fpm-sync.sh` forward 가 exclude 를 sanitize **前** 적용하도록 순서 교정 — exclude 대상인 `_doc_arch/publishable-policy.md` 의 마커 문법 설명이 redaction 마커 불균형으로 오검출돼 forward 가 중단됐다(`_doc_arch` 추적 전환 후 발현)
    - server(방어): `live_pid` 사망이어도 heartbeat 가 `LIVE_TTL`(300s) 이내면 TTL 로 판정하고 죽은 `live_pid` 를 제거(self-heal). 이미 등록된 데드 세션·resume 시나리오 커버

## Issue340: cdf 계열 Linux 이식성 — macOS 하드코딩 제거·헤드리스 거짓 성공 차단 ✅
* 목적: host(Linux) 에서 `cdf 1 3 5` 가 `osascript: command not found` 만 뱉고 동작 안 함. cdf 계열이 macOS 전용 도구(`osascript`·`open`·`pbcopy`·`say`·`/opt/homebrew/bin/tmux`)를 직접 호출한 탓. fpm 이 Linux 로 배포되는 이상 이식성은 선택이 아님.
* 구현 명세:
    - 판정 헬퍼 8종 신설(`sh/fpm_function.sh` 상단): `_fpm_os`·`_fpm_is_macos`·`_fpm_need_macos`·`_fpm_has_display`·`_fpm_tmux_bin`·`_fpm_split_pane`·`_fpm_tmux_focus`·`_fpm_say`
    - 핵심 판정 — **명령 존재 확인만으로 부족**. headless 는 도구가 깔려 있어도 실패하므로 `DISPLAY`/`WAYLAND_DISPLAY` 까지 본다(`_fpm_has_display`)
    - `cdf` 다중: iTerm2 → tmux `split-window` → ⛔ 안내 + **`cdft <ids>` 대안 제시** + 경로 출력(안내 1회만, `_CDF_HINTED`)
    - `cdfc`: headless 사전 차단 + 복사 exit code 검사 fail-loud / `cdff`: headless 면 xdg-open 실행 자체 생략
    - `cdfn`: stdin≠tty 면 명시 오류 + 후보 목록(zsh·bash 양쪽)
    - `cdft`: tmux 경로 PATH 우선 해석 + 완료 후 `_fpm_tmux_focus` 자동 attach(tmux 안=select-window, stdout≠tty=생략 — `pm-do` 파싱 블로킹 방지, `FPM_NO_ATTACH=1` 억제)
    - 검증: host 실환경에서 cdf·cdff·cdfc·cdfn·cdft·cdf-num·sshf 전수 실행. 4회 배포 후 사용자 최종 확인

## Issue339: fpm-core 사전요구 미고지 — mermaid-cli 의존성 ✅
* 목적: 번들 `issue-map` 이 mermaid 렌더러를 요구하는데 `INSTALL.md`·`plugins/fpm-core/CLAUDE.md` 어디에도 언급이 없음. 소비자는 `/fpm-issue-map` 실행 후에야 실패로 알게 됨(host 실측). 사전요구를 설치 문서에 고지해야 함.
* depends: prj3#Issue317
* 구현 명세:
    - [v] `INSTALL.md` "# 요구 사항" 에 2줄 추가 — `* (선택) Node.js + npx — /fpm-issue-map 다이어그램 렌더(없으면 이 커맨드만 미동작)` / `* (선택) mermaid-cli(mmdc) 전역 설치 — 있으면 npx 다운로드 없이 즉시·오프라인 렌더`
    - [v] `plugins/fpm-core/CLAUDE.md` "## 구성 요소" 표 갱신 — Commands 에 `fpm-issue-map` 추가, Skills 를 `fpm-pm`, `fpm-cdf`, `fpm-issue-map` 으로 정정
    - [v] 같은 파일에 "## 사전요구" 절 신설 — 위 상세 ①~④ 를 4줄로. 실패 시 나오는 문구(`mmdc·npx 모두 없음`)를 그대로 적어 검색 가능하게
    - [v] 검증: 두 문서의 문구가 `resolve_mmdc()` 실제 동작과 일치하는지 대조(선택/필수 표기 역전 없을 것)
    - [v] `fpm-sync.sh forward` → `deploy`(버전 bump) → `publish --push`(prj20 포함) 로 마켓 반영. 문서 전용 변경이라 patch bump
    - [v] host 실환경 검증 — 0.2.8→0.2.10 업데이트, 번들 `CLAUDE.md` 9·10·34·38·40·41 행에 구성요소·사전요구 반영 확인. 실측 `mmdc` 부재 · `npx` = /usr/bin/npx · node v22.23.1 → 문서가 서술한 npx 경로와 일치

## Issue338: fpm-core 번들에 issue-map 생성기 누락 — 반쪽 배포 ✅
* 목적: 번들 hub `services/hub/server.py` 는 `Issue_map.htm` 을 serve(`/issue-map`, `ISSUE_MAP_NAME` 고정)하는데 그 파일을 **생성하는 `issue-map` 스킬이 번들에 없음**. 소비자만 배포하고 생산자를 뺀 반쪽 배포 → 플러그인 전용 설치 환경에서 `/issue-map` 영구 404.
* depends: (없음)
* 구현 명세:
    - [v] `plugins/fpm-core/skills/fpm-issue-map/` 생성 + 라이브(`~/.claude/skills/issue-map/`)에서 seed
    - [v] `scripts/fpm-bundle-sync.sh` 에 `sync_skill fpm-issue-map "$GLOBAL/skills/issue-map"` 추가 (사유 주석 동반)
    - [v] `bash scripts/fpm-bundle-sync.sh --check` → "표류 없음" 확인
    - [v] `plugins/fpm-core/commands/fpm-issue-map.md` 수동 편입 — 번들 commands 는 이름 일치분만 동기하므로 신규 파일은 seed 필요
    - [v] prj3#Issue316 반영분 재동기(`bundle-sync` → 표류 없음, 번들 hub test_*.py 전량 통과, `CLAUDE_PLUGIN_ROOT` resolver 실행 검증)
    - [v] `fpm-sync.sh deploy` (v0.2.8, mirror `<commit>`) + `fpm-sync.sh publish --push` (prj20 `<commit>`) 로 마켓 반영
    - [v] host 실환경 검증 — `claude plugin update fpm-core@f-claude-plugins` 0.2.2→0.2.8, 번들 `commands/fpm-issue-map.md` 존재, **글로벌 issue-map 스킬이 없는 플러그인 전용 환경에서** resolver 가 번들 사본 선택 → `Issue_map.htm` 생성 성공(10.3 KB, 이슈 71건)

## Issue336: hub 세션 capabilities 통째 교체로 Zed 신호 유실 ✅
* 목적: hub 카드의 Zed 아이콘이 세션 시작 직후에만 보이고 첫 프롬프트 이후 사라진다. 원인은 `/session/register` 핸들러가 heartbeat 재등록마다 `capabilities` 를 **병합이 아니라 통째 교체**하기 때문. Zed 판정 신호(`capabilities.editor="zed"`)는 SessionStart 훅이 1회만 싣는 값이라, `editor` 없는 caps 를 보내는 topic·model 훅이 그것을 지운다. VSCode 는 `entrypoint` 를 매 등록마다 재전송하므로 무사해서 Zed 만 회귀로 보였다.
* depends: prj3#Issue313
* 구현 명세:
    - `/session/register` 의 기존 entry 갱신 경로를 교체 → **병합**(`entry["capabilities"].update(caps)`)으로 변경. 매 등록에서 재전송되는 `source`·`kind`·`model`·`entrypoint` 는 병합해도 최신값이 이기므로 회귀 없음
    - 신규 entry 생성 경로는 현행 유지(비교 대상 없음)
    - 검증: Zed 세션에서 프롬프트 1회 이상 진행 후 `sessions.json` 에 `editor=zed` 잔존 확인 + hub 카드 아이콘 유지 확인

## Issue335: pm-do 프롬프트의 쉘 메타문자가 tmux send-keys 경로에서 리다이렉션으로 해석됨 ✅
* 목적: `pm-do <prj> "<프롬프트>"` 의 프롬프트에 `<`, `>`, `|` 가 들어가면 위임 세션의 zsh 가 이를 리다이렉션·파이프로 해석해 명령이 조각나고, claude 는 아예 기동되지 않거나 잘린 프롬프트를 받는다. 위임이 조용히 실패하고 원인은 tmux 패인을 직접 봐야만 드러난다.
* 구현 명세:
    - `~/.bin/pm-do` 의 프롬프트 조립부에서 **셸 인용을 명시 적용**한다. zsh 기준 `${(q)PROMPT}` 또는 python `shlex.quote` 등가 처리로 단일 인자화. 임시방편으로 메타문자를 이스케이프하는 방식은 누락 문자가 남으므로 채택하지 않는다
    - 검증: `<`, `>`, `|`, `$`, 백틱, 개행을 모두 포함한 프롬프트로 no-op 위임 1건을 실행해 **패인에 원문 그대로** 도달하는지 확인. 대화형이 아니라 tmux 위임 경로로 검증할 것
    - 2원 구조 주의: 문서는 `~/.claude/skills/fpm-pm-do/SKILL.md`, 실동작 코드는 `~/.bin/pm-do`. 이번 수정은 코드 전용이나 SKILL 문서가 프롬프트 작성 제약을 안내하고 있으면 함께 갱신
    - 관련: Issue334(pm-do extract_hash PATH 의존) 와 같은 스크립트다. 함께 손대면 1커밋으로 묶어도 무방

## Issue337: Bash 로 쓴 htm 은 등록 훅이 아예 안 돌아 영구 403 — 서버 self-heal 등록 ✅
* 목적: <private-project-5> 세션이 렌더한 [hub_htm_20260728_010327_a_rfp-plan.htm](/Users/user/work/<private-project-5>/_doc_work/htm/hub_htm_20260728_010327_a_rfp-plan.htm) 이 `/htm-doc` 에서 `{"error": "not a registered htm doc"}` 403 dead link 가 됐다. 파일·파일명 규약·서버 모두 정상인데 registry 에만 없다.
* 구현 명세:
    - `_htm_doc_autoregister()` 신설 — `/htm-doc` 미등록 판정 시 403 직전에 self-heal 등록 시도. 4조건 전부 충족해야 등록(화이트리스트 모델 유지): ① 실존 파일 + `.htm`/`.html` ② 부모 폴더가 canonical(`_doc_work/{htm,z_done/htm,z_htm}` 또는 `TMP_OUT_DIR`) ③ 파일명이 `_htm_output_stem()` 규약(`hub_htm_*`/legacy `claude-htm-*`) ④ `HTM_CLEARED` tombstone 에 없음(사용자 명시 제거 존중).
    - 임의 경로 노출은 ②③ 이, 사용자 의사는 ④ 가 막는다. 생산자가 어떤 도구로 쓰든 무관하게 링크가 산다.
    - 검증(2026-07-28): 문제 URL → **200** + 로그 `self-heal autoregister (Issue337)`. `/etc/hosts`(비규약) → 403. cleared 문서 → 403 유지.

## Issue332: hub allowlist 적재 race window — 재시작 직후 자기 tailscale IP 가 403 ✅
* 목적: hub 서버 재시작 직후 약 25초 동안 allowlist 가 비어 있어, MagicDNS 호스트명(`<tailnet-host>`)으로 접속한 **자기 자신**이 `{"error": "ip not allowed"}` 403 을 받는다. Issue200 이 재시작 다운타임을 줄이려 allowlist 적재를 백그라운드 스레드로 뺐고, 그 주석은 "루프백은 항상 허용 → 로컬 무영향" 을 전제했으나, tailnet 호스트명으로 열면 같은 머신도 소스 IP 가 tailscale IP(`100.89.64.124`)라 이 전제가 깨진다. hub 를 tailnet 으로 상시 여는 현재 운용에서 재시작마다 재현된다.
* 구현 명세:
    - **DNS 불요 항목은 bind 이전 동기 적재**: `BIND_HOSTS`(self IP 문자열)와 `hub_setting.yml` inline `allow_list`(IP/CIDR) 는 resolve 가 필요 없다. `_populate_allowlist` 에서 이 둘을 분리해 스레드 시작 전에 채운다 → 다운타임 증가 0 으로 창이 닫힌다
    - **Servers.md 호스트 resolve 만 백그라운드 유지** (Issue200 의 원래 목적 보존)
    - **적재 완료 플래그 + 503**: `_allowlist_ready` 플래그를 두고, 미완료 상태에서 비허용 판정이 나면 403 대신 `503` + `Retry-After: 2` 로 응답한다. "차단" 과 "준비 중" 이 구분되어 오진이 사라진다
    - 검증: 서버 재시작 직후 즉시 `curl http://<tailnet-host>:9876/hub` → 200 (기존엔 403). `time` 으로 재시작~bind 소요가 기존 대비 증가 없음 확인

## Issue334: pm-do extract_hash() 가 `head` 를 PATH 로 찾아 위임 완료 hash 회수가 상시 실패 ✅
* 목적: `pm-do <prj> "<명령>"` 위임이 정상 완료되어도 완료 커밋 hash 를 회수하지 못하고 `extract_hash:6: command not found: head` 로 끝난다. 위임의 계약이 "완료 대기 + hash 회수" 인데 그 마지막 단계가 항상 깨지므로, 호출자는 매번 `git log` 로 직접 확인해야 한다.
* 구현 명세:
    - `extract_hash()` 의 `head -1` 을 `/usr/bin/head -1` 로 교체.
    - 같은 스크립트 전체를 훑어 PATH 의존 호출이 더 있는지 확인 (`grep -nE '(^|[^/[:alnum:]_])(head|tail|cut|tr|wc|date|sort|uniq)[[:space:]]' ~/.bin/pm-do`). 발견되면 함께 절대경로화.
    - 검증: 짧은 위임 1건(ex: 이미 종결된 이슈 대상 no-op)을 실행해 hash 가 실제로 출력되는지 확인. 대화형이 아니라 **tmux 위임 경로**로 검증할 것 — 대화형에서는 버그가 재현되지 않는다.
    - 2원 구조 주의: `skills/fpm-pm-do/SKILL.md` 는 문서, `~/.bin/pm-do` 가 실동작 코드다. 이번 수정은 코드 전용이라 문서 동반 변경은 불필요하나, 동작 설명이 hash 회수를 보증하는 문구를 담고 있으면 함께 점검한다.
    - **해결**: `head -1`→`/usr/bin/head -1`(4곳), `tail -1`→`/usr/bin/tail -1`, `date +%s`→`/bin/date +%s` 전면 절대경로화. 검증은 tmux 위임 대신 `PATH=""` 환경에서 `extract_hash` 직접 호출로 대체 — 동일 실패 조건을 결정적으로 재현하며 위임 1건보다 강한 증거다(`hash=[<commit>]` 정상 반환). `skills/fpm-pm-do/SKILL.md` 는 코드 로직을 복제하지 않아 문서 동반 변경 불요.

## Issue333: iterm-bg 가 배경만 칠하고 전경색을 안 바꿔 밝은 프로젝트 색에서 터미널 글자 판독 불가 ✅
* 목적: `Projects.md` 의 파스텔 계열 프로젝트 색(ex: prj15 `#8bd6b3`)이 적용된 폴더에서 iTerm2 터미널 글자가 배경에 묻혀 읽히지 않는다. VSCode 밝기 조정으로는 해결되지 않는다 — 색을 칠하는 주체가 VSCode 테마가 아니라 `chpwd` → `iterm-bg` OSC 이스케이프이기 때문이다.
* 구현 명세:
    - `iterm-bg()` 에 `readable_fg()` 와 동일한 상대 휘도 공식(`0.2126R + 0.7152G + 0.0722B`)을 zsh 정수 산술로 이식하고, 임계값 초과 시 `fg=15202b` · 이하면 `fg=e8e8e8` 을 `SetColors` 로 함께 전송.
    - 인자 없는 복원 경로에 전경색 기본값 복원(`\033]110;\007`)을 추가. 현재는 배경만 되돌리는 `\033]111;\007` 뿐이라, 프로젝트 폴더를 벗어나면 검은 글자가 남는다.
    - ANSI 16색 스왑은 별도 판단 — (a) `Projects.md` 색상을 다크 톤으로 교체(코드 변경 불요, VSCode 타이틀바 인상 변화) 또는 (b) 밝은 배경일 때 ANSI 0~15 라이트 팔레트 동시 스왑(복원 경로도 함께 확장). 이슈 착수 시 택일.
    - 검증: 밝은 색 프로젝트(prj15)와 어두운 색 프로젝트 양쪽에서 `cd` 후 글자 판독 확인 + 비프로젝트 폴더로 이동 시 기본색 복원 확인.

## Issue331: Zed 세션 orphan 누적 — 하이브리드 리퍼(브리지 사망 + idle TTL) ✅
* 목적: Zed 에서 Claude Code 를 쓰면 VSCode 확장 같은 세션 관리(스레드 종료 시 프로세스 정리)가 없어, 스레드마다 새로 뜬 claude 프로세스(ACP 브리지, entrypoint `sdk-ts`)가 스레드를 닫아도 살아남는다. 그 결과 hub 활성 세션 카드가 무한 누적되고 메모리도 계속 점유된다.
* 구현 명세:
    - 판정 `_zed_orphan_reason(entry, now)`: origin(`_origin_from_caps`)이 `zed` 인 live 세션만 대상. `gc_meta.shell_pid`(등록 시 캡처한 브리지 pid)와 현재 `ps -o ppid=` 를 대조해 불일치·사망·`ppid<=1` 이면 `bridge-dead`, 아니면 heartbeat age ≥ `ZED_IDLE_TTL`(1800초) 이면 `idle-ttl`, 그 외 보존
    - 처리 `_reap_zed_orphans()`: `_gc_execute` 의 `kill-claude` 단계 재사용(comm 대조 가드로 pid 재사용 오살 차단, SIGTERM → 2초 → SIGKILL) → `_live_dismiss_add` tombstone → `sessions` prune → `persist_sessions`
    - 배치: `_orphan_reaper_loop` 데몬 스레드(120초 주기) + 수동 트리거 `POST /reap-orphan-live`(loopback only). `/kill-empty-live` 와 완전히 분리 — label 조건을 쓰지 않으므로 VSCode·터미널 세션은 판정 대상이 아니다
    - 검증 결과(2026-07-27): dry-run 에서 zed 10건만 `idle-ttl` 판정, vscode 9건·terminal 2건은 전부 `None`(보존). 실행 후 zed pid 10개 전부 사망 확인, live 항목 23 → 13(잔존은 vscode·terminal). 서버 재기동 로그 `[reaper] started — interval=120.0s idle_ttl=1800.0s (zed only)` 확인
    - 대상 파일: `services/hub/server.py` (`_zed_orphan_reason`·`_reap_zed_orphans`·`_orphan_reaper_loop`·`_handle_reap_orphan_live`)
    - **좀비 킬러 폐기 경로 (사용자 결정 2026-07-27)**: 현행 `/kill-empty-live` 는 VSCode 전용 임시 수단으로 취급한다. 본 이슈의 부모 프로세스 판정 리퍼가 안정화되면 버튼·엔드포인트·`liveSessions.zombie*` i18n 키를 제거한다. 결정사항 섹션에 명시됨

## Issue330: fpm 배포 파이프라인 통합테스트 (원본→미러→마켓→소비자 정합)
* 목적: v0.2.1 배포에서 **버전 문자열은 전부 일치하는데 실제 파일이 어긋난** 상태가 발견됐다. prj20 마켓의 vendored `fpm-core` 가 원본과 54개 파일 상이했고 소비자(host)는 그 구버전 SCAR 를 받아 쓰고 있었다. 원인은 `deploy` 가 `--with-marketplace` 없이 돌아 publish 가 누락된 것인데, 버전 체계가 서로 달라(prj20 `0.9.1` vs 원본 `0.2.1`) 번호 비교로는 탐지 자체가 불가능했다. 지점 *안*을 보는 단위 테스트는 있으나 지점 *사이*를 보는 검사가 없어, 배포 직후 전 구간 정합을 1회 명령으로 판정하는 스모크가 필요하다.
* 구현 명세:
    - 신규 `scripts/fpm-integration-test.sh` — `[--host <ssh-host>] [--quiet]`, 전부 PASS=0 / 1건+ FAIL=1, SKIP 은 0 유지
    - T2 diff 제외는 `.DS_Store`(macOS 부산물)와 `.claude-plugin/plugin.json`(publish 가 버전 주입) 2종만. 제외 추가 시 스크립트 주석에 사유 필수
    - FAIL 출력에 해소 명령 병기 (ex: `→ 해소: bash scripts/fpm-sync.sh publish --push`)
    - 소비자 검사는 `zsh -ic` + 명시 PATH(`$HOME/.local/bin`) 로 호출 — `zsh -lc` 는 `.zshrc` 를 읽지 않음
    - 문서 갱신: `_doc_arch/fpm-sync-deploy.md`(실전 게이트 대응·publish 누락 리스크) + `_doc_arch/fpm-consumer-install.md`(신규, 소비자 설치 SSOT)

## Issue328: Zed·터미널 세션이 hub 활성 세션에 안 보임 — title 폴백 부재
* 목적: Zed(ACP/sdk-ts) 세션이 살아있고 hub 에 register 도 되는데 활성 세션 목록에서 전부 사라짐. 세션 감지가 아니라 title 폴백 부재가 원인이므로 서버측 폴백을 넣어 Zed·터미널 세션을 정상 노출시킴
* 구현 명세:
    - `_collect_live_sessions` live 분기 title 결정 순서에 3단 폴백 추가: `ai_title` → `live_label` → **JSONL 첫 user 프롬프트 발췌**(신규 `_session_first_prompt(cwd, sid)`)
    - `_session_first_prompt`: `_resolve_session_jsonl` 로 경로 해석 후 head 방향 스캔, `type=="user"` 첫 레코드의 텍스트 1줄 발췌(최대 60자, 개행·공백 정규화). mtime 캐시(`doc_cache`)로 재파싱 차단 — `_session_ai_title` 과 동일 패턴
    - 폴백은 hook 변경 불요(prj1 단독). prj3 hook 의 `live_label` 전송은 별건으로 남김
    - 검증: 서버 재시작 후 `/boards` live_sessions 에 `<commit>`(~/.claude, Zed) 세션이 프롬프트 발췌 제목으로 노출되는지 확인

## Issue327: 에디터 추상화 — Zed 1급 지원 ✅
* 목적: fpm 이 VSCode 를 유일 에디터로 가정하여, Zed 병행 사용 시 프로젝트 열기·색 동기·hub 표면·세션 배지가 전부 VSCode 로만 동작한다. 어댑터 계층으로 추상화해 두 에디터 병행을 정상 상태로 만든다
* 구현 명세:
    - P1: `data/editor.yml` + `_fpm_editor_bin`(CLI 해석 5단계, 하드코딩 제거) + `_fpm_editor_open` + `cdfv -e`/`cdfz`
    - P1b: `sh/fpm_editors.sh` 신설(`v`/`z`/`zn`/`za`/`zw`/`vn`/`vw`) + `fpm.sh` source + dotfile 정리
    - P2: `fpm-projects-sync` writer 다중화(`.zed/settings.json`) + `chpwd` 폴백 — Zed 색 키 확정 전 착수 불가
    - P3: `server.py` 앱명 일원화 + 세션 배지 실제 로고 이미지 3값화(`zed.png` 추가) + 클릭 분기 + frontmost `Zed`
    - P5: `pm` 스캐폴드 `.vscode` 조건화 + VSCode 전용 커맨드 명시
    - P3g·P4(prj3 글로벌 hook): `origin=zed` 판정 + `render_target` 자동 강등 — 별건 위임

## Issue325: 공개 미러 개인정보 유출 방지 — 태그 정합 게이트 + 사설 사전 + 반출 diff 승인 ✅
* 목적: Issue324 에서 digest 참조 필터를 도입했으나, 곧바로 주석 태그 오기(무관 번호 `(Issue323)`) 하나로 사설 이슈가 공개 digest 에 실리는 사고가 났다. 현행 방어(정책 exclude·sanitize 리터럴·구조 패턴 VERIFY·참조 필터)는 모두 **작성자가 실수 없이 태깅·등록한다**는 가정 위에 서 있어, 가정이 깨지면 조용히 통과한다. 가정에 기대지 않는 게이트로 대체한다.
* depends: Issue324
* 구현 명세:
    - **G1. 태그 정합 pre-commit 게이트** — `scripts/install-precommit-tagcheck.sh` 신설(기존 `install-precommit-scar.sh` 의 마커 블록 패턴·graceful skip 관례 그대로 따름, 마커 `# tagcheck-precommit-start`)
        - 검사 대상: staged diff 의 **추가된 줄**에 새로 등장한 `Issue{N}` (삭제·기존 줄 무시)
        - 조건 ①실존: `Issue.md` 에 `## Issue{N}:` 헤딩이 있을 것
        - 조건 ②동시성: 그 `Issue{N}` 이 **같은 커밋에서 staged 된 `Issue.md` 변경분에도 등장**할 것 (= 이번 작업이 실제로 다룬 이슈)
        - 위반 시 커밋 거부 + 해당 파일:라인·번호·해소 방법 출력. 우회는 `SKIP_TAGCHECK=1` 환경변수(의도적 예외만, 기록 남게 stderr 경고)
        - 예외 화이트리스트: 이력 서술용 문맥(`Issue.md` 자신·`_doc_work/**`·`_doc_arch/**`) 은 검사 제외
    - **G2. 사설 사전 자동 수집** — `scripts/fpm-issue-digest.sh` scrub 단계에 동적 사전 추가
        - 소스: `Projects.md`(비공개, 미러 제외) 의 경로·프로젝트명 컬럼 → 미러 공개 대상이 아닌 항목의 **경로 마지막 세그먼트·프로젝트명 토큰**을 수집
        - 수집 토큰 중 길이 4 이상·영숫자/언더스코어/하이픈 구성만 채택(일반 단어 오탐 억제용 stop-list 병행)
        - 치환: `<private-project>` (기존 정책 리터럴 치환과 동일 지점, 정책 리터럴이 우선)
        - 정책 `sanitize[]` 하드코딩은 백스톱으로 유지 — 사전이 못 잡는 표현(한글 클라이언트명 등) 담당
    - **G3. 반출 diff 승인 게이트** — `scripts/fpm-sync.sh` forward 경로에 digest 변경 확인 단계 추가
        - 스냅샷의 `Issue_public.md` 와 미러 현행본을 비교해 **새로 추가된 이슈 헤딩 목록**을 출력
        - 대화형(TTY)이면 y/N 확인, 비대화면 `FPM_DIGEST_ACK=1` 없으면 abort(fail-loud)
        - 승인 내역 1줄을 `data/hub/` 밖 로그가 아닌 stderr + 커밋 메시지 관행으로 남김(추가 상태 파일 신설 안 함)
    - **G4. 문서화** — `_doc_arch/publishable-policy.md` 에 "유출 방지 4중 게이트(정책 exclude → scrub/사전 → 참조 필터 → 태그·반출 게이트)" 절 추가 + 사고 대응 런북(인지→제거 커밋→push→히스토리 재작성 판단(승인 필수)→재발 방지 이슈 등록)
    - **검증**:
        - G1: 무관 번호 태그를 넣은 임시 커밋이 거부되는지 / 정상 작업(같은 커밋에 Issue.md 동반 수정)이 통과하는지 / `Issue.md` 미존재 번호 거부
        - G2: `Projects.md` 사설 프로젝트명을 임시로 이슈 본문에 넣고 digest 재생성 → `<private-project>` 치환 확인
        - G3: 새 이슈가 추가된 상태에서 forward 를 비대화로 돌리면 abort, `FPM_DIGEST_ACK=1` 이면 통과
        - 회귀: 현행 digest 13건 구성이 변하지 않을 것(사전 오탐으로 정상 코드 서술이 뭉개지지 않는지 확인)

## Issue324: Issue_public digest — 미참조 이슈·사설 경로 유출 차단 ✅
* 목적: 공개 미러 digest 에 미러 소스가 참조하지 않는 이슈(내부 문서 감사·프로젝트 등록 결정 등)와 사설 경로·프로젝트명이 그대로 실려 나갔다. digest 의 존재 이유는 미러 코드 주석의 `(Issue{N})` 근거 제공 하나이므로, 참조되지 않는 항목은 공개 이득 없이 내부 사정만 노출한다.
* 구현 명세:
    - `scripts/fpm-issue-digest.sh` 코드 참조 필터 신설: `git grep` 으로 미러 반출 대상 소스의 `Issue{N}` 집합을 구해, 그 집합에 없는 이슈 블록을 digest 에서 제거. 참조 코퍼스에서 비반출·예제 경로(설계문서·작업문서·프로젝트 인덱스·템플릿 예제) 제외
    - 포맷 드리프트 가드는 필터 **이전** 추출량(`PRE_FILTER_GOT`)으로 판정 — 필터의 정상 감소를 오탐하지 않도록
    - scrub 규칙 추가: 홈 하위 개인 폴더 경로, 외장 볼륨(`<private-path>`) 경로 → `<private-path>`
    - 정책 `sanitize[]` 리터럴을 검증뿐 아니라 **치환**에도 적용 (종전엔 fail-loud 만 → 수동 대응). 정책 파일은 self-exclude 라 리터럴 자체는 미러로 나가지 않음
    - 검증: 재생성 결과 24→13 이슈, 잔존 PII grep 0건, `--check` 신선도 통과

## Issue322: prj82 경로 갱신 + prj81 관리범위에서 <private-project-3> 제외
* 목적: prj81(<private-project-5>) 안에서 `<private-project-3>` 이 `40-server/` 하위로 재이동(커밋 `<commit>`)됨. registry 의 구 prj82 매핑이 stale 이 되어 갱신 요청됨 (요청 출처: <private-project-5> 세션 2026-07-25)
* 구현 명세:
    - 조치 없음. <private-project-5> 측 문서는 커밋 `<commit>` 으로 새 번호 체계 반영 완료
    - 남은 판단거리: 자체 `Issue.md` 를 가진 하위 트리(`40-server/<private-project-3>`)를 registry 없이 nPTiR 루트로 쓰는 패턴을 일반 규칙으로 명문화할지 여부 → 필요 시 별도 이슈로 신설

## Issue322: prj82 경로 갱신 + prj81 관리범위에서 <private-project-3> 제외 ✅
* 목적: prj81(<private-project-5>) 안에서 `<private-project-3>` 이 `40-server/` 하위로 재이동(prj81 커밋 `<commit>`)됨. prj1 registry 의 prj82 매핑 경로가 구 위치를 가리켜 stale 이며, 중첩 미니프로젝트가 prj81 관리범위에 겹쳐 잡히는 문제도 함께 정리 요청됨 (요청 출처: prj81 세션 2026-07-25)
* 구현 명세:
    - `projects/82` 1줄 경로 교체 + `projects-map` 계열 산출물 재생성(있으면)
    - prj81 관리범위 제외 방식은 prj1 의 registry/스캔 규약에 맞춰 결정 (제외 목록 필드 or 중첩 프로젝트 우선 판정). 중첩 프로젝트 일반 규칙으로 다룰지 여부도 함께 판단
    - 검증: `cdf 82` 가 새 경로로 이동 / `cdf-num` 이 `40-server/<private-project-3>` cwd 에서 82 를 반환 (최장 prefix 일치로 81 이 아닌 82)

## Issue321: hub_setting `unregistered_render` 키 신설 — 미등록 폴더 렌더 정책 ✅
* 목적: 글로벌 hook 이 소비할 미등록 폴더(IS_PROJECT=0) 렌더 정책 키를 hub_setting SSOT 에 추가. prj3#Issue280 의 data 절반.
* 구현 명세: 소비처는 글로벌 `~/.claude/hooks/fpm-hub-trigger.sh` (prj3#Issue280). 키 부재 시 hook 이 안전 기본값 text 로 fallback. + 아이콘 좌측 정렬 (등록: 2026-07-23, 해결: 2026-07-23, commit: <commit>) ✅
* 목적: `host.local:9876/projects-map` 상단 헤더(보라 바)가 뷰포트 절반 폭에만 그려지고 액션 아이콘(📝🗂️)이 제목 옆 좌측에 붙음. 원인은 builder 가 `<div id="topbar">` 안에 `<h1>` 만 방출 → 서버 `_synthesize_hub_header` 가 그 `<h1>` 을 `<header>` 로 승격하는데, 승격된 `<header>` 가 `#topbar` flex 컨테이너의 **자식(flex item)** 이라 content 폭(≈절반)으로 shrink. canonical full-bleed CSS(`margin-inline: calc(50% - 50vw)`)가 body 직속 블록을 전제하는데 flex 자식이라 미적용.
* 구현 명세:
    - `.claude/skills/projects-map/build_projects_map.py`: `#topbar` div 래퍼 제거 → builder 가 **body 직속 canonical `<header>`** 를 직접 방출. hub-link(좌) + h1(좌, `margin-right:auto`) + `nav.header-actions`(우: 📝 btn-note · 🗂️ btn-projects-md · 📁 proj-badge · ✕ close) 구조.
    - 서버 `_synthesize_hub_header` 는 `<header>` 존재 시 no-op → 중복 승격 없음. `_normalize_hub_header_css` 는 `header{` 규칙 부재 시 canonical full-bleed CSS 주입 → **전체 폭**. 🔗 복사(COPY_LINK_SHIM)·닫기(CLOSE_SHIM)·hub 링크(HUB_LINK_SHIM) 는 클래스 셀렉터 기반이라 authored `<header>` 에도 그대로 동작.
    - proj-badge onclick 은 서버 합성본과 동형(`/open-project` fetch + fail-loud alert). 제목 좌측 정렬은 h1 inline `text-align:left;margin-right:auto` 로 canonical 중앙정렬 override.
    - 검증: 재빌드 `Projects_map.htm` 에 `<header>` 방출 확인, `header{` css 규칙 0건(서버 주입 조건 충족), `<div id=topbar>` 소멸. htm/md 는 빌드 산출물(git 미추적).

## Issue319: fpm-projects-sync — projects/ 에 실물 디렉토리 침입 시 침묵 실패 (경로 파일 재생성 불가) ✅
* 목적: `projects/9a` 가 경로 한 줄 파일이 아니라 14MB 논문 프로젝트 실물 디렉토리(+`9a.bak` 중복)로 존재해 `cdf 9a` 등 index 가 깨짐. 원인은 실물 프로젝트(`<private-project-1>`)가 타깃 `<private-project-2>/_doc_base/` 대신 ___pm index 폴더에 잘못 배치됨(수동 mv/cp 또는 haiku 에이전트 실수 추정). `gen_projects` 는 디렉토리를 걸러내지 못해 `os.remove`(IsADirectoryError)·`open(...,'w')` 둘 다 실패, path 파일을 재생성하지 못하고 침묵 실패함.
* 구현 명세:
    - `sh/fpm-projects-sync` `gen_projects()`: 재생성 직전 `projects/<pid>` 중 디렉토리인 항목을 스캔하는 fail-loud 가드 추가. stray 발견 시 Projects.md 의 올바른 타깃 경로와 함께 stderr 출력 후 `sys.exit(2)`. 자동 rmtree 는 백업 없는 실물 삭제 위험이라 금지 — 수동 이동 안내만.
    - 검증: 구문검사 통과, 정상 상태 `--index-only` 43개 재생성 성공, 임시 `projects/99z` 주입 시 exit=2 + 안내 메시지 정상.
    - 현물: 실물은 이미 타깃(`<private-path>`, 2445 파일/14M)으로 이관됨, `9a.bak` 제거됨, `projects/9a` 는 경로 파일로 정상화.
    - 한계: 실물이 index 에 들어오는 것 자체(상류 mv/cp)는 못 막음. sync 단계에서 침묵 오배치를 즉시 감지 가능한 에러로 전환하는 것이 본 이슈 범위.

## Issue317: Projects_map 노드 클릭 403 "loopback only" — `/open-prj` 게이트 `/open-project` 와 불일치 ✅
* 목적: `host.local:9876/projects-map` 에서 노드 클릭 시 `/open-prj?id=1` 가 `{"error":"loopback only"}` 403 반환. 페이지 자체는 `_ip_allowed()`(bind self IP 포함) 로 열리는데, 클릭 핸들러만 strict `client_ip not in LOOPBACK_IPS` 라 bind_host 를 비루프백(LAN, host.local)으로 연 상태에서 페이지는 뜨고 클릭만 죽는 오작동. 동일하게 host-local `open` 을 실행하는 `/open-project`(Issue42/237)는 `_ip_allowed()` + 비루프백 alias 폴백을 쓰는데 `/open-prj`(Issue294)만 더 엄격한 loopback-only 로 묶여 있었음 — Issue284_2 와 동일 유형의 재발.
* 구현 명세:
    - `services/hub/server.py` `_handle_open_prj`: 진입 게이트 `client_ip not in LOOPBACK_IPS` → `not _ip_allowed(client_ip)` (에러 메시지 `/open-project` 와 통일 "localhost only")
    - `subprocess.Popen(open ...)` 직전에 `/open-project` 와 동일한 비루프백+`ssh_remote_alias` 폴백 추가 — alias 설정 시 host-local open 대신 `vscode-remote://` 302 redirect (GET `<a href>` 링크라 JSON 응답 대신 Location 헤더 사용)
    - 검증: `python3 -m py_compile services/hub/server.py` 통과

## Issue316: fPm Hub 프로젝트 카드 배지 — 활성 세션 수 → 미완료 이슈 수로 교체 ✅
* 목적: hub 메인 화면(`/hub`) 프로젝트 카드 배지가 현재 "활성 세션 갯수"(`g.items.length`)를 보여줌. 사용자 피드백: 세션 수는 무의미, 각 프로젝트 미완료 이슈 갯수(Issue.md `🚧 진행중`+`📕`+`📙`+`📗` 합)가 더 유용함 → 배지를 미완료 이슈 수로 교체.
* 구현 명세:
    - 신규 `_find_issue_md`/`_count_open_issues`/`_issue_open_count` 추가. TTL 캐시(`_issue_open_count_cache`, 30s)
    - done 판정: 섹션이 `✅ 완료`(`_ISSUE_DONE_SECTIONS`)면 1차 done, 헤더 줄 끝 `✅` 는 보강 신호(OR) — 최초엔 헤더 접미사만 봤다가 구식 이슈(Issue230/232/236 등, 접미사 없이 섹션만으로 완료 처리된 실제 사례)가 미완료로 오카운트되는 버그 발견 후 교정
    - `_collect_live_sessions()` 결과 dict에 `open_issue_count` 필드 추가
    - 클라이언트 JS 그룹핑에서 프로젝트별 `openIssueCount` 저장, 배지 렌더 `${g.items.length}` → `${g.openIssueCount}` 교체 + `data-tip` 툴팁에 세션 수 병기(정보 손실 없음), `.live-badge[data-tip]` 를 기존 hover 툴팁 위임 셀렉터에 추가
    - Issue.md 없는 프로젝트는 0 처리
    - 검증: `python3 -m py_compile` 통과, hub 재시작 후 `/boards` API 로 pm=3(Issue316 자신 포함 전 3=316+315+310)·obsidian=1·claude=4·m2slide=5·videoMaker=0·common=0 확인 — 수정 전 오카운트(섹션 미반영 시 pm=9)와 대조해 로직 정정 검증

## Issue313: `_doc_arch` 감사 Group C — prj8 _user_lib 감사 방향 결정 ✅
* 목적: prj8 _user_lib(라이브러리 루트, 하위 prj55·56·57 포함)는 `Issue.md` 가 없어 nPTiR 미초기화 상태. Issue307 감사에서 보류됨. 감사 방향 결정 필요.
* depends: Issue307
* 구현 명세:
    - 결정: 루트는 **컨텐츠 없는 컨테이너 폴더로 감사 대상에서 제외**. 실 콘텐츠는 하위 prj55·56·57 각자 독립 관리(이미 등록 프로젝트) — 루트에 별도 Issue.md 신설 불필요
    - 커밋 없음(문서상 결정만)

## Issue311: hub 서버 disk-scan 파일명 패턴 stale ✅
* 목적: hub 서버 htm 디스크 스캔이 구 파일명 패턴만 매치해 현행 산출물을 놓치는 버그 수정 (Issue306 감사 발견)
* 구현 명세:
    - `_htm_output_stem()` 헬퍼 신설 — 구 `claude-htm-*.html` / 현행 `hub_htm_*.htm` 둘 다 인식
    - `_scan_htm_docs_in`(→`/hub-rescan`), `_all_disk_htm_paths`(→`/htm-doc` clear tombstone) 두 곳 적용
    - 검증: `python3 -m py_compile` 통과, `_htm_output_stem` 단독 실행으로 신구 패턴 매치 확인

## Issue309: dash-registry path 정규화 불일치로 dashboard 카드 중복 ✅
* 목적: 같은 `.dash.yaml` 하나가 hub 대시보드에 카드 2장으로 뜨는 버그 근절. macOS `/tmp`→`/private/tmp` symlink 환경에서 dash 등록 writer 2곳이 서로 다른 path 정규화를 써 dedup 이 실패한다.
* 구현 명세:
    - fix: `_handle_register_doc` dash 분기에서 이미 계산된 `path_real`(realpath)로 stored path·dedup 통일 (htm 분기는 기존 abspath 유지 — htm-doc whitelist 는 serve 시 realpath 비교라 무관). server.py:4678 `path = path_real`
    - 정리: 기존 dash-registry.json 중복 entry 1건 제거 (realpath 표기 유지, abspath 제거) — 검증 시 llmwiki entry 1장 확인
    - 검증: dash-registry.json llmwiki entry 1건(`/private/tmp/___pm/llmwiki-compile.dash.yaml`)으로 dedup 됨

## Issue308: cdf "session ready" say 하드코딩 — Issue271(prj3) say 단일 게이트 미경유 교정 ✅
* 목적: prj3 Issue271 이 모든 say 호출을 `~/.claude/hooks/hook-say.sh` 게이트(+`data/hook_say_setting.yml` 카테고리 토글)로 모았으나, cdf(tmux 세션 준비) 계열은 `/usr/bin/say "session ready"` 를 직접 호출해 게이트를 우회함. 카테고리 토글로 끌 수 없어 "session ready" 발화가 계속 남 — 게이트 경유로 교정하여 yml 로 제어 가능하게 함.
* 구현 명세:
    - 8개소 치환: `/usr/bin/say "session ready"` → `SAY_GATE="$HOME/.claude/hooks/hook-say.sh"; if [ -x "$SAY_GATE" ]; then "$SAY_GATE" session_ready "session ready"; else /usr/bin/say "session ready"; fi` (게이트 부재 시 fail-open — 기존 패턴과 동일)
    - prj3 측: `data/hook_say_setting.yml` categories 에 `session_ready: false` 추가 + `hooks/hook-say.sh` `--status` 카테고리 목록에 session_ready 추가 (prj3 커밋 별도)
    - allowlist: `Bash(/usr/bin/say \"session ready\")` → 게이트 스크립트 호출 허용 항목으로 교체
    - 검증: `hook-say.sh session_ready "session ready"` 무음 확인 + `hook-say.sh --status` 에 session_ready OFF 표시

## Issue305: Projects_map 상단에 `_note.md` 렌더 — 하단 수기 `#notes` 블록 대체, 공개 빌드는 고정 문구 ✅
* 목적: 프로젝트 맵을 열 때마다 보이는 "지금 신경 쓸 일"을 파일 하나(`_note.md`)로 관리하고, 맵 상단(부제 바로 아래)에 렌더한다. 현재 메모 창구인 하단 `#notes` HTML 구간은 재생성 보존 마커에 의존해 편집이 번거롭고 실사용 이력이 0이라 대체한다.
* 구현 명세:
    - `build_projects_map.py`:
        - `NOTE_PLACEHOLDER = "_note.md의 내용"` 상수 신설
        - `read_note(root)` — `{root}/_note.md` 를 읽어 마크다운 bullet(`* `/`- `)을 `<ul><li>` 로, 그 외 줄을 `<p>` 로 변환. 파일 부재·빈 내용이면 `NOTE_PLACEHOLDER` 반환
        - 산출물 `<div class="meta">` 직후에 `<div id="note">` 삽입 (htm), md 판은 부제 다음 문단에 같은 내용 삽입
        - 하단 `<div id="notes">`·`DEFAULT_NOTES`·`extract_existing_notes()` 제거 (보존 마커 소비처 소멸)
    - `data/publishable-policy.yml` `exclude[]` 에 `_note.md` 추가 — 향후 ___pm 에서 tracked 로 전환되더라도 미러 유출 차단(방어적 이중화)
    - 검증: `_note.md` 있는 상태 빌드 → 상단 렌더 확인 / 임시로 파일 치운 상태 빌드 → 고정 문구 `_note.md의 내용` 확인

## Issue303: 하위 프로젝트 접미 id(`9a`) 도입 — 정수 전용 id 스킴 확장 ✅
* 목적: 다른 프로젝트의 하위 자산인 폴더를 별도 프로젝트로 등록할 때, 소속을 번호 자체로 표현할 수단이 없었음. 기존 id 는 정수 전용이라 무관한 빈 정수를 배정하고 계층은 설명란에만 적어야 했음. 접미 id 를 도입해 `9a` 가 `9` 의 하위임을 번호만으로 드러냄
* 구현 명세:
    - id 정본 정규식 `^[0-9]+(?:[a-z][0-9]*)?$` 단일 패턴으로 전 소비처 통일. 정렬키 `(정수부, 문자부, 하위정수부)`
    - `sh/fpm-projects-sync`: `parse_table` 의 `pid.isdigit()`/`int(pid)`, `gen_projects` 의 `f.isdigit()` 정리 로직, 정렬 `key=lambda r: r['id']`
    - `sh/fpm_function.sh`: `_cdf_base` 토큰 판별 `^[0-9]+$` 확장. 범위 검사보다 **뒤**에 배치하여 `11-16` 보존. glob·case 는 무변경(이미 매칭)
    - `sh/update-iterm-bg`: `proj_id.isdigit()`/`int(proj_id)` → alias `iterm-bg-9a`
    - `plugins/fpm-core/services/hub/server.py`: 색·이모지·목록 캐시 3곳의 `int(cells[0])`, `/open-prj` 의 `raw.isdigit()`, `/issue-open` 의 `re.fullmatch(r"\d+", prj)`
    - `plugins/fpm-core/hooks/fpm-hub-trigger.sh`: 프로젝트 판정의 `fn.isdigit()`
    - `.claude/skills/projects-map/build_projects_map.py`: 표 행·트리 노드 regex 3곳
    - `Projects.md`: `9a` 행 추가(부모 `9` 바로 아래) + 번호 대역 규칙에 접미 id 문법 명시 + Project Map 트리 노드
    - 검증: `cdf 9a` 이동, `cdf 11-16` 범위 회귀 없음, `fpm-projects-sync` 로 `projects/9a` 생성, hub 목록 노출

## Issue301: 맵 세션 배지 — 실패 원인 은폐·stale 방치 교정 ✅
* 목적: 맵(`host.local:9876/projects-map`)에서 배지 클릭 시 "hub 서버 미응답 — 세션 열기 실패" alert. 서버 로그 대조 결과 **같은 시각 사용자 클릭 4건은 200 정상 처리**되었고 실패한 클릭만 **로그가 없다** — 요청이 hub 에 닿지 못한 클라이언트측 실패. Issue299 코드가 (1) 실패 원인을 한 문장으로 뭉개 진단을 막고 (2) 폴 실패를 조용히 삼켜 낡은 배지를 그대로 두는 것이 실제 결함.
* depends: Issue299
* 구현 명세:
    - `openSession` 을 `r.text()` → JSON 파싱 시도로 바꿔 3분기 처리 — ① 서버 `error` 필드(HTTP status 병기) ② 비-JSON 오류 응답(원문 200자) ③ 전송 실패(`origin` + 예외 원문). `.local` mDNS 해석 실패가 "서버 미응답"으로 오인되던 경로 제거
    - `poll` 에 `failStreak` 도입 — 2회 연속 실패 시 `setStale(true)`: 배지 `opacity .3` + `grayscale`, 툴팁 뒤에 "⚠️ hub 응답 없음 — 최신 상태 아님" 부착(HTML 배지=`title` 속성 / SVG 배지=자식 `<title>` 양쪽 처리), 콘솔 경고. 성공 시 원복
    - `renderKey()` = 세션 집합(`cwd|sid|content_type` 정렬) + SVG 노드 수. 키 동일하면 `render()` 즉시 반환 → destroy/recreate 제거. 노드 수를 섞어 mermaid 렌더가 늦게 끝난 경우도 1회 잡음

## Issue302: mermaid 다이어그램이 코드블록 배경(`pre`)을 상속 ✅
* 목적: 밝은 hub 문서 위에 다이어그램만 검은 캔버스로 렌더되는 mismatch. 원인은 mermaid 테마가 아니라 페이지 CSS — 다이어그램이 `<pre class="mermaid">` 로 저작되므로 코드블록 스타일 `pre { background:#2d2d2d }` 를 그대로 상속하고, mermaid SVG 는 배경이 투명해 그 검정이 비쳐 보인다. Issue245 의 luminance 판정은 `document.body` 만 보므로 `<pre>` 자체 배경은 사정권 밖이었다(테마는 `neutral` 로 정상 선택됨 — 노드가 밝은 회색인 것이 증거).
* 구현 명세:
    - `services/hub/server.py` `MERMAID_RUNTIME` 선두에 `<style>pre.mermaid,.mermaid{background:transparent;color:inherit;padding:0;}</style>` 추가
    - 런타임이 서브 시점에 주입되므로 **기존 문서에 소급 적용**. Issue244(서버가 mermaid 렌더의 단일 권위) 철학의 연장
    - 검증: 위 m2slide 문서를 `/htm-doc` 로 재요청 → 주입된 규칙 확인

## Issue258: hub 내부 탭 alt+w 닫기 시 Chrome 크래시 — **macOS 접근성(AX) abort** (iframe 이론 오판, 재개: 2026-07-11, 보류: 2026-07-11) ⏸️
* 목적: Issue223(디바운스)·237(playwright headless)·250(iframe fallback) 이후에도 Chrome 이 죽는 케이스 잔존. 사용자 확정 repro: **"hub 탭 여러 개 떠있을 때 + 내부 탭 alt+w 로 닫을 때"**. "완전 해결"(탭 수 무관) 요구.
* depends: Issue223, Issue237, Issue250

## Issue115: Hub 자동 리프레쉬 (tmux 백그라운드 프로세스 제거)
* 목적: dashboard 데이터 파일 변경 시 hub 페이지 자동 리프레쉬 (수동 새로고침 제거). tmux 환경에서는 별도 백그라운드 프로세스 대신 window 내부 폴링으로 구현.
* 구현 명세:
    - dashboard 데이터 파일 감시 (mtime 폴링)
    - 변경 감지 시 페이지 reload (js: location.reload 또는 fetch + DOM 업데이트)
    - 간격: 5초 (hub 페이지 로드 시 자동 시작)
    - 중지: 탭 닫기 또는 명시적 중지 버튼

