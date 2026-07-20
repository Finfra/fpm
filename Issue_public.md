---
name: Issue_public
description: "fpm 공개용 이슈 근거 요약 — Issue.md 에서 제목·목적·구현 명세만 추출한 파생본"
generator: scripts/fpm-issue-digest.sh
source_sha: 79ed652fdf753402cc27efd33222c661a4a0058ed0aacc27e173919340acf017
---

# 안내

본 문서는 자동 생성 파생본이다. 원본 이슈 트래커(`Issue.md`)는 개인정보가 포함되어 공개하지
않으며, 여기에는 **코드 변경의 근거를 이해하는 데 필요한 필드만** 추출되어 있다.

* 포함: 이슈 제목 · `목적` · `구현 명세` · `depends`
* 제외: 상세 · Walkthrough · 진행 결과 · 커밋 해시 · plan/task 경로

소스 코드 주석의 `(Issue{N})` 참조는 아래 항목에서 찾을 수 있다. 직접 편집하지 말 것 —
`scripts/fpm-issue-digest.sh` 가 덮어쓴다.

# 이슈 근거

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

## Issue304: `render_target` 정본에 b모드(ask 폼) 표면 매핑 동기 ✅
* 목적: prj3#Issue269 가 b모드 ask 폼의 표면을 `render_target` 2축 기준으로 이행했으나, 키 상세 **정본**인 prj1 `_doc_arch/hub_setting.md` 는 여전히 이 키를 "`..show`·자동 렌더(a모드)" 전용으로 서술 중이었다. 정본이 소비처 하나를 누락하면 다음 변경 때 같은 stale 매핑이 재발한다.
* depends: prj3#Issue269 (완료 — commit <commit>)
* 구현 명세:
    - `_doc_arch/hub_setting.md`: 도입부에 b모드 포함 명시 + prj3#Issue269 인용 blockquote 신설 / 값 표 아래 "b모드 폼의 표면 매핑" 항목 추가(회수는 same-origin 상대경로라 표면 무관) / `simple_browser_focus` 절에 "적용 대상 축소" 항목 추가
    - `_doc_arch/hub_htm.md`: Mode B 절의 `file://` 폼 서술 폐기 → 표면은 `render_target` 이 결정한다고 교정
    - 복잡도 triage: 문서 2파일 + 방법 자명(선행 이슈 결과 반영) → **단순** (plan/task/report 없음)

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

## Issue300: 세션 📋 두 번 클릭 시 VSCode 세션으로 이동 (숨은 기능) ✅
* 목적: hub 활성 세션 행에서 그 세션의 VSCode 탭으로 가는 조작을 하나 더 얹되(Projects_map 활성 세션 🟢 아이콘과 같은 동작), 버튼은 늘리지 않는다. 행은 이미 [행 클릭 = VSCode 포커스] + [📋 = sid 복사] + [✕ = dismiss] 로 차 있어 아이콘을 추가하면 좁은 행이 4개가 된다. 이미 있는 "복사됨(녹색)" 상태를 두 번째 클릭의 모드 구분자로 재사용한다.
* 구현 명세:
    - `services/hub/server.py` `copySid()` 진입부에서 `.copied` 클래스 검사로 분기 → `openSession(row.dataset.cwd, row.dataset.sid)` (= `POST /open-session`, 행 클릭·Projects_map 🟢 와 동일 경로)
    - `origin=terminal` 세션은 VSCode 포커스 불가(Issue177) → `openSessionViewer(row.dataset.url)` 로 폴백
    - 녹색 유지 1.2s → 3s (두 번째 클릭 여유). 타이머는 `btn._sidTimer` 보관 → 연타 시 중복 setTimeout 정리
    - 신규 엔드포인트 없음 — 기존 `/open-session`(Issue131)·행 `data-url`(Issue219) 재사용
    - `plugins/fpm-core` 번들 사본 동기화 (Issue291 게이트)
    - 검증: 재기동된 hub(`/hub`)가 새 `copySid` 를 serve 하는지 curl grep 으로 확인 ✅

## Issue299: 프로젝트 맵에 활성 세션 아이콘 + 클릭 시 VSCode 세션 포커스 ✅
* 목적: `Projects_map.htm` 은 "무엇을 하려고 무엇이 필요한가"만 보여줄 뿐 **지금 어디가 살아 있는지**를 못 보여준다. 맵을 열어 놓고 작업하는 흐름에서 활성 세션을 보려면 hub 로 되돌아가야 한다. 맵 노드에 활성 세션 아이콘을 얹고 클릭으로 해당 VSCode Claude Code 세션 탭까지 바로 가게 한다.
* 구현 명세:
    - `build_projects_map.py` — `render_session_script()` 신설. 빌드는 `경로 → prj id` 매핑만 굽고, 세션은 페이지가 열려 있는 동안 `GET /boards` 의 `live_sessions` 를 5초 주기로 조회해 그린다(스냅샷을 박으면 여는 즉시 stale)
    - 세션 `cwd` 가 서브폴더면 등록 루트까지 상향 탐색해 해석 — 서버 `_resolve_project_root` 와 같은 규칙 (`fSnippet/_public` → prj25, `videoMaker/lib/m2slide` → prj42 실측)
    - 배지는 mermaid 라벨이 아니라 노드 `<g>` 의 SVG `<text>` 로 얹음 — `<foreignObject>` 는 렌더 시점 크기로 클리핑되어 나중에 덧붙인 요소가 안 보인다
    - 노드 id 가 `mermaid-<ts>-flowchart-P{id}-{n}` 이라 prefix 매칭(`^=`) 불가 → 부분 매칭(`*=`) + 뒤의 `-` 로 `P1`/`P10` 분리
    - 대상 3곳: mermaid 노드 · 텍스트 트리 `li` · 미할당 목록(그래프에 없다고 배지까지 빼면 "어디가 살아 있는가"에 구멍)
    - 🟢 일반 세션 / 📊 dashboard, 툴팁 = 제목 · 종류 · sid 앞 8자. 클릭은 `preventDefault`+`stopPropagation` 로 노드 링크(`/open-prj`) 전이 차단
    - **부수 수정** — `services/hub/server.py` `_normalize_mermaid_runtime` 의 스크립트 제거 판정을 "mermaid 문자열 포함"에서 "런타임 로드·초기화 신호"(`src`/`import` mermaid · `mermaid.initialize|run|render|mermaidAPI` · `window.mermaid` · `startOnLoad`)로 축소. 종전 규칙이 주석의 mermaid 언급만으로 이 오버레이 스크립트를 통째로 삭제했고, 조용히 증발해 콘솔에 흔적이 없어 추적이 어려웠다. 번들 미러 `plugins/fpm-core/services/hub/server.py` 동시 반영

## Issue298: 프로젝트 맵 v2 — 확정 표기 파서 구현 + 소스 정합화 ✅
* 목적: 맵 표기 규약(펜스 제거·Main/Sub Map·`:`목적·`@`담당주체·`"참조"`)이 확정됐으나 파서가 따라오지 못해 **맵 생성이 멈춰 있다**. 파서를 확정 표기에 맞추고 소스 정합 결함을 해소해 지도를 되살린다.
* depends: Issue294
* 구현 명세:
    - **P1 파서 개정** — ① 펜스 의존 제거, `## Main Map`·`### {맵}` 헤딩 단위 수집(반환을 `{맵: [루트]}` 로 확장) ② `- "맵이름"` 을 참조 노드로 인식 ③ `:` 뒤를 `purpose` 로 분리(라벨 제외, 툴팁 병기) ④ `@` 접두·중위 양쪽 관용 파싱 ⑤ 완전성을 전 맵 **합집합**으로. 렌더는 참조를 **간선으로 환원**(참조 노드 생성 금지 — 한 장 통합·순환 무한전개 방지), Sub Map 헤딩을 `subgraph` 제목/루트로 승격
    - **P2 감지 확장** — `detect_dead_loops()` 를 참조 환원 그래프 기준으로. 참조발 다중 부모는 **정상**(실물 1회 + 참조면 중복 아님), 자기 참조는 즉시 결함
    - **P3 소스 정합화** — 헤딩 따옴표 제거 · 중복 3건 해소 · `:` 설명 3건을 목적으로 · `## "fApp"` → `### fApp` · 분류 라벨 교체. **감지기 경고를 근거로** 진행
    - **P4 커버리지(선택)** — 목적이 분명한데 빠진 것 배치(`81·82`·`45~47`·`60~62·71·58`·`7`). 나머지는 미분류로 두어 "목적 미할당" 신호 유지
    - **순서 제약**: P1 → P2 → P3. P3 를 먼저 하면 파서가 소스를 못 읽는 상태라 **고쳤는지 검증할 수단이 없다**
    - mermaid 라벨은 `숫자.` 로 시작시키지 않는다(`videoMaker #41`) — Issue204/242 오파싱

## Issue297: `default_browser` 설정 밖의 Chrome 유입 3경로 정리 ✅
* 목적: `hub_setting.yml` 의 `default_browser: firefox` 를 지정해도 hub 대시보드·터미널 경로는 계속 Chrome 으로 열림. 원인이 설정 무시가 아니라 **설정의 적용 범위 밖에 있는 3개 경로**임을 확인했으므로, 각 경로를 설정 SSOT 로 수렴시키거나 최소한 문서화해 재혼란을 막는다.
* depends: Issue295
* 구현 명세:
    - `sh/fpm_function.sh` `fhub()` 의 `*) db=chrome ;;` 강제 치환 제거 → firefox 는 firefox 로 열되 탭 재사용 포기(helper 가 Firefox 탭 제어 불가 → 매 호출 새 탭 누적). 트레이드오프를 주석에 명시
    - KM 매크로 "fPm hub page Open" 을 AppleScript 하드코딩 대신 `fhub` 셸 호출로 교체 → 설정 SSOT 단일화. ①은 ② 수정 후에만 의미 있음
    - `fpm-browser-open.sh` helper 기본값 `app_raw="chrome"` → `firefox` 또는 필수 인자화 검토(직접 호출 시 함정 제거)
    - ③ OS 기본 브라우저는 **코드로 해결 불가** — 사용자 판단 영역. `CLAUDE.md` 의 "Chrome=일반 / Firefox=hub 전용 분리" 운영 모델과 충돌하므로 변경 권고하지 않고, 대신 `_doc_arch/hub_setting.md` 에 "설정이 커버하지 않는 경로" 절을 추가해 명문화
    - 검증: `fhub` 실행 시 Firefox 로 열리는지 + KM 매크로 실행 결과 동일 확인

## Issue288: 백그라운드 세션 자동 렌더가 VSCode 포커스를 탈취 ✅
* 목적: 사용자가 A 프로젝트 VSCode 창에서 타이핑 중인데, 다른(백그라운드) 프로젝트 세션이 hub 문서를 자동 렌더하면 그 프로젝트 창이 강제 전면화되어 포커스·키 입력을 빼앗기는 문제 제거. 사용자 클릭 기반 전면화(정상 동작)는 보존.
* 구현 명세:
    - 신규 설정 `simple_browser_focus` (advanced 탭, select) — `gate`(기본)/`always`(구 동작)/`never`(URI 미발사, 등록만)
    - `gate` 판정: frontmost 프로세스가 `Code` 인데 front window 제목이 owner 프로젝트 basename 과 불일치 → **다른 프로젝트 창에서 작업 중**으로 보고 open skip(200 `skipped-not-frontmost`). 일치하면 이미 전면이므로 그대로 진행(체감 전환 없음). frontmost 가 VSCode 가 아니면(iTerm 등) 기존 동작 유지 — 그 세션과 상호작용 중일 가능성이 높음
    - 판정 실패(접근성 권한 부재·osascript 오류·timeout) 시 fail-open + WARNING 로그 (기능 조용한 무력화 금지)
    - 문서 등록(register-doc)은 skip 여부와 무관하게 유지 → hub-shell 탭·폴링(Issue199)·채팅 fallback URL 로 수거 가능, 정보 유실 0
    - 한계(명시): iTerm/tmux 세션은 프로세스명만으로 어느 pane 의 세션인지 식별 불가 → iTerm frontmost 상태에서의 백그라운드 세션 렌더는 여전히 전환됨
    - 검증: `python3 -m py_compile` + 서버 재기동 healthz + 실제 POST 로 gate/always/never 3분기 로그 확인

## Issue292: `test_i18n_parity.py` 가 상시 FAIL — `t()` 참조 키 정규식이 `split(".")` 을 오탐 (!) ✅
* 목적: hub 테스트 13종 중 1종이 항상 실패해 회귀 감지력이 죽어 있음. 실패 원인이 실제 i18n 누락이 아니라 테스트 자체의 정규식 오탐이므로, 이 상태로는 진짜 i18n 키 누락이 생겨도 구분되지 않는다.

## Issue296: Issue.md 비공개 전환 — exclude + 파생 digest + 과거 유출분 history 정리 ✅
* 목적: `Issue.md` 3,822줄이 fpm 공개 미러(github.com/Finfra/fpm)로 전량 공개되어 개인정보(실사용 호스트명·사설 IP·tailnet ID·홈 경로·세션 ID)가 노출됨. 비공개로 전환하되, 2026-06-21 Issue187 이 "소스코드 수정시 근거 없어서 오작동 가능성" 을 이유로 폐기했던 실패를 반복하지 않도록 **근거 보전 장치를 함께 도입**함.
* 구현 명세:
    - **계층 1**: `data/publishable-policy.yml` `exclude[]` 에 `Issue.md` 등록 (통째 제외).
    - **계층 2**: `fpm-issue-digest.sh` 신설 — `Issue.md` → `Issue_public.md` 화이트리스트 추출(제목·`* 목적`·`* 구현 명세`·`* depends`). `___pm` 에서 생성·커밋하여 사람 리뷰 게이트 확보. `git archive HEAD` 특성상 미커밋분은 반출 불가.
    - **신선도 게이트**: `Issue_public.md` frontmatter `source_sha` ↔ 현재 `Issue.md` 해시 대조. 불일치 시 forward 중단(fail-loud). 자동 재생성 금지(리뷰 우회 방지).
    - **파이프라인 무수정**: digest 는 평범한 tracked 파일로 기존 sanitize→gitleaks→guard 를 그대로 통과. `fpm-sync.sh` 변경 없음.
    - **과거분 정리** (사용자 결정 2026-07-19, 과거분 포함): `git filter-repo --path Issue.md --invert-paths` + `--replace-text` 로 외주 클라이언트 리터럴 치환 → `git push --force`. 사전 `git clone --mirror` 백업 필수. **force push 직전 사용자 승인 재확인 게이트** (설계 확정 ≠ 실행 승인).
    - **재유출 방지**: `.gitleaks.toml` 에 tailnet 호스트명 등 내용 룰 추가. exclude 적용 후 TMP2 dry-run 으로 오탐 0 확인 후 활성(선행 활성 시 forward 영구 차단 위험).
    - 복잡도: **복잡** — 파괴적 원격 작업 + 정책 변경이 후속 공개 운영 전반에 영향.

## Issue295: render_target 의미 드리프트 — 표면(surface) 축 분리로 직교성 복원 ✅
* 목적: `render_target` 이 원설계상 **URL 형식**(file:// vs hub http)만 담당하는 직교 키였는데(prj1#Issue170 "render_target 은 URL 형식만 담당(직교)"), prj3#Issue170 에서 `hub` 값이 **표면 선택**(VSCode Simple Browser 패널 + 외부 open 금지)으로 재정의되며 두 축이 한 키에 눌려 담김. 결과로 "hub 서버 URL 로 **브라우저**에 열기" 조합이 **어떤 값으로도 표현 불가**해짐. 표면 축을 값으로 분리해 직교성 복원.
* depends: prj3#Issue263
* 구현 명세:
    - `services/hub/server.py` HUB_SETTING_SCHEMA `render_target`: options `["local-open", "hub", "vscode", "both"]` 로 확장, comment 를 4값 기준으로 재작성 (`hub`=hub 서버 http URL 로 외부 브라우저 open / `vscode`=VSCode Simple Browser 패널, 외부 open 금지)
    - `data/hub_setting.yml`: 주석 4값 기준 갱신 + 현재 값 `hub` → `vscode` 로 변경(현행 동작 무변경 보존). **prj3 hook 반영 후에만 수행**
    - `_doc_arch/hub_setting.md` SSOT 미러 갱신
    - 본 파일 1696행 prj1#Issue170 기록에 "prj3#Issue170 에서 재정의됨 → Issue295 에서 축 분리" 각주 추가 (stale 기록 교정)
    - 검증: `python3 -m py_compile services/hub/server.py` + 서버 재기동 후 설정창 고급 탭에서 4값 노출 확인 + 각 값으로 1회씩 `..show` 실행하여 표면 확인

## Issue294: 프로젝트 맵을 mermaid 다이어그램으로 전환 + 버튼명 `Map` ✅
* 목적: `Projects.md` 섹션명이 `# Project Map` 으로 바뀌면서 생성기가 파싱 대상을 못 찾아 **맵 생성이 실패**하고 있다(산출물 stale). 동시에 표현을 이슈맵과 같은 mermaid 다이어그램으로 통일해 계층·소속을 한눈에 보이게 하고, 노드에서 프로젝트로 바로 점프할 수 있게 한다.
* depends: Issue293
* 구현 명세:
    - `build_projects_map.py` — heading 매칭을 `# Project Map` 으로 갱신하되 legacy(`# 프로젝트 트리` · `# Project Tree`)도 허용(구 문서 호환)
    - `build_projects_map.py` — 출력 본문을 `<pre class="mermaid">` flowchart 로 교체. 번호 대역 그룹은 `subgraph`, 프로젝트는 노드(`이모지 이름 #id`), 계층은 화살표. 각 노드에 `click N href "/open-prj?id=<id>"` 부여. 런타임 스크립트는 저작하지 않는다 — hub `_normalize_mermaid_runtime` 이 canonical 로 주입(직접 넣으면 정규화가 제거)
    - `services/hub/server.py` — GET 브리지 `/open-prj?id=<정수>` 신설. `/ob` 와 동일 등급(호스트에서 `open` 실행)이므로 **loopback 전용**. 입력은 정수 id 하나뿐이고 경로는 서버가 `projects/<id>` 인덱스에서 조회 → 클라이언트발 경로 입력면 0. 성공 시 VSCode 로 열고 204/안내 응답
    - `services/hub/server.py` — 헤더 버튼 라벨 `🌳 Tree` → `🗺️ Map`, `data-title` 도 `Project Map`
    - `data/locales/{ko,en}.json` — `projectsMap.openTitle` 문구를 새 섹션명 기준으로 갱신
    - 번들 동기: `scripts/fpm-bundle-sync.sh` (Issue291 게이트)
    - 검증: 생성기 재실행 성공 → `/projects-map` 200 → playwright 로 노드 앵커 `href` 가 `/open-prj?id=` 로 나오는지 확인 → `/open-prj?id=1` 이 VSCode 를 여는지 확인 → hub 테스트·번들 표류 검사

## Issue293: hub 헤더에 프로젝트 트리 맵 버튼 추가 (`📋 Projects` 오른쪽) ✅
* 목적: `Projects.md` 의 `# Project Tree` 섹션을 렌더한 `Projects_map.htm` 이 이미 생성되어 있으나 hub 에서 여는 경로가 없다. 생성기만 있고 소비 UI 가 없어 사실상 안 쓰이는 산출물이므로, hub 헤더에서 한 번에 열 수 있게 한다.
* 구현 명세:
    - `services/hub/server.py` 상수: `PROJECTS_MAP_NAME = "Projects_map.htm"`, 경로는 `os.path.join(REPO_ROOT, PROJECTS_MAP_NAME)` 서버 고정
    - 엔드포인트 `/projects-map` → `_handle_projects_map()`. 파일 부재 시 404 + 재생성 커맨드를 담은 안내(생성기 경로 명시). 성공 시 `_send_htm_html()` 재사용 — `/htm-doc`·`/issue-map` 과 동일 렌더 규약(mermaid 정규화·헤더 CSS·close/copy shim) 자동 적용
    - UI: `server.py:8293` `.header-actions` 의 `📋 Projects` **바로 오른쪽**에 `<button class="btn-project-list" id="btn-projects-map" title="{T:projectsMap.openTitle}">🌳 Tree</button>` 추가(⚙️ 설정 버튼보다는 왼쪽). 스타일은 기존 `.btn-project-list` 클래스 재사용 — 새 CSS 불요
    - JS: `btn-project-list` 와 같은 위치(`server.py:9490` 인근)에 리스너 추가 → `/projects-map` 을 hub 쉘 탭으로 open (기존 문서 열기 경로와 동일 방식 사용, OS 새 탭 직행 금지)
    - i18n: `data/locales/{ko,en}.json` 에 `projectsMap.openTitle` 추가. 키 누락 시 `test_i18n_parity.py` 가 잡아야 정상이나 그 테스트는 Issue292 로 오탐 상태 — 수동 확인 병행
    - 번들 동기: 라이브 `services/hub/server.py` 변경이므로 완료 후 `scripts/fpm-bundle-sync.sh` 실행(Issue291 게이트)
    - 검증: `python3 -m py_compile` → 서버 재기동 healthz 200 → 버튼 클릭 시 트리 맵 렌더 확인 → `Projects_map.htm` 을 임시로 치워 404 안내가 뜨는지 확인

## Issue291: plugins/fpm-core 번들이 라이브 SCAR 대비 ~100개 이슈 뒤처짐 ✅
* 목적: 마켓플레이스 배포본 `plugins/fpm-core/` 가 라이브(`~/.claude/hooks`, `services/hub/`) 대비 크게 정체되어, 플러그인으로 fpm 을 설치한 사용자는 수개월치 수정이 빠진 hub 를 받는다. 정체 규모를 확정하고 동기 전략을 정한다.
* 구현 명세:
    - 1단계 — 동기 방식 결정: (a) 라이브 전량 복사 후 회귀 테스트, (b) 번들 폐기하고 설치 시 라이브에서 생성, (c) 정체 허용하고 번들 버전을 명시적으로 pin. 셋 중 택1이 본 이슈의 핵심 결정
    - 2단계 — (a) 선택 시: `services/hub/` + `hooks/` + `commands/` + `agents/` 를 한 커밋으로 복사, `test_*.py` 3종 통과 확인, 플러그인 재설치 스모크(렌더 1회 → `/htm-doc` 200)
    - 3단계 — 재정체 방지: 라이브 변경 시 번들 동기를 강제할 hook 또는 릴리스 체크리스트 항목 추가
    - 참고: 본 이슈는 Issue289 의 파생이나 범위가 별개(번들 수명주기 전반). Issue289 종결을 막지 않는다

## Issue289: z_htm 무한 누적 해소 — htm 수명주기 도입 (활성 `htm/` → 아카이브 `z_done/htm/`) ✅
* 목적: `_doc_work/z_htm/` 에 hub 렌더 산출물이 회수 경로 없이 무한 누적되어 관리 불가 상태. 활성/아카이브 폴더를 이름과 의미가 일치하도록 재편하고, 아카이브 이동 시 참조가 깨지지 않게 만든다.
* 구현 명세:
    - P1 (읽기 지원, 본 이슈): `server.py` 에 `HTM_DIRS = ["htm", "z_done/htm", "z_htm"]` 상수 도입 → 15+ 하드코딩 전량 치환. `/htm-doc?path=` 가 ENOENT 일 때 동일 프로젝트 루트 하위 `HTM_DIRS` 에서 **basename 만** 재탐색하여 hit 시 200 서빙 + registry 경로 rewrite(self-heal). traversal 방지 위해 basename 외 경로 성분 미사용, 기존 whitelist·tombstone 판정은 재탐색 경로에도 동일 적용(cleared 문서 부활 금지)
    - P1 검증: `python3 -m py_compile services/hub/server.py` + 서버 재기동 healthz + 이동시킨 htm 1건으로 fallback 200·registry rewrite 실측
    - P3 (마이그레이션): `/pm-check` 필수 폴더에 `_doc_work/htm` 추가, `_doc_work/` 보유 전 프로젝트에 `z_done/` 보장, `z_htm` 발견 시 `z_done/htm/` 이관 제안. `.claude/skills/pm/SKILL.md` 멱등 매트릭스도 동반 갱신. **완료 조건은 `/pm-check all` 실행 후 37개 프로젝트 결과표에서 `z_done`·`htm` 전부 ✓ 확인** (정의만 고치고 끝내면 z_done 7개 부재가 그대로 재현됨)
    - P3 `SKIP` 갱신: `"0 7 25 26"` → `"0 2 7 25 26"`. prj2 기존 `z_htm/`(78건)은 이관하지 않고 현상 유지 — 대상 아님
    - P4: 전 프로젝트 마이그레이션 확인 후 `HTM_DIRS` 에서 legacy `z_htm` 제거
    - **순서 제약**: P1(읽기) → prj3#Issue258 P2(쓰기 전환) → P3 → P4. 역순이면 전환 구간 생성분이 전부 미등록 403

## Issue290: hub 카드 🗺️ 배지 false positive 재발 — `_issue_md_has_depends()` 가 보류·취소 섹션을 모름 ✅
* 목적: prj3#Issue259(issue-map 이 ⏸️ 보류·🚫 취소 이슈를 관계도에서 제외) 반영 후, hub 카드는 🗺️ 를 띄우는데 실제 맵은 "그래프 생략(depends 연결 0건)" 을 렌더하는 불일치가 prj1 에서 재현됨. Issue284_3 에서 완료 이슈에 대해 막았던 것과 동일 계열 결함이 제외 섹션 축으로 되살아난 것 — 판정 기준을 맵 생성기와 다시 일치시킨다.
* depends: prj3#Issue259
* 구현 명세:
    - `services/hub/server.py` `_issue_md_has_depends()`: 섹션 추적 추가 — `^#\s+(.+?)\s*$` 로 H1 헤딩을 만나면 현재 섹션 갱신, 섹션이 `⏸️ 보류` · `🚫 취소` 이면 그 구간의 `* depends:` 를 무효 처리. 정규식·섹션명은 `build_issue_map.py` 의 `EXCLUDED_SECTIONS` 를 그대로 미러
    - 화이트리스트(포함 섹션 열거)가 아닌 **블랙리스트**로 구현 — 프로젝트별 완료 섹션명 커스터마이즈(ex: `🏁 완료-해결순`, `issue-g.md` 참고)를 화이트리스트가 깨뜨림
    - 캐시 TTL(`_issue_map_cache`) 구조는 불변 — 판정 함수 내부만 교체
    - 검증: prj1 에서 판정 False 확인(맵 그래프 0건과 일치) + 보류 섹션 depends 를 임시 제거한 합성 케이스에서 True 유지 확인

## Issue287: open-simple-browser 서브폴더 cwd 미정규화로 VSCode 새 창 발생 ✅
* 목적: hub 문서 카드 "↗"(Simple Browser 열기) 클릭 시, 등록된 문서의 `owner_cwd`가 프로젝트 루트가 아닌 하위 폴더(예: `m2slide/Projects/aTest`)이면 정규화 없이 그대로 VSCode 오픈 대상으로 써서 이미 열려있는 프로젝트 루트 창을 재사용하지 못하고 새 창이 뜨는 문제 수정.
* 구현 명세:
    - `_handle_open_simple_browser`의 target_cwd 판정을 `_resolve_project_root(owner_cwd)` 결과의 `path`로 정규화한 뒤 `allowed` 검증으로 교체
    - 검증: `python3 -m py_compile services/hub/server.py` 통과(문법 OK) + 파이썬 인터프리터로 `_resolve_project_root("/Users/user/_git/__all/videoMaker/lib/m2slide/Projects/aTest")` 직접 호출해 `.../videoMaker/lib/m2slide` 로 정규화됨을 확인 + `dev-server-restart` hook 이 hub 서버 자동 재기동(healthz 200 확인)

## Issue286: 전 프로젝트 .gitignore 에 `Issue_map.htm` 추가 (생성 산출물 추적 제외) ✅
* 목적: `issue-map` 스킬 산출물 `Issue_map.htm` 은 `Issue.md` 로부터 매번 재생성되는 **파생 산출물**이므로 git 추적 대상이 아님. `_doc_work` 계열을 이미 ignore 하는 프로젝트는 같은 정책을 `Issue_map.htm` 에도 적용해야 일관됨. 지금은 **41개 프로젝트 중 0개**만 `Issue_map` 패턴을 가짐 → prj3 Issue246(issue-map 글로벌 승격)으로 전 프로젝트가 이 파일을 생성하기 시작하면 대량 오추적 발생
* 구현 명세:
    - 대상 35개 프로젝트 `.gitignore` 말미에 아래 2줄 append (중복 방지 — 기존에 `Issue_map` 문자열 있으면 skip):
        ```
        # issue-map 산출물 (Issue.md 로부터 재생성 — prj1#Issue286)
        Issue_map.htm
        ```
    - 이미 추적 중인 `Issue_map.htm` 이 있으면 `git rm --cached Issue_map.htm` 로 untrack (현재 조사상 해당 없음 — 실행 시점 재확인)
    - 파일명은 `Issue_map.htm` **고정**(prj1#Issue284 hub 카드 탐지 기준·prj3 Issue246 산출물 표준과 동일). 다른 이름 병행 시 본 이슈도 함께 갱신
    - **검증**: 스윕 후 35개 전부에서 `grep -c 'Issue_map' .gitignore` ≥ 1, 대상 외 6개는 무변경 확인. 각 프로젝트는 자체 repo 이므로 프로젝트별 commit 필요(단일 commit 불가)
    - triage: 중간 (다수 repo 동시 변경 — 커밋 단위·미추적 확인이 필요)
    - **연관**: prj3 Issue246(issue-map 글로벌 승격 — 본 이슈의 원인), prj3 Issue246_1(본 이슈 완료 검증), prj1 Issue284(hub 카드 이슈맵 아이콘)

## Issue285: 배포본 fpm-hub.md mermaid 런타임 규정을 canonical 1줄로 동기 ✅
* 목적: prj3(`~/.claude`)가 Issue244 로 mermaid 런타임 규정을 canonical 1줄로 갱신했으나 **prj1 배포본은 구 2줄 규정 그대로** → 마켓플레이스로 fpm-core 를 설치한 사용자는 hub 서버·정규화기 실동작과 어긋나는 문서를 수령 중. 규정대로 저작해도 매 렌더 정규화가 발생해 "이탈" 경고가 뜨는 알람 피로 유발
* 구현 명세:
    - prj3 가 이미 반영한 [`~/.claude/commands/fpm-hub.md`](../../.claude/commands/fpm-hub.md) "다이어그램 런타임" 절을 배포본에 동일 적용 (prj3 commit `<commit>` 참조)
    - 반영 항목 4가지:
        1. canonical = `</body>` 직전 외부 UMD **1줄**. 인라인 `<script>` 0줄, `<head>` 배치 아님
        2. 인라인 폐기 사유 명시 — VSCode HTML preview CSP(`script-src https: vscode-resource:`)에 `'unsafe-inline'` 없어 인라인 `<script>` 통째 차단
        3. `theme: 'neutral'`(Issue58 흰 배경 정책)은 인라인 JS 대신 **다이어그램 소스 선두 frontmatter**(`config: theme: neutral`)로 지정. prj3 Playwright 실측 확인 (node fill `#eee`, default 테마 `#ECECFF` 아님)
        4. 이탈 금지 목록에 "인라인 `mermaid.initialize()`" 추가 (구 Issue82 2줄 형식 폐기 명시)
    - **검증**: 갱신된 문서대로 저작한 htm 을 `sh/fpm-htm-mermaid-normalize.py --check` 에 통과시켜 rc=0(무이탈) 확인. rc=1 이면 문서가 아직 정규화기와 불일치
    - **참조**: prj3 Issue244 (쓰기시점 hook 집행 — `~/.claude/hooks/hub-htm-mermaid-normalize.sh`), 관련 prj1 Issue244(서버 런타임 정규화)·Issue256(코드펜스 재작성)·Issue190(산문 이탈 금지 가드)

## Issue284: hub 프로젝트 카드에 Issue Map 아이콘 노출 ✅
* 목적: 이슈맵 문서(`Issue_map.htm`)를 가진 프로젝트는 hub 활성 세션 카드에서 **🗺️ 1클릭으로 이슈 의존 관계도**를 열 수 있게 함 — 종전엔 파일 위치를 알아야 열 수 있어 사실상 사장됨

## Issue283: hub htm 문서 `file://` 절대경로 이미지 깨짐 — /htm-res abs 모드 신설 ✅
* 목적: Issue255(상대 `<img src>` → `/htm-res?doc=&rel=`)가 커버하지 못한 **절대 `file://` src** 사각 제거. 이미지 생성 스킬(`img-add`)이 프로젝트 밖(`~/Desktop`)에 저장한 파일을 문서가 `file:///…` 로 참조 → hub 에서 항상 깨짐

## Issue282: hub 활성 세션 카드 중복 — 동일 세션이 cwd 드리프트로 2장 노출 ✅
* 목적: 같은 claude 세션(sid·pid 동일)이 fSnippetData·unity_base 등에서 카드 2장(이모지 有/無)으로 중복 노출되는 결함 제거
* 구현 명세:
    - `_handle_session_register` live 분기: 동일 sid 가 다른 hash 아래 이미 존재하면 기존 프로젝트 cwd 로 치환(sid-sticky) — cd 드리프트 재등록이 신규 entry 를 못 만들게 원천 차단 + projects 등록 오염 방지
    - `_collect_live_sessions`: Issue99 dedup 키를 `(h, live_pid)` → `live_pid` 전역으로 확장 (freshest 승) — 기존 잔존 중복 자가 정리
    - `_project_emoji`: exact 실패 시 `_resolve_project_root` prefix fallback — name/emoji 매칭 대칭화
    - 검증: `test_session_dup_issue282.py` 11건 전건 통과 + hub 전체 스위트 회귀 없음(i18n 2건 실패는 HEAD 기존 실패로 무관 확인) + 라이브 서버 재시작 후 sessions.json sid 중복 0건

## Issue281: prj1 로컬 SCAR → 글로벌 승격 후 잔여 원본 정리 (prj3 Issue229 대응) ✅
* 목적: prj3(`~/.claude`)에서 Issue229(서브이슈1~5)로 prj1 로컬 SCAR 5건(gh-sync/scar-export/fapp-parallel·serial/hub-dev-rules/server-check)을 글로벌 승격 완료. 글로벌 이관은 전제로 두고, prj1 쪽에 남은 구 로컬 원본을 정리(삭제/wrapper화/설정 이관)했다. prj3 세션이 완료 후 commit hash 를 폴링 회수.

## Issue280: hub 세션 페이지 GC 버튼 — 세션·터미널 pane 강제 종료 ✅
* 목적: VSCode 터미널·tmux·iTerm 기반 Claude 세션이 정리되지 않고 가비지로 쌓임. 세션 페이지(`/s/{h}/{sid}`) 상·하단 버튼으로 해당 세션과 터미널 pane 을 강제 종료(GC). 종료 메시지는 실전달 없이 레코드로만 저장(향후 분석용).

## Issue279: hub 새 피드 도착 시 헤더 토글 아이콘 깜빡임 (기본 on, 고급탭 off) ✅
* 목적: 활동피드에 새 항목이 도착해도 헤더 토글 아이콘(🙉/🙈)은 정적이라 새 활동 인지가 어려움. 새 피드 도착 순간 아이콘을 반대 이모지로 잠깐 깜빡(🙉↔🙈)여 시각 알림. 고급탭 옵션으로 off 가능, 기본 on.

## Issue278: hub 문서 뷰 헤더에 세션 ID 복사 버튼 추가 (🆚 뒤 📋) ✅
* 목적: Issue276/277 은 hub 메인 패널 활성세션 목록 행에만 복사 버튼을 달았다. 문서 뷰 헤더(`/view`·`/htm-doc` 로 serve 되는 canonical 핑크 헤더)에도 동일한 📋 세션 ID 복사 버튼을 추가 — 문서를 보면서 그 문서를 만든 세션의 sid 를 `/cc-session id` 없이 바로 복사. 사용자 제안(이미지: m2slide Issue290 렌더 헤더, 🆚VS 뒤·🔗 앞 위치).
* depends: Issue276, Issue277
* 구현 명세:
    - 대상: `services/hub/server.py` (SID_COPY_SHIM 상수 + 2개 serve 경로 게이트 주입)
    - 검증: `ast.parse` OK → hub 재시작(launchd bootout+bootstrap, pid=15993 uptime=1) → m2slide Issue290 문서(`/view`, sid `<commit>-…`) curl: `class="sess-link"`+`sid:'<commit>-…'` 추출·`copy-sid` 주입 1건·타이틀 `이 세션 ID 복사` 서빙 확인. 옵션 게이트 실측: `live_session_copy_button: false` → copy-sid 0건, 복원 후 1건.
    - ⚠️ serve-time 주입이므로 이미 열린 문서 탭은 새로고침해야 반영(COPY_LINK_SHIM 과 동일).
    - 한계: 서버 주입(HTML 바이트) 검증까지 완료. 브라우저 실렌더에서 버튼 클릭→클립보드 복사 동작은 COPY_LINK_SHIM 검증된 동형 로직 재사용 — 육안 확인은 사용자 새로고침 시.

## Issue277: hub 세션 ID 복사 버튼 표시 유무 설정 옵션 추가 (고급탭 토글, 기본 표시) ✅
* 목적: Issue276 복사 버튼(📋) 표시 여부를 설정 고급탭에서 토글로 제어. 기본값=표시(true). 사용자 요청.
* depends: Issue276
* 구현 명세:
    - apply=auto → 서버 재렌더로 반영(restart 불요). 단 schema/payload 코드 변경이라 이번엔 hub restart 수행(pid=26051)
    - 검증: `ast.parse` OK + ko.json 파싱 OK + 6지점 grep 각 1 + `/boards` payload `live_session_copy_button: true` 서빙 + `/hub` JS `s.sid && showCopy`·`data.live_session_copy_button)` 서빙 확인
    - i18n parity 선재 2실패(ko 전용 settings.label.* · `split(".")` 오탐) 유지 — 본 변경 무관(ko 전용 label 은 기존 관례)
* 목적: `/cc-session id` 를 별도 실행하지 않고 hub 활성세션 카드에서 바로 세션 ID(sid)를 클립보드에 복사. 다른 세션 참조·연동(resume 등) 시 sid 확보 경로 단축. 사용자 제안 — 각 세션 행 X(닫기) 왼쪽에 복사 버튼.
* 구현 명세:
    - 행-클릭 위임은 `closest('button,a')` 로 버튼 제외 → 복사 버튼 클릭이 VSCode 포커스 행-클릭 미발동 (stopPropagation 불요)
    - 검증: `python3 -c ast.parse`(server.py OK) + locale JSON 파싱 OK + i18n parity 테스트 신규 키 양쪽 반영(참조 55→56, 누락 미포함). hub 재시작(pid=76512, uptime=1) 후 `/hub` 렌더에 `function copySid`·`class="copy-sid"`·`${approveBtn}${copyBtn}${killBtn}`·`세션 ID 복사`(ko) 서빙 확인
    - 기존 test 2건 실패(`ko 전용 settings.label.*` 키·`split(".")` 정규식 오탐)는 HEAD 부터 존재하는 선재 결함으로 본 변경 무관(orig·현재 동일 6 passed/2 failed)
* 목적: hub 활성세션 카드의 모델 신호등 배지(🟣opus/🔵sonnet/🟢haiku/🟠fable)·출처 배지(🆚VSCode/⌨️터미널)에 마우스 hover 시 `?`(help 커서)만 즉시 뜨고 툴팁 팝업은 ~1.5~2.5s 후에야 등장. 사용자 즉시 표시 요구.
* 구현 명세:
    - `escapeHtml` 유지(data-tip 속성 값 안전). 다크/라이트 무관 다크 배경 툴팁
    - 검증: `/hub` 렌더 HTML 에 `data-tip="모델...`·`.live-model[data-tip]:hover::after` 존재 + 배지 구 `title=` 잔존 0 확인. hub 재시작(pid 갱신, uptime 1)
    - 별개 이슈: 새 세션 model dot 첫 응답 지연(producer hook 타이밍)은 글로벌 SCAR ~/.claude Issue221 (본 이슈는 툴팁 지연만, 서로 무관)

## Issue274: "Save Point/세이브포인트" 용어 → "Update checkpoint/체크포인트" 전 프로젝트 통일 ✅
* 목적: 트리거·필드 용어를 "save point update/세이브포인트 업데이트"에서 "Update checkpoint/체크포인트 갱신"으로 통일. 전 프로젝트 Issue.md 필드·SCAR·설계문서·볼트 노트 일괄 반영.

## Issue273: hub 활성세션 카드에 메인 세션 모델 신호등 이모지 표시 ✅
* 목적: hub 활성세션 카드에서 각 세션의 메인 모델을 한눈에 식별. "opus 인 줄 알았는데 sonnet/haiku 였다" 오인 방지. 표시 전용(모델 변경은 VSCode 세션 외부 주입 경로 부재로 제외).
* depends: prj3#Issue217 (producer hook, ~/.claude commit <commit>)

## Issue267: hub 외부(tailnet) 링크 host 관리 체계 — advertise_host MagicDNS hostname 전환 + /etc/resolver 자기해석 수리 ✅
* 목적: hub 링크를 외부 기기(폰 등 tailnet)에 통지할 때 `host.local`(mDNS·LAN 한정) 해석 불가 문제의 prj1 정본 해결. raw IP 관리 대신 MagicDNS hostname 관리 체계 확립.

## Issue272: 브라우저 helper AppleScript 전면 복구 + browser_tab_reuse Chrome 계열 게이팅 ✅
* 목적: prj3#Issue166 이 "AppleScript 구동 = Chrome 크래시 원인"으로 판단하고 `fpm-browser-open.sh` 의 AppleScript 를 전면 제거했으나, Issue258 3차 분석(2026-07-11)이 오판임을 증명 — AppleScript 제거(6-26, <commit>) 이후에도 7-11 크래시 덤프 재발, 진짜 원인 = 외부 AX 클라이언트(KM 등)의 AX 트리 조회 × Chrome 149/macOS 26.6 자체 버그(AppleEvent 경로와 별개). 오판으로 잃은 기능(전면화 차단 `_bg_open` make new tab + Chromium 탭 재사용)을 복구하고, 재사용 옵션을 지원 브라우저(Chrome 계열)로 게이팅.
* 구현 명세:
    - `plugins/fpm-core/hooks/fpm-browser-open.sh`: <commit> 역방향 — `_bg_open` Chromium make new tab + Chromium reuse(windows×tabs 순회) 복구. 주석을 Issue166 오판 정정(Issue258 근거)으로 갱신
    - `services/hub/server.py` 설정 UI: `default_browser` 가 chrome/edge/safari 외(firefox·custom .app)일 때 `browser_tab_reuse` 토글 disable + 클릭 시 팝업(toast) "Chrome/Edge/Safari 에서만 활성화" — default_browser 변경 시 라이브 재판정
    - `data/hub_setting.yml`·`hub_setting_org.yml`: browser_tab_reuse 주석에 지원 브라우저 명시
    - 설계 문서: `_doc_arch/hub_setting.md`(browser_tab_reuse·browser_open 섹션 정정) + `_doc_base/hub-browser-tradeoffs.md`(타임라인·매트릭스 갱신)
    - 검증: `bash -n` + `ast.parse` + `/hub restart` + helper 실행 테스트(make new tab 동작·포커스 미탈취)
* depends: Issue258 (오판 정정 근거 — 3차 분석)

## Issue271: Issue269 후속 정합 — folder_arch.md stale parity 문구·template gitignore 규칙 동기 ✅
* 목적: Issue269(`_doc_base` gitignore origin 기반 전환) 반영 누락 2건 + template↔정책 표기 불일치 1건 교정. prj1 정본 내 folder_arch.md ↔ gitignore-policy.md 모순 해소.
* depends: Issue269
* 구현 명세:
    - folder_arch.md:64 말미 문구 교정: parity 유지 → "`_doc_base/` gitignore 는 origin 기반 (정본: [`gitignore-policy.md`](gitignore-policy.md))" (로컬파일 — _doc_arch 미추적)
    - gitignore-policy.md "# `_doc_base/` 예외" 섹션에 신규 템플릿 예외 명시: template 은 **안전 기본값**으로 선제 ignore(추후 origin 추가 시 유출 방지) — origin 없는 프로젝트가 `_doc_base` 실사용 시작 시 라인 제거로 불변식 회복. 미사용 동안은 "미사용 repo 무관" 조항 해당 (로컬파일)
    - data/template/gitignore `# Project` 블록 디렉토리 4항목 trailing slash 부여 (`_doc_work/`·`_doc_arch/`·`_doc_base/`·`.claude/`) — commit <commit>
    - 검증: 3자 grep 교차 확인 — parity 잔존은 폐기 이력 서술 2건뿐(정상), live 규칙 전부 origin 기반
    - 연동: prj3 `doc-base-design.md` 불변식 문구에 template 예외 동기 — ~/.claude Issue 별도 등록 (Issue269 위임 패턴 동일)

## Issue270: hub 설정창 연필(✏️) 기본값 SSOT를 hub_setting_org.yml 로 변경 ✅
* 목적: 설정창 연필(기본값 대비 변경) 판정이 `HUB_SETTING_DEFAULTS`·위젯 자연기본(toggle→False)에 의존하여, org 템플릿 그대로 설치해도 연필이 표시됨 (ex: `browser_tab_reuse: true` — DEFAULTS 미선언 → 추정 기본 false ≠ 현재 true). 사용자 결정: 시스템 기본값 = `hub_setting_org.yml` (키 삭제 시 복원 참조본 역할 겸함)
* 구현 명세:
    - `services/hub/server.py`: `HUB_SETTING_ORG_FILE` 상수 + `_load_hub_setting_org()` 로더 신설 (스키마 키만 파싱, `_cast_setting_value` 캐스팅, 파일 부재 시 log + 빈 dict fail-safe)
    - `_handle_get_settings` defaults 체인 변경: ① org.yml → ② `HUB_SETTING_DEFAULTS` → ③ 위젯 자연기본(select 첫 옵션/toggle False/number 0/그 외 "")
    - 검증: ast 구문 검사 통과 → /hub restart (hub-dev-rules, pid=59904 uptime=1) → `/api/settings` defaults 가 org 값(browser_tab_reuse=True, default_browser=chrome, browser_open=background) 반환 확인 — 현재값=기본값 → 연필 미표시

## Issue269: `_doc_base` gitignore 정책 origin 기반 전환 (arch↔base parity 폐기) ✅
* 목적: 사용자 신규 규칙 — **`_doc_base` gitignore ⟺ remote origin 존재**. origin 있으면 유출 방지 위해 ignore, origin 없으면 로컬 전용이라 미ignore(추적 허용). Issue264 의 arch↔base parity 규칙을 `_doc_base` 측에서 origin 기반으로 대체.
* depends: Issue264, Issue265
* 구현 명세: 레포별 gitignore 편집 + 추적 전환 개별 커밋. 사후 불변식(base-ignore ⟺ origin) 전 프로젝트 검증 — in-play repo 위반 0 (제외 3개는 폴더 부재로 무관).

## Issue268: hub 설정 — render_tab_mode 기본 탭 이동 + 탭 관련 2키 설명 강화 ✅
* 목적: 내부 탭(hub-internal) 진입 설정이 고급 탭에 숨어 있어 사용자가 기본 탭의 "탭 재사용"과 혼동. 두 키를 기본 탭에 나란히 배치하고 역할 구분이 명확하도록 설명 강화
* 구현 명세:
    - `services/hub/server.py` HUB_SETTING_SCHEMA 항목 이동·comment 갱신 → ast 구문 검사 통과 → /hub restart (hub-dev-rules)
    - 검증: GET `/api/settings?lang=ko` 에서 두 키 `tab == "basic"` + 신규 설명 반환 확인 ✅

## Issue266: hub 서버 /ob 엔드포인트 — 채팅 http 링크 → Obsidian 점프 브리지 ✅
* 목적: prj3 ob-* SCAR 완료 보고에 클릭 링크를 넣으려 했으나 VSCode 채팅 webview 가 `obsidian://` 커스텀 스킴·`file://`·상대경로 앵커를 모두 차단(7종 형식 실측 전부 불가). http 링크만 클릭 가능 확인 → hub 서버가 브리지 역할 수행.

## Issue265: `_doc_base/` 물리 스캐폴드 폴더 전 프로젝트 롤아웃 (.gitkeep) ✅
* 목적: 사용자 명시 지시 — `_doc_base/` 를 실제 폴더로 생성(.gitkeep). doc-base-design 의 "선택 폴더(강제 생성 금지)" 기본값을 **사용자가 명시적으로 override**(지시 우선순위). Issue264(gitignore parity)에 이어 물리 스캐폴드까지 확산.
* depends: Issue264
* 구현 명세: `mkdir -p <docroot>_doc_base && : > .gitkeep`. gitignore 무시 여부는 `git check-ignore` 로 판정 → 추적 가능만 개별 커밋. prj42 는 feature 브랜치이나 `_doc_base` ignore 라 미커밋(브랜치 영향 없음). 폴더는 빈 스캐폴드 — 원천자료(매뉴얼 소스·사양·배경조사) 발생 시 사용.

## Issue264: `_doc_base/` gitignore parity 누락 7 레포 보정 (prj3#Issue206 P4 후속) ✅
* 목적: prj3#Issue206 P4(gitignore parity 롤아웃)가 "parity 위반 0" 종결했으나, 이후 스캔 결과 `_doc_arch` 는 무시하는데 `_doc_base` 는 누락한 레포 7개 잔존. doc-base-design.md ".gitignore parity(arch↔base)" 강제 조항("반드시 함께 추가") 이행. **`_doc_base/` 폴더 자체는 선택(강제 생성 금지)이므로 폴더 생성 아님 — gitignore 라인만 보정.**
* depends: prj3#Issue206
* 구현 명세: 각 레포 `.gitignore` 의 `_doc_arch` 라인 직후에 동일 스타일 `_doc_base` 라인 삽입 (awk exact-match 삽입, prj25/26 주석 라인 오매치 없음) → 레포별 개별 커밋. 사후 parity 스캔 전 프로젝트 위반 0 확인. 실 `_doc_base/` 폴더는 현행 prj3·prj47 만 보유(선택 폴더 설계 정합), 나머지는 원천자료 발생 시 생성.

## Issue263: data/template `_doc_base/` gitignore parity 반영 ✅
* 목적: `_doc_base/` 를 신규 프로젝트가 자동 인지하도록 템플릿에 반영 (prj3#Issue206 P3).
* depends: prj3#Issue206, Issue262
* 구현 명세: 커밋 <commit>. 기존 12개 레포 parity 는 prj3#Issue206 P4 롤아웃 완료(본 이슈는 신규 프로젝트 예방)

## Issue262: folder_arch.md 정본에 `_doc_base/` 타입 승격 (문서 폴더 3분류) ✅
* 목적: 문서 폴더 3분류 관례 정본(prj1 `folder_arch.md`)에 `_doc_base/` 승격 (prj3#Issue206 P2).
* depends: prj3#Issue206
* 구현 명세: ⚠️ ___pm `_doc_arch/` gitignore(0 tracked) → folder_arch.md 는 **로컬 파일**, 디스크 편집으로 SSOT 유지(git 커밋 대상 외). 커밋 해시 없음

## Issue261: hub 설정 모달 UI 3종 — 키 라벨 좌측정렬 + 한국어 i18n + 탭 균일 높이 ✅
* 목적: 설정 모달(⚙️) UX 3건 개선 요청 — (1) 키 이름 우측정렬 → 좌측정렬, (2) 키 이름이 영문 원본(`default_browser`)뿐이라 한국어 다국어 미지원(prj42=m2slide 참고), (3) 탭(기본/세션관리/고급) 전환 시 행 수 차이로 모달 높이 점프.
* 구현 명세:
    - **(1) 좌측정렬**: `.set-row label.set-key` `text-align: right` → `left`.
    - **(2) 한국어 i18n**: `ko.json` 에 `settings.label.<key>` 24종 신설(렌더 브라우저·언어·탭 재사용 등). 라벨 렌더(`setRenderForm`)가 `ttf('settings.label.'+key,'')` 조회 — ko 카탈로그에만 등록 → **ko 뷰=한국어 / en 뷰=원본 키**(`_` 숨김 + 복붙 시 실제 키 보존 Issue208 유지). `__i18n_all` 양쪽 카탈로그 주입 + KO/EN 토글이 `setRenderForm` 재호출 → 즉시 전환. tooltip 은 `<키> — <설명>` 병기(한국어 라벨에서도 실제 yaml 키 확인 가능).
    - **(3) 균일 높이**: `.set-pane` `display:none/block` → `grid-area:1/1` + `visibility` 적층, `#set-modal .modal-body { display:grid; align-items:start }` → 숨은 탭도 높이 점유 → body 높이 = 가장 높은 탭(세션관리) 기준 고정 → 탭 전환 리사이즈 제거.
    - 검증: `python3 -c ast.parse` PY OK, ko.json JSON 유효, hub 재시작 pid=18778 uptime=1. 실반영은 브라우저 hub-shell 재로드 필요.

## Issue260: 외부 기기(아이폰 등)에서 hub 원격 접속 — source-IP allowlist 기기 단위 허용 ✅
* 목적: 같은 WiFi 의 임의 기기 유입을 차단하면서 특정 기기(아이폰)만 hub(9876) 접근 허용. IP 가변 기기는 Tailscale(기기 키 신원), 같은 LAN 직결은 기기 IP 를 `/32` 명시 허용.
* 구현 명세:
    - `data/hub_setting.yml`: `bind_host` 에 tailscale IP 추가, `allow_list` 에 tailnet CIDR + 아이폰 LAN `/32` (구체 값은 `_doc_arch` 참조)
    - `services/hub/server.py` `_ip_allowed`: 거부 시 `[allowlist] DENY — src=... IPs=... NETS=...` 로깅 추가 (source IP 로 경로 판별)
    - `_doc_arch/hub-remote-access.md`: 토폴로지·3경로·allowlist 상호작용 SSOT 신설 (채택 = Tailscale 단일 경로, 포트포워딩 폐기)
    - 후속(사용자 액션): 공유기 DHCP 예약(아이폰 MAC→고정 IP)으로 LAN IP 고정 — 미예약 시 IP 변경으로 접속 끊김·남 기기 IP 탈취 위험
    - 검증(사용자 액션): 아이폰 같은 WiFi 접속 확인, 셀룰러(외부) tailscale 접속 확인 — 실사용 확인은 사용자 몫

## Issue259: hub htm-doc 본문 좁게 중앙정렬 → 헤더와 폭 불일치 + 표 셀 잘림 ✅
* 목적: hub 내부 탭에 뜬 문서가 창 가운데 좁게 정렬되어 서버 full-bleed 헤더와 폭이 안 맞고, 표 셀 긴 텍스트가 좁은 본문을 넘쳐 잘림. 사용자 요구: 전체 폭 렌더 + 표 안 잘리게.
* 구현 명세:
    - `HUB_BODY_CSS` + `_normalize_hub_body_css` 신설(services/hub/server.py). `<body>` 직전 항상 주입 → 저작 head 스타일보다 뒤 → tie 이김 + `!important` override.
    - body `max-width:none`·전체 폭 padding, `table{width:100%}`, `th,td{word-break:break-word;overflow-wrap:anywhere}`, `pre,code,img{max-width:100%;overflow-x:auto}`.
    - htm-doc·view 두 serve 경로에 header 정규화와 동일 지점 배치. header 정규화(저작본 유무 분기)와 달리 **항상 주입**.
    - 검증: ast.parse OK → /hub restart(hub-dev-rules, uptime=1) → 실제 Issue953 문서에 `_normalize_hub_body_css` 적용 확인(injected=True, `</body>` 앞 위치).

## Issue257: hub 문서 헤더 닫기 버튼 standalone no-op — native close 차단 시 /hub funnel ✅
* 목적: standalone(top-level 직접 열람 — 외부 브라우저 새 탭·주소창 입력)에서 문서 헤더 닫기 버튼의 `window.close()` 가 브라우저 보안상 script 로 연 창만 닫혀 no-op(침묵 실패). 유저가 직접 연 탭·hub `open -a` 탭은 안 닫힘.

## Issue256: a모드 htm 저작 mermaid 미렌더 — `<pre><code>` wrapper 라 서버 normalizer 스킵 ✅
* 목적: `..show`/a모드 htm 문서의 mermaid 코드가 다이어그램으로 렌더되지 않고 소스 평문으로 노출됨 (실증: `hub_htm_20260706_172534_a_issue197-dash-reg.htm`). 문서 품질·가독성 저하.
* depends: Issue244

## Issue255: hub htm 문서 이미지 깨짐 — /htm-doc 상대 리소스 서빙 라우트 신설 (C방식) ✅
* 목적: hub 로 serve 되는 htm 문서의 로컬 이미지(상대경로 `<img src>`)가 404 로 깨지는 사각 제거

## Issue254: /notify 수신 시 dash 산출물 auto-register — dashboard hub 미노출 사각 제거 ✅
* 목적: dash 산출물은 htm 과 달리 자동 등록 경로가 전무(runner 는 `/notify` 만 POST, `/register-doc type=dash` 호출 주체 부재) → dash-registry 가 비면 dashboard 가 hub 에 영구 미노출. 2026-07-06 host-tar-copy dashboard 미노출로 실증 — 수동 `/hub-rescan` 이 유일 복구 경로였음
* 구현 명세:
    - `_auto_register_dash(cwd, abs_path)` helper 신설, `_handle_notify` 말미 호출. title 은 `_read_dash_file`(mtime 캐시) 로 회수
    - 검증(3종 통과): 신규 dash notify → registry 등록 ✅ / 재notify → registry 미재기록 ✅ / unregister(tombstone) 후 notify → 미부활 ✅

## Issue253: hub favicon·문서 hub-link 아이콘을 서버 아이콘(배지 이모지)으로 전환 ✅
* 목적: 배지 서버(Servers.md 이모지 등록: host=🐧, host=🖥️)의 hub 웹페이지 파비콘과 htm 문서 헤더 "허브로 가기" 버튼이 fPm 고정 아이콘이라 어느 서버의 hub 인지 탭·버튼에서 구분 불가 — 서버 아이콘으로 통일 (Issue242 헤더 이모지 배지의 확장)
* 구현 명세:
    - `_self_server_badge()` 이모지 존재 시: 이모지 `<text>` SVG 를 `Content-Type: image/svg+xml` 로 서빙 (브라우저는 확장자 아닌 Content-Type 기준 렌더). 미등록 서버는 종전 fpm-icon.png PNG 유지 (canonical)
    - 검증: host `curl /fpm-icon.png` → `image/svg+xml` + 🖥️ SVG 확인, hub 재시작(pid 20465) 완료
    - host 배포: `~/_git/fpm/services/hub/server.py` 동일 패치 직접 적용(백업 `server.py.bak-issue253`) + 재기동(pid 383428) → 🐧 SVG 서빙 확인. fpm 미러 정식 반영은 차기 fpm-sync 시 도달

## Issue249: hub-shell 내부 탭 자체 중복 — SSE 즉시 broadcast와 폴링 fallback의 view_url 형식 불일치 ✅
* 목적: Issue248(hub-shell↔VSCode 표면 이중) 해결 후에도 hub-shell **자체 탭바 안에서** 같은 문서가 2개로 뜨는 현상 재확인. 사용자 스크린샷 — "___pm — Issue248 재검…" 탭 2개, ".claude — Issue188 해결…" 탭 2개, 각각 동일 문서인데 별도 탭.
* depends: 없음 (Issue248 잔여 항목 — "hub-shell 내부에 동일 문서가 2개 뜨던 부분... 재발 시 별도 조사"의 후속)

## Issue251: playwright-mcp가 실제 Chrome 번들을 headless 점유 — 사용자 Chrome GUI 기동 차단 ✅
* 목적: prj1 Claude Code 세션의 playwright-mcp(`npm exec @playwright/mcp --isolated --headless`)가 `/Applications/Google Chrome.app` 본체 바이너리를 headless 로 실행하는 동안, macOS LaunchServices 가 Dock/Finder/`open -a` 의 Chrome 기동 요청을 새 프로세스 대신 기존 headless 인스턴스 활성화로 돌려버림 → headless 는 `--no-startup-window` 라 창이 없어 사용자 입장에서 "Chrome 이 안 켜짐". 2026-07-03 prj6(___common) 세션에서 진단·재현 확인 (증거: `_git/___common/_doc_work/z_htm/hub_htm_20260703_162637_a_chrome-blocked.htm`).

## Issue252: hub 문서 🔗 링크 복사 버튼 insecure context 침묵 실패 ✅
* 목적: `host.local:9876` 등 HTTP 비-localhost 접근 시 문서 헤더 🔗 "링크 복사" 버튼이 눌러도 무반응. 전에 작동하던 기능(127.0.0.1 접근)이 호스트만 바뀌면 죽음.
* 구현 명세:
    - `services/hub/server.py` `COPY_LINK_SHIM`: 기존 `.copy-link` 버튼 발견 시 스킵 대신 **onclick 재바인딩**(inline 속성 제거 + 가드된 핸들러 장착) — 과거 생성된 모든 .htm 도 서빙 시점 자동 교정.
    - 복사 로직 3단 폴백: `navigator.clipboard && window.isSecureContext` 가드 → hidden textarea + `document.execCommand('copy')` → `window.prompt` 최종 폴백.
    - dash 헤더(`_serve_dash_inline` `copy_onclick`)에도 동일 가드 적용.
    - 연계: hook 템플릿 자체 교정은 prj3#Issue190 (canonical 헤더 구코드 → 가드 버전 교체).

## Issue250: hub-internal 모드 VSCode Simple Browser fallback — Chrome 탭 freeze 시 렌더 중복 표시 + 포커스 탈취 ✅
* 목적: hub-shell(Chrome)에 렌더가 정상 표시된 뒤에도 VSCode 가 전면화되며 같은 문서가 Simple Browser 로 한 번 더 뜸. 다른 프로젝트 입력 중 포커스가 탈취되어 작업 연속성 파괴.
* depends: 없음 (Issue248 표면 단일화의 잔여 — freeze 된 hub-shell 을 "죽음"으로 오판하는 케이스)

## Issue248: hub 렌더 표면 이중 — hub-shell 내부 탭 + VSCode Simple Browser 동시 표시 ✅
* 목적: prj3#Issue187(외부 브라우저 file:// 중복 open) 수정 후에도, `render_tab_mode: hub-internal` + `render_target: hub` 조합에서 hub-shell 내부 탭과 VSCode Simple Browser 패널이 동시에 뜨는 잔여 중복 발생. 사용자 스크린샷(hub-shell 탭바에 동일 문서 2개 + 별도 VSCode 창 Simple Browser 패널 동시 표시).
* depends: 없음 (prj3#Issue180 잔여 각주 — "server.py `_hub_holder_alive` 판정으로 표면 단일화 필요. prj1 세션에서 처리" — 그 각주의 실제 이행)
* 구현 명세:
    - `services/hub/server.py`: 모듈 레벨 `_any_hub_shell_alive(ttl=30)` 헬퍼 추가 — `hub_lease` 전체(ip 무관)를 스캔해 `hub_lease_ttl` 이내 heartbeat 존재 여부로 "지금 hub-shell 이 살아있는가" 판정 (localhost curl 호출자는 브라우저의 source-ip 를 모르므로 ip-특정 `_hub_holder_alive` 대신 전역 스캔 버전 신설).
    - `_handle_open_simple_browser`: 화이트리스트 검증 이전에 `render_tab_mode == hub-internal` AND `_any_hub_shell_alive()` 면 VSCode open 을 **skip**(`{"status":"skipped-hub-shell-alive"}` 응답) — register-doc 의 자동 hub-shell 표시가 이미 유일 표면이 되므로 이중 표시 제거. hub-shell 이 안 살아있거나 hub-internal 모드가 아니면 기존 동작(VSCode open) 유지 — 회귀 없음.
    - 재시작 완료: `/hub restart` 실행, healthz uptime=1·pid=10620=listener 일치 확인 (hub-dev-rules.md 준수).
    - 검증(2026-07-03): `..show` 재실행 → `/open-simple-browser` 응답 `{"status":"skipped-hub-shell-alive"}` 확인(VSCode open 스킵 정상 동작). 사용자 `/issue-closer` 호출로 종결 승인.

## Issue247: hub-shell 탭바 자동 숨김 — 탭 1개(home) 이하일 때 ✅
* 목적: hub-shell(`/hub-shell`) 상단 탭바가 열린 문서 탭 유무와 무관하게 항상 표시되어, home 탭 하나뿐일 때도 불필요한 UI 공간을 차지함. 사용자 스크린샷 지적 — "탭이 없을때는 자동으로 탭부분 숨기기".
* 구현 명세:
    - `render()` 탭 DOM 생성 루프 직후 `bar.style.display = tabs.length > 1 ? "flex" : "none"` 추가. 탭 2개 이상(문서 탭 열림)일 때만 `#tabbar` 노출, home 단독이면 숨김.
    - CSS 초기값(`#tabbar{display:flex}`)은 유지 — 인라인 스크립트가 body 파싱 완료 전 동기 실행되어 초기 렌더 시 FOUC 없이 즉시 반영됨.
    - hub 서버 launchd restart(`/hub restart`) 후 healthz uptime 한자릿수로 반영 확인.

## Issue246: cdfv 에 -n(새 창) 옵션 추가 ✅
* 목적: `cdfv -n 15 25` 처럼 입력 시 지정 프로젝트들을 **기존 창과 분리된 새 창(탭 그룹)에 함께** 열기. 기존 `cdfv 15 25` 는 창 재사용/탭 동작이라 지정 프로젝트 그룹 분리 불가.
* 구현 명세:
    - `cdfv` 첫 인자가 `-n`/`--new-window` 면 flag set + shift 후 `_cdf_base` 위임. `cdfvn` 도 numeric 모드에서 `-n` 통과 보정.
    - **1차(<commit>) `code -n` 만**: 사용자 환경 macOS `AppleWindowTabbingMode=always` 라 `code -n` 새 창이 기존 창의 **탭으로 병합** → 옵션 없는 것과 시각적 동일(실패). 스크린샷으로 진단.
    - **2차(<commit>) applescript detach 매 target**: `code -n` 로 연 뒤 `sleep 0.8` → applescript `System Events` Window 메뉴 **"Move Tab to New Window"** 클릭(enabled 가드) → front 탭 독립 창 분리. E2E `cdfv -n 15 25` → Code 창 7→9(+2). 단 **각 프로젝트가 완전 별도 창**으로 흩어짐.
    - **3차(<commit>) detach 최초 1회만**: 사용자 피드백 "두개 같이, applescript 처음 한번만". `nw_detached` 가드로 **첫 프로젝트만** 별도 창(W1)으로 분리, 이후 프로젝트는 frontmost 병합에 맡겨 지정 그룹으로 모이도록 의도. 현 상태 사용자 만족.
    - 전제/한계: applescript System Events accessibility 권한 필요(부여됨). 미부여 시 detach 무동작 — fail-safe. 이미 열린 동일 폴더·기존 창 배치까지 결정론 보장 안 함(사용자 "이미 열린 창 걱정 불요" 합의).

## Issue245: hub mermaid 다이어그램 테마가 페이지 배경과 불일치 (밝은 페이지에 어두운 다이어그램) ✅
* 목적: Issue244 서버 mermaid 런타임 정규화 후속. 다이어그램은 렌더되나 **밝은 hub 페이지에 어두운 테마 다이어그램**이 얹혀 시각 부조화. 사용자 스크린샷 진단.
* 구현 명세:
    - `services/hub/server.py` `MERMAID_RUNTIME`: `matchMedia('(prefers-color-scheme: dark)')` → **실제 페이지 배경 luminance 감지**(`getComputedStyle(document.body).backgroundColor` → `0.299R+0.587G+0.114B < 128` 이면 dark, 투명 배경은 light 간주)로 교체. 페이지가 밝으면 `neutral`, 어두우면 `dark` → 페이지와 항상 일치.
    - 검증(Playwright): body bg `rgb(255,255,255)`·lum 255 → theme `neutral` 선택, node fill `rgb(238,238,238)`(밝은 회색). 스크린샷으로 밝은 다이어그램(회색 배경) 확인. bomb 없음.

## Issue244: hub mermaid 다이어그램 간헐 "Syntax error" bomb — 런타임 drift 근절 ✅
* 목적: hub 문서(a모드 렌더·b모드 `..ask` iframe 임베드)의 mermaid 다이어그램이 "Syntax error in text (mermaid version 11.16.0)" bomb 으로 **간헐** 깨지는 현상 근절. 사용자 보고 "요즘 들어 자주 발생".
* 구현 명세:
    - `services/hub/server.py`: `_normalize_mermaid_runtime(body)` 신설 — `class="mermaid"` 블록이 있을 때만 (1) 페이지 저작 mermaid `<script>`(esm/umd·버전 불문) 정규식 제거 (2) pinned UMD `mermaid@11/dist/mermaid.min.js`(동기) + `startOnLoad:false` + 명시적 `mermaid.run()` 주입. `_handle_htm_doc`·`/view` 두 serve 경로 모두 적용(shim 주입 직전). 서버가 mermaid 런타임 **단일 권위** → 페이지가 뭘 썼든 결정적·race-free 렌더.
    - **검증(grounded)**: hub 재시작(pid 17874) 후 Playwright 로 실제 렌더 확인 — served HTML: esm 0개·UMD@11+run() 주입 확인. iframe 임베드 시나리오 3회 리로드 반복: 양쪽 블록 SVG 렌더·**bomb 0회**. @10 파일 → @11 정규화 확인. 비-mermaid 페이지 미주입(회귀 없음). Mode A(nptir) 파일은 소스 invalid 라 여전히 bomb — 서버 범위 밖(정직 고지).

## Issue243: host 머신에 llmwiki(llm-wiki-compiler) 전역 설치 ✅
* 목적: host 에 설치·검증 완료한 llm-wiki-compiler(CLI `llmwiki`)를 host 머신에도 전역 설치하여 host 세션·prj 에서도 마크다운 → 인용 추적 위키 컴파일 사용. graphify(코드 그래프)와 병용하는 문서 위키 하니스.

## Issue242: hub 헤더 서버별 이모지 + 그라디언트 (Servers.md Emoji 컬럼) ✅
* 목적: 원격 서버(host)와 로컬(host)의 hub 페이지가 동일한 fPm 헤더라 어느 서버 hub 인지 시각 구분 불가 → host(5개 프로젝트)를 host(37개)로 착각하는 혼동 발생. 서버별 이모지·헤더 색으로 즉시 식별.
* 구현 명세:
    - `_parse_servers_md`: 맨 끝 optional `emoji` 셀 캡처 (cells[8]). check 는 여전히 index7 → allowlist(Issue141) 무손상
    - `_self_server_badge()` 신설: `socket.gethostname()` → Servers.md Name 매치 → (emoji, hue, name)
    - `_emoji_hue()` 신설: 큐레이션 맵(🐧→25 Ubuntu주황 등) + codepoint 해시 fallback
    - `HUB_HTML`: `{HUB_LOGO}`·`{HUB_HEADER_GRAD}` placeholder → `_handle_hub` 에서 치환
    - 검증: host 로컬(이모지 공란)=fPm+파랑보라 유지 확인 / host=🐧 hue25 그라디언트, f=☁️ hue205 시뮬 확인 / allowlist·settings 테스트 22 pass. ⚠️ host 실제 렌더는 host 머신 코드+Servers.md 갱신 후 적용(원격 배포 별도).

## Issue241: check.sh hook 이중 등록 가드 추가 ✅
* 목적: fpm hook 은 두 경로로 등록됨 — (a) `~/.claude/settings.json` 수동 블록(원작자 환경), (b) fpm-core 플러그인 `hooks/hooks.json`(배포 표준). Claude Code 가 두 소스를 dedup 없이 합집합 머지 → 둘 다 활성이면 동일 hook 이 한 이벤트에 2회 실행(알림 중복·HTML 2회 렌더). 기존 `check.sh` 는 hook 을 전혀 검증하지 않아 사용자가 실수로 양쪽 활성해도 무검출.
* 구현 명세:
    - `sh/check.sh` 에 `── 10b. hook 이중 등록 가드 ──` 섹션 신설 (flat_file drift 앞).
    - `~/.claude/settings.json` 의 `.claude/hooks/fpm-` 매칭 수 + `installed_plugins.json` 의 `"fpm-core@` 존재를 직독(claude CLI·repo 무관).
    - 둘 다 활성 → FAIL("한쪽만 유지, 플러그인 단일화 권장"). 한쪽만 → PASS(단일 등록). 둘 다 없음 → WARN(hook 비활성).
    - 검증: 작가 환경(수동 9개 + 플러그인 미설치) → PASS "단일 등록" 정상 판정 확인.

## Issue240: SCAR 설치/제거/업데이트 통합 SSOT (data/scar-manifest.yml + .md) — 원격 플랫파일 삭제 누락 버그 수정 ✅
* 목적: 다른 서버에 SCAR 설치/제거/업데이트 시 소스에서 rename·삭제된 파일이 원격 `~/.claude/` 에 잔존하는 버그("파일을 지우지 못하는 현상") 수정 + install.sh·update.sh·remove.sh(to-be)·remote.sh(to-be) 가 참조할 단일 SSOT 정립
* 구현 명세:
    - `data/scar-manifest.yml` 신설 — 통합 SSOT(셸 아티팩트 + 플러그인 + 플랫파일 페이로드 + delete-set + protect + 소비 계약)
    - `data/scar-manifest.md` 신설 — 설계 문서(버그 근원·2경로·소비 계약·생성 절차)
    - `sh/gen-install-manifest.sh` 신설 — yml → `data/install_manifest.sh` 생성기(python3, yq 무의존, --check drift 가드). 기존 FPM_* 값 byte-호환 검증 완료(변수값 100% 동일) → install/check/uninstall/update/publish 무손상
    - `data/install_manifest.sh` → yml 파생물 전환(AUTO-GENERATED 헤더)
    - `data/claude_forNewServer.md` rsync `--delete` + `--exclude`(protect) 추가 — orphan 잔존 버그 직접 해결
    - 검증: `bash sh/check.sh` 매니페스트 소비 PASS(SCAR drift 12/3/1 일치), `--check` drift 없음. remote.sh/remove.sh 는 to-be(범위 외, md 에 소비 계약 명문화)

## Issue239: [Track3] prj1 마스터 _doc_arch 문서 정리 (hub/board 인덱스·분류 + 주제 마스터 SSOT 명문화 + prj1↔prj3 매핑 박제 + projects-relations prj3 노드) ✅
* 목적: prj3 Issue177(prj1-prj3 SSOT 경계 정식화)의 위임 트랙. prj1 마스터 설계 문서의 정본/파생/이력 경계를 인덱스로 박제하여 양쪽 중복 정본·추적 불가 상태를 차단
* depends: prj3#Issue177

## Issue225: [강화 Phase0·T2] 디스커버리 등재 (awesome-claude-code + 마켓 디렉토리) ✅
* depends: Issue224

## Issue226: [강화 Phase1·T3] README·랜딩 보강 (prj7 미러) ✅
* depends: Issue224
* 구현 명세:
    - quickstart(원라인 최상단)·기능 표·데모 GIF·아키텍처 다이어그램 추가 / 검증: prj7 README 렌더 + 원라인 명령 정확성

## Issue233: [강화 Phase2·T6] Issue.md ↔ GitHub Issues 양방향 동기(옵트인 브리지) ✅
* 목적: Issue.md(로컬 SSOT) 와 GitHub Issues 를 옵트인 브리지로 양방향 동기. 1인 우선 기본값(브리지 off) 유지하되, 팀·외부 기여 시 GH Issues 로 노출. 강화 로드맵 Phase 2 T6.
* 구현 명세:
    - ✅ design 확정(권장 기본값): 양방향(local-wins)·인라인 `* gh:#M` 매핑·섹션→label/🚧✅→state·수동 `/gh-sync` 트리거
    - ✅ MVP 구현(2026-06-28): `data/gh-sync.yml`(토글 기본 off) + `scripts/gh-sync/{parse_issuemd,map,engine}.py` + `scripts/gh-sync.sh` + `.claude/commands/gh-sync.md`
    - ✅ 검증: 파서 217이슈 정확 파싱, push dry-run 7건(label/state 정확·📜참고 제외), pull read-only, writeback `* gh:#M` 삽입/갱신 데이터 안전(이슈수 STABLE)
    - ✅ dry-run E2E 재검증(2026-06-28, /dev): 임시 enabled:true+repo 로 push dry-run → active 6건 CREATE payload(title/label/state 정확), enabled-gate→payload 전 경로 무결, 복원 후 enabled:false 확인. gh API 미접촉(외부 쓰기 0)
    - ✅ 실 repo push --apply E2E(2026-06-29, prj7 `Finfra/fpm` 활성 remote): fpm-sync forward 출고(동기 상태) → prj7 `data/gh-sync.yml` enabled:true+repo 임시 → dry-run 3 CREATE(label/state 정확) → `push --apply` → 실 `gh issue create` 3건 성공(#1 Issue225·#2 Issue233·#3 Issue226) → writeback `* gh: #N` 삽입 → status 매핑됨 3/미매핑 0 라운드트립 검증 → enabled:false 복원. 매핑 ___pm SSOT 전파. gh 이슈: https://github.com/Finfra/fpm/issues
    - 비고: prj7 가드 skip(`fpm-guard.sh` 공개 미러 제외) — push 대상이 이미 공개 미러 콘텐츠라 무해. ___pm 직접 push 는 원격 부재로 불가 → 공개 repo 소속 prj7 경유가 정상 경로

## Issue227: [강화 Phase1·T4] cdf frecency / 퍼지 점프 옵션 ✅
* 목적: 공개 후 사용성. `cdf` 번호 SSOT 유지 + 인자가 번호 아닐 때 최근 방문·fuzzy 매칭(`fzf` 가용 시) 보조 점프. 번호 결정론성은 약화 금지 — fuzzy 는 fallback 레이어 한정.
* 구현 명세:
    - `sh/fpm_function.sh` 단일 파일. frecency 스토어 `projects/.frecency`(`id|freq|epoch`, projects/ 전체 gitignore) + `_cdf_resolve_smart`(fzf 가용+tty → fuzzy picker / 미가용·no-match → 기존 `_cdfn_resolve` 이름·한글 substring 위임)
    - `_cdf_base` case 분기: 첫 토큰 비번호 → smart resolve, 번호/범위/`list`/`---` → 기존 경로(결정론 100% 보존). `cdf()` 가 방문 id frecency bump
    - zsh 함정 2건 처리: (1) `$path` 는 `$PATH` tie 특수배열 → 변수명 `_p` 회피, (2) 외부명령 alias 오파싱 → `command` prefix 통일
    - 검증: zsh -f·bash 양쪽 통과 — 번호 `11`·범위 `11-16`·subfolder `1 sh`·`1 --- ls` 회귀 없음 + 비번호 `cdf fBanner` fallback 라우팅 동작
    - 잔여(범위 외): 라이브 셸 적용은 새 셸/`source` 재실행 / fpm 공개 미러 동기화는 `fpm-sync` 별도

## Issue237: Playwright MCP Chrome 반복 크래시 — macOS 접근성 API 충돌 ✅
* 목적: Playwright MCP(`@playwright/mcp@latest`, `~/.claude.json` 글로벌)가 띄운 Chrome(149.0.7827.200)이 macOS 26.6에서 반복 크래시. `EXC_BREAKPOINT(SIGTRAP)` — Chrome 안전 단언 실패. 스택 전체가 macOS 접근성 경로(`NSAccessibilityEntryPointValueForAttributeWithParameter` → `CopyParameterizedAttributeValue` → `CoreAccessibility` → `_AXMIGCopyParameterizedAttributeValue`). 부모=`node`, 책임=VSCode → 자동화 브라우저 확정.
* 구현 명세:
    - **채택안**: Playwright MCP 를 `--isolated --headless` 로 실행 → 네이티브 윈도우 없음 → macOS AX 경로 미진입 → 크래시 차단. `browser_snapshot`(CDP 기반)은 headless 에서도 동작.
    - 적용: `~/.claude.json` `mcpServers.playwright.args` 에 `--headless`(+ `--isolated`) 추가
    - **트레이드오프**: 수동 로그인 필요 흐름(naver-blog, linkedin)은 headless 불가 → 해당 스킬은 영속 프로필 + 비-headless 별도 실행 필요. 본 이슈는 기본값만 headless 전환.
    - 대안(미채택): ① Chrome 런치 플래그 `--disable-renderer-accessibility`(snapshot 손상 위험) ② Chrome 채널 다운그레이드(유지보수 부담)
    - 검증: 설정 적용 후 `browser_navigate` + `browser_snapshot` 1회 라운드트립 크래시 없음 확인

## Issue228: [강화 Phase1·T5] 모바일·원격 hub 접속 (QR + 반응형) ✅
* 목적: 공개 후 사용성. hub `:9876` 에 모바일 반응형 뷰 + 접속 QR 생성 엔드포인트. `host.local` 원격 표시 자산 재활용. 네트워크 한정 보안 가드 필수.
* 구현 명세:
    - ✅ `/qr` 반응형 페이지 + `/assets/qrcode.min.js`(vendored qrcode-generator MIT, 오프라인) + LAN URL 자동탐지(advertise_host 우선) + bind 127.0.0.1 경고
    - ✅ 검증(2026-06-29 재확인): healthz LIVE(pid 81927) → `/qr` 200(advertise `http://<lan-ip>:9876`·QR DOM·경고) → `/assets/qrcode.min.js` 200(20KB). bind_host LAN IP 포함 → 동일 Wi-Fi 휴대폰 접속 가능 상태

## Issue236: fpm-core 발행(소스→마켓)·머신 갱신 자동화 — update.sh + install.sh skip 갭 수정
* 목적: fpm-core SCAR 갱신 경로가 수동·갭 다수. (1) fpm `plugins/fpm-core` 소스 → `f-claude-plugins`(prj20) 마켓 발행이 수동 rsync+버전 bump+push, (2) `install.sh` 재실행은 이미 설치된 플러그인을 skip 하여 SCAR 업데이트 불가(설계 갭), (3) 머신 갱신은 `claude plugin marketplace update` + `claude plugin update` 2단계 수동. host 진단 중 fpm-core 가 0.3.1(마켓 동결) ↔ 0.7.11(소스) 로 크게 벌어진 채 방치됐음이 드러남(2026-06-28 발행으로 해소).
* 구현 명세:
    - **발행 자동화**: `fpm plugins/fpm-core` → `f-claude-plugins/fpm-core` rsync(--delete) + `plugin.json`↔`marketplace.json` 버전 동기 bump + 무관 변경 제외 staging + commit/push 를 단일 스크립트(ex: `sh/publish-scar.sh`)로. `claude plugin validate` 게이트 포함
    - **install.sh skip 갭**: `install_scar()` 가 이미 설치 시 "skip" 대신 `claude plugin update` 호출하도록 수정(install=update 멱등 통합) — 옵션 A
    - **update.sh 신설(옵션 B)**: ① 셸 `git -C $FPM_BASE pull`(+재source 안내) ② `claude plugin marketplace update` + `claude plugin update fpm-core@f-claude-plugins` 오케스트레이션. 셸·SCAR 이원 경로를 한 진입점으로
    - **버전 SSOT**: fpm `VERSION`/`plugin.json` ↔ 마켓 `marketplace.json` fpm-core entry 3곳 버전 일치 강제(release-check 확장 후보)
    - **부수 정리**: f-claude-plugins origin URL 대소문자 교정(`finfra`→`Finfra`, push redirect 경고 제거)
    - 검증: 클린 머신에서 install → 소스 변경 → publish → update 1회 라운드트립, 버전 3곳 일치 확인

## Issue224: [강화 Phase0·T1] 원라인 설치(curl|sh) + 셀프업데이트 fpm 셸 커맨드 ✅
* 목적: fPm 공개 blocker. 현재 `sh/install.sh` 는 repo 를 먼저 클론해야 실행 가능하고, 설치본을 갱신하는 셀프업데이트 커맨드가 없다. 경쟁자(ccpi `install/update/upgrade`) 대비 가장 뼈아픈 격차. 원격 `curl | sh` 원라인 진입점 + `fpm` 셸 커맨드를 신설하여 "설치·갱신 가능" 상태로 만든다.
* 구현 명세:
    - `sh/bootstrap.sh` 신설: `curl -fsSL <raw>/sh/bootstrap.sh | sh` 진입점. repo `git clone`(또는 tarball) → 표준 위치 배치 → 기존 `sh/install.sh` 위임(멱등)
    - `fpm` 셸 함수(`sh/fpm_function.sh`): `fpm update`(git pull + install.sh 재실행 + `claude plugin update`), `fpm upgrade`(VERSION 비교 후 최신 태그 체크아웃), `fpm version`, `fpm uninstall`(→ uninstall.sh)
    - clean-check 가드: 로컬 미커밋 변경 있으면 셀프업데이트 중단·경고
    - 설치 표준 위치 결정(`~/_git/__all/fpm` vs `~/.fpm`) — 기존 prj7 미러 경로와 정합
    - 검증: 클린 머신(임시 HOME)에서 원라인 → 셸·SCAR 설치 → `fpm update` 멱등 재실행

## Issue235: [강화 Phase2·T7] SCAR 크로스 툴 이식(Cursor·Codex·Gemini export) ✅
* 목적: ___pm 의 SCAR(Skill/Command/Agent/Rule) 자산을 Cursor·Codex·Gemini 등 타 AI 코딩 툴 포맷으로 export. fPm 생태계 확장·락인 완화. 강화 로드맵 Phase 2 T7(최장기).
* depends: Issue233
* 구현 명세:
    - ✅ design 확정: 단방향(export-only), frontmatter 추출 공통 레이어 + 포맷별 emitter, 라운드트립 불요
    - ✅ MVP 구현(2026-06-28): `scripts/scar-export/{scan,emit}.py` + `scripts/scar-export.sh` + `.claude/commands/scar-export.md`. plan: `_doc_work/plan/scar-crosstool-export_plan.md`
    - ✅ 검증: scan 16항목(command12·skill3·agent1), export all → AGENTS.md·GEMINI.md·16 .cursor/rules/*.mdc, .mdc frontmatter YAML 유효, 이름충돌 kind접미사 분리(데이터 손실 0)

## Issue234: board 이슈 대시보드 카드 배치 최적화 (좁은 카드 단일 컬럼 낭비) ✅
* 목적: board(`/s/<hash>/issue-status`) 대시보드에서 좁은 status 카드(활성 이슈·진행중 목록·Issue.md 수정)가 full-width 위젯 사이에 끼어 각자 한 행을 독점, 옆 2칸이 빈공간으로 낭비되는 단일 컬럼 문제 해소.
* 구현 명세:
    - `services/hub/server.py` `.dash-grid` 에 `grid-auto-flow: row dense` (빈칸 backfill) + `align-items: start` (행 내 카드 높이 강제 stretch 방지) 추가.
    - 위젯 데이터(`dash.yaml`)·렌더 로직 무변경 → 의미 순서·full 위젯 `grid-column: 1 / -1` 호환.
    - 검증: `ast.parse` SYNTAX_OK → hub 재시작 (old pid 9876 점유 → 강제 kill 후 pid 90089 uptime 3 = 새 코드 반영).

## Issue232: hub Simple Browser 문서가 생성 프로젝트 아닌 frontmost VSCode 창에 표시 (완료: 2026-06-28, Hash: <commit>)
* 목적: hub 렌더 문서가 자기 owner 프로젝트 창에 뜨도록 보장 (다른 프로젝트 작업 후 복귀 시 엉뚱한 창에 표시되는 문제 차단)
* 구현 명세:
    - registry 엔트리의 `cwd`(owner 프로젝트 경로)를 조회하여, 등록 프로젝트면 owner 폴더를 먼저 `open -a "Visual Studio Code" <cwd>` 로 전면화 후 0.4s sleep → URI 호출 (open-session 동일 패턴)
    - cwd 미등록·부재 시 기존 동작(URI 단독 호출) fallback
    - 검증: server.log 에 `owner_cwd=/Users/user/_git/___pm` 기록 확인, hub 서버 재기동(pid 24242) 후 새 코드 로드
    - plugin 미러(`plugins/fpm-core/services/hub/server.py`)는 핸들러 자체가 없는 stale 스냅샷 → 본 이슈 범위 밖(별도 릴리스 사안)

## Issue230: Mode C dashboard 위젯 데이터 미렌더 (progress 0%·table/text/checklist 공백) (완료: 2026-06-28, Hash: <commit>)
* 목적: hub SPA dashboard(`/s/<hash>/issue-status` 등)에서 progress 바가 0% 로만 나오고 table·text·checklist 위젯이 빈 칸으로 표시됨. 이슈 번호(graph DAG 노드)만 보이고 나머지 데이터가 전부 누락되는 회귀.
* 구현 명세:
    - `renderWidget` 상단에 `_pval` 헬퍼 추가 (JSON 문자열 → 객체/배열, 스칼라는 그대로).
    - progress: `value`·`max` `parseFloat` 강제 → `max>0` 분수, 아니면 `value` 퍼센트. 하위호환 `value:100` no-max → 100%.
    - table: native `rows` 비면 `_pval` 주입 + array-of-arrays 첫 행 헤더 승격.
    - checklist: native `items` 비면 `_pval` 주입.
    - text: 스칼라 `value`(live) 가 정적 `content` 보다 우선.

## Issue229: dashboard /s/{sid} 뷰어 "대기 중..." — 디스크 dashboard sessions 미등록 ✅
* 목적: `..board` 로 띄운 dashboard 가 SSE 연결됐는데도 위젯이 안 뜨고 "대기 중..." 만 표시되는 문제 해결. 사용자 스크린샷 보고.
* 구현 명세:
    - `services/hub/server.py` `_handle_session_get` data 분기: `sessions` 미스 시 신설 `_dash_entry_for_sid(cwd_h, cwd, sid)` 로 fallback — DASH_REGISTRY 에서 (cwd_h, sid) 매칭 dash 파일을 풀 파싱(PyYAML, fallback `_parse_dash_yaml`)해 `content_type=dashboard` 합성 entry 반환. 기존 `_dash_runner_state` stale 보정과 호환.
    - 검증: live 서버(pid 77689) `_handle_session_get` data 분기에 `_dash_entry_for_sid` fallback wired 확인(5894·5981행). `/s/{cwd_h}/{sid}/data` 토큰 동반 시 합성 dashboard entry 반환 — 404 미발견 경로 제거.

## Issue223: hub-shell 탭 빠른 닫기 시 Chrome 렌더러 크래시 — iframe 재네비 디바운스 ✅
* 목적: 여러 탭이 떠 있을 때 탭을 빠르게 연속으로 닫으면 이벤트가 꼬여 Chrome 이 죽는 문제 해결. hub-shell 안전성 강화. 사용자 보고.
* 구현 명세:
    - `services/hub/server.py` `HUB_SHELL_HTML` 에 `navTo(url)` 추가 — 60ms 윈도로 버스트 네비를 코얼레싱(최종 목표 1회만 `view.src` 할당) + 멱등 가드(목표 embed URL 이 현재 `view.src` 와 절대 URL 기준 동일하면 skip → EventSource churn 제거). `activate` 가 `view.src` 직접 할당 대신 `navTo` 경유. 탭바 `render()` 는 동기 유지(시각 지연 없음).
    - 검증: `ast.parse` 구문검사 통과 → `/hub restart`(hub-dev-rules) → healthz pid=80569·listener 일치, 서빙 `/hub-shell` 에 `navTo` ×4 확인(새 코드 live). 브라우저 크래시 자체는 재현 테스트 불가 — 로직상 버스트 네비 제거로 근본 차단(미재현 검증).

## Issue222: hub-shell 기존 탭 포커스 미이동 버그 수정 + /hub restart 자동화(rule) ✅
* 목적: (1) hub-shell 내부 탭에서 이미 열린 문서 카드(↗)를 재클릭해도 포커스가 이동하지 않는 버그 수정. (2) `/hub restart` 가 pidfile stale 시 silently no-op 하던 문제 해결로 "코드 수정 → 재시작 반영"을 신뢰성 있게 자동화. (3) hub 서버 코드 편집 시 자동 재시작을 hook 없이 rule 로 강제. 사용자 스크린샷 보고.
* 구현 명세:
    - `services/hub/server.py` `addTab(d, focus)`: focus 플래그 추가. dedup 분기에서 `focus && ex.id !== activeId` 면 `activate(ex.id)`(기존 탭 전환), 아니면 `render()`(폴·이미 활성 → reload 없음). 호출부 3곳 — `tab-open` SSE=true(신규 렌더), `fpm-open-tab` postMessage=true(카드 클릭), `pollDocs`=false(백그라운드 폴 미탈취).
    - `.claude/commands/hub.md`: `restart`·`stop` 블록을 pidfile ∪ 포트 9876 listener(lsof) 합집합 kill 로 변경 + 포트 비움 대기 + 기동 후 pidfile 자가 보정 + uptime 검증. 가드 주석 추가.
    - `.claude/rules/hub-dev-rules.md`(신규): `services/hub/**` 런타임 소스 편집한 응답에서 구문검사 → `/hub restart` → uptime/pidfile 검증을 자동 강제하는 rule. 한계(Claude 편집만 커버) 명시.
    - 검증: py 문법 OK. 실제 재시작 2회 검증(85567→27081, uptime 한 자릿수, pidfile==listener). 라이브 서버에 addTab 수정 반영.
    - 비고: 본 커밋 <commit> 은 동일 working tree 에 있던 Issue219/220/221(funnel·HUB_LINK_SHIM·transcript) 미커밋 작업도 함께 포함("모두 커밋" 사용자 결정).

## Issue221: 채팅 fallback URL 외부 클릭 시 VSCode·브라우저 이중 노출 — funnel 우회 ✅
* 목적: 외부 브라우저(Chrome)에서 채팅 fallback URL `http://host.local:9876/htm-doc?path=…` 클릭 시, funnel(Issue209/213)이 살아있는 hub-shell(=VSCode 패널, Issue170)에 tab-open SSE push + 클릭한 Chrome 엔 "기존 hub 창에 열림" 확인 페이지를 serve → 같은 문서가 VSCode·외부 브라우저 양쪽에 이중 노출. 사용자 보고.
* 구현 명세:
    - `_handle_htm_doc` (`services/hub/server.py`): non-embed(`_shell` 마커·Sec-Fetch-Dest 없음) + hub-internal 일 때의 funnel 블록 제거 → 클릭한 그 브라우저에 standalone serve(fall-through). (구 동작: holder alive → tab-open SSE + `HUB_OPENED_HTML` / else 302 `/hub-shell`)
    - VSCode 패널 경로는 `/open-simple-browser` → `/htm-doc?…&_shell=1`(`_is_embed=True`)라 이 블록 자체를 안 타 무영향.
    - 검증: py 문법 OK, 서버 재시작(pid 39340) 200, non-embed GET `/htm-doc?path=…` → 확인 페이지 대신 실제 문서(`<!DOCTYPE>`+제목) serve 확인. SSE push 경로 제거.
    - 잔여: `HUB_OPENED_HTML` 상수 미사용화(제거 안 함 — 저위험 dead constant). `depends: Issue220`(같은 fallback/shell 흐름 후속).

## Issue220: hub-shell 문서 헤더 🗂 Hub 링크 클릭 시 새로고침만 — home 탭 전환 안 됨 ✅
* 목적: hub-shell iframe 안 렌더 문서 헤더의 🗂 Hub 링크(`.hub-link`, `href="/hub"`)를 클릭하면 iframe 이 in-place 로 `/hub` 로 네비게이트 → 현재 문서 탭 내용만 `/hub` 로 바뀌어 "새로고침"처럼 보이고, 정작 쉘의 기존 home(🗂 Hub) 탭으로는 전환되지 않음(`alt+h` 단축키와 동작 불일치). 사용자 요청 — 클릭 시 home 탭으로 이동.
* 구현 명세:
    - `HUB_LINK_SHIM` 신설(`services/hub/server.py`): 임베드(`window.parent!==window`)일 때만 `a.hub-link` 클릭을 capture-phase 로 가로채 `preventDefault` + 부모 쉘에 `postMessage {type:'fpm-goto-home'}`. standalone 은 native href 유지.
    - hub-shell message 핸들러에 `fpm-goto-home` → `activate("home")` 분기 추가.
    - serve 3경로(`/htm-doc`·`/view`·dash inline) 에 `HUB_LINK_SHIM` 주입.
    - 검증: py 문법 OK, 서버 재시작 후 라이브 — `/hub-shell` 에 핸들러 1건, `/htm-doc?…&_shell=1` 에 `fpm-goto-home`+`fpm-close-tab`+`copy-link` 전부 주입 확인.

## Issue218: hub 채팅 링크 2종을 외부 브라우저 대신 VSCode 로 (사용자 원 요청 · 통합 추적) ✅
* 목적: 본 작업의 **시작점(origin)** — 사용자 원 요청 추적 umbrella 이슈. VSCode 채팅에서 hub 가 출력하는 링크 2종이 클릭 시 외부 브라우저(Firefox)로 빠져나감. 사용자는 VSCode 내부에 머물기를 원함. 두 갈래로 분해 — prj1 서버 브리지(Issue216) + prj3 글로벌 hook 전환(Issue170).

## Issue219: 터미널(CLI) 세션 카드 클릭 시 대화 내용 확인 불가 — transcript 뷰어로 라우팅 ✅
* 목적: hub dashboard 의 터미널(iTerm/tmux) 세션 카드는 클릭해도 VSCode 로 포커스 불가(Issue177) → 빨간 토스트 "⌨️ 터미널 세션 — VSCode 로 포커스 불가" 만 뜨는 dead-end. 사용자는 포커스는 포기하되 세션 **대화 내용을 확인할 방법**을 요구.
* 구현 명세:
    - 클릭 핸들러: 터미널 origin → 토스트 대신 `openSessionViewer(row.dataset.url, topic)` 호출
    - 신규 `openSessionViewer(url,title)`: 임베드(hub-shell) 시 `postMessage fpm-open-tab` 으로 부모 쉘 내부 탭, 비임베드면 `window.open(_,'_blank')`
    - `rowHtml` li 에 `data-url="${s.url}"` 추가, 터미널 배지 툴팁 "포커스 불가, 클릭 무동작" → "클릭 시 대화 내용 보기(뷰어)", CSS cursor default→pointer
    - 1차(프론트 라우팅): 단일 파일(`services/hub/server.py`) 프론트 JS·CSS 변경
    - **2차(핵심 — 빈 응답 회귀)**: `/s/{h}/{sid}` 뷰어는 세션이 **푸시한 렌더 content**(mode A)만 표시 → 터미널 CLI 세션(content_type "live", 푸시 없음)은 "(빈 응답)"만 떴음. 서버 `/data` 핸들러에 **JSONL transcript fallback** 추가: `content_out` 비면 `_session_transcript_html(cwd,sid)` 로 JSONL 파싱(user/assistant 턴·thinking 접기·tool 한 줄 요약·최근 60턴·텍스트 4000자 절단·mtime 캐시) → content_type "response"/mode A 반환, SPA 그대로 렌더
    - 검증: py_compile OK · 서버 재시작 healthz 200 · 실제 터미널 세션 `/data` → content_type response·mode A·transcript div·60턴 렌더 확인
    - 사용자 액션: 이미 열린 "(빈 응답)" 뷰어 탭은 SSE 미수신(터미널 세션) → **카드 재클릭으로 탭 재오픈** 필요

## Issue214: hub 렌더 문서 헤더 UX 개선 (Issue213 후속) ✅
* 목적: Issue213 으로 문서가 쉘 iframe 안에서 열리며 주소창이 `/hub-shell` 만 보임 → 브라우저로 문서 URL 직접 복사 불가. 헤더 액션 4종 개편.
* 구현 명세:
    - `services/hub/server.py` `_serve_dash_inline` 내 `header_html`(5320) + `.dash-hdr`/`.hdr-actions` CSS(5436~5445) 수정
    - triage: 단순 (1파일·방법 자명) → plan/task 생략

## Issue216: hub 렌더 문서를 VSCode Simple Browser 패널에 띄우는 브리지 신설 ✅
* 목적: 글로벌 Issue170(~/.claude) 에서 hub 가 채팅에 출력하는 문서 링크가 클릭 시 외부 브라우저로 빠져나감. 사용자는 VSCode 안에서 작업하므로 렌더된 문서가 VSCode 내부(Simple Browser 패널)에 뜨길 원함. 본 브리지가 글로벌 Issue170 의 선행 조건.

## Issue217: hub-shell 내부 탭 문서 닫기 버튼 무동작 (Issue214 ✕ 닫기 기능 결함) ✅
* 목적: hub 렌더 문서 헤더의 닫기 버튼(canonical pink 헤더 `닫기 ✕`·dash 헤더 `✕`·Issue214 추가분)이 `/hub-shell` iframe 탭 안에서 클릭해도 아무 동작 안 함. 사용자가 "닫기 작동 안 함 + Issue214 미해결"로 보고.
* 구현 명세:
    - `services/hub/server.py` 4곳:
        1. `CLOSE_SHIM` 상수 + `_inject_before_body_end()` 헬퍼 신설 — `window.close` override: 임베드(`window.parent!==window`)면 부모로 `postMessage({type:'fpm-close-tab'})`, 최상위면 네이티브 close 유지.
        2. hub-shell `message` 핸들러에 `fpm-close-tab` 분기 추가 → `active()` 탭 닫기(home 탭 제외).
        3. `_handle_htm_doc`(canonical 렌더 문서) serve body 에 `CLOSE_SHIM` 주입.
        4. `_serve_dash_inline`(dash 헤더) serve body 에 `CLOSE_SHIM` 주입.
    - triage: 단순 (1파일·방법 자명) → plan/task 생략. prj1 hub 서버 버그 (트리거 변경 아님 → prj3 무관).

## Issue215: Project List 마스터 "hub" 토글 무력 — 시스템 OFF 마스킹 ✅
* 목적: Project List 헤더 마스터 "hub" 토글 클릭 시 화면 무변화("버튼 안 됨"). 사용자는 hub 전체 on/off 를 기대하나 dominant 플래그(`.hub-system-off`)를 무시하여 무력.
* 구현 명세:
    - `services/hub/server.py` `_handle_htm_toggle_all`: target=on → `.hub-system-off` 삭제(시스템 on 해제) + per-cwd on, target=off → `.hub-system-off` 생성 + per-cwd off. 마스터 토글을 진짜 마스터(= `..hub on/off` 동치)로 승격
    - 검증: curl `/htm-toggle-all {state:on}` → `still_off:0` + 플래그 삭제, `{state:off}` → 36/36 off + 플래그 생성. 양방향 통과
    - triage: 중간 (1파일이나 시스템 플래그 통제 = 후속 동작 영향). 자동 결정: 마스터 토글이 시스템 플래그까지 통제하도록 승격(라벨·사용자 기대 일치)

## Issue211: fpm 공개 배포 전 검증(release test) 구축 ✅
* 목적: fpm 공개(GitHub 미러 prj7 + 마켓 플러그인 fpm-core) 전, 임의 사용자 환경에서 설치·작동·설정·다국어가 정상이고 **공개 push 시 개인정보/시크릿 누출 0** 임을 보증. 기존 자산(check.sh 10항목 + hub test_*.py 7개) 위에 신규 테스트 5건 + release gate 통합.
* depends: Issue213 (hub-internal standalone /hub 중복창 funnel — 공개 전 hub UX 선결. B-2 수동검증이 Issue213 fix 후라야 통과)
* 구현 명세:
    - 신규: `sh/release-check.sh`(샌드박스 하니스) / `scripts/test_publish_gates.sh`(게이트 양·음성 픽스처) / `services/hub/test_i18n_parity.py`(en↔ko 패리티) / 설정 cast·mtime 갭 테스트 / hub UI 수동 체크리스트
    - 우선순위 E>A>D>C>B. 완료: 자동영역 release-check exit 0 + 게이트 dry-run 누출 0 + report 사인오프
    - triage: 복잡 (5영역·신규 5건·후속 공개 게이트 영향) → plan+task+report 전체 사이클

## Issue213: hub-internal 모드 standalone `/hub` 중복 창 제거 — 단일 쉘 funnel ✅
* 목적: `hub_single_window=true` + `render_tab_mode=hub-internal` 인데도 `/hub-shell`(렌더 경로)과 `/hub`(루트/Hub링크 경로) 두 창 공존. `/hub` 는 이미 쉘 home 탭(iframe src=/hub?_shell=1)이므로 standalone 진입을 전부 `/hub-shell` 로 funnel → 단일 창 보장.
* 구현 명세:
    - 핵심: `_handle_hub` 진입부 — hub-internal + top-level(무마커) → `302 /hub-shell`. 임베드(`_shell=1`/Sec-Fetch-Dest:iframe)는 raw serve(loop 방지). htm-doc 와 동일 패턴
    - 보조: 루트 `/` 302 hub-internal 분기(`/hub-shell`), static iframe src `/hub`→`/hub?_shell=1`, nav "🗂 Hub" 링크 ×3 `target="_blank"` 제거 (server.py + hook 637·803)
    - 검증: hub test_*.py 8개 127 pass / 격리 라우팅 5경로 통과 / browser-tab 회귀 0 / 실서버(pid 70379) 재기동 후 `/hub`·`/`→302 /hub-shell 확인
    - 후행: **Issue211 진행 가능** (B-2 수동검증 선결 완료)

## Issue212: gstack 잔재 제거 (Harness.md + .claude/ dead 참조) ✅
* 목적: gstack 은 Issue143(2026-06-12)에서 제거됨. Harness.md 의 `gstack ↔ nPTiR bridge` 블록(존재 안 하는 /gstack-plan·/gstack-report·/gstack-retro-report 3 커맨드) + 삭제된 `~/.claude/rules/gstack-nptir-rules.md` 를 가리키는 dead 참조 4건이 활성 SCAR 영역에 잔존 → 제거.

## Issue209: hub 외부 링크 클릭 시 새 hub-shell 탭 충돌 — 기존 쉘 합류 ✅
* 목적: VSCode 등 외부에서 `/htm-doc?path=` 링크 클릭 시 OS 새 탭에 2번째 hub-shell 이 떠 단일 인스턴스 lease 가드("이미 hub 창 열림 / 여기서 인계") 오버레이가 발동. 기존 쉘에 합류시키고 새 탭엔 경량 확인 페이지를 serve해 충돌 제거.
* 구현 명세:
    - `_handle_htm_doc` 302 분기에 `_hub_holder_alive(ip)` 판정 추가(`hub_single_window` on + lease last_seen ≤ ttl). 보유자 있으면: `tab-open` SSE push(즉시 반영) + 경량 확인 HTML(`HUB_OPENED_HTML`) serve. 보유자 없거나 단일창 off → 종전 302 `/hub-shell`.
    - 검증: `py_compile` OK + bg SSE 로 lease 보유 시 200 확인 페이지 + `tab-open` 수신 / lease 만료 후 302 / `_shell=1` embed raw serve 3분기 모두 통과.

## Issue210: hub Settings 필드 tooltip 언어 불일치 — 영문 모드에 한글 설명 노출 ✅
* 목적: hub Settings(Advanced 등) 일부 필드의 `?` tooltip 이 language=en 인데도 한글로 표시됨. i18n catalog 에 해당 키가 누락되어 schema 내장 한글 comment 로 fallback 되는 게 원인.
* 구현 명세:
    - en.json: 5키 영문 설명 추가. ko.json: 5키 한글 설명 추가(schema comment 일치).
    - 검증: 누락 0 재확인 + `t(key,'en')`/`t(key,'ko')` 가 schema comment 로 fallback 안 함 확인 (스크립트 PASS).

## Issue208: hub Settings 키 라벨 `_` 시각적 숨김 ✅
* 목적: hub Settings 다이얼로그의 설정 키 라벨(`default_browser` 등)에서 언더스코어를 배경색과 동일 색으로 렌더해 시각적으로 숨김. space 치환이 아닌 색상 처리인 이유는 복붙 시 실제 키명(`default_browser`)이 보존되어야 하기 때문.
* 구현 명세:
    - 라벨: `setEsc(s.key).replaceAll('_','<span class="set-us">_</span>')` (키는 식별자 안전 — 이스케이프 후 치환 무해)
    - 검증: hub 재시작(pid 60601, etime 38s) 후 serve HTML 에 `set-us` 2회(CSS+JS) 확인

## Issue206: hub Settings 모달 설명·배지 아이콘+팝업 통일 → (해결: 2026-06-24, commit: <commit>) ✅
* 목적: 설정 모달 행이 인라인 설명 풀텍스트로 길어짐. 아이콘+hover팝업으로 압축해 가독성·밀도 개선
* 구현 명세:
    - `services/hub/server.py`: setRenderForm() set-desc → `?`+data-tip, mouseover/out 핸들러 `.set-badge, .set-desc` 확장, CSS `.set-desc` 원형 아이콘화
    - `data/locales/{en,ko}.json`: settings.applyBadge.{auto,hook,restart} 텍스트 제거 → 이모지만
    - `plugins/fpm-core` 미러엔 해당 설정 코드 부재(구버전) → 미수정
    - 검증: py_compile + JSON valid + 단일 인스턴스 재시작 healthz 200 + 서빙 페이지 신 마커 확인

## Issue207: hub Settings 탭바 sticky 음수마진 갭 회귀 → (해결: 2026-06-24, commit: <commit>) ✅
* 목적: Issue205 의 `.set-tabs` 음수마진+sticky+top패딩 방식이 head 와 탭바 사이 빈 갭 + 첫 행(default browser) 위치 어긋남 유발. 음수마진 제거하고 탭바를 스크롤 영역 밖으로 분리.
* depends: Issue205 (commit <commit>)
* 구현 명세:
    - HTML: `.set-tabs` 를 `.modal-body` 밖, `.modal-head` 직후로 이동 → `.modal` flex 컬럼의 비스크롤 형제(head/tabs/body/foot)로 자연 고정
    - CSS: sticky·음수마진·top패딩 제거, `padding: 0 1.1rem; flex: 0 0 auto` 단순화
    - 검증: py_compile OK / 서버 재시작 healthz 200 / DOM 순서 head→set-tabs→modal-body 확인 (갭 소멸)

## Issue205: hub Settings 모달 탭바 스크롤 시 고정 → (해결: 2026-06-24, commit: <commit>) ✅
* 목적: hub Settings 모달에서 본문(panes)을 스크롤하면 탭바(Basic/Sessions/Advanced)도 함께 위로 사라짐 → 탭 전환 접근성 저하. 탭바를 상단 고정(sticky)하여 스크롤 무관 상시 노출.
* 구현 명세:
    - `.set-tabs` 에 `position: sticky; top: 0; z-index: 5; background: var(--bg)` 부여
    - modal-body 패딩(0.9rem/1.1rem)을 음수 마진으로 bleed + 패딩 재부여 → 고정 바 배경이 좌우 끝까지 덮어 콘텐츠 측면 누출 방지
    - 검증: py_compile OK / 서버 재시작 후 healthz 200 / curl `/hub` HTML 에 `position: sticky` + `top: 0` + `var(--bg)` 토큰 노출 확인

## Issue204: hub-shell 모든 탭 닫기 버튼 추가 → (해결: 2026-06-24, commit: <commit>) ✅
* 목적: `/hub-shell` 내부 탭바에서 열린 렌더 탭을 한 번에 정리하는 "🗑️ 모든 탭 닫기" 버튼 제공 (기존엔 탭별 ✕ 또는 단축키만 존재)
* 구현 명세:
    - CSS: `#closeall` 버튼 스타일 (라이트/다크 hover 포함)
    - `render()`: `tabs.length > 1` 일 때만 탭바 우측(hint 뒤)에 `🗑️ 모든 탭 닫기` 버튼 append
    - `closeAllTabs()`: home 제외 전체 탭 제거 → home 활성화
    - 검증: 서버 재시작 후 `curl /hub-shell` 에 `closeall`·`closeAllTabs`·`모든 탭 닫기` 노출 확인, healthz ok

## Issue203: hub 탭 세로 적층(2중 탭바) 버그 → (해결: 2026-06-24, commit: <commit>) ✅
* 목적: `/hub-shell` 내부 탭바가 가로 1행이 아니라 동일 탭이 2행으로 중복 적층되는 버그 해결
* 구현 명세:
    - `services/hub/server.py` `HUB_SHELL_HTML`:
        1. 중첩 가드: IIFE 진입 직후 `window.self !== window.top` 이면 탭바·iframe 미초기화 + 빈 본문 대체 후 return (재귀 차단 안전망)
        2. `embedUrl()`: 상대경로뿐 아니라 `location.origin` 동일 origin 절대 URL 에도 `_shell=1` 부여 (302 재진입 트리거 제거)
    - 검증: `py_compile` + curl `/view`·`/htm-doc` embed(`_shell=1`)=200 / top-level=302 유지

## Issue190: hub 서버 lifecycle 커맨드 단일화 → (해결: 2026-06-24, commit: <commit>) ✅
* 목적: `/hub`(prj1 로컬)·`/fpm-board-server`(글로벌) 가 동일 단일 데몬(port 9876 `server.py`)을 만지는 중복 lifecycle wrapper → `/fpm-hub-server` 단일 글로벌 커맨드로 통합.

## Issue200: hub 기동 시 allowlist DNS resolve 비동기화 → (해결: 2026-06-24, commit: <commit>) ✅
* 목적: Issue199 잔여 분리. hub 서버 기동 시 allowlist DNS resolve 가 동기 블로킹 → 재시작 다운타임 ~5s. 비동기화로 단축.
* depends: Issue199 (완료, commit <commit>)
* 구현 명세: SSOT=`services/hub/server.py`. triage=단순. 검증: compile OK / 재시작 후 healthz 200 until **0.04s**(이전 ~5s — `host.local` resolve 5s 블로킹이 백그라운드로 격리) / server.log allowlist 5 IP 정확 적재(판정 정확성 유지)

## Issue202: htm-doc 쉘 착지 결정적화 — `_shell` 마커 우선(Sec-Fetch-Dest 의존 제거) → (해결: 2026-06-24, commit: <commit>) ✅
* 목적: Issue201 의 302 게이트가 `Sec-Fetch-Dest: document` 헤더에만 의존 → 헤더 누락 top-level 네비(일부 브라우저·IDE 링크 open)에서 raw 200 standalone 누출(htm-doc URL 직접 열람이 OS 새 탭으로 뜸). 임베드 판정을 결정적 쿼리 마커로 교체.
* depends: Issue201 (commit <commit>)
* 구현 명세: SSOT=`services/hub/server.py`. triage=중간. 검증: 마커無+헤더無=302 /hub-shell·_shell=1=200·iframe헤더=200·document헤더=302·compile OK

## Issue201: hub-internal 렌더 — 표준 htm-doc URL 도 hub 쉘 내부 탭으로 착지 → (해결: 2026-06-23, commit: <commit>) ✅
* 목적: render_tab_mode 기본이 browser-tab 이라 `..show` 산출물이 OS 새 탭(`/htm-doc?path=`)으로 뜸. 사용자는 `/hub-shell` 내부 iframe 탭 표시(hub-internal) 원함. ① 기본값을 hub-internal 로 전환 ② 표준 htm-doc URL 을 직접 열어도 OS 탭이 아닌 쉘 내부 탭으로 착지.
* depends: Issue199 (commit <commit>)
* 구현 명세: SSOT=`services/hub/server.py`. triage=중간. 검증: compile OK·재시작·curl Sec-Fetch-Dest document=302 /hub-shell·iframe=200·헤더無=200

## Issue199: hub 내부 탭 SOT 안정화 — SSE 단독 의존 → 레지스트리 보강 → (해결: 2026-06-23, commit: <commit>) ✅
* 목적: Issue194 hub 내부 탭에서 탭 목록을 휘발성 SSE(`tab-open`)에만 의존 → 서버 재시작 시 전 탭이 동시에 재연결 시도 → Chrome 크래시 유발(restart storm). 탭의 진실 원천을 레지스트리로 옮겨 재시작·SSE 끊김에 견고화.
* depends: Issue194
* 구현 명세:
    - SSOT=`services/hub/server.py` HUB_SHELL_HTML. 검증: compile OK·재시작·주입 확인·/boards mtime_ts 보유
    - 잔여(DNS resolve 비동기화) → Issue200 분리

## Issue194: hub 내부 탭 렌더 모드 — OS 브라우저 탭 대신 hub 쉘 iframe 탭 → (해결: 2026-06-23, commit: <commit>) ✅
* 목적: 현재 hub 렌더(`..show`/`..ask`/`..board`)는 매 렌더마다 OS 브라우저 새 탭/창을 연다. Chrome 계열에서 새 탭 open 이 창을 foreground 활성화 → 보던 타 앱 창을 가림. OS 탭 대신 hub 쉘이 렌더 문서를 내부 iframe 탭으로 호스팅하는 신규 모드 도입.
* 구현 명세:
    - 구조: iframe 격리(`/htm-doc` 핸들러 무변경) + 신규 SSE `tab-open` push + `GET /hub-shell` 라우트
    - `render_tab_mode` 서버 yml 직독 → hook 변경 없이 서버·설정만으로 MVP 성립
    - triage=복잡(서버+설정+쉘+리스 다컴포넌트). SSOT=`services/hub/server.py`
    - ⚠️ 글로벌 hook(`fpm-hub-trigger.sh`·`fpm-hub-doc-register.sh`) OS open 분기는 글로벌 SCAR → `~/.claude/Issue.md` 별도 이슈 (본 이슈 범위 외)

## Issue192: c모드 `/boards` 신규 카드 자동 등록 갭 ✅
* 목적: c모드 runner 가 생성한 신규 `.dash.yaml` 카드가 dash-registry 미등록 → `/boards` 자동 노출 안 됨(사용자가 수동 `rescan` 필요)이던 자동화 갭 해소.

## Issue193: `/boards` 카드 progress 스칼라 미집계 — 문자열 value 타입 불일치 ✅
* 목적: Issue189 board rename 재테스트서 발견. `/boards` 카드 레벨 `progress` 스칼라가 `null`. 카드 메타 집계·정렬에서 progress 누락.

## Issue198: browser_focus deprecated 줄 제거 + org 템플릿 현행화 ✅
* 목적: Issue170 에서 `browser_open` 이 `browser_focus` 를 흡수(3옵션 통합)한 뒤 `hub_setting.yml` 에 deprecated 주석으로 남아있던 `browser_focus` 줄을 완전 제거하고, 설치 템플릿 `hub_setting_org.yml` 을 현행 스키마·안전 기본값으로 현행화.
* 구현 명세:
    - triage=단순(설정 파일 2개 정리, 키 의미 무변경). reg→commit→close.
    - 검증: `test_settings_loader.py` 10/10, `test_settings_writer.py` 17/17 pass, 서버 재시작 정상(healthz ok).

## Issue197: hub 설정 탭 내용 재배치 (Basic/Sessions/Advanced 그룹 정리) ✅
* 목적: 기존 3탭에 설정 키 임의 배치 → 의미별 응집도 기준 재배치. deprecated `browser_focus` 정합.
* depends: Issue196

## Issue196: hub 설정창 너비 확대 + 행 레이아웃 2행화 ✅
* 목적: hub Settings 모달이 좁아(~720px) `label·control·description` 3컬럼 중 설명 칸이 굶어 단어당 한 줄로 깨짐. 너비 확대 + 2행 레이아웃으로 가독성 확보.

## Issue195: hub bind_host 리스트화(멀티 bind) + inline allow_list + allow_server_list 게이트 분리 ✅
* 목적: hub 서버의 source-IP 접근 제어를 `bind_host` 에서 분리하고 세분화. (1) `bind_host` 가 listen 인터페이스 결정에만 쓰이도록 `allow_server_list` 토글 분리, (2) `bind_host` 를 리스트로 받아 0.0.0.0 와일드카드 없이 특정 주소들에만 멀티소켓 bind, (3) Servers.md 외에 yml inline `allow_list` 로 IP/CIDR 직접 추가 허용.
* 구현 명세:
    - `services/hub/server.py`(commit <commit>): `BIND_HOSTS` 전역, `_parse_yml_list()` 헬퍼, 로더 리스트 파싱(bind_host 대괄호 + allow_list), defaults `allow_list: []`, main() 멀티 bind serve(첫 소켓 메인 스레드, 나머지 데몬 스레드) + `_open_mode = any(비루프백)` 일반화 + allow_list 병합 적재(개방 모드, allow_server_list 토글과 독립)
    - `data/hub_setting.yml`(commit <commit>): bind_host 리스트 표기, allow_server_list, allow_list 예시 주석
    - `allow_list` 는 yml 전용(설정 UI text 위젯이 `/`·`,` 거부 → schema 미등록, HUB_SETTING_DEFAULTS 에만 추가)

## Issue191: fpm-hub-trigger.sh subagent_type stale 식별자 정리 ✅
* 목적: 글로벌 Issue161(board rename 글로벌 전파) 의 후속 과제 — 렌더 문서 `~/.claude/_doc_work/z_htm/hub_htm_20260621_163550_a_issue161-board-rename.htm` 에 scope·WIP 근거로 기록된 hooks 잔존 참조. dispatch 프롬프트의 agent 타입 식별자가 `fpm-board` rename(Issue189) 과 불일치.
* depends: Issue189

## Issue189: dashboard 식별자 → board 통일 rename ✅
* 목적: c모드 트리거 `..board` 와 내부 식별자 `fpm-dashboard`/`/dashboards`/`spa_dashboard` 의 단어 불일치 해소. `..show`→`fpm-show`, `..hub`→`fpm-hub` 와 동일하게 트리거=커맨드명 정합. 사용자 결정(폼 회수)=전부 board 통일.

## Issue187: fpm 공개(public release) 사전 정비 — 개인정보·기술유출 가드 + copyright/문서 영·한 분리 ✅
* 목적: ___pm → 공개 미러 fpm 의 정식 오픈소스 공개 전, (1) 잔존 개인정보 제거 (2) 비공개 기술자료(특히 공개 전환된 Issue.md) 유출 차단 (3) copyright 영/한 분리 (4) 모든 공개 문서의 영·한 2개 버전화 + 상호 링크. 글로벌 영어권 + 국내 독자 동시 대응 + 법적·프라이버시 리스크 제거.
* 구현 명세:
    - 편집 위치: 정책은 ___pm `data/publishable-policy.yml` (fpm-sync 스킬 경유 편집 권장). 문서 본문은 README 가 prj7(fpm) 수동 편집 대상인 점 유의(README 충돌 방지 정책). 나머지 공개 문서는 ___pm forward 동기화 경로.
    - 동기화: ___pm 편집 → `scripts/fpm-sync.sh` forward (가드 통과분만 미러). 항목1·2 가드는 결정적 sh 헬퍼(`fpm-guard.sh`·`fpm-sanitize.sh`·`fpm-secret-scan.sh`)가 집행.
    - 복잡도: **복잡** (정책 변경이 후속 공개 운영에 영향 + 다파일 + 영·한 문서 체계 신설). plan/task 별도 요청 시 생성 — 본 등록은 리스트·이슈 등록까지만.
    - 의존: 항목2(이슈 redaction 메커니즘)는 항목1(개인정보 가드) 정합 전제. 항목4(문서 영·한)는 항목3(copyright 분리) 네이밍 규칙과 정렬.

## Issue188: hub 렌더 포커스 복원 불완전 — 프로세스명↔앱명 불일치 시 Chrome 포커스 잔류 ✅
* 목적: Issue173 `_restore_focus` 가 앱명 기반 `tell application "<name>" to activate` 라 프로세스명↔앱명 불일치(VSCode 프로세스 "Code") 시 복원 실패 → Chrome 포커스 잔류. 사용자가 겪은 실제 focus-steal 잔존 원인.
* depends: Issue173

## Issue186: 폐쇄망(air-gapped) 설치 — 다운로드된 f-claude-plugins 로컬 설치 파라메터 ✅
* 목적: 인터넷 차단 환경에서 `sh/install.sh` SCAR 설치 시 GitHub 마켓(`claude plugin marketplace add <github-url>`) 접근 불가 → 미리 받아둔 f-claude-plugins(prj20) 로컬 사본을 마켓 소스로 쓰는 명시 파라메터 제공. 폐쇄망 설치 가능화.
* depends: Issue185

## Issue185: install.sh·check.sh·uninstall.sh → sh/ 이동 + SCAR 인벤토리 매니페스트화 ✅
* 목적: 설치 페이로드를 `sh/`(CLAUDE.md "단일 SSOT 설치 페이로드") 한 곳으로 집약. 공개 명령 `bash sh/install.sh` 로 변경.

## Issue181: fpm-core SCAR 를 prj20 마켓플레이스 게시 + install.sh 마켓 경유 설치 (A안) — host E2E ✅
* 목적: `install.sh`·등록 플러그인 어느 쪽도 `~/.claude` SCAR 를 설치 안 하는 gap 을 A안(플러그인 정식 게시)으로 해소. fpm-core 를 prj20(f-claude-plugins) 마켓에 게시, `fpm-sync` 가 게시 자동화, `install.sh` 가 마켓 경유 설치. host 원격 E2E 로 검증.

## Issue184: hub Activity feed 헤더 한 줄 — title nowrap + 종 이모지 제거 ✅
* 목적: hub 우측 Activity feed 패널 헤더가 제목 "🔔 Activity feed" + count badge(300) + 버튼 4개를 한 줄에 못 담아 제목이 글자 단위로 줄바꿈되고 "300"이 아래 줄로 밀리는 레이아웃 깨짐 수정. 한 줄로 표시.
* 구현 명세:
    - `services/hub/server.py:5666` — `.feed-title-label` 에 `white-space: nowrap` 추가 (핵심 수정).
    - `data/locales/{ko,en}.json:54` — `feed.title` 에서 🔔 제거 ("활동 피드" / "Activity feed").
    - live 서버(`services/hub`) 재시작·healthz 200 확인. `plugins/fpm-core/services/hub` 미러는 미반영 — 배포 시 fpm-sync 동기화.
    - 복잡도: 단순 (파일 3개·자명 → plan/task/report 생략).

## Issue183: dashboard 강제 종료 버그 — 한글/비ASCII window명이 검증 정규식에 막혀 kill_pane 400 ✅
* 목적: dashboard view "강제 종료" 버튼이 한글 window명(ex `_테스트`) dashboard 에서 항상 실패. `/control` kill_pane 핸들러의 window_name 검증 정규식이 ASCII 만 허용해 `tmux kill-window` 도달 전 400 으로 거부되던 버그 해소.
* 구현 명세:
    - 검증(서버 재시작 후 curl): 한글 가짜 window → `already_gone`(정규식 통과 확인), `bad;rm` → 400(보안 유지)
    - 복잡도: 단순 (2 사본·정규식 1줄)
    - commit: <commit>

## Issue182: hub 🎯 이모지 아이콘 → fPm 프로젝트 로고(Finfra fox) 교체 ✅
* 목적: 신규 프로젝트 아이콘(`~/Desktop/_rsc/icons/fPm.png`, Finfra fox 로고)을 hub 곳곳의 🎯 이모지(favicon + 헤더 브랜딩) 자리에 반영. 일관된 브랜딩.
* 구현 명세:
    - **SSOT drift 발견**: `~/.claude` 미러(라이브 hook)가 bundle(`plugins/fpm-core`)보다 앞서 있음(Issue152/153/158/172/173 적용, bundle 미반영). 라이브=`~/.claude` 이므로 아이콘 편집을 양쪽(bundle + ~/.claude)에 독립 적용. **bundle forward-sync 필요(별도 처리)** — 본 이슈 범위 외.
    - 검증: `ast.parse` PASS(양 server.py), `bash -n` PASS(hook 3종 ×2). 서버 재시작 후 `curl /fpm-icon.png`=HTTP 200 image/png 56499B, `/hub`=favicon + h1 img 서빙 확인. (브라우저 favicon 캐시 → 하드 리프레시 필요)
    - 자동 결정(triage 중간): plan/task 미생성. report 생략(검증 증거 본 이슈 인라인).

## Issue180: Projects.md → projects/ 자동 동기화 — cdf lazy sync-on-use ✅
* 목적: `Projects.md`(SSOT) 편집 후 "동기화 해줘" 수동 프롬프트(`fpm-projects-sync`)를 잊으면 `projects/` 인덱스가 silently 낡아 `cdf` 가 어긋남. 사용자가 "언제·무엇으로 동기화?"를 매번 기억해야 하는 인지 부담 제거.
* 구현 명세:
    - **설계 전환(중요)**: 1차 후보였던 git pre-commit hook(Projects.md staged 감지)은 **무효** — `Projects.md` 와 `projects/` 모두 `.gitignore` 대상(로컬 전용 머신 상태). git 은 자연 트리거가 아님. → **lazy sync-on-use** 로 선회.
    - **fpm_function.sh `_pm_manager()`**: base_dir 확정 직후 mtime 가드 추가. `Projects.md -nt projects/.sync-stamp` 이면 `fpm-projects-sync --index-only` 1회 실행 + stamp touch. stamp 부재(첫 실행)도 `-nt` 참 → 1회 동기화. cdf 계열 모든 진입점이 `_pm_manager` 경유 → 사용 시점 항상 최신.
    - **fpm-projects-sync `--index-only` 플래그 신설**: `projects/` 인덱스(step 1/3)만 재생성. `.vscode`(타 repo)·iterm-bg(머신 로컬·gitignore)는 cdf 와 무관하므로 skip → lazy 경로 경량화. 수동 full 동기화는 기존대로.
    - **stamp**: `projects/.sync-stamp` — `projects/` 가 이미 gitignore 라 자동 무시(추가 .gitignore 불요).
    - **수동 경로 유지**: `fpm-projects-sync`(full) 명령은 그대로. lazy 는 "잊어도 되게" 보강이지 대체 아님(vi 편집·비대화 셸 대비).
    - **검증**: subshell 에서 ① stamp 부재+Projects.md touch → sync 발동·stamp 생성 ✅ ② Projects.md not newer → skip ✅ ③ 재 touch → stale 재감지 ✅ ④ `git check-ignore projects/.sync-stamp` ✅.
    - **부수 발견**: `projects/` 26개 파일이 gitignore 이전 레거시로 tracked 상태(현 이슈 범위 외, 별도 정리 후보).

## Issue179: hub 세션 출처 배지 회귀 — UserPromptSubmit 훅이 entrypoint 매 턴 clobber ✅
* depends: Issue177 (출처 배지 도입 — 본 이슈는 그 회귀 수정)
* 목적: Issue177 이 SessionStart 훅(register.sh)에 `CLAUDE_CODE_ENTRYPOINT` 캡처를 넣었으나, VSCode fWarrange 세션 2개가 hub 카드에 항상 ⌨️(터미널)로 표시됨. Issue177 fix 가 매 프롬프트마다 무효화되던 회귀.
* 구현 명세:
    - **root cause**: `UserPromptSubmit` 훅 `fpm-hub-session-topic.sh` 가 매 프롬프트마다 `/session/register` 를 caps=`{source:prompt, kind:live}`(entrypoint 없음)로 호출. 서버 merge 로직 `entry["capabilities"] = caps or existing` 은 비어있지 않은 caps 를 **replace** → SessionStart 훅이 심은 `entrypoint=claude-vscode` 를 첫 프롬프트에 덮어쓰고 이후 매 턴 terminal 로 회귀. (수동 POST 한 테스트 행만 entrypoint 보존되어 정상 → 회귀가 실제 세션에서만 발현)
    - **수정**: `plugins/fpm-core/hooks/fpm-hub-session-topic.sh` — register.sh 와 대칭으로 `ENTRY="${CLAUDE_CODE_ENTRYPOINT:-}"` 캡처 후 caps 에 `entrypoint` 동봉. 매 프롬프트 재등록이 올바른 출처를 carry → server 재시작·중간 합류 상황에도 robust(SessionStart 단독 의존 제거).
    - **배포**: repo SSOT(`plugins/fpm-core/hooks/`) → `~/.claude/hooks/` cp 동기 (IDENTICAL 확인).
    - **검증**: 현재 vscode 세션 + fWarrange 세션 2개 재등록 후 `/dashboards` JSON `origin=vscode` 확인. 기존 등록분은 다음 프롬프트 때 자동 self-heal.

## Issue178: hub 렌더 백그라운드 전용 열기 — Chromium open -g self-activate 깜빡임 제거 ✅
* depends: Issue173 (chrome focus 탈취 trap 복원 — 본 이슈가 trap "전면화 후 복구" 자체를 제거)
* 목적: `browser_focus: false`(=`browser_open: background`) 여도 렌더 시 Chrome 이 잠깐 전면화됐다가 직전 앱으로 복원 → 타이핑 끊김. 원인은 Issue173 trap 이 "포커스 재탈환 보정"이지 "전면화 차단"이 아니었던 것.
* 구현 명세:
    - **root cause**: 자동 렌더는 `-r false`(탭 미재사용) → 항상 `_fallback_open` 의 `open -g -a "Google Chrome"`. Chromium 은 `open -g` 무시 self-activate → trap `_restore_focus` 가 직후 복원 = "전면화→복구" 깜빡임. (Firefox 는 `open -g` 존중하여 무증상)
    - **수정**: `plugins/fpm-core/hooks/fpm-browser-open.sh` — `_bg_open()` 신설. Chrome/Edge 가 실행 중이고 창 1개 이상이면 `open` 우회하고 AppleScript `make new tab`(activate 미호출)로 탭만 생성 → 전면화 자체 회피. 미실행·창0 은 `open -g` 폴백(어차피 1회 떠야 함). osascript 실패 시 `|| open -g` 안전망. `_fallback_open` 의 `focus != true` 분기가 `open -g` 대신 `_bg_open` 호출. Firefox 등 기타는 `open -g` 존중(무변경).
    - Issue173 `trap _restore_focus` 는 무해 no-op 안전망으로 유지.

## Issue177: hub 활성 세션 카드에 출처(VSCode/터미널) 배지 + 클릭 동작 분기 ✅
* 목적: hub 활성 세션 카드가 VSCode 확장 세션과 iTerm CLI(claude code) 세션을 구분하지 못함. 카드 클릭 시 출처 무관하게 `vscode://anthropic.claude-code/open?session=<sid>` URI 를 무조건 발사해 터미널 세션도 VSCode 로 잘못 재오픈됨. 출처 배지 표시 + 클릭 분기로 해결.

## Issue176: fpm-sync 기본값을 양방향(sync)으로 — 인자 없이 실행 시 버전 게이트 자동 방향 ✅
* 목적: 인자 없는 `fpm-sync.sh` 가 forward 단방향이라 fpm upstream 흡수를 놓칠 위험 → 기본값을 버전 게이트 자동 방향(sync)으로 변경.

## Issue175: hub allowlist CIDR(서브넷) 지원 — exact-IP → ip_network 매칭 확장 ✅
* 목적: bind_host=0.0.0.0 원격 개방 시 source-IP allowlist 가 exact-IP 일치만 지원 → 서브넷 단위 허용(`<lan-ip>`) 불가. CIDR 의 올바른 자리는 allowlist (bind_host 는 단일 listen 인터페이스라 CIDR 자리 아님).

## Issue174: fpm 버전이 ___pm 보다 앞설 때 검증된 변경을 ___pm 으로 흡수(upstream pull) — 버전 게이트 + 컴펌 필수 ✅
* 목적: prj7(`~/_git/__all/fpm`)·host·기타 서버·GitHub bare 에서 fpm 공개 미러를 테스트한 결과(중요 코드·SCAR)를 ___pm(SRC) 로 역흡수. fpm 이 단방향 다운스트림이 아니라, bare 환경에서 검증된 변경이 fpm 버전을 먼저 올린 뒤 ___pm 에 반영되는 흐름. 목적은 ___pm 업데이트 시 fpm 과의 충돌 최소화.

## Issue173: chrome focus 탈취 수정 — hub 렌더/폼 open 포커스 미탈취 ✅
* depends: gscar#Issue156 (글로벌 ~/.claude — 3 hook open 명령 helper 전환, commit <commit> ✅)
* 목적: `data/hub_setting.yml` `default_browser: chrome` 로 변경하니 hub 렌더·b모드 폼 open 시 포커스가 자꾸 Chrome 으로 이동. 기존 firefox 에서는 정상.
* 구현 명세:
    - **root cause**: Chrome 은 이미 실행 중일 때 URL/파일을 받으면 `open -g`(백그라운드) 플래그를 무시하고 self-activate. AppleScript `set URL of tab` 도 `doFocus=false` 여도 전면화. Firefox 는 `open -g` 존중 → 이 비대칭이 증상의 직접 원인. (재현: frontmost 캡처 before/after — firefox=Code 유지 ✓ / chrome=전면화 ✗)
    - **수정**: `plugins/fpm-core/hooks/fpm-browser-open.sh` — `focus != true` 면 open 직전 frontmost GUI 앱을 osascript 로 기억 → `trap _restore_focus EXIT` 으로 종료 시 재활성. fallback open / osascript reuse(탭재사용) / notfound 전 경로 커버. firefox 등 무해 no-op, 권한부재·앱명불일치 시 `|| true`.
    - **글로벌 연계(Issue156)**: 라이브 경로는 글로벌 ~/.claude hook 3종이 plain `open -g -a chrome` 생성 → 본 helper `-f false -r false` 경유로 전환(focus 복원 적용). `-r false`=렌더/폼 새 탭(Issue153 정합).
    - **검증**: helper `-f false -r false` (chrome) → BEFORE/AFTER 동일(iTerm2 유지, 미탈취) ✓. 4 파일 `bash -n` 통과. foreground(`-f true`)는 `open -a` 무변경.
    - **잔존(미작업)**: 플러그인 미러 카피(`plugins/fpm-core/hooks/fpm-hub-trigger.sh`·`fpm-ask-*.sh`)는 글로벌(Issue152/153) 대비 이미 stale — 본 fix 미반영. 마켓플레이스 배포 정합은 별도 sync 이슈. 단 helper 본체는 플러그인 경로(live) 라 즉시 유효.

## Issue171: browser_tab_reuse 재정의 — /hub 단일 탭 전용, ..show/..ask 렌더는 매번 새 탭 ✅
* depends: gscar#hub-tab-reuse-split (글로벌 ~/.claude/Issue.md Issue153 — ✅ 완료 commit <commit>)
* 목적: `browser_tab_reuse=true` 구 의미가 origin(:9876) 매칭이라 `/hub` + 모든 `/htm-doc` 렌더를 단일 탭에 덮어씀 → 렌더 히스토리를 탭별로 닫으며 검토 불가. 사용자 요구: 렌더는 매번 새 탭, `/hub` 모니터링만 단일 탭 재사용.

## Issue169: hub 다국어 지원(i18n) — language 설정 + data/locales catalog + JS 런타임 t() ✅
* 목적: hub UI 다국어 지원. ~7000줄 한국어 하드코딩 → 언어 전환 가능 구조. fpm 공개 미러 국제 사용자 대비. 지원 en/ko 2종, 차후 N개 확장.

## Issue172: b모드 ask 폼 file:// → :9876 hub URL — a모드 doc 과 탭 동작 정합 (등록: 2026-06-14, 해결: 2026-06-14, commit: <commit>(~/.claude)) ✅
* 목적: `..ask`(b모드) 폼이 `open file://` 로 직접 열려 :9876 origin 미매칭 → 탭재사용 helper 가 안 잡아 매 폼 새 탭 누적(사용자 이미지1=틀림). a모드 doc 은 `render_target:hub` → `/htm-doc?path=` :9876 URL 로 단일 탭(이미지2=맞음). 원인 = ask-intercept 에 render_target/reuse 라우팅 부재(grep 0건 vs hub-trigger 18건).
* depends: Issue171(같은 영역 — 새탭 재설계 시 동반 갱신), gscar(`~/.claude/hooks/fpm-ask-intercept.sh`)

## Issue170: hub 브라우저 자동 open 3옵션 통합 — browser_open 단일 키 ✅
* 목적: hub 렌더 브라우저 open 동작이 `render_target`(hub=open안함) × `browser_focus`(true=포커스탈취) 2축 조합으로 흩어져 모호한 조합("의도하지 않은 방식")이 발생. off/background/foreground 3옵션을 단일 키 `browser_open` 으로 통합.

## Issue168: hub ⚙️ 설정창 UI — 파일 열기 대신 인앱 3탭 모달 + 주석보존 yml 라이터 ✅
* 목적: 현재 hub 페이지 ⚙️ 버튼은 `/open-settings-yml` 로 `data/hub_setting.yml` 을 VSCode 파일로 연다. 사용자가 yml 문법·유효값·소비처(자동재로드/hook/restart)를 직접 외워야 함. 이를 hub 페이지 내 **3탭 모달 설정창**으로 전환하여 폼으로 편집하고, 저장 시 yml 을 주석 보존하며 갱신. raw 편집 경로는 모달 하단 "설정 파일 열기" 버튼으로 보존.
* 구현 명세:
    - `HUB_SETTING_SCHEMA` 상수(탭·위젯·유효값·적용방식·설명) — 본 문서 분류 SSOT 는 `_doc_arch/hub_settings_ui.md`
    - `_load_hub_setting_raw()` 전 키 파서(hook 키 포함) + `_write_hub_setting(payload)` 라인 in-place 치환(inline 주석 보존)·temp→`os.replace` 원자적 쓰기
    - 단위테스트 2종(`test_settings_loader.py`·`test_settings_writer.py`)
    - 기존 `/open-settings-yml`·`btn-settings` ID 유지(모달 하단 버튼 재사용)
    - ⚠️ browser_*·render_target·advertise_host 키는 글로벌 hook 소비 — server.py 는 값 기록 게이트키퍼일 뿐 키 의미 불변(글로벌 SCAR 가드 비위반)

## Issue167: advertise_host 를 hub 렌더 HTML 헤더 endpoint 까지 전파 + `hook 미구현` 마커 정정 ✅
* depends: Issue153, Issue141
* 목적: prj57(jmDashboard) 의 "서버→브라우저 자동 갱신"을 ___pm hub 에 원격/타기기까지 적용하려 할 때, `advertise_host` 가 **채팅 htm-doc URL** 에만 반영되고 **렌더된 HTML 본문**에는 반영되지 않는 누락 발견. canonical 헤더(Issue132)의 `📁 open-project` · `🆚 open-session` · `🎯📊 hub-link` 세 endpoint 가 `http://127.0.0.1:9876` 하드코딩 → 원격 브라우저에서 헤더 버튼 전부 실패. `data/hub_setting.yml:22` 의 `hook 미구현🔧` 마커도 실제(부분 구현)와 불일치.

## Issue166: hub 빈 live 세션 표시 토글 — live_session_show_empty (기본 숨김) ✅
* 목적: hub 활성 세션 목록에 명령(프롬프트)을 한 번도 받지 않은 "시작도 안 한 세션"(카드에 `-` 로 표시되는 빈 live 세션)이 노출됨. VSCode 가 세션 종료 후에도 `claude` 프로세스를 살려두면 `live_pid` 생존(force_live)으로 계속 떠 카드가 `-` 행으로 도배된다. 사용자별로 보고 싶을 수도, 가리고 싶을 수도 있으므로 설정 토글을 추가하되 기본값은 숨김으로 한다.

## Issue164: fpm 공개 미러 내용 기반 secret 가드 — gitleaks scan + 신규 디렉토리 게이트 ✅
* 목적: Issue163 에서 드러난 두 구조적 갭 차단. (1) `exclude[]`(파일 denylist)이라 신규 최상위 디렉토리가 자동 미러 포함(`resource/`·`keyboard-maestro/` 누락 원인). (2) `personal_guard` 가 경로 매칭 전용이라 in-content 시크릿(토큰·키·UUID)을 못 잡음.
* depends: Issue163 (전제 충족)

## Issue165: hub_setting 설치 기본값 템플릿화 — hub_setting_org.yml 분리 + install.sh 적용 + publishable 제외 ✅
* 목적: `data/hub_setting.yml` 이 개인 환경값(bind_host·advertise_host IP 등)을 담은 채 publishable exclude 누락으로 공개 미러 fpm 에 동기화됨. 신규 설치자는 원작자 환경값이 박힌 yml 을 받게 됨. 설치용 기본값 템플릿(default_browser: chrome·browser_tab_reuse: true)을 분리하고, install.sh 가 부재 시 복사, 개인 hub_setting.yml 은 미러 제외. Issue162 에서 chrome+탭재사용 채택했으므로 설치 기본값도 chrome.
* depends: Issue162

## Issue162: hub 렌더 브라우저 탭 재사용 — fpm-browser-open.sh helper + fhub CLI + hook 치환 ✅
* 목적: Firefox 는 hub 렌더 시 매번 새 탭을 생성하여 무한 누적(`/hub` 대시보드 + 응답별 htm-doc). Firefox 는 tab 제어 사전 부재로 재사용 불가, Chrome/Safari/Edge 는 AppleScript 로 기존 탭 재사용 가능. Keyboard Maestro 매크로 "fPm hub page Open" 의 탭-재사용 로직을 CLI/hook 공용 helper 로 포팅하여 탭 누적 제거 + iTerm 등 터미널에서도 동일 동작(`fhub`) 제공.

## Issue163: fpm 공개 미러 사적 아티팩트 유출 차단 + 공개 전 보안 감사 ✅
* 목적: `noteForHuman.md` 의 host 하드웨어 UUID, `resource/`(Apple 인증서·프로비저닝 프로파일·device UDID·CSR), `keyboard-maestro/`(머신 KM 매크로)가 공개 미러 fpm 으로 동기화되고 있었음. `publishable-policy.yml` exclude 가 `Servers.md`/`Projects.md` 만 막고 디렉토리 단위 사적 아티팩트는 누락(갭). sanitize 는 `host.local` 만 있고 bare 하드웨어 UUID 미커버. personal_guard 는 **경로 매칭 전용**이라 in-content UUID 차단 불가. fpm 공개 전환 예정이므로 (1) 향후 재유출 차단(예방) + (2) 미러 히스토리 purge + (3) 공개 전 전수 보안 감사 수행.

## Issue161: fpm 클린 설치 — uninstall.sh + install.sh --clean (백업 후 제거) ✅
* 목적: fpm 설치 흔적(셸 rc 의 fpm 블록 + `~/.info/__pmBasePath.txt`)을 백업 후 제거하는 자동화가 없음. 클린 재설치 시 사용자가 zshrc 를 수동 편집해야 해 오류·누락 위험. `uninstall.sh` primitive + `install.sh --clean` 플래그로 멱등 클린 재설치를 제공하고, 기존 흔적은 `_doc_work/z_done/fpm-uninstall-<ts>/` 로 백업.
* 목적: `/hub` 페이지의 활성 세션·dashboard·hub 문서 섹션이 항상 전체 펼침 고정이라 세션·문서가 많으면 스크롤 부담. 섹션별로 헤더만 남기고 접었다 펼 수 있는 토글 제공.

## Issue159: hub 활성세션 카드 순서 적용 옵션 ✅
* 목적: `/hub` 활성 세션 목록이 `updated_age` 최근갱신순 고정 정렬이라 세션 활동마다 행·카드가 점프함. 정렬 방식을 `hub_setting.yml` 옵션으로 선택 가능하게 함.

## Issue157: ~/.claude(prj3) fpm SCAR 업데이트 → fpm-core 번들 동기화 ✅
* 목적: prj3(~/.claude) = fpm SCAR 정본. render_target(Issue141)·peacock 실색+emoji 스킴(Issue157)·dashboard 갱신이 번들(plugins/fpm-core)에 미반영(구버전)된 것을 동기화. 사용자 선택 = **이식성 보존 머지(B)** — 번들의 `${CLAUDE_PLUGIN_ROOT}` 경로 손실 없이 내용만 반영.

## Issue156: hub 서버 페이지(`/hub`·issue-tree·view 등) `<head>` 에 🎯 favicon 추가 ✅
* 목적: Issue155 는 Claude 생성 `.htm`(hook 경유)만 favicon 부여 → 사용자가 보는 `http://127.0.0.1:9876/hub` 등 **server.py 직접 서빙 페이지**는 여전히 회색 globe 아이콘. server.py HTML head 에 동일 favicon 삽입하여 모든 hub 서버 페이지 탭에 🎯 표시.

## Issue148: dashboard 9개 시나리오 재현 키트 — `_doc_work/board/s1~s9/` (재현 프롬프트 + fixture) ✅
* 목적: noteForHuman.md `## board (c모드)` 의 9개 dashboard 시나리오(L190~230)를 향후 재현·재테스트할 수 있도록 시나리오별 구현 프롬프트(트리거)와 부속 fixture(queue.yaml/dash.yaml/시계열 샘플)를 `_doc_work/board/s{N}/` 에 영속 보존. Issue147(시나리오 3 렌더 강화) 완성 후속.

## Issue148_1: s1 대량 순차 파일 생성 재현 검증·반영 ✅
* 목적: `board/s1/` (build-1000) 키트 실제 실행으로 동작 실증 + 의견 반영하여 README·fixture 업데이트

## Issue148_2: s2 크로스 프로젝트 위임 재현 검증·반영 ✅
* 목적: `board/s2/` (cap35v2 cross-prj DAG) 키트 실제 실행으로 동작 실증 + 의견 반영

## Issue148_3: s3 Issue tree (의존 트리) 재현 검증·반영 ✅
* 목적: `board/s3/` (issue-tree-sample, Issue147 렌더 강화 산출) 키트 실제 실행으로 동작 실증 + 의견 반영

## Issue148_4: s4 nPTiR 파이프라인 재현 검증·반영 ✅
* 목적: `board/s4/` (s4verify 선형 큐) 키트 실제 실행으로 동작 실증 + 의견 반영

## Issue148_5: s5 /goal 마일스톤 진행도 재현 검증·반영 ✅
* 목적: `board/s5/` (s5verify 마일스톤 큐) 키트 실제 실행으로 동작 실증 + 의견 반영

## Issue148_6: s6 Task 병렬 관리 재현 검증·반영 ✅
* 목적: `board/s6/` (tasks-parallel, 신규 fixture) 키트 실제 실행으로 동작 실증 + 의견 반영

## Issue148_7: s7 주기적 모니터링 재현 검증·반영 ✅
* 목적: `board/s7/` (jm1-모니터링 골격) 키트 실제 실행으로 동작 실증 + 의견 반영

## Issue148_8: s8 정기 작업 스케줄 재현 검증·반영 ✅
* 목적: `board/s8/` (schedule-tasks, 신규 fixture, Issue118 일원화) 키트 실제 실행으로 동작 실증 + 의견 반영

## Issue148_9: s9 대용량 전송 + SVG 시계열 재현 검증·반영 ✅
* 목적: `board/s9/` (scp-final-demo + history.sample.tsv) 키트 실제 실행으로 동작 실증 + 의견 반영

## Issue155: hub 렌더 HTML `<head>` 에 🎯 이모지 SVG favicon 추가 ✅
* 목적: hub 자동 렌더 `.htm` 문서에 favicon 이 없어 Firefox 탭이 기본 회색 문서 아이콘으로 표시됨. 별도 `.ico` 파일·네트워크 요청 없이 인라인 SVG data URI 로 🎯 이모지 탭 아이콘을 부여하여 hub 문서 탭을 시각적으로 식별 가능하게 함.

## Issue153: `data/hub_setting.yml` render_target·advertise_host 키 신설 — yml 한 줄로 모든 ..show hub 경유 표시 SSOT ✅
* 목적: yml **한 줄 셋팅으로 모든 `..show`(+자동 hub 모드)를 hub 서버 경유로 표시**하도록 전환하는 데이터 키를 `data/hub_setting.yml`(렌더 정책 SSOT)에 추가. 개별 SCAR 수정 없이 단일 hook(`fpm-hub-trigger.sh`)이 이 키를 grep 하여 모든 렌더에 일괄 적용. 본 이슈 스코프 = **키 신설(데이터 자리 선점)**. 실제 분기 로직은 hook → 글로벌 Issue141(차후, 같이 되면 좋음).
* 구현 명세:
    - `server.py` 미사용 (hook 전용 키) — `bind_host` 처럼 주석에 소비처(`~/.claude/hooks/fpm-hub-trigger.sh`) + 글로벌 Issue141 명시
    - 인프라 재확인 완료: `services/hub/server.py` `/view`·`/htm-doc` 라우트, `_path_ok` confinement, `bind_host` 0.0.0.0, IP allowlist 이미 존재 → 신규는 키(본 이슈) + 글로벌 hook 분기(Issue141)뿐
    - 키 추가 완료. 기본값 `local-open` 유지 — 동작 무변경, `hub` 전환 시 hook(글로벌 Issue141) 구현 후 실효
    - 분석 문서: `_doc_work/z_htm/hub_htm_20260610_175702_a_remote-render-setting.htm`, `hub_htm_20260610_182717_a_render-target-mechanism.htm`

## Issue154: fpm 설치·함수 bash 호환 포팅 — zsh/bash 양쪽 지원 ✅
* 목적: 설치 프로세스(`install.sh`)가 `~/.zshrc` 만 하드코딩하고, 네비게이션 함수(`sh/fpm_function.sh`)에 zsh 전용 문법(`$match`·1-based 배열·`${=}`)이 다수라 bash 로그인 셸에서 fpm 이 동작하지 않음. 양쪽 셸 지원으로 포팅.
* depends: (없음)

## Issue152: dashboard 운영 정책 YAML 구동 — `data/board_policy.yml` SSOT + SCAR wiring ✅
* 목적: Mode C(dashboard) 운영 상수(갱신 주기·견고성 임계·sentinel 경로)가 글로벌 SCAR 스크립트 3종에 하드코딩되어 있어, 프로젝트 단위 튜닝이 불가하고 변경 시 글로벌 SCAR 수정이 필요. hub_setting.yml(서버측)의 dashboard 짝으로 `data/board_policy.yml`(클라이언트측 운영 상수 SSOT)을 신설하고, SCAR 스크립트가 이를 읽도록 wiring. 우선순위 `env > board_policy.yml > 스크립트 기본값`.

## Issue151: publishable 정책 YAML 구동 재설계 — `data/publishable-policy.yml` 데이터 SSOT + fpm-sync.sh YAML 구동 + 편집 스킬 ✅
* 목적: 정책 데이터(EXCLUDES·PERSONAL_RE·sanitize)가 `scripts/fpm-sync.sh` 에 **하드코딩**되고 doc 은 **서술만** → 공개 대상 변경 시 **코드+문서 이중 수정**·drift(Issue150 구현 중 실제 발생). 정책을 **머신 판독 YAML 단일 SSOT** 로 외부화 → "편집 1곳 → 엔진 자동 반영".

## Issue150: ___pm publishable 정책 문서화 — `_doc_arch/publishable-policy.md` SSOT (prj42 file-deployment-rules 패턴 참고) ✅
* 목적: ___pm 의 공개 미러(fpm/prj7) publishable 정책이 `scripts/fpm-sync.sh` 의 EXCLUDES·PERSONAL_RE·sanitize 에 **음성적(negative)으로만 묻혀** 있어 "publishable 이 무엇인가"를 단일 문서로 추적 불가. prj42(m2slide) 의 선언적 정책 문서 패턴(`.claude/rules/file-deployment-rules.md` — 허용/금지 패턴 표)을 **참고**하여 ___pm 에 publishable 정책 SSOT 문서를 신설. **prj42 읽기 전용 참고(무수정)**.

## Issue149: sh/ 공개화 단일화 — install 페이로드를 sh/fpm.sh 로 통합, 중복 shell/ 폴더 제거 ✅
* 목적: 설치 페이로드가 `shell/fpm-functions.zsh`(손수 sanitize 한 공개 subset)와 개인용 `sh/`(FPM_BASE 기반 전체 도구)로 이원화되어 이중 유지보수 부담 발생. FPM_BASE 리팩터(2026-06-09)로 sh/ 의 `/Users/user` 하드코딩이 이미 제거되어 sh/ 를 공개 미러 대상으로 승격 가능. sh/ 를 단일 SSOT 공개 페이로드로 통합하고 중복 shell/ 제거.

## Issue146: fpm 공개화 잔여 — 하드코딩 경로/호스트 일반화 + 최종 push + 미커밋 WIP 정리 ✅
* 목적: Issue140 종결 시 분리된 미완료분. 공개 fpm 의 잔여 sanitization·배포·미커밋 작업물 정리.

## Issue147: dashboard 시나리오 3 (Issue tree) 렌더 강화 — graph 위젯 노드에 상태 아이콘·이슈별 progress·current 마커 (show 모드 동등) ✅
* 목적: `..board` 이슈 의존성 트리(시나리오 3) dashboard 가 `..show` 모드보다 빈약 — show 는 ✅/🔴 상태 배지·이슈별 진행 상태 풍부, dashboard graph 위젯은 노드 박스(label+테두리색)만. 사용자 요청 "show 만큼(특히 진행 상태) 잘 보여주게".

## Issue140: ___pm → fpm 공개 전환 사전작업 (등록: 2026-06-06, 해결: 2026-06-09, commit: <commit>(폴더분리)·<commit>·<commit>·<commit>·<commit>, 공개 repo: github.com/Finfra/fpm) ✅
* 목적: 비공개 `___pm`(공개 핵심=hub)을 공개 프로젝트 `fpm`으로 전환. 이름 정리·개인정보 분리·풀스택 설치·MCP·SCAR marketplace·듀얼 라이선스 사전작업.
* 구현 명세:
    - Phase 0 rename: README/제목 fpm, 경로·식별자·폴더명 `___pm` 유지
    - Phase 1 개인정보 분리: `Servers.md`·`Projects.md` → gitignore + `*_org.md` 예제. `finfra-server-access.md`·`fapp-projects.md` → gitignore+rm
    - Phase 2 [폴더 분리 채택] in-place filter-repo 대신 `~/_git/__all/fpm`(prj7) fresh export + `git init`(이력 0, 민감정보 미포함) = `<commit>`. prj #7 등록. **공개 repo `github.com/Finfra/fpm` 라이브**(remote main `<commit>`)
    - fpm-sync 자동화: `scripts/fpm-sync.sh`(엔진 SSOT, 개인정보 2중 가드, forward/reverse 분기) + `install-fpm-hook.sh` + ___pm post-commit hook. `.claude/agents/fpm-sync.md` 에이전트. `sh/` 공개미러 제외(`<commit>`)
    - Phase 5 MCP: `mcp/server.py`(stdlib JSON-RPC 2.0, 5 도구) 검증 통과
    - Phase 3 설치: `shell/fpm-functions.zsh` + `install.sh` + `INSTALL.md`. Phase 6 marketplace: `.claude-plugin/marketplace.json` + `fpm-core`. Phase 7 라이선스: PolyForm Noncommercial + `COMMERCIAL.md`
    - Harness ___pm/fpm 구조 문서화(`<commit>`)
    - **잔여 → Issue146 분리**: 하드코딩 경로/호스트 일반화 + fpm 최종 push(local 1 ahead) + 미커밋 WIP(fpm-projects-sync 배선·sync-host·gitignore-policy)

## Issue141: hub 네트워크 접근 개방 — Servers.md 호스트 allowlist ✅
* 목적: host 등 Servers.md 등록 머신에서 host 의 hub(`:9876`)에 접근 가능하게. 안전 옵트인 설계(기본 127.0.0.1 유지)로 네트워크 개방.
* 구현 명세:
    - `_ip_allowed(ip)` = 루프백 무조건 허용 + `ip in ALLOWED_IPS`. `do_GET`/`do_POST` 상단 단일 전역 게이트로 통일(산재 14개 체크 → helper)
    - `_load_server_allowlist()` = `Servers.md` `check=O` 호스트 → `socket.gethostbyname` resolve, 실패 skip+log, 공개 호스트 경고 log. `HOST != 127.0.0.1` 개방 모드에서만 populate
    - 우선순위 `env HTM_SERVER_HOST > hub_setting.yml bind_host > 127.0.0.1`. 기본 미설정 시 `ALLOWED_IPS` 빈 set → 동작 변화 0
    - vendored `plugins/fpm-core/services/hub/server.py` 동기(PROJECTS_MD env 1줄 차이만 보존), SSOT `_doc_arch/hub_htm.md` "기본 차단 + 옵트인 allowlist" 모델로 갱신
    - 검증: 기본 모드 회귀 통과(loopback `healthz`/`hub` = 200, ALLOWED_IPS 기본 빈 set, 전역 게이트 14+ 적용, 두 사본 sync, syntax OK). `HTM_SERVER_HOST=0.0.0.0`+host→host `/hub` 200 은 원격 머신 필요한 옵트인 수동 검증으로 분리

## Issue145: fpm 셸 자산 부트스트랩 분리 + FPM_BASE 포터블화 (self-detect + self-healing 캐시) ✅
* 목적: fpm 셸 자산을 설치 위치 무관(`$FPM_BASE` 기반)하게 만들어 `~/_git/___pm`·`~/_git/__all/fpm` 어디 설치해도 동작. 단일 진입 `fpm.sh` 부트스트랩화 + 함수/alias 분리. 부수적으로 iterm-bg alias 미로드 버그 수정.
* 구현 명세:
    - 변경: `sh/{fpm.sh, fpm_function.sh(신규), fpm_aliases.sh(신규)}`, `update-iterm-bg`, `fpm-projects-sync`, `~/.zshrc`, `~/.bashrc`, `CLAUDE.md`, `.gitignore`(생성물 무시)
    - bash 안전: 부트스트랩 zsh-ism `${(%):-%x}` 을 `eval` 로 감싸 bash 파싱 단계 syntax error 회피
    - 검증: `FPM_HOME` 잔여 0 / zsh self-detect / 캐시 생성 / env override(`__all/fpm`) / 실제 `.zshrc` 로드(cdf·iterm-bg alias) / py_compile — 전부 OK
    - 후속(미적용): KM 매크로(`keyboard-maestro/cdf.kmmacros`) 캐시 소비 배선 / `install.sh` 가 `export FPM_BASE=$REPO_DIR`+`sh/fpm.sh` 기록(= `sh/` 공개미러 포함 결정 + fpm-sync `sh/` 제외 정책 재검토) / legacy `~/.info/__pmBasePath.txt` 삭제

## Issue144: fpm-core 번들 SCAR·hook 접두어 → fpm- 전면 통일 + 참조 동기 ✅
* 목적: 마켓플레이스 번들(`plugins/fpm-core/`) 자산 접두어를 fpm- 으로 통일 → 테스트 PC clean install/uninstall(glob `~/.claude/**/fpm-*`). 글로벌 loose 원본 측은 prj3 `~/.claude` Issue138 쌍작업.
* depends: prj3#Issue138 (글로벌 측 — 쌍작업)

## Issue143: hub b모드(ask 폼) → 짝 a모드(show 렌더) 페이지 링크+iframe 임베드 (등록: 2026-06-08, 해결: 2026-06-08, fix: `<commit>` + 런타임 `~/.claude/hooks/ask-intercept.sh`(repo 외부, 동일 edit 반영)) ✅
* 목적: `..show`(a모드 렌더) 직후 `..ask`(b모드 폼)로 이어지는 흐름에서, 폼 페이지에 짝이 되는 직전 show 페이지로 가는 경로가 없어 수동 추적해야 했던 문제 해결. 폼에서 직전 show 페이지를 임베드로 한번에 보고 링크로도 이동 가능하게 함.
* 구현 명세:
    - `plugins/fpm-core/hooks/ask-intercept.sh` python 블록: 페어 a-page 계산(후보 폴더 합집합에서 `hub_htm_*_a_*.htm` 중 mtime 최신 1개) + `<title>` 추출 → 접이식 `<details open>` iframe + 새탭 링크 스니펫 생성, deny-reason 지침에 주입(페어 없으면 생략·무해)
    - 런타임 `~/.claude/hooks/ask-intercept.sh` 동일 edit 반영(유일 차이 line 221 `CLAUDE_PLUGIN_ROOT` 분기 보존)
    - 검증: bash -n + embedded python ast.parse OK(양쪽) / 두 파일 diff = line 221 만 / 격리 실행으로 mtime 최신 a-page(`_202212_a_gitignore-doc`) 페어 검출 + `<title>` "gitignore 정책 문서화 완료" 추출 + file:// 스니펫 생성 확인

## Issue142: hub htm-server launchd 자동시작 실패 — plist 경로 stale ✅
* 목적: 로그인 시 hub htm-server(`:9876`)가 자동 기동되지 않아 매번 수동 `hub start` 필요했던 문제 해결. launchd plist 의 server.py 경로가 옛 경로(`services/htm-server/`)를 가리켜 RunAtLoad 가 exit 2(파일 없음)로 반복 실패한 것이 원인.
* 구현 명세:
    - plist 경로 `services/htm-server/server.py` → `services/hub/server.py` 교정
    - stale 수동 서버 kill → `launchctl unload`/`load -w` 재로드 → RunAtLoad 정상 기동
    - 검증 통과: `launchctl list` PID 23717·exit 0, healthz=200, err log `started on http://127.0.0.1:9876 (pid=23717)` (에러 종료)

## Issue139: debug_TECH.md 트러블슈팅 로그 종결 (회고) — openclaw keychain 중복 토큰 + htm-server 좀비 카드 ✅
* 목적: `_doc_work/debug_TECH.md`(기술 트러블슈팅 누적 로그, 재발 방지용)에 기록된 2건의 디버깅 작업을 회고 이슈로 명시 종결. 구성 fix는 이미 다른 이슈·운영 조치로 랜딩됨 — 본 이슈는 추적성 확보용 회고 기록. (요청 출처: ___pm `/issue-closer debug_TECH`, 2026-06-04)
* 구현 명세:
    - 산출물: `_doc_work/debug_TECH.md` (2건 트레이스 — 증상·진단 경로·근본 원인·조치·재발 방지·검증 명령). 트래킹 시작 커밋 `<commit>`(Issue91 services/htm-server→hub rename 시 흡수).
    - (1) 조치=운영(코드 외): 옛 게이트웨이 kill + launchd bootstrap, keychain 옛 entry `security delete-generic-password` 1회(2회 시 fresh도 삭제), `openclaw secrets reload`. 재발 방지=`/login` 후 1회 삭제+expiresAt 검증.
    - (2) 코드 fix는 좀비 계열 이슈로 분리 랜딩: Issue136(빈 live 세션 cwd당 1개 dedup, `<commit>`)·Issue137(🧟 좀비 킬러 버튼, `<commit>`·`<commit>`)·Issue138(worker_pid stale 강등·활성세션, `<commit>`). 서버측 3-layer(heartbeat 신선도 게이트 + `worker_pid` fallback + 파서 5곳 추출)가 최종 방어선.
    - 검증: 구성 fix 전부 각 이슈에서 검증 완료(좀비 카드 0개 영구 제거 curl 확인). 본 회고는 코드 변경 0 — Issue.md 문서 기록만.

## Issue138: dashboard `/view` UI 4건 — stop 동작·디자인 통일·강제종료/done전환·활성세션 버튼 ✅
* 목적: dashboard read-only `/view`(Issue35)가 hub `/view`(ask 폼)·`/hub` 와 디자인 상이 + 컨트롤 부재. done 후 runner pid dead 라 stop 버튼 무의미하고 잔존 tmux window 종료 수단이 보드에 없음. (요청 출처: ___pm hub Mode C 테스트 중 발견, 2026-06-03, Issue131 후속)
* 구현 명세:
    - `_handle_view`: `_serve_dash_inline(abs_path, cwd, token)` 로 cwd/token 전달 (control wiring).
    - `_serve_dash_inline`: canonical 헤더(📁 배지·🛰 활성세션·🗂 Hub·닫기) + 컨트롤바(🔄 refresh·⏹ stop·✕ 종료) + JS(dashStop/dashKill/dashRefresh → `/control`). runner pid dead 감지(`_pid_alive`) → status 보정 + pid `⚠ 종료됨` 배지 + `ctl-note` + stop 숨김·"✕ 종료(window 정리)" done-스타일 노출. status≠terminal 시 `interval`(2~60s clamp) 자동 reload.
    - `_handle_control`: kill_pane 분기를 registration 게이트 **앞**으로 이동 — window kill 은 pid liveness 무관(window_name 대상). cwd+token 인증 유지. window 부재 시 graceful 200 `already_gone`.
    - 변경 파일: `services/hub/server.py` (+161/-31, 3지점). dashboard agent(글로벌 SCAR) 변경 없음.
    - 복잡도: 중간 (파일 1, 렌더러 확장 + control 게이트 수정).

## Issue137: hub 🧟 좀비 킬러 버튼 — 빈 live 세션 일괄 종료 + 새로고침 ✅
* 목적: Issue136 dedup 은 빈 세션 *표시*를 cwd당 1개로 줄일 뿐, 좀비 프로세스 자체는 살아남아 카드가 잔존. 매번 수동 `ps`+`kill` 하던 좀비 정리를 hub UI 버튼으로 1클릭화. (요청 출처: ___pm hub 운영 중, 2026-06-03, Issue136 후속)
* 구현 명세:
    - **서버**: `POST /kill-empty-live`(`_handle_kill_empty_live`, 127.0.0.1 trust). sessions 스냅샷 순회 → `content_type=="live"` + `live_label` 빈 세션만 → `live_pid` `os.kill(SIGTERM)` graceful + `sessions.pop` + `_live_dismiss_add`(재등록 차단). titled live·dashboard 는 제외(오살 방지). 라우팅 `/clear-done` 옆.
    - **UI**: 활성 세션 섹션 헤더에 `btn-zombie`(🧟 좀비 킬러) + `killEmptyLive()` JS(confirm→fetch→`toast`→`reload`). CSS `.section-title .btn-zombie`(녹색). 바인딩 `rescanBtn` 옆.
    - 변경 파일: `services/hub/server.py`(+74, 6개 지점: 라우팅·핸들러·헤더HTML·CSS·JS함수·바인딩).
    - 복잡도: 중간 (파일 1, endpoint+UI 신설, kill 정책 = titled 보존·SIGTERM graceful 설계 결정).

## Issue136: hub ✕(dismiss) 무력 — 좀비 프로세스 빈 세션 부활, cwd당 1개 표시로 우회 ✅
* 목적: 활성 세션 카드 ✕(dismiss) 버튼이 여전히 "안 됨"으로 체감. Issue135 tombstone 도입 후에도 빈 세션("-")이 카드에 도배됨. 진짜 원인 재확인 + 근본 차단 불가 시 노이즈 우회. (요청 출처: ___pm hub 운영 중 발견, 2026-06-03, Issue135 후속)
* 구현 명세:
    - **빈 세션 dedup**: `_collect_live_sessions` `results.sort()`(updated_age 오름차순) 직후, `content_type=="live"` + title 빈 세션을 `cwd_hash` 당 가장 최근 1개만 남기고 collect 단계에서 제외. title 있는 live·dashboard 세션은 전부 유지(정보 손실 0).
    - 변경 파일: `services/hub/server.py`(+23).
    - 복잡도: 중간 (파일 1, "빈 세션 표시 정책" 설계 결정 有 — kill vs 숨김, cwd당 1개 vs N개).

## Issue133: design-doc(_doc_arch 적용 스킬) 갱신 시 연결 SCAR 동기 갱신 검증·보강 ✅
* 목적: `/design-doc` 으로 `_doc_arch/` 영속 설계 문서를 갱신할 때, 그 설계와 연결된 SCAR(command/rule/skill/agent) **본문도 함께 동기 갱신되는지** 확인. 설계↔구현 동기 갱신 절차 부재(gap) 검증·보강안 도출. (요청 출처: ___pm 이슈후보, 2026-06-03)

## Issue135: hub live 카드 dismiss 후 부활 — dismiss tombstone 부재 ✅
* 목적: 활성 세션 카드의 ✕(dismiss) 버튼이 "동작 안함"으로 체감됨. 디버그 결과 dismiss 핸들러·JS·검증은 정상(로그 `22:48:58`·`22:49:04` `pruned` 성공). 진짜 원인 = dismiss 는 `sessions.pop((h,sid))` 만 하고 **재등록 차단 tombstone 이 없어**, VSCode 확장 native 프로세스가 살아있는 한(Issue132 게이트 `_pid_alive(live_pid)` 영구 통과) 다음 hook register/heartbeat 가 sessions 를 재생성 → 카드 부활. (요청 출처: ___pm hub 운영 중 발견, 2026-06-03, Issue132 후속 결함)
* 구현 명세:
    - **tombstone 신설**: `LIVE_DISMISSED`(`data/hub/live-dismissed.json`, dict `{h}|{sid}`→ts) + `LIVE_DISMISS_TTL=120s`. 헬퍼 `_load_live_dismissed`(TTL lazy purge)·`_save_live_dismissed`·`_live_dismiss_add`. HTM_CLEARED/DASH_CLEARED 와 대칭.
    - **dismiss 핸들러**(`_handle_session_dismiss`): `sessions.pop` 후 `_live_dismiss_add(h,sid)` 기록(pop 여부 무관 — 이미 재등록 직후일 수 있음).
    - **collect live 분기**(`_collect_live_sessions`): 시작 시 `_load_live_dismissed()` 1회 스냅샷 → `{h}|{sid}` tombstone hit 시 `continue`(표시 제외, sessions 는 유지). TTL 만료 후 자동 해제(살아있는 세션 정상 복귀).
    - 변경 파일: `services/hub/server.py`(+59), 신규 `services/hub/test_live_dismiss_tombstone.py`.
    - 복잡도: 중간 (파일 1+1, tombstone 설계 결정 有 — TTL·키 단위·표시제외 vs pop)

## Issue134: hub 활동 피드 갑자기 사라짐 — persist_feed race condition ✅
* 목적: 활동 피드(15 live session 화면)가 간헐적으로 전체 사라짐. 사용자 추측은 "feed_limit(300) 초과 시 전체 삭제"였으나 실제 원인은 다름 — `deque(maxlen=300)`+`appendleft` 는 정상(로그 `feed=300` 유지). 진짜 원인 = `persist_feed` 의 동시 쓰기 race 로 `hook-feed.json` 손상 → 재시작 시 `load_feed` 파싱 실패 → 피드 전체 0. (요청 출처: ___pm hub 운영 중 발견, 2026-06-03)
* 구현 명세:
    - **루트 원인**: `ThreadingHTTPServer` 다중 요청 스레드가 `persist_feed` 동시 호출 → 모두 공유 경로 `hook-feed.json.tmp` 에 `open(w)`/write → 내용 혼입(JSON `Extra data`) + `os.replace` race(`Errno 2`). 손상 파일은 재시작 `load_feed` `json.load` 예외 → feed 전체 손실(로그: `22:01:15 persist_feed failed`, `22:02:32 load_feed failed: Extra data` → `feed=1` 재축적).
    - **수정 A (persist_feed)**: tmp 경로를 `{HOOK_FEED_FILE}.{pid}.{tid}.tmp` 로 유니크화(스레드간 충돌 제거) + snap·write·replace 전체를 `feed_lock` 으로 직렬화(원자화). 모든 `persist_feed()` 호출부가 lock 밖임을 검증(deadlock 없음).
    - **수정 B (load_feed)**: `json.load` 단계 분리 — 손상 시 `.corrupt` 백업 후 빈 상태로 진행(추가 손실 방지 + 사후 분석).
    - 변경 파일: `services/hub/server.py` (`persist_feed`, `load_feed`).

## Issue132: hub 빈 live 세션 카드 잔존 수정 — session_end prune + 수동 dismiss ✅
* 목적: 활성 세션 카드 중 빈 카드(제목 "-", 프롬프트 전 세션)가 세션 종료 후에도 영구 잔존. 원인 = (1) `_handle_hook_event` 가 `event=session_end` + `sid` 를 받고도 피드에만 적재하고 `sessions` 테이블을 prune 하지 않음(SessionEnd 훅 무효), (2) VSCode 확장이 세션 UI 종료 후에도 `claude` native 프로세스를 살려둬 유일 게이트 `_pid_alive(live_pid)` 가 영원히 통과. (요청 출처: prj `.claude` 작업 중 발견, 2026-06-03)
* 구현 명세:
    - **A — session_end prune**: `_handle_hook_event` 에서 `event=="session_end"` 이고 `sid` 존재 시 `sessions.pop((cwd_hash(cwd), sid))` + `persist_sessions()`. SessionEnd 훅(`~/.claude/hooks/hub-session-end.sh`)을 실효화. 프로세스 kill 아님 — 등록 해제만.
    - **B — 수동 dismiss**: 신규 엔드포인트 `POST /session/dismiss?cwd=&sid=&token=` (`_handle_session_dismiss`) — `validate(cwd,token)` 후 sessions entry 만 제거. live 카드(pid 없는 claude 세션)에 `✕ dismiss` 버튼(`dismissSession()` JS) 노출 — `confirm` 후 fetch, 프로세스 미종료. dashboard kill 버튼(`stopRunner`/`removeQueueDash`)과 분리.
    - 변경 파일: `services/hub/server.py` (라우팅 +`/session/dismiss`, `_handle_hook_event` prune 분기, `_handle_session_dismiss` 신규, 카드 렌더 dismiss 버튼, `dismissSession` JS).

## Issue131: hub 활성 세션 행 클릭 → VSCode 세션 탭 포커스 ✅
* 목적: 활성 세션 카드의 각 행이 Claude Code 세션(sid)에 대응하나, 클릭 시 프로젝트 폴더만 열려 특정 세션으로 이동 불가. 행 클릭으로 해당 세션 탭에 바로 포커스.
* 구현 명세:
    - 메커니즘: Claude Code extension URI `vscode://anthropic.claude-code/open?session=<sid>` (공식 문서 — 세션 탭이 열려 있으면 그 탭을 포커스). 제약: 세션이 현재 열린 VSCode 워크스페이스(cwd)에 속해야 함.
    - 서버 `_handle_open_session` (POST `/open-session`): localhost only + cwd 화이트리스트(open-project 동일) + sid 엄격 검증(`[A-Za-z0-9_-]{1,128}` — 셸/URI 주입 차단). `open -a "Visual Studio Code" <cwd>` 로 워크스페이스 전면화 후(0.4s) 세션 URI 호출.
    - 클라: 행 `<li>` 에 `data-sid`·`data-cwd`, `#live-grid` 클릭 핸들러에 세션 행 분기(more-toggle 다음·openProject 앞), `openSession()` fetch, hover 커서·title 툴팁(전체 제목).

## Issue129: hub 활성 세션 카드 표시 정리 — 명령 전 "-", 1행 ellipsis, 카드당 세션 행 상한 ✅
* 목적: 명령(프롬프트) 전 세션이 "claude · win 1" 로 표기되어 무의미, 긴 제목이 여러 줄로 흘러 카드 비대, 한 프로젝트 세션이 많으면 카드가 과도하게 길어짐.
* 구현 명세:
    - 명령 전 세션(ai-title·live_label 없음) → live 분기 `claude · win N` fallback 제거 → title None → 클라 `s.title || '-'`.
    - `.live-topic` CSS: `white-space:nowrap; overflow:hidden; text-overflow:ellipsis` (1행 ellipsis, 전체는 title 툴팁).
    - `live_session_limit`(hub_setting.yml, 기본 6) — `HUB_SETTING_DEFAULTS` 등록 + `/dashboards` 페이로드 전달. 카드(프로젝트 그룹)당 세션 행 상한. (초과 시 "외 N개 더" → Issue104 확장 연계)

## Issue127: hub 활성 세션 카드 제목 — VSCode 탭 제목(ai-title) 동기화 ✅
* 목적: 카드 제목이 프롬프트 첫 줄(`live_label`)이라 VSCode 탭 제목(`aiTitle`, AI 생성 짧은 요약)과 달랐음. 둘을 일치.
* 구현 명세:
    - SSOT: 세션 JSONL 의 `{"type":"ai-title","aiTitle":...,"sessionId":...}` = VSCode 탭 제목.
    - `_session_ai_title(cwd, sid)`: JSONL 경로 해석(`_resolve_session_jsonl` — cwd 비영숫자→`-` 인코딩 직접 경로 + glob fallback, sid 캐시) → 최신 ai-title reverse-scan(EOF부터 256K→1M→8M 청크 확장) → mtime 캐시(doc_cache). live 분기에서 `aiTitle` 최우선 → `live_label` → win.

## Issue104: hub 활성 세션 카드 "외 N개 더" 클릭 → 카드 확장 ✅
* 목적: Issue129 의 `live_session_limit` 초과분 "외 N개 더" 요약 행이 `data-sid` 없는 plain `<li>` 라 클릭 시 카드 fallback 으로 **VSCode 가 열림**(의도치 않음). "외 N개 더" 클릭 시 숨긴 세션 행을 펼쳐 카드 확장.
* 구현 명세:
    - `renderLiveSessions`: 초과 행을 잘라내지 않고 `live-hidden` 클래스로 전체 렌더(기본 `display:none`). 요약 행 `live-more`(`data-more` 카운트). 카드 cwd 가 `expandedCards` Set 에 있으면 `expanded` 클래스.
    - 5초 `reload()` 재렌더에도 확장 유지: 전역 `expandedCards` Set 으로 cwd 추적·재적용.
    - `#live-grid` 클릭 핸들러: `.live-more` 분기 추가(session row·openProject 보다 우선) — `expanded` 토글 + Set 갱신 + 라벨 `외 N개 더 ▾` ↔ `접기 ▴`.
    - CSS: `.live-item.live-hidden{display:none}`, `.card.live.expanded .live-item.live-hidden{display:flex}`.

## Issue103: hub render-only htm 헤더 `📁{프로젝트명}` 배지 클릭 → VSCode 열기 (cdfv) 미구현 ✅
* 목적: render-only `.htm`(file://) 헤더의 `📁{프로젝트명}` 배지가 plain `<span>` 이라 클릭해도 해당 프로젝트를 VSCode 로 열지 못함(cdfv 효과 부재). `/hub` 페이지 활성 세션 카드는 Issue101 에서 클릭→VSCode(`/open-project`)가 동작하나, 생산되는 htm 문서엔 미반영. 양쪽 일관성 확보.
* 구현 명세:
    - `~/.claude/commands/hub.md` 헤더 섹션: `<span class="proj-badge">📁 {프로젝트명}</span>` → 클릭 가능 `<a class="proj-badge">` 로 변경. inline `onclick` 에서 `fetch('http://127.0.0.1:9876/open-project', {POST, body:{cwd:'{프로젝트 절대경로}'}})` 호출. 성공 무음(VSCode 가시 open), 실패 `alert` fail-loud. `cwd` 절대경로 임베드 지시 추가, `.proj-badge { cursor: pointer }`.
    - 기존 인프라 재사용: 서버 `POST /open-project`(server.py:2557, Issue42) — `{cwd}` 화이트리스트(Projects.md ∪ 레지스트리) 검증 후 `open -a "Visual Studio Code" <cwd>`. `_send_json` 의 `Access-Control-Allow-Origin: null` → file://(origin null) cross-origin fetch 허용. 서버 코드 변경 0.
    - `_doc_arch/hub_htm.md` `/open-project` 섹션에 render-only htm 배지 호출처 명시.

## Issue97: Dashboard SCAR 기본조건 + noteForHuman 시나리오 1~8 전수 검증 ✅
* 목적: dashboard SCAR(agent + runner/supervisor/queue-runner + hub) 기본조건 5가지 + noteForHuman 시나리오 1~8 을 라이브 검증해 완성도 확정.

## Issue102: hub htm 카드 "열기" 링크 깨짐 — `/view`·`/htm-doc` 가 `.htm` 확장자 거부 ✅
* 목적: htm 스킬(Issue123)이 `hub_htm_*.htm` 확장자로 문서를 쓰는데, hub 서버의 `/view`·`/htm-doc` 핸들러는 `.html` 확장자만 허용 → 카드 "열기" 클릭 시 `{"error": "extension not allowed"}` 403 반환. 양끝 확장자 정책 불일치 해소.
* 구현 명세:
    - `_handle_view`(L3245)·`_handle_htm_doc`(L3206) 확장자 체크 `endswith(".html")` → `endswith((".html", ".htm"))`
    - `.htm`/`.html` 둘 다 `text/html` content-type serve (기존 헤더 그대로)

## Issue101: hub 활성 세션 카드 간소화 + 클릭 시 VSCode 열기 ✅
* 목적: 활성 세션(📡) 카드가 sid/SSE subs/cwd 등 너무 자세함. 프로젝트 제목과 간단 내용만 `:` 로 구분해 한 줄로 노출하고, 카드 클릭 시 cdfv(아이콘 클릭) 효과처럼 해당 프로젝트를 VSCode 로 열기.
* 구현 명세:
    - 로직: card div 에 `data-cwd` + hover 시각화, body 를 colon 라인(live-line/live-prj/live-sep/live-topic)으로 교체. live-grid 위임 click 핸들러 추가 (버튼/링크 closest 시 무시)
    - 검증: hub restart 후 서빙 HTML 에 `data-cwd`·`live-prj`·`live-grid 위임 핸들러`·`card.live[data-cwd]` CSS 모두 무결 확인. py_compile OK

## Issue100: hub important_events R2 — 죽은 세션 wait 가 영구 critical 칩으로 부활 ✅
* 목적: PM Hub 헤더 빨간 칩에 `htm-server — 응답 1311분 대기`, `__capture_previous — 2655분`, `test1 — 3148분` 등 22~52h 된 유령 "요청 필요" 칩이 계속 부활. UX 신뢰 저하 (Issue92 htm tombstone 의 important_events 판 변종).

## Issue99: hub live 카드 중복·열기 깨짐 — 서버 pid 계약 강제 + dedup + 열기 링크 제거 ✅
* 목적: Issue98 배포 후 사용자 보고 — tmux 1창인데 hub live 카드 2개, 각 "열기" 동작 안 함.

## Issue98: 모든 claude 세션을 hub live 카드로 자동 등록 — 서버측 ✅
* 목적: hub `_collect_live_sessions` 는 Mode C dashboard 세션만 📡 활성 세션 카드로 노출. tmux pm window 1 같은 일반 claude dev 세션은 카드 미생성·활동 피드(cwd 단위)로만 표현됨. 일반 세션도 per-window live 카드로 노출.
* depends: 글로벌 ~/.claude#Issue121 (SessionStart 훅 — 생산자. 서버측 본 이슈와 분리)

## Issue95: dashboard 삭제 후 자동 부활 — 3채널 tombstone (feed / orphan disk / live session) ✅
* 목적: hub dashboard 카드 "정리"·`/control action=remove`로 삭제했는데 서버 재시작 후 같은 dashboard 항목이 부활. Issue92(htm) tombstone 패턴의 dashboard 대칭 적용.

## Issue96: `_build-1000` 윈도우가 hub 대시보드에 표시되지 않음 ✅
* 목적: tmux pm 세션에 `_build-1000` 윈도우 존재. 설계상 `_<topic>` window는 dashboard unit. hub 웹 대시보드에 카드로 표시되지 않음.

## Issue94: tmux 기반 dashboard 에이전트/커맨드 구현 ✅
* 목적: Issue93 설계(`hub_dashboard_tmux_design.md`) 기반으로 agents/dashboard.md, commands/dashboard.md 재구현. HTTP/SSE 코드 제거 후 tmux send-keys/capture-pane 기반 단순화

## Issue93: Dashboard 설계 전환 HTTP/SSE → tmux window 매칭 ✅
* 목적: noteForHuman.md 시나리오 1~7 (Dashboard 모니터링) 구현 가능하게 설계 단순화. HTTP/SSE 복잡도 제거 → 로컬 tmux window 1:1 매칭

## Issue92: htm 목록 clear 후 오래된 내역 부활 (orphan 디스크 파일 tombstone 누락) ✅
* 목적: PM Hub htm 문서 목록에서 "최신 12개만 남기기"·"전체 제거"를 눌러도 아주 오래된 내역이 계속 살아남거나 부활. UX 신뢰 저하.

## Issue91: services/htm-server → services/hub/ 폴더 refactoring ✅
* 목적: "htm-server"는 원래 html/htm 렌더링 전용 서버였으나, 현재 dashboard 기능 포함 + PM Hub 통합으로 역할 확장. 폴더명을 "hub"로 통일하여 담당 기능 명확화. 글로벌 SCAR(~/.claude)에서 하드코딩된 참조는 별도 이슈(Issue109)로 이관.

## Issue87: hub 페이지 PM Hub 재구성 — 동적 헤더 + 중요 이벤트 패널 ✅
* 목적: 현재 hub 헤더는 정적 문구("📊 htm Hub — 전 cwd dashboard 통합")만 노출해 hub 를 열어도 *지금 무엇이 일어나고 있는지* 한눈에 안 보였다. PM Hub 로 재구성하여 (1) 헤더에 마지막 활동 피드를 동적 반영하고 (2) 사용자 주의가 필요한 항목을 중요도 점수화 모듈로 추려 헤더 하단에 노출.
* 구현 명세:
    - `server.py` `_compute_important_events()` 신규: 4규칙 점수화 — R1 워크플로우 판단 요청(waiting_approval, critical) / R2 응답 정체(AskUserQuestion·Notification 5분+ 미경신, warning, 30분+ critical) / R3 dashboard 카드 정리(done/stopped/stale/missing ≥5, info) / R4 htm 문서 누적(≥20, info). score 내림차순 반환
    - `_handle_dashboards` 응답에 `important_events` 키 추가
    - `HUB_HTML`: H1 동적 span(`#hub-headline`) + sub 동적(`#hub-important`), `renderHeadline()`·`renderImportant()` JS, 칩 CSS(critical/warning/info)
    - 판정 임계값 `IMPORTANT_RESPONSE_WAIT_SEC`(300)·`IMPORTANT_RESPONSE_CRIT_SEC`(1800)·`IMPORTANT_STALE_CARD_MIN`(5)·`IMPORTANT_HTM_DOC_MIN`(20) 모듈 상수로 분리

## Issue86: htm-server _session_supervisor_pid 가 sid 부재 시 dashboard 임의 선택 ✅
* 목적: dashboard 9능력 검증 캠페인(#7) 중 발견된 방어 부족. `/control action=remove` 의 supervisor_pid 해석 함수 `_session_supervisor_pid(h, sid)` 가 sid 빈 값이면 cwd_hash 내 dashboard 세션을 순회하다 **첫 번째** supervisor_pid 를 반환 — 다수 dashboard 동시 운영 시 의도와 다른(또는 stale) supervisor 를 가리킬 수 있음.
* 구현 명세:
    - `_session_supervisor_pid`: sid 빈 값 + cwd_hash 내 supervisor_pid 보유 dashboard 2개 이상이면 None 반환 (임의 선택 금지). 정확히 1개면 그대로 반환. sid 지정 시 세션 키 (h,sid) 유일 → 정확 해석.
    - `_handle_control_remove`: content ambiguous(None) 시 body `supervisor_pid` fallback 유지.
    - test_control_gate.py: ambiguous None + sid 지정 정확 해석 3건 추가 → 45 passed.
    - `hub_dashboard_protocol.md` `/control` body 스키마 action별 분리 + remove sid 권고 명시.

## Issue82: 세션 페이지 SSE 끊김 배지가 reload() 에 덮여 사라짐 ✅
* 목적: 세션 SPA(`/s/{h}/{sid}`)는 SSE 끊김 시 `es.onerror` → `setStatus('error'/'polling')` 으로 🔴/🟡 배지를 띄우나, polling fallback(`setInterval(reload,3000)`)이 3초마다 `reload()` 를 호출하고 `reload()` 성공 시 무조건 `statusEl.className='status connected'` + `'갱신: HH:MM'` 으로 덮어씀. 결과적으로 SSE 가 끊겨 polling 으로만 연명 중인 세션도 상단 status 가 connected 처럼 보여, 끝났거나 끊긴 세션을 사용자가 살아있는 것으로 오인.

## Issue83: hub 「정리」 버튼이 stale dashboard 카드를 여전히 못 지움 — Issue60 불완전 수정 ✅
* 목적: Issue60 이 `_is_clearable_status` 에 `stale` 을 추가해 stale 카드를 정리 대상에 포함시켰으나, `/clear-done`(`_handle_clear_done`)은 dash 파일을 `_read_dash_file` 로 raw 재읽기하여 디스크의 `status:` 필드(여전히 `running`)를 본다. Issue58 의 stale 강등은 `_handle_dashboards` 렌더 경로에서 dict 복사본에만 적용되고 파일·registry 에 기록되지 않으므로, clear 경로는 `stale` 을 영영 보지 못함. 결과: hub 카드에 `stale` 배지가 떠도 「🧹 정리」 버튼이 그 카드를 제거하지 못함. Issue60 은 clearable 집합만 넓혔을 뿐, stale 판정 자체가 clear 경로에 닿지 않는 비대칭을 고치지 못했다.

## Issue81: hub 활동 피드 「클리어」 버튼 무반응 — confirm() Firefox 차단 + 「20개만」 버튼 추가 ✅
* 목적: hub 우측 활동 피드의 「🗑 클리어」 버튼이 클릭해도 무반응. 핸들러가 네이티브 `confirm()` 게이트라 Firefox '추가 대화상자 차단' 시 즉시 `false` 반환 → fetch 미발생 (Issue79 와 동일 원인, feed-clear 만 누락됨). 추가로 피드 전량 삭제 대신 최신 일부만 보존하는 수단이 없어 「20개만 남기고 제거」 버튼 신설 요청.

## Issue80: htm Hub 활성 세션 카드 제목이 dashboard topic 대신 "dashboard" 고정 표시 ✅
* 목적: hub 활성 세션 섹션에서 dashboard 세션 다수가 모두 카드 제목 "dashboard"로 표시됨. 실제로는 서로 다른 dashboard(s5verify, goal3verify1 등)인데 카드 제목만으로 구분 불가.

## Issue78: dashboard runner 가 hub 등록 시 sid 누락 → 카드 "열기"가 dashboard SPA 아닌 raw YAML 표시 ✅
* 목적: hub dashboard 카드의 "열기" 가 dashboard SPA(`/s/{h}/{sid}`)가 아니라 `.dash.yaml` 원문(`/view?path=`)을 연다. ___pm#Issue75 가 서버측을 고쳐 `/register-doc` 가 `sid` 수신 시 SPA 라우트 `view_url` 생성하도록 했으나, 생산자(runner)가 `sid` 미전송이라 미발동 — Issue75 의 잔여 미완.

## Issue79: hub 정리 버튼 작동 안함 — confirm() 이 Firefox '추가 대화상자 차단'에 막혀 침묵 ✅
* 목적: hub 의 「htm 목록 전체 제거」·「최신 12개만 남기기」 버튼이 클릭해도 무반응. 핸들러가 `if (!confirm(...)) return;` 으로 게이트되는데, Firefox 가 한 페이지의 반복 대화상자를 '추가 대화상자 차단' 체크박스로 막으면 그 탭의 `confirm()` 은 UI 없이 즉시 `false` 반환 → fetch 미발생 → 버튼 침묵. 같은 게이트의 「done/stopped/stale 정리」도 동일 영향.

## Issue76: dashboard 통신 계약 문서 분리 — hub_dashboard_protocol.md 신설 ✅
* 목적: dashboard 에이전트군과 htm-server 의 HTTP·SSE 통신 계약이 `hub_dashboard.md`(서버 구현)와 글로벌 `agents/dashboard.md`(클라이언트 절차) 양쪽에 분산 → 한쪽 수정 시 다른 쪽 계약 인식 어긋남. 계약(wire contract)만 별도 SSOT 로 분리.

## Issue75: hub dashboard 카드 "열기" 링크 깨짐 — registry sid 미저장 + path serve-root 밖 ✅
* 목적: hub dashboard 섹션 카드의 "열기 ↗" 가 session-backed dashboard 를 못 엶. goal4dag 카드 클릭 시 `{"error": "path outside cwd"}` 발생. 카드가 동작하는 SPA 세션 라우트(`/s/{h}/{sid}`)로 연결되지 않는 구조적 공백.

## Issue77: dashboard SPA renderer 위젯 `width: full` 지원 + log 위젯 monospace 세로 스크롤 (글로벌 .claude#Issue91 짝) ✅
* 목적: `renderDashboard` 가 위젯을 균일 멀티컬럼 카드 그리드(`repeat(auto-fit, minmax(280px,1fr))`)로 배치 → `log`/`text`/`graph` 위젯의 긴 줄·다행 콘텐츠가 좁은 셀에서 클리핑. 글로벌 `.claude#Issue91` 이 위젯 spec 에 optional `width` 필드(`width: full` = 그리드 전폭 1컬럼 행)를 클라이언트측 SSOT(`~/.claude/_doc_arch/dashboard.md`)에 확정. ___pm htm-server 가 이 스키마를 SPA 렌더링으로 구현.
* 구현 명세:
    - A. `spa_dashboard.py` `renderDashboard` — 위젯 wrapper 에 `w.width === 'full'` 시 `w-full` 클래스 부착. action 위젯은 `widget-actionable w-full` 병행 부착, action 없는 위젯은 `<div class="w-full">` wrapper.
    - B. `server.py` `.dash-grid` CSS — `.dash-grid > .w-full { grid-column: 1 / -1; }` 규칙 추가(auto-fit 그리드 전폭 점유).
    - C. `spa_widgets.py` log 위젯 — monospace 세로 스크롤 렌더 주석 명시. 기존 `.widget.log .log-box` CSS(monospace + max-height + overflow-y:auto + white-space:pre-wrap)가 이미 클리핑 없는 스크롤 충족.
    - D. `validators.py` `validate_dashboard` — `width` 필드 optional 허용. 비문자열 값만 reject, 미지의 문자열 값은 통과(renderer 가 기본 1셀 처리).
    - E. `_doc_arch/hub_dashboard.md` — `🔧 [FIXME]` 절을 "위젯 너비 힌트" 구현 완료 기술로 갱신, 이력에 Issue77 추가, 검증 시나리오·미해결 항목 정리.
    - 검증: 4개 py `py_compile` OK. htm-server 재시작 후 e2e 스모크 9/9 PASS — width:full/half/omit + log + action 위젯 유효 update 200, width:99 비문자열 reject 400, SPA shell `.w-full` CSS·`renderDashboard` 로직·`log-box` monospace 확인.
* depends: .claude#Issue91 (글로벌측 스키마 확정 — 완료)

## Issue71: dashboard 9 목적 통합 검증 캠페인 ✅
* 목적: dashboard 큐/DAG 오케스트레이션 agent "## 목적" 9개 항목을 단일 tmux 세션 + curl 로 일괄 end-to-end 검증. Phase 6(T11)는 6-1/6-2/6-3 3종만 — 목적 1·2·6·8·9 미커버. 본 캠페인이 9개 전부 검증.
* 구현 명세: 검증 전용 — 글로벌 supervisor·runner·서버 코드 변경 없음(기검증 코드 대상). report 산출.

## Issue66: htm-server dashboard 큐 모드 서버측 — graph 위젯·/issue·/answer sid·/control remove ✅
* 목적: dashboard 큐/DAG 오케스트레이션 모드 재설계의 ___pm htm-server 측 변경. 글로벌 SCAR 측(supervisor·runner·agent)은 `~/.claude#Issue84`. 본 이슈는 서버 endpoint·위젯·hub UI 담당.
* depends: `~/.claude#Issue84` (글로벌 SCAR 측). 양 이슈 병행 — 클라이언트(supervisor·runner)가 본 이슈 신규 endpoint 에 의존.
* 구현 명세: `dashboard-orchestration_plan.md` Phase 1 + Phase 5(hub_dashboard.md). 설계 SSOT: `_doc_arch/hub_dashboard_detail.md`.

## Issue70: hub htm-doc 카드 — 본문에 문서 요약 2줄 미표시 ✅
* 목적: htm-doc 카드 본문이 제목·경로·날짜만 표시. 문서 내용을 가늠할 수 없음. 카드 본문에 문서 `<body>` 텍스트에서 추출한 간단 요약 2줄을 표시.

## Issue69: hub htm-doc 카드 — z_htm 경로 접두사 노출·날짜 본문 배치 ✅
* 목적: htm-doc 카드 본문 `meta` 가 경로를 `_doc_work/z_htm/claude-htm-*.html` 전체로 표시. `_doc_work/z_htm/` 은 기본 출력 경로이므로 생략하고 파일명만 `열기` 버튼 옆에 표시. 날짜(`mtime`)는 본문에서 카드 헤드로 이동, 오른쪽 정렬.

## Issue68: hub htm-doc 카드 — 헤드 프로젝트명·본문 문서제목 중복 표시 ✅
* 목적: htm-doc 카드는 헤드에 프로젝트명(`📁 ___pm`), 본문 `dash-title` 에 문서 제목(`___pm — 주제`)을 따로 표시 → 프로젝트명이 두 번 노출. 본문 제목에서 중복 프로젝트명 접두사를 제거하여 1회만 표시.

## Issue67: hub 활동 피드 — 항목 배경에 프로젝트색 그래디언트 부재 ✅
* 목적: 활동 피드 항목(`feed-item`)은 좌측 4px 보더만 프로젝트색으로 표시. 항목별 프로젝트 식별성이 약함. 배경에 프로젝트색을 좌→우 그래디언트로 깔아 시각 식별 강화.

## Issue64: hub dashboard — 활성 세션 카드 ✕(제거) 버튼 오동작 ✅
* 목적: hub 활성 세션 카드의 ✕ 버튼이 dashboard runner 를 종료하지 못함. Issue63 이 `pids` 영속화를 추가했으나 여전히 결함:
    1. **종료 실패(403)**: `pids.json` 이 `{}` 인 상태에서 live runner(pid 49808) 존재 → ✕ 클릭 시 `/control` 이 `403 pid not registered for this cwd`. `pids` 레지스트리는 `/register-pid` 1회성 등록 + `pids.json` 휘발(빈 `{}` 재시작)로 live runner 가 누락됨. 반면 활성 세션 카드의 kill pid 는 `_dash_runner_state`(dashboard data content)에서 추출 — 매 iter 갱신되는 authoritative 신호라 레지스트리와 불일치.
    2. **레이아웃 깨짐**: `stopRunner` 실패 시 `btn.textContent` 에 긴 에러문("pid not registered for this cwd")을 주입 → 1.6em 원형 아이콘 버튼(✕)에서 텍스트가 카드 헤더로 흘러넘침.

## Issue65: hub 활동 피드 — 카드 제목이 한 줄 클램프로 잘리고 전체 제목 복구 경로 없음 ✅
* 목적: 활동 피드 카드 제목(`htm_title`)이 길면 `…` 로 잘려 일부만 보임. CSS `.feed-summary`(`white-space:nowrap; overflow:hidden; text-overflow:ellipsis`)의 의도된 한 줄 클램프이나, 잘린 전체 제목을 다시 볼 수단이 전무한 것이 결함:
    1. `.feed-summary` 에 `title` 속성 미부착 → 호버 툴팁 없음 (형제 `.feed-icon`·`.feed-title` 에는 있음)
    2. 카드 펼침 `.feed-detail` 은 event/cwd/detail 만 표시 → `htm_title`/`summary` 전체 문자열 미포함
    3. 결국 `↗` 로 htm 문서를 직접 열어야만 전체 제목 확인 가능

## Issue63: hub dashboard — 서버 재시작 후 종료 신호 처리 불가 + dead runner 세션 활성 목록 잔존 ✅
* 목적: dashboard 사용 불가 상태 해결. 서버측 결함:
    1. **종료 신호 처리 불가**: SPA stop/kill_pane 버튼이 "pid not registered for this cwd" 에러. `pids` 레지스트리(`/register-pid` 등록분)가 in-memory only — `sessions` 만 `sessions.json` 으로 영속되고 `pids` 는 비영속. 서버 재시작 시 모든 runner pid 등록 소실 → 복원된 세션의 `/control` 이 전부 403.
    2. **dead runner 세션 잔존**: `_collect_live_sessions` zombie 필터가 `subs>0`(브라우저 탭 열림)이면 통과 — runner 가 죽어도 탭만 열려 있으면 "활성 세션" 무한 노출. 자동 정리 불가.
    3. **runner status stale**: detail page 가 죽은 runner 의 마지막 데이터(🟢 alive)를 그대로 렌더.

## Issue62: hub 활동 피드 — B모드 htm 문서가 ↗ 링크로 연결 안 됨 ✅
* 목적: B모드(`claude-htm-ask-*`) htm 문서를 만든 프로젝트의 완료 피드 항목에 ↗(htm 문서 열기) 아이콘이 표시되지 않음. 일부 항목만 ↗ 가 붙고 일부는 빈칸 — 사용자가 불일치 현상으로 보고.

## Issue57: dashboard 서버 구현 SSOT 신규 작성 — _doc_arch/hub_dashboard.md ✅
* 목적: htm-server 의 dashboard(Mode C) 서버측 구현이 `hub_htm.md` 에 htm 과 혼재되어 dashboard 단독 추적·갱신이 어려움. dashboard 서버 구현 명세를 `_doc_arch/hub_dashboard.md` 로 분리하여 dashboard 서버측 SSOT 를 명확히 함. 글로벌 `~/.claude/_doc_arch/dashboard.md`(클라이언트측 SSOT)와 상호 링크로 연결.

## Issue61: hub 활동 피드 — 아이콘만 보기 모드에서 프로젝트 클릭(cdfv) 불가 ✅
* 목적: 활동 피드 항목의 아이콘·프로젝트명을 클릭하면 `cdfv` 효과(`/open-project` → VSCode 열기)로 해당 프로젝트가 열려야 하나, `feed_show_project_name: false`(아이콘만 보기) 설정에서 동작하지 않음.

## Issue60: hub stale dashboard 카드가 "정리" 버튼으로 제거되지 않음 ✅
* 목적: Issue58 이 죽은 runner 의 dashboard 카드를 `status: running` → `stale` 로 강등하나, `_is_clearable_status` 는 clear 대상을 `done`/`stopped`/`stop` 으로만 판정 → "🧹 정리" 버튼(`/clear-done`)이 `stale` 좀비 카드를 쓸어내지 못함. 사용자가 카드마다 ✕ 를 수동 클릭해야 하여 Issue58 의 의도(좀비 식별 + 일괄 정리)가 절반만 달성됨.

## Issue59: htm-server 시작 실패 cleanup 이 살아있는 다른 서버의 pid 파일을 파괴 ✅
* 목적: `server.py main()` 이 socket bind 보다 먼저 `PID_FILE` 에 자기 pid 를 기록함. 포트가 이미 점유된 상태로 두 번째 서버가 기동하면 (1) PID_FILE 을 자기 pid 로 덮어쓰고 (2) bind 실패 → `cleanup()` 이 `os.remove(PID_FILE)` 실행 → **살아있는 첫 서버의 pid 파일까지 삭제**. 결과로 정상 동작 중인 서버가 pid 파일 없이 남아 `/hub stop`·`/hub restart` 가 서버를 찾지 못함. `/hub restart` 중 잉여 start 1회만 발생해도 재현.
* 구현 명세:
    - `services/htm-server/server.py` `main()`: `ThreadingHTTPServer` bind 를 `PID_FILE` 기록보다 **먼저** 수행. bind 실패 시 PID_FILE 미생성·미삭제로 즉시 `sys.exit(2)` (cleanup 미경유)
    - `services/htm-server/server.py` `cleanup()`: PID_FILE 내용이 `os.getpid()` 와 일치할 때만 `os.remove` — 다른 서버 pid 파일 파괴 방지
    - 검증: 라이브 서버 1대 기동 후 두 번째 server.py 기동 → bind 실패, 첫 서버 pid 파일 보존 + 2nd 가 pid 파일 미생성 확인 (exit code 2)

## Issue58: hub dashboard 카드 "running" 배지가 죽은 runner 도 running 으로 표시 ✅
* 목적: hub dashboard 카드의 status 배지가 `.dash.json`/`.dash.yaml` 파일의 `status:` 필드 텍스트를 그대로 렌더링하며 runner 프로세스 생존을 검증하지 않음. runner 가 크래시·SIGKILL·tmux pane 강제종료로 죽으면 파일에 `running` 이 잔존 → hub 는 영원히 "running" 표시. `_read_dash_file` 의 mtime 캐시가 죽은 status 를 박제하여 악화. Issue37 의 zombie 노출 차단은 `_collect_live_sessions`(live_sessions 섹션)만 처리했고 dashboard 카드 경로(`_handle_dashboards`)는 미처리.
* 구현 명세:
    - `services/htm-server/server.py` `_handle_dashboards`: dash entry 의 `status` 가 `running` 이고 `pid` 가 정수이며 `_pid_alive(pid)` 가 False 면 `entry["status"]` 를 `stale` 로 강등. `pid` 가 None 이면 검증 불가 → `running` 유지 (verification 한계)
    - pid 검증은 `_read_dash_file` 캐시 외부(매 `/dashboards` 요청마다)에서 수행 — mtime 캐시 박제 회피
    - `services/htm-server/README.md` — stale 강등 동작 한 줄 추가

## Issue55: hub 디스크 재스캔이 전체 제거한 htm 카드를 부활시킴 + 스캔 성능 상한 ✅
* 목적: hub "htm 목록 전체 제거"(`/clear-htm-docs` keep=0) 후 "🔄 디스크 재스캔" 클릭 시, 디스크에 `.html` 파일이 남아 있는 한 htm-registry 에 재등록되어 카드가 부활함. Issue53 이 `HTM_CLEARED` tombstone 을 도입했으나 autoheal 차단 전용이고, `_handle_hub_rescan` 은 발견된 htm path 를 오히려 tombstone 에서 해제(recover)하므로 clear 가 무효화됨. Issue54 가 dash 측은 `DASH_CLEARED` skip 으로 해결했으나 htm rescan 은 의도적으로 recover 로 남겨둠 — 사용자 결정으로 htm 도 tombstone 존중으로 전환. 동시에 `_scan_htm_docs_in` 은 디렉토리 전수 `os.listdir`+파일별 `os.stat`+`_extract_html_title`(파일 열람) 이라 z_htm 누적 시 재스캔이 O(N) 파일 IO 로 느려질 위험 → `search_limit` 설정으로 상한.
* 구현 명세:
    - `data/hub_setting.yml` — `search_limit: 200` 키 추가 (디렉토리당 스캔 처리 파일 수 상한, 0=무제한, `card_limit` 대칭)
    - `services/htm-server/server.py`:
        - `HUB_SETTING_DEFAULTS` 에 `search_limit: 200` 추가
        - `_scan_htm_docs_in(directory, skip=None, limit=0)` — `skip` set 의 path 는 후보에서 제외(title 추출 skip), `limit>0` 이면 파일명 unixtime 최신순 N개만 stat+title 추출
        - `_scan_htm_docs` / `_scan_tmp_htm_docs` — `skip`·`limit` 인자 전달
        - `_handle_hub_rescan` — `HTM_CLEARED` 를 skip set 으로, `search_limit` 을 limit 으로 htm 스캔에 전달. Issue53 의 "발견 htm path tombstone 해제" 블록 제거 (rescan 은 더 이상 htm recover 안 함 — `_handle_register_doc` 생산자 명시 재등록만 recover 경로로 유지)
    - `services/htm-server/README.md` — tombstone(Issue53/54/55) 설명 갱신 + search_limit 키 명시

## Issue56: hub htm-doc 가상 카드 "열기" 링크 클릭 불가 ✅
* 목적: hub "디스크 재스캔"으로 부활한(또는 `/tmp/___pm` 등 cwd 미매핑) htm 카드의 "열기 ↗" 링크가 회색 + 클릭 무반응. 파일은 존재하고 `/htm-doc` 엔드포인트도 HTTP 200 으로 정상 serve 됨에도 열리지 않음.
* 구현 명세:
    - `services/htm-server/server.py` CSS: `.card.virtual .actions a` → `.card.virtual:not(.htm-doc) .actions a` (htm-doc 가상 카드 제외, dashboard 가상 카드만 링크 비활성 유지)
    - 검증: 라이브 서버 — `/dashboards` 응답 `view_url` 정상, `curl /htm-doc` HTTP 200 확인 완료. 서버 재기동 후 가상 htm 카드 "열기" 클릭 동작 확인 필요

## Issue42: htm Hub 활동 피드 패널 — 우측 1/3 영역 hook 호출 스트림 ✅
* 목적: 작업 완료·응답 대기 등 hook 이벤트가 현재 `say` 음성 알림만 제공되어 휘발성·다중 프로젝트 식별난 문제가 있음. 동일 hook 이벤트를 htm-server 로 전달하여 hub `/hub` 페이지 우측 1/3 영역에 프로젝트별 호출 이력을 최신순 시각 피드로 노출. 음성 알림은 그대로 유지.
* depends: AskUserQuestion 질문 이벤트 포착(Phase 2)은 글로벌 SCAR — `~/.claude/Issue.md` 연계 이슈 별도 등록 후 처리
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

## Issue54: hub 디스크 재스캔이 닫은 dashboard 카드를 부활시킴 — dash tombstone 부재 ✅
* 목적: hub 에서 dashboard 카드를 닫거나(✕) done/stopped 목록 정리로 제거해도, `🔄 디스크 재스캔` 클릭 시 `/tmp/___pm/*.dash.{json,yaml,yml}` 파일이 디스크에 남아 있는 한 dash-registry 에 재등록되어 카드가 부활함. Issue53 이 htm-registry 에 `HTM_CLEARED` tombstone 을 도입했으나 dash-registry 는 동일 보호장치가 없음 — 같은 버그 클래스의 dash 측 미패치분.
* 구현 명세:
    - `services/htm-server/server.py`:
        - `DASH_CLEARED` = `data/hub/dash-cleared.json` — 명시 제거된 dash path tombstone (`HTM_CLEARED` 대칭, gitignore)
        - `_handle_unregister_doc` — 카드 닫기 시 removed path 를 해당 종류 tombstone(`HTM_CLEARED`/`DASH_CLEARED`)에 추가. htm 카드 닫기 후 autoheal 부활 gap 도 동시 차단
        - `_handle_clear_done_dashboards` — removed dash path 를 `DASH_CLEARED` 에 추가, 디스크 부재 path prune
        - `_handle_hub_rescan` — dash 재등록 루프에서 `DASH_CLEARED` path skip (htm 과 달리 recover 안 함 — dash 는 rescan 이 유일 부활 경로)
        - `_handle_register_doc` — 생산자(dashboard runner)가 명시 재등록 시 해당 path 를 tombstone 에서 해제 (recover 경로). htm·dash 공통
    - `services/htm-server/README.md` — tombstone(Issue53/54) 한 줄 추가

## Issue53: htm 목록 정리 버튼이 autoheal 로 즉시 되살아남 — clear 무효화 ✅
* 목적: hub htm 문서 목록 정리 버튼이 의도대로 동작하지 않음. "htm 목록 전체 제거"(keep=0) 클릭 시 모두 제거되지 않고 일부(feed 버퍼에 남은 ~10개)가 남고, "최신 12개만 남기기"(keep=12)는 13개가 남음. 사용자에게는 off-by-one + 전체 제거 불가로 보임.
* 구현 명세:
    - `services/htm-server/server.py`:
        - `HTM_CLEARED` = `data/hub/htm-cleared.json` — clear 로 명시 제거된 htm path tombstone (list[str], `load_registry`/`save_registry` 재사용, gitignore)
        - `_handle_clear_htm_docs` — removed path 를 tombstone 에 추가, kept path 는 tombstone 에서 제거, 디스크 부재 path prune 후 저장
        - `_autoheal_htm_registry` — tombstone 에 등록된 path 는 재등록 skip (registry_lock 내 load)
        - `_handle_hub_rescan` — 명시적 사용자 액션이므로 htm_found path 를 tombstone 에서 해제 (recover 의미)

## Issue51: htm 실행 문서가 hub htm 문서 카드에 미노출 ✅
* 목적: htm 스킬을 실행해 `_doc_work/z_htm/claude-htm-*.html` 산출물을 만든 프로젝트가 hub htm 문서 섹션에 카드로 안 나옴. 원인 — hub 는 `htm-registry.json` 등록 항목만 노출(Issue41)하는데, 생산자(htm 스킬의 `/register-doc` 호출)가 누락·실패하면 영구 미등록. 글로벌 SCAR(htm 스킬) 수정 없이 ___pm 서버가 자가치유.
* 구현 명세:
    - `services/htm-server/server.py`:
        - 모듈 레벨 `_autoheal_htm_registry(feed_items)` + `_HTM_DOC_PATH_RE` — feed detail 정규식으로 `.../_doc_work/z_htm/claude-htm-*.html` 절대경로 추출, `os.path.isfile` 확인 후 htm-registry 미등록분 append. cwd 는 경로의 `/_doc_work/z_htm/` 앞부분으로 유추 (feed cwd 비신뢰)
        - `_handle_dashboards` — feed 스냅샷 직후 `_collect_htm_docs` 호출 전 `_autoheal_htm_registry(hook_feed)` 1회 호출
    - 검증: 서버 재기동 후 `/dashboards` `htm_docs` 12→19 증가 (fSnippet·fBoard·fBanner·fQRGen·fGoogleSheet·htm-server·_public 자가치유 노출), `htm-registry.json` 19 entries 영속 확인

## Issue50: hub 활동 피드 항목 열기 아이콘 미표시 ✅
* 목적: Issue42_2 에서 추가한 피드 항목 htm 문서 열기 아이콘(↗)이 거의 노출되지 않음. 실측 — 피드 z_htm html 참조 11건 중 `htm_view_url` 매칭 2건뿐. 원인 (a) 참조 htm 문서가 htm-registry 미등록 → 매칭 대상 부재 (Issue51 자가치유로 해소), (b) 등록돼도 해당 프로젝트에 `/register` 토큰 없으면 `view_url=""` 로 아이콘 미생성. 등록된 모든 htm 문서를 토큰 유무 무관하게 열 수 있게 함.
* 구현 명세:
    - `services/htm-server/server.py`:
        - `GET /htm-doc?path=` 신규 endpoint — htm-registry 등록 경로 exact-match (`realpath` 정규화) 만 serve. registry 는 localhost 전용 endpoint 로만 기록되는 화이트리스트 → 토큰·cwd-jail 불요. 미등록 경로·비-html 403
        - `_collect_htm_docs` — `view_url` 을 토큰 있으면 `/view`, 없으면 `/htm-doc` 형식으로 항상 생성 (`missing` 제외)
        - HUB_HTML `renderHtmDocs` — `openLink` 조건에서 `!d.virtual` 제거, `view_url` 만으로 열기 링크 노출
    - 검증: 서버 재기동 후 `/dashboards` 피드 `htm_view_url` 2→9, `htm_docs` 19/19 view_url 채워짐. `/htm-doc` serve HTTP 200(11KB), `/etc/passwd` 403

## Issue52: hub_setting.yml card_limit 추가 — htm 문서 카드 표시 수 제한 ✅
* 목적: hub htm 문서 섹션이 registry 등록 전수를 카드로 노출 → 누적 시 카드 과다. mtime 최신 N개만 카드로 노출하는 `card_limit` 설정을 `hub_setting.yml` 에 추가(기본 40). 기존 "최신 12개만 남기기" 버튼은 registry 영구 정리(수동), `card_limit` 은 표시 제한(자동) — 역할 분리.
* 구현 명세:
    - `data/hub_setting.yml` — `card_limit: 40` 키 추가 (`feed_*` 키와 동일 계열)
    - `services/htm-server/server.py`:
        - `HUB_SETTING_DEFAULTS` 에 `card_limit: 40` 추가 (`_load_hub_setting` int 캐스팅 재사용)
        - `_collect_htm_docs` — mtime desc 정렬 후 `results[:card_limit]` 절단 (`card_limit<=0` 이면 무제한). registry 자체는 미변경
    - 검증: 서버 재기동 후 `_load_hub_setting` card_limit=40 인식, 절단 로직 단위 검증 (40→40·0→무제한·5→5). 현재 htm_docs 19 < 40 → 미절단 정상

## Issue49: hub 카드 '닫기' 버튼 — 단일 카드 hub 목록에서만 제거 ✅
* 목적: hub `/hub` 페이지의 htm 문서 카드·dashboard 카드는 일괄 정리(`/clear-htm-docs`·`/clear-done`)만 가능하고 카드 1건을 골라 목록에서 빼는 수단이 없음. 각 카드에 '닫기' 버튼을 추가하여 해당 카드만 hub registry 에서 제거. clear-* 와 동일하게 실제 파일은 보존.
* 구현 명세:
    - `services/htm-server/server.py`:
        - `POST /unregister-doc?type=htm|dash&path=<abs>` 신규 — `_handle_unregister_doc`. path 매칭 단일 registry 항목 제거, 127.0.0.1 trust, removed 카운트 반환
        - HUB_HTML — htm-doc 카드·dash 카드 `.actions` 에 `✕ 닫기` 버튼(`.card-close`, inline `closeCard()`) 추가, `.actions .card-close` CSS(우측 정렬·hover 빨강) 추가
        - JS — `closeCard(type, path, btn)`: `/unregister-doc` POST → toast → `reload()`
    - 검증: 등록→제거 라운드트립 — `/register-doc` htm_docs 14건 → `✕ 닫기` 클릭 시 `/unregister-doc` removed=1, 실제 파일 보존, htm_docs 13건. bad params 400, 미존재 path removed=0

## Issue48: hub 활동 피드 — 펼친 항목 일괄 접기 버튼 ✅
* 목적: hub `/hub` 활동 피드 항목은 클릭 시 detail 이 펼쳐짐(`.feed-item.open`). 여러 항목을 펼친 뒤 일일이 다시 클릭해 접어야 함. 헤더에 일괄 접기 버튼을 추가하여 펼쳐진 detail 을 한 번에 닫음.
* 구현 명세:
    - `services/htm-server/server.py` HUB_HTML:
        - CSS — `.feed-actions` flex 그룹 추가, `#feed-collapse-all` 스타일을 기존 `#feed-toggle` 와 공유(셀렉터 그룹화)
        - `.feed-head` — `feed-count` 와 `feed-toggle` 사이를 `.feed-actions` span 으로 묶고 `⊟` 버튼(`#feed-collapse-all`, title "펼친 항목 모두 줄이기") 추가
        - JS — `feedCollapseAll` 클릭 핸들러: `openFeedItems.clear()` + `feedList` 의 `.feed-item.open` 전체 `open` 클래스 제거
    - 검증: 서버 재기동 → `curl /hub` 에 `feed-collapse-all` 포함 확인. 피드 항목 다수 펼침 → `⊟` 클릭 시 일괄 접힘

## Issue47: hub 활동 피드 — 프로젝트 아이콘·이름 표시 토글 ✅
* 목적: hub `/hub` 활동 피드 항목이 `[상태아이콘][프로젝트이모지][프로젝트명][요약]` 고정 표시임. 프로젝트이모지(Issue46)·프로젝트명 노출 여부를 `hub_setting.yml` 설정으로 켜고 끌 수 있게 함 — 단일 프로젝트 작업 시 중복 정보 제거, 다중 프로젝트 시 식별성 우선 등 사용자 취향 대응.
* 구현 명세:
    - `data/hub_setting.yml` — `feed_show_project_emoji`(기본 true)·`feed_show_project_name`(기본 true) 2개 키 추가
    - `services/htm-server/server.py`:
        - `HUB_SETTING_DEFAULTS` 에 2개 bool 키 추가 (`_load_hub_setting` 의 true/false 캐스팅 재사용)
        - `_handle_hub` — `{FEED_SHOW_PROJECT_EMOJI}`·`{FEED_SHOW_PROJECT_NAME}` placeholder 를 설정값으로 치환 (`{FEED_DEFAULT_VISIBLE}` 패턴)
        - HUB_HTML — `FEED_SHOW_EMOJI`/`FEED_SHOW_NAME` JS 상수 + `renderFeed` 에서 `feed-proj-emoji`·`feed-title` 조건부 렌더
    - 검증: 서버 재기동 → `feed_show_project_emoji: false` 시 이모지 숨김 / `feed_show_project_name: false` 시 프로젝트명 숨김 / 양쪽 true(기본) 시 종전 동일. 사용자 hub 확인 "잘 작동함"

## Issue45: hub registry 항목 mtime 캐시 — 폴링마다 전체 재파싱하던 오버헤드 제거 ✅
* 목적: hub `/hub` 페이지가 `feed_poll_interval`(기본 5초)마다 `/dashboards` 를 폴링할 때 서버가 등록된 htm·dash 산출물 전체를 매번 open+read+parse 함. 등록 문서가 늘수록 폴링당 파일 IO 가 선형 증가하나, 실제 내용이 바뀐 항목은 새로 추가된 소수뿐임. mtime 불변 항목은 재파싱을 생략하고 추가·변경분만 실제 IO 하도록 전환.
* 구현 명세:
    - `services/htm-server/server.py`:
        - 모듈 레벨 `_doc_parse_cache`(abs_path → {mtime_ts, data}) + `_doc_parse_cache_lock` + `doc_cache_get`/`doc_cache_put` 헬퍼 추가 (`_load_projects_colors` mtime 캐시 패턴 동일 철학). 256 항목 초과 시 clear
        - `_read_dash_file` — `os.stat` 후 mtime 캐시 hit 시 저장 dict 복사본 반환(호출측 mutate 대비), miss 시 파싱 후 캐시 적재
        - `_collect_htm_docs` — `_extract_html_title` 호출을 mtime 캐시 경유로 전환
    - 검증: 단위 테스트 6종(cache get/put·mtime 무효화·빈문자열 hit 구분·cap·mutate 격리·부재파일) PASS, `/dashboards` 2회 폴링 byte-동일
    - 종결: 코드는 동시 진행된 Issue46 커밋(`<commit>`)에 함께 swept 되어 별도 기능 커밋 없음. 본 이슈는 문서 종결만 수행

## Issue46: hub 활동 피드 항목에 프로젝트 이모지 표시 ✅
* 목적: hub `/hub` 활동 피드 항목이 상태 아이콘(✅/❓/🔔) + 프로젝트명만 표시해 다중 프로젝트 식별이 약함. `Projects.md` 이모지 컬럼 값을 상태 아이콘과 프로젝트명 사이에 노출하여 시각 식별성 강화.
* 구현 명세:
    - `services/htm-server/server.py`:
        - `_load_projects_emojis()` — `Projects.md` 📋 테이블 cwd 경로 → 이모지 매핑 (`_load_projects_colors` mtime 캐시 패턴)
        - `_project_emoji(cwd)` 헬퍼 + `project_meta` 에 `emoji` 추가
        - `_handle_hook_event` — 신규 feed 항목에 `emoji` 저장
        - `_handle_dashboards` — `hook_feed` 전 항목에 `emoji` 재계산 부여 (기존 항목·Projects.md 라이브 반영)
        - HUB_HTML `renderFeed` — `feed-icon` 과 `feed-title` 사이 `.feed-proj-emoji` span 삽입
    - 검증: `/dashboards` 응답 19개 피드 항목 전부 `emoji` 채워짐 (`___pm`→🗓️🎯, `_doc`→💜, `m2slide`→🎬📑, `.claude`→🧠), 서빙 HTML 에 `feed-proj-emoji` 코드 포함 확인

## Issue44: htm 만 실행한 프로젝트가 dashboard 섹션에 빈 카드로 노출 ✅
* 목적: `htm` 스킬만 실행한 프로젝트(dashboard 미실행)가 hub dashboard 섹션에 "활성 dashboard 없음" 빈 카드로 노출됨. htm 스킬은 `/view` token 발급 위해 `/register` 를 호출하므로 `projects` dict 에 등록되고, `_handle_dashboards` 가 dash 0건 등록 프로젝트도 빈 카드로 추가하기 때문. dashboard 를 실행하지 않은 프로젝트는 dashboard 섹션에 표시될 이유가 없음.
* 구현 명세:
    - `services/htm-server/server.py` `_handle_dashboards` — dash-registry 미등록 프로젝트를 빈 카드로 append 하는 블록 제거. dashboard 섹션은 `dash-registry.json` 등록 항목만 노출
    - 검증: 서버 재시작 후 `GET /dashboards` → `projects: []` (m2slide 제거), `htm_docs: ['m2slide']` (htm 섹션 유지)

## Issue43: hub dashboard 섹션 빈 상태 — `..htm dash` 안내 문구 제거, 비워두기 ✅
* 목적: hub `/hub` dashboard 섹션이 등록 dashboard 0건일 때 "등록된 프로젝트 없음. `..htm dash`로 dashboard 시작." 안내 문구를 표시함. `..dashboard` alias 도 정상 동작하므로 특정 alias 만 안내하는 문구는 오해 소지가 있고, 사용자는 dashboard 없을 때 섹션을 비워두기를 원함.
* 구현 명세:
    - `services/htm-server/server.py` HUB_HTML `renderProjects()` — `!projects.length` 분기의 `grid.innerHTML` 안내 문구를 빈 문자열로 교체

## Issue41: htm-server hub 를 등록 기반(registry)으로 전환 — 디렉토리 스캔·실제 파일 삭제 제거 ✅
* 목적: hub `/dashboards` `/hub` 가 등록 프로젝트의 `_doc_work/z_htm/` 를 5초 주기 스캔하고, clear 버튼이 `os.remove` 로 다른 프로젝트의 `.html`/`.dash.*` 파일을 영구 삭제했음. (a) 타 프로젝트 디렉토리 무차별 접근 (b) hub 가 추적만 하던 파일 파괴 — 두 문제 제거. hub 가 `data/hub/` registry 에 등록된 항목만 노출하고, clear 는 registry 항목만 제거(파일 보존)하도록 전환.
* depends: 생산자 자동 등록 측은 글로벌 SCAR — `~/.claude/Issue.md` Issue69

## Issue40: htm 스킬 단발 출력을 hub `/hub` 페이지에 노출 ✅
* 목적: htm 스킬은 `claude-htm-{ts}.html` 평면 파일만 생성하고 `.dash.*` 사이드카가 없어 hub `/hub` 페이지가 모니터링 못 함. 서버가 htm 출력 html 을 직접 스캔하여 hub 에 별도 섹션으로 노출. htm 스킬 무수정 → 글로벌 SCAR 변경 없음, ___pm 단독 변경

## Issue39: htm-server `/tmp` → `/tmp/___pm/` 통합 ✅
* 목적: `~/.claude#Issue64` 동기 — htm/dashboard fallback 산출물이 `/tmp` 평면에 흩어져 OS 관리 어려움. server 측 STATE_DIR/INBOX_ROOT + `/tmp` dash scan 경로를 `/tmp/___pm/` 하위로 통합

## Issue37: dashboard-runner zombie 차단 — runner lifecycle + register-pid 자동화 ✅
* 목적: dashboard agent 종료 후 dashboard-runner.sh zombie 잔존 → 11s 주기 `/notify`+`/session/update` → hub `live_sessions` 5s alive_window 안팎 깜빡임. `/control` stop 시도 시 `not registered for hash` 403

## Issue38: htm Hub sort dropdown 동작 정상화 — 진행률순 무동작 fix + dashless stable comparator ✅
* 목적: hub 우측 상단 `sort` dropdown 사용자 인지 "작동안함". 실측 결과 `진행률순` 선택 시 카드 순서 무변화. 원인 — 모든 dash 의 `progress` 필드가 `null` 이므로 `(b||0)-(a||0) === 0` → stable sort 가 직전 순서 그대로 유지 → 시각 변화 없음. dashless 카드(`활성 dashboard 없음`) 끼리 비교 시 comparator 가 `1` 만 반환 (대칭성 위반) → undefined behavior

## Issue35: htm Hub 카드 `.html` 부재 시 dash 파일 인라인 렌더 ✅
* 목적: dashboard agent가 `.html` 산출물을 만들지 않고 `.dash.{json,yaml,yml}` 만 쓰는 케이스에서 hub "열기" 버튼 동작 보장. 이전 A안(`.html` 없으면 "열기" 숨김) 대체

## Issue36: htm Hub 카드 dash path 표시 — 프로젝트 내부는 상대 경로, /tmp 는 절대 경로 ✅
* 목적: hub 카드 path 표시 가독성 개선. 프로젝트 cwd 하위 dash 는 `_doc_work/z_htm/...` 상대 경로, /tmp 가상 dash 는 절대 경로 유지
* 구현 명세:
    - `services/htm-server/server.py` `_handle_dashboards` 루프(server.py:651-) 에 `path_display` 필드 산출. cwd prefix 일치 시 `os.path.relpath(path, cwd)`, 미일치 또는 예외 시 절대 경로 fallback
    - 가상 프로젝트(/tmp) dash 는 `path_display` 미설정 → SPA 폴백으로 절대 경로 유지
    - SPA 카드 렌더(`d.path` → `d.path_display || d.path`) — server.py:1697
    - 검증: `curl /dashboards` 응답 — `.claude` cwd dash 는 `_doc_work/z_htm/folder-creation-monitor.dash.yaml`, `system/tmp` virtual 은 `/tmp/test2-folder-creation.dash.yaml` 절대 유지

## Issue34: ___pm 로컬 `/hub` 커맨드 추가 — htm-server lifecycle wrapper ✅
* 목적: port 9876 htm-server 운영을 ___pm 컨텍스트에서 짧은 별칭으로 제어 + state wipe (clear) 추가
* 구현 명세:
    - 신규: `.claude/commands/hub.md` (105 라인)
    - SSOT: `_doc_arch/hub_htm.md`
    - 글로벌 wrapper: `~/.claude/commands/dashboard-server.md`

## Issue32: htm-server `/tmp` fallback dash 노출 (Issue31 (b) 후속) ✅
* 목적: cwd 에 `_doc_work/z_htm/` 부재 + dashboard agent OUT_DIR=/tmp fallback 케이스에서 dash 파일이 hub 에 미노출

## Issue33: htm-server hub `live_sessions` 노출 (Issue31 (c) 후속) ✅
* 목적: SSE alive (subscriber>0) 또는 최근 update<5s 인 registered session 을 hub 에 노출. 파일 dash 무관 live-only session 인식

## Issue31: htm-server `_scan_dashes` yaml status 파싱 + hub 활성 세션 인식 ✅
* 목적: `/hub` 의 `활성만` 필터가 실행 중 dashboard 를 잡지 못함. cwd=`/Users/user` (홈) + `/tmp/test2-folder-creation.dash.yaml` 사례

## Issue29: htm-server Mode C Phase 6 — milestone Notification API + preview endpoint ✅
* 목적: Issue24 plan Phase 6 (선택) — dashboard 의 사용자 인지 채널 + 발행 전 검증 채널 확보

## Issue30: services/htm-server/server.py 모듈 분리 (2130 줄 → 4 모듈) ✅
* 목적: server.py 단일 파일 ~2130 줄 → 가독성·테스트성 회복

## Issue28: htm-server HTML 템플릿 배경 흰색 고정 + project_meta() Projects.md peacock.color 참조 ✅
* 목적: `services/htm-server/server.py` 의 HUB_HTML + SESSION_SHELL_HTML 두 템플릿에 `@media (prefers-color-scheme: dark)` override 가 있어 OS 다크모드 시 dashboard·session 셸이 검정 배경으로 렌더. 또한 `project_meta()` 가 cwd_hash 기반 hsl 자동 컬러를 사용 → `~/_git/___pm/Projects.md` 의 peacock.color 컬럼 무시. 사용자가 흰 배경 고정 + Projects.md 컬러 참조 요청

## Issue27: htm-server SPA dashboard refresh 버튼 + /control?action=refresh 액션 ✅
* 목적: SPA dashboard 헤더에 ⏹ stop / ✕ kill_pane 외 🔄 refresh 버튼 추가. 사용자가 interval 무시하고 즉시 1 iter 강제 갱신 + DOM 강제 swap 가능하게 함. ~/.claude#Issue56 (dashboard agent + runner refresh 지원) 와 양방향 연동

## Issue24: htm Mode C(Live Dashboard) 우아함·UX·성능 개선 ✅
* 목적: 현재 위젯 4종(progress/table/checklist/text) + SSE+polling fallback + hub 한계 해소. 위젯 표현력 + 인터랙션 + SSE-only + hub UX 단계적 도입

## Issue25: htm-server 역할을 dashboard 전용으로 명시 — htm 스킬 분리 반영 ✅
* 목적: 글로벌 SCAR `~/.claude` 측 htm 스킬을 ___pm 서버 의존에서 분리(Mode A only, paste-back) → ___pm 서버는 dashboard agent(Mode C) 단독 클라이언트가 됨. 서버 설계 SSOT 와 README 를 dashboard 전용 역할로 재정렬하여 양측 정합성 확보

## Issue26: htm-server form 전송 후 answers JSON paste-back fallback UI ✅
* 목적: Mode B 폼 전송 성공 후 SPA 가 "답변 전송됨 — Claude 처리 대기 중..." placeholder 만 표시하여, Claude polling 누락·timeout·세션 교체·새 prompt 진입 등으로 회수 실패 시 사용자가 답변을 잃음. 폼 결과 JSON 을 화면에 노출 + 복사 버튼 제공으로 paste-back 우회 동선 확보
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

## Issue23: htm-server Mode B form field type 확장 (text/textarea/number/slider/date) ✅
* 목적: Mode B form 이 radio/checkbox 만 지원하여 자유 입력·수치·날짜 답변 수집 불가. 객관식 외 필드 타입 5종 추가로 office-hours·planning 등 폭넓은 워크플로우 커버
* 구현 명세:
    - `services/htm-server/server.py`:
        - `renderForm` → `renderField` 함수 분리, `inferType(q)` 헬퍼 추가
        - 각 type 별 input HTML 생성 (slider 는 live value `<span>` 동기화, oninput 핸들러)
        - CSS: `.q-field`, `.q-slider-row`, `.q-slider-val`, `.q-hint`, `.q-required-mark` 추가
        - `collectAnswers`: card `data-type` 기반 분기. textarea trim, number/slider `Number()` 변환, 빈 입력 null
    - 검증: 7-field 혼합 폼 (text + textarea + number + slider + date + radio + checkbox) push → 브라우저 정상 렌더 확인

## Issue22: htm-server Mode B form 라디오 선택 wipe 회귀 (polling re-render) ✅
* 목적: Mode B 폼에서 사용자가 라디오 선택 후 전송 시 value=null 회수되는 회귀 차단. 사용자 답변 손실 방지
* 구현 명세:
    - `services/htm-server/server.py` `reload()` 함수:
        - `lastSig` 모듈 변수 추가 (mode + content concat)
        - `reload(force)` 시그니처 변경. sig 동일하고 `!force` 면 statusEl 만 갱신하고 early return (innerHTML 미변경)
        - SSE event handler (`reload`, `session_update`) 는 `reload(true)` 로 강제 재렌더
        - polling 은 `reload()` 호출 → sig 비교 → 변경 시만 재렌더
    - 검증: 재시작 후 1+2 / 색상 / 계절 폼 테스트 시 value 정상 회수 (null 회귀 차단)

## Issue21: htm-server `/session/register` 응답에 SSE subscriber 카운트 포함 ✅
* 목적: 클라이언트 hook 이 stable URL 탭 open 여부를 정확히 판정하도록 SSE subscriber 수를 진실 소스로 제공. marker 파일 단독 판정의 사각지대(사용자가 탭 닫음 → marker 잔존 → "이미 열림"으로 오판) 해소
* 구현 명세:
    - `services/htm-server/server.py` line 770 부근: `with sse_lock: subscribers = len(...)` 추가 후 응답에 포함
    - 검증: `curl POST /session/register` → 응답에 `"subscribers": <int>` 확인. 다중 EventSource 구독 시 카운트 증가 확인

## Issue20: htm-server Mode B inbox sid 서브폴더 격리 ✅
* 목적: `_handle_session_answer` 의 inbox 경로가 `{cwd_hash}` 단위만 격리되어, 동일 cwd 내 다중 Claude 세션의 답변이 교차 회수되는 회귀 차단. sid 서브폴더 추가
* 구현 명세:
    - `services/htm-server/server.py` `_handle_session_answer` (line 933 부근): `inbox = f"{INBOX_ROOT}/{cwd_h}/{sid}"` 로 sid 서브폴더 신설. record 본문에 sid 필드는 이미 존재 — 경로만 추가
    - `_handle_answer` / `_handle_register` 의 cwd_h-only 경로는 backward-compat 유지 (sid 없는 legacy 호출)
    - 검증: `python3 ast.parse` 통과. 서버 재기동 후 다중 sid 동시 form 테스트 시 각자 본 sid 폴더로만 회수 확인

## Issue19: htm-server Phase 3 — Mode C dashboard renderer ✅
* 목적: `~/.claude` Issue27 / Phase 3. Mode C(Live Dashboard) 를 server-side SPA shell 에서 실제 렌더. 위젯 4종 (progress/table/checklist/text) 통합
* depends: ___pm#Issue17 (완료, <commit>)
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

## Issue18: htm-server Phase 2 — Mode B form/answer renderer ✅
* 목적: `~/.claude` Issue27 / Phase 2. Mode B(Q&A form) 를 server-side SPA shell 에서 실제 렌더. form 컴포넌트 + answer endpoint 통합
* depends: ___pm#Issue17 (완료, <commit>)
* 구현 명세:
    - **SPA shell `renderForm(content)`**: content(JSON 문자열) 파싱 → `{questions:[{question, header, options:[{label, description}], multiSelect?}]}` → 각 question 을 `.q-card` 로 렌더, radio (`multiSelect:false`) 또는 checkbox (`multiSelect:true`), 마지막 "전송" 버튼
    - **`POST /s/{cwd_hash}/{sid}/answer?token=`** 신규 endpoint:
        - URL token 인증 + sid 안전화 검증
        - body `{answers:[{question, value}, ...]}` → `/tmp/claude-htm-inbox/{cwd_hash}/{ts}.json` 저장 (Claude polling 호환, `{sid, ts, answers, source:"session_answer"}`)
        - 성공 시 세션 → mode A placeholder 전환 ("답변 전송됨 — Claude 처리 대기 중...") + `sse_broadcast` → 같은 탭 자동 reload
    - **CSS**: `.q-card` border/padding, `.q-opt` 큰 클릭 영역(transform scale 1.2), `.btn-submit` accent color, dark mode 호환

## Issue17: htm-server Phase 1 — 세션 중심 stable URL + server-side mode dispatcher 기반 구축 ✅
* 목적: `~/.claude` Issue27의 server-side 부분. (cwd, sid) 단위 세션 상태 보관 + stable URL `/s/{cwd_hash}/{sid}` + SSE 컴포넌트 swap. Phase 1 은 Mode A(response)만 실제 렌더. Mode B(form)·Mode C(dashboard)는 sessions table 에 mode 저장만 (Phase 2~3 확장)
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

## Issue16_7: Multi-project Dashboard Hub — 전 cwd dash 통합 모니터링 페이지 ✅
* 목적: 다중 프로젝트(`.claude`, m2slide, fWarrange 등) 동시 작업 시 각 탭 개별 확인 부담 제거. `http://127.0.0.1:9876/hub` 한 페이지에서 전 cwd 의 `*.dash.json` 진행률·상태·stop 제어 통합
* 구현 명세:
    - **`services/htm-server/server.py`** (Issue16_7):
        - `GET /dashboards`: tokens.json 순회 → 각 cwd의 `_doc_work/z_htm/*.dash.{json,yaml,yml}` 스캔. `.dash.json` 만 stdlib JSON 파싱 (title/status/progress/pid + widgets[0].value fallback), `.dash.yaml` 은 메타(path/mtime)만. 응답에 각 프로젝트 token + 같은 stem `.html` 존재 시 `view_url` 자동 생성
        - `GET /hub`: 내장 HUB_HTML template — 카드 grid, 5초 polling, 진행률 bar, status badge, mini stop 버튼 (`pid` 있는 dash만), Issue16_4 callout contrast 룰 준수 (자식 `code` color/background 명시)
        - 인증: 없음 (`/healthz`와 동일 localhost trust). `127.0.0.1` bind, 동일 user 접근 가정
        - 빈 상태: dash 파일 없는 cwd는 "활성 dashboard 없음" empty 카드
    - **`_doc_arch/hub_htm.md`**: `/dashboards` + `/hub` API 명세 + 검증 시나리오 2 케이스 추가
    - **`~/.claude/commands/htm-server.md`**: Endpoints 요약 표에 `/dashboards`, `/hub` 추가
    - **`~/.claude/commands/htm.md`**: Mode C 섹션 intro에 "Hub (Issue16_7)" 1줄 추가

## Issue16_6: htm-trigger.sh runtime reminder에 Mode A→B 자동 승격 룰 inline 강제 ✅
* 목적: Issue16_3 룰(선택지 N개 + 결정 요청 감지 시 AskUserQuestion 우선 호출)이 `commands/htm.md`에만 존재 → 옛 세션은 hook reminder만 보고 작동하여 룰 미인지 회귀. m2slide 시연에서 Mode A bullet dump 재현. runtime hook reminder text에 룰 압축본 inline 주입하여 세션 노후 무관 즉시 적용
* 구현 명세:
    - **`~/.claude/hooks/htm-trigger.sh`** Mode A `..htm` reminder text 블록("후속 질문" 직후, "HTML 템플릿 요구사항" 직전)에 "### 선택지 자동 승격 (Issue16_3·Issue16_6, 필수)" 하위절 신설
        - 트리거 3 조건 inline: `.htm-mode-active` 활성 + 선택지 N=2~4 (번호/알파벳/dash) + 결정 요청 문구 (선택해줘/어느 옵션/y/N/번호로 답해/골라줘/어느 쪽/Yes/No)
        - 동작: 텍스트 bullet dump 금지. 응답 본문(HTML)은 옵션 설명·비교만, 결정 요청은 `AskUserQuestion` 분리. intercept hook이 Mode B form 또는 Mode A paste-back 자동 분기
        - AskUserQuestion 호출 예시 1줄 (multiSelect + options[0] 권장 라벨)
        - 예외: 단순 비교표·정보성·코드·N>4·simple confirm
        - 상세 참조: `commands/htm.md` Issue16_3 섹션
    - **Mode C `..htm dash` reminder**에도 동일 하위절 추가 (server_section 직후, HTML 템플릿 직전)
    - 변경 영역: `~/.claude/hooks/htm-trigger.sh` 단일 파일. `commands/htm.md` Issue16_3 정식 섹션 유지 (hook reminder는 압축본, doc은 상세본)

## Issue16_5: 브라우저 일관성 — `/htm` 전체를 default browser로 통일 (Firefox 강제 잔존 제거) ✅
* 목적: 모든 `..htm`/`/htm` 흐름이 사용자 기본 브라우저(host=Chrome)로 통일. 종전 `open -a Firefox 'file://...'` 강제 + "Firefox open / Firefox 표시" 단독 표기 잔존 일관성 깨짐 제거. 사용자 default browser 변경 시 자동 추종
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

## Issue16_4: htm 템플릿 callout/info-box 내 code 텍스트 컨트래스트 버그 ✅
* 목적: `commands/htm.md` HTML 템플릿이 컬러 배경 callout/info-box를 생성할 때 내부 `<code>` 가 부모 `color: white` 상속 + 흰색 배경(`var(--code-bg)`) → 흰 배경 위 흰 글자 invisible 버그 차단. 글로벌 룰에 자식 인라인 요소 `color` 명시 강제
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

## Issue16_3: ..htm Mode A 응답에서 선택지 패턴 감지 시 AskUserQuestion 우선 호출 (Mode A→B 자동 승격) ✅
* 목적: `..htm` Mode A 활성 상태에서 사용자에게 객관식 선택지를 제시할 때 Claude가 텍스트 bullet 리스트로 dump하지 않고 `AskUserQuestion` 도구를 호출하도록 룰 강화. intercept hook이 자동 Mode B form 회수 또는 Mode A paste-back로 분기 → 브라우저 폼 무인 진행
* 구현 명세:
    - **`~/.claude/commands/htm.md`** Mode A 섹션(동작 원리 직후, Form 템플릿 직전)에 "선택지 자동 승격 (Issue16_3) — Mode A → Mode B 자동 전환" 하위절 신설
        - 트리거 3 조건 표: ① `.htm-mode-active` 존재 ② N개 선택지 (2~4개, 번호/알파벳/dash 리스트) ③ 결정 요청 문구 ("선택해줘", "어느 옵션", "y/N", "번호로 답해", "골라줘", "어느 쪽", "Yes/No" 등)
        - 매핑 규칙: 응답 본문은 옵션 설명/비교 (HTML), AskUserQuestion은 question+options만 (압축). multiSelect 분기, description 1~2문장, 권장안은 `options[0]` + `(권장)` 라벨
        - 호출 예시 Python 코드 블록
        - 예외 5 케이스 (단순 비교표·정보성·코드 dump·옵션 5개 이상·simple confirm 예외)
        - 비-htm 모드 명시 (`.htm-mode-active` 없으면 적용 안 함)
    - 변경 영역: `commands/htm.md` 단일 파일 (사용자 결정: CLAUDE.md / `_doc_arch/htm-mode-arch.md` 미터치)

## Issue16_2: htm-server `/view` endpoint + 글로벌 hook open URL을 http:// 전환 ✅
* 목적: dashboard·답변 폼·일반 결과 HTML을 모두 `http://127.0.0.1:9876/view?...` 동일 origin으로 serve → Chrome·Safari·Firefox 전 브라우저 CORS 제약 없이 fetch `/data`·`/answer`·`/notify`·`/events` 가능. 종전 `file://` open + http fetch 조합은 Chrome이 `Access-Control-Allow-Origin: null` 거부로 dashboard 미동작
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

## Issue16: htm-server `/control` stop endpoint + Mode C dashboard stop 버튼 ✅
* 목적: Mode C Live Dashboard에서 백그라운드 runner를 사용자가 직접 중단할 수 있도록 stop 제어 추가. 종전에는 별도 터미널에서 `kill <pid>` 필요
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

## Issue15: htm-server를 ___pm 소유 단일 공유 서비스로 재구조화 ✅
* 목적: 종전 htm-server는 프로젝트별 개별 인스턴스(cwd hash → port 9876+%100, `/tmp/claude-htm-server-{hash}/`) + `~/.claude/.htm-server-active` 글로벌 flag 구조. flag와 실제 lifecycle 불일치(fWarrange Issue25 재발) 제거를 위해 ___pm 소유 단일 daemon으로 재구조화
* 구현 명세:
    - **서버**: `~/_git/___pm/services/htm-server/server.py` (Python stdlib `ThreadingHTTPServer`, 단일 port 9876 고정, env `HTM_SERVER_PORT` override). md5(cwd)[:8] 해시 + `cwd+token` 페어 검증으로 다중 프로젝트 격리. `tokens.json` persist로 재시작 회복. `127.0.0.1` 바인딩 + `hmac.compare_digest` + `/data` path traversal 차단 + body size 상한
    - **README**: `services/htm-server/README.md` (운영 가이드)
    - **설계 SSOT**: `_doc_arch/hub_htm.md` (lifecycle·API·격리 모델·migration·검증 시나리오)
    - **글로벌 hooks 패치 (단일 서버 모델)**: `~/.claude/hooks/htm-ask-intercept.sh`, `htm-trigger.sh`, `htm-dash-notify.sh` — flag 제거, healthz + `/register` + `cwd+token` 페어 호출 패턴 통일. `.htm-mode-active` 플래그는 유지 (모드 활성화 신호용, 서버 lifecycle과 분리)
    - **글로벌 wrapper 재작성**: `~/.claude/commands/htm-server.md` + `~/.claude/skills/htm-server/SKILL.md` — start/stop/status/restart를 ___pm 서비스에 위임. 종전 `~/.claude/skills/htm-server/server.py` 제거
    - **endpoints**: `GET /healthz`, `POST /register?cwd=...`, `POST /answer?cwd=...&token=...`, `GET /events?cwd=...&token=...`, `POST /notify?cwd=...&token=...`, `GET /data?cwd=...&token=...&path=...`
    - **inbox**: `/tmp/claude-htm-inbox/{cwd_hash}/{ts}.json`
    - **상태**: `/tmp/claude-htm-server/{pid, tokens.json, server.log}`
    - **stale 자원 정리(1회)**: `rm -f ~/.claude/.htm-server-active` + `rm -rf /tmp/claude-htm-server-* /tmp/claude-htm-inbox-*` (host 적용 완료)
    - **하위 호환**: 서버 미실행·healthz 실패 시 hook이 Mode A(paste-back) fallback

## Issue14: proj-refactor·pm-* sync (ma·m2·host) + host 로컬 전 프로젝트 _doc_design → _doc_arch 적용 ✅
* 목적: proj-refactor 스킬(v1.2, 함정 33종)과 pm-* 글로벌 커맨드 3개 원격 머신 동기화 + host 로컬 모든 프로젝트 _doc_design → _doc_arch 리팩토링 적용

## Issue12: graphify-brief Skill 구현 ✅
* 목적: "주제" 입력 시 `graphify query` + `GRAPH_REPORT.brief.md` + `wiki/{community}.md` 발췌를 조합한 50줄 이내 요약을 반환하는 스킬 작성
* 구현 명세:
    - 입력: `<주제>` (자유 문자열, `$ARGUMENTS`)
    - 동작: `graphify query --top 5` → `GRAPH_REPORT.brief.md` 우선 grep(없으면 `GRAPH_REPORT.md`) → 매칭 `wiki/*.md` 최대 2개 발췌
    - 출력 제약: 50줄 이내. 초과 시 wiki→RELATED→QUERY 순으로 축소
    - 예외: graphify CLI 미설치 / `graphify-out/` 없음 / 빈 주제 → 명시적 에러 메시지 후 종료 (재시도 금지)
    - 검증: graphify CLI 0.x 환경(`~/.local/bin/graphify`)에서 query·grep·wiki 매칭 모든 단계 정상 동작 확인

## Issue11: graphify 토큰 절감 SCAR 글로벌 승격 ✅
* 목적: 프로젝트(`___pm`)에 구현된 graphify 토큰 절감 SCAR를 `~/.claude/` 글로벌로 이식하여 모든 프로젝트에서 공통 적용
* 구현 명세:
    - 프로젝트(`___pm`) 버전을 `cp`로 글로벌에 복사 (graphify-rules.md, graphify-prune.md, gq.md)
    - 기존 글로벌 `gq.md`는 `$1` → `$ARGUMENTS` 표준화 버전으로 덮어씀
    - CLAUDE.md graphify 섹션에 3줄 보강 (토큰 절감 규칙·보조 커맨드·요약 스킬)

## Issue13: 고객 서버용 글로벌 nPTiR·SCAR 하네스 구현 ✅
* 목적: 새 서버 `~/.claude`에 복사할 수 있는 nPTiR·SCAR 글로벌 하네스 구축 (___pm 미포함, 개인정보 제거, macOS 앱 도메인 제외)
* 구현 명세:
    - CLAUDE.md, Harness.md 서버 전용 재작성 (개인정보·fApp·-m 도메인 제거)
    - rules/ 9개 (nptir, issue-g, md, naming, language, refs, change-detect, info-files, opus-4-7)
    - commands/ 10개 (issue-*-g, needs, design-doc, new-project, md-add, gstack-*)
    - skills/ 7개 (issue-g, dev-g, dev-w, issue-w, doc-work-archive, git, gstack)
    - new-project.md: ___pm 스킬 참조 제거, 독립형 nPTiR 초기화 커맨드로 재작성
    - info-files.md: 개인 파일(past_prompts, instincts) 참조 제거

## Issue10: 글로벌 SCAR 변경 호환성 감사 및 정렬 (Opus 4.7 실행제약·gstack-nptir 연동·Harness SSOT·VERSION) ✅
* 목적: 글로벌 `~/.claude/` SCAR 대대적 수정(Opus 4.7 실행제약 의무화·gstack-nptir 연동·nPTiR 경로 복수화·version-manager 신규·Harness SSOT)과 프로젝트(`~/_git/___pm`) SCAR 간 호환성 정렬
* 구현 명세:
    - **선행 완료**: Harness SSOT 분리(루트=인덱스, _doc_arch=상세 설계), 루트 Harness.md 교정(fcapture 표기·___pm 섹션 도메인·sync-ma 보강·local 섹션 추상화), md-rule-apply 코드블록 가드 추가
    - **Phase 1**: 프로젝트 SCAR 30개(agents 2 + commands 23 + skills 5)에 "Opus 4.7 실행 제약" 표준 섹션 일괄 추가. 누락 0 확인
    - **Phase 2**: issue 관련 SCAR 4개(rules/issue-rules + commands/issue-{reg,fix,closer})에 gstack-nptir-rules 참조 및 글로벌 `-g` 커맨드와의 관계 명시
    - **Phase 3**: nPTiR 경로 단수/복수 검증. 프로젝트는 이미 복수 `tasks/` 준수 상태 → 스킵
    - **Phase 4**: pm skill mac 타입에 `version-manager-m` Skills 포함 + VERSION SSOT 초기화 필수 요구사항 명시
    - **nPTiR 산출물**: plan/task/report 전부 생성, frontmatter 양방향 연결(issue, plan, task) 완료
    - **집계**: 단일 커밋(<commit>) · 95 files changed · +1807 / -952

## Issue9: fApp 8개 프로젝트 메모리 일관성 확보 (Bundle ID·구조·파일명·메타 통일) ✅
* 목적: fApp 프로젝트(#11~16, #25, #26)의 `~/.claude/projects/*/memory/` 메모리 파일들이 생성 시점·방식이 달라 파일명/구조/Bundle ID 값이 제각각인 문제를 일괄 정리하여 재사용성과 신뢰성 확보
* 구현 명세:
    - **Bundle ID 통일**: Xcode `project.pbxproj` 실측 기준으로 모든 메모리의 Bundle ID 정정. 8개 앱 타겟 전부 `kr.finfra.*` prefix로 확정 (`kr.user.fSnippet` → `kr.finfra.fSnippet`, `com.finfra.fWarrange` → `kr.finfra.fWarrange` 등). `com.finfra.*`·`kr.user.*`는 더 이상 사용 안 함
    - **파일명/타입 표준화**: `project_bundle-ids.md` (type: project), `project_parallel-projects.md`, `project_similar-project.md` (type: project), `project_nptir-path.md`로 통일. 기존 `feedback_bundle-id.md`·`project_parallel-context.md`·`reference_similar-project.md`·`project_nptir-structure.md`·`refactoring_issue-commands.md` 삭제
    - **MEMORY.md 표준 구조**: `# {프로젝트명} (#번호) Memory Index` 헤더 + `## Feedback` / `## Project` 섹션. index-only 원칙 준수 (본문은 별도 파일로 분리)
    - **앱 분류 메타 추가**: 각 MEMORY.md 상단에 `> **앱 분류**: 유료앱/무료앱 · **서브 프로젝트**: 있음/없음` blockquote 삽입. fBanner/fBoard/fGoogleSheet=유료·서브없음, fQRGen=무료·서브없음
    - **fBoard 잘못된 내용 정정**: `project_structure.md`의 "Pro/Basic 2-앱 구성"·"Basic→Pro 기능 이식" 표현 삭제, 단일 유료앱으로 재작성. `project_bundle-ids.md`에서 `Finfra.com.fBoard-basic` 항목 제거
    - **fGoogleSheet 메모리 디렉토리 신규 생성**: 기존에 없었던 `memory/` 디렉토리 및 MEMORY.md/project_bundle-ids.md 생성
    - **data/fapp-projects.md 테이블 확장**: "판매"(유료/무료) 및 "서브 프로젝트" 컬럼 추가, 서브 프로젝트 상세 섹션(25/26/35) 신설

## Issue4: pm 스킬 및 커맨드 구현 (pm-new, pm-del, pm-update, pm-query) ✅
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

## Issue1: cdf (N) 윈도우 번호 미존재 시 자동 생성 ✅
* 목적: `(4)` 지정 시 해당 인덱스 윈도우가 없으면 자동 생성
* 구현 명세:
    - 증상: 존재하지 않는 윈도우 번호 지정 시 fallback 이름으로 다른 윈도우에 배정
    - 수정 대상: `.claude/skills/cdf.md` Step 1 `(N)` 파싱 및 Step 3 window 생성 로직

## Issue2: cdf 각괄호 `[NAME]` 구문으로 윈도우 이름 직접 지정 ✅
* 목적: `6 7[mywin] --- ls` 형태로 윈도우 이름을 인라인 지정
* 구현 명세:
    - 기존: 비숫자 단독 토큰이 WIN_NAME으로 해석 (모호함)
    - 개선: `[NAME]` 각괄호 구문 추가하여 명시적 윈도우 이름 지정
    - 수정 대상: `.claude/skills/cdf.md` Step 1 토큰 분류 로직

## Issue3: cdf REUSE 시 pane 경로 일치 검증 후 CMD만 전달 ✅
* 목적: pane 수 일치해도 경로가 다르면 재생성, 경로까지 일치하면 CMD만 전달
* 구현 명세:
    - 증상: pane 수만 비교하여 다른 프로젝트 조합의 window를 재사용
    - 개선: 각 pane의 `pane_current_path`를 PROJ_PATHS와 비교
    - 수정 대상: `.claude/skills/cdf.md` Step 3 window 확인/생성 로직

## Issue258: hub 내부 탭 alt+w 닫기 시 Chrome 크래시 — **macOS 접근성(AX) abort** (iframe 이론 오판, 재개: 2026-07-11, 보류: 2026-07-11) ⏸️
* 목적: Issue223(디바운스)·237(playwright headless)·250(iframe fallback) 이후에도 Chrome 이 죽는 케이스 잔존. 사용자 확정 repro: **"hub 탭 여러 개 떠있을 때 + 내부 탭 alt+w 로 닫을 때"**. "완전 해결"(탭 수 무관) 요구.
* depends: Issue223, Issue237, Issue250

## Issue238: 원격 브라우저에서 Remote-SSH 연결된 VSCode 에디터 열기 (open-project/open-session 클라이언트측 URI 분기)
* 목적: host 브라우저에서 host hub 에 접속(Remote-SSH 로 VSCode 는 이미 host 연결됨)한 상태에서, hub 의 `📁 open-project`·`🆚 open-session` 버튼을 눌러도 VSCode 에디터가 열리지 않는다. Issue167 이 헤더 endpoint URL 을 `advertise_host` 로 전파해 원격 브라우저 → host 서버 POST 자체는 도달하나, 서버가 `open -a "Visual Studio Code"` 를 **host(서버)에서** 실행 → 창은 host 화면에 뜨고 host 사용자 화면엔 안 뜸. 창을 띄우는 주체가 서버가 아니라 **브라우저 머신(host)** 이어야 한다.
* 구현 명세:
    - 분기: `_handle_open_project`/`_handle_open_session` 에서 `client_ip in LOOPBACK_IPS` → 기존 `open`(서버==클라이언트, 로컬 폴더) 유지 / 원격 IP → `open` 대신 `{status:"remote", uri:"vscode-remote://ssh-remote+<alias><cwd>"}` JSON 반환.
    - alias 소스: `hub_setting.yml` 신규 키 `ssh_remote_alias`(예: `gl`) 또는 `Servers.md` self 행 `ssh alias` 컬럼 보존·노출. 미설정 시 원격 분기 비활성(기존 동작 폴백).
    - onclick JS(canonical 헤더 + hub UI 카드 핸들러): fetch 응답에 `uri` 존재 시 `window.location.href = uri` 로 분기, 없으면 기존 무음 처리.
    - 파일 단위 열기(선택): 경로가 파일이면 에디터 탭, 폴더면 워크스페이스. open-session 은 워크스페이스 보장 후 세션 URI — Remote 권한 창에서 동작 검증 필요(리스크 약간 ↑).
    - 보안: URI 자체엔 권한 없음(접속권은 클라이언트 SSH 키). 기존 cwd 화이트리스트 유지 — 공격면 불변.

## Issue115: Hub 자동 리프레쉬 (tmux 백그라운드 프로세스 제거)
* 목적: dashboard 데이터 파일 변경 시 hub 페이지 자동 리프레쉬 (수동 새로고침 제거). tmux 환경에서는 별도 백그라운드 프로세스 대신 window 내부 폴링으로 구현.
* 구현 명세:
    - dashboard 데이터 파일 감시 (mtime 폴링)
    - 변경 감지 시 페이지 reload (js: location.reload 또는 fetch + DOM 업데이트)
    - 간격: 5초 (hub 페이지 로드 시 자동 시작)
    - 중지: 탭 닫기 또는 명시적 중지 버튼

