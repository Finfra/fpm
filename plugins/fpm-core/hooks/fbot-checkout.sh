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
  FBOT_DB="$DB" FBOT_HANDOFF="$HANDOFF" FBOT_EVENT="$input" \
  FBOT_SESSION_END_LIB="$_HOOKS_SELF/lib/session-end.py" FBOT_ORG_PY="$_HOOKS_SELF/fbot-org.py" python3 - <<'PY' || true
import importlib.util, json, os, sqlite3, time, uuid

db, handoff, bot = os.environ["FBOT_DB"], os.environ["FBOT_HANDOFF"], os.environ["FBOT_ID"]
now = int(time.time())
try:
    ev = json.loads(os.environ.get("FBOT_EVENT") or "{}")
except Exception:
    ev = {}

# prj3#Issue743 — 종료 사유. 종전엔 무조건 status='done' 이라 쿼터로 죽은 워커가 원장에
#   «정상 퇴근» 으로 남았다(2026-09-27 21:25 prj1 Issue550). 판정은 lib/session-end.py
#   단일 지점이 하고, 여기는 적기만 한다. 판정 불가(unknown)는 실패로 단정하지 않는다 — done 유지.
end = {"end_reason": "unknown"}
if ev.get("transcript_path"):
    # prj3#Issue951 — 미완 백그라운드는 실행직에만 치명이다. 비실행 관리직(총괄·팀장)의 백그라운드는 워커 대기 루프라
    #   세션을 failed 로 세지 않는다(HR fail_pct). 판정은 fbot-org `bot_nonexec` — 못 읽으면 실행직(종전 판정 그대로)
    bg_fatal = True
    try:
        _ospec = importlib.util.spec_from_file_location("fbot_org_co", os.environ["FBOT_ORG_PY"])
        _org = importlib.util.module_from_spec(_ospec)
        _ospec.loader.exec_module(_org)
        bg_fatal = not _org.bot_nonexec(bot)
    except Exception:
        pass
    try:
        _spec = importlib.util.spec_from_file_location("session_end", os.environ["FBOT_SESSION_END_LIB"])
        _mod = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        end = _mod.classify(ev["transcript_path"], bg_fatal=bg_fatal)
    except Exception:
        pass   # fail-soft — 판정 실패가 퇴근 기록을 막지 않는다
# prj3#Issue788_1 — 도구 왕복 도중 kill 된 세션(interrupted)도 failed — done 이면 sweep 이 배분을 닫는다
failed = end.get("end_reason") in ("quota", "api_error", "interrupted")
# prj3#Issue951 — `-p` 몸체가 미완 백그라운드를 남기고 끝내면 fbot-idle.sh 가 **Stop 시점**에 이 훅을 부른다(at_stop).
#   그 경로는 SessionEnd 퇴근 기록이 남지 않은 실측이 있어서다. SessionEnd 가 뒤이어 돌면 같은 세션을 두 번 적지 않는다
#   — 실패 세션 수가 두 배로 세지지 않게(세션 단위 1기록). at_stop 기록이 없는 세션은 종전 그대로다.
at_stop = os.environ.get("FBOT_CHECKOUT_AT_STOP") == "1"

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
        # prj3#Issue743 — API 오류(쿼터 등)로 끝난 세션은 'failed'. `done` 을 요구하는 소비처
        #   (sweep 완료 판정·세션 완료 통지)가 구조적으로 제외한다 — 소비처마다 거르지 않는다.
        cur = cx.execute("SELECT current_task FROM bot WHERE bot_id=?", (bot,)).fetchone()
        rec = {"bot_id": bot, "cwd": ev.get("cwd"), "session_id": ev.get("session_id"),
               "current_task": cur[0] if cur else None, "checkout_at": now,
               "end_reason": end.get("end_reason")}
        if failed:
            rec.update({k: end.get(k) for k in ("resets_at", "limit_type", "error", "message")})
        if at_stop:
            rec["at_stop"] = True
        dup = (not at_stop) and ev.get("session_id") and cx.execute(
            "SELECT 1 FROM job WHERE kind='fbot_session' AND owner=? AND json_extract(payload,'$.session_id')=?"
            " AND json_extract(payload,'$.at_stop')=1 LIMIT 1", (bot, str(ev["session_id"]))).fetchone()
        if not dup:
            cx.execute(
                "INSERT INTO job(id,store,kind,status,payload,result,attempts,owner,"
                "lease_until,blocked_since,created_at) VALUES(?,NULL,?,?,?,NULL,0,?,NULL,NULL,?)",
                ("fbotjob-%d-%s" % (now, uuid.uuid4().hex[:8]), "fbot_session",
                 "failed" if failed else "done", json.dumps(rec, ensure_ascii=False), bot, now))
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

# prj3#Issue644 ③ — 몸체가 끝났으니 이 봇 앞으로 걸린 **배분 잠금**을 비운다.
#   Issue555 의 `dispatch-claim` 에는 짝이 없었다 — 한 번 박힌 `spawned_by` 를 푸는 수단이
#   0개라, 이슈를 닫지 않고 끝난 세션이 그 워커를 향한 **이후 모든 스폰을 영구 차단**했다
#   (2026-09-19 실측: prj3 배분 3건 정지, `cancel` 우회로만 해소 — 예산 1 소모 + 원장 오염).
#   ⚠️ 순서가 의미를 만든다 — 위 transition 으로 **checkout 이 된 뒤** 불러야 한다.
#   해제는 "워커가 퇴근 상태" 일 때만 도는데(Issue555 회귀 방지), 그 조건을 세우는 것이
#   바로 앞 줄이다. 뒤집으면 매번 skipped 로 조용히 아무것도 안 한다.
#   fail-soft — 해제 실패가 퇴근을 막지 않는다. 못 풀린 잠금은 다음 claim 의 생사 판정(①)이 받는다.
[ -f "$STATE_PY" ] && python3 "$STATE_PY" dispatch-claim --release --worker "$FBOT_ID" \
  --by "checkout:${CLAUDE_CODE_SESSION_ID:-unknown}" >/dev/null 2>&1

# prj3#Issue748 — 퇴근 재기상. 몸체 실행 중 도착한 요청은 `send` 가 `alive` 로 기상을 건너뛰었고,
#   몸체는 `claude -p` 라 넛지가 닿지 않는다. 남았으면 퇴근 직후 다시 깨운다(다음 tick 30분 대기 제거).
#   판정(매니저·출근 후 도착분·잠금)은 fbot-inbox.py 단일 지점 — 여기는 부르기만 한다.
#   ⚠️ 분리 실행 — 전 몸체 창이 빌 때까지 기다리므로 SessionEnd 를 막으면 안 된다. checkout 전이 **뒤**여야 한다.
INBOX_PY="$_HOOKS_SELF/fbot-inbox.py"
[ -f "$INBOX_PY" ] && nohup python3 "$INBOX_PY" rewake --bot-id "$FBOT_ID" >/dev/null 2>&1 </dev/null &

# Issue442 — 세션 id 마커 회수. heartbeat 폴백이 읽는 캐시라 퇴근하면 의미가 없다.
#   남겨두면 UUID 이름 파일이 세션 수만큼 무한 누적된다(자기 상태 파일 — 규칙8 예외).
if [ -n "${CLAUDE_CODE_SESSION_ID:-}" ]; then
  # Issue549 — `.hb` 도 함께. 판정 재료가 둘인데 하나만 지우면 반쪽이다:
  #   `.id` 는 결속 조회용, `.hb` 는 heartbeat 스로틀용이라 남으면 퇴근한 봇이
  #   lease 를 되살린다. 불변은 "퇴근 = 마커 소멸".
  rm -f "$CLAUDE_DIR/.fbot-handoff/sid-$CLAUDE_CODE_SESSION_ID.id" \
        "$CLAUDE_DIR/.fbot-handoff/sid-$CLAUDE_CODE_SESSION_ID.hb" 2>/dev/null || true
fi

exit 0
