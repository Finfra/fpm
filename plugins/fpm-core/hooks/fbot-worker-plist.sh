#!/usr/bin/env bash
# ⚠️ 글로벌 SCAR — 모든 프로젝트 공유. 즉흥 수정 금지(cwd ≠ ~/.claude 면 Issue.md 등록 후 처리)
#    절차: ~/.claude/rules/global-scar-change-rules.md
# 🔒 집행: passive — 본 스크립트는 생성기다. 등재(launchctl)는 하지 않는다
# 📚 설계 SSOT: ~/.claude/_doc_arch/fbot-arch.md §소유·배포
#    plan: ~/.claude/_doc_work/plan/fbot-s0-worker_plan.md 단계 5 (Issue436_3)
#
# fbot s0 — aoa-memory launchd LaunchAgent plist 생성기 (템플릿 내장, 2배관)
#
#   fbot-worker-plist.sh write [worker|ingest|all]   # plist 생성 (파일 기록, 멱등). 기본 all
#   fbot-worker-plist.sh show  [worker|ingest|all]   # 생성될 내용 출력 (파일 미기록). 기본 all
#   fbot-worker-plist.sh path  [worker|ingest|all]   # plist 절대경로 출력. 기본 all
#
# ## 왜 2배관인가 (2026-08-23 실측)
#
#   worker.py 에는 **적재(ingest) 경로가 없다** — 서브커맨드 choices 는
#   status|run|consolidate|gc|enqueue 뿐이고, run_jobs() 는 kind=='consolidation' 만
#   처리하며 나머지는 "미구현 kind" 로 failed 시킨다. 따라서 `worker.py run` 단독으로는
#   관측 적재가 재개되지 않는다. 적재는 ingest_obs.py 가 별도 진입점으로 소유한다.
#
#     worker  — consolidation enqueue→run  : 잡 원장 생산+소비   (30분 간격)
#     ingest  — homunculus 관측 → learn.db : 적재               (15분 간격)
#
#   적재를 촘촘하게 두는 이유: 적재는 가볍고(읽기+배치 insert), 지연이 곧 학습 공백이다.
#
# ## 왜 python3 직접 호출이 아니라 래퍼인가 (QA 발견 A·C, 2026-08-23)
#
#   A. `worker.py run` 은 pending 잡을 **소비만** 한다. 생산자(enqueue)가 없으면 launchd 가
#      30분마다 "처리 0건" 만 남기고 끝난다 — 배관이 영구 공회전한다
#   C. launchd 리다이렉트 로그에는 시각도 회전도 없다
#
#   그래서 두 plist 모두 [fbot-tick.sh](fbot-tick.sh) 를 부른다. 래퍼가 enqueue→run 연결·
#   python 경로·타임스탬프·1MB 로그 회전을 소유하고, plist 는 **언제 부를지**만 소유한다.
#   plist 의 `AOA_MEMORY_DIR` env 는 그대로 유지한다 — 래퍼가 이 값을 우선 사용한다
#   (래퍼 기본값은 폴백일 뿐이므로 데이터 경로 계약의 소유는 계속 plist 쪽에 남는다).
#
# ⚠️ launchd 는 plist 문자열의 `~`·`$HOME` 을 전개하지 않는다.
#    따라서 모든 경로는 이 스크립트가 셸에서 전개해 **절대경로로 박아 넣는다**.
#    렌더 후 `~`/`$HOME` 잔류를 자체 검사하고, 1건이라도 있으면 fail-loud 로 중단한다.
#
# ⚠️ 생성물(plist)은 repo 밖(~/Library/LaunchAgents/)에 놓인다 — repo 반입 금지
#    (publishable sanitize 의 $HOME 치환이 plist 를 기동 불능으로 만드는 무신호 경로 차단).
#
# ⚠️ 본 스크립트는 launchctl 을 절대 호출하지 않는다. 등재·기동은 별도 단계(plan 6).

set -euo pipefail

# --- 공통 상수 (셸에서 전개 → 절대경로) --------------------------------------

die() { printf 'fbot-worker-plist: %s\n' "$*" >&2; exit 1; }

# 경로 계약 (Issue450) — env 가 정식 설정. 미설정 시 제품 중립 기본(prj5 미클론 머신 대응).
#   생성 시점의 env 가 plist 에 박힌다 — 설치 환경의 실경로가 그대로 고정된다.
AOA_HOME="${AOA_HOME:-${HOME}/.claude/mcp/aoa-memory}"

# 데이터 경로 계약 (fbot-arch §소유·배포 · Issue450) — 데이터는 옮기지 않는다.
#   env 가 있으면 그 위치를, 없으면 제품 중립 기본을 plist 에 박는다.
AOA_MEMORY_DIR="${AOA_MEMORY_DIR:-${HOME}/.claude/data/aoa}"

# 로그 — repo 밖. /tmp 는 재부팅 시 소실되어 fail-loud 근거가 사라지므로 쓰지 않는다
LOG_DIR="${HOME}/Library/Logs/fbot"

LAUNCH_AGENTS="${HOME}/Library/LaunchAgents"

# launchd 가 부르는 단일 진입점 — python 경로·env·로그 타임스탬프·회전을 래퍼가 소유한다
TICK="${HOME}/.claude/hooks/fbot-tick.sh"

# python3 해석 (Issue451 ①) — **생성 시점에 절대경로로 확정**해 plist 에 박는다.
#   launchd 는 셸 프로파일도 PATH 관례도 주지 않는다. 래퍼(fbot-tick.sh)에 탐색 로직이
#   있어도 plist 가 주는 PATH 에 python3 가 없으면 그 탐색이 헛돈다 — 그래서 여기서
#   먼저 풀어 FBOT_PYTHON 으로 넘긴다(래퍼는 ①에서 즉시 끝난다).
#   ⚠️ 해석 실패는 fail-loud. python3 없는 머신에 plist 를 깔면 30분마다 조용히 죽는다.
resolve_python() {
    local c
    if [[ -n "${FBOT_PYTHON:-}" ]]; then printf '%s' "$FBOT_PYTHON"; return 0; fi
    c="$(command -v python3 2>/dev/null || true)"
    [[ -n "$c" ]] && { printf '%s' "$c"; return 0; }
    for c in /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
        [[ -x "$c" ]] && { printf '%s' "$c"; return 0; }
    done
    return 1
}
PY_BIN="$(resolve_python)" || die "python3 미발견 — FBOT_PYTHON 을 절대경로로 지정하고 재실행하라"

# PATH — 해석된 python3 의 디렉토리를 맨 앞에 둔다(관례 경로만 나열하면 pyenv·conda 등
#   비관례 설치를 놓친다). 뒤쪽 관례 목록은 python 외 보조 명령(date·tmux 등)용 폴백.
PATH_BASE="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
PY_DIR="$(dirname "$PY_BIN")"
case ":${PATH_BASE}:" in
    *":${PY_DIR}:"*) PATH_ENV="$PATH_BASE" ;;            # 이미 관례 목록 안 — 중복 금지
    *)               PATH_ENV="${PY_DIR}:${PATH_BASE}" ;;
esac

UNITS=(worker ingest)

# --- 유닛 정의 ---------------------------------------------------------------
# 유닛 하나를 고르면 아래 전역이 채워진다. 유닛별 차이를 여기 한 곳에만 둔다.

select_unit() {
    case "$1" in
        worker)
            U_LABEL="kr.finfra.fbot-worker"
            U_SCRIPT="${AOA_HOME}/worker.py"    # 래퍼가 부르는 실제 대상 (preflight 확인용)
            U_MINUTES=(0 30)                    # 30분 간격 (PM 확정)
            U_LOG_BASE="${LOG_DIR}/aoa-worker"
            ;;
        ingest)
            U_LABEL="kr.finfra.fbot-ingest"
            U_SCRIPT="${AOA_HOME}/ingest_obs.py"
            U_MINUTES=(0 15 30 45)              # 15분 간격 — 적재 지연이 곧 학습 공백
            U_LOG_BASE="${LOG_DIR}/aoa-ingest"
            ;;
        *) die "알 수 없는 유닛: $1 (worker|ingest)" ;;
    esac
    # ProgramArguments — 유닛 구분은 래퍼 인자 하나로 끝난다
    U_PROG=("/bin/bash" "$TICK" "$1")
    U_PLIST="${LAUNCH_AGENTS}/${U_LABEL}.plist"
    U_OUT="${U_LOG_BASE}.out.log"
    U_ERR="${U_LOG_BASE}.err.log"
}

# --- 템플릿 렌더 -------------------------------------------------------------

render() {
    local cal="" argxml="" m a
    for m in "${U_MINUTES[@]}"; do
        cal+=$'\t\t<dict>\n\t\t\t<key>Minute</key>\n\t\t\t<integer>'"${m}"$'</integer>\n\t\t</dict>\n'
    done
    for a in "${U_PROG[@]}"; do
        argxml+=$'\t\t<string>'"${a}"$'</string>\n'
    done

    cat <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>Label</key>
	<string>${U_LABEL}</string>
	<key>ProgramArguments</key>
	<array>
${argxml}	</array>
	<key>WorkingDirectory</key>
	<string>${AOA_HOME}</string>
	<key>EnvironmentVariables</key>
	<dict>
		<key>AOA_MEMORY_DIR</key>
		<string>${AOA_MEMORY_DIR}</string>
		<key>FBOT_PYTHON</key>
		<string>${PY_BIN}</string>
		<key>PATH</key>
		<string>${PATH_ENV}</string>
	</dict>
	<key>StartCalendarInterval</key>
	<array>
${cal}	</array>
	<key>RunAtLoad</key>
	<false/>
	<key>ProcessType</key>
	<string>Background</string>
	<key>LowPriorityIO</key>
	<true/>
	<key>StandardOutPath</key>
	<string>${U_OUT}</string>
	<key>StandardErrorPath</key>
	<string>${U_ERR}</string>
</dict>
</plist>
PLIST
}

# 렌더 결과에 `~` 또는 `$HOME` 이 남아 있으면 launchd 가 전개하지 못해 조용히 죽는다 → 중단
TILDE_RE='(\$HOME|\$\{HOME\}|(^|[[:space:]>"])~/)'
assert_no_tilde() {
    local content="$1"
    if printf '%s' "$content" | grep -nE "$TILDE_RE" >/dev/null; then
        printf '%s' "$content" | grep -nE "$TILDE_RE" >&2
        die "plist 에 미전개 경로(~ 또는 \$HOME)가 남았다 — launchd 는 이를 전개하지 않는다"
    fi
}

preflight() {
    [[ -f "$TICK" ]]     || die "래퍼 부재: ${TICK}"
    [[ -f "$U_SCRIPT" ]] || die "래퍼가 부를 실행 대상 부재: ${U_SCRIPT}"
}

# --- 유닛 단위 동작 ----------------------------------------------------------

unit_show() {
    select_unit "$1"; preflight
    local out; out="$(render)"
    assert_no_tilde "$out"
    printf '%s\n' "$out"
}

unit_write() {
    select_unit "$1"; preflight
    local out; out="$(render)"
    assert_no_tilde "$out"

    mkdir -p "$LOG_DIR"          # StandardOutPath 상위 디렉토리 부재 시 launchd 기동 실패
    mkdir -p "$LAUNCH_AGENTS"

    if [[ -f "$U_PLIST" ]] && printf '%s\n' "$out" | cmp -s - "$U_PLIST"; then
        printf 'unchanged: %s\n' "$U_PLIST"
        return 0
    fi
    printf '%s\n' "$out" > "${U_PLIST}.tmp.$$"
    mv -f "${U_PLIST}.tmp.$$" "$U_PLIST"
    printf 'written: %s\n' "$U_PLIST"
}

unit_path() { select_unit "$1"; printf '%s\n' "$U_PLIST"; }

# --- 디스패치 ----------------------------------------------------------------

expand_target() {
    case "${1:-all}" in
        all)            printf '%s\n' "${UNITS[@]}" ;;
        worker|ingest)  printf '%s\n' "$1" ;;
        *)              die "알 수 없는 대상: $1 (worker|ingest|all)" ;;
    esac
}

action="${1:-}"; target="${2:-all}"
[[ -n "$action" ]] || die "usage: $(basename "$0") {write|show|path} [worker|ingest|all]"

multi=0; [[ "$target" == "all" ]] && multi=1

while read -r u; do
    case "$action" in
        write) unit_write "$u" ;;
        # all 모드에서만 구분자를 넣는다 — 단일 유닛 출력은 순수 XML 로 유지해
        # `show <unit> | diff - <plist>` 검증이 그대로 성립하게 한다
        show)  [[ $multi -eq 1 ]] && printf '<!-- ===== %s ===== -->\n' "$u"
               unit_show "$u" ;;
        path)  unit_path "$u" ;;
        *)     die "usage: $(basename "$0") {write|show|path} [worker|ingest|all]" ;;
    esac
done < <(expand_target "$target")
