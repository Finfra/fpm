#!/usr/bin/env bash
# ⚠️ 글로벌 SCAR — 모든 프로젝트 공유. 즉흥 수정 금지(cwd ≠ ~/.claude/ 면 Issue.md 등록 후 처리)
#    절차: rules/global-scar-change-rules.md
# 🔒 집행: passive — 런타임 집행 없음. 보드 위젯 값 산출 전용(읽기 전용).
# 📚 분류: 사실 — registry.db `bot` 테이블 → hub 보드 위젯 값 사영기
#
# fbot-board-monitor.sh — `..board bots` 보드 monitor 스크립트 (Issue436_3 s6, 구현단계 5·7)
#
# 계약 (prj3 _doc_arch/board.md "### monitor 스크립트" · agents/fpm-board.md 2절):
#   * 단일 책임 — 위젯 1종당 stdout 산출. 인자로 위젯 종류를 구분한다
#   * read-only — registry.db 를 `mode=ro` URI 로만 연다. write/mkdir/rm 금지
#   * 명시적 실패 — 인자 누락·미지원 위젯·DB 부재·봇 0건이면 exit 1 (runner last_eval_rc != 0 → SPA stale)
#   * dynamic_eval 은 이 스크립트 경로만 호출한다 (inline shell 금지)
#   * runner 개조 금지 — 사영은 이 스크립트 + bots.dash.yaml 의 dynamic_eval 배선으로만 한다
#
# 사용:
#   fbot-board-monitor.sh summary   # → text 위젯 value (1줄 요약)
#   fbot-board-monitor.sh table     # → table 위젯 value (rows JSON 배열)
#
# 상태 표기는 s6 범위상 badge·이모지 (hub 위젯 스키마에 icon/color 필드 없음 — 커스텀 SVG 는 s7)
set -euo pipefail

WIDGET="${1:-}"
# DB 경로 knob 은 fbot-state.py·fbot-checkout.sh 와 **같은 env**(AOA_MEMORY_DIR)
# 경로 계약 (Issue450) — env 가 정식 설정. 미설정 시 제품 중립 기본(prj5 미클론 머신 대응).
AOA_DIR="${AOA_MEMORY_DIR:-$HOME/.claude/data/aoa}"
DB="$AOA_DIR/registry.db"

if [[ -z "$WIDGET" ]]; then
  echo "위젯 종류 인자 필요: summary|table" >&2
  exit 1
fi
case "$WIDGET" in
  summary|table) ;;
  *) echo "미등재 위젯 종류: '$WIDGET' (지원: summary|table)" >&2; exit 1 ;;
esac
if [[ ! -f "$DB" ]]; then
  echo "레지스트리 DB 없음: $DB (AOA_MEMORY_DIR 확인)" >&2
  exit 1
fi

exec python3 - "$DB" "$WIDGET" <<'PYTHON'
import json, sqlite3, sys, time

db, widget = sys.argv[1], sys.argv[2]

# 상태 저장값 → (이모지 badge, 한글 호칭). SSOT: _doc_arch/fbot-arch.md "저장 값 매핑"
STATE = {
    "working":       ("\U0001F7E2", "작업중"),
    "checkin":       ("\U0001F7E1", "출근중"),
    "waiting_input": ("⏳",     "수신대기"),
    "waiting_child": ("\U0001F535", "완료대기"),
    "checkout":      ("⬜",     "퇴근"),
}
ORDER = ["working", "checkin", "waiting_input", "waiting_child", "checkout"]
CAREER = {"probation": "수습", "active": "정식", "leave": "휴직", "terminated": "해고"}

try:
    con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
    rows = con.execute(
        "SELECT bot_id, title, role, state, career, current_task FROM bot"
    ).fetchall()
    con.close()
except sqlite3.Error as e:
    sys.stderr.write("registry.db 조회 실패: %s\n" % e)
    sys.exit(1)

if not rows:
    sys.stderr.write("등록된 봇 0건 — 데이터 부재\n")
    sys.exit(1)


def rank(state):
    return ORDER.index(state) if state in ORDER else len(ORDER)


rows.sort(key=lambda r: (rank(r[3]), r[1] or r[0]))

if widget == "summary":
    counts = {s: 0 for s in ORDER}
    unknown = 0
    for _, _, _, state, _, _ in rows:
        if state in counts:
            counts[state] += 1
        else:
            unknown += 1
    parts = ["%s%s %d" % (STATE[s][0], STATE[s][1], counts[s]) for s in ORDER]
    if unknown:
        parts.append("❓미등재 %d" % unknown)
    print("총 %d봇 · %s · %s 기준"
          % (len(rows), " · ".join(parts), time.strftime("%Y.%m.%d %H:%M:%S")))
    sys.exit(0)

# widget == "table" → rows JSON 배열 (columns 는 dash.yaml 이 소유)
out = []
for bot_id, title, role, state, career, current_task in rows:
    emoji, label = STATE.get(state, ("❓", "미등재:%s" % state))
    out.append([
        title or bot_id,
        role or "-",
        "%s %s" % (emoji, label),
        (current_task or "").strip() or "—",
        CAREER.get(career, career or "-"),
    ])
print(json.dumps(out, ensure_ascii=False))
PYTHON
