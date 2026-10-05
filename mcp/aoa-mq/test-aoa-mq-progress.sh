#!/usr/bin/env bash
# test-aoa-mq-progress.sh — aoa-mq-progress.sh 회귀 테스트 (prj3#Issue651)
#
# ⚠️ 글로벌 SCAR 변경 가드 (prj3#Issue46): 본 script 는 aoa-mq(prj3) 전용 회귀 테스트.
#   cwd ≠ ~/.claude 면 즉시 수정 금지 → ~/.claude/Issue.md 이슈 등록 후 처리.
#   설계 SSOT: ~/.claude/_doc_arch/aoa-mq.md "진행 가시성 — claimed_by·progress·result"
#
# 왜 (prj3#Issue651): `oneline()` 이 `cut -c1-400`(BSD 는 **바이트**) 으로 한글을 경계 중간에서
#   끊어, 134자 이상의 진행 메모가 ① 파일에는 U+FFFD 로 깨져 굳고 ② stdout decode 를 죽여
#   호출자에게는 «실패» 로 보였다. 기록이 사라지는 종류의 버그는 **눈에 안 띄므로** 테스트로 박제한다.
#
# 사용법: bash test-aoa-mq-progress.sh        (격리된 임시 큐에서 돈다 — 실 큐를 건드리지 않는다)
# 종료코드: 0=전부 통과 · 1=하나라도 실패

set -u
HERE=$(cd "$(dirname "$0")" && pwd)
PROGRESS="$HERE/aoa-mq-progress.sh"
[ -f "$PROGRESS" ] || { echo "helper 없음: $PROGRESS" >&2; exit 1; }

T=$(mktemp -d "${TMPDIR:-/tmp}/aoa-mq-test.XXXXXX")
T=$(cd "$T" && pwd)       # TMPDIR 끝 '/' 로 생기는 '//' 정규화 — 기동 cwd($PWD)와 문자열 비교한다(Issue770)
# prj3#Issue863_7 — 기동이 작업 메시지로 Jev(selection.py pick)를 부른다. 정책을 없는 경로로 두어 외부 호출·운영 원장 기록 없이
#   기본값으로 떨어지게 한다(hermetic)
export SELECTION_POLICY="$T/no-selection.yml"
export AOA_MEMORY_DIR="$T/no-aoa"   # 선택 기록(sel_event)이 운영 원장에 쌓이지 않게 — selection 은 없는 원장을 만들지 않는다(FBOT_ 계열은 기동 전 env 차단이 지운다)
trap 'rm -rf "$T"' EXIT
mkdir -p "$T/queue" "$T/queue_done"
export AOA_MQ_DIR="$T"
# 실 세션의 락 대기에 끌려가지 않는다 — 격리 큐라 경합이 없다
export AOA_MQ_LOCK_WAIT=3

PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); printf '  ✅ %s\n' "$1"; }
bad()  { FAIL=$((FAIL+1)); printf '  ❌ %s\n' "$1"; }

mkitem() { # $1=id
  cat > "$T/queue/$1.json" <<JSON
{ "id": "$1", "kind": "reminder", "msg": "회귀 테스트", "status": "in_progress" }
JSON
}

# 한 케이스 = (글자수, 하위명령) — stdout decode · 파일 내용 · JSON 파싱을 함께 본다
case_run() { # $1=글자수 $2=note|result
  local n="$2" len="$1" id field
  id="20260919-000000-$(printf '%03d' $((RANDOM % 900 + 1)))"
  field=$([ "$n" = note ] && echo progress || echo result)
  mkitem "$id"
  local text; text=$(python3 -c "print('가'*$len, end='')")

  # stdout 을 바이트로 받아 decode 가능한지 본다 — 여기서 죽던 것이 원래 증상이다
  local out rc
  out=$(bash "$PROGRESS" "$n" "$id" --text "$text" 2>&1); rc=$?
  if [ $rc -ne 0 ]; then bad "$n/${len}자: helper rc=$rc — $out"; return; fi
  if ! printf '%s' "$out" | python3 -c "import sys; sys.stdin.buffer.read().decode('utf-8')" 2>/dev/null; then
    bad "$n/${len}자: stdout 이 유효한 UTF-8 이 아니다"; return
  fi

  python3 - "$T/queue/$id.json" "$field" "$len" <<'PY'
import json, sys
path, field, n = sys.argv[1], sys.argv[2], int(sys.argv[3])
try:
    d = json.load(open(path, encoding="utf-8"))
except Exception as e:
    print(f"JSON 파싱 실패: {e}"); sys.exit(1)
v = d.get(field)
if v is None:
    print(f"{field} 가 기록되지 않았다"); sys.exit(1)
if "�" in v:
    print(f"{field} 에 U+FFFD(깨진 문자)가 있다 — 바이트 절단 회귀"); sys.exit(1)
if n <= 400:
    if v != "가" * n:
        print(f"{field}: 원문과 다르다 (길이 {len(v)}, 기대 {n})"); sys.exit(1)
else:
    if len(v) != 400 or not v.endswith("…") or v[:399] != "가" * 399:
        print(f"{field}: 절단 결과가 «399자+…» 가 아니다 (길이 {len(v)}, 끝 {v[-1]!r})"); sys.exit(1)
PY
  if [ $? -eq 0 ]; then ok "$n/${len}자"; else bad "$n/${len}자"; fi
}

echo "▶ 한글 길이별 — note·result 양쪽 (prj3#Issue651)"
# 133/134 = 구 `cut -c1-400` 의 바이트 경계(399/402바이트) · 150 = 최초 실발생 · 400 = 문자 상한 경계
for len in 133 134 150 400; do
  case_run "$len" note
  case_run "$len" result
done

echo "▶ 상한 초과 — 절단 표식(…)"
case_run 401 note
case_run 401 result

echo "▶ 개행 정규화 — 1줄 계약 유지"
nid="20260919-000000-999"; mkitem "$nid"
bash "$PROGRESS" note "$nid" --text "$(printf '첫줄\n둘째줄\r셋째줄')" >/dev/null 2>&1
if [ "$(jq -r '.progress' "$T/queue/$nid.json")" = "첫줄 둘째줄 셋째줄" ]; then
  ok "개행·복귀문자 → 공백"
else
  bad "개행 정규화: $(jq -r '.progress' "$T/queue/$nid.json")"
fi

# ════════════════════════════════════════════════════════════════════
# prj3#Issue770 — 대기(waiting)·승인 판정·대상 prj·사람 몫·mq 의존
#   tick 을 실제로 돌린다 — 격리 큐 · hub 미가용 포트 · 가짜 claude · 가짜 HR 게이트.
#   ⚠️ 실 claude -p 를 띄우지 않는다(AOA_MQ_CLAUDE_BIN = 기록만 하는 가짜).
# ════════════════════════════════════════════════════════════════════
TICK="$HERE/aoa-mq-tick.sh"
ENQ="$HERE/aoa-mq-enqueue.sh"

# 번호 → 경로 SSOT 대역 (~/_git/___pm/projects/{N} 과 같은 형식: 1줄 경로)
PJ="$T/projects"; mkdir -p "$PJ" "$T/p3" "$T/p5" "$T/p16" "$T/home"
printf '%s\n' "$T/p3"  > "$PJ/3"
printf '%s\n' "$T/p5"  > "$PJ/5"
printf '%s\n' "$T/p16" > "$PJ/16"
printf '%s\n' "$T/p7-이-머신에-없음" > "$PJ/7"      # 매핑은 있으나 경로가 없는 prj
export AOA_MQ_PROJECTS_DIR="$PJ"

# 가짜 claude — --version 은 성공, 그 밖엔 cwd·WAKE_ID·프롬프트를 기록만 한다
cat > "$T/fake-claude" <<'SH'
#!/bin/bash
[ "${1:-}" = "--version" ] && { echo "fake 0.0"; exit 0; }
last=""; for a in "$@"; do last="$a"; done
printf 'CWD=%s ID=%s\n' "$PWD" "${AOA_MQ_WAKE_ID:-}" >> "$FAKE_CLAUDE_LOG"
printf '%s\n----\n' "$last" >> "$FAKE_CLAUDE_LOG.prompt"
SH
chmod +x "$T/fake-claude"
cat > "$T/fake-gate.py" <<'PY2'
import os, sys; sys.exit(int(os.environ.get("FAKE_GATE_RC", "0")))
PY2

newmq() { # $1=이름 → 격리 큐 경로 echo (policy 포함)
  local d="$T/mq-$1"
  rm -rf "$d"; mkdir -p "$d/queue" "$d/queue_done" "$d/handoff"
  cat > "$d/policy.yml" <<'YML'
allow_wip_autostart: true
wip_stale_hours: 1
wip_autostart_hours: 1
wip_wake_max: 5
wip_autostart_max_per_tick: 5
notify_on_wip_stale: false
YML
  printf '%s' "$d"
}
put() { # $1=큐 $2=id $3=json(추가 필드, 앞에 쉼표 없이)
  printf '{ "id": "%s", "type": "scheduled", "kind": "pre", "ask_count": 0, "source": "t", %s }\n' "$2" "$3" > "$1/queue/$2.json"
}
fld() { jq -r "$3" "$1/queue/$2.json" 2>/dev/null; }     # $1=큐 $2=id $3=jq
run_tick() { # $1=큐 [추가 인자...]
  local d="$1"; shift
  : > "$T/claude.log"; : > "$T/claude.log.prompt"
  AOA_MQ_DIR="$d" AOA_MQ_CWD="$T/home" HTM_SERVER_PORT=1 \
  AOA_MQ_CLAUDE_BIN="$T/fake-claude" AOA_MQ_HR_GATE="$T/fake-gate.py" FAKE_CLAUDE_LOG="$T/claude.log" \
    ${TEST_BASH:-bash} "$TICK" --no-ask-wait "$@" >/dev/null 2>&1
  sleep 1   # 기동은 nohup 백그라운드다
}
P() { AOA_MQ_DIR="$1" ${TEST_BASH:-bash} "$PROGRESS" "${@:2}"; }      # $1=큐 나머지=helper 인자
chk() { if eval "$2"; then ok "$1"; else bad "$1 — ${3:-}"; fi; }

echo "▶ 대상 prj 판정 3단 폴백 (Issue770 — target → message prjN → source)"
Q=$(newmq target)
put "$Q" A '"status":"in_progress","target":"prj16","message":"prj5 언급만 있는 작업","source":"claude@p3"'
put "$Q" B '"status":"in_progress","message":"[컨펌] [H:스토어] prj16 Issue265 재촬영","source":"claude@p3"'
put "$Q" C '"status":"in_progress","message":"그냥 작업","source":"claude@p5"'
put "$Q" D '"status":"in_progress","message":"그냥 작업","source":"pm-ee@prj3"'
put "$Q" E '"status":"in_progress","message":"그냥 작업","source":"fbot-lead"'
put "$Q" F '"status":"in_progress","target":"prj8","message":"prj5 언급","source":"claude@p3"'
for pair in "A|prj16|$T/p16|target|true" "B|prj16|$T/p16|message|true" "C|prj5|$T/p5|source|true" \
            "D|prj3|$T/p3|source|true" "E||$T/home|default|false" "F|prj8||target|false"; do
  IFS='|' read -r id wp wc wv wr <<<"$pair"
  out=$(AOA_MQ_CWD="$T/home" P "$Q" target "$id" --json 2>&1)
  got=$(printf '%s' "$out" | jq -r '[.target,.cwd,.via,(.resolved|tostring)]|join("|")' 2>/dev/null)
  chk "target $id → ${wp:-미상}/${wv}" '[ "$got" = "$wp|$wc|$wv|$wr" ]' "got=[$got] out=[$out]"
done

echo "▶ retarget — 잘못 박힌 대상 prj 정정 (Issue925 — 큐 직접 Write 금지의 짝)"
Q=$(newmq retarget)
put "$Q" RT1 '"status":"in_progress","target":"prj5","message":"[컨펌] [H:보안] prj5#Issue112 shadow","approved_ts":"2026-10-04T19:32:49"'
P "$Q" retarget RT1 --to prj3 --by "human:test" >/dev/null 2>&1; rc=$?
chk "retarget → rc 0 · target=prj3" '[ $rc -eq 0 ] && [ "$(fld "$Q" RT1 .target)" = prj3 ]' "rc=$rc target=$(fld "$Q" RT1 .target)"
chk "retarget → 이력 target_prev·retargeted_by·retargeted_ts" '[ "$(fld "$Q" RT1 .target_prev)" = prj5 ] && [ "$(fld "$Q" RT1 .retargeted_by)" = "human:test" ] && [ -n "$(fld "$Q" RT1 ".retargeted_ts // empty")" ]'
chk "retarget → 상태·승인 기록 불변" '[ "$(fld "$Q" RT1 .status)" = in_progress ] && [ "$(fld "$Q" RT1 .approved_ts)" = 2026-10-04T19:32:49 ]'
got=$(P "$Q" target RT1 --json 2>/dev/null | jq -r '[.target,.cwd,.via]|join("|")' 2>/dev/null)
chk "retarget 뒤 판정(lib 단일 지점) = prj3/target" '[ "$got" = "prj3|$T/p3|target" ]' "got=[$got]"
P "$Q" retarget RT1 --to prj3 >/dev/null 2>&1; rc=$?
chk "같은 대상 재지정 → rc 0 · 이력 덮지 않음" '[ $rc -eq 0 ] && [ "$(fld "$Q" RT1 .target_prev)" = prj5 ]' "rc=$rc prev=$(fld "$Q" RT1 .target_prev)"
put "$Q" RT2 '"status":"in_progress","target":"prj5","message":"x"'
for bad_to in "three" "prj99" ""; do
  P "$Q" retarget RT2 --to "$bad_to" >/dev/null 2>&1; rc=$?
  chk "retarget --to '${bad_to:-빈값}' 거부(rc≠0)·무변경" '[ $rc -ne 0 ] && [ "$(fld "$Q" RT2 .target)" = prj5 ]' "rc=$rc"
done
P "$Q" retarget RT2 >/dev/null 2>&1; rc=$?
chk "retarget --to 생략 거부(rc≠0)" '[ $rc -ne 0 ] && [ "$(fld "$Q" RT2 .target)" = prj5 ]' "rc=$rc"
# 값 없는 끝 인자 — `shift 2` 가 실패하면 인자 루프가 멎지 않는다(Issue925 리뷰 M2 · 기존 결함). perl alarm = 휴대 timeout
for tail_args in "--to" "--to prj3 --by" "--to prj3 --text"; do
  # shellcheck disable=SC2086
  AOA_MQ_DIR="$Q" perl -e 'alarm 5; exec @ARGV' ${TEST_BASH:-bash} "$PROGRESS" retarget RT2 $tail_args >/dev/null 2>&1; rc=$?
  chk "끝 인자 '${tail_args##* }' 값 없음 → 즉시 거부(rc 1, 멎지 않음)·무변경" '[ $rc -eq 1 ] && [ "$(fld "$Q" RT2 .target)" = prj5 ]' "rc=$rc(142=alarm 무한 루프)"
done
printf '{"id":"RTD","status":"confirmed","target":"prj5","message":"끝난 것"}\n' > "$Q/queue_done/RTD.json"
P "$Q" retarget RTD --to prj3 >/dev/null 2>&1; rc=$?
chk "종결 항목 retarget 거부" '[ $rc -ne 0 ] && [ "$(jq -r .target "$Q/queue_done/RTD.json")" = prj5 ]' "rc=$rc"
put "$Q" RT3 '"status":"in_progress","message":"대상 표기 없던 항목"'
P "$Q" retarget RT3 --to prj16 >/dev/null 2>&1; rc=$?
chk "target 없던 항목 → 지정 · target_prev=null" '[ $rc -eq 0 ] && [ "$(fld "$Q" RT3 .target)" = prj16 ] && [ "$(fld "$Q" RT3 .target_prev)" = null ]' "rc=$rc"
put "$Q" RT4 '"status":"in_progress","target":"prj5","message":"x","claimed_by":"session:old-prj5","claimed_ts":"2026-10-04T19:40:00"'
P "$Q" retarget RT4 --to prj3 >/dev/null 2>&1; rc=$?
chk "구 대상 세션의 claim 은 해제·claimed_prev 로 보존(새 대상 세션이 다시 집는다)" '[ $rc -eq 0 ] && [ "$(fld "$Q" RT4 ".claimed_by // \"none\"")" = none ] && [ "$(fld "$Q" RT4 .claimed_prev)" = "session:old-prj5" ]' "rc=$rc claimed=$(fld "$Q" RT4 .claimed_by)"

echo "▶ wait / resume — 대기 진입·원상태 복귀 (Issue770)"
Q=$(newmq wait)
put "$Q" W1 '"status":"in_progress","message":"prj5 Issue95 signup","started_at":"2026-09-26T11:38:00"'
P "$Q" wait W1 --for "typesafe.ai signup 재개" --recheck 2026-09-29T09:00:00 >/dev/null 2>&1
chk "wait → status=waiting" '[ "$(fld "$Q" W1 .status)" = waiting ]' "$(fld "$Q" W1 .status)"
chk "wait → wait_from=in_progress" '[ "$(fld "$Q" W1 .wait_from)" = in_progress ]'
chk "wait → wait_for·recheck_ts 기록" '[ "$(fld "$Q" W1 .wait_for)" = "typesafe.ai signup 재개" ] && [ "$(fld "$Q" W1 .recheck_ts)" = 2026-09-29T09:00:00 ]'
P "$Q" resume W1 >/dev/null 2>&1
chk "resume → in_progress 복귀" '[ "$(fld "$Q" W1 .status)" = in_progress ]' "$(fld "$Q" W1 .status)"
chk "resume → 대기 필드 정리·last_wait 이력" '[ "$(fld "$Q" W1 ".wait_for // \"none\"")" = none ] && [ "$(fld "$Q" W1 .last_wait.for)" = "typesafe.ai signup 재개" ]'
put "$Q" W2 '"status":"due","message":"x","due_ts":"2026-09-01T09:00:00"'
P "$Q" wait W2 --for "선행 확인" >/dev/null 2>&1
chk "wait --recheck 생략 → 기본 재확인 시각 기록" '[ -n "$(fld "$Q" W2 ".recheck_ts // empty")" ]'
P "$Q" resume W2 >/dev/null 2>&1
chk "resume 은 원래 상태(due)로만 — in_progress 를 만들지 않는다" '[ "$(fld "$Q" W2 .status)" = due ]' "$(fld "$Q" W2 .status)"
P "$Q" wait W2 >/dev/null 2>&1; rc=$?
chk "wait 은 --for 필수(rc≠0)" '[ $rc -ne 0 ]'
put "$Q" W3 '"status":"in_progress","message":"x"'
P "$Q" wait W3 --for "mq:NOPE" >/dev/null 2>&1; rc=$?
chk "wait --for mq:<없는 id> 거부(rc≠0)" '[ $rc -ne 0 ] && [ "$(fld "$Q" W3 .status)" = in_progress ]'

echo "▶ tick 5.1 — recheck 재부상 · mq 의존 자동 resume (Issue770)"
Q=$(newmq recheck)
put "$Q" R1 '"status":"waiting","wait_from":"in_progress","wait_for":"외부 조건","recheck_ts":"2020-01-01T00:00:00","message":"x"'
put "$Q" R2 '"status":"waiting","wait_from":"in_progress","wait_for":"외부 조건","recheck_ts":"2099-01-01T00:00:00","message":"x"'
put "$Q" DEP '"status":"in_progress","message":"선행 작업"'
put "$Q" R3 '"status":"waiting","wait_from":"in_progress","wait_for":"mq:DONE1","recheck_ts":"2099-01-01T00:00:00","message":"후행"'
put "$Q" R4 '"status":"waiting","wait_from":"in_progress","wait_for":"mq:DEP","recheck_ts":"2099-01-01T00:00:00","message":"후행2"'
printf '{"id":"DONE1","status":"confirmed","message":"끝난 선행"}\n' > "$Q/queue_done/DONE1.json"
run_tick "$Q"
chk "recheck_ts 도달 → due 재부상" '[ "$(fld "$Q" R1 .status)" = due ]' "$(fld "$Q" R1 .status)"
chk "recheck_ts 미도달 → waiting 유지" '[ "$(fld "$Q" R2 .status)" = waiting ]' "$(fld "$Q" R2 .status)"
chk "mq:<선행> 종결 → 자동 resume(in_progress)" '[ "$(fld "$Q" R3 .status)" = in_progress ]' "$(fld "$Q" R3 .status)"
chk "mq:<선행> 미종결 → waiting 유지" '[ "$(fld "$Q" R4 .status)" = waiting ]' "$(fld "$Q" R4 .status)"

echo "▶ tick start — 승인 기록 단일 지점 (Issue770)"
Q=$(newmq start); IB="$T/inbox-start"; mkdir -p "$IB"
put "$Q" S1 '"status":"due","message":"[컨펌] [H:스토어] prj16 x","wait_for":"잔재","recheck_ts":"2020-01-01T00:00:00"'
printf '{"question":"aoa-mq-ack:S1:start"}\n' > "$IB/s1.json"
AOA_MQ_INBOX_DIR="$IB" run_tick "$Q" --consume-only
chk "start → in_progress" '[ "$(fld "$Q" S1 .status)" = in_progress ]' "$(fld "$Q" S1 .status)"
chk "start → approved_by·approved_ts 기록" '[ -n "$(fld "$Q" S1 ".approved_ts // empty")" ] && [ -n "$(fld "$Q" S1 ".approved_by // empty")" ]'
chk "start → 대기 잔재 제거" '[ "$(fld "$Q" S1 ".wait_for // \"none\"")" = none ]'

echo "▶ tick 7.8 — 승인 술어·사람 차례·대기 제외·대상 cwd (Issue770)"
Q=$(newmq wake)
OLD='"started_at":"2026-01-01T00:00:00"'
put "$Q" K1 "\"status\":\"in_progress\",\"message\":\"[컨펌] [H:스토어] prj16 재촬영\",\"approved_ts\":\"2026-09-28T12:27:00\",\"approved_by\":\"human:/mq\",$OLD"
put "$Q" K2 "\"status\":\"in_progress\",\"message\":\"[컨펌] [H:배포] prj16 출고\",$OLD"
put "$Q" K3 "\"status\":\"in_progress\",\"message\":\"prj5 일반 작업\",\"needs_human\":[\"decide:문의처 통일\"],$OLD"
put "$Q" K5 "\"status\":\"in_progress\",\"message\":\"대상 표기 없는 작업\",\"source\":\"fbot-lead\",$OLD"
put "$Q" K6 "\"status\":\"in_progress\",\"message\":\"경로 없는 prj\",\"target\":\"prj7\",$OLD"
put "$Q" K7 "\"status\":\"in_progress\",\"message\":\"매핑 없는 명시 대상\",\"target\":\"prj8\",$OLD"
put "$Q" K4 "\"status\":\"waiting\",\"wait_from\":\"in_progress\",\"wait_for\":\"x\",\"recheck_ts\":\"2099-01-01T00:00:00\",\"message\":\"prj5 대기\",$OLD"
run_tick "$Q"
chk "[컨펌]+approved → 기동" 'grep -q "ID=K1" "$T/claude.log"' "$(cat "$T/claude.log")"
chk "기동 cwd = 대상 prj(prj16)" 'grep -q "CWD=$T/p16 ID=K1" "$T/claude.log"' "$(cat "$T/claude.log")"
chk "[컨펌] 미승인 → 제외" '! grep -q "ID=K2" "$T/claude.log"'
chk "사람 차례(needs_human) → 제외" '! grep -q "ID=K3" "$T/claude.log"'
chk "waiting → 7.8 제외" '! grep -q "ID=K4" "$T/claude.log"'
chk "기동 프롬프트 = 착수 승인 문구" 'grep -q "착수 승인" "$T/claude.log.prompt"'
chk "기동 프롬프트 = needs_human 규약" 'grep -q "needs_human" "$T/claude.log.prompt"'
chk "대상 미상 → 종전 기동 cwd(AOA_MQ_CWD)" 'grep -q "CWD=$T/home ID=K5" "$T/claude.log"' "$(cat "$T/claude.log")"
chk "대상 경로가 이 머신에 없으면 기동 안 함" '! grep -q "ID=K6" "$T/claude.log"'
chk "명시 target 매핑 없음 → 다른 곳으로 폴백 기동하지 않음" '! grep -q "ID=K7" "$T/claude.log"'
chk "기동 기록 woken_by=tick-7.8 · wake_count 1" '[ "$(fld "$Q" K1 .woken_by)" = tick-7.8 ] && [ "$(fld "$Q" K1 .wake_count)" = 1 ]'
chk "waiting 은 7.7 적체 집계 제외" '! grep -E "in_progress 적체 [0-9]+건/착수 4건" "$Q/tick.log" >/dev/null'

echo "▶ 사람 몫 needs_human — decide:/act: (Issue770)"
Q=$(newmq need)
put "$Q" N1 '"status":"in_progress","message":"x"'
P "$Q" need N1 --text "decide:문의처 통일(kr/en)" >/dev/null 2>&1
P "$Q" need N1 --text "act:jma 잠금 해제" >/dev/null 2>&1
P "$Q" need N1 --text "decide:문의처 통일(kr/en)" >/dev/null 2>&1
chk "need 2건 기록·중복 무시" '[ "$(fld "$Q" N1 ".needs_human|length")" = 2 ]' "$(fld "$Q" N1 ".needs_human|tostring")"
P "$Q" need N1 --text "접두 없는 항목" >/dev/null 2>&1; rc=$?
chk "접두(decide:/act:) 없으면 거부" '[ $rc -ne 0 ] && [ "$(fld "$Q" N1 ".needs_human|length")" = 2 ]'
P "$Q" need-done N1 --index 1 --by "human:/mq" >/dev/null 2>&1
chk "need-done → 목록에서 빠지고 이력에 남음" '[ "$(fld "$Q" N1 ".needs_human|length")" = 1 ] && [ "$(fld "$Q" N1 ".needs_human_done[0].item")" = "decide:문의처 통일(kr/en)" ]'

echo "▶ enqueue --target · reschedule 대기 정리 (Issue770)"
Q=$(newmq enq)
AOA_MQ_DIR="$Q" bash "$ENQ" --message "x" --due +1d --target prj16 >/dev/null 2>&1
f=$(ls "$Q/queue/"*.json 2>/dev/null | head -1)
chk "enqueue --target prj16 → target 필드" '[ -n "$f" ] && [ "$(jq -r .target "$f")" = prj16 ]'
AOA_MQ_DIR="$Q" bash "$ENQ" --message "x" --due +1d --target sixteen >/dev/null 2>&1; rc=$?
chk "--target 형식 오류 거부" '[ $rc -ne 0 ]'
AOA_MQ_DIR="$Q" bash "$ENQ" --message "x" --due +1d --target prj99 >/dev/null 2>&1; rc=$?
chk "--target 매핑 없는 번호 거부" '[ $rc -ne 0 ]'
put "$Q" RS '"status":"waiting","wait_from":"in_progress","wait_for":"x","recheck_ts":"2099-01-01T00:00:00","message":"x","due_ts":"2026-09-29T19:30:00"'
AOA_MQ_DIR="$Q" bash "$ENQ" --reschedule RS --due +1d >/dev/null 2>&1
chk "reschedule → pending + 대기 잔재 제거" '[ "$(fld "$Q" RS .status)" = pending ] && [ "$(fld "$Q" RS ".wait_for // \"none\"")" = none ]'

echo "▶ 락 규약 — 새 쓰기 명령도 .tick.lock 을 따른다 (Issue770)"
Q=$(newmq lock)
put "$Q" L1 '"status":"in_progress","message":"x"'
mkdir "$Q/.tick.lock"; printf '%s' "$$" > "$Q/.tick.lock.pid"      # 살아 있는 보유자(이 셸)
for c in "need L1 --text act:x" "wait L1 --for 조건" "need-done L1 --index 1"; do
  # shellcheck disable=SC2086
  AOA_MQ_LOCK_WAIT=1 P "$Q" $c >/dev/null 2>&1; rc=$?
  chk "락 보유 중 ${c%% *} → 거부(rc≠0)·무변경" '[ $rc -ne 0 ] && [ "$(fld "$Q" L1 .status)" = in_progress ] && [ "$(fld "$Q" L1 ".needs_human // \"none\"")" = none ]'
done
put "$Q" L2 '"status":"in_progress","target":"prj5","message":"x"'
AOA_MQ_LOCK_WAIT=1 P "$Q" retarget L2 --to prj3 >/dev/null 2>&1; rc=$?
chk "락 보유 중 retarget → 거부(rc≠0)·무변경 (Issue925)" '[ $rc -ne 0 ] && [ "$(fld "$Q" L2 .target)" = prj5 ]' "rc=$rc"
AOA_MQ_LOCK_HELD=1 P "$Q" need L1 --text "act:x" >/dev/null 2>&1; rc=$?
chk "tick 재진입(AOA_MQ_LOCK_HELD=1) → 통과" '[ $rc -eq 0 ] && [ "$(fld "$Q" L1 ".needs_human|length")" = 1 ]'
rmdir "$Q/.tick.lock"; rm -f "$Q/.tick.lock.pid"

echo "▶ 넛지 범위 — 내 prj 항목만 본문·claim, 타 prj 는 1줄 (Issue770 원인 ③)"
INBOX_HOOK="${AOA_MQ_INBOX_HOOK:-$HERE/../../hooks/session-inbox.sh}"
Q=$(newmq nudge)
put "$Q" X1 '"status":"in_progress","target":"prj16","message":"prj16 스토어 재촬영 X1본문"'
put "$Q" X2 '"status":"in_progress","target":"prj5","message":"prj5 작업 X2본문"'
put "$Q" X3 '"status":"in_progress","message":"대상 표기 없는 X3본문","source":"fbot-lead"'
put "$Q" X4 '"status":"waiting","target":"prj16","wait_for":"외부","recheck_ts":"2099-01-01T00:00:00","wait_from":"in_progress","message":"대기 X4본문"'
put "$Q" X5 '"status":"in_progress","target":"prj16","message":"[컨펌] [H:스토어] prj16 제출 X5본문","approved_ts":"2026-09-28T12:27:00","needs_human":["decide:문의처 통일(kr/en)"]'
nudge() { # $1=cwd $2=sid → stdout(hook 출력)
  printf '{"session_id":"%s","cwd":"%s","prompt":"x"}' "$2" "$1" \
    | env -u FBOT_ID -u ECC_SKIP_OBSERVE AOA_MQ_DIR="$Q" AOA_MQ_HOME="$HERE" AOA_MQ_CWD="$T/home" \
        SESSION_INBOX_ROOT="$T/inbox-none" SESSION_NUDGE_STATE="$T/nudge-state" bash "$INBOX_HOOK" 2>/dev/null
}   # SESSION_NUDGE_STATE — 넛지 «세션당 1회» 상태를 회차마다 새로(prj3#Issue779_4). 고정 sid 라 이전 실행 상태를 보면 생략된다
out=$(nudge "$T/p16" sid-a)
# claim 은 백그라운드 + 락 직렬화(1초 단위 재시도)라 여러 항목이면 몇 초 걸린다 — 최대 6초 대기
for _i in 1 2 3 4 5 6; do [ -n "$(fld "$Q" X1 ".claimed_by // empty")" ] && [ -n "$(fld "$Q" X5 ".claimed_by // empty")" ] && break; sleep 1; done
chk "내 prj(prj16) 항목 본문 주입" 'printf "%s" "$out" | grep -q "X1본문"' "$out"
chk "타 prj(prj5) 항목은 본문 미주입" '! printf "%s" "$out" | grep -q "X2본문"'
chk "타 prj 항목은 1줄 요약(다른 prj 진행 중 1건)" 'printf "%s" "$out" | grep -q "다른 prj 진행 중 1건"'
chk "대상 미상 항목은 종전대로 주입(유실 방지)" 'printf "%s" "$out" | grep -q "X3본문"'
chk "waiting 항목은 미주입" '! printf "%s" "$out" | grep -q "X4본문"'
chk "사람 몫(needs_human) 표시" 'printf "%s" "$out" | grep -q "decide:문의처 통일"'
chk "넛지 문구 = 착수 승인 규약" 'printf "%s" "$out" | grep -q "착수 승인"'
chk "넛지 문구 = needs_human 기록 규약" 'printf "%s" "$out" | grep -q "needs_human"'
chk "미종결 건수는 대기 제외(4건)" 'printf "%s" "$out" | grep -q "미종결 4건"' "$(printf "%s" "$out" | grep "미종결")"
chk "내 prj 항목만 claim" '[ "$(fld "$Q" X1 ".claimed_by // empty")" = session:sid-a ] && [ -z "$(fld "$Q" X2 ".claimed_by // empty")" ]' "X1=$(fld "$Q" X1 .claimed_by) X2=$(fld "$Q" X2 .claimed_by)"
out=$(nudge "$T/p16/sub" sid-b)
chk "하위 폴더 세션도 그 prj(가장 긴 접두)" 'printf "%s" "$out" | grep -q "X1본문"'
out=$(nudge "$T/p5" sid-c); sleep 1
chk "prj5 세션은 X2 만 본문·prj16 항목은 1줄" 'printf "%s" "$out" | grep -q "X2본문" && ! printf "%s" "$out" | grep -q "X1본문" && printf "%s" "$out" | grep -q "다른 prj 진행 중 2건"' "$out"

echo "▶ launch — 사람 클릭 즉시 기동 (Issue770 — hub [진행] 이 부른다)"
Q=$(newmq launch)
put "$Q" LA '"status":"in_progress","message":"[컨펌] [H:스토어] prj16 재촬영","approved_ts":"2026-09-28T12:27:00","approved_by":"human:/mq","started_at":"2026-09-28T12:27:00"'
put "$Q" LB '"status":"in_progress","message":"[컨펌] [H:배포] prj16 출고"'
put "$Q" LC '"status":"due","message":"prj16 아직 미착수"'
LX() { AOA_MQ_DIR="$Q" AOA_MQ_CWD="$T/home" AOA_MQ_CLAUDE_BIN="$T/fake-claude" AOA_MQ_HR_GATE="$T/fake-gate.py" \
         FAKE_CLAUDE_LOG="$T/claude.log" ${TEST_BASH:-bash} "$PROGRESS" launch "$@"; }
: > "$T/claude.log"; : > "$T/claude.log.prompt"
out=$(LX LA --dry-run 2>&1); rc=$?
chk "launch --dry-run → rc 0 · 대상 cwd·프롬프트 출력" '[ $rc -eq 0 ] && printf "%s" "$out" | grep -q "$T/p16" && printf "%s" "$out" | grep -q "착수 승인"' "rc=$rc $out"
chk "launch --dry-run → 실기동 없음·기록 없음" '[ ! -s "$T/claude.log" ] && [ -z "$(fld "$Q" LA ".woken_at // empty")" ]'
LX LA >/dev/null 2>&1; rc=$?; sleep 1
chk "launch → 대상 cwd 에서 기동" '[ $rc -eq 0 ] && grep -q "CWD=$T/p16 ID=LA" "$T/claude.log"' "rc=$rc $(cat "$T/claude.log")"
chk "launch → woken_by=launch · wake_count 1(7.8 과 공유)" '[ "$(fld "$Q" LA .woken_by)" = launch ] && [ "$(fld "$Q" LA .wake_count)" = 1 ]'
chk "launch 프롬프트 = 즉시 기동·착수 승인" 'grep -q "즉시 기동" "$T/claude.log.prompt" && grep -q "착수 승인" "$T/claude.log.prompt"'
LX LA >/dev/null 2>&1; rc=$?
chk "재클릭 쿨다운 → 거부(rc≠0)" '[ $rc -ne 0 ] && [ "$(fld "$Q" LA .wake_count)" = 1 ]' "rc=$rc"
LX LA --force >/dev/null 2>&1; rc=$?
chk "--force → 쿨다운 무시하고 기동" '[ $rc -eq 0 ] && [ "$(fld "$Q" LA .wake_count)" = 2 ]' "rc=$rc"
out=$(LX LB 2>&1); rc=$?
chk "[컨펌] 미승인 → 거부 + [진행] 재클릭 안내" '[ $rc -ne 0 ] && printf "%s" "$out" | grep -q "진행" && [ -z "$(fld "$Q" LB ".woken_at // empty")" ]' "rc=$rc $out"
LX LC >/dev/null 2>&1; rc=$?
chk "in_progress 아님 → 거부" '[ $rc -ne 0 ]'
printf 'allow_start_launch: false\n' >> "$Q/policy.yml"
LX LA --force >/dev/null 2>&1; rc=$?
chk "policy allow_start_launch=false → 거부" '[ $rc -ne 0 ] && [ "$(fld "$Q" LA .wake_count)" = 2 ]'
sed -i '' '/allow_start_launch/d' "$Q/policy.yml"
FAKE_GATE_RC=1 LX LA --force >/dev/null 2>&1; rc=$?
chk "HR 게이트 거부 → fail-closed(rc≠0)" '[ $rc -ne 0 ] && [ "$(fld "$Q" LA .wake_count)" = 2 ]'

echo "▶ MCP server — snooze 단일 경로·progress 인자·enqueue target (Issue770)"
mcp() { # $1=큐 $2=tool $3=arguments(json) → content text
  printf '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"%s","arguments":%s}}\n' "$2" "$3" \
    | AOA_MQ_DIR="$1" python3 "$HERE/server.py" 2>/dev/null | jq -r '.result.content[0].text // .error.message'
}
Q=$(newmq mcp)
put "$Q" M1 '"status":"due","message":"x","due_ts":"2099-01-01T19:30:00"'
out=$(mcp "$Q" aoa_mq_ack '{"id":"M1","status":"snoozed","snooze_days":1,"note":"외부 회신 대기"}')
chk "MCP snoozed → status=pending(snoozed 고착 아님)" '[ "$(fld "$Q" M1 .status)" = pending ]' "$out / $(fld "$Q" M1 .status)"
chk "MCP snoozed → 시각 보존(19:30 유지·+1일)" '[ "$(fld "$Q" M1 .due_ts)" = 2099-01-02T19:30:00 ]' "$(fld "$Q" M1 .due_ts)"
chk "MCP snoozed → 사유(note) 보존" 'fld "$Q" M1 ".progress // empty" | grep -q "외부 회신 대기"' "$(fld "$Q" M1 .progress)"
put "$Q" M2 '"status":"in_progress","message":"x"'
mcp "$Q" aoa_mq_progress '{"id":"M2","wait_for":"signup 재개","recheck":"+1d"}' >/dev/null
chk "MCP progress wait_for → waiting" '[ "$(fld "$Q" M2 .status)" = waiting ] && [ "$(fld "$Q" M2 .wait_for)" = "signup 재개" ]'
mcp "$Q" aoa_mq_progress '{"id":"M2","resume":true}' >/dev/null
chk "MCP progress resume → in_progress" '[ "$(fld "$Q" M2 .status)" = in_progress ]'
mcp "$Q" aoa_mq_progress '{"id":"M2","needs_human":"decide:문의처 통일"}' >/dev/null
chk "MCP progress needs_human → 추가" '[ "$(fld "$Q" M2 ".needs_human[0]")" = "decide:문의처 통일" ]'
out=$(mcp "$Q" aoa_mq_list '{}')
chk "MCP list → 사람 몫 표시" 'printf "%s" "$out" | grep -q "decide:문의처 통일"' "$out"
mcp "$Q" aoa_mq_progress '{"id":"M2","needs_human_done":"decide:문의처 통일"}' >/dev/null
chk "MCP progress needs_human_done → 해소" '[ "$(fld "$Q" M2 ".needs_human // [] | length")" = 0 ] && [ "$(fld "$Q" M2 ".needs_human_done | length")" = 1 ]'
out=$(AOA_MQ_PROJECTS_DIR="$PJ" mcp "$Q" aoa_mq_enqueue '{"message":"prj 지정","due":"+1d","target":"prj16"}')
f=$(grep -l '"prj 지정"' "$Q/queue/"*.json 2>/dev/null | head -1)
chk "MCP enqueue target → 필드 기록" '[ -n "$f" ] && [ "$(jq -r .target "$f")" = prj16 ]' "$out"

echo
echo "결과: 통과 $PASS · 실패 $FAIL"
[ "$FAIL" -eq 0 ]
