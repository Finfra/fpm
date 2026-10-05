#!/usr/bin/env bash
# fpm-board-queue-runner.test.sh — board-queue-widget-authoring 회귀 픽스처 (Issue727 · Issue140)
#
# ⚠️ 글로벌 SCAR 변경 가드 (Issue46): 본 테스트는 모든 프로젝트가 공유. cwd ≠ ~/.claude
#   면 즉시 수정 금지 → ~/.claude/Issue.md 이슈 등록 후 처리. 설계 SSOT:
#   ~/.claude/_doc_arch/board.md. 절차: ~/.claude/rules/global-scar-change-rules.md
#
# 회귀 차단 — (1) queue-runner 가 생성한 dash.yaml 이 위젯 레이아웃 규칙(Issue140)을 지킨다:
#   graph→width≥2 · supervisor 로그→type:log+width:full · table→width:2. 규칙 정본은
#   ___pm board/README "## dashboard 위젯 레이아웃 규칙".
#   (2) 기동 시 register-doc 은 BOARD_HUB_URL 로 간다 — 운영 hub(9876) 무접촉 (Issue727 격리).
# 실행: bash ~/.claude/agents/fpm-board-queue-runner.test.sh
#   BOARD_QUEUE_RUNNER=<경로> 로 대상 스크립트를 바꿀 수 있다 (red 확인용 변형본)

set -uo pipefail
SELFDIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
SUT="${BOARD_QUEUE_RUNNER:-$SELFDIR/fpm-board-queue-runner.sh}"
# shellcheck source=/dev/null
source "$SELFDIR/fpm-board-test-lib.sh"

export BOARD_POLICY="$TL_TMP/none.policy.yml"
hub_stub_start "$TL_TMP/hub.log" || exit 1
export BOARD_HUB_URL="$HUB_STUB_URL"

QF="$TL_TMP/q.yaml"
DF="$TL_TMP/wq.dash.yaml"
SLOG="$TL_TMP/wq.supervisor.log"
printf '[sv] line1\n[sv] line2\n' > "$SLOG"
# state=done → runner 가 1 iter 로 dash.yaml 을 쓰고 자가 종료한다
cat > "$QF" <<'YAML'
title: widget-authoring
state: done
items:
- id: a
  prj: 1
  issue: 10
  status: done
  started_at: '2026-09-27T10:00:00'
  ended_at: '2026-09-27T10:05:00'
- id: b
  prj: 3
  issue: 20
  status: done
  depends: [a]
YAML

QUEUE_FILE="$QF" DATA_FILE="$DF" SUPERVISOR_LOG="$SLOG" WIN_NAME=_wq \
  INTERVAL_ACTIVE=0.2 INTERVAL_IDLE=0.2 bash "$SUT" > "$TL_TMP/qr.log" 2>&1 &
QR=$!
tl_track "$QR"
if ! wait_until 10 dead "$QR"; then
  ng "queue-runner 가 state=done 큐에서 자가 종료하지 않음"
fi

w() { yget "$DF" "next((x for x in d.get('widgets', []) if x.get('id') == '$1'), {}).get('$2')"; }

echo "[widget-authoring] 레이아웃 규칙 (Issue140)"
check "graph 위젯 type"          "graph" "$(w queue-graph type)"
gw=$(w queue-graph width)
if [[ "$gw" =~ ^[0-9]+$ ]] && [ "$gw" -ge 2 ]; then ok "graph width ≥ 2 ($gw)"; else ng "graph width ≥ 2 (실제 [$gw])"; fi
check "supervisor 로그 type=log"  "log"   "$(w supervisor-log type)"
check "supervisor 로그 width=full" "full" "$(w supervisor-log width)"
check "table(소요) type"          "table" "$(w queue-cost type)"
check "table(소요) width=2"       "2"     "$(w queue-cost width)"
check "graph 간선 a→b"            "a>b"   "$(yget "$DF" "'|'.join(e['from']+'>'+e['to'] for e in next(x for x in d['widgets'] if x['id']=='queue-graph')['edges'])")"
check "로그 위젯이 supervisor.log tail 을 싣는다" "yes" \
  "$(yget "$DF" "'yes' if 'line2' in next(x for x in d['widgets'] if x['id']=='supervisor-log')['content'] else 'no'")"
check "완주 큐 → status=done"     "done"  "$(yget "$DF" "d.get('status')")"

echo "[isolation] hub 등록 경로"
if grep -q '^/register-doc .*"title": "wq"' "$TL_TMP/hub.log"; then
  ok "register-doc → 주입한 BOARD_HUB_URL 스텁 수신 (title=basename)"
else
  ng "register-doc 이 BOARD_HUB_URL 로 오지 않음 (운영 hub 로 샜을 수 있음)"
fi

echo
echo "결과: PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ] || exit 1
