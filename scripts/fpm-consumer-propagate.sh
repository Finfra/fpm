#!/usr/bin/env bash
# fpm-consumer-propagate.sh — 소비자 3대 전파 표준 명령: clone 갱신·plugin 재설치·hub 재기동·healthz (Issue607)
#
# 왜 — 전파가 plugin·clone 만 갱신하면 상주 hub 는 구버전 코드로 계속 돈다(v0.8.4 1차 출고: jma·fg1 hub 가 갱신 전 pid).
#   런북 S6 의 수동 표를 명령 하나로 고정한다. 검증은 이어서 `scripts/fpm-ship-verify.sh --tag <태그>` 가 맡는다.
#   갱신 주체는 jm4 다 — 대상 머신이 스스로 pull 하지 않는다(_doc_arch/fpm-consumer-install.md).
#
# 사용: bash scripts/fpm-consumer-propagate.sh --tag v0.8.3 [--host jma] [--host fg1] [--host jpc1:win] [--dry-run]
#   --host 생략 시 기본 3대. `:win` = 원격 셸이 cmd 라 Git Bash 를 명시 호출한다
#   --dry-run   ssh 를 부르지 않고 머신별로 무엇을 할지만 출력한다
#   증거: _doc_work/_release/v<ver>/evidence/propagate-<host>.log
# exit: 0 전 머신 healthz 200 · 1 하나라도 실패 · 2 인자 오류
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
PAYLOAD="$HERE/fpm-consumer-propagate-payload.sh"
WIN_BASH='"C:\Program Files\Git\bin\bash.exe"'

TAG=""; PORT=9876; DRY=0; OUT=""; HOSTS=()
while [ $# -gt 0 ]; do
    case "$1" in
        --tag) TAG="${2:-}"; shift 2 ;;
        --host) HOSTS+=("${2:-}"); shift 2 ;;
        --port) PORT="${2:-}"; shift 2 ;;
        --out) OUT="${2:-}"; shift 2 ;;
        --dry-run) DRY=1; shift ;;
        -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
        *) echo "❌ 알 수 없는 인자: $1" >&2; exit 2 ;;
    esac
done
[ -n "$TAG" ] || { echo "❌ --tag 필수 (ex) --tag v0.8.3)" >&2; exit 2; }
[ -f "$PAYLOAD" ] || { echo "❌ 페이로드 없음: $PAYLOAD" >&2; exit 2; }
VER="${TAG#v}"
[ ${#HOSTS[@]} -gt 0 ] || HOSTS=(jma fg1 jpc1:win)

hub_step() {   # 머신 종류별 재기동 방식 — 페이로드의 분기와 같다
    case "$1" in
        fg1)  echo "systemctl --user restart fpm-hub" ;;
        jpc1) echo "taskkill 9876 리스너 → wmic process call create (Git Bash 표준입력)" ;;
        *)    echo "기존 pid 종료 → nohup <python3 절대경로> ~/_git/fpm/services/hub/server.py (유닛 없을 때)" ;;
    esac
}

if [ "$DRY" = 1 ]; then
    echo "▶ consumer-propagate (dry-run) — $TAG · 머신 ${HOSTS[*]}"
    for s in "${HOSTS[@]}"; do
        h="${s%%:*}"
        echo "- $h: ① git -C ~/_git/fpm pull --ff-only → ② plugin marketplace update·uninstall·install fpm-core@f-claude-plugins → ③ hub 재기동: $(hub_step "$h") → ④ /healthz 200 대기(무응답이면 FAIL)"
    done
    exit 0
fi

OUT="${OUT:-$REPO/_doc_work/_release/v$VER}"
EV="$OUT/evidence"; mkdir -p "$EV"
run_host() {
    local spec="$1" h="${1%%:*}" log="$EV/propagate-${1%%:*}.log" rc
    if [ "$spec" != "$h" ] && [ "${spec#*:}" = "win" ]; then
        ssh "$h" "$WIN_BASH -l -s -- $PORT" < "$PAYLOAD" 2>&1 | grep -v -E "post-quantum|store now|upgraded|fpm.sh: No such" > "$log"
        rc=${PIPESTATUS[0]}
    else
        ssh -x "$h" "export PATH=\$HOME/.local/bin:/opt/homebrew/bin:\$PATH; bash -s -- $PORT" < "$PAYLOAD" 2>&1 | grep -v -E "post-quantum|store now|upgraded" > "$log"
        rc=${PIPESTATUS[0]}
    fi
    echo "FPMR ssh_rc=$rc" >> "$log"
    echo "$rc" > "$log.rc"
}
echo "▶ consumer-propagate — $TAG · 머신 ${HOSTS[*]} · 증거 $EV"
for s in "${HOSTS[@]}"; do run_host "$s" & done
wait
fail=0
for s in "${HOSTS[@]}"; do
    h="${s%%:*}"; log="$EV/propagate-$h.log"; rc="$(cat "$log.rc" 2>/dev/null || echo 1)"; rm -f "$log.rc"
    line="$(grep -h '^FPMR' "$log" 2>/dev/null | tr '\n' ' ')"
    if [ "$rc" = 0 ]; then echo "✅ $h — $line"; else echo "❌ $h (rc=$rc) — $line"; fail=1; fi
done
[ "$fail" = 0 ] && echo "다음: bash scripts/fpm-ship-verify.sh --tag $TAG" || echo "FAIL 머신이 있다 — 출고를 «완료» 로 닫지 않는다 (Issue607·609)"
exit "$fail"
