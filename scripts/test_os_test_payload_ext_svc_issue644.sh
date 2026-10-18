#!/bin/bash
# test_os_test_payload_ext_svc_issue644.sh — Issue644 회귀 테스트
#
# zero-base 재구성(`~/.claude` 비우기) 페이로드가 «`~/.claude` 를 런타임으로 쓰는 외부 서비스(OpenClaw gateway)»
# 를 비우기 전에 세우고, 설치 뒤 판정기를 되돌려 재기동·probe 하는지 본다. 안 하면 fg1 에서 gateway 재시작이
# `plugin path not found` 로 약 2분 실패했고 jev-model 판정이 judge_missing 으로 조용히 끊겼다(2026-10-17).
#
#   ① 서비스가 떠 있으면: 비우기 전에 stop → 판정기(selection.py) 보존 → 비운 뒤 복원 → start → probe ok
#   ② 재기동 로그에 `plugin path not found` → probe FAIL
#   ③ 재기동 뒤 jev-model.jsonl 에 judge_missing 이 새로 생김 → probe FAIL
#   ④ 서비스가 안 떠 있으면: stop·start 를 부르지 않고 none 으로 기록 (없는 서비스를 일으켜 세우지 않는다)
#   ⑤ 중간에 비정상 종료해도 세워 둔 서비스는 EXIT trap 이 되살린다
#
# 격리: 가짜 HOME + 가짜 systemctl·journalctl. 검사 대상 구간은 실물 페이로드에서 **추출**해 돌린다(재구현 금지).
# 실행: bash scripts/test_os_test_payload_ext_svc_issue644.sh [페이로드경로]
set -u

REPO="$(cd "$(dirname "$0")/.." && pwd)"
PAYLOAD="${1:-$REPO/_doc_work/_release/v0.8.3/os-test/os-test-payload.sh}"
SB="$(mktemp -d "${TMPDIR:-/tmp}/ext-svc.XXXXXX")"
trap 'rm -rf "$SB"' EXIT
PASS=0; FAIL=0
ok()   { PASS=$((PASS + 1)); echo "  ok   $1"; }
fail() { FAIL=$((FAIL + 1)); echo "  FAIL $1"; }
check() { if [ "$2" = "$3" ]; then ok "$1"; else fail "$1 (want='$3' got='$2')"; fi; }

echo "[test_os_test_payload_ext_svc_issue644]"

# 구간 추출: 0.5(정지·보존) = "# 0.5" ~ "# 1. " 직전 · 10(복원·probe) = "# 10." ~ 't "out=' 직전
S05="$SB/s05.sh"; S10="$SB/s10.sh"
awk '/^# 0\.5 /{p=1} /^# 1\. /{p=0} p' "$PAYLOAD" > "$S05"
awk '/^# 10\. /{p=1} /^t "out=/{p=0} p' "$PAYLOAD" > "$S10"
[ -s "$S05" ] && ok "구간 0.5 존재" || fail "구간 0.5 없음 — 페이로드에 외부 서비스 정지 단계가 없다"
[ -s "$S10" ] && ok "구간 10 존재" || fail "구간 10 없음 — 페이로드에 복원·probe 단계가 없다"

# 하니스 한 판: $1=이름 $2=서비스 초기 상태(active|inactive) $3=journal 내용 $4=재기동 시 jev 로그에 덧붙일 줄 $5=비정상 종료 여부(0|1)
run_case() {
    local name="$1" state0="$2" jour="$3" jev_add="$4" crash="$5"
    local D="$SB/$name"; local H="$D/home" B="$D/bin" L="$D/calls.log"
    mkdir -p "$H/.claude/hooks/lib" "$H/.openclaw/logs" "$B"
    echo "SEL" > "$H/.claude/hooks/lib/selection.py"
    printf '{"judged":"haiku"}\n{"judged":"sonnet"}\n' > "$H/.openclaw/logs/jev-model.jsonl"
    echo "$state0" > "$D/state"; printf '%s' "$jour" > "$D/journal"; printf '%s' "$jev_add" > "$D/jev_add"
    cat > "$B/systemctl" <<EOF
#!/bin/sh
shift; verb="\$1"; echo "systemctl \$verb \$*" >> "$L"
case "\$verb" in
  is-active) if [ "\$2" = "--quiet" ]; then [ "\$(cat "$D/state")" = active ]; exit \$?; fi
             cat "$D/state"; [ "\$(cat "$D/state")" = active ]; exit \$? ;;
  stop)  echo inactive > "$D/state" ;;
  start) echo active > "$D/state"; [ -s "$D/jev_add" ] && { cat "$D/jev_add"; echo; } >> "$H/.openclaw/logs/jev-model.jsonl" ;;
esac
exit 0
EOF
    printf '#!/bin/sh\ncat "%s"\n' "$D/journal" > "$B/journalctl"
    chmod +x "$B/systemctl" "$B/journalctl"
    {
        echo "export HOME=\"$H\" PATH=\"$B:\$PATH\""
        echo "OUT=\"$D/out\"; mkdir -p \"\$OUT\"; OS=linux"
        echo 't() { echo "FPMT $*"; }'
        cat "$S05"
        echo '# 비우기 모사 — 페이로드 1단계가 하는 일 (판정기는 보존분만 남는다)'
        echo 'rm -rf "$HOME/.claude/hooks"'
        [ "$crash" = 1 ] && echo 'exit 10'
        cat "$S10"
    } > "$D/harness.sh"
    bash "$D/harness.sh" > "$D/out.txt" 2>&1
    CALLS="$(cat "$L" 2>/dev/null)"; OUTTXT="$(cat "$D/out.txt")"
    RESTORED="$([ -f "$H/.claude/hooks/lib/selection.py" ] && echo yes || echo no)"
    FINAL="$(cat "$D/state")"
}

# ① 정상
run_case normal active "" "" 0
case "$CALLS" in *"stop openclaw-gateway"*) ok "① stop 호출" ;; *) fail "① stop 안 부름: $CALLS" ;; esac
check "① 판정기 복원" "$RESTORED" "yes"
case "$OUTTXT" in *"ext_svc_stopped=openclaw-gateway stash_selection=yes"*) ok "① 정지·보존 기록" ;; *) fail "① 기록 없음: $OUTTXT" ;; esac
case "$OUTTXT" in *"ext_svc_probe=ok"*) ok "① probe ok" ;; *) fail "① probe ok 아님: $OUTTXT" ;; esac
check "① 최종 상태 active" "$FINAL" "active"

# ② plugin path not found
run_case pathbad active "May 01 plugin path not found: ~/.claude/openclaw-plugins/jev-model" "" 0
case "$OUTTXT" in *"ext_svc_probe=FAIL"*"plugin_path_err=1"*) ok "② 플러그인 경로 오류 → FAIL" ;; *) fail "② FAIL 아님: $OUTTXT" ;; esac

# ③ judge_missing 신규
run_case jmiss active "" '{"skip":"x","judge_missing":true}' 0
case "$OUTTXT" in *"ext_svc_probe=FAIL"*"judge_missing=1"*) ok "③ judge_missing → FAIL" ;; *) fail "③ FAIL 아님: $OUTTXT" ;; esac

# ④ 안 떠 있음
run_case idle inactive "" "" 0
case "$CALLS" in *"systemctl stop"*|*"systemctl start"*) fail "④ 없는 서비스를 건드림: $CALLS" ;; *) ok "④ stop·start 미호출" ;; esac
case "$OUTTXT" in *"ext_svc_stopped=none"*) ok "④ none 기록" ;; *) fail "④ none 아님: $OUTTXT" ;; esac

# ⑤ 비정상 종료 → trap 이 되살림
run_case crash active "" "" 1
check "⑤ 비정상 종료 후에도 서비스 active" "$FINAL" "active"

echo "결과: PASS $PASS / FAIL $FAIL"
[ "$FAIL" -eq 0 ]
