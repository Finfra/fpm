#!/usr/bin/env bash
# fpm-consumer-propagate-payload.sh — 소비자 1대 전파 원격 페이로드 (Issue607)
#
# 소비자 머신에서 ssh 표준입력으로 실행된다 — 드라이버 scripts/fpm-consumer-propagate.sh 가 보낸다.
# 순서: ① clone 갱신 ② plugin 재설치 ③ 상주 hub 재기동 ④ healthz 200 확인.
#   ⚠️ 갱신만 하고 재기동하지 않으면 구버전 hub 가 계속 서빙한다(v0.8.4 1차 출고 실측: jma pid 가 전날 기동분).
#   ⚠️ 같은 버전 재출고는 `plugin update` 가 «already at the latest» 로 무효 — 재설치(uninstall→install)가 표준이다.
# 출력 계약: `FPMR key=value` 줄. rc 0 = healthz 200 · rc 1 = 그 외(거짓 성공 금지).
# 환경: FPM_PROP_NO_INSTALL=1 clone·plugin 단계 생략 · FPM_PROP_RESTART_CMD 재기동 명령 대체(테스트) ·
#       FPM_PROP_PORT(기본 9876) · FPM_PROP_WAIT(healthz 대기 초, 기본 20) · FPM_CLONE(기본 ~/_git/fpm)
# 사용: ssh <host> 'bash -s' < scripts/fpm-consumer-propagate-payload.sh
set -uo pipefail
PORT="${FPM_PROP_PORT:-${1:-9876}}"
WAIT="${FPM_PROP_WAIT:-20}"
FPM_DIR="${FPM_CLONE:-$HOME/_git/fpm}"
PLUGIN="${FPM_PLUGIN:-fpm-core@f-claude-plugins}"
MKT="${FPM_MKT:-f-claude-plugins}"
export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"
echo "FPMR host=$(hostname) os=$(uname -s)"

# ① clone — 소비자 hub 는 clone 의 services/hub/server.py 를 돌린다
if [ "${FPM_PROP_NO_INSTALL:-0}" != 1 ]; then
    if git -C "$FPM_DIR" pull --ff-only >/dev/null 2>&1; then echo "FPMR clone_pull=ok"; else echo "FPMR clone_pull=FAIL"; fi
    # ② plugin 재설치 — claude 를 못 찾으면 «생략» 을 성공으로 말하지 않는다
    if command -v claude >/dev/null 2>&1; then
        claude plugin marketplace update "$MKT" >/dev/null 2>&1 || true
        claude plugin uninstall "$PLUGIN" >/dev/null 2>&1 || true
        if claude plugin install "$PLUGIN" >/dev/null 2>&1; then echo "FPMR plugin_install=ok"; else echo "FPMR plugin_install=FAIL"; fi
    else
        echo "FPMR plugin_install=SKIPPED(claude 미발견)"
    fi
fi
echo "FPMR clone_version=$(tr -d '\r' < "$FPM_DIR/VERSION" 2>/dev/null || echo ?)"

# ③ hub 재기동 — 인터프리터는 clone 의 sh/fbot-python.sh(해석 단일 지점)가 고른다 (Issue642)
#   종전 `command -v python3` 는 fg1 22.04 에서 3.14 가 깔려 있어도 맨 python3(3.10)로 hub 를 띄웠다.
#   HUB_PY_ARGV[0] 은 절대경로로 편다 — nohup·wmic 은 PATH 가 다른 자식에서 돈다.
resolve_hub_python() {
    HUB_PY_ARGV=()
    if [ -f "$FPM_DIR/sh/fbot-python.sh" ]; then
        # shellcheck source=/dev/null
        . "$FPM_DIR/sh/fbot-python.sh"
        if ! fbot_resolve_python; then
            echo "FPMR hub_python=FAIL(${FBOT_PY_WARN:-후보 전멸 ${FBOT_PY_REJECT:-}})"
            return 1
        fi
        HUB_PY_ARGV=("${FBOT_PY_ARGV[@]}")
        echo "FPMR hub_python=$FBOT_PY_DISPLAY v=${FBOT_PY_VERSION:-?} path=$FBOT_PY_PATH"
        [ -n "${FBOT_PY_WARN:-}" ] && echo "FPMR hub_python_warn=$FBOT_PY_WARN"
    else   # fbot-python.sh 가 없는 옛 clone
        local p; p="$(command -v python3 || command -v python)" || { echo "FPMR hub_python=FAIL(python 미발견)"; return 1; }
        HUB_PY_ARGV=("$p")
        echo "FPMR hub_python=$p v=? path=$p (fbot-python.sh 없음)"
    fi
    HUB_PY_ARGV[0]="$(command -v "${HUB_PY_ARGV[0]}" 2>/dev/null || printf '%s' "${HUB_PY_ARGV[0]}")"
}
# systemd 유닛 인터프리터 고정 — 유닛은 머신 소유(fg1 은 수기 작성)라 덮지 않고 drop-in 으로 ExecStart 만 바꾼다.
#   Issue637_3 fg1 실측: 유닛 `ExecStart=/usr/bin/python3` 때문에 위 해석과 무관하게 hub 가 3.10.12 로 떴다.
pin_hub_unit() {
    local dir="$HOME/.config/systemd/user/fpm-hub.service.d" f want
    f="$dir/10-fpm-python.conf"
    want="$(printf '[Service]\nExecStart=\nExecStart=%s %s\n' "${HUB_PY_ARGV[*]}" "$FPM_DIR/services/hub/server.py")"
    if [ "$(cat "$f" 2>/dev/null)" != "$want" ]; then
        mkdir -p "$dir" && printf '%s\n' "$want" > "$f" || { echo "FPMR hub_unit_python=FAIL(drop-in 쓰기)"; return 1; }
        systemctl --user daemon-reload
    fi
    echo "FPMR hub_unit_python=${HUB_PY_ARGV[*]}"
}
restart_hub() {
    resolve_hub_python || return 1
    if [ -n "${FPM_PROP_RESTART_CMD:-}" ]; then eval "$FPM_PROP_RESTART_CMD"; return; fi
    case "$(uname -s)" in
        MINGW*|MSYS*|CYGWIN*)   # Windows — taskkill 후 wmic 로 기동(PowerShell Start-Process 는 ssh 종료와 함께 죽는다)
            local pid
            pid=$(netstat -ano 2>/dev/null | tr -d '\r' | awk -v p=":$PORT" '$2 ~ p"$" && /LISTENING/ {print $NF; exit}')
            [ -n "$pid" ] && taskkill //PID "$pid" //F >/dev/null 2>&1
            sleep 1
            local py srv; srv="$(cygpath -w "$FPM_DIR/services/hub/server.py" 2>/dev/null || echo "$FPM_DIR/services/hub/server.py")"
            py="$(cygpath -w "${HUB_PY_ARGV[0]}" 2>/dev/null || echo "${HUB_PY_ARGV[0]}")"
            wmic process call create "$py ${HUB_PY_ARGV[*]:1} $srv" >/dev/null 2>&1 ;;
        *)
            if command -v systemctl >/dev/null 2>&1 && systemctl --user cat fpm-hub >/dev/null 2>&1; then
                pin_hub_unit || return 1
                systemctl --user restart fpm-hub
            else   # 유닛이 없으면 pid 종료 후 절대경로 기동
                local old
                old=$(pgrep -f 'services/hub/server\.py' 2>/dev/null | head -1)
                [ -n "$old" ] && kill "$old" 2>/dev/null
                sleep 1
                ( cd "$FPM_DIR" && nohup "${HUB_PY_ARGV[@]}" "$FPM_DIR/services/hub/server.py" >/tmp/fpm-hub-propagate.log 2>&1 & )
            fi ;;
    esac
}
if restart_hub; then echo "FPMR hub_restart=issued"; else echo "FPMR hub_restart=FAIL"; fi

# ④ healthz — 응답할 때까지 대기. 끝내 무응답이면 rc 1
code() { curl -s -o /dev/null -m 5 -w '%{http_code}' "http://127.0.0.1:$PORT$1" 2>/dev/null || echo 000; }
hz=000; i=0
while [ "$i" -lt "$WAIT" ]; do
    hz=$(code /healthz); [ "$hz" = 200 ] && break
    sleep 1; i=$((i + 1))
done
bd=$(code /boards)
echo "FPMR healthz=$hz boards=$bd"
[ "$hz" = 200 ]
