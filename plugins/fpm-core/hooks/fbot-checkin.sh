#!/usr/bin/env bash
# fbot-checkin.sh — SessionStart hook 모듈 (matcher: 없음 · dispatch-sessionstart.sh 자식), Issue436_3
#
# ⚠️ 글로벌 SCAR 변경 가드 (Issue46): 본 hook 은 모든 프로젝트가 공유.
#   cwd ≠ ~/.claude 면 즉시 수정 금지 → ~/.claude/Issue.md 이슈 등록 후 처리.
#   배선 색인: ~/.claude/_doc_arch/hook-arch.md · 절차: ~/.claude/_doc_arch/rules-ondemand/hook-rules.md
#
# 발동: 스폰 시 기동 파라미터로 주입된 env **FBOT_ID 가 있을 때만** (계약 fbot-arch.md §출퇴근 훅 F2).
#       출근 절차 = state:checkin → 종류(role)별 매뉴얼 주입 → kv 복원(ns=fbot:{id}) → state:working.
# no-op: FBOT_ID 부재(= 일반 세션) → 첫 줄에서 즉시 exit 0. 레지스트리 역조회로 봇 여부를
#        추정하지 않는다(오인 판정 방지 — 계약 F2 명문).
#
# fail-soft (규칙4): DB·상태 헬퍼·매뉴얼이 없어도 조용히 건너뛴다. 출근이 안 되는 것보다
#   세션이 안 뜨는 것이 나쁘다. 데이터 유실 위험이 없는 경로라 loud 로 만들지 않는다.
#
# ⚠️ 상태 전이는 hooks/fbot-state.py 단일 지점을 경유한다(규칙5). 여기서 bot.state 를
#   직접 UPDATE 하지 않는다 — 판정이 두 곳으로 갈라지는 순간 상태가 어긋난다.
#   읽기(role·kv)는 sqlite3 직접 조회다. MCP 는 훅에서 호출할 수 없다(서버 왕복 = 예산 초과).

set -uo pipefail

[ -n "${FBOT_ID:-}" ] || exit 0          # ← 규칙3 무비용 가드. 이 앞에 어떤 프로세스도 두지 않는다

CLAUDE_DIR="$HOME/.claude"
# DB 경로 knob 은 fbot-state.py·fbot-tick.sh 와 **같은 env**(AOA_MEMORY_DIR)를 쓴다 —
#   훅과 헬퍼가 서로 다른 DB 를 보면 상태와 kv 가 조용히 갈라진다.
DB="${AOA_MEMORY_DIR:-$HOME/_git/___common/data/aoa}/registry.db"
STATE_PY="$CLAUDE_DIR/hooks/fbot-state.py"
# 🚧 매뉴얼 경로 규약은 s5 확정 대기(fbot-arch.md 미해결 표). 그때까지 데이터 자산 규약
#    (`~/.claude/data/fbot/`)을 따르고, 파일이 없으면 조용히 건너뛴다.
MANUAL_DIR="${FBOT_MANUAL_DIR:-$CLAUDE_DIR/data/fbot/manuals}"

# 상태 헬퍼는 다른 워커가 소유한다. 부재 시 전이는 건너뛰되 매뉴얼·kv 주입은 계속한다.
fbot_state() { [ -f "$STATE_PY" ] || return 0; python3 "$STATE_PY" "$@" >/dev/null 2>&1 || true; }

fbot_state transition --bot-id "$FBOT_ID" --to checkin

# --- role 판정: 스폰 env 우선, 없으면 레지스트리 1회 조회 -------------------
sql_esc() { printf '%s' "${1//\'/\'\'}"; }        # SQL 문자열 리터럴 이스케이프
# ⚠️ `-readonly` 를 쓰지 않는다. registry.db 는 **WAL** 이라, 다른 접속이 없어 `-shm` 이
#   없는 순간에 readonly 로 열면 "unable to open database file (14)" 로 실패한다(실측).
#   그러면 매뉴얼·kv 복원이 조용히 빈 값이 된다 — 침묵 실패가 더 나쁘다. 대신 SELECT 만
#   쓰고 busy_timeout 으로 워커 쓰기와의 경합을 흡수한다.
q() { sqlite3 -cmd ".timeout 2000" "$DB" "$1" 2>/dev/null || true; }
ID_SQL="$(sql_esc "$FBOT_ID")"
role="${FBOT_ROLE:-}"
if [ -z "$role" ] && [ -f "$DB" ]; then
  role=$(q "SELECT role FROM bot WHERE bot_id='$ID_SQL';")
fi

# --- 매뉴얼 (부재 시 skip — 계약: "부재면 skip") ---------------------------
manual=""
if [ -n "$role" ] && [ -r "$MANUAL_DIR/$role.md" ]; then
  manual=$(cat "$MANUAL_DIR/$role.md" 2>/dev/null || true)
fi

# --- 봇별 상태 복원 (registry.kv ns=fbot:{id}) ------------------------------
# 만료된 키는 제외한다. -json 으로 뽑아 손실 없이 그대로 넘긴다(값에 개행이 있어도 안전).
kv=""
if [ -f "$DB" ]; then
  kv=$(sqlite3 -cmd ".timeout 2000" -json "$DB" \
    "SELECT key, value FROM kv WHERE ns='fbot:$ID_SQL'
       AND (expires_at IS NULL OR expires_at > strftime('%s','now')) ORDER BY key;" 2>/dev/null || true)
  [ "$kv" = "[]" ] && kv=""
fi

# --- 등록 여부 판정 (QA 발견 C — 유령 봇 위장 출근 차단) -----------------------
# 미등록 bot_id 에 정상 출근 컨텍스트를 주입하면 세션이 허위 상태("작업중")를 믿는다.
# fail-soft 는 유지하되(세션은 안 깨짐) 문구로 명확히 구분한다. 전이도 등록 시에만.
registered=""
[ -f "$DB" ] && registered=$(q "SELECT 1 FROM bot WHERE bot_id='$ID_SQL' LIMIT 1;")

if [ -z "$registered" ]; then
  ctx="[⚠️ 핀봇 출근 실패 — $FBOT_ID 는 레지스트리 **미등록**]

이 세션은 핀봇으로 등록되지 않았다 — 상태 전이·기록 귀속·매뉴얼 주입은 수행되지 않는다.
채용(등록)이 먼저다 — python3 ~/.claude/hooks/fbot-state.py register --bot-id $FBOT_ID --role {role} --title {호칭} (계약: _doc_arch/fbot-arch.md §호출 경계 — 미등록 role 채용 불가)"
  CTX="$ctx" jq -n --arg ev SessionStart '{hookSpecificOutput:{hookEventName:$ev, additionalContext: env.CTX}}' 2>/dev/null || printf '%s\n' "$ctx"
  exit 0
fi

fbot_state transition --bot-id "$FBOT_ID" --to working

# --- 컨텍스트 조립 ----------------------------------------------------------
ctx="[핀봇 출근 — $FBOT_ID${role:+ (role: $role)}]

이 세션은 핀봇 **$FBOT_ID** 의 런타임 몸체다. 상태: 작업중(working).
기록·책임은 세션이 아니라 봇 이름에 귀속된다(계약: _doc_arch/fbot-arch.md)."
[ -n "$manual" ] && ctx="$ctx

## 작업 매뉴얼 ($role)

$manual"
[ -n "$kv" ] && ctx="$ctx

## 복원된 봇별 상태 (registry.kv ns=\`fbot:$FBOT_ID\`)

\`\`\`json
$kv
\`\`\`"

out=$(CTX="$ctx" jq -n --arg ev SessionStart \
  '{hookSpecificOutput:{hookEventName:$ev, additionalContext:env.CTX}}' 2>/dev/null)
# jq 부재·인코딩 실패 시에도 출근 사실을 잃지 않는다(fail-soft — 평문도 컨텍스트로 읽힌다)
printf '%s\n' "${out:-$ctx}"
exit 0
