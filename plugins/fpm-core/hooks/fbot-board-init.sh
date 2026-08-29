#!/usr/bin/env bash
# ⚠️ 글로벌 SCAR — 모든 프로젝트 공유. 즉흥 수정 금지(cwd ≠ ~/.claude/ 면 Issue.md 등록 후 처리)
#    절차: rules/global-scar-change-rules.md
# 🔒 집행: advisory — `_bots` window 중복 기동을 **검출해 안내**한다. tmux 조작은 하지 않는다(사용자·board agent 소관)
# 📚 분류: 사실 — `..board bots` 보드 data 파일(bots.dash.yaml) 템플릿 생성기
#
# fbot-board-init.sh — `..board bots` 보드 data 파일 준비 (Issue436_3 s6, 구현단계 5·6)
#
# 계약 (prj3 _doc_arch/board.md §자원·경로 / §data 파일 스키마 / §주기 모니터링 패턴):
#   * 순수 모니터링 모드 = **`worker_pid` 키 생략**(무한 heartbeat). `null` 명시 금지 — Issue142
#   * 위젯 `dynamic_eval` 은 monitor 스크립트 **경로만** 호출(inline shell 금지) — agents/fpm-board.md 2절
#   * **전역 싱글턴** — 고정 OUT_DIR(`~/.claude/_doc_work/htm/`). cwd 무관하게 항상 같은 파일을 쓴다
#   * 멱등 — 2회 실행 시 산출 sha 동일(기존 `started_at` 보존, 템플릿 동일하면 무변경 no-op)
#   * runner 개조 금지 — DB 사영은 monitor 스크립트 + 아래 dynamic_eval 배선으로만 이뤄진다
#
# 사용: fbot-board-init.sh [--force]
#   --force : runner 가동(status=running + pid 생존) 중이어도 덮어쓴다
set -euo pipefail

FORCE=0
[[ "${1:-}" == "--force" ]] && FORCE=1

TOPIC="bots"
OUT_DIR="$HOME/.claude/_doc_work/htm"          # 전역 싱글턴 — cwd 무관 고정
DATA_FILE="$OUT_DIR/${TOPIC}.dash.yaml"
# 형제 hook 경로 (Issue460 — Issue451 과 같은 결함이 남아 있던 자리)
#   소비자는 SCAR 를 **플러그인**으로 받으므로 `~/.claude/hooks` 가 존재하지 않는다.
#   훅 자체는 플러그인 경로에서 정상 발화하는데(env·매뉴얼 주입까지 성공) 그 안에서
#   부르는 헬퍼만 `~/.claude/hooks` 를 가리켜 **조용히 실패**했다 — fg1 실측:
#   `SID`·`FBOT_ID` 는 정상 도착하는데 `bind`·`transition` 이 안 먹어 결속·전이가 0.
#   자기 위치가 곧 형제들의 위치다. 개발 머신(prj3)에서도 같은 값이 나온다.
_HOOKS_SELF="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
MONITOR="$_HOOKS_SELF/fbot-board-monitor.sh"
INTERVAL="${FBOT_BOARD_INTERVAL:-10}"          # sec — 사용자 명시 우선(board_policy interval_default=5 상회)

if [[ ! -x "$MONITOR" ]]; then
  echo "monitor 스크립트 없음·비실행: $MONITOR" >&2
  exit 1
fi
mkdir -p "$OUT_DIR"

python3 - "$DATA_FILE" "$TOPIC" "$INTERVAL" "$FORCE" <<'PYTHON'
import os, sys, time, yaml

data_file, topic, interval, force = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4] == "1"

old = {}
if os.path.exists(data_file):
    with open(data_file) as f:
        old = yaml.safe_load(f) or {}

# runner 가동 중 보호 — status=running + pid 생존이면 --force 없이는 덮어쓰지 않는다
pid = old.get("pid")
live = old.get("status") == "running" and isinstance(pid, int)
if live:
    try:
        os.kill(pid, 0)
    except OSError:
        live = False
if live and not force:
    print("SKIP  runner 가동 중(pid=%s) — 덮어쓰지 않음. 강제하려면 --force" % pid)
    sys.exit(0)

# dynamic_eval 은 monitor 스크립트 경로 호출만. $HOME 상대화(개인 경로 하드코딩 금지)
mon = '$HOME/.claude/hooks/fbot-board-monitor.sh'
doc = {
    "title": topic,
    # ⚠️ **`running` 이 아니다** (Issue455, 2026-08-29). init 은 data 파일만 준비하고
    #   runner 는 사용자가 `..board bots` 를 입력할 때 뜬다 — 그 사이를 `running` 으로
    #   적으면 **거짓 running 카드**가 된다(실사고: 08-25 12:00 mtime 에 status=running·
    #   pid=null 인 파일이 hub 에서 가동 중으로 렌더).
    #   내부 모순도 있었다 — 아래 `pid: None` 은 위 덮어쓰기 보호 조건
    #   (`status=="running" and isinstance(pid,int)`)을 **구조적으로 만족할 수 없다**.
    #   자기가 만든 파일이 자기 보호를 못 받는 상태였다.
    # ⚠️ 값은 계약 3종(`running|stopped|done` — board.md L110) 안에서 고른다.
    #   `pending` 은 계약 밖이라 소비처 아이콘·판정이 정의돼 있지 않다.
    # ⚠️ 수용측 완화(prj1#Issue403 mtime 강등)로 대체하지 않은 이유 — 그쪽은 **늙은 것**을
    #   잡는 장치이고 여기는 **처음부터 틀린 것**이라 성격이 다르다. 갓 만든 파일은
    #   mtime 이 새것이라 그 강등에 걸리지 않는다.
    "status": "stopped",
    # 기존 값 보존 → 재실행 멱등(sha 동일)
    "started_at": old.get("started_at") or time.strftime("%Y-%m-%dT%H:%M:%S"),
    "pid": None,
    # worker_pid 키는 **생략** = infinite heartbeat (board.md Issue142 — null 명시 금지)
    "worker_interval": None,
    "window_name": None,
    "interval": interval,
    "controls": {"stop": True, "kill_pane": True, "refresh": True},
    "commands": [],
    "widgets": [
        {
            "type": "text",
            "title": "핀봇 현황 요약",
            "width": "full",
            "value": "",
            "dynamic_eval": 'bash "%s" summary' % mon,
        },
        {
            "type": "table",
            "title": "핀봇 명부 (호칭·role·상태·현재 작업·career)",
            "width": 2,
            "columns": ["호칭", "role", "상태", "현재 작업", "career"],
            "rows": [],
            "dynamic_eval": 'bash "%s" table' % mon,
        },
    ],
}

new = yaml.dump(doc, allow_unicode=True, sort_keys=False)
cur = open(data_file).read() if os.path.exists(data_file) else None
if cur == new:
    print("OK    변경 없음(멱등): %s" % data_file)
else:
    tmp = data_file + ".tmp"
    with open(tmp, "w") as f:
        f.write(new)
    os.replace(tmp, data_file)          # atomic write
    print("OK    %s: %s" % ("갱신" if cur is not None else "생성", data_file))
PYTHON

# ── 전역 싱글턴 안내 (검출만 — tmux 조작 금지) ────────────────────────────────
WIN="_${TOPIC}"
if command -v tmux >/dev/null 2>&1 && tmux list-windows -a -F '#{window_name}' 2>/dev/null | grep -qx "$WIN"; then
  echo "GUARD '$WIN' window 이미 존재 — **재사용**하라(중복 기동 금지). 새 window 를 만들지 말 것"
else
  echo "GUARD '$WIN' window 없음 — '..board ${TOPIC}' 로 신규 기동 가능(board agent 소관)"
fi
echo "NEXT  '..board ${TOPIC}' 실행. data=$DATA_FILE interval=${INTERVAL}s (무한 heartbeat — worker_pid 키 없음)"
