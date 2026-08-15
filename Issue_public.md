---
name: Issue_public
description: "fpm 공개용 이슈 근거 요약 — Issue.md 에서 제목·목적·구현 명세만 추출한 파생본"
generator: scripts/fpm-issue-digest.sh
source_sha: 7f90eaf4b9765ded20f7fcf2abf89216a949928249be748d3f17b80ac286c8d1
---

# 안내

본 문서는 자동 생성 파생본이다. 원본 이슈 트래커(`Issue.md`)는 개인정보가 포함되어 공개하지
않으며, 여기에는 **코드 변경의 근거를 이해하는 데 필요한 필드만** 추출되어 있다.

* 포함: 이슈 제목 · `목적` · `구현 명세` · `depends`
* 제외: 상세 · Walkthrough · 진행 결과 · 커밋 해시 · plan/task 경로

소스 코드 주석의 `(Issue{N})` 참조는 아래 항목에서 찾을 수 있다. 직접 편집하지 말 것 —
`scripts/fpm-issue-digest.sh` 가 덮어쓴다.

# 이슈 근거

## Issue379: hub 가 Host 헤더를 판정하지 않아 임의 도메인으로 200 응답 — DNS rebinding 표면 ✅
* 목적: hub 는 `bind_host` 3소켓(`127.0.0.1`·`<lan-ip>`·`<tailnet-ip>`)에 도달하기만 하면 **`Host` 헤더가 무엇이든 200** 을 준다. `curl -H 'Host: evil.example' http://127.0.0.1:9876/hub` → 200 실측(2026-08-15). Issue141 의 source-IP 게이트(`_ip_allowed`)는 **어디서 왔는가**만 보고 **어느 이름으로 불렸는가**를 안 보므로, 브라우저를 경유하는 DNS rebinding 은 src 가 loopback 이라 그대로 통과한다. 수신 이름을 known-host 집합으로 제한해 이 표면을 닫는다
* 구현 명세:
    - 진입점 3곳 단일 삽입 — [do_GET:3648](services/hub/server.py#L3648)·[do_POST:3830](services/hub/server.py#L3830)·[do_OPTIONS:3645](services/hub/server.py#L3645) 의 `_ip_allowed` 직후에 `_host_allowed()` 호출. 핸들러별 산재 금지(판정 단일 지점)
    - `_host_allowed(host_header)` 산출 집합: `bind_host` 전 항목 + `advertise_host` + `localhost` + `hostname -s` 결과 + `{hostname}.local` + 신규 키 `extra_hosts[]`. 정규화 = `:port` 분리 · 소문자화 · trailing dot 제거 · IPv6 `[...]` 해제
    - **IP 리터럴 Host 는 항상 통과** — 잠김 사고 방지의 핵심. rebinding 은 반드시 도메인 이름을 Host 로 보내므로 IP 리터럴 허용은 방어를 약화시키지 않고, 게이트 오설정 시 사용자는 `http://127.0.0.1:9876` 으로 항상 복구할 수 있다
    - 거부 응답 `421 Misdirected Request` + `[hostgate] DENY — host='...' KNOWN=[...]` 로깅 (`_ip_allowed` 의 `[allowlist] DENY` 로그 형식과 대칭)
    - Host 헤더 부재(HTTP/1.0) → source IP 가 loopback 일 때만 통과, 그 외 거부
    - fail-open 조건 명시: known 집합 산출 실패·공집합이면 게이트 **비활성**(종전 동작). 설정 파싱 사고가 hub 를 통째로 죽이지 않게 한다
    - 신규 yml 키 2종 — `host_gate: true`(기본 on) · `extra_hosts: []`. [data/hub_setting.yml](data/hub_setting.yml)·[hub_setting_org.yml](plugins/fpm-core/data/hub_setting_org.yml)·`SETTING_FIELDS`·locales [ko.json](plugins/fpm-core/data/locales/ko.json)/[en.json](plugins/fpm-core/data/locales/en.json) 동시 반영
    - 2원 사본 동시 반영 — [services/hub/server.py](services/hub/server.py)(SSOT) + [plugins/fpm-core/services/hub/server.py](plugins/fpm-core/services/hub/server.py)(번들 미러)
    - 문서 갱신: [hub-remote-access.md](_doc_arch/hub-remote-access.md) 에 "수신 이름 게이트" 절 추가 — 2단 게이트(source-IP)가 3단(+Host)이 됨을 SSOT 로 기록. 승격 포워딩 기각 근거도 함께 박제
    - 검증: 등록 7종 이름 전부 200 유지 · `Host: evil.example` → 421 · `Host` 부재 loopback → 200 · 폰(ts.net)·host 실기 접속 200 · `host_gate: false` 로 되돌리면 종전 동작

## Issue378: 이미 열려 있는 hub 탭이 모드 변경을 모른다 — 302 는 재진입에만 걸려 새로고침을 요구한다 ✅
* depends: Issue377
* 목적: Issue377 이 `/hub ↔ /hub-shell` funnel 을 양방향으로 만들었지만, 302 는 **새 요청**에만 작용한다. 이미 200 으로 serve 되어 떠 있는 탭은 그 뒤 `render_tab_mode` 가 바뀌어도 자기가 무효 표면이 된 걸 모르고 그대로 남는다 → 사용자가 수동으로 새로고침해야 유효 표면에 합류한다. **떠 있는 탭도 현재 모드에 맞는 URI 로 스스로 이동**하게 하여, 새로고침 요구 없이 "유효 표면 1개" 불변식이 시간에 대해서도 유지되게 한다
* 구현 명세:
    - 서버 ①: `/boards` 응답(`_handle_dashboards`)에 `render_tab_mode` 키 추가 — additive 라 기존 소비자 무영향
    - 서버 ②: `_handle_hub_events` keepalive 루프에서 모드가 `hub-internal` 이 아니게 되면 `event: mode-change` push 후 스트림 종료 → 쉘은 15초 이내 반응(서버 주도, 폴링보다 빠름)
    - 클라 ①: HUB_SHELL_HTML — SSE `mode-change` 수신 시 `location.replace("/hub")`. `pollDocs` 에도 동일 판정을 폴백으로 이중화(SSE 끊긴 구간 커버)
    - 클라 ②: HUB_HTML `reload()` — top-level 이고 모드가 `hub-internal` 이면 `location.replace("/hub-shell")`. embed(`window.top !== window.self`)면 이동 금지
    - `location.replace` 사용(`href` 아님) — 무효 표면을 히스토리에 남기지 않아야 뒤로가기로 되돌아가지 않는다
    - 2원 사본(`services/` SSOT + `plugins/fpm-core/` 번들 미러) 동시 반영
    - 검증: 서버 가동 중 yml 모드를 바꾸고 각 탭이 자동 이동하는지 실측. 이동 후 재이동(핑퐁) 0 · iframe home 탭 정상 확인

## Issue377: /hub ↔ /hub-shell funnel 이 한쪽만 있어 render_tab_mode 와 어긋난 표면이 그대로 열린다 ✅
* 목적: 같은 서버에 `/hub`(standalone)와 `/hub-shell`(내부 탭 쉘) 두 표면이 공존하는데, funnel 이 **hub-internal → /hub → /hub-shell 한 방향만** 구현돼 있다. `render_tab_mode: browser-tab` 인데 `/hub-shell` 을 열면 쓰지 않기로 한 쉘이 그대로 뜨고, hook 은 같은 모드에서 OS 새 탭도 열어 **표면 2개가 동시에 산다**. 설정이 표면을 결정한다는 계약을 양방향으로 복원해 "지금 유효한 표면 1개"만 남긴다
* 구현 명세:
    - `_handle_hub_shell` 최상단에 역방향 게이트: `render_tab_mode != "hub-internal"` → 302 `/hub`
    - 루프 불가 검증: 두 조건이 배타(`== hub-internal` vs `!= hub-internal`)라 동시 성립 없음. 설정 변경 순간의 교차도 브라우저 리다이렉트 상한이 흡수
    - 쿼리스트링은 전달하지 않는다 — `_shell=1` 이 넘어가면 `/hub` 가 embed 로 오인해 정방향 가드를 건너뛴다
    - 검증: browser-tab 에서 `curl -sI /hub-shell` → 302 Location `/hub`, `/hub` → 200 / hub-internal 로 바꾸면 정확히 반대

## Issue375: projects-map 맵 배경 전역 클릭 제거 — 🗂️ 버튼이 있는데 아무 데나 눌러도 Projects.md 가 열림 ✅
* 목적: `/projects-map` 은 헤더에 **🗂️ Projects.md 열기(VSCode)** 버튼을 이미 갖고 있는데, 맵 영역 아무 곳을 눌러도 같은 `vscode://file` 링크가 열린다. 명시 버튼과 광역 클릭이 공존해 후자가 오작동으로 읽힌다
* 구현 명세:
    - `.claude/skills/projects-map/build_projects_map.py` — CLICK_SCRIPT_TMPL 의 `#map-canvas` click 리스너 제거(사유 주석 유지). Projects.md 진입점은 헤더 `btn-projects-md` 단일화
    - 같은 파일 CSS `#map-canvas { cursor: pointer; }` 제거 — 클릭 대상이 아닌 곳에 pointer 커서는 거짓 신호
    - meta 안내 문구 `맵 빈 곳 클릭 → Projects.md` → `🗂️ 버튼 → Projects.md`
    - `📝`/note 박스 → `_note.md` 는 존치 (박스 경계가 명확하고 사용자 지적 대상 아님)
    - 재생성 후 `curl /projects-map` 로 canvas 리스너 0건 확인

## Issue374: live 세션에도 heartbeat 신선도 게이트 — 세션보다 오래 사는 호스트 프로세스가 만든 영구 좀비 카드 ✅
* 목적: `content_type="live"` 는 `_pid_alive(live_pid)` 가 **단독 권위**라, 세션이 끝나도 그 세션을 띄웠던 프로세스가 남아 있으면 카드가 영구히 활성 세션에 남는다. dashboard 는 `pid 생존 + age ≤ DASH_HEARTBEAT_STALE` 를 **함께** 요구해 같은 시나리오를 막는데, live 만 그 게이트가 없다 — 이 비대칭이 원인이다
* 구현 명세:
    - `services/hub/server.py` — 상수 `LIVE_HEARTBEAT_STALE = 172800.0`(48h) 신설. live 는 hook 발동 시에만 heartbeat 가 오르므로(장시간 유휴가 정상) `DASH_HEARTBEAT_STALE`(1800s)보다 훨씬 넓게
    - `_collect_live_sessions()` live 분기 — dismiss tombstone 검사 직후, `live_pid` 판정 **앞**에 `age > LIVE_HEARTBEAT_STALE → terminal_keys` 게이트 삽입 (pid 유무 양쪽 경로에 동일 적용)
    - prune 되어도 다음 hook 발동에 재등록되므로 손실은 유휴 구간의 카드 표시뿐 (Issue341 self-heal 과 같은 성질)
    - 번들 미러 `plugins/fpm-core/services/hub/server.py` 동기 후 hub 재기동·실측 검증

## Issue373: 활성 세션 행 제목 툴팁에서 세션 ID 제거 — sid 병기는 📋 버튼의 역할 ✅
* 목적: Issue369 가 sid 를 `data-tip-sid` 로 **행 `<li>` 에도** 붙여, 세션 제목 hover 만 해도 36자 uuid 가 따라 뜬다. 제목 hover 는 *"무슨 세션인가"*(topic)를 보는 자리이고, sid 확인은 복사 직전 📋 위에서 하면 된다 — 제목 쪽 sid 는 읽히지 않는 소음
* 구현 명세:
    - `services/hub/server.py` `rowHtml()` — `const sidAttr` 선언과 `<li>` 의 `${sidAttr}` 삽입 제거. `liveTipShow()` 의 `data-tip-sid` 처리는 손대지 않음(📋 가 계속 사용)
    - 번들 미러 `plugins/fpm-core/services/hub/server.py` 동기
    - 검증: `ast.parse` OK → hub 재시작 → `/hub` 서빙 HTML 에서 `li.live-item` 의 `data-tip-sid` 0건 · `button.copy-sid` 의 `data-tip-sid` 유지 실측

## Issue372: 이슈맵 신호를 2단 → 3단으로 — "맵은 있는데 그래프가 없다"를 노드 테두리로 ✅
* 목적: Issue371 은 `issue_map`(맵 파일 존재 **AND** 그래프 보유) 하나로만 갈라, **맵 문서는 있는데 선수 관계가 없는** 프로젝트를 "아무것도 없음"과 같이 취급했다. 그 문서에도 이슈 목록·완료 이력 등 정보가 있으므로 열 수 있어야 한다. 또 지금은 **hover 해야만** 이슈맵 유무를 알 수 있어, 맵 전체를 훑으며 "어디에 관계도가 있나"를 볼 수 없다
* 구현 명세:
    - 서버: `_projects_list_with_htm()` 에 `issue_map_file`(= `_issue_map_scan()[0]` 존재) 추가. 기존 `issue_map`(그래프 보유)은 그대로 — 판정 단일 지점 유지
    - 맵: 점선은 SVG `rect` 의 한 변만 파선 처리할 수 없으므로 노드 `<g>` 에 `<line>` 을 얹는다(세션 배지가 `<text>` 를 얹는 것과 같은 방식·같은 재적용 주기)

## Issue371: Projects_map 노드 hover 팝업 — 그 프로젝트의 이슈맵으로 가는 버튼 ✅
* 목적: `/projects-map` 은 "무엇이 무엇을 필요로 하는가"(프로젝트 축)를 보여주지만, 거기서 **그 프로젝트 안의 이슈 선수 관계**로 내려가려면 hub 로 되돌아가 카드를 찾아야 한다. 노드에 마우스를 올렸을 때 이슈맵 진입 버튼을 바로 띄워 두 축을 잇는다
* 구현 명세:
    - `.claude/skills/projects-map/build_projects_map.py` 에 팝업 CSS + 스크립트 템플릿 추가, `render_map()` 조립부에 삽입
    - 노드 → prj id 는 기존 규약(`svg g.node[id*="flowchart-P{id}-"]`) 재사용
    - 빌드 후 `Projects_map.htm` 재생성 (생성물이라 git 비추적)

## Issue370: Project List 행 hover 배경을 프로젝트 색으로 — Map 셀과 행이 따로 놀지 않게 ✅
* 목적: Issue368 로 색이 `Map` 셀 배경으로 내려가면서, 행에 마우스를 올리면 나머지 셀만 파란 hover 색(`#e8eef9`)이 되고 Map 셀만 프로젝트 색으로 남아 **한 행이 두 색으로 쪼개져 보인다**. hover 시 행 전체를 그 프로젝트 색으로 칠해 "지금 가리키는 행 = 이 프로젝트" 를 한 덩어리로 읽히게 한다

## Issue368: Project List 의 `색` 컬럼 → `Map` — 이슈맵 아이콘 3단 가시성, 색은 셀 배경 ✅
* 목적: Project List 팝업의 마지막 컬럼이 색 스와치만 보여줘 **정보량이 0에 가깝다**. 색은 이미 행마다 고유하니 셀 배경으로 충분하고, 그 자리는 hub 메인 카드처럼 **이슈맵 유무**를 알려주는 데 쓰는 편이 낫다. 프로젝트별로 "관계도를 볼 수 있는가"를 목록에서 한눈에 판정하고 바로 열 수 있게 한다
* 구현 명세:
    - 백엔드: `_projects_list_with_htm()` 행에 `issue_map`·`issue_map_stale` 주입 (`_issue_map_visible`/`_issue_map_stale` 재사용, TTL 30s 캐시 공유)
    - 프런트: `renderProjectList()` 의 `td.pl-color` → `td.pl-map`, 헤더 `{T:projectList.col.map}`. 링크는 카드와 동일하게 `fpmOpenInShell` 경유
    - 행 클릭 위임 핸들러에 `closest('a')` 가드 추가 — 아이콘 클릭이 행 선택으로 새지 않게
    - i18n: `data/locales/{ko,en}.json` 키 교체 (`col.color` 제거, `col.map` 추가)

## Issue369: 활성 세션 툴팁이 마우스 포인터에 가린다 — 행·버튼 네이티브 title 전면 → #live-tip + sid 병기 ✅
* 목적: hub 활성 세션 행의 📋 버튼이 **네이티브 `title`** 을 쓴다. 브라우저가 툴팁을 **커서 바로 아래**에 띄우므로 마우스 포인터에 가려 읽히지 않는다. 게다가 문구가 "세션 ID 복사" 뿐이라 **어느 세션의 sid 인지 복사 전에 확인할 수 없다**
* 구현 명세:
    - `services/hub/server.py` `rowHtml()` — 행 `<li>`·`.copy-sid`·`.card-close`(✕ 3종)·`.approve-btn` 의 `title=` → `data-tip=` 일괄 전환. 활성 세션 행에 네이티브 title 잔존 0
    - sid 는 `data-tip-sid` 속성으로 전달, `liveTipShow()` 가 `.tip-sid`(모노스페이스·디밍) 줄로 조립. **innerHTML 미사용** — topic 은 임의 문자열이라 DOM 조립만
    - `LIVE_TIP_SEL` 상수 신설(중복 셀렉터 2곳 통일) — 위임 대상 한 곳에서 관리
    - `#live-tip` 의 `white-space: nowrap` 폐기 → `pre-line` + `overflow-wrap: anywhere`. nowrap 은 `max-width` 를 무력화해 sid·행 설명을 실으면 화면을 넘긴다
    - 번들 미러 `plugins/fpm-core/services/hub/server.py` 동기 (i18n 키 추가 없음 — 기존 `liveSessions.copySidTitle`·`topicTitle` 재사용)

## Issue365: bare `IssueN` 이 prj 소속을 표현 못 해 digest 근거가 오귀속·이탈한다 ✅
* 목적: 공개 digest([`Issue_public.md`](Issue_public.md))는 소스 주석의 `(IssueN)` 을 스캔해 근거 이슈를 싣는다. 그런데 번들(`plugins/fpm-core`)은 prj3·prj1 양쪽에서 온 파일이 섞여 있고 주석의 번호는 **접두 없는 bare `IssueN`** 이라, 어느 프로젝트 이슈인지 표현할 수단이 없다. 그 결과 ① prj3 번호가 prj1 번호와 충돌하면 **엉뚱한 prj1 이슈가 공개**되고 ② `Issue335` 처럼 진짜 prj1 참조인데 경로로 일괄 제외하면 **근거가 미러에서 조회 불가**가 된다. 경로 단위 제외로는 못 고치는 표현력 문제다.
* depends: 없음
* 구현 명세:
    - 후보 방향 — ① 번들 주석의 prj3-origin 태그에 `prj3#` 접두를 강제(생성기·라이브가 prj3 소관이라 prj3 협조 필요) ② digest 스캐너가 파일의 origin(라이브 대응 존재 여부)을 보고 소속을 추론 ③ 번들 전용 파일만 tagcheck 대상으로 되돌림(곁가지 한정 처방)
    - ⚠️ prj3 자산을 고쳐야 하는 방향은 prj3 `Issue.md` 에 별도 등록하고 여기서는 prj1 몫만 다룬다

## Issue363: hub 🗺️ 판정↔맵 파일 stale 구조 불일치 — 아이콘은 실시간, 맵은 스냅샷 ✅
* 목적: 카드 🗺️ 아이콘 표시 여부는 `Issue.md` 를 **실시간** 파싱해 정하는데(`_issue_md_has_depends`), 클릭하면 서빙되는 `Issue_map.htm` 은 **생성 시점 스냅샷**이다. 이슈가 바뀐 뒤 맵을 재생성하기 전까지 아이콘과 내용이 어긋나, 아이콘을 믿고 눌렀는데 낡은 관계도(혹은 "생략" 안내)를 만난다. Issue361 원인 B 로 실측된 뒤 코드 버그가 아니라는 이유로 미뤄 둔 **구조적** 불일치다.
* depends: 없음
* 구현 명세:
    - 후보 방향 — ① `Issue.md` 보다 오래된 맵이면 아이콘에 stale 표식 ② `/issue-map` serve 시 mtime 비교 후 온디맨드 재생성 ③ `Issue.md` 편집 hook 으로 재생성
    - ⚠️ **방향 선택 시 제약**: ③은 hook 신설이라 이벤트 총합 예산·no-op 가드 규약([`~/.claude/rules/hook-rules.md`](~/.claude/rules/hook-rules.md))에 걸리고 배선이 prj3 소관이 된다. ①·②는 prj1 `services/hub` 안에서 닫힌다
    - 변경 범위는 **prj1 안으로 한정**한다. `~/.claude`(prj3) 수정이 필요한 방향은 별도 이슈로 분리
    - 검증: 맵보다 새로운 `Issue.md` 상태를 만든 뒤 카드 아이콘·서빙 결과가 일치함을 실측 · 기존 hub 테스트 회귀 없음

## Issue364: tagcheck 가 번들 동기 커밋을 구조적으로 차단 — 파생 경로 제외 부재 ✅
* 목적: [`scripts/precommit-tagcheck.py`](scripts/precommit-tagcheck.py) 의 `EXCLUDE_PREFIX` 에 `plugins/` 가 없다. 번들(`plugins/fpm-core`)은 라이브의 **기계적 파생물**이라 코드 주석의 Issue 태그가 prj3 번호(Issue360_4·366·370·371 등)를 그대로 들고 오는데, 검사는 prj1 `Issue.md` 기준이라 전부 "미등록 번호"로 잡힌다. 번들 동기 커밋은 **구조상 항상** 차단되고, 매번 `SKIP_TAGCHECK=1` 로 우회하면 게이트가 형해화된다.
* depends: 없음
* 구현 명세:
    - **채택: ① `EXCLUDE_PREFIX` 에 `plugins/` 추가 단독.** 근거는 "번들 태그는 공개 스위치가 아니다"가 **아니라** *"태그를 저작하는 곳이 여기가 아니라 원본이고, 원본은 이 검사를 그대로 받는다"* 이다. 번들 사본에서 차단해 봐야 고칠 곳이 여기가 아니라 조치로 이어지지 않고 동기 커밋만 막힌다
    - ⚠️ **digest 참조 코퍼스(`fpm-issue-digest.sh` pathspec)는 건드리지 않는다** — 초안은 `':(exclude)plugins/**'` 를 짝으로 넣었으나 검증에서 *"정당한 근거 손실 0"* 주장이 **거짓으로 반증**됐다(아래 결과 참조). 남는 구멍은 Issue365 로 분리
    - 검증: 번들 동기 커밋이 `SKIP_TAGCHECK` 없이 통과 · prj1 소스의 실제 오타 태그는 **여전히 차단**됨을 양성/음성 양쪽으로 실측

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

