---
title: Project Mananger Issue
description: Project Mananger 이슈 관리 파일
date: 2026-03-27
---

# Issue Management
* Issue HWM: 197
* 오래된 Issue: `_doc_work/Issue_OLD.md` (General)
* Save Point:
    - 3e69d0f (2026-04-24) Feat: graphify 토큰 절감 SCAR 프로젝트 구현 (Issue11·12 등록)
    
# 🤔 결정사항

* **htm-doc 빈 화면 ↔ VSCode OUTLINE 괴리는 추가 구현하지 않는다** : htm-doc 는 registry 화이트리스트만 serve(미등록=403), OUTLINE 은 파일 직접 파싱이라 구조상 독립. fallback 렌더링 등 우회 장치 불필요 — hub 서버 모드 끄고(`..hub off`) `file://` 직접 열거나 register-doc 등록하면 보임. 같은 조사·구현 시도 반복 금지. 상세: `_doc_work/debug_TECH.md` 2026-06-14 항목
* Issue.md파일 공개 하기로 함. 

# 🌱 이슈후보

# 🚧 진행중

## Issue194: hub 내부 탭 렌더 모드 — OS 브라우저 탭 대신 hub 쉘 iframe 탭 (등록: 2026-06-23)
* 목적: 현재 hub 렌더(`..show`/`..ask`/`..board`)는 매 렌더마다 OS 브라우저 새 탭/창을 연다. Chrome 계열에서 새 탭 open 이 창을 foreground 활성화 → 보던 타 앱 창을 가림. OS 탭 대신 hub 쉘이 렌더 문서를 내부 iframe 탭으로 호스팅하는 신규 모드 도입.
* plan: `_doc_work/plan/hub-internal-tabs_plan.md`
* task: `_doc_work/tasks/hub-internal-tabs_task.md`
* arch: `_doc_arch/hub_internal_tabs.md`
* 상세 (요구 4종):
    - R1 옵션: 신규 키 `render_tab_mode: browser-tab(기본·무변경) | hub-internal`. opt-in → 회귀 0
    - R2 탭 닫기 단축키 지정: `tab_close_shortcut`(기본 `alt+w` — Ctrl/Cmd+W 브라우저 선점 회피)
    - R3 단축키는 show/ask/board 에서만: 활성 탭 content_type ∈ {response,form,dashboard} 일 때만 바인딩·힌트 노출
    - R4 외부 다중 접속 추적, 호스트당 1창: 서버가 source-IP(호스트)당 hub 리스 + SSE heartbeat TTL. 2번째 창 takeover 안내, 명시 `[인계]` 로만 양도
* 구현 명세:
    - 구조: iframe 격리(`/htm-doc` 핸들러 무변경) + 신규 SSE `tab-open` push + `GET /hub-shell` 라우트
    - `render_tab_mode` 서버 yml 직독 → hook 변경 없이 서버·설정만으로 MVP 성립
    - triage=복잡(서버+설정+쉘+리스 다컴포넌트). SSOT=`services/hub/server.py`
    - ⚠️ 글로벌 hook(`fpm-hub-trigger.sh`·`fpm-hub-doc-register.sh`) OS open 분기는 글로벌 SCAR → `~/.claude/Issue.md` 별도 이슈 (본 이슈 범위 외)

# 📕 중요

# 📙 일반

## Issue193: `/boards` 카드 progress 스칼라 미집계 — 문자열 value 타입 불일치 (등록: 2026-06-21)
* 목적: Issue189 board rename 재테스트(board-retest)서 발견. `/boards` 카드 레벨 `progress` 스칼라가 `null`. rename 회귀 아님(엔드포인트·식별자만 변경, 집계 로직 무관).
* 상세 (근본 원인 확인 완료):
    - server.py 의 progress 위젯 추출이 `isinstance(w.get("value"), (int, float))` 숫자 타입만 인정 (line 2110-2111, 2147-2150, 2182-2183).
    - runner/monitor 가 progress 위젯 value 를 **문자열 `'100'`** 으로 기록 → 숫자 체크 실패 → `entry["progress"]` = None 잔류.
    - 위젯 자체 value 표시('100')는 정상 → 카드 UI 영향 없음. 카드 메타 progress 집계만 비어, 정렬·집계 용도에서 누락 가능.
* 구현 명세 (택1):
    - 옵션1(소비자): server.py progress 추출에 문자열-숫자 coercion 추가 — `float()` try 후 반영
    - 옵션2(생산자): runner/monitor 가 numeric value 기록
    - SSOT=`plugins/fpm-core/services/hub/server.py` + `services/hub/server.py`(본체). triage=단순(타입 coercion 1~2곳). 옵션1 권장(소비자 방어적 — 기존 문자열 dash 파일 호환).

## Issue192: c모드 `/boards` 신규 카드 자동 등록 갭 (등록: 2026-06-21)
* 목적: Issue189 board rename 후 c모드(Live Dashboard) 실 에이전트 테스트(board-rename-test)에서 발견. rename 회귀는 아니나 c모드 자동화 완결성 갭 — runner 가 생성한 신규 `.dash.yaml` 카드가 `/boards` 에 자동 노출 안 됨(dash-registry 미등록). 사용자가 hub UI `rescan` 을 눌러야 보임.
* 상세:
    - 원인: `/boards` dashboard 섹션은 dash-registry 등록 항목만 노출(Issue44). 레지스트리는 `/register-doc`(생산자) 또는 `/hub-rescan`(수동)으로만 채워짐.
    - `plugins/fpm-core/hooks/fpm-board-notify.sh`(PostToolUse)는 `/register`+`/notify`(SSE)만 호출, `/register-doc` 미호출. runner 는 순수 파일 기반(서버 호출 0).
    - 검증: 최초 `/boards` 카드 부재 → `POST /hub-rescan` `{added:{dash:11}}` 후 노출 확인. SSE 실시간 push 는 이미 열린 뷰어에만 적용, 신규 카드 발견은 별개.
* 구현 명세 (택1):
    - 옵션1: `fpm-board-notify.sh` 에 `.dash.yaml` 매칭 시 `/register-doc` 호출 추가(producer 등록)
    - 옵션2: `fpm-board.md` 절차 — tmux window 시작 직후 dashboard 가 `/register-doc` 1회 호출 명시
    - SSOT=`plugins/fpm-core`(___pm 편집 가능, 글로벌은 reinstall 전파). triage=중간(설계 선택 필요) → 구현 전 plan 권장.

## Issue190: hub 서버 lifecycle 커맨드 `/hub` 단일화 (등록: 2026-06-21)
* 목적: `/hub`(prj1 로컬)·`/board-server`(글로벌, 구 dashboard-server)가 동일 단일 데몬(port 9876 `server.py`)을 만지는 중복 wrapper. 데몬은 hub 서버(a/b/c 3모드+Q&A 공통)이고 board 는 한 클라이언트뿐 → 사용자 결정(폼 회수)=`/hub` 로 통일.
* depends: Issue189 (board rename 선행 완료, commit 1455b66)
* 상세:
    - `/board-server` 폐기(deprecated alias) → `/hub` 흡수
    - `/hub` 글로벌 승격(현 prj1-local `.claude/commands/hub.md` → 전 프로젝트 사용 가능)
    - 서브커맨드 합집합: start/stop/restart/**status**/clear/reset (status 는 board-server 에만 있던 것 흡수)
* 구현 명세 (선행 해결 필요 — 이름 충돌):
    - ⚠️ "hub" 단어 3중 사용 충돌 정리 선행: `/hub`(lifecycle) vs `..hub`(우산 토글 on/off/start/stop, Issue105) vs `/fpm-hub`·`..hub`(a모드 render deprecated alias, Issue133). `/hub start` 와 `..hub start`(per-folder 토글)가 의미 충돌 — lifecycle 의 start/stop 과 토글의 start/stop 이 동음이의.
    - 글로벌 승격 시 플러그인 네임스페이스 `fpm-` 충돌: `fpm-hub`(render)가 이미 점유 → lifecycle 글로벌명 후보 `fpm-hub-server` 또는 토글과 구분되는 별도 동사 필요.
    - 글로벌 SCAR 가드: `plugins/fpm-core/commands/` 변경은 글로벌 영향 → 재설치 전파 + 글로벌 Issue 연계
    - 권장: plan 작성하여 충돌 해소안(네이밍 매트릭스) 확정 후 구현. rename-reference 5단계.
* 비고: 단순 rename 아님(설계 결정 — 후속 영향). triage=복잡 → plan 필수.

# 📗 선택

# ✅ 완료
## Issue197: hub 설정 탭 내용 재배치 (Basic/Sessions/Advanced 그룹 정리) (등록: 2026-06-23, 해결: 2026-06-23, commit: 3842ee0) ✅
* 목적: 기존 3탭에 설정 키 임의 배치 → 의미별 응집도 기준 재배치. deprecated `browser_focus` 정합.
* depends: Issue196
* 결과:
    - basic: `default_browser`, `browser_open`, `browser_focus`(dep), `browser_tab_reuse`, `language`
    - session: `live_session_*`(3), `card_limit`, `search_limit`, 피드 키 5종(`feed_default_visible`·`feed_limit`·`feed_poll_interval`·`feed_show_*`) 일원화
    - advanced: `render_target`·`render_tab_mode`·`tab_close_shortcut`·`hub_single_window`·`hub_lease_ttl`(렌더·탭) + `bind_host`·`advertise_host`·`allow_server_list`(네트워크)
    - `browser_focus` 미이동 (deprecated, 타 세션 제거 작업중)
    - 검증: `GET /api/settings` 라이브 스키마 = 의도한 탭 매핑 일치 확인. SSOT=`services/hub/server.py` + `_doc_arch/hub_settings_ui.md` 갱신
    - ⚠️ `plugins/fpm-core/services/hub/server.py` 미러는 전체 구버전(스키마 부재) → fpm-sync 배포로 갱신 (수동 패치 안 함)

## Issue196: hub 설정창 너비 확대 + 행 레이아웃 2행화 (등록: 2026-06-23, 해결: 2026-06-23, commit: 3842ee0) ✅
* 목적: hub Settings 모달이 좁아(~720px) `label·control·description` 3컬럼 중 설명 칸이 굶어 단어당 한 줄로 깨짐. 너비 확대 + 2행 레이아웃으로 가독성 확보.
* 결과:
    - 모달 너비 `min(720px,94vw)` → `min(960px,92vw)`
    - `.set-row` flex-wrap + `.set-desc { flex:1 0 100%; padding-left:14.7em }`(컨트롤 아래 전체폭) + `.set-badge { margin-left:auto }`(1행 우측). DOM 순서 label→input→badge→desc
    - 검증: 서빙 `/hub` HTML 에 `width:min(960px,92vw)`·`flex: 1 0 100%`·`margin-left: auto` 3종 존재 확인. SSOT=`services/hub/server.py`
    - 설계 근거: `_doc_work/z_htm/hub_htm_20260623_215458_a_settings-final.htm`

## Issue195: hub bind_host 리스트화(멀티 bind) + inline allow_list + allow_server_list 게이트 분리 (등록: 2026-06-23, 해결: 2026-06-23, commit: 48e4365, 1257b61) ✅
* 목적: hub 서버의 source-IP 접근 제어를 `bind_host` 에서 분리하고 세분화. (1) `bind_host` 가 listen 인터페이스 결정에만 쓰이도록 `allow_server_list` 토글 분리, (2) `bind_host` 를 리스트로 받아 0.0.0.0 와일드카드 없이 특정 주소들에만 멀티소켓 bind, (3) Servers.md 외에 yml inline `allow_list` 로 IP/CIDR 직접 추가 허용.
* 상세:
    - `allow_server_list: true`(기본)=비루프백 bind 시 Servers.md(check=O)+self allowlist 적재 / `false`=self+루프백만 허용(외부 전부 차단). bind_host 와 독립 토글
    - `bind_host` 스칼라 또는 `[127.0.0.1, 192.168.0.17]` 리스트 — 리스트면 각 주소 개별 `ThreadingHTTPServer`(멀티소켓), 단일 문자열 하위호환
    - `allow_list: [IP, CIDR]` — yml inline allowlist, Servers.md 와 **additive 병합**. IP/CIDR 만(호스트명 미지원, DNS 비의존). 비-IP 항목 무시+로그
* 구현 명세:
    - `services/hub/server.py`(commit 48e4365): `BIND_HOSTS` 전역, `_parse_yml_list()` 헬퍼, 로더 리스트 파싱(bind_host 대괄호 + allow_list), defaults `allow_list: []`, main() 멀티 bind serve(첫 소켓 메인 스레드, 나머지 데몬 스레드) + `_open_mode = any(비루프백)` 일반화 + allow_list 병합 적재(개방 모드, allow_server_list 토글과 독립)
    - `data/hub_setting.yml`(commit 1257b61): bind_host 리스트 표기, allow_server_list, allow_list 예시 주석
    - `allow_list` 는 yml 전용(설정 UI text 위젯이 `/`·`,` 거부 → schema 미등록, HUB_SETTING_DEFAULTS 에만 추가)
* Walkthrough: 폼 미응답으로 신규 기능 보안 기본값(additive 병합 + IP/CIDR 만) 채택. 검증 — 파싱 단위테스트·멀티소켓(127.0.0.1+192.168.0.17 동시 bind 양쪽 200)·test_settings_loader 10 pass·test_settings_writer 17 pass·라이브 재시작 회귀 없음. server.py 는 동시 작업 세션의 48e4365(allow_server_list false 의미 재작업 + Issue194 번들)에 함께 커밋됨. ⚠️ 미사용 `ALLOW_ALL` 전역 dead flag 잔존(무해).

## Issue191: fpm-hub-trigger.sh subagent_type stale 식별자 정리 (등록: 2026-06-21, 해결: 2026-06-21, commit: cf5c958) ✅
* 목적: 글로벌 Issue161(board rename 글로벌 전파) 의 후속 과제 — 렌더 문서 `~/.claude/_doc_work/z_htm/hub_htm_20260621_163550_a_issue161-board-rename.htm` 에 scope·WIP 근거로 기록된 hooks 잔존 참조. dispatch 프롬프트의 agent 타입 식별자가 `fpm-board` rename(Issue189) 과 불일치.
* depends: Issue189
* 상세:
    - `plugins/fpm-core/hooks/fpm-hub-trigger.sh:362` `subagent_type='dashboard'` → `'fpm-board'` (등록 agent 명 정합)
    - 보존: line 405 `~/.claude/skills/dashboard/ 폐기됨`(역사적 폐기 공지), 13건 `..dashboard` deprecated alias·UI 명사 "dashboard"
* Walkthrough: ___pm SSOT(`plugins/fpm-core`) 1줄 수정. 글로벌 `~/.claude/hooks/*` 잔존(ask-form-template.js·ask-marker-detect.sh·ask-intercept.sh·hub-trigger.sh)은 글로벌 Issue161 재설치 전파로 흡수 — SSOT 가 board 정합이므로 reinstall 시 자동 갱신.

## Issue189: dashboard 식별자 → board 통일 rename (등록: 2026-06-21, 해결: 2026-06-21, commit: 1455b66) ✅
* 목적: c모드 트리거 `..board` 와 내부 식별자 `fpm-dashboard`/`/dashboards`/`spa_dashboard` 의 단어 불일치 해소. `..show`→`fpm-show`, `..hub`→`fpm-hub` 와 동일하게 트리거=커맨드명 정합. 사용자 결정(폼 회수)=전부 board 통일.
* plan: `_doc_work/plan/dashboard-to-board-rename_plan.md`
* task: `_doc_work/tasks/dashboard-to-board-rename_task.md`
* arch: `_doc_arch/hub_board_tmux_design.md`
* 상세:
    - rename(식별자 한정): `fpm-dashboard*`→`fpm-board*`(agent 6·command 2), `spa_dashboard.py`→`spa_board.py`, `/dashboards`→`/boards`, `/dashboard-server`→`/board-server`, `_doc_arch/hub_dashboard*.md`→`hub_board*.md`+`dashboard-scenario-kit.md`→`board-scenario-kit.md`, `install_manifest.sh`
    - 유지: 트리거 `..board`·`_doc_work/board/`·`..dashboard` deprecated alias·UI 명사 "Dashboard"·과거 동결 산출물·캐시·git branch
* Walkthrough: rename-reference 5단계로 git mv 14파일 + 토큰 sed 29파일 → 라이브 소스 식별자 0건(잔존은 Issue.md 이력·img png·UI 명사뿐), `spa_board.py` py_compile PASS, frontmatter `name: fpm-board` 정합. 단일 commit 1455b66.
* 후속(out-of-prj1): 글로벌 `~/.claude` 전파 = 글로벌 `~/.claude/Issue.md` **Issue161** 로 위임(글로벌 SCAR 가드, 사용자 폼 선택). fpm 미러 동기화는 미선택(다음 deploy 시).

## Issue187: fpm 공개(public release) 사전 정비 — 개인정보·기술유출 가드 + copyright/문서 영·한 분리 (등록: 2026-06-21, 해결: 2026-06-21, commit: 8794169, dda74d7) ✅
* 목적: ___pm → 공개 미러 fpm 의 정식 오픈소스 공개 전, (1) 잔존 개인정보 제거 (2) 비공개 기술자료(특히 공개 전환된 Issue.md) 유출 차단 (3) copyright 영/한 분리 (4) 모든 공개 문서의 영·한 2개 버전화 + 상호 링크. 글로벌 영어권 + 국내 독자 동시 대응 + 법적·프라이버시 리스크 제거.
* 상세:
    - **항목1 — 개인정보 제거 (audit + 강화)**:
        - 현황: `data/publishable-policy.yml` 이 exclude[]·sanitize[]·personal_guard[]·secret-scan 으로 1차 집행 중 (`$HOME`→`$HOME`, `user@`→`user@`, mac HW UUID, jm4/host.local, exampleProj 등).
        - 작업: 미러 산출물 전수 grep 으로 잔존 PII 탐지 — 실명·개인 이메일·전화·서버 IP·내부 호스트명·절대경로·Team ID·UDID. 누락분은 sanitize/exclude 규칙 추가.
        - 산출: 공개 미러(`~/_git/__all/fpm`) 기준 "개인정보 0건" 검증 리포트.
    - **항목2 — 이슈 제외 기술 자료 유출 방지**:
        - 배경: 🤔 결정사항 "Issue.md 파일 공개" → Issue.md 전체가 미러로 나감. 본문에 비공개 의도 기술자료(미공개 제품 설계·외주 프로젝트 상세·내부 인프라 구조·보안 게이트 내부 로직)가 섞일 위험.
        - 작업: 공개 부적합 이슈 본문 판정 기준 정의(외주/사적 인프라/보안 우회 상세/미공개 상용 설계). 해당 이슈를 미러에서 제외하거나 마스킹하는 메커니즘 설계 — sanitize 리터럴 치환만으로 부족 → "이슈 단위 redaction" 또는 공개용 Issue.md 별도 생성안 검토.
        - 가드: `.gitleaks.toml`·`fpm-secret-scan.sh` 와 정합. 공개 전 최종 1회 수동 리뷰 게이트 명문화.
    - **항목3 — copyright 영문/한글 버전 분리**:
        - 현황: `LICENSE`(PolyForm Noncommercial, 영문) + `COMMERCIAL.md`(한글). copyright notice 가 혼재 — "Required Notice: Copyright fpm contributors (https://finfra.kr/nowage)".
        - 작업: copyright/라이선스 안내를 영(`COMMERCIAL_en.md` 또는 `LICENSE-COMMERCIAL_en`)·한(`COMMERCIAL_ko.md`) 으로 분리. LICENSE 원문(PolyForm)은 영문 표준 유지(법적 효력 원문), 한글본은 "참고 번역" 명시. copyright notice 표기 통일.
    - **항목4 — 각 문서 영·한 버전 + 상호 링크**:
        - 현황: 공개 문서 전부 한글 단일 (README.md / INSTALL.md / COMMERCIAL.md / CLAUDE.md / Harness.md / noteForHuman.md). en/ko 분리본 없음.
        - 작업: 공개 대상 문서별 `*_en.md` / `*_ko.md` 페어 생성. 네이밍 규칙 확정(`README.md`=영문 기본 + `README_ko.md`, 또는 `README_en.md`/`README_ko.md` 양립). 각 문서 상단에 상호 링크 뱃지(`[English](README_en.md) | [한국어](README_ko.md)`).
        - 주의: rename/신규 시 `~/.claude/rules/rename-reference-rules.md` 5단계(사전 grep→rename→참조 갱신→사후 검증→단일 commit) 준수. 과거 fSnippet `README_kr.md→README_ko.md` 링크 누락 회귀 재발 방지.
* 구현 명세:
    - 편집 위치: 정책은 ___pm `data/publishable-policy.yml` (fpm-sync 스킬 경유 편집 권장). 문서 본문은 README 가 prj7(fpm) 수동 편집 대상인 점 유의(README 충돌 방지 정책). 나머지 공개 문서는 ___pm forward 동기화 경로.
    - 동기화: ___pm 편집 → `scripts/fpm-sync.sh` forward (가드 통과분만 미러). 항목1·2 가드는 결정적 sh 헬퍼(`fpm-guard.sh`·`fpm-sanitize.sh`·`fpm-secret-scan.sh`)가 집행.
    - 복잡도: **복잡** (정책 변경이 후속 공개 운영에 영향 + 다파일 + 영·한 문서 체계 신설). plan/task 별도 요청 시 생성 — 본 등록은 리스트·이슈 등록까지만.
    - 의존: 항목2(이슈 redaction 메커니즘)는 항목1(개인정보 가드) 정합 전제. 항목4(문서 영·한)는 항목3(copyright 분리) 네이밍 규칙과 정렬.
* 진행 결과 (2026-06-21, commit ab101c1·6a892dd / 미러 454ab8a·294d89f):
    - **항목1 완료**: 미러 전수 grep → 실이메일 유출 1건(Issue.md 내 본 이슈 본문) 발견·제거. sanitize 백스톱 추가(`user@example.com`→`user@example.com`). 미러 PII 재스캔 0건 확인. (Issue.md 는 사용자 정책 편집으로 미러 exclude 복원 — 항목2 완료까지 비공개 게이트)
    - **항목2 완료(메커니즘)**: `fpm-sanitize.sh` 에 블록 redaction 패스 신설 — 마크다운(`*.md`)에서 `` 구간을 forward 스냅샷서 제거. 마커 불균형 시 fail-loud(exit 2). 테스트 PASS. **운영 컨벤션**: 공개 부적합 이슈/구간을 이 마커로 감싸면 미러서 자동 redaction. Issue.md 공개 재개 전 마커 적용 + 최종 수동 리뷰 게이트.
    - **항목3 완료**: `COMMERCIAL.md`(영)+`COMMERCIAL_ko.md`(한) 분리. `LICENSE`(PolyForm 영문 법적원문) 유지 + `LICENSE_ko.md`(참고 번역, 비효력 명시) 신설. copyright notice `Copyright fpm contributors (https://finfra.kr/nowage)` 통일.
    - **항목4 완료**: `README`·`INSTALL`·`COMMERCIAL` 각 `X.md`(영문 GitHub 기본)+`X_ko.md`(한글) 페어 + 상단 상호링크 뱃지(`🌐 English | 한국어`). 동급 문서 링크 언어판 정렬. README 는 prj7 미러 직접 편집(forward 제외).
    - **결정**: 상용 라이선스 연락처 = `finfra@gmail.com` (sanitize `user@`→`user@` 회피 위해 `user@gmail.com` 대체 — 기존 미러서 `user@gmail.com` 으로 망가져 연락불가였던 버그 해소).
    - **잔여**: 내부 운영문서(CLAUDE.md·Harness.md·noteForHuman.md) 영·한은 범위 외(저가치). Issue.md 공개 재개 = 비공개 이슈 마커 적용 + 수동 리뷰 후 별도 결정.
* 사용자 결정 (2026-06-21, 폼 회수):
    - **Issue.md 공개 = 전체 그대로 공개** — redaction 없이 통째 공개. `publishable-policy.yml` exclude[] 에서 `Issue.md` 제거. sanitize+secret-scan 게이트 통과분만 미러(여전히 적용).
    - **내부 운영문서 영·한 = 함** — CLAUDE.md·Harness.md·noteForHuman.md 도 `X.md`(영)+`X_ko.md`(한) 페어 분리(범위 편입).
    - **이슈 종결 = 완료** — 아래 두 작업 반영·검증·미러 전파 완료(2026-06-21).
* 종결 결과 (2026-06-21, commit 8794169·dda74d7):
    - **Issue.md 공개 전환 완료**: `publishable-policy.yml` exclude[] 에서 `Issue.md` 제거 → 전체 공개. sanitize+secret-scan 게이트는 유지(통과분만 미러).
    - **내부 운영문서 영·한 완료**: CLAUDE.md·Harness.md·noteForHuman.md 각 `X.md`(영문 기본)+`X_ko.md`(한글) 페어 + 상단 상호링크 뱃지(`🌐 English | 한국어`).
    - **README_ko.md exclude 보정**(dda74d7): prj7 미러 전용 한글판을 forward `--delete` 로부터 보호(README.md 동일 제약).
    - 워킹트리 clean · origin/main 푸시 완료. 4개 본항목 + 사용자 결정 2건 전부 반영.

## Issue188: hub 렌더 포커스 복원 불완전 — 프로세스명↔앱명 불일치 시 Chrome 포커스 잔류 (등록: 2026-06-21, 해결: 2026-06-21, commit: f0c8be7) ✅
* 목적: Issue173 `_restore_focus` 가 앱명 기반 `tell application "<name>" to activate` 라 프로세스명↔앱명 불일치(VSCode 프로세스 "Code") 시 복원 실패 → Chrome 포커스 잔류. 사용자가 겪은 실제 focus-steal 잔존 원인.
* depends: Issue173
* 진행 결과 (2026-06-21, commit f0c8be7):
    - `plugins/fpm-core/hooks/fpm-browser-open.sh` `_restore_focus` 를 System Events 프로세스 도메인으로 통일 — `tell application "System Events" to tell process "$_prev_front" to set frontmost to true`. 캡처(name of first process)와 동일 도메인 → mismatch 제거.
    - 검증: VSCode("Code") frontmost 상태서 `-f false -r false` 호출 → BEFORE=Code, AFTER=Code 포커스 유지 확인.
    - 복잡도 단순 — plan/task/report 없음.

## Issue186: 폐쇄망(air-gapped) 설치 — 다운로드된 f-claude-plugins 로컬 설치 파라메터 (등록: 2026-06-21, 해결: 2026-06-21, commit: 1cc7ad8) ✅
* 목적: 인터넷 차단 환경에서 `sh/install.sh` SCAR 설치 시 GitHub 마켓(`claude plugin marketplace add <github-url>`) 접근 불가 → 미리 받아둔 f-claude-plugins(prj20) 로컬 사본을 마켓 소스로 쓰는 명시 파라메터 제공. 폐쇄망 설치 가능화.
* depends: Issue185
* 결과 (Walkthrough):
    - **`--local` 파라메터 신설**: `sh/install.sh` 인자 파싱을 `for arg` → `while + shift` 로 전환(값 동반 플래그 지원). `--local [경로]`·`--local=경로` 추가. 내부적으로 `FPM_MKT_REF` 채택. 우선순위 **CLI `--local` > env `FPM_MKT_REF` > 매니페스트 기본(GitHub)**.
    - **경로 자동 탐색**: 경로 생략 시 관례 후보(`<repo>/../f-claude-plugins`, `~/_git/__all/f-claude-plugins`, `~/_git/f-claude-plugins`, `./f-claude-plugins`) 순회 — 첫 `marketplace.json` 보유 디렉토리 채택.
    - **검증 가드 (fail-loud)**: 지정/탐색 경로에 `marketplace.json`(또는 `.claude-plugin/marketplace.json`) 부재 시 설치 중단 + 사전 다운로드 안내. 디렉토리 아님도 중단.
    - **INSTALL.md**: `# 폐쇄망(air-gapped) 설치` 섹션 추가 + SCAR 설치 단계(6번) 명시. (후속 i18n 패스로 영문 INSTALL.md + INSTALL_ko.md 분리됐으나 air-gapped 섹션 유지됨.)
    - **검증**: `bash -n` 구문 OK · `--help` 항목 표시 · 잘못된 경로 `--local /nonexistent` → fail-loud 중단 · AUTO 탐색 1st 후보(marketplace.json 부재) skip → 2nd `~/_git/__all/f-claude-plugins` 채택 격리 테스트 통과. (실제 네트워크 차단 E2E 는 미수행 — 코드 경로만 검증.)
    - **fpm 미러 전파**: 사용자 "지금 forward 전파" 선택 → `fpm-sync forward` (commit `1cc7ad8` 기준 v0.3.7 auto-bump) → fpm `6bfe7ef` 공개 origin push (`4c38057..6bfe7ef`, fast-forward). fpm INSTALL.md·install.sh `--local` 전파 확인.
    - 복잡도: 단순~중간 (install.sh 단일 파일 + INSTALL.md · plan/task/report 생략).
## Issue185: install.sh·check.sh·uninstall.sh → sh/ 이동 + SCAR 인벤토리 매니페스트화 (등록: 2026-06-21, 해결: 2026-06-21, commit: 63f9dc5) ✅
* 목적: 설치 페이로드를 `sh/`(CLAUDE.md "단일 SSOT 설치 페이로드") 한 곳으로 집약. 공개 명령 `bash sh/install.sh` 로 변경.
* 결과:
    - **이동**: `git mv` 로 3 스크립트 → `sh/` (추적 보존). REPO_DIR 자기탐지 `/..` 보정 — sh/ 하위에서 repo 루트 정확히 가리킴(`bash sh/check.sh` PASS 14 로 검증). `--clean` 의 uninstall 호출·usage·안내 문구 모두 `sh/` 경로화.
    - **SCAR 인벤토리(사전작업 흡수)**: `install_manifest.sh` 에 `FPM_SCAR_COMMANDS`(11)/`SKILLS`(3)/`AGENTS`(1)+`FPM_PLUGIN_SRC_REL_REPO` 선언(신규 SSOT — plugin.json 미열거). `check.sh #10` 선언↔소스 양방향 drift diff(양성·음성 테스트 통과). `uninstall.sh` fpm-core plugin 제거+`--no-scar`(marketplace 공유 보존).
    - **참조 동기화**: `INSTALL.md`·`noteForHuman.md` sh/ 경로화(forward 자동 미러). `fpm README.md`(prj7, sync 제외) 수동 편집 완료.
* 잔여: **fpm 미러 전파** — fpm-sync forward(rsync `--delete`)가 fpm 레포 루트 옛 사본 제거+sh/ 신규 생성 + fpm README 커밋. `fpm-sync` deploy 단계에서 일괄 처리.
* 후속: **Issue186(폐쇄망 설치) unblock** — `depends: Issue185` 해소, 착수 가능.

## Issue181: fpm-core SCAR 를 prj20 마켓플레이스 게시 + install.sh 마켓 경유 설치 (A안) — fg1 E2E (등록: 2026-06-20, 해결: 2026-06-21, commit: c5bc00e, cfe5ae8) ✅
* 목적: `install.sh`·등록 플러그인 어느 쪽도 `~/.claude` SCAR 를 설치 안 하는 gap 을 A안(플러그인 정식 게시)으로 해소. fpm-core 를 prj20(f-claude-plugins) 마켓에 게시, `fpm-sync` 가 게시 자동화, `install.sh` 가 마켓 경유 설치. fg1 원격 E2E 로 검증.
* plan: `_doc_work/plan/fpm-marketplace-install_plan.md`
* task: `_doc_work/tasks/fpm-marketplace-install_task.md`
* report: `_doc_work/report/fpm-marketplace-install_issue181_report.md`
* arch: `_doc_arch/fpm-sync-deploy.md`
* 결과 (Walkthrough):
    - **Phase 0~2 (선행 완료)**: R1 cross-repo git-subdir 지원·R2 헤드리스 `claude plugin` CLI 검증. `fpm-sync publish` 서브커맨드 + `install.sh` SCAR 설치 경로(기본 ON) 구현.
    - **Phase 3 게시**: 미커밋 hub 아이콘 절대 URL 화 + png 최적화를 `c5bc00e` 로 커밋(AUTOBUMP=0 더블 bump 회피). prj7(fpm) push `4415d92..612f5a1`. prj20 `fpm-sync publish --push` → marketplace.json fpm-core **v0.3.1** upsert + validate PASS + 커밋 `cfe5ae8` push. (deploy 재bump 회피 — 0.3.1 갓 bump·미push)
    - **Phase 4 fg1 E2E**: T4-1/T4-2(SCAR 삭제) 생략 — fg1 SCAR 이미 clean + 백업 3종 확정. `claude plugin marketplace add` + `install fpm-core@f-claude-plugins` → v0.3.1 enabled. skills(3)/commands(11)/agents(6)/hooks(10+) 플러그인 경유 실재 확인. GitHub-source 마켓 직접 install E2E 통과.
    - **검증**: prj7·prj20 local=remote HEAD 일치. 원격 marketplace.json·vendored plugin.json 모두 v0.3.1. fg1(claude 2.1.143, Linux) install 성공.
    - **후속**: fg1 fpm-core 유지(원복 안 함). prj20 origin URL `finfra` 소문자 → push 시 GitHub 리다이렉트 경고(무해, 기능 정상).
    - 복잡도: 복잡 (multi-repo·신규 서브커맨드·install 변경·원격 E2E → plan+task+report 전체 사이클).
## Issue184: hub Activity feed 헤더 한 줄 — title nowrap + 종 이모지 제거 (등록: 2026-06-21, 해결: 2026-06-21, commit: 1ea9b5a) ✅
* 목적: hub 우측 Activity feed 패널 헤더가 제목 "🔔 Activity feed" + count badge(300) + 버튼 4개를 한 줄에 못 담아 제목이 글자 단위로 줄바꿈되고 "300"이 아래 줄로 밀리는 레이아웃 깨짐 수정. 한 줄로 표시.
* 상세:
    - 원인: `services/hub/server.py` `.feed-title-label` CSS 에 `white-space: nowrap` 부재 → flex 자식이 최소폭까지 축소되며 제목 텍스트가 단어 단위 wrap.
    - 종 이모지 🔔 는 폭 절감 미미 — 진짜 원인은 nowrap 부재 (사용자 가설 보정).
* 구현 명세:
    - `services/hub/server.py:5666` — `.feed-title-label` 에 `white-space: nowrap` 추가 (핵심 수정).
    - `data/locales/{ko,en}.json:54` — `feed.title` 에서 🔔 제거 ("활동 피드" / "Activity feed").
    - live 서버(`services/hub`) 재시작·healthz 200 확인. `plugins/fpm-core/services/hub` 미러는 미반영 — 배포 시 fpm-sync 동기화.
    - 복잡도: 단순 (파일 3개·자명 → plan/task/report 생략).
## Issue183: dashboard 강제 종료 버그 — 한글/비ASCII window명이 검증 정규식에 막혀 kill_pane 400 (등록: 2026-06-21, 해결: 2026-06-21) ✅
* 목적: dashboard view "강제 종료" 버튼이 한글 window명(ex `_테스트`) dashboard 에서 항상 실패. `/control` kill_pane 핸들러의 window_name 검증 정규식이 ASCII 만 허용해 `tmux kill-window` 도달 전 400 으로 거부되던 버그 해소.
* 상세:
    - 대상(두 사본): `services/hub/server.py`(실행본) + `plugins/fpm-core/services/hub/server.py`(번들 SSOT)
    - 기존: `re.match(r'^[a-zA-Z0-9_.:-]+$', window_name)` → 한글 unmatch → 400 invalid_window_name
    - 수정: ASCII 화이트리스트 → 위험 메타문자 블랙리스트(제어문자·공백·셸 메타). 매치 시 거부(+ 길이 200 상한), 그 외(한글 포함) 통과. subprocess list 인자(shell=False)라 인젝션 위험 없고 tmux 타깃 파싱 보호만 유지
    - 별건(비버그): "정지" 403 pid not registered 는 수동 테스트 yaml(/register-pid 미호출) 한계 — 정상 `..board` 워크플로우엔 미발생
* 구현 명세:
    - 검증(서버 재시작 후 curl): 한글 가짜 window → `already_gone`(정규식 통과 확인), `bad;rm` → 400(보안 유지)
    - 복잡도: 단순 (2 사본·정규식 1줄)
    - commit: aab5eda

## Issue182: hub 🎯 이모지 아이콘 → fPm 프로젝트 로고(Finfra fox) 교체 (등록: 2026-06-20, 해결: 2026-06-20) ✅
* 목적: 신규 프로젝트 아이콘(`~/Desktop/_rsc/icons/fPm.png`, Finfra fox 로고)을 hub 곳곳의 🎯 이모지(favicon + 헤더 브랜딩) 자리에 반영. 일관된 브랜딩.
* 상세 (사용자 선택 = "전부 + 앱 아이콘 자산화"):
    - **자산화**: fPm.png 256² 리사이즈 → `plugins/fpm-core/services/hub/fpm-icon.png` + `services/hub/fpm-icon.png`(실행본 옆) 배치. 풀해상도 원본 `img/fPm.png`.
    - **서버 라우트**: 양 `server.py` do_GET 에 `GET /fpm-icon.png` 추가 — `os.path.dirname(__file__)/fpm-icon.png` 를 `image/png`, `Cache-Control: public, max-age=86400` 로 서빙.
    - **favicon 교체**: 🎯 인라인 SVG data URI → `<link rel="icon" href="/fpm-icon.png">` (host-relative, 원격 접근 시에도 hub 서버로 해석). server.py 4곳 + `fpm-hub-trigger.sh` 2곳.
    - **헤더 브랜딩**: `/hub` h1 `🎯📊 fPm Hub` → 로고 `<img>` + " fPm Hub". canonical 헤더 hub-link 버튼 `🎯📊` → `<img src="/fpm-icon.png">` (trigger.sh 2, ask-intercept.sh 1, ask-marker-detect.sh 1, fpm-hub.md 1).
    - **불변식 갱신**: fpm-hub.md 블록 불변식 (2) "Hub=🎯 단독" → "Hub=fPm 로고 img" (향후 agent 가 img→🎯 되돌림 차단).
* 구현 명세:
    - **SSOT drift 발견**: `~/.claude` 미러(라이브 hook)가 bundle(`plugins/fpm-core`)보다 앞서 있음(Issue152/153/158/172/173 적용, bundle 미반영). 라이브=`~/.claude` 이므로 아이콘 편집을 양쪽(bundle + ~/.claude)에 독립 적용. **bundle forward-sync 필요(별도 처리)** — 본 이슈 범위 외.
    - 검증: `ast.parse` PASS(양 server.py), `bash -n` PASS(hook 3종 ×2). 서버 재시작 후 `curl /fpm-icon.png`=HTTP 200 image/png 56499B, `/hub`=favicon + h1 img 서빙 확인. (브라우저 favicon 캐시 → 하드 리프레시 필요)
    - 자동 결정(triage 중간): plan/task 미생성. report 생략(검증 증거 본 이슈 인라인).
* commit: 3245d6b

## Issue180: Projects.md → projects/ 자동 동기화 — cdf lazy sync-on-use (등록: 2026-06-20, 해결: 2026-06-20) ✅
* 목적: `Projects.md`(SSOT) 편집 후 "동기화 해줘" 수동 프롬프트(`fpm-projects-sync`)를 잊으면 `projects/` 인덱스가 silently 낡아 `cdf` 가 어긋남. 사용자가 "언제·무엇으로 동기화?"를 매번 기억해야 하는 인지 부담 제거.
* 구현 명세:
    - **설계 전환(중요)**: 1차 후보였던 git pre-commit hook(Projects.md staged 감지)은 **무효** — `Projects.md` 와 `projects/` 모두 `.gitignore` 대상(로컬 전용 머신 상태). git 은 자연 트리거가 아님. → **lazy sync-on-use** 로 선회.
    - **fpm_function.sh `_pm_manager()`**: base_dir 확정 직후 mtime 가드 추가. `Projects.md -nt projects/.sync-stamp` 이면 `fpm-projects-sync --index-only` 1회 실행 + stamp touch. stamp 부재(첫 실행)도 `-nt` 참 → 1회 동기화. cdf 계열 모든 진입점이 `_pm_manager` 경유 → 사용 시점 항상 최신.
    - **fpm-projects-sync `--index-only` 플래그 신설**: `projects/` 인덱스(step 1/3)만 재생성. `.vscode`(타 repo)·iterm-bg(머신 로컬·gitignore)는 cdf 와 무관하므로 skip → lazy 경로 경량화. 수동 full 동기화는 기존대로.
    - **stamp**: `projects/.sync-stamp` — `projects/` 가 이미 gitignore 라 자동 무시(추가 .gitignore 불요).
    - **수동 경로 유지**: `fpm-projects-sync`(full) 명령은 그대로. lazy 는 "잊어도 되게" 보강이지 대체 아님(vi 편집·비대화 셸 대비).
    - **검증**: subshell 에서 ① stamp 부재+Projects.md touch → sync 발동·stamp 생성 ✅ ② Projects.md not newer → skip ✅ ③ 재 touch → stale 재감지 ✅ ④ `git check-ignore projects/.sync-stamp` ✅.
    - **부수 발견**: `projects/` 26개 파일이 gitignore 이전 레거시로 tracked 상태(현 이슈 범위 외, 별도 정리 후보).
## Issue179: hub 세션 출처 배지 회귀 — UserPromptSubmit 훅이 entrypoint 매 턴 clobber (등록: 2026-06-18, 해결: 2026-06-18) ✅
* depends: Issue177 (출처 배지 도입 — 본 이슈는 그 회귀 수정)
* 목적: Issue177 이 SessionStart 훅(register.sh)에 `CLAUDE_CODE_ENTRYPOINT` 캡처를 넣었으나, VSCode fWarrange 세션 2개가 hub 카드에 항상 ⌨️(터미널)로 표시됨. Issue177 fix 가 매 프롬프트마다 무효화되던 회귀.
* 구현 명세:
    - **root cause**: `UserPromptSubmit` 훅 `fpm-hub-session-topic.sh` 가 매 프롬프트마다 `/session/register` 를 caps=`{source:prompt, kind:live}`(entrypoint 없음)로 호출. 서버 merge 로직 `entry["capabilities"] = caps or existing` 은 비어있지 않은 caps 를 **replace** → SessionStart 훅이 심은 `entrypoint=claude-vscode` 를 첫 프롬프트에 덮어쓰고 이후 매 턴 terminal 로 회귀. (수동 POST 한 테스트 행만 entrypoint 보존되어 정상 → 회귀가 실제 세션에서만 발현)
    - **수정**: `plugins/fpm-core/hooks/fpm-hub-session-topic.sh` — register.sh 와 대칭으로 `ENTRY="${CLAUDE_CODE_ENTRYPOINT:-}"` 캡처 후 caps 에 `entrypoint` 동봉. 매 프롬프트 재등록이 올바른 출처를 carry → server 재시작·중간 합류 상황에도 robust(SessionStart 단독 의존 제거).
    - **배포**: repo SSOT(`plugins/fpm-core/hooks/`) → `~/.claude/hooks/` cp 동기 (IDENTICAL 확인).
    - **검증**: 현재 vscode 세션 + fWarrange 세션 2개 재등록 후 `/dashboards` JSON `origin=vscode` 확인. 기존 등록분은 다음 프롬프트 때 자동 self-heal.
## Issue178: hub 렌더 백그라운드 전용 열기 — Chromium open -g self-activate 깜빡임 제거 (등록: 2026-06-18, 해결: 2026-06-18, commit: b4a1bd3) ✅
* depends: Issue173 (chrome focus 탈취 trap 복원 — 본 이슈가 trap "전면화 후 복구" 자체를 제거)
* 목적: `browser_focus: false`(=`browser_open: background`) 여도 렌더 시 Chrome 이 잠깐 전면화됐다가 직전 앱으로 복원 → 타이핑 끊김. 원인은 Issue173 trap 이 "포커스 재탈환 보정"이지 "전면화 차단"이 아니었던 것.
* 구현 명세:
    - **root cause**: 자동 렌더는 `-r false`(탭 미재사용) → 항상 `_fallback_open` 의 `open -g -a "Google Chrome"`. Chromium 은 `open -g` 무시 self-activate → trap `_restore_focus` 가 직후 복원 = "전면화→복구" 깜빡임. (Firefox 는 `open -g` 존중하여 무증상)
    - **수정**: `plugins/fpm-core/hooks/fpm-browser-open.sh` — `_bg_open()` 신설. Chrome/Edge 가 실행 중이고 창 1개 이상이면 `open` 우회하고 AppleScript `make new tab`(activate 미호출)로 탭만 생성 → 전면화 자체 회피. 미실행·창0 은 `open -g` 폴백(어차피 1회 떠야 함). osascript 실패 시 `|| open -g` 안전망. `_fallback_open` 의 `focus != true` 분기가 `open -g` 대신 `_bg_open` 호출. Firefox 등 기타는 `open -g` 존중(무변경).
    - Issue173 `trap _restore_focus` 는 무해 no-op 안전망으로 유지.
* 검증: `bash -n` PASS / 포커스 frontmost BEFORE=AFTER=`firefox`(전면화 0, 이전 깜빡임 제거) / Chrome 탭에 렌더 URL 실제 생성 확인.
* 잔여(선택): 공개 미러 사본 `~/_git/__all/fpm/plugins/fpm-core/hooks/fpm-browser-open.sh` 미반영 — 차기 `fpm-sync deploy` 시 전파.

## Issue177: hub 활성 세션 카드에 출처(VSCode/터미널) 배지 + 클릭 동작 분기 (등록: 2026-06-18, 해결: 2026-06-18, commit: 9ae36f9) ✅
* 목적: hub 활성 세션 카드가 VSCode 확장 세션과 iTerm CLI(claude code) 세션을 구분하지 못함. 카드 클릭 시 출처 무관하게 `vscode://anthropic.claude-code/open?session=<sid>` URI 를 무조건 발사해 터미널 세션도 VSCode 로 잘못 재오픈됨. 출처 배지 표시 + 클릭 분기로 해결.
* plan: `_doc_work/plan/session-origin-badge_plan.md`
* task: `_doc_work/tasks/session-origin-badge_task.md`
* arch: `_doc_arch/hub_htm.md`
* 상세:
    - 구분 신호: 환경변수 `CLAUDE_CODE_ENTRYPOINT` (VSCode=`claude-vscode`, 터미널 CLI=`cli`). Claude Code 가 직접 세팅 → SessionStart 훅 env 로 전파됨(검증 완료). `TERM_PROGRAM` 은 VSCode 확장에서 빈 값이라 비권장.
    - 변경 3곳:
        - `plugins/fpm-core/hooks/fpm-hub-session-register.sh`: caps 에 `entrypoint=$CLAUDE_CODE_ENTRYPOINT` 추가 전송 (→ `~/.claude/hooks/` 배포본 동기화)
        - `services/hub/server.py` `_collect_live_sessions`: 등록 entry `capabilities.entrypoint` → 카드 result 에 `origin: "vscode"|"terminal"` 노출 (claude-vscode→vscode, 그 외→terminal)
        - 클라이언트 카드 렌더: `data-origin` + 배지(🆚 VSCode / ⌨️ 터미널) + 클릭 분기 — terminal 은 `openSession` 호출 안 하고 toast 표시
    - 클릭 분기로 `_handle_open_session` 무조건 VSCode 재오픈 버그 동시 제거
    - 터미널 세션 포커스는 불가(범위 외). 배지 표시 + 잘못된 재오픈 차단이 목표
* 검증:
    - `python3 ast.parse` server.py PASS, `bash -n` hook PASS
    - 기능 테스트: `/session/register` 2건(entrypoint=claude-vscode/cli) → `/dashboards` live_sessions origin 매핑 = vscode/terminal 정확 확인
* 잔여(선택): 기존 등록 세션은 구 훅으로 등록돼 entrypoint 없음(=terminal 표기) → 각 세션 재시작 시 정상화. plugin 배포 payload `plugins/fpm-core/services/hub/server.py` 는 이번 변경 미반영(기존부터 services/ 와 divergent) — fpm-sync 별도 배포 시 동기화.
## Issue176: fpm-sync 기본값을 양방향(sync)으로 — 인자 없이 실행 시 버전 게이트 자동 방향 (등록: 2026-06-18, 해결: 2026-06-18, commit: 9eec0f5) ✅
* 목적: 인자 없는 `fpm-sync.sh` 가 forward 단방향이라 fpm upstream 흡수를 놓칠 위험 → 기본값을 버전 게이트 자동 방향(sync)으로 변경.
* arch: `_doc_arch/fpm-sync-deploy.md`
* 상세:
    - `do_sync()` 신설: fpm `git show HEAD:VERSION` vs ___pm VERSION 비교 → fpm 앞서면 reverse 흡수(dry-run), 아니면 forward 반영
    - 기본 MODE `forward` → `sync`, dispatch `sync)` case 추가. forward/deploy/reverse/policy 명시 호출 불변
    - push/commit 자동 없음 유지 (forward=push X, reverse=working tree). 출고=deploy·흡수적용=reverse --apply 는 명시 호출 유지
* 검증: `bash -n` PASS + 방향 판정 4케이스(fpm앞섬→reverse, 동일/pm앞섬/비교불가→forward) 격리 통과

## Issue175: hub allowlist CIDR(서브넷) 지원 — exact-IP → ip_network 매칭 확장 (등록: 2026-06-15, 해결: 2026-06-16, commit: 332c340) ✅
* 목적: bind_host=0.0.0.0 원격 개방 시 source-IP allowlist 가 exact-IP 일치만 지원 → 서브넷 단위 허용(`192.168.0.0/24`) 불가. CIDR 의 올바른 자리는 allowlist (bind_host 는 단일 listen 인터페이스라 CIDR 자리 아님).
* 구현:
    - `services/hub/server.py`: `import ipaddress` + 전역 `ALLOWED_NETS`. `_load_server_allowlist()` → `(exact_ips, nets)` 튜플 반환 (Host 에 `/` → `ip_network(strict=False)`, 실패 skip+log). `_ip_allowed()` → 루프백/exact 후 `any(addr in net)` 멤버십 검사, invalid IP 안전 거부. startup 튜플 언팩 + 로그 CIDR 개수.
    - 신규 `services/hub/test_allowlist.py` — 12 케이스 전부 통과. 회귀: settings 테스트 10+17 통과.
    - `Servers.md`(gitignore, 로컬): Host 컬럼 CIDR 사용법 주석 추가.
* 잔여(선택): 실제 LAN 다기기 환경 1회 서브넷 허용 동작 확인.

## Issue174: fpm 버전이 ___pm 보다 앞설 때 검증된 변경을 ___pm 으로 흡수(upstream pull) — 버전 게이트 + 컴펌 필수 (등록: 2026-06-15, 해결: 2026-06-15, commit: 29c4167) ✅
* 목적: prj7(`~/_git/__all/fpm`)·fg1·기타 서버·GitHub bare 에서 fpm 공개 미러를 테스트한 결과(중요 코드·SCAR)를 ___pm(SRC) 로 역흡수. fpm 이 단방향 다운스트림이 아니라, bare 환경에서 검증된 변경이 fpm 버전을 먼저 올린 뒤 ___pm 에 반영되는 흐름. 목적은 ___pm 업데이트 시 fpm 과의 충돌 최소화.
* 상세:
    - 현재 `fpm-sync.sh reverse` 는 버전 무관 전체 트리 rsync(되돌리기 의미) — 버전 인식 없음
    - 신규 요구: **fpm VERSION > ___pm VERSION 일 때만** ___pm working tree 에 적용 (version-ahead gate)
    - **컴펌 필수**: dry-run 으로 적용 대상 diff 노출 → 사용자 동의 후에만 실제 적용 (`--apply`). 커밋은 사용자가 검토 후 직접 (reverse 와 동일 정책)
    - 동기화 대상: 중요 코드 + SCAR(`.claude/`, `plugins/fpm-core/`, `sh/` 등) — 정책 yml exclude/guard 그대로 준수, 개인정보 가드(fpm-guard.sh) 양방향 적용
    - SSOT 기준: VERSION 의 SSOT 는 ___pm 이나, 본 흐름에서는 fpm 이 일시적으로 앞설 수 있음 — 게이트가 이 역전을 명시 처리
* 구현 명세 (컴펌 확정 2026-06-15):
    - **Q1=reverse 통합**: 신규 모드 추가 없이 기존 `reverse` 에 버전 게이트 통합 (`reverse [--apply] [--force]`)
    - **Q2=경고 후 강제 허용**: 기본은 fpm VERSION > ___pm VERSION 일 때만 흡수, 미앞섬이면 `흡수 불필요` no-op 종료. `--force` 로 게이트 우회(순수 되돌리기)
    - **Q3=fpm 값으로 끌어올림**: 적용 시 전체 트리 rsync 가 VERSION+매니페스트도 fpm 값으로 정렬 (이후 deploy 충돌 최소화)
    - `ver_cmp` semver 헬퍼 추가 (단위 테스트 통과). fpm 버전은 `git show HEAD:VERSION` 직독(미커밋분 무시). dry-run/apply 양쪽 게이트 적용
    - 수정 파일: `scripts/fpm-sync.sh`(게이트+헬퍼+dispatcher), `.claude/skills/fpm-sync/SKILL.md`, `.claude/agents/fpm-sync.md`
* 검증 (2026-06-15):
    - `ver_cmp` 단위 테스트 6/6 PASS (0.1.18>0.1.17=1, 0.1.17<0.1.18=-1, 동일=0, 1.0.0>0.9.9, 0.2.0>0.1.99, semver 동일=0)
    - 게이트 실동작: 양버전 0.1.18(동일) → `reverse` 기본 `흡수 불필요` no-op 종료 확인 / `reverse --force` → 게이트 우회 dry-run 진행, 적용 대상 diff 노출(적용 안 함) 확인
    - SKILL.md·agent.md 게이트 문서 반영 확인
* 잔여(차기 사이클): 실제 fpm VERSION > ___pm VERSION 상황에서 1회 라이브 흡수 검증 — 현재 양버전 동일(0.1.18)이라 차기 deploy 사이클에서 수행

## Issue173: chrome focus 탈취 수정 — hub 렌더/폼 open 포커스 미탈취 (등록: 2026-06-15, 해결: 2026-06-15, commit: 877f4d4) ✅
* depends: gscar#Issue156 (글로벌 ~/.claude — 3 hook open 명령 helper 전환, commit fade008 ✅)
* 목적: `data/hub_setting.yml` `default_browser: chrome` 로 변경하니 hub 렌더·b모드 폼 open 시 포커스가 자꾸 Chrome 으로 이동. 기존 firefox 에서는 정상.
* 구현 명세:
    - **root cause**: Chrome 은 이미 실행 중일 때 URL/파일을 받으면 `open -g`(백그라운드) 플래그를 무시하고 self-activate. AppleScript `set URL of tab` 도 `doFocus=false` 여도 전면화. Firefox 는 `open -g` 존중 → 이 비대칭이 증상의 직접 원인. (재현: frontmost 캡처 before/after — firefox=Code 유지 ✓ / chrome=전면화 ✗)
    - **수정**: `plugins/fpm-core/hooks/fpm-browser-open.sh` — `focus != true` 면 open 직전 frontmost GUI 앱을 osascript 로 기억 → `trap _restore_focus EXIT` 으로 종료 시 재활성. fallback open / osascript reuse(탭재사용) / notfound 전 경로 커버. firefox 등 무해 no-op, 권한부재·앱명불일치 시 `|| true`.
    - **글로벌 연계(Issue156)**: 라이브 경로는 글로벌 ~/.claude hook 3종이 plain `open -g -a chrome` 생성 → 본 helper `-f false -r false` 경유로 전환(focus 복원 적용). `-r false`=렌더/폼 새 탭(Issue153 정합).
    - **검증**: helper `-f false -r false` (chrome) → BEFORE/AFTER 동일(iTerm2 유지, 미탈취) ✓. 4 파일 `bash -n` 통과. foreground(`-f true`)는 `open -a` 무변경.
    - **잔존(미작업)**: 플러그인 미러 카피(`plugins/fpm-core/hooks/fpm-hub-trigger.sh`·`fpm-ask-*.sh`)는 글로벌(Issue152/153) 대비 이미 stale — 본 fix 미반영. 마켓플레이스 배포 정합은 별도 sync 이슈. 단 helper 본체는 플러그인 경로(live) 라 즉시 유효.
## Issue171: browser_tab_reuse 재정의 — /hub 단일 탭 전용, ..show/..ask 렌더는 매번 새 탭 (등록: 2026-06-14, 해결: 2026-06-14, commit: e50c1c1) ✅
* arch: `_doc_arch/hub_setting.md`
* depends: gscar#hub-tab-reuse-split (글로벌 ~/.claude/Issue.md Issue153 — ✅ 완료 commit d814aa8)
* 목적: `browser_tab_reuse=true` 구 의미가 origin(:9876) 매칭이라 `/hub` + 모든 `/htm-doc` 렌더를 단일 탭에 덮어씀 → 렌더 히스토리를 탭별로 닫으며 검토 불가. 사용자 요구: 렌더는 매번 새 탭, `/hub` 모니터링만 단일 탭 재사용.
* Walkthrough:
    - **신 의미 확정**: `browser_tab_reuse=true` → `/hub` hub-link `target="fpm-hub"` 명명 탭 단일 재사용 / `false` → `target="_blank"`. 렌더(`..show`·`..ask`·자동 hub)는 값 무관 **항상 새 탭**.
    - **글로벌 구현(Issue153 d814aa8)**: hook `fpm-hub-trigger.sh` 가 `browser_tab_reuse` grep → `HUB_LINK_TARGET` env 주입(true=`fpm-hub`/else=`_blank`). canonical 헤더 템플릿(`commands/fpm-hub.md`)에 `{hub_target}` placeholder + "렌더 vs /hub 탭 정책" blockquote 추가. 렌더 HTM_OPEN_CMD 에서 reuse helper 치환 제거 → 항상 `open`/`open -g`.
    - **구 Issue162 폐기**: reuse helper 가 :9876 origin 매칭으로 모든 hub URL 을 한 탭에 collapse 하던 경로 제거.
    - **ask 폼 정합(Issue172 59e14c3)**: b모드 ask 도 동일 render open 경로 사용하므로 reuse helper 분기 동반 제거 완료.
    - **___pm 측(본 세션)**: `_doc_arch/hub_setting.md` browser_tab_reuse 섹션 + `data/hub_setting.yml` 주석의 🚧 [TODO] 마커를 구현완료(✅ d814aa8)로 해제.
    - **잔존(미작업, 영향 없음)**: `plugins/fpm-core/hooks/fpm-browser-open.sh` 는 렌더에서 분리됨 — `/hub` 직접 open(`fhub`)용으로만 잔존, 별도 편집 불필요.
## Issue169: hub 다국어 지원(i18n) — language 설정 + data/locales catalog + JS 런타임 t() (등록: 2026-06-14, 해결: 2026-06-14, commit: 9f46da9) ✅
* plan: `_doc_work/plan/localization_plan.md`
* task: `_doc_work/tasks/localization_task.md`
* arch: `_doc_arch/localization.md`
* 목적: hub UI 다국어 지원. ~7000줄 한국어 하드코딩 → 언어 전환 가능 구조. fpm 공개 미러 국제 사용자 대비. 지원 en/ko 2종, 차후 N개 확장.
* Walkthrough:
    - **번역 catalog 분리 파일** `data/locales/{en,ko}.json` (160키, 다른 언어권 기여자가 코드 무관 번역. 신규 언어=파일 복사+번역+`SUPPORTED`·schema 2줄)
    - **`services/hub/i18n.py`** — stdlib-only 로더(mtime 캐시) + `t(key,lang)`(en fallback) + `merged(lang)`
    - **`language` 설정** — `HUB_SETTING_DEFAULTS`/`SCHEMA`(select en/ko, basic 탭, apply=auto) + `data/hub_setting.yml`. 저장→페이지 reload 로 전환
    - **2경로 치환**: 서버 정적 `{T:key}` 정규식 1패스(`_handle_hub`) + JS 런타임 `t(key,vars)` `{var}` 보간(인라인 `window.__i18n` 주입 + `GET /api/i18n?lang=` 엔드포인트)
    - **전 영역 전환**: 설정모달·Project List(동적 포함)·status바·활성세션·대시보드·hub문서·활동피드·confirm/toast·설정 필드 comment(`_handle_get_settings` lang 번역) → hub 페이지 **렌더 한글 0**
    - **i18n 비대상**: 활동 피드 항목·세션 토픽·프로젝트명 등 런타임 데이터(실제 hook 이벤트·사용자 프롬프트)는 원문 보존
    - 검증: 설정 회귀 27 테스트 통과, 서버 restart 후 en/ko 라이브 전환 확인
    - SSOT `services/hub/` 편집. `plugins/fpm-core/` 미러는 fpm-sync 로 차후 전파
* 차후: 세션 SPA(`spa_*.py`)는 `/api/i18n` 연결 시 동일 패턴 적용 가능
## Issue172: b모드 ask 폼 file:// → :9876 hub URL — a모드 doc 과 탭 동작 정합 (등록: 2026-06-14, 해결: 2026-06-14, commit: 59e14c3(~/.claude)) ✅
* 목적: `..ask`(b모드) 폼이 `open file://` 로 직접 열려 :9876 origin 미매칭 → 탭재사용 helper 가 안 잡아 매 폼 새 탭 누적(사용자 이미지1=틀림). a모드 doc 은 `render_target:hub` → `/htm-doc?path=` :9876 URL 로 단일 탭(이미지2=맞음). 원인 = ask-intercept 에 render_target/reuse 라우팅 부재(grep 0건 vs hub-trigger 18건).
* depends: Issue171(같은 영역 — 새탭 재설계 시 동반 갱신), gscar(`~/.claude/hooks/fpm-ask-intercept.sh`)
* Walkthrough:
    - `~/.claude/hooks/fpm-ask-intercept.sh` — browser_focus 후 Issue162 탭재사용 helper 블록 + render host 산출 추가(hub-trigger L523~551 미러), python env 에 `RENDER_HOST` 전달, `hub_doc_url` 변수 추가, deny-reason step2 를 `file://` → `{open_cmd} "http://<host>:9876/htm-doc?path=<절대경로>"` 로 교체
    - 인프라 기존재 확인: `fpm-hub-doc-register`(Issue80)가 이미 mode b 폼을 register-doc → `/htm-doc?path=` 즉시 유효. helper `fpm-browser-open.sh` 가 `-m http://127.0.0.1:9876` match 로 기존 :9876 탭 덮어쓰기
    - 글로벌 변경(cwd≠~/.claude)이나 사용자가 폼에서 "즉시 수정" 명시 승인 → 즉시 적용
* 효과(1차): b모드 폼이 file:// → :9876 register-doc 경유 (원격/타기기 표시 가능, /tmp 경로 탈피)
* Issue153 정합(2차, prj3 Issue153 완료 d814aa8 후): ask-intercept 도 hub-trigger 와 동일하게 reuse helper 제거 → 렌더 폼 **항상 새 탭**(Issue153 — 하나씩 닫으며 검토), hub-link `target` 을 `__HUBTARGET__`(browser_tab_reuse=true→fpm-hub 명명탭 / false→_blank) 배선. 헤더 흐름 shell `_reuse`→`HUB_LINK_TARGET`→env→python `hub_link_target`→`.replace("__HUBTARGET__")`. deny-reason step2 문구도 "단일 탭 재사용" → "새 탭" 정정
* commit: `~/.claude` 59e14c3(1차 file://→:9876) + 2f11e7b(2차 Issue153 정합) + `___pm` Issue.md (본 항목)

## Issue170: hub 브라우저 자동 open 3옵션 통합 — browser_open 단일 키 (등록: 2026-06-14, 해결: 2026-06-14, commit: 14db483) ✅
* 목적: hub 렌더 브라우저 open 동작이 `render_target`(hub=open안함) × `browser_focus`(true=포커스탈취) 2축 조합으로 흩어져 모호한 조합("의도하지 않은 방식")이 발생. off/background/foreground 3옵션을 단일 키 `browser_open` 으로 통합.
* Walkthrough:
    - `data/hub_setting.yml` — `browser_open: background` 추가, `browser_focus` deprecated 주석 (commit 14db483)
    - `services/hub/server.py` — `HUB_SETTING_SCHEMA` 에 browser_open select 추가, browser_focus `deprecated:True` + 모달 폼 deprecated 시각 표시(흐림+라벨). **커밋 완료** — Issue169 종결 시 동반 커밋(commit 9f46da9)
    - `_doc_arch/hub_setting.md`·`hub_settings_ui.md` SSOT 미러 갱신 (git ignore, 로컬 전용)
    - hook 소비(off→open 생략 / background→`open -g` / foreground→`open` + browser_focus fallback): 글로벌 `~/.claude/Issue.md` **Issue152 완료**(commit 53221cd) — browser_open 3옵션 현재 동작
* 의미: `off`=자동 open 안 함(채팅 URL만) / `background`(기본)=포커스 미탈취 / `foreground`=포커스 탈취. `render_target` 은 URL 형식만 담당(직교)

## Issue168: hub ⚙️ 설정창 UI — 파일 열기 대신 인앱 3탭 모달 + 주석보존 yml 라이터 (등록: 2026-06-14, 해결: 2026-06-14, commit: a762bc7) ✅
* plan: `_doc_work/plan/hub-settings-ui_plan.md`
* task: `_doc_work/tasks/hub-settings-ui_task.md`
* arch: `_doc_arch/hub_settings_ui.md`
* 목적: 현재 hub 페이지 ⚙️ 버튼은 `/open-settings-yml` 로 `data/hub_setting.yml` 을 VSCode 파일로 연다. 사용자가 yml 문법·유효값·소비처(자동재로드/hook/restart)를 직접 외워야 함. 이를 hub 페이지 내 **3탭 모달 설정창**으로 전환하여 폼으로 편집하고, 저장 시 yml 을 주석 보존하며 갱신. raw 편집 경로는 모달 하단 "설정 파일 열기" 버튼으로 보존.
* 상세:
    - 키 14개를 3탭 분류 — 기본(브라우저·렌더 5키) / 세션관리(세션·피드·상한 8키) / 고급(네트워크 3키)
    - 적용방식 3종 배지 UI 명시: 🟢 자동(server.py mtime 재로드) / 🔵 다음턴(hook grep) / 🟠 restart(`bind_host`)
    - 신규 엔드포인트 `GET /api/settings`(현재값+schema) / `POST /api/settings`(검증→주석보존 기록)
    - 위험조합(`bind_host: 0.0.0.0` + `advertise_host` 생략) 저장 차단
    - 대상 단일 파일 `services/hub/server.py` (HTML/CSS/JS 인라인), 외부 yaml 라이브러리 미사용(stdlib-only 유지)
* 구현 명세:
    - `HUB_SETTING_SCHEMA` 상수(탭·위젯·유효값·적용방식·설명) — 본 문서 분류 SSOT 는 `_doc_arch/hub_settings_ui.md`
    - `_load_hub_setting_raw()` 전 키 파서(hook 키 포함) + `_write_hub_setting(payload)` 라인 in-place 치환(inline 주석 보존)·temp→`os.replace` 원자적 쓰기
    - 단위테스트 2종(`test_settings_loader.py`·`test_settings_writer.py`)
    - 기존 `/open-settings-yml`·`btn-settings` ID 유지(모달 하단 버튼 재사용)
    - ⚠️ browser_*·render_target·advertise_host 키는 글로벌 hook 소비 — server.py 는 값 기록 게이트키퍼일 뿐 키 의미 불변(글로벌 SCAR 가드 비위반)
* 검증: 단위테스트 27건(loader 10/writer 17) 통과 + 서버 재기동 라이브 라운드트립(card_limit 주석 보존)·위험조합 400 차단 + Playwright 3탭 시각 검증 + hover 즉시 풍선(배지 위쪽) 동작 확인. hub_setting.yml 무변경 원복
## Issue167: advertise_host 를 hub 렌더 HTML 헤더 endpoint 까지 전파 + `hook 미구현` 마커 정정 (등록: 2026-06-14, 해결: 2026-06-14, commit: 7fb699c) ✅
* depends: Issue153, Issue141
* 목적: prj57(jmDashboard) 의 "서버→브라우저 자동 갱신"을 ___pm hub 에 원격/타기기까지 적용하려 할 때, `advertise_host` 가 **채팅 htm-doc URL** 에만 반영되고 **렌더된 HTML 본문**에는 반영되지 않는 누락 발견. canonical 헤더(Issue132)의 `📁 open-project` · `🆚 open-session` · `🎯📊 hub-link` 세 endpoint 가 `http://127.0.0.1:9876` 하드코딩 → 원격 브라우저에서 헤더 버튼 전부 실패. `data/hub_setting.yml:22` 의 `hook 미구현🔧` 마커도 실제(부분 구현)와 불일치.
* 구현 명세 (완료):
    - `plugins/fpm-core/hooks/fpm-hub-trigger.sh` canonical_header 의 3 endpoint + hub-link href 를 placeholder `http://__HOST__:__PORT__` 로 치환 (양 블록: `..show` 수동 ~621/623/624 + 자동 hub 모드 ~768/770/771)
    - 두 렌더 블록 `.replace()` 체인에 `__HOST__→render_host`, `__PORT__→render_port` 추가
    - `HTM_OPEN_CMD` 는 host-local `open` 전용(127.0.0.1 정상) → 변경 제외
    - `data/hub_setting.yml` render_target 마커 정정 (Issue167 반영 명시)
    - 배포: bundle SSOT → 실행 사본 `~/.claude/hooks/fpm-hub-trigger.sh` cp 동기 (구버전이라 함께 최신화)
    - 검증: advertise_host=192.168.0.50 mock → 헤더 endpoint 가 192.168.0.50 으로 렌더 / advertise 미설정+bind 0.0.0.0 → 127.0.0.1 fallback (좀비 URL 가드 회귀 없음), `bash -n` 통과
## Issue166: hub 빈 live 세션 표시 토글 — live_session_show_empty (기본 숨김) (등록: 2026-06-13, 해결: 2026-06-13, commit: 9e44ceb) ✅
* 목적: hub 활성 세션 목록에 명령(프롬프트)을 한 번도 받지 않은 "시작도 안 한 세션"(카드에 `-` 로 표시되는 빈 live 세션)이 노출됨. VSCode 가 세션 종료 후에도 `claude` 프로세스를 살려두면 `live_pid` 생존(force_live)으로 계속 떠 카드가 `-` 행으로 도배된다. 사용자별로 보고 싶을 수도, 가리고 싶을 수도 있으므로 설정 토글을 추가하되 기본값은 숨김으로 한다.
* 구현 명세 (완료):
    - **`services/hub/server.py`**: `HUB_SETTING_DEFAULTS` 에 `live_session_show_empty: False` 추가. `_collect_live_sessions` 의 Issue136 dedup 루프에서 설정값 분기 — `false`(기본)=빈 live 세션 전체 skip / `true`=프로젝트당 최신 1개 표시(종전 Issue136 동작 유지). 빈 세션 판정 = `content_type=="live"` + title(ai-title·프롬프트 요약) 부재.
    - **`data/hub_setting.yml`** + **`data/hub_setting_org.yml`**(설치 템플릿): `live_session_show_empty: false` 키 추가. 신규 설치자도 기본 숨김.
    - **`_doc_arch/hub_setting.md`**(SSOT, 로컬전용): 키 설명 행 + 소비처 키 목록(`server.py`) 갱신.
    - 적용: 코드·기본값 변경이라 hub 서버 재시작 후 반영(flat 파서가 미등록 키 skip). 값 토글만은 mtime 재로드로 즉시 반영. 재시작·healthz `status: ok` 확인.
    - 검증: server.py AST 파싱 OK, flat 파서 `live_session_show_empty=False` 캐스팅 확인.

## Issue164: fpm 공개 미러 내용 기반 secret 가드 — gitleaks scan + 신규 디렉토리 게이트 (등록: 2026-06-13, 해결: 2026-06-13, commit: 3039c1a) ✅
* 목적: Issue163 에서 드러난 두 구조적 갭 차단. (1) `exclude[]`(파일 denylist)이라 신규 최상위 디렉토리가 자동 미러 포함(`resource/`·`keyboard-maestro/` 누락 원인). (2) `personal_guard` 가 경로 매칭 전용이라 in-content 시크릿(토큰·키·UUID)을 못 잡음.
* 구현 명세 (완료):
    - **fpm-secret-scan.sh** (신규): `gitleaks dir` 로 미러 반영 트리 내용 스캔. 검출 시 fail-loud abort (exit 0/1/2). `fpm-guard.sh` 결정성 패턴 동일.
    - **fpm-dir-gate.sh** (신규): TMP2 top-level 디렉토리 ∉ `mirror_dir_allow[]` → fail-closed abort. denylist 갭을 allowlist 로 보강.
    - **.gitleaks.toml** (신규): `useDefault` + 커스텀 `macos-hardware-uuid` 룰(대문자 hex — 소문자 세션 sid 와 구분, 저오탐) + sanitize placeholder·example 도메인 allowlist. IP/소문자 UUID 광역 룰은 오탐 폭주로 의도적 미도입(hub_setting exclude·sanitize 가 1차 담당, 본 스캔은 backstop).
    - **스캔 대상 = TMP2**(exclude 적용 fresh 스냅샷): TMP 직접 스캔은 제외될 사적 파일 오탐, DST 직접 스캔은 stale/untracked cruft 혼입 → forward 가 `rsync -a EXCLUDES TMP/ TMP2/` 로 미러 반영분과 동일 트리 생성 후 게이트.
    - `data/publishable-policy.yml`: `mirror_dir_allow[]`(10개 dir) 추가 + 가드 머신 3종 exclude self-등록(미러 비공개). `fpm-policy-lib.sh`: `MIRROR_DIR_ALLOW[]` 파서. `fpm-sync.sh do_forward`: 게이트 2종 통합 + `policy show` 4번째 키.
    - **적용 범위**: forward 단일 chokepoint(deploy 도 do_forward 호출 → push 커버). 별도 미러측 pre-push hook 불필요.
    - 검증: T1~T6(validate/파서/clean/leak/dir clean/신규 dir) 전부 통과 + end-to-end no-op forward(게이트 통과·DST 커밋·VERSION bump 부작용 0). baseline 실 공개 콘텐츠 0 leaks.
    - full-history scan 절차(공개 전환 직전 `gitleaks git`)는 `_doc_arch/publishable-policy.md`(로컬전용) 운영 섹션에 명시.
* depends: Issue163 (전제 충족)
* 후속 발견(저위험): fpm 미러에 `.vscode/settings.json` 이 stale tracked(exclude 추가 前 커밋분, rsync `--exclude` 가 기존 파일 미삭제). 내용은 peacock 색상·window.title 뿐 — 민감정보 없음. 정리 시 `git -C ~/_git/__all/fpm rm --cached .vscode/settings.json` + push (긴급도 낮음).

## Issue165: hub_setting 설치 기본값 템플릿화 — hub_setting_org.yml 분리 + install.sh 적용 + publishable 제외 (등록: 2026-06-13, 해결: 2026-06-13, commit: 60cfd05, mirror 9858879) ✅
* 목적: `data/hub_setting.yml` 이 개인 환경값(bind_host·advertise_host IP 등)을 담은 채 publishable exclude 누락으로 공개 미러 fpm 에 동기화됨. 신규 설치자는 원작자 환경값이 박힌 yml 을 받게 됨. 설치용 기본값 템플릿(default_browser: chrome·browser_tab_reuse: true)을 분리하고, install.sh 가 부재 시 복사, 개인 hub_setting.yml 은 미러 제외. Issue162 에서 chrome+탭재사용 채택했으므로 설치 기본값도 chrome.
* depends: Issue162
* 구현 명세 (완료):
    - 템플릿 `data/hub_setting_org.yml` 신설 — 개인값 제거(advertise_host=예시 192.168.1.5), default_browser: chrome·browser_tab_reuse: true 기본. 헤더에 "install 시 hub_setting.yml 자동 생성" 명시
    - `install.sh`: `place_org "data/hub_setting.yml" "data/hub_setting_org.yml"` 추가 (Servers_org 선례 동일 — 부재 복사·존재 보존, 멱등). 헤더 주석 갱신
    - `data/publishable-policy.yml` `exclude[]` 에 `data/hub_setting.yml` 추가 → 개인 설정 미러 제외, 템플릿만 공개 전파
    - 미러 잔존분 purge: rsync `--delete` 가 exclude 파일을 protect 하여 잔존하던 미러 hub_setting.yml(개인 IP) 제거 (미러 commit 9858879, push 대기)
* 검증 (통과): `bash -n install.sh`, place_org 멱등 시뮬(복사→보존), 템플릿 개인 IP 부재, exclude 등록, 미러 forward 결과(템플릿 포함·개인본 제외), GitHub 공개본 404(미노출)
* 결정 (폼 미응답 → 권장 기본값 채택): Q1=`data/hub_setting_org.yml`(Servers_org 선례 일치) / Q2=tracked 유지 + 미러 exclude만(설정 백업 보존)
* 후속: 미러 hub_setting.yml history 9커밋 잔존 — GitHub 미노출(404)·사설 IP 라 긴급도 낮음. fpm 공개 전환 시 Issue164 full-history scan 에서 처리

## Issue162: hub 렌더 브라우저 탭 재사용 — fpm-browser-open.sh helper + fhub CLI + hook 치환 (등록: 2026-06-13, 해결: 2026-06-13, commit: 42ac68a) ✅
* 목적: Firefox 는 hub 렌더 시 매번 새 탭을 생성하여 무한 누적(`/hub` 대시보드 + 응답별 htm-doc). Firefox 는 tab 제어 사전 부재로 재사용 불가, Chrome/Safari/Edge 는 AppleScript 로 기존 탭 재사용 가능. Keyboard Maestro 매크로 "fPm hub page Open" 의 탭-재사용 로직을 CLI/hook 공용 helper 로 포팅하여 탭 누적 제거 + iTerm 등 터미널에서도 동일 동작(`fhub`) 제공.
* 구현 명세 (완료):
    - 공용 helper `plugins/fpm-core/hooks/fpm-browser-open.sh` 신설 — 플래그 기반(`-a app -f focus -r reuse -m match <url>`, url 을 마지막 위치인자로 두어 hook `{open_cmd} "url"` 패턴과 직접 호환). chrome/edge=Chromium AppleScript(`using terms from` 으로 동적 앱명 컴파일), safari=current tab, firefox/reuse=false=`open` 폴백
    - iTerm 진입점 `sh/fpm_function.sh` 의 `fhub [url]` — KM 매크로 CLI 버전. default_browser 자동 적용(firefox→chrome 강제), match=origin(:9876)
    - `data/hub_setting.yml`: 신규 키 `browser_tab_reuse`(사용자 환경 기준 기본 true 채택)
    - hook 3개(`fpm-hub-trigger`·`fpm-ask-intercept`·`fpm-ask-marker-detect`) `HTM_OPEN_CMD` 빌드부 → `browser_tab_reuse=true` & chrome/safari/edge 면 helper 호출로 치환, 그 외 기존 `open -g -a` 폴백
    - `_doc_arch/hub_setting.md`(browser_tab_reuse 섹션 + Issue130 권장 철회), `noteForHuman.md`(브라우저 선택 근거 단락) 갱신
* 검증 (통과): `bash -n` 4파일 + `shellcheck` helper clean. 실측 — hub 탭 누적 2개 상태에서 helper/fhub 실행 후 새 탭 없이 재사용. hook `HTM_OPEN_CMD` 빌드 시뮬(chrome→helper 호출 / firefox→폴백). zsh `fhub` 정의·실행·exit 0
* 결정 기록 (hub form): Q1 범위 = 풀 완결 진행 / Q2 탭 정책 = **단일 탭 통합**(origin `:9876` prefix 매칭 → /hub 대시보드 + htm-doc?path=… 같은 탭 1개 덮어쓰기. 분리는 탭 잔존이라 누적 제거 목적에 부적합)
* 미적용 메모: Safari 실측(Apple Events 자동화 허용 사전 설정)은 코드 분기만 포함·런타임 미검증. `_doc_arch/hub_setting.md` 는 로컬전용(gitignore) — 커밋 미포함, 로컬 갱신만
## Issue163: fpm 공개 미러 사적 아티팩트 유출 차단 + 공개 전 보안 감사 (등록: 2026-06-13, 해결: 2026-06-13, commit: 1fcff13 + mirror 25d4c00) ✅
* 목적: `noteForHuman.md` 의 jm4 하드웨어 UUID, `resource/`(Apple 인증서·프로비저닝 프로파일·device UDID·CSR), `keyboard-maestro/`(머신 KM 매크로)가 공개 미러 fpm 으로 동기화되고 있었음. `publishable-policy.yml` exclude 가 `Servers.md`/`Projects.md` 만 막고 디렉토리 단위 사적 아티팩트는 누락(갭). sanitize 는 `host.local` 만 있고 bare 하드웨어 UUID 미커버. personal_guard 는 **경로 매칭 전용**이라 in-content UUID 차단 불가. fpm 공개 전환 예정이므로 (1) 향후 재유출 차단(예방) + (2) 미러 히스토리 purge + (3) 공개 전 전수 보안 감사 수행.
* 발견 경위: 사용자가 `noteForHuman.md:21` 의 `* jm4 : 769B52BA-...` 라인을 보고 "개인정보 sync 안 되는 것 확실한가?" 질의 → 전수 확인 중 사적 아티팩트 동기화 확정.
* 심각도 정정: Finfra/fpm 은 **현재 PRIVATE** (`isPrivate:true`, forks:0, stars:0) — UUID/인증서는 **공개 노출된 적 없음**(접근권자 한정, 외부 사본 0). 따라서 본 작업은 *공개 전환 전 클린업*이며, 회전 불가 식별자라도 자격증명 아님(.cer=공개키 → revoke 불필요).
* 구현 명세 (완료):
    - **예방 (___pm commit 1fcff13)**:
        - `noteForHuman.md` `## Mac UUID` 블록 삭제 (유출원 제거). install·glossary 등 나머지 공개 유지
        - `data/publishable-policy.yml` exclude += `resource/`·`keyboard-maestro/` (rsync denylist), sanitize += `{769B52BA-...→<mac-hw-uuid>}` 백스톱 (정책 파일 self-exclude 라 리터럴 비공개)
        - `data/hub_setting.yml` 주석 예시 IP `192.168.1.5`→`192.168.0.10` (공개 hygiene, 저위험)
    - **미러 히스토리 purge (force push, 불가역)**:
        - 백업 번들 2개 (`/tmp/fpm-mirror-pre-purge*.bundle`)
        - `git filter-repo --invert-paths --path resource/ --path keyboard-maestro/ --replace-text <UUID>` → 전 히스토리 제거 (39→37 커밋, 단독 커밋 prune)
        - origin 재연결 + `git push --force origin main` (`ee8885f`→`25d4c00`)
    - **공개 전 전수 보안 감사**: 트리+히스토리 스캔 — 개인경로(`$HOME`)·이름·이메일·private key·AWS/GitHub/Slack token·password 대입 **전부 0**. `Servers_org.md`/`Projects_org.md` = 의도된 예제(오탐). sanitize 정상 동작 확인.
* 검증 (통과): origin/main tip+전 히스토리 — UUID 0건 / `resource/`·`keyboard-maestro/` 0건 / 시크릿 0건. local↔origin 동기. 트리 secret 스캔 0.
* 결정 기록 (hub form): 제거 범위=`전부`(UUID+인증서+매크로), force push=`지금 실행`. 둘 다 사용자 승인(`ㅇㅇ`).
* 남은 한계: 예시 IP 는 미러 히스토리 3커밋에 잔존(주석·RFC1918 사설 → 저위험, 별도 purge 미실시). personal_guard 가 경로 전용인 구조적 한계는 후속 이슈 후보(내용 기반 가드/pre-push secret scan).
* 산출물: `_doc_work/z_htm/hub_htm_20260613_144403_a_uuid-leak.htm`, `..._183233_a_leak-remediation-done.htm`
## Issue161: fpm 클린 설치 — uninstall.sh + install.sh --clean (백업 후 제거) (등록: 2026-06-13, 해결: 2026-06-13, commit: 5281cc1) ✅
* 목적: fpm 설치 흔적(셸 rc 의 fpm 블록 + `~/.info/__pmBasePath.txt`)을 백업 후 제거하는 자동화가 없음. 클린 재설치 시 사용자가 zshrc 를 수동 편집해야 해 오류·누락 위험. `uninstall.sh` primitive + `install.sh --clean` 플래그로 멱등 클린 재설치를 제공하고, 기존 흔적은 `_doc_work/z_done/fpm-uninstall-<ts>/` 로 백업.
* 구현 명세 (완료):
    - `uninstall.sh` 신설 (REPO_DIR self-detect, `set -euo pipefail`):
        - zshrc·bashrc 의 fpm 블록(마커 `# >>> fpm functions >>>` ~ `# <<< fpm functions <<<`) 추출 백업 후 제거 (멱등 — 블록 없으면 skip)
        - `~/.info/__pmBasePath.txt` 백업 후 제거
        - 백업 위치: `${FPM_BACKUP_DIR:-$REPO_DIR/_doc_work/z_done}/fpm-uninstall-<YYYYMMDD_HHMMSS>/`, 런타임 `mkdir -p`
        - **보존(삭제 안 함)**: `projects/`·`Projects.md`·`Servers.md` (사용자 데이터) — 정리 범위 = 셸 아티팩트만 (form 결정)
    - `install.sh` 에 `--clean` 플래그 추가: 설치 전 `uninstall.sh` 호출(백업+제거) 후 정상 설치. `-h/--help` usage 출력 + 알 수 없는 인자 warn
    - `INSTALL.md` "제거" 섹션을 수동 안내 → `uninstall.sh` / `install.sh --clean` 자동화 안내로 갱신
    - 소스=___pm(prj1) → fpm-sync 로 공개 미러 fpm 전파 (install.sh·uninstall.sh·INSTALL.md 모두 root tracked = mirror 대상; `_doc_work/` 는 미러 제외 → 백업물 비공개)
* 검증 (통과): `bash -n` + shellcheck clean. 임시 HOME 라운드트립 — 설치(마커2)→uninstall(마커0·basepath제거·백업물 2개)→install --clean(마커2 중복없음)→재uninstall(no-op). repo 사용자 데이터 무변경 확인.
* 결정 기록 (hub form): 커맨드 형태=`uninstall.sh + install.sh --clean`, 정리 범위=`셸 아티팩트만`
* 목적: `/hub` 페이지의 활성 세션·dashboard·hub 문서 섹션이 항상 전체 펼침 고정이라 세션·문서가 많으면 스크롤 부담. 섹션별로 헤더만 남기고 접었다 펼 수 있는 토글 제공.
* 구현 명세 (완료):
    - 3개 섹션 헤더에 ▾/▸ 토글 버튼 (`.sec-toggle`, `data-sec`=섹션 id). 접힘 시 `section.sec-collapsed` 클래스로 grid 본문 + 부속 컨트롤(좀비 킬러·dashboard filter/sort·htm 필터/정리 버튼) 숨김, 제목·카운트 배지는 유지
    - 상태 localStorage `hubSecCollapsed` 영속 — 5초 reload() 재렌더는 grid innerHTML 만 교체하므로 section 클래스 보존(Issue104 expandedCards 동일 원리), 새로고침은 `applySecCollapse()` 재적용
    - `services/hub/server.py`(실행본) + `plugins/fpm-core/services/hub/server.py`(번들 미러) 동일 반영
* 검증: `ast.parse` 양 파일 PASS. 서버 재시작(pid 96491) 후 Playwright — 접기(grid·좀비 버튼 숨김, 글리프 ▸, localStorage 저장) PASS / 새로고침 영속 PASS / 재펼침 PASS / hub 문서 섹션(grid·필터·정리 버튼 숨김, 카운트 유지) PASS
* 자동 결정 (`/dev` 비대화): triage 단순(파일 2개·방법 자명) → plan/task/report 미생성. 영속 방식은 서버 설정 아닌 localStorage(브라우저별 UI 상태 — hub_setting.yml 부적합). dashboard 섹션은 검증 시점 0건으로 숨김 상태 — 동일 코드 경로라 별도 검증 생략. 재시작 중 pid 파일 부재로 구 인스턴스(11796) 직접 kill
## Issue159: hub 활성세션 카드 순서 적용 옵션 (등록: 2026-06-12, 해결: 2026-06-12, commit: 4573928, 28f7820) ✅
* 목적: `/hub` 활성 세션 목록이 `updated_age` 최근갱신순 고정 정렬이라 세션 활동마다 행·카드가 점프함. 정렬 방식을 `hub_setting.yml` 옵션으로 선택 가능하게 함.
* 구현 명세 (완료):
    - 신규 키 `live_session_order: updated|created|project` (`data/hub_setting.yml`, 기본 `updated`=현행 최근갱신순 / `created`=세션 시작 시각 오름차순 고정 / `project`=Projects.md 번호 오름차순 — 점프 방지). mtime 재로드 → 값 변경 시 restart 불요
    - `HUB_SETTING_DEFAULTS` 에 `"live_session_order": "updated"` 추가 (문자열 키 — bind_host 캐스팅 경로 재사용)
    - 세션 result dict 에 `created` 필드 추가. Issue136 빈 세션 dedup(updated_age 오름차순 전제) **이후** 재정렬 적용 — dedup 로직 불변
    - `project` 모드(28f7820 후속): `_load_projects_list()` path→id 매핑(`expanduser().rstrip("/")` — colors 매핑과 동일 정규화), 미등록 cwd 는 끝(10^9), 2차 키 created
    - 번들 미러 `plugins/fpm-core/services/hub/server.py` 동일 반영, `_doc_arch/hub_setting.md` 키 문서·소비처 표 갱신(gitignored — 로컬 반영)
* 검증: `ast.parse` 양 파일 PASS. 서버 재시작 후 `/dashboards` — updated 모드 age 오름차순 PASS, created 모드 created 오름차순 PASS(27세션), project 모드 prj1 ___pm→prj2 _doc→prj3 .claude 번호순 PASS(26세션), updated 복원 PASS
## Issue158: fpm 동기화를 sh → skill 기반 양방향(sync)으로 재설계 + deploy→sync 네이밍 통일 (등록: 2026-06-12, 해결: 2026-06-12, commit: 551d23f) ✅
* plan: `_doc_work/plan/fpm-sync-skill_plan.md` / task: `_doc_work/tasks/fpm-sync-skill_task.md`
* 결정: D1=B(Skill orchestrator + 결정성 sh 헬퍼), D2=B(publishable 흡수 → 단일 `fpm-sync` 스킬)
* 구현 명세 (완료):
    - **결정성 헬퍼 3종**: `scripts/fpm-policy-lib.sh`(정책 파서 yq→python3 fallback), `scripts/fpm-guard.sh`(개인정보 `personal_guard[]` abort, LLM 판단 금지), `scripts/fpm-sanitize.sh`(`sanitize[]` perl 치환, 스냅샷만)
    - **통합 dispatcher**: `scripts/fpm-sync.sh <forward|deploy|reverse|policy>` — hook·스킬 공용 진입점. 정책 YAML 직독, 헬퍼 조립. 구 `fpm-deploy.sh`(deploy)·`publishable.sh`(policy) 로직 흡수
    - **신규 스킬**: `.claude/skills/fpm-sync/` (정책 직독 + 4모드 오케스트레이션). 구 `publishable` 스킬 → deprecated shim, `fpm-deploy.sh` → deprecated shim
    - **네이밍 통일**: deploy(단방향)→sync(양방향) 수렴. 사후 grep 잔존은 shim 자신·exclude 엔트리·이슈 이력만(의도적)
    - **참조 갱신**: `agents/fpm-sync.md`(reverse 커맨드), `noteForHuman.md`, `data/publishable-policy.yml`(주석+exclude: sync 툴링 5 + skills/fpm-sync 내부화), `_doc_arch/publishable-policy.md`(B/B 아키텍처)
    - **검증**: 헬퍼 단위(guard exit/sanitize md5)·policy show/validate·reverse dry-run·shim 라우팅 PASS. post-commit hook e2e forward 성공(fpm 92a8d78 ← 551d23f), 개인정보 유출 0·sync 툴링 7종 제외 확인. hook 비대화 forward 경로 보존
    - 연관: Issue150/151(정책 문서화·YAML 구동), Issue149(sh SSOT)
## Issue157: ~/.claude(prj3) fpm SCAR 업데이트 → fpm-core 번들 동기화 (등록: 2026-06-10, 해결: 2026-06-10, commit: d0da1a6) ✅
* 목적: prj3(~/.claude) = fpm SCAR 정본. render_target(Issue141)·peacock 실색+emoji 스킴(Issue157)·dashboard 갱신이 번들(plugins/fpm-core)에 미반영(구버전)된 것을 동기화. 사용자 선택 = **이식성 보존 머지(B)** — 번들의 `${CLAUDE_PLUGIN_ROOT}` 경로 손실 없이 내용만 반영.
* 구현 명세 (완료):
    - **straight copy 8**: fpm-hub-trigger.sh(render_target +68줄), fpm-board-notify.sh, fpm-dashboard.md, fpm-dashboard-{queue-runner,runner,supervisor.test}.sh, fpm-dashboard-queue.sample.yaml, fpm-dashboard.md(agent)
    - **copy + 이식성 복원 2**: fpm-ask-intercept.sh, fpm-ask-marker-detect.sh — Issue157 peacock/emoji 내용 반영 후 `form_js` 경로를 `os.environ.get('CLAUDE_PLUGIN_ROOT', ...)` 로 복원
    - **부분 머지 1**: fpm-hub.md — emoji 스킴(🖥 세션/🎯 Hub)·`fpm-show.md` 참조 반영, server.py 줄은 번들 `${CLAUDE_PLUGIN_ROOT}` 유지
    - **SKIP 1**: fpm-dashboard-server.md — 경로/워딩만 차이(번들 이미 정확)
    - **신규 3**: commands/fpm-new-project.md, fpm-show.md, skills/fpm-pm-do/SKILL.md
* 검증: `bash -n` 전 .sh PASS, `yaml.safe_load` PASS, 최종 잔여 diff = 4 이식성 파일의 경로 라인만(의도)
* 발견·주의:
    - ⚠️ `fpm-new-project.md:7` 하드코딩 절대경로(`$HOME/_git/___pm/.claude/skills/new-project/SKILL.md`) — 재배포 비이식적. prj3 원본 그대로 동기, **별도 이슈로 교정 필요**
    - ⚠️ 작업 중 ~/.claude 가 **활성 편집됨**(Issue157 진행 — marker-detect 가 2→48줄로 증가). 무빙 타겟이라 재스냅샷으로 추격. prj3 Issue157 가 더 진행되면 재동기 필요
* 자동 결정: prj1#Issue157 번호는 prj3#Issue157(peacock)과 별개 네임스페이스

## Issue156: hub 서버 페이지(`/hub`·issue-tree·view 등) `<head>` 에 🎯 favicon 추가 (등록: 2026-06-10, 해결: 2026-06-10, commit: 8bee2b3) ✅
* 목적: Issue155 는 Claude 생성 `.htm`(hook 경유)만 favicon 부여 → 사용자가 보는 `http://127.0.0.1:9876/hub` 등 **server.py 직접 서빙 페이지**는 여전히 회색 globe 아이콘. server.py HTML head 에 동일 favicon 삽입하여 모든 hub 서버 페이지 탭에 🎯 표시.
* 구현 명세 (완료):
    - `services/hub/server.py`(실행본) + `plugins/fpm-core/services/hub/server.py`(번들) HTML head 4곳(issue-tree / view / `fPm Hub` 인덱스 / preview) `<meta charset="utf-8">` 직후 favicon `<link>` 삽입
    - favicon: `<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🎯</text></svg>">`
    - 4곳 중 3곳 viewport 선행(replace_all), 1곳 `<title>{esc(title)}</title>` 선행(단건) — 분기 처리
* 검증: `ast.parse` PASS(양 파일). `/fpm-dashboard-server restart`(pid 4059) 후 `curl /hub | grep rel="icon"` → favicon link 서빙 확인. 브라우저는 favicon 캐시 → 하드 리프레시 필요
* 자동 결정 (`/dev` 비대화): triage 단순 → plan/task 미생성. Issue155 후속(스코프 누락 보완). server.py 는 ~/.claude 미러 없음(실행 서버가 ___pm 직접)

## Issue148: dashboard 9개 시나리오 재현 키트 — `_doc_work/board/s1~s9/` (재현 프롬프트 + fixture) (등록: 2026-06-09, 해결: 2026-06-09, commit: 4cf3d91) ✅
* 목적: noteForHuman.md `## board (c모드)` 의 9개 dashboard 시나리오(L190~230)를 향후 재현·재테스트할 수 있도록 시나리오별 구현 프롬프트(트리거)와 부속 fixture(queue.yaml/dash.yaml/시계열 샘플)를 `_doc_work/board/s{N}/` 에 영속 보존. Issue147(시나리오 3 렌더 강화) 완성 후속.
* 구현 명세 (완료):
    - 폴더 `_doc_work/board/s1~s9/` (각 README.md + fixture) + 인덱스 `_doc_work/board/README.md` 생성. 총 24 파일, YAML 13종 전부 `yaml.safe_load` PASS.
    - 각 s{N}/README.md: 시나리오 정의 + 모드/위젯 구성 + 재현 트리거(`..board ...`) + 재현 절차 + fixture 표 + 검증 체크리스트 + 관련 문서
    - fixture 원천 추출(z_htm 검증 산출물): s1=build-1000 / s2=cap35v2(cross-prj) / s3=issue-tree-sample(Issue147) / s4=s4verify / s5=s5verify / s7=jm1-모니터링 / s9=scp-final-demo+scp-copy-jpc1. 신규 작성: s6=tasks-parallel(15 item·concurrency 3) / s8=schedule-tasks(infinite heartbeat) / s9 history.sample.tsv(시계열 15포인트)
    - noteForHuman.md L189(빈 `* `)에 board 재현 키트 참조 1줄 추가
    - 기존 dashboard agent/스키마 무수정 (재현 자료 보존 — 코드 변경 없음)
* 자동 결정 (`/dev` 비대화):
    - triage 단순 — 문서·fixture 생성, 설계 결정 없음 → plan/task/report 미생성
    - `_doc_work/` gitignore 대상 → board/ 는 git 미추적 **로컬 보존** (정책 준수, force add 안 함). 커밋은 추적 파일 noteForHuman.md 1줄(commit 4cf3d91) — 산출물 자체는 로컬 영속
    - 등록 Edit 부작용으로 Issue146 제목이 손상되어 종결 단계에서 복원
* 서브 이슈: **Issue148_1~Issue148_9** — `board/s1~s9` 각 시나리오 1:1 재현 검증·반영 (번호 순 1개씩 순차, 매 단계 사용자 의견 게이트)
* 공통 운영 규칙 (전 서브 이슈 적용):
    - 실행 단위: 시나리오 **1개씩 순차** (병렬 금지). 사이클: `s{N} 실행(..board) → 위젯 렌더·동작 관찰 → 사용자 피드백 → s{N}/README·fixture 반영 → 다음`
    - 사전 조건: `pm` tmux 세션 + hub 서버(`/dashboard-server status`)
    - 반영 대상: 각 `s{N}/README.md`(재현 절차·검증 체크리스트) + fixture(`*.dash.yaml`/`*.queue.yaml`)
    - 각 서브 완료 조건: 해당 s{N} 실행·검증·피드백 반영 + 사용자 승인. depends 공통: prj1#Issue148(완료 — 키트 생성)

## Issue148_1: s1 대량 순차 파일 생성 재현 검증·반영 (등록: 2026-06-09, 검증: 2026-06-09) ✅
* 목적: `board/s1/` (build-1000) 키트 실제 실행으로 동작 실증 + 의견 반영하여 README·fixture 업데이트
* 상세:
    - 트리거: `..board build-1000` (순수 모니터링 + synthetic worker 1초 sleep × 1000)
    - 검증: progress 0→1000 실시간 증가 · worker 완료 시 `status=done` 자가 종료 + 완료 alert · checklist(100/1000) · stop 시 worker_pid 회수
    - 반영: `s1/README.md` + `build-1000.dash.yaml`
* 검증 결과 (실가동 PASS 5/6): progress 0→191 단조 증가 · 위젯 5종 dynamic_eval · checklist "100개↑" done · runner SIGTERM→cleanup→worker 94286 자동 회수 · status running→stopped(graceful). worker 1000 완주(자가종료+alert)는 17분 소요라 stop 경로로 대체 검증(미관측). 의견 반영: `s1/README.md` monitor 재생성 블록에 `conditions.sh` 누락 보완. [완료 — 부모 Issue148 종결 시 완료 이동]

## Issue148_2: s2 크로스 프로젝트 위임 재현 검증·반영 (등록: 2026-06-09, 검증: 2026-06-09) ✅
* 목적: `board/s2/` (cap35v2 cross-prj DAG) 키트 실제 실행으로 동작 실증 + 의견 반영
* 상세:
    - 트리거: `..board queue 1:72,3:99,1:74@2` (큐 모드, supervisor+queue-runner 짝 기동)
    - 검증: i72 완료 전 i99/i74 `blocked` · 완료 시 ready 승격 + 각 prj worker lazy spawn(cross-prj) · `{{i72.result}}` 전파 · graph DAG SVG 렌더
    - 반영: `s2/README.md` + `cap35v2.{queue,dash}.yaml` (재실행 시 status 리셋 안내 검증)
* 검증 결과 (실가동 PASS 6/6): cross-prj `worker@prj1 %11`+`worker@prj3 %12(cwd ~/.claude)` lazy spawn · DAG i72→i99,i74 위상 · `{{i72.result}}` 전파 · 전 항목 done(state=done, 5:03) · 산출물 a.txt/b.txt(B3, prj3)/c.txt · dash 위젯 6종. 관찰: i72 sentinel 지연 재주입 1회(정상 크래시 복구). **레이아웃 결함 발견·반영**: queue-runner 생성 dash.yaml 이 graph 좁고 로그가 `type:text` 라 세로 폭발 → board/README "## dashboard 위젯 레이아웃 규칙" 명문화(graph width≥2·로그 type log+full+scroll·table width2) + queue-runner authoring 보강을 글로벌 `~/.claude/Issue.md` Issue140 등록. [완료 — 부모 Issue148 종결 시 완료 이동]

## Issue148_3: s3 Issue tree (의존 트리) 재현 검증·반영 (등록: 2026-06-09, 검증: 2026-06-09) ✅
* 목적: `board/s3/` (issue-tree-sample, Issue147 렌더 강화 산출) 키트 실제 실행으로 동작 실증 + 의견 반영
* 상세:
    - 트리거: `..board issue-tree-sample` 또는 `..show` (graph(tree) 위젯)
    - 검증: 노드 박스+의존 엣지(레이어드 DAG) · 노드별 progress 바 · 상태 아이콘(✅🔴⬜) · `current:true` glow · 구형 노드 하위호환
    - 반영: `s3/README.md` + `issue-tree-sample.dash.yaml`
* 검증 결과 (정적 렌더 PASS): tree 위젯 width:full 전폭, 노드 7개(Issue909~915) 중 6 done(progress 100)+Issue915 unresolved(progress 60, current glow), overall 6/7, badge 미해결. Issue147 강화 요소(노드별 progress·상태 아이콘·current·tint) 전부 렌더. s2 레이아웃 결함 무관(Issue147 fixture 양호). [완료 — 부모 Issue148 종결 시 완료 이동]

## Issue148_4: s4 nPTiR 파이프라인 재현 검증·반영 (등록: 2026-06-09, 검증: 2026-06-09) ✅
* 목적: `board/s4/` (s4verify 선형 큐) 키트 실제 실행으로 동작 실증 + 의견 반영
* 상세:
    - 트리거: `..board queue <nptir 6단계>` (선형 의존 DAG)
    - 검증: 6단계 선형 순차 진행(이전 done 후 다음 ready) · 각 단계 산출물 파일 생성 확인(checklist) · 단계별 progress
    - 반영: `s4/README.md` + `s4verify.{dash,queue}.yaml`
* 검증 결과 (실가동 PASS, 4:45): needs→plan→task→issue→impl→verify 6단계 **선형 순차**(concurrency 1, 각 done→다음 ready 승격) · 산출물 6개(`/tmp/dash-s4nptir/1_needs.md`~`6_verify.md`) 전부 생성 · state=done. worker@prj1 lazy spawn(%15) 동일 pane 순차.
* fixture 재작성 (**명세 불일치 수정**): 기존 `s4verify.queue.yaml` 이 s2 cap35v2 복제본(Issue72→73,74 fan-out)이라 nPTiR 6단계 미표현 → needs→plan→task→issue→impl→verify 선형(`on_fail: halt`, concurrency 1)으로 재작성. Issue148 키트 생성 시 z_htm 추출 오류.
* 발견 (board/README 룰 보강): **활성 큐(running)에서 dash 레이아웃 수동 보정 무의미** — queue-runner 가 매 iter dash.yaml 통째 재생성하여 width/type 덮어씀. s2 보정 유지된 건 done 상태(queue-runner 종료) 였기 때문. → 큐 모드는 완주 후 보정 또는 Issue140(queue-runner authoring) 근본 수정만 유효. [완료 — 부모 Issue148 종결 시 완료 이동]

## Issue148_5: s5 /goal 마일스톤 진행도 재현 검증·반영 (등록: 2026-06-09, 검증: 2026-06-10) ✅
* 목적: `board/s5/` (s5verify 마일스톤 큐) 키트 실제 실행으로 동작 실증 + 의견 반영
* 상세:
    - 트리거: `..board queue <goal-name>` (마일스톤 의존 DAG)
    - 검증: 마일스톤 의존 graph SVG · 마일스톤별 progress 독립 추적 · 예상 vs 실제 소요시간(`started_at`/`ended_at`) table
    - 반영: `s5/README.md` + `s5verify.{dash,queue}.yaml`
* 검증 결과 (실가동 PASS, 2:41): decompose→m1→m2→m3 마일스톤 **선형 순차**(concurrency 1) · 산출물 4개(`/tmp/dash-s5goal/0_decompose.md`~`3_m3.md`) · 예상 vs 실제 소요 table(decompose 0:30·m1 0:09·m2 0:29·m3 0:30) · state=done. 완주 후 dash 보정(graph w2·table w2·log full).
* fixture 재작성 (**명세 불일치 수정, s4 와 동일 유형**): 기존 `s5verify.queue.yaml` 이 합성 위상검증 큐(a/b/c/d)라 마일스톤 미표현 → decompose→m1→m2→m3 선형으로 재작성. [완료 — 부모 Issue148 종결 시 완료 이동]

## Issue148_6: s6 Task 병렬 관리 재현 검증·반영 (등록: 2026-06-09, 검증: 2026-06-10) ✅
* 목적: `board/s6/` (tasks-parallel, 신규 fixture) 키트 실제 실행으로 동작 실증 + 의견 반영
* 상세:
    - 트리거: `..board queue <items>@3` (15 독립 item, concurrency 3)
    - 검증: 동시 running ≤ 3 유지 · 완료 시 즉시 다음 ready 디스패치(순환) · badge(running 비율) · table(task별 소요시간) · prj 1/3 분산 실 병렬 관찰
    - 반영: `s6/README.md` + `tasks-parallel.queue.yaml`
* 검증 결과 (실가동 PASS): 15 item 전부 done(state=done), 산출물 15개(`/tmp/dash-s6/t01~t15.txt`) · 동시 running 상한 3 위반 없음 · done→다음 ready 순환 · worker prj별 lazy spawn(prj1 %21·prj3 %22). 완주 후 dash 보정(graph w2·table w2·log full).
* 발견·반영 (**concurrency 실효 = prj 종수**): 큐 모드는 prj당 worker pane 1개 → 실 동시 running 상한 = min(concurrency, prj 종수). 초판 fixture prj 1/3 **2종**이라 실측 동시 running 최대 2(3 아님) → fixture 를 **prj 1/3/0 3종 순환**으로 보강(동시 3 가능) + s6/README 정정. [완료 — 부모 Issue148 종결 시 완료 이동]

## Issue148_7: s7 주기적 모니터링 재현 검증·반영 (등록: 2026-06-09, 검증: 2026-06-10) ✅
* 목적: `board/s7/` (jm1-모니터링 골격) 키트 실제 실행으로 동작 실증 + 의견 반영
* 상세:
    - 트리거: `..board monitor-health` (infinite heartbeat, worker_pid 미설정)
    - 검증: interval 마다 헬스 지표 갱신 · 실행 결과·시각 로그 누적(pane) · 마지막 상태 badge · 완료 폴러 생략 · stop/kill 로만 정지
    - 반영: `s7/README.md` + `monitor-health.dash.yaml`(jm1 골격 치환) + monitor 스크립트 재생성법
* 검증 결과 (실가동 PASS): infinite heartbeat — status running **지속 유지**(runner 50272 alive) · 10s 주기 헬스 갱신(disk 78%·proc·load·lastcheck) · 누적 로그(health_log width full, 3줄+) · worker_pid 미설정 = 완료 폴러 생략. 신규 헬스체크 dash 작성(`board/s7/health-monitor.dash.yaml`) + monitor 6종(disk/proc/load/lastcheck/runner_status/healthlog).
* 발견 (**글로벌 Issue142 등록**): 1차 가동에서 `worker_pid: null` 명시 → runner 가 `.get('worker_pid','')` 로 `None`("None") 읽어 `kill -0 None` 실패 → 첫 iter 후 즉시 `status=done` (infinite heartbeat 깨짐). **worker_pid 키 생략**으로 우회·정상화. runner 템플릿 None/null 정규화 필요 → `~/.claude/Issue.md` Issue142. board/s7 README 에 "키 생략 필수, null 명시 금지" 명문화. [완료 — 부모 Issue148 종결 시 완료 이동]

## Issue148_8: s8 정기 작업 스케줄 재현 검증·반영 (등록: 2026-06-09, 검증: 2026-06-10) ✅
* 목적: `board/s8/` (schedule-tasks, 신규 fixture, Issue118 일원화) 키트 실제 실행으로 동작 실증 + 의견 반영
* 상세:
    - 트리거: `..board schedule-tasks` (infinite heartbeat, 단일 interval)
    - 검증: table(작업별 주기/마지막완료/다음예정/상태) · interval 마다 due 판정 → due 작업 실행 + 다음예정 갱신 · crontab 미사용 · 항목별 상이 주기 시 별도 window 안내
    - 반영: `s8/README.md` + `schedule-tasks.dash.yaml` + monitor 스크립트(due 판정 로직)
* 검증 결과 (실가동 PASS): infinite heartbeat — status running 유지(runner 42520 alive) · table(일일/주간/월간 작업별 주기·마지막완료·다음예정·due 상태, width full) · last_status·next_run(다음 일일 브리핑 14시간 후 산출) · crontab 미사용. monitor 4종(schedule due 판정/last_status/next_run/runner_status).
* 반영 (s7 교훈 일괄 적용): fixture 의 `worker_pid: null` 제거(Issue142), `runner_status` dynamic_eval `$MY_PID`→`runner_status.sh`(dash pid 읽기), table `width: full`, interval 600→10(데모). [완료 — 부모 Issue148 종결 시 완료 이동]

## Issue148_9: s9 대용량 전송 + SVG 시계열 재현 검증·반영 (등록: 2026-06-09, 검증: 2026-06-10) ✅
* 목적: `board/s9/` (scp-final-demo + history.sample.tsv) 키트 실제 실행으로 동작 실증 + 의견 반영
* 상세:
    - 트리거: `..board scp-<dest>` (순수 모니터링 interval 15s + scp watcher)
    - 검증: pie 도넛(진행률 순간값) + 전송량 line + 파일갯수 chart SVG · history.tsv 1줄/폴 append(단일 writer) · injector chart dict atomic 주입(race 없음) · 속도(GB/min)·ETA · watcher 자가 종료 · 포인트<2 fallback
    - 반영: `s9/README.md` + `scp-final-demo.dash.yaml` + `history.sample.tsv` + injector 스크립트
* 검증 결과 (정적 데모 렌더 PASS): 실 scp(원격 호스트) 불필요 — 완성형 데모 `scp-final-demo.dash.yaml` 정적 렌더. chart dict 유효(`yaml.safe_load`) — pie 진행률(순간값, w1) + 전송량 line(40pt·ymax116·GB, w2) + 파일갯수 chart(40pt·ymax8·개, w2) + checklist + table(파일 8개, w2). /view 200, SVG 라인+도넛 렌더. **의미 중복 회피**(pie 순간 + line 시계열) 명세 충족. width 힌트 내장(완성 데모라 s2 레이아웃 문제 없음). history.sample.tsv·injector 는 실 scp 재현용(README).
* fixture 양호 (s4·s5 와 달리 재작성 불필요 — 완성형 데모로 추출됨). [완료 — 부모 Issue148 종결 시 완료 이동]

## Issue155: hub 렌더 HTML `<head>` 에 🎯 이모지 SVG favicon 추가 (등록: 2026-06-10, 해결: 2026-06-10, commit: 4f206b3) ✅
* 목적: hub 자동 렌더 `.htm` 문서에 favicon 이 없어 Firefox 탭이 기본 회색 문서 아이콘으로 표시됨. 별도 `.ico` 파일·네트워크 요청 없이 인라인 SVG data URI 로 🎯 이모지 탭 아이콘을 부여하여 hub 문서 탭을 시각적으로 식별 가능하게 함.
* 구현 명세 (완료):
    - `fpm-hub-trigger.sh` a모드(`..show`)·자동 모드 2곳 `<head>` 지시 문자열의 `viewport` 와 `<title>` 사이에 favicon `<link>` 주입 지시 삽입
    - `fpm-hub.md` 템플릿 요구사항 doc 에 favicon 항목(Issue155) 추가
    - favicon: `<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🎯</text></svg>">` — SVG 속성 작은따옴표라 외곽 `href="..."` 큰따옴표와 무충돌
    - 런타임 미러 동시 갱신: `~/.claude/hooks/fpm-hub-trigger.sh`(cp, 편집전 identical) + `~/.claude/commands/fpm-hub.md`(동일 Edit, 39B 차이 보존)
* 검증: `bash -n` PASS(번들+미러). hook 런타임 실행(auto-mode payload) → 출력 additionalContext 에 favicon 지시 1회 정상 emit, JSON 디코드 시 `<link rel="icon" ...>` well-formed 확인
* 자동 결정 (`/dev` 비대화): triage 단순(자명·소규모) → plan/task 미생성. 런타임 미러는 변경 즉시 적용 위해 lockstep 동기(기존 fpm-core 번들↔~/.claude 운영 패턴)
* 복구 기록: 편집 도중 외부 수정으로 `중요/일반/선택/완료` 헤더가 Issue148 앞으로 이동(구조 깨짐) → 헤더 블록을 Issue148 뒤 원위치로 복구 후 정상 종결

## Issue153: `data/hub_setting.yml` render_target·advertise_host 키 신설 — yml 한 줄로 모든 ..show hub 경유 표시 SSOT (등록: 2026-06-10, 해결: 2026-06-10, commit: 4fe1957) ✅
* 목적: yml **한 줄 셋팅으로 모든 `..show`(+자동 hub 모드)를 hub 서버 경유로 표시**하도록 전환하는 데이터 키를 `data/hub_setting.yml`(렌더 정책 SSOT)에 추가. 개별 SCAR 수정 없이 단일 hook(`fpm-hub-trigger.sh`)이 이 키를 grep 하여 모든 렌더에 일괄 적용. 본 이슈 스코프 = **키 신설(데이터 자리 선점)**. 실제 분기 로직은 hook → 글로벌 Issue141(차후, 같이 되면 좋음).
* 상세:
    - `data/hub_setting.yml` 에 키 추가 (주석 포함):
        - `render_target`: `local-open`(기본, 현행 file:// 직접 open) / `hub`(hub 서버 경유 `http://<advertise_host>:9876/view?path=<절대경로>` — 로컬·원격·타 기기 모두 hub 한 곳 통해 도달) / `both`
        - `advertise_host`: `hub`|`both` 모드에서 URL 에 박을 호스트(LAN IP·도메인). **optional** — 생략 시 `bind_host` 값으로 fallback. `bind_host: 0.0.0.0` 이어야 원격 실효
    - **키 적용 규칙 (사용자 결정 — 후속 보강, advertise 라인 주석화)**: `render_target: local-open` → advertise_host·bind_host 둘 다 생략 가능(URL 미사용). `render_target: hub|both` → advertise_host 명시 시 그 값, 생략 시 bind_host fallback. ⚠️ 생략 + `bind_host: 0.0.0.0` 금지(URL=`http://0.0.0.0` 접속 불가) → 0.0.0.0 개방 시 advertise_host 구체값 명시
    - 기존 `default_browser`·`browser_focus`·`bind_host` 와 같은 렌더 정책 계열로 배치
    - **bind_host 와 직교**: render_target=출력 경로(hook 소비) / bind_host=수신 게이트(server.py 소비). 별개 진행
    - **키 상세 문서 분리(후속)**: `hub_setting.yml` 본문은 키별 한 줄 요약 주석만 유지, 전체 키 레퍼런스(소비처·규칙·금지조합)는 `_doc_arch/hub_setting.md` SSOT 로 분리
* 구현 명세:
    - `server.py` 미사용 (hook 전용 키) — `bind_host` 처럼 주석에 소비처(`~/.claude/hooks/fpm-hub-trigger.sh`) + 글로벌 Issue141 명시
    - 인프라 재확인 완료: `services/hub/server.py` `/view`·`/htm-doc` 라우트, `_path_ok` confinement, `bind_host` 0.0.0.0, IP allowlist 이미 존재 → 신규는 키(본 이슈) + 글로벌 hook 분기(Issue141)뿐
    - 키 추가 완료. 기본값 `local-open` 유지 — 동작 무변경, `hub` 전환 시 hook(글로벌 Issue141) 구현 후 실효
    - 분석 문서: `_doc_work/z_htm/hub_htm_20260610_175702_a_remote-render-setting.htm`, `hub_htm_20260610_182717_a_render-target-mechanism.htm`

## Issue154: fpm 설치·함수 bash 호환 포팅 — zsh/bash 양쪽 지원 (등록: 2026-06-10, 해결: 2026-06-10, commit: 0da9a26) ✅
* 목적: 설치 프로세스(`install.sh`)가 `~/.zshrc` 만 하드코딩하고, 네비게이션 함수(`sh/fpm_function.sh`)에 zsh 전용 문법(`$match`·1-based 배열·`${=}`)이 다수라 bash 로그인 셸에서 fpm 이 동작하지 않음. 양쪽 셸 지원으로 포팅.
* depends: (없음)
* 상세:
    - `install.sh`: `~/.zshrc` 단일 하드코딩 → 로그인 셸(`$SHELL`) 기준 rc 선택 + 반대편 rc 존재 시 추가(평소 zsh / 스크립트 bash 이중 사용 커버). `fpm.sh` 부트스트랩이 이미 셸 분기하므로 동일 source 라인이 양쪽 동작.
    - `sh/fpm_function.sh`: zsh 전용 문법 셸 분기 처리
        - `${match[n]}`(regex 결과) 4곳 → `_fpm_rematch` 헬퍼 신설(zsh `$match` / bash `$BASH_REMATCH` 통합, `$_M1/$_M2` 노출)
        - `${=WIN_ORDER}`(word-split) → 셸 분기(zsh `eval '(${=..})'` 로 bash 파싱 격리 / bash 무따옴표 IFS split)
        - sshf 다중 서버 1-based 배열 → `lo/hi` 인덱스 통합(zsh lo=1 / bash lo=0)
        - cdft 기타 배열(PROJ_PATHS·PANE_MAP·FOUND_TARGETS)은 명시 1-base 인덱스(0-index 미접근) → bash sparse array 로 동작, 수정 불필요
        - 예외 `chpwd`: zsh 전용 디렉토리 훅 — bash 자동 호출 안 됨(함수 정의만 존재, 주석 명시)
* 구현 명세 (완료):
    - 헬퍼 `_fpm_rematch <str> <regex>` → 매치 시 `$_M1 $_M2`(최대 2그룹), 비매치 return 1
    - 검증: syntax 3셸(bash 5.2 / zsh / bash 3.2 시스템) `-n` PASS · 파싱 단위 18/18 PASS(rematch 범위·@N·비매치 / cdf 범위확장·단일 / sshf 인덱싱 × 3셸) · install.sh rc선택 4케이스 + 멱등 PASS(임시 HOME 격리)
    - 분석·결과 문서: `_doc_work/z_htm/hub_htm_20260610_174900_a_shell-detect.htm`(감지 방법), `hub_htm_20260610_180245_a_bash-port-done.htm`(검증 결과)
    - triage 중간(2파일·셸 분기 설계 결정) — 분석 HTML 보존으로 report 대체
    - 사용자 결정(Mode B 폼): 적용 범위 = **완전 포팅**

## Issue152: dashboard 운영 정책 YAML 구동 — `data/board_policy.yml` SSOT + SCAR wiring (등록: 2026-06-09, 해결: 2026-06-09, commit: 86a633e, 300d87b) ✅
* 목적: Mode C(dashboard) 운영 상수(갱신 주기·견고성 임계·sentinel 경로)가 글로벌 SCAR 스크립트 3종에 하드코딩되어 있어, 프로젝트 단위 튜닝이 불가하고 변경 시 글로벌 SCAR 수정이 필요. hub_setting.yml(서버측)의 dashboard 짝으로 `data/board_policy.yml`(클라이언트측 운영 상수 SSOT)을 신설하고, SCAR 스크립트가 이를 읽도록 wiring. 우선순위 `env > board_policy.yml > 스크립트 기본값`.
* 구현 명세 (완료):
    - `data/board_policy.yml` 신규 (___pm 86a633e) — flat key:value 8종(`interval_default·interval_active·interval_idle_supervisor·interval_idle_runner·max_attempts·nosent_strikes·stuck_secs·sentinel_base`). hub_setting.yml 동일 철학(stdlib grep 파싱).
    - SCAR 스크립트 3종에 정책 로더 `_bp()` + `BOARD_POLICY` 경로(`${FPM_BASE:-$HOME/_git/___pm}/data/board_policy.yml`) 추가 (~/.claude 300d87b):
        - `agents/fpm-dashboard-supervisor.sh` — INTERVAL_ACTIVE/INTERVAL_IDLE/MAX_ATTEMPTS/NOSENT_STRIKES/STUCK_SECS/SENTINEL_DIR(base)
        - `agents/fpm-dashboard-runner.sh` — INTERVAL
        - `agents/fpm-dashboard-queue-runner.sh` — INTERVAL_ACTIVE/INTERVAL_IDLE
    - `_doc_arch/dashboard.md` — `## 운영 정책 (board_policy.yml)` 섹션(SSOT·우선순위·key↔상수 매핑표) + 가드박스 연관 SCAR 에 board_policy.yml 추가 + 이력 + 미externalize 항목(poller 30s/6h·send_retry `/3`) 🚧 TODO 마커.
    - env-override 패턴(`${VAR:-...}`) 보존 — 기존 동작 회귀 없음(정책 부재 시 기본값 동일).
* 검증 결과:
    - `bash -n` 3/3 PASS (supervisor/runner/queue-runner)
    - `_bp` 기능: 정책값 읽기 8/8 정확, 미존재 key→fallback, 정책파일 부재→fallback
    - 정책 구동 증명: 임시정책(interval_active=7, stuck_secs=1234) → 반영 확인 (기본값 무시)
    - 우선순위: env(99) > 정책(7) > 기본(3) 확정
    - 실 스크립트 상수해석: supervisor 로더~상수 블록 source → INTERVAL_ACTIVE=3/INTERVAL_IDLE=20/MAX_ATTEMPTS=2/NOSENT_STRIKES=10/STUCK_SECS=600, SENTINEL_DIR=/tmp/___pm/<sid>.sentinel
* 자동 결정 (`/dev` 비대화 + SCAR 가드 폼 응답 "즉시 수정 ___pm 오너"):
    - dashboard.md 는 글로벌 SCAR — cwd≠~/.claude 이나 ___pm 이 hub/dashboard 상시 운영 주체(Issue45)이므로 ___pm Issue.md 등록 + 즉시 수정 (b모드 폼 확인 완료).
    - triage 복잡(5 파일·정책 SSOT 계약) — scope 명확하여 report 생략, 이슈 + dashboard.md 이력으로 갈음.
    - inert key 방지 — board_policy.yml 에는 실제 wiring 된 8 key 만 수록. poller/send_retry 는 dashboard.md 🚧 TODO 마커로 후속.
    - 2 repo 분리 커밋: ___pm(board_policy.yml) 86a633e + ~/.claude(SCAR wiring+doc) 300d87b. Issue.md 종결은 본 bookkeeping 커밋.

## Issue151: publishable 정책 YAML 구동 재설계 — `data/publishable-policy.yml` 데이터 SSOT + fpm-sync.sh YAML 구동 + 편집 스킬 (등록: 2026-06-09, 해결: 2026-06-09, commit: a6f8299) ✅
* 목적: 정책 데이터(EXCLUDES·PERSONAL_RE·sanitize)가 `scripts/fpm-sync.sh` 에 **하드코딩**되고 doc 은 **서술만** → 공개 대상 변경 시 **코드+문서 이중 수정**·drift(Issue150 구현 중 실제 발생). 정책을 **머신 판독 YAML 단일 SSOT** 로 외부화 → "편집 1곳 → 엔진 자동 반영".
* 구현 명세 (완료):
    - **`data/publishable-policy.yml`** (신규, 데이터 SSOT) — `exclude[]`/`personal_guard[]`/`sanitize[]`. tracked + **self-exclude**(+`.claude/skills/publishable/` 도 제외 — 내부 메타도구라 공개 마켓 부적합)
    - **`scripts/fpm-sync.sh`** (리라이트) — 하드코딩 제거, `read_policy()`+`pol_emit()` 가 yq(1차)/python3+pyyaml(fallback) 로 동적 구성. 파서 부재 시 **fail-loud**(silent skip 금지). do_forward/do_reverse 진입 시 read_policy
    - **`.claude/skills/publishable/`** (신규 로컬 스킬 + backing `publishable.sh`) — show/validate/exclude add·rm/guard add/sanitize add/dry-run. yq `strenv()` injection-safe, self-exclude 제거 거부, 자동 validate
    - **`_doc_arch/publishable-policy.md`**(로컬) — 3요소(데이터/실행기/편집기)+스키마+mermaid 흐름으로 아키텍처 재작성
* 검증 (무회귀):
    - yq 추출 parity: EXCLUDES/PERSONAL_RE/sanitize 6쌍 = 기존 하드코딩 1:1 (`$HOME` 리터럴·한글 보존)
    - **end-to-end sandbox forward**: 제외 13종(self·skill 포함) 전부 차단 · 공개 페이로드(sh/·install.sh) 정상 · sanitize 누락 0($HOME·exampleProj·user@ 잔존 없음)
    - 스킬 dogfood: validate·exclude add(self skill)·show·injection 방어·self-exclude rm 거부 전부 PASS
    - bash -n PASS · 실 post-commit hook 새 YAML 엔진으로 정상(변경 없음 skip)
* 자동 결정:
    - YAML 위치 = `data/` tracked + self-exclude (fpm-sync.sh self-exclude 선례 일치 — 타 머신 sync·버전관리 위해 _doc_arch 로컬전용 대신 선택)
    - publishable 스킬도 mirror 제외 (___pm 내부 정책 자기관리 도구 → 공개 fpm 부적합. 새 YAML 구조 dogfood)
    - triage 복잡(다파일+엔진 리라이트+스킬)이나 사용자 명시 설계 → plan 생략, 본 이슈 상세로 갈음
    - 설계 doc 은 `_doc_arch/` gitignored → 로컬 전용(미커밋). 추적 변경은 fpm-sync.sh·yml·스킬·Issue.md 뿐이며 전부 fpm 제외 → 미러 무영향
## Issue150: ___pm publishable 정책 문서화 — `_doc_arch/publishable-policy.md` SSOT (prj42 file-deployment-rules 패턴 참고) (등록: 2026-06-09, 해결: 2026-06-09, commit: e5acd2a) ✅
* 목적: ___pm 의 공개 미러(fpm/prj7) publishable 정책이 `scripts/fpm-sync.sh` 의 EXCLUDES·PERSONAL_RE·sanitize 에 **음성적(negative)으로만 묻혀** 있어 "publishable 이 무엇인가"를 단일 문서로 추적 불가. prj42(m2slide) 의 선언적 정책 문서 패턴(`.claude/rules/file-deployment-rules.md` — 허용/금지 패턴 표)을 **참고**하여 ___pm 에 publishable 정책 SSOT 문서를 신설. **prj42 읽기 전용 참고(무수정)**.
* 구현 명세 (완료):
    - 신규 `_doc_arch/publishable-policy.md` (로컬 전용 — `_doc_arch/` gitignored) — 핵심 원칙 / 정의 / 적용 트리거 / 공개 대상 / 제외 대상(EXCLUDES 1:1) / 개인정보 하드 가드(PERSONAL_RE) / sanitize 치환 표 / 동작 흐름(mermaid) / 적용 시점 / 위반 대응 / 예외 / 참조. prj42 file-deployment-rules.md 구조 차용
    - `scripts/fpm-sync.sh` 헤더에 정책 SSOT 링크 1줄 (코드=실행기 / 문서=SSOT 역할 분리). 동작 무변경 (commit e5acd2a)
    - `gitignore-policy.md`(로컬전용 docs 축)와 상호 링크 — "무엇을 gitignore 하나" vs "무엇을 공개 미러에 보내나" 축 구분
    - prj42 무수정 (구조 참고만)
* 구현 중 발견·교정:
    - 1턴 stale read 로 정책 doc 초안이 `sh/` 를 "제외 대상"·`shell/fpm-functions.zsh` 를 공개판으로 기재 → **Issue149(commit a28b727) 가 이미 `sh/` 를 공개 페이로드로 승격(shell/ 제거, FPM_BASE 리팩터로 $HOME 하드코딩 제거)** 함을 확인하고 doc 을 현 코드(EXCLUDES 에 sh/ 없음)와 1:1 재정합
    - 유출 오탐: `sh/` 제외 누락은 회귀 아님(Issue149 의도). git diff HEAD 가 내 헤더 주석 2줄만 표시로 확인
* 자동 결정 (`/dev` 비대화):
    - "polish" 단어 prj42 전수 grep 0건 → 사용자 "polish" = prj42 의 선언적 publishable 정책 doc 패턴(file-deployment-rules.md)으로 해석
    - 작업 위치 = 현재 프로젝트 ___pm (사용자 명시: "42 참고, 현재 프로젝트에 구현, 42 무수정")
    - triage 중간(설계 SSOT 신설) — dev-g 비대화 보수 규칙상 단순 처리, plan/task 미생성
    - 정책 doc 은 `_doc_arch/` gitignored → 로컬 전용. fpm 미러 미포함(self-mangle·유출 회피). 추적 변경은 Issue.md·fpm-sync.sh 뿐이며 둘 다 fpm EXCLUDES → 미러 무영향
## Issue149: sh/ 공개화 단일화 — install 페이로드를 sh/fpm.sh 로 통합, 중복 shell/ 폴더 제거 (등록: 2026-06-09, 해결: 2026-06-09, commit: a28b727) ✅
* 목적: 설치 페이로드가 `shell/fpm-functions.zsh`(손수 sanitize 한 공개 subset)와 개인용 `sh/`(FPM_BASE 기반 전체 도구)로 이원화되어 이중 유지보수 부담 발생. FPM_BASE 리팩터(2026-06-09)로 sh/ 의 `$HOME` 하드코딩이 이미 제거되어 sh/ 를 공개 미러 대상으로 승격 가능. sh/ 를 단일 SSOT 공개 페이로드로 통합하고 중복 shell/ 제거.
* 구현 명세 (완료):
    - install.sh: `FUNC_FILE` `shell/fpm-functions.zsh`→`sh/fpm.sh`. .zshrc 블록에 `export FPM_BASE="$REPO_DIR"` + `source "$REPO_DIR/sh/fpm.sh"` 기입(fpm.sh 권장 로드 규약). 주석 동기화.
    - scripts/fpm-sync.sh: EXCLUDES 에서 `--exclude='sh/'` 제거 → sh/ 가 sanitize_tree 거쳐 공개 미러 반영. 주석(30~32) 갱신(sh/ 더 이상 제외 아님 — stale "하드코딩 포함" 교정).
    - 문서: INSTALL.md:27 / README.md:69 / CLAUDE.md:21 의 `shell/fpm-functions.zsh` 참조 → `sh/` 페이로드로 갱신. Issue.md:156(Issue144 Phase3 이력) 보존.
    - `git rm shell/fpm-functions.zsh` → 폴더 제거(유일 파일). 사용자 명시 승인.
* 검증 (완료):
    - `FPM_BASE=... zsh -c 'source sh/fpm.sh'` → cdf/cdff/cdfc/cdfv/sshf 5개 전부 function 로드 ✅
    - `bash -n install.sh` syntax OK ✅. `grep exclude='sh/'` 0건 ✅
    - `git archive HEAD sh/` = 5파일(fpm-projects-sync/fpm.sh/fpm_aliases.sh/fpm_function.sh/update-iterm-bg) — `$HOME`·`user@` 매칭 0줄(sanitize 불필요·방어층만), 생성물 `fpm_aliases_iterm-bg.sh` archive 미포함(gitignored) ✅
    - 잔여 `shell/fpm-functions` 활성 운영 참조 0 (Issue.md 명세·이력 + CLAUDE.md "구 shell/ 제거" 설명만 잔존 — 의도적)
* 자동 결정 (`/dev` 비대화):
    - triage 모호(6파일 변경, 단 기계적) → 단순 처리, plan/task/report 미생성

## Issue146: fpm 공개화 잔여 — 하드코딩 경로/호스트 일반화 + 최종 push + 미커밋 WIP 정리 (등록: 2026-06-09, 해결: 2026-06-09, commit: 572d8b4·5c36aa8·f2345d0·1cf237f·ae64b1f, fpm push: b05a4b3) ✅
* 목적: Issue140 종결 시 분리된 미완료분. 공개 fpm 의 잔여 sanitization·배포·미커밋 작업물 정리.
* 확정 결정 (hub 폼): Q1=엔진 sed 패스(원본 버그만 수정) / Q2=제너릭 치환 / push=클린 squash(force 없음)
* 구현 명세 (완료):
    - **미커밋 WIP 3묶음 분리 커밋**: 3a fpm-projects-sync 배선(peacock-sync.md·settings.json·setup-projects.sh, `572d8b4`) / 3b sync-jma(sync-jma.md·cdf.kmmacros·Prompts.md, `5c36aa8`) / 3c gitignore-policy SSOT 참조(pm/SKILL.md, `f2345d0`). projects/9 은 gitignore(자동생성)라 제외
    - **하드코딩 sanitization (엔진 패스)**: `scripts/fpm-sync.sh` forward 에 `sanitize_tree()` 추가 — TMP 스냅샷에만 perl in-place 치환(___pm 원본 불변). `$HOME`→`$HOME`·`user@`→`user@`·`exampleProj`→`exampleProj`·"외주 프로젝트 예시"→"외주 프로젝트 예시"·`host.local`/`host.local`→`host.local`. bare `jm4·jma`(sync-jma 식별자) 보존 (`1cf237f`)
    - **버그 2건 교정** (`ae64b1f`): ① sanitize 루프 `grep -Z`+`read -d ''`(null) 미iterate → newline-delimited. ② `scripts/fpm-sync.sh` 자신을 EXCLUDES 추가 — sanitize 룰셋이 exampleProj·경로 리터럴 포함 → 미러 self-mangle 방지. 미러의 stale 엔진 git-rm
    - Harness.md frontmatter `name` 풀경로 → `Harness` (md-rules)
    - **fpm 최종 push**: 미push 12 sync 커밋 전부 누출 포함 발견 → `reset --soft origin/main` 후 1개 클린 커밋 squash(added-line 누출 0 가드) → `git push origin main`(fast-forward, force 없음) = `c85952f..b05a4b3`. origin/main HEAD 트리 누출 0 검증
* 잔여 (사용자 A선택 수용): origin **과거 공개 히스토리**(c85952f 및 이전 커밋)에 누출 잔존 — 이미 공개된 데이터라 비파괴 클린 push 채택. 완전 scrub 필요 시 별도 force-push remediation


## Issue147: dashboard 시나리오 3 (Issue tree) 렌더 강화 — graph 위젯 노드에 상태 아이콘·이슈별 progress·current 마커 (show 모드 동등) (등록: 2026-06-09, 해결: 2026-06-09, commit: c7e6003) ✅
* 목적: `..board` 이슈 의존성 트리(시나리오 3) dashboard 가 `..show` 모드보다 빈약 — show 는 ✅/🔴 상태 배지·이슈별 진행 상태 풍부, dashboard graph 위젯은 노드 박스(label+테두리색)만. 사용자 요청 "show 만큼(특히 진행 상태) 잘 보여주게".
* 진단 (양쪽 다 원인):
    - A (시나리오 미인식·authoring): 문제의 `issue-tree-915.dash.yaml` 이 graph DAG 대신 flat `checklist`+`progress`+`text` 사용 → 의존 트리 미시각화
    - B (렌더 빈약·___pm 소유): `_render_nodegraph_svg` 가 노드당 라벨+상태색 테두리만. 진행 상태 표현 부재
* 구현 명세 (완료):
    - `services/hub/server.py:_render_nodegraph_svg` 강화: 노드 optional 필드 `progress`(0~100 또는 {value,max,label})·`sub`/`note`·`current` + 상태별 아이콘(✅🔴🟢⏳🚫⬜)+tint 배경+상태색. 노드 높이 동적. 하위호환 검증(구형 노드/문자열/빈/value-dict 전부 PASS)
    - `.w-graph` max-height 320→560, `.graph-sub`/`.graph-prog-lab` CSS 추가
    - `_doc_arch/hub_dashboard_detail.md §11` 노드 스키마 표 문서화 (gitignore 로컬)
    - 검증 fixture `_doc_work/z_htm/issue-tree-sample.dash.yaml` (Issue909~915 트리) + hub 서버 재기동·Playwright 스크린샷 검증 — 노드별 progress 바·current 글로우·상태 아이콘 정상 렌더 확인
    - 후속: 글로벌 agent 명세 갱신 → `~/.claude/Issue.md` Issue139 등록 (글로벌 SCAR 가드, 별도 세션)
* 자동 결정: triage 중간 판정 — plan/task/report 미생성 (방법 자명·스크린샷 검증으로 충분)

## Issue140: ___pm → fpm 공개 전환 사전작업 (등록: 2026-06-06, 해결: 2026-06-09, commit: ccb413e(폴더분리)·d464b4d·31db837·98eded5·24add17, 공개 repo: github.com/Finfra/fpm) ✅
* 목적: 비공개 `___pm`(공개 핵심=hub)을 공개 프로젝트 `fpm`으로 전환. 이름 정리·개인정보 분리·풀스택 설치·MCP·SCAR marketplace·듀얼 라이선스 사전작업.
* plan: `_doc_work/plan/pre-job-for-publish_plan.md`
* 확정 결정: 1=노출표면만 fpm(폴더명 유지) / 4=풀스택(cdf·sshf·hub) / 5=듀얼 라이선스 / A=MCP pm전체 / B=marketplace 로컬핵심 / C=PolyForm Noncommercial / D=_org는 Servers·Projects
* 구현 명세:
    - Phase 0 rename: README/제목 fpm, 경로·식별자·폴더명 `___pm` 유지
    - Phase 1 개인정보 분리: `Servers.md`·`Projects.md` → gitignore + `*_org.md` 예제. `finfra-server-access.md`·`fapp-projects.md` → gitignore+rm
    - Phase 2 [폴더 분리 채택] in-place filter-repo 대신 `~/_git/__all/fpm`(prj7) fresh export + `git init`(이력 0, 민감정보 미포함) = `ccb413e`. prj #7 등록. **공개 repo `github.com/Finfra/fpm` 라이브**(remote main `c85952f`)
    - fpm-sync 자동화: `scripts/fpm-sync.sh`(엔진 SSOT, 개인정보 2중 가드, forward/reverse 분기) + `install-fpm-hook.sh` + ___pm post-commit hook. `.claude/agents/fpm-sync.md` 에이전트. `sh/` 공개미러 제외(`24add17`)
    - Phase 5 MCP: `mcp/server.py`(stdlib JSON-RPC 2.0, 5 도구) 검증 통과
    - Phase 3 설치: `shell/fpm-functions.zsh` + `install.sh` + `INSTALL.md`. Phase 6 marketplace: `.claude-plugin/marketplace.json` + `fpm-core`. Phase 7 라이선스: PolyForm Noncommercial + `COMMERCIAL.md`
    - Harness ___pm/fpm 구조 문서화(`24add17`)
    - **잔여 → Issue146 분리**: 하드코딩 경로/호스트 일반화 + fpm 최종 push(local 1 ahead) + 미커밋 WIP(fpm-projects-sync 배선·sync-jma·gitignore-policy)

## Issue141: hub 네트워크 접근 개방 — Servers.md 호스트 allowlist (등록: 2026-06-07, 해결: 2026-06-09, commit: aea6105) ✅
* 목적: jma 등 Servers.md 등록 머신에서 jm4 의 hub(`:9876`)에 접근 가능하게. 안전 옵트인 설계(기본 127.0.0.1 유지)로 네트워크 개방.
* 구현 명세:
    - `_ip_allowed(ip)` = 루프백 무조건 허용 + `ip in ALLOWED_IPS`. `do_GET`/`do_POST` 상단 단일 전역 게이트로 통일(산재 14개 체크 → helper)
    - `_load_server_allowlist()` = `Servers.md` `check=O` 호스트 → `socket.gethostbyname` resolve, 실패 skip+log, 공개 호스트 경고 log. `HOST != 127.0.0.1` 개방 모드에서만 populate
    - 우선순위 `env HTM_SERVER_HOST > hub_setting.yml bind_host > 127.0.0.1`. 기본 미설정 시 `ALLOWED_IPS` 빈 set → 동작 변화 0
    - vendored `plugins/fpm-core/services/hub/server.py` 동기(PROJECTS_MD env 1줄 차이만 보존), SSOT `_doc_arch/hub_htm.md` "기본 차단 + 옵트인 allowlist" 모델로 갱신
    - 검증: 기본 모드 회귀 통과(loopback `healthz`/`hub` = 200, ALLOWED_IPS 기본 빈 set, 전역 게이트 14+ 적용, 두 사본 sync, syntax OK). `HTM_SERVER_HOST=0.0.0.0`+jma→jm4 `/hub` 200 은 원격 머신 필요한 옵트인 수동 검증으로 분리

## Issue145: fpm 셸 자산 부트스트랩 분리 + FPM_BASE 포터블화 (self-detect + self-healing 캐시) (등록: 2026-06-09, 해결: 2026-06-09, commit: 585d571) ✅
* 목적: fpm 셸 자산을 설치 위치 무관(`$FPM_BASE` 기반)하게 만들어 `~/_git/___pm`·`~/_git/__all/fpm` 어디 설치해도 동작. 단일 진입 `fpm.sh` 부트스트랩화 + 함수/alias 분리. 부수적으로 iterm-bg alias 미로드 버그 수정.
* 상세:
    - 분리: `sh/fpm.sh`(20KB 함수묶음) → 부트스트랩(FPM_BASE 결정+캐시+source) / `fpm_function.sh`(cdf·cdff·cdfc·cdfv·cdft·sshf) / `fpm_aliases.sh`(alias)
    - 포터블화: 전 스크립트 하드코딩 `$HOME/_git/___pm`·`$HOME` → `$FPM_BASE`. `update-iterm-bg`·`fpm-projects-sync` 포함 (env 우선 + `__file__` self-detect)
    - SSOT 계층: ① `export FPM_BASE`(명시 override) → ② self-detect(`.git` 미확인, 자기 위치 `${BASH_SOURCE}`/`${(%):-%x}`) → ③ `~/.config/fpm/base` self-healing 캐시(fpm 미source 외부 소비자용, 로드마다 갱신)
    - iterm-bg 버그: 생성물 `~/.zsh_aliases_iterm-bg.sh` 가 어디서도 미로드 → `$FPM_BASE/sh/fpm_aliases_iterm-bg.sh` 이동, `fpm_aliases.sh` 가 source
    - 함수 이관: `~/.zsh_functions` 의 fpm 결합 함수 `iterm-bg`·`chpwd`·`server-check` → `fpm_function.sh` 이관(원본 삭제+TOC 갱신). `server-check` 경로 버그(`$HOME/Servers.md` 미존재) → `_sshf_file`(`$FPM_BASE/Servers.md`) 로 수정. `~/.zsh_aliases` 는 fpm 결합 0개(잔류)
* 구현 명세:
    - 변경: `sh/{fpm.sh, fpm_function.sh(신규), fpm_aliases.sh(신규)}`, `update-iterm-bg`, `fpm-projects-sync`, `~/.zshrc`, `~/.bashrc`, `CLAUDE.md`, `.gitignore`(생성물 무시)
    - bash 안전: 부트스트랩 zsh-ism `${(%):-%x}` 을 `eval` 로 감싸 bash 파싱 단계 syntax error 회피
    - 검증: `FPM_HOME` 잔여 0 / zsh self-detect / 캐시 생성 / env override(`__all/fpm`) / 실제 `.zshrc` 로드(cdf·iterm-bg alias) / py_compile — 전부 OK
    - 후속(미적용): KM 매크로(`keyboard-maestro/cdf.kmmacros`) 캐시 소비 배선 / `install.sh` 가 `export FPM_BASE=$REPO_DIR`+`sh/fpm.sh` 기록(= `sh/` 공개미러 포함 결정 + fpm-sync `sh/` 제외 정책 재검토) / legacy `~/.info/__pmBasePath.txt` 삭제

## Issue144: fpm-core 번들 SCAR·hook 접두어 → fpm- 전면 통일 + 참조 동기 (등록: 2026-06-09, 해결: 2026-06-09, commit: f07b495) ✅
* 목적: 마켓플레이스 번들(`plugins/fpm-core/`) 자산 접두어를 fpm- 으로 통일 → 테스트 PC clean install/uninstall(glob `~/.claude/**/fpm-*`). 글로벌 loose 원본 측은 prj3 `~/.claude` Issue138 쌍작업.
* 설계 SSOT: `_doc_arch/fpm-scar-prefix-unification.md`
* depends: prj3#Issue138 (글로벌 측 — 쌍작업)
* 결정: D1 전면 fpm- / D2 shell 함수 예외 / D3 즉시 전환(alias 없음)
* 구현:
    - git mv 27 (hooks 10·agents 6·commands 9·skills pm/cdf) + hooks.json 9 hook 경로 fpm- 동기
    - 기능 참조: fpm-ask-form-template.js read(intercept/marker-detect), supervisor.test source, pm-do skill 백킹(fpm-pm-do), frontmatter name/title 동기, 번들 CLAUDE.md 자기설명 갱신
    - 검증: bash -n 전부, hooks.json/plugin.json JSON 유효, 더블프리픽스 0, 기능 잔여 0
* 잔여(보류): slash 산문 참조(`/fpm-*`) cosmetic, 설계 🔧 FIXME(services/hub dir·pm→do 축약·_doc_arch 파일명)

## Issue143: hub b모드(ask 폼) → 짝 a모드(show 렌더) 페이지 링크+iframe 임베드 (등록: 2026-06-08, 해결: 2026-06-08, fix: `26f4345` + 런타임 `~/.claude/hooks/ask-intercept.sh`(repo 외부, 동일 edit 반영)) ✅
* 목적: `..show`(a모드 렌더) 직후 `..ask`(b모드 폼)로 이어지는 흐름에서, 폼 페이지에 짝이 되는 직전 show 페이지로 가는 경로가 없어 수동 추적해야 했던 문제 해결. 폼에서 직전 show 페이지를 임베드로 한번에 보고 링크로도 이동 가능하게 함.
* 상세:
    - 증상: `hub_htm_..._a_proj-audit.htm`(z_htm) ↔ `hub_htm_..._b_gitignore-scope.htm`(/tmp/___pm)가 논리적 페어였으나 b 폼에서 a 로 갈 단서 없음 → 거의 추적 수준의 수작업
    - 난점: a(Claude Write, `_doc_work/z_htm/`)와 b(hook 생성, OUT_DIR fallback 시 `/tmp/___pm/`)가 서로 다른 OUT_DIR 일 수 있어 단순 "같은 폴더 최신 `_a_`" 스캔으론 페어 미검출 → 후보 폴더(OUT_DIR + cwd z_htm + /tmp/___pm) 합집합을 mtime 기준 스캔
    - 결정(2026-06-08 ..ask 폼 회수): 변경 라우팅 = fpm-core 소스 즉시 구현(+런타임 동시 반영) / 표현 = 링크 + iframe 임베드
* 구현 명세:
    - `plugins/fpm-core/hooks/ask-intercept.sh` python 블록: 페어 a-page 계산(후보 폴더 합집합에서 `hub_htm_*_a_*.htm` 중 mtime 최신 1개) + `<title>` 추출 → 접이식 `<details open>` iframe + 새탭 링크 스니펫 생성, deny-reason 지침에 주입(페어 없으면 생략·무해)
    - 런타임 `~/.claude/hooks/ask-intercept.sh` 동일 edit 반영(유일 차이 line 221 `CLAUDE_PLUGIN_ROOT` 분기 보존)
    - 검증: bash -n + embedded python ast.parse OK(양쪽) / 두 파일 diff = line 221 만 / 격리 실행으로 mtime 최신 a-page(`_202212_a_gitignore-doc`) 페어 검출 + `<title>` "gitignore 정책 문서화 완료" 추출 + file:// 스니펫 생성 확인

## Issue142: hub htm-server launchd 자동시작 실패 — plist 경로 stale (등록: 2026-06-08, 해결: 2026-06-08, fix: `~/Library/LaunchAgents/kr.finfra.htm-server.plist` — repo 외부, Issue.md 커밋 대기) ✅
* 목적: 로그인 시 hub htm-server(`:9876`)가 자동 기동되지 않아 매번 수동 `hub start` 필요했던 문제 해결. launchd plist 의 server.py 경로가 옛 경로(`services/htm-server/`)를 가리켜 RunAtLoad 가 exit 2(파일 없음)로 반복 실패한 것이 원인.
* 상세:
    - 증상: 6/7 21:37 로그인 후 htm-server DOWN 지속 → 6/8 19:14 수동 기동 전까지 hub Q&A form 자동회수 불가(서버 의존)
    - 원인: plist `ProgramArguments` = `.../services/htm-server/server.py`. 실제 디렉토리는 `services/hub/` 로 rename 됨 → 옛 경로 부재. rename-reference-rules 위반(디렉토리 이동 시 launchd plist 미갱신)
    - 증거: `launchctl list` → `-  2  kr.finfra.htm-server`(미실행·last exit 2). `/tmp/htm-server.err.log` 에 `can't open file '.../services/htm-server/server.py': [Errno 2]` 반복(KeepAlive+ThrottleInterval 10s 재시도)
* 구현 명세:
    - plist 경로 `services/htm-server/server.py` → `services/hub/server.py` 교정
    - stale 수동 서버 kill → `launchctl unload`/`load -w` 재로드 → RunAtLoad 정상 기동
    - 검증 통과: `launchctl list` PID 23717·exit 0, healthz=200, err log `started on http://127.0.0.1:9876 (pid=23717)` (에러 종료)

## Issue139: debug_TECH.md 트러블슈팅 로그 종결 (회고) — openclaw keychain 중복 토큰 + htm-server 좀비 카드 (등록: 2026-06-04, 해결: 2026-06-04, commit: 1a69985) ✅
* 목적: `_doc_work/debug_TECH.md`(기술 트러블슈팅 누적 로그, 재발 방지용)에 기록된 2건의 디버깅 작업을 회고 이슈로 명시 종결. 구성 fix는 이미 다른 이슈·운영 조치로 랜딩됨 — 본 이슈는 추적성 확보용 회고 기록. (요청 출처: ___pm `/issue-closer debug_TECH`, 2026-06-04)
* 상세:
    - (1) 2026-05-16 OpenClaw clawM4 Discord 봇 무응답 — macOS keychain `Claude Code-credentials` svce 동명 entry 중복 2개, 옛 만료 토큰이 1순위 매칭. `/login`은 fresh entry 추가만 하고 옛 entry 미삭제 → 영구 만료 토큰 read. 동시에 v2026.5.7 옛 게이트웨이(PID 63155)가 포트 18765 점유로 launchd 신규 부팅 차단.
    - (2) 2026-05-30 htm-server 좀비 dashboard 카드 부활 — `✕` dismiss 한 카드가 새로고침마다 `status:running` 부활. 근본: "pid 살아있으면 runner 살아있다" 가정이 orphan sleep·PID 재사용·필드 불일치(`worker_pid` vs `pid`) 앞에서 깨짐.
* 구현 명세:
    - 산출물: `_doc_work/debug_TECH.md` (2건 트레이스 — 증상·진단 경로·근본 원인·조치·재발 방지·검증 명령). 트래킹 시작 커밋 `1a69985`(Issue91 services/htm-server→hub rename 시 흡수).
    - (1) 조치=운영(코드 외): 옛 게이트웨이 kill + launchd bootstrap, keychain 옛 entry `security delete-generic-password` 1회(2회 시 fresh도 삭제), `openclaw secrets reload`. 재발 방지=`/login` 후 1회 삭제+expiresAt 검증.
    - (2) 코드 fix는 좀비 계열 이슈로 분리 랜딩: Issue136(빈 live 세션 cwd당 1개 dedup, `344eb54`)·Issue137(🧟 좀비 킬러 버튼, `53d1f97`·`6312c65`)·Issue138(worker_pid stale 강등·활성세션, `96101cb`). 서버측 3-layer(heartbeat 신선도 게이트 + `worker_pid` fallback + 파서 5곳 추출)가 최종 방어선.
    - 검증: 구성 fix 전부 각 이슈에서 검증 완료(좀비 카드 0개 영구 제거 curl 확인). 본 회고는 코드 변경 0 — Issue.md 문서 기록만.
* 교훈: liveness 판정은 pid 존재 단독 신뢰 금지 → pid + heartbeat 신선도 양쪽 필요. keychain 동명 svce 중복은 1순위 매칭 함정. 일괄 치환 시 들여쓰기 차이로 `replace_all` 누락 가능 → 실제 코드 경로 직접 호출로 검증.
## Issue138: dashboard `/view` UI 4건 — stop 동작·디자인 통일·강제종료/done전환·활성세션 버튼 (등록: 2026-06-03, 해결: 2026-06-04, commit: 96101cb) ✅
* 목적: dashboard read-only `/view`(Issue35)가 hub `/view`(ask 폼)·`/hub` 와 디자인 상이 + 컨트롤 부재. done 후 runner pid dead 라 stop 버튼 무의미하고 잔존 tmux window 종료 수단이 보드에 없음. (요청 출처: ___pm hub Mode C 테스트 중 발견, 2026-06-03, Issue131 후속)
* 상세:
    - (1) stop 버튼 동작 안 함 — done 대시보드는 runner pid 이미 dead → `/control stop` = `already_dead`. + read-only `/view` 엔 컨트롤 버튼 자체 없음.
    - (2) 디자인 통일 — `/view` 가 평이한 `<h1>`+banner. canonical hub 헤더(sticky 보라·📁 배지·🗂 Hub·닫기)와 불일치.
    - (3) 강제 종료(kill window) 버튼 + status:done 시 stop→"종료" 전환. **추가 버그**: `_handle_control` kill_pane 이 registration 게이트(dead pid → already_dead 조기반환)에 막혀 window kill 미실행 → done 후 window 종료 불가.
    - (4) 활성 세션 보기 버튼 부재 — `/view` 에서 `/hub` 진입 수단 없음(← hub 텍스트 링크만).
* 구현 명세:
    - `_handle_view`: `_serve_dash_inline(abs_path, cwd, token)` 로 cwd/token 전달 (control wiring).
    - `_serve_dash_inline`: canonical 헤더(📁 배지·🛰 활성세션·🗂 Hub·닫기) + 컨트롤바(🔄 refresh·⏹ stop·✕ 종료) + JS(dashStop/dashKill/dashRefresh → `/control`). runner pid dead 감지(`_pid_alive`) → status 보정 + pid `⚠ 종료됨` 배지 + `ctl-note` + stop 숨김·"✕ 종료(window 정리)" done-스타일 노출. status≠terminal 시 `interval`(2~60s clamp) 자동 reload.
    - `_handle_control`: kill_pane 분기를 registration 게이트 **앞**으로 이동 — window kill 은 pid liveness 무관(window_name 대상). cwd+token 인증 유지. window 부재 시 graceful 200 `already_gone`.
    - 변경 파일: `services/hub/server.py` (+161/-31, 3지점). dashboard agent(글로벌 SCAR) 변경 없음.
    - 복잡도: 중간 (파일 1, 렌더러 확장 + control 게이트 수정).
* 검증 (단일 파일 복사 dashboard `copytest1`, runner 51118):
    - `ast.parse` OK, `test_control_gate.py` 45 passed.
    - **live /view**: 📁 배지·🛰 활성세션·🗂 Hub·닫기 + 🔄/⏹ 정지/✕ 강제종료 + 🟢 alive 렌더 확인.
    - **stop**: `POST /control stop` → `{stopped, TERM}` → runner 51118 종료 ✅.
    - **runner-dead /view**: pid `⚠ 종료됨`·`ctl-note`·**stop 버튼 count 0**·"✕ 종료(window 정리)" done-스타일 전환 확인.
    - **kill-window (게이트 수정 확정)**: dead/미등록 pid 51118 + 실재 더미 window `_killtest138` → `{killed_pane}` → window 제거 ✅ (구버전이면 게이트의 `already_dead`에 막혔을 것).
* 후속 (별건, 미처리): dashboard agent `worker.sh` 가 stop 시 rsync **grandchild orphan** 미회수 (trap 이 손자 프로세스 미전파). 글로벌 SCAR(`~/.claude/agents/`) — `~/.claude/Issue.md` 등록 대상.
## Issue137: hub 🧟 좀비 킬러 버튼 — 빈 live 세션 일괄 종료 + 새로고침 (등록: 2026-06-03, 해결: 2026-06-03, commit: 53d1f97, 6312c65) ✅
* 목적: Issue136 dedup 은 빈 세션 *표시*를 cwd당 1개로 줄일 뿐, 좀비 프로세스 자체는 살아남아 카드가 잔존. 매번 수동 `ps`+`kill` 하던 좀비 정리를 hub UI 버튼으로 1클릭화. (요청 출처: ___pm hub 운영 중, 2026-06-03, Issue136 후속)
* 상세:
    - 빈 세션 = VSCode 확장이 세션 종료 후 살려둔 native claude(`--output-format stream-json`, 프롬프트 전 `live_label` 없음). `live_pid` 영구 생존 → `force_live`. dismiss(tombstone 120s)는 부활 → 근본 제거 = 프로세스 SIGTERM.
* 구현 명세:
    - **서버**: `POST /kill-empty-live`(`_handle_kill_empty_live`, 127.0.0.1 trust). sessions 스냅샷 순회 → `content_type=="live"` + `live_label` 빈 세션만 → `live_pid` `os.kill(SIGTERM)` graceful + `sessions.pop` + `_live_dismiss_add`(재등록 차단). titled live·dashboard 는 제외(오살 방지). 라우팅 `/clear-done` 옆.
    - **UI**: 활성 세션 섹션 헤더에 `btn-zombie`(🧟 좀비 킬러) + `killEmptyLive()` JS(confirm→fetch→`toast`→`reload`). CSS `.section-title .btn-zombie`(녹색). 바인딩 `rescanBtn` 옆.
    - 변경 파일: `services/hub/server.py`(+74, 6개 지점: 라우팅·핸들러·헤더HTML·CSS·JS함수·바인딩).
    - 복잡도: 중간 (파일 1, endpoint+UI 신설, kill 정책 = titled 보존·SIGTERM graceful 설계 결정).
* 검증: `ast.parse` OK. 서버 재기동(pid 72757) healthz ok. `POST /kill-empty-live` 200(`killed:[]` — 직전 Issue136 정리로 빈 세션 0 상태). `/hub` HTML 에 `id="btn-zombie"`·`🧟 좀비 킬러` 렌더 확인.
* 회귀 fix (6312c65): 최초 커밋(53d1f97)의 `killEmptyLive` confirm 메시지 `\n`(단일 백슬래시)이 HUB_HTML(Python triple-quoted 일반 문자열)에서 실제 개행으로 변환 → JS 문자열 리터럴 내 개행 → "Invalid or unexpected token" 전체 인라인 스크립트 파싱 중단 → `reload()` 미등록 → hub "로딩 중..." 영구 정지. `\n`→`\\n`(dismissSession 등 기존 패턴 동일) 으로 수정. Playwright 콘솔 에러 0·화면 정상 로드 확인. 교훈: HUB_HTML 내 JS 문자열 개행은 항상 `\\n`.
## Issue136: hub ✕(dismiss) 무력 — 좀비 프로세스 빈 세션 부활, cwd당 1개 표시로 우회 (등록: 2026-06-03, 해결: 2026-06-03, commit: 344eb54) ✅
* 목적: 활성 세션 카드 ✕(dismiss) 버튼이 여전히 "안 됨"으로 체감. Issue135 tombstone 도입 후에도 빈 세션("-")이 카드에 도배됨. 진짜 원인 재확인 + 근본 차단 불가 시 노이즈 우회. (요청 출처: ___pm hub 운영 중 발견, 2026-06-03, Issue135 후속)
* 상세:
    - **원인 데이터**: 진단 시 `sessions.json` 빈 live 세션 6개의 `live_pid`(75198·39538·52582·95359·23220·24258) `os.kill(pid,0)` 전부 ALIVE. VSCode 확장이 세션 종료 후에도 claude 네이티브 프로세스를 안 죽임 → 프롬프트 전(title 없음) register 만 한 세션이 collect `content_type=="live"` 분기에서 `_pid_alive→force_live=True` 로 영구 노출.
    - **✕ 무력 메커니즘**: dismiss → `sessions.pop` + tombstone(`LIVE_DISMISS_TTL=120s`) → 카드 즉시 사라짐. 그러나 살아있는 프로세스가 heartbeat/register 로 sessions 재생성 → 120초 후 tombstone 만료 → 부활. 프로세스 kill 은 정당 세션 오살 위험 → 근본 차단 불가(Issue135 tombstone 은 일시 숨김의 한계).
* 구현 명세:
    - **빈 세션 dedup**: `_collect_live_sessions` `results.sort()`(updated_age 오름차순) 직후, `content_type=="live"` + title 빈 세션을 `cwd_hash` 당 가장 최근 1개만 남기고 collect 단계에서 제외. title 있는 live·dashboard 세션은 전부 유지(정보 손실 0).
    - 변경 파일: `services/hub/server.py`(+23).
    - 복잡도: 중간 (파일 1, "빈 세션 표시 정책" 설계 결정 有 — kill vs 숨김, cwd당 1개 vs N개).
* 검증: `ast.parse` OK. 서버 재기동(pid 77550) healthz ok. `/dashboards` 재조회 — ___pm(ccf9da30)·_public(3d31ec39)·finfraHome(27de9da6) 빈세션 **2→1**, titled(.claude 2·___pm 3) 전부 보존. 디버그 리포트: `_doc_work/z_htm/hub_htm_20260603_232512_a_empty-session-dedup.htm`.

## Issue133: design-doc(_doc_arch 적용 스킬) 갱신 시 연결 SCAR 동기 갱신 검증·보강 (등록: 2026-06-03, 해결: 2026-06-03, commit: 3ed8164) ✅
* 목적: `/design-doc` 으로 `_doc_arch/` 영속 설계 문서를 갱신할 때, 그 설계와 연결된 SCAR(command/rule/skill/agent) **본문도 함께 동기 갱신되는지** 확인. 설계↔구현 동기 갱신 절차 부재(gap) 검증·보강안 도출. (요청 출처: ___pm 이슈후보, 2026-06-03)
* Walkthrough:
    - **읽기 검증(1차) — gap 확정**: 글로벌 SCAR 2파일 전문 Read.
        - `commands/design-doc.md` "5. 검증"(108~112행): `/md-rule-apply` + 관련자료 링크 + **SSOT 중복 grep(보고만, 자동 수정 X)**. → 중복 *탐지*(같은 내용 두 곳→축약)용. 설계→구현 *전파* 아님.
        - `_doc_arch/doc-design-rules.md` "규칙·plan과의 연결 규칙"(203~227행): 규칙→_doc_arch 링크, plan→_doc_arch 영속화, _doc_arch→역참조 — 전부 **링크(역참조) 규칙**. 본문 동기화 절차 없음.
        - design-doc Case B/C(섹션 갱신, 58~70행)는 `_doc_arch` 파일만 Edit → 영향 SCAR 본문 식별·동기 단계 부재.
    - **결론**: 설계↔구현 동기 갱신 절차 gap 실재. (1) SSOT 중복방지(같은 정보 두 곳→축약) ≠ (2) 설계→구현 동기(설계 A 변경→A 구현 SCAR B 본문 갱신) — 방향이 다름.
    - **변경 가드 위임**: 실제 보강(design-doc "5. 검증" 단계 추가 + doc-design-rules `## _doc_arch 설계 변경 → 연결 SCAR 본문 동기` 규칙 신설)은 글로벌 SCAR(cwd≠`~/.claude`) → 글로벌 `~/.claude/Issue.md` **Issue135** 로 등록(글로벌 HWM 134→135). 별도 글로벌 세션 처리.
* 검증: design-doc.md·doc-design-rules.md 전문 Read 로 gap 2건 라인 단위 확인(design-doc 58~70·108~112, doc-design-rules 181~193·203~227). 글로벌 Issue135 등록 완료(보강안·구현 명세 포함). ___pm 측 코드 변경 0(검증·위임만).
* 복잡도: 중간 (읽기 검증 + 글로벌 위임)
## Issue135: hub live 카드 dismiss 후 부활 — dismiss tombstone 부재 (등록: 2026-06-03, 해결: 2026-06-03, commit: 142479d) ✅
* 목적: 활성 세션 카드의 ✕(dismiss) 버튼이 "동작 안함"으로 체감됨. 디버그 결과 dismiss 핸들러·JS·검증은 정상(로그 `22:48:58`·`22:49:04` `pruned` 성공). 진짜 원인 = dismiss 는 `sessions.pop((h,sid))` 만 하고 **재등록 차단 tombstone 이 없어**, VSCode 확장 native 프로세스가 살아있는 한(Issue132 게이트 `_pid_alive(live_pid)` 영구 통과) 다음 hook register/heartbeat 가 sessions 를 재생성 → 카드 부활. (요청 출처: ___pm hub 운영 중 발견, 2026-06-03, Issue132 후속 결함)
* 상세:
    - 데이터 증거: `sessions.json` `ccf9da30`(=___pm) 에 live 항목 8개 누적, 각 `live_pid`(76105·28573·21631·46603·56236) `ps` 확인 전부 ALIVE(`/.vscode/extensions/anthropic…`). collect `content_type=="live"` 분기는 `_pid_alive` 면 무조건 `force_live=True` → dismiss 후 재등록분이 다시 노출됨.
    - 대비: htm/dash clear 는 `HTM_CLEARED`/`DASH_CLEARED` tombstone 으로 재등록 차단. live dismiss 만 tombstone 부재.
* 구현 명세:
    - **tombstone 신설**: `LIVE_DISMISSED`(`data/hub/live-dismissed.json`, dict `{h}|{sid}`→ts) + `LIVE_DISMISS_TTL=120s`. 헬퍼 `_load_live_dismissed`(TTL lazy purge)·`_save_live_dismissed`·`_live_dismiss_add`. HTM_CLEARED/DASH_CLEARED 와 대칭.
    - **dismiss 핸들러**(`_handle_session_dismiss`): `sessions.pop` 후 `_live_dismiss_add(h,sid)` 기록(pop 여부 무관 — 이미 재등록 직후일 수 있음).
    - **collect live 분기**(`_collect_live_sessions`): 시작 시 `_load_live_dismissed()` 1회 스냅샷 → `{h}|{sid}` tombstone hit 시 `continue`(표시 제외, sessions 는 유지). TTL 만료 후 자동 해제(살아있는 세션 정상 복귀).
    - 변경 파일: `services/hub/server.py`(+59), 신규 `services/hub/test_live_dismiss_tombstone.py`.
    - 복잡도: 중간 (파일 1+1, tombstone 설계 결정 有 — TTL·키 단위·표시제외 vs pop)
* 검증: py_compile OK. 신규 `test_live_dismiss_tombstone.py` 8/8(제외/회귀/TTL복귀+lazy purge/핸들러 E2E 부활차단). 회귀 `test_control_gate` 45·`test_feed_link` 21·`test_dash_tombstone_session` 6 전부 통과. 서버 재기동(pid 71094) healthz ok, `/hub` 200. 디버그 리포트: `_doc_work/z_htm/hub_htm_20260603_225739_a_dismiss-revive.htm`.
## Issue134: hub 활동 피드 갑자기 사라짐 — persist_feed race condition (등록: 2026-06-03, 해결: 2026-06-03, commit: 41ba2b9) ✅
* 목적: 활동 피드(15 live session 화면)가 간헐적으로 전체 사라짐. 사용자 추측은 "feed_limit(300) 초과 시 전체 삭제"였으나 실제 원인은 다름 — `deque(maxlen=300)`+`appendleft` 는 정상(로그 `feed=300` 유지). 진짜 원인 = `persist_feed` 의 동시 쓰기 race 로 `hook-feed.json` 손상 → 재시작 시 `load_feed` 파싱 실패 → 피드 전체 0. (요청 출처: ___pm hub 운영 중 발견, 2026-06-03)
* 구현 명세:
    - **루트 원인**: `ThreadingHTTPServer` 다중 요청 스레드가 `persist_feed` 동시 호출 → 모두 공유 경로 `hook-feed.json.tmp` 에 `open(w)`/write → 내용 혼입(JSON `Extra data`) + `os.replace` race(`Errno 2`). 손상 파일은 재시작 `load_feed` `json.load` 예외 → feed 전체 손실(로그: `22:01:15 persist_feed failed`, `22:02:32 load_feed failed: Extra data` → `feed=1` 재축적).
    - **수정 A (persist_feed)**: tmp 경로를 `{HOOK_FEED_FILE}.{pid}.{tid}.tmp` 로 유니크화(스레드간 충돌 제거) + snap·write·replace 전체를 `feed_lock` 으로 직렬화(원자화). 모든 `persist_feed()` 호출부가 lock 밖임을 검증(deadlock 없음).
    - **수정 B (load_feed)**: `json.load` 단계 분리 — 손상 시 `.corrupt` 백업 후 빈 상태로 진행(추가 손실 방지 + 사후 분석).
    - 변경 파일: `services/hub/server.py` (`persist_feed`, `load_feed`).
* 검증: py_compile OK. 서버 재기동(pid 11095, healthz ok), feed 10개 정상 복원. 동시 20 `POST /hook-event` 부하 → JSON 무손상·`persist_feed failed` 0건·`.corrupt`/`.tmp` 잔재 0개(이전 7건 persist 에러는 모두 옛 코드). 디버그 리포트: `_doc_work/z_htm/hub_htm_20260603_221710_a_feed-disappear-fix.htm`.
## Issue132: hub 빈 live 세션 카드 잔존 수정 — session_end prune + 수동 dismiss (등록: 2026-06-03, 해결: 2026-06-03, commit: 41ba2b9) ✅
* 목적: 활성 세션 카드 중 빈 카드(제목 "-", 프롬프트 전 세션)가 세션 종료 후에도 영구 잔존. 원인 = (1) `_handle_hook_event` 가 `event=session_end` + `sid` 를 받고도 피드에만 적재하고 `sessions` 테이블을 prune 하지 않음(SessionEnd 훅 무효), (2) VSCode 확장이 세션 UI 종료 후에도 `claude` native 프로세스를 살려둬 유일 게이트 `_pid_alive(live_pid)` 가 영원히 통과. (요청 출처: prj `.claude` 작업 중 발견, 2026-06-03)
* 구현 명세:
    - **A — session_end prune**: `_handle_hook_event` 에서 `event=="session_end"` 이고 `sid` 존재 시 `sessions.pop((cwd_hash(cwd), sid))` + `persist_sessions()`. SessionEnd 훅(`~/.claude/hooks/hub-session-end.sh`)을 실효화. 프로세스 kill 아님 — 등록 해제만.
    - **B — 수동 dismiss**: 신규 엔드포인트 `POST /session/dismiss?cwd=&sid=&token=` (`_handle_session_dismiss`) — `validate(cwd,token)` 후 sessions entry 만 제거. live 카드(pid 없는 claude 세션)에 `✕ dismiss` 버튼(`dismissSession()` JS) 노출 — `confirm` 후 fetch, 프로세스 미종료. dashboard kill 버튼(`stopRunner`/`removeQueueDash`)과 분리.
    - 변경 파일: `services/hub/server.py` (라우팅 +`/session/dismiss`, `_handle_hook_event` prune 분기, `_handle_session_dismiss` 신규, 카드 렌더 dismiss 버튼, `dismissSession` JS).
* 검증: py_compile OK. 서버 재기동(healthz ok). A — 임시 live 세션 register→session_end→테이블 제거 확인(+로그 `session_end pruned`). B — dead 세션 `543834f2` dismiss→`pruned:true` 테이블 제거 확인. 실환경 — 실제 세션 종료(`363693e9`)가 SessionEnd 훅으로 자동 prune 됨(로그 확인). 빈 카드(프로세스 잔존분)는 dismiss 버튼으로 수동 정리 가능.
## Issue131: hub 활성 세션 행 클릭 → VSCode 세션 탭 포커스 (등록: 2026-06-03, 해결: 2026-06-03, commit: 6412ef3) ✅
* 목적: 활성 세션 카드의 각 행이 Claude Code 세션(sid)에 대응하나, 클릭 시 프로젝트 폴더만 열려 특정 세션으로 이동 불가. 행 클릭으로 해당 세션 탭에 바로 포커스.
* 구현 명세:
    - 메커니즘: Claude Code extension URI `vscode://anthropic.claude-code/open?session=<sid>` (공식 문서 — 세션 탭이 열려 있으면 그 탭을 포커스). 제약: 세션이 현재 열린 VSCode 워크스페이스(cwd)에 속해야 함.
    - 서버 `_handle_open_session` (POST `/open-session`): localhost only + cwd 화이트리스트(open-project 동일) + sid 엄격 검증(`[A-Za-z0-9_-]{1,128}` — 셸/URI 주입 차단). `open -a "Visual Studio Code" <cwd>` 로 워크스페이스 전면화 후(0.4s) 세션 URI 호출.
    - 클라: 행 `<li>` 에 `data-sid`·`data-cwd`, `#live-grid` 클릭 핸들러에 세션 행 분기(more-toggle 다음·openProject 앞), `openSession()` fetch, hover 커서·title 툴팁(전체 제목).
* 검증: 주입 sid→`400 invalid sid format`, 비화이트 cwd→`403`, HTML 배선(data-sid·openSession·핸들러) 확인. 회귀 0 (45+21+6). 권위 확인: code.claude.com/docs + 로컬 extension anthropic.claude-code v2.1.161.

## Issue129: hub 활성 세션 카드 표시 정리 — 명령 전 "-", 1행 ellipsis, 카드당 세션 행 상한 (등록: 2026-06-03, 해결: 2026-06-03, commit: 6412ef3, a29f300) ✅
* 목적: 명령(프롬프트) 전 세션이 "claude · win 1" 로 표기되어 무의미, 긴 제목이 여러 줄로 흘러 카드 비대, 한 프로젝트 세션이 많으면 카드가 과도하게 길어짐.
* 구현 명세:
    - 명령 전 세션(ai-title·live_label 없음) → live 분기 `claude · win N` fallback 제거 → title None → 클라 `s.title || '-'`.
    - `.live-topic` CSS: `white-space:nowrap; overflow:hidden; text-overflow:ellipsis` (1행 ellipsis, 전체는 title 툴팁).
    - `live_session_limit`(hub_setting.yml, 기본 6) — `HUB_SETTING_DEFAULTS` 등록 + `/dashboards` 페이로드 전달. 카드(프로젝트 그룹)당 세션 행 상한. (초과 시 "외 N개 더" → Issue104 확장 연계)
* 검증: 페이로드 `live_session_limit:6`, 명령 전 세션 `title:null`, 슬라이싱(7건/lim6→5행+"외 2개 더") node 검증, 회귀 0.

## Issue127: hub 활성 세션 카드 제목 — VSCode 탭 제목(ai-title) 동기화 (등록: 2026-06-03, 해결: 2026-06-03, commit: 6412ef3) ✅
* 목적: 카드 제목이 프롬프트 첫 줄(`live_label`)이라 VSCode 탭 제목(`aiTitle`, AI 생성 짧은 요약)과 달랐음. 둘을 일치.
* 구현 명세:
    - SSOT: 세션 JSONL 의 `{"type":"ai-title","aiTitle":...,"sessionId":...}` = VSCode 탭 제목.
    - `_session_ai_title(cwd, sid)`: JSONL 경로 해석(`_resolve_session_jsonl` — cwd 비영숫자→`-` 인코딩 직접 경로 + glob fallback, sid 캐시) → 최신 ai-title reverse-scan(EOF부터 256K→1M→8M 청크 확장) → mtime 캐시(doc_cache). live 분기에서 `aiTitle` 최우선 → `live_label` → win.
* 검증: b55d2cca→"Firefox 백그라운드 열기 옵션 추가", 8b60a1df→"Issue97 진행" — VSCode 탭과 일치. 회귀 0.

## Issue104: hub 활성 세션 카드 "외 N개 더" 클릭 → 카드 확장 (등록: 2026-06-03, 해결: 2026-06-03, commit: 6412ef3) ✅
* 목적: Issue129 의 `live_session_limit` 초과분 "외 N개 더" 요약 행이 `data-sid` 없는 plain `<li>` 라 클릭 시 카드 fallback 으로 **VSCode 가 열림**(의도치 않음). "외 N개 더" 클릭 시 숨긴 세션 행을 펼쳐 카드 확장.
* 구현 명세:
    - `renderLiveSessions`: 초과 행을 잘라내지 않고 `live-hidden` 클래스로 전체 렌더(기본 `display:none`). 요약 행 `live-more`(`data-more` 카운트). 카드 cwd 가 `expandedCards` Set 에 있으면 `expanded` 클래스.
    - 5초 `reload()` 재렌더에도 확장 유지: 전역 `expandedCards` Set 으로 cwd 추적·재적용.
    - `#live-grid` 클릭 핸들러: `.live-more` 분기 추가(session row·openProject 보다 우선) — `expanded` 토글 + Set 갱신 + 라벨 `외 N개 더 ▾` ↔ `접기 ▴`.
    - CSS: `.live-item.live-hidden{display:none}`, `.card.live.expanded .live-item.live-hidden{display:flex}`.
* 검증: ___pm 카드(8세션>limit6) "외 3개 더" 클릭 5→8행 + 라벨 `접기 ▴`, 재클릭 복귀, reload 재렌더 확장 유지. py_compile OK, 회귀 0. [세션 B 구현분 — 6412ef3 server.py 일괄 커밋에 포함]

## Issue103: hub render-only htm 헤더 `📁{프로젝트명}` 배지 클릭 → VSCode 열기 (cdfv) 미구현 (등록: 2026-06-03, 해결: 2026-06-03, commit: ~/.claude@36acd3a) ✅
* 목적: render-only `.htm`(file://) 헤더의 `📁{프로젝트명}` 배지가 plain `<span>` 이라 클릭해도 해당 프로젝트를 VSCode 로 열지 못함(cdfv 효과 부재). `/hub` 페이지 활성 세션 카드는 Issue101 에서 클릭→VSCode(`/open-project`)가 동작하나, 생산되는 htm 문서엔 미반영. 양쪽 일관성 확보.
* 구현 명세:
    - `~/.claude/commands/hub.md` 헤더 섹션: `<span class="proj-badge">📁 {프로젝트명}</span>` → 클릭 가능 `<a class="proj-badge">` 로 변경. inline `onclick` 에서 `fetch('http://127.0.0.1:9876/open-project', {POST, body:{cwd:'{프로젝트 절대경로}'}})` 호출. 성공 무음(VSCode 가시 open), 실패 `alert` fail-loud. `cwd` 절대경로 임베드 지시 추가, `.proj-badge { cursor: pointer }`.
    - 기존 인프라 재사용: 서버 `POST /open-project`(server.py:2557, Issue42) — `{cwd}` 화이트리스트(Projects.md ∪ 레지스트리) 검증 후 `open -a "Visual Studio Code" <cwd>`. `_send_json` 의 `Access-Control-Allow-Origin: null` → file://(origin null) cross-origin fetch 허용. 서버 코드 변경 0.
    - `_doc_arch/hub_htm.md` `/open-project` 섹션에 render-only htm 배지 호출처 명시.
* 검증 (라이브): healthz ok / `OPTIONS /open-project` → `Access-Control-Allow-Origin: null` 확인 / `POST /open-project {cwd:___pm}` → `{"status":"opened"}` (VSCode 가 ___pm 열림). 신규 render-only htm 헤더 배지가 클릭 가능 `<a>` 로 생성됨.
* 선례: Issue88(동일 배지 헤더 통합, `~/.claude@4369405`) — hub.md 글로벌 SCAR 변경을 ___pm Issue.md 로 추적하는 확립된 패턴.
## Issue97: Dashboard SCAR 기본조건 + noteForHuman 시나리오 1~8 전수 검증 (등록: 2026-05-31, 해결: 2026-06-03, commit: be3a5b1) ✅
* 목적: dashboard SCAR(agent + runner/supervisor/queue-runner + hub) 기본조건 5가지 + noteForHuman 시나리오 1~8 을 라이브 검증해 완성도 확정.
* report: `_doc_work/report/dashboard-scenario-verification_issue97_report.md` (스크린샷: `_doc_work/report/issue97_shots/` 4장)
* 검증 결과 (T1 사용자 선택 = 전수 8개 라이브 실행):
    - 기본조건 1~5 전부 ✅. 시나리오 1~8 dummy queue/data → hub 라이브 등록·렌더 전수 PASS. 시나리오 9(scp SVG)는 프로덕션 라이브 가동 중.
    - S3(이슈트리 DAG)·S6(병렬 conc3)·S7(헬스 dynamic_eval) 인라인 `/view` 스크린샷 직접 확인. S2·S4·S5 동일 queue-runner 메커니즘, S8 동일 monitor heartbeat.
    - 글로벌 스크립트(`~/.claude/agents/dashboard-*.sh`) 무수정 사용(USE only) — 기검증 코드 대상 동작 확인. 소스 변경 0.
* 발견 사항 재판정 (전부 stale → 글로벌 SCAR 변경 불필요):
    - queue.yaml 스키마 "queue:→items:" → 이미 `items:` 일관(sample.yaml:17, supervisor.sh:127). 정정 불요
    - hub `_` prefix window 필터 → server.py 에 부재. hub 렌더는 `.dash.yaml` 파일스캔(`/dashboards`) 기반(Issue96 결과). "window 필터" 비적용 개념
    - 시나리오 스크립트 위치 → scenario 7·8 task는 `~/.claude/_doc_work/tasks/`, synthetic 검증은 임시 하니스로 충분
* T1~T5 충족: T1(전수 PASS+스샷)·T2(스키마 확정)·T3(prj3 변경 불요)·T4(파일스캔 동작 확인, window 필터 재정의)·T5(4 컴포넌트 trap 매핑 문서화)
* 선행 이슈: Issue94 (구현), Issue96 (hub 렌더). agent 9능력은 dashboard.md L40-50 에 cap35v2/cap6v2/cap7v5/cap8appr 로 기 PASS
## Issue102: hub htm 카드 "열기" 링크 깨짐 — `/view`·`/htm-doc` 가 `.htm` 확장자 거부 (등록: 2026-06-03, 해결: 2026-06-03, commit: 4ade281) ✅
* 목적: htm 스킬(Issue123)이 `hub_htm_*.htm` 확장자로 문서를 쓰는데, hub 서버의 `/view`·`/htm-doc` 핸들러는 `.html` 확장자만 허용 → 카드 "열기" 클릭 시 `{"error": "extension not allowed"}` 403 반환. 양끝 확장자 정책 불일치 해소.
* 구현 명세:
    - `_handle_view`(L3245)·`_handle_htm_doc`(L3206) 확장자 체크 `endswith(".html")` → `endswith((".html", ".htm"))`
    - `.htm`/`.html` 둘 다 `text/html` content-type serve (기존 헤더 그대로)
* 검증: 서버 재시작 후 `.htm → 200 text/html`, `.py → 403`(보안 경계 유지), bad token → `401`(인증 유지) 확인
* 비고: server.py 동일 working tree 에 무관한 chart/sparkline 위젯 WIP(+426) 공존 → `git apply`/HEAD-restore 로 본 2줄만 격리 커밋
## Issue101: hub 활성 세션 카드 간소화 + 클릭 시 VSCode 열기 (등록: 2026-06-03, 해결: 2026-06-03, commit: 86d2c36, 3baad51, 7e97e3c) ✅
* 보강(7e97e3c): 같은 프로젝트 세션이 여러 카드로 흩어지는 문제 → cwd 기준 그룹화(1카드=1프로젝트), body 에 세션 topic 리스트 + 세션 수 배지. kill/승인 버튼은 각 리스트 항목으로 이동
* 목적: 활성 세션(📡) 카드가 sid/SSE subs/cwd 등 너무 자세함. 프로젝트 제목과 간단 내용만 `:` 로 구분해 한 줄로 노출하고, 카드 클릭 시 cdfv(아이콘 클릭) 효과처럼 해당 프로젝트를 VSCode 로 열기.
* 상세:
    - 대상: services/hub/server.py `renderLiveSessions` (활성 세션 카드 렌더)
    - 카드 body 간소화: `프로젝트명 : 간단내용(title)` 단일 라인. sid `<code>`, subs/age meta, cwd span/열기 링크 제거
    - 카드 전체 클릭 → `openProject(s.cwd)` (기존 /open-project 핸들러 재사용, cdfv 효과)
    - kill(✕)/승인(▶) 버튼은 closest('button,a') 위임 제외로 카드 열기 억제
* 구현 명세:
    - 로직: card div 에 `data-cwd` + hover 시각화, body 를 colon 라인(live-line/live-prj/live-sep/live-topic)으로 교체. live-grid 위임 click 핸들러 추가 (버튼/링크 closest 시 무시)
    - 검증: hub restart 후 서빙 HTML 에 `data-cwd`·`live-prj`·`live-grid 위임 핸들러`·`card.live[data-cwd]` CSS 모두 무결 확인. py_compile OK
## Issue100: hub important_events R2 — 죽은 세션 wait 가 영구 critical 칩으로 부활 (등록: 2026-05-31, 해결: 2026-05-31, commit: cbca2f1) ✅
* 목적: PM Hub 헤더 빨간 칩에 `htm-server — 응답 1311분 대기`, `__capture_previous — 2655분`, `test1 — 3148분` 등 22~52h 된 유령 "요청 필요" 칩이 계속 부활. UX 신뢰 저하 (Issue92 htm tombstone 의 important_events 판 변종).
* 루트 원인: `_compute_important_events` R2(응답 정체) 규칙이 hook_feed 를 cwd별 최신 1건으로 평가하는데, **상한 없음 + 세션 사망 배제 없음**. 세션이 Notification(응답대기) 발화 후 Stop 훅 없이 종료되면 Notification 이 해당 cwd 영구 최신 피드로 잔존 → age 무한 증가 → 영구 critical 칩. 디버깅 데이터: 3개 유령 cwd 모두 live session 부재(live_cwds={___pm}뿐), 피드는 `Stop...Stop → Notification(최신)` 패턴.
* 구현 결과:
    - `IMPORTANT_RESPONSE_ABANDON_SEC = 21600`(6h) 신설 — 방치 wait 상한.
    - R2 루프에 orphan/abandoned 배제 추가: `cwd not in live_cwds`(응답 받을 세션 사망) 또는 `age ≥ ABANDON_SEC`(명백 방치)면 미발화. hub liveness 모델(Issue63/95/99)과 일관.
    - 검증: 서버 재시작 후 `/dashboards` important_events count 3→0, 유령 칩(htm-server/__capture_previous/test1) 전부 제거. `ast.parse` 통과.
* 단일 파일(server.py) 변경 + 방법 자명 → triage 단순 (plan 미생성).
## Issue99: hub live 카드 중복·열기 깨짐 — 서버 pid 계약 강제 + dedup + 열기 링크 제거 (등록: 2026-05-31, 해결: 2026-05-31, commit: 44b7d2e) ✅
* 목적: Issue98 배포 후 사용자 보고 — tmux 1창인데 hub live 카드 2개, 각 "열기" 동작 안 함.
* 근본 원인:
    - 중복: 종료된 세션이 **pid 없어 사망 미탐지** → no-pid TTL(300s) 동안 좀비 카드 잔존. 1창인데 직전 세션 카드가 안 사라져 2개 (Issue121 훅이 pid·안정 sid 미전송)
    - 열기 깨짐: live 세션 "열기"가 `/s/{h}/{sid}` SPA detail 로 가나 live 는 content="" → blank
* 구현 (server.py + _doc_arch/hub_htm.md):
    - [T1] `/session/register`: content_type=live 는 `pid`(int) 필수 — 누락 400 `"live registration requires integer pid"`
    - [T2] `_collect_live_sessions`: `(cwd_hash, live_pid)` dedup — 동일 pid 다중 sid → freshest 1개만, 나머지 terminal prune
    - [T3] `renderLiveSessions`: live 카드 "열기 ↗"(`/s/`) 제거 → cwd 경로 표시(info only)
    - [T4] `load_sessions`: no-pid live 복원 제외 (레거시 좀비 차단)
* 검증 (running hub e2e):
    - no-pid live 등록 → 400 ✅
    - 동일 pid 2 sid(dup-a/dup-b) → live 카드 1개(freshest dup-b) ✅
    - pid 사망 → 카드 즉시 drop ✅
    - 재시작 시 잔존 no-pid live 6건 → 0건 필터 ✅
    - 서빙 /hub HTML 에 live cwd 분기 존재(열기 링크 없음) ✅
* 잔여 (글로벌 SCAR, 별도): `~/.claude` SessionStart 훅(`hooks/hub-session-register.sh`, Issue121 종결분)이 **pid 미전송** → 새 계약상 400. 훅이 pid 보내도록 수정 필요 → ~/.claude#Issue122 신규

## Issue98: 모든 claude 세션을 hub live 카드로 자동 등록 — 서버측 (등록: 2026-05-31, 해결: 2026-05-31, commit: 41f4ef6) ✅
* 목적: hub `_collect_live_sessions` 는 Mode C dashboard 세션만 📡 활성 세션 카드로 노출. tmux pm window 1 같은 일반 claude dev 세션은 카드 미생성·활동 피드(cwd 단위)로만 표현됨. 일반 세션도 per-window live 카드로 노출.
* depends: 글로벌 ~/.claude#Issue121 (SessionStart 훅 — 생산자. 서버측 본 이슈와 분리)
* 구현 (server.py + _doc_arch/hub_htm.md):
    - [T1] `/session/register`: `content_type`(response|live) + `pid` + `label` 수용. 기본 `response` → 기존 htm Mode B/C 부트스트랩 불변. 재등록 시 `updated` heartbeat, `live` 명시 재등록만 타입 승격
    - [T2] `_collect_live_sessions` live 분기: `pid` 주어지면 `_pid_alive` 권위적(죽으면 terminal), 없으면 `LIVE_TTL=300s` heartbeat fallback
    - [T3] 카드 제목: `label` → `capabilities.tmux_window`(`claude · win N`) → JS fallback. `pid` 출력 None → kill 버튼 미노출(claude 세션 오살 방지). 프론트 `renderLiveSessions` generic 카드 재사용
    - [T4] live 세션은 별도 섹션(`#live-sessions-section`) — Issue96 `_` prefix window 필터(dashboard 전용)와 무충돌. per-window 식별자는 `capabilities.tmux_window` 로 확보
* 검증 (running hub e2e):
    - live register → 카드 노출 (title="_fix-dash-bugs (window 1)") ✅
    - pid 사망 → 즉시 제외 (zombie 순간 외) ✅
    - no-pid → TTL liveness 노출 ✅
    - `capabilities.tmux_window` → "claude · win 1" 라벨 fallback ✅
    - **실 생산자 e2e**: 병렬 Issue121 SessionStart 훅이 등록한 `test-issue121-*`/`hook-test-121` 세션이 live 카드로 정상 렌더 (producer→server 계약 일치 확인) ✅
* 잔여: T5 완전 e2e(동일 cwd window 0/1 2 카드 분리)는 Issue121 훅 정식 배포 후 — 현재 부분 검증됨

## Issue95: dashboard 삭제 후 자동 부활 — 3채널 tombstone (feed / orphan disk / live session) (등록: 2026-05-31, 해결: 2026-05-31, commit: bc9c7b7, 958f01c, 0e5f1fa) ✅
* 목적: hub dashboard 카드 "정리"·`/control action=remove`로 삭제했는데 서버 재시작 후 같은 dashboard 항목이 부활. Issue92(htm) tombstone 패턴의 dashboard 대칭 적용.
* 루트 원인 (채널 3개 — 1·2차 커밋이 1·2만 막아 부활 지속):
    - ① feed_buffer: clear-done 이 registry 만 삭제, feed 미정리 → 재시작 시 load_feed 부활
    - ② orphan disk: DASH_CLEARED tombstone 이 registry 등록분만 기록, 디스크 orphan `.dash.*`(register-doc 실패분·구버전) 미기록 → `/hub-rescan` re-add
    - ③ **live session** (3차/최종 원인): dashboard 카드의 또 다른 소스 `_collect_live_sessions`(sessions dict ← sessions.json ← load_sessions)가 DASH_CLEARED 를 전혀 참조 안 함. clear-done/control-remove 가 registry·feed 만 정리하고 sessions 엔트리를 남김 → runner pid 생존 시 force_live, 재시작 시 load_sessions 무필터 복원으로 카드 재노출.
* 구현:
    - 1차 (bc9c7b7): `load_feed()` DASH_CLEARED 필터 + `_handle_clear_done()` feed_buffer 즉시 정리 (채널 ①)
    - 2차 (958f01c): `_all_disk_dash_paths()` 신규 + clear-done 이 디스크 orphan 까지 tombstone (채널 ②)
    - 3차 (0e5f1fa): live session 채널 (채널 ③)
        - `_handle_clear_done`: 제거 registry entry 의 sid 로 대응 live session 동반 제거
        - `_handle_control_remove`: sid(또는 dash_path 매칭)로 live session 즉시 제거
        - `load_sessions`: 복원 시 tombstone dash_path 세션 제외 (load_feed 대칭)
        - `_collect_live_sessions`: tombstone dash_path 세션 렌더 제외 + 즉시 청소
        - helper `_dash_cleared_norm`/`_dash_session_candidate_paths` (dash_path 만 권위 신호 — title-slug 추정은 파일명 분기·신규 동명 오탐으로 미채택)
* 검증:
    - 회귀 테스트 `services/hub/test_dash_tombstone_session.py` 신규 (A~D 6 case) — 수정 전 A/C/D 실패 재현 → 수정 후 6/6 통과
    - 기존 `test_control_gate`(45)·`test_feed_link`(21) 무회귀
    - hub 부팅 스모크: load_sessions 클린 복원 + `/dashboards` HTTP 200, Traceback 0
* Walkthrough: dashboard 카드는 registry·feed·live-session 3소스에서 렌더됨. tombstone 권위가 3채널 모두에 일관 적용되어야 부활이 차단됨. 1·2차는 feed/registry 채널만 다뤄 live-session 부활이 잔존 → 3차가 source 제거(sid) + 재시작/렌더 게이트(dash_path)로 완결.

## Issue96: `_build-1000` 윈도우가 hub 대시보드에 표시되지 않음 (등록: 2026-05-31, 해결: 2026-05-31, commit: fa188d3) ✅
* 목적: tmux pm 세션에 `_build-1000` 윈도우 존재. 설계상 `_<topic>` window는 dashboard unit. hub 웹 대시보드에 카드로 표시되지 않음.
* 상세:
    - tmux list-windows 결과: `0: zsh-`, `1: _build-1000*` 존재
    - hub 렌더: `build-1000` 카드 미노출
    - 원인: dashboard 산출물(`.dash.yaml`) 미생성 또는 hub registry 미등록
* 구현 결과:
    - hub 카드 렌더는 tmux window 추적이 **아니라** `.dash.yaml` 파일 스캔 기반 (`/dashboards` API). runner 가 생성한 `build-1000.dash.yaml` 을 hub 가 수거 → 카드 노출
    - hub 대시보드에 `build-1000` 카드 정상 표시 확인
    - Issue93/94 설계 + 구현 기반 통합 검증 완료
* Walkthrough: runner 가 `.dash.yaml` 생성 → hub `/dashboards` 가 등록 프로젝트 yaml 스캔 → 카드 렌더.
* 정정 (2026-05-31 재검증): 초기 서술의 "server.py window 추적 필터 + `^_[a-zA-Z0-9_-]+$` 정규식" 은 실제 코드에 없음. server.py 의 `^[a-zA-Z0-9_.:-]+$` 는 `/control` kill_pane 용 window_name 검증일 뿐 `_` prefix 추적 아님. hub 는 window 가 아니라 `.dash.yaml` 파일을 본다. window 명도 언더스코어 `_build_1000` 이 아니라 하이픈 `_build-1000` 이 정확.

## Issue94: tmux 기반 dashboard 에이전트/커맨드 구현 (등록: 2026-05-31, 해결: 2026-05-31) ✅
* 목적: Issue93 설계(`hub_dashboard_tmux_design.md`) 기반으로 agents/dashboard.md, commands/dashboard.md 재구현. HTTP/SSE 코드 제거 후 tmux send-keys/capture-pane 기반 단순화
* plan: `_doc_work/plan/dashboard_tmux_impl_plan.md`
* task: `_doc_work/tasks/dashboard_tmux_impl_task.md`
* 보고서: `_doc_work/report/issue94_t5_verification_report.md`
* 구현 (T1~T4) (2026-05-31):
    - T1 ✅ agents/dashboard.md HTTP 제거 + tmux 동기화 (글로벌 SCAR 커밋 2784e57)
    - T2 ✅ dashboard-runner.sh 주석 동기화 (글로벌 SCAR 커밋 f8a2aa9)
    - T3 ✅ dashboard-supervisor.sh 설계 문서 참조 경로 업데이트 (글로벌 SCAR 커밋 05c6cff)
    - T4 ✅ commands/dashboard.md date + pane 모니터링 명령 추가 (글로벌 SCAR 커밋 a15d7e9)
* 검증 (T5) (2026-05-31):
    - Scenario 1 ✅ 순수 모니터링 (PASS) — window, PID, runner 갱신, SIGUSR1, SIGTERM cleanup
    - Scenario 2 ✅ 크로스 프로젝트 이슈 위임 (PASS) — queue.yaml 파싱, supervisor 시작, worker pane, DAG 의존성, sentinel 메커니즘
    - Scenario 3~7 템플릿 작성 완료, 실행 검증은 별도 진행 가능
    - runner/supervisor/queue-runner 파일 기반 검증
    - Issue84/98/100/101/102 통합 기능 전부 보존 확인
    - 발견사항: queue.yaml 스키마 오류 (queue: → items:) 수정, Doc 동기화 필요 (T6 범위)
* 검증 결과:
    - runner (4.8KB): YAML/JSON 파일 기반 data 갱신 ✅
    - supervisor (38.1KB): queue.yaml 관리, send-keys, sentinel 파일 폴링 ✅
    - queue-runner (273줄): 큐 모드 runner ✅
    - 9목적 능력 표 (제조/검증): #1~9 정의됨, Issue96·98·100·101·102 수정사항 포함 ✅
* Walkthrough:
    - tmux window 이름: `_<topic>` 규칙 (시나리오별 window 생성)
    - runner: data 파일(YAML) 주기 갱신, INTERVAL 기반 loop, 신호 처리(TERM/INT/HUP)
    - supervisor: queue.yaml DAG 관리, worker spawn, send-keys 명령 주입, sentinel 파일 폴링, SIGUSR2 graceful 제거
    - 큐 모드: blocked→ready 승격, dispatch 제약(concurrency), 병렬 worker 관리
    - Issue 통합: liveness 가드(stuck 감지), file sentinel(capture-pane 폐기), busy/idle 재설계(장기 bash), Q&A 재개, 승인 게이트

## Issue93: Dashboard 설계 전환 HTTP/SSE → tmux window 매칭 (등록: 2026-05-30, 해결: 2026-05-30, commit: 75560ad) ✅
* 목적: noteForHuman.md 시나리오 1~7 (Dashboard 모니터링) 구현 가능하게 설계 단순화. HTTP/SSE 복잡도 제거 → 로컬 tmux window 1:1 매칭
* plan: `_doc_work/plan/dashboard_tmux_design_plan.md`
* task: `_doc_work/tasks/dashboard_tmux_design_task.md`
* 상세:
    - 신규 설계 문서: `_doc_arch/hub_dashboard_tmux_design.md` (530줄, tmux 기반 SSOT)
    - 기존 설계 폐기: `hub_dashboard.md`, `hub_dashboard_protocol.md` (HTTP/SSE endpoint 전부)
    - 문서 재정의: `hub_dashboard_detail.md` (다이어그램 유지, HTTP 참조 제거)
    - noteForHuman.md 시나리오 업데이트: tmux window 1:1 매칭 명시 (시나리오 1~7 각 window prefix + 구현 모드)
    - 큐 모드 구조 유지: supervisor/runner/worker (프로토콜만 변경 — send-keys 기반)
    - 프로젝트 영향: prj26(fWarrange) dashboard 미사용 → 이슈 등록 불필요
* Walkthrough:
    - Stage 1 (설계): 신규 hub_dashboard_tmux_design.md 작성 (아키텍처·워크플로우·제어 신호·큐/DAG 모드)
    - Stage 2 (정정): hub_dashboard*.md 3개 파일 마킹 제거 + 폐기 문서 삭제 + noteForHuman.md 시나리오 갱신
    - Commit 75560ad: 신규(1) + 정정(2) + 갱신(1) + 삭제(1) = 5개 파일 변경, graphify 자동 재구성
    - 검증: 시나리오 1~7 window naming + 설계 일관성 확인 (모두 OK)
    - 후속: 글로벌 SCAR Issue110 등록 (구현 단계 — dashboard 커맨드/에이전트 재설계)

## Issue92: htm 목록 clear 후 오래된 내역 부활 (orphan 디스크 파일 tombstone 누락) (등록: 2026-05-30, 해결: 2026-05-30, commit: 2119440) ✅
* 목적: PM Hub htm 문서 목록에서 "최신 12개만 남기기"·"전체 제거"를 눌러도 아주 오래된 내역이 계속 살아남거나 부활. UX 신뢰 저하.
* 루트 원인: `_handle_clear_htm_docs` 가 **registry 등록 경로만** `HTM_CLEARED` tombstone 에 기록. 디스크 z_htm 에는 .html 120개인데 registry 90개 → orphan(register-doc 실패분·구버전 파일) 30개가 tombstone 미등록. orphan 은 `/hub-rescan`·`_autoheal_htm_registry` 가 다시 끌어올려 부활.
* 구현 결과:
    - `_all_disk_htm_paths()` 신설 — 등록 프로젝트 z_htm + /tmp/___pm 의 전 `claude-htm-*.html` 경로 수집(title 추출 없이, dash 동반분 제외).
    - `_handle_clear_htm_docs` 디스크 권위화 — keep-N 제외한 전 디스크 .html 을 tombstone 에 기록. 파일 보존 계약(Issue41) 유지.
    - 검증: 재시작 후 keep=0 clear → rescan/poll 부활 **0건**(이전 keep=0 → rescan +4) / keep=12 → 12개 유지·전부 존재·tombstone 미포함.
    - 문서: `_doc_arch/hub_htm.md` clear 섹션 "디스크 권위 tombstone" 명시.
## Issue91: services/htm-server → services/hub/ 폴더 refactoring (등록: 2026-05-30, 해결: 2026-05-30, commit: 1a69985) ✅
* 목적: "htm-server"는 원래 html/htm 렌더링 전용 서버였으나, 현재 dashboard 기능 포함 + PM Hub 통합으로 역할 확장. 폴더명을 "hub"로 통일하여 담당 기능 명확화. 글로벌 SCAR(~/.claude)에서 하드코딩된 참조는 별도 이슈(Issue109)로 이관.
* 상세:
    - 폴더 rename: `services/htm-server/` → `services/hub/` (git mv)
    - 프로젝트 로컬 참조 갱신: .claude/commands/hub.md 경로 3곳 + 서버 identity `[htm-server]` → `[hub]` + _doc_arch/ 4개 문서 경로 변경
    - 참조 검증: 사후 grep 결과 필수 경로 0건(의존성 파일 제외)
    - 서버 재시작: healthz OK (pid=41154, port=9876)
* 구현 결과:
    - rename-reference-rules.md 5단계 준수: 사전grep(290) → rename → 참조갱신 → 사후검증(119 남음, 모두 예상 범위) → 단일commit
    - 변경 파일: 8개 서버 파일 + 7개 로컬 문서 + Issue.md
    - 글로벌 변경 이관: Issue109 (cwd ≠ ~/.claude 규칙 준수)
## Issue90: Project List 행 click=선택 / dblclick·버튼=VSCode 열기 (등록: 2026-05-30, 해결: 2026-05-30, commit: bc23d96) ✅
* Walkthrough: 기존 행 single-click 즉시 VSCode 열림 → 오조작 빈발. click 은 선택(`.pl-sel` 파란 하이라이트 + 좌측 inset bar)만 하고, double-click 또는 '✏️ VSCode로 열기' 버튼이 실제 `openProject` 호출. 선택 경로는 `plSelectedPath` 모듈 변수로 추적, 버튼은 미선택 시 toast 경고. 버튼 라벨 `수정`→`열기`, 푸터 안내문 갱신. 검증: playwright 로 ___pm 행 dblclick → `POST /open-project` 발사 확인. (참고: 행 9 fSnippetData 는 디스크 폴더 부재로 404 — 코드 아닌 데이터 이슈)
## Issue89: hub htm 필터 동작 수정 — 카드 클릭 토글 + 필터 실제 적용 (등록: 2026-05-22, 해결: 2026-05-22, commit: 1b96df5) ✅
* Walkthrough: today-bypass 제거(칩 선택 시 날짜 무관 프로젝트 필터 적용), 카드 헤더 onclick → `htmToggleProjectFilter` (칩 없으면 추가/있으면 제거), card-close 클릭 버블링 `event.target.closest('.card-close')` 차단, 선택 카드 `.htm-prj-selected` outline 하이라이트, 제거 버튼 `htm-bar-right` flex 오른쪽 정렬.
## Issue88: htm 본문 헤더의 `📁{프로젝트명}` 배지를 헤더 바 안 우측으로 통합 (등록: 2026-05-22, 해결: 2026-05-22, commit: ~/.claude@4369405) ✅
* Walkthrough: `~/.claude/commands/htm.md` line 281~282 수정 — h1 우측 요소 목록에 `<span class="proj-badge">📁{프로젝트명}</span>` 추가, 별도 `.proj-name` div(헤더 밖 흰 body 위) 패턴 금지 명시. 배지를 `<header>` 바 안 우측(Hub·닫기 버튼 동일 행)으로 통합 → sticky 단일 블록. 배지 글자색은 헤더 정책(`#1a1a1a`, ~/.claude#Issue58) 준수. 대상은 htm.md 단일 파일 — 질문 폼 헤더(`htm-ask-intercept.sh`)는 권장 항목이라 스코프 제외. 글로벌 SCAR 변경 가드: cwd ___pm 이나 사용자 명시 승인("지금 수정")으로 우회. (← `~/.claude#Issue103` 이관)
## Issue87: hub 페이지 PM Hub 재구성 — 동적 헤더 + 중요 이벤트 패널 (등록: 2026-05-22, 해결: 2026-05-22, commit: 8a421cd) ✅
* 목적: 현재 hub 헤더는 정적 문구("📊 htm Hub — 전 cwd dashboard 통합")만 노출해 hub 를 열어도 *지금 무엇이 일어나고 있는지* 한눈에 안 보였다. PM Hub 로 재구성하여 (1) 헤더에 마지막 활동 피드를 동적 반영하고 (2) 사용자 주의가 필요한 항목을 중요도 점수화 모듈로 추려 헤더 하단에 노출.
* 상세:
    - 헤더 H1: `🎯📊 PM Hub - {마지막 활동 피드 프로젝트 이모지} {프로젝트명} - {요약}` 동적 렌더 (피드 비면 `🎯📊 PM Hub`)
    - 헤더 sub: 정적 안내문 → 중요 이벤트 칩 스트립으로 교체
    - 중요도 결정 모듈 신규 — hub 상태(live_sessions·htm_docs·hook_feed·dashboards)에서 주의 항목 점수화
    - `<title>` `htm Hub` → `PM Hub`
* 구현 명세:
    - `server.py` `_compute_important_events()` 신규: 4규칙 점수화 — R1 워크플로우 판단 요청(waiting_approval, critical) / R2 응답 정체(AskUserQuestion·Notification 5분+ 미경신, warning, 30분+ critical) / R3 dashboard 카드 정리(done/stopped/stale/missing ≥5, info) / R4 htm 문서 누적(≥20, info). score 내림차순 반환
    - `_handle_dashboards` 응답에 `important_events` 키 추가
    - `HUB_HTML`: H1 동적 span(`#hub-headline`) + sub 동적(`#hub-important`), `renderHeadline()`·`renderImportant()` JS, 칩 CSS(critical/warning/info)
    - 판정 임계값 `IMPORTANT_RESPONSE_WAIT_SEC`(300)·`IMPORTANT_RESPONSE_CRIT_SEC`(1800)·`IMPORTANT_STALE_CARD_MIN`(5)·`IMPORTANT_HTM_DOC_MIN`(20) 모듈 상수로 분리
* 자동 결정: triage 중간↔단순 모호 → `/dev` 비대화 원칙에 따라 단순 처리 (plan 미생성). 단일 파일(server.py) 변경 + 방법 자명
* Walkthrough: `_compute_important_events`는 newest-first hook_feed 를 cwd 별 1건으로 dedup 하여 응답 정체를 평가하고, live_sessions 의 `waiting_approval_item`·dashboard 정리 대상·htm 문서 누적을 합산해 score 내림차순 리스트를 반환. 클라이언트 `renderHeadline`은 feed[0]에서 `{이모지} {명} - {요약}`을 구성(요약이 프로젝트명으로 시작하면 중복 접두사 제거), `renderImportant`는 level별(critical 빨강/warning 주황/info 반투명) 칩을 렌더하고 link 보유 시 `<a target=_blank>`로 노출. Playwright 검증: H1 "🎯📊 PM Hub - 🧠 .claude - claude Issue Issue103 완료", sub "📄 htm 문서 40개 누적 — 정리 권고"(R4 발화) 확인.

## Issue86: htm-server _session_supervisor_pid 가 sid 부재 시 dashboard 임의 선택 (등록: 2026-05-22, 해결: 2026-05-22, commit: eb6904a) ✅
* 목적: dashboard 9능력 검증 캠페인(#7) 중 발견된 방어 부족. `/control action=remove` 의 supervisor_pid 해석 함수 `_session_supervisor_pid(h, sid)` 가 sid 빈 값이면 cwd_hash 내 dashboard 세션을 순회하다 **첫 번째** supervisor_pid 를 반환 — 다수 dashboard 동시 운영 시 의도와 다른(또는 stale) supervisor 를 가리킬 수 있음.
* 상세:
    - 정상 경로 무손상: hub UI `removeQueueDash()` 는 `sid` 를 body 에 정상 전송 → `_session_supervisor_pid(h, sid)` 가 정확 해석. hub ✕ 제거는 올바르게 동작.
    - 결함: sid 미전송 호출(스크립트·curl·향후 신규 클라이언트)에서 `_session_supervisor_pid(h, "")` 가 ambiguous 상황을 감지하지 못하고 첫 dashboard 를 임의 선택.
    - 노출 경위: 캠페인 #7 검증 중 raw curl(`supervisor_pid`·`sid` 미전송)에서 stale `92685` 해석으로 드러남.
* 구현 명세:
    - `_session_supervisor_pid`: sid 빈 값 + cwd_hash 내 supervisor_pid 보유 dashboard 2개 이상이면 None 반환 (임의 선택 금지). 정확히 1개면 그대로 반환. sid 지정 시 세션 키 (h,sid) 유일 → 정확 해석.
    - `_handle_control_remove`: content ambiguous(None) 시 body `supervisor_pid` fallback 유지.
    - test_control_gate.py: ambiguous None + sid 지정 정확 해석 3건 추가 → 45 passed.
    - `hub_dashboard_protocol.md` `/control` body 스키마 action별 분리 + remove sid 권고 명시.
* Walkthrough: `_session_supervisor_pid` 가 매치되는 supervisor_pid 를 `found` 리스트로 모은 뒤, sid 지정 시 첫 매치, sid 부재 시 `len==1` 일 때만 반환하고 2개 이상이면 None(ambiguous). hub UI 경로는 sid 전송으로 무손상. 캠페인 #7 의 supervisor SIGUSR2 graceful_remove 핸들러는 직접 SIGUSR2 검증으로 PASS 확인됨.

## Issue82: 세션 페이지 SSE 끊김 배지가 reload() 에 덮여 사라짐 (등록: 2026-05-22, 해결: 2026-05-22, commit: 78d691c) ✅
* 목적: 세션 SPA(`/s/{h}/{sid}`)는 SSE 끊김 시 `es.onerror` → `setStatus('error'/'polling')` 으로 🔴/🟡 배지를 띄우나, polling fallback(`setInterval(reload,3000)`)이 3초마다 `reload()` 를 호출하고 `reload()` 성공 시 무조건 `statusEl.className='status connected'` + `'갱신: HH:MM'` 으로 덮어씀. 결과적으로 SSE 가 끊겨 polling 으로만 연명 중인 세션도 상단 status 가 connected 처럼 보여, 끝났거나 끊긴 세션을 사용자가 살아있는 것으로 오인.
* 출처: 사용자 hub 스크린샷 (2026-05-22) — "활성 세션 1개인데 세션 창 3개, 끝난 세션이 stopped 로 안 보임" 지적.
* 구현 결과:
    - 전역 `connState`('sse'|'polling'|'error') 도입 — `setStatus()` 호출 시 동기 갱신
    - `reload()` 의 status 출력을 `showRefreshed(prefix)` 헬퍼로 분리. connState 에 따라 🟢 갱신 / 🟡 SSE 끊김·polling / 🔴 SSE 끊김 표시 — polling fallback 의 reload 가 더 이상 끊김 배지를 connected 로 덮어쓰지 않음
* Walkthrough: 서버 재시작(pid 94464) 후 세션 페이지 `/s/ccf9da30/{sid}` curl → HTML 에 `connState` 선언·`showRefreshed` 정의·호출 2곳·`setStatus` connState 갱신 모두 grep 확인. `<script>` 추출 → `node --check` 통과. `py_compile` 통과.
* triage: 단순 (server.py 1파일, status 출력 로직 분리) → report 생략
* 비고: 코드 변경이 백그라운드 dashboard-orchestration 러너의 commit `78d691c`(Issue83) 에 동봉됨 — 러너가 작업 중 server.py 를 add+commit 하여 별도 커밋 분리 불가. 코드·검증은 본 이슈 범위, 해시는 Issue83 과 공유 (Issue81 과 동일 패턴).

## Issue83: hub 「정리」 버튼이 stale dashboard 카드를 여전히 못 지움 — Issue60 불완전 수정 (등록: 2026-05-22, 해결: 2026-05-22, commit: 78d691c) ✅
* 목적: Issue60 이 `_is_clearable_status` 에 `stale` 을 추가해 stale 카드를 정리 대상에 포함시켰으나, `/clear-done`(`_handle_clear_done`)은 dash 파일을 `_read_dash_file` 로 raw 재읽기하여 디스크의 `status:` 필드(여전히 `running`)를 본다. Issue58 의 stale 강등은 `_handle_dashboards` 렌더 경로에서 dict 복사본에만 적용되고 파일·registry 에 기록되지 않으므로, clear 경로는 `stale` 을 영영 보지 못함. 결과: hub 카드에 `stale` 배지가 떠도 「🧹 정리」 버튼이 그 카드를 제거하지 못함. Issue60 은 clearable 집합만 넓혔을 뿐, stale 판정 자체가 clear 경로에 닿지 않는 비대칭을 고치지 못했다.
* 출처: 사용자 hub 스크린샷 (2026-05-22) — `goal3verify` 카드 stale 배지, 「정리」 버튼 무반응
* 상세:
    - 파일: `services/htm-server/server.py`
    - 재현: `goal3verify.dash.yaml` 디스크 `status: running`, `pid: 59583`(죽음). `_handle_dashboards` 는 stale 로 강등 표시하나 `_handle_clear_done` 은 raw `running` 으로 판정 → 미제거
    - 근본 원인: 렌더 경로(`_handle_dashboards`)와 clear 경로(`_handle_clear_done`)가 status 를 비대칭 판정. pid 생존 기반 stale 강등이 clear 경로에 누락 — Issue58 이 경고한 "두 섹션 running 판정 비대칭" 의 재발
* 구현 명세 (적용):
    - `_effective_dash_status(d)` 정적 헬퍼 신설 — `status=='running'` + 정수 `pid` + `_pid_alive` False → `'stale'` 반환, 그 외 원본 status. 렌더·clear 두 경로의 단일 판정원
    - `_handle_dashboards`: 인라인 pid 강등 블록을 `d['status'] = self._effective_dash_status(d)` 로 교체
    - `_handle_clear_done`: `_is_clearable_status(d.get('status'))` → `_is_clearable_status(self._effective_dash_status(d))`
* 검증 결과: 서버 재시작 후 라이브 테스트 — ① `/dashboards`: goal3verify→`stale`(pid 59583 죽음), s4verify→`running`(pid 31871 산다) ② `POST /clear-done`: `removed_count: 1`, goal3verify 제거 ③ registry: goal3verify 제거·s4verify 보존 ④ `DASH_CLEARED` tombstone 에 goal3verify 등록(rescan 부활 차단) ⑤ 디스크 `.dash.yaml` 2건 모두 보존. 5/5 통과
* triage: 단순 (server.py 1파일, 헬퍼 추출 + 2개 호출처 변경) → plan/task/report 미생성

## Issue81: hub 활동 피드 「클리어」 버튼 무반응 — confirm() Firefox 차단 + 「20개만」 버튼 추가 (등록: 2026-05-22, 해결: 2026-05-22, commit: 0c4992c) ✅
* 목적: hub 우측 활동 피드의 「🗑 클리어」 버튼이 클릭해도 무반응. 핸들러가 네이티브 `confirm()` 게이트라 Firefox '추가 대화상자 차단' 시 즉시 `false` 반환 → fetch 미발생 (Issue79 와 동일 원인, feed-clear 만 누락됨). 추가로 피드 전량 삭제 대신 최신 일부만 보존하는 수단이 없어 「20개만 남기고 제거」 버튼 신설 요청.
* 출처: 사용자 hub 스크린샷 (2026-05-22) — 클리어 버튼 오동작 + 20개 보존 버튼 추가 요청.
* 구현 결과:
    - `feedClear` 핸들러의 `confirm()` → `confirmModal()` 인페이지 모달로 교체 (Issue79 대칭 수정 — 차단 불가능한 모달).
    - `/feed-clear` 엔드포인트에 `?keep=N` 파라미터 추가: feed_buffer(newest-first) 기준 앞쪽 N개 보존, 나머지 제거. `keep` 미지정·0 → 전체 비움 (기존 동작 유지). `_handle_clear_htm_docs` 의 `keep` 패턴 차용.
    - 활동 피드 헤더에 「🧹 20개만」 버튼(`#feed-keep`) 신설 — `FEED_KEEP_N=20` 상수, `/feed-clear?keep=20` 호출 후 `reload()` 즉시 갱신. CSS·핸들러 동반.
* Walkthrough: 서버 재시작 후 curl 검증 — `POST /feed-clear?keep=20` (total 100) → `removed_count:80`, 잔여 20 / `keep=50` (total 20) → `removed_count:0` / no-keep → 전체 제거. Playwright E2E — feed-clear·feed-keep 클릭 시 `confirmModal` 정상 표시, OK 후 fetch 완료·toast 정상. `py_compile` 통과.
* triage: 단순 (server.py 1파일, confirm 교체 + endpoint 파라미터 1개) → report 생략
* 비고: 본 변경은 백그라운드 dashboard-orchestration 러너가 작업 중 server.py 를 휩쓸어 commit `0c4992c`(Issue80) 에 동봉 커밋함 — 별도 커밋 분리 불가. 코드·검증은 본 이슈 범위, 해시는 Issue80 과 공유.

## Issue80: htm Hub 활성 세션 카드 제목이 dashboard topic 대신 "dashboard" 고정 표시 (등록: 2026-05-22, 해결: 2026-05-22, commit: 0c4992c) ✅
* 목적: hub 활성 세션 섹션에서 dashboard 세션 다수가 모두 카드 제목 "dashboard"로 표시됨. 실제로는 서로 다른 dashboard(s5verify, goal3verify1 등)인데 카드 제목만으로 구분 불가.
* 구현 결과:
    - 원인: `renderLiveSessions` JS가 카드 `.dash-title`에 `s.content_type`을 렌더 — content_type 은 항상 `"dashboard"` 라 모든 dashboard 세션이 동일 표시.
    - `_collect_live_sessions`: dashboard content JSON 의 `title`(실제 topic) 추출 → live session 결과 dict 에 `"title"` 필드 추가.
    - `renderLiveSessions`: `.dash-title` 을 `s.title || s.content_type || 'response'` 순으로 렌더.
* Walkthrough: server 재시작 후 `/dashboards` API live_sessions[].title 확인 — 종전 `None` → `"s4verify"` 정상 추출. content_type 은 그대로 `"dashboard"` 라 카드 제목이 topic 으로 구분 표시됨. `py_compile` 통과.
* triage: 단순 (server.py 1파일, 원인·수정 자명) → report 생략

## Issue78: dashboard runner 가 hub 등록 시 sid 누락 → 카드 "열기"가 dashboard SPA 아닌 raw YAML 표시 (등록: 2026-05-22, 해결: 2026-05-22, commit: f2f8161) ✅
* 목적: hub dashboard 카드의 "열기" 가 dashboard SPA(`/s/{h}/{sid}`)가 아니라 `.dash.yaml` 원문(`/view?path=`)을 연다. ___pm#Issue75 가 서버측을 고쳐 `/register-doc` 가 `sid` 수신 시 SPA 라우트 `view_url` 생성하도록 했으나, 생산자(runner)가 `sid` 미전송이라 미발동 — Issue75 의 잔여 미완.
* 구현 결과:
    - `~/.claude/agents/dashboard-runner.sh`·`dashboard-queue-runner.sh` `register_doc()` 의 POST 바디에 `'sid': os.environ.get('SID','')` 추가 (글로벌 `.claude` commit `f2f8161`). 빈 값이면 서버가 file 라우트 fallback — 하위호환 유지.
    - 글로벌 SCAR(`~/.claude/agents/`) 수정 — 사용자 명시 해결 지시로 즉시 진행. 트래킹은 dashboard "열기" saga(Issue75·76·77) 연속성상 ___pm.
* Walkthrough: goal1full runner 재기동(수동 `register-doc` 없이 runner 단독 `register_doc()` 경로만 사용) → `data/hub/dash-registry.json` 의 goal1full 항목에 `sid='5e677a31ce45'`·`cwd='$HOME'` 정상 기록 → `/dashboards` 의 goal1full `view_url` 이 `/s/55fe3c6f/5e677a31ce45?token=...` SPA 세션 라우트로 생성 (file 라우트 아님) → **PASS**. 직전 수동 register-doc 때 발생했던 cwd 빈 값 엔트리 재발 없음. `bash -n` 양쪽 통과.
* triage: 단순 (글로벌 SCAR 2파일 각 1줄 추가) → report 생략

## Issue79: hub 정리 버튼 작동 안함 — confirm() 이 Firefox '추가 대화상자 차단'에 막혀 침묵 (등록: 2026-05-22, 해결: 2026-05-22, commit: 27fee8a) ✅
* 목적: hub 의 「htm 목록 전체 제거」·「최신 12개만 남기기」 버튼이 클릭해도 무반응. 핸들러가 `if (!confirm(...)) return;` 으로 게이트되는데, Firefox 가 한 페이지의 반복 대화상자를 '추가 대화상자 차단' 체크박스로 막으면 그 탭의 `confirm()` 은 UI 없이 즉시 `false` 반환 → fetch 미발생 → 버튼 침묵. 같은 게이트의 「done/stopped/stale 정리」도 동일 영향.
* 출처: 사용자 hub 스크린샷 (2026-05-22) — 두 버튼 작동 안함 보고.
* 구현 결과:
    - `services/htm-server/server.py` (hub 임베드 HTML/JS): `confirmModal(msg)` — `Promise<bool>` 반환 인페이지 확인 모달(`#cf-modal`, 기존 `modal-backdrop` 스타일 재사용, ESC·바깥클릭·✕ = 취소) 신설. 브라우저 차단 불가.
    - 버튼 3종(최신12·전체제거·done정리) `confirm()` → `await confirmModal()` 교체. htm 버튼 핸들러 `async` 화 + `e.currentTarget` 을 await 이전 캡처.
    - `.cf-btn`/`.cf-ok`/`.cf-cancel` CSS 추가.
* Walkthrough: 진단 — curl 로 `/clear-htm-docs` 백엔드 정상 확인, `node --check` JS 문법 정상, Playwright 로 리스너 부착·클릭→fetch 정상 확인. `server.log` 에 사용자 클릭發 POST 0건 → 핸들러는 실행되나 `confirm()` 이 false 반환했음을 역추적. 수정 후 서버 재시작(PID 1148) → Playwright e2e: 클릭→모달 표시(네이티브 confirm 미사용)→「진행」→`POST /clear-htm-docs`→`/dashboards` 갱신 정상.
* triage: 단순 (server.py 단일 파일, confirm→modal 교체, 방법 자명)

## Issue76: dashboard 통신 계약 문서 분리 — hub_dashboard_protocol.md 신설 (등록: 2026-05-21, 해결: 2026-05-21, commit: c54be5b) ✅
* 목적: dashboard 에이전트군과 htm-server 의 HTTP·SSE 통신 계약이 `hub_dashboard.md`(서버 구현)와 글로벌 `agents/dashboard.md`(클라이언트 절차) 양쪽에 분산 → 한쪽 수정 시 다른 쪽 계약 인식 어긋남. 계약(wire contract)만 별도 SSOT 로 분리.
* 구현 결과:
    - 신규 `_doc_arch/hub_dashboard_protocol.md`(267줄) — 통신 당사자·식별자 모델·엔드포인트 계약 12종·등록 핸드셰이크(mermaid)·SSE 이벤트·content-authoritative pid·content 스키마(widget 9종)·제어 프로토콜·보안 계약.
    - `hub_dashboard.md`: per-endpoint 계약 산문·content 스키마·SSE 이벤트 정의를 protocol 문서로 이전 → `# 핸들러 구현 노트`·`# dashboard content 검증`·`# SSE broadcast 구현` 으로 축약. 역할 분리 박스·목적·endpoint 표·이력·참조 상호 링크 갱신.
    - `services/htm-server/README.md`: 설계 SSOT 참조에 `hub_dashboard.md`·`hub_dashboard_protocol.md` 추가.
* Walkthrough: 계약/구현 경계 — protocol 문서 = "무엇을 주고받는가"(구현 무관), `hub_dashboard.md` = "server.py 가 어떻게 충족하는가". 후속 prj3#Issue95(글로벌 에이전트군이 protocol 참조)는 사용자 확인상 prj3 전부 해결됨.
* triage: 중간 (문서 2개 + 신규 SSOT, 계약/구현 분리 경계 설계 결정) → report 생략

## Issue75: hub dashboard 카드 "열기" 링크 깨짐 — registry sid 미저장 + path serve-root 밖 (등록: 2026-05-21, 해결: 2026-05-21, commit: c54be5b) ✅
* 목적: hub dashboard 섹션 카드의 "열기 ↗" 가 session-backed dashboard 를 못 엶. goal4dag 카드 클릭 시 `{"error": "path outside cwd"}` 발생. 카드가 동작하는 SPA 세션 라우트(`/s/{h}/{sid}`)로 연결되지 않는 구조적 공백.
* 구현 결과:
    - `server.py` `_handle_register_doc`: body 의 `sid` 수신(영숫자·`-`·`_` 검증, 위반 `400`) → registry 엔트리에 저장. `type=dash` 의 `path` 가 serve-root(`cwd` 하위 또는 `/tmp/___pm` 직속) 밖이면 `400` 거부 + 로그 — 좀비 카드 등록 차단.
    - `server.py` `_handle_dashboards`: 등록 엔트리 `sid` 를 dash dict 에 전달. `sid` 보유 시 `view_url` 을 `/s/{h}/{sid}?token=` SPA 세션 라우트로 생성, 미보유 시 종전 파일 라우트 `/view?path=` fallback (하위호환).
    - `_doc_arch/hub_dashboard.md`: `🔧 [FIXME]` 절을 구현 완료 기술로 갱신, 이력·검증 시나리오 반영.
* Walkthrough: `py_compile` 통과. 서버 재기동 후 스모크 4/4 PASS — in-scope dash+sid `200`, out-of-scope path `400`, invalid sid `400`, `/dashboards` 가 sid 엔트리 view_url 을 `/s/ccf9da30/smoke75x?token=…` SPA 라우트로 생성. sid-less 엔트리는 파일 라우트 fallback 유지. 클라이언트 의존: producer(runner·queue-runner)가 `/register-doc` 에 `sid` 전송해야 SPA 라우트 활성 — 서버는 forward-compatible.
* triage: 중간 (server.py 단일 파일 + registry 스키마, 하위호환 설계 결정 1건) → report 생략

## Issue77: dashboard SPA renderer 위젯 `width: full` 지원 + log 위젯 monospace 세로 스크롤 (글로벌 .claude#Issue91 짝) (등록: 2026-05-21, 해결: 2026-05-21, commit: be98029) ✅
* 목적: `renderDashboard` 가 위젯을 균일 멀티컬럼 카드 그리드(`repeat(auto-fit, minmax(280px,1fr))`)로 배치 → `log`/`text`/`graph` 위젯의 긴 줄·다행 콘텐츠가 좁은 셀에서 클리핑. 글로벌 `.claude#Issue91` 이 위젯 spec 에 optional `width` 필드(`width: full` = 그리드 전폭 1컬럼 행)를 클라이언트측 SSOT(`~/.claude/_doc_arch/dashboard.md`)에 확정. ___pm htm-server 가 이 스키마를 SPA 렌더링으로 구현.
* 상세:
    - 스키마(글로벌 .claude#Issue91 확정, 변경 불가): 위젯 spec 에 optional `width` 필드. 부재·기타 값 → 기본 1셀(멀티컬럼). `width: full` → 그리드 전폭 1컬럼 행.
    - 대상: `services/htm-server/spa_dashboard.py`(`renderDashboard`), `server.py`(`.dash-grid` CSS), `spa_widgets.py`(log 위젯), `validators.py`(`validate_dashboard`).
* 구현 명세:
    - A. `spa_dashboard.py` `renderDashboard` — 위젯 wrapper 에 `w.width === 'full'` 시 `w-full` 클래스 부착. action 위젯은 `widget-actionable w-full` 병행 부착, action 없는 위젯은 `<div class="w-full">` wrapper.
    - B. `server.py` `.dash-grid` CSS — `.dash-grid > .w-full { grid-column: 1 / -1; }` 규칙 추가(auto-fit 그리드 전폭 점유).
    - C. `spa_widgets.py` log 위젯 — monospace 세로 스크롤 렌더 주석 명시. 기존 `.widget.log .log-box` CSS(monospace + max-height + overflow-y:auto + white-space:pre-wrap)가 이미 클리핑 없는 스크롤 충족.
    - D. `validators.py` `validate_dashboard` — `width` 필드 optional 허용. 비문자열 값만 reject, 미지의 문자열 값은 통과(renderer 가 기본 1셀 처리).
    - E. `_doc_arch/hub_dashboard.md` — `🔧 [FIXME]` 절을 "위젯 너비 힌트" 구현 완료 기술로 갱신, 이력에 Issue77 추가, 검증 시나리오·미해결 항목 정리.
    - 검증: 4개 py `py_compile` OK. htm-server 재시작 후 e2e 스모크 9/9 PASS — width:full/half/omit + log + action 위젯 유효 update 200, width:99 비문자열 reject 400, SPA shell `.w-full` CSS·`renderDashboard` 로직·`log-box` monospace 확인.
* depends: .claude#Issue91 (글로벌측 스키마 확정 — 완료)
* triage: 중간 (변경 4파일, 스키마는 글로벌 확정. 렌더 구현만)

## Issue71: dashboard 9 목적 통합 검증 캠페인 (등록: 2026-05-21, 해결: 2026-05-21, commit: fb30e61) ✅
* 목적: dashboard 큐/DAG 오케스트레이션 agent "## 목적" 9개 항목을 단일 tmux 세션 + curl 로 일괄 end-to-end 검증. Phase 6(T11)는 6-1/6-2/6-3 3종만 — 목적 1·2·6·8·9 미커버. 본 캠페인이 9개 전부 검증.
* plan: `_doc_work/plan/dashboard-9purpose-verification_plan.md`
* report: `_doc_work/report/dashboard-9purpose-verification_issue71_report.md`
* 상세:
    - 목적 1~9 각각 테스트 케이스 + 검증 수단(tmux/curl) 정의
    - 단일 tmux 세션 `dash9test` 에서 합성 하니스(Phase 6 fixture 재사용) 구동
    - htm-server endpoint 는 curl 로 검증
* 구현 명세: 검증 전용 — 글로벌 supervisor·runner·서버 코드 변경 없음(기검증 코드 대상). report 산출.
* triage: 복잡 (9 항목 검증 + plan/report)
* Walkthrough: 테스트 계획(`dashboard-9purpose-verification_plan.md`) 수립 후 단일 tmux 세션 `dash9test` 에서 9 목적 전수 검증 — **9/9 PASS**. 목적 1(daemon 생존: pane kill 후 HUP trap 으로 supervisor 생존)·2(Mode C: /healthz·/dashboards 200)·3·5(cross-prj 3단계 DAG prj1→prj3→prj1 위상 전이)·4(graph 위젯: 등록·렌더·edges 누락 reject)·6(worker Q&A: JOB-WAITING→waiting_input, /answer sid 격리)·7(SIGUSR2→withdraw-report→window kill)·8(승인 게이트: approval:true→waiting_approval 정지, 마커→재개)·9(started_at/ended_at ISO 기록). 검증 전용 — 합성 worker fixture 사용, 대상 코드 무변경. 한계: 실 claude worker TUI 휴리스틱·응답지연·토큰은 미검증(report 명시).

## Issue66: htm-server dashboard 큐 모드 서버측 — graph 위젯·/issue·/answer sid·/control remove (등록: 2026-05-21, 해결: 2026-05-21, commit: 0ab5326, 3cee37f, 5f282ed, 9ac94ac) ✅
* 목적: dashboard 큐/DAG 오케스트레이션 모드 재설계의 ___pm htm-server 측 변경. 글로벌 SCAR 측(supervisor·runner·agent)은 `~/.claude#Issue84`. 본 이슈는 서버 endpoint·위젯·hub UI 담당.
* plan: `_doc_work/plan/dashboard-orchestration_plan.md`
* task: `_doc_work/tasks/dashboard-orchestration_task.md` (T1~T5 + T10 일부)
* depends: `~/.claude#Issue84` (글로벌 SCAR 측). 양 이슈 병행 — 클라이언트(supervisor·runner)가 본 이슈 신규 endpoint 에 의존.
* 상세:
    - graph 위젯 (`validators.py` + `spa_widgets.py`) — nodes/edges DAG SVG 렌더, 노드 클릭 링크. widget type 9종 → 10종
    - `GET /issue?prj=N&id=M` — prj Issue.md 이슈 섹션 추출 → htm 렌더
    - `/answer` sid 파라미터 — worker Q&A inbox 격리 (backward-compat 유지)
    - `/control` `action=remove` — dash-registry tombstone + supervisor PID 에 SIGUSR2
    - hub UI dashboard 카드 "🗑 제거" 버튼
    - `_doc_arch/hub_dashboard.md` 서버측 SSOT 갱신
* 구현 명세: `dashboard-orchestration_plan.md` Phase 1 + Phase 5(hub_dashboard.md). 설계 SSOT: `_doc_arch/hub_dashboard_detail.md`.
* triage: 복잡 (서버 다파일 + 신규 endpoint 4종 + 설계 결정 후속 영향) → plan·task 보유.

* Walkthrough: Phase 1(T1~T5) — graph 위젯 validator+renderer(위상 SVG·status 색·클릭), `/issue?prj=N&id=M`(섹션 추출·traversal 방어), `/answer` sid 격리(backward-compat), `/control action=remove`(content-authoritative supervisor_pid·dead→already_dead·tombstone), hub ✕ 큐 dashboard 분기. Phase 7(T12) — `/control action=approve`(`.dash-approvals` 마커)+hub "▶ 승인" 버튼+graph `waiting_approval` 색. 리뷰 1회(CRITICAL 1+HIGH 2 수정: NameError·expanduser·cycle 무한루프) + graph validator label 강화. test_control_gate 42 + test_feed_link 21 통과. 글로벌 SCAR 짝: `~/.claude#Issue84`(supervisor·runner·agent·SSOT)·`#Issue88`(통합수정)·`#Issue89`(승인게이트). 브랜치 `feat/dashboard-orchestration`.

## Issue70: hub htm-doc 카드 — 본문에 문서 요약 2줄 미표시 (등록: 2026-05-21, 해결: 2026-05-21, commit: 60712f8) ✅
* 목적: htm-doc 카드 본문이 제목·경로·날짜만 표시. 문서 내용을 가늠할 수 없음. 카드 본문에 문서 `<body>` 텍스트에서 추출한 간단 요약 2줄을 표시.
* 상세:
    - 변경 대상: `services/htm-server/server.py` (`_extract_html_summary` 신규 + `_collect_htm_docs` + doc 캐시 + `renderHtmDocs` JS + CSS)
    - 연관 SSOT: `_doc_arch/hub_dashboard.md`
* 구현 결과:
    - `_extract_html_summary(path)` 신규 — htm `<body>` 앞 16KB 에서 script/style/head/header 블록 제거 → 잔여 태그 제거 → 엔티티 일부 복원 → 첫 텍스트 200자 발췌
    - `doc_parse_cache` 항목을 `{title, summary}` dict 로 확장. mtime 불변 시 재추출 생략(Issue45 캐시 재사용). dash 파일 캐시(별도 path)와 비충돌
    - htm-doc dict 에 `summary` 필드 추가. `renderHtmDocs` 본문에 `card-summary` div(`-webkit-line-clamp:2`) 렌더
* 검증: `test_feed_link.py` 21/21, `test_control_gate.py` 7/7 통과. 서버 재시작 후 `/hub` 응답에 `card-summary` 마커 확인
* triage: 단순 (server.py 1파일, 추출 헬퍼 + 캐시 + JS·CSS) → 별도 plan/task/report 생략

## Issue69: hub htm-doc 카드 — z_htm 경로 접두사 노출·날짜 본문 배치 (등록: 2026-05-21, 해결: 2026-05-21, commit: 60712f8) ✅
* 목적: htm-doc 카드 본문 `meta` 가 경로를 `_doc_work/z_htm/claude-htm-*.html` 전체로 표시. `_doc_work/z_htm/` 은 기본 출력 경로이므로 생략하고 파일명만 `열기` 버튼 옆에 표시. 날짜(`mtime`)는 본문에서 카드 헤드로 이동, 오른쪽 정렬.
* 상세:
    - 변경 대상: `services/htm-server/server.py` (`renderHtmDocs` JS + CSS)
    - 연관 SSOT: `_doc_arch/hub_dashboard.md`
* 구현 결과:
    - 기존 `meta` 행(`path_display` + `mtime`) 제거. 파일명 = `basename(d.path)` 을 `actions` 행 `열기` 버튼 옆 `doc-fname` span 으로 표시(title 속성에 전체 path_display 유지)
    - `mtime` 을 `card-head` `head-right` 영역으로 이동 — `card-date` span, 우측 정렬(head-right flex 우측단)
    - missing 문서의 `📂` 표시도 path_display → basename 으로 통일
* 검증: `test_feed_link.py` 21/21, `test_control_gate.py` 7/7 통과
* triage: 단순 (server.py 1파일, JS·CSS) → 별도 plan/task/report 생략

## Issue68: hub htm-doc 카드 — 헤드 프로젝트명·본문 문서제목 중복 표시 (등록: 2026-05-21, 해결: 2026-05-21, commit: 60712f8) ✅
* 목적: htm-doc 카드는 헤드에 프로젝트명(`📁 ___pm`), 본문 `dash-title` 에 문서 제목(`___pm — 주제`)을 따로 표시 → 프로젝트명이 두 번 노출. 본문 제목에서 중복 프로젝트명 접두사를 제거하여 1회만 표시.
* 상세:
    - 변경 대상: `services/htm-server/server.py` (`renderHtmDocs` JS)
    - 연관 SSOT: `_doc_arch/hub_dashboard.md`
* 구현 결과:
    - 헤드는 프로젝트명만 유지. 본문 `dash-title` 은 `cleanTitle` 사용 — `d.title` 이 프로젝트명으로 시작하면(대소문자 무시) 해당 길이만큼 자르고 선두 구분자(`\s — : -`) trim. 결과가 비면 원본 `d.title` 폴백
    - 동적 `RegExp` + 백슬래시 이스케이프 제거 → `startsWith` 기반으로 단순화 (SyntaxWarning 회피)
* 검증: `test_feed_link.py` 21/21, `test_control_gate.py` 7/7 통과. `python3 -W error::SyntaxWarning` compile 무경고 확인
* triage: 단순 (server.py 1파일, JS 1곳) → 별도 plan/task/report 생략

## Issue67: hub 활동 피드 — 항목 배경에 프로젝트색 그래디언트 부재 (등록: 2026-05-21, 해결: 2026-05-21, commit: 60712f8) ✅
* 목적: 활동 피드 항목(`feed-item`)은 좌측 4px 보더만 프로젝트색으로 표시. 항목별 프로젝트 식별성이 약함. 배경에 프로젝트색을 좌→우 그래디언트로 깔아 시각 식별 강화.
* 상세:
    - 변경 대상: `services/htm-server/server.py` (`renderFeed` JS)
    - 연관 SSOT: `_doc_arch/hub_dashboard.md`
* 구현 결과:
    - `feed-item` inline style 에 `background: linear-gradient(to right, color-mix(in srgb, <color> 22%, var(--bg)), var(--bg))` 적용. 좌측만 프로젝트색 22% 농도, 우측은 카드 배경(`--bg`)으로 수렴. 기존 `border-left-color` 유지
    - `it.color` 가 hex·hsl 어느 포맷이든 `color-mix` 가 수용 (Firefox 전용 환경 — color-mix 지원)
* 검증: `test_feed_link.py` 21/21, `test_control_gate.py` 7/7 통과
* triage: 단순 (server.py 1파일, inline style) → 별도 plan/task/report 생략

## Issue64: hub dashboard — 활성 세션 카드 ✕(제거) 버튼 오동작 (등록: 2026-05-21, 해결: 2026-05-21, commit: 6a998ad, 6dbb274) ✅
* 목적: hub 활성 세션 카드의 ✕ 버튼이 dashboard runner 를 종료하지 못함. Issue63 이 `pids` 영속화를 추가했으나 여전히 결함:
    1. **종료 실패(403)**: `pids.json` 이 `{}` 인 상태에서 live runner(pid 49808) 존재 → ✕ 클릭 시 `/control` 이 `403 pid not registered for this cwd`. `pids` 레지스트리는 `/register-pid` 1회성 등록 + `pids.json` 휘발(빈 `{}` 재시작)로 live runner 가 누락됨. 반면 활성 세션 카드의 kill pid 는 `_dash_runner_state`(dashboard data content)에서 추출 — 매 iter 갱신되는 authoritative 신호라 레지스트리와 불일치.
    2. **레이아웃 깨짐**: `stopRunner` 실패 시 `btn.textContent` 에 긴 에러문("pid not registered for this cwd")을 주입 → 1.6em 원형 아이콘 버튼(✕)에서 텍스트가 카드 헤더로 흘러넘침.
* 상세:
    - 변경 대상: `services/htm-server/server.py` (Python + HUB_HTML 내 JS)
    - 연관 SSOT: `_doc_arch/hub_dashboard.md`
    - 연관 이슈: Issue63(종료 신호 처리 — `pids` 영속화) 후속. `pids` 레지스트리 단일 의존의 구조적 취약성 노출
* 구현 결과:
    - Fix A(기능): `_session_runner_pids(h)` 헬퍼 신규 — cwd_hash 의 dashboard 세션 data content 에 기록된 runner pid 집합 반환. `/control` 등록 게이트가 미등록 pid 라도 이 authoritative 집합에 포함되면 인정 + `pids` 레지스트리에 self-heal(`persist_pids`)
    - Fix B(UI): `stopRunner` 가 결과/에러를 `toast` 로만 표시. 실패 시 `btn.innerHTML` 원복 — 아이콘 버튼에 에러문 주입 제거. `중단 중...` 진행 텍스트도 제거(아이콘 버튼 대응)
* 검증: 서버 재시작 후 `pids.json={}` 상태에서 `/control refresh pid=49808` → 종전 `403` → `200 refreshed` + `pids.json` self-heal(`{"c89ac282":[49808]}`). 비파괴 `refresh` 액션으로 live runner 미종료 검증. 회귀 테스트 `test_control_gate.py` 7/7, 기존 `test_feed_link.py` 21/21 통과
* 종결 비고: Issue64 코드(server.py)는 commit `6a998ad`(Issue65 와 동시 land), 회귀 테스트 `test_control_gate.py` 는 commit `6dbb274` 로 분리 커밋
* triage: 단순 (server.py 1파일 + 테스트, fallback 추가) → 별도 plan/task/report 생략

## Issue65: hub 활동 피드 — 카드 제목이 한 줄 클램프로 잘리고 전체 제목 복구 경로 없음 (등록: 2026-05-21, 해결: 2026-05-21, commit: 6a998ad) ✅
* 목적: 활동 피드 카드 제목(`htm_title`)이 길면 `…` 로 잘려 일부만 보임. CSS `.feed-summary`(`white-space:nowrap; overflow:hidden; text-overflow:ellipsis`)의 의도된 한 줄 클램프이나, 잘린 전체 제목을 다시 볼 수단이 전무한 것이 결함:
    1. `.feed-summary` 에 `title` 속성 미부착 → 호버 툴팁 없음 (형제 `.feed-icon`·`.feed-title` 에는 있음)
    2. 카드 펼침 `.feed-detail` 은 event/cwd/detail 만 표시 → `htm_title`/`summary` 전체 문자열 미포함
    3. 결국 `↗` 로 htm 문서를 직접 열어야만 전체 제목 확인 가능
* 상세:
    - 변경 대상: `services/htm-server/server.py` (HUB_HTML 내 JS `renderFeed`)
    - 연관 SSOT: `_doc_arch/hub_dashboard.md`
* 구현 결과:
    - Fix A(툴팁): `.feed-summary` span 에 `title="${escapeHtml(summaryText)}"` 부착 — 호버 시 전체 제목 노출
    - Fix C(detail): `renderFeed` 의 `detail` 배열에 `제목: <summaryText>` 줄 추가 — 카드 펼치면 잘린 전체 제목 확인. `summaryText` 정의를 `detail` 앞으로 이동
* triage: 단순 (server.py 1파일, JS 2줄 변경) → /별도 plan/task/report 생략

## Issue63: hub dashboard — 서버 재시작 후 종료 신호 처리 불가 + dead runner 세션 활성 목록 잔존 (등록: 2026-05-21, 해결: 2026-05-21, commit: 0434db8, 4537b39) ✅
* 목적: dashboard 사용 불가 상태 해결. 서버측 결함:
    1. **종료 신호 처리 불가**: SPA stop/kill_pane 버튼이 "pid not registered for this cwd" 에러. `pids` 레지스트리(`/register-pid` 등록분)가 in-memory only — `sessions` 만 `sessions.json` 으로 영속되고 `pids` 는 비영속. 서버 재시작 시 모든 runner pid 등록 소실 → 복원된 세션의 `/control` 이 전부 403.
    2. **dead runner 세션 잔존**: `_collect_live_sessions` zombie 필터가 `subs>0`(브라우저 탭 열림)이면 통과 — runner 가 죽어도 탭만 열려 있으면 "활성 세션" 무한 노출. 자동 정리 불가.
    3. **runner status stale**: detail page 가 죽은 runner 의 마지막 데이터(🟢 alive)를 그대로 렌더.
* 상세:
    - 변경 대상: `services/htm-server/server.py`, `services/htm-server/spa_dashboard.py`
    - 연관 SSOT: `_doc_arch/hub_dashboard.md` (dashboard 서버 구현 SSOT)
    - 연관 이슈: Issue58(running 배지 dead runner), Issue60(stale 카드 정리) — 동일 계열 후속. client 측 dashboard runner 는 `~/.claude` Issue81(worker 완료 자가 종료)로 선행 수정 — runner 가 status=done 푸시
* 구현 결과:
    - Fix A: `PIDS_FILE`(`pids.json`) + `persist_pids()`/`load_pids()` — `/register-pid`·`/control` 후 flush, 시작 시 load(dead pid 필터). 재시작 후 `/control` 권한 복구
    - Fix B: `_dash_runner_state()` 파서 신규 — dashboard 세션 content 의 `pid`·`status` 가 authoritative. `_collect_live_sessions` 가 status terminal(done/stopped)·pid dead 세션을 활성 목록 제외(`subs>0` 이어도), pid 생존이면 `force_live` 로 Issue37 게이트 우회. terminal 세션 1h TTL prune
    - Fix C: `/control` 미등록 pid → `_pid_alive` 확인 → dead 면 `200 already_dead`(graceful), alive 면 `403`
    - Fix D: `/s/{h}/{sid}/data` — runner pid dead + status 비-terminal 시 served `status` 를 `stopped` 로 override + `_runner_dead` 플래그
    - 시각화: `renderDashboard` 에 status 배지(🟢running/🔴stopped/✅done, dead 시 "⚠ runner 종료됨") + 메타 칩(pid/worker/iter/interval/updated) 추가. CSS `.dash-status`/`.dash-meta`. badge 위젯 SPA renderer 지원 확인(Issue44 우회 불요)
* Walkthrough: 4개 Fix 전부 end-to-end 검증 — (A) 더미 runner `/register-pid` → `pids.json` flush → 서버 재시작 → `load_pids: restored 1 (dropped 0 dead)` → `/control stop` → `{status:stopped,signal:TERM}` → 프로세스 실제 종료. dead pid 재시작 시 `dropped 1 dead` 필터 확인. (B) `/dashboards` live_sessions — dead dashtest 3건 제외, live graphify-index 1건 유지(재시작 후 subs=0 여도 force_live). (C) dead pid `/control` → `{status:already_dead}`. (D) `/s/.../data` dead runner 세션 → served status `stopped`+`_runner_dead:true`. dashboard agent 풀 재테스트(dashtest3, 90폴더 worker) — 위젯 8종(progress×2/checklist/table/text×2/badge/timer) 전부 `last_eval_rc:0`, worker 완료 → runner status=done 자가 종료 → 활성 목록 자동 제외.
* triage: 중간 (server.py 세션 lifecycle 설계 변경) → Walkthrough 에 검증 증거 흡수, 별도 report 생략

## Issue62: hub 활동 피드 — B모드 htm 문서가 ↗ 링크로 연결 안 됨 (등록: 2026-05-20, 해결: 2026-05-20, commit: 6040eb3) ✅
* 목적: B모드(`claude-htm-ask-*`) htm 문서를 만든 프로젝트의 완료 피드 항목에 ↗(htm 문서 열기) 아이콘이 표시되지 않음. 일부 항목만 ↗ 가 붙고 일부는 빈칸 — 사용자가 불일치 현상으로 보고.
* 상세:
    - 요청 출처: ___pm hub 사용 중 — `_public` 프로젝트 "Issue137 plan 완료" 피드 항목에 ↗ 미표시 발견 (B모드 폼은 디스크에 존재)
    - 근본 원인: `services/htm-server/server.py` 피드↔htm 연결(Issue42_1)이 `path in detail` — htm 문서 **절대경로가 Claude 마지막 메시지(feed detail)에 그대로 등장**해야만 ↗ 부여. B모드 폼은 대화 도중 생성돼 완료 메시지에 경로 언급이 없음 → 영구 미연결. 상대경로·백틱 표기(`loginScript` 사례)도 미연결.
    - 카드 등록 측은 글로벌 hook `htm-doc-register.sh` Issue80(2026-05-20)에서 `-ask-` 포함으로 이미 해결됨 — 본 이슈는 ↗ 링크 한정.
* 구현 명세 (적용):
    - `server.py`: 피드↔htm 연결을 헬퍼 `_link_feed_htm_docs` 로 분리, 3단계 매칭 — ①절대경로 ②basename ③턴 근접(htm 문서 생성 ts 가 같은 프로젝트의 직전 Stop~해당 Stop 구간에 들면 그 완료 피드에 연결)
    - 보조 헬퍼 `_htm_doc_ts`(파일명 ts 추출), `_cwd_related`(상위/하위 cwd 매칭)
    - 턴 근접은 `dts <= fts` 엄격 비교 — 시계 오차 유예(+120s)를 두면 다음 턴 문서가 직전 완료 피드로 새어 오연결됨(라이브 검증 중 발견·교정)
    - 검증: `test_feed_link.py` 회귀 테스트 21개 통과 + 서버 재기동(pid 62008) 후 라이브 `/dashboards` — B모드 문서(`___pm`·`_public`)·`loginScript`(상대경로) 모두 ↗ 연결 확인, 오연결 0
* 비고: 이미 디스크에 있으나 registry 미등록인 구(舊) B모드 폼(Issue80 hook 수정 2026-05-20 22:53 이전 생성분)은 등록 자체가 없어 ↗ 미표시 — orphan. 신규 B모드 문서는 hook 등록 → 본 수정 연결로 end-to-end 정상. orphan 수거는 별건(`/hub-rescan` recursion 한계).
* 자동 결정: triage 단순 (server.py 1파일 + 테스트 1파일) → plan/task/report 미생성

## Issue57: dashboard 서버 구현 SSOT 신규 작성 — _doc_arch/hub_dashboard.md (등록: 2026-05-20, 해결: 2026-05-20, commit: 748d00e) ✅
* 목적: htm-server 의 dashboard(Mode C) 서버측 구현이 `hub_htm.md` 에 htm 과 혼재되어 dashboard 단독 추적·갱신이 어려움. dashboard 서버 구현 명세를 `_doc_arch/hub_dashboard.md` 로 분리하여 dashboard 서버측 SSOT 를 명확히 함. 글로벌 `~/.claude/_doc_arch/dashboard.md`(클라이언트측 SSOT)와 상호 링크로 연결.
* 상세:
    - 요청 출처: 글로벌 `~/.claude` 세션 — 사용자 지시 "dashboard 구현은 prj1 `_doc_arch/hub_dashboard.md` 에 정의, 상호 링크 연결". htm 폼 Q&A 로 작업 방식 확정 (Q1=서버 구현 상세를 dashboard.md 에서 hub_dashboard.md 로 트림 이전, Q2=server.py 코드 확인 후 작성)
    - 글로벌 측 대응: `~/.claude/Issue.md` Issue78 후속 — `dashboard.md` 서버 구현 상세 트림 (commit f69a061)
* 구현 명세 (적용):
    - `_doc_arch/hub_dashboard.md` 신규 작성 (283줄, server.py 기준): dashboard 전용 endpoint 11종, 세션 모델, `validate_dashboard` 위젯 9종, SSE broadcast, SPA shell 렌더링, dash-registry + tombstone, 보안, 검증 시나리오, 이력
    - `hub_htm.md`: §"Mode C dashboard" 에 hub_dashboard.md 위임 안내 + SCAR 분담표·참조에 dashboard 서버/클라이언트 SSOT 양분 명시
    - 글로벌 `~/.claude/_doc_arch/dashboard.md`: 서버 구현 상세(`/control` 메커니즘·서버측 보안·세션 테이블)를 hub_dashboard.md 로 트림 이전, 클라이언트 관점 요약 + 링크만 잔존
    - 상호 링크 3-way: `dashboard.md`(클라이언트) ↔ `hub_dashboard.md`(서버) ↔ `hub_htm.md`(서버 공통)
* 자동 결정: triage 중간 (SSOT 설계 문서) — 작업 자체로 완결, 별도 plan/task/report 미생성

## Issue61: hub 활동 피드 — 아이콘만 보기 모드에서 프로젝트 클릭(cdfv) 불가 (등록: 2026-05-20, 해결: 2026-05-20, commit: 9baf865) ✅
* 목적: 활동 피드 항목의 아이콘·프로젝트명을 클릭하면 `cdfv` 효과(`/open-project` → VSCode 열기)로 해당 프로젝트가 열려야 하나, `feed_show_project_name: false`(아이콘만 보기) 설정에서 동작하지 않음.
* 상세:
    - 요청 출처: ___pm hub 사용 중 — 아이콘만 보기 상태에서 클릭 무반응 발견
    - 근본 원인: `services/htm-server/server.py` `renderFeed`/클릭 핸들러가 클릭 대상을 `.feed-title`(프로젝트명 anchor)로만 한정. `feed_show_project_name: false` 시 `.feed-title` 자체가 미렌더 → 클릭 가능 요소 부재. `.feed-icon`·`.feed-proj-emoji` 는 `data-cwd`·클릭 바인딩 모두 없었음
* 구현 명세 (적용):
    - `renderFeed`: `.feed-icon`·`.feed-proj-emoji` span 에 `data-cwd` 부여
    - 클릭 핸들러: `closest('.feed-title')` → `closest('.feed-title, .feed-icon, .feed-proj-emoji')` 확장 후 `openProject(dataset.cwd)` 호출
    - CSS: `.feed-icon`·`.feed-proj-emoji` 에 `cursor: pointer` + hover 밝기 효과
    - 검증: 서버 재기동(pid 49418) 후 아이콘만 보기 모드에서 아이콘·이모지 클릭 → `/open-project` → VSCode 열림
* 자동 결정: triage 단순 (server.py 1파일, 임베디드 JS/CSS 로컬 변경) → plan/task/report 미생성

## Issue60: hub stale dashboard 카드가 "정리" 버튼으로 제거되지 않음 (등록: 2026-05-20, 해결: 2026-05-20, commit: 218eb9a) ✅
* 목적: Issue58 이 죽은 runner 의 dashboard 카드를 `status: running` → `stale` 로 강등하나, `_is_clearable_status` 는 clear 대상을 `done`/`stopped`/`stop` 으로만 판정 → "🧹 정리" 버튼(`/clear-done`)이 `stale` 좀비 카드를 쓸어내지 못함. 사용자가 카드마다 ✕ 를 수동 클릭해야 하여 Issue58 의 의도(좀비 식별 + 일괄 정리)가 절반만 달성됨.
* 상세:
    - 요청 출처: ___pm hub Issue58 fix 검토 — `stale` 강등 후 정리 경로 누락 발견
    - 근본 원인: `services/htm-server/server.py` `_is_clearable_status` 가 Issue58 신규 도입 status 값 `stale` 을 미포함
* 구현 명세 (적용):
    - `_is_clearable_status`: clear 대상 집합에 `stale` 추가 → `/clear-done` 이 stale 카드 registry 항목 제거 + `DASH_CLEARED` tombstone 등록
    - 버튼 라벨·tooltip·confirm·toast 문구를 `done/stopped/stale` 로 갱신
    - `services/htm-server/README.md`: stale 강등 항목에 clear 대상 포함 명시
    - 검증: `_is_clearable_status("stale")` → True. 정리 버튼이 stale 카드 일괄 제거
* 자동 결정: triage 단순 (server.py·README.md 2파일, `_is_clearable_status` 로컬 변경) → plan/task/report 미생성

## Issue59: htm-server 시작 실패 cleanup 이 살아있는 다른 서버의 pid 파일을 파괴 (등록: 2026-05-20, 해결: 2026-05-20, commit: 71a1e0f) ✅
* 목적: `server.py main()` 이 socket bind 보다 먼저 `PID_FILE` 에 자기 pid 를 기록함. 포트가 이미 점유된 상태로 두 번째 서버가 기동하면 (1) PID_FILE 을 자기 pid 로 덮어쓰고 (2) bind 실패 → `cleanup()` 이 `os.remove(PID_FILE)` 실행 → **살아있는 첫 서버의 pid 파일까지 삭제**. 결과로 정상 동작 중인 서버가 pid 파일 없이 남아 `/hub stop`·`/hub restart` 가 서버를 찾지 못함. `/hub restart` 중 잉여 start 1회만 발생해도 재현.
* 상세:
    - 요청 출처: ___pm `/hub restart` 실행 — pid 파일 부재로 구 서버(23608) 미종료, 신규 서버 bind 실패 "Address already in use" 연쇄
    - 근본 원인 1: `main()` 이 `with open(PID_FILE, "w")` 를 `ThreadingHTTPServer((HOST,PORT),...)` bind 보다 먼저 수행
    - 근본 원인 2: `cleanup()` 이 PID_FILE 내용 검증 없이 무조건 `os.remove` — 자기 소유 여부 미확인
* 구현 명세:
    - `services/htm-server/server.py` `main()`: `ThreadingHTTPServer` bind 를 `PID_FILE` 기록보다 **먼저** 수행. bind 실패 시 PID_FILE 미생성·미삭제로 즉시 `sys.exit(2)` (cleanup 미경유)
    - `services/htm-server/server.py` `cleanup()`: PID_FILE 내용이 `os.getpid()` 와 일치할 때만 `os.remove` — 다른 서버 pid 파일 파괴 방지
    - 검증: 라이브 서버 1대 기동 후 두 번째 server.py 기동 → bind 실패, 첫 서버 pid 파일 보존 + 2nd 가 pid 파일 미생성 확인 (exit code 2)
* 비고: 코드 수정(`server.py`)이 병렬 세션의 Issue58 fix 커밋 `71a1e0f` 에 동반 커밋됨 (working tree 충돌). 따라서 commit hash 는 Issue58 과 공유. Issue.md 종결 정리는 본 Docs 커밋.
* 자동 결정: triage 단순 (server.py 1파일, `main()`·`cleanup()` 로컬 변경) → plan/task/report 미생성

## Issue58: hub dashboard 카드 "running" 배지가 죽은 runner 도 running 으로 표시 (등록: 2026-05-20, 해결: 2026-05-20, commit: 71a1e0f) ✅
* 목적: hub dashboard 카드의 status 배지가 `.dash.json`/`.dash.yaml` 파일의 `status:` 필드 텍스트를 그대로 렌더링하며 runner 프로세스 생존을 검증하지 않음. runner 가 크래시·SIGKILL·tmux pane 강제종료로 죽으면 파일에 `running` 이 잔존 → hub 는 영원히 "running" 표시. `_read_dash_file` 의 mtime 캐시가 죽은 status 를 박제하여 악화. Issue37 의 zombie 노출 차단은 `_collect_live_sessions`(live_sessions 섹션)만 처리했고 dashboard 카드 경로(`_handle_dashboards`)는 미처리.
* 상세:
    - 요청 출처: ___pm hub 점검 — "dashboard 실행중 아닌데 왜 running 인가" 질의
    - 근본 원인: `_handle_dashboards` 가 `_read_dash_file` 결과의 `status` 를 검증 없이 그대로 응답. dash 파일에 `pid` 필드가 추출되어 있음에도(`_read_dash_file` 의 entry["pid"]) `_pid_alive` 검증 미적용
    - `_collect_live_sessions` 은 `_pid_alive(pid)` 검증함 — 동일 응답 내 두 섹션의 running 판정이 비대칭
* 구현 명세:
    - `services/htm-server/server.py` `_handle_dashboards`: dash entry 의 `status` 가 `running` 이고 `pid` 가 정수이며 `_pid_alive(pid)` 가 False 면 `entry["status"]` 를 `stale` 로 강등. `pid` 가 None 이면 검증 불가 → `running` 유지 (verification 한계)
    - pid 검증은 `_read_dash_file` 캐시 외부(매 `/dashboards` 요청마다)에서 수행 — mtime 캐시 박제 회피
    - `services/htm-server/README.md` — stale 강등 동작 한 줄 추가
* 검증 결과: 라이브 서버 재기동 후 — ① 죽은 pid(999999) 주입한 `status: running` dash → `/dashboards` 응답 `status=stale` ② 산 pid dash → `running` 유지 ③ 기존 좀비 dash 카드 5건(folder-creation-monitor 등, 죽은 pid)도 일괄 `stale` 로 교정 ④ 파일 status 가 이미 `stopped` 인 항목은 미변경. 4/4 통과
* 자동 결정: triage 단순 (server.py·README.md 2파일, `_handle_dashboards` 메서드 로컬 변경) → plan/task/report 미생성

## Issue55: hub 디스크 재스캔이 전체 제거한 htm 카드를 부활시킴 + 스캔 성능 상한 (등록: 2026-05-20, 해결: 2026-05-20, commit: be76985, 348ebad) ✅
* 목적: hub "htm 목록 전체 제거"(`/clear-htm-docs` keep=0) 후 "🔄 디스크 재스캔" 클릭 시, 디스크에 `.html` 파일이 남아 있는 한 htm-registry 에 재등록되어 카드가 부활함. Issue53 이 `HTM_CLEARED` tombstone 을 도입했으나 autoheal 차단 전용이고, `_handle_hub_rescan` 은 발견된 htm path 를 오히려 tombstone 에서 해제(recover)하므로 clear 가 무효화됨. Issue54 가 dash 측은 `DASH_CLEARED` skip 으로 해결했으나 htm rescan 은 의도적으로 recover 로 남겨둠 — 사용자 결정으로 htm 도 tombstone 존중으로 전환. 동시에 `_scan_htm_docs_in` 은 디렉토리 전수 `os.listdir`+파일별 `os.stat`+`_extract_html_title`(파일 열람) 이라 z_htm 누적 시 재스캔이 O(N) 파일 IO 로 느려질 위험 → `search_limit` 설정으로 상한.
* 상세:
    - 요청 출처: ___pm hub 점검 — "전체 제거" 후 "디스크 재스캔"하면 13개 htm 카드 전부 부활, 파일 수 증가 시 스캔 지연 우려
    - 근본 원인 1: `_handle_hub_rescan` 의 Issue53 블록이 발견 htm path 를 `HTM_CLEARED` 에서 제거 — rescan 이 clear 를 무효화
    - 근본 원인 2: `_scan_htm_docs_in` 이 후보 전체에 `_extract_html_title`(open+read) 수행 — 상한 없음
    - 사용자 결정: Q1=tombstone 존중 (재스캔이 cleared htm 부활 안 함), Q2=search_limit 디렉토리당 최신 N개·기본 200·0=무제한
* 구현 명세:
    - `data/hub_setting.yml` — `search_limit: 200` 키 추가 (디렉토리당 스캔 처리 파일 수 상한, 0=무제한, `card_limit` 대칭)
    - `services/htm-server/server.py`:
        - `HUB_SETTING_DEFAULTS` 에 `search_limit: 200` 추가
        - `_scan_htm_docs_in(directory, skip=None, limit=0)` — `skip` set 의 path 는 후보에서 제외(title 추출 skip), `limit>0` 이면 파일명 unixtime 최신순 N개만 stat+title 추출
        - `_scan_htm_docs` / `_scan_tmp_htm_docs` — `skip`·`limit` 인자 전달
        - `_handle_hub_rescan` — `HTM_CLEARED` 를 skip set 으로, `search_limit` 을 limit 으로 htm 스캔에 전달. Issue53 의 "발견 htm path tombstone 해제" 블록 제거 (rescan 은 더 이상 htm recover 안 함 — `_handle_register_doc` 생산자 명시 재등록만 recover 경로로 유지)
    - `services/htm-server/README.md` — tombstone(Issue53/54/55) 설명 갱신 + search_limit 키 명시
* 검증 결과: 라이브 서버 재기동 후 — ① 전체 제거(registry 28→0, 28 path tombstone) → 재스캔 `added.htm` 은 신규 미등록 파일만 수거, cleared 28 은 부활 안 함 ② register-doc 으로 cleared path 1건 명시 재등록 → registry 복귀 + tombstone 해제(28→27) ③ search_limit=2 설정 후 재스캔 → ___pm z_htm 13개 중 파일명 unixtime 최신 2개만 registry 등록(정확히 2개 확인) ④ 최종 전체 제거 후 재스캔 → `added.htm=0` (전체 제거가 재스캔에도 유지). 4/4 통과
* 자동 결정: triage 단순 (server.py·hub_setting.yml·README.md 3파일, Issue53/54 대칭 패치) → plan/task/report 미생성
* 비고: 작업 중 병렬 Issue56 세션의 `git add` 가 server.py 본체 변경 + Issue.md Issue55 항목을 `be76985`(메시지는 "Issue56")에 함께 커밋. 잔여 설정·문서분은 `348ebad` 로 별도 커밋

## Issue56: hub htm-doc 가상 카드 "열기" 링크 클릭 불가 (등록: 2026-05-20, 해결: 2026-05-20, commit: be76985) ✅
* 목적: hub "디스크 재스캔"으로 부활한(또는 `/tmp/___pm` 등 cwd 미매핑) htm 카드의 "열기 ↗" 링크가 회색 + 클릭 무반응. 파일은 존재하고 `/htm-doc` 엔드포인트도 HTTP 200 으로 정상 serve 됨에도 열리지 않음.
* 상세:
    - 요청 출처: ___pm hub 점검 — `system/___pm-tmp` 가상 카드 "열기" 클릭 무반응
    - 근본 원인: CSS `.card.virtual .actions a { pointer-events: none; opacity: 0.4 }` 가 모든 가상 카드의 actions 링크를 차단. 이 규칙은 token 미발급으로 `/view` 불가한 **dashboard** 가상 카드용이나, Issue50 이 token 없는 htm 도 `/htm-doc?path=` 로 열람 가능하게 한 뒤 CSS 갱신을 누락 → htm-doc 가상 카드 링크까지 죽임 (`pointer-events: none` = 클릭 차단, `opacity: 0.4` = 회색)
* 구현 명세:
    - `services/htm-server/server.py` CSS: `.card.virtual .actions a` → `.card.virtual:not(.htm-doc) .actions a` (htm-doc 가상 카드 제외, dashboard 가상 카드만 링크 비활성 유지)
    - 검증: 라이브 서버 — `/dashboards` 응답 `view_url` 정상, `curl /htm-doc` HTTP 200 확인 완료. 서버 재기동 후 가상 htm 카드 "열기" 클릭 동작 확인 필요

## Issue42: htm Hub 활동 피드 패널 — 우측 1/3 영역 hook 호출 스트림 (등록: 2026-05-20, 해결: 2026-05-20, commit: bbf8894, 68fce76, 1ed12a7) ✅
* 목적: 작업 완료·응답 대기 등 hook 이벤트가 현재 `say` 음성 알림만 제공되어 휘발성·다중 프로젝트 식별난 문제가 있음. 동일 hook 이벤트를 htm-server 로 전달하여 hub `/hub` 페이지 우측 1/3 영역에 프로젝트별 호출 이력을 최신순 시각 피드로 노출. 음성 알림은 그대로 유지.
* arch: `_doc_arch/hub_htm_history.md`
* depends: AskUserQuestion 질문 이벤트 포착(Phase 2)은 글로벌 SCAR — `~/.claude/Issue.md` 연계 이슈 별도 등록 후 처리
* 상세:
    - 요청 출처: ___pm 작업 중 hook 알림 가시화 개선 요청 (사용자 8항 명세)
    - 설계 SSOT: `_doc_arch/hub_htm_history.md` (본 이슈 등록과 함께 작성 완료)
    - Phase 1(본 이슈, ___pm 단독 — `.claude/` 미포함) / Phase 2(글로벌 SCAR — 연계 이슈)로 분리
* 구현 명세:
    - `data/hub_setting.yml` 신규 — `feed_limit`(기본 100)·`feed_default_visible`·`feed_poll_interval` flat key. git 추적 대상
    - `services/htm-server/server.py`:
        - `_load_hub_setting()` — mtime 캐시 로더 (`_load_projects_colors` 패턴, stdlib only)
        - `feed_buffer` = `deque(maxlen=feed_limit)`, `data/hub/hook-feed.json` 영속(gitignore)·기동 시 로드
        - `POST /hook-event` — hook 이벤트 수신, `project_meta(cwd)` 로 name·color 보강, newest-first append
        - `GET /dashboards` 응답에 `hook_feed[]` 추가
        - `POST /open-project` — `Projects.md`/registry 등록 경로 화이트리스트 검증 후 `open -a "Visual Studio Code"` spawn (cdfv 효과 재현)
        - HUB_HTML — `main` 2-컬럼 재편(`.hub-main` 2fr / `.hub-feed` aside 1fr), `renderFeed()`, 제목 클릭→`/open-project`, 본문 클릭→detail 토글, 사이드바 숨김/보기 + localStorage, `{FEED_DEFAULT_VISIBLE}` placeholder 주입
    - `~/.bin/claude_hook_noti.sh` — Stop·Notification 경로에 `POST /hook-event` fire-and-forget 1줄 추가 (`curl --max-time 1 &`, 비-블로킹). `~/.bin/` 소속이라 글로벌 SCAR 가드 비대상이나 공유 자산이므로 본 이슈로 추적
    - 동기화: `_doc_arch/hub_htm.md` `/dashboards` 스키마, `services/htm-server/README.md`
    - 검증: hook 발생 → `/hook-event` → `/dashboards` 반영 → hub 피드 노출 → 제목 클릭 시 VSCode 열림 → 본문 클릭 detail 토글 → 사이드바 토글·localStorage 영속

### Issue42_1: 활동 피드 제목 ↔ htm 문서 카드 제목 불일치 (등록: 2026-05-20) ✅ 완료 (해결: 2026-05-20, commit: 68fce76)
* 목적: hub 활동 피드 항목 제목(`name` + hook `summary`)이 동일 htm 출력의 htm 문서 카드 제목(htm-registry `title`)과 다름. 카드 제목이 정답 — 피드 항목이 htm 문서와 연결될 때 카드 제목으로 표시해야 일관됨.
* 상세:
    - 요청 출처: ___pm hub 점검 — 카드 "m2slide — 최근 이슈 5개 핵심 정리" vs 피드 "m2slide HTML Firefox 완료"
    - 연결 단서: 피드 `detail` 의 `📁 {html 경로}` 가 htm-registry `path` 와 일치
* 구현 명세:
    - `services/htm-server/server.py` `_handle_dashboards` — `hook_feed` 항목 복사본에 detail 내 htm 경로 매칭 시 `htm_title` 부여 (`feed_buffer` 원본 비변경)
    - HUB_HTML `renderFeed` — `htm_title` 있으면 `feed-summary` 텍스트로 사용
    - 동기화: `_doc_arch/hub_htm.md` `hook_feed` 스키마

### Issue42_2: 활동 피드 항목에 htm 문서 열기 아이콘 추가 (등록: 2026-05-20) ✅ 완료 (해결: 2026-05-20, commit: 68fce76)
* 목적: htm 문서 카드를 가진 피드 항목은 카드처럼 "열기" 가능해야 함. 피드 항목 시각 표시 왼쪽에 open 아이콘 추가 — 클릭 시 htm 문서를 브라우저로 염.
* 상세:
    - 요청 출처: ___pm hub 점검 — 피드 항목에서 htm 문서 직접 열기 요청
* 구현 명세:
    - `services/htm-server/server.py` `_handle_dashboards` — feed 항목에 `htm_view_url` 부여 (Issue42_1 매칭 로직 공유)
    - HUB_HTML `renderFeed` — `htm_view_url` 있으면 `.feed-age` 좌측에 `↗` anchor(`target=_blank`), 클릭 시 detail 토글 차단
    - 동기화: `_doc_arch/hub_htm.md` `hook_feed` 스키마

### Issue42_3: 활동 피드 전체 비우기(클리어) 버튼 (등록: 2026-05-20) ✅ 완료 (해결: 2026-05-20, commit: 1ed12a7)
* 목적: 활동 피드가 hook 이벤트 누적으로 길어져도 일괄 제거 수단이 없음. ⊟(일괄 접기)는 detail 만 접을 뿐 항목을 지우지 못함. 헤더에 전체 비우기 버튼 추가.
* 상세:
    - 요청 출처: ___pm hub 점검 — 활동 피드 헤더에 클리어 버튼 요청
* 구현 명세:
    - `services/htm-server/server.py`:
        - HUB_HTML `feed-actions` — `🗑 클리어` 버튼 추가 (⊟ 와 ◀숨기기 사이), `#feed-clear` CSS (hover 빨강)
        - `renderFeed` JS — confirm 후 `POST /feed-clear` → `openFeedItems.clear()` + `renderFeed([])` + toast
        - `POST /feed-clear` — `_handle_feed_clear`: localhost trust, `feed_buffer` deque clear + `persist_feed()` 로 `hook-feed.json` 비움
    - 검증: 버튼 클릭 → confirm → 피드 0개 + hook-feed.json `[]`. 엔드포인트 단독 호출 시 `removed_count` 반환 (84개 제거 확인)
* 자동 결정: triage 단순 (server.py 1파일, 방법 자명) → plan/task/report 미생성

## Issue54: hub 디스크 재스캔이 닫은 dashboard 카드를 부활시킴 — dash tombstone 부재 (등록: 2026-05-20, 해결: 2026-05-20, commit: 9b6857b) ✅
* 목적: hub 에서 dashboard 카드를 닫거나(✕) done/stopped 목록 정리로 제거해도, `🔄 디스크 재스캔` 클릭 시 `/tmp/___pm/*.dash.{json,yaml,yml}` 파일이 디스크에 남아 있는 한 dash-registry 에 재등록되어 카드가 부활함. Issue53 이 htm-registry 에 `HTM_CLEARED` tombstone 을 도입했으나 dash-registry 는 동일 보호장치가 없음 — 같은 버그 클래스의 dash 측 미패치분.
* 상세:
    - 요청 출처: ___pm hub 점검 — `graphify 인덱싱 상태` dash 카드가 디스크 재스캔으로 부활 (dash-registry.json `registered_at` = rescan 시각 일치 확인)
    - 근본 원인: `_handle_hub_rescan` → `_scan_tmp_dashes()` 가 디스크의 `.dash.*` 파일을 발견해 무조건 재등록. dash 측 tombstone 없음. `_handle_unregister_doc`(카드 닫기)·`_handle_clear_done_dashboards`(done/stopped 정리) 모두 registry 항목만 삭제하고 tombstone 미기록
    - htm 과 차이: htm 은 매 폴링 autoheal 이 재등록 → tombstone 이 autoheal 차단, rescan 은 recover. dash 는 autoheal 없음 → 유일 재등록 경로가 rescan → tombstone 이 rescan 을 차단해야 의미 있음
* 구현 명세:
    - `services/htm-server/server.py`:
        - `DASH_CLEARED` = `data/hub/dash-cleared.json` — 명시 제거된 dash path tombstone (`HTM_CLEARED` 대칭, gitignore)
        - `_handle_unregister_doc` — 카드 닫기 시 removed path 를 해당 종류 tombstone(`HTM_CLEARED`/`DASH_CLEARED`)에 추가. htm 카드 닫기 후 autoheal 부활 gap 도 동시 차단
        - `_handle_clear_done_dashboards` — removed dash path 를 `DASH_CLEARED` 에 추가, 디스크 부재 path prune
        - `_handle_hub_rescan` — dash 재등록 루프에서 `DASH_CLEARED` path skip (htm 과 달리 recover 안 함 — dash 는 rescan 이 유일 부활 경로)
        - `_handle_register_doc` — 생산자(dashboard runner)가 명시 재등록 시 해당 path 를 tombstone 에서 해제 (recover 경로). htm·dash 공통
    - `services/htm-server/README.md` — tombstone(Issue53/54) 한 줄 추가
* 검증 결과: 라이브 서버 재기동 후 — ① 카드 닫기 → dash-registry 제거 + dash-cleared.json 기록 ② 디스크 재스캔 → `added.dash=0` (부활 안 함) ③ register-doc → tombstone 해제 + 복귀 ④ 재스캔 재실행 → `added.dash=0` (중복 없음, 정상). 4/4 통과
* 자동 결정: triage 단순 (server.py 1파일, Issue53 대칭 패치) → plan/task/report 미생성

## Issue53: htm 목록 정리 버튼이 autoheal 로 즉시 되살아남 — clear 무효화 (등록: 2026-05-20, 해결: 2026-05-20, commit: 1ed12a7) ✅
* 목적: hub htm 문서 목록 정리 버튼이 의도대로 동작하지 않음. "htm 목록 전체 제거"(keep=0) 클릭 시 모두 제거되지 않고 일부(feed 버퍼에 남은 ~10개)가 남고, "최신 12개만 남기기"(keep=12)는 13개가 남음. 사용자에게는 off-by-one + 전체 제거 불가로 보임.
* 상세:
    - 요청 출처: ___pm hub 점검 — 전체 제거가 "최신 10개 남기기"처럼 동작, 12개 남기기가 13개 남음 지적
    - 근본 원인: `_handle_clear_htm_docs` 는 htm-registry 를 정상 trim 하나, 모든 `/hub` 폴링마다 `_autoheal_htm_registry(hook_feed)`(Issue51) 가 feed 버퍼 detail 의 z_htm html 경로를 registry 미등록분으로 판단해 재등록함. clear 직후 다음 폴링에서 cleared 항목이 부활 — clear 가 무효화됨. 남는 개수는 feed 버퍼가 참조하는 distinct z_htm 경로 수에 좌우 (off-by-one 아님)
* 구현 명세:
    - `services/htm-server/server.py`:
        - `HTM_CLEARED` = `data/hub/htm-cleared.json` — clear 로 명시 제거된 htm path tombstone (list[str], `load_registry`/`save_registry` 재사용, gitignore)
        - `_handle_clear_htm_docs` — removed path 를 tombstone 에 추가, kept path 는 tombstone 에서 제거, 디스크 부재 path prune 후 저장
        - `_autoheal_htm_registry` — tombstone 에 등록된 path 는 재등록 skip (registry_lock 내 load)
        - `_handle_hub_rescan` — 명시적 사용자 액션이므로 htm_found path 를 tombstone 에서 해제 (recover 의미)
* 검증 결과: feed 버퍼에 12개 z_htm 참조 주입 후 — keep=12 → htm_docs 정확히 12 (폴링 반복 유지), keep=0 → 0, rescan → 13 정상 복구·tombstone 해제 확인
* 자동 결정: triage 단순 (server.py 1파일, 방법 자명) → plan/task/report 미생성
* 비고: 본 커밋(1ed12a7)에 작업 트리 미커밋 상태였던 Issue50/51/52 server.py 산출물 동봉 — 세 이슈 commit:TBD 갱신

## Issue51: htm 실행 문서가 hub htm 문서 카드에 미노출 (등록: 2026-05-20, 해결: 2026-05-20, commit: 1ed12a7) ✅
* 목적: htm 스킬을 실행해 `_doc_work/z_htm/claude-htm-*.html` 산출물을 만든 프로젝트가 hub htm 문서 섹션에 카드로 안 나옴. 원인 — hub 는 `htm-registry.json` 등록 항목만 노출(Issue41)하는데, 생산자(htm 스킬의 `/register-doc` 호출)가 누락·실패하면 영구 미등록. 글로벌 SCAR(htm 스킬) 수정 없이 ___pm 서버가 자가치유.
* 상세:
    - 요청 출처: ___pm hub 점검 — htm 모드로 작동했는데 카드에 안 나옴 지적 (스크린샷)
    - 근본 원인: `/register-doc` 는 글로벌 SCAR(htm 스킬 step7) 책임. 서버 다운·호출 누락 시 영구 미등록 — 서버 측 복구 경로 부재
* 구현 명세:
    - `services/htm-server/server.py`:
        - 모듈 레벨 `_autoheal_htm_registry(feed_items)` + `_HTM_DOC_PATH_RE` — feed detail 정규식으로 `.../_doc_work/z_htm/claude-htm-*.html` 절대경로 추출, `os.path.isfile` 확인 후 htm-registry 미등록분 append. cwd 는 경로의 `/_doc_work/z_htm/` 앞부분으로 유추 (feed cwd 비신뢰)
        - `_handle_dashboards` — feed 스냅샷 직후 `_collect_htm_docs` 호출 전 `_autoheal_htm_registry(hook_feed)` 1회 호출
    - 검증: 서버 재기동 후 `/dashboards` `htm_docs` 12→19 증가 (fSnippet·fBoard·fBanner·fQRGen·fGoogleSheet·htm-server·_public 자가치유 노출), `htm-registry.json` 19 entries 영속 확인

## Issue50: hub 활동 피드 항목 열기 아이콘 미표시 (등록: 2026-05-20, 해결: 2026-05-20, commit: 1ed12a7) ✅
* 목적: Issue42_2 에서 추가한 피드 항목 htm 문서 열기 아이콘(↗)이 거의 노출되지 않음. 실측 — 피드 z_htm html 참조 11건 중 `htm_view_url` 매칭 2건뿐. 원인 (a) 참조 htm 문서가 htm-registry 미등록 → 매칭 대상 부재 (Issue51 자가치유로 해소), (b) 등록돼도 해당 프로젝트에 `/register` 토큰 없으면 `view_url=""` 로 아이콘 미생성. 등록된 모든 htm 문서를 토큰 유무 무관하게 열 수 있게 함.
* 상세:
    - 요청 출처: ___pm hub 점검 — 활동 피드 열기 아이콘 안 보임 지적 (스크린샷)
    - 근원 2: `tokens.json` 3개(m2slide·___pm·_doc)만 토큰 보유 → 나머지 fApp 프로젝트 htm 은 `view_url=""` → 카드·피드 아이콘 모두 미생성
* 구현 명세:
    - `services/htm-server/server.py`:
        - `GET /htm-doc?path=` 신규 endpoint — htm-registry 등록 경로 exact-match (`realpath` 정규화) 만 serve. registry 는 localhost 전용 endpoint 로만 기록되는 화이트리스트 → 토큰·cwd-jail 불요. 미등록 경로·비-html 403
        - `_collect_htm_docs` — `view_url` 을 토큰 있으면 `/view`, 없으면 `/htm-doc` 형식으로 항상 생성 (`missing` 제외)
        - HUB_HTML `renderHtmDocs` — `openLink` 조건에서 `!d.virtual` 제거, `view_url` 만으로 열기 링크 노출
    - 검증: 서버 재기동 후 `/dashboards` 피드 `htm_view_url` 2→9, `htm_docs` 19/19 view_url 채워짐. `/htm-doc` serve HTTP 200(11KB), `/etc/passwd` 403

## Issue52: hub_setting.yml card_limit 추가 — htm 문서 카드 표시 수 제한 (등록: 2026-05-20, 해결: 2026-05-20, commit: 1ed12a7) ✅
* 목적: hub htm 문서 섹션이 registry 등록 전수를 카드로 노출 → 누적 시 카드 과다. mtime 최신 N개만 카드로 노출하는 `card_limit` 설정을 `hub_setting.yml` 에 추가(기본 40). 기존 "최신 12개만 남기기" 버튼은 registry 영구 정리(수동), `card_limit` 은 표시 제한(자동) — 역할 분리.
* 상세:
    - 요청 출처: ___pm hub 점검 — `hub_setting.yml` 에 card_limit 설정 기능 요청, 기본값 40. 활동 피드는 정상 동작 확인됨(별도 `feed_limit` 적용 중)
* 구현 명세:
    - `data/hub_setting.yml` — `card_limit: 40` 키 추가 (`feed_*` 키와 동일 계열)
    - `services/htm-server/server.py`:
        - `HUB_SETTING_DEFAULTS` 에 `card_limit: 40` 추가 (`_load_hub_setting` int 캐스팅 재사용)
        - `_collect_htm_docs` — mtime desc 정렬 후 `results[:card_limit]` 절단 (`card_limit<=0` 이면 무제한). registry 자체는 미변경
    - 검증: 서버 재기동 후 `_load_hub_setting` card_limit=40 인식, 절단 로직 단위 검증 (40→40·0→무제한·5→5). 현재 htm_docs 19 < 40 → 미절단 정상

## Issue49: hub 카드 '닫기' 버튼 — 단일 카드 hub 목록에서만 제거 (등록: 2026-05-20, 해결: 2026-05-20, commit: 81f35e0) ✅
* 목적: hub `/hub` 페이지의 htm 문서 카드·dashboard 카드는 일괄 정리(`/clear-htm-docs`·`/clear-done`)만 가능하고 카드 1건을 골라 목록에서 빼는 수단이 없음. 각 카드에 '닫기' 버튼을 추가하여 해당 카드만 hub registry 에서 제거. clear-* 와 동일하게 실제 파일은 보존.
* 상세:
    - 요청 출처: ___pm hub 점검 — 카드별 '닫기(리스트에서만 제거)' 버튼 요청
    - 글로벌 SCAR 변경 없음 — ___pm `services/htm-server/server.py` 단독 변경
* 구현 명세:
    - `services/htm-server/server.py`:
        - `POST /unregister-doc?type=htm|dash&path=<abs>` 신규 — `_handle_unregister_doc`. path 매칭 단일 registry 항목 제거, 127.0.0.1 trust, removed 카운트 반환
        - HUB_HTML — htm-doc 카드·dash 카드 `.actions` 에 `✕ 닫기` 버튼(`.card-close`, inline `closeCard()`) 추가, `.actions .card-close` CSS(우측 정렬·hover 빨강) 추가
        - JS — `closeCard(type, path, btn)`: `/unregister-doc` POST → toast → `reload()`
    - 검증: 등록→제거 라운드트립 — `/register-doc` htm_docs 14건 → `✕ 닫기` 클릭 시 `/unregister-doc` removed=1, 실제 파일 보존, htm_docs 13건. bad params 400, 미존재 path removed=0

## Issue48: hub 활동 피드 — 펼친 항목 일괄 접기 버튼 (등록: 2026-05-20, 해결: 2026-05-20, commit: 81e857c) ✅
* 목적: hub `/hub` 활동 피드 항목은 클릭 시 detail 이 펼쳐짐(`.feed-item.open`). 여러 항목을 펼친 뒤 일일이 다시 클릭해 접어야 함. 헤더에 일괄 접기 버튼을 추가하여 펼쳐진 detail 을 한 번에 닫음.
* 상세:
    - 요청 출처: ___pm hub 점검 — 활동 피드 "모두 줄이기 아이콘" 추가 요청
* 구현 명세:
    - `services/htm-server/server.py` HUB_HTML:
        - CSS — `.feed-actions` flex 그룹 추가, `#feed-collapse-all` 스타일을 기존 `#feed-toggle` 와 공유(셀렉터 그룹화)
        - `.feed-head` — `feed-count` 와 `feed-toggle` 사이를 `.feed-actions` span 으로 묶고 `⊟` 버튼(`#feed-collapse-all`, title "펼친 항목 모두 줄이기") 추가
        - JS — `feedCollapseAll` 클릭 핸들러: `openFeedItems.clear()` + `feedList` 의 `.feed-item.open` 전체 `open` 클래스 제거
    - 검증: 서버 재기동 → `curl /hub` 에 `feed-collapse-all` 포함 확인. 피드 항목 다수 펼침 → `⊟` 클릭 시 일괄 접힘

## Issue47: hub 활동 피드 — 프로젝트 아이콘·이름 표시 토글 (등록: 2026-05-20, 해결: 2026-05-20, commit: 024c9bd) ✅
* 목적: hub `/hub` 활동 피드 항목이 `[상태아이콘][프로젝트이모지][프로젝트명][요약]` 고정 표시임. 프로젝트이모지(Issue46)·프로젝트명 노출 여부를 `hub_setting.yml` 설정으로 켜고 끌 수 있게 함 — 단일 프로젝트 작업 시 중복 정보 제거, 다중 프로젝트 시 식별성 우선 등 사용자 취향 대응.
* 상세:
    - 요청 출처: ___pm hub 점검 — 활동 피드 프로젝트 아이콘·이름 표시 유무 기능 요청
    - 설정 위치: `data/hub_setting.yml` (기존 `feed_*` 키와 동일 계열, 사용자가 IDE 로 해당 파일 오픈)
* 구현 명세:
    - `data/hub_setting.yml` — `feed_show_project_emoji`(기본 true)·`feed_show_project_name`(기본 true) 2개 키 추가
    - `services/htm-server/server.py`:
        - `HUB_SETTING_DEFAULTS` 에 2개 bool 키 추가 (`_load_hub_setting` 의 true/false 캐스팅 재사용)
        - `_handle_hub` — `{FEED_SHOW_PROJECT_EMOJI}`·`{FEED_SHOW_PROJECT_NAME}` placeholder 를 설정값으로 치환 (`{FEED_DEFAULT_VISIBLE}` 패턴)
        - HUB_HTML — `FEED_SHOW_EMOJI`/`FEED_SHOW_NAME` JS 상수 + `renderFeed` 에서 `feed-proj-emoji`·`feed-title` 조건부 렌더
    - 검증: 서버 재기동 → `feed_show_project_emoji: false` 시 이모지 숨김 / `feed_show_project_name: false` 시 프로젝트명 숨김 / 양쪽 true(기본) 시 종전 동일. 사용자 hub 확인 "잘 작동함"

## Issue45: hub registry 항목 mtime 캐시 — 폴링마다 전체 재파싱하던 오버헤드 제거 (등록: 2026-05-20, 해결: 2026-05-20, commit: 68fce76) ✅
* 목적: hub `/hub` 페이지가 `feed_poll_interval`(기본 5초)마다 `/dashboards` 를 폴링할 때 서버가 등록된 htm·dash 산출물 전체를 매번 open+read+parse 함. 등록 문서가 늘수록 폴링당 파일 IO 가 선형 증가하나, 실제 내용이 바뀐 항목은 새로 추가된 소수뿐임. mtime 불변 항목은 재파싱을 생략하고 추가·변경분만 실제 IO 하도록 전환.
* 상세:
    - 요청 출처: ___pm hub 점검 — "재스캔 없이 추가분만 증분 업데이트" 요청
    - 현재: `_handle_dashboards` → dash 항목마다 `_read_dash_file`(open+read+json/yaml parse), `_collect_htm_docs` → htm 항목마다 `os.stat` + `_extract_html_title`(open+8KB read+regex). 폴링 주기·브라우저 수에 비례하여 전수 반복
    - 스코프 판정: 생산자(htm 커맨드 step7, dashboard-runner.sh `register_doc`)는 이미 `/register-doc` 로 증분 등록 중 → 글로벌 SCAR(htm 커맨드·dashboard 에이전트) 수정 불필요. 본 이슈는 ___pm htm-server 읽기 경로 단독
* 구현 명세:
    - `services/htm-server/server.py`:
        - 모듈 레벨 `_doc_parse_cache`(abs_path → {mtime_ts, data}) + `_doc_parse_cache_lock` + `doc_cache_get`/`doc_cache_put` 헬퍼 추가 (`_load_projects_colors` mtime 캐시 패턴 동일 철학). 256 항목 초과 시 clear
        - `_read_dash_file` — `os.stat` 후 mtime 캐시 hit 시 저장 dict 복사본 반환(호출측 mutate 대비), miss 시 파싱 후 캐시 적재
        - `_collect_htm_docs` — `_extract_html_title` 호출을 mtime 캐시 경유로 전환
    - 검증: 단위 테스트 6종(cache get/put·mtime 무효화·빈문자열 hit 구분·cap·mutate 격리·부재파일) PASS, `/dashboards` 2회 폴링 byte-동일
    - 종결: 코드는 동시 진행된 Issue46 커밋(`68fce76`)에 함께 swept 되어 별도 기능 커밋 없음. 본 이슈는 문서 종결만 수행

## Issue46: hub 활동 피드 항목에 프로젝트 이모지 표시 (등록: 2026-05-20, 해결: 2026-05-20, commit: 68fce76) ✅
* 목적: hub `/hub` 활동 피드 항목이 상태 아이콘(✅/❓/🔔) + 프로젝트명만 표시해 다중 프로젝트 식별이 약함. `Projects.md` 이모지 컬럼 값을 상태 아이콘과 프로젝트명 사이에 노출하여 시각 식별성 강화.
* 상세:
    - 요청 출처: ___pm hub 점검 — 활동 피드 패널 식별성 개선 요청
    - 상태 아이콘은 정상 동작 — 그 우측·프로젝트명 좌측에 프로젝트 이모지 삽입
* 구현 명세:
    - `services/htm-server/server.py`:
        - `_load_projects_emojis()` — `Projects.md` 📋 테이블 cwd 경로 → 이모지 매핑 (`_load_projects_colors` mtime 캐시 패턴)
        - `_project_emoji(cwd)` 헬퍼 + `project_meta` 에 `emoji` 추가
        - `_handle_hook_event` — 신규 feed 항목에 `emoji` 저장
        - `_handle_dashboards` — `hook_feed` 전 항목에 `emoji` 재계산 부여 (기존 항목·Projects.md 라이브 반영)
        - HUB_HTML `renderFeed` — `feed-icon` 과 `feed-title` 사이 `.feed-proj-emoji` span 삽입
    - 검증: `/dashboards` 응답 19개 피드 항목 전부 `emoji` 채워짐 (`___pm`→🗓️🎯, `_doc`→💜, `m2slide`→🎬📑, `.claude`→🧠), 서빙 HTML 에 `feed-proj-emoji` 코드 포함 확인

## Issue44: htm 만 실행한 프로젝트가 dashboard 섹션에 빈 카드로 노출 (등록: 2026-05-20, 해결: 2026-05-20, commit: bbf8894) ✅
* 목적: `htm` 스킬만 실행한 프로젝트(dashboard 미실행)가 hub dashboard 섹션에 "활성 dashboard 없음" 빈 카드로 노출됨. htm 스킬은 `/view` token 발급 위해 `/register` 를 호출하므로 `projects` dict 에 등록되고, `_handle_dashboards` 가 dash 0건 등록 프로젝트도 빈 카드로 추가하기 때문. dashboard 를 실행하지 않은 프로젝트는 dashboard 섹션에 표시될 이유가 없음.
* 상세:
    - 요청 출처: ___pm hub 점검 중 사용자 지적 (스크린샷 1 — m2slide 가 htm 만 했는데 dashboard 카드로 표시)
    - 근본 원인: `_handle_dashboards` 의 "dash 등록 0 인 등록 프로젝트도 빈 카드로 노출" 블록 (server.py:996-1005)
* 구현 명세:
    - `services/htm-server/server.py` `_handle_dashboards` — dash-registry 미등록 프로젝트를 빈 카드로 append 하는 블록 제거. dashboard 섹션은 `dash-registry.json` 등록 항목만 노출
    - 검증: 서버 재시작 후 `GET /dashboards` → `projects: []` (m2slide 제거), `htm_docs: ['m2slide']` (htm 섹션 유지)

## Issue43: hub dashboard 섹션 빈 상태 — `..htm dash` 안내 문구 제거, 비워두기 (등록: 2026-05-20, 해결: 2026-05-20, commit: bbf8894) ✅
* 목적: hub `/hub` dashboard 섹션이 등록 dashboard 0건일 때 "등록된 프로젝트 없음. `..htm dash`로 dashboard 시작." 안내 문구를 표시함. `..dashboard` alias 도 정상 동작하므로 특정 alias 만 안내하는 문구는 오해 소지가 있고, 사용자는 dashboard 없을 때 섹션을 비워두기를 원함.
* 상세:
    - 요청 출처: ___pm hub 점검 중 사용자 지적 (스크린샷 2 — 빈 상태 안내 문구)
    - `..htm dash` / `..dashboard` 둘 다 유효 alias (Issue41). `..dashboard` 미동작 아님 — 단지 문구가 한쪽만 안내
* 구현 명세:
    - `services/htm-server/server.py` HUB_HTML `renderProjects()` — `!projects.length` 분기의 `grid.innerHTML` 안내 문구를 빈 문자열로 교체

## Issue41: htm-server hub 를 등록 기반(registry)으로 전환 — 디렉토리 스캔·실제 파일 삭제 제거 (등록: 2026-05-20, 해결: 2026-05-20, commit: 3c5b1ca) ✅
* 목적: hub `/dashboards` `/hub` 가 등록 프로젝트의 `_doc_work/z_htm/` 를 5초 주기 스캔하고, clear 버튼이 `os.remove` 로 다른 프로젝트의 `.html`/`.dash.*` 파일을 영구 삭제했음. (a) 타 프로젝트 디렉토리 무차별 접근 (b) hub 가 추적만 하던 파일 파괴 — 두 문제 제거. hub 가 `data/hub/` registry 에 등록된 항목만 노출하고, clear 는 registry 항목만 제거(파일 보존)하도록 전환.
* arch: `_doc_arch/hub_htm.md`
* depends: 생산자 자동 등록 측은 글로벌 SCAR — `~/.claude/Issue.md` Issue69
* 적용:
    - `data/hub/{htm,dash}-registry.json` — hub 목록 SSOT (런타임 상태, `.gitignore`). 항목 스키마 `{path, cwd, title, registered_at}`. `data/hub/README.md` 동봉
    - `services/htm-server/server.py`:
        - registry 상수 + `load_registry`/`save_registry` 헬퍼 (tmp→`os.replace` 원자적 저장)
        - `POST /register-doc` — 생산자가 산출 파일 등록 (디렉토리 스캔 대체, path dedup)
        - `POST /hub-rescan` — 수동 부트스트랩, 등록 누락분 1회 스캔 수거 (hub 버튼 트리거 전용, 자동 호출 없음)
        - `_read_dash_file()` — 등록 경로 1건만 read (디렉토리 스캔 없음)
        - `_handle_dashboards` / `_collect_htm_docs` — registry 기반 재작성, cwd 로 프로젝트 그룹화, 파일 부재 시 `missing:true`
        - `_handle_clear_done` / `_handle_clear_htm_docs` — registry 항목만 제거, `os.remove` 전부 삭제. dead code `_delete_dash_files` 제거
        - HUB_HTML — `🔄 디스크 재스캔` 버튼 추가, clear 버튼 라벨·confirm·toast 를 "목록에서 제거(파일 보존)" 로 변경, `removed_count` 응답 키 반영
    - `_doc_arch/hub_htm.md` — `hub registry 모델` 섹션 + `/register-doc`·`/hub-rescan`·`/clear-*` 명세 추가
    - `services/htm-server/README.md` — registry endpoint 명기
    - `.gitignore` — `data/hub/*.json`
* 검증:
    - `python3 -m py_compile server.py` OK
    - `/register-doc` htm/dash 등록 → `/dashboards` 반영, cwd→프로젝트 매핑·token view_url 확인
    - `/clear-done` missing dash 제거 → registry `[]`, 실제 파일 보존
    - `/clear-htm-docs?keep=0` htm 항목 제거 → registry `[]`, 실제 `.html` 파일 보존 확인 ✓ (핵심 요구)
    - `/hub-rescan` → `/tmp/___pm` htm 2건 수거
    - `/hub` HTTP 200

## Issue40: htm 스킬 단발 출력을 hub `/hub` 페이지에 노출 (등록: 2026-05-20, 해결: 2026-05-20, commit: f791299) ✅
* 목적: htm 스킬은 `claude-htm-{ts}.html` 평면 파일만 생성하고 `.dash.*` 사이드카가 없어 hub `/hub` 페이지가 모니터링 못 함. 서버가 htm 출력 html 을 직접 스캔하여 hub 에 별도 섹션으로 노출. htm 스킬 무수정 → 글로벌 SCAR 변경 없음, ___pm 단독 변경
* 적용:
    - `services/htm-server/server.py`:
        - `_extract_html_title()` — html head 8KB 에서 `<title>` 추출
        - `_scan_htm_docs_in(dir)` — `claude-htm-*.html` 스캔, 동반 `.dash.*` 형제 있는 html 제외 (dashboard 산출물 방어)
        - `_scan_htm_docs(cwd)` — 프로젝트 `_doc_work/z_htm/` 대상
        - `_scan_tmp_htm_docs()` — `/tmp/___pm` 평면 fallback
        - `_collect_htm_docs()` — 등록 프로젝트 + /tmp 평면 평탄 목록, mtime desc 정렬, view_url 부여 (프로젝트 매핑은 `/view` endpoint, /tmp 평면은 token 없어 비활성 + `virtual:true`)
        - `_handle_dashboards` 응답에 `htm_docs` 추가
        - hub HTML: `📄 htm 문서` 섹션 + `renderHtmDocs()` + `.card.htm-doc` 보라색 좌측 바 CSS + `reload()` summary `htm doc` 카운트
    - `_doc_arch/hub_htm.md` — `/dashboards` 응답 스키마에 `htm_docs` 동기화
* 검증:
    - `python3 -m py_compile server.py` 통과
    - 서버 restart → `/dashboards` 응답 `keys: [projects, live_sessions, htm_docs, ts]`, `htm_docs count: 42` 인식, `<title>` 추출 정상
    - `/hub` HTML 에 `htm-docs-section`/`renderHtmDocs`/`htm 문서` 마커 존재 확인
* 비고:
    - htm 문서는 status 없음 → 기존 `🧹 Clear done/stopped` 버튼 영향 없음 (파일 보존 의도 유지). 누적 정리 수단(TTL/별도 clear)은 후속 이슈 후보

## Issue39: htm-server `/tmp` → `/tmp/___pm/` 통합 (등록: 2026-05-19, 해결: 2026-05-19, commit: 3ae04b1, depends ~/.claude#Issue64) ✅
* 목적: `~/.claude#Issue64` 동기 — htm/dashboard fallback 산출물이 `/tmp` 평면에 흩어져 OS 관리 어려움. server 측 STATE_DIR/INBOX_ROOT + `/tmp` dash scan 경로를 `/tmp/___pm/` 하위로 통합
* 적용:
    - `services/htm-server/server.py`:
        - `STATE_DIR`/`INBOX_ROOT` → `/tmp/___pm/claude-htm-{server,inbox}` (line 36-37)
        - `_scan_tmp_dashes` tmp_dir `/tmp` → `/tmp/___pm` (line 511)
        - 가상 프로젝트 cwd/name `/tmp`·`system/tmp` → `/tmp/___pm`·`system/___pm-tmp` (line 704-706)
        - `_handle_clear_done` scan dir `/tmp` → `/tmp/___pm` (line 803)
        - HTML 주석 (line 1784, 1956) `Issue32` → `Issue32/Issue39` 라벨 갱신
    - `services/htm-server/README.md` — `/tmp/claude-htm-{server,inbox}` 전부 `/tmp/___pm/...` 로 일괄 치환
    - `mkdir -p /tmp/___pm` 부팅 보장: `os.makedirs(STATE_DIR, exist_ok=True)` 가 `/tmp/___pm` 부모 자동 생성 (server.py:2362)
* 검증:
    - `python3 -m py_compile server.py` 통과
    - server kill + restart → healthz `pid=80598, status=ok`
    - `/tmp/___pm/{claude-htm-server,claude-htm-inbox}/` 자동 생성 확인
* 비고:
    - 기존 `/tmp/claude-htm-{server,inbox}/` 잔존물은 휘발 데이터 → 다음 OS 재부팅 또는 수동 `rm -rf` 로 정리
    - hub 카드 라벨 `system/tmp` → `system/___pm-tmp`

## Issue37: dashboard-runner zombie 차단 — runner lifecycle + register-pid 자동화 (등록: 2026-05-19, 해결: 2026-05-19, commit: 10dac29, depends ~/.claude#Issue63=f70d4d1) ✅
* 목적: dashboard agent 종료 후 dashboard-runner.sh zombie 잔존 → 11s 주기 `/notify`+`/session/update` → hub `live_sessions` 5s alive_window 안팎 깜빡임. `/control` stop 시도 시 `not registered for hash` 403
* 적용:
    - (1) runner 시작 시 `/register-pid` 자동 호출 — `~/.claude/agents/dashboard-runner.sh:147` (글로벌 ~/.claude#Issue63 commit f70d4d1)
    - (2) SIGTERM/SIGHUP trap + ORIG_PPID 캡처 후 main loop 안 `kill -0 $PPID` 부모 사망 감지 자가 종료 — dashboard-runner.sh:41,134,170-172 (글로벌 ~/.claude#Issue63 commit f70d4d1)
    - (3) htm-server zombie 노출 차단 — `_collect_live_sessions` subs<=0 + alive registered_pid 없음 → 제외 (services/htm-server/server.py:706-, commit 10dac29). `_pid_alive(pid)` 헬퍼 추가 (server.py:204)
* 검증:
    - server restart 후 `/dashboards` `live_sessions=[]` (zombie nowage sid 31df5fdf1c12 노출 차단)
    - dashboard agent stop → 5s 후 hub UI live_sessions 사라짐
* 참조:
    - server-side fix: commit 10dac29 (본 prj)
    - runner-side fix: ~/.claude#Issue63 commit f70d4d1 (글로벌 SCAR)

## Issue38: htm Hub sort dropdown 동작 정상화 — 진행률순 무동작 fix + dashless stable comparator (등록: 2026-05-19, 해결: 2026-05-19, commit: 10dac29) ✅
* 목적: hub 우측 상단 `sort` dropdown 사용자 인지 "작동안함". 실측 결과 `진행률순` 선택 시 카드 순서 무변화. 원인 — 모든 dash 의 `progress` 필드가 `null` 이므로 `(b||0)-(a||0) === 0` → stable sort 가 직전 순서 그대로 유지 → 시각 변화 없음. dashless 카드(`활성 dashboard 없음`) 끼리 비교 시 comparator 가 `1` 만 반환 (대칭성 위반) → undefined behavior
* 상세:
    - 재현: hub `진행률순` 클릭 → 카드 순서 직전 정렬 그대로 (cards no-op)
    - comparator: `services/htm-server/server.py:1842-1865` (수정 후)
* 적용:
    - dashed 우선, dashless 끼리는 `name` asc 로 stable
    - 진행률순: null progress 는 뒤로, 동률은 mtime desc tiebreaker
    - 이름순: 프로젝트명 동률 시 mtime desc tiebreaker
    - 사후 verify (playwright): recent (mtime desc) / name (proj asc + mtime tiebreaker) / progress (null → mtime fallback) 3 모드 모두 시각적 차이 발생 + dashless 8개는 모든 모드에서 alphabetical stable
* 비고: Issue37 zombie 차단과 같은 commit (10dac29) 에 land

## Issue35: htm Hub 카드 `.html` 부재 시 dash 파일 인라인 렌더 (등록: 2026-05-19, 해결: 2026-05-19, commit: 20c3c98) ✅
* 목적: dashboard agent가 `.html` 산출물을 만들지 않고 `.dash.{json,yaml,yml}` 만 쓰는 케이스에서 hub "열기" 버튼 동작 보장. 이전 A안(`.html` 없으면 "열기" 숨김) 대체
* 채택: 옵션 C-1 — `_handle_view`가 `.dash.{json,yaml,yml}` 도 수락, server-side 인라인 렌더
* 적용:
    - `_serve_dash_inline(abs_path)` 신규 메서드 (`server.py:1033-`). json은 stdlib, yaml은 PyYAML 우선 + `_parse_dash_yaml` fallback. 응답: title/status/pid/progress + widgets 카드 grid + raw source `<details>`
    - `_handle_view` 분기 추가 — `.dash.{json,yaml,yml}` 들어오면 `_serve_dash_inline` 위임 (server.py:985)
    - `_handle_dashboards` `view_url` 생성 — `.html` 우선, 없으면 dash 파일 경로로 fallback (A안 fix 복원)
* 검증:
    - `curl /view?...path=...dash.yaml` → HTTP 200 + HTML (title=folder-creation-monitor, status=running, pid=93132, widgets 5개 카드) ✅
    - `curl /view?...path=...dash.json` → HTTP 200 + HTML (status=done) ✅
    - cwd jail 유지 — `/etc/passwd` 시도 → 403 "path outside cwd" ✅
* 후속:
    - SPA-grade 인터랙션 (stop/refresh/kill 버튼, SSE auto-reload) — 별도 이슈로 분리 (현 구현은 read-only)

## Issue36: htm Hub 카드 dash path 표시 — 프로젝트 내부는 상대 경로, /tmp 는 절대 경로 (등록: 2026-05-19, 해결: 2026-05-19) ✅
* 목적: hub 카드 path 표시 가독성 개선. 프로젝트 cwd 하위 dash 는 `_doc_work/z_htm/...` 상대 경로, /tmp 가상 dash 는 절대 경로 유지
* 구현 명세:
    - `services/htm-server/server.py` `_handle_dashboards` 루프(server.py:651-) 에 `path_display` 필드 산출. cwd prefix 일치 시 `os.path.relpath(path, cwd)`, 미일치 또는 예외 시 절대 경로 fallback
    - 가상 프로젝트(/tmp) dash 는 `path_display` 미설정 → SPA 폴백으로 절대 경로 유지
    - SPA 카드 렌더(`d.path` → `d.path_display || d.path`) — server.py:1697
    - 검증: `curl /dashboards` 응답 — `.claude` cwd dash 는 `_doc_work/z_htm/folder-creation-monitor.dash.yaml`, `system/tmp` virtual 은 `/tmp/test2-folder-creation.dash.yaml` 절대 유지

## Issue34: ___pm 로컬 `/hub` 커맨드 추가 — htm-server lifecycle wrapper (등록: 2026-05-19, 해결: 2026-05-19, commit: 95bb50f) ✅
* 목적: port 9876 htm-server 운영을 ___pm 컨텍스트에서 짧은 별칭으로 제어 + state wipe (clear) 추가
* 상세:
    - 서브커맨드: `start`, `stop`, `restart`, `clear`
    - `clear` = tokens.json / sessions.json / opened-* 삭제, PID 유지 (서버 재시작 없음), 로그 보존
    - 글로벌 `/dashboard-server` 와 동일 서버 대상. `clear` 추가가 차별점
* 구현 명세:
    - 신규: `.claude/commands/hub.md` (105 라인)
    - SSOT: `_doc_arch/hub_htm.md`
    - 글로벌 wrapper: `~/.claude/commands/dashboard-server.md`

## Issue32: htm-server `/tmp` fallback dash 노출 (Issue31 (b) 후속) (등록: 2026-05-19, 해결: 2026-05-19, commit: c9bf32e) ✅
* 목적: cwd 에 `_doc_work/z_htm/` 부재 + dashboard agent OUT_DIR=/tmp fallback 케이스에서 dash 파일이 hub 에 미노출
* 채택: 옵션 (2) — `/tmp` dash 를 별도 가상 프로젝트 `system/tmp` 카드로 노출. dashboard.md 글로벌 SCAR 변경 회피, cwd 매핑 불필요
* 적용:
    - `_scan_tmp_dashes()` 신규 메서드 — `/tmp/*.dash.{json,yaml,yml}` 평면 스캔. yaml/json 공통 파싱 헬퍼 (`_parse_dash_yaml`/`_fill_dash_entry_from_dict`) 재사용
    - `_handle_dashboards` 응답 끝에 `virtual: true` 가상 entry append (`cwd_hash="__tmp__"`, `token=""`, `color="hsl(0,0%,75%)"`)
    - SPA hub: `card.virtual` CSS (점선 테두리) + view/stop 버튼 비활성 (token 없음) + dash 파일 경로 직접 노출
* 검증:
    - `/tmp/issue32-verify.dash.yaml` (`status:running`, `progress:42`, `pid:88888`) → `/dashboards` 응답에 `system/tmp` 가상 project 카드로 노출 확인 ✅
* 후속:
    - 옵션 (1)(dashboard.md `cwd:` 필드 추가) 채택 시 별도 글로벌 SCAR 이슈 등록 후 진행 가능. 본 이슈로 현재 케이스는 커버됨

## Issue33: htm-server hub `live_sessions` 노출 (Issue31 (c) 후속) (등록: 2026-05-19, 해결: 2026-05-19, commit: c9bf32e) ✅
* 목적: SSE alive (subscriber>0) 또는 최근 update<5s 인 registered session 을 hub 에 노출. 파일 dash 무관 live-only session 인식
* 채택: 옵션 (1) — `/dashboards` 응답에 `live_sessions` 배열 별도 추가. hub UI 별도 섹션 `📡 활성 세션` 분리 표기
* 적용:
    - `_collect_live_sessions(alive_window=5.0)` 신규 메서드 — `sessions` × `sse_subscribers` × `projects` lock 스냅샷 합성. `updated_age` 오름차순 정렬
    - 응답 메타: `cwd/cwd_hash/sid/name/color/mode/content_type/updated_age/subscribers/url`
    - SPA hub: `<section id="live-sessions-section">` + `renderLiveSessions()` JS. `.card.live` 좌측 그린 바 (3px solid hsl(140,60%,45%))
    - status-bar summary 갱신: `{N} project · {M} dashboard · {L} live session`
* 검증:
    - 기존 etc. mode=C 세션 `/s/55fe3c6f/31df5fdf1c12` (cwd=`$HOME`, content_type=dashboard, updated_age=1.0s) → `live_sessions[0]` 정확 노출 확인 ✅
    - hub HTML grep: `live-sessions-section`/`renderLiveSessions`/`virtual` 토큰 8건 매칭 ✅
* 비고: Issue32 와 동일 commit (c9bf32e) 에 land — SPA hub 동시 갱신 필요로 분리 불가능



## Issue31: htm-server `_scan_dashes` yaml status 파싱 + hub 활성 세션 인식 (등록: 2026-05-19, 해결: 2026-05-19, commit: fc36967) ✅
* 목적: `/hub` 의 `활성만` 필터가 실행 중 dashboard 를 잡지 못함. cwd=`$HOME` (홈) + `/tmp/test2-folder-creation.dash.yaml` 사례
* 적용 (a 만 — b/c 는 Issue32/Issue33 으로 분리):
    - `_scan_dashes` 가 `.dash.yaml/.yml` 도 status/title/pid/progress 추출 (services/htm-server/server.py:454)
    - 신규 헬퍼: `_parse_dash_yaml` (경량 yaml 파서, dashboard.md 양식 한정 — top-level scalar + widgets[id=progress].value), `_yaml_scalar` (null/true/false/quoted/int/float/str), `_fill_dash_entry_from_dict` (json/yaml 공통 entry 충전)
    - PyYAML 의존 추가 없음 — stdlib only
* 검증:
    - `cwd/_doc_work/z_htm/` 에 `status: running` yaml 배치 → `/dashboards` 응답에 `status="running"`, `title`, `progress`, `pid` 모두 추출 확인 ✅
    - yaml `widgets:` 빈 list 케이스도 정상 처리 ✅
* 후속 (분리):
    - Issue32: `/tmp` fallback 경로 스캔 (cwd=홈+/tmp 케이스)
    - Issue33: live session 가상 dash 노출 (registered SSE alive session)
* 비고: Issue31 (a) 코드는 Issue30 (모듈 분리, commit `fc36967`) 와 동일 commit 에 포함되어 land. 본 close commit 은 doc 갱신만.

## Issue29: htm-server Mode C Phase 6 — milestone Notification API + preview endpoint (등록: 2026-05-19, 해결: 2026-05-19, commit: 725c679) ✅
* 목적: Issue24 plan Phase 6 (선택) — dashboard 의 사용자 인지 채널 + 발행 전 검증 채널 확보
* 출처: Issue24 (commit `c558004`) Phase 1~5+7 완료 후 잔여 phase
* 적용:
    - (a) Notification API: SPA shell 초기화 시 `Notification.requestPermission()` 1회. progress 위젯 임계치(50/80/100%) 통과 시 `new Notification()` 발행. `progressNotified[widget_index]` 에 최고 도달 임계치 기록하여 재발 차단 (hysteresis). `tag` 키 = `${CWD_HASH}:${SID}:${widget_index}:${threshold}` (OS dedup)
    - (b) `POST /session/preview?cwd=&token=` endpoint — `validate_dashboard` 적용(`?lenient=1` 우회 가능), ephemeral preview entry 생성 (TTL 60s, `previews` dict + `preview_lock`), sessions table 미반영, SSE 미전파. 응답: `{ok, mode, preview_url, ttl}`
    - (c) `GET /preview/{cwd_hash}/{pid}` — PREVIEW SPA shell (`{PREVIEW}=1` placeholder). 동일 SESSION_SHELL_HTML 재사용, `ROOT_PREFIX` 가 `/s/` vs `/preview/` 분기. PREVIEW 모드는 SSE/polling/알림 모두 skip. 헤더 표기 `🔍 PREVIEW: {name}`
    - (d) `GET /preview/{cwd_hash}/{pid}/data` — preview JSON (`preview:true`). TTL 만료 시 404
    - (e) `_doc_arch/hub_htm.md` Phase 6 섹션 추가 (API 명세 + Notification 동작 + PREVIEW placeholder 규약)
* 검증:
    - POST `/session/preview` (valid dashboard) → 200 + preview_url ✅
    - GET preview HTML → `🔍 PREVIEW` 헤더 + `const PREVIEW = "1" === "1"` 주입 확인 ✅
    - GET preview/data → `preview:true` 필드 ✅
    - 잘못된 widget type → 400 "widget[0].type unknown" ✅
    - `?lenient=1` 우회 → 200 (검증 skip) ✅
* 후방호환: 외부 API 변경 없음 (신규 endpoint만 추가)
* 참고: Issue30 (server.py 모듈 분리) 와 동시 진행 — 본 commit (725c679) 에 Issue30 일부 분리 (validators/spa_form/spa_widgets/spa_dashboard import) 포함되었으나 별도 commit (fc36967) 에서 본격 완성

## Issue30: services/htm-server/server.py 모듈 분리 (2130 줄 → 4 모듈) (등록: 2026-05-19, 해결: 2026-05-19, commit: fc36967) ✅
* 목적: server.py 단일 파일 ~2130 줄 → 가독성·테스트성 회복
* 적용:
    - `validators.py` (86줄) — validate_dashboard + DASH_WIDGET_TYPES
    - `spa_form.py` (194줄) — FORM_JS (inferType/renderField/renderForm/collectAnswers/submitForm/renderAnswerPlaceholder/copyAnswersJSON 7개)
    - `spa_widgets.py` (98줄) — WIDGET_JS (renderWidget 9종)
    - `spa_dashboard.py` (127줄) — DASHBOARD_JS (renderDashboard/dispatchWidgetAction/dashStop/dashRefresh/dashKillPane)
    - `server.py` — 2130 → 1946 줄. SESSION_SHELL_HTML 은 3-segment concat (`"""head""" + FORM_JS + WIDGET_JS + DASHBOARD_JS + r"""tail"""`)
* 검증:
    - validate_dashboard 단위 테스트 (valid/unknown/missing) 통과
    - `/session/update?content_type=dashboard` 정상 200, unknown 400, ?lenient=1 우회 200
    - Mode B form round-trip 정상
    - SPA shell 35KB HTML 응답 — 13 JS 함수 전부 + 모든 placeholder 치환 확인
* 후방호환: 외부 API 변경 없음

## Issue28: htm-server HTML 템플릿 배경 흰색 고정 + project_meta() Projects.md peacock.color 참조 (등록: 2026-05-19, 해결: 2026-05-19, commit: fecf778) ✅
* 목적: `services/htm-server/server.py` 의 HUB_HTML + SESSION_SHELL_HTML 두 템플릿에 `@media (prefers-color-scheme: dark)` override 가 있어 OS 다크모드 시 dashboard·session 셸이 검정 배경으로 렌더. 또한 `project_meta()` 가 cwd_hash 기반 hsl 자동 컬러를 사용 → `~/_git/___pm/Projects.md` 의 peacock.color 컬럼 무시. 사용자가 흰 배경 고정 + Projects.md 컬러 참조 요청
* 짝 이슈: `~/.claude#Issue58`
* 상세:
    - 요청 출처: ~/.claude 작업 중 (스크린샷: dashboard 검정 배경 vs 다른 폼 흰 배경 비일관)
    - 영향 파일: `services/htm-server/server.py` (HUB_HTML CSS + SESSION_SHELL_HTML CSS + `project_meta()` Projects.md 파서)
* 구현 명세 (적용):
    - (a) HUB_HTML: `@media (prefers-color-scheme: dark) { :root { ... } }` 블록 삭제. 흰 배경 변수만 사용
    - (b) SESSION_SHELL_HTML: 동일하게 다크 override 블록 삭제. `header.sess` 글자색 `white` → `#1a1a1a` (peacock.color 파스텔 대비)
    - (c) `.card-head` 글자색 `white` → `#1a1a1a` + `.badge` 배경 어두운 톤으로 (파스텔 헤더 대비)
    - (d) `_load_projects_colors()` 신규 함수: Projects.md `📋 프로젝트` 테이블 파싱 → `{abs_path: hex_color}` 매핑 (mtime 캐시)
    - (e) `project_meta()`: Projects.md 매핑 우선, 없으면 기존 `hsl(hue, 60%, 45%)` fallback
* 검증:
    - 서버 restart 후 `http://127.0.0.1:9876/` (Hub) 흰 배경
    - session SPA 흰 배경 + 헤더 peacock.color
    - OS 다크모드에서도 흰 배경 유지
    - ~/.claude 세션 헤더 `#f0d5cc`, ___pm 세션 헤더 `#ffffdd` 등 Projects.md 값 그대로

## Issue27: htm-server SPA dashboard refresh 버튼 + /control?action=refresh 액션 (등록: 2026-05-19, 해결: 2026-05-19, commit: f71f985) ✅
* 목적: SPA dashboard 헤더에 ⏹ stop / ✕ kill_pane 외 🔄 refresh 버튼 추가. 사용자가 interval 무시하고 즉시 1 iter 강제 갱신 + DOM 강제 swap 가능하게 함. ~/.claude#Issue56 (dashboard agent + runner refresh 지원) 와 양방향 연동
* 상세:
    - 요청 출처: ~/.claude 작업 중 ("dashboard 에이전트 업데이트. stop만 있는데 refresh버튼 추가 필요. agents가 리프레쉬 주기도 관리해야함")
    - 영향 파일: `services/htm-server/server.py` (renderDashboard / `/control` action 분기 / data schema controls 필드)
    - 짝 이슈: `~/.claude#Issue56` (9317593)
* 구현 명세 (적용):
    - (a) data schema `controls.refresh: true` 인식. renderDashboard 가 ctrlBar 에 🔄 refresh 버튼 prepend
    - (b) `/control` action allowlist `("stop","kill_pane","refresh")`. refresh 분기 → `os.kill(pid, SIGUSR1)` → 200 응답. PID dead → 404
    - (c) dashRefresh(pid, btn) JS: POST 성공 후 `reload(true)` 호출하여 클라이언트 DOM 즉시 swap (양쪽 다 옵션 충족)
    - (d) `_doc_arch/hub_htm.md`: `/control` action 분기 표 (stop/kill_pane/refresh)
    - (e) CSS `.dash-ctrl.refresh` (녹색)
* 검증: ~/.claude#Issue56 와 함께 사용자 검증 (test2 또는 임의 dashboard 재실행 시 🔄 버튼 + 클릭 즉시 1 iter)

## Issue24: htm Mode C(Live Dashboard) 우아함·UX·성능 개선 (등록: 2026-05-19, 해결: 2026-05-19, commit: 3343cf1, c558004) ✅
* 목적: 현재 위젯 4종(progress/table/checklist/text) + SSE+polling fallback + hub 한계 해소. 위젯 표현력 + 인터랙션 + SSE-only + hub UX 단계적 도입
* plan: `_doc_work/plan/htm-mode-c-improvements_plan.md`
* 진행:
    - ✅ Phase 1: 위젯 type 5종 (chart/log/diff/timer/badge) 추가 — commit `3343cf1`
    - ✅ Phase 2: data schema 검증 (validate_dashboard, ?lenient=1 우회) — commit `c558004`
    - ✅ Phase 3: 위젯 인터랙션 (action: link/notify/control, inbox `action-*.json` 분리, `_handle_session_action` endpoint) — commit `c558004`
    - ✅ Phase 4: SSE-only + `es.onerror` polling fallback + status indicator (🟢🟡🔴) — commit `c558004`
    - ✅ Phase 5: hub UX (filter status/sort recent/name/progress, sparkline SVG, diff-recent highlight) — commit `c558004`
    - ⏭ Phase 6: 선택 (milestone Notification API + preview endpoint) — 본 이슈에서는 미구현
    - ✅ Phase 7: dashboard 운영 모델 skill → agent 전환 — 이미 완료 상태 (`~/.claude/agents/dashboard.md` + `agents/dashboard-runner.sh` 존재, `skills/dashboard*` 없음). 본 이슈와 무관하게 사전 완료
    - 🌐 Phase 8: `/htm` 브라우저 표시 실패 대비 채팅 fallback 강화 — 글로벌 SCAR(`~/.claude/commands/htm.md` + hook) 영역. `~/.claude/Issue.md` 별도 등록 필요 (본 prj 범위 밖)
* 검증:
    - Phase 1: curl `/session/update` content_type=dashboard 위젯 10개(chart×2/log/diff/timer×2/badge×4) → mode=C ✅
    - Phase 2: unknown type → 400, missing required field → 400, `?lenient=1` 우회 200, valid → 200 ✅
    - Phase 3: POST `/s/.../action` notify → inbox `action-{ts}.json` 저장 확인, invalid action_type → 400 ✅
    - Phase 4/5: SPA shell `es.onerror`·`startPolling`·`setStatus` + /hub `filter-status`·`sort-by`·`sparkSvg`·`diff-recent` grep 확인 ✅
* 후방호환: 기존 4종 위젯(progress/table/checklist/text) 그대로 동작, schema 검증 우회 옵션 제공

## Issue25: htm-server 역할을 dashboard 전용으로 명시 — htm 스킬 분리 반영 (등록: 2026-05-19, 해결: 2026-05-19, commit: 7ce474b) ✅
* 목적: 글로벌 SCAR `~/.claude` 측 htm 스킬을 ___pm 서버 의존에서 분리(Mode A only, paste-back) → ___pm 서버는 dashboard agent(Mode C) 단독 클라이언트가 됨. 서버 설계 SSOT 와 README 를 dashboard 전용 역할로 재정렬하여 양측 정합성 확보
* 상세:
    - `_doc_arch/hub_htm.md` 상단에 역할 재정렬 박스 추가 (Issue25, 2026-05-19) — dashboard agent 가 1차 클라이언트임 명시
    - 적용 범위·글로벌 SCAR 분담·참조 섹션을 dashboard SSOT(`~/.claude/_doc_arch/dashboard.md` + `~/.claude/agents/dashboard.md`) 기준으로 재정렬
    - Mode B form/answer 섹션(Issue18 Phase 2) 헤더에 DEPRECATED 표기 — 코드 보존(후방호환), 신규 클라이언트 통합 없음
    - `services/htm-server/README.md` — 역할 문구 "htm-server (___pm 서비스)" → "htm-server (___pm 서비스) — dashboard 백엔드", 1차 endpoint(dashboard) vs deprecated endpoint(Mode B form) 분리 명시
    - `services/htm-server/server.py` 변경 없음 (호환성 유지)
* 검증:
    - grep `htm + dashboard 백엔드` 잔존 0건 ✅
    - grep `Mode B`·`paste-back` 잔존: 모두 deprecated/historical/fallback 맥락에 한정 ✅

## Issue26: htm-server form 전송 후 answers JSON paste-back fallback UI (등록: 2026-05-19, 해결: 2026-05-19, commit: 7f9287e) ✅
* 목적: Mode B 폼 전송 성공 후 SPA 가 "답변 전송됨 — Claude 처리 대기 중..." placeholder 만 표시하여, Claude polling 누락·timeout·세션 교체·새 prompt 진입 등으로 회수 실패 시 사용자가 답변을 잃음. 폼 결과 JSON 을 화면에 노출 + 복사 버튼 제공으로 paste-back 우회 동선 확보
* 상세:
    - 회귀 시나리오: (1) Claude 가 다른 작업 진입하여 inbox polling 중단, (2) 사용자가 form 전송 후 Claude 가 turn 종료, (3) 브라우저 새로고침으로 form 상태 손실, (4) timeout 600s 경과 후 새 prompt 입력으로 inbox 누락 — 어떤 경우든 사용자가 답변 JSON 을 채팅에 paste 하면 회복 가능해야 함
    - 현재 동작 (`server.py` line 983): session content 를 `<p><em>답변 전송됨 — Claude 처리 대기 중...</em></p>` 로 교체 → reload 후 정보 0
    - 신규 동작:
        1. 서버 측: `_handle_session_answer` 가 placeholder 대신 answers JSON pretty-print 한 `<pre>` 박스 + 복사 버튼이 포함된 HTML 을 session content 로 저장
        2. 클라이언트 측: `submitForm()` 성공 시 reload 의존 없이 즉시 동일 UI 렌더 (JSON 표시 + 복사 버튼 + 안내 문구)
        3. 복사 버튼: `navigator.clipboard.writeText(jsonStr)` + 성공 피드백 ("✅ 복사됨 — 채팅에 paste")
* 구현 명세:
    - `services/htm-server/server.py`:
        - `_handle_session_answer` (line 983): placeholder HTML 빌더 함수 추가. `record["answers"]` JSON dump 를 escape 한 후 `<pre>` + `<button onclick="copyAnswers()">` 포함
        - `SESSION_SHELL_HTML` `submitForm()` (line 1357): 성공 분기에서 reload 대신 `contentEl.innerHTML = ` 직접 갱신 + `copyAnswers()` global function 정의
        - 복사 JSON 형식: `record` 전체 (sid, ts, answers, source) — Claude 가 paste-back 시 동일 schema 인식
    - 검증:
        1. healthz OK 상태에서 폼 push → 전송 → JSON + 복사 버튼 표시 확인
        2. 복사 버튼 클릭 → 클립보드 내용이 record JSON 인지 확인
        3. 브라우저 reload → 동일 UI 유지 확인 (server-side placeholder 동기화)
        4. inbox 파일 read 후 삭제 시뮬레이션 → 복사한 JSON paste 만으로 Claude 가 answers 회수 가능 확인

## Issue23: htm-server Mode B form field type 확장 (text/textarea/number/slider/date) (등록: 2026-05-19, 해결: 2026-05-19, commit: c95f5b6) ✅
* 목적: Mode B form 이 radio/checkbox 만 지원하여 자유 입력·수치·날짜 답변 수집 불가. 객관식 외 필드 타입 5종 추가로 office-hours·planning 등 폭넓은 워크플로우 커버
* 상세:
    - 기존: `q.multiSelect` boolean 으로 radio/checkbox 분기만 가능. options 없는 질문은 렌더 불가
    - 신규 type 5종: `text` (single line), `textarea` (multi-line + rows), `number` (min/max/step), `slider` (range + live value display), `date` (date picker)
    - 스키마 확장 필드: `type`, `required`, `placeholder`, `default`, `min`, `max`, `step`, `rows`, `hint`
    - backward compat: `type` 미지정 시 `options` 존재 → radio/checkbox, 없으면 `text` 추론
* 구현 명세:
    - `services/htm-server/server.py`:
        - `renderForm` → `renderField` 함수 분리, `inferType(q)` 헬퍼 추가
        - 각 type 별 input HTML 생성 (slider 는 live value `<span>` 동기화, oninput 핸들러)
        - CSS: `.q-field`, `.q-slider-row`, `.q-slider-val`, `.q-hint`, `.q-required-mark` 추가
        - `collectAnswers`: card `data-type` 기반 분기. textarea trim, number/slider `Number()` 변환, 빈 입력 null
    - 검증: 7-field 혼합 폼 (text + textarea + number + slider + date + radio + checkbox) push → 브라우저 정상 렌더 확인

## Issue22: htm-server Mode B form 라디오 선택 wipe 회귀 (polling re-render) (등록: 2026-05-19, 해결: 2026-05-19, commit: c95f5b6) ✅
* 목적: Mode B 폼에서 사용자가 라디오 선택 후 전송 시 value=null 회수되는 회귀 차단. 사용자 답변 손실 방지
* 상세:
    - 회귀: `setInterval(reload, 3000)` 가 SSE 연결 무관하게 3초마다 `contentEl.innerHTML = renderForm(...)` 실행. 사용자가 라디오 선택 → 3초 내 polling 발생 → form HTML 재설정 → 선택 wipe → 전송 시 `input:checked` 0개 → value=null
    - 재현: 폼 push 후 사용자가 옵션 선택 → 3초 대기 → 전송 → 회수 JSON 의 value 가 null. 본 fix 전 색상 폼 테스트에서 실제 발생
* 구현 명세:
    - `services/htm-server/server.py` `reload()` 함수:
        - `lastSig` 모듈 변수 추가 (mode + content concat)
        - `reload(force)` 시그니처 변경. sig 동일하고 `!force` 면 statusEl 만 갱신하고 early return (innerHTML 미변경)
        - SSE event handler (`reload`, `session_update`) 는 `reload(true)` 로 강제 재렌더
        - polling 은 `reload()` 호출 → sig 비교 → 변경 시만 재렌더
    - 검증: 재시작 후 1+2 / 색상 / 계절 폼 테스트 시 value 정상 회수 (null 회귀 차단)

## Issue21: htm-server `/session/register` 응답에 SSE subscriber 카운트 포함 (등록: 2026-05-19, 해결: 2026-05-19, commit: 01eac30) ✅
* 목적: 클라이언트 hook 이 stable URL 탭 open 여부를 정확히 판정하도록 SSE subscriber 수를 진실 소스로 제공. marker 파일 단독 판정의 사각지대(사용자가 탭 닫음 → marker 잔존 → "이미 열림"으로 오판) 해소
* 연관 이슈: `~/.claude/Issue.md` Issue34 (depends 측)
* 상세:
    - `_handle_session_register` 응답 JSON 에 `subscribers` 필드 추가
    - 값: `len(sse_subscribers.get((cwd_h, sid), []))`, `sse_lock` 으로 보호
    - 클라이언트 hook (`htm-trigger.sh`) 가 0 이면 `FIRST_OPEN=yes` 강제 → 탭 재 open
* 구현 명세:
    - `services/htm-server/server.py` line 770 부근: `with sse_lock: subscribers = len(...)` 추가 후 응답에 포함
    - 검증: `curl POST /session/register` → 응답에 `"subscribers": <int>` 확인. 다중 EventSource 구독 시 카운트 증가 확인

## Issue20: htm-server Mode B inbox sid 서브폴더 격리 (등록: 2026-05-18, 해결: 2026-05-18, commit: dfd14f7) ✅
* 목적: `_handle_session_answer` 의 inbox 경로가 `{cwd_hash}` 단위만 격리되어, 동일 cwd 내 다중 Claude 세션의 답변이 교차 회수되는 회귀 차단. sid 서브폴더 추가
* 연관 이슈: `~/.claude/Issue.md` Issue32 (depends 측)
* 상세:
    - 회귀: 동일 cwd 내 sid 다른 두 세션이 Mode B 폼을 사용하면 inbox `/tmp/claude-htm-inbox/{cwd_h}/*.json` 에 양쪽 답변이 섞여 저장됨. Claude polling 패턴 `ls .../*.json` 이 무필터라 wrong sid 답변 회수
    - 영향: tmux pane / 다중 터미널 / IDE 동시 사용 시 답변 오 회수
* 구현 명세:
    - `services/htm-server/server.py` `_handle_session_answer` (line 933 부근): `inbox = f"{INBOX_ROOT}/{cwd_h}/{sid}"` 로 sid 서브폴더 신설. record 본문에 sid 필드는 이미 존재 — 경로만 추가
    - `_handle_answer` / `_handle_register` 의 cwd_h-only 경로는 backward-compat 유지 (sid 없는 legacy 호출)
    - 검증: `python3 ast.parse` 통과. 서버 재기동 후 다중 sid 동시 form 테스트 시 각자 본 sid 폴더로만 회수 확인

## Issue19: htm-server Phase 3 — Mode C dashboard renderer (등록: 2026-05-18, 해결: 2026-05-18, commit: a5c4008 [___pm]) ✅
* 목적: `~/.claude` Issue27 / Phase 3. Mode C(Live Dashboard) 를 server-side SPA shell 에서 실제 렌더. 위젯 4종 (progress/table/checklist/text) 통합
* 연관 이슈: `~/.claude/Issue.md` Issue27 (umbrella), 본 prj Issue17 (Phase 1 기반)
* depends: ___pm#Issue17 (완료, 0269a20)
* 구현 명세:
    - **SPA shell `renderDashboard(content)`**: content(JSON 문자열) 파싱 → `{title, widgets:[...]}` 추출 → `.dash-grid` 위젯 그리드 렌더
    - **위젯 type 4종**:
        - `progress`: `value` (0~100) → bar + 퍼센트 + optional `label`
        - `checklist`: `items: [{text,done}|"text"]` → ☑/☐ 마크 + done 시 line-through
        - `table`: `headers` + `rows` (array or object) → thead/tbody
        - `text`: `content`/`text` → `<pre>` 박스
    - **unknown type**: "unknown widget: {type}" `.widget.unknown` placeholder
    - **SSE reload/session_update 시 위젯 전체 swap** (`reload()` 함수 재호출, polling fallback 3초)
    - **CSS**: `dash-grid` (auto-fit, minmax 280px), `.widget` 카드, dark mode 호환
* 검증:
    - `/session/update?content_type=dashboard` body `{content:"{...JSON...}"}` → `mode:"C"` ✅
    - `/s/{h}/{sid}/data` → dashboard content 회수 (content_type=dashboard, mode=C) ✅
    - SPA shell HTML 에 `renderDashboard`/`renderWidget`/`dash-grid` 포함 ✅
    - 4종 위젯 + unknown type placeholder 모두 정상 렌더 (수동 브라우저 검증)
* 영향 파일:
    - `services/htm-server/server.py` (SESSION_SHELL_HTML — renderDashboard + renderWidget + CSS)
    - `_doc_arch/hub_htm.md` ("Mode C dashboard (Issue19 Phase 3)" 섹션)
* 비범위: 클라이언트 hook 전환 (Phase 4), file:// fallback 제거 (Phase 5), `/dashboards` `/hub` 통합 (별도 issue)

## Issue18: htm-server Phase 2 — Mode B form/answer renderer (등록: 2026-05-18, 해결: 2026-05-18, commit: a5c4008 [___pm]) ✅
* 목적: `~/.claude` Issue27 / Phase 2. Mode B(Q&A form) 를 server-side SPA shell 에서 실제 렌더. form 컴포넌트 + answer endpoint 통합
* 연관 이슈: `~/.claude/Issue.md` Issue27 (umbrella), 본 prj Issue17 (Phase 1 기반)
* depends: ___pm#Issue17 (완료, 0269a20)
* 구현 명세:
    - **SPA shell `renderForm(content)`**: content(JSON 문자열) 파싱 → `{questions:[{question, header, options:[{label, description}], multiSelect?}]}` → 각 question 을 `.q-card` 로 렌더, radio (`multiSelect:false`) 또는 checkbox (`multiSelect:true`), 마지막 "전송" 버튼
    - **`POST /s/{cwd_hash}/{sid}/answer?token=`** 신규 endpoint:
        - URL token 인증 + sid 안전화 검증
        - body `{answers:[{question, value}, ...]}` → `/tmp/claude-htm-inbox/{cwd_hash}/{ts}.json` 저장 (Claude polling 호환, `{sid, ts, answers, source:"session_answer"}`)
        - 성공 시 세션 → mode A placeholder 전환 ("답변 전송됨 — Claude 처리 대기 중...") + `sse_broadcast` → 같은 탭 자동 reload
    - **CSS**: `.q-card` border/padding, `.q-opt` 큰 클릭 영역(transform scale 1.2), `.btn-submit` accent color, dark mode 호환
* 검증:
    - `/session/update?content_type=form` body `{content:"{...form JSON...}"}` → `mode:"B"` ✅
    - `/s/{h}/{sid}/data` → form content 회수 ✅
    - SPA shell HTML 에 `renderForm`/`ANSWER_URL`/`btn-submit` 포함 ✅
    - `POST /s/{h}/{sid}/answer` → `{ok:true, path, ts}` + inbox JSON 생성 ✅
    - inbox JSON 형식: `{sid, ts, answers:[{question, value}], source:"session_answer"}` ✅
    - 답변 후 세션 자동 mode A placeholder 전환 ✅
    - 잘못된 token → 401 ✅, 빈 body (`answers` 누락) → 400 ✅
* 영향 파일:
    - `services/htm-server/server.py` (`_handle_session_answer` + SESSION_SHELL_HTML renderForm + CSS, `do_POST` `/s/.../answer` 라우팅)
    - `_doc_arch/hub_htm.md` ("Mode B form/answer (Issue18 Phase 2)" 섹션)
* 비범위: Mode C(별도 — Issue19), 클라이언트 hook 전환(~/.claude / Phase 4)

## Issue17_2: SPA shell JS 템플릿 리터럴 버그 (Python .replace 가 ${CWD_HASH} 내부 치환) (등록: 2026-05-18, 해결: 2026-05-18, commit: 15e52ef) ✅
* 부모: Issue17 (Phase 1 SPA shell)
* 증상: 브라우저 stable URL open 시 `/s/$ea6aeb24/$demo/data` 형태로 잘못된 URL → HTTP 400 → "대기 중..." 무한 stuck
* 원인: `SESSION_SHELL_HTML` JS 에 `${CWD_HASH}/${SID}/data` 템플릿 리터럴 사용. Python 측 `.replace("{CWD_HASH}", h)` 가 JS `${CWD_HASH}` 안의 `{CWD_HASH}` 도 치환 → `$ea6aeb24` 가 됨
* 해결: JS 템플릿 리터럴 → string concat 전환. `DATA_URL`, `ANSWER_URL`, `SSE_URL` 3곳
* 영향: `services/htm-server/server.py` (3줄 교체 + comment)
* 검증:
    - 재시작 후 SPA shell DATA_URL = `'/s/' + CWD_HASH + '/' + SID + '/data...'` 정상 ✅
    - `/s/ea6aeb24/demo/data?token=...` 200 OK ✅
    - 브라우저 새로고침 → 본문 표시 + SSE 구독 정상

## Issue17: htm-server Phase 1 — 세션 중심 stable URL + server-side mode dispatcher 기반 구축 (등록: 2026-05-18, 해결: 2026-05-18, commit: 0269a20, b95c54f [___pm]) ✅
* 목적: `~/.claude` Issue27의 server-side 부분. (cwd, sid) 단위 세션 상태 보관 + stable URL `/s/{cwd_hash}/{sid}` + SSE 컴포넌트 swap. Phase 1 은 Mode A(response)만 실제 렌더. Mode B(form)·Mode C(dashboard)는 sessions table 에 mode 저장만 (Phase 2~3 확장)
* 연관 이슈: `~/.claude/Issue.md` Issue27 (전체 아키텍처 + 클라이언트 측 hooks 작업)
* 구현 명세:
    - **세션 상태 모델** (`services/htm-server/server.py`):
        - `sessions[(cwd_hash, sid)] = {mode, content_type, content, capabilities, created, updated}` + `sessions_lock`
        - `persist_sessions()`: atomic flush(`tmp + os.replace`) to `/tmp/claude-htm-server/sessions.json` (mode 0600)
        - `load_sessions()`: main() 시작 시 복원
        - `cleanup()` 핸들러가 SIGTERM/SIGINT 시 persist 호출
    - **신규 endpoint**:
        - `POST /session/register?cwd=<abs>` body `{sid, capabilities?}` → `{url, token, cwd_hash, sid, mode}` (cwd 미등록 시 자동 `/register`). sid 안전화 (영문/숫자/`-`/`_` 만)
        - `POST /session/update?cwd=&sid=&token=` body `{content_type, content}` → `{ok, mode, clients}` + `sse_broadcast` (해당 sid 채널만)
        - `GET /s/{cwd_hash}/{sid}?token=` → SPA shell HTML (header + `<main id="content">` + EventSource subscribe + 3초 polling fallback)
        - `GET /s/{cwd_hash}/{sid}/data?token=` → `{content_type, content, mode, updated, capabilities}` JSON
    - **SSE 채널 확장**: `sse_subscribers[(cwd_hash, sid)]` → sid 별 분리. 빈 sid 는 backward-compat 채널 (`/events?cwd=&token=`)
    - **`sse_broadcast(cwd_h, event, data, sid=None)`**: `sid=None` 은 해당 cwd 의 모든 채널 fan-out, `sid=<str>` 은 정확 채널만
    - **`determine_mode(content_type)`**: 모드 판정 단일 진입점. `form→B`, `dashboard→C`, 그 외→`A`
    - **기존 endpoint 호환**: `/view`, `/answer`, `/notify`, `/healthz`, `/dashboards`, `/hub`, `/register`, `/control`, `/events` (sid 없는 호출) 모두 유지
    - **SPA shell**: Mode A 만 `content.innerHTML = data.content` 실제 렌더. Mode B/C 는 "Phase N에서 구현" placeholder
* 검증:
    - `py_compile` 통과 ✅
    - `/session/register` `{sid:"test1"}` → 200 + url + token ✅
    - `/session/update` content_type=response → `{ok:true,mode:"A",clients:0}` ✅
    - `/session/update` content_type=form → `mode:"B"` ✅
    - `/session/update` content_type=dashboard → `mode:"C"` ✅
    - `/s/{h}/test1/data` → JSON (content_type/content/mode/updated/capabilities 모두 표시) ✅
    - `/s/{h}/test1` → 200 `text/html` 3501 bytes, EventSource/session_update/`fetch(DATA_URL` 모두 hit ✅
    - 잘못된 token → 401 (HTML/data 양쪽) ✅
    - 잘못된 sid 형식 → 400 ✅
    - 미등록 session → 404 ✅
    - 서버 재시작 → `restored 1 sessions from /tmp/claude-htm-server/sessions.json` 로그 + 같은 URL 재open 시 마지막 content 표시 ✅
    - 기존 endpoint 회귀 없음 (`/healthz` projects=6 그대로) ✅
* 영향 파일:
    - `services/htm-server/server.py` (+250줄 — sessions state + 3 handlers + SESSION_SHELL_HTML template + persist/load + sse_broadcast sid 인자)
    - `_doc_arch/hub_htm.md` (Phase 1 섹션 + 검증 시나리오 3 케이스 추가)
* 비범위 (Phase 2~):
    - Mode B form/answer renderer 통합 (Phase 2)
    - Mode C dashboard renderer 통합 (Phase 3)
    - 클라이언트 hook 전환 (Phase 4 — `~/.claude` Issue27)
    - file:// fallback 제거 (Phase 5)

## Issue16_7: Multi-project Dashboard Hub — 전 cwd dash 통합 모니터링 페이지 (등록: 2026-05-18, 해결: 2026-05-18, commit: b4088a8 [___pm], ab4faaa [~/.claude]) ✅
* 목적: 다중 프로젝트(`.claude`, m2slide, fWarrange 등) 동시 작업 시 각 탭 개별 확인 부담 제거. `http://127.0.0.1:9876/hub` 한 페이지에서 전 cwd 의 `*.dash.json` 진행률·상태·stop 제어 통합
* 부모 이슈: Issue16, Issue16_2~Issue16_6
* 구현 명세:
    - **`services/htm-server/server.py`** (Issue16_7):
        - `GET /dashboards`: tokens.json 순회 → 각 cwd의 `_doc_work/z_htm/*.dash.{json,yaml,yml}` 스캔. `.dash.json` 만 stdlib JSON 파싱 (title/status/progress/pid + widgets[0].value fallback), `.dash.yaml` 은 메타(path/mtime)만. 응답에 각 프로젝트 token + 같은 stem `.html` 존재 시 `view_url` 자동 생성
        - `GET /hub`: 내장 HUB_HTML template — 카드 grid, 5초 polling, 진행률 bar, status badge, mini stop 버튼 (`pid` 있는 dash만), Issue16_4 callout contrast 룰 준수 (자식 `code` color/background 명시)
        - 인증: 없음 (`/healthz`와 동일 localhost trust). `127.0.0.1` bind, 동일 user 접근 가정
        - 빈 상태: dash 파일 없는 cwd는 "활성 dashboard 없음" empty 카드
    - **`_doc_arch/hub_htm.md`**: `/dashboards` + `/hub` API 명세 + 검증 시나리오 2 케이스 추가
    - **`~/.claude/commands/htm-server.md`**: Endpoints 요약 표에 `/dashboards`, `/hub` 추가
    - **`~/.claude/commands/htm.md`**: Mode C 섹션 intro에 "Hub (Issue16_7)" 1줄 추가
* 검증:
    - `/healthz` projects=6 (등록된 6 프로젝트) ✅
    - `/dashboards`: 200 + 6 프로젝트 배열. 테스트 dash 파일(title/status/progress/pid 모두 포함) 정상 파싱, view_url 생성 (`/view?cwd=&token=&path=`) ✅
    - `/hub`: 200 text/html 6.8KB ✅
    - stop 버튼: `pid` 필드 있는 dash만 렌더 (JS 검증) ✅
    - 다중 cwd 동시 등록: ___pm + .claude + fWarrange + fSnippet + videoMaker/lib/m2slide 등 카드 다건 표시 확인

## Issue16_6: htm-trigger.sh runtime reminder에 Mode A→B 자동 승격 룰 inline 강제 (등록: 2026-05-18, 해결: 2026-05-18, commit: 8887974 [~/.claude]) ✅
* 목적: Issue16_3 룰(선택지 N개 + 결정 요청 감지 시 AskUserQuestion 우선 호출)이 `commands/htm.md`에만 존재 → 옛 세션은 hook reminder만 보고 작동하여 룰 미인지 회귀. m2slide 시연에서 Mode A bullet dump 재현. runtime hook reminder text에 룰 압축본 inline 주입하여 세션 노후 무관 즉시 적용
* 부모 이슈: Issue16, Issue16_2, Issue16_3, Issue16_4, Issue16_5
* 구현 명세:
    - **`~/.claude/hooks/htm-trigger.sh`** Mode A `..htm` reminder text 블록("후속 질문" 직후, "HTML 템플릿 요구사항" 직전)에 "### 선택지 자동 승격 (Issue16_3·Issue16_6, 필수)" 하위절 신설
        - 트리거 3 조건 inline: `.htm-mode-active` 활성 + 선택지 N=2~4 (번호/알파벳/dash) + 결정 요청 문구 (선택해줘/어느 옵션/y/N/번호로 답해/골라줘/어느 쪽/Yes/No)
        - 동작: 텍스트 bullet dump 금지. 응답 본문(HTML)은 옵션 설명·비교만, 결정 요청은 `AskUserQuestion` 분리. intercept hook이 Mode B form 또는 Mode A paste-back 자동 분기
        - AskUserQuestion 호출 예시 1줄 (multiSelect + options[0] 권장 라벨)
        - 예외: 단순 비교표·정보성·코드·N>4·simple confirm
        - 상세 참조: `commands/htm.md` Issue16_3 섹션
    - **Mode C `..htm dash` reminder**에도 동일 하위절 추가 (server_section 직후, HTML 템플릿 직전)
    - 변경 영역: `~/.claude/hooks/htm-trigger.sh` 단일 파일. `commands/htm.md` Issue16_3 정식 섹션 유지 (hook reminder는 압축본, doc은 상세본)
* 검증:
    - `bash -n ~/.claude/hooks/htm-trigger.sh` → syntax OK ✅
    - Mode A 트리거 mock 입력 → reminder text에 "선택지 자동 승격" 1 hit + "Issue16_3·Issue16_6" 1 hit + `AskUserQuestion(questions` 예시 1 hit ✅
    - Mode C dash 트리거 mock 입력 → 동일 마커 1 hit ✅
    - 비-htm prompt → reminder 출력 없음 (오발동 없음) ✅
    - 실사용: 옛 세션이라도 hook reminder를 fresh emit 시 룰 적용

## Issue16_5: 브라우저 일관성 — `/htm` 전체를 default browser로 통일 (Firefox 강제 잔존 제거) (등록: 2026-05-18, 해결: 2026-05-18, commit: 7e6e4dd [~/.claude]) ✅
* 목적: 모든 `..htm`/`/htm` 흐름이 사용자 기본 브라우저(jm4=Chrome)로 통일. 종전 `open -a Firefox 'file://...'` 강제 + "Firefox open / Firefox 표시" 단독 표기 잔존 일관성 깨짐 제거. 사용자 default browser 변경 시 자동 추종
* 부모 이슈: Issue16, Issue16_2, Issue16_3, Issue16_4
* 구현 명세:
    - **`~/.claude/hooks/htm-ask-intercept.sh`**:
        - line 214 Mode A fallback: `open -a Firefox 'file://<절대경로>'` → `open 'file://<절대경로>'` (기본 브라우저)
        - line 126 reason intro: "Firefox HTML 폼" → "기본 브라우저 HTML 폼"
    - **`~/.claude/hooks/htm-trigger.sh`**:
        - line 5 주석: "Firefox 표시" → "기본 브라우저 표시"
        - line 300 Mode A reminder: "Firefox open" → "기본 브라우저 open"
        - line 325 Mode A 후속 흐름: "Firefox open" → "기본 브라우저 open"
    - **`~/.claude/commands/htm.md`** 7 sites:
        - description: "Firefox 브라우저에 표시" → "기본 브라우저에 표시"
        - 본문 intro: "Firefox로 자동 표시" → "기본 브라우저로 자동 표시"
        - 프로젝트 식별 헤더: "다중 Firefox 탭" → "다중 브라우저 탭"
        - caveman 보고 예시: "Firefox 열림" → "브라우저 열림"
        - Mode A 동작 원리 #3: "Firefox open" → "기본 브라우저 open"
        - 시퀀스 다이어그램 2건: "Firefox open" → "기본 브라우저 open"
        - 사용자 폼 단계: "Firefox 폼" → "브라우저 폼"
    - **`~/.claude/_doc_arch/htm-mode-arch.md`** 3 sites:
        - L11 개요: "Firefox HTML 문서" → "기본 브라우저 HTML 문서"
        - L43 다이어그램: `Bash: open -a Firefox 'file://<절대경로>'` → `open "http://127.0.0.1:9876/view?..."` 또는 file:// fallback (기본 브라우저, Issue16_5)
        - L56 [5] 단계: "Firefox 표시" → "기본 브라우저 표시"
* 보존 (의도적 미터치):
    - "Chrome/Safari/Firefox 호환" / "Chrome·Safari·Firefox 호환" 호환성 열거 5건 (호환 보장 의미) — htm-ask-intercept.sh:183, htm-trigger.sh:204·312, commands/htm.md:424, _doc_arch/htm-mode-arch.md:176
* 검증:
    - `grep -rn 'open -a Firefox' ~/.claude/{hooks,commands,_doc_arch} ~/_git/___pm/{services,_doc_arch}` → **0 hit** ✅
    - `grep -rn 'Firefox' ...` → 5건 모두 호환성 열거 (보존 의도) ✅
    - `bash -n ~/.claude/hooks/htm-{trigger,ask-intercept}.sh` → syntax OK ✅
    - 후속 `..htm` 세션 실사용: jm4 환경에서 Chrome으로 자동 open (사용자 default 추종)

## Issue16_4: htm 템플릿 callout/info-box 내 code 텍스트 컨트래스트 버그 (등록: 2026-05-18, 해결: 2026-05-18, commit: 96b0e0d [~/.claude]) ✅
* 목적: `commands/htm.md` HTML 템플릿이 컬러 배경 callout/info-box를 생성할 때 내부 `<code>` 가 부모 `color: white` 상속 + 흰색 배경(`var(--code-bg)`) → 흰 배경 위 흰 글자 invisible 버그 차단. 글로벌 룰에 자식 인라인 요소 `color` 명시 강제
* 부모 이슈: Issue16, Issue16_2, Issue16_3
* 발견 경위: jm4 videoMaker/lib/m2slide cwd에서 "git 변경 분류 + commit 진행안" htm doc 렌더링 시 핵심 발견 callout 내부 `_doc_arch`·`.gitignore`·`cost-manager.md`·`git add -f` 코드 토큰이 흰 배경 위 흰 글자 invisible (selection 시에만 가시) 확인
* 구현 명세:
    - **`~/.claude/commands/htm.md`** "HTML 템플릿 요구사항 (필수)" 섹션 프로젝트 식별 헤더 직후에 "컬러 영역 자식 인라인 요소 contrast (Issue16_4, 필수)" 하위절 신설
        - 룰: 컬러 배경 + `color: white` 컨테이너(`header`, `.callout`, `.info-box`, `.note-box`, `.warn-box`, `.tip-box`)는 자식 `<code>`/`<a>`/`<strong>`/`<em>`의 `color` 반드시 명시
        - 권장 CSS 패턴: 5 변종 + `header` 모두 동일 selector로 적용
            - `code` → `color: var(--fg)` + `background: rgba(255,255,255,0.92)` + padding + border-radius
            - `a` → `color: #fff` + `text-decoration: underline`
            - `strong` → `color: #fff`
            - `em` → `color: rgba(255,255,255,0.9)`
        - 자가 검증: 컬러 박스 추가 시 자식 인라인 색 명시 누락 여부 확인
    - 변경 영역: `commands/htm.md` 단일 파일 (사용자 결정: CLAUDE.md / `_doc_arch/htm-mode-arch.md` 미터치)
* 검증:
    - `commands/htm.md` 패치 후 룰 마커 grep 2 hit (`Issue16_4` + `컬러 영역 자식`) ✅
    - mock HTML 작성: `.callout` 안 `<code>` + 권장 패턴 적용 → contrast 정상 (시각 검증은 후속 `..htm` 세션 실사용)
    - 룰 발동은 Claude HTML 작성 시 적용됨 — m2slide 동일 케이스 재현 안 됨 확인은 후속 `..htm` 세션

## Issue16_3: ..htm Mode A 응답에서 선택지 패턴 감지 시 AskUserQuestion 우선 호출 (Mode A→B 자동 승격) (등록: 2026-05-18, 해결: 2026-05-18, commit: d7ea593 [~/.claude]) ✅
* 목적: `..htm` Mode A 활성 상태에서 사용자에게 객관식 선택지를 제시할 때 Claude가 텍스트 bullet 리스트로 dump하지 않고 `AskUserQuestion` 도구를 호출하도록 룰 강화. intercept hook이 자동 Mode B form 회수 또는 Mode A paste-back로 분기 → 브라우저 폼 무인 진행
* 부모 이슈: Issue16, Issue16_2
* 구현 명세:
    - **`~/.claude/commands/htm.md`** Mode A 섹션(동작 원리 직후, Form 템플릿 직전)에 "선택지 자동 승격 (Issue16_3) — Mode A → Mode B 자동 전환" 하위절 신설
        - 트리거 3 조건 표: ① `.htm-mode-active` 존재 ② N개 선택지 (2~4개, 번호/알파벳/dash 리스트) ③ 결정 요청 문구 ("선택해줘", "어느 옵션", "y/N", "번호로 답해", "골라줘", "어느 쪽", "Yes/No" 등)
        - 매핑 규칙: 응답 본문은 옵션 설명/비교 (HTML), AskUserQuestion은 question+options만 (압축). multiSelect 분기, description 1~2문장, 권장안은 `options[0]` + `(권장)` 라벨
        - 호출 예시 Python 코드 블록
        - 예외 5 케이스 (단순 비교표·정보성·코드 dump·옵션 5개 이상·simple confirm 예외)
        - 비-htm 모드 명시 (`.htm-mode-active` 없으면 적용 안 함)
    - 변경 영역: `commands/htm.md` 단일 파일 (사용자 결정: CLAUDE.md / `_doc_arch/htm-mode-arch.md` 미터치)
* 검증:
    - `commands/htm.md` Mode A 섹션 정합성 확인 (선택지 자동 승격 + Issue16_3 마커 1건 grep hit) ✅
    - intercept hook 호환: htm 모드 활성 + AskUserQuestion 호출 → `permissionDecision: deny` + Mode B/A 분기 reason 정상 emit (mock JSON 검증) ✅
    - 룰 발동은 Claude 응답 동작에 적용됨 — 본 이슈 후속 `..htm` 세션 실사용에서 검증 (이미 Mode B form 흐름 정상 작동)

## Issue16_2: htm-server `/view` endpoint + 글로벌 hook open URL을 http:// 전환 (등록: 2026-05-18, 해결: 2026-05-18, commit: 2be867e [___pm], 005a176 [~/.claude]) ✅
* 목적: dashboard·답변 폼·일반 결과 HTML을 모두 `http://127.0.0.1:9876/view?...` 동일 origin으로 serve → Chrome·Safari·Firefox 전 브라우저 CORS 제약 없이 fetch `/data`·`/answer`·`/notify`·`/events` 가능. 종전 `file://` open + http fetch 조합은 Chrome이 `Access-Control-Allow-Origin: null` 거부로 dashboard 미동작
* 부모 이슈: Issue16
* 구현 명세:
    - **`services/htm-server/server.py`**:
        - `GET /view?cwd=&token=&path=` 핸들러 추가
        - 검증: cwd+token 페어 + `os.path.realpath` 후 cwd realpath 하위 + `.html` 확장자만 허용
        - 응답: 파일 raw bytes + `text/html; charset=utf-8` + `Cache-Control: no-store`
        - 에러: 401(token)/400(path 누락)/403(cwd 외부 또는 확장자 불일치)/404(미존재)
    - **`_doc_arch/hub_htm.md`**: `/view` 명세 + 검증 시나리오 3 케이스 추가
    - **글로벌 hook open URL 전환** (`~/.claude/hooks/`):
        - `htm-trigger.sh` Mode A `..htm`: 종전 file:// 전용 → healthz+register로 token 회수 후 http://view URL emit, 서버 실패 시 file:// fallback 안내
        - `htm-trigger.sh` Mode C `..htm dash`: 동일 패턴 적용
        - `htm-ask-intercept.sh` Mode B: 동일 패턴 적용 (기존 SERVER_TOKEN 재사용)
        - `htm-ask-intercept.sh` Mode A: 서버 down 상태이므로 file:// 유지
        - `htm-dash-notify.sh`: 자체 open 호출 없음, 변경 불필요
    - **글로벌 commands 갱신**:
        - `commands/htm.md`: HTML open 절차 `/view` 패턴으로 교체, CORS 섹션 갱신
        - `commands/htm-server.md`: Endpoints 요약 표 추가 (`/view`, `/register-pid`, `/control` 포함)
    - **`~/.claude/_doc_arch/htm-mode-arch.md`**: CORS 우회 항목 + Mode C 엔드포인트 표에 `/view`·`/data` 명시
* 검증:
    - `/view` 정상 → 200 `text/html` (jm4 pid=76319) ✅
    - 잘못된 token → 401 ✅
    - path 누락 → 400 ✅
    - cwd 외부 (`/etc/passwd`) → 403 `path outside cwd` ✅
    - 확장자 불일치 (`.md`) → 403 `extension not allowed` ✅
    - 미존재 → 404 ✅
    - symlink → realpath로 탈출 시도 → 403 `path outside cwd` (검증 완료: `/etc/hosts` 링크 거부) ✅
    - hook instruction 출력 검증: Mode A trigger / Mode C trigger / Mode B intercept 모두 `open "http://127.0.0.1:9876/view?cwd=...&token=...&path=${PATH_ENC}"` emit, file:// fallback 안내 포함 ✅

## Issue16: htm-server `/control` stop endpoint + Mode C dashboard stop 버튼 (등록: 2026-05-18, 해결: 2026-05-18, commit: c82a944 [___pm], efb6103 [~/.claude]) ✅
* 목적: Mode C Live Dashboard에서 백그라운드 runner를 사용자가 직접 중단할 수 있도록 stop 제어 추가. 종전에는 별도 터미널에서 `kill <pid>` 필요
* 카테고리: SCAR (htm-server + commands/htm.md + arch doc)
* 요청 출처: ~/.claude cwd에서 "/tmp/test/ 1000개 폴더 생성" Mode C 시연 도중 사용자 요청 — option A (dashboard 전용 stop 버튼) 선택
* 구현 명세:
    - **`services/htm-server/server.py`**:
        - in-memory `pids` dict (cwd_hash → set[int]), `pids_lock`
        - `POST /register-pid?cwd=&token=` body=`{"pid":N}` → token 검증 + `os.kill(pid,0)` alive 확인 + `pids[cwd_hash]` 추가. 에러: 401/400/404/403
        - `POST /control?cwd=&token=` body=`{"action":"stop","pid":N}` → 등록 pid 검증 → `SIGTERM` → 2초 100ms 폴링 → 미종료 시 `SIGKILL` → 200 `{status,pid,signal}` 또는 `already_dead`. 에러: 401/400/403/500
        - `/healthz` 응답에 `registered_pids` 필드 추가
    - **`_doc_arch/hub_htm.md`**: API 명세 `/register-pid` + `/control` 섹션 추가, 검증 시나리오 3 케이스 추가
    - **`~/.claude/commands/htm.md`**: Mode C 섹션에 Issue16 하위절 추가
        - runner 등록 + SIGTERM trap → data 파일 `status: stopped`/`stopped_at` 마킹 bash 패턴
        - data 파일 표준 필드 (`pid`, `status`, `started_at`, `stopped_at`)
        - dashboard HTML stop 버튼 + confirm 다이얼로그 + fetch + 상태 배지 JS 템플릿
        - 보안 모델 요약 (cwd+token+pid 3중 검증 + 동일 user 소유 검사)
    - data 파일 마킹 책임: runner SIGTERM trap. server는 kill만 수행 (책임 분리)
* 검증 (jm4 pid=82780):
    - `/register-pid` 정상 등록 → 200 ✅
    - `/register-pid` 음수/미실행 pid → 400/404 ✅
    - `/control` 미등록 pid → 403 ✅
    - `/control` 알 수 없는 action → 400 ✅
    - `/control` `SIGTERM` 정지 (sleep 600 runner) → 200 `signal=TERM`, 사후 `kill -0` DEAD 확인 ✅
    - 사전 `kill -9` 후 `/control` → 200 `already_dead` ✅
    - `/control` 잘못된 token → 401 ✅
    - `/healthz registered_pids` 카운트 정상 (stop 후 0) ✅

## Issue15: htm-server를 ___pm 소유 단일 공유 서비스로 재구조화 (등록: 2026-05-18, 해결: 2026-05-18, commit: a3db31b [___pm], ecc7fe8 [~/.claude]) ✅
* 목적: 종전 htm-server는 프로젝트별 개별 인스턴스(cwd hash → port 9876+%100, `/tmp/claude-htm-server-{hash}/`) + `~/.claude/.htm-server-active` 글로벌 flag 구조. flag와 실제 lifecycle 불일치(fWarrange Issue25 재발) 제거를 위해 ___pm 소유 단일 daemon으로 재구조화
* 흡수: `~/.claude/Issue.md` Issue25 (C안 = 본 이슈로 흡수, 종결)
* 구현 명세:
    - **서버**: `~/_git/___pm/services/htm-server/server.py` (Python stdlib `ThreadingHTTPServer`, 단일 port 9876 고정, env `HTM_SERVER_PORT` override). md5(cwd)[:8] 해시 + `cwd+token` 페어 검증으로 다중 프로젝트 격리. `tokens.json` persist로 재시작 회복. `127.0.0.1` 바인딩 + `hmac.compare_digest` + `/data` path traversal 차단 + body size 상한
    - **README**: `services/htm-server/README.md` (운영 가이드)
    - **설계 SSOT**: `_doc_arch/hub_htm.md` (lifecycle·API·격리 모델·migration·검증 시나리오)
    - **글로벌 hooks 패치 (단일 서버 모델)**: `~/.claude/hooks/htm-ask-intercept.sh`, `htm-trigger.sh`, `htm-dash-notify.sh` — flag 제거, healthz + `/register` + `cwd+token` 페어 호출 패턴 통일. `.htm-mode-active` 플래그는 유지 (모드 활성화 신호용, 서버 lifecycle과 분리)
    - **글로벌 wrapper 재작성**: `~/.claude/commands/htm-server.md` + `~/.claude/skills/htm-server/SKILL.md` — start/stop/status/restart를 ___pm 서비스에 위임. 종전 `~/.claude/skills/htm-server/server.py` 제거
    - **endpoints**: `GET /healthz`, `POST /register?cwd=...`, `POST /answer?cwd=...&token=...`, `GET /events?cwd=...&token=...`, `POST /notify?cwd=...&token=...`, `GET /data?cwd=...&token=...&path=...`
    - **inbox**: `/tmp/claude-htm-inbox/{cwd_hash}/{ts}.json`
    - **상태**: `/tmp/claude-htm-server/{pid, tokens.json, server.log}`
    - **stale 자원 정리(1회)**: `rm -f ~/.claude/.htm-server-active` + `rm -rf /tmp/claude-htm-server-* /tmp/claude-htm-inbox-*` (jm4 적용 완료)
    - **하위 호환**: 서버 미실행·healthz 실패 시 hook이 Mode A(paste-back) fallback
* 검증 (jm4 단일 daemon, pid=31290):
    - `GET /healthz` → 200, projects=3 (fWarrange, fSnippet, ___pm 동시 격리) ✅
    - `POST /register` (___pm cwd) → 신규 token + inbox `/tmp/claude-htm-inbox/ccf9da30` 발급 ✅
    - `POST /answer` → inbox JSON 저장 ✅
    - `POST /notify` → SSE broadcast 정상 (구독자 0 시 status: broadcast) ✅
    - `POST /answer?token=wrongtoken` → 401 `invalid cwd or token` ✅
    - 종전 자원 정리 후 stale 잔존 0건 ✅

## Issue14: proj-refactor·pm-* sync (ma·m2·fg1) + jm4 로컬 전 프로젝트 _doc_design → _doc_arch 적용 (등록: 2026-05-16, 해결: 2026-05-16) ✅
* 목적: proj-refactor 스킬(v1.2, 함정 33종)과 pm-* 글로벌 커맨드 3개 원격 머신 동기화 + jm4 로컬 모든 프로젝트 _doc_design → _doc_arch 리팩토링 적용
* 연동: `~/.claude/Issue.md` Issue15 (글로벌 SCAR ~/.claude 본체)

* Phase A — 스킬 sync (ma·m2·fg1):
    - `~/.claude/skills/proj-refactor/` (v1.2, 함정 33종) rsync
    - `~/.claude/commands/pm-{new,del,update,query}.md` (4종) rsync
    - 검증: ma·m2·fg1 모두 설치 확인

* Phase B — jm4 로컬 적용 (총 23개 git repo, verify 모두 0건):
    - 0번 ~: 사용자 선행 처리
    - 1번 ___pm: 커밋 50f5bf6→3e85d0f→d4029aa
    - 2번 ~/_doc: 커밋 d9b34ce (Obsidian, P30 EXPECT_DIR_CREATION=0)
    - 3번 ~/.claude: ~/.claude/Issue.md Issue15 ✅
    - 4번~ __all/* 14개: fBanner, fBoard, fCapture, fGoogleSheet, finfraHome, fQRGen, fSnippet, fWarrange, social, videoMaker, ollamaClaude, fSnippetOld/* 3
    - 25/26 _public 2개: fSnippet/_public, fWarrange/_public (cli/_doc_design)
    - 추가 영역 7개 (A·B·C·E):
        * videoMaker/lib/m2slide, lib/tts (별도 git repo)
        * ~/work/AgenticCoding_lec, ~/work/work-exampleProj
        * iCloud/share/fSnippetData
        * Google Drive/_git/fQRGen
    - 백업 태그: 전 프로젝트 `pre-refactor-2026-05-16-doc-arch`

* Phase C — ma·m2·fg1 프로젝트별 적용 (미진행, 별도 세션):
    - ma 13개, m2 3개, fg1 4개 (sync 시점 detect 결과)

* 보존 영역 (변경 금지):
    - 아카이브: ~/_git/z_backup, z_done
    - 클라우드 외부 sync 영역 변경분: 별도 충돌 모니터링 필요
    - 의도 보존: doc_arch.md (P1·P26 설명), pm/SKILL.md (옛 오타 이력)

* 학습 (`~/.claude/learning_log.md` 등재):
    - P25 다이어그램(*.excalidraw/*.mermaid) include_globs 누락
    - P26 자가 치환 2회 발현 (___pm doc_arch.md, ~/.claude proj-refactor 스킬·recipe·Issue15)
    - P27 사용자 미커밋 격리 (Save Point)
    - P28 CLAUDE.md·memory propagate 누락
    - P29 프로젝트 로컬 SCAR 검증
    - P30 _doc_design 폴더 미보유 (Obsidian)
    - P31 nested git repo (1.Area)
    - P32 휴지통(.trash/)
    - P33 보고서 자기참조

## Issue12: graphify-brief Skill 구현 (등록: 2026-04-24, 해결: 2026-05-16, commit: 2cd3cf9 [~/.claude]) ✅
* 목적: "주제" 입력 시 `graphify query` + `GRAPH_REPORT.brief.md` + `wiki/{community}.md` 발췌를 조합한 50줄 이내 요약을 반환하는 스킬 작성
* 산출물: `~/.claude/skills/graphify-brief/SKILL.md` (글로벌)
* 구현 명세:
    - 입력: `<주제>` (자유 문자열, `$ARGUMENTS`)
    - 동작: `graphify query --top 5` → `GRAPH_REPORT.brief.md` 우선 grep(없으면 `GRAPH_REPORT.md`) → 매칭 `wiki/*.md` 최대 2개 발췌
    - 출력 제약: 50줄 이내. 초과 시 wiki→RELATED→QUERY 순으로 축소
    - 예외: graphify CLI 미설치 / `graphify-out/` 없음 / 빈 주제 → 명시적 에러 메시지 후 종료 (재시도 금지)
    - 검증: graphify CLI 0.x 환경(`~/.local/bin/graphify`)에서 query·grep·wiki 매칭 모든 단계 정상 동작 확인

## Issue11: graphify 토큰 절감 SCAR 글로벌 승격 (등록: 2026-04-24, 해결: 2026-05-16, commit: 2cd3cf9 [~/.claude]) ✅
* 목적: 프로젝트(`___pm`)에 구현된 graphify 토큰 절감 SCAR를 `~/.claude/` 글로벌로 이식하여 모든 프로젝트에서 공통 적용
* 산출물:
    - `~/.claude/rules/graphify-rules.md` (신규) — 결정 트리 + Read 허용표
    - `~/.claude/commands/graphify-prune.md` (신규) — GRAPH_REPORT 100줄 압축
    - `~/.claude/commands/gq.md` (갱신, `$ARGUMENTS` 표준화) — `graphify query` 래퍼
    - `~/.claude/CLAUDE.md` graphify 섹션에 룰·보조 커맨드·요약 스킬 참조 3줄 추가
* 구현 명세:
    - 프로젝트(`___pm`) 버전을 `cp`로 글로벌에 복사 (graphify-rules.md, graphify-prune.md, gq.md)
    - 기존 글로벌 `gq.md`는 `$1` → `$ARGUMENTS` 표준화 버전으로 덮어씀
    - CLAUDE.md graphify 섹션에 3줄 보강 (토큰 절감 규칙·보조 커맨드·요약 스킬)

## Issue13: 고객 서버용 글로벌 nPTiR·SCAR 하네스 구현 (등록: 2026-04-28, 해결: 2026-04-28, commit: 93f896a) ✅
* 목적: 새 서버 `~/.claude`에 복사할 수 있는 nPTiR·SCAR 글로벌 하네스 구축 (___pm 미포함, 개인정보 제거, macOS 앱 도메인 제외)
* 산출물: `data/claude_forNewServer/` 디렉토리 + `data/claude_forNewServer.md` (rsync 설치 가이드·사용법)
* 구현 명세:
    - CLAUDE.md, Harness.md 서버 전용 재작성 (개인정보·fApp·-m 도메인 제거)
    - rules/ 9개 (nptir, issue-g, md, naming, language, refs, change-detect, info-files, opus-4-7)
    - commands/ 10개 (issue-*-g, needs, design-doc, new-project, md-add, gstack-*)
    - skills/ 7개 (issue-g, dev-g, dev-w, issue-w, doc-work-archive, git, gstack)
    - new-project.md: ___pm 스킬 참조 제거, 독립형 nPTiR 초기화 커맨드로 재작성
    - info-files.md: 개인 파일(past_prompts, instincts) 참조 제거

## Issue10: 글로벌 SCAR 변경 호환성 감사 및 정렬 (Opus 4.7 실행제약·gstack-nptir 연동·Harness SSOT·VERSION) (등록: 2026-04-19, 해결: 2026-04-19, commit: 6593ed3) ✅
* 목적: 글로벌 `~/.claude/` SCAR 대대적 수정(Opus 4.7 실행제약 의무화·gstack-nptir 연동·nPTiR 경로 복수화·version-manager 신규·Harness SSOT)과 프로젝트(`~/_git/___pm`) SCAR 간 호환성 정렬
* plan: `_doc_work/plan/global-scar-sync_plan.md`
* task: `_doc_work/tasks/global-scar-sync_task.md`
* report: `_doc_work/report/global-scar-sync_issue10_report.md`
* 구현 명세:
    - **선행 완료**: Harness SSOT 분리(루트=인덱스, _doc_arch=상세 설계), 루트 Harness.md 교정(fcapture 표기·___pm 섹션 도메인·sync-ma 보강·local 섹션 추상화), md-rule-apply 코드블록 가드 추가
    - **Phase 1**: 프로젝트 SCAR 30개(agents 2 + commands 23 + skills 5)에 "Opus 4.7 실행 제약" 표준 섹션 일괄 추가. 누락 0 확인
    - **Phase 2**: issue 관련 SCAR 4개(rules/issue-rules + commands/issue-{reg,fix,closer})에 gstack-nptir-rules 참조 및 글로벌 `-g` 커맨드와의 관계 명시
    - **Phase 3**: nPTiR 경로 단수/복수 검증. 프로젝트는 이미 복수 `tasks/` 준수 상태 → 스킵
    - **Phase 4**: pm skill mac 타입에 `version-manager-m` Skills 포함 + VERSION SSOT 초기화 필수 요구사항 명시
    - **nPTiR 산출물**: plan/task/report 전부 생성, frontmatter 양방향 연결(issue, plan, task) 완료
    - **집계**: 단일 커밋(6593ed3) · 95 files changed · +1807 / -952

## Issue9: fApp 8개 프로젝트 메모리 일관성 확보 (Bundle ID·구조·파일명·메타 통일) (등록: 2026-04-17, 해결: 2026-04-17, commit: 025fdee) ✅
* 목적: fApp 프로젝트(#11~16, #25, #26)의 `~/.claude/projects/*/memory/` 메모리 파일들이 생성 시점·방식이 달라 파일명/구조/Bundle ID 값이 제각각인 문제를 일괄 정리하여 재사용성과 신뢰성 확보
* 구현 명세:
    - **Bundle ID 통일**: Xcode `project.pbxproj` 실측 기준으로 모든 메모리의 Bundle ID 정정. 8개 앱 타겟 전부 `kr.finfra.*` prefix로 확정 (`kr.nowage.fSnippet` → `kr.finfra.fSnippet`, `com.finfra.fWarrange` → `kr.finfra.fWarrange` 등). `com.finfra.*`·`kr.nowage.*`는 더 이상 사용 안 함
    - **파일명/타입 표준화**: `project_bundle-ids.md` (type: project), `project_parallel-projects.md`, `project_similar-project.md` (type: project), `project_nptir-path.md`로 통일. 기존 `feedback_bundle-id.md`·`project_parallel-context.md`·`reference_similar-project.md`·`project_nptir-structure.md`·`refactoring_issue-commands.md` 삭제
    - **MEMORY.md 표준 구조**: `# {프로젝트명} (#번호) Memory Index` 헤더 + `## Feedback` / `## Project` 섹션. index-only 원칙 준수 (본문은 별도 파일로 분리)
    - **앱 분류 메타 추가**: 각 MEMORY.md 상단에 `> **앱 분류**: 유료앱/무료앱 · **서브 프로젝트**: 있음/없음` blockquote 삽입. fBanner/fBoard/fGoogleSheet=유료·서브없음, fQRGen=무료·서브없음
    - **fBoard 잘못된 내용 정정**: `project_structure.md`의 "Pro/Basic 2-앱 구성"·"Basic→Pro 기능 이식" 표현 삭제, 단일 유료앱으로 재작성. `project_bundle-ids.md`에서 `Finfra.com.fBoard-basic` 항목 제거
    - **fGoogleSheet 메모리 디렉토리 신규 생성**: 기존에 없었던 `memory/` 디렉토리 및 MEMORY.md/project_bundle-ids.md 생성
    - **data/fapp-projects.md 테이블 확장**: "판매"(유료/무료) 및 "서브 프로젝트" 컬럼 추가, 서브 프로젝트 상세 섹션(25/26/35) 신설
* 커밋 대상: `data/fapp-projects.md` (메모리 파일은 `~/.claude/projects/` 하위로 gitignore됨)

## Issue4: pm 스킬 및 커맨드 구현 (pm-new, pm-del, pm-update, pm-query) (등록: 2026-04-11, 해결: 2026-04-12, commit: 2be3ef6, b5c9dc5) ✅
* 목적: 프로젝트 관리(생성·삭제·업데이트·조회)를 위한 pm 스킬과 4개 커맨드 구현
* 구현 명세:
    - pm 스킬 (SKILL.md): 공통 로직 (Projects.md 참조, cdf 연동, 번호 대역, 타입 정의)
    - pm-new: 타입별 초기화 + 형식 B(단일 인자 자동 추론: 타입·번호 자동 할당)
    - pm-del: backup(기본, 폴더 mv)/keep(레지스트리만 정리) 2가지 모드
    - pm-update: SCAR·템플릿·폴더 최신화 (기존 파일 컨펌 강제)
    - pm-query: 프로젝트 조회·검색
    - 실행 이력: `_doc_work/pm_history/{YYYY-MM-DD}-{action}-{번호}-{프로젝트명}.md` 폴더화
    - 타입 파라미터: 한글(일반/웹/맥) → 영문(general/web/mac)
    - 기본 생성 경로: `~/_git/__all/{프로젝트명}`
* 설계 문서: `_doc_arch/Harness/plans/pm-skill-plan.md` 외 4건

## Issue1: cdf (N) 윈도우 번호 미존재 시 자동 생성 (등록: 2026-03-28, 해결: 2026-03-31, commit: d66a3c9) ✅
* 목적: `(4)` 지정 시 해당 인덱스 윈도우가 없으면 자동 생성
* 구현 명세:
    - 증상: 존재하지 않는 윈도우 번호 지정 시 fallback 이름으로 다른 윈도우에 배정
    - 수정 대상: `.claude/skills/cdf.md` Step 1 `(N)` 파싱 및 Step 3 window 생성 로직

## Issue2: cdf 각괄호 `[NAME]` 구문으로 윈도우 이름 직접 지정 (등록: 2026-03-28, 해결: 2026-03-31, commit: d66a3c9) ✅
* 목적: `6 7[mywin] --- ls` 형태로 윈도우 이름을 인라인 지정
* 구현 명세:
    - 기존: 비숫자 단독 토큰이 WIN_NAME으로 해석 (모호함)
    - 개선: `[NAME]` 각괄호 구문 추가하여 명시적 윈도우 이름 지정
    - 수정 대상: `.claude/skills/cdf.md` Step 1 토큰 분류 로직

## Issue3: cdf REUSE 시 pane 경로 일치 검증 후 CMD만 전달 (등록: 2026-03-28, 해결: 2026-03-31, commit: d66a3c9) ✅
* 목적: pane 수 일치해도 경로가 다르면 재생성, 경로까지 일치하면 CMD만 전달
* 구현 명세:
    - 증상: pane 수만 비교하여 다른 프로젝트 조합의 window를 재사용
    - 개선: 각 pane의 `pane_current_path`를 PROJ_PATHS와 비교
    - 수정 대상: `.claude/skills/cdf.md` Step 3 window 확인/생성 로직

# ⏸️ 보류
# 🚫 취소
# 📜 참고

## Issue115: Hub 자동 리프레쉬 (tmux 백그라운드 프로세스 제거)
* 목적: dashboard 데이터 파일 변경 시 hub 페이지 자동 리프레쉬 (수동 새로고침 제거). tmux 환경에서는 별도 백그라운드 프로세스 대신 window 내부 폴링으로 구현.
* 상세:
    - 현재: 새로고침(F5) 필요 → dashboard 카드 표시
    - 필요: 자동 갱신 (5초 주기)
    - 제약: tmux 백그라운드 프로세스 제거, window 내부 폴링 방식 권장
    - 구현 대상: prj3 (hub 서버, ~/_git/__all/finfraHome)
* 구현 명세:
    - dashboard 데이터 파일 감시 (mtime 폴링)
    - 변경 감지 시 페이지 reload (js: location.reload 또는 fetch + DOM 업데이트)
    - 간격: 5초 (hub 페이지 로드 시 자동 시작)
    - 중지: 탭 닫기 또는 명시적 중지 버튼

