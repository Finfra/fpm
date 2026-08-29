#!/usr/bin/env bash
# ⚠️ 글로벌 SCAR — 모든 프로젝트 공유. 즉흥 수정 금지(cwd ≠ ~/.claude 면 Issue.md 등록 후 처리)
#    절차: ~/.claude/rules/global-scar-change-rules.md
# 🔒 집행: passive — 생성기 진입점이다. 등재(launchctl·systemctl)는 하지 않는다
# 📚 설계 SSOT: ~/.claude/_doc_arch/fbot-arch.md §소유·배포   (Issue454 ③)
#
# fbot s0 — 상주 배관 생성기 **단일 진입점**. 플랫폼 판정을 여기 한 곳에만 둔다.
#
#   fbot-schedule.sh write   [worker|ingest|all]   # 스케줄 유닛 생성 (멱등). 기본 all
#   fbot-schedule.sh show    [worker|ingest|all]   # 생성될 내용 출력
#   fbot-schedule.sh path    [worker|ingest|all]   # 유닛 절대경로 출력
#   fbot-schedule.sh backend                       # 선택될 백엔드 이름만 출력
#
# ## 왜 진입점을 하나 더 두는가 (Issue454 ③)
#
#   호출측(설치 스크립트·문서·사람)이 **플랫폼을 알 필요가 없어야 한다**. 지금까지는
#   `fbot-worker-plist.sh` 가 곧 진입점이라 이름부터 launchd 전용이었고, 그래서 Linux 에는
#   상주 배관이 통째로 없었다(fg1 실측 fbot 스케줄 0건).
#
#   ⚠️ **백엔드 스크립트를 통합하지 않았다.** plist 와 systemd unit 은 문법·로그 수집
#      방식(파일 리다이렉트 vs journald)·env 전달이 전부 달라, 한 파일에 합치면 분기가
#      본문을 덮는다. 대신 **계약을 같게** 두고(write|show|path, 멱등, 절대경로 박기,
#      fail-loud 잔류 검사) 판정만 여기서 한다.
#      부수 효과로 **macOS 경로가 한 글자도 바뀌지 않는다** — jm4 무회귀가 구조적으로 보장된다.

set -euo pipefail

die() { printf 'fbot-schedule: %s\n' "$*" >&2; exit 1; }

HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"

# 플랫폼 판정 — 단일 지점. FBOT_SCHED_BACKEND 로 강제 지정 가능(테스트·특수 환경).
resolve_backend() {
    case "${FBOT_SCHED_BACKEND:-}" in
        launchd|systemd) printf '%s' "$FBOT_SCHED_BACKEND"; return 0 ;;
        "")              ;;
        *)               die "알 수 없는 백엔드 지정: ${FBOT_SCHED_BACKEND} (launchd|systemd)" ;;
    esac
    case "$(uname -s)" in
        Darwin) printf 'launchd' ;;
        Linux)  printf 'systemd' ;;
        *)      die "미지원 플랫폼: $(uname -s) — launchd(macOS)·systemd(Linux) 만 지원한다" ;;
    esac
}

BACKEND="$(resolve_backend)"
case "$BACKEND" in
    launchd) GEN="${HERE}/fbot-worker-plist.sh" ;;
    systemd) GEN="${HERE}/fbot-worker-unit.sh"  ;;
esac

action="${1:-}"
[[ -n "$action" ]] || die "usage: $(basename "$0") {write|show|path|backend} [worker|ingest|all]"

if [[ "$action" == "backend" ]]; then
    printf '%s\n' "$BACKEND"; exit 0
fi

# systemd 백엔드는 user manager 가 실제로 살아 있어야 의미가 있다 — 없으면 fail-loud.
#   ⚠️ 여기서 조용히 cron 으로 폴백하지 않는다. 폴백은 관측성 손실(stdout 유실)을
#      동반하므로 **사람이 알고 고르는 결정**이어야 한다(Issue454 ②는 폴백 후보로만 남겼다).
if [[ "$BACKEND" == "systemd" && "$action" == "write" ]]; then
    systemctl --user show-environment >/dev/null 2>&1 \
        || die "systemd --user 미가용 — 'loginctl enable-linger \$USER' 후 재로그인하거나 cron 배선을 사람이 선택하라"
fi

[[ -x "$GEN" ]] || die "백엔드 생성기 부재·비실행: ${GEN}"
exec "$GEN" "$@"
