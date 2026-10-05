---
name: Issue_public
description: "fpm 공개용 이슈 근거 요약 — Issue.md 에서 제목·목적·구현 명세만 추출한 파생본"
generator: scripts/fpm-issue-digest.sh
source_sha: cb96d673a16cec78ad7ce7b765efc1d2f03d8e8fafd173106f9fb8c97a198bc6
---

# 안내

본 문서는 자동 생성 파생본이다. 원본 이슈 트래커(`Issue.md`)는 개인정보가 포함되어 공개하지
않으며, 여기에는 **코드 변경의 근거를 이해하는 데 필요한 필드만** 추출되어 있다.

* 포함: 이슈 제목 · `목적` · `구현 명세` · `depends`
* 제외: 상세 · Walkthrough · 진행 결과 · 커밋 해시 · plan/task 경로

## 코드 주석의 `IssueN` 을 어디까지 따라갈 수 있나 (prj3#Issue469)

소스 주석의 `IssueN` 은 **내부 트래커 번호**다. 그중 **아래 "이슈 근거" 에 실린 것만**
해소된다 — 나머지는 이 저장소에서 찾을 수 없다.

* **왜 전부가 아닌가** — 공개 대상은 화이트리스트로 고른다(개인정보·미공개 결정 제외).
  게다가 **주석은 이슈보다 오래 산다**: 종결돼 아카이브로 옮겨진 옛 번호도 코드에는 남는다
* **찾지 못해도 코드를 읽는 데 지장은 없다** — 주석 본문이 근거를 이미 담고 있고,
  번호는 원본 트래커의 상호참조용 꼬리표다
* `IssueN(비공개)` 표기는 *"의도적으로 제외된 이슈"* 라는 뜻이다(번호 오타가 아니다)

직접 편집하지 말 것 — `scripts/fpm-issue-digest.sh` 가 덮어쓴다.

# 이슈 근거

## Issue604: v0.8.4 재출고 — prj1·prj3 동반 출고 + 3 OS(host·host·jpc1) 배포·hub 점검·네이티브 TDD·종합 리포트
* 목적: 15:20 v0.8.4 출고가 prj1 단독으로 나가 prj3(release/0.8.4)와 라인이 갈라졌다. 사용자 결정(2026-10-05 *"0.8.5로 브랜치가 올라갔다 … prj3과 같이 가야 하고 0.8.4는 아직 deploy도 되지 않았음"* → «재출고» 선택)으로 v0.8.4 를 prj1·prj3 동반으로 다시 내보내고, 소비자 3 OS 를 실측 증거로 판정한다
* depends: Issue605, Issue606
* 구현 명세:
    - Issue605·606 수정(TDD red 먼저) → R1(`tdd/run-release.sh --version 0.8.4`) → main merge → 원격 태그·GitHub Release 정리 → `deploy 0.8.4 --with-marketplace`
    - prj3 동반: prj3 release/0.8.4 → main merge · 태그 v0.8.4 · 다음 라인은 prj1·prj3 동시 개시
    - 소비자: host·host·jpc1 갱신 + hub 재기동 + ego-browser 점검 + 네이티브 TDD(run-remote laptop·gpu-server, GitHub 태그 clean clone 3 OS)
    - 산출: 종합 판단 리포트 `_doc_work/report/` (증거 host·host·jpc1) · 재사용 plan · deploy 절차 갱신

## Issue605: prj20 publish 무결성 매니페스트가 sanitize 이전 바이트로 생성됨 — 마켓 설치 소비자 `check.sh` 전원 FAIL
* 목적: 소비자는 prj20 마켓에서 fpm-core 를 받는데 그 안의 `.fpm-integrity.json` 이 sanitize **전** 정본 바이트로 만들어져, sanitize 가 바꾼 파일(8건)이 항상 «변조/구버전» 으로 판정된다. 진짜 변조와 구분이 안 되어 무결성 게이트가 무력화된다
* 구현 명세:
    - `do_publish`: staging sanitize **뒤** staging 트리에서 매니페스트를 재생성해 vendor 한다(정본 불변)
    - 검증(TDD red 먼저): `tdd/cases/deploy.yml` 에 publish 경로 순서 검사(sanitize < 매니페스트 재생성 < rsync vendor) — 현 코드에서 FAIL 확인 후 수정

## Issue606: hub `/boards` 가 Windows 에서 크래시 — `os.uname()` 부재로 대시보드가 `Loading…` 에서 멈춤
* 목적: Windows(Git Bash·네이티브 Python) 소비자의 hub 메인 화면이 영구 로딩 상태다. `_collect_bots()` 의 `os.uname().nodename` 이 Windows Python 에 없어 `/boards` 요청마다 AttributeError → 연결 끊김
* 구현 명세:
    - `platform.node()`(또는 `socket.gethostname()`)로 교체 — 번들 내 `os.uname()` 호출은 이 1곳
    - 검증(TDD red 먼저): `os.uname` 을 제거한 상태에서 `_collect_bots()` 호출 단위 테스트 → 수정 전 AttributeError, 수정 후 `bots_scope` 문자열 · `sh/check.sh` 크로스플랫폼 항목(15)에 `os.uname(` 정적 검출 추가

## Issue601: 릴리스 라인 마감을 출고 절차에 배선 — deploy 가 소스 태그·GitHub Release·다음 라인까지 (해결: 2026-10-05, commit: <commit>) ✅
* 목적: v0.8.3 출고 뒤 `release/0.8.3` 이 닫히지 않아 539커밋이 출고된 이름 아래 쌓이고, 출고 절차가 `deploy minor` 로 0.9.0 을 계산한 사고를 절차 수준에서 재발 방지한다
* depends: prj3#Issue967
* 구현 명세:
    - `fpm-sync.sh deploy` 마감 단계: 미러 태그에 더해 **소스(prj1) 태그** `v$NEW` · `--push` 시 **GitHub Release** `gh release create v$NEW -R Finfra/fpm --verify-tag` · 완료 로그에 «다음 라인 `release/<다음>` 을 prj1·prj3 에 열 것» 안내
    - [fpm-gitflow.md](_doc_arch/fpm-gitflow.md) R1 정리 — 규칙은 `release/{X.Y}` ↔ `{X.Y}.0` 인데 실태는 `release/0.8.0`·`0.8.1`·`0.8.3`·`0.8.4`(X.Y.Z). 한쪽으로 확정(가드는 둘 다 수용)
    - «출고» 절의 `next-version minor`·`deploy minor` 고정 해소 — VERSION 이 이미 라인 버전이면 `deploy <VERSION>`(명시), 라인 전환만 minor
    - Issue592 검증 기준 «미러·marketplace 버전 0.8.3 일치» → v0.8.4 로 정정(0.8.3 은 09-01 출고분)
    - 검증: 격리 클론에서 deploy dry 경로 — 소스 태그 생성·Release 명령 조립·`deploy patch` 가 VERSION==라인 버전일 때 경고/거부

## Issue602: hub-internal 모드에서 aoa-mq(/mq)가 내부 탭이 아니라 OS 새 탭으로 열림 (해결: 2026.10.05, commit: <commit>) ✅
* 목적: `render_tab_mode: hub-internal` 이면 hub 가 여는 화면은 /hub-shell 내부 탭에 실려야 하는데, 📮 Aoa-mq 만 OS 새 탭으로 빠져 단일 표면 계약이 깨진다
* 구현 명세:
    - `#btn-mq` 에 `data-title` + `onclick="return fpmOpenInShell(event,this)"` (비임베드 /hub 는 종전 새 탭 유지)
    - /mq 페이지에 임베드 판정 헬퍼 1개 — 임베드면 부모 셸로 `fpm-open-tab` postMessage, 아니면 새 탭. `window.open(_blank)` 지점과 same-origin `a[target=_blank]` 클릭을 이 헬퍼로 모은다(외부 URI·vscode:// 제외)
    - 검증: 회귀 테스트(red→green) — HUB_HTML 의 `#btn-mq` 라우팅 · /mq 페이지에 `_blank` 직접 호출 잔존 0 · 헬퍼가 `fpm-open-tab` 을 보낸다

## Issue600: aoa-mq·aoa-memory `tools/list` 에 `resultType` 누락 — Claude Code(2026-07-28)가 «tools fetch failed» 로 도구를 안 올려 전 세션에서 MCP 도구 부재 (해결: 2026.10.05, commit: <commit>) ✅
* 목적: 두 서버의 모든 결과 응답을 2026-07-28 계약대로 맞춰 세션이 aoa-mq·aoa-memory 도구를 다시 받게 한다
* 구현 명세:
    - `resultType` 부여를 결과 응답 한 곳(ex) `reply` 의 result 경로)으로 모아 `tools/list`·`initialize` 외 모든 result 에 적용 — 메서드별 복제 금지(판정 단일 지점) · 2026-07-28 스펙에서 필수인 메서드 목록을 스펙으로 확인
    - 검증(TDD red 먼저): [mcp/tests](mcp/tests) 에 «협상 버전 2026-07-28 이면 모든 result 에 `resultType`» 단언 → red → green · 실측: 대화형 세션 `/mcp` 에서 두 서버 ✔ 도구 수 표시
    - prj3 사본 동기: aoa-mq 설정이 `~/.claude/mcp/aoa-mq/server.py` 를 가리키므로 prj1 → prj3 동기까지 해야 해소(prj3 커밋은 보고)

## Issue598: prj8 v0.9.0 R1 재실패(2회차) 원인 제거 — 번들 표류 경합·release-run-remote 하네스 차이 (해결: 2026-10-05, commit: <commit>) ✅
* 목적: Issue597 로 닫은 R1 fail 2건이 후보 `<commit>` 에서 그대로 재발했다. 재동기·«일과성 추정»으로 닫지 말고 원인을 실측으로 확정해 제거한다
* depends: Issue597
* 구현 명세:
    - ① 판정 단일화: 번들 동기를 R1 진입 직전 단계로 고정하거나 출고 후보 시점 스냅샷으로 고정한다 — «prj3 라이브가 앞서면 R1 이 깨지는» 경합 자체를 없앤다. 선택 근거를 `_doc_arch/` 해당 출고 문서에 남긴다
    - ② R1 하네스 실행과 직접 실행의 차이(cwd·env·worktree·원격 상태)를 실측으로 확정 → 원인 제거. 진단 경로·오진(Issue597)을 `_doc_work/debug_TECH.md` 에 기록
    - 검증: R1 하네스와 같은 조건(격리 worktree)에서 `deploy-chain-integrity`·`release-run-remote` 개별 PASS + 재생목록 1행 dev-playlist-green PASS
    - 완료 시 수리 커밋·후보 커밋 hash 를 fbot-lead-fpm 에 회신 → R1 재실행부터 재배분
    - 결과: 격리 worktree(R1 하네스)에서 deploy 16/16·`test_run_remote.sh` 33/33·핀 테스트 5/5 PASS(반복 시 `--check` 10회 중 1회 표류 2건 일과성 관측 — 재현 못 함, 핀 기준 판정으로 갱신된 뒤 9/9 clean). 후속: 재출고 커밋에 `release-gates.yml` 포함
    - 진행: ② 원인 확정 = R1 하네스가 주입한 `FPM_RELEASE_CANDIDATE` 를 테스트가 상속(fixture 에 없는 SHA → rc 2, 20건) · 수리 = 테스트 env 격리. ① 수리 = 번들 동기 핀(`data/releases/bundle-live-ref`)·R1 핀 기준 판정 (`_doc_arch/fpm-release-gate.md` «번들 동기 핀»). 오진 경로 `_doc_work/debug_TECH.md` 2026-10-05

## Issue597: prj8 v0.9.0 출고 R1 fail 2건 수리 — deploy-chain-integrity·release-run-remote
* 목적: prj8 미러 출고(H:배포 승인 mq `<commit>-224248-001`)가 prj1 R1 게이트(dev-playlist-green)에서 차단됐다. 두 테스트를 원인 수리로 개별 green 으로 만든다
* 구현 명세:
    - 각 fail 의 원인을 환경 vs 코드로 실측 확정 → 원인 수리 (환경 원인이면 근거와 함께 `_doc_work/debug_TECH.md` 기록)
    - 검증: `bash tdd/run-tdd.sh --only deploy` 와 `bash scripts/test_run_remote.sh` 가 개별 전부 PASS
    - 완료 시 커밋 해시를 fbot-lead-fpm 에 회신 → fpm 팀장이 재출고(R1→main merge→deploy minor→back-merge) 재배분

## Issue595: /mq «집은 주체» 클릭 → VSCode 빈 세션 — headless(`sdk-*`) 세션을 «재개 가능»으로 판정 (해결: 2026-10-04, commit: <commit>) ✅
* 목적: VSCode 가 열 수 없는 headless 세션을 hub 가 열기 가능으로 판정해 빈 새 세션을 띄우는 것을 끝낸다 — 판정 단일 지점(`_session_open_mode`)을 확장의 실제 계약에 맞춘다
* 구현 명세:
    - `_session_open_mode(sid)`: 레지스트리 밖이면 트랜스크립트 첫 200줄의 `entrypoint`(및 `sessionKind`)를 읽어(`_transcript_cwd` 와 같은 캐시 방식) `sdk-cli|sdk-ts|sdk-py`·`daemon*` 이면 열기 불가. 레지스트리 안이라도 caps.entrypoint 가 `sdk-*` 이고 editor 표지가 없으면 같다(Zed 는 기존 분기 유지)
    - `_mq_claimed_session`: 열기 가능 여부와 열기 대체 URL(`/s/{cwd_h}/{sid}?token=…` — 기존 종료 세션 폴백 뷰)을 함께 싣는다. 대상 cwd 가 미등록이면 URL 없음 → 종전 sid 복사
    - `/mq` JS `whoHtml`·`openClaimed`: 열기 불가 세션은 ⏻ 대신 «📜 기록» 표시·툴팁 «headless 세션 — VSCode 에서 열 수 없음, 대화 기록 보기», 클릭은 새 탭으로 트랜스크립트 뷰. `/open-session` 도 열기 불가 sid 는 딥링크를 쏘지 않는다(서버 방어)
    - 검증: TDD red 먼저 — `sdk-cli` 트랜스크립트 fixture 로 `_session_open_mode` 가 `(vscode, False)` · interactive(`claude-vscode`·`cli`) fixture 는 `True` 유지 · `/mq` 수집 결과에 대체 URL · 회귀 `test_mq_progress_issue506.py`·Issue526·542 테스트 · 실측: 같은 항목 클릭 시 트랜스크립트 뷰가 열리고 VSCode 빈 탭이 생기지 않음
    - 종결 시 `_doc_work/debug_TECH.md` 에 기록(원인이 외부 도구 계약 — 기록 트리거 ③)

## Issue593: (!) /mq 잡 탭 «최신 결과 문서» 링크 — 잡 선언 `result:` → 최신 산출물 문서로 (해결: 2026-10-04, commit: <commit>, <commit>, <commit>, <commit>, prj3 <commit>) ✅
* 목적: /mq 잡 탭에서 잡이 마지막으로 만든 결과 문서를 한 번에 연다. 지금은 실행 로그(Issue581)까지만 이어지고 산출물은 찾아 들어가야 한다
* depends: prj3#Issue893
* 구현 명세:
    - ① 판정 먼저: 결과 문서가 hub 허용 트리 밖이면 `/md-doc` 가 403 이다. register-doc 경유로 열지, 허용 규칙을 넓힐지 정하고 근거를 이 블록에 남긴다(허용 범위를 넓히는 쪽이면 공개 노출 경계 점검 포함)
        - ✅ 판정(2026-10-03, 설계핀봇): **둘 다 아님 → 잡 라벨 키 전용 라우트 `GET /sched-result?job=<잡>`** — `/sched-log`(Issue580) 선례 복제. 클라이언트는 라벨만, 경로는 서버가 prj3#Issue893 잡 조회의 «최신 일치 파일» 에서 꺼낸다. 허용 단위 = 경로 패턴이 아니라 «선언된 잡 1건의 최신 1파일». 정본: [hub_htm.md](_doc_arch/hub_htm.md) "GET /sched-result?job=<잡> (Issue593)"
        - register-doc 기각: registry 가 곧 hub 카드 목록이라 결과가 카드로 쏟아지고, mtime 기준 prune(7일)이 오래된 최신 결과를 깎아 다시 403(거짓 링크), 재등록은 사용자가 지운 카드를 부활시키며 hub-internal 모드면 등록마다 탭 push
        - 경로 규칙 확장 기각: `_htm_doc_autoregister` 는 경로 접미사만 봐서 홈 아래 모든 repo 의 그 폴더(일일 브리핑 등)가 열린다. 결과 위치는 잡마다 달라 폴더 규칙으로 못 덮는다
        - 노출 경계 점검: 네트워크 반경 불변(`_ip_allowed`+`_host_allowed` 2단 게이트 뒤, 공개 포트 없음) · 데이터 반경 = `result:` 선언 잡의 최신 1파일 · 서버 재검증 `$HOME` 하위·실존·`path_is_sensitive()` 아님·`.md` · registry 무기록
        - prj3 소유 2건: 조회 결과 필드명 ✅ 확정(prj3#Issue893 `<commit>` — `status --json` jobs[] 의 `result`·`result_latest`{path,mtime}|null) · 잡 선언 문서 «`result:` 선언 = tailnet 기기 열람 동의» 문구 → prj3#Issue894 등록(`<commit>`, ② 구현의 선행 아님)
    - ② ✅ 구현(2026-10-03): `server.py` `_handle_sched_result`(`/sched-result`)·`resultLink()`(잡 탭 최근 칸 아래) · 테스트 `test_sched_result_issue593.py` 14/14·`test_mq_sched_result_link_issue593.js` 7/7 · 회귀 580 41/41·JS 10/10. ✅ 운영 hub 교체(2026-10-04 launchd 재기동) 후 실데이터 확인 — 아래 결과 참조
    - ② 잡 탭 각 행에 «📄 최신 결과» 링크(파일명·상대 시각) → `/sched-result?job=<잡>`. `result` 없음 → 링크 없음 · 일치 0건 → «결과 없음» 회색 표시 · `.htm/.html` 결과는 1차 범위 밖(파일명만 회색)
    - 검증: hub 테스트 red→green(있음·없음·0건·재검증 403·잡 없음 404 경로) + 재생목록 행 추가 · 운영 hub 교체 후 실데이터 잡 1건에서 링크가 문서를 연다

## Issue591: fpm-core 번들 누적 드리프트 25건 동기 — deploy 재생목록 `bundle-in-sync` fail 해소 (해결: 2026-10-03, commit: <commit>, <commit>) ✅
* 목적: 0.8.3 출고(Issue592)의 재검증 관문인 재생목록 #5 `deploy-chain-integrity` 가 `bundle-in-sync` 1건으로 fail 한다. 라이브(prj3) ↔ `plugins/fpm-core/` 번들을 다시 맞춰 17/17 PASS 로 되돌린다
* 구현 명세:
    - `bash scripts/fpm-bundle-sync.sh` (catalog 제외 전량) → `catalog.yml` 은 `git -C ~/.claude show HEAD:data/fbot/icons/catalog.yml` 로 번들에 기록 → 무결성 매니페스트 재생성
    - 검증: `bash tdd/run-tdd.sh --only deploy` 17/17 PASS. 단 catalog 는 라이브 미커밋분 때문에 `--check` 가 계속 DRIFT 로 볼 수 있다 — 그러면 원인과 해소 조건(prj3 커밋 후 재동기)을 결과에 적는다

## Issue590: hub Project List — Domain 열 축약·설명 잘림 해소·컬럼 정렬(정렬 상태 영속) (해결: 2026-10-02, commit: <commit>) ✅
* 목적: Project List 모달에서 설명 열이 오른쪽으로 잘리고 `Map` 열이 화면 밖으로 밀린다. Domain 열을 `g`·`w` 폭으로 줄이고 표를 모달 폭에 맞춰 설명이 보이게 하며, 헤더 클릭 정렬을 더한다
* 구현 명세:
    - Domain 헤더를 `D`(title=Domain)로 축약, 열 폭 최소화·가운데 정렬
    - 표 폭 고정(`table-layout: fixed` + 열별 폭) · 경로 `code` 는 `overflow-wrap:anywhere` · 설명 열은 남는 폭 전부 · 모달 폭 확대
    - 정렬: 번호·프로젝트명·Domain·경로·설명·hub·Map 헤더 클릭 → 오름/내림 토글, 화살표 표시. 번호는 `9a` 같은 접미 id 를 자연 정렬. 상태는 `localStorage` `plSort` 에 `{key,dir}` 저장, 재오픈·새로고침 뒤 복원
    - 검증: `test_pl_sort_issue590.js` — 서버 HTML 에서 정렬 함수를 떼어 node vm 으로 실행(자연 정렬·역순·영속 키). 브라우저 실측 1회

## Issue588: prj6 개명(___architect → ___oracle) 후속 — 옛 경로 참조 갱신 팬아웃 + 생성물 재렌더
* 목적: prj6 폴더가 `~/_git/___oracle` 로 바뀌었다(prj6#Issue21, `<commit>`). 옛 경로를 가리키는 참조를 갱신하고 호환 symlink 를 걷을 수 있게 한다
* 구현 명세:
    - prj1 자기 몫: `data/template/CLAUDE.md:7`·`.claude/skills/pm/SKILL.md:141`·`plugins/fpm-core/skills/fpm-pm/SKILL.md`(+ fpm 미러 동기)·`data/claude_forNewServer/CLAUDE.md` 의 옛 경로 → `___oracle`. `Projects_map.md:206` click href 는 재렌더로. `~/.claude/.hub-projects-cache` 는 `hub-scope.sh` 재생성 확인
    - 팬아웃(승인 후): 각 repo CLAUDE.md/AGENTS.md 의 `# 스키마 정본` 1줄 + license 링크 — 대상 목록은 prj6 세션 도구 출력 `~/.claude/projects/-Users-user--git----architect/<commit>-1a01-4df1-9568-<commit>/tool-results/bysvvvud0.txt`(repo 별 건수). 과거 기록(Issue_OLD·report·z_done·htm)은 소급 치환하지 않는다
    - 검증: `rg --hidden --no-ignore -l "___architect" ~/_git ~/_doc -g '!**/htm/**' -g '!*.jsonl' -g '!**/_doc_work/report/**' -g '!**/z_done/**' -g '!**/*_OLD.md'` 가 prj6 자기 기록(구 이름 명시) 외 0건 → symlink 제거
    - 승인 범위(총괄 C 결정 `fbotev-<commit>-<commit>`, 원 요청 `fbotreq-<commit>-<commit>` 사용자 지시): ① 타 repo 팬아웃 기계 치환·repo 별 커밋 **승인** ③ 호환 symlink 제거 **승인** — 위 검증 0건 + `old-path-gone` 통과 뒤에만 ② fpm 미러(prj8) 동기는 **보류** — mq `[H:공개]` `<commit>-194056-001` 결정 전 손대지 않는다
    - prj1 잔여(같은 배분에 묶음): `Projects_map.htm` 재렌더 · `~/.claude/.hub-projects-cache` 가 `hub-scope.sh` 로 `___oracle` 재생성되는지 확인. prj1 자기 몫은 `<commit>` 로 완료
    - **진행 결과 (2026-10-02, fbot-developer-issue588)**: ① 팬아웃 완료 — 타 repo 24곳 커밋(`<commit>` ___cg · `<commit>` _doc · `<commit>` claudeCloudSession · `<commit>` ___common · `<commit>` finfraHome · `<commit>`·`<commit>`·`<commit>` m2slide · `<commit>` videoStudio · `<commit>` fBoard · `<commit>` fSnippet · `<commit>` fSnippet/_public · `<commit>` fWarrange · `<commit>` fWarrange/_public · `<commit>` fGoogleSheet · `<commit>` fQRGen · `<commit>` social · `<commit>` dockers · `<commit>` fBanner · `<commit>` fSnippetWinv-basic · `<commit>` f-claude-plugins · `<commit>` fCapture · `<commit>` Karabiner/n2sh). 타 세션 미커밋분은 HEAD blob 치환 → 인덱스 직접 갱신으로 비혼입. 실측이 «35곳» 을 넘어 약 60 파일이었고 `~/_git` 밖 n2sh 1곳 추가 발견(tdd `old-path-gone` 이 검출)
    - ③ 완료 — `~/_git/___architect` symlink 제거, `tdd/run.sh old-path-gone` PASS. `Projects_map.htm`·`.hub-projects-cache` 는 이미 `___oracle`(재생성 불필요 확인)
    - 치환 제외(의도): prj6 자기 기록 · 이력 서술(`___pm`·social Issue.md) · 생성물(`evolved_obs_*`·m2slide `Issue_map.htm`) · 테스트 fixture(`___cg/tdd`·`test_mq_doc_issue565.py`) · fpm 미러(prj8) 전체
    - **② fpm 미러(prj8) 동기 (2026-10-02 19:5x, 사용자 세션 직접 승인 «편집+repo별 커밋»)**: fpm 6파일(`CLAUDE.md`·`sh/fpm-identity-collect`·`.claude/skills/pm/SKILL.md`·`services/hub/server.py`·`plugins/fpm-core/{services/hub/server.py,skills/fpm-pm/SKILL.md}`) 치환 + `.fpm-integrity.json` 재생성(선행 drift `commands/fpm-hub.md` 1건 흡수) → `<commit>` **로컬 커밋만, push 없음** — 공개(push·deploy)는 mq `<commit>-194056-001` 사용자 결정으로 남긴다
    - 2차 보강(같은 세션): 테스트 fixture 도 치환 — `___cg/tdd/test_doc_arch.py`(`<commit>`, 19 tests OK)·`test_mq_doc_issue565.py`(56 passed) · `architect-identity` → `oracle-identity` 문서명 참조(hub `server.py`·`fpm-identity-collect`) · fBoard `tdd/playlist.md`(`<commit>`)·social `visual-scar-inventory.md`(`<commit>`) · hub 로컬 데이터 `data/hub/*.json` 101건(gitignored, 백업 후 치환) · prj1 2차 `<commit>`
    - 커밋 안 한 편집(디스크만): fSnippet `_doc_arch/fsnippet-identity.md`(타 세션 미커밋 변경과 혼재 — 그 세션이 커밋) · 미추적 4파일(m2slide `license-attribution.md`·`m2slide-identity.md` · videoStudio `CLAUDE.md` · social `AGENTS.md`)
    - 최종 검증: 생성물(graphify-out·Issue_map.htm)·이력(Issue*.md·evolved_obs)·prj6 자기 기록 제외 **0건** · symlink 부재 확인 · `Projects_map.htm` 재렌더 0건

## Issue589: prj6#Issue21 착수 조건 7 잔여 — 수집기 미지 필드 pass-through(`--json`) + `Identity.md` `now` 열 + `tdd` 열 갱신 (해결: 2026-10-02, commit: <commit>) ✅
* 목적: prj6 가 L1 선택 필드 `handles:`·`now:` 를 더했다(Q4 담당 판정·Q5 현황 맵). 수집기가 그 값을 버리지 않고 색인·맵 자동부에 싣게 한다
* depends: prj6#Issue21
* 구현 명세:
    - `REQUIRED` 불변. 미지 필드 pass-through — 최소 `handles`·`now` 원문 한 줄
    - `--json`: 파일을 쓰지 않고 stdout 에 `{"<prj id>": {필드: 값}}` JSON 1개 · `Identity.md` 표에 `now` 열(값 없으면 빈 칸, 경고 문자열 아님) · 블록 리스트는 `--check` 에 «블록 리스트 무시» 1줄
    - 알 수 없는 플래그는 **파일을 쓰기 전에** 거부(rc 2) — 위 부작용의 재발 방지. prj1 `tdd/playlist.md` 에 재현 목표 1행
    - 검증: `bash ~/_git/___oracle/tdd/run.sh collect-passthrough collect-now-column` 전부 PASS (prj6 인수 시나리오 4·5행)
    - TDD(종결): 해당 항목 · local(host) — red 10건 FAIL → green (`python3 tdd/cases/test_identity_collect.py` PASS · prj6 `run.sh collect-passthrough collect-now-column` PASS 2/2) · playlist 69행 신설
    - 구현: `sh/fpm-identity-collect` — `PASSTHROUGH`(handles·now) · `--json` · `now` 열 · 미지 플래그 rc 2(쓰기 전) · `--check` 블록 리스트 무시 1줄 · 헤더 `정체성 (identity)`(prj6 테스트 계약). `Projects.md` 6행 tdd ➖→🆕 (gitignore 파일이라 로컬 반영만)

## Issue585: 테스트 샌드박스가 운영 aoa 폴더에 그림자 policy 를 다시 만든다 — 임시 HOME + 상속 `AOA_MEMORY_DIR` 로 Issue576 가드 통과 (해결: 2026-09-29, commit: <commit>) ✅
* 목적: Issue576 이 막은 그림자 사본이 같은 날 22:41 에 **다른 경로로** 되살아나 prj3 정본 policy 를 다시 가린다 — 가드가 «정본 유무» 를 `$HOME` 기준으로만 보고, 테스트는 `HOME` 만 바꾸고 `AOA_MEMORY_DIR` 는 운영값을 상속한다
* 구현 명세:
    - ① 테스트 격리: install·bootstrap 을 부르는 테스트 전부 `AOA_MEMORY_DIR`(·`AOA_MQ_DIR`)를 임시 경로로 명시하거나 `env -i` — `grep -ln "install.sh\|fbot-bootstrap" scripts/test_*.sh` 전수
    - ② bootstrap 방어(판정 단일 지점): `AOA_DIR` 이 `$HOME` 밖인데 `$HOME` 에 prj3 정본이 없으면 «HOME 과 데이터 루트가 다른 머신 문맥» 으로 보고 policy 를 쓰지 않거나 fail-loud — 소비자 기본 경로(`$HOME/.claude/data/aoa`)는 종전 생성 유지
    - TDD red 먼저: `scripts/test_bootstrap_policy_shadow_issue576.sh` 에 «임시 HOME + HOME 밖 AOA_MEMORY_DIR → 사본 없음» 케이스 추가 → 현행에서 red 확인 → 수정 → green · 재생목록 58 행 목표 갱신
    - 검증: prj1 `tdd/run.sh` 전체 실행 전후 운영 `~/_git/___common/data/aoa/policy.yml` 부재 유지(실행 전 사본이 없을 때)

## Issue587: prj3#Issue757 종결분 번들 동기 — 관리직 몸체 추가 배선·환기 대상·매뉴얼 개정 12종·관찰 봇 표지 (해결: 2026-09-29, commit: <commit>) ✅
* 목적: prj3#Issue757 마무리(2026-09-29) 변경을 fpm-core 번들에 싣는다 — Issue757 구현 명세의 «prj1 번들 md5» 검증
* 구현 명세:
    - `bash scripts/fpm-bundle-sync.sh` → `--check` 표류 0 · prj1 재생목록(번들 동기 행) green · 라이브↔번들 md5 대조
    - 선행 확인: prj3 쪽 해당 파일에 미커밋 편집이 없는지(`git -C ~/.claude status --porcelain -- <경로>`) — 있으면 그 커밋 뒤 동기

## Issue584: tagcheck 맹점 3종 — prj3#Issue793 의 prj1 `scripts/precommit-tagcheck.py` 짝 (해결: 2026-09-29, commit: <commit>) ✅
* 목적: prj3 `sh/precommit-tagcheck.py` 와 2원 구조인 prj1 짝을 같은 판정(«staged Issue.md 에서 그 번호의 블록이 바뀌었는가»)으로 맞춘다
* depends: prj3#Issue793
* 구현 명세:
    - prj3#Issue793 의 판정 함수와 동일 규칙으로 개정 — TDD red 먼저(맹점 ⓐⓑⓒ 재현)
    - 검증: prj1 tagcheck 테스트 green · prj3#Issue793 결과에 prj1 해시 병기
    - TDD(종결): 해당 항목 · local — prj3 `sh/test-precommit-tagcheck.py` 를 [test_tagcheck_block_touched_issue584.py](scripts/test_tagcheck_block_touched_issue584.py) 로 이식(케이스 동일, issue-tx 는 prj3 공유본) → red 7(ⓐ·ⓑ·net-zero·ⓒ 선언 단일·복수·인과 인용·issue-tx e2e) → green 17/17 · 회귀 Issue566 7/7 · 재생목록 [tdd/playlist.md](tdd/playlist.md) 67행 `tagcheck-block-touched` 러너 pass

## Issue583: projects-map 박스별 분리 렌더 — Main Map 순서대로 서브맵을 따로 그려 쌓는다 ✅
* 목적: 사용자 지시 *"프로모션을 가장 위에, 다음이 App 개발, 그 아래 강의_과목"*(2026-09-28). 한 장 flowchart 에서는 **박스 세로 순서를 지정할 수 없다** — dagre 가 교차 최소화로 정하고, 데이터 편집마다 다시 섞인다. 사용자 선택: **박스별 분리 렌더**(ELK 대안은 아래)
* 구현 명세:
    - **박스 순서** = Main Map `Goal` 자식 중 참조(`"맵"`)의 순서 → 참조되지 않은 서브맵은 파일 순서로 뒤에(현재 Infra 하나 — `@6` 경유로 이어짐)
    - **머리 다이어그램**: Main Map(Goal·`@6` 판정 주체)은 작은 도식 1장으로 맨 위에. 박스 간 간선(Goal 부채꼴)은 순서 자체가 대신한다
    - **박스마다 mermaid 1장**(`flowchart LR` + 현행 init 간격). 제목 = 서브맵 이름. 다른 박스에도 나오는 노드(현재 `42 m2slide`: 프로모션 정의 + 강의_과목 뿌리)는 두 박스 모두에 그린다 — 세션 배지·hover 는 `flowchart-P{id}-` 를 `querySelectorAll` 로 찾으므로 두 곳 모두 붙는지 확인
    - 박스를 넘는 트리 간선은 현재 없다(`6 → 5` 는 Infra 박스 안, `58 ↔ 58a` 는 제거됨). 생기면 그 자리에 «→ {맵} {노드}» 표식
    - 보존: 숨김(Issue574)·미할당 목록·note 박스·텍스트 트리·Issue573 id 해시·데드 루프·목적 충돌 검사
    - red 먼저: 순서가 다른 서브맵 3개 + Main Map 참조 순서를 가진 임시 소스로 **출력 HTML 의 박스 등장 순서 = 참조 순서** 단언
    - 검증: hub `/projects-map` 에서 위→아래 `Main Map 머리 · 프로모션 · fApp · 강의_과목 · 컨설팅 · Infra`, 박스별 축소 없음(폭 ≤ 컨테이너)

## Issue545: 핀봇 ↔ 이슈맵·nPTiR 연동 + 지시 흐름 시각화 (prj1 화면 구현) (해결: 2026-09-28, commit: <commit>) ✅
* 목적: 누가 누구에게 무엇을 시키고 있는지 root 기준으로 보이지 않는다(사용자 지적 4·5). 설계 SSOT 는 prj3
* depends: prj3#Issue739, prj3#Issue740
* 구현 명세:
    - prj3#Issue739(구 Issue725 M1 — 원장 공백 제거·`parent_dispatch_id`) 완료 전 착수 금지 — 원장이 비면 화면도 빈다
    - 검증: 실배분 2단 이상 체인 1건 실측 렌더

## Issue581: /sched-log 회차 절단·잡 산출물 링크 — Issue580 C·D 후속 (해결: 2026-09-28, commit: <commit> — D 는 이슈후보로 분리) ✅
* 목적: Issue580 은 누적 로그 끝부분 + «회차 구분 불가» 로 동작한다. 과거 회차를 누르면 이후 회차 출력이 보인다 — 회차 단위로 잘라야 「최근 실행」 행 링크가 그 회차 결과가 된다
* depends: prj3#Issue780
* 구현 명세:
    - prj3 이슈 등록(경계 표식 형식 합의) → prj1 절단 + 테스트(경계 있음/없음 혼재 로그 · 회전 경계 · 거짓 절단 금지)

## Issue579: fbot 신규 훅 2종 번들 편입·플러그인 배선 — SendMessage 위임 자동 기록·포그라운드 Agent 봇 매핑 (prj3#Issue739) (해결: 2026-09-28, commit: <commit>) ✅
* 목적: prj3#Issue739 M1-3 이 훅 2종을 신설했다(prj3 <commit>). prj3 `settings.json` 에는 배선됐으나 번들(`plugins/fpm-core/hooks/`)·플러그인 `hooks.json` 에는 없다 — 플러그인 설치 머신에서 SendMessage 로 넘긴 지시가 원장에 안 남고, 포그라운드 Agent 봇의 송신자가 미상이 된다(prj3#Issue559 가 훅 7종에서 겪은 같은 결손)
* depends: prj3#Issue739
* 구현 명세:
    - `fpm-bundle-sync.sh` 신규 편입(수동) → 번들 복사 · 매니페스트 `FPM_MANIFEST_EXTRA`
    - 플러그인 `hooks.json` 배선 4건(PreToolUse Agent·SubagentStart·SubagentStop·PostToolUse SendMessage) — 예산: 플러그인 쪽 SubagentStart 이벤트 신설
    - 검증: prj3 `hooks/test-fbot-agent-map.py`·`test-fbot-sendmessage-record.py` 를 번들 경로로도 실행 · 설치 머신에서 SendMessage 지시 1건 → 원장 `source=sendmessage` 1건

## Issue580: /mq 스케줄·잡 탭에 실행 결과 링크 — 「최근 실행」 행 → 그 회차 로그, 잡 → 마지막 실행 결과 (해결: 2026-09-28, commit: <commit>) ✅
* 목적: 사용자 요청(2026-09-28, prj5 세션 — «"최근 실행"에서 결과 확인하는 링크 추가 · 잡에서도 마지막 실행 결과 링크»). 지금 `/mq?tab=schedule` 「최근 실행」 표와 스케줄·잡 행의 「최근」 칸은 ledger 의 시각·rc·소요만 보여 준다. **무엇이 나왔는지**는 `~/.claude/data/schedule/log/<잡>.out·.err` 를 터미널로 열어야 안다
* 구현 명세:
    - A (prj1 단독) 잡 로그 뷰 라우트 `/sched-log?job=<잡>[&run=<pid>]` — 잡 이름은 `_SCHED_NAME_RE` 로 검증하고, 파일 경로는 `schedule.sh status --json` 의 잡 `log` 필드(없으면 `data/schedule/log`)에서 **서버가 조립**한다(사용자 경로 입력 없음). `.out`·`.err` 를 `_send_md_html` 셸로 보이고, 잡음 줄은 접는다(숨기지 않는다)
    - B 링크 배치 — 「최근 실행」 각 행 · 스케줄 행 「최근」 · 잡 탭 「최근」(= 마지막 실행 결과)의 rc pill 옆에 📄 → `/sched-log`
    - C 회차 단위 절단은 **prj3 보강이 선행**한다 — `schedule-run.sh` 가 실행 전후 `.out`·`.err` 에 경계 줄(`── <ts> <event> <job> pid=<pid> ──` / `── rc=<rc> <dur>s ──`)을 남기거나, ledger detail 에 `off=<out>,<err>` 를 싣는다. prj1 은 `run=<pid>` 로 그 구간만 자른다. prj3 보강 전에는 A·B 가 **누적 로그 끝부분 + «회차 구분 불가» 안내**로 동작한다(거짓 절단 금지). prj3 이슈는 C 착수 시 등록
    - D (선택) 잡 산출물 링크 — 잡 선언에 `result:`(파일 glob, ex) `~/_git/___common/mq-asset/강모/*.md`)를 두면 잡 탭에 «최신 결과 문서» 링크. 403 을 피할 방법(register-doc 경유·허용 규칙)은 착수 시 판정
    - 검증: hub 테스트 — `/sched-log` 잡 이름 검증(`../`·대문자 거부)·없는 잡 404·잡음 접힘 · 세 칸의 링크 렌더(js, 기존 `test_mq_job_*` 형식)
    - 요청 출처: prj5 세션(Issue106 주간 수집 운영 중) — 등록 대행

## Issue577: projects-map 배치 압축 — Main Map 을 박스에서 빼고 간격을 줄여 축소 없이 읽히게 (해결: 2026-09-28, commit: <commit>) ✅
* 목적: 사용자 지적 *"좀 잘 보이게 배치, 공간 낭비 없게"*(2026-09-28). 원본이 화면보다 훨씬 커서 폭 맞춤으로 **축소**되고, 그만큼 글자가 작아진다. prj6 가 `Projects.md` 만으로 할 수 있는 부분은 적용했고, 남은 개선은 생성기 코드 몫이다
* 구현 명세:
    - `render_mermaid()`: Main Map 노드는 `subgraph` 없이 정의(맵 경계 표시가 필요하면 Goal 노드 스타일로 대신) · 머리에 flowchart init 지시문
    - 기존 규약 보존: 노드 id `P{id}`(세션 배지·hover JS) 불변, 숨김(Issue574)·미할당 목록 불변
    - 검증: 현행 `Projects.md` 로 viewBox 폭 ≤ 1675(축소 없음) · 노드 점유율 v2 대비 상승 · hub 캡처

## Issue578: hub /mq 스케줄 탭 발화 누락 표시 — 가동 중 누락(⚠)·꺼짐 누락 배지 + 최근 기대·발화 요약 (prj3#Issue775 후속) (해결: 2026-09-28, commit: <commit>) ✅
* 목적: prj3#Issue775(<commit>)가 `schedule.sh status --json` 에 발화 누락 판정(`events[].missed`·최상위 `missed`)을 더했다. 스케줄 탭은 «다음 실행» 만 보여 줘, 예정 시각에 **안 돈 것**이 화면에 드러나지 않는다(2026-09-28 prj3 세션 통지 — 이슈후보에서 승격)
* 구현 명세:
    - 스케줄 행 «상태» 칸 + 이벤트 상세표에 누락 배지: `up` 이 있으면 ⚠ 빨강 «누락 N», `off` 만 있으면 회색 «꺼짐 누락 N» · title 에 슬롯 시각·원인 목록
    - 부제에 «최근 {hours}h 기대 {expected} · 발화 {fired}» + 누락이 있으면 «⚠ 누락 N(가동중 a · 꺼짐 b)»
    - TDD(red 먼저): 서빙 스크립트 `renderSchedule()` 을 node 로 실행해 배지·요약 렌더 단언

## Issue574: projects-map 숨김 표기 — 일부러 안 그리는 프로젝트가 «미할당(목적 없음)» 상자에 섞인다 (해결: 2026-09-28, commit: <commit>) ✅
* 목적: 사용자가 맵을 **프로젝트 단위로 간추리려고** 표시하지 않을 프로젝트 11건을 지정했다. 트리에서 빼면 그래프에서는 사라지지만, 완전성 보장이 이들을 `미할당 11건` 상자로 되살려 *"아직 어느 목적에도 붙지 않은 프로젝트 — 목적 미할당 신호"* 라고 표시한다. **숨김**과 **목적 없음**이 한 자리에 섞여 미할당 신호가 오염되고, 숨긴 것도 계속 보인다
* 구현 명세:
    - 표기 후보: `# Project Map` 안 `### 숨김` 절(렌더 제외 맵) 또는 노드 접두 표기. 숨김 목록은 완전성 계산에 넣어 `미할당` 에 뜨지 않게 하고, 필요하면 다이어그램 아래 별도 «숨김 N건» 접힘 목록으로 둔다
    - 숨김 표기 문법은 [projects-map-design.md](_doc_arch/projects-map-design.md) «표기 규칙» 에 추가 · `.claude`·`.agents` 사본 둘 다
    - red 먼저: 숨김 절에 적은 id 가 `미할당` 목록에 **없음**을 단언하는 테스트 → 현행 실패 확인 후 구현
    - 이관: 위 11건을 숨김 절로 옮겨 `미할당 0건` 이 되는지 확인

## Issue573: projects-map 한글 맵 이름 subgraph id 충돌 — 글자 수가 같은 서브맵이 한 박스로 합쳐진다 (해결: 2026-09-28, commit: <commit>) ✅
* 목적: `Projects.md` 서브맵 `### 생애 판정` 을 추가하자 `### 강의_과목` 과 **한 박스로 합쳐져** 렌더된다. 두 맵 이름이 모두 5글자라 subgraph id 가 같아지기 때문이다. 앞으로 한글 맵이 늘수록 같은 길이끼리 계속 충돌한다
* 구현 명세:
    - 방향: 치환이 일어난 키에만 원문의 짧은 해시를 접미한다(ex: `SG_____` + `_{sha1[:6]}`). ASCII 키(`P9a`·`SGfApp`·`SGInfra`)는 그대로 두어 JS 규약을 건드리지 않는다
    - `.claude`·`.agents` 사본 둘 다(playlist #26 과 같은 이중 사본)
    - red 먼저: 같은 길이 한글 맵 2개를 가진 임시 소스로 subgraph id 가 서로 다름을 단언 → 현행 실패 확인 후 수정. `tdd/playlist.md` 에 재현 목표 1행
    - 검증: 현행 `Projects.md` 재생성 시 subgraph 8개 · hub `/projects-map` 에서 `생애 판정`·`강의_과목` 이 별개 박스

## Issue576: fbot-bootstrap 이 prj3 정본이 있는 머신에 그림자 policy 사본을 만든다 — 로더 1순위라 정본을 가린다 (해결: 2026-09-28, commit: <commit>) ✅
* 목적: prj3#Issue755 관측·prj3#Issue757 스위치 켜기 중 확정. 2026-09-27 18:41 `sh/fbot-bootstrap.sh` 가 운영 aoa 폴더(`AOA_MEMORY_DIR`=`~/_git/___common/data/aoa`)에 템플릿으로 `policy.yml` 을 만들었다. fbot 로더는 «aoa 폴더 → prj3 정본 → policy_org» 순이라 이 사본이 prj3 정본(`~/.claude/data/aoa/policy.yml`, Issue626 이관)을 가린다 — prj3 정책 개정(`fbot_dispatch_repeat_hourly_limit` 등)이 운영에 안 닿고, 새 스위치(`fbot_manager_multibody`)도 켜지지 않는다
* depends: prj3#Issue757
* 구현 명세:
    - `sh/fbot-bootstrap.sh` 3단계 앞: 정본 판정(`$HOME/.claude/data/aoa/policy.yml` 존재 · aoa 폴더 실경로 ≠ 정본 폴더 실경로) → 건너뜀 + 사본 경고
    - 검증: `scripts/test_bootstrap_policy_shadow_issue576.sh`(red 먼저) · 기존 `test_decision_policy_seed_issue566.sh` 불변

## Issue575: hub 핀봇 카드·타임라인에 관리직 몸체 표시 — 한 관리직의 여러 몸체를 구분 (prj3#Issue757 T15 ⑦) (해결: 2026-09-28, commit: <commit>) ✅
* 목적: prj3#Issue757 T15 — 관리직(총괄·팀장)은 지휘 흐름마다 몸체가 하나씩 뜬다(몸체 원장 `fbot_body`). 봇 행은 몸체들의 사영이라 카드의 «세션» 칸은 최근 몸체 하나만 보여 준다 — 몇 개의 몸체가 어떤 흐름을 쥐고 있는지 화면에서 보이지 않는다. 사용자 승인(2026-09-28)
* depends: prj3#Issue757
* 구현 명세:
    - IO: `_fbot_board_data` 가 살아 있는 몸체(open · lease 유효)를 읽어 `_fbot_board_payload(bodies=)` 로 넘긴다
    - payload: `bots[bid].bodies = [{session, flow, state, started_at}]`(최근 순) · 이벤트·job payload 에 `by_session`·`by_flow` 통과
    - 카드: 몸체 2개 이상이면 «몸체 N» 줄에 흐름·상태 · 관리직 타임라인 항목에 몸체 표지(세션 앞 8자)
    - 검증: `test_fbot_bodies_issue575.py`(red 먼저) · hub `test_*.py` 전건 · 매니페스트

## Issue568: /mq 「🔨 작업 중 · 🙋 내 차례 · ⏳ 대기」 구분 표시 + [진행] 클릭 즉시 대상 prj 기동 (prj3#Issue770 추적) (해결: 2026-09-28, commit: <commit>, <commit>) ✅
* 목적: 사용자 지적(2026-09-28) — `/mq-doc?id=<commit>-113830-001`(기다려야 함)과 `<commit>-120452-001`(진행 중이어야 함)이 화면에서 똑같이 `in_progress` 주황 배지라 구분되지 않고, [진행] 을 눌러도 대상 prj 에서 아무것도 시작되지 않는다. 상태 어휘·승인 판정·대상 prj·기동 helper 는 큐 정본인 prj3#Issue770 몫이고, 여기는 prj1 이 소유한 화면과 [진행] 배선이다
* depends: prj3#Issue770
* 구현 명세:
    - **배지 3색**: 🔨 작업 중(주황 — 현행 + 경과) · 🙋 내 차례(빨강, `needs_human` 존재 시, 목록 **최상단 고정**, 체크리스트 펼침) · ⏳ 대기(회색, `wait_for` + `recheck_ts` 표시, 경과 배지 없음). `/mq-doc` «정보» 표에도 같은 표기와 `대기 조건`·`재확인`·`승인`·`대상 prj` 행 추가(`_mq_item_md` `:3222`)
    - **버튼**: ⏳ 항목 [▶ 재개] · 🔨 항목 [⏸ 대기로](사유·재확인일 입력) · 🙋 체크리스트 항목별 [승인]. 모두 prj3 helper 경유(큐 파일 직접 쓰기 금지)
    - **[진행] 즉시 기동**: start 처리 직후 hub 가 prj3 `aoa-mq-progress.sh launch <id>` 호출 → 결과(기동 cwd·세션 id·거부 사유)를 행에 즉시 표시. 대상 cwd 에 살아 있는 세션이 있으면 기동 대신 그 세션으로 전달하고 `/open-session` 링크를 세운다(`_mq_claimed_session` `:2934` 재사용)
    - 회귀 테스트(red 먼저): `test_mq_render_issue521.js` 계열로 3배지·버튼 조건, `test_mq_doc_issue565.py` 에 정보 행 추가 케이스, [진행]→launch 호출 목(mock) 테스트
    - 실례 2건으로 수용 확인: 113830 → ⏳(재확인 09-29 09:00) · 120452 → [진행] 시 prj16 cwd 에서 기동, 세션 몫 수행 후 🙋 (스크린샷 선정·Connect 제출·privacy 게시)

## Issue543: 출고 TDD 강화 — 격리 worktree R1·G4→R2·네이티브 머신·출고 후 검증 (해결: 2026-09-28, commit: <commit>, <commit>, <commit>, <commit>, <commit> — 잔여 M4·M5 prj8#Issue2 이관) ✅
* 목적: G3 기록 12/12 `dirty: yes` 로 지금 deploy 하면 G4 가 항상 막힌다. prj8 배포·push 절차와 mac(다른 머신)·linux·win 설치 검증이 출고 전 TDD 로 고정돼 있지 않다(사용자 지적 2·3, prj3#Issue715 정합)
* depends: prj3#Issue726
* 구현 명세:
    - M0 격리 worktree 실행기(기록은 본 작업트리로) → M1 드라이버 `tdd/run-release.sh`·md 증거 → M2 R2 배선 → M3 원격 러너(laptop·gpu-server) → M4 win11 → M5 P1~P3
    - 검증: 각 마일스톤 red 재현 후 green (task 파일 완료 조건)

## Issue556: fpm-core Apache-2.0 번들 전파(prj8·prj20) + prj20 README 예외 줄 교체 — Issue550 후속 (해결: 2026-09-28, commit: <commit>, <commit> — 잔여 prj8#Issue1·prj20#Issue13 이관) ✅
* 목적: Issue550 이 원천 `plugins/fpm-core/.claude-plugin/plugin.json` 을 Apache-2.0 으로 고쳤지만 미러 2곳은 아직 PolyForm NC 다. 전파는 원천에서만 한다(미러 직접 수정 금지 — Issue550 상세). forward 는 `release/*` 에서 G2 dry-run 이라 이 세션에서 반출할 수 없었다
* depends: Issue550
* 구현 명세:
    - 트리거: fpm 다음 출고(main 병합 + forward/deploy)
    - 검증: prj8·prj20 사본의 `plugin.json` `license` = `Apache-2.0` · `gen-integrity-manifest.sh --check --bundle <미러>/plugins/fpm-core` OK · prj20 README 예외 줄 교체

## Issue572: 핀봇 비실행 원칙 prj1 측 — fbot 데이터 번들 동기(조직 선언 스윕·신설 매뉴얼 seed) + hub 카드 요청 버튼 관리직 한정 (prj3#Issue757 추적) (해결: 2026-09-28, commit: <commit>, <commit>)
* 목적: prj3#Issue757(총괄·팀장은 일을 직접 하지 않는다 — 사람 지시는 총괄·팀장만 받는다) 의 prj1 측. 사용자 승인(2026-09-28 «승인함 진행. 단, prj1의 세션 검토»)
* depends: prj3#Issue757
* 구현 명세:
    - `scripts/fpm-bundle-sync.sh` — 번들에 이미 있는 `data/fbot/org/_hq.yml`·`org/_template/*`·`manuals/ref/*` 이름 일치 스윕 추가. ⚠️ 번들의 사용자 prj 인스턴스(`org/<N>.yml`, prj3#Issue559 편입)는 대상 아님(범위 밖 — 공개 경계 판단은 별건)
    - 신설 매뉴얼 9종 + `ref/` 2종 수동 seed(«신규 편입은 수동» 원칙) → 이후 스윕이 따라간다 · 무결성 매니페스트에 신규 파일 명시(`FPM_MANIFEST_EXTRA`)
    - hub: «요청 보내기» 조건 `mgr` → 총괄·팀장(`nonexec`) · «재기동 요청(wake)» 총괄·팀장 카드만 · 워커 카드엔 «팀장에게 요청» 안내
    - TDD(red 먼저): `scripts/test_bundle_sync_fbot_data_issue572.sh`(스윕 대상·인스턴스 무접촉·--check 고지) · hub 카드 버튼 조건 테스트 · `tdd/playlist.md` 행

## Issue561: 핀봇 질문 상향 중계 prj1 측 — 번들 동기 + hub 카드 «❓ 질문 대기» 답변 UI (prj3#Issue749 추적) (해결: 2026-09-28, commit: <commit>, <commit>, <commit>, <commit>, <commit>) ✅
* 목적: 사용자 요청(2026-09-28 `/dev`) — 나래가 팀장에게 일을 시키고 팀원이 AskUserQuestion 상황을 만나면 질문이 **사람에게 의뢰를 받은 세션**으로 올라가 거기서 사람에게 물을 수 있어야 한다. 핵심(포착·라우팅·배분 `blocked(question)`·재개)은 fbot 훅 SSOT 인 prj3 몫이라 prj3#Issue749 로 등록했다(사용자 결정 2026-09-28 «prj3 이슈 + prj1 추적»). 여기는 prj1 이 소유한 두 가지 — 번들 사본과 hub 답변 창구
* depends: prj3#Issue749
* 구현 명세:
    - 번들 동기: `scripts/fpm-bundle-sync.sh` → `--check` 표류 0 · md5 일치 확인 후 `Chore(bundle): prj3#Issue749 …` 커밋
    - hub 카드: 배분이 `blocked` + `payload.blocked_by=question` 인 워커 카드에 «❓ 질문 대기» 칩 · 수신 매니저 카드 인박스 목록에서 `kind=question` 항목은 질문·선택지를 렌더하고 선택지 버튼 + 자유 입력 «답하기» 제공
    - `POST /fbot-inbox-reply` — `fbot-inbox.py reply <qid> --status done --body <답> --by hub:<사람>` 얇은 래퍼(판정·재개는 prj3 `reply` 가 한다 — 서버에 복제 금지). `_handle_fbot_inbox_send()` 와 같은 경로 해석·503 폴백
    - TDD(red 먼저): `services/hub/test_fbot_question_issue561.js`(또는 py) — 칩 렌더·선택지 버튼·reply POST 인자 · `test_fbot_inbox_badge.py` 회귀 유지 · `tdd/playlist.md` 행 추가

## Issue566: fpm-bundle-sync 가 data/decision-authority.yml 을 동반하지 않음 — 번들 동기 후 플러그인 사용자의 [컨펌] 전건 거부 (해결: 2026-09-28, commit: <commit>) ✅
* 목적: prj3#Issue756 이 mq 등록 helper(`aoa-mq-enqueue.sh`)에 `[컨펌] [H:<분류>]` 게이트를 넣었고, 게이트는 정책 파일 `~/.claude/data/decision-authority.yml` 을 읽는다(부재 시 fail-loud). `scripts/fpm-bundle-sync.sh` 는 manuals·icons 만 동기해(`:219-220`) helper 만 번들에 실리면 플러그인 사용자 머신에서 모든 `[컨펌]` 이 exit 1 로 거부된다
* 구현 명세:
    - `fpm-bundle-sync.sh` 동기 목록에 `data/decision-authority.yml` 추가 → `--check` 로 표류 0 확인 · 다음 출고(Issue556) 전 동기
    - 원안 정정(2026-09-28 착수 실측): **번들에 싣는 것만으로는 소비자에게 닿지 않는다.** helper 는 번들이 아니라 repo `mcp/aoa-mq/` 로 배송되고, 번들 훅·helper 모두 `$HOME/.claude/data/…` 를 읽는다. 소비자 머신에서 그 자리를 채우는 주체는 `sh/fbot-bootstrap.sh`(install.sh 가 호출) 하나뿐이다 → 원본은 repo 템플릿으로, 배치는 bootstrap 이
    - `scripts/fpm-bundle-sync.sh`: `sync_file data/template/decision-authority.yml ← ~/.claude/data/decision-authority.yml` (aoa-policy.default.yml 과 같은 템플릿 자리, Issue449) — helper(mcp/aoa-mq)와 같은 커밋으로 나가야 한다는 주석
    - `sh/fbot-bootstrap.sh` 4단계: `${AOA_DECISION_POLICY:-~/.claude/data/decision-authority.yml}`(helper 와 같은 해석) 부재 시에만 템플릿 복사 · 존재하면 불변(키 병합 안 함 — H 분류 목록은 운영자의 방침이라 템플릿 값을 덧붙이면 방침을 몰래 넓힌다) · 템플릿 부재는 fail-loud exit 1
    - 동기: `--only data/template/decision-authority.yml` + `--only mcp/aoa-mq`(prj3#Issue756 산출 3건 — 게이트 helper·server.py·게이트 테스트)를 이 커밋에 함께 싣는다
    - 배포 케이스 `decision-policy-template-tracked`(tdd/cases/deploy.yml) — 저작 머신은 prj3 추적 파일이 늘 있어 존재 검사로는 통과하므로 **git 추적**을 본다 · 재생목록 #51 `decision-policy-shipped` · #5 케이스 17건
    - TDD: red — `scripts/test_decision_policy_seed_issue566.sh` 7 실패(템플릿 미동기·--check 무고지·bootstrap 미seed·배송 helper 게이트 없음) → green — 10/10 · 회귀 `test_bundle_sync_no_clobber.sh` 10/10 · `mcp/aoa-mq/test-aoa-mq-confirm-gate.sh` 18/0 · 배포 케이스 red(UNTRACKED) → 커밋 후 재실행
    - 커밋 중 발견·수정: tagcheck 훅이 동기 사본 `mcp/aoa-mq/test-aoa-mq-confirm-gate.sh:37` 의 prj3 번호로 커밋 거부 — 제외가 번들(`plugins/`, Issue364)에만 걸리고 같은 동기 스크립트의 두 번째 목적지 `mcp/<유닛>/` 에는 없었다(판정 한쪽만 갱신). `scripts/precommit-tagcheck.py` 가 `fpm-bundle-sync.sh` 의 `sync_mcp_unit` 선언에서 제외 접두를 파생(목록 복제 없음 · `mcp/server.py` 는 계속 검사). TDD: red — `scripts/test_tagcheck_sync_dest_issue566.py` 3 실패 → green 7/7
    - TDD(종결): 전체 · local — red 7 → green 10/10 · tagcheck red 3 → green 7/7 · 재생목록 전 행(HEAD `<commit>`) pass 48·fail 1·skip 5 — fail #25 는 이 이슈와 무관(Issue561 번들 동기 회귀, `<commit>` 복구 후 7/7) · 배포 케이스 17/17

## Issue571: 핀봇 조직도 보드 요약 배지 — 상태·열린 배분·교착·자리 배지도 클릭하면 목록 ✅
* 목적: 사용자 요청(2026-09-28 `/dev`, 스크린샷) — 보드 탭 요약 바에서 인박스·미종결은 누르면 내용이 나오는데(prj1#Issue557) «작업중·수신대기·완료대기·출근중·퇴근·열린 배분»(+교착·자리·공석·스폰 대기)은 `<span>` 이라 숫자만 보이고 무엇이 그 수인지 확인할 길이 없다
* 구현 명세:
    - 패널 일반화: `state.chip`(열린 배지 키 1개) + 공용 패널 1개. 인박스도 이 경로로 합류(같은 배지 재클릭 = 접기, 다른 배지 = 전환)
    - 순수 함수 `chipRows(data, key)` — 상태 키(`working`…`checkout`)는 그 상태 봇, `open_dispatch` 는 열린 배분, `deadlocks` 는 ⛔ hard(명부에 없음 고아 + 순환), `spawning` 은 스폰 대기, `seats` 는 공석 자리. **행 수 = 배지 수**(summary 와 같은 기준)
    - 항목 클릭: 봇 → 자리 선택 + 조직도 포커스(인박스 행과 같은 착지) · 배분 → `selJob` · 공석 → 그 자리 선택
    - TDD(red 먼저): `services/hub/test_fbot_chip_panel_issue571.py` — 서빙 JS 의 `chipRows` 를 node 로 실행해 키별 행 수 = summary 수 · 배지가 전부 `data-go` 버튼 · `test_fbot_inbox_badge.py` 회귀 유지

## Issue569: hub mermaid 가 라벨 속 `x@` 하나로 통째로 오류 박스가 된다 — 부동 CDN 태그 + 무방비 렌더 ✅
* 목적: fWarrange 라이브 뷰(`/s/…/live`) 문서의 flowchart 가 «Syntax error» 폭탄으로 대체됐다(사용자 신고). 라벨 `C[%@ ↔ %lld 불일치]` 한 줄이 원인이다. 같은 계열(라벨 문자 하나로 다이어그램 전체 소실)이 prj3#Issue183·prj3#Issue733 에 이어 세 번째이고, 둘 다 작성 룰 보강으로만 막았다
* 구현 명세:
    - `md_shell.py` 에 공용 `MERMAID_JS`(한 벌) — `quoteLabels`(flowchart/graph 의 따옴표 없는 노드·edge 라벨을 `"…"` 로) · `plan`(파싱 OK → 그대로 / 실패 → 따옴표 보정 후 재파싱 OK → 보정본 / 여전히 실패 → 원문 코드블록 + 오류 한 줄) · `run`(직렬화)
    - 유효한 다이어그램은 **건드리지 않는다** — 보정은 파싱이 실패했을 때만, 보정본이 파싱될 때만 채택
    - `CDN_MERMAID` 를 정확 버전(현 서빙본 11.17.2)으로 고정 — 오늘 동작 변화 0, 이후 문법 변경은 의식적 bump 로만
    - `server.py` `MERMAID_RUNTIME` 은 `md_shell.CDN_MERMAID`·`MERMAID_JS` 로 조립 — 사본 제거
    - 검증: `test_mermaid_heal_issue569.js`(보정·판정 단위 + 두 런타임 단일 출처) red→green · 실 CDN 브라우저에서 보정본 렌더 · 신고 라이브 뷰 재확인

## Issue570: 핀봇 조직도 「승인 필요 액션」에서 컨펌할 수 없음 — 에스컬 판정 통일 + 사람 결정 대기 인라인 처리
* 목적: `/fbot-map` 봇 상세의 「승인 필요 액션 (mq [컨펌] · 사람 ACK 후 집행)」 칸을 사람이 **결정 대기 목록**으로 읽는데 누를 것이 없다(상비봇은 안내 1줄뿐). 옆의 빨간 「에스컬 8」 은 전부 이미 수락된 요청이라 거짓 경보다. 사람은 무엇을 어디서 답해야 하는지 모른 채 봇이 멈춘 것으로 본다(사용자 지적 2026-09-28 — *"이거 어떻게 컨펌하나? … 계속 멈춰있게 됨"*)
* 구현 명세:
    - ① 에스컬 = `escalated_at ∧ result IS NULL` 로 통일: 봇별 `escalated` 집계 SQL · 요청 job `problem` · `work.deferred(unaccepted)` 가 같은 기준을 쓴다
    - ② 봇 상세에 「사람 결정 대기」 칸 신설 — mq 미종결 중 `[컨펌]` ∧ `source` 가 그 봇인 항목을 싣고, 행마다 **승인·거절 버튼**(기존 `/mq-ack` 계약 그대로, 새 종결 경로 없음)과 문서 링크(`/mq-doc`). 없으면 *"이 봇이 기다리는 사람 결정 없음"* 을 명시
    - ③ 기존 칸은 「관리 요청 올리기 (→ mq [컨펌])」 로 이름을 바꿔 결정 대기 목록으로 오독되지 않게 한다
    - ④ 열린 요청은 원장 로드의 7일·400건 상한과 무관하게 따로 싣는다(`_fbot_extra_jobs`). 실측 — 이벤트가 7일 1,780건이라 400건이 3.5시간치(09:41 이후)로 줄어 나래의 열린 요청 18건이 「받은 일 0」 으로 사라졌다. 기다리는 일이 안 보이면 멈춘 이유도 안 보인다
    - 검증: 순수 함수 단위 테스트(에스컬 판정·결정 대기 매칭·상한 밖 열린 요청) red → green, 실서버 `/fbot-map.json` 에서 나래 `escalated` 0 확인
    - 범위 밖(prj3 이관): 매니저가 수락하면서 *"사용자 확인 후 착수"* 로 미룬 요청이 `[컨펌]` 으로 올라가지 않아 조용히 멈추는 규약 결손 → prj3#Issue773 (`fbotreq-<commit>-<commit>`) — hub 가 산문을 해석해 잡을 일이 아니다

## Issue565: /mq 큐 탭 — 📋 mq ID 메뉴(스케줄·잡과 같은 꼴) + 내용 클릭 → 문서 뷰(md-doc 셸) + 처리 버튼 이모지 ✅
* 목적: 큐 탭에는 mq 번호를 복사할 길이 없다(스케줄·잡 탭은 📋 메뉴가 있다 — Issue540·558). 또 내용 열은 `esc()` 로 개행까지 뭉개 한 덩어리 산문으로 보인다 — `1) … 2) …` 번호 목록·`①②③` 하위 항목이 있는 결정 묶음은 특히 읽기 어렵다(사용자 요청, 스크린샷 `<commit>-102923-001`)
* 구현 명세:
    - 서버: `GET /mq-doc?id=<id>` — id 형식 검증(경로 탈출 차단) → `queue/`·`queue_done/` 의 `<id>.json` 직접 조회(종결 40건 한도 밖도 열림) → `_mq_item_md()` 가 md 조립 → `_send_md_html()`
    - `_mq_item_md()`: 첫 줄 = 제목(` — ` 앞, 선두 `[태그]` 는 칩) · 메타 표(ID·상태·마감·등록·출처·질의) · 본문 줄 `N)` → 번호 목록, `①…` → 하위 불릿, 번호 없는 긴 산문은 문장 단위 불릿 · 진행 3종(집은 주체·진행·결과) 절 · `prjN#IssueM` → `/issue` 링크, 본문 속 mq id → `/mq-doc` 링크
    - 화면: 내용 본문 클릭(텍스트 선택 중·링크·버튼 클릭 제외) → 새 탭 `/mq-doc` · 📋 메뉴 = mq ID 복사 · 내용 복사 · 문서로 보기 · 문서 링크 복사
    - TDD(red 먼저): `test_mq_doc_issue565.py`(md 조립·id 검증·조회) + `test_mq_id_menu_issue565.js`(행 📋·본문 링크·메뉴 항목) · 재생목록 행 추가

## Issue567: install.sh 완료 안내 heredoc 의 백틱이 명령으로 실행된다 — `python3 server.py` 가 호출 위치에서 돈다 ✅
* 목적: Issue543 M3 네이티브 실측(host·host 둘 다)의 샌드박스 로그에 `python3: can't open file '…/src/server.py'` 가 찍혔다. `sh/install.sh` «5. 안내» 가 `cat <<EOF`(따옴표 없는 heredoc — `$REPO_DIR` 전개용)인데 본문에 `` `python3 server.py` `` 를 백틱으로 적어, 설치할 때마다 **호출한 셸의 cwd 에서 그 명령을 실행**한다. 안내 문구에서는 그 부분이 빠진다
* 구현 명세:
    - 백틱 이스케이프(`\``) — heredoc 은 `$REPO_DIR` 전개가 필요해 따옴표 heredoc 으로 바꿀 수 없다
    - TDD(red 먼저): `scripts/test_install_heredoc_backtick.sh` — ① `server.py` 스텁(표식 파일 생성)이 있는 cwd 에서 샌드박스 install → 스텁 미실행 ② 안내 출력에 `` `python3 server.py` `` 문자 그대로 ③ 정적 검사: `sh/*.sh` 의 따옴표 없는 heredoc 본문에 비이스케이프 백틱 0 · 재생목록 행 추가

## Issue564: claude CLI 판정이 7곳으로 갈림 — 공식 설치 경로 `~/.local/bin` 을 케이스·install·uninstall·check 가 못 찾는다 ✅
* 목적: Issue543 M3 원격 러너의 첫 네이티브 실측(host, 2026-09-28)에서 `claude-cli-available` 이 FAIL(`MISSING`) — host 에는 `~/.local/bin/claude`(공식 네이티브 설치 경로)가 **있다**. SSH 비대화 PATH 에 없을 뿐이다. 같은 결함을 `sh/update.sh` 는 prj3#Issue467(2026-08-30)에서 관례 경로 4개 탐색으로 고쳤는데, **나머지 판정 지점은 한쪽만 갱신된 채 갈라져** 있다
* 구현 명세:
    - 해석 단일 지점 `sh/fpm-claude-bin.sh` — `fpm_resolve_claude`(`sh/fbot-python.sh` 와 같은 꼴). 후보: PATH → `~/.local/bin` → `~/.claude/local` → `/opt/homebrew/bin` → `/usr/local/bin` → `/usr/bin` → nvm 최신. 채택 = 실행 가능. PATH 밖에서 찾으면 그 디렉토리를 PATH 앞에 붙여 기존 `claude …` 호출을 그대로 살린다(호출부 무변경). CLI 모드 `bash sh/fpm-claude-bin.sh` = 경로 출력(대화 셸 PATH 를 건드리지 않아야 하는 fpm_function.sh 용)
    - 7곳 전부 이 해석기로 교체 · 케이스도 같은 해석기를 부른다(케이스와 실행체의 판정이 다시 갈리지 않게)
    - TDD(red 먼저): `scripts/test_claude_bin_resolve.sh` — 해석기 후보·우선순위·실행 불가 제외·전멸 rc 1 + **claude 가 PATH 밖(`$HOME/.local/bin`)에만 있는 샌드박스에서 install.sh 가 SCAR 를 건너뛰지 않는다** · 재생목록 행 추가
    - 검증: host 원격 러너 재실측에서 `claude-cli-available` ✅

## Issue562: /mq alert 버튼 단일화 — 통지(done_unacked)는 «확인» 하나로, 후속 없음으로 종결 (prj3#Issue750 후속) ✅
* 목적: 사용자 지적(2026-09-27, `/mq` 스크린샷) — *«어짜피 확인 아님 버림인데, 둘 차이도 미묘함»*. 통지 항목에 [확인]·[버림] 두 버튼이 있으나 사람이 읽고 닫는 동작은 하나다. 실측으로는 차이가 **있다** — 그런데 그 차이가 사용자 의도와 반대 방향이다
* depends: prj3#Issue750
* 구현 명세:
    - `notice` 분기 버튼을 [확인] 하나로. 종결 action 은 «후속 없음» 으로 기록되게 한다 — 택1: ① 버튼이 `dismiss` 를 호출(라벨만 확인) ② prj3 정책 `handoff_no_followup_actions` 에 `acked_done` 추가(prj3 이슈 필요 — 정책 SSOT 가 prj3). ② 가 의미상 정확하나 repo 가 갈린다 — 착수 시 결정
    - 후속이 필요한 통지는 [확인] 대신 [진행]·[mq-handoff] 경로가 이미 있다 — 이 경로는 건드리지 않는다
    - 검증: `/mq` 통지 행 버튼 1개 · 누른 뒤 handoff 가 `z_consumed/` 로 이관(승격 대상 아님) · 기존 `[컨펌]`·예약 행 버튼 불변

## Issue560: hub 핀봇 현황 배치 — 큰 조직만 세로로 길고 옆 열이 비는 문제 ✅
* 목적: 사용자 요청(2026-09-28, `/hub` 스크린샷) — 조직 그룹(Issue547) 하나가 `.grid` **한 칸**이라, 활성 10 인 `claude 팀장핀봇` 그룹은 카드 10장이 한 열로 내려가고 활성 1 인 나래·pm 그룹 열은 카드 1장 아래가 통째로 빈다. 카드 수와 무관하게 그룹 폭이 같은 것이 원인
* 구현 명세:
    - 그룹 폭 = 활성 카드 수(열 수로 클램프) — `span min(k, C)`. 그룹 안 카드는 같은 열 폭의 내부 grid 로 가로 배치 → 활성 10 그룹은 3열×4행, 나래·pm 은 한 줄에 나란히
    - `#bots-grid` 는 `auto-fill` + `grid-auto-flow: row dense` — 빈 칸을 작은 그룹이 메우고, 그룹 1개일 때 카드가 전폭으로 늘어나지 않는다(카드 폭 일관)
    - 열 수 C 는 렌더 직후·ResizeObserver 로 계산(`gridTemplateColumns` 트랙 수). 접힌 섹션(`none`)은 건너뛴다
    - TDD: `test_bot_layout_issue560.py` red 먼저(원문 JS 추출·node 실행) · Issue402·546·547 회귀 유지 · `tdd/playlist.md` 행 추가

## Issue558: /mq 잡 탭 📋 잡 ID 팝업 — 스케줄 탭(Issue540)과 같은 꼴 + 부가 기능 ✅
* 목적: 사용자 요청(2026-09-27·28, `/mq?tab=schedule` 팝업 스크린샷) — 스케줄 탭 행에는 📋 팝업(스케줄 ID 복사·실행 명령 복사·지금 실행·설명·잡 열기)이 있는데 잡 탭에는 잡 ID 를 복사할 길이 없다. 잡 이름은 CLI `schedule.sh dispatch --job <이름>`·큐 `job:` 필드가 그대로 쓰는 식별자다
* 구현 명세:
    - 잡 행 액션 열 맨 앞에 `📋`(`.sid-copy` · `data-kind="job"`) — `.agrid` 6버튼(Issue554)은 그대로
    - `jobMenuOpen()` — 같은 `#sch-menu` 재사용. 머리 = 잡 이름 · «📋 잡 ID 복사» · «⌨️ 실행 명령 복사»(`bash ~/.claude/hooks/schedule.sh dispatch --job <이름>`) · «▶ 지금 실행»(confirm) · «✎ 설명 추가/수정»(시스템 잡 disabled) · «🗓 스케줄 보기 (N)»(스케줄 탭 «🧩 잡 열기» 의 짝)
    - 메뉴 위치 계산은 `schMenuPlace()` 로 뽑아 두 메뉴가 공유 · hover-intent 위임은 `idMenuOpen()` 한 곳에서 `data-kind` 로 가른다
    - TDD: `test_mq_job_id_issue558.js` red 먼저 · Issue554 판정 «시스템 잡 액션 없음» → «📋 만» 계약 갱신 · Issue549·555·521 회귀 유지 · `tdd/playlist.md` 행 추가

## Issue544: dashboard(board) 자동 검증 3층 — L1 단위·L2 headless 시나리오·L3 실 worker ✅
* 목적: board 시나리오 s1~s9 는 수동 확인 기록뿐이고 TDD 재생목록에 board 항목 0건이다(사용자 지적 1)
* depends: prj3#Issue727
* 구현 명세:
    - M0 기존 3종 등재 → M1 L1 신규 3종(prj3) → M2 격리 하네스·`tdd/cases/board.yml` → M3 실 worker E2E(`tdd/release.md` 7행)
    - 검증: 운영 tmux·hub(9876) 무접촉 음성 검증 포함

## Issue557: 핀봇 보드 «미종결·인박스» 배지를 목록으로 잇는다 — 누르면 미종결 배너로 이동·매니저별 인박스 요청 펼침 ✅
* 목적: 보드 요약 바의 «미종결 N · 인박스 N» 배지가 숫자만 보이고 눌러도 아무 데도 안 간다(사용자 질의 2026-09-27 «사용자가 어떻게 확인하나»). 미종결은 상단 노란 배너에 목록이 있으나 배지와 연결이 없고, 인박스는 누구 앞인지조차 안 보여 매니저를 하나씩 눌러 봐야 한다 — 인박스 전체 목록 자체가 없다
* 구현 명세:
    - 서버: `_fbot_board_data` 가 인박스 수와 **같은 쿼리**로 행을 모아 `_fbot_board_payload(inbox_items=)` 에 넘기고, payload `inbox` 배열(id·owner·owner_title·from·body·ts·escalated)로 싣는다 — 수(`summary.inbox_open`)와 목록이 같은 기준
    - 화면: 미종결 배지 클릭 → 상단 미종결 배너로 스크롤·강조. 인박스 배지 클릭 → 요약 바 아래 패널 토글, 매니저별로 묶어 경과·보낸 이·요지 표시, 행 클릭 → 그 매니저 선택
    - TDD: `services/hub/test_fbot_inbox_badge.py` red → green
    - TDD: red — 12 FAIL(payload inbox 키·배지 data-go·패널 부재) → 실측 후 2단언 추가 red 2 → green 14 passed · 기존 hub 테스트 4종 135·274·16·6 passed
    - 실측(ego-browser): `scrollIntoView({behavior:"smooth"})` 는 2초 뒤에도 0px — 즉시 스크롤로 교체. 요약 바가 SSE·폴링마다 5초 1회 교체돼 클릭 순간 요소가 바뀜 — 직전 문자열과 같으면 건너뜀(6초 0회). 원장 무변경 클라이언트 주입으로 목록 렌더·행 클릭(`sel=hq/hq-chief-1&job=…`) 확인

## Issue550: `Projects.md` license 열 신설 + prj8 fpm PolyForm NC → Apache-2.0 (prj6#Issue17 집행) ✅
* 목적: prj6 정본(license-profiles.md)의 집행 두 건 — 레지스트리 열은 prj1 소유(조항 1)이고, fpm 은 Issue.md 없는 공개 미러라 이슈를 여기 둔다
* 구현 명세:
    - 검증: `Projects.md` 소비처 파서 정상 · fpm 파일 5종 존재 · README 절 링크
    - 금지: `git push`(두 repo 모두 사용자가 push) · 기존 태그 변경
    - `Issue.md` 는 `sh/issue-tx.py stage --issues <N>` / `check` 경유 · 커밋 2건(prj1 hash · prj8 hash 둘 다 기록) 후 ✅ 이동

## Issue555: /mq 잡 탭 — 스텝을 2열로 독립(잡 | 스텝 | 최근 · 걸린 곳 | 액션) ✅
* 목적: 사용자 지적(2026-09-27, Issue554 반영 직후) — *"스텝은 두번째 컬럼으로 독립, 첫번째 컬럼에 내용이 너무 많음"*. Issue554 로 설명·상태 표시를 옮겼어도 1열에 이름 줄·스텝 칩·메타 줄이 남아 있다
* depends: Issue554
* 구현 명세:
    - `<td class="jsteps"><div class="jsteps-in">칩 · 메타</div></td>` — `.jsteps-in{width:max-content;max-width:22rem}` (칩은 기존 `.stp` 15rem 상한 유지)
    - thead `잡 | 스텝 | 최근 · 걸린 곳 | (액션)`
    - TDD: `test_mq_job_steps_col_issue555.js` red 먼저 — thead·셀 수·1열에 칩·메타 없음·2열에 칩·메타·폭 상한 규칙. Issue554 테스트는 열 번호 대신 셀 class 로 찾게 고쳐 성질(설명 이름 줄·걸린 곳 병합·상태 표시·버튼 grid)만 계속 지킨다. `tdd/playlist.md` 행 추가(`mq-job-steps-column`)
    - 검증: ego-browser 실화면 열 폭·가로 넘침

## Issue554: /mq 잡 탭 레이아웃 — 1열 정보 분산(설명 제목 옆 · 걸린 곳→최근 병합 · 상태 표시 이동 · 액션 2행) ✅
* 목적: 사용자 지적(2026-09-27, `/mq?tab=job` 주석 스크린샷) — 잡 행의 1열(잡 · 스텝)에 이름·설명·멈춤 표시·스텝·메타가 몰려 세로로 길고, 오른쪽 액션 6버튼이 한 줄로 가로 폭을 차지한다. 정보를 옆 열로 나누고 액션을 2행으로 접어 폭을 확보한다
* 구현 명세:
    - 열 구성 `잡 · 스텝 | 최근 · 걸린 곳 | (액션)` — 3열. 1열 = 이름 줄(이름 + 설명 + ✎) · 스텝 칩 · 메타
    - 2열 = `<div>최근</div><div class="jref">상태 표시 + 🗓 N · ⏰ N</div>`
    - 3열 = `.agrid`(`display:inline-grid; grid-template-columns:repeat(3,auto)`) 안에 6버튼 — 열 정렬된 2행
    - TDD: `test_mq_job_layout_issue554.js` red 먼저 — 서버가 내려준 스크립트를 vm 에서 실행해 thead·셀 수·이름 줄·상태/걸린 곳 순서·버튼 순서·grid 3열 규칙 판정. Issue549·521 회귀 유지. `tdd/playlist.md` 행 추가(`mq-job-layout-spread`)
    - 검증: ego-browser 캡처로 실화면 확인

## Issue553: hub 자리 해소 경로 connection 1개 관통 — prj3#Issue732 짝 (완료: 2026-09-27)
* 목적: prj3#Issue732 가 `fbot-org.py` 판정 함수에 `con=None` 관통 규약과 git 활동 캐시를 넣었다. hub 쪽 `_fbot_org_seats_compute`·`_org_all_scopes`·`_org_formed_cached` 가 connection 하나를 열어 넘겨야 요청당 sqlite 177회가 1회가 된다. Issue551 의 스냅샷 캐시는 «요청 비용을 끊는» 층이고, 이것은 «콜드 계산 자체를 싸게 하는» 층이다
* depends: prj3#Issue732

## Issue552: hub 홈 핀봇 명부가 해고·휴직자를 조직 구성원으로 센다 — 조직도와 재직 판정이 갈림 ✅
* 목적: 사용자 지시(2026-09-27) *"하나 제거. prj60"* — prj60 팀장 중복의 한쪽 `fbot-lead-issue4` 는 원장에서 **이미 해고(career·employment = terminated)** 인데 홈 명부(`_fbot_roster`)는 원장 전원을 실어 prj60 그룹 구성원·머리 후보로 계속 셌다. 조직도는 `_fbot_filter_career`(Issue451)로 휴직·해고를 빼므로 **같은 사실을 두 화면이 다르게 말한다**
* 구현 명세:
    - ⓐ `_fbot_retired(career)` 신설 = `career in ("leave", "terminated")`. `_fbot_filter_career` 가 이를 사용
    - ⓑ `_collect_bots`: 퇴역 행은 `bots_roster`·`bots_total` 에서 제외(활성 카드는 원래 상태 축으로 이미 빠짐)
    - TDD: `test_fbot_bots.py` 에 red 먼저 — 해고·휴직 봇이 roster 에 없고 total 에서 빠지며, 그룹 머리 후보도 아니다

## Issue547: hub 홈 핀봇 카드의 그룹 축을 루트 봇 → prj 조직으로 (조직도 org 탭과 축 일치) ✅
* 목적: 홈 카드는 Issue402 이후 루트 봇(부모 사슬 끝) 기준 그룹인데 원장의 `parent_bot_id` 는 55/60 이 `fbot-lead`(본사 팀장 자리)다 — 배분 체인 기록용 부모이지 조직 단위가 아니다. 결과 *"팀장핀봇 활성 1/56"* 한 그룹에 팀장 41·워커 15 가 전부 들어가 "어느 prj 가 무슨 일을 하나" 가 안 보인다 (Issue546 진단 문서 원인 B)
* depends: Issue546
* 구현 명세:
    - ⓐ 그룹 키 = `prj`(None 이면 본사 그룹 1개). 그룹 헤더 = 그 prj 의 팀장(`pm_bot` 판정과 같은 규칙 — role lead + prj) 호칭, 없으면 `prj{N}`
    - ⓑ 그룹 정렬은 `_org_scope_key`(hub 활성 세션과 같은 `_pid_sort_key`) 재사용
    - ⓒ *"활성 0 조직은 그리지 않는다"*(Issue611) 는 prj 단위로 그대로 적용
    - ⓓ 회귀: `test_fbot_bots.py`·`test_fbot_map_issue402.py` 의 root 기반 검사 재작성

## Issue551: 핀봇 조직도·보드 무한 로딩 — 요청마다 sqlite 177회·git 22회를 도는 자리 해소가 I/O 정체에 100배 증폭 → 스냅샷 캐시(single-flight·SWR) + 보드 JS 타임아웃 (완료: 2026-09-27)
* 목적: 2026-09-27 20:42 `/fbot-map#sel=7/ops-lead-1` 이 로딩에서 멈춤(사용자 신고). 실측 `/fbot-map`·`/fbot-map.json` 30~80초(완주 79.7초), 같은 순간 `/boards` 0.05초. 서버가 멈춘 게 아니라 조직 판정 경로가 I/O 정체에 비례해 느려졌고, 보드 JS `fetch` 에 타임아웃이 없어 스피너가 무한처럼 보였다. 진단 전문: `_doc_work/debug_TECH.md` 2026-09-27 항목
* 구현 명세:
    - `_fbot_org_seats(prj)` 를 **스냅샷 캐시** 로: 키 `prj`, TTL 60s + 조직 yml mtime 서명. **single-flight**(동시 요청은 한 계산을 공유) + **stale-while-revalidate**(만료 항목은 즉시 반환하고 배경 스레드가 갱신). 계산 본체는 `_fbot_org_seats_compute` 로 분리
    - `fbot-org.py` 는 mtime 이 바뀔 때만 `exec_module`(`_org_mod`). `_org_formed_invalidate`(해산 버튼) 가 스냅샷도 함께 비움. 기동 시 배경 예열 1회
    - 보드 JS `load()`: `AbortController` 20s → «서버 응답 지연» 표시 + 10s 후 재시도 (증상 가시화)
    - 검증: `test_fbot_org_cache_issue551.py` — 동시 6요청 계산 1회 · TTL 내 캐시 · 만료 시 즉시 반환+배경 갱신 · 해산 무효화 · 모듈 mtime 재로드 · JS 타임아웃 존재. hub 재기동 후 부하 재현(find×6+dd) 아래 `/fbot-map.json` 웜 <1s 확인

## Issue549: /mq 잡 탭 — 설명 인라인 추가·수정(✎ 설명) 스케줄 탭과 동일 UX ✅
* 목적: 사용자 요청(2026-09-27) — `/mq?tab=schedule` 행에는 ✎ 설명 버튼이 있어 프롬프트 한 번으로 스케줄 설명을 붙이는데, `/mq?tab=job` 은 잡 폼(✎ 수정)을 열어야만 설명을 고칠 수 있다. 잡 설명(«무엇을»)도 같은 한 번 클릭으로 붙인다
* 구현 명세:
    - ⓐ `renderJobs()` 잡 행의 설명 줄(`.jdesc`)에 사용자 잡 한정 `✎ 설명`(추가)·`✎`(수정) 버튼(`.mini.bnote` — hover 노출 CSS 공유) → `jobNote(name)`
    - ⓑ `jobNote(name)`: `prompt`(현재 desc 프리필) → 취소면 no-op · 200자 초과면 거부 · 그 외 `sPost({action:"job-edit", name, desc: trim})` → `sReload()` (잡·스케줄 탭 둘 다 desc 갱신)
    - TDD: [`test_mq_job_note_issue549.js`](plugins/fpm-core/services/hub/test_mq_job_note_issue549.js) red 먼저 — 렌더(사용자 잡 desc 유·무·시스템 잡)와 전송 payload(trim·취소·빈 값=삭제·200자 초과 거부). `tdd/playlist.md` 행 추가(`mq-job-note-inline`)

## Issue546: hub 홈 핀봇 카드 — 퇴근 칩 기본 접힘 + 개수 상한 (웨이브 날엔 Issue450 의 24h 창이 무력) ✅
* 목적: 사용자 지적(2026-09-27) — 홈 핀봇 섹션의 팀장핀봇 그룹 아래 퇴근 칩 30여 개가 나열돼 *"너무 복잡"*. Issue450 은 24h 이내 퇴근만 칩으로 남겼는데, 하루 26 prj 웨이브로 24h 안에 31 봇이 퇴근하면 전부 선다 — **시간 창만 있고 개수 상한이 없다**
* 구현 명세:
    - ⓐ 그룹당 퇴근 칩을 **한 줄 토글**(`bot-rest-toggle`: `최근 퇴근 {r} · 퇴근 전체 {n} ▸`)로 접는다. 기본 접힘, 클릭으로 펼침. 펼침 상태는 `openBotRest` Set 으로 5초 재렌더에도 유지(Issue104 `expandedCards` 와 같은 패턴)
    - ⓑ 펼쳐도 **개수 상한** `BOT_CHIP_MAX = 6` — 최근 퇴근 중 최신순 6개까지 칩, 나머지는 기존 `bots.restMore`(조직도 `?all=1`) 링크로. 24h 창(`BOT_RECENT_SEC`)·`bot-chip-recent` 강조는 유지
    - ⓒ i18n `bots.restToggle` ko·en(parity) · CSS `.bot-rest-toggle` + `.bot-group-rest[hidden]`(flex 가 hidden 을 이기지 않게)
    - ⓓ 토글 클릭은 Issue401 아코디언(`.bot-card[data-bot]`)·Issue505 이름 링크(`a`)와 충돌하지 않게 `bindBotToggle` 에서 먼저 가로챈다
    - TDD: [`test_fbot_bots.py`](plugins/fpm-core/services/hub/test_fbot_bots.py) 에 red 먼저 — 상한 상수·토글 클래스·기본 hidden·i18n 키. `tdd/playlist.md` 행 추가(`hub-bot-rest-collapsed`)

## Issue542: hub 문서 헤더 세션 버튼 — 에디터 능력별 표시·동작 분기 ✅
* 목적: 세션 딥링크가 없는 에디터(Zed 등)는 아이콘만, VSCode 처럼 세션을 열 수 있으면 아이콘+"열기" 표시. "열기"가 없으면 클릭 시 앱 포커스만 이동
* 구현 명세:
    - `server.py`: `_EDITOR_SESSION_DEEPLINK` 능력표 + `_session_open_mode()` · `/open-session` 에서 불가 에디터는 앱 포커스만(`_focus_editor_app`)
    - `md_shell.py`: 헤더 버튼을 `data-sid/cwd` + 에디터 아이콘(`/editor-icon/<ed>.png`, emoji 폴백) + 조건부 "열기" 로 렌더, nonce 스크립트로 클릭 바인딩(배지 포함)
    - `SID_COPY_SHIM`: `data-sid` 우선 읽기(onclick 정규식은 htm 문서 호환 폴백)
    - 검증: 단위 테스트(렌더 분기·판정·CSP 인라인 핸들러 부재) + 라이브 셸 실측

## Issue541: prj1 TDD 재생목록 전 목표 green — prj5#Issue100 배분분 ✅
* 목적: 나래(prj5#Issue100) 배분 — `tdd/playlist.md` 16목표 전부 실제 실행해 green, red 는 원인 수정
* 구현 명세:
    - 완료 판정: 러너 전체 + `--only release` + hub `test_*.py` 전건 + 신규 4테스트 PASS (실행 머신 host — 셸·파이썬 경량 격리 테스트만, 빌드성 없음)

## Issue537: (!) TDD 미실행 프로젝트 10개 첫 TDD 실행 배분 ✅
* 목적: TDD 재생목록은 있으나 한 번도 TDD 프로세스를 타지 않은 프로젝트에 첫 red→green 을 돌린다 (사용자 지시 — 나래)
* 구현 명세:
    - 완료 판정: `fbot-lead.py sweep` 수령 + 나머지 8개 재생목록 ✅ 1개 이상

## Issue540: /mq 스케줄 탭 — 스케줄 ID hover 메뉴(복사 + 부가 기능)
* 목적: 스케줄(바인딩) ID 를 복사할 방법이 없다. hub 활성세션의 📋 세션 ID 메뉴(Issue383·384)처럼 hover 로 여는 메뉴에서 ID 복사와 부가 기능을 제공한다
* 구현 명세:
    - [server.py](plugins/fpm-core/services/hub/server.py) /mq 페이지 JS·CSS — hub `#sid-menu` 패턴(Issue384 hover 브리지)을 /mq 에 이식
    - 검증: ego-browser 로 hover → 메뉴 표시 · ID 복사 결과 확인

## Issue538: 핀봇 보드 — 팀장핀봇(자리) 클릭 시 조직도에 무관한 타 프로젝트 레인까지 전부 표시 (완료: 2026-09-27)
* 목적: 자리·봇을 고르면 그 팀 레인만 보여야 한다. 타 prj 레인은 **협업(배분 왕래)이 있을 때만** 함께 선다
* 구현 명세:
    - 선택 prj 판정 단일 지점 `laneKeyOf()` — scope/dept/자리 주소/봇 focus(임시 워커면 소속 레인) 모두 같은 키로 수렴. 본사(hq)는 한정 없음(현행)
    - 협업 판정 `lanePick()` — 기간 안 dispatch 의 양 끝(owner·dst)이 선택 레인과 타 레인에 걸치면 그 타 레인을 협업으로 포함
    - 검증: 순수 함수 node 실행 테스트(`test_fbot_map_issue402.py`)

## Issue536: 핀봇 조직도 그래프 탭 — 「전체 보기」 스크립트 오류·「기록 보기」 무반응·root 오지정 링크 (완료: 2026-09-26)
* 목적: 사용자 요청으로 나래(prj3 총괄핀봇)가 ego-browser 로 검토한 결과, 그래프 탭(`/fbot-map?tab=map`)의 토글 두 개가 제 역할을 못 한다(2026-09-26 실측). 사용자 지시 «진행»(나래 경유)
* 구현 명세:
    - ① 오류 원인 줄 특정(CDN 스크립트라 `Script error.` — `crossorigin` 속성 또는 로컬 재현으로 메시지 확보) → 퇴근 봇·채용 엣지가 섞인 데이터에서 레이아웃이 깨지는 조건 수정(부모 자기참조·존재하지 않는 노드 참조·compound 순환 등 점검). 한 그래프의 실패가 다른 그래프 초기화를 막지 않게 격리
    - ② `hist=1` 이 그래프 데이터에 완료·취소 배분을 실제로 포함하는지 서버측 필터 확인 → 포함되게 수정(숨김 계수와 일치)
    - ③ `root=fbot-lead` 를 만드는 링크 교정(루트 판정과 같은 규칙 사용)
    - 검증: ego-browser 로 `tab=map` · `all=1` · `hist=1` · `all=1&hist=1` 4개 URL 에서 오류 0, org boundingBox 가 노드 수에 맞게 퍼짐, flow cy 생성, `hist=1` 에서 배분 엣지 증가 · `test_fbot_map_issue402.py` 회귀
    - 외부핀봇 활용: 변경분은 codex-diff-reviewer 2차 의견 1회

## Issue535: 조직도 그래프 봇 상세 패널 링크가 개체 봇 id 를 `?root=` 에 실어 "루트 핀봇이 아닙니다" 경고
* 목적: 그래프 노드 클릭 → 옆 패널 "보드에서 이 봇 보기 →" 가 `/fbot-map?tab=board&root=<개체 bot_id>` 를 만든다. `root_filter` 는 루트 봇과만 대조되므로 `unknown_root` 경고가 뜨고, 탭·토글 링크(`_href`)가 root 를 보존해 org 탭까지 경고가 따라간다(실측 `root=fbot-contractor-issue415` — 부모 `fbot-lead`)
* 구현 명세:
    - 패널 링크를 `/fbot-map?tab=board#bot=<id>` 로 통일 (botNameLink 와 같은 계약)
    - 검증: 회귀 테스트 — 그래프 JS 에 `tab=board&root='+encodeURIComponent(d.bot)` 부재 · `#bot=` 존재

## Issue532: hub 가 라이브 뷰 탭과 md 문서 탭을 따로 띄워 브라우저 탭이 두 배로 쌓임 (완료: 2026-09-26)
* 목적: 세션당 브라우저 창 하나 — 라이브 뷰가 유일한 창이 되고 md 문서는 그 안에 인라인으로 나타난다. 자동 모드에서 문서 없는 턴은 탭 0개
* 구현 명세:
    - mailbox 가 hub 문서 Write 를 `doc` 블록(경로만)으로 적재 → 라이브 셸이 `/md-doc?raw=1` 로 인라인 렌더
    - `GET /live-route` 로 세션 라이브 창 생존 판정 → `fpm-browser-open.sh` 가 md-doc URL 을 열기 전에 조회(skip / 라이브 URL / 원래 URL, fail-open)
    - prj3 훅 선오픈은 `..show` 턴 한정
    - 검증: 단위 테스트 + hub 재시작 후 실측 탭 수

## Issue533: VSCode 에서 채팅 이름을 바꿔도 hub 세션 카드 제목이 안 바뀜 (완료: 2026-09-26)
* 목적: VSCode 탭 rename 이 hub 활성 세션 카드에 반영되지 않는다. refresh 해도 자동 제목(ai-title)이 그대로 남는다
* 구현 명세:
    - `custom-title` 을 `ai-title` 보다 우선. 역방향 스캔 중 `custom-title` 을 먼저 만나면 즉시 채택, `ai-title` 만 만나면 후보로 두고 같은 window 끝까지 `custom-title` 을 계속 찾는다
    - 검증: `test_session_title_issue533.py` — rename 후 ai-title 재append 배치에서 customTitle 반환, rename 없으면 aiTitle, 재rename 시 최신 customTitle

## Issue531: hub 핀봇 카드가 수신대기 봇을 "lease 만료·크래시 의심"으로 오표시 (완료: 2026-09-26)
* 목적: 사용자 입력을 기다리는 살아 있는 세션(나래 <commit>, PID 생존)이 hub 에서 크래시 의심으로 뜬다. reap(`fbot-state.py cmd_reap`)은 prj3#Issue554 로 waiting_input 에 `idle_ttl_secs` 유예를 두는데 hub `_collect_bots` 의 `lease_stale` 은 `now > lease` 만 봐서 판정이 갈렸다
* 구현 명세:
    - `lease_stale` 에 reap 과 같은 유예 규칙 적용(waiting_input 이고 `lease + idle_ttl_secs` 이전이면 stale 아님). `idle_ttl_secs` 는 fbot-state.py `_policy_path` 와 같은 순서로 policy.yml 을 읽고 부재 시 7200
    - 유예 구간 봇은 `lease_idle` 로 구분해 중립 문구("유휴 N분")로 표시
    - 검증: `test_fbot_bots.py` 회귀 케이스(red 먼저) + ego-browser 로 실 hub 카드 확인

## Issue530: hub 카드 헤더 배경이 진한 색으로 바뀌어 프로젝트명이 안 보임
* 목적: hub 활성 세션 카드 헤더가 파스텔 peacock 색 대신 진한 `hsl(…,60%,45%)` 로 칠해져 어두운 글자(#1a1a1a)의 프로젝트명이 묻힘. 이모지 자리엔 🆕/✅/➖ 가 뜸
* 구현 명세:
    - server.py 에 헤더 기반 단일 파서 `_projects_table_rows()` 신설, 두 로더가 이를 공유. 헤더 미인식 시 구 위치(emoji=6·color=7) fallback
    - `fpm-hub-trigger.sh`(cells[6], `..hub list` 이모지)는 정본이 글로벌 `~/.claude/hooks/` 라 번들만 고치면 역표류 → prj3 이슈로 이관(본 이슈 범위 밖)
    - 검증: `test_projects_columns_issue530.py` (tdd 컬럼 포함 표 → color·emoji 정확) + 기존 test_session_dup_issue282 회귀

## Issue529: 핀봇 조직도 — 접힘 상태를 새로고침 후에도 유지
* 목적: 다른 hub 페이지(Issue160 섹션 접기)는 접힘 상태가 localStorage 로 영속되는데 /fbot-map 만 메모리 state 라 새로고침·재진입 시 초기화된다(알림 스트림은 항상 open 으로 다시 그려짐)
* 구현 명세:
    - server.py fbot-map 스크립트에 localStorage 키 `fb-fold-state` 하나로 {open, drawer, stream, dormant} 저장·복원 (실패 시 기본값)
    - 작업 모드 prj details 도 state.open 을 따르도록 수정(하드코딩 open 제거)
    - 검증: node 로 스크립트 구문 검사 + 기존 test_fbot_map_issue402.py 통과

## Issue527: 핀봇 보드 — 조직도 블록 접기 + 프로젝트 전환 시 높이 자동 맞춤
* 목적: 프로젝트를 바꿀 때마다 조직도·작업 상세 경계를 손으로 다시 끌어야 한다(사용자: "prj 바꿀 때마다 조정하는 것은 불편함"). 조직도의 블록은 접을 수 있게 하고, 프로젝트를 바꾸면 **접힘과 높이가 자동으로** 맞춰지게 한다
* depends: Issue524, Issue525
* 구현 명세:
    - `plugins/fpm-core/services/hub/server.py` 보드 JS/CSS:
        - **블록 접기**: 위 블록마다 제목 줄에 ▾/▸ 토글. 접으면 제목 한 줄 + 요약(인원·`⏳/⏸/✗` 합계)만 남긴다. 본사 블록은 Issue525 한 줄 바를 이 공통 접기로 흡수(방식 하나로 통일)
        - **자동 규칙(선택이 바뀔 때마다 적용)**: 프로젝트 선택 → 본사 접힘 · 그 프로젝트 레인과 부서 펼침 / 본사·미선택 → 본사 펼침 · 레인은 현행. 사용자가 수동으로 접고 편 상태는 **그 선택이 유지되는 동안만** 유효하고, 선택이 바뀌면 자동 규칙으로 돌아간다
        - **높이 자동 맞춤**: 선택이 바뀌면 `#fb-org-pane` 높이를 **내용 높이에 맞춤**(하한 8rem, 상한 = 뷰포트에서 작업 상세 최소 10rem 확보). 경계 드래그(Issue524)로 정한 높이는 **현재 선택 동안만** 유지하고, 선택이 바뀌면 다시 자동 맞춤. 경계 더블클릭 = 자동 맞춤으로 즉시 복귀. localStorage `fb-orgh` 고정 복원은 제거(선택마다 자동이 기준)
        - 낮은 뷰포트에서 아래로 끌면 오히려 줄어드는 역방향 스냅(Issue524 관찰)도 이 상한 계산 통일로 함께 해소
    - 검증: `test_fbot_map_issue402.py` 통과(기존 `botNameLink` 1건 무관 실패 제외). **가동 hub 재기동 후** ego-browser 로 `host.local:9876/fbot-map?tab=board` 에서 ① 미선택 ② prj1 선택(본사 접힘·높이 자동) ③ prj42 선택(자리 많은 레인 — 높이 자동 확대) ④ 레인 부서 수동 접기 ⑤ 다시 prj1 선택(자동 복귀) 5장 캡처, 각 단계 `#fb-org-pane` 높이 수치 기록 → `_doc_work/report/issue527/`. 뷰포트 900px 에서 아래 드래그 시 줄어들지 않음 확인

## Issue526: mq 표 — 「집은 주체」 세션을 클릭해 그 세션 탭으로 바로 이동
* 목적: `/mq` 표의 `집은 주체 <commit>` 는 글자뿐이라, 어느 세션이 집었는지 보고도 그 세션을 손으로 찾아가 모니터링해야 한다. hub 세션 카드에는 이미 `/open-session`(VSCode 세션 탭 포커스)이 있으니 같은 경로로 연결한다
* 구현 명세:
    - `plugins/fpm-core/services/hub/server.py` `_mq_collect()`: `claimed_by` 가 `session:<sid>` 이면 hub `sessions` 레지스트리에서 sid → cwd 를 찾아 `_claimed_session = {sid, cwd}` 로 **덧붙인다**(원 필드 불변 · `_wip_age_sec` 와 같은 서버 부가 필드 규약). 레지스트리에 없으면 `{sid, cwd: null}`
    - `/mq` JS `msgCell()`: 세션 꼴이면 값을 버튼으로 — cwd 있으면 `POST /open-session {cwd,sid}` (원격 응답 `uri`·`folder_uri` 처리 동일), cwd 없거나 실패하면 sid 를 클립보드에 복사하고 사유 toast(Issue486 폴백 규약). 봇 꼴은 현행 글자
    - 검증: `test_mq_progress_issue506.py` 통과 + 가동 hub 재기동 후 `/mq-data` 에 `_claimed_session.cwd` 실림 확인

## Issue525: 핀봇 보드 — 본사 영역은 본사 선택 때만 펼치고, 프로젝트 선택 시 한 줄로 접기
* 목적: 1열에서 프로젝트를 고르면 조직도 위쪽의 **본사 영역**(나래·인사·팀장·발굴·HQ 임시 워커 카드 블록)이 그대로 남아 프로젝트 조직도를 아래로 밀어낸다. 프로젝트를 볼 때 본사 조직도는 매번 볼 필요가 없다
* depends: Issue523
* 구현 명세:
    - `plugins/fpm-core/services/hub/server.py` 보드 JS 조직도 렌더:
        - 펼침 조건: 선택 없음 · `scope:hq` · `dept:hq/…` · HQ 자리(`hq/…`) 선택 · HQ 봇 focus → **본사 블록 펼침**(현행)
        - 접힘 조건: `scope:N`(프로젝트) · `dept:N/…` · 프로젝트 자리/봇 선택 → 본사 블록을 **한 줄 요약 바**로 접는다: `★ 본사 ▸ · 나래 <상태점> · 총괄발 열린 배분 N · ⏳/⏸/✗ 합계` (카드 그리드 미렌더)
        - 한 줄 바 클릭 → 그 자리에서 펼침(선택은 유지, 수동 펼침은 다음 선택 변경 때 다시 자동 규칙으로 복귀). 펼친 상태에서 제목 클릭 → 접기
        - 선택이 프로젝트로 바뀌는 순간 조직도 스크롤을 맨 위로 — 접힌 결과 프로젝트 레인이 바로 보이게
    - 기존 해시·기간 토글·focus 동작 불변
    - 검증: `test_fbot_map_issue402.py` 통과(기존 `botNameLink` 1건 무관 실패 제외). **가동 hub 재기동 후** ego-browser 로 `host.local:9876/fbot-map?tab=board` 에서 ① 미선택(본사 펼침) ② 1열 prj1 클릭(본사 한 줄) ③ 한 줄 바 클릭(펼침) ④ 1열 본사 클릭(펼침) 4장 캡처 → `_doc_work/report/issue525/`. ⚠️ 격리 서버가 아니라 **가동 hub 에서** 실측(Issue524 교훈)

## Issue524: 핀봇 보드 — 조직도·작업 상세 경계를 끌어서 높이 조절
* 목적: Issue523 보드에서 위(업무 배당 조직도)와 아래(작업 상세) 경계를 **경계선 자체를 끌어** 조절하게 한다. 1열 ↔ 오른쪽 폭은 이미 끌어서 조절된다 — 같은 조작감으로 맞춘다
* depends: Issue523
* 구현 명세:
    - `plugins/fpm-core/services/hub/server.py`: `#fb-org-pane` 과 `#fb-work` 사이에 가로 분할 바(`.fb-hsplit`, `cursor:row-resize`, `touch-action:none`, hover 시 accent 선) 추가 — 기존 `.fb-split` 과 같은 pointer capture 패턴. 끌면 `#fb-org-pane` 높이 변경(하한 8rem, 상한 = 뷰포트에서 작업 상세 최소 10rem 확보), 놓을 때 localStorage `fb-orgh` 저장, **더블클릭 = 기본 높이 복귀**
    - 기존 `resize:vertical`·ResizeObserver 저장·pane 더블클릭 복귀는 제거(판정 한 방식으로 통일). 700px 이하 1열 적층에서는 분할 바 숨김
    - 검증: 셸 테스트에 `.fb-hsplit` 존재·`resize:vertical` 부재 확인 추가, `test_fbot_map_issue402.py` 통과(기존 `botNameLink` 1건 무관 실패 제외). ego-browser 로 경계 드래그 전후 캡처 + 새로고침 후 높이 유지 실측 → `_doc_work/report/issue524/`

## Issue522: hub 부팅 경쟁으로 Tailscale bind 유실 — 재시도 self-heal + 로그 정직화
* 목적: 부팅 시 hub 가 Tailscale 주소(<tailnet-ip>)에 bind 하지 못한 채 기동을 마쳐, tailnet URL(<tailnet-host>:9876)이 재부팅마다 불통이 된다. 매번 수동 restart 로 때우는 구조를 없앤다.
* 구현 명세:
    - **① bind 재시도 self-heal**: 실패한 주소를 데몬 스레드가 주기(예: 10초 간격 · 상한 30회) 재시도해 성공하면 소켓을 추가하고 serve 스레드를 띄운다. 기동 순서 의존을 없애 Tailscale 재연결·IP 변동에도 복구된다. 전부 실패 시 기존 `sys.exit(2)` 경로는 유지.
    - **② 개방 모드 배너 정직화**: `bind={BIND_HOSTS}` → 실제 성공 목록 `_bound` 로 교체. 실패분이 있으면 같은 줄에 `failed=[...]` 를 병기한다.
    - **③ `/healthz` 확장**: `bound_hosts`(실제 LISTEN 목록)·`bind_failed`(미성공 목록) 필드 추가. 외부 감시가 부분 실패를 잡을 수 있게 한다.
    - **검증**: 재부팅 후 수동 개입 없이 `lsof -nP -iTCP:9876 -sTCP:LISTEN` 가 3개를 보이고, tailnet URL 이 200 을 반환할 것.

## Issue523: (!) 핀봇 조직도 보드 탭 재설계 — 2·3열 병합(프로젝트별 업무배당 조직도 + 개체 작업 상세)
* 목적: 보드 탭(`/fbot-map?tab=board`) 3열 중 2열(개체 상세)·3열(작업 체인)을 하나로 합쳐, 위에는 **프로젝트별 업무 배당 조직도**(핵심), 아래에는 선택 개체의 **받은 일·하는 일·미룬 일**을 보여준다. 1열(나래 + 프로젝트 트리)은 유지
* 구현 명세:
    - 대상: `plugins/fpm-core/services/hub/server.py` — `_FBOT_BOARD_CSS`·`_FBOT_BOARD_JS`·`_fbot_board_html`·`_fbot_board_payload`. 설계 문서 `_doc_arch/hub_internal_tabs.md` 동반 갱신
    - 레이아웃: `.fb` 를 2열(1열 트리 유지 | 오른쪽 통합)로. 오른쪽 = 위 `#fb-org`(업무 배당 조직도, 세로 크기 조절) + 아래 `#fb-work`(작업 상세). 1열 폭 splitter 는 유지(3열용 `--fb-w3` 제거). 기존 테스트가 보는 id(`fb-tree`·`fb-detail`·`fb-chain`)는 새 구조에서 의미를 옮겨 유지하거나 테스트를 함께 갱신
    - **서버 판정 단일 지점**: `_fbot_board_payload` 가 봇마다 `work={received,doing,deferred:[{id,why}],directed}` 를 싣는다. received = 나에게 온 배분(open·blocked·logged·deferred 또는 recent) + 인박스 요청 open / doing = 받은 open 중 정체 아님 / deferred why = `gate`(blocked)·`stale`(deadlocks.stale 판정)·`deferred`(명시 상태)·`unaccepted`(요청 에스컬) / directed = 내가 src 인 배분(live 또는 recent). `_FBOT_FLOW_SIGN` 에 `deferred:"⏸"` 추가(문제 아님). 화면은 이 id 만 쓴다 — 카드·상세가 다른 판정을 쓰지 않는다
    - 조직도(위): 상단 총괄 바(나래 카드 + 나래발 배분 수) → 아래 **프로젝트 레인**(scope 별 열, flex 가로 스크롤). 레인 = 루트 자리(보고선이 레인 밖인 자리, 보통 팀장) 카드 → 부서 그룹별 자리 카드(보고선 트리) → **임시 워커**(자리 없이 이 레인 봇에게 배분받은 봇). 기본은 활성/배분 있는 레인만, 「전체」 토글이면 전 레인. 1열 `scope:N` 선택 = 그 레인만 넓게(부서를 가로 열로), `dept:` 선택 = 그 부서 강조
    - 노드 카드: 상태 점 · 아이콘 · 이름·role · `LIVE` 펄스(working) · current_task 1줄(없으면 last_task 흐리게) · **가지 합계 칩** `open·⏸·✓·✗`(자기+하위 받은 배분, 기간 토글 반영) · 공석은 점선 빈 카드. 카드 왼쪽 연결선 색 = 그 카드로 온 최신 배분 status(open 실선·blocked 주황·done 회색·reaped/cancelled 빨강 점선·외부컨설턴트 점선). 카드 클릭 = 그 봇 포커스 + 나머지 흐림(가지 강조)
    - 기간 토글: `열린만 | 최근 3일(기본) | 전체` — 칩·임시 워커·지시한 일 목록에 공통 적용
    - 작업 상세(아래): 기본 포커스 = 나래, `scope:N` 선택 시 그 레인 팀장, 카드 클릭 시 그 봇. 헤더 1줄(아이콘·이름·role·상태·자리·등급·마지막 활동·인박스/에스컬 배지) + `[상세 ▾]` 서랍(기존 seatCardInner — 요청 보내기·승인 액션·타임라인 **기능 보존**) + 3칸 **받은 일 / 하는 일 / 미룬 일**(미룬 일은 why 아이콘: ⏸ 선행대기 · ⌛ 정체 · 📥 미수락 · ⏸ 보류) + 매니저거나 directed 가 있으면 **지시한 일** 목록(기존 작업 체인 행 형식 `sign 배분자→대상 · 요지 · 경과`, 부모-자식 들여쓰기, problem 먼저). 배분 행 클릭 = 배분 상세 박스(기존 selJob 화면 + 배분 닫기) 
    - 해시 상태: 기존 `sel/mem/job/mode/all/problem/bot` 유지 + `focus=<bot_id>`·`period=`. `#bot=` 딥링크는 focus 로도 해석
    - 모바일(≤700px): 1열 → 조직도 → 상세 세로 적층
    - 검증: `test_fbot_map_issue402.py` 에 work 분류 단위 테스트(gate·stale·unaccepted·directed·recent 밖 제외) 추가, 전체 통과(기존 실패 1건 `botNameLink` 홈 렌더는 무관 — 그대로면 명시). ego-browser 로 `/fbot-map?tab=board` 전체·`#sel=scope:3`·카드 클릭 3장 캡처해 `_doc_work/report/` 에 첨부
    - 후속(별도): prj3 `fbot-lead.py defer --reason` 로 `deferred` 상태 신설 — `~/.claude/Issue.md` 등록 (나래 담당)

## Issue512: 공개 미러(prj8)가 «origin 이 없다» 고 선언한 `doc-base.yml` 을 들고 있다 — 선언이 forward 로 흘러간 사본이다 ✅
* 목적: [`sh/doc-base-check.sh --all`](sh/doc-base-check.sh) 가 **🚨 불일치 1건**을 낸다 — `7 ~/_git/__all/fpm  allow 인데 추적 0 (files 1) — 백업 없음`. 겉보기에는 prj8 의 `.gitignore` 문제지만, 원인은 **`_doc_base/` 추적 선언이 repo 마다 달라야 하는데 prj1 것이 미러로 복제되고 있다**는 구조다
* depends: Issue497
* 구현 명세:
    - ① **원인 제거(prj1 몫)**: [`data/publishable-policy.yml`](data/publishable-policy.yml) `exclude[]` 에 `.claude/doc-base.yml` 추가 — 미러가 자기 선언을 소유하게 한다. 주석에 «repo 고유 판단이라 동기 대상이 아님» 을 남길 것
    - ② **증상 제거(prj8 몫 · 승인 필요)**: prj8 `.claude/doc-base.yml` 을 `tracking: deny` + 근거 «공개 origin 을 가진 미러 — 유출 경로가 실재한다» 로 교정. 그러면 `.gitignore:10` 과 선언이 일치해 🚨 가 해소된다
    - ③ ①만으로는 🚨 가 안 꺼진다 — ② 까지 가야 끝난다. ① 을 먼저 넣지 않으면 ② 가 다음 forward 에 되돌아간다. **순서는 ① → ②** 다
    - ④ 판정 SSOT [`_doc_arch/gitignore-policy.md`](_doc_arch/gitignore-policy.md) 에 «미러 repo 의 기본값은 deny» 를 1줄 명문화할지 함께 결정
    - ⑤ 검증: `bash sh/doc-base-check.sh --all` 이 `🚨 불일치 0 건` 을 낼 것
    - ⚠️ 본 이슈는 **prj1 세션이 착수하지 않았다** — ② 가 타 repo 파일 수정이라 승인 대상이고([input-interpretation-rules](.claude/rules/input-interpretation-rules.md)), ① 만 넣으면 ③ 때문에 미완으로 남는다

## Issue520: `fpm-projects-sync` 가 JSONC 를 못 읽어 prj0 색 동기화가 조용히 끊겨 있다
* 목적: VSCode `settings.json` 은 **주석을 공식 허용**하는 JSONC 다. 그런데 `[2/4]` 단계가 표준 `json` 파서를 써서 주석이 있으면 파싱에 실패하고 그 프로젝트를 **skip 한다**. 경고 1줄만 흘러가므로 색이 안 맞는다는 사실이 드러나지 않는다. 실제로 prj0(홈)은 `peacock.color` 가 `#dddddd` 로 남아 SSOT(`Projects.md`) 와 **오래 어긋나 있었고**, [Issue510](Issue.md) 전수 재배정에서도 혼자 빠졌다
* depends: Issue510
* 구현 명세:
    - ① `sh/fpm-projects-sync` 의 `settings.json` 로더를 JSONC 대응으로 바꾼다. 의존성을 늘리지 않으려면 `//`·`/* */` 를 문자열 리터럴 밖에서만 제거하는 전처리를 쓴다 — **문자열 안의 `//`(ex: URL `http://…`)를 지우면 안 된다**
    - ② 쓰기 경로도 함께 본다: 주석을 보존하며 키만 갈아끼울지, 주석이 사라짐을 고지하고 재작성할지 결정한다. 보존이 어려우면 **파싱 실패 skip 대신 명시적 경고 + 사유**를 남기는 것이 최소선이다
    - ③ 파싱 실패를 `[2/4]` 요약의 `(파싱skip N)` 으로만 세지 말고, **어느 프로젝트가 왜 skip 됐는지 끝에 다시 모아 출력**한다. 지금은 중간 로그라 뒤 단계 출력에 묻힌다
    - ④ 검증: prj0 에 주석을 남긴 채 sync → `~/.vscode/settings.json` 의 `peacock.color` 가 `#e8ccc4` 가 되는지 확인한다

## Issue519: `fpm-bundle-sync.sh` 가 타 세션의 미커밋 작업을 되돌릴 수 없게 덮는다 ✅
* 목적: 무결성 hook 이 실행을 지시하는 스크립트인데, 그 실행이 라이브(prj3)를 원본으로 복사하면서 목적지의 **in-flight 작업을 rsync 로 덮었다**. 커밋 전이라 git 에도 없어 복구 경로가 0 이었다

## Issue518: hub 격리 하네스(`FPM_TMP_ROOT`)가 구동 중인 운영 hub 의 상태 파일을 끌어간다 ✅
* 목적: `_migrate_legacy_state()`([Issue446](Issue.md))의 판정이 «`STATE_DIR` 이 구 경로와 다른가» 뿐이라, 테스트·격리용 `FPM_TMP_ROOT` 를 쓰면 그 조건이 곧바로 성립해 **운영 hub 의 `pid`·`tokens.json`·`server.log` 를 샌드박스로 move** 했다

## Issue521: /mq — 결과가 이미 있는 항목에 [진행] 버튼이 뜬다 ✅
* 목적: 사용자 발의 — *"결과가 나온 것은 완료만 누르면 되는 것 같은데, 진행이 활성화 될 필요가 있나?"* 끝난 일에 [진행] 을 누르면 항목이 다시 `in_progress` 로 서고 **세션 넛지에 없는 일이 올라간다**. 지시가 실제로 나가므로 표시 문제가 아니라 동작 결함이다
* depends: Issue513
* 구현 명세:
    - ① [server.py](plugins/fpm-core/services/hub/server.py) `render()` 에 `hasResult` 판정을 세우고 `${wip?'':…}` 를 `${(wip||hasResult)?'':…}` 로 바꾼다. 남는 버튼은 `완료`·`연기`·`취소`
    - ② 빈 값 판정은 `progLine` 과 **같은 식**(`null` 또는 공백만 = 없음)이다 — 화면에 「결과」 줄이 뜨는 것과 [진행] 이 사라지는 것이 같은 조건이어야 사용자가 둘을 연결해 읽는다
    - ③ 숨김을 택하고 «비활성 + 툴팁» 은 쓰지 않는다 — 누를 수 없는 버튼을 남기면 어차피 같은 질문을 다시 낳는다
    - ④ `done_unacked` 는 이미 별도 분기(`확인`·`버림`)라 영향 없다

## Issue513: /mq 접속 간헐 정지 — hub listen backlog 가 기본 5였다 ✅
* 목적: 사용자 보고 *"`http://<tailnet-host>:9876/mq` 브라우저 죽는 문제 있음"* 의 실체는 **렌더러 크래시가 아니라 TCP 접속 실패**다. hub 서버가 `listen(5)` 로 떠 있어 정상 사용에서 backlog 가 포화하고, 브라우저는 SYN 재전송 간격(1.06s·3.00s)만큼 멈춘 듯 보인다. 접속 자체를 되살리는 것이 목적이다
* 구현 명세:
    - ① [server.py](plugins/fpm-core/services/hub/server.py) 에 `HubHTTPServer(ThreadingHTTPServer)` 서브클래스를 신설하고 `request_queue_size = 128` · `daemon_threads = True` 를 **클래스 속성**으로 둔다
    - ② ⚠️ **인스턴스 생성 후 대입은 늦다** — `server_activate()` 가 생성자 안에서 이미 `listen()` 을 끝낸다. 생성 전에 결정되는 클래스 속성이어야 한다
    - ③ 값은 **128** — macOS `kern.ipc.somaxconn` 이 128 이라 더 올려도 커널이 깎는다(실측 `sysctl kern.ipc.somaxconn: 128`)
    - ④ bind 지점(`for _h in BIND_HOSTS`)의 `ThreadingHTTPServer(...)` 호출을 `HubHTTPServer(...)` 로 바꾸고, 중복이 된 `_s.daemon_threads = True` 줄은 제거한다
    - ⑤ 검증: 재기동 후 `SYN_RCVD` 가 5에 고정되지 않을 것 · `curl -m 3` 10회 전건 200 · `time_connect` < 10ms · 병렬 12 요청 전건 성공
    - ⑥ `services/hub` 는 `plugins/fpm-core/services/hub` 로의 **심볼릭 링크**라 사본이 2벌이 아니다(md5 일치 확인). 공개 미러(prj8 fpm) 전파는 [fpm-sync](.claude/skills/fpm-sync/SKILL.md) 의 별도 결정

## Issue510: peacock 팔레트 전수 재배정 — 52색을 거리 50 공간으로 다시 깐다 ✅
* 목적: [Issue494](Issue.md) 가 색 공간 설계를 확정했다(채도 축 · 명도 가드 유지 · 거리 40 규칙). 남은 것은 **기존 52색을 그 공간으로 옮기는 실행**이다. 현재 최근접 거리 중앙값 25.6 · 최소 11.3 이고, 빈 팔레트로 다시 깔면 **거리 50 이상 76색**이 가능하므로 목표(중앙값 40·최소 30)를 크게 넘는다
* depends: Issue494
* 구현 명세:
    - ① 후보 팔레트 산출: `sh/fpm-peacock-audit.py --headroom 50 --fresh` 로 거리 50 이상 76색을 얻고, 도메인 톤(맥=난색·웹=청록·일반=중성)으로 배분한다. **톤은 색상 힌트일 뿐 저채도를 뜻하지 않는다**(Issue494)
    - ② 이동 최소화: 기존 색과 가까운 후보를 우선 배정해 «색이 확 바뀌는» 프로젝트 수를 줄인다. 특히 일상 작업 프로젝트(prj1·2·3·5·6·9~16)는 가능한 유지
    - ③ 적용 순서: `Projects.md` color 열 갱신 → `python3 sh/fpm-projects-sync` (`[2/4]` 가 `.vscode`·`.zed` 재생성) → `[3/4]` iterm-bg alias 재생성. [/peacock-sync](.claude/commands/peacock-sync.md) 는 `peacock.color` 키만 바꾸므로 단독으로는 부족하다
    - ④ ⚠️ **역방향 reconcile 주의**: `[0/4]` 는 `settings.json` mtime > `Projects.md` mtime 이면 에디터 색을 SSOT 로 되받는다. `Projects.md` 를 **마지막에 쓴 직후** 실행하거나 `--no-reverse` 를 붙인다. 이 때문에 «Projects.md 만 먼저 고쳐 두는» 부분 적용은 금지다 — 조용히 되돌아간다
    - ⑤ 커밋 경계: prj1 은 `Projects.md`(미추적)·도구만 커밋하고, 각 repo 의 `.vscode`·`.zed` 커밋은 **그 repo 담당**에게 넘긴다
    - ⑥ 검증: `sh/fpm-peacock-audit.py` 로 중앙값 40 이상·최소 30 이상·거리 30 미만 0쌍을 확인한다

## Issue494: peacock 팔레트 색 공간 확장 — 명도·채도 축 확대 ✅
* 목적: 등록 51색이 **밝은 파스텔 한 대역에 몰려 포화**했다. prj6 전수 실측에서 최근접 거리 중앙값이 18.0 에 불과했고, 최소 4.0(prj10 ↔ prj16)은 16진수 한 자리 차이로 사실상 같은 색이다. 신규 배정 로직을 아무리 고쳐도 고를 색이 남아 있지 않으므로, 팔레트가 쓰는 **색 공간 자체를 명도·채도 축으로 넓힌다**
* 구현 명세:
    - **① 명도 축을 내리려면 전경색을 함께 바꿔야 한다** — peacock 과 [fpm-projects-sync](sh/fpm-projects-sync) 는 `activityBar.foreground`·`statusBar.foreground`·`titleBar.activeForeground` 를 배경과 **함께** 생성한다. 어두운 배경에는 밝은 전경이 필요하다. `readable_fg()` 가 이미 `lum > 0.5 → #15202b / 그 외 #e8e8e8` 분기를 갖고 있으므로 배선은 있으나, **임계 0.5 부근(중간 명도)에서 대비가 무너지는 구간**을 실측해 임계를 재보정할 것. 가드(`L>=80`·`lum>=78`)도 이 전제 위에서 완화 폭을 정한다
    - **② 채도 축** — 가드는 이미 채도를 기준으로 삼지 않는다(`#fee4e9` L 94.5% · S 92.9% 선례). 명도만 유지한 채 채도를 넓히는 것만으로도 색상환 전역을 쓸 수 있으므로, 명도 완화보다 **부작용이 작은 쪽을 먼저** 검증할 것
    - **③ 목표치**: 최근접 거리 **중앙값 40 이상** · **최소 거리 30 이상** · 신규 배정 여유분 20색 이상. Issue494_1 조치 후 현재 중앙값은 24.3 이므로 목표까지 약 1.6배가 남았다
    - **④ 파생 액센트 키 재생성 범위** — `activityBar.activeBackground`·`statusBarItem.hoverBackground`·`statusBar.debuggingBackground` 는 peacock 이 **구색에서 파생**해 만든 값이고 `fpm-projects-sync` 의 merge 집합 밖이라, 색을 바꿔도 구색 파생값이 남는다(ex: prj101 라임 배경에 `statusBarItem.hoverBackground: #bfbfce` 청회색). 전수 재배정 전에 이 키들을 도구가 소유할지 결정할 것
    - **⑤ 51개 일괄 적용 절차**: `Projects.md` color 열 갱신 → `python3 sh/fpm-projects-sync` (`[2/4]` 가 `.vscode/settings.json` + `.zed/settings.json` 을 `data/editor.yml` 의 `color_sync` 에 따라 재생성) → `[3/4]` iterm-bg alias 재생성. [/peacock-sync](.claude/commands/peacock-sync.md) `pm` 은 `peacock.color` 키만 바꾸므로 **단독으로는 부족**하다
    - ⚠️ **역방향 reconcile 주의** — `fpm-projects-sync` 의 `[0/4]` 는 `settings.json` mtime > `Projects.md` mtime 이면 에디터 색을 SSOT 로 되받는다. 전수 재배정은 `Projects.md` 를 **마지막에 쓴 직후** 실행하거나 `--no-reverse` 를 붙일 것
    - **⑥ 타 repo 커밋 경계**: `.vscode`·`.zed` 산출물은 각 프로젝트 repo 소유다. prj1 세션은 **편집까지만** 하고 커밋은 각 repo 담당에게 넘긴다([input-interpretation-rules.md](.claude/rules/input-interpretation-rules.md))
    - 검증 스크립트(재사용): `Projects.md` 표를 파싱해 전체 쌍 거리를 정렬 출력. 원본은 위임 지시서에 있었고 본 이슈 조치에서 그대로 사용해 prj6 수치를 재현했다

## Issue499: `pm-new` 스캐폴드가 양식만 놓고 내용을 안 채운다 — 템플릿 오염 12개 프로젝트 ✅
* 목적: [data/template/Issue.md](data/template/Issue.md) 가 **prj1 자신의 frontmatter**(오타 `Mananger` 포함)와 미치환 플레이스홀더를 담고 있어, `pm-new` 로 태어나는 모든 프로젝트가 그대로 물려받는다. [Harness.md](data/template/Harness.md) 는 *"동일 타입의 기존 프로젝트에서 자동 수집하여 초기 채움"* 이라 적혀 있으나 **그 수집을 하는 코드가 없다** — 집행자가 기억해서 손으로 해야 한다
* 구현 명세:
    - ① 템플릿 frontmatter 를 **플레이스홀더로** 바꿀 것 — `title: {프로젝트명} Issue`. 지금은 prj1 것이 박혀 있어 **치환 대상인지조차 보이지 않는다**. 오타 `Mananger` → `Manager` 는 prj1 자신의 `Issue.md` 도 함께 고친다
    - ② **가짜 완료 이슈를 제거**하거나 `<!-- 예시 -->` 주석 블록으로 감쌀 것. 예시를 남기려면 `✅` 를 떼고 `🌱 이슈후보` 로 옮긴다
    - ③ `pm-new` 가 **치환을 실제로 수행**하게 할 것. 현재 `CLAUDE.md`·`PROMPTS.md`·`vscode.json`·`zed.json` 만 치환하고 `Issue.md`·`Harness.md`·`noteForHuman.md` 는 `cp` 다. 치환 대상 목록을 스킬에 명시한다
    - ④ `Harness.md` global layer **자동 채움을 구현하거나 문구를 «수동» 으로 고칠 것.** 문서가 자동이라고 말하는데 구현이 없어 집행자마다 결과가 다르다 — **Issue496 과 같은 형태**(문서가 약속한 것을 코드가 안 한다)다

## Issue497: 로컬전용 docs 표준 블록이 origin 없는 프로젝트를 "버전이력·백업 0" 으로 만든다 ✅
* 목적: [gitignore-policy.md](_doc_arch/gitignore-policy.md) 의 6항목 표준 블록은 **신규·미추적 프로젝트에 자동 적용**된다. origin 이 없는 프로젝트에 적용되면 `Issue.md`·`CLAUDE.md`·`_doc_arch/` 가 **버전 이력도 원격 백업도 없는** 상태가 된다. 같은 문서가 `_doc_base/` 에 대해 **이미 이 실패를 기록**하고 있으면서(Issue477) docs 블록에는 그 교훈이 적용돼 있지 않다
* 구현 명세:
    - ① **판정축을 다시 origin 으로 돌리지 말 것** — 정책의 "왜 origin 기반을 폐기했나" 절이 30개 전수 실측으로 그 불변식이 이미 깨져 있었음을 보였다. 같은 실패를 docs 블록에서 반복하면 안 된다
    - ② 유력안은 **`_doc_base/` 와 같은 명시 선언**이다. `pm-new` 가 `.claude/doc-base.yml` 을 만들듯 docs 추적 여부도 선언 파일로 받는다
    - ③ **안전측이 어느 쪽인지 먼저 정할 것.** `_doc_base` 는 *유출 방지*가 안전측이라 미선언을 `deny` 로 뒀다. docs 는 유출 위험이 낮고 **유실 위험이 높아** 안전측이 반대일 수 있다 — 이 판정이 ②의 기본값을 정한다
    - ④ ~~전수 조사할 것~~ → **완료(아래 절).** 결과가 ③의 답을 사실상 정해 준다
    - ⑤ 결론이 나면 prj7 의 현재 상태(`<commit>`)를 표준으로 승격할지 되돌릴지 확정한다. 그때까지 prj7 은 **의도된 예외**로 둔다

## Issue508: graphify brief 리포트가 3개월 낡아 「최우선 진입점」이 옛 요약을 가리킨다 ✅
* 목적: [graphify-rules](.claude/rules/graphify-rules.md) 는 `GRAPH_REPORT.brief.md` 를 *"존재 시 최우선"* 진입점으로 규정하고 매 턴 hook 이 그 파일을 가리킨다. 그런데 prj1 의 brief 는 **2026-06-12 · 2,948 노드**이고 실제 `graph.json` 은 **2026-09-01 · 9,155 노드**다. **3.1배 차이로 3개월 낡은 요약이 최우선으로 읽힌다** — 조회가 틀리는 것이 아니라 *조용히 옛날 사실을 답한다*
* depends: Issue495
* 구현 명세:
    - ① brief 갱신을 **빌드에 종속**시킬 것 — 빌드·`graphify update` 성공 시 prune 을 자동 호출하거나, 최소한 brief 가 `graph.json` 보다 오래되면 hook 이 경고한다. 어느 쪽이든 수동 기억에 의존하는 구조를 없앤다
    - ② **신선도 판정 기준을 수치로 명문화**할 것 — `graph.json` mtime 대비 brief mtime 이 N일 이상 뒤지면 stale. 임계 N 은 실측으로 정한다(mtime 뿐 아니라 노드 수 배율도 후보다 — 3.1배·6.4배는 날짜보다 먼저 눈에 띈다)
    - ③ stale 일 때의 **동작**을 정할 것: 경고만 띄우고 그대로 쓸지, brief 를 건너뛰고 `GRAPH_REPORT.md` 로 폴백할지. **낡은 요약을 최우선으로 읽는 것이 무경고보다 위험**하므로 폴백 쪽이 기본값 후보다
    - ④ **조치 위치는 prj3 일 가능성이 높다** — `graphify-rules` 와 매 턴 hook 은 글로벌 SCAR 다. prj1 에서 기준을 확정한 뒤 [글로벌 SCAR 변경 절차](.claude/rules/global-scar-change-rules.md) 로 prj3 에 이슈를 등록한다. **prj1 세션이 직접 고치지 않는다**

## Issue509: `/mq` 액션 후 화면이 「처리 중…」에서 멈춘다 — 낙관적 상태가 영구히 남는다 ✅
* 목적: `/mq` 에서 버튼을 누르면 결과가 화면에 반영되지 않고 「처리 중…」 칩만 남는다. 수동 새로고침해야 보인다. 데이터는 이미 바뀌어 있으므로 **그리는 쪽의 결함**이다. 위임 요청서: `~/.claude/_doc_work/report/mq-autorefresh-gap_delegation.md` (fbot-chief-narae)
* 구현 명세:
    - ① `ACKED` 를 `{action, at, status, due_ts}` 레코드로 바꾼다 — 언제 눌렀고 누를 때 상태가 무엇이었는지 기억해야 「반영됐는가」를 판정할 수 있다
    - ② `load()` 끝에 조정 단계를 둔다: 목록에서 사라졌거나 `status`·`due_ts` 가 눌렀을 때와 달라졌으면 반영된 것 → `ACKED` 에서 제거. 판정을 **한 지점**에 두어 호출 경로마다 갈라지지 않게 한다
    - ③ TTL(25초) 만료 시에도 제거하고 버튼을 되살린다 — 반영이 늦어도 화면이 영구히 잠기지 않아야 한다. 만료는 토스트로 알린다
    - ④ `consumed:false` 분기에서도 즉시 `load()` 하고 후속 재조회를 2·5·10·20초에 예약한다. tick 이 소비하는 즉시 화면이 따라간다
    - ⑤ 검증: `python3 -m py_compile` · hub 재시작 후 `/mq` 에서 실제 클릭 → 버튼 복구·목록 갱신 육안 확인

## Issue506: `/mq` 표에 진행 3종 표시 — prj3#Issue643 의 화면 절반 ✅
* 목적: prj3#Issue643 이 큐 스키마에 `claimed_by`·`progress`·`result` 를 세우면, **그것을 사람이 보는 자리**가 이쪽이다. 지금 `/mq` 표는 `in_progress` 와 경과 배지까지만 보여줘서 *"누가 집었나·뭘 하나·결과가 뭔가"* 에 답하지 못한다(2026-09-19 사용자 지적)
* depends: prj3#Issue643
* 구현 명세:
    - `_mq_collect()` 가 `claimed_by`·`progress`·`result` 를 그대로 실어 보낸다(서버가 해석하지 않는다 — 정본은 prj3 큐 파일)
    - 표 **내용 열**에 진행 정보를 덧붙인다. 열을 새로 늘리지 않는다 — Issue501 에서 내용 열에 폭을 몰아준 결정이 유효하고, 열이 늘면 모바일에서 다시 갈린다
    - `claimed_by` 는 짧게(세션 8자 또는 봇 title), `progress` 는 1줄, `result` 는 경로면 링크로 세운다
    - 필드가 없는 기존 항목은 **아무것도 렌더하지 않는다**(빈 칸·`-` 표시 금지 — 없는 것과 비어 있는 것은 다르다)
    - 검증: 3종이 채워진 항목과 비어 있는 항목을 나란히 두고 `/mq` 를 열어 전자만 표시되는지 확인

## Issue505: hub 봇 카드에서 조직도(`/fbot-map`)로 넘어갈 길이 없다 — 클릭이 아코디언에 점유됨 ✅
* 목적: hub 「🤖 핀봇 현황」의 **봇 카드에서 그 봇의 조직도로 갈 수 없다.** 카드 본체 클릭은 Issue401 펼침 상세(아코디언)가 점유해 사용자 눈에는 *"내용만 조금 확대"* 로만 보이고, 조직도 링크는 그룹 헤더 우측 끝의 작은 👥 뿐이라 **개체 단위 진입점이 0개**다. 사용자 지시(2026-09-19): *"각 핀봇에서 해당 페이지로 넘어가야 함 — 아이콘을 만들 것이 아님"*
* 구현 명세:
    - `botCard()` 의 봇 **제목 자체**를 앵커로 만든다 — `/fbot-map?tab=board#bot=<bot_id>`, `target=_blank`. 아이콘 부착이 아니라 이름이 진입점이다(사용자 지시)
    - board `readHash()` 에 `bot` 키를 추가하고, 데이터 도착 후 `bot_id` 로 `seat.addr` 을 찾아 `state.sel` 로 승격한 뒤 `writeHash()` 로 `sel=` 로 정규화한다. 자리 없는 봇(미배치)은 승격 실패해도 보드가 그대로 뜬다(fail-soft)
    - `bindBotToggle()` 의 click·keydown 에 `e.target.closest('a')` 가드 — 링크 클릭이 아코디언을 **동시에** 토글하지 않게. Issue401 25항(카드 클릭=펼침)은 그대로 보존한다
    - CSS `.bot-name-link`(색 상속·hover 밑줄) + i18n `bots.openBoardTitle` ko/en
    - 검증: 브라우저로 hub 를 열어 카드 제목 클릭 → 새 탭 board 에서 **그 봇의 자리가 선택된 상태**로 열리는지 실측

## Issue504: `/mq` 표에 in_progress 경과 배지 — prj3#Issue638_1 의 화면 절반 ✅
* 목적: prj3#Issue638_1 이 tick 쪽 감시(경과 집계 + Discord 백오프 통지)를 세웠으나, **화면 배지는 표 렌더를 소유한 이쪽 몫으로 남았다.** `/mq` 목록은 `in_progress` 를 재발견할 **유일한 경로**다 — 재질의 대상에서 빠져 있고 stale 자동 정리 대상도 아니라, 화면에서 눈에 띄지 않으면 사람이 알 방법이 없다
* depends: prj3#Issue638_1
* 구현 명세:
    - `_mq_collect()` 가 항목에 경과(`started_at` 없으면 큐 파일 mtime 기준)를 실어 내보내고, `/mq` 표의 상태 열 `in_progress` 배지 옆에 **경과 시간**을 표시한다
    - 임계 초과분은 시각적으로 구분한다(색·아이콘). 임계값은 prj3 policy `wip_stale_hours` 를 **읽어서** 쓴다 — 숫자를 이쪽에 복제하면 두 곳이 갈라진다
    - 기준 시각이 없는 항목도 감시 면제를 만들지 않는다(mtime 폴백 — 선행 구현과 같은 규칙)
    - 검증: in_progress 항목을 임계 미만·초과 2건 만들고 `/mq` 를 열어 배지·강조가 갈리는지 확인

## Issue503: 이슈맵 페이지에서 바로 재생성 — 🔄 업데이트 버튼 ✅
* 목적: `/issue-map` 으로 연 관계도가 낡았을 때(`Issue.md` 가 더 최신) 화면은 "흐림 표식" 으로 고지만 하고, 재생성은 **터미널로 가서 `/fpm-issue-map` 을 치는 것** 뿐이었다. 폰·원격 브라우저에서는 그 경로가 아예 없다. 보고 있는 그 자리에서 갱신할 수 있어야 한다
* 구현 명세:
    - **버튼은 serve 시점 주입**(`COPY_LINK_SHIM` 동형). 생성기가 버튼을 심으면 ① 이미 만들어진 맵에는 버튼이 없어 *재생성해야 재생성 버튼이 생기는* 닭-달걀이 되고 ② `file://` 로 연 맵에 눌러도 안 되는 거짓 버튼이 남는다
    - 엔드포인트 `POST /issue-map/rebuild {cwd}` — 게이트는 GET `/issue-map` 과 **같은 함수**를 공유(등록 프로젝트 at-or-under 화이트리스트). 경로는 서버가 재계산하므로 traversal 입력면 없음
    - 생성기 경로 해석은 [fpm-issue-map.md](plugins/fpm-core/commands/fpm-issue-map.md) 의 2단계 resolver(플러그인 번들 → 글로벌 SCAR) 미러. 하드코딩 금지
    - 재생성 후 `_issue_map_cache` 무효화 — 안 하면 TTL 동안 stale 표식이 그대로 남는다

## Issue502: hub 가 tick 을 SIGKILL 해 고아 락을 남긴다 — /mq 클릭이 30분간 무효 ✅
* 목적: `/mq` 에서 **진행을 눌러도 아무 일도 일어나지 않고 버튼이 계속 살아 있는** 현상의 원인. UI 버그가 아니라 **큐 전체가 멈춰 있었다**
* 구현 명세:
    - **B (본 이슈)**: `run()` 을 `Popen` + `communicate(timeout)` 로 바꿔 **SIGTERM 을 먼저** 준다. 그래도 안 죽으면 SIGKILL. kill 이 끝나면 `_mq_reap_orphan_lock()` 으로 **자기가 죽인 tick 의 잔여 락만** 걷는다 — 살아 있는 tick 이 하나라도 있으면 손대지 않고, `rm -rf` 가 아니라 `os.rmdir`(빈 디렉토리 전용)로 지운다
    - **C (본 이슈)**: `consumed:false` 일 때 응답에 락 상태(`held`·`age_sec`·`alive`)를 실어 UI 가 **사실대로** 안내한다. 종전 문구 *"다음 tick(≤5분)이 반영"* 은 락이 고아면 30분간 거짓말이었다
    - **A (prj3 소관 · 별도 등록)**: 락에 PID 를 기록하고 보유 프로세스 liveness 로 stale 을 즉시 판정. 30분 대기 자체를 없앤다. `~/.claude/mcp/aoa-mq/aoa-mq-tick.sh` — 글로벌 SCAR 라 `~/.claude/Issue.md` 에 등록
    - 대상: `plugins/fpm-core/services/hub/server.py`

## Issue501: /mq 내용 열 확장 — 출처를 `@`·` (` 에서 접어 잉여 폭을 본문에 넘긴다 ✅
* 목적: 열을 6개까지 줄였는데도 **내용 열이 화면의 3분의 1 남짓**이다. 출처 `claude@sreMsa (fbot-lead-sremsa)` 가 `nowrap` 단일 줄이라 열 하나가 30자 폭을 점유하고, `td.msg` 에 걸린 `max-width` 가 남는 폭을 본문이 받지 못하게 막는다
* depends: Issue500
* 구현 명세:
    - 출처: `srcCell()` 로 `@` 뒤·` (` 앞에 `<br>` 삽입. 열 폭이 최장 조각 하나로 수렴한다. `nowrap` 은 유지 — 조각 **안쪽**이 임의로 깨지면 오히려 읽기 어렵다
    - 내용: `max-width` 제거 후 `width:100%` — auto table layout 에서 잉여 폭이 본문 열로 몰린다
    - 필터·검색은 원본 `x.source` 를 그대로 쓰므로 영향 없음(`<br>` 은 표시 계층에만 들어간다)
    - 대상: `plugins/fpm-core/services/hub/server.py` `_MQ_PAGE_HTML`

## Issue500: /mq 큐 표 2차 접기 — 출처·질의 통합 · 마감 2줄 · ID 강조 반전 ✅
* 목적: [Issue498](Issue.md) 로 열 8 → 7 까지 줄였으나 **질의 열이 전 항목 `0` 인 채 폭을 통째로 먹고**, 마감은 `2026-09-19 09:00:00` 한 줄이라 여전히 가로를 밀어낸다
* depends: Issue498
* 구현 명세:
    - 출처·질의: 열 1개로 병합, **출처 위 · 질의 아래**(`질의 N` 라벨 동반 — 헤더가 스크롤 밖으로 나가도 숫자의 뜻이 남는다). 헤더 `출처 / 질의`, 두 키 모두 정렬 가능
    - 마감: `2026-09-19`(진함·위) / `09:00:00`(흐림·아래). 값이 없으면 `–` 한 줄
    - ID: 강조 반전 — `114718-001`(흐림·위) / `<commit>`(진함·아래)
    - `colspan="7"` → `6` 동반 수정
    - 대상: `plugins/fpm-core/services/hub/server.py` `_MQ_PAGE_HTML`

## Issue498: /mq 큐 표 가독성 — ID 2줄 분할 + 상태·유형 열 통합 ✅
* 목적: `/mq` 큐 표가 가로로 퍼져 **내용 열이 sticky 처리 열에 밀려 잘린다**. 정작 읽어야 할 것은 내용인데 고정폭 메타(ID·상태·유형)가 가로를 먹는다
* 구현 명세:
    - ID: `YYYYMMDD` / `HHMMSS-SEQ` 2줄. 날짜는 식별 보조라 흐리게, 시각-순번을 본문 톤으로
    - 상태·유형: 열 1개로 병합, 상태 배지 위 · 유형 아래 2줄. 헤더는 `상태 / 유형` 이고 **두 키 모두 정렬 가능**해야 한다(`/ 유형` 을 별도 `data-k` 로 두고 버블링 차단)
    - `colspan="8"` → `7` 동반 수정 (빈 목록 행)
    - 대상: `plugins/fpm-core/services/hub/server.py` `_MQ_PAGE_HTML`

## Issue491: 상비 핀봇에 「해고 검토 요청」 버튼이 뜬다 — 조직 골격은 해고 대상이 아니다 ✅
* 목적: 사용자 지시(2026-09-10) — *"필수 핀봇은 「해고 검토 요청」 버튼 있으면 아니됨."* 상비봇은 **조직 골격**이라 해고하면 그 자리의 기능이 통째로 사라진다. 눌릴 수 있는 자리에 둔 것 자체가 결함이다
* 구현 명세:
    - `_fbot_board_payload`(또는 bots 조립부)에서 각 봇에 **`core: true|false`** 를 싣는다. 판정은 prj3 `is_core_bot` 과 **동일 규칙**으로 — 규칙을 새로 쓰지 말고 옮긴다(단일 지점 유지)
    - 카드 렌더에서 `core` 면 「해고 검토 요청」을 **만들지 않는다**. 숨김(CSS)이 아니라 미생성 — DOM 에 있으면 개발자도구로 눌린다
    - 대신 **왜 없는지 1줄**을 남긴다(ex: *"상비 — 조직 골격이라 해고 대상이 아니다"*). 버튼만 사라지면 사용자는 렌더 실패로 읽는다
    - 「재기동 요청(wake)」은 **그대로 둔다** — 상비봇도 깨울 수는 있어야 한다
    - 서버측 `/fbot-mq-confirm` 에도 **같은 판정으로 방어**한다. 버튼을 지우는 것은 UI 이고, 엔드포인트는 직접 호출될 수 있다 — `action=terminate` + 상비면 거부
    - 검증: ego-browser 로 상비 4종 카드에 버튼 부재·비상비 카드에 버튼 존재 · `curl -X POST /fbot-mq-confirm` 로 상비 terminate 가 거부되는지

## Issue489: hub 테스트가 2세대에서 사라진 mermaid API 를 계속 부른다 ✅
* 목적: 보드 2세대(Cytoscape) 전환 때 서버가 mermaid 문자열을 만들지 않게 되었는데 `test_fbot_map_issue402.py` 가 그 함수를 계속 호출해 **회귀가 통째로 죽어 있었다**. 이름 개편(prj3#Issue610) 회귀를 돌리다 드러났다
* 구현 명세:
    - 검증 대상을 **렌더 문자열에서 데이터 층으로** 내렸다 — 표기 요구(prj·아이콘·개체색·고아 구분·세션 배지)는 그대로 유효하고 이제 노드 필드가 그 계약을 진다
    - 흐름 그래프는 `_fbot_deadlocks` 판정 + `dispatch[].sign`·`recent` 로, 페이지는 `id="fb-cy-org"`·`var DATA={org:` 로 확인
    - 결과 **216 케이스 전건 통과** · hub 25파일 전건 통과

## Issue486: hub 중요 칩 — 응답 대기 알림에서 대상 세션으로 못 가고, 실패해도 세션 ID 조차 못 얻음 ✅
* 목적: 헤더 중요 칩 `fWarrangeCli — 응답 27분 대기, 요청 필요` 를 눌러도 그 세션에 도달할 수 없다. 칩이 가진 정보가 활동 피드 항목 id 뿐이라 **피드로 스크롤**만 하고(피드가 접혀 있으면 아무 일도 안 일어난다), 세션 이동 경로가 아예 없다. 사용자 지시 — 이동이 불가하면 **세션 ID 라도 클립보드에 복사**할 것
* 구현 명세:
    - 서버 `_compute_important_events` R2: 같은 cwd 의 live 세션 후보 중 **피드 항목 ts 와 갱신 시각이 가장 가까운** 세션을 골라 `sid`/`cwd`/`session_url`/`origin` 을 이벤트에 부착
    - 클라 `renderImportant`: `sid` 보유 칩은 `impGotoSession(this)` 로 배선(데이터는 `data-*` 로 전달)
    - `impGotoSession`: origin=vscode/zed → `openSessionRaw` 로 탭 포커스, 실패 시 sid 복사 / origin=terminal → 즉시 sid 복사 + 사유 토스트 / sid 없음 → 기존 피드 포커스 폴백
    - 복사는 insecure context(host.local) 대비 `execCommand` → `prompt` 3단 폴백 (Issue276 과 동일 규약)
    - i18n `msg.sidCopied*` ko/en 동시 추가 (test_i18n_parity 통과)

## Issue484: prj1 MCP 서버 2종이 2026-07-28 무상태 스펙 미반영 — aoa-mq 는 `initialize` 를 세션 마커로 쓰고 있어 그대로 전환하면 깨진다 ✅ 완료 (<commit>, <commit>, prj3 <commit>)
* 목적: prj20 f-claude-plugins 의 6개 MCP 서버는 무상태 스펙을 반영했으나(<commit>), prj1 이 소유한 [aoa-memory](mcp/aoa-memory/server.py)·[aoa-mq](mcp/aoa-mq/server.py) 는 미반영 상태다. 표준을 맞추되, aoa-mq 는 `initialize` 에 기능이 얹혀 있어 단순 복사가 회귀를 만든다 — 그 지점을 함께 처리한다.
* 구현 명세:
    - 로직:
        1. 두 `server.py` 의 `main()` 디스패처 맨 앞에 `server/discover` 분기 추가 — `supportedVersions: ["2026-07-28"]` · `ttlMs` · `cacheScope: "private"` · `capabilities` 반환
        2. `tools/list` 결과에 `ttlMs`·`cacheScope` 추가
        3. `tools/call` 결과에 `resultType: "complete"` 추가
        4. `initialize` 분기는 **삭제하지 않는다** — 구 클라이언트 하위호환
        5. **aoa-mq 전용**: `if method in ("initialize", "tools/call")` 를 `("server/discover", "initialize", "tools/call")` 로 확장. 이 항목이 빠지면 위 회귀가 그대로 발생한다
    - 검증:
        - 신 클라이언트 경로 — `server/discover` → `tools/list` 만으로 도구 목록 수신(`initialize` 미발생)
        - 구 클라이언트 경로 — `initialize` → `notifications/initialized` → `tools/list` 정상 동작
        - aoa-mq 마커 — `server/discover` 단독 수신 후 세션 활성 마커 파일의 mtime 이 갱신되는지 실측
        - 두 서버의 기존 도구 호출 각 1건 이상이 `resultType` 추가 후에도 정상 응답하는지 확인
    - 참조: prj20 f-claude-plugins `<commit>` (동일 변경의 선행 사례, 서버당 +19줄)

## Issue477: `_doc_base` gitignore 판정이 public/private 을 구분하지 않는다 — 백업 0 을 만든다 ✅ 완료 (<commit>, prj3 <commit>)
* 목적: 규칙의 **근거는 유출 방지**인데 **판정은 origin 유무**다. private repo 는 유출 경로가 없는데도 ignore 되어, 원천자료가 **버전이력·원격백업 둘 다 없는** 상태로 남는다. 실피해 1건 실측
* 구현 명세:
    - **판정 축을 `origin 유무` → `origin 의 공개성`으로 좁힌다**: public/미확인 → ignore(현행 유지) · **private → 추적 허용**
    - ⚠️ **반론을 함께 검토할 것 — 채택 전 결정 필요**:
        - private → public 전환 시 이력에 원천자료가 남는다. 전환은 클릭 한 번이고 **되돌려도 이미 노출된 것은 회수 불가**다. 현행 보수적 판정은 이 시나리오를 막는다
        - private 도 collaborator·조직 멤버에게는 열려 있다 — *"유출 0"* 이 아니라 *"유출면이 좁다"* 가 정확하다
        - 따라서 **자동 판정보다 프로젝트별 명시 선언**(`.claude/` 에 `doc_base_tracking: allow|deny`)이 나을 수 있다. 판정을 코드가 추측하지 않고 사람이 적는다
    - 어느 안이든 **백업 부재 자체는 별도 문제**다 — 정책을 안 고치더라도 원천자료의 백업 경로(별도 private repo·외부 백업)는 있어야 한다. aoa-mq 컨펌 항목이 그 결정을 묻고 있다
    - 전 프로젝트 영향 조사 선행: `_doc_base/` 를 실사용하면서 origin 이 private 인 repo 가 몇 개인지 — prj9a 외에도 같은 상태가 있을 수 있다

## Issue480: sanitize 가 문서 속 마커 *예시* 를 실제 redaction 마커로 센다 — forward 통째 중단 ✅ 완료 (<commit>)
* 목적: [`fpm-sanitize.sh`](scripts/fpm-sanitize.sh) 가 `grep -cF` 로 `<!-- fpm_private -->` 개수를 세는데, **그 마커를 설명하는 문서**의 백틱 인라인 코드까지 실제 마커로 센다. 불균형 판정 → fail-loud `exit 2` → `set -euo pipefail` 인 `do_forward` 가 그 자리에서 죽는다. **지금 미러 반출이 통째로 막혀 있다**
* 구현 명세:
    - 후보 ① 마커 카운터가 백틱 인라인 코드(`` `<!-- fpm_private -->` ``)를 제외 ② sanitize 를 exclude 적용 **뒤**로 이동 ③ 문서에서 마커 예시를 백틱이 아닌 다른 표기로
    - ⚠️ ②는 P3 가드(*"exclude 밖 파일에 private 블록"*)의 의미를 바꾼다 — 그 가드는 exclude 밖을 보는 것이 목적이라 순서를 옮기면 대상이 사라진다. ①이 가장 좁은 수정으로 보이나 **보안 게이트를 느슨하게 만드는 방향**이라 실측 후 확정
    - 종결 조건: `bash scripts/test_mirror_install.sh` 11건 전건 PASS (현재 10 PASS / 1 FAIL)

## Issue482: 게이트 판정이 공허하다 — `expect: nonempty` 는 절대 실패하지 않는다 ✅ 완료 (<commit>)
* 목적: `bundle-in-sync`·`i18n-parity` 는 `echo ok || echo DRIFT` 라 **양쪽 분기 모두** 비지 않은 값을 낸다. `nonempty` 판정에서 **원리적으로 상시 PASS** 다. 상시 통과는 진짜 실패를 묻는다
* 구현 명세:
    - 지목된 2건만 `contains:ok` 로. 나머지 `nonempty` 는 **환경 사실 보고**형(플랫폼명·date 구현·case sensitivity)이라 판정이 아니라 기록이 목적 — 유지한다. `windows.yml` 주석이 이미 *"FAIL 대상이 아니라 기록 대상"* 이라 적고 있다
    - ⚠️ **선행: 러너의 skip 인식**. `contains:ok` 로 좁히면 `skip(저작 머신 전용)` 출력이 FAIL 이 된다

## Issue483: `release-check.sh` 샌드박스가 실 저장소를 오염시킨다 ✅ 완료 (<commit>)
* 목적: 스테이지3 의 `uninstall.sh` 가 `HOME=$SBX` 로 돌아도 백업은 `${FPM_BACKUP_DIR:-<repo>/_doc_work/z_done}` 기본값을 타고 **실 저장소**로 나간다. 격리 HOME 인데 산출물은 밖에 쌓인다
* 구현 명세: `sb()` 에 `FPM_BACKUP_DIR="$SBX/backup"` 을 얹는다. uninstall 호출은 전부 `sb()` 경유라 지점이 하나다

## Issue478: release 라인 검수 게이트가 없다 — 안정화 브랜치가 그대로 미러로 나간다 ✅ 완료 (<commit>, <commit>, <commit>, prj3 <commit>)
* 목적: `release/{X.Y}` 라인을 실운용(0.8.0·0.8.1·0.8.3)하면서도 **검수가 언제 도는가**가 정의되지 않았다. 그 결과 ① 안정화 중인 코드가 매 커밋 공개 미러로 반출되고 ② 만들어 둔 통합 검증 게이트는 한 번도 돌지 않는다. 게이트를 **전이(커밋·반출·병합·출고) 4지점**에 배선한다
* 구현 명세:
    - **판정 한 줄**: *"게이트는 브랜치가 아니라 전이에 붙는다."* 브랜치가 늘어도 게이트 수는 늘지 않는다
    - **신설 자산은 `tdd/cases/release.yml` 하나** — `run-tdd.sh`·`release-check.sh`·브랜치 가드 셋은 이미 있다. 나머지는 전부 배선 문제다
    - 사용자 결정(2026-09-05): ① `release` 를 **정식 브랜치로 승격** ② G3 는 **enforce + 수동 사인오프 분리**
    - 서브 이슈 4건으로 분리. **478_1 이 최우선** — 유출이 진행 중이다

## Issue479: 무결성 매니페스트가 번들 변경을 따라가지 못한다 — 저작 머신 `check.sh` 상시 FAIL ✅ 완료 (<commit>, <commit>)
* 목적: `plugins/fpm-core/.fpm-integrity.json` 재생성이 `deploy`·`forward` 경로에만 배선돼 있어, **번들만 고치고 커밋하는 경로**가 매니페스트를 stale 로 남긴다. 그 결과 `sh/check.sh` 가 상시 FAIL 이고, **상시 FAIL 은 진짜 변조를 묻는다**
* depends: Issue478_2
* 구현 명세:
    - **선행 조건**: 번들 표류 먼저 해소해야 한다 — `bash scripts/fpm-bundle-sync.sh --check` 가 현재 `plugins/fpm-core/commands/fpm-hub.md` 1건 DRIFT(prj3 Issue529 in-flight). 표류 상태에서 매니페스트를 재생성하면 **표류를 그대로 봉인**한다. 순서는 `bundle-sync → gen-integrity-manifest → 커밋` 이다
    - 근본 원인 제거: 재생성 시점을 배포 경로에만 두지 말고 **번들이 바뀌는 지점**에 붙인다. 후보 ① `fpm-bundle-sync.sh` 말미에서 재생성 ② `pre-commit` 에 매니페스트 drift 검사 추가(prj1 은 이미 scar-manifest drift hook 보유 — 같은 계열)
    - ②는 G1 게이트 강화이자 **커밋 시점 차단**이라 재발 자체를 없앤다. ①만 하면 손으로 번들을 고치는 경로가 남는다. 실측 후 선택
    - ⚠️ 이 이슈를 닫기 전에는 `bash tdd/run-tdd.sh --only release` 가 FAIL 이므로 **출고(G4)가 막힌다**. 우회는 `FPM_SKIP_RELEASE_GATE=1` 이지만 그것은 무결성 결손을 안고 나가는 것이다

## Issue476: `pm-new` 등록 게이트에 저작자 판정이 없다 — 남의 repo 가 명부에 든다 ✅
* 목적: 등록 시 *"이게 내 프로젝트인가"* 를 묻는 자리가 없어 **외부 저작 클론이 명부에 섞였다**. 실발생 1건(prj17)이 212일 무커밋 🔴 로 잡혀 일몰 심사 후보까지 올라갔는데, 실제로는 방치가 아니라 **남의 repo** 였다
* 구현 명세:
    - **판정 한 줄**: *"내 커밋이 0건이고 origin 이 upstream 이면 등록하지 않는다."* 둘 다여야 한다 — fork 후 내가 커밋했으면 정당한 내 프로젝트다
    - ⚠️ **경로 기준(`_open/` 하위 제외)으로 잡지 말 것** — 그것은 관례일 뿐이라 보관소 밖에 둔 남의 repo 를 못 잡는다. prj6 초안이 경로 기준이었고, 저작자 기준이 실측 가능하고 경로에 의존하지 않는다는 이유로 바꿨다
    - `pm` 스킬 등록 절차에 확인 단계 추가 — `git log --author` 0건 + `git remote get-url origin` 이 upstream 이면 **경고 후 사용자 확인**. 차단이 아니라 확인이다(의도적 등록도 있을 수 있다)
    - 기존 명부 전수 점검은 **하지 않는다** — prj6#Issue7 이 미할당 25건을 이미 훑었고 나온 것은 prj17 하나다. 나머지는 손댈 때 걸린다
    - 연관: Issue472_7(`pm-new` 가 L1 을 얹는다)과 같은 등록 게이트를 건드리므로 함께 손보는 것이 자연스럽다

## Issue471: `fpm-simple-browser` 허용목록이 조항1 을 거부한다 — grep 사각지대 ✅
* 목적: [fpm-identity.md](_doc_arch/fpm-identity.md) 조항 1(외부 링크 = hub URL)을 **지킬수록 깨지는** 지점. hub 가 조항대로 `advertise_url`(MagicDNS 이름) 링크를 만들면 vscode 확장이 그 URL 을 **거부**한다
* depends: Issue469
* 구현 명세:
    - 허용목록을 `advertise_host` 기반으로 — 하드코딩 대신 hub `/healthz` 값 또는 설정에서 유도. **보안 허용목록 완화를 겸하므로 범위를 좁게** 잡을 것(임의 외부 URL 이 열리면 안 된다)
    - `vscode-ext/fpm-simple-browser/README.md:21` 동반 갱신
    - 🔑 재발 방지: **준수 실측을 grep 으로 갈음하지 말 것** — 출구(외부 발신·URL 생성·허용목록) 목록을 전수 대조하는 것이 시작점이다

## Issue475: `fpm-do` 가 자유 명령 위임에서 조용히 죽는다 — `set -e` + AND-list ✅
* 목적: `/issue-fix-*` 형태로 **변환되지 않는 모든 위임**이 무출력·rc=0 으로 종료된다. 실패했는데 성공처럼 보이므로 호출자는 위임이 걸린 줄 안다
* 구현 명세:
    - `[ -n "$n" ] && { ...; }` → `if [ -n "$n" ]; then ...; fi` (AND-list 를 없앤다) 또는 각 분기 뒤 `|| true`
    - 회귀 확인: ① `/issue-fix-g 3` ② `"Issue472 …"` ③ `"5 …"` ④ 숫자 0개 자유 명령 — **네 형태 모두** 위임이 걸리는가
    - ⚠️ **소유 경계 확인 필요** — 설계 SSOT 는 prj3 [`_doc_arch/fpm-do.md`](~/.claude/_doc_arch/fpm-do.md), 실행체는 `~/.bin/fpm-do`(prj5 가 `~/.bin` 배포 관리). 글로벌 SCAR 변경 가드 대상이므로 **prj3 `Issue.md` 등록 후 별도 세션**에서 수정한다. 본 이슈는 prj1 측 발견 기록이다
    - 무출력 자체도 결함이다 — `set -e` 로 죽더라도 trap 으로 사유 1줄은 남겨야 한다

## Issue474: tagcheck 가 서브이슈 번호를 구조적으로 거부한다 — `HEADING_RE` 가 `##` 만 본다 ✅
* 목적: 코드 주석에 **서브이슈 번호를 달 수 없다.** [precommit-tagcheck.py:29](scripts/precommit-tagcheck.py#L29) 의 `HEADING_RE` 가 `^## Issue` 만 매치하는데 서브이슈 헤딩은 `### Issue472_2:` 이므로, 정상 등록된 서브이슈도 *"오타·미등록 번호"* 로 판정되어 커밋이 거부된다
* 구현 명세:
    - `HEADING_RE` 를 `^#{2,3} Issue(...)` 로 확장. `issue-g.md` 규칙6·7 이 서브이슈를 부모 하위에 두도록 규정하므로 `###` 는 정상 형태다
    - L109 의 `HEADING_RE.match` 도 같은 패턴을 쓰므로 자동 해소된다
    - 회귀 확인: `### Issue{N}_{M}:` 등록분을 코드에 태그한 커밋이 통과하는가 · 미등록 `IssueN_M` 은 여전히 거부되는가
    - ⚠️ **부모 번호 태그를 금지하지는 않는다** — 코드가 부모 이슈 전체의 산출물인 경우가 정상이다. 서브이슈 번호를 **쓸 수 있게** 하는 것이 목적이지 강제가 아니다

## Issue472: 프로젝트 아이덴티티·목표 3층 체계 — CLAUDE.md frontmatter 소유 + Identity.md 집계 ✅
* 목적: 프로젝트가 **무엇이고 어디로 가는가**가 4곳에 흩어져 대부분 비어 있다. [fpm-identity.md](_doc_arch/fpm-identity.md) 가 생긴 이유(*"규약을 아는 곳은 있었으나 규약이 적힌 곳이 없었다"*)가 프로젝트 단위로 그대로 반복되는 중
* depends: Issue469, prj6#Issue2
* 구현 명세:
    - **3층 + 소유 주체** — L1 한 줄 정체성·수명은 각 프로젝트 `CLAUDE.md` frontmatter · L2 불변 조항 문서는 각 프로젝트 `_doc_arch/{name}-identity.md`(영속형+외부노출) · L3 **방법론·템플릿**은 prj6 `___architect`(조항 4) · **집계 생성물·수집기는 prj1**
    - **L1 필드 9종** (선택 2) — `prj`·`identity`(현재 무엇인가)·`identity_origin`(최초 목적, **갈렸을 때만**)·`not`(무엇이 아닌가)·`goal_parent`(목적 트리 부모)·`lifetime`(`finite`/`perpetual`)·`outcome`(기대 성과)·`deadline`(시한, 영속형 생략 가능)·`status`
    - **CLAUDE.md 에 두는 근거**: 매 세션 자동 로드되는 유일한 파일 → 정체성이 문서가 아니라 **작업 중 판정 기준**으로 작동한다. 별도 파일은 안 읽혀서 썩는다
    - 집계 `Identity.md` 는 **생성물**(직접 편집 금지). 미기재는 `⚠️ 미기재` 로 출력
    - ⚠️ **알림·스케줄·훅을 만들지 않는다** (prj6 조항 6) — 비어 있음·시한 경과는 **볼 때 보이는 표면**에만 노출한다. 목적 트리 `미할당` 과 같은 철학
    - 50개 일괄 금지 — 활성분부터. 나머지는 미기재로 남겨 노출만 한다

## Issue473: 조직도 노드가 아이콘 갤러리가 된다 — mermaid 주입 인라인 style 이 `width=16` 을 덮어씀 ✅
* 목적: 사용자 지적 — 조직도 아이콘이 너무 커서 한 화면에 조직이 안 담긴다. 노드가 아이콘 갤러리가 되고 정작 **관계**가 안 보인다
* 구현 명세:
    - [server.py](plugins/fpm-core/services/hub/server.py) `_render_fbot_map` CSS 에 `pre.mermaid img{display:inline-block !important;width:2.4em !important;height:2.4em !important;vertical-align:middle;margin-right:.25em}` 1규칙 추가. 인라인 style 을 이기는 수단은 `!important` 뿐
    - 아이콘 SVG 전환은 **불필요** — `data/fbot/icons/*.svg` 로 이미 전부 SVG 다(신규 생성분도 `fbot-icon` 스킬이 SVG 로 만든다). 구조 변경 0

## Issue469: 조항1(외부 링크=hub URL) 코드 정합 — aoa-mq 폴백 통일 + 발신 가드 ✅
* 목적: [fpm-identity.md](_doc_arch/fpm-identity.md) 조항 1 을 신설하며 실측했더니, 같은 규약이 코드 **3곳에서 각자 발명**되어 있었고 성숙도가 갈렸다. 조항을 문서로 박제했으니 구현을 그 문서에 맞춘다. 규약이 적힌 곳이 없어 새 출구마다 재발명되던 것이 근본 원인이다.
* 구현 명세:
    - `aoa-mq-tick.sh`: `ADVERTISE_HOST` 를 `/healthz` 의 `advertise_url` 조회로 교체. 값 부재 시 **Discord 발송에서 링크 줄을 빼고**, 그 사실을 본문에 1줄 명시(죽은 링크 금지 — 받는 쪽이 "링크 없음"과 "hub 꺼짐"을 구분할 수 있어야 함)
    - 잔존 0건 검증: `grep -rn "host\.local" mcp/ plugins/ sh/ scripts/` → 0
    - 조항 집행 가드(선택, 별도 판단): 외부 발신 직전 페이로드에서 로컬 절대경로·`file://`·`127.0.0.1`·`*.local` 을 검출하는 hook. 현재 조항 1 은 집행 수단이 없는 **passive** 상태이며, 가드를 넣어야 advisory 이상으로 올라간다
    - 종결 시 [fpm-identity.md](_doc_arch/fpm-identity.md) "현행 준수 실측" 표와 "미해결 항목" 을 같은 커밋으로 갱신

## Issue258: hub 내부 탭 alt+w 닫기 시 Chrome 크래시 — **macOS 접근성(AX) abort** ✅
* 목적: Issue223(디바운스)·237(playwright headless)·250(iframe fallback) 이후에도 Chrome 이 죽는 케이스 잔존. 사용자 확정 repro: **"hub 탭 여러 개 떠있을 때 + 내부 탭 alt+w 로 닫을 때"**. "완전 해결"(탭 수 무관) 요구.
* depends: Issue223, Issue237, Issue250

## Issue461: 공개 마켓 repo 는 sanitize 미적용 — 미러와 위생 정책 비대칭 + 유물 태그 ✅
* 목적: 미러(prj8)는 sanitize 를 거치는데 마켓 repo(prj20)로 가는 `do_publish` 는 **정본을 무치환 rsync** 한다. 공개 repo 에 내부 호스트명이 그대로 게시되는 상태
* 구현 명세:
    - 위생 정책을 어느 쪽으로 통일할지 **먼저 결정** — ⓐ 마켓도 sanitize 적용 vs ⓑ 내부 호스트명을 공개 허용으로 명문화
    - 유물 태그 삭제는 **사용자 승인 필수**(원격 ref 파괴 — `input-interpretation-rules` 예외 아님)

## Issue465: hub `server.py` 이중화 — 실행본과 배포 정본이 따로 있다 ✅
* 목적: `services/hub/`(실행)와 `plugins/fpm-core/services/hub/`(배포 정본)가 따로 존재해 bundle-sync 로만 일치가 유지된다. 한쪽만 고치면 조용히 갈라지는 구조 — 2원 자산의 전형
* 구현 명세: ⓐ 단일화(심볼릭 링크·단일 소스) vs ⓑ 현행 유지 + 자동 검증 강화 판정 → 택일 후 적용. 배포 경로에 영향이 크므로 배포 사이클 밖에서 착수

## Issue466: 에디터 지정이 macOS 전용 — `open -a` 잔존 (Issue432 잔여) ✅
* 목적: `_open_cmd()` 로 열기 자체는 3축 분기됐으나 **에디터 지정 경로**는 `open -a` 를 그대로 쓴다. Linux(host)·Windows(jpc1)에서 에디터 지정이 동작하지 않음
* 구현 명세: `open -a` 사용처 전수 → 플랫폼 분기(macOS `open -a` · Linux `xdg-open`/직접 실행 · Windows `start`) → 3축 스모크

## Issue459: 미러 무결성 매니페스트가 sanitize **이전** 기준으로 생성됨 — 소비자 `check.sh` 가 항상 FAIL ✅
* 목적: `.fpm-integrity.json` 은 정본 `$SRC/plugins/fpm-core` 바이트로 생성되는데 forward 는 미러에 **sanitize 변환본**을 쓴다. 매니페스트가 미러 바이트를 검증할 수 없어 **설치한 소비자가 check.sh 를 돌리면 무조건 무결성 FAIL** — 진짜 변조와 구분이 안 되므로 게이트가 무력화됨
* 구현 명세:
    - `gen-integrity-manifest.sh` 호출 시점을 forward(sanitize) **이후 미러에서** 재생성·커밋하도록 배포 순서 교정
    - 교정 후 미러에서 `check.sh --quiet` 무결성 FAIL 0 을 종결 조건으로 확인

## Issue467: `_doc_work/board/**/README.md` 추적 정책 (Issue430 곁가지) ✅
* 목적: gitignore 앵커를 고친 뒤 그동안 누락돼 있던 board README 들이 추적 대상으로 드러났다. 추적할지 계속 제외할지 정책 미정
* 구현 명세: board 산출물의 수명(이슈 단위 휘발 vs 영속) 판정 → gitignore 확정 → 이미 추적 중인 것 정리

## Issue463: `z_htm` 읽기 경로 제거 — 유지 근거의 전제 2개가 모두 소멸 ✅
* 목적: `_doc_arch/htm-lifecycle-design.md` 가 읽기 경로를 유지한 유일한 근거는 "제거하면 prj2 의 htm 77건이 즉시 403" 이었는데, 2026-09-01 재대조에서 그 피해 대상이 실측 0건으로 확인됨. 문서가 스스로 적어 둔 재검토 조건이 충족된 상태
* 구현 명세: `services/hub/server.py:144` `HTM_DIRS` 1줄 제거 + 주석·docstring 6건 정리 → `htm-lifecycle-design.md` FIXME 종결. 제거 후 hub 문서 링크 스모크 1회

## Issue457: deploy 에 정본↔미러 문서 diff 검출 가드 — INSTALL drift 재발 방지 ✅
* 목적: 코드·브랜치 가드(F5 계열)는 문서 역류를 못 잡는다 — INSTALL.md drift(Issue441) 실측의 재발 방지. `fpm-gitflow.md` "문서 파일도 C1~C3 대상" [TODO] 의 집행체 (후보 승격)
* 구현 명세: deploy 전 단계에서 정본↔미러 md 대조(tdd `mirror-doc-no-orphan-edit` 의 배포 게이트 편입 검토)

## Issue456: `check.sh` editor.yml 파싱이 로케일에 좌우된다 — LC_ALL=ko 에서 주석 미제거 WARN 13건 ✅
* 목적: [`sh/check.sh`](sh/check.sh) 409행 `sed -E` 가 host(`LC_ALL=ko_KR.UTF-8`)에서 주석을 못 걷어 한글 낱말을 에디터 이름으로 오인, WARN 13건 잡음. 실해는 없으나 같은 파싱이 다른 값에 번지면 오판이 된다 (후보 승격 — host 실측 2026-08-31)
* 구현 명세: 해당 sed 호출에 `LC_ALL=C` 접두(또는 파싱을 python 으로) + host 재실측으로 WARN 0 확인

## Issue441: `INSTALL.md` 가 prj1 ↔ 미러로 갈라졌다 — 미러 쪽이 더 최신이다 ✅
* 목적: host 설치 테스트 중 `INSTALL.md` 의 요구사항 절을 보강하려다 발견했다. **미러(prj8)에는 있고 prj1 에는 없는 내용**이 있다 — SSOT 가 하위 사본보다 낡았다
* 구현 명세:
    - ⓐ 두 판본을 **대조**해 미러에만 있는 개선을 prj1 으로 역류시킨다 (i18n 짝 `INSTALL_ko.md` 동반)
    - ⓑ 역류 후 sync 로 재배포해 **양쪽이 같은 내용**임을 확인한다
    - ⓒ 재발 방지 — 미러 직접 커밋이 문서에까지 일어났다는 것은 C1 규약이 문서에는 덜 지켜진다는 뜻이다. `deploy.yml` 에 **prj1↔미러 문서 drift 케이스**를 둘지 검토한다
    - ⓓ 검증: `diff` 로 두 판본의 요구사항 절이 일치

## Issue455: `..ask` 모달에서 답한 질문이 계속 펼쳐져 있어 다음 질문이 화면 밖으로 밀린다 — 질문 접기 ✅
* 목적: 사용자 지적(스크린샷 실측) — 질문 2건에 각 옵션 4개·설명문이면 모달 한 화면에 **한 질문도 다 안 들어간다**. 이미 답한 질문이 같은 높이를 계속 차지해, 다음 질문을 보려면 매번 스크롤해야 하고 지금 무엇에 답하는 중인지도 흐려진다
* depends: Issue452
* 구현 명세:
    - ⓐ `legend` 를 토글로 — 클릭하면 그 카드 본문만 접힌다. caret 로 상태 표시
    - ⓑ **답하면 자동으로 접는다** — radio 선택 시 그 카드를 접고 legend 에 **선택한 라벨을 요약**으로 남긴다(무엇을 골랐는지 접힌 채로 보여야 한다). 접은 뒤 다음 미답 카드로 스크롤
    - ⓒ 자동 접기를 **하면 안 되는 경우**를 지킨다: ① checkbox(multiSelect — 여러 개 고르는 중) ② '기타 (직접 입력)' 선택(입력이 남았다) ③ 카드가 1개뿐(접을 이유가 없다)
    - ⓓ CSP — shim JS 는 nonce 를 타므로 인라인 핸들러 금지, `addEventListener` 만 (Issue452 와 동일 제약)
    - ⓔ 폼 구조에 과하게 기대지 않는다 — 폼 HTML 은 Claude 생성이라 class 가 어긋날 수 있다. `legend` 가 있는 `fieldset` 이면 붙인다

## Issue449: aoa 정책 템플릿이 정본·미러 두 벌로 갈라진다 — 동기 수단도 검사도 없다 ✅
* 목적: Issue447 처리 중 실측으로 드러났다. `data/aoa/policy.default.yml` 이 **정본(prj1)과 미러(prj8) 양쪽에 각각 존재**하는데, `publishable-policy.yml` 의 `exclude[]` 에 `data/aoa/` 가 있어 forward 가 이 파일을 전송하지 않는다. 즉 **한쪽을 고쳐도 다른 쪽은 영원히 모른다**
* depends: Issue447
* 구현 명세:
    - ⓐ 세 안 중 택일 — ① 템플릿을 `data/aoa/` **밖**으로 옮긴다(`data/template/` 등. 런타임 디렉토리와 배포 자산을 분리 — 뿌리 제거) ② `exclude[]` 를 `data/aoa/` → 런타임 산출물 개별 항목으로 좁힌다(신규 산출물 자동 노출 갭 발생) ③ 정책 스키마에 `!` 재포함을 도입해 rsync `--include` 로 변환(엔진 변경 — `_commit_is_exclude_only` 등 다른 소비처 영향 검토 필요)
    - ⓑ **미러 결손 4키를 먼저 해소**한다 — ⓐ 결정 전이라도 소비자 실해가 진행 중이다. 미러 직접 수정은 타 repo 이므로 승인 대상
    - ⓒ 이행 후 검증 — 정본과 미러의 템플릿이 **내용 동일**한지 tdd·`check.sh` 중 한 곳에서 본다. 지금은 갈라져도 아무도 모른다
    - ⓓ 같은 형태의 자산이 더 있는지 전수 — "미러 단독 자산 8종"(Issue411 검증 목록)이 각각 왜 단독인지, 갈라짐 검사가 있는지

## Issue452: hub `..ask` 가 맥락 문서를 55vh iframe 에 가둔다 — 주종을 뒤집어 a 문서 위 모달로 ✅
* 목적: `..ask` 는 b(폼)를 주 페이지로 열고 짝 a(`..show` 렌더)를 `<details>`+`iframe height:55vh` 로 종속 임베드했다(prj3#Issue143). 정작 읽어야 할 본문이 반쪽 창에 갇혀 이중 스크롤이 되고, iframe src 가 `/md-doc` 셸이라 hub 헤더가 두 번 렌더되며, 탭·URL 이 2개로 갈렸다. **맥락이 주(主), 질문이 종(從)** 이 되도록 뒤집는다. 본 이슈 범위는 **hub 서버**뿐 — 생성 지점(hook `show-pair` 스니펫)은 짝 이슈 prj3#Issue492

## Issue454: 조직도에 완료·취소 배분과 원장 고아가 상시 그려진다 — 기록을 옵션 버튼으로 ✅
* 목적: 사용자 지적 — 원장에만 남은 고아(fbot-research-issue4363, done)가 점선으로 **영원히** 남는다. 조직도의 목적은 "지금 어떤 핀봇이 어떤 핀봇에게 일을 시키는가" 이지 done·cancelled 잔재 열람이 아니다. 옵션 버튼 요구

## Issue446: hub 의 `/tmp` 상태 경로가 셸과 python 에서 **다른 폴더**다 — Windows 에서 상태 파일이 갈라진다 ✅
* 목적: Issue437 검증 중 발견. hub 가 죽어 pid 파일을 지우려 했는데 **셸에서 지운 파일과 python 이 보는 파일이 서로 달랐다.** 지웠는데도 같은 오류가 반복돼 원인을 한 번 헛짚었다 — 사람을 오진으로 끌고 가는 종류다
* depends: Issue437
* 구현 명세:
    - ⓐ 상태 루트를 **1지점**에서 결정한다. python 은 `/tmp` 하드코딩 대신 `tempfile.gettempdir()`(Windows = `%TEMP%`)를 쓰고, 셸은 **그 값을 물어보는** 형태로 맞춘다 — 양쪽이 각자 계산하면 다시 갈라진다
    - ⓑ `/tmp/___pm/…` 하드코딩을 전수 제거(셸·python 양쪽). 남은 1건이 곧 갈라짐이다
    - ⓒ 이행 — 기존 경로에 파일이 있으면 새 경로로 이관하거나 self-heal 한다. 그냥 옮기면 구동 중인 hub 가 자기 pid 파일을 잃는다
    - ⓓ 검증: jpc1 에서 ① 셸과 python 이 **같은 파일**을 가리키는지 ② `/hub stop` 이 실제 그 파일을 지우는지 ③ macOS 회귀 없음(`/tmp` 그대로)

## Issue451: 조직도 all=1 에 퇴역(휴직·해고)까지 같은 비중으로 그려진다 — 그래프 제외·명부 전수 보존 ✅
* 목적: 사용자 지적 — `?all=1` 전체 뷰에 퇴근이 너무 많다. 실측: taskmgr 그룹 11봇 중 **5봇이 휴직(leave)** 인데 전부 그려짐. `all` 은 하루 축(출근/퇴근) 복원이지 경력 축 퇴역까지 그리라는 뜻이 아니다

## Issue450: 홈 핀봇 카드 퇴근 워커 무한 성장 — 최근 24h 칩만 남기고 "외 N개" 접기 ✅
* 목적: 사용자 지적 — 작업핀봇 그룹에 퇴근 워커 칩 11개가 나열되고 이슈마다 늘어난다. 조직도(?root=fbot-taskmgr, Issue488 활성 기본)와도 정합하지 않는다. 활성 세션의 "외 N개" 관례로 접는다

## Issue447: `policy.default.yml` 이 gitignore 에 걸려 배포되지 않는다 — 소비자의 aoa 부트스트랩이 통째로 막힌다 ✅
* 목적: [`sh/fbot-bootstrap.sh`](sh/fbot-bootstrap.sh) 가 정책 템플릿 정본으로 읽는 `data/aoa/policy.default.yml` 이 **git 이력에 한 번도 올라간 적이 없다.** 소비자는 clone 직후 `🚨 정책 템플릿 부재 (저장소 손상?)` 를 받는다 — 저장소는 멀쩡한데 손상됐다고 보고하는, 사람을 오진으로 끌고 가는 종류다
* 구현 명세:
    - ⓐ [`.gitignore`](.gitignore) 에 `!data/aoa/policy.default.yml` 예외를 둔다 — 런타임 산출물(`registry.db`·`learn.db`·`policy.yml`)은 계속 무시하고 **템플릿만** 추적. 미러 반출 대상인지도 함께 확인한다(`publishable-policy.yml` 이 이미 이 파일을 "미러 단독 자산" 으로 열거하고 있다 — 정본이 없는데 검증 목록에는 있다)
    - ⓑ 템플릿을 **실제로 작성**해 커밋한다. 현재 파일 자체가 없으므로 [`mcp/aoa-memory/policy.py`](mcp/aoa-memory/policy.py) `DEFAULTS` 18키를 근거로 만들되, `consolidation_budget_monthly_tokens: 0`(미지정 시 fail-loud) 같은 항목은 **주석으로 의미를 남긴다**
    - ⓒ tdd 케이스 — 템플릿이 **git 에 추적되는지**(`git ls-files`)를 본다. 파일 존재만 검사하면 저작 머신에서 통과하고 소비자에서 깨진다(Issue435 계열의 함정 그대로다)
    - ⓓ 가드 순서 재검토 — 정책 템플릿 부재가 스토어 생성까지 막을 이유가 있는지. 없다면 policy 단계 직전으로 내린다
    - ⓔ 검증: 깨끗한 clone 에서 `bash sh/fbot-bootstrap.sh` 가 rc=0 이고 `registry.db`·`policy.yml` 이 모두 생기는지

## Issue448: (!) hub 헤더에 핀봇 조직도 버튼 신설 + fbot-map 이모지를 👥 로 분리 ✅
* 목적: 사용자 지적 2건 — ① `/fbot-map` 진입이 핀봇 섹션 안 작은 링크뿐이라 헤더 버튼이 필요 ② 그 링크가 프로젝트 Map 버튼과 같은 🗺 이모지를 써서 **두 지도가 구분되지 않는다**. 조직도는 👥(구성원 은유)로 분리한다(사용자 선택)

## Issue436: `python3` 가 MS Store 스텁인데 설치기가 그것을 실물로 잡아 MCP 커맨드에 박는다 ✅
* 목적: jpc1 에서 MCP 서버 2종(`aoa-mq`·`aoa-memory`)이 **연결 실패**(`CONNECTION_CLOSED`)한다. 원인은 등록된 커맨드가 `…/WindowsApps/python3` — 실행하면 rc=49 로 죽는 **Microsoft Store 리디렉터 스텁**이다. Windows 는 `python3` 라는 이름이 *"있지만 실행되지 않는"* 상태가 기본값이라, `command -v` 만으로는 판정이 안 된다
* 구현 명세:
    - ⓐ 인터프리터 판정을 **존재 → 실행**으로 바꾼다: `"$c" -c 'import sys' >/dev/null 2>&1` 이 통과한 후보만 채택. 후보 순서는 `$FBOT_PYTHON` → `python3` → `python` → `py -3`
    - ⓑ 채택 근거를 **1줄 로그**로 남긴다(어느 후보가 왜 탈락했는지). 지금은 스텁을 잡은 사실이 출력에 안 보인다
    - ⓒ MCP 재등록에 **경로 검증 후 갱신** 경로를 둔다 — 등록된 커맨드의 인터프리터가 실행 불가면 "보존" 이 아니라 교체한다. 사용자 커스터마이즈 보존 원칙과 충돌하므로, 교체는 **실행 실패가 확인된 경우로 한정**한다
    - ⓓ `fbot-bootstrap.sh` 의 실패 메시지에서 FTS5 단정을 걷어낸다 — FTS5 여부를 **실제로 검사한 뒤에만** 그 원인을 말한다
    - ⓔ 검증: jpc1 에서 `claude mcp list` 가 2종 모두 ✔ Connected 인지 확인

## Issue437: Git Bash 에 `pkill`·`pgrep`·`setsid` 가 없다 — hub 재기동이 Windows 에서 성립하지 않는다 ✅
* 목적: 설계문서 W6 축의 실측 결과. tdd `process-mgmt` 가 **FAIL** 이다. Git Bash(MSYS2)는 procps 를 동봉하지 않아 세 명령이 **모두 부재**한다 — "동작 차이" 가 아니라 "없음" 이다
* 구현 명세:
    - ⓐ 프로세스 조회·종료를 **헬퍼 1지점**으로 모은다(`_fpm_pgrep`·`_fpm_pkill`). OS 로 분기하지 말고 **도구 가용성으로 분기**한다 — 원칙 3-1
    - ⓑ Windows 폴백: `tasklist`/`taskkill` 또는 MSYS `ps` 파싱. 어느 쪽이 PID 정합을 유지하는지 jpc1 에서 먼저 측정한다
    - ⓒ 폴백조차 없으면 **조용히 넘어가지 말고** 경고를 낸다 — "재기동했다" 는 거짓 보고가 지금의 실패 양상이다
    - ⓓ 검증: jpc1 에서 `process-mgmt` 케이스 PASS + hub stop/start 실제 확인

## Issue445: 핀봇 조직도·홈에서 "누가 누구에게 일을 시켰는지" 와 "봇↔세션 연결" 이 안 보인다 ✅
* 목적: prj3 세션 위임. 조직 관측의 목적이 *"묻지 않아도 안다"* 인데, 정작 **지시 관계**와 **봇↔Claude 세션 연결**이 화면 어디에도 없어 사용자가 세션 UUID 를 들고 와 "이게 중역핀봇이냐" 고 되물어야 했다(2026-08-31 실발생 — `<commit>-…` 는 `fbot-igmaker-issue335` 였고 나래는 별도 세션 `<commit>-…`).
* 구현 명세:
    - A. 표시 — `_collect_bots()` 에 `parent_title`·`session_id`·`tmux_target` 편입, `botCard()` 표면에 지시자 이름 + 세션 단축칩, `botDetail()` parent 를 **이름(ID)** 로 resolve, `/fbot-map` 명부 표에 **지시자·세션·pane** 3열 추가
    - B. 기록 — `fbot-state.py` 에 `dispatch-record` 서브커맨드 신설(배분 원장 `kind='fbot_dispatch'` 1행 기록, **상한 미차감·미검증** — 이미 일어난 사건의 기록이지 신규 배분 승인이 아니다), `~/.bin/fpm-do` 가 봇 스폰 위임(`FBOT_ID` 있음)에서 호출
    - 판정 단일 지점 유지 — 부모-자식은 `_fbot_root_map()` 재사용, 배분자 해소는 레지스트리 `parent_bot_id`/`whois` 재사용. 재귀·역조회 로직 재작성 금지
    - **중간 사영 파일 금지** — `registry.db` 직독 유지(`server.py` 2913-2914 anti-pattern)
    - payload 비대화 주의 — 신규 필드는 **활성 봇 카드(`bots`)에만**. `bots_roster`(전원)에는 싣지 않는다(아이콘을 루트 봇에만 싣는 기존 판정 승계)
    - 구 스키마 호환 — `session_id`·`tmux_target` 은 prj3#Issue448 ALTER 로 들어온 컬럼이다. `PRAGMA table_info` 로 실재를 확인하고 SELECT 를 구성한다. 없는 DB 에서 `no such column` 으로 핀봇 섹션이 통째로 죽으면 안 된다
    - 2원 배포 동시 수정 — `services/hub/server.py` ↔ `plugins/fpm-core/services/hub/server.py`
    - ⚠️ **repo 경계**: `~/.claude/hooks/fbot-state.py`(prj3 라이브 SSOT)·`~/.bin/fpm-do` 는 **다른 repo** 다. 본 세션은 위임 안전 지시에 따라 **편집만 하고 커밋하지 않는다** — 해당 커밋은 각 repo 소유 세션 몫

## Issue444: hub htm 문서가 목록에서 빠지면 `/hub-rescan` 이 되살리지 못한다 — 활성 세션 프로젝트만 스캔한다 ✅
* 목적: 6일 전 만든 hub 문서를 다시 열자 403 `not a registered htm doc`. **파일은 멀쩡히 있고 tombstone 도 아닌데**, 설계가 약속한 복구 경로(`/hub-rescan`)가 그 파일을 되살리지 못했다. 게다가 이 증상은 *"Tailscale 로만 안 보인다"* 로 오인되기 쉽다 — 원격에서 열려다 실패하지만 실제로는 `127.0.0.1` 도 똑같이 403 이다(실측)
* 구현 명세:
    - [`services/hub/server.py`](services/hub/server.py)(+번들 사본 `plugins/fpm-core/services/hub/server.py`)에 `_registered_project_dirs()` 신설 — `REPO_ROOT/projects/{번호}` 전수를 읽어 존재하는 디렉토리 경로 목록을 반환
    - `_handle_hub_rescan()` 의 스캔 대상을 `for h, p in snap`(런타임 `projects` 만) 에서 **활성 세션 cwd ∪ `_registered_project_dirs()`** 집합으로 확장 — 세션 유무와 무관하게 등록 프로젝트 전체가 스캔 대상이 되어 `_prune_htm_registry` 와 대칭이 맞음
    - 판정 보류: "링크 수명을 registry 수명과 분리해 경로 화이트리스트로 열지" 여부는 별도 설계 결정 사항으로 남긴다 — 이번 수정은 rescan 이 등록 프로젝트를 빠짐없이 스캔하는 것만으로 재현 증상을 해소함

## Issue435: `run-tdd.sh` 가 케이스 0건을 돌고 "전부 통과" 를 낸다 — 검증 체계 자신이 실패를 삼킨다 ✅
* 목적: jpc1 실측에서 `bash tdd/run-tdd.sh` 가 **PASS 0 / FAIL 0 / exit 0 / "✅ 이 머신에서 전부 통과"** 를 출력했다. 한 건도 돌지 않았는데 통과로 보고한 것이다. tdd 는 "조용한 실패" 를 잡으려고 만든 폴더인데 **러너 자신이 그 패턴의 사례**가 됐다
* depends: Issue436
* 구현 명세:
    - ⓐ 케이스 수 파싱을 **fail-loud** 로: 파서가 실패하면 `0` 이 아니라 **즉시 비정상 종료**(rc≠0)한다. "돌 게 없다" 와 "돌 수 없다" 를 구분한다
    - ⓑ **실행 0건이면 통과가 아니다** — `PASS+FAIL == 0` 이면 성공 문구를 내지 말고 rc=1 로 끝낸다. 파싱을 고쳐도 이 가드는 남긴다(다른 이유로 0건이 되는 경우가 또 생긴다)
    - ⓒ 인터프리터 해석을 `python3 → python → py -3` 순 폴백으로. `core.yml:python3-available` 이 이미 쓰는 계약과 일치시킨다
    - ⓓ 검증: 인터프리터를 일부러 못 찾게 한 상태에서 러너를 돌려 **rc≠0** 인지 확인한다

## Issue443: 죽은 `/sync-ma` 자산 폐기 — 호스트 `ma` 부재 (prj5#Issue80 요청) ✅
* 목적: `/sync-ma` 는 **영구 실패 상태**로 방치돼 있었다. 대상 호스트 `ma` 는 2026-04-02 `host` 로 개명됐고 지금 `~/.ssh/config` 에도 DNS 에도 **없다** — 호출하면 `Could not resolve hostname ma` 로 반드시 실패한다. 죽은 커맨드가 목록에 남아 있으면 다음 세션이 그것을 유효한 선택지로 읽는다. 요청 출처는 **prj5(`___common`) Issue80**(2026-08-31 사용자 승인 "전체 진행"), 위임 요청서는 prj5 `_doc_work/plan/sync-ma-retire_task.md`
* depends: prj5#Issue79 (완료 — `/sync-host` 진입점 PATH shim, prj5 `<commit>`·`<commit>`)
* 구현 명세:
    - **삭제 2건**: [`.claude/commands/sync-ma.md`](.claude/commands/sync-ma.md)(wrapper 커맨드) · `.claude/skills/sync-ma/`(폴더째, 내부 `index.md`)
    - **갱신 5건**: [`Harness.md`](Harness.md) "동기화 (sync)" 절 · [`_doc_arch/Harness/Harness.md`](_doc_arch/Harness/Harness.md) sync 도메인 블록·실행 환경 분류 표·글로벌 의존성 표 · [`_doc_arch/prj1-prj5-scope-split.md`](_doc_arch/prj1-prj5-scope-split.md) 43행(🚧 해소) · [`.claude-plugin/README.md`](.claude-plugin/README.md) 공개/비공개 자산 표 · ⚠️ **요청서에 없던 2건 추가** — [`_doc_arch/prj1-prj5-scope-split.md`](_doc_arch/prj1-prj5-scope-split.md) **31행**(A 표 "잔류 확정" 항목이 `sync-ma` 를 열거하고 있어 43행 각주와 어긋남) · — [`data/publishable-policy.yml`](data/publishable-policy.yml) `exclude[]` 의 `sync-ma` 2행. 파일이 사라지면 죽은 참조가 되므로 `rename-reference-rules`("사후 0건") 취지에 따라 함께 제거
    - **보존** — 당시에 사실이었던 기록은 손대지 않는다: `_doc_work/Issue_OLD.md` · `_doc_work/z_done/` · `_doc_work/report/_dailyBriefing/` · [`_doc_arch/publishable-policy.md`](_doc_arch/publishable-policy.md)(redaction 예시) · [`_doc_arch/issue-private-mode.md`](_doc_arch/issue-private-mode.md)(이력 재작성 당시 커밋 사실) · [`_doc_arch/fpm-competitive-benchmark.md`](_doc_arch/fpm-competitive-benchmark.md)(chezmoi 비교 문맥)
    - 절차: `rename-reference-rules` 준수 — 사전 grep → 제거 → 참조 갱신 → 사후 확인 → **단일 커밋**

## Issue440: `tdd/results/` 가 소비자 repo 에서 추적 후보로 뜬다 — 미러 `.gitignore` 는 sync 대상이 아니다 ✅
* 목적: [`tdd/README.md`](tdd/README.md) 는 *"결과는 `tdd/results/` 에 남고 **gitignore** 다 — 개인 경로·호스트명이 섞이므로 공유하지 않는다"* 고 규정한다. 그러나 소비자 머신에서 `git status` 는 `?? tdd/results/` 를 낸다 — 규약과 실제가 어긋나 **개인 정보가 커밋될 수 있는 상태**다
* 구현 명세:
    - ⓐ 미러 `.gitignore` 를 고치는 길은 C1 규약상 **단명 브랜치 왕복**이 필요하다 → 채택하지 않는다
    - ⓑ 대신 **결과 폴더가 스스로를 무시**하게 한다 — 러너가 `results/` 를 만들 때 그 안에 `.gitignore`(`*`) 를 함께 둔다. 미러를 건드리지 않고 어느 설치본에서든 성립한다

## Issue439: rc 블록이 있으면 **경로가 달라도 갱신하지 않는다** — repo 이전·재설치에서 낡은 경로가 고착된다 ✅
* 목적: host 클린 설치 실측에서 드러났다. `~/_git/fpm` 을 지웠는데 `.zshrc:242`·`.bashrc:137` 의 fpm 블록은 남아, 셸을 열 때마다 `no such file or directory: …/sh/fpm.sh` 가 났다. 그 상태로 재설치했더니 [`sh/install.sh`](sh/install.sh) 는 **"이미 fpm 블록 존재 — skip"** 을 냈다
* 구현 명세:
    - ⓐ 블록 안의 `FPM_BASE` 를 읽어 **현재 repo 와 비교**한다. 같으면 skip, 다르면 갱신
    - ⓑ 갱신은 **백업 후 블록 범위 안에서만** 치환한다 — rc 의 다른 라인은 건드리지 않는다
    - ⓒ 검증: 낡은 경로 블록 + 블록 밖 동명 변수(decoy)를 둔 rc 로 설치해 **블록만 갱신**되는지 확인

## Issue438: `source` 의 rc 로 판정해 cdf 로드를 오탐한다 — 부트스트랩의 rc 가 우연에 좌우된다 ✅
* 목적: host `check.sh` 가 `cdf 함수 로드 실패` WARN 을 냈다. 그러나 실제 셸에서 `cdf` 는 **정상 동작한다**. 검증기가 멀쩡한 설치를 실패로 보고한 것이다
* 구현 명세:
    - ⓐ `check.sh` 의 판정을 **결과 기준**으로 — source 의 rc 를 보지 않고 `cdf` 가 정의됐는지만 본다
    - ⓑ `fpm.sh` 의 **source rc 를 계약으로 고정** — 말미에 명시적 성공을 둔다. 부트스트랩의 rc 가 "마지막 선택 파일의 존재 여부" 에 좌우되면 안 된다. ⓐ 만으로는 `source fpm.sh && …` 를 쓰는 다른 소비자가 같은 함정에 빠진다

## Issue421: 미러에 릴리스 브랜치를 두면 F5-0 가드와 충돌한다 ✅
* 목적: prj8 미러를 `release/0.8.0` 으로 체크아웃한 상태에서 `forward` 를 돌리면 **F5-0 가드가 차단**한다(*"미러 상주 브랜치는 main 하나다"*). 릴리스 라인을 6곳에 맞추라는 운영 요구와, 미러를 단일 브랜치로 묶는 가드가 **서로를 배제**한다. 이번(Issue420)에는 두 브랜치가 같은 커밋이라 `main` 전환 → forward → `release/*` 를 main 으로 이동해 넘겼지만, **수동 3단계를 매번 반복**해야 하고 잊으면 미러 브랜치가 갈라진다
* 구현 명세:
    - ① **판정 먼저** — ⓐ 미러는 `main` 만 두고 릴리스 라인은 **정본·prj3 에만** 두는가, ⓑ 미러도 `release/*` 를 갖되 F5-0 이 `main` + `release/*` 를 함께 허용하는가
    - ② ⓐ 채택 시 — [`fpm-gitflow.md`](_doc_arch/fpm-gitflow.md) R1~R4 에 *"미러는 릴리스 라인을 갖지 않는다"* 를 명문화하고, 미러의 `release/*` 를 정리
    - ③ ⓑ 채택 시 — `guard_dst_branch()` 의 허용 목록에 `release/*` 추가. ⚠️ 그러면 **어느 브랜치로 sync 됐는지**가 갈릴 수 있어 `mirror_scan()` 의 미흡수 판정 기준을 함께 손봐야 한다
    - 검증: 판정된 쪽으로 `forward` 를 1회 태워 **수동 브랜치 전환 없이** 통과할 것

## Issue433: jpc1 적용 전 점검 3종 — 설계·전제조건·Windows 시뮬레이션 ✅
* 목적: 사용자 지시 — *"이제 jpc1 에 적용할 것인데 그 전에 ① 설계 문서 검토 ② 설치 문서에서 pre-requisite 검토(claude code 설치 여부, 노드 최소 버전 등) ③ 윈도우 버전에 대한 tdd 시뮬레이션"*
* depends: Issue432

## Issue432: OS별 설치 문서 + Windows 판정을 Git Bash 로 전환 ✅
* 목적: 사용자 질문 — *"설치 문서 따로 있나? README.md 에 있는 것이 다인가? 맥·리눅스·윈도우 버전별 설치 문서가 필요해졌는데, 윈도우는 gitbash 방식이 더 유리하지 않은지 검토도 같이 해달라"*
* depends: Issue431

## Issue431: `mcp/` 제거 판정 + tdd 확충 + Windows 이식 설계 ✅
* 목적: 사용자 지시 — *"mcp 폴더는 이제 제거되어야 하지 않을까? prj20 에서 진행하잖아. tdd 작업 진행(host·host)하고, 이번 tdd 성공하면 windows 버전 테스트 진행 예정이니 설계문서와 tdd 항목과 windows 구현을 위한 설계를 진행해달라"*
* depends: Issue430
* 구현 명세:
    - ① tdd core 케이스 **+3** — `mcp-server-present`(위 사실을 **케이스로 붙잡아 둔다** — 이행 전까지 누가 지우면 즉시 FAIL) · `hub-tick-resolvable` · `aoa-mq-due-transition`(파싱만이 아니라 **전이까지** 확인)
    - ② [`windows-port.md`](windows-port.md) 신설 — **실패 축 W1~W8**(줄바꿈·심볼릭링크·경로형식·python 이름·date·프로세스관리·파일권한·대소문자) · 셸 후보 4종 비교 · 이행 순서
    - ③ windows 케이스 **8종** 완비 — 설계 문서의 W# 와 케이스 id 를 상호 연결
    - ④ `_doc_arch/README.md` 색인 등재

## Issue430: Windows 11 대비 3축 설계 + 머신별 기능 테스트 `tdd/` 신설 ✅
* 목적: 사용자 지시 — *"최종적으로 windows11 에서도 동작해야 한다. 이런 문제를 해결하기 위한 설계 업데이트가 필요하고, 동작하는 각 머신에서 기능 테스트를 위한 목록 파일도 같이 동기화되어야 한다. github 에 공유되어야 하니 `_doc_*` 폴더가 아닌 `tdd` 폴더를 따로 만들어 관리하면 좋겠다"*
* depends: Issue429
* 구현 명세:
    - ① `_fpm_platform()` 신설 — `macos|linux|wsl|windows|unknown` 정규화 1단어. **wsl 을 linux 와 나눈다**(파일시스템·시계·GUI·`wslpath` 가 달라 "리눅스인데 리눅스가 아닌" 실패가 난다)
    - ② **`tdd/` 신설** — `machines.yml`(명부) · `cases/{core,macos,linux,windows}.yml` · `run-tdd.sh`(러너). 케이스마다 `why:` 에 **실패 이력(이슈 번호)** 을 남긴다 — 왜 있는지 모르면 다음 사람이 지운다
    - ③ `publishable-policy.yml` — `mirror_dir_allow` 에 `tdd` 등재(**소비자가 받아야 한다**), `exclude` 에 `tdd/results/`(개인 경로·호스트명 섞임)
    - ④ [`fpm-sync-deploy.md`](fpm-sync-deploy.md) — 3축 표 · Windows 실패 축 5종 · `tdd/` 절 (489 → 616줄)

## Issue429: 크로스플랫폼 함정을 검사로 잡는다 + 배포 경로 교통정리 ✅
* 목적: 사용자 지적 — *"배포 절차가 복잡하고 역방향과 정방향도 있고 복잡하다. 정방향 쪽도 Linux 와 mac 의 차이라 OS 따라 다르게 진행되는 스크립트가 필요하니 교통정리가 필요하다. 배포설계문서 보강하고 함정 해결해달라"*
* depends: Issue428, prj3#Issue475, prj3#Issue476
* 구현 명세:
    - ① [`check.sh`](../sh/check.sh) **항목 15 신설** — 15-1 BSD date 에 GNU fallback(**FAIL**) · 15-2 홈 절대경로 실행체 탐색(WARN) · 15-3 **이 OS 에서 date 파싱 실측**(FAIL)
    - ② 15-3 이 핵심 — 코드를 읽어 `date -j` 가 Linux 에서 안 되는 것은 알아도 **그 실패가 `0` 으로 둔갑해 무증상이 된다**는 것은 정적 검사로 안 보인다. **실행해 본다**
    - ③ [`fpm-sync-deploy.md`](fpm-sync-deploy.md) 에 *"크로스플랫폼 — 배포되는 코드는 남의 OS 에서 돈다"* 절 신설 — 함정 3종 표 · *"왜 조용히 실패하는가"* · **3원칙** · 집행 표 · **배포 경로 3종 표** · 버전 같으면 갱신 안 되는 문제(Issue422 부작용)

## Issue428: hub 가 tick 스크립트를 홈 절대경로로만 찾는다 — 소비자 머신에서 타이머 미기동 ✅
* 목적: 0.8.1 발행 검증 중 발견. [`server.py`](services/hub/server.py) 가 `AOA_MQ_TICK` 을 **`~/.claude/mcp/aoa-mq/aoa-mq-tick.sh` 하나로 하드코딩**한다. host 는 `~/.claude` 가 곧 prj3 repo 라 파일이 있지만, **소비자 머신의 `~/.claude` 는 플러그인 설치본**이라 그 경로가 없다 → host 에서 hub 의 **tick 타이머가 통째로 미기동**했다
* depends: Issue425
* 구현 명세:
    - `_resolve_aoa_mq_tick()` 신설 — env(`AOA_MQ_TICK`) → **repo 동거본**(`REPO_ROOT/mcp/aoa-mq/`) → 홈(`~/.claude/mcp/`) → 폴백. `REPO_ROOT` 는 942행에 이미 `__file__` 기준으로 정의돼 있다
    - 우선순위가 **repo 동거본 먼저**인 이유 — hub 를 띄운 그 repo 의 tick 과 짝이 맞아야 버전 불일치가 없다

## Issue427: Discord 알림에서 hub 로 넘어갈 링크가 없다 — 체인이 네 군데 끊겨 있었다 ✅
* 목적: 사용자 지적 — *"tailscale 을 쓰는 이유가 openclaw 에서 링크해서 넘어가기 위함(외부망일 때)인데, openclaw 설정부터 해서 discord 로 전송되게 해야 한다"*. 목적을 듣고 보니 **체인 전체가 끊겨 있었다** — Issue425 가 고친 것은 그중 한 조각일 뿐이었다
* depends: Issue425, Issue426
* 구현 명세:
    - ① `hub_links()` 신설 — `/healthz` 의 `advertise_url` 을 조회해 `{base}/mq`·`{base}/hub` 2줄. **값이 없으면 링크를 만들지 않는다**(Issue425 원칙 그대로)
    - ② **링크는 sanitize 뒤에 붙인다** (사용자 판정: 링크만 예외). 본문의 다른 개인 경로·계정·사설 프로젝트명은 그대로 마스킹된다 — 예외는 링크 줄에 한정. 경계 assert(`assert_clean`)는 절대경로·토큰·이메일만 보므로 정상 통과
    - ③④ 사용자 입력 대기 — 채널 id·설치

## Issue426: 설정창에서 tailscale 설정을 찾을 수 없다 ✅
* 목적: 사용자 지적 — *"tailscale 설정 어디 있는지 나는 못 찾겠음"*. 실제로 **설정창 어디에도 "tailscale" 이라는 단어가 없었다**. 항목은 `advertise_host`(한글 라벨 **"어드버타이즈 호스트"**)이고 설명은 *"Claude Code 가 채팅에 표시하는 hub|both URL 의 host"* 뿐이라, **"tailscale" 로도 "advertise" 로도 검색되지 않았다**
* depends: Issue425
* 구현 명세:
    - ① `bind_host` — 값별 의미(루프백/LAN/전체)와 *"다른 기기에서 접속이 안 되면 대개 여기가 127.0.0.1 이다 — 열어도 안 되면 짝인 advertise_host 확인"*
    - ② `advertise_host` — *"외부 기기에서 이 hub 를 열 주소. 비워 두면 링크를 만들지 않는다(= 외부 공유 안 함)"* + **【Tailscale 을 쓴다면】** MagicDNS 권장·공식 문서 링크·macOS resolver 주의 + **【Tailscale 설치】** macOS·Linux 설치 명령(사용자 요청: *"설정창의 ? 버튼에 설치 방법 표시"*)
    - ③ ko·en 양쪽 갱신 (parity 테스트 통과 필수)

## Issue425: hub 링크의 호스트가 문서에 하드코딩돼 있다 — host 에서 host 주소를 보낸다 ✅
* 목적: 사용자 지적 — *"설정파일에서 읽는 것 맞나? host 에서도 잘 작동하나?"*. **둘 다 아니었다.** social `daily-digest.md` 가 `<tailnet-host>:9876` 을 **문서에 박아** 두고 있어, host 에서 digest 를 돌리면 **host 큐를 안내해야 할 자리에 host 주소를 보낸다**. Issue420 에서 링크만 `/mq` 로 바꾸고 이 하드코딩은 그대로 답습했다
* depends: Issue420
* 구현 명세:
    - ① `/healthz` 에 **`advertise_host`·`advertise_url`** 추가 — hub 가 자기 공개 주소를 아는 **유일한 주체**다
    - ② 미설정이면 **`null`** 이다 — 빈 문자열이나 `localhost` 로 때우지 않는다. 그럴듯한 값을 지어내면 **열리지 않는 링크를 폰으로 보낸다**
    - ③ social `daily-digest.md` — 하드코딩 제거, `curl /healthz | jq -r '.advertise_url'` 조회로 교체. 비었으면 링크 없이 `/mq-list --all` 폴백

## Issue424: /mq 액션 체계를 "진행 → 완료" 로 — 할 일과 끝난 일에 같은 버튼을 달지 않는다 ✅
* 목적: 사용자 지적 — *"scheduled 인 큐(미완료)는 완료보다 **진행** 버튼이 맞고, 이미 완료된 작업은 완료 대신 **확인**이 맞다. 진행을 누르면 작업을 진행하고, 완료를 누르면 완료 상태로 이동하면 되잖아"*. Issue423 이 상태별로 버튼을 갈랐지만 **착수라는 단계 자체가 없었다**
* depends: Issue423, prj3#Issue473
* 구현 명세:
    - ① `/mq-ack` 허용 action 에 `start` 추가 (prj3#Issue473 이 tick 쪽 소비를 담당)
    - ② 버튼 — 미종결: **[진행][완료][연기][취소]** · `in_progress`: [완료][연기][취소](진행 숨김) · `done_unacked`: **[확인][버림]**
    - ③ 라벨 정정 — `done_unacked` 의 "읽음 확인" → **"확인"**, 미종결의 "완료" 는 종결 의미 유지
    - ④ `in_progress` 배지 스타일 · [진행] 버튼 강조(accent)
    - ⑤ 안내문에 **"진행은 종결이 아니다"** 를 첫 줄에 명시

## Issue423: /mq 의 액션이 "눌러도 아무 일이 없다" — 이름·의미·반영 셋이 어긋났다 ✅
* 목적: Issue420 이 만든 처리 액션을 사용자가 실제로 써 보니 **셋 다 어긋나 있었다**. ⓐ 안내문이 *"처리 버튼"* 이라 쓰는데 그런 버튼이 없다(`처리` 는 컬럼 헤더다) ⓑ `완료` 와 `확인` 이 **비슷한 의미로 둘** 있다 ⓒ **눌러도 목록에서 사라지지 않는다**
* depends: Issue420
* 구현 명세:
    - ① **`aoa-mq-tick.sh --consume-only`** 신설(prj3) — `consume_inbox()` 까지만 태우고 종료. 상태 전이 로직을 **복제하지 않으므로 소유는 여전히 tick 하나**다. 세션 활성 판정(pgrep·tmux)도 건너뛴다 — 통지를 안 하므로 불필요
    - ② `/mq-ack` 가 접수 직후 ①을 **동기 실행**. 실패해도 접수는 끝났으므로 200 을 유지하고 `consumed:false` 로만 알린다
    - ③ **상태별 액션** — `done_unacked` → [읽음 확인][버림] · 그 외 → [완료][연기][취소]. 각 버튼에 결과 상태를 `title` 로 명시
    - ④ 접수 후 `consumed` 면 **`load()` 재조회** — 종결 항목이 목록에서 실제로 빠진다
    - ⑤ 안내문을 액션별 의미 설명으로 교체

## Issue422: R3 가 코드로 집행되지 않는다 — forward 의 AUTOBUMP 기본값이 1 ✅
* 목적: Issue417 이 R3(*"값을 올리는 것은 `deploy` 하나뿐"*)를 [`fpm-gitflow.md`](_doc_arch/fpm-gitflow.md) 에 못 박았으나, [`fpm-sync.sh`](scripts/fpm-sync.sh) 의 `AUTOBUMP` **기본값은 `1` 그대로**였다. **규칙은 문서에만 있고 코드가 반대로 동작**한 것이다
* depends: Issue417
* 구현 명세:
    - ① `"${AUTOBUMP:-1}"` → **`"${AUTOBUMP:-0}"`** — Issue417 ⓐ(배포 단위) 채택이다. R3 를 코드가 집행한다
    - ② `deploy` 는 영향 없음 — 자체 `write_version_files` 로 bump 하고 forward 에는 이미 `AUTOBUMP=0` 을 export 한다(`do_deploy` 449행). 즉 **올리는 경로는 deploy 하나로 좁혀진다**
    - ③ 문서 동반(hook-rules 규칙2) — R4 아래에 *"R3 는 코드로 집행된다"* 를 명시. R4 의 `AUTOBUMP=0` 은 이제 기본 동작이라 따로 걸 필요가 없다
    - ④ VERSION 6곳을 `0.8.0` 으로 재고정(R1·R2)

## Issue420: aoa-mq 전용 관리 페이지 — 목록만 있고 검색·정렬·처리를 할 수 없다 ✅
* 목적: 현재 mq 를 다루는 수단이 셋인데 **어느 것도 "쌓인 것을 훑어보고 처리하는" 용도가 못 된다.** ⓐ 세션 넛지 배너는 건수만 알리고 클릭할 것이 없다 ⓑ tick 이 만드는 `hub_htm_*_b_aoa-mq-ask.htm` 폼은 **그 회차 due 항목만** 담고 세션이 활성이면 아예 안 뜬다 ⓒ `mq_list_*.htm` 은 **리스트 뿐**이라 검색·정렬·처리가 없다. 그 결과 미종결이 8건까지 쌓이고 `ask_count` 가 47회에 이른 항목이 생겼다
* 구현 명세:
    - ① **hub 헤더에 `📮 Aoa-mq` 버튼** — [`services/hub/server.py`](services/hub/server.py) 의 `📋 Projects`([L11358](services/hub/server.py#L11358)) **왼쪽**에 배치
    - ② **`GET /mq`** — 전용 페이지. 서버 내장 template(hub 와 같은 방식)
    - ③ **`GET /mq-data`** — 큐 JSON. `queue/`(미종결) + `queue_done/`(종결, 최근 N)를 함께 반환해 "처리한 것"도 볼 수 있게 한다
    - ④ **필터** — 속성별(status·type·source·bot) + **유저 키워드**(message 전문 검색). 복수 조건 AND
    - ⑤ **정렬** — due·created·ask_count·status 오름/내림
    - ⑥ **처리 액션** — 완료(`confirm`)·연기(`snooze:<days>`)·취소(`dismiss`)·확인(`ack`)·닫기(`defer`)
    - 🔑 **ack 는 기존 `/answer` 를 재사용한다** — `POST /answer?cwd=<큐 소유 cwd>&sid=aoa-mq` · body `[{question:"aoa-mq-ack:<id>:<action>[:<arg>]", answers:[action]}]`. tick 의 `consume_inbox()` 가 그 시그니처를 소비하므로 **새 종결 API 를 만들면 배관이 둘로 갈라진다**
    - ⚠️ 큐 경로는 tick 과 **같은 knob** 을 쓴다 — `AOA_MQ_DIR`(기본 `~/.claude/data/aoa/mq`). 하드코딩하면 prj5 레거시 큐를 보게 될 수 있다
    - ⚠️ 처리 결과는 **즉시 반영되지 않는다**(다음 tick 이 소비) — UI 가 "접수됨"과 "종결됨"을 구분해 표시해야 사용자가 눌렀는데 안 변한다고 오해하지 않는다
    - 검증: 버튼이 `Projects` 왼쪽에 렌더 · `/mq` 가 미종결 8건 표시 · 키워드로 좁혀질 것 · 정렬 동작 · 액션 1건 실행 후 inbox 에 파일 생성 → 다음 tick 에서 종결 확인

## Issue417: 버전이 커밋마다 소비된다 — 릴리스 단위를 표현하지 못한다 ✅
* 목적: 2일간 버전이 **15회** 변경됐다(`v0.6.0` → `0.7.4`, auto-bump 9 + deploy 6). 그중 실제 배포는 6회다. 버전 번호가 *"무엇이 릴리스됐는가"* 를 더 이상 말하지 못하고 **커밋 카운터**에 가까워졌다
* 구현 명세:
    - ① **판정 먼저** — 버전이 표현해야 하는 것이 ⓐ 배포 단위인가 ⓑ 정본 스냅샷인가. ⓐ면 auto-bump 를 걷어내고 `deploy` 만 올린다. ⓑ면 현행이 맞고 대신 **배포 일련번호를 따로** 둔다
    - ② ⓐ 채택 시 — `forward` 의 `AUTOBUMP` 기본값을 0 으로 뒤집는다. ⚠️ 그러면 미러가 정본보다 뒤처진 버전을 달게 되므로, **미러 VERSION 의 의미**(정본 스냅샷 vs 배포본)를 함께 정해야 한다
    - ③ 어느 쪽이든 [`fpm-gitflow.md`](_doc_arch/fpm-gitflow.md) "VERSION 충돌 차단 규칙" 에 **버전이 언제 오르는가**를 명문화 — 지금은 *누가* 올리는지만 있고 *언제* 가 없다
    - ⚠️ 태그(`v*`)와의 관계도 정리 — 현재 tag 는 `deploy` 만 만든다. bump 15회 중 6회만 태그가 있어 **버전과 태그가 1:1이 아니다**
    - 검증: 정책 확정 후 배포 1회를 태워 버전 증가 횟수가 **의도와 일치**할 것 · 6곳(정본·미러·마켓·소비자 2·prj3/5) 버전이 배포 직후 **동시에** 같아질 것

## Issue415: 공개 digest 에 `\1` 리터럴이 새겨진다 — awk 는 replacement 백레퍼런스를 지원하지 않는다 ✅
* 목적: 공개 미러로 나가는 [`Issue_public.md`](Issue_public.md) 에 `Issue{385}(비공개)\1가드로 검사하지만` 같은 **깨진 문자열**이 (여기 `{}` 는 digest 자기치환을 피하려는 표기) 실린다. 공개 산출물이라 그대로 배포되고, 읽는 사람에게는 오타로 보인다
* 구현 명세:
    - ① 캡처가 필요 없는 방식으로 — `index()`+`substr()` 로 토큰을 직접 스캔해 치환하는 awk 함수. 뒤 문자가 `[0-9_]` 면 다른 번호의 일부이므로 건너뛰고, 그 외(문자열 끝 포함)면 `(비공개)` 를 붙인다
    - ② 기존 두 `gsub`(중간·문자열 끝)을 **함수 하나로 통합** — 끝 케이스는 "뒤 문자가 빈 문자열" 로 자연히 처리된다. 두 벌로 두면 한쪽만 고쳐지는 사고가 난다
    - ③ 이미 오염된 `Issue_public.md` 는 digest **재생성**으로 교정(수기 편집 금지 — 생성물이다)
    - 검증: 재생성 후 `Issue_public.md` 에 `\1` **0건** · `Issue{N}(비공개)` 뒤 원문 한 글자가 **보존**될 것 · `Issue{385}` 와 `Issue{3850}` 이 구분될 것(접두 오치환 없음)

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
* 목적: `deploy` 는 `$SRC`(prj1) 브랜치를 Issue385(비공개) 가드로 검사하지만 **`$DST`(미러) 브랜치는 판정하지 않는다.** 비대칭이라 미러가 `develop`·`fix/*` 에 체크아웃돼 있으면 F5-1 미흡수 가드가 **엉뚱한 사유로** 발화해 배포가 중단되고, bump 는 이미 끝난 뒤라 버전 번호만 소비된다
* depends: Issue409
* 구현 명세:
    - ① [`scripts/fpm-sync.sh`](scripts/fpm-sync.sh) `do_forward` 진입부(F5-1 **앞**)에 DST 브랜치 판정 추가. `$DST` 가 `main` 이 아니면 fail-loud `exit 1` + 조치 문구를 `switch main` 으로 명시. 우회는 `FPM_ALLOW_DST_BRANCH=1`
    - ② 집행 등급 **enforce** — Issue385(비공개)(`$SRC` 가드)와 대칭. advisory 경고 금지
    - ③ `sh/check.sh` 에 소비자 브랜치 경고(advisory) 추가 — `$FPM_BASE` 가 `main` 이 아니면 경고
    - 검증: 미러를 임시 브랜치에 두고 `forward` → 새 메시지로 중단 · `main` 복귀 후 정상 통과 · `FPM_ALLOW_DST_BRANCH=1` 우회 동작

## Issue409: fpm 배포 브랜치 이원화 정리 — 미러 상주 `develop` 폐지, 배포본 직접 수정은 조건부 허용 ✅
* 목적: Issue408 은 갈라진 브랜치를 **합치는 것**으로 끝났고 구조는 그대로였다. 배포본을 직접 고치는 습관이 남으면 같은 분기가 반복된다. *"어느 브랜치가 배포 정본인가"* 와 *"배포본 직접 수정을 허용하는가"* 를 판정해 문서에 박는다
* depends: Issue408

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
    - **push 여부와 무관하게 항상 신선도를 대조하고 불일치를 non-zero 로 보고**한다. Issue387(비공개) 의 실패 모드("백업은 있는데 최신이 아니다")를 구조적으로 검출하기 위함
    - ⚠️ 위임 범위 준수: prj3 저장소 **무수정**(읽기 전용 실측만), 원격 push **미실행**(승인 필요 → Issue387(비공개))

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

## Issue238: 원격 브라우저에서 Remote-SSH 연결된 VSCode 에디터 열기 (open-project/open-session 클라이언트측 URI 분기) 🚫
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

