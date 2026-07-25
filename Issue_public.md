---
name: Issue_public
description: "fpm 공개용 이슈 근거 요약 — Issue.md 에서 제목·목적·구현 명세만 추출한 파생본"
generator: scripts/fpm-issue-digest.sh
source_sha: d1b73454056120ebda0c1a09c8a1c9c119baac5b64de0e367a61cc73a0ed1b97
---

# 안내

본 문서는 자동 생성 파생본이다. 원본 이슈 트래커(`Issue.md`)는 개인정보가 포함되어 공개하지
않으며, 여기에는 **코드 변경의 근거를 이해하는 데 필요한 필드만** 추출되어 있다.

* 포함: 이슈 제목 · `목적` · `구현 명세` · `depends`
* 제외: 상세 · Walkthrough · 진행 결과 · 커밋 해시 · plan/task 경로

소스 코드 주석의 `(Issue{N})` 참조는 아래 항목에서 찾을 수 있다. 직접 편집하지 말 것 —
`scripts/fpm-issue-digest.sh` 가 덮어쓴다.

# 이슈 근거

## Issue324: Issue_public digest — 미참조 이슈·사설 경로 유출 차단 ✅
* 목적: 공개 미러 digest 에 미러 소스가 참조하지 않는 이슈(내부 문서 감사·프로젝트 등록 결정 등)와 사설 경로·프로젝트명이 그대로 실려 나갔다. digest 의 존재 이유는 미러 코드 주석의 `(Issue{N})` 근거 제공 하나이므로, 참조되지 않는 항목은 공개 이득 없이 내부 사정만 노출한다.
* 구현 명세:
    - `scripts/fpm-issue-digest.sh` 코드 참조 필터 신설: `git grep` 으로 미러 반출 대상 소스의 `Issue{N}` 집합을 구해, 그 집합에 없는 이슈 블록을 digest 에서 제거. 참조 코퍼스에서 비반출·예제 경로(설계문서·작업문서·프로젝트 인덱스·템플릿 예제) 제외
    - 포맷 드리프트 가드는 필터 **이전** 추출량(`PRE_FILTER_GOT`)으로 판정 — 필터의 정상 감소를 오탐하지 않도록
    - scrub 규칙 추가: 홈 하위 개인 폴더 경로, 외장 볼륨(`<private-path>`) 경로 → `<private-path>`
    - 정책 `sanitize[]` 리터럴을 검증뿐 아니라 **치환**에도 적용 (종전엔 fail-loud 만 → 수동 대응). 정책 파일은 self-exclude 라 리터럴 자체는 미러로 나가지 않음
    - 검증: 재생성 결과 24→13 이슈, 잔존 PII grep 0건, `--check` 신선도 통과

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
* 목적: `projects/9a` 가 경로 한 줄 파일이 아니라 14MB 논문 프로젝트 실물 디렉토리(+`9a.bak` 중복)로 존재해 `cdf 9a` 등 index 가 깨짐. 원인은 실물 프로젝트(`<private-project>`)가 타깃 `<private-project>/_doc_base/` 대신 ___pm index 폴더에 잘못 배치됨(수동 mv/cp 또는 haiku 에이전트 실수 추정). `gen_projects` 는 디렉토리를 걸러내지 못해 `os.remove`(IsADirectoryError)·`open(...,'w')` 둘 다 실패, path 파일을 재생성하지 못하고 침묵 실패함.
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

