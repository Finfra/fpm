#!/usr/bin/env bash
# fbot-checkout.sh — SessionEnd hook 모듈 (matcher: 없음 · dispatch-sessionend.sh 자식), Issue436_3
#
# ⚠️ 글로벌 SCAR 변경 가드 (Issue46): 본 hook 은 모든 프로젝트가 공유.
#   cwd ≠ ~/.claude 면 즉시 수정 금지 → ~/.claude/Issue.md 이슈 등록 후 처리.
#   배선 색인: ~/.claude/_doc_arch/hook-arch.md · 절차: ~/.claude/_doc_arch/rules-ondemand/hook-rules.md
#
# 발동: env **FBOT_ID 가 있을 때만** (계약 fbot-arch.md §출퇴근 훅 F2).
#       퇴근 절차 = 봇별 상태 저장(registry.kv ns=fbot:{id}) → 작업 기록 append(registry.job)
#       → state:checkout.
# no-op: FBOT_ID 부재(= 일반 세션) → 첫 줄에서 즉시 exit 0. 부작용 0.
#
# fail-soft (규칙4): DB·헬퍼 부재 시 조용히 건너뛴다. 턴 종료를 막지 않는다.
#
# ⚠️ Stop 은 **턴 종료**마다 돈다(세션 종료 전용 이벤트가 아니다 — 그쪽은 SessionEnd).
#   계약 §출퇴근 훅이 배선 지점을 Stop 으로 명시했으므로 그대로 따른다. 결과적으로
#   퇴근 기록·상태 저장은 **턴 단위로 갱신**된다(마지막 값이 곧 최신 상태라 멱등).
#
# 상태 저장의 입력 — `~/.claude/.fbot-handoff/{bot_id}.json`
#   훅은 세션 내부 맥락을 볼 수 없다. 그래서 봇(세션)이 남기고 싶은 상태를 이 파일에
#   객체로 써 두면 퇴근 시 kv 로 flush 한다. 자기가 쓰고 자기가 읽는 파일이라 hook 간
#   순서 의존이 아니다(규칙8 예외). 🚧 파일 규약 정식화는 s5 매뉴얼 절과 함께.

set -uo pipefail

[ -n "${FBOT_ID:-}" ] || exit 0          # ← 규칙3 무비용 가드

input=$(cat)

CLAUDE_DIR="$HOME/.claude"
# DB 경로 knob 은 fbot-state.py 와 **같은 env**(AOA_MEMORY_DIR) — 훅과 헬퍼가 서로 다른
#   DB 를 보면 상태와 kv 가 조용히 갈라진다.
# 경로 계약 (Issue450) — env 가 정식 설정. 미설정 시 제품 중립 기본(prj5 미클론 머신 대응).
DB="${AOA_MEMORY_DIR:-$HOME/.claude/data/aoa}/registry.db"
# 형제 hook 경로 (Issue460 — Issue451 과 같은 결함이 남아 있던 자리)
#   소비자는 SCAR 를 **플러그인**으로 받으므로 `~/.claude/hooks` 가 존재하지 않는다.
#   훅 자체는 플러그인 경로에서 정상 발화하는데(env·매뉴얼 주입까지 성공) 그 안에서
#   부르는 헬퍼만 `~/.claude/hooks` 를 가리켜 **조용히 실패**했다 — fg1 실측:
#   `SID`·`FBOT_ID` 는 정상 도착하는데 `bind`·`transition` 이 안 먹어 결속·전이가 0.
#   자기 위치가 곧 형제들의 위치다. 개발 머신(prj3)에서도 같은 값이 나온다.
_HOOKS_SELF="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
STATE_PY="$_HOOKS_SELF/fbot-state.py"
HANDOFF="$CLAUDE_DIR/.fbot-handoff/$FBOT_ID.json"

# kv flush + 작업 기록 append 를 **python3 1회**로 묶는다.
#   따로 돌리면 프로세스 기동(~40ms)을 두 번 물고, SQL 문자열 이스케이프를 셸에서
#   손으로 하게 되어 주입 위험이 생긴다. 파라미터 바인딩이 있는 쪽으로 모은다.
if [ -f "$DB" ]; then
  FBOT_DB="$DB" FBOT_HANDOFF="$HANDOFF" FBOT_EVENT="$input" python3 - <<'PY' || true
import json, os, sqlite3, time, uuid

db, handoff, bot = os.environ["FBOT_DB"], os.environ["FBOT_HANDOFF"], os.environ["FBOT_ID"]
now = int(time.time())
try:
    ev = json.loads(os.environ.get("FBOT_EVENT") or "{}")
except Exception:
    ev = {}

# 봇이 남긴 인계 상태(있으면) + 훅이 관측 가능한 세션 메타
pairs = {}
try:
    with open(handoff, encoding="utf-8") as f:
        d = json.load(f)
    if isinstance(d, dict):
        pairs = {str(k): (v if isinstance(v, str) else json.dumps(v, ensure_ascii=False))
                 for k, v in d.items()}
except Exception:
    pass
pairs["last_checkout_at"] = str(now)
if ev.get("session_id"): pairs["last_session_id"] = str(ev["session_id"])
if ev.get("cwd"):        pairs["last_cwd"] = str(ev["cwd"])

ns = "fbot:%s" % bot
try:
    cx = sqlite3.connect(db, timeout=3)
    cx.execute("PRAGMA busy_timeout=3000")
    with cx:
        cx.executemany(
            "INSERT INTO kv(ns,key,value,expires_at,updated_at,updated_by) VALUES(?,?,?,NULL,?,?) "
            "ON CONFLICT(ns,key) DO UPDATE SET value=excluded.value, "
            "updated_at=excluded.updated_at, updated_by=excluded.updated_by",
            [(ns, k, v, now, bot) for k, v in pairs.items()])
        # 작업 기록 (F4 — 잡 원장 귀속은 owner=bot_id). status='done' 으로 넣어
        # worker 의 pending 리스를 타지 않게 한다(큐가 아니라 원장 용도).
        cur = cx.execute("SELECT current_task FROM bot WHERE bot_id=?", (bot,)).fetchone()
        cx.execute(
            "INSERT INTO job(id,store,kind,status,payload,result,attempts,owner,"
            "lease_until,blocked_since,created_at) VALUES(?,NULL,?,?,?,NULL,0,?,NULL,NULL,?)",
            ("fbotjob-%d-%s" % (now, uuid.uuid4().hex[:8]), "fbot_session", "done",
             json.dumps({"bot_id": bot, "cwd": ev.get("cwd"),
                         "session_id": ev.get("session_id"),
                         "current_task": cur[0] if cur else None,
                         "checkout_at": now}, ensure_ascii=False), bot, now))
    cx.close()
except Exception:
    pass   # fail-soft — 기록 실패가 턴 종료를 막지 않는다

# flush 된 인계 파일은 지운다 — 다음 세션이 낡은 값을 다시 올리지 않게
try:
    os.remove(handoff)
except OSError:
    pass
PY
fi

# 상태 전이는 단일 지점 경유(규칙5). 헬퍼 부재 시 no-op.
[ -f "$STATE_PY" ] && python3 "$STATE_PY" transition --bot-id "$FBOT_ID" --to checkout >/dev/null 2>&1

# Issue442 — 세션 id 마커 회수. heartbeat 폴백이 읽는 캐시라 퇴근하면 의미가 없다.
#   남겨두면 UUID 이름 파일이 세션 수만큼 무한 누적된다(자기 상태 파일 — 규칙8 예외).
if [ -n "${CLAUDE_CODE_SESSION_ID:-}" ]; then
  rm -f "$CLAUDE_DIR/.fbot-handoff/sid-$CLAUDE_CODE_SESSION_ID.id" 2>/dev/null || true
fi

exit 0
