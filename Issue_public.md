---
name: Issue_public
description: "fpm 공개용 이슈 근거 요약 — Issue.md 에서 제목·목적·구현 명세만 추출한 파생본"
generator: scripts/fpm-issue-digest.sh
source_sha: 7e5dc50c5a6ff455a9d0c4b1bb3e29c947b50f589980f39437ecf4c758fddc76
---

# 안내

본 문서는 자동 생성 파생본이다. 원본 이슈 트래커(`Issue.md`)는 개인정보가 포함되어 공개하지
않으며, 여기에는 **코드 변경의 근거를 이해하는 데 필요한 필드만** 추출되어 있다.

* 포함: 이슈 제목 · `목적` · `구현 명세` · `depends`
* 제외: 상세 · Walkthrough · 진행 결과 · 커밋 해시 · plan/task 경로

소스 코드 주석의 `(Issue{N})` 참조는 아래 항목에서 찾을 수 있다. 직접 편집하지 말 것 —
`scripts/fpm-issue-digest.sh` 가 덮어쓴다.

# 이슈 근거

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
* 목적: <private-project> 세션이 렌더한 [hub_htm_20260728_010327_a_rfp-plan.htm](/Users/user/work/<private-project>/_doc_work/htm/hub_htm_20260728_010327_a_rfp-plan.htm) 이 `/htm-doc` 에서 `{"error": "not a registered htm doc"}` 403 dead link 가 됐다. 파일·파일명 규약·서버 모두 정상인데 registry 에만 없다.
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

