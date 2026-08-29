---
name: Issue_public
description: "fpm 공개용 이슈 근거 요약 — Issue.md 에서 제목·목적·구현 명세만 추출한 파생본"
generator: scripts/fpm-issue-digest.sh
source_sha: d286cdf2a47150fc32d2c2accd9616c227c69e19509d6cf8e79c3e3cdc74142c
---

# 안내

본 문서는 자동 생성 파생본이다. 원본 이슈 트래커(`Issue.md`)는 개인정보가 포함되어 공개하지
않으며, 여기에는 **코드 변경의 근거를 이해하는 데 필요한 필드만** 추출되어 있다.

* 포함: 이슈 제목 · `목적` · `구현 명세` · `depends`
* 제외: 상세 · Walkthrough · 진행 결과 · 커밋 해시 · plan/task 경로

소스 코드 주석의 `(Issue{N})` 참조는 아래 항목에서 찾을 수 있다. 직접 편집하지 말 것 —
`scripts/fpm-issue-digest.sh` 가 덮어쓴다.

# 이슈 근거

## Issue413: 마켓 발행과 forward 자동 bump 가 서로를 앞질러 무결성 검사가 상시 FAIL 이다 ✅
* 목적: 저작 머신에서 check.sh 항목 13(설치본 무결성)이 **거의 항상 FAIL** 이다. 원인은 표류가 아니라 **두 자동화의 순서**다. 상시 FAIL 은 진짜 표류를 묻는다 — 항목 13 이 존재하는 이유를 무력화한다
* 구현 명세:
    - ① 판정 — 마켓 발행을 `deploy` 안으로 넣을 것인가, 아니면 `publish-scar` 에도 `AUTOBUMP=0` 배선을 줄 것인가. **버전을 움직이는 주체를 하나로** 모으는 것이 요점이다
    - ② 저작 머신에서 항목 13 의 의미 재정의 — 저작 머신에는 **설치본이 없다**(항목 14 가 이미 "플러그인 미등록(저작 머신)" 으로 판정한다). 검사 대상이 없는 곳에서 FAIL 을 내는 것이 맞는지부터 정한다
    - ③ 발행 대기 상태(정본이 마켓보다 앞섬)는 **정상**이다 — 이것을 FAIL 이 아니라 "미발행 N건" 같은 정보로 낼 것
    - ⚠️ 버전 번호를 손으로 맞추는 것은 해법이 아니다 — 다음 커밋에서 즉시 어긋난다(실측)
    - 검증: 발행 → 임의 커밋 → check.sh 가 FAIL 을 내지 않을 것 · 진짜 내용 표류(②형)는 여전히 검출될 것

## Issue412: prj3 → prj1 번들 `hooks/` 사본이 조용히 늙는다 — 동기 수단도 검사도 없다 ✅
* 목적: Issue388 이 `flat_file` 에서 없앤 *"사본이 원본과 갈라져도 아무 신호가 없다"* 가 **`plugin.hooks` 에는 그대로 남아 있다**. 배포 체인의 **가장 상류**라, 여기서 누락되면 그 아래 순방향 전체가 낡은 것을 실어 나른다
* 구현 명세:
    - ① **판정 먼저** — `hooks/` 의 소스가 prj3 인가 prj1 인가. 매니페스트 선언(prj1)과 실운영(prj3)이 어긋난 상태이므로, 고치기 전에 어느 쪽이 정본인지 정한다. 정하지 않고 스크립트부터 만들면 반대 방향으로 굳는다
    - ② prj3 정본으로 확정 시: [`sh/scar-flatfile-sync.sh`](sh/scar-flatfile-sync.sh) 와 **같은 형태**로 `hooks/` 동기 경로 신설(단방향 prj3 → prj1 · 원본 읽기 전용 · 선언에 없는 사본은 orphan 보고). 바퀴를 다시 만들지 말고 그 스크립트의 인벤토리 방식을 따를 것
    - ③ `scar:` 인벤토리에 `hooks` 키 추가 + check.sh 가 **양방향 대조**(선언↔디스크, 사본↔원본). 항목 12 와 같은 구조
    - ④ prj1 고유 훅(`fpm-browser-open.sh` 등)은 **명시적 예외 목록**으로 — "prj3 에 없음" 이 결손인지 정상인지 사람이 매번 판단하게 두지 않는다
    - 검증: prj3 훅 1건을 고치고 동기를 **돌리지 않은** 상태에서 check.sh 가 **검출할 것** · 동기 후 PASS · 예외 목록 항목은 검출되지 않을 것

## Issue414: 회수(reverse)를 **판정 자동화**로 바꾼다 — "sync 한 것은 자동 승인, 바뀐 것만 검토" ✅
* 목적: 개발 머신이 늘어난다(host Linux · **windows 예정**). 지금의 정방향·역방향 절차는 **단계가 너무 많고 사람이 매번 판단**해야 해서, 머신 수만큼 부담이 곱해진다. 회수를 자동 판정으로 바꿔 **사람은 실제로 바뀐 것만** 보게 한다 (2026-08-29 사용자 방향)
* 구현 명세:
    - ① **reverse 판정 축을 커밋으로 전환** — 대상은 *"마지막 `Sync:` 이후 미러에서 실제로 바뀐 파일"* 뿐. 그 외는 정본에서 나간 그대로이므로 **회수 대상이 아니다**(= sync 한 것은 자동 승인). VERSION 게이트는 보조 신호로 강등
    - ② ①이 서면 **sanitize 차이는 구조적으로 후보에서 빠진다** — 되돌릴 파일 목록 자체가 "미러에서 바뀐 것" 으로 좁혀지기 때문. 별도 sanitize 비교 로직을 만들지 말 것(다대일이라 복원 불가)
    - ③ forward 게이트와 **같은 함수**를 공유 — 두 축이 갈라진 것이 교착의 원인이므로 판정 지점을 하나로 모은다
    - ④ 자동 승인 경계 — **`fpm:private` 블록·시크릿 스캔은 자동화 대상이 아니다**(P1 3번째 이유·P5). 파일 목록 판정만 자동화하고 이 둘은 게이트로 남긴다
    - ⑤ 다중 머신 대비 — 회수 출처를 `on <machine>` 으로 기록. 머신이 늘면 *"어느 머신발 변경인가"* 가 판정에 필요하다(`prjN#IssueM` 과 별개 축)
    - 검증: 미러를 건드리지 않은 상태의 reverse → **후보 0건**(현재는 20건) · 미러에서 1파일만 고친 뒤 → **그 1건만** 후보 · 그 상태에서 forward 도 같은 판정을 낼 것(교착 없음)

## Issue410: `do_forward` 에 DST(미러) 브랜치 가드가 없다 — 미러가 `main` 이 아니면 배포가 엉뚱한 사유로 중단된다 ✅
* 목적: `deploy` 는 `$SRC`(prj1) 브랜치를 Issue385(비공개)\1가드로 검사하지만 **`$DST`(미러) 브랜치는 판정하지 않는다.** 비대칭이라 미러가 `develop`·`fix/*` 에 체크아웃돼 있으면 F5-1 미흡수 가드가 **엉뚱한 사유로** 발화해 배포가 중단되고, bump 는 이미 끝난 뒤라 버전 번호만 소비된다
* depends: Issue409
* 구현 명세:
    - ① [`scripts/fpm-sync.sh`](scripts/fpm-sync.sh) `do_forward` 진입부(F5-1 **앞**)에 DST 브랜치 판정 추가. `$DST` 가 `main` 이 아니면 fail-loud `exit 1` + 조치 문구를 `switch main` 으로 명시. 우회는 `FPM_ALLOW_DST_BRANCH=1`
    - ② 집행 등급 **enforce** — Issue385(비공개)\1`$SRC` 가드)와 대칭. advisory 경고 금지
    - ③ `sh/check.sh` 에 소비자 브랜치 경고(advisory) 추가 — `$FPM_BASE` 가 `main` 이 아니면 경고
    - 검증: 미러를 임시 브랜치에 두고 `forward` → 새 메시지로 중단 · `main` 복귀 후 정상 통과 · `FPM_ALLOW_DST_BRANCH=1` 우회 동작

## Issue407: 구버전 `Projects_org.md` 로 설치된 사본은 `# Project Map` 섹션을 영영 못 받는다 — 맵이 통째로 미생성 ✅
* 목적: `place_org()` 는 실파일이 있으면 무조건 보존하므로, 템플릿이 나중에 보강돼도 기존 설치본은 갱신되지 않는다. host 은 7/17 에 트리 섹션이 없던 org 를 복사했고 8/23 에 org 가 보강됐으나 반영되지 않아, `Projects_map.htm`·`.md` 가 둘 다 생성되지 않는다(빌더 rc=1 `# Project Map 섹션을 찾지 못함`).
* 구현 명세:
    - SSOT `data/scar-manifest.yml` `shell.org_files[]` 에 선택 필드 `sections` 추가(첫 항목이 삽입 정본, 나머지는 허용 별칭). `projects_map` 블록으로 빌더·산출물 경로도 SSOT 화
    - `gen-install-manifest.sh` → `FPM_ORG_SECTIONS`·`FPM_PROJECTS_MAP_{BUILDER,OUT}` 투영
    - `install.sh` 4단계: 파일 보존 원칙은 유지하되 **허용 헤딩이 하나도 없을 때만** org 에서 해당 섹션을 append(사전 백업). 이어서 산출물 부재 시 빌더 1회 실행
    - `check.sh` 5단계: 섹션 결손·산출물 부재를 경고로 검출

## Issue405: 퇴근한 핀봇의 **마지막 실행 시각**이 hub payload 에 없다 — 5분 전 퇴근과 두 달 전 퇴근이 같은 칩 ✅
* 목적: 사용자가 *"나래가 지금 도는가"* 를 hub 화면만으로 판정할 수 없다. 퇴근 봇은 `⬜ 나래(중역핀봇)` 칩 하나로만 그려지고 시각 정보는 **조직 전체 `last_ts` 1개**뿐이라 개체별 최신성이 사라진다. 방금 퇴근한 봇과 오래 전 퇴근한 봇이 화면상 구분되지 않아, prj3#Issue438 이 없애려던 "세션에 되묻는 상황" 이 그대로 재현된다
* depends: Issue404
* 구현 명세:
    - 서버 — 봇별 마지막 job 시각을 `SELECT owner, MAX(created_at) FROM job WHERE kind LIKE 'fbot_%' GROUP BY owner` 로 집계. `_fbot_session_counts` 와 **같은 커넥션·같은 fail-soft 규약**(실패는 빈 dict, 봇 카드를 깨지 않는다)
    - roster 의 **비활성(퇴근) 봇에만** `last_seen` 을 싣는다 — 활성 봇은 카드가 이미 정보를 들고 있어 소비처가 없다(아이콘을 루트에만 싣는 것과 같은 판정)
    - 클라이언트 — 마지막 실행이 **24시간 이내**면 칩에 `{t} 전 퇴근` 을 덧붙이고 강조한다. 24h 초과분은 현행 칩 유지하되 **툴팁에 절대시각**을 남겨 정보 손실을 만들지 않는다
    - ⚠️ `server.py` 는 `services/hub/`(실행 경로)·`plugins/fpm-core/services/hub/`(배포 정본) **두 벌**이다 — 양쪽 동시 수정 + 단일 커밋
    - 검증: 픽스처로 **24h 경계 양쪽**을 박제(경계 조건 회귀가 잦다) · 활성 봇에 `last_seen` 이 안 실리는지 · launchd hub 실측

## Issue404: hub 를 띄우는 launchd agent 에 `AOA_MEMORY_DIR` 이 없다 — 핀봇 섹션이 통째로 "봇 0" ✅
* 목적: 상시 hub 는 **launchd agent `kr.finfra.htm-server`** 가 띄운다. 그 plist 의 `EnvironmentVariables` 에는 `PATH` 뿐이라 `AOA_MEMORY_DIR` 이 없다. prj3#Issue450(커밋 `<commit>`)이 `FBOT_AOA_DIR` 기본값을 `~/_git/___common/data/aoa` → `~/.claude/data/aoa`(제품 중립)로 바꾸면서, **env 없이 뜬 hub 는 레지스트리 DB 를 못 찾는다.** Issue399·400·401·402 가 만든 핀봇 섹션이 전부 화면에서 사라진다
* depends: Issue402

## Issue402: 핀봇 조직도 — 루트 핀봇 단위 그룹 + 클릭 시 위임 관계 별창 시각화 ✅
* 목적: Issue401 로 카드 상세는 열렸으나 **"어느 핀봇이 어느 핀봇에게 일을 시켰는가"** 는 여전히 안 보인다. 사용자는 개체 나열이 아니라 **조직 구조**를 보고 싶어 하며, 진입 단위는 *"나와 소통하는 핀봇"*(= 부모 없는 루트 봇)이다. 이슈맵(`Issue_map.htm`)이 이슈 의존을 그리듯, 봇 위임을 그린다
* depends: Issue401, prj3#Issue456
* 구현 명세:
    - ⓐ **별창은 hub 라우트로** — `/fbot-map`(신설). `registry.db` 를 `mode=ro` 직독해 **매 요청 실시간 생성**한다. `Issue_map.htm`·`Projects_map.htm` 은 파일 산출물이지만 그 패턴을 **쓰지 않는다** — Issue438 ③ 계약 *"중간 사영 파일 금지 — 판정 단일 지점"* 과 정면 충돌하기 때문. 헤더 합성은 기존 맵 2종과 동형([`services/hub/server.py`](services/hub/server.py) `_handle_projects_map` 선례)
    - ⓑ **홈 섹션 그룹핑** — `renderBots()` 를 루트 봇 기준 그룹으로 재편. 그룹 헤더에 루트 봇 호칭·소속 수·활성 수. 퇴근 봇도 조직 구성원으로 표기하되 상태로 구분(Issue400 의 "전원 퇴근을 숨기지 않는다" 를 그룹 단위로 승계)
    - ⓒ **클릭 의미 분리 주의** — 카드 본체 클릭은 Issue401 아코디언(상세 펼침)이 **이미 점유**했다. 조직도는 **별도 어포던스**(그룹 헤더의 맵 아이콘 등)로 열고 `target="_blank"`. 카드 클릭을 빼앗으면 Issue401 회귀
    - ⓓ **엣지 렌더** — 채용은 실선, 배분은 화살표 + 이슈·`status` 라벨(cancelled 는 흐리게). `/fbot-map?root=<bot_id>` 로 해당 루트 하위 트리만 필터
    - ⓔ mermaid 생성 규약은 [`skills/mermaid-diagram`](.claude/skills/) 준수. 아이콘·개체색은 `bot.icon`·`bot.color`(prj3#Issue438 ③ 채용 시 생성분) 재사용 — 새 색 체계 금지
    - 검증: 나래 그룹에 하위 3봇이 **실제로 그려지는지**(배분 원장 0건인데도) · 고아 노드 표기 · 루트 3그룹 전건 렌더 · 카드 아코디언 무회귀(Issue401 25항) · `bots_error` 경로에서 맵도 조용히 죽지 않는지

## Issue403: dash 카드가 영구 running 으로 박제된다 — pid 검증 불가 경로에 강등이 없다 ✅
* 목적: `status: running` 인데 `pid` 가 정수가 아니고 `worker_pid` 키도 없으면 [`services/hub/server.py`](services/hub/server.py) `_effective_dash_status` 가 *"검증 불가 → running 유지"* 로 빠진다. mtime 이 며칠 정체돼도 강등이 없고, `running` 은 `_is_clearable_status` 가 False 라 **hub "정리" 버튼으로도 지워지지 않는다.** Issue58·83 이 잡으려던 좀비 카드의 **미처리 잔여 경로**
* 구현 명세:
    - ⓐ `_effective_dash_status` 에 **mtime 기반 강등** 추가 — `status == "running"` 이고 pid 검증이 불가능하면(둘 다 비정수) `mtime_ts` 정체를 본다. 임계는 `interval` 의 배수로 산출(고정 상수 금지 — 10초 보드와 5분 보드가 같은 임계를 쓰면 한쪽이 반드시 틀린다). `interval` 부재 시에만 기존 `DASH_STATUS_NONE_GRACE_SEC` 준용
    - ⓑ 강등 결과는 `stale` — `_is_clearable_status` 가 이미 `stale` 을 포함하므로 **"정리" 버튼이 자동으로 먹는다**. 별도 분기 추가 금지(Issue83 이 없앤 렌더·정리 비대칭을 되살리지 말 것)
    - ⓒ ⚠️ **정상 보드 오강등 금지** — 살아 있는 순수 모니터링 보드는 runner 가 매 주기 write 하므로 mtime 이 전진한다. 임계를 `interval` 배수로 잡는 이유가 이것. 실가동 보드 1건으로 무회귀 실측 필수
    - 검증: 정체 보드 → `stale` 강등 + 정리 버튼 동작 · 가동 보드 → `running` 유지(오강등 0) · `pid` 보유 보드 무회귀(Issue58) · 렌더·정리 판정 일치(Issue83)

## Issue401: 핀봇 카드 클릭 → 세부 펼침 (prj3#Issue444 의 prj1 접점) ✅
* 목적: hub 핀봇 카드는 title·role·prj·상태·`current_task`(2줄 clamp)만 보여준다. 레지스트리가 **이미 들고 있는** `bot_id`·`career`·`parent_bot_id`·`lease_expires` 와 잘린 작업 전문을 hub 안에서 볼 길이 없어, 결국 `/fbot <bot_id>` 로 터미널에 되돌아가야 한다 — 관측 진입점이 요약에서 끊긴다
* depends: Issue400, prj3#Issue444
* 구현 명세:
    - `.bot-card.open .bot-detail { display: block }` + 펼침 시 `.bot-task` 의 `-webkit-line-clamp` 해제 → 잘린 작업 전문 복구
    - 표시 항목: `bot_id` · `career`(수습/정식/휴직) · 부모 봇 · lease 잔여/만료 경과 · 현재 작업 전문
    - 접근성: `role="button"` + `tabindex="0"` + Enter/Space — 피드 항목과 동일 수준
    - ⚠️ **회귀 주의**: 주기 갱신이 `grid.innerHTML = …` 로 카드를 통째 재생성한다 → 열어둔 카드가 갱신마다 닫히는 결함이 나기 쉽다. 피드의 `openFeedItems` 와 동형으로 `bot_id` 기준 열림 상태를 보존한다
    - 검증: 활성 봇 2개 이상 독립 토글 · 재렌더 후 펼침 유지 · 키보드 단독 조작 · 유휴 요약 줄(Issue400)은 토글 대상 아님

## Issue400: 핀봇 섹션이 "전원 퇴근" 을 통째로 숨긴다 — 기능 사망과 봇 유휴가 화면상 구분 불가 ✅
* 목적: Issue399 가 만든 hub 홈 핀봇 섹션은 `활성 0 → 섹션 미표시` 계약이라, 13봇 전원 `checkout` 인 상태에서 **홈에 아무것도 남지 않는다**. 사용자는 기능이 죽은 건지 봇이 노는 건지 화면만 봐선 구분할 수 없어 결국 세션에 되묻게 된다 — prj3#Issue438 이 없애려던 상황 그 자체
* depends: Issue399
* 구현 명세:
    - `_collect_bots()` 에 `bots_today` 신설 — `registry.db` `job` 원장을 같은 `mode=ro` 커넥션으로 직독해 오늘(로컬 자정 이후) `배분`·`완료`·`취소` 건수 + 마지막 fbot job 시각. 중간 사영 파일 금지(Issue399 와 동일 원칙)
    - `job.store` 값이 `'fbot'`·`''` 로 갈려 있어 **`kind LIKE 'fbot_%'` 로 판정**한다(store 필터는 세션 완료 10건을 통째로 놓친다 — 실측)
    - `job` 에 완료 시각 컬럼이 없다 → 집계는 **`created_at` 기준**임을 payload·i18n 문구·툴팁에 명시. 추정치를 확정치처럼 보이게 하지 않는다
    - `renderBots` 표시 조건 교체: `total===0` 이면 미표시(fbot 미설치 graceful — 기존 계약 유지) · `total>0 && active===0` 이면 **유휴 요약 1줄** 표시 · 그 외 기존 카드 그리드
    - i18n `bots.idle`·`bots.today*` ko/en 추가. 카운트 배지는 `0/13` 로 유지해 총원이 보이게 한다
    - 검증: `test_fbot_bots.py` 에 `bots_today` 집계·store 혼재·미설치 graceful 회귀 추가 + 기존 hub 테스트 무회귀

## Issue398: projects-map 메모(note 박스) 실시간 인라인 편집 — 저장 버튼 없는 초단위 자동 동기화 ✅
* 목적: `/projects-map` 의 `_note.md` 메모 박스가 읽기 전용(클릭 시 VSCode 오픈)이라 브라우저에서 즉석 수정이 불가. 저장 버튼 없이 타이핑만으로 서버(`_note.md`)에 자동 반영되게 한다
* 구현 명세:
    - builder: `read_note` contenteditable 부여, NOTE_EDIT_SCRIPT(DOM→md 직렬화·1s throttle·`.` 즉시 flush·pagehide sendBeacon·sync-err 표시) 추가, 안내 문구 갱신
    - hub 서버: `POST /projects-map/note` 신설 — `{md}` 수신 → `_note.md` tmp+`os.replace` 원자 기록. `_rebuild_projects_map_if_stale` stale 판정에 `_note.md` mtime 포함

## Issue397: live 세션 live_pid 사망 시 gc_meta.shell_pid 승격 복구 — 오염 pid 방어 ✅
* 목적: 훅이 단명 pid 를 등록(prj3#Issue428)하면 서버가 `live_pid` 를 pop 하고 복구 경로가 없어, 살아있는 세션이 LIVE_TTL(300s) 경과 후 카드에서 사라짐(prj9a 실측 — 생존 4세션 중 2개만 표시). 훅 수정과 별개로 서버측 방어선을 추가
* depends: 없음 (prj3#Issue428 훅 수정과 상호 독립 — 양쪽 모두 단독으로 증상 완화)
* 구현 명세:
    - `_claude_proc_like(pid)` 헬퍼 신설 — `ps -o comm=,args=` 로 basename claude|claude-code 또는 args 에 claude 배포본 cli.js/native-binary 매칭
    - pop 분기 진입 시 승격 1회 시도 → 성공 시 live_pid 교체 + gc_meta 재캡처 + log, 실패 시 현행 pop 유지
    - ps 호출은 live_pid 사망 시에만 발생(희귀 경로) — 폴링 비용 순증 0
    - 검증: 단명 pid 등록 시뮬레이션으로 승격 확인 + 기존 test_session_gc.py 회귀 통과

## Issue391: check.sh 가 저작 머신(host)을 소비자로 오판해 상시 FAIL 1건 ✅
* 목적: Issue389 로 인벤토리 FAIL 3건을 없앴는데 `플러그인 미설치: fpm-core` FAIL 이 남는다. 그런데 **host 에서는 미설치가 정상**이다 — 경보 피로를 없애려다 마지막 1건이 남아 `check.sh` 는 여전히 rc=1 이다
* 구현 명세:
    - 판정: `REPO_DIR` 이 `$FPM_BASE` 이면서 `~/.claude` 에 라이브 SCAR 가 존재하면 **저작 머신**
    - 저작 머신에서는 플러그인 설치 항목을 FAIL → **skip 또는 WARN** 으로 강등 (소비자 머신 동작은 불변)
    - 검증: host 에서 `bash sh/check.sh` rc=0 · 소비자 머신(host·host)에서는 기존대로 FAIL 유지

## Issue396: `fpm-backup-repo.sh` 의 push 가 git 문법상 성립하지 않는다 — `--all --tags` 동시 사용 불가 ✅
* 목적: prj3 배선 중 실측된 버그. [`scripts/fpm-backup-repo.sh`](scripts/fpm-backup-repo.sh) 의 `--push` 경로가 **한 번도 성공할 수 없는 명령**을 쓰고 있었다. 백업 실행체 자신이 백업을 못 하는 상태였다 (prj3 위임)
* 구현 명세:
    - push 를 2회로 분리: `push --all` → `push --tags`. 각각 독립 실패 메시지(브랜치/태그)로 어느 쪽이 죽었는지 드러낸다
    - 헤더 주석에 재발 방지 근거 3줄 기재 — "합치면 push 가 통째로 실패해 백업이 안 된다"
    - 검증: scratch repo 로 결합=fatal / 분리=성공 + 원격 refs(`heads/main`·`heads/develop`·`tags/v1`) 실측. `bash -n` 통과

## Issue388: `data/claude_forNewServer/` 공개 사본이 prj3 원본과 drift — 몇 달 전 SCAR 가 배포되고 있다 ✅
* 목적: Issue386 판정 중 실측. 공개 배포되는 글로벌 SCAR 사본이 원본과 어긋난 채 굳었다. 사본 방식은 원본이 움직이면 **조용히 늙는다** — 실패 신호가 없다
* depends: Issue386
* 구현 명세:
    - 판정 먼저: ⓐ 사본을 원본에서 **재생성**(동기 스크립트 + drift check) 하는가 ⓑ 매니페스트를 현행에 맞게 줄이는가
    - drift 검사를 [`sh/check.sh`](sh/check.sh) 에 편입해 **실패 신호를 만든다** — 사본 방식을 유지하려면 이것이 필수 조건
    - ⚠️ prj3 파일을 prj1 이 고치지 않는다(단방향 prj3 → prj1 사본)

## Issue386: prj3(~/.claude) 백업·미러 체계 판정 — 위임 회신 ✅
* 목적: prj3 가 remote 없는 로컬 단일 사본이라는 문제에 대해, prj1 의 publishable 체계를 재사용할지 **prj1 이 판정**해 회신한다 (prj3#Issue416 위임)
* 구현 명세:
    - 신설: [`scripts/fpm-backup-repo.sh`](scripts/fpm-backup-repo.sh) — repo 무관 오프사이트 백업. prj1·prj3 공용
    - 기본 **읽기 전용 점검**(gitleaks 이력 스캔 + 로컬↔원격 tip 대조), 쓰기는 `--push` 명시 시에만. 삭제 전파(`--mirror`) 금지 — 로컬 실수 삭제가 백업까지 지우면 백업이 아니라 복제다
    - **push 여부와 무관하게 항상 신선도를 대조하고 불일치를 non-zero 로 보고**한다. Issue387(비공개)\1의 실패 모드("백업은 있는데 최신이 아니다")를 구조적으로 검출하기 위함
    - ⚠️ 위임 범위 준수: prj3 저장소 **무수정**(읽기 전용 실측만), 원격 push **미실행**(승인 필요 → Issue387(비공개)\1

## Issue384: 📋 세션 작업 메뉴를 hover 로 연다 — 툴팁이 메뉴로 오인돼 클릭 불가였던 문제 ✅
* depends: Issue383
* 목적: 사용자 보고 — *"팝업은 나오는데 마우스 가져가면 팝업이 사라져서 클릭을 할 수가 없음."* Issue383 이 없애려던 **"발견 불가능"** 병이 툴팁 문구 층에서 그대로 재발했다

## Issue383: 📋 세션 ID 복사 버튼을 2지선다로 — 복사 / 세션 내용 새 창 보기 ✅
* 목적: **VSCode·Zed 세션은 브라우저에서 대화 내용을 볼 경로가 아예 없다.** 활성 세션 행 클릭은 origin 별로 갈리는데([server.py:10530](services/hub/server.py#L10530)) `terminal` 만 `openSessionViewer()` 로 뷰어를 열고, `vscode`·`zed` 는 에디터 탭 포커스로 빠진다. 즉 에디터 세션의 내용을 hub 에서 읽으려면 방법이 없다. 📋 버튼 자리에서 **복사 / 내용 보기**를 고르게 하여 이 비대칭을 없앤다
* 구현 명세:
    - ⚠️ **UX 분기 — 착수 전 택일 필요**:
        - **(A) 클릭 시 소형 메뉴 (권장)**: 📋 클릭 → 버튼 아래 2항목 메뉴(📋 ID 복사 / 👁 내용 보기). hover 팝업보다 접근성·모바일·오작동 면에서 안전하고, 기존 `#live-tip` hover 툴팁과 **충돌하지 않는다**
        - **(B) hover 팝업 (요청 원문)**: hover 로 팝업. 단 `.copy-sid` 는 이미 hover 에 툴팁을 띄우므로 **둘이 겹친다** — 툴팁을 팝업으로 대체하거나 지연을 둬야 하고, 포인터가 팝업으로 이동하는 사이 사라지는 고전적 문제를 처리해야 한다(선례: Issue275 hover 후 ~2.5s 지연 팝업, [debug_TECH.md](_doc_work/debug_TECH.md))
    - 메뉴 항목 2종: `copySid(sid, btn)` 재사용 · `openSessionViewer(url, topic)` 재사용
    - `s.url` 이 빈 세션은 "내용 보기" 항목을 **비활성**(회색)으로 렌더 — 눌러도 아무 일 없는 항목을 살아 있는 것처럼 두지 않는다
    - 위임 핸들러가 `closest('button,a')` 로 버튼을 제외하므로([server.py:10434](services/hub/server.py#L10434)) 메뉴 클릭이 행-클릭을 발동시키지 않는지 확인
    - `live_session_copy_button` 토글(Issue277)과의 관계 정리 — false 면 메뉴 자체가 없어지므로 "내용 보기"도 함께 사라진다. 이것이 의도인지 판단(아니면 옵션 의미를 재정의)
    - locales [ko.json](data/locales/ko.json)/[en.json](data/locales/en.json) 문자열 추가, 2원 사본([services/hub/server.py](services/hub/server.py) + [plugins/fpm-core](plugins/fpm-core/services/hub/server.py)) 동시 반영
    - 검증: vscode·zed·terminal 3 origin 각각에서 메뉴 2항목 동작 · 행 클릭 회귀 없음 · 툴팁 이중 표시 없음

## Issue381: fpm 미러가 45커밋 뒤처져 host hub 는 여전히 구버전 — 고친 것이 소비자에 도달하지 않는다 ✅
* depends: Issue377, Issue378
* 목적: hub 수정이 **host 에서만 산다**. host 은 hub 서버를 `~/_git/fpm`(공개 미러 배포본)에서 돌리는데 그 미러가 45커밋 뒤처져 있어, Issue377(양방향 funnel)·Issue378(자기이동)·Issue379(Host 게이트)가 host 에는 하나도 없다. 사용자가 최초 보고한 "URL 2종 혼란"의 host 쪽 절반이 **미수정 상태로 남아 있다**. 배포 경로를 돌려 고친 것을 소비자까지 도달시킨다
* 구현 명세:
    - ① `fpm-sync forward` — ___pm → fpm 공개 반영. `data/publishable-policy.yml` 필터 경유(개인정보 가드는 결정적 sh 헬퍼가 집행)
    - ② 45커밋 누적분이므로 **반영 후 diff 리뷰 필수** — 이번 세션 3이슈 외 Issue361~374 대의 변경이 함께 나간다. 공개 반출 부적합 문자열이 섞이지 않았는지 확인
    - ③ `fpm-sync deploy` — 버전 bump + push. ⚠️ **공개 미러 push = 외부 시스템 변경 → 사용자 승인 필수**(글로벌 룰 §5)
    - ④ 소비자 전파 — 배포 후 host·host `plugin update` 까지 수행해야 실제로 반영된다(배포만 하고 멈추면 소비자는 계속 구버전)
    - ⑤ 검증: host 에서 `/hub-shell` → 302 `/hub` · `/boards` 에 `render_tab_mode` 존재 확인
    - ⚠️ 타 머신(host) 서비스 재시작을 수반한다 — systemd 관리이므로 재시작 방법을 확인하고 진행

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

