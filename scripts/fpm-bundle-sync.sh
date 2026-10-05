#!/bin/bash
# fpm-bundle-sync.sh — plugins/fpm-core 번들을 라이브 SCAR·서버 코드와 동기 (Issue291)
#
# 배경: 번들이 라이브 대비 ~100개 이슈 정체된 채 VERSION 은 최신을 주장하는 상태가 발생했다
#   (2026-07-19 실측: 번들 server.py 6,838줄 vs 라이브 10,537줄, 마지막 반영 Issue193).
#   버전이 내용을 보증하지 못하면 플러그인 사용자는 수개월치 수정이 빠진 hub 를 받는다.
#
# 원칙:
#   1. 라이브가 원본, 번들은 배포 스냅샷. 단방향(라이브 → 번들)만 수행한다.
#   2. **번들 전용 파일은 절대 삭제하지 않는다** (hooks.json·fpm-browser-open.sh·fpm-cdf.md·
#      fpm-hub-server.md·vscode-ext/ 등 배포 전용 자산). rsync --delete 금지.
#   3. 개인 환경 파일은 반입하지 않는다 (data/hub_setting.yml 등). 공개 안전장치는
#      forward 스냅샷 단계(fpm-guard/fpm-sanitize)가 담당하나, 여기서도 최소 반입 원칙을 지킨다.
#   6. **미커밋 변경 위에는 쓰지 않는다** (Issue519). 이 스크립트는 라이브(prj3)를 원본으로
#      복사하므로, 목적지에 다른 세션의 in-flight 작업이 있으면 rsync/cp 가 그것을 통째로
#      덮는다 — 커밋 전이라 **되돌릴 수단이 없다**(2026-09-20 실발생: `mcp/aoa-mq/` 소실).
#      목적지가 git dirty(미커밋·미추적)면 그 파일만 건너뛰고 fail-loud 로 알린다.
#   4. **services/hub 는 더 이상 동기 대상이 아니다** (Issue465, 2026-09-01). 번들이 유일
#      실체이고 라이브 `services/hub` 는 그것을 가리키는 상대 심볼릭 링크다 — 복사할 사본이
#      없으니 갈라질 수도 없다. 여기서는 링크 구조만 fail-loud 로 확인한다.
#      (종전: server.py 만 옮기고 의존 i18n.py·assets/ 를 빠뜨리면 import 에서 죽으므로
#       디렉토리 전체를 rsync 했다. 단일 실체가 되면서 그 위험 자체가 사라졌다.)
#   5. 목적지는 번들만이 아니다 (prj3#Issue436_3, fbot 2배관) — SCAR 는 plugins/fpm-core 로,
#      MCP 서버 코드는 repo top-level `mcp/<유닛>/` 로 간다. 후자는 **하위 디렉토리 고정**이며
#      기존 `mcp/server.py`(fpm MCP)를 덮거나 지우지 않는다.
#
# 사용:
#   scripts/fpm-bundle-sync.sh                  # 동기 실행
#   scripts/fpm-bundle-sync.sh --check          # 표류 검사만 (변경 없음, 표류 시 exit 1)
#   scripts/fpm-bundle-sync.sh --only mcp/aoa-mq  # 목적지를 이 경로 아래로 한정 (Issue519)
#
# exit: 0=정상 · 1=표류(--check)·동기 실패·dirty 로 건너뛴 대상 있음 · 2=인자 오류
#
# 설계 SSOT: _doc_arch/htm-lifecycle-design.md 는 htm 수명주기, 본 스크립트는 Issue291.

set -u

REPO="$(cd "$(dirname "$0")/.." && pwd)"
BUNDLE="$REPO/plugins/fpm-core"
GLOBAL="$HOME/.claude"
CHECK=0
ONLY=""

cd "$REPO" || exit 1
drift=0
changed=0
blocked=0

say() { printf '[bundle-sync] %s\n' "$*"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --check)  CHECK=1 ;;
    --only)   shift; ONLY="${1:-}" ;;
    --only=*) ONLY="${1#--only=}" ;;
    *) say "알 수 없는 인자: $1 (사용: [--check] [--only <repo 상대 경로>])"; exit 2 ;;
  esac
  shift
done
ONLY="${ONLY%/}"

# --- 원본 = 라이브 HEAD (Issue591) ---
#   번들에 싣는 것은 prj3 **HEAD 판**이다(미커밋 사본 반출 금지). 종전엔 라이브 **작업트리**를 읽어
#   판정이 갈렸다 — 다른 세션이 prj3 를 편집 중이면 번들 == HEAD 인데도 `--check` 가 DRIFT 를 내
#   deploy 재생목록 `bundle-in-sync` 가 떨어졌고(2026-10-03 실측 16/17), 동기를 돌리면 그 미완성
#   편집을 번들로 반출했다. 라이브가 git repo 면 대상 경로만 `git archive HEAD` 로 떠서 원본으로 쓴다.
#   라이브가 git repo 가 아니면(소비자 머신·샌드박스) 종전대로 작업트리가 원본이다.
LIVE_WT="$GLOBAL"
SNAP=""
LIVE_PATHS=(hooks commands agents skills/fpm-pm-do skills/issue-map skills/fbot-icon skills/fbot-scout
            data/decision-authority.yml data/fbot mcp/aoa-memory mcp/aoa-mq)
# 기준 ref (Issue598) — 기본 HEAD. R1(`RELEASE_TEST_R1=1`)에서는 **동기 시점에 박아 둔 핀**을 쓴다.
#   번들은 «동기한 순간의 prj3 HEAD» 사본이다. R1 이 판정을 «지금의 prj3 HEAD» 와 하면, 후보를 고정한 뒤에
#   prj3 가 커밋될 때마다 후보와 무관하게 DRIFT 가 난다(2026-10-05 R1 재실패: db91a07e 동기 → b80d5d34 등 라이브
#   커밋으로 재표류). 핀 = 후보 커밋에 실려 있는 prj3 커밋이므로 후보가 고정되면 판정도 고정된다.
#   라이브가 더 앞섰다는 사실은 숨기지 않는다 — 아래 live_ahead_report 가 고지한다(판정 제외).
#   핀은 전체 동기(부분 동기 아님)가 성공했을 때만 쓴다. 명시 override: FPM_BUNDLE_LIVE_REF.
PIN_FILE="$REPO/data/releases/bundle-live-ref"
LIVE_REF="${FPM_BUNDLE_LIVE_REF:-}"
if [ -z "$LIVE_REF" ] && [ -n "${RELEASE_TEST_R1:-}" ] && [ -s "$PIN_FILE" ]; then
  LIVE_REF="$(head -1 "$PIN_FILE" | tr -d '[:space:]')"
fi
LIVE_REF="${LIVE_REF:-HEAD}"
LIVE_HEAD_SHA=""
live_top="$(git -C "$GLOBAL" rev-parse --show-toplevel 2>/dev/null)"
if [ -n "$live_top" ] && [ "$(cd "$live_top" && pwd -P)" = "$(cd "$GLOBAL" && pwd -P)" ]; then
  LIVE_HEAD_SHA="$(git -C "$GLOBAL" rev-parse --verify -q HEAD 2>/dev/null)"
  if ! git -C "$GLOBAL" rev-parse --verify -q "${LIVE_REF}^{commit}" >/dev/null 2>&1; then
    say "⚠️ 기준 ref '$LIVE_REF' 를 라이브에서 찾지 못했다 — HEAD 로 대체"
    LIVE_REF="HEAD"
  fi
  in_head=()
  for p in "${LIVE_PATHS[@]}"; do
    git -C "$GLOBAL" cat-file -e "$LIVE_REF:$p" 2>/dev/null && in_head+=("$p")
  done
  SNAP="$(mktemp -d "${TMPDIR:-/tmp}/bundle-src.XXXXXX")"
  if [ "${#in_head[@]}" -gt 0 ] && ! git -C "$GLOBAL" archive "$LIVE_REF" -- "${in_head[@]}" | tar -x -C "$SNAP"; then
    say "🚨 라이브 HEAD 스냅샷 추출 실패 ($GLOBAL) — 작업트리로 대체하지 않는다"
    rm -rf "$SNAP"; exit 1
  fi
  GLOBAL="$SNAP"
fi
#   ⚠️ 스냅샷의 mtime 은 추출 시각이다 — 디렉토리 rsync(skills·mcp)는 `--checksum` 으로 **내용**을 비교한다.
#      크기+mtime 기본 비교로 두면 내용이 같은 파일까지 전부 표류로 센다(실측: 30건 오탐).

# --- dirty 가드 (Issue519) ---
#   목적지에 미커밋 변경이 있으면 «라이브 원본» 으로 덮지 않는다. 이 스크립트가 복사하는
#   것은 남의 저작물(prj3 라이브)이고, 목적지의 미커밋 변경은 **지금 다른 세션이 쓰고 있는
#   작업**이다. 덮는 순간 git 에도 없어 복구 경로가 0 이다.
#   `-uall` 로 미추적 파일을 전개한다 — 축약된 `?? dir/` 만 보면 그 안의 신규 파일이
#   보호 대상에서 빠진다(신규 파일이야말로 덮이면 흔적 없이 사라진다).
DIRTY_LIST="$(mktemp)"
trap 'rm -f "$DIRTY_LIST"; [ -n "$SNAP" ] && rm -rf "$SNAP"' EXIT
git status --porcelain -uall 2>/dev/null | sed -e 's/^...//' -e 's/^.* -> //' -e 's/^"//' -e 's/"$//' > "$DIRTY_LIST"

is_dirty() {  # $1=repo 상대 경로
  grep -qxF -- "$1" "$DIRTY_LIST"
}

in_scope() {  # $1=repo 상대 경로 — --only 미지정이면 전부 통과
  [ -z "$ONLY" ] && return 0
  case "$1" in
    "$ONLY"|"$ONLY"/*) return 0 ;;
  esac
  case "$ONLY" in
    "$1"/*) return 0 ;;   # 목적지가 --only 의 상위 디렉토리 — 내부에서 다시 거른다
  esac
  return 1
}

# 디렉토리 단위 동기(rsync)에서 그 안의 dirty 파일만 제외한다.
#   ⚠️ bash 3.2(macOS 기본) + `set -u` 에서 빈 배열 전개는 unbound 오류다 —
#      호출측은 반드시 `${DIRTY_EX[@]+"${DIRTY_EX[@]}"}` 형태로 쓴다.
dirty_ex() {  # $1=목적지 디렉토리(절대)
  local base="${1#$REPO/}" rel
  base="${base%/}"
  DIRTY_EX=()
  while IFS= read -r rel; do
    case "$rel" in
      "$base"/*)
        DIRTY_EX+=(--exclude="${rel#$base/}")
        blocked=$((blocked + 1))
        say "⏭ SKIP(dirty) $rel — 미커밋 변경 위로 덮지 않는다"
        ;;
    esac
  done < "$DIRTY_LIST"
}

# 이 실행이 **새로 만든** 파일을 기억한다 (Issue561).
#   무결성 매니페스트(7단계)는 `git ls-files` 추적 파일만 싣는다 — 동기가 만든 신규 파일은 아직
#   미추적이라 매니페스트에서 빠지고, 커밋 때 pre-commit 무결성 게이트가 «ADDED» 로 거부한다
#   (2026-09-28 lib 3종 반입에서 실발생). 목록을 생성기에 명시로 넘겨(FPM_MANIFEST_EXTRA) 싣는다.
#   ⚠️ 공유 인덱스를 건드리지 않는다 — intent-to-add(`git add -N`)로 풀면 issue-tx 임시 인덱스 커밋
#      뒤에 공유 인덱스에 i-t-a 가 남고, 다른 세션의 맨 `git commit` 이 그 파일을 **삭제로 커밋**한다
#      (실측). 커밋에 실을 파일은 끝에 고지하고, 싣는 것은 커밋하는 사람이 한다.
NEW_FILES=""
track_new() {  # $1=repo 상대 경로
  NEW_FILES="${NEW_FILES}$1
"
}

# 파일 1건 동기 (번들에 이미 있는 것만 — 신규 파일은 의도적 편입이므로 수동)
sync_file() {  # $1=번들경로 $2=라이브경로
  local dst="$1" src="$2" rel="${1#$REPO/}"
  [ -f "$src" ] || return 0          # 라이브에 없음 = 번들 전용 → 보존
  in_scope "$rel" || return 0        # Issue519 — --only 범위 밖
  cmp -s "$dst" "$src" && return 0   # 동일
  if is_dirty "$rel"; then           # Issue519 — 미커밋 변경 위로 덮지 않는다
    blocked=$((blocked + 1))
    say "⏭ SKIP(dirty) $rel — 미커밋 변경 위로 덮지 않는다"
    return 0
  fi
  drift=$((drift + 1))
  if [ "$CHECK" -eq 1 ]; then
    say "DRIFT ${dst#$REPO/}"
  else
    local new=0
    [ -e "$dst" ] || new=1
    cp "$src" "$dst" && changed=$((changed + 1))
    if [ "$new" -eq 1 ]; then track_new "$rel"; fi   # Issue561
  fi
}

sync_dir_by_name() {  # $1=번들 디렉토리 $2=라이브 디렉토리
  local bdir="$1" ldir="$2" f
  [ -d "$bdir" ] || return 0
  for f in "$bdir"/*; do
    [ -f "$f" ] || continue
    sync_file "$f" "$ldir/$(basename "$f")"
  done
}

# --- 1. services/hub — **동기 대상이 아니다. 실체가 하나뿐이다** (Issue465) ---
#   종전엔 라이브 `services/hub/` 를 번들로 rsync 해 **두 벌**을 유지했고, 한쪽만 고치면
#   조용히 갈라졌다(특히 번들만 고친 경우 — 다음 sync 가 그 수정을 덮어 없앤다).
#   지금은 번들이 유일 실체이고 `services/hub` 는 그것을 가리키는 **상대 심볼릭 링크**다.
#   복사할 것이 없으므로 여기서는 **구조가 유지되는지**만 본다 — 링크가 실디렉토리로
#   되돌아가는 순간 2원화가 부활하기 때문이다.
#   ⚠️ 왜 반대 방향(번들이 링크)이 아닌가: `sh/gen-integrity-manifest.sh` 의 walk 는
#      `os.walk`(followlinks 기본 False) + `os.path.islink` skip 이고, write 모드 tracked
#      필터는 `git ls-files` 를 읽는다. git 은 링크를 **한 엔트리**(mode 120000)로 저장하므로
#      번들을 링크로 만들면 hub 39개 파일이 매니페스트에서 통째로 빠지고, prj20 vendor
#      (`rsync -a`)는 번들 밖을 가리키는 링크를 그대로 복사해 **플러그인이 깨진다**.
#   ⚠️ 미러(fpm)에는 링크가 아니라 **실파일**이 나간다 — `scripts/fpm-sync.sh` do_forward 가
#      sanitize 직전에 편다. Windows 소비자는 심볼릭 링크를 못 받는다
#      (_doc_arch/windows-port.md W2 = 실측 FAIL).
#   설계 SSOT: _doc_arch/fpm-sync-deploy.md "hub 실체 단일화"
RSYNC_EX=(--exclude='__pycache__/' --exclude='.pytest_cache/' --exclude='.vscode/' --exclude='.DS_Store')
HUB_LINK="$REPO/services/hub"
HUB_LINK_WANT="../plugins/fpm-core/services/hub"
if [ ! -L "$HUB_LINK" ] || [ "$(readlink "$HUB_LINK")" != "$HUB_LINK_WANT" ]; then
  say "🚨 services/hub 가 '$HUB_LINK_WANT' 심볼릭 링크가 아니다 — hub 2원화 부활"
  say "   조치: rm -rf services/hub && ln -s $HUB_LINK_WANT services/hub"
  exit 1
fi
if [ ! -f "$BUNDLE/services/hub/server.py" ]; then
  say "🚨 유일 실체 $BUNDLE/services/hub/server.py 부재 — 링크가 허공을 가리킨다"
  exit 1
fi

# --- 2. hooks / commands / agents — 이름 일치분만 ---
#   fbot 훅(fbot-*.py|sh · dispatch-session{start,end}.sh, prj3#Issue436_3)은 라이브와 번들의
#   파일명이 같아 아래 이름 일치 스윕이 그대로 수집한다 — 별도 매핑을 두지 않는다.
#   신규 fbot 훅을 추가할 때는 번들에 1회 수동 seed 해야 이 스윕의 사정권에 들어온다(원칙: 신규 편입은 수동).
sync_dir_by_name "$BUNDLE/hooks"    "$GLOBAL/hooks"
sync_dir_by_name "$BUNDLE/hooks/lib" "$GLOBAL/hooks/lib"   # prj3#Issue545 — 번들 훅이 source 하는 라이브러리

#   번들 훅의 lib 의존 동반 (Issue561). 위 이름 일치 스윕은 번들에 **이미 있는** lib 만 갱신한다.
#   «신규 파일은 수동 편입» 원칙이 훅의 의존까지 막아, 훅은 새 판으로 올라가는데 그 훅이
#   `$(dirname "$0")/lib/<x>` 로 부르는 lib 은 번들에 없는 상태가 생겼다 — 소비자 머신에서 조용히
#   실패한다(2026-09-28 실측: fbot-checkout.sh→session-end.py · fbot-writeguard.sh→shcmd.py 는
#   `|| exit 0` 으로 fail-open · fpm-ask-question-guard.sh→decision-question.py).
#   편입된 훅의 의존은 새 편입 결정이 아니다 — 훅을 실은 순간 이미 결정된 것이라 자동으로 싣는다.
#   참조는 **라이브 판**에서 읽는다(--check 에서도 동기 후의 번들 = 라이브). lib 의 lib 은 전이로 따라간다.
#   라이브에도 없는 참조는 만들지 않고, 번들에 없는 훅은 스캔하지 않는다(훅 편입은 여전히 수동).
lib_refs() {  # $1=파일 → 참조하는 lib 파일명(공백 구분)
  grep -o 'lib/[A-Za-z0-9_.-]*\.\(py\|sh\)' "$1" 2>/dev/null | sed 's|^lib/||' | sort -u | tr '\n' ' '
}
sync_hook_lib_deps() {
  local f live name queue="" seen=" " guard=0
  for f in "$BUNDLE"/hooks/* "$BUNDLE"/hooks/lib/*; do
    [ -f "$f" ] || continue
    live="$GLOBAL/hooks/${f#$BUNDLE/hooks/}"
    [ -f "$live" ] || live="$f"             # 번들 전용 훅은 자기 판을 본다
    queue="$queue $(lib_refs "$live")"
  done
  set -f                                     # 이름 목록 분해 시 glob 전개 금지
  while [ -n "${queue// /}" ] && [ "$guard" -lt 500 ]; do
    guard=$((guard + 1))
    set -- $queue; name="$1"; shift; queue="$*"
    case "$seen" in *" $name "*) continue ;; esac
    seen="$seen$name "
    [ -f "$GLOBAL/hooks/lib/$name" ] || continue          # 라이브에도 없음 → 만들지 않는다
    [ -f "$BUNDLE/hooks/lib/$name" ] || sync_file "$BUNDLE/hooks/lib/$name" "$GLOBAL/hooks/lib/$name"
    queue="$queue $(lib_refs "$GLOBAL/hooks/lib/$name")"  # 전이
  done
  set +f
}
sync_hook_lib_deps
sync_dir_by_name "$BUNDLE/commands" "$GLOBAL/commands"
sync_dir_by_name "$BUNDLE/agents"   "$GLOBAL/agents"

# --- 3. skills — 번들 이름과 라이브 이름이 다른 케이스가 있어 명시 매핑 ---
#   fpm-cdf ← prj1 .claude/skills/cdf, fpm-pm ← prj1 .claude/skills/pm,
#   fpm-pm-do ← 글로벌 ~/.claude/skills/fpm-pm-do,
#   fpm-issue-map ← 글로벌 ~/.claude/skills/issue-map (Issue338)
#     번들 hub server.py 가 Issue_map.htm 을 serve 하는데 생성기가 빠져 있어
#     플러그인 전용 설치(fg1)에서 /issue-map 이 영구 404 였다.
sync_skill() {  # $1=번들 스킬명 $2=라이브 디렉토리
  local dst="$BUNDLE/skills/$1" src="$2"
  [ -d "$dst" ] && [ -d "$src" ] || return 0
  in_scope "${dst#$REPO/}" || return 0   # Issue519
  local flag=""; [ "$CHECK" -eq 1 ] && flag="-n"
  local n out p
  dirty_ex "$dst"                        # Issue519 — 그 안의 미커밋 파일만 제외
  out=$(rsync -a --checksum $flag --itemize-changes --exclude='__pycache__/' --exclude='.DS_Store' ${DIRTY_EX[@]+"${DIRTY_EX[@]}"} "$src/" "$dst/")
  n=$(printf '%s\n' "$out" | grep -c '^[>c]')
  [ "$n" -gt 0 ] || return 0
  if [ "$CHECK" -eq 0 ]; then            # Issue561 — rsync 가 새로 만든 파일(`>f+++++++`)도 기억
    #   파이프 뒤 while 은 서브셸이라 NEW_FILES 갱신이 사라진다 — here-string 으로 받는다
    while IFS= read -r p; do
      [ -n "$p" ] && track_new "${dst#$REPO/}/$p"
    done <<< "$(printf '%s\n' "$out" | sed -n 's/^>f+++++++ //p')"
  fi
  if [ "$CHECK" -eq 1 ]; then drift=$((drift + n)); say "DRIFT skills/$1 ($n)"
  else changed=$((changed + n)); say "skills/$1 $n 파일 갱신"; fi
}
sync_skill fpm-pm-do "$GLOBAL/skills/fpm-pm-do"
sync_skill fpm-pm    "$REPO/.claude/skills/pm"
sync_skill fpm-cdf   "$REPO/.claude/skills/cdf"
sync_skill fpm-issue-map "$GLOBAL/skills/issue-map"
#   fbot-icon 은 예외적으로 번들명 = 라이브명이다 (prj3#Issue436_3).
#   `fbot-` 자체가 이미 독립 네임스페이스라 fpm- 접두가 중복이고, SKILL.md 본문이
#   `~/.claude/skills/fbot-icon/scripts/fbot-icon-gen.py` 를 문자열로 참조해 이름을 바꾸면 문서가 거짓이 된다.
sync_skill fbot-icon "$GLOBAL/skills/fbot-icon"
#   fbot-scout 도 같은 예외 계열 — 번들명 = 라이브명 (prj3#Issue480, 위 fbot-icon 근거 동일)
sync_skill fbot-scout "$GLOBAL/skills/fbot-scout"

# --- 4. 런타임 데이터 (i18n catalog + 설치 템플릿) ---
#   locales 부재 시 hub UI 가 번역 키 그대로 노출되고 test_i18n_parity 가 깨진다.
#   hub_setting.yml(개인 환경값)은 반입 금지 — org 템플릿만.
if in_scope "${BUNDLE#$REPO/}/data/locales"; then
  dirty_ex "$BUNDLE/data/locales"        # Issue519
  if [ "$CHECK" -eq 1 ]; then
    n=$(rsync -an --itemize-changes ${DIRTY_EX[@]+"${DIRTY_EX[@]}"} "$REPO/data/locales/" "$BUNDLE/data/locales/" 2>/dev/null | grep -c '^[>c]')
    [ "$n" -gt 0 ] && { drift=$((drift + n)); say "DRIFT data/locales ($n)"; }
  else
    mkdir -p "$BUNDLE/data/locales"
    n=$(rsync -a --itemize-changes ${DIRTY_EX[@]+"${DIRTY_EX[@]}"} "$REPO/data/locales/" "$BUNDLE/data/locales/" | grep -c '^[>c]')
    [ "$n" -gt 0 ] && { changed=$((changed + n)); say "data/locales $n 파일 갱신"; }
  fi
fi
sync_file "$BUNDLE/data/hub_setting_org.yml" "$REPO/data/hub_setting_org.yml"

#   결정 권한 정책 (Issue566, prj3#Issue756). 아래 mcp/aoa-mq 의 등록 helper 가 `[컨펌]` 마다 읽고,
#   부재면 fail-loud 로 거부한다 — helper 만 배송되면 소비자 머신의 `[컨펌]` 이 **전건** 막힌다.
#   번들이 아니라 repo 템플릿 자리로 보낸다: helper 가 읽는 곳은 `~/.claude/data/` 이고, 그 자리에
#   놓는 주체는 sh/fbot-bootstrap.sh(비파괴 seed)다. aoa-policy.default.yml 과 같은 경로(Issue449).
#   ⚠️ helper(mcp/aoa-mq)와 **같은 커밋**으로 나가야 한다 — 한쪽만 나간 커밋이 곧 이 결함이다.
sync_file "$REPO/data/template/decision-authority.yml" "$GLOBAL/data/decision-authority.yml"

#   fbot 데이터 자산 (매뉴얼 + 아이콘 카탈로그, prj3#Issue436_3 — 매뉴얼 수는 카탈로그를 따른다).
#   ⚠️ 여기서 rsync 를 쓰지 않는 것이 의도다 — icons/ 에는 `{role|bot_id}.svg` 생성물이 함께 있고
#      그것은 결정론 재생성물이라 배포 대상이 아니다. 이름 일치 스윕이면 번들에 seed 한
#      catalog.yml 만 따라오고 SVG 는 구조적으로 못 들어온다(제외 규칙을 따로 관리할 필요가 없다).
sync_dir_by_name "$BUNDLE/data/fbot/manuals" "$GLOBAL/data/fbot/manuals"
sync_dir_by_name "$BUNDLE/data/fbot/icons"   "$GLOBAL/data/fbot/icons"
#   조직 선언·매뉴얼 참조 (Issue572, prj3#Issue757). 종전엔 `org/` 를 아예 보지 않아 번들의 본사 조직·
#   조직 템플릿이 옛 역할명(`taskmgr`)에 머물렀다 — 소비자는 설치하는 순간 이미 폐기된 조직을 받았다.
#   번들에 **이미 있는** 본사·템플릿·ref 만 따라간다(신규 편입은 여전히 수동).
#   ⚠️ 사용자 prj 인스턴스(`org/<N>.yml`)는 스윕하지 않는다 — 조직은 그 머신이 선언한다. 번들의 인스턴스는
#      prj3#Issue559 편입분이고 여기서 갱신할 대상이 아니다(공개 경계 판단은 별건).
sync_file        "$BUNDLE/data/fbot/org/_hq.yml"    "$GLOBAL/data/fbot/org/_hq.yml"
sync_dir_by_name "$BUNDLE/data/fbot/org/_template"  "$GLOBAL/data/fbot/org/_template"
sync_dir_by_name "$BUNDLE/data/fbot/manuals/ref"    "$GLOBAL/data/fbot/manuals/ref"

# --- 5. mcp — 라이브 MCP 서버 코드 (fbot 2배관 ②, prj3#Issue436_3) ---
#   목적지가 **번들 밖 repo top-level** 인 첫 사례다. MCP 서버는 플러그인 SCAR 가 아니라
#   `claude mcp` 등록 대상이라 fpm `mcp/server.py` 와 같은 자리(repo `mcp/`)를 쓴다.
#
#   ⚠️ **하위 디렉토리 고정** — `$REPO/mcp/` 자체를 rsync 목적지로 삼으면 기존
#      `mcp/server.py`·`mcp/README.md`(fpm MCP)가 사정권에 들어온다. 반드시 `mcp/<유닛>/`
#      까지 내려서 동기하고, --delete 는 쓰지 않는다(번들 원칙 2 와 같은 이유).
#   ⚠️ 데이터는 코드가 아니다 — learn.db·큐 파일은 `data/aoa` 소관이며 이 경로로 오지 않는다.
#      그래도 오배치가 조용히 반입되지 않도록 *.db/*.log 를 명시 제외한다.
MCP_EX=(--exclude='__pycache__/' --exclude='.pytest_cache/' --exclude='.DS_Store' --exclude='*.db' --exclude='*.log')
sync_mcp_unit() {  # $1=유닛명 — $GLOBAL/mcp/$1 → $REPO/mcp/$1
  local name="$1" src="$GLOBAL/mcp/$1" dst="$REPO/mcp/$1" flag="" n
  [ -d "$src" ] || return 0        # 라이브에 없음 = 아직 수렴 전 → no-op
  in_scope "mcp/$name" || return 0 # Issue519
  if [ "$CHECK" -eq 1 ]; then flag="-n"; else mkdir -p "$dst"; fi
  dirty_ex "$dst"                  # Issue519 — 실발생 지점이 정확히 여기다
  n=$(rsync -a --checksum $flag --itemize-changes "${MCP_EX[@]}" ${DIRTY_EX[@]+"${DIRTY_EX[@]}"} "$src/" "$dst/" | grep -c '^[>c]')
  [ "$n" -gt 0 ] || return 0
  if [ "$CHECK" -eq 1 ]; then drift=$((drift + n)); say "DRIFT mcp/$name ($n)"
  else changed=$((changed + n)); say "mcp/$name $n 파일 갱신"; fi
}
sync_mcp_unit aoa-memory
sync_mcp_unit aoa-mq

# --- 6. 실행 권한 (cp 는 mode 를 보존하지 않음) ---
#   hooks/*.py 도 포함한다 — fbot 훅은 파이썬 실행체이고 직접 호출되는 경로가 있다.
if [ "$CHECK" -eq 0 ]; then
  for f in "$BUNDLE"/hooks/*.sh "$BUNDLE"/hooks/*.py "$BUNDLE"/agents/*.sh; do
    [ -f "$f" ] && [ ! -x "$f" ] && chmod +x "$f"
  done
fi

# --- 7. 무결성 매니페스트 재생성 (Issue479) ---
#   왜 여기인가: 종전 재생성 지점은 **배포 경로뿐**이었다(publish-scar.sh · fpm-sync.sh
#   do_deploy/do_forward). 그래서 *번들만 고치고 커밋하는 경로* 가 매니페스트를 stale 로
#   남겼고, `sh/check.sh` 는 2026-09-01 이래 상시 FAIL 이었는데 **아무도 몰랐다**
#   (release-check.sh 호출처가 0건이라 - prj1#Issue478 결손2). 재생성을 *배포* 가 아니라
#   **번들이 바뀌는 지점** 에 붙여 재발을 없앤다.
#
#   drift 가 있을 때만 쓴다 — 무조건 write 하면 mcp/ 만 바뀐 실행(매니페스트 대상 밖)에서도
#   generated_at·git_sha 가 갱신되어 의미 없는 diff 가 커밋에 섞인다.
#   `changed` 와 무관하게 항상 검사한다 — 손으로 번들을 고친 뒤 sync 를 돌린 경우
#   (changed=0 인데 매니페스트는 stale)가 정확히 이 이슈의 재발 경로다.
#   ⚠️ **부분 동기에서는 재생성하지 않는다** (Issue519). dirty 로 건너뛴 대상이 있거나
#      `--only` 로 범위를 좁힌 실행은 «번들 = 라이브» 가 아니다. 그 상태의 해시를 배포
#      기준선으로 쓰면 미동기분을 **정상으로 봉인**한다 — 매니페스트가 잡으라는 표류가
#      정확히 그것이다. 전체 동기를 마친 뒤 다시 돌리면 된다.
GEN="$REPO/sh/gen-integrity-manifest.sh"
#   Issue561 — 이 실행이 새로 만든 번들 파일(아직 미추적)을 생성기에 명시로 넘긴다(번들 상대 경로).
BUNDLE_REL="${BUNDLE#$REPO/}"
export FPM_MANIFEST_EXTRA="$(printf '%s' "$NEW_FILES" | sed -n "s|^$BUNDLE_REL/||p")"
if [ "$blocked" -gt 0 ] || [ -n "$ONLY" ]; then
  say "↷ 부분 동기 — 무결성 매니페스트 재생성을 건너뛴다"
  say "   전체 동기 후: bash sh/gen-integrity-manifest.sh"
elif [ -f "$GEN" ]; then
  if bash "$GEN" --check >/dev/null 2>&1; then
    :   # 일치 — 할 일 없음
  elif [ "$CHECK" -eq 1 ]; then
    drift=$((drift + 1)); say "DRIFT plugins/fpm-core/.fpm-integrity.json (매니페스트 미갱신)"
  elif bash "$GEN" >/dev/null 2>&1; then
    changed=$((changed + 1)); say "무결성 매니페스트 재생성"
  else
    say "⚠️ 무결성 매니페스트 재생성 실패 — 'bash sh/gen-integrity-manifest.sh' 로 원인 확인"
    exit 1
  fi
fi

# --- 핀 기록 (Issue598) — 전체 동기가 성공한 실행만 «이 번들 = prj3@HEAD» 를 박는다 ---
if [ "$CHECK" -eq 0 ] && [ -n "$SNAP" ] && [ -n "$LIVE_HEAD_SHA" ] && [ "$LIVE_REF" = "HEAD" ] \
   && [ "$blocked" -eq 0 ] && [ -z "$ONLY" ]; then
  mkdir -p "$(dirname "$PIN_FILE")"
  if [ "$(cat "$PIN_FILE" 2>/dev/null)" != "$LIVE_HEAD_SHA" ]; then
    printf '%s\n' "$LIVE_HEAD_SHA" > "$PIN_FILE"
    say "📌 핀 기록: data/releases/bundle-live-ref = prj3@${LIVE_HEAD_SHA:0:8} — 동기 결과와 함께 커밋할 것"
  fi
fi

live_ahead_report() {  # 핀 기준 판정일 때 라이브가 얼마나 앞섰는지 고지(판정 제외)
  [ -n "$SNAP" ] && [ -n "$LIVE_HEAD_SHA" ] || return 0
  local live_full pin_full n
  live_full="$LIVE_HEAD_SHA"; pin_full="$(git -C "$LIVE_WT" rev-parse --verify -q "${LIVE_REF}^{commit}" 2>/dev/null)"
  [ -n "$pin_full" ] && [ "$pin_full" != "$live_full" ] || return 0
  n="$(git -C "$LIVE_WT" rev-list --count "$pin_full..$live_full" 2>/dev/null)"
  say "ℹ️ 핀 기준(prj3@${pin_full:0:8}) 판정 — 라이브 HEAD 는 ${n:-?} 커밋 앞섰다(후보 판정 제외·다음 동기 때 반영)"
}
live_ahead_report

# --- 결과 ---
blocked_report() {  # Issue519 — 건너뛴 대상이 있으면 조용히 끝내지 않는다
  [ "$blocked" -gt 0 ] || return 0
  say "🚨 미커밋 변경 $blocked 건을 건너뛰었다 — 그만큼 번들이 라이브와 갈라진 채 남는다"
  say "   조치: 해당 경로를 커밋(또는 되돌림)한 뒤 재실행 · 범위 한정은 '--only <경로>'"
  return 1
}

live_wip_report() {  # Issue591 — HEAD 기준으로 뺀 라이브 미커밋분을 조용히 묻지 않는다(판정에는 영향 없음)
  [ -n "$SNAP" ] || return 0
  local wip n
  wip="$(git -C "$LIVE_WT" status --porcelain -uall -- "${LIVE_PATHS[@]}" 2>/dev/null | sed 's/^...//')"
  n="$(printf '%s' "$wip" | grep -c .)"
  [ "$n" -gt 0 ] || return 0
  say "ℹ️ 라이브 미커밋 $n 건은 원본에서 제외했다 — 번들은 prj3 HEAD 판 기준 (반출하려면 prj3 커밋 후 재실행)"
  printf '%s\n' "$wip" | head -5 | while IFS= read -r p; do say "   · $p"; done
  [ "$n" -gt 5 ] && say "   · … 외 $((n - 5)) 건"
  return 0
}
live_wip_report

if [ "$CHECK" -eq 1 ]; then
  rc=0
  blocked_report || rc=1
  if [ "$drift" -gt 0 ]; then
    say "표류 $drift 건 — 'scripts/fpm-bundle-sync.sh' 실행 필요"
    rc=1
  fi
  [ "$rc" -eq 0 ] && say "표류 없음 (번들 = 라이브${SNAP:+ ${LIVE_REF}})"
  exit "$rc"
fi

if [ "$changed" -gt 0 ]; then
  say "총 $changed 파일 동기 완료 — 커밋 전 테스트 권장:"
  say "  (cd plugins/fpm-core/services/hub && for t in test_*.py; do python3 \$t >/dev/null || echo FAIL \$t; done)"
else
  say "변경 없음 (이미 최신)"
fi
if [ -n "$NEW_FILES" ]; then   # Issue561 — 새로 만든 파일은 미추적이다. 커밋에 빠지면 매니페스트와 갈라진다
  say "📎 신규 $(printf '%s' "$NEW_FILES" | grep -c .) 파일 — 커밋에 함께 실을 것:"
  printf '%s' "$NEW_FILES" | while IFS= read -r p; do [ -n "$p" ] && say "   + $p"; done
  #   Issue579 — 번들 hooks/ 신규는 인벤토리 선언도 필요하다(Issue561 lib 3종이 선언 없이 반입됐다)
  if printf '%s' "$NEW_FILES" | grep -q "^${BUNDLE_REL}/hooks/"; then
    say "   ↳ hooks/ 신규는 data/scar-manifest.yml payloads.plugin.scar.hooks[] 에도 선언 — 확인: bash sh/scar-hooks-check.sh"
  fi
fi
blocked_report || exit 1
exit 0
