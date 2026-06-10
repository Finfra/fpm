#!/usr/bin/env bash
# fpm-dashboard-queue-runner.sh — dashboard 큐 모드 시각화 runner (Issue84, tmux 재설계 Tier 2)
#
# ⚠️ 글로벌 SCAR 변경 가드 (Issue46): 본 runner 는 모든 프로젝트가 공유. cwd ≠ ~/.claude
#   면 즉시 수정 금지 → ~/.claude/Issue.md 이슈 등록 후 처리. 설계 SSOT:
#   ~/.claude/_doc_arch/dashboard.md, ~/_git/___pm/_doc_arch/hub_dashboard_tmux_design.md
#   절차: ~/.claude/rules/global-scar-change-rules.md
#
# tmux window 의 runner pane 에서 실행됨. queue.yaml(supervisor 가 갱신하는 SSOT)을 읽어
# graph·progress·badge·text·log 위젯으로 시각화 → .dash.yaml write (파일 기반, HTTP 없음).
# 순수 모니터링 모드 runner(fpm-dashboard-runner.sh)와 별개.
#
# 환경변수 (필수):
#   QUEUE_FILE       queue.yaml 절대경로 (supervisor 와 공유 SSOT, 읽기 전용)
#   DATA_FILE        .dash.yaml 절대경로 (본 runner 가 write)
# 환경변수 (선택):
#   INTERVAL_ACTIVE  running 항목 존재 시 주기 초 (기본 3)
#   INTERVAL_IDLE    전부 대기/완료 시 주기 초 (기본 15)
#   SUPERVISOR_LOG   supervisor.log 경로 (log 위젯 tail 원본)
#   WIN_NAME         tmux window 이름 (데이터 전달용)
#
# 동작:
#   1) trap TERM/INT/HUP → status='stopped' 마킹 후 exit / USR1 → 즉시 refresh
#   2) loop: queue.yaml read → 위젯 구성 → .dash.yaml write (파일 기반)
#   3) queue.state ∈ {done,halted,removing} → status 마킹 후 자가 종료
#
# 설계: ~/_git/___pm/_doc_arch/hub_dashboard_tmux_design.md

set -uo pipefail

# board_policy.yml 로더 (Issue152) — 운영 상수 SSOT. 우선순위: env VAR > board_policy.yml > 인자 기본값.
BOARD_POLICY="${BOARD_POLICY:-${FPM_BASE:-$HOME/_git/___pm}/data/board_policy.yml}"
_bp() {  # _bp <key> <default>
  local v
  v=$(grep -E "^$1:[[:space:]]" "$BOARD_POLICY" 2>/dev/null | head -1 \
      | sed -E "s/^[^:]*:[[:space:]]*//; s/[[:space:]]*#.*$//; s/[[:space:]]*$//") || true
  printf '%s' "${v:-$2}"
}

INTERVAL_ACTIVE="${INTERVAL_ACTIVE:-$(_bp interval_active 3)}"
INTERVAL_IDLE="${INTERVAL_IDLE:-$(_bp interval_idle_runner 15)}"
: "${QUEUE_FILE:?QUEUE_FILE required}"
: "${DATA_FILE:?DATA_FILE required}"
SUPERVISOR_LOG="${SUPERVISOR_LOG:-}"

MY_PID=$$
ORIG_PPID=$PPID   # 부모(tmux pane shell) PID — orphan 자가 종료용

# queue.yaml → .dash.yaml 데이터(JSON) 구성. stdout: data JSON
build_data() {
  QF="$QUEUE_FILE" SLOG="$SUPERVISOR_LOG" PID="$MY_PID" ITER="$1" WIN_NAME="${WIN_NAME:-}" \
    python3 <<'PYEOF'
import json, os, datetime, yaml

qf = os.environ['QF']
try:
    q = yaml.safe_load(open(qf)) or {}
except Exception:
    q = {}
items = q.get('items', [])
TERMINAL = {'done', 'failed', 'skipped', 'withdrawn'}

# graph 위젯 — 이슈 DAG
nodes, edges = [], []
for it in items:
    label = 'prj%s #%s' % (it.get('prj', '?'), it.get('issue', '?'))
    node = {'id': it['id'], 'label': '%s · %s' % (it['id'], label),
            'status': it.get('status', 'blocked')}
    if it.get('detail_url'):
        node['action'] = {'link': it['detail_url']}
    nodes.append(node)
    for d in (it.get('depends') or []):
        edges.append({'from': d, 'to': it['id']})

# progress — done / total
total = len(items)
done = sum(1 for it in items if it.get('status') == 'done')
pct = int(done / total * 100) if total else 0

# 현재 running / waiting_input / waiting_approval 항목
running = [it for it in items if it.get('status') == 'running']
waiting = [it for it in items if it.get('status') == 'waiting_input']
waiting_approval = [it for it in items if it.get('status') == 'waiting_approval']
if running:
    cur = ', '.join('%s(prj%s #%s)' % (it['id'], it.get('prj'), it.get('issue')) for it in running)
elif waiting:
    cur = '⏸ 입력 대기: ' + ', '.join(it['id'] for it in waiting)
elif waiting_approval:
    cur = '🟠 승인 대기: ' + ', '.join(it['id'] for it in waiting_approval)
else:
    cur = '(없음)'

# Q&A 질문 위젯 (Issue102) — waiting_input item 의 question 필드를 사용자에게 노출.
#   worker 가 .waiting sentinel 에 질문을 적으면 supervisor 가 item.question 에 기록한다.
#   사용자가 답변 마커(<OUT_DIR>/.dash-answers/<topic>__<id>, 내용=답변)를 생성하면
#   supervisor ②.6 이 worker 를 재개시킨다 (상세: _doc_arch/dashboard.md Q&A 재개 프로토콜).
qa_lines = []
for it in waiting:
    qn = it.get('question')
    tag = '%s (prj%s #%s)' % (it['id'], it.get('prj', '?'), it.get('issue', '?'))
    if qn:
        qa_lines.append('❓ %s\n   %s' % (tag, qn))
    else:
        qa_lines.append('❓ %s\n   (질문 내용 미기록 — worker 가 .waiting 에 질문 누락)' % tag)
qa_content = '\n'.join(qa_lines) if qa_lines else '(입력 대기 중인 질문 없음)'

# badge — 큐 state + worker liveness
qstate = q.get('state', 'running')
badge_state = {'running': 'running', 'waiting_input': 'waiting',
               'done': 'done', 'halted': 'error', 'removing': 'warn'}.get(qstate, 'running')
# 승인 대기 item 이 있으면 badge 를 warn 으로 (사용자 액션 필요 — Issue89 T12-A)
if waiting_approval and badge_state == 'running':
    badge_state = 'warn'
badge_label = '%s · 실행 %d · 대기 %d' % (qstate, len(running), len(waiting))
if waiting_approval:
    badge_label += ' · 승인대기 %d' % len(waiting_approval)
# liveness 가드 (Issue98) — supervisor 가 stuck_since 를 기록하면 dash 에 stuck 배지 노출.
# 영구 정지가 'running' 으로 위장되던 UX 결함 차단.
stuck_since = q.get('stuck_since')
if stuck_since:
    badge_state = 'error'
    badge_label += ' · ⚠ STUCK (%s~ 상태 변화 없음)' % stuck_since

# log — supervisor.log tail
log_tail = ''
slog = os.environ.get('SLOG', '')
if slog and os.path.isfile(slog):
    try:
        with open(slog) as f:
            log_tail = ''.join(f.readlines()[-12:])
    except Exception:
        log_tail = '(supervisor.log 읽기 실패)'

all_terminal = bool(items) and all(it.get('status') in TERMINAL for it in items)
status = 'done' if (all_terminal or qstate in ('done', 'halted')) else 'running'

# 비용 모니터링 (Issue89 T12-B) — item별 started_at/ended_at(ISO, supervisor 기록) →
# elapsed 계산. table 위젯. 토큰 카운트는 범위 밖 — 시간·iteration 기반 추적만.
def _parse_iso(s):
    try:
        return datetime.datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None

def _fmt_elapsed(sec):
    sec = max(0, int(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return '%d:%02d:%02d' % (h, m, s) if h else '%d:%02d' % (m, s)

_now = datetime.datetime.now()
cost_rows, _starts, _ends = [], [], []
for it in items:
    st = _parse_iso(it.get('started_at'))
    en = _parse_iso(it.get('ended_at'))
    if st:
        _starts.append(st)
        elapsed = _fmt_elapsed(((en or _now) - st).total_seconds())
    else:
        elapsed = '-'
    if en:
        _ends.append(en)
    cost_rows.append([it['id'], it.get('status', ''),
                      it.get('started_at') or '-', it.get('ended_at') or '-', elapsed])
if _starts:
    _qend = max(_ends) if (_ends and all_terminal) else _now
    queue_elapsed = _fmt_elapsed((_qend - min(_starts)).total_seconds())
else:
    queue_elapsed = '-'

# window_name — 데이터 전달용 (tmux window 이름 표시)
wn = os.environ.get('WIN_NAME', '').strip()

data = {
    'title': q.get('title', 'queue'),
    'type': 'queue',
    'status': status,
    'pid': int(os.environ['PID']),
    'iter': int(os.environ['ITER']),
    'updated_at': datetime.datetime.now().isoformat(),
    'queue_state': qstate,
    # Issue140: 위젯 width/type authoring 보강 — graph→width:2(노드 겹침 회피),
    #   supervisor 로그→type:log+width:full(.w-log max-height 260+scroll, text 의 .w-value 세로폭발 회피),
    #   table(5컬럼)→width:2. 정본: ___pm board/README "## dashboard 위젯 레이아웃 규칙"
    #   (dynamic_eval 불요 — queue-runner 가 매 iter dash.yaml 통째 재생성하여 content 갱신)
    'widgets': [
        {'id': 'queue-graph', 'type': 'graph', 'title': '이슈 DAG', 'width': 2,
         'nodes': nodes, 'edges': edges},
        {'id': 'queue-progress', 'type': 'progress', 'title': '진행률',
         'value': pct, 'label': '%d/%d done' % (done, total)},
        {'id': 'queue-state', 'type': 'badge', 'title': '큐 상태',
         'label': badge_label, 'state': badge_state},
        {'id': 'queue-running', 'type': 'text', 'title': '현재 실행',
         'content': cur},
        {'id': 'queue-qa', 'type': 'text', 'title': '⏸ 입력 대기 질문 (Q&A)',
         'content': qa_content},
        {'id': 'queue-cost', 'type': 'table', 'title': '작업 소요 (큐 전체 %s)' % queue_elapsed,
         'width': 2,
         'columns': ['item', 'status', '시작', '종료', '소요'],
         'rows': cost_rows},
        {'id': 'supervisor-log', 'type': 'log', 'title': 'supervisor 로그', 'width': 'full',
         'content': log_tail or '(로그 없음)'},
    ],
}
if wn:
    data['window_name'] = wn
print(json.dumps(data))
PYEOF
}

write_data() {
  JSON="$1" python3 -c "
import yaml, json, os, sys
d = json.loads(os.environ['JSON'])
yaml.safe_dump(d, open(sys.argv[1], 'w'), allow_unicode=True, sort_keys=False)" "$DATA_FILE"
}

mark_status() {
  local new="$1" data
  data=$(build_data "${ITER:-0}")
  data=$(S="$new" python3 -c "
import json, os, sys, datetime
d = json.loads(sys.stdin.read())
d['status'] = os.environ['S']
if os.environ['S'] in ('stopped', 'done'):
    d['stopped_at'] = datetime.datetime.now().isoformat()
print(json.dumps(d))" <<< "$data")
  write_data "$data"
}

cleanup() {
  mark_status stopped
  echo "[queue-runner] stopped at $(date -Iseconds)" >&2
  exit 0
}

refresh_signal() {
  if [ -n "${SLEEP_PID:-}" ]; then
    kill "$SLEEP_PID" 2>/dev/null
    echo "[queue-runner] SIGUSR1 → refresh" >&2
  fi
}

trap cleanup TERM INT HUP
trap refresh_signal USR1

echo "[queue-runner] PID=$MY_PID start at $(date -Iseconds)"
echo "[queue-runner] QUEUE_FILE=$QUEUE_FILE DATA_FILE=$DATA_FILE"

ITER=0
while true; do
  ITER=$((ITER + 1))

  # 부모(tmux pane shell) 사망 → 자가 종료 (HUP trap 누락 fallback)
  if ! kill -0 "$ORIG_PPID" 2>/dev/null; then
    echo "[queue-runner] parent pid=$ORIG_PPID dead, self-terminating" >&2
    cleanup
  fi

  DATA=$(build_data "$ITER")
  write_data "$DATA"

  QSTATE=$(printf '%s' "$DATA" | python3 -c "import json,sys; print(json.loads(sys.stdin.read()).get('queue_state',''))")
  RUN_STATUS=$(printf '%s' "$DATA" | python3 -c "import json,sys; print(json.loads(sys.stdin.read()).get('status',''))")
  echo "[queue-runner] iter=$ITER queue_state=$QSTATE status=$RUN_STATUS"

  # 큐 종료 → runner 자가 종료 (Issue81 패턴 — queue.state 키)
  case "$QSTATE" in
    done|halted|removing)
      echo "[queue-runner] queue_state=$QSTATE → status='done', exiting" >&2
      mark_status "done"
      exit 0
      ;;
  esac

  # 적응형 sleep (Phase 0 #4) — running 항목 있으면 active
  if printf '%s' "$DATA" | grep -q '"status": *"running"' && \
     printf '%s' "$DATA" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); w=[x for x in d.get('widgets',[]) if x.get('id')=='queue-running']; sys.exit(0 if w and w[0].get('content','(없음)')!='(없음)' else 1)"; then
    SLEEP_SECS="$INTERVAL_ACTIVE"
  else
    SLEEP_SECS="$INTERVAL_IDLE"
  fi
  sleep "$SLEEP_SECS" &
  SLEEP_PID=$!
  wait "$SLEEP_PID" 2>/dev/null
  SLEEP_PID=""
done
