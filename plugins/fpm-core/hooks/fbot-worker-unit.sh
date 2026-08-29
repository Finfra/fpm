#!/usr/bin/env bash
# ⚠️ 글로벌 SCAR — 모든 프로젝트 공유. 즉흥 수정 금지(cwd ≠ ~/.claude 면 Issue.md 등록 후 처리)
#    절차: ~/.claude/rules/global-scar-change-rules.md
# 🔒 집행: passive — 본 스크립트는 생성기다. 등재(systemctl)는 하지 않는다
# 📚 설계 SSOT: ~/.claude/_doc_arch/fbot-arch.md §소유·배포   (Issue454)
#
# fbot s0 — systemd --user timer 생성기 (Linux 상주 배관). launchd 판의 형제.
#
#   fbot-worker-unit.sh write [worker|ingest|all]   # unit 생성 (파일 기록, 멱등). 기본 all
#   fbot-worker-unit.sh show  [worker|ingest|all]   # 생성될 내용 출력 (파일 미기록)
#   fbot-worker-unit.sh path  [worker|ingest|all]   # unit 절대경로 출력 (.service, .timer)
#
# ## 왜 systemd --user timer 인가 (fg1 실측 2026-08-27, Issue454)
#
#   ⑴ `loginctl show-user` → **Linger=yes** — 로그아웃 후에도 user manager 가 유지되므로
#      상주 tick 이 끊기지 않는다.
#   ⑵ 로그 회수 — `journalctl --user -u fbot-worker` 로 tick 별 exit code·stdout·소요시간을
#      한 번에 얻는다. cron 은 실행 사실만 남고 **stdout 이 유실**된다.
#   cron 도 살아 있으나 관측성에서 밀렸다 — 폴백 후보로만 남긴다.
#
# ## 🔴 함정 2건 — fg1 실측으로 확인된 것 (Issue454)
#
#   ① **TZ 가 `Etc/UTC` 다.** macOS launchd 는 로컬 TZ(Asia/Seoul)라 그대로 두면 **양쪽
#      동작이 9시간 갈린다** — 주1회 매뉴얼 개정(월요일 첫 tick)·1일 1회 daily report
#      게이트가 직접 영향받는다.
#      ⚠️ 타이머 발화 자체는 무관하다 — `*:00,30` 같은 **간격 스케줄**은 UTC/KST 가 정확히
#         9시간(정시 배수) 차이라 같은 벽시계 분에 뜬다. 어긋나는 것은 tick **안의**
#         `date +%u`·`date +%Y-%m-%d` 게이트다.
#      ⚠️ systemd 249(fg1 실측)는 `OnCalendar` 의 타임존 접미사를 지원하지 않는다(v252+).
#         그래서 TZ 는 **service 의 `Environment=TZ=`** 로 준다. fbot-tick.sh 도 같은 값을
#         자체 기본값으로 갖는다(이중 방어 — 어느 쪽이 빠져도 KST 로 판정).
#   ② **user 세션 env 가 로그인 셸과 다르다.** `~/.zshrc` 도 PATH 관례도 없다.
#      python3 은 **생성 시점에 절대경로로 확정**해 `FBOT_PYTHON` 으로 박는다(launchd 판과
#      동일 규약). `daemon-reload`+`enable --now` 를 빠뜨리면 **조용히 안 돈다** — 본
#      스크립트는 등재하지 않으므로 호출측이 반드시 그 2줄을 실행해야 한다(usage 에 명시).
#
# ⚠️ systemd 는 unit 문자열의 `~`·`$HOME` 을 전개하지 않는다(`%h` 지정자는 별개 문법).
#    launchd 판과 같은 이유로 모든 경로를 셸에서 전개해 절대경로로 박고, 렌더 후 잔류를
#    자체 검사해 1건이라도 있으면 fail-loud 로 중단한다.
#
# ⚠️ 생성물은 repo 밖(~/.config/systemd/user/)에 놓인다 — repo 반입 금지.

set -euo pipefail

die() { printf 'fbot-worker-unit: %s\n' "$*" >&2; exit 1; }

# 플랫폼 가드 — launchd 머신에서 잘못 부르면 즉시 알린다(무신호 생성 차단)
[[ "$(uname -s)" == "Linux" ]] || die "Linux 전용 생성기다 (현재 $(uname -s)) — macOS 는 fbot-worker-plist.sh, 판정은 fbot-schedule.sh 가 한다"

# 경로 계약 (Issue450) — env 가 정식 설정. 미설정 시 제품 중립 기본.
AOA_HOME="${AOA_HOME:-${HOME}/.claude/mcp/aoa-memory}"
AOA_MEMORY_DIR="${AOA_MEMORY_DIR:-${HOME}/.claude/data/aoa}"

UNIT_DIR="${XDG_CONFIG_HOME:-${HOME}/.config}/systemd/user"

# tick 래퍼 위치 — 자기 자신의 형제다. 소비자는 플러그인 번들 경로로 받으므로
#   `$HOME/.claude/hooks` 하드코딩은 성립하지 않는다(Issue451 과 같은 교훈).
TICK="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)/fbot-tick.sh"

# 스케줄 판정 TZ — 함정 ①. launchd(로컬 TZ=Asia/Seoul)와 동작을 일치시킨다.
FBOT_TZ="${FBOT_TZ:-Asia/Seoul}"

# python3 해석 — 생성 시점에 절대경로 확정. 실패는 fail-loud.
resolve_python() {
    local c
    if [[ -n "${FBOT_PYTHON:-}" ]]; then printf '%s' "$FBOT_PYTHON"; return 0; fi
    c="$(command -v python3 2>/dev/null || true)"
    [[ -n "$c" ]] && { printf '%s' "$c"; return 0; }
    for c in /usr/bin/python3 /usr/local/bin/python3 /opt/homebrew/bin/python3; do
        [[ -x "$c" ]] && { printf '%s' "$c"; return 0; }
    done
    return 1
}
PY_BIN="$(resolve_python)" || die "python3 미발견 — FBOT_PYTHON 을 절대경로로 지정하고 재실행하라"

PATH_BASE="/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
PY_DIR="$(dirname "$PY_BIN")"
case ":${PATH_BASE}:" in
    *":${PY_DIR}:"*) PATH_ENV="$PATH_BASE" ;;
    *)               PATH_ENV="${PY_DIR}:${PATH_BASE}" ;;
esac

UNITS=(worker ingest)

# --- 유닛 정의 ---------------------------------------------------------------

select_unit() {
    case "$1" in
        worker)
            U_NAME="fbot-worker"
            U_SCRIPT="${AOA_HOME}/worker.py"
            U_ONCAL="*-*-* *:00,30:00"           # 30분 간격 (launchd 판과 동일)
            U_DESC="fbot worker tick — consolidation enqueue→run·reap·sweep·리포트 게이트"
            ;;
        ingest)
            U_NAME="fbot-ingest"
            U_SCRIPT="${AOA_HOME}/ingest_obs.py"
            U_ONCAL="*-*-* *:00,15,30,45:00"     # 15분 간격 — 적재 지연이 곧 학습 공백
            U_DESC="fbot ingest tick — homunculus 관측 → learn.db 적재"
            ;;
        *) die "알 수 없는 유닛: $1 (worker|ingest)" ;;
    esac
    U_SERVICE="${UNIT_DIR}/${U_NAME}.service"
    U_TIMER="${UNIT_DIR}/${U_NAME}.timer"
}

# --- 템플릿 렌더 -------------------------------------------------------------
# stdout·stderr 는 journald 가 받는다 — 파일 리다이렉트를 두지 않는다.
#   `journalctl --user -u <unit>` 하나로 tick 별 exit code·stdout·소요시간이 모두 나온다.
#   (launchd 판이 파일로 받는 것은 launchd 에 journald 상당물이 없기 때문이다)

render_service() {
    cat <<UNIT
[Unit]
Description=${U_DESC}
Documentation=file://${HOME}/.claude/_doc_arch/fbot-arch.md

[Service]
Type=oneshot
WorkingDirectory=${AOA_HOME}
Environment=AOA_MEMORY_DIR=${AOA_MEMORY_DIR}
Environment=AOA_HOME=${AOA_HOME}
Environment=FBOT_PYTHON=${PY_BIN}
Environment=PATH=${PATH_ENV}
Environment=TZ=${FBOT_TZ}
ExecStart=/bin/bash ${TICK} ${U_NAME#fbot-}
Nice=10
IOSchedulingClass=idle
TimeoutStartSec=900
UNIT
}

render_timer() {
    cat <<UNIT
[Unit]
Description=${U_DESC} (timer)

[Timer]
OnCalendar=${U_ONCAL}
Persistent=true
AccuracySec=1min
Unit=${U_NAME}.service

[Install]
WantedBy=timers.target
UNIT
}

# 렌더 결과에 `~`·`$HOME` 이 남으면 systemd 가 전개하지 못해 조용히 죽는다 → 중단
TILDE_RE='(\$HOME|\$\{HOME\}|(^|[[:space:]=])~/)'
assert_no_tilde() {
    local content="$1"
    if printf '%s' "$content" | grep -nE "$TILDE_RE" >/dev/null; then
        printf '%s' "$content" | grep -nE "$TILDE_RE" >&2
        die "unit 에 미전개 경로(~ 또는 \$HOME)가 남았다 — systemd 는 이를 전개하지 않는다"
    fi
}

preflight() {
    [[ -f "$TICK" ]]     || die "래퍼 부재: ${TICK}"
    [[ -f "$U_SCRIPT" ]] || die "래퍼가 부를 실행 대상 부재: ${U_SCRIPT}"
}

# --- 유닛 단위 동작 ----------------------------------------------------------

unit_show() {
    select_unit "$1"; preflight
    local s t; s="$(render_service)"; t="$(render_timer)"
    assert_no_tilde "$s"; assert_no_tilde "$t"
    printf '# ===== %s.service =====\n%s\n\n# ===== %s.timer =====\n%s\n' \
        "$U_NAME" "$s" "$U_NAME" "$t"
}

write_one() {   # $1=경로 $2=내용
    if [[ -f "$1" ]] && printf '%s\n' "$2" | cmp -s - "$1"; then
        printf 'unchanged: %s\n' "$1"; return 0
    fi
    printf '%s\n' "$2" > "$1.tmp.$$"
    mv -f "$1.tmp.$$" "$1"
    printf 'written: %s\n' "$1"
}

unit_write() {
    select_unit "$1"; preflight
    local s t; s="$(render_service)"; t="$(render_timer)"
    assert_no_tilde "$s"; assert_no_tilde "$t"
    mkdir -p "$UNIT_DIR"
    write_one "$U_SERVICE" "$s"
    write_one "$U_TIMER"   "$t"
}

unit_path() { select_unit "$1"; printf '%s\n%s\n' "$U_SERVICE" "$U_TIMER"; }

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

while read -r u; do
    case "$action" in
        write) unit_write "$u" ;;
        show)  unit_show  "$u" ;;
        path)  unit_path  "$u" ;;
        *)     die "usage: $(basename "$0") {write|show|path} [worker|ingest|all]" ;;
    esac
done < <(expand_target "$target")

# write 시에만 등재 2줄을 안내한다 — 본 스크립트는 systemctl 을 부르지 않는다(함정 ②).
if [[ "$action" == "write" ]]; then
    cat >&2 <<'HINT'

# ⚠️ 생성만 했다. 아래 2줄을 실행하지 않으면 조용히 안 돈다 (Issue454 함정 ②)
systemctl --user daemon-reload
systemctl --user enable --now fbot-worker.timer fbot-ingest.timer
HINT
fi
