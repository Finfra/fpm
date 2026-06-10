#!/usr/bin/env bash
# fpm-dashboard-supervisor.sh — dashboard 큐 모드 DAG 구동 daemon (Issue84)
#
# ⚠️ 글로벌 SCAR 변경 가드 (Issue46): 본 daemon 은 모든 프로젝트가 공유. cwd ≠ ~/.claude
#   면 즉시 수정 금지 → ~/.claude/Issue.md 이슈 등록 후 처리. 설계 SSOT:
#   ~/.claude/_doc_arch/dashboard.md. 절차: ~/.claude/rules/global-scar-change-rules.md
#
# tmux window 의 supervisor pane 에서 실행됨. queue.yaml(런타임 SSOT)을 위상 스케줄로 구동:
# blocked→ready 승격 → send-keys 로 worker 명령 주입 → capture-pane + sentinel 파일로 완료 감지 → cursor 진행.
# Claude 메인 세션과 독립 생존 (tmux daemon). Issue100(파일 sentinel) 기반.
#
# 환경변수 (필수):
#   QUEUE_FILE   queue.yaml 절대경로 (런타임 SSOT)
#   TOPIC        dashboard topic 식별자
# 환경변수 (선택):
#   OUT_DIR          산출물 디렉토리 (기본: QUEUE_FILE 의 dir)
#   SESSION          tmux 세션 (기본: pm)
#   WINDOW           tmux window 이름 (기본: dash-<TOPIC>)
#   INTERVAL_ACTIVE  worker busy 시 poll 주기 초 (기본: 3) — Phase 0 #4 적응형
#   INTERVAL_IDLE    전부 idle/대기 시 poll 주기 초 (기본: 20)
#   MAX_ATTEMPTS     항목당 최대 디스패치 시도 (기본: 2)
#   NOSENT_STRIKES   idle-무sentinel 연속 N회 시 재시도/failed (기본: 10 — Issue101 D6
#                    장기 작업 보호로 상향. worker_busy 가 장기 Bash 대기를 busy 로
#                    잡으므로 strike 는 진짜 idle 에만 누적되나, 여유를 크게 둔다.)
#   WORKER_CMD       worker pane 에서 기동할 명령 (기본: claude) — Phase 6 합성 하니스
#                    검증용 테스트 훅. 기본값은 실제 claude 세션 (Issue89 T11-harness).
#   STUCK_SECS       상태 변화 0 이 이 초 이상 지속되면 stuck 자가 진단 (기본: 600, Issue98)
#   SENTINEL_DIR     worker 완료 sentinel 파일 디렉토리 (기본: /tmp/___pm/<sid>.sentinel, Issue100)
#   SID              sentinel 격리 키 (기본: md5(QUEUE_FILE)[:12], Issue100)
#
# 종료:
#   - SIGTERM/INT  → 로그 남기고 exit (queue.yaml 보존 — 재기동 시 running→ready resume)
#   - SIGUSR2      → graceful 제거 프로토콜 (Phase 0 #1: send-keys 중단 지시 → withdraw-report → window kill)
#   - 큐 전부 terminal → state=done 후 exit
#
# 설계: ~/_git/___pm/_doc_arch/hub_dashboard_tmux_design.md (tmux 파일 기반)
# 클라이언트: ~/.claude/_doc_arch/dashboard.md

set -uo pipefail

# bash 4+ 필수 — declare -A(연관배열) 사용. macOS 기본 /bin/bash 는 3.2 (Issue88 H6).
# shebang 을 #!/usr/bin/env bash 로 두어 PATH 상 Homebrew bash(5.x)를 우선 선택하되,
# 그래도 3.2 면 fail-loud 종료 (자동 우회 금지 — opus-4-7-execution-rules 재시도 정책).
if [ "${BASH_VERSINFO:-0}" -lt 4 ]; then
  echo "[supervisor] FATAL: bash 4+ 필요 (declare -A) — 현재 버전 ${BASH_VERSION:-unknown}." \
       "Homebrew bash 설치(brew install bash) 후 PATH 우선순위를 확인하세요." >&2
  exit 1
fi

# board_policy.yml 로더 (Issue152) — 운영 상수 SSOT. 우선순위: env VAR > board_policy.yml > 인자 기본값.
#   flat `key: value` 만 grep 파싱 (yq 불요). 정책 파일·키 부재 시 인자 기본값으로 무해 fallback.
BOARD_POLICY="${BOARD_POLICY:-${FPM_BASE:-$HOME/_git/___pm}/data/board_policy.yml}"
_bp() {  # _bp <key> <default>
  local v
  v=$(grep -E "^$1:[[:space:]]" "$BOARD_POLICY" 2>/dev/null | head -1 \
      | sed -E "s/^[^:]*:[[:space:]]*//; s/[[:space:]]*#.*$//; s/[[:space:]]*$//") || true
  printf '%s' "${v:-$2}"
}

QUEUE_FILE="${QUEUE_FILE:?QUEUE_FILE required}"
TOPIC="${TOPIC:?TOPIC required}"
OUT_DIR="${OUT_DIR:-$(dirname "$QUEUE_FILE")}"
SESSION="${SESSION:-pm}"
WINDOW="${WINDOW:-dash-$TOPIC}"
INTERVAL_ACTIVE="${INTERVAL_ACTIVE:-$(_bp interval_active 3)}"
INTERVAL_IDLE="${INTERVAL_IDLE:-$(_bp interval_idle_supervisor 20)}"
MAX_ATTEMPTS="${MAX_ATTEMPTS:-$(_bp max_attempts 2)}"
NOSENT_STRIKES="${NOSENT_STRIKES:-$(_bp nosent_strikes 10)}"
STUCK_SECS="${STUCK_SECS:-$(_bp stuck_secs 600)}"

LOG_FILE="$OUT_DIR/$TOPIC.supervisor.log"
WORKERS_FILE="$OUT_DIR/$TOPIC.workers"          # 런타임 worker 맵: "<prj> <pane_id>" 줄
WITHDRAW_REPORT="$OUT_DIR/$TOPIC.withdraw-report.md"
APPROVAL_DIR="$OUT_DIR/.dash-approvals"          # T12-A 승인 마커 디렉토리 (<topic>__<id>)
ANSWERS_DIR="$OUT_DIR/.dash-answers"             # Issue102 Q&A 답변 마커 디렉토리 (<topic>__<id>, 내용=답변)
PROJECTS_DIR="$HOME/_git/___pm/projects"
MY_PID=$$
ORIG_PPID=$PPID   # Issue120: 부모(tmux pane) PID — orphan guard 기준
# sentinel 파일 디렉토리 — 완료 감지를 파일 기반으로 구현. 동시 실행 대시보드 간 격리는
#   SID(=md5(QUEUE_FILE)[:12])로 수행. SID는 HTTP session ID가 아니라 파일 격리키.
#   worker가 sentinel 파일을 기록하면 supervisor가 폴링함.
SID="${SID:-$(python3 -c 'import hashlib,sys; print(hashlib.md5(sys.argv[1].encode()).hexdigest()[:12])' "$QUEUE_FILE")}"
SENTINEL_DIR="${SENTINEL_DIR:-$(_bp sentinel_base /tmp/___pm)/${SID}.sentinel}"

mkdir -p "$OUT_DIR" "$APPROVAL_DIR" "$ANSWERS_DIR" "$SENTINEL_DIR"
: > "$WORKERS_FILE"

# ===== sentinel · busy 규약 SSOT =====
# 완료 권위 = 파일 sentinel (Issue100 D5). worker 가 Bash 로 기록한
#   <SENTINEL_DIR>/<topic>.<id>.{done,waiting,withdrawn} 파일을 supervisor 가 폴링한다.
#   구 방식(capture-pane 텍스트 스캔 + detect_sentinel regex)은 worker Claude TUI 가
#   완료신호 안의 꺾쇠 토큰을 HTML 태그로 렌더·스트립하고, capture 40줄 truncation·
#   공백 변동에 취약해 근본 폐기 — Issue96 D2(공백 허용 regex)·Issue98 D4 는 이 깨진
#   전제 위의 미봉책이었다.
# 아래 2곳이 sentinel 파일 규약을 공유한다 — 한쪽만 바꾸면 worker↔supervisor 모순:
#   1. send_prompt()      — worker 에게 sentinel 파일을 기록하라고 지시 (.done/.waiting)
#   2. detect_sentinel()  — sentinel 파일 존재·내용을 폴링
#   .done 파일 형식: 'DONE\t<rc>\t<result>' 한 줄(탭 구분). .waiting/.withdrawn 은 존재만 의미.
# busy 판정·capture-pane 은 보조 — 크래시 감지·idle strike 누적용. 완료 권위 아님.
# busy/idle 판정 (Issue101 D6): busy 마커 열거가 아니라 idle 상태 명시 검출의 부정.
#   idle claude TUI 는 빈 입력창 박스(꺾쇠 테두리 ╭╰ + 프롬프트 ❯)와 권한 모드 푸터
#   ⏵⏵ 를 표시하고 작업 상태 문자열이 없다 → worker_idle = IDLE_BOX_RE 존재 AND
#   BUSY_RE 부재. worker_busy = NOT worker_idle (worker_ready 도 IDLE_BOX_RE 공유).
#   BUSY_RE 에 'Waiting…'·'shells still running' 포함 — 장기 Bash 대기(sleep 150 류)
#   상태를 idle 로 오판해 조기 no-sentinel 실패하던 버그 (Issue101 D6). 스피너
#   글리프(✻✶✳)는 idle 요약 줄('✻ Cogitated for Ns')에도 busy 줄('✻ Crunched')에도
#   등장 → 단독 매칭 금지, 어느 RE 에도 미포함 (Issue98 D4 회귀 방지).
IDLE_BOX_RE='╭|╰|❯|⏵⏵'
BUSY_RE='esc to interrupt|esc 로 중단|Running…|Waiting…|shells? still running|tokens·'

log() { printf '%s [supervisor] %s\n' "$(date '+%H:%M:%S')" "$*" >> "$LOG_FILE"; }

# ===== queue.yaml python 헬퍼 =====
# qpy <op> [args...] — queue.yaml 읽기/조작. op 별 stdout 규약은 아래 PYEOF 주석 참조.
qpy() {
  QF="$QUEUE_FILE" python3 - "$@" <<'PYEOF'
import sys, os, re, datetime, yaml
qf = os.environ['QF']

def load():
    try:
        with open(qf) as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}

def save(q):
    tmp = qf + '.tmp'
    with open(tmp, 'w') as f:
        yaml.safe_dump(q, f, allow_unicode=True, sort_keys=False)
    os.replace(tmp, qf)

TERMINAL = {'done', 'failed', 'skipped', 'withdrawn'}
op = sys.argv[1]
a = sys.argv[2:]
q = load()
items = q.get('items', [])
by_id = {it['id']: it for it in items}

if op == 'meta':
    # stdout: "<state>|<on_fail>|<concurrency>|<title>"
    print('%s|%s|%s|%s' % (q.get('state', 'running'), q.get('on_fail', 'continue'),
                           q.get('concurrency', 1), q.get('title', '')))

elif op == 'set-state':
    q['state'] = a[0]
    save(q)

elif op == 'set-supervisor-pid':
    # set-supervisor-pid <pid> — 최상위 supervisor_pid 기록 (content-authoritative pid).
    # 서버 /control remove 가 queue.yaml → .dash.yaml 경유로 추출 (Issue88 C1).
    # 변경 없으면 save 생략 — 매 iter 호출되므로 첫 iter 외엔 no-op write.
    pid = int(a[0])
    if q.get('supervisor_pid') != pid:
        q['supervisor_pid'] = pid
        save(q)

elif op == 'state-sig':
    # 상태 시그니처 — 모든 item 의 status·attempts + 큐 state 를 이어붙임.
    # liveness 가드(Issue98)가 iteration 간 상태 변화 유무를 비교하는 데 사용.
    print('|'.join('%s:%s:%s' % (it.get('id'), it.get('status'), it.get('attempts', 0))
                    for it in items) + '#' + str(q.get('state', '')))

elif op == 'set-stuck':
    # set-stuck <iso|null> — 최상위 stuck_since 기록 (liveness 가드, Issue98 방지대책).
    # queue-runner build_data() 가 읽어 dash 에 stuck 배지 노출. 변경 시에만 save.
    nv = None if a[0] == 'null' else a[0]
    if q.get('stuck_since') != nv:
        q['stuck_since'] = nv
        save(q)

elif op == 'promote':
    # blocked 항목: depends 전부 done → ready 승격. stdout: 승격된 id 공백구분
    promoted = []
    for it in items:
        if it.get('status') == 'blocked':
            deps = it.get('depends') or []
            if all(by_id.get(d, {}).get('status') == 'done' for d in deps):
                it['status'] = 'ready'
                promoted.append(it['id'])
    if promoted:
        save(q)
    print(' '.join(promoted))

elif op == 'list':
    # list <status> → "<id>|<prj>|<issue>|<attempts>" 줄
    for it in items:
        if it.get('status') == a[0]:
            print('%s|%s|%s|%s' % (it['id'], it.get('prj', ''),
                                   it.get('issue', ''), it.get('attempts', 0)))

elif op == 'mark':
    # mark <id> <status> — running 마킹 시 attempts++.
    # Issue89 T12-B: running 첫 진입 시 started_at, terminal 진입 시 ended_at(ISO) 기록.
    it = by_id.get(a[0])
    if it is not None:
        it['status'] = a[1]
        now_iso = datetime.datetime.now().isoformat(timespec='seconds')
        if a[1] == 'running':
            it['attempts'] = int(it.get('attempts', 0)) + 1
            if not it.get('started_at'):
                it['started_at'] = now_iso
        if a[1] in TERMINAL and not it.get('ended_at'):
            it['ended_at'] = now_iso
        save(q)

elif op == 'resume':
    # resume <id> — waiting_input → running 복귀, attempts 미증가 (Q&A 재개, Issue102).
    #   Q&A 일시정지는 디스패치 시도가 아니므로 mark 와 달리 attempts 를 보존한다.
    it = by_id.get(a[0])
    if it is not None:
        it['status'] = 'running'
        save(q)

elif op == 'needs-approval':
    # needs-approval <id> — Issue89 T12-A 승인 게이트.
    # 'yes' = approval 필드 truthy + 아직 approved 안 됨. 그 외 'no'.
    it = by_id.get(a[0])
    print('yes' if (it and it.get('approval') and not it.get('approved')) else 'no')

elif op == 'set':
    # set <id> <field> <value> — value 가 정수면 int, 'null'이면 None
    it = by_id.get(a[0])
    if it is not None:
        v = a[2]
        if v == 'null':
            v = None
        elif re.fullmatch(r'-?\d+', v):
            v = int(v)
        it[a[1]] = v
        save(q)

elif op == 'get':
    # get <id> <field>
    it = by_id.get(a[0])
    print('' if it is None else ('' if it.get(a[1]) is None else it.get(a[1])))

elif op == 'wrapped-prompt':
    # wrapped-prompt <id> — prompt 의 {{<dep>.result}} 를 선행 result 로 치환
    it = by_id.get(a[0])
    if it is not None:
        p = it.get('prompt', '')
        def sub(m):
            dep = by_id.get(m.group(1), {})
            return str(dep.get('result') or '')
        print(re.sub(r'\{\{(\w+)\.result\}\}', sub, p))

elif op == 'all-terminal':
    print('yes' if items and all(it.get('status') in TERMINAL for it in items) else 'no')

elif op == 'counts':
    # "<running> <ready> <blocked> <waiting> <terminal> <total>"
    c = {'running': 0, 'ready': 0, 'blocked': 0, 'waiting_input': 0, 'term': 0}
    for it in items:
        s = it.get('status')
        if s in TERMINAL:
            c['term'] += 1
        elif s in c:
            c[s] += 1
    print('%d %d %d %d %d %d' % (c['running'], c['ready'], c['blocked'],
                                 c['waiting_input'], c['term'], len(items)))

elif op == 'cycle-check':
    # Kahn 위상 정렬로 사이클 검출. stdout: "ok" 또는 "cycle"
    indeg = {it['id']: 0 for it in items}
    adj = {it['id']: [] for it in items}
    for it in items:
        for d in (it.get('depends') or []):
            if d in adj:
                adj[d].append(it['id'])
                indeg[it['id']] += 1
    queue = [i for i, d in indeg.items() if d == 0]
    seen = 0
    while queue:
        n = queue.pop()
        seen += 1
        for m in adj[n]:
            indeg[m] -= 1
            if indeg[m] == 0:
                queue.append(m)
    print('ok' if seen == len(items) else 'cycle')

elif op == 'reset-running':
    # 재기동 resume: running/waiting_input → ready 되돌림
    changed = False
    for it in items:
        if it.get('status') in ('running', 'waiting_input'):
            it['status'] = 'ready'
            changed = True
    if changed:
        save(q)

elif op == 'running-prj':
    # prj 번호로 현재 running/waiting_input 항목 id 찾기 (per-prj 1 worker 전제)
    for it in items:
        if it.get('status') in ('running', 'waiting_input') and str(it.get('prj')) == a[0]:
            print(it['id'])
            break
PYEOF
}

# ===== prj / worker 관리 =====

prj_cwd() {
  # prj 번호 → cwd 절대경로 (없으면 rc 1)
  local f="$PROJECTS_DIR/$1" p
  [ -f "$f" ] || return 1
  p=$(tr -d '[:space:]' < "$f")
  [ -n "$p" ] || return 1
  eval printf '%s' "$p"   # ~ 확장
}

worker_pane() {
  # prj → pane_id (WORKERS_FILE 에서). 없으면 빈 출력
  awk -v p="$1" '$1==p {print $2; exit}' "$WORKERS_FILE" 2>/dev/null
}

worker_spawn() {
  # prj worker pane lazy 생성 + worker 기동 (기본 claude, WORKER_CMD 로 override 가능)
  local prj="$1" cwd pid
  cwd=$(prj_cwd "$prj") || { log "prj$prj cwd 해석 실패 — 디스패치 보류"; return 1; }
  pid=$(tmux split-window -t "$SESSION:$WINDOW" -c "$cwd" -P -F '#{pane_id}' 2>/dev/null) || {
    log "prj$prj worker pane 생성 실패 (tmux)"; return 1; }
  tmux select-pane -t "$pid" -T "worker@prj$prj" 2>/dev/null
  tmux select-layout -t "$SESSION:$WINDOW" tiled 2>/dev/null
  # WORKER_CMD: 기본 claude. Phase 6 합성 하니스 검증 시 가짜 worker 스크립트 주입 (Issue89).
  tmux send-keys -t "$pid" "${WORKER_CMD:-claude}" Enter 2>/dev/null
  printf '%s %s\n' "$prj" "$pid" >> "$WORKERS_FILE"
  log "worker@prj$prj 생성 pane=$pid cwd=$cwd (${WORKER_CMD:-claude} 기동)"
  return 0
}

worker_capture() {
  # prj worker pane 의 마지막 40줄 capture. pane 소멸 시 rc 1
  local pane
  pane=$(worker_pane "$1")
  [ -n "$pane" ] || return 1
  tmux capture-pane -p -t "$pane" 2>/dev/null | tail -40
}

worker_busy() {
  # capture 텍스트($1)로 busy 판정. 0=busy, 1=idle. busy = NOT idle (Issue101 D6).
  # Issue101 D6: busy 마커 열거의 부정이 아니라 idle 상태 명시 검출의 부정으로 재설계.
  #   장기 Bash 대기(sleep 150 류 — TUI 가 'Waiting…'·'N shell still running'·
  #   '✻ Crunched' 표시)를 idle 로 오판해 조기 no-sentinel 실패하던 버그. Issue98 D4 가
  #   ✻✶✳ 글리프를 BUSY_RE 에서 단순 제거하며 장기 Bash 대기까지 미검출이 된 게 직접 원인.
  # idle 정의: 빈 입력창 박스 마커(IDLE_BOX_RE) 존재 AND busy 마커(BUSY_RE) 부재.
  #   그 외(박스 없음=부팅중/welcome, 또는 busy 마커 존재)는 모두 busy 로 본다.
  local cap="$1"
  if printf '%s' "$cap" | grep -qE "$IDLE_BOX_RE" \
     && ! printf '%s' "$cap" | grep -qE "$BUSY_RE"; then
    return 1   # idle — 빈 입력창 + busy 마커 없음
  fi
  return 0     # busy — 박스 없음(부팅) 또는 busy 마커 존재
}

worker_ready() {
  # capture 텍스트($1)로 claude TUI 입력 준비(ready) 판정. 0=ready, 1=아직 부팅중.
  # Issue96 D1: worker_spawn 직후 실 claude TUI 부팅(welcome 화면→입력창)이 디스패치보다
  #   느리면 send-keys Enter 가 유실되어 프롬프트가 미제출로 박힌다. 입력창 마커가
  #   나타날 때까지 디스패치를 보류한다 (고정 sleep 대신 ready 폴링).
  # 마커: 입력창 박스 테두리 '╭'·'╰', 프롬프트 '❯', 권한 모드 푸터 '⏵⏵' (IDLE_BOX_RE 공유).
  # 합성 하니스(WORKER_CMD≠claude)는 즉시 부팅 — ready 게이트 불필요.
  [ "${WORKER_CMD:-claude}" != "claude" ] && return 0
  printf '%s' "$1" | grep -qE "$IDLE_BOX_RE" && return 0
  return 1
}

worker_drop() {
  # WORKERS_FILE 에서 prj 항목 제거
  local prj="$1" tmp="$WORKERS_FILE.tmp"
  grep -v "^$prj " "$WORKERS_FILE" > "$tmp" 2>/dev/null
  mv "$tmp" "$WORKERS_FILE"
}

sentinel_clear() {
  # item id 의 sentinel 파일(.done/.waiting/.withdrawn) 일괄 제거 (Issue100).
  #   소비 직후·재디스패치 직전 호출 — 직전 attempt 의 잔존 파일 오감지 차단.
  rm -f "$SENTINEL_DIR/$TOPIC.$1.done" "$SENTINEL_DIR/$TOPIC.$1.waiting" \
        "$SENTINEL_DIR/$TOPIC.$1.withdrawn"
}

detect_sentinel() {
  # $1=item-id → stdout 한 줄:
  #   "DONE <rc>\t<result>"  — .done 파일. rc·result 는 파일 내용에서 파싱
  #   "WAITING\t<질문>" / "WITHDRAWN" / "" (없음)
  # Issue100 D5: capture-pane 텍스트 스캔(구 regex)을 폐기하고 파일 sentinel 을 폴링한다.
  #   worker 가 Bash 로 기록한 <SENTINEL_DIR>/<topic>.<id>.{done,waiting,withdrawn} 파일이
  #   완료 권위. 파일 쓰기는 worker 의 실제 액션 → TUI 마크다운 렌더(꺾쇠 토큰 HTML 스트립)·
  #   capture 40줄 truncation·공백 변동 전부 무관하게 결정적.
  # 우선순위: .done > .withdrawn > .waiting — worker 가 입력 대기(.waiting) 후 재개·완료
  #   하면 .done 이 생기므로 .done 이 .waiting 을 이긴다.
  local id="$1" base raw rc res
  base="$SENTINEL_DIR/$TOPIC.$id"
  if [ -f "$base.done" ]; then
    # .done 파일 형식: 'DONE\t<rc>\t<result>' 한 줄(탭 구분). 마지막 비어있지 않은 줄 사용.
    raw=$(grep -v '^[[:space:]]*$' "$base.done" 2>/dev/null | tail -1)
    [ -n "$raw" ] || return 0          # 파일 생성됐으나 아직 미기록 — 다음 폴링 대기
    rc=$(printf '%s' "$raw" | cut -f2 | grep -oE '[0-9]+' | head -1)
    res=$(printf '%s' "$raw" | cut -f3-)
    printf 'DONE %s\t%s\n' "${rc:-0}" "$res"
    return 0
  fi
  [ -f "$base.withdrawn" ] && { echo "WITHDRAWN"; return 0; }
  if [ -f "$base.waiting" ]; then
    # .waiting 파일 형식: 'WAITING' 또는 'WAITING\t<질문 한 줄>' (Issue102 Q&A 질문 캡처).
    #   worker 가 입력 필요 시 질문을 탭 뒤에 적는다. 질문을 그대로 동봉해 반환.
    raw=$(grep -v '^[[:space:]]*$' "$base.waiting" 2>/dev/null | tail -1)
    res=$(printf '%s' "$raw" | cut -f2-)
    [ "$res" = "$raw" ] && res=""        # 탭 없음 → cut 가 전체 반환 → 질문 없음
    printf 'WAITING\t%s\n' "$res"
    return 0
  fi
  return 0
}

send_prompt() {
  # prj worker pane 에 작업 프롬프트 주입. 완료 보고는 파일 sentinel (Issue100).
  local prj="$1" id="$2" base wrapped pane done_file wait_file
  pane=$(worker_pane "$prj"); [ -n "$pane" ] || return 1
  base=$(qpy wrapped-prompt "$id")
  done_file="$SENTINEL_DIR/$TOPIC.$id.done"
  wait_file="$SENTINEL_DIR/$TOPIC.$id.waiting"
  # 재디스패치 대비 stale sentinel 제거 — 직전 attempt 의 .done 잔존 시 즉시 오감지 차단.
  sentinel_clear "$id"
  # Issue100 D5: 완료 신호를 capture-pane 텍스트로 출력하라는 구 지시를 폐기. worker
  #   Claude TUI 가 꺾쇠 토큰을 HTML 태그로 렌더·스트립해 capture 에 '<>' 만 남던 근본
  #   결함 → worker 가 Bash 로 sentinel 파일을 기록하게 한다. 파일 쓰기는 실제 액션이라
  #   TUI 렌더·40줄 truncation·공백 변동과 무관하게 결정적. 합성 하니스(WORKER_CMD)도
  #   동일 지시·동일 파일 경로를 받으므로 fixture 와 실 worker 동작이 갈리지 않는다.
  #   프롬프트에 literal 경로·명령이 들어가도 supervisor 는 파일만 폴링하므로 false
  #   positive 없음 (구 방식의 토큰 오인 제약이 사라짐).
  wrapped="[dashboard 큐 작업 — item $id]

$base

---
이 작업의 완료는 **파일 sentinel** 로 보고합니다 (화면 출력이 아니라 파일 기록).
작업을 모두 끝내면 Bash 로 아래 명령을 정확히 1회 실행하세요:
  · 성공 시: printf 'DONE\\t0\\t<결과 한 줄 요약>\\n' > '$done_file'
  · 실패 시: printf 'DONE\\t<0이외 종료코드>\\t<실패 사유 요약>\\n' > '$done_file'
  - 필드는 탭(\\t) 구분 3개: DONE / 종료코드 / 결과요약. 결과요약은 한 줄로 짧게
    (커밋 해시·핵심 결론 등) — 후속 큐 항목이 이 요약을 참조합니다.
작업 도중 사용자 입력·결정이 필요해 멈춰야 할 때는 완료 파일 대신 아래를 1회
실행하세요 (WAITING 다음에 탭으로 구분해 사용자에게 할 질문을 한 줄로 적습니다):
  printf 'WAITING\\t<사용자에게 할 질문 한 줄>\\n' > '$wait_file'
  - 그 뒤 이번 턴을 끝내세요. supervisor 가 이 질문을 dashboard 에 노출하고,
    사용자 답변이 도착하면 답변과 함께 후속 프롬프트를 이 worker 에 다시 보내
    작업을 재개시킵니다. 재개되면 답변을 반영해 남은 작업을 마저 수행하고 위
    .done 기록을 하면 됩니다 (멈춤은 영구가 아니라 답변 대기일 뿐입니다).
큐 supervisor 는 이 sentinel 파일의 생성·내용을 폴링하여 완료를 감지합니다 (capture-pane 아님)."
  tmux send-keys -t "$pane" -l "$wrapped" 2>/dev/null
  tmux send-keys -t "$pane" Enter 2>/dev/null
  # Enter 유실 가드 (Issue96 D1, 보조): 실 claude TUI 가 부팅 직후라 Enter 가 유실되면
  #   프롬프트가 입력창에 미제출 상태로 잔류한다. 제출되면 worker 가 busy 로 전이하거나
  #   sentinel 파일을 기록하므로, 둘 다 아니면 Enter 를 최대 3회 재송신한다 (빈 입력창
  #   Enter 는 무해).
  local tries=0 vcap
  while [ "$tries" -lt 3 ]; do
    sleep 2
    vcap=$(tmux capture-pane -p -t "$pane" 2>/dev/null | tail -40)
    if worker_busy "$vcap" || [ -n "$(detect_sentinel "$id")" ]; then
      break
    fi
    tmux send-keys -t "$pane" Enter 2>/dev/null
    tries=$((tries + 1))
    log "item $id: 제출 미확인 — Enter 재송신 ($tries/3)"
  done
  log "item $id → worker@prj$prj 주입 (pane=$pane, sentinel=$done_file)"
}

resume_prompt() {
  # waiting_input worker 에 답변 + 재개 지시 재주입 (Issue102 Q&A 재개).
  #   worker 는 .waiting 기록 후 턴을 끝내 idle 상태 → 후속 프롬프트를 send-keys 로
  #   주입하면 작업을 이어간다. pane 소멸 시 rc 1 (호출부가 ready 재디스패치로 폴백).
  local prj="$1" id="$2" question="$3" answer="$4" pane done_file wait_file wrapped
  pane=$(worker_pane "$prj"); [ -n "$pane" ] || return 1
  done_file="$SENTINEL_DIR/$TOPIC.$id.done"
  wait_file="$SENTINEL_DIR/$TOPIC.$id.waiting"
  sentinel_clear "$id"   # 직전 .waiting 제거 — 재개 후 새 sentinel 만 유효
  wrapped="[dashboard 큐 작업 — item $id · 답변 수신, 작업 재개]

앞서 입력이 필요해 .waiting 으로 멈춘 작업입니다. 사용자 답변이 도착했습니다.
질문: ${question:-(기록된 질문 없음)}
답변: $answer

이 답변을 반영해 남은 작업을 마저 수행하세요. 완료 시 처음 안내대로 Bash 로
sentinel 파일을 1회 기록하세요:
  · 성공: printf 'DONE\\t0\\t<결과 한 줄 요약>\\n' > '$done_file'
  · 실패: printf 'DONE\\t<0이외 종료코드>\\t<사유>\\n' > '$done_file'
추가 입력이 또 필요하면: printf 'WAITING\\t<질문 한 줄>\\n' > '$wait_file'"
  tmux send-keys -t "$pane" -l "$wrapped" 2>/dev/null
  tmux send-keys -t "$pane" Enter 2>/dev/null
  # Enter 유실 가드 — send_prompt 와 동일 (Issue96 D1)
  local tries=0 vcap
  while [ "$tries" -lt 3 ]; do
    sleep 2
    vcap=$(tmux capture-pane -p -t "$pane" 2>/dev/null | tail -40)
    if worker_busy "$vcap" || [ -n "$(detect_sentinel "$id")" ]; then
      break
    fi
    tmux send-keys -t "$pane" Enter 2>/dev/null
    tries=$((tries + 1))
    log "item $id: 재개 제출 미확인 — Enter 재송신 ($tries/3)"
  done
  log "item $id → worker@prj$prj 재개 주입 (답변 반영, pane=$pane)"
  return 0
}

# ===== 종료 핸들러 =====

_STOPPING=0
graceful_stop() {
  # Issue120: USR2(graceful_remove)와 이중 진입 방지 — 한 번만 수행
  [ "$_STOPPING" = "1" ] && return 0
  _STOPPING=1
  log "SIGTERM/INT/HUP 수신 — supervisor 종료 (queue.yaml 보존, 재기동 시 resume)"
  exit 0
}

graceful_remove() {
  # SIGUSR2 — D5 제거 프로토콜 ③~⑤ (Phase 0 #1: send-keys 중단 지시)
  log "SIGUSR2 수신 — graceful 제거 프로토콜 시작"
  qpy set-state removing
  local prj pane id sent wfile
  # 각 worker 에 중단 지시 send-keys — 회수 보고도 파일 sentinel (Issue100)
  while read -r prj pane; do
    [ -n "${prj:-}" ] || continue
    id=$(qpy running-prj "$prj")
    [ -n "$id" ] || continue
    wfile="$SENTINEL_DIR/$TOPIC.$id.withdrawn"
    tmux send-keys -t "$pane" Escape 2>/dev/null
    tmux send-keys -t "$pane" -l \
      "작업을 중단합니다. 진행분이 있으면 부분 커밋한 뒤, Bash 로 다음 명령을 정확히 1회 실행하세요: printf 'WITHDRAWN\\n' > '$wfile'" 2>/dev/null
    tmux send-keys -t "$pane" Enter 2>/dev/null
    log "item $id (prj$prj) 중단 지시 전송"
  done < "$WORKERS_FILE"
  # WITHDRAWN sentinel 파일 수거 (최대 60초)
  local waited=0
  while [ "$waited" -lt 60 ]; do
    local pending=0
    while read -r prj pane; do
      [ -n "${prj:-}" ] || continue
      id=$(qpy running-prj "$prj"); [ -n "$id" ] || continue
      sent=$(detect_sentinel "$id")
      case "$sent" in
        WITHDRAWN|DONE*) qpy mark "$id" withdrawn; sentinel_clear "$id" ;;
        *) pending=$((pending + 1)) ;;
      esac
    done < "$WORKERS_FILE"
    [ "$pending" -eq 0 ] && break
    sleep 3; waited=$((waited + 3))
  done
  write_withdraw_report
  log "withdraw-report 작성 완료 → $WITHDRAW_REPORT. window kill 후 종료"
  tmux kill-window -t "$SESSION:$WINDOW" 2>/dev/null
  exit 0
}

write_withdraw_report() {
  # D5 ⑤ — 항목별 최종 status + 회수 시각 (구현 상세 노트 #12)
  {
    echo "# $TOPIC — 큐 회수 리포트 (withdraw-report)"
    echo
    echo "회수 시각: $(date '+%Y-%m-%d %H:%M:%S')"
    echo
    echo "| item | prj | issue | 최종 status | rc | result |"
    echo "| :--- | :-- | :---- | :---------- | :- | :----- |"
    QF="$QUEUE_FILE" python3 - <<'PYEOF'
import os, yaml
q = yaml.safe_load(open(os.environ['QF'])) or {}
for it in q.get('items', []):
    print('| %s | %s | %s | %s | %s | %s |' % (
        it.get('id',''), it.get('prj',''), it.get('issue',''),
        it.get('status',''), it.get('rc') if it.get('rc') is not None else '',
        str(it.get('result') or '').replace('|','/').replace(chr(10),' ')))
PYEOF
    echo
    echo "메인 Claude 세션이 본 리포트를 읽어 미완료 항목을 인계함."
  } > "$WITHDRAW_REPORT"
}

trap graceful_stop TERM INT
trap graceful_remove USR2
trap graceful_stop HUP   # Issue120: SIGHUP→cleanup 연결 (runner 와 동일, tmux kill-window 시 종료)

# 회귀 픽스처 훅 (Issue98 방지대책) — SUPERVISOR_SELFTEST=1 로 source 하면 함수 정의까지만
#   로드하고 main loop 진입 전에 반환한다. fpm-dashboard-supervisor.test.sh 가 worker_busy·
#   worker_ready·detect_sentinel 을 idle/busy 코퍼스로 회귀 검증하는 데 쓴다.
if [ "${SUPERVISOR_SELFTEST:-0}" = "1" ]; then
  return 0 2>/dev/null || exit 0
fi

# ===== 기동 =====

log "supervisor 기동 PID=$MY_PID topic=$TOPIC queue=$QUEUE_FILE"

if [ ! -f "$QUEUE_FILE" ]; then
  log "queue.yaml 없음 — 종료"; exit 1
fi
# 빈 큐 가드 (Issue89 R2): items 가 빈 배열이면 main loop 가 무한 idle 하므로
# 즉시 state=done 후 종료. counts 6번째 필드가 총 item 수.
read -r _ _ _ _ _ TOTAL < <(qpy counts)
if [ "${TOTAL:-0}" -eq 0 ]; then
  log "queue.yaml items 빈 배열 — state=done 후 종료 (R2)"
  qpy set-state done; exit 0
fi
if [ "$(qpy cycle-check)" = "cycle" ]; then
  log "큐에 순환 의존 — state=halted 후 종료 (구현 상세 노트 #9)"
  qpy set-state halted; exit 1
fi
qpy reset-running   # 재기동 resume: running/waiting_input → ready

declare -A nosent   # item id → idle-무sentinel 연속 strike

# liveness 가드 (Issue98 방지대책) — 상태 시그니처가 STUCK_SECS 초 이상 불변이면
#   supervisor stuck 으로 자가 진단해 queue.yaml stuck_since 를 기록하고 로그 경고.
#   영구 정지가 'running' 으로 위장되는 UX 결함(s4verify 가짜 카운트) 차단.
LAST_SIG=""
LAST_CHANGE=$(date +%s)
STUCK_FLAGGED=0

# ===== main loop (D2) =====
while true; do
  # Issue120: orphan guard — 부모(tmux pane) 사망 자가 감지 (runner line 112 패턴)
  if ! kill -0 "$ORIG_PPID" 2>/dev/null; then
    log "orphan guard: 부모($ORIG_PPID) 사망 — graceful_stop"
    graceful_stop
  fi

  # 매 iter 시작 시 자기 PID 를 queue.yaml 최상위 supervisor_pid 에 기록 (Issue88 C1).
  # 서버 /control remove 의 SIGUSR2 송신 대상 — content-authoritative pid.
  qpy set-supervisor-pid "$MY_PID"

  # liveness 가드 (Issue98) — 상태 변화가 STUCK_SECS 초 이상 없으면 stuck 진단.
  SIG=$(qpy state-sig)
  NOW_TS=$(date +%s)
  if [ "$SIG" != "$LAST_SIG" ]; then
    LAST_SIG="$SIG"; LAST_CHANGE="$NOW_TS"
    if [ "$STUCK_FLAGGED" -eq 1 ]; then
      qpy set-stuck null; STUCK_FLAGGED=0
      log "liveness: 상태 변화 재개 — stuck 해제"
    fi
  elif [ "$STUCK_FLAGGED" -eq 0 ] && [ "$(( NOW_TS - LAST_CHANGE ))" -ge "$STUCK_SECS" ]; then
    qpy set-stuck "$(date '+%Y-%m-%d %H:%M:%S')"
    STUCK_FLAGGED=1
    log "liveness: WARN — 상태 변화 0 이 ${STUCK_SECS}초 지속. supervisor stuck 의심 (큐 자가 진행 불가 가능)."
  fi

  IFS='|' read -r Q_STATE Q_ONFAIL Q_CONC _ < <(qpy meta)
  Q_CONC="${Q_CONC:-1}"

  case "$Q_STATE" in
    done|halted) log "state=$Q_STATE — 종료"; exit 0 ;;
    # state=removing 은 graceful_remove(SIGUSR2 trap)가 진입 시 설정함. 메인 루프에서
    # graceful_remove 를 재호출하면 trap 과 이중 진입 위험 → 여기선 idle 만 (Issue88 H4).
    # 실제 회수·종료는 USR2 trap → graceful_remove 가 단독 수행.
    removing)    log "state=removing — graceful_remove(trap) 진행 대기"; sleep 5; continue ;;
  esac

  # ① blocked → ready 승격
  promoted=$(qpy promote)
  [ -n "$promoted" ] && log "승격 ready: $promoted"

  # ② running/waiting_input 항목 완료 감지 — 완료 권위는 sentinel 파일 (Issue100)
  any_busy=0
  while IFS='|' read -r id prj _ attempts; do
    [ -n "${id:-}" ] || continue
    # 완료 감지: capture-pane 텍스트 스캔이 아니라 sentinel 파일 폴링 (Issue100 D5).
    #   capture-pane 보다 먼저 확인 — worker 가 작업 후 pane 을 닫아도 .done 파일이
    #   남아 있으면 완료로 인정된다.
    sent=$(detect_sentinel "$id")
    case "$sent" in
      DONE\ *)
        # detect_sentinel DONE 출력: "DONE <rc>\t<result>"
        rest="${sent#DONE }"
        rc="${rest%%$'\t'*}"
        res="${rest#*$'\t'}"; [ "$res" = "$rest" ] && res=""
        sentinel_clear "$id"
        if [ "$rc" = "0" ]; then
          qpy mark "$id" "done"; qpy set "$id" rc 0
          [ -n "$res" ] && qpy set "$id" result "$res"
          log "item $id: sentinel DONE rc=0 → done${res:+ (result=$res)}"
        else
          if [ "$attempts" -lt "$MAX_ATTEMPTS" ]; then
            qpy mark "$id" ready; qpy set "$id" rc "$rc"
            log "item $id: sentinel DONE rc=$rc → 재시도 (attempt $attempts/$MAX_ATTEMPTS)"
          else
            qpy mark "$id" failed; qpy set "$id" rc "$rc"
            [ -n "$res" ] && qpy set "$id" result "$res"
            log "item $id: sentinel DONE rc=$rc → failed (한도 초과)"
            [ "$Q_ONFAIL" = "halt" ] && { qpy set-state halted; log "on_fail=halt → 큐 중단"; }
          fi
        fi
        unset "nosent[$id]"
        continue
        ;;
      WAITING*)
        # Issue102: detect_sentinel 이 "WAITING\t<질문>" 반환 — 질문 텍스트를 파싱해
        #   queue.yaml item.question 에 기록(②.6 답변 마커·queue-runner 위젯이 사용).
        question="${sent#WAITING}"
        question="${question#$'\t'}"
        qpy mark "$id" waiting_input
        [ -n "$question" ] && qpy set "$id" question "$question"
        log "item $id: sentinel WAITING → waiting_input${question:+ (질문: $question)}"
        unset "nosent[$id]"
        continue
        ;;
      WITHDRAWN)
        qpy mark "$id" withdrawn; sentinel_clear "$id"
        log "item $id: sentinel WITHDRAWN → withdrawn"
        unset "nosent[$id]"
        continue
        ;;
    esac
    # sentinel 파일 없음 — capture-pane 은 보조로만: 크래시 감지 + busy/idle strike.
    if ! cap=$(worker_capture "$prj"); then
      # worker pane 소멸 → 크래시 복구 (2-5)
      log "item $id: worker@prj$prj pane 소멸 — 크래시 복구"
      worker_drop "$prj"; sentinel_clear "$id"
      if [ "$attempts" -lt "$MAX_ATTEMPTS" ]; then
        qpy mark "$id" ready
      else
        qpy mark "$id" failed; qpy set "$id" result "crash: max attempts"
        log "item $id: 재시도 한도 초과 → failed"
      fi
      continue
    fi
    if worker_busy "$cap"; then
      any_busy=1; unset "nosent[$id]"
    else
      nosent[$id]=$(( ${nosent[$id]:-0} + 1 ))
      if [ "${nosent[$id]}" -ge "$NOSENT_STRIKES" ]; then
        strikes="${nosent[$id]}"
        unset "nosent[$id]"
        if [ "$attempts" -lt "$MAX_ATTEMPTS" ]; then
          # D3 (Issue96): no-sentinel 도 MAX_ATTEMPTS 범위 내 재시도. 유실된 프롬프트의
          #   safety net — ready 로 되돌리면 ③ 가 같은 worker 에 재주입.
          # D6 (Issue101): NOSENT_STRIKES 기본 10 으로 상향 — worker_busy 가 장기 Bash
          #   대기를 busy 로 잡으므로 strike 는 진짜 idle 에만 쌓이나, 장기 작업 보호로
          #   escalation 진입 자체를 크게 늦춘다.
          qpy mark "$id" ready
          log "item $id: idle ${strikes}회 무sentinel → 재시도 (attempt $attempts/$MAX_ATTEMPTS)"
        else
          qpy mark "$id" failed
          qpy set "$id" result "no-sentinel (idle, ${attempts}회 시도 소진)"
          log "item $id: idle ${strikes}회 무sentinel + 시도 한도 → failed(no-sentinel)"
          [ "$Q_ONFAIL" = "halt" ] && qpy set-state halted
        fi
      fi
    fi
  done < <(qpy list running; qpy list waiting_input)

  # ②.5 승인 마커 소비 (T12-A) — waiting_approval item 의 승인 마커
  #   <APPROVAL_DIR>/<topic>__<id> 가 존재하면 ready 복귀 + approved 마킹 + 마커 rm.
  while IFS='|' read -r id _ _ _; do
    [ -n "${id:-}" ] || continue
    marker="$APPROVAL_DIR/${TOPIC}__${id}"
    if [ -f "$marker" ]; then
      qpy mark "$id" ready
      qpy set "$id" approved true
      rm -f "$marker"
      log "item $id: 승인 마커 감지 → ready 복귀 (approved)"
    fi
  done < <(qpy list waiting_approval)

  # ②.6 답변 마커 소비 (Issue102 Q&A 재개) — waiting_input item 의 답변 마커
  #   <ANSWERS_DIR>/<topic>__<id> (내용=답변 텍스트)가 존재하면 worker 에 답변+재개
  #   프롬프트를 재주입하고 running 복귀(attempts 미증가) + question·마커 정리.
  #   승인 게이트(②.5, Issue89)의 마커→재개 패턴 재사용. worker pane 소멸 시엔
  #   ready 로 되돌려 ③ 가 새 worker 로 재디스패치.
  while IFS='|' read -r id prj _ _; do
    [ -n "${id:-}" ] || continue
    marker="$ANSWERS_DIR/${TOPIC}__${id}"
    [ -f "$marker" ] || continue
    answer=$(cat "$marker" 2>/dev/null)
    question=$(qpy get "$id" question)
    rm -f "$marker"
    if resume_prompt "$prj" "$id" "$question" "$answer"; then
      qpy resume "$id"               # waiting_input → running, attempts 미증가
      qpy set "$id" question null
      log "item $id: 답변 마커 감지 → worker 재개 (running 복귀, 답변 반영)"
      any_busy=1
    else
      qpy mark "$id" ready           # worker pane 없음 → ③ 재디스패치 폴백
      qpy set "$id" question null
      log "item $id: 답변 마커 감지 but worker pane 없음 → ready 재디스패치"
    fi
  done < <(qpy list waiting_input)

  # ③ ready 디스패치 — concurrency 상한 내, per-prj 1 worker 직렬
  read -r RUN_N _ _ _ _ _ < <(qpy counts)
  room=$(( Q_CONC - RUN_N ))
  if [ "$room" -gt 0 ]; then
    while IFS='|' read -r id prj _ attempts; do
      [ -n "${id:-}" ] || continue
      [ "$room" -le 0 ] && break
      # 승인 게이트 (T12-A): approval:true 미승인 item 은 디스패치 대신 waiting_approval.
      # 승인 마커가 들어오면 ②.5 가 ready 로 되돌려 다음 iter 정상 디스패치.
      if [ "$(qpy needs-approval "$id")" = "yes" ]; then
        qpy mark "$id" waiting_approval
        log "item $id: approval 필요 → waiting_approval (승인 마커 대기)"
        continue
      fi
      # per-prj 직렬: 같은 prj 가 이미 running 이면 skip
      [ -n "$(qpy running-prj "$prj")" ] && continue
      pane=$(worker_pane "$prj")
      if [ -z "$pane" ]; then
        worker_spawn "$prj" || continue   # 생성한 iteration 은 idle 대기 (다음 iter 디스패치)
        any_busy=1; continue
      fi
      cap=$(worker_capture "$prj") || { worker_drop "$prj"; continue; }
      if worker_busy "$cap"; then
        any_busy=1; continue              # 타작업 중 — 다음 iter
      fi
      if ! worker_ready "$cap"; then
        # claude TUI 부팅중 (Issue96 D1) — 입력창 준비 전 디스패치하면 Enter 유실
        any_busy=1; continue
      fi
      qpy mark "$id" running
      send_prompt "$prj" "$id"
      any_busy=1; room=$(( room - 1 ))
    done < <(qpy list ready)
  fi

  # ④ 종료 조건
  if [ "$(qpy all-terminal)" = "yes" ]; then
    qpy set-state "done"
    log "전 항목 terminal → state=done. supervisor 종료"
    exit 0
  fi

  # ⑤ 적응형 sleep (Phase 0 #4)
  if [ "$any_busy" -eq 1 ]; then
    sleep "$INTERVAL_ACTIVE"
  else
    sleep "$INTERVAL_IDLE"
  fi
done
