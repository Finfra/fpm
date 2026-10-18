#!/usr/bin/env bash
# test-aoa-mq-ask-nag-new.sh — Discord 질의 통지: 새 항목은 전역 백오프를 우회한다 (prj3#Issue1107)
#
# ⚠️ 글로벌 SCAR 변경 가드 (prj3#Issue46): cwd ≠ ~/.claude 면 즉시 수정 금지 → Issue.md 이슈 등록 후 처리.
#
# 무엇을 지키나 — §6 의 `.ask_nag` 는 «전역» 백오프(Issue676)라 대기가 0건이 안 되면 리셋되지 않는다.
#   소진(cnt=3, last=now)된 채 고정되면 그 뒤 올라온 [컨펌] 이 Discord 로 영영 안 간다(2026-10-16 실측).
#   → 항목별 표지 `discord_notified_ts` 가 없는 대기 항목은 백오프와 무관하게 1회 발송하고,
#     기존 항목의 재알림 백오프·상한(Issue676)은 그대로다.
# 실 Discord·실 큐 무접촉 — AOA_MQ_DIR 샌드박스 · 가짜 openclaw(PATH) · 가짜 hub(로컬 포트).
# 실행: bash ~/.claude/mcp/aoa-mq/test-aoa-mq-ask-nag-new.sh   (exit 0 = 전부 PASS)
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
TICK="$HERE/aoa-mq-tick.sh"
T=$(mktemp -d "${TMPDIR:-/tmp}/aoa-mq-asknag.XXXXXX"); T=$(cd "$T" && pwd)
HUBPID=""
trap '[ -n "$HUBPID" ] && kill "$HUBPID" 2>/dev/null; rm -rf "$T"' EXIT
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); printf '  ✅ %s\n' "$1"; }
bad() { FAIL=$((FAIL+1)); printf '  ❌ %s\n' "$1"; }
chk() { if eval "$2"; then ok "$1"; else bad "$1 — ${3:-}"; fi; }

# 가짜 openclaw — --version 은 성공, 발신 인자는 로그에 1건씩 기록(실 발송 없음)
mkdir -p "$T/bin" "$T/home"
cat > "$T/bin/openclaw" <<'SH'
#!/bin/bash
[ "${1:-}" = "--version" ] && { echo "fake 0.0"; exit 0; }
[ -n "${FAKE_OC_FAIL:-}" ] && { echo "boom" >&2; exit 1; }
printf '@@SEND %s\n' "$*" >> "$FAKE_OC_LOG"
exit 0
SH
chmod +x "$T/bin/openclaw"
export FAKE_OC_LOG="$T/oc.log"

# 가짜 hub — healthz(advertise_url)·register(token)·그 밖은 {} (포트는 OS 가 정한다)
cat > "$T/hub.py" <<'PY'
import http.server, json, sys
class H(http.server.BaseHTTPRequestHandler):
    def _r(self):
        p = self.path.split("?")[0]
        body = {"advertise_url": "http://hub.test"} if p == "/healthz" else \
               {"token": "tok", "cwd_hash": "h"} if p == "/register" else {}
        b = json.dumps(body).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    do_GET = do_POST = _r
    def log_message(self, *a): pass
s = http.server.HTTPServer(("127.0.0.1", 0), H)
open(sys.argv[1], "w").write(str(s.server_address[1]))
s.serve_forever()
PY
python3 "$T/hub.py" "$T/port" &
HUBPID=$!
for _ in 1 2 3 4 5 6 7 8 9 10; do [ -s "$T/port" ] && break; sleep 0.5; done
PORT=$(cat "$T/port" 2>/dev/null)
[ -n "$PORT" ] || { echo "❌ 가짜 hub 기동 실패"; exit 1; }

Q="$T/mq"; mkdir -p "$Q/queue" "$Q/queue_done" "$Q/handoff"
cat > "$Q/policy.yml" <<'YML'
notify_on_ask: true
discord_account: acct-test
discord_target: tgt-test
ask_nag_backoff_days: 0,1,3,7
allow_wip_autostart: false
notify_on_wip_stale: false
notify_on_handoff_stale: false
YML
put() { # $1=id $2=추가 json 필드(쉼표 없이, 비면 생략)
  printf '{ "id": "%s", "type": "scheduled", "kind": "pre", "status": "due", "ask_count": 1, "source": "t", "message": "%s"%s }\n' \
    "$1" "$3" "${2:+, $2}" > "$Q/queue/$1.json"
}
run_tick() {
  PATH="$T/bin:$PATH" AOA_MQ_DIR="$Q" AOA_MQ_CWD="$T/home" HTM_SERVER_PORT="$PORT" \
    bash "$TICK" --force-render >/dev/null 2>&1
}
sent() { [ -f "$FAKE_OC_LOG" ] && grep -c '^@@SEND ' "$FAKE_OC_LOG" || echo 0; }     # 본문이 여러 줄이라 발송 1건 = 표지 1줄
last_send() { awk '/^@@SEND /{buf=""} {buf=buf $0 "\n"} END{printf "%s", buf}' "$FAKE_OC_LOG"; }
mark() { jq -r '.discord_notified_ts // empty' "$Q/queue/$1.json"; }

echo "▶ 전제 — 소진된 전역 백오프(cnt=3, last=now) + 기존 대기 1건(표지 있음) + 새 [컨펌] 1건"
NOW=$(date +%s)
printf '%s %s\n' "$NOW" 3 > "$Q/.ask_nag"
put OLD1 '"discord_notified_ts":"2026-10-01T00:00:00"' "기존 항목 OLD1"
put NEW1 '' "[컨펌] [H:보안] 새 항목 NEW1"

echo "▶ tick 1 — 새 항목만 1회 발송 (현행은 백오프 대기로 미발송 = red)"
run_tick
chk "Discord 발송 1회" '[ "$(sent)" = 1 ]' "sent=$(sent)"
chk "본문에 새 항목 포함" 'grep -q "NEW1" "$FAKE_OC_LOG"' "$(cat "$FAKE_OC_LOG" 2>/dev/null)"
chk "본문에 기존(이미 통지된) 항목 미포함 — 재알림 도배 금지" '! grep -q "OLD1" "$FAKE_OC_LOG"'
chk "새 항목에 discord_notified_ts 표지 기록" '[ -n "$(mark NEW1)" ]' "mark=[$(mark NEW1)]"
chk "기존 항목 표지는 그대로" '[ "$(mark OLD1)" = "2026-10-01T00:00:00" ]'
chk "전역 백오프 상태(.ask_nag)는 새 항목 발송이 소비하지 않음" '[ "$(cat "$Q/.ask_nag")" = "$NOW 3" ]' "$(cat "$Q/.ask_nag")"

echo "▶ tick 2 — 새 항목 없음 → 백오프 대기 (재발송 없음)"
run_tick
chk "발송 수 불변(1)" '[ "$(sent)" = 1 ]' "sent=$(sent)"

echo "▶ 발송 실패 — 표지를 기록하지 않아 다음 tick 이 재시도"
put NEW2 '' "[컨펌] [H:배포] 새 항목 NEW2"
FAKE_OC_FAIL=1 run_tick
chk "실패 시 NEW2 표지 없음" '[ -z "$(mark NEW2)" ]' "mark=[$(mark NEW2)]"
chk "실패 시 발송 로그 불변(1)" '[ "$(sent)" = 1 ]'
run_tick
chk "재시도 발송(2) · NEW2 표지 기록" '[ "$(sent)" = 2 ] && [ -n "$(mark NEW2)" ]' "sent=$(sent) mark=[$(mark NEW2)]"

echo "▶ 기존 항목 재알림 백오프 계약 유지 — 백오프 만료 시 새 항목 먼저 + 기존 항목 동반, 카운터 전진"
printf '%s %s\n' "$((NOW - 30*86400))" 4 > "$Q/.ask_nag"     # 시퀀스 0,1,3,7 을 4회 다 씀 = 상한 → 오래 지나도 재알림 없음
run_tick
chk "상한 도달(cnt=4) 이면 새 항목 없을 때 미발송(2 유지)" '[ "$(sent)" = 2 ]' "sent=$(sent)"
printf '%s %s\n' "$((NOW - 2*86400))" 1 > "$Q/.ask_nag"      # 간격 1일 경과 → 재알림 시점
put NEW3 '' "[컨펌] [H:방침] 새 항목 NEW3"
run_tick
last=$(last_send)
chk "재알림 회차 발송(3)" '[ "$(sent)" = 3 ]' "sent=$(sent)"
pre_new=${last%%NEW3*}; pre_old=${last%%OLD1*}
chk "새 항목이 기존 항목보다 앞" '[ "$pre_new" != "$last" ] && [ "$pre_old" != "$last" ] && [ ${#pre_new} -lt ${#pre_old} ]' "$last"
read -r _l nag_cnt < "$Q/.ask_nag"
chk "재알림이면 백오프 카운터 전진(1→2)" '[ "$nag_cnt" = 2 ]' "$(cat "$Q/.ask_nag")"

echo; echo "PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
