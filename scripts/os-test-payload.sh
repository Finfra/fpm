#!/usr/bin/env bash
# os-test-payload.sh — Issue637_2·637_3 OS 구현 테스트 원격 페이로드 (zero-base → GitHub 태그 clean clone 설치·동작)
# 사용: ssh <host> 'bash -s -- <tag> <stamp>' < os-test-payload.sh   (Windows: Git Bash -l -s)
#       구동기 scripts/os-test-ctl.sh clear <host> 가 이 파일을 보낸 뒤 **항상** os-test-restore-payload.sh 로 복귀한다 (Issue652)
# 출력: `FPMT key=value` 줄 = 판정 재료. 상세 로그는 ~/fpm-os-test/<stamp>/ 에 남긴다.
# ⚠️ 이 페이로드는 비우기만 한다 — 복귀는 하지 않는다. 단독으로 돌렸다면 끝난 뒤 반드시 복귀 페이로드를 돌릴 것
#    (복귀 수단: ~/claude-backup-<stamp>.tar.gz · ~/fpm-local-<stamp>.tar.gz · ~/_git/fpm.bak-<stamp>).
set -uo pipefail
TAG="${1:?tag}"; STAMP="${2:?stamp}"
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
OUT="$HOME/fpm-os-test/$STAMP"; mkdir -p "$OUT"
FPM="$HOME/_git/fpm"
t() { echo "FPMT $*"; echo "FPMT $*" >> "$OUT/fpmt.txt"; }
# 새 대화형 쉘이 조용히 뜨는가 (Issue653) — fpm 블록이 stderr 에 경고·오류를 내면 쉘을 열 때마다 보인다.
# 구 dotfile 의 alias v/z 와 fpm 런처가 겹쳐 «⚠️ fpm: alias …» 가 새 쉘마다 떴다. 출력: 경고가 난 쉘만 "zsh:2,bash:1" (없으면 빈 문자열)
shell_startup_warn() {
  local sh n out="" T=""
  command -v timeout >/dev/null 2>&1 && T="timeout 30"
  for sh in zsh bash; do
    command -v "$sh" >/dev/null 2>&1 || continue
    n=$($T "$sh" -ic true 2>&1 >/dev/null </dev/null | grep -c 'fpm')
    [ "${n:-0}" -gt 0 ] && out="${out:+$out,}$sh:$n"
  done
  printf '%s' "$out"
}
case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) OS=windows ;; Darwin) OS=macos ;; *) OS=linux ;; esac
t "host=$(hostname) os=$OS uname=$(uname -sr | tr ' ' '_')"

# 0. 환경 — python 후보·claude
{
  for c in python3.14 python3 python /usr/bin/python3; do
    p="$(command -v "$c" 2>/dev/null)" && echo "$c -> $p $("$p" --version 2>&1 | tr -d '\r')"
  done
  command -v py >/dev/null 2>&1 && py -0 2>&1
  claude --version; claude auth status 2>&1 | grep -E 'loggedIn|email' | sed -E 's/"email": "[^"]+"/"email": "<redacted>"/'
} > "$OUT/env.txt" 2>&1
t "claude=$(claude --version 2>/dev/null | awk '{print $1}') loggedIn=$(claude auth status 2>/dev/null | grep -o '"loggedIn": *[a-z]*' | awk '{print $2}')"

# 0.5 `~/.claude` 를 런타임 경로로 쓰는 외부 서비스 정지 (Issue644) — 비우기 전에 세운다. 안 세우면 gateway 재시작이 `plugin path not found` 로 2분 실패했다(fg1 2026-10-17)
#     소비 지점 정본: ~/.claude/_doc_arch/openclaw-inbound.md §5 (플러그인 경로·hooks/lib/selection.py·claude-cli 런타임)
EXT_SVC=""; EXT_PLIST=""; STASH="$OUT/stash"; mkdir -p "$STASH"
# 서비스 기동·가동 판정 — OS 별 (linux: systemd user · macos: launchd gui 도메인)
ext_start()  { case "$OS" in macos) launchctl bootstrap "gui/$(id -u)" "$EXT_PLIST" >/dev/null 2>&1 ;; *) systemctl --user start "$EXT_SVC" >/dev/null 2>&1 ;; esac; }
ext_active() { case "$OS" in macos) launchctl list 2>/dev/null | awk -v l="$EXT_SVC" '$3==l && $1!="-" {f=1} END{exit !f}' ;; *) systemctl --user is-active --quiet "$EXT_SVC" ;; esac; }
case "$OS" in
  linux)   if systemctl --user is-active --quiet openclaw-gateway 2>/dev/null; then systemctl --user stop openclaw-gateway && EXT_SVC=openclaw-gateway; fi ;;
  macos)   EXT_PLIST="$HOME/Library/LaunchAgents/ai.openclaw.gateway.plist"
           if [ -f "$EXT_PLIST" ] && launchctl list 2>/dev/null | grep -q 'ai\.openclaw\.gateway'; then
             launchctl bootout "gui/$(id -u)/ai.openclaw.gateway" >/dev/null 2>&1 && EXT_SVC=ai.openclaw.gateway
           fi ;;
esac
# 어떤 경로로 끝나도 세워 둔 서비스는 되살린다 (이미 떠 있으면 no-op) — 정상 경로는 아래 10단계가 probe 까지 한다
[ -n "$EXT_SVC" ] && trap 'ext_active || ext_start' EXIT
# 판정기 보존 — fpm 설치는 hooks/lib/selection.py 를 만들지 않으므로 비우면 jev-model 이 judge_missing 으로 조용히 끊긴다
[ -f "$HOME/.claude/hooks/lib/selection.py" ] && cp -p "$HOME/.claude/hooks/lib/selection.py" "$STASH/selection.py"
t "ext_svc_stopped=${EXT_SVC:-none} stash_selection=$([ -f "$STASH/selection.py" ] && echo yes || echo no)"

# 1. ~/.claude zero-base 재정리 — .credentials.json 보존 (백업 tar 먼저, 백업 실패면 중단)
#    openclaw-plugins 도 보존: fg1 상주 OpenClaw 서비스가 쓰는 폴더라 fpm 과 무관하고, 지우면 그 서비스가 깨진다
#    fpm 로컬 파일(untracked+ignored — Projects.md·Servers.md·projects/·data/hub_setting.yml 등)은 `~/.claude` 밖이라
#    위 tar 에 안 들어간다 — 기본값으로 덮이는 이 파일들이 jma 긴급 복구 때 `.bak` 폴더에만 남아 있었다 (Issue652).
#    그래서 비우기 **전에** 별도 tar 를 만들고, 실패하면 아무것도 비우지 않고 중단한다.
if [ -d "$FPM/.git" ]; then
  FL="$HOME/fpm-local-$STAMP.tar.gz"
  git -C "$FPM" ls-files -o -z 2>/dev/null | tr '\0' '\n' \
    | grep -vE '(^|/)(\.DS_Store|__pycache__|node_modules)(/|$)|^tdd/results/|^\.git/' > "$OUT/fpm-local.list"
  if tar -czf "$FL" -C "$FPM" -T "$OUT/fpm-local.list" 2>>"$OUT/backup.err"; then
    t "fpm_local=ok files=$(wc -l < "$OUT/fpm-local.list" | tr -d ' ') tar=$FL"
  else
    rm -f "$FL"; t "fpm_local=FAIL(tar)"; exit 10
  fi
fi
if [ -d "$HOME/.claude" ]; then
  BK="$HOME/claude-backup-$STAMP.tar.gz"
  n_src=$(find "$HOME/.claude" -type f | wc -l | tr -d ' ')
  if tar -czf "$BK" -C "$HOME" .claude 2>"$OUT/backup.err"; then
    # 목록을 파일로 받는다 — pipefail 아래 'tar | grep -q' 는 grep 조기 종료의 SIGPIPE 로 실패가 된다
    tar -tzf "$BK" > "$OUT/backup.list" 2>>"$OUT/backup.err"
    n_bk=$(grep -cv '/$' "$OUT/backup.list")
    if [ "$n_bk" -ge "$n_src" ] && grep -q '\.claude/\.credentials\.json$' "$OUT/backup.list"; then
      ( cd "$HOME/.claude" && ls -A | grep -vxE '\.credentials\.json|openclaw-plugins' > "$OUT/delete.txt"; while IFS= read -r e; do rm -rf -- "$e"; done < "$OUT/delete.txt" )
      t "zero_base=ok before=$n_src backup=$n_bk left=$(ls -A "$HOME/.claude" | tr '\n' ',')"
    else
      t "zero_base=FAIL(백업 검증 실패 src=$n_src bk=$n_bk)"; exit 10
    fi
  else
    t "zero_base=FAIL(tar)"; exit 10
  fi
fi

# 2. 기존 hub 정지 + 기존 clone 보존 이동
case "$OS" in
  windows) pid=$(netstat -ano 2>/dev/null | tr -d '\r' | awk '$2 ~ ":9876$" && /LISTENING/ {print $NF; exit}'); [ -n "$pid" ] && taskkill //PID "$pid" //F >/dev/null 2>&1 ;;
  *) if systemctl --user cat fpm-hub >/dev/null 2>&1; then systemctl --user stop fpm-hub; else pkill -f 'services/hub/server\.py' 2>/dev/null; fi ;;
esac
sleep 1
[ -d "$FPM" ] && mv "$FPM" "$FPM.bak-$STAMP" && t "old_clone=moved($FPM.bak-$STAMP)"

# 3. GitHub 태그 clean clone
if git clone -q --branch "$TAG" https://github.com/Finfra/fpm.git "$FPM" >"$OUT/clone.log" 2>&1; then
  t "clone=ok head=$(git -C "$FPM" rev-parse --short HEAD) version=$(tr -d '\r\n' < "$FPM/VERSION")"
else
  t "clone=FAIL"; exit 11
fi
cd "$FPM" || exit 11

# 4. install
bash sh/install.sh >"$OUT/install.log" 2>&1; rc=$?
t "install_rc=$rc warn=$(grep -c -E '⚠️|WARN' "$OUT/install.log")"
grep -E 'python|Python' "$OUT/install.log" | head -5 | sed 's/^/  /'
SW="$(shell_startup_warn)"; t "shell_startup=$([ -z "$SW" ] && echo ok || echo "FAIL($SW)")"

# 5. plugin·MCP
claude plugin list >"$OUT/plugin-list.txt" 2>&1
t "plugin=$(grep -A2 'fpm-core' "$OUT/plugin-list.txt" | grep -oE 'Version: *[0-9.]+' | head -1 | tr -d ' ')"
claude mcp list >"$OUT/mcp-list.txt" 2>&1
t "mcp_connected=$(grep -c -i 'connected' "$OUT/mcp-list.txt") mcp_failed=$(grep -c -i -E 'failed|error' "$OUT/mcp-list.txt")"

# 6. check.sh
bash sh/check.sh >"$OUT/check.log" 2>&1; rc=$?
t "check_rc=$rc"

# 7. python 해석 (Issue642 ④) — 설치본 해석기 2종
FBOT_PY="$(bash -c '. sh/fbot-python.sh; fbot_resolve_python; echo "$FBOT_PY_DISPLAY v=$FBOT_PY_VERSION below=$FBOT_PY_BELOW"' 2>&1 | tail -1)"
t "fbot_python=$(echo "$FBOT_PY" | tr ' ' '_')"
PR="$(ls -d "$HOME"/.claude/plugins/cache/*/fpm-core/*/hooks/lib/py-resolve.sh 2>/dev/null | head -1)"
if [ -n "$PR" ]; then
  t "py_resolve=$(bash -c ". '$PR'; p=\$(py_resolve 2>&1); echo \"\$p\"" | tail -1 | tr ' ' '_')"
else
  t "py_resolve=MISSING(플러그인 캐시에 hooks/lib/py-resolve.sh 없음)"
fi

# 8. hub 기동 — 전파 페이로드(해석 단일 지점) 재사용
FPM_CLONE="$FPM" FPM_PROP_NO_INSTALL=1 FPM_PROP_WAIT=30 bash scripts/fpm-consumer-propagate-payload.sh >"$OUT/hub-start.log" 2>&1
grep '^FPMR' "$OUT/hub-start.log" | sed 's/^FPMR /FPMT hub_/' | tee -a "$OUT/fpmt.txt"
code() { curl -s -o /dev/null -m 5 -w '%{http_code}' "http://127.0.0.1:9876$1" 2>/dev/null || echo 000; }
t "http_root=$(code /) http_hub=$(code /hub) http_boards=$(code /boards) http_healthz=$(code /healthz)"
curl -s -m 5 http://127.0.0.1:9876/healthz > "$OUT/healthz.json" 2>/dev/null
case "$OS" in
  windows) hp=$(netstat -ano 2>/dev/null | tr -d '\r' | awk '$2 ~ ":9876$" && /LISTENING/ {print $NF; exit}'); t "hub_proc=$(wmic process where processid=$hp get commandline 2>/dev/null | tr -d '\r' | sed -n 2p | tr ' ' '_' | cut -c1-200)" ;;
  *) t "hub_proc=$(ps -o args= -p "$(pgrep -f 'services/hub/server\.py' | head -1)" 2>/dev/null | tr ' ' '_' | cut -c1-200)" ;;
esac

# 9. 네이티브 TDD
FPM_TDD_NATIVE_REMOTE=1 bash tdd/run-tdd.sh >"$OUT/tdd.log" 2>&1; rc=$?
t "tdd_rc=$rc $(grep '결과:' "$OUT/tdd.log" | sed 's/\x1b\[[0-9;]*m//g' | tr -s ' ' | tr ' ' '_' | tail -1)"
grep '❌' "$OUT/tdd.log" | sed 's/\x1b\[[0-9;]*m//g' | sed 's/^/  /'
# 10. 외부 서비스 복원 + probe (Issue644) — 판정기 복원 → 재기동 → 기동 실패·judge_missing 여부
if [ -n "$EXT_SVC" ]; then
  if [ -f "$STASH/selection.py" ]; then mkdir -p "$HOME/.claude/hooks/lib" && cp -p "$STASH/selection.py" "$HOME/.claude/hooks/lib/selection.py"; fi
  JL="$HOME/.openclaw/logs/jev-model.jsonl"; L0=$(wc -l < "$JL" 2>/dev/null | tr -d ' '); L0=${L0:-0}
  T0="$(date '+%Y-%m-%d %H:%M:%S')"
  GL="$HOME/Library/Logs/openclaw/gateway.log"; G0=$(wc -l < "$GL" 2>/dev/null | tr -d ' '); G0=${G0:-0}
  ext_start
  for _i in $(seq 1 30); do ext_active && break; sleep 1; done
  if ext_active; then st=active; else st=inactive; fi
  case "$OS" in
    macos) sleep 3; bad=$(tail -n +$((G0 + 1)) "$GL" 2>/dev/null | grep -c 'plugin path not found') ;;
    *)     bad=$(journalctl --user -u "$EXT_SVC" --since "$T0" --no-pager 2>/dev/null | grep -c 'plugin path not found') ;;
  esac
  miss=$(tail -n +$((L0 + 1)) "$JL" 2>/dev/null | grep -c judge_missing)
  verdict=ok; [ "$st" = active ] && [ "$bad" = 0 ] && [ "$miss" = 0 ] || verdict=FAIL
  t "ext_svc_probe=$verdict svc=$EXT_SVC state=$st plugin_path_err=$bad judge_missing=$miss judged=MANUAL(@claw 응답 뒤 jev-model.jsonl 에 judged 1건 확인)"
fi

t "out=$OUT"
