#!/bin/bash
# hub-trigger.sh — UserPromptSubmit hook
#
# ⚠️ 글로벌 SCAR 변경 가드 (Issue46): 본 hook 은 모든 프로젝트가 공유. cwd ≠ ~/.claude
#   면 즉시 수정 금지 → ~/.claude/Issue.md 이슈 등록 후 처리. 설계 SSOT:
#   ~/.claude/_doc_arch/hub-mode-arch.md. 절차: ~/.claude/rules/global-scar-change-rules.md
#
# 프롬프트에 a모드 render 트리거 `..show` (Issue133, 구 `..hub` deprecated alias) 감지 시:
#   1. .hub-mode-active 플래그 touch (Q&A intercept 활성화)
#   2. HTML 렌더링 + 기본 브라우저 표시 + 후속 질문 form 처리 지시문 주입
# `..hub stop` 또는 `..hub off` 감지 시 플래그 해제 (단방향 모드 복귀 — 토글은 `..hub` 유지)
# Issue133: render 트리거만 `..hub`→`..show` rename. 우산 토글(`..hub on|off|start|stop`)·
#   c모드(`..hub dash`)는 `..hub` 보존 (우산명 충돌 해소가 목적).
#
# Issue83: `..show` 마커가 없어도 cwd 가 ___pm 등록 프로젝트면 hub 기본 on (자동 모드).
#   비프로젝트(/tmp 등)는 기본 off. per-cwd 상태는 ~/.claude/.hub-state/<hash> (on|off).
#
# Issue86: `/hub on|off` · `..hub on|off` — 폴더별 자동 모드 명시 토글.
#   상태 파일만 전환, render-blocking 미발동 (bare `..show` 와 구분).
#
# 출력 경로 결정 (Issue21):
#   - hook 입력 JSON의 cwd에서 _doc_work/z_htm/ 존재 확인
#   - 존재 시 거기에 저장, else /tmp/ fallback

input=$(cat)
FLAG_FILE="$HOME/.claude/.hub-mode-active"
# Issue83: 프로젝트 폴더 hub 기본 on — per-cwd 상태 파일로 override
STATE_DIR="$HOME/.claude/.hub-state"
# Issue105: 시스템 단위 마스터 OFF 플래그 (모든 프로젝트 자동 모드 차단)
SYSTEM_OFF_FLAG="$HOME/.claude/.hub-system-off"

# python3로 cwd / prompt / session_id 파싱 (hook 입력 JSON)
cwd=$(printf '%s' "$input" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('cwd', ''))
except Exception:
    pass" 2>/dev/null)

prompt=$(printf '%s' "$input" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('prompt', ''))
except Exception:
    pass" 2>/dev/null)

session_id=$(printf '%s' "$input" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('session_id', ''))
except Exception:
    pass" 2>/dev/null)

# Issue26: SID(세션 식별자) 결정 — session_id 우선, 미존재 시 cwd_hash로 fallback
SID="$session_id"
if [ -z "$SID" ] && [ -n "$cwd" ]; then
  SID=$(CWD_VAL="$cwd" python3 -c "
import hashlib, os
cwd = os.environ.get('CWD_VAL', '')
print(hashlib.md5(cwd.encode('utf-8')).hexdigest()[:12] if cwd else 'unknown')")
fi
# SID_FULL: open-session API 호출용 full UUID (Issue137 회귀 fix — truncate 시 vscode 세션 매칭 실패 → 새 세션 생성)
SID_FULL=$(printf '%s' "$SID" | tr -c 'A-Za-z0-9-' '-')
# SID는 파일명·URL 안전화용 32자 slug (영문/숫자/하이픈만)
SID=$(printf '%s' "$SID" | tr -c 'A-Za-z0-9-' '-' | cut -c1-32)

# OUT_DIR 결정: 프로젝트 로컬 우선
# 1) $cwd/_doc_work/z_htm  (단일 레포)
# 2) $cwd/*/​_doc_work/z_htm (mono-repo / sub-package 구조 — ex: cli/_doc_work/z_htm)
# 3) /tmp fallback
if [ -n "$cwd" ] && [ -d "$cwd/_doc_work/z_htm" ]; then
  OUT_DIR="$cwd/_doc_work/z_htm"
elif [ -n "$cwd" ]; then
  sub_found=$(find "$cwd" -mindepth 3 -maxdepth 3 -type d -path "*/_doc_work/z_htm" 2>/dev/null | head -1)
  if [ -n "$sub_found" ]; then
    OUT_DIR="$sub_found"
  else
    OUT_DIR="/tmp/___pm"
    mkdir -p "$OUT_DIR"
  fi
else
  OUT_DIR="/tmp/___pm"
  mkdir -p "$OUT_DIR"
fi

# Issue22: PROJECT_NAME + PROJECT_COLOR 계산 (cwd hash 기반, 다중 탭 식별용)
read -r PROJECT_NAME PROJECT_COLOR <<< $(CWD_VAL="$cwd" python3 -c "
import hashlib, os
cwd = os.environ.get('CWD_VAL', '')
h = hashlib.md5(cwd.encode('utf-8')).hexdigest()[:8] if cwd else ''
name = os.path.basename(cwd) or cwd or 'unknown'
color = f'hsl({int(h[:4],16) % 360}, 60%, 45%)' if h else 'hsl(220,60%,45%)'
# 공백 없는 형식으로 출력 (read -r 안전)
print(name.replace(' ', '_'), color.replace(' ', ''))
")

# Issue83: cwd_hash + 프로젝트 판정 + per-cwd 상태 파일 경로
# Issue105: 파일명에 프로젝트 라벨 포함 (`<hash>__<label>`) — 어느 폴더가 stop 상태인지 가시
CWD_HASH=$(CWD_VAL="$cwd" python3 -c "
import hashlib, os
c = os.environ.get('CWD_VAL', '')
print(hashlib.md5(c.encode('utf-8')).hexdigest()[:8] if c else 'none')")

# 라벨: 마지막 path segment. basename 이 '_'로 시작하면 parent-base 결합 (ex: _public → fSnippet-_public)
PROJECT_LABEL=$(CWD_VAL="$cwd" python3 -c "
import os, re
cwd = os.environ.get('CWD_VAL', '').rstrip('/')
if not cwd:
    print('unknown')
else:
    parts = cwd.split('/')
    base = parts[-1] if parts else 'unknown'
    parent = parts[-2] if len(parts) >= 2 else ''
    label = f'{parent}-{base}' if base.startswith('_') and parent else base
    print(re.sub(r'[^A-Za-z0-9._-]', '_', label)[:48] or 'unknown')")

STATE_FILE="$STATE_DIR/${CWD_HASH}__${PROJECT_LABEL}"

# Issue105 마이그레이션: 기존 hash-only 파일이 있고 새 라벨 파일이 없으면 rename
OLD_STATE_FILE="$STATE_DIR/$CWD_HASH"
if [ -f "$OLD_STATE_FILE" ] && [ ! -f "$STATE_FILE" ]; then
  mv "$OLD_STATE_FILE" "$STATE_FILE" 2>/dev/null
fi

# 프로젝트 판정: cwd 가 ~/_git/___pm/projects/* 번호 파일이 가리키는 경로에 at-or-under 인가
IS_PROJECT=$(CWD_VAL="$cwd" python3 -c "
import os
cwd = os.environ.get('CWD_VAL', '')
pdir = os.path.join(os.path.expanduser('~'), '_git', '___pm', 'projects')
hit = False
if cwd:
    cwd = os.path.realpath(cwd)
    try:
        for fn in os.listdir(pdir):
            if not fn.isdigit():
                continue
            try:
                with open(os.path.join(pdir, fn)) as f:
                    p = f.read().strip()
            except Exception:
                continue
            if not p:
                continue
            p = os.path.realpath(os.path.expanduser(p))
            if cwd == p or cwd.startswith(p + os.sep):
                hit = True
                break
    except Exception:
        pass
print('1' if hit else '0')")

# Issue105: 토글 의미 재정의
#   * 시스템 단위 (모든 프로젝트):  `..hub on|off` · `/hub on|off`
#     - `off` → SYSTEM_OFF_FLAG touch (모든 프로젝트 자동 모드 차단)
#     - `on`  → SYSTEM_OFF_FLAG rm   (시스템 자동 모드 복귀, per-cwd 상태는 유지)
#   * 프로젝트 단위 (현재 cwd):     `..hub start|stop` · `/hub start|stop`
#     - `stop`  → STATE_FILE=off (이 폴더만 영구 off)
#     - `start` → STATE_FILE=on  (이 폴더만 영구 on)
#   * bare `..show <요청>` (구 `..hub`) 은 별도 분기 (render-only trigger, 아래)

# 시스템 토글 — `..hub on|off` · `/hub on|off`
HTM_SYSTEM=""
if printf '%s' "$prompt" | grep -qiE '(^|[[:space:]])(\.\.hub|/hub)[[:space:]]+on([[:space:]]|$)'; then
  HTM_SYSTEM="on"
elif printf '%s' "$prompt" | grep -qiE '(^|[[:space:]])(\.\.hub|/hub)[[:space:]]+off([[:space:]]|$)'; then
  HTM_SYSTEM="off"
fi
if [ -n "$HTM_SYSTEM" ]; then
  if [ "$HTM_SYSTEM" = "on" ]; then
    rm -f "$SYSTEM_OFF_FLAG"
    rm -f "$FLAG_FILE"  # 본 turn 은 토글 전용 — 렌더 미진입
    cat <<'JSON'
{
  "hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": "## hub 시스템 ON (Issue105)\n\n시스템 단위 마스터 OFF 플래그 (`~/.claude/.hub-system-off`) 제거. 모든 프로젝트의 자동 hub 모드 재활성 (per-cwd `stop` 기록 폴더는 여전히 off 유지).\n\n### 본 turn 처리\n- 토글 전용 — **렌더·폼·워크플로우 진입 금지**. 한 줄 확인만: `hub 시스템 on.`\n- 프로젝트 단위 끄기: `..hub stop` / 다시 켜기: `..hub start`\n- 시스템 단위 끄기: `..hub off`"
  }
}
JSON
  else
    touch "$SYSTEM_OFF_FLAG"
    rm -f "$FLAG_FILE"
    cat <<'JSON'
{
  "hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": "## hub 시스템 OFF (Issue105)\n\n시스템 단위 마스터 OFF 플래그 (`~/.claude/.hub-system-off`) 생성. 모든 프로젝트 자동 hub 모드 차단 (per-cwd `start` 기록 폴더 포함). bare `..hub <요청>` render-only 트리거는 여전히 동작.\n\n### 본 turn 처리\n- 토글 전용 — **렌더·폼·워크플로우 진입 금지**. 한 줄 확인만: `hub 시스템 off.`\n- 재활성: `..hub on`"
  }
}
JSON
  fi
  exit 0
fi

# 프로젝트 단위 토글 — `..hub start|stop` · `/hub start|stop`
HTM_PROJ=""
if printf '%s' "$prompt" | grep -qiE '(^|[[:space:]])(\.\.hub|/hub)[[:space:]]+start([[:space:]]|$)'; then
  HTM_PROJ="on"
elif printf '%s' "$prompt" | grep -qiE '(^|[[:space:]])(\.\.hub|/hub)[[:space:]]+stop([[:space:]]|$)'; then
  HTM_PROJ="off"
fi
if [ -n "$HTM_PROJ" ]; then
  mkdir -p "$STATE_DIR"
  printf '%s' "$HTM_PROJ" > "$STATE_FILE"
  if [ "$HTM_PROJ" = "on" ]; then
    rm -f "$FLAG_FILE"  # 토글 전용 — 다음 turn 부터 자동 모드 발동
    PROJECT_LABEL="$PROJECT_LABEL" CWD_HASH="$CWD_HASH" python3 <<'PYEOF'
import os, json
label = os.environ.get('PROJECT_LABEL', 'unknown')
h = os.environ.get('CWD_HASH', 'none')
print(json.dumps({"hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": (
        f"## hub 프로젝트 ON ({label} — Issue105)\n\n"
        f"이 폴더의 자동 hub 모드를 `on` 으로 기록 (`~/.claude/.hub-state/{h}__{label}`). "
        "다음 턴부터 자동 HTML 렌더 (trivial 응답은 Issue85 로 skip).\n\n"
        "### 본 turn 처리\n"
        "- 토글 전용 — **렌더·폼·워크플로우 진입 금지**. 한 줄 확인만: "
        f"`hub 프로젝트 on ({label}).`\n"
        "- 끄려면 `..hub stop` (이 폴더만) / 시스템 전체 끄기 `..hub off`"
    )
}}, ensure_ascii=False))
PYEOF
  else
    rm -f "$FLAG_FILE"
    PROJECT_LABEL="$PROJECT_LABEL" CWD_HASH="$CWD_HASH" python3 <<'PYEOF'
import os, json
label = os.environ.get('PROJECT_LABEL', 'unknown')
h = os.environ.get('CWD_HASH', 'none')
print(json.dumps({"hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": (
        f"## hub 프로젝트 OFF ({label} — Issue105)\n\n"
        f"이 폴더의 자동 hub 모드를 `off` 로 기록 (`~/.claude/.hub-state/{h}__{label}`). "
        "프로젝트 폴더라도 자동 렌더 안 함. AskUserQuestion 정상 동작 복귀.\n\n"
        "### 본 turn 처리\n"
        "- 토글 전용 — **렌더·폼·워크플로우 진입 금지**. 한 줄 확인만: "
        f"`hub 프로젝트 off ({label}).`\n"
        "- 다시 켜려면 `..hub start` (이 폴더만)"
    )
}}, ensure_ascii=False))
PYEOF
  fi
  exit 0
fi

# Issue24 Phase 7 / Issue37 / Issue41 / Issue126: `..hub dash` / `..dashboard` / `..board` — Mode C Live Dashboard agent 트리거
# Mode C 는 ___pm 서버(htm-server) 의 SSE 사용. hub Q&A 도 동일 서버 inbox 사용 (Issue45).
# Issue41 (2026-05-19): `..dashboard` alias 추가 — 자연어 매칭 강화
# Issue126 (2026-06-03): `..board <topic>` 신설 — c모드 단일 단어 트리거. `..hub dash`/`..dashboard` 는
#   하위호환 별칭으로 유지 (deprecation 예정, 즉시 제거 금지 — 기존 muscle memory 보호).
if printf '%s' "$prompt" | grep -qE '(^|[[:space:]])(\.\.hub[[:space:]]+dash|\.\.dashboard|\.\.board)([[:space:]]|$)'; then
  touch "$FLAG_FILE"
  SERVER_PORT="${HTM_SERVER_PORT:-9876}"
  health=$(curl -s -o /dev/null -w "%{http_code}" --max-time 2 "http://127.0.0.1:${SERVER_PORT}/healthz" 2>/dev/null)

  # topic 추출: "..hub dash <topic ...>" / "..dashboard <topic ...>" / "..board <topic ...>" 에서 트리거 다음 토큰들
  TOPIC=$(printf '%s' "$prompt" | sed -nE 's/.*(\.\.hub[[:space:]]+dash|\.\.dashboard|\.\.board)[[:space:]]+(.+)/\2/p' | head -1)
  # Issue131: --auto-kill 플래그 — 완료 alert 후 tmux window 자동 kill (기본 미설정 = 잔존, 로그 보존)
  AUTO_KILL=false
  if printf '%s' "$TOPIC" | grep -qE '(^|[[:space:]])--auto-kill([[:space:]]|$)'; then
    AUTO_KILL=true
    TOPIC=$(printf '%s' "$TOPIC" | sed -E 's/(^|[[:space:]])--auto-kill([[:space:]]|$)/ /g' | sed -E 's/^[[:space:]]+//; s/[[:space:]]+$//')
  fi

  PROJECT_NAME="$PROJECT_NAME" \
    SERVER_PORT="$SERVER_PORT" \
    HEALTH="$health" \
    PROJECT_CWD="$cwd" \
    TOPIC="$TOPIC" \
    AUTO_KILL="$AUTO_KILL" \
    python3 <<'PYEOF'
import os, json
project_name = os.environ.get('PROJECT_NAME', 'unknown')
server_port = os.environ.get('SERVER_PORT', '9876')
health_ok = os.environ.get('HEALTH', '') == '200'
cwd = os.environ.get('PROJECT_CWD', '')
topic = os.environ.get('TOPIC', '').strip()
auto_kill = os.environ.get('AUTO_KILL', 'false') == 'true'

if not health_ok:
    context = (
        "## ⚠️ `..board` 트리거 — dashboard-server 미실행\n\n"
        f"Mode C(dashboard) agent 는 ___pm 서버 (port {server_port}, htm-server daemon) 필수. healthz 실패.\n\n"
        "### 즉시 조치\n"
        "1. 사용자에게 `/dashboard-server start` 안내 (Issue37 이후 명칭)\n"
        "2. 시작 후 다시 `..board <topic>` 입력 (별칭: `..hub dash` / `..dashboard`)\n\n"
        "본 turn 응답: agent 호출 금지. 채팅으로 서버 미실행 안내만."
    )
else:
    topic_clause = f"`{topic}`" if topic else "(사용자에게 topic 확인 필요)"
    context = (
        "## `..board` 트리거 감지 — Mode C Live Dashboard agent (Issue24 Phase 7, Issue126)\n\n"
        "(별칭: `..hub dash` / `..dashboard` — 하위호환 유지)\n\n"
        f"프로젝트 `{project_name}`. 본 turn 은 **dashboard agent 1회 호출 후 종료**. 다른 작업 금지.\n\n"
        "### 처리 절차 (필수)\n"
        f"1. **topic 확인**: 트리거에서 추출된 topic = {topic_clause}\n"
        "   - 비어있으면 사용자에게 topic 1회 질의 후 종료 (자동 추측 금지)\n"
        "2. **Agent 도구 호출**:\n"
        "   ```\n"
        "   Agent(\n"
        "     description='dashboard 시작',\n"
        "     subagent_type='dashboard',\n"
        "     prompt='topic=<TOPIC>; cwd=" + cwd + "; htm-server 활성. tmux pane 에서 runner 시작 + dashboard push. ~/.claude/agents/dashboard.md 절차 따를 것.'\n"
        "   )\n"
        "   ```\n"
        "3. agent 반환 결과를 채팅에 그대로 전달 (요약 + stable URL + pane 명령 + 핵심 데이터)\n\n"
        "### 4. 완료 폴러 기동 (Issue131 — finite 작업만)\n"
        "agent 반환 메타로 finite 판정:\n"
        "- worker_pid 설정 모니터링 / 큐 모드 → **finite** (status:done 도달) → 폴러 기동\n"
        "- 무한 heartbeat (worker_pid 미설정 순수 모니터링) → 폴러 **생략** (수동 stop 용도, alert 불필요)\n\n"
        "finite 면 turn 종료 전 `run_in_background: true` Bash 폴러 1개 기동 (DATA_FILE=agent 반환 dash.yaml 절대경로):\n"
        "```bash\n"
        "DATA_FILE='<dash.yaml 절대경로>'; TOPIC='<topic>'\n"
        "ETA_SEC=''   # agent ETA 추정 있으면 초 단위, 없으면 빈 값\n"
        "POLL=30; TIMEOUT=${ETA_SEC:+$((ETA_SEC*2))}; TIMEOUT=${TIMEOUT:-21600}   # 기본 6h (ETA 알면 ETA*2)\n"
        "START=$(date +%s)\n"
        "while :; do\n"
        "  st=$(yq -r '.status' \"$DATA_FILE\" 2>/dev/null)\n"
        "  case \"$st\" in\n"
        "    done) echo \"BOARD_DONE topic=$TOPIC\"; break;;\n"
        "    stopped|halted) echo \"BOARD_END topic=$TOPIC status=$st\"; break;;\n"
        "  esac\n"
        "  [ $(( $(date +%s) - START )) -ge \"$TIMEOUT\" ] && { echo \"BOARD_TIMEOUT topic=$TOPIC elapsed=$(( $(date +%s) - START ))s\"; break; }\n"
        "  sleep \"$POLL\"\n"
        "done\n"
        "```\n"
        "→ 폴러 exit 시 harness 가 본 세션 재호출. 폴 30s, 기본 만료 6h (SCAR 전역 스케줄링: crontab 금지·네이티브 폴링 허용).\n\n"
        "### 5. 완료 alert (폴러 exit 후 재호출 시)\n"
        "폴러 stdout 확인 후 채팅 alert:\n"
        "- `BOARD_DONE` → DATA_FILE `yq` read → ✅ `<topic>` 완료 · 소요시간 · 핵심 결과(checklist done 비율 / progress / 검증 통과) · 산출물 경로\n"
        "- `BOARD_END` (stopped/halted) → ⏹ 중단 alert (사유)\n"
        "- `BOARD_TIMEOUT` → ⏳ 폴러 만료 (ETA×2 또는 6h 경과, 여전히 running) → 폴러 재기동 여부 사용자 질의\n\n"
        + ("### 6. auto-kill (--auto-kill 지정됨)\n"
           "BOARD_DONE alert 후 tmux window 자동 종료: `cdft kill :<win_name>` (또는 `tmux kill-window -t pm:<win_name>`). 로그 유실 주의.\n\n"
           if auto_kill else
           "### 6. window 잔존 (기본 — --auto-kill 미지정)\n"
           "완료 후 tmux window 잔존 (로그 보존). alert 에 수동 kill 명령 안내: `cdft kill :<win_name>`.\n\n")
        + "### 채팅 응답 의무 (Issue24 Phase 8)\n"
        "- 한 줄 요약 (무엇을, 어디 pane 에)\n"
        "- stable URL 전체 (token 포함, 임의 제거 금지)\n"
        "- pane capture/kill 명령\n"
        "- 데이터 핵심 bullet 2~3개 (브라우저 못 봐도 채팅만으로 상태 파악 가능)\n"
        "- finite 면 폴러 기동 사실 명시 (\"완료 시 자동 alert\")\n\n"
        "### 구버전 (참고)\n"
        "Mode C skill (`~/.claude/skills/dashboard/`) 폐기됨. 본 turn 부터 agent 만 사용.\n"
    )

print(json.dumps({"hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": context
}}, ensure_ascii=False))
PYEOF
  exit 0
fi


# Issue126 (2026-06-03): `..ask <주제>` — b모드(양방향 Q&A 폼) 명시 진입점
# 기존 b모드는 트리거 단어 없이 AskUserQuestion intercept 로만 진입했으나, 이제 단일 단어
#   `..ask` 로 "나에게 물어봐" 모드를 직접 호출. 플래그 touch → 후속 AskUserQuestion 을
#   ask-intercept.sh 가 동일 form 자동 회수 경로로 처리 (인프라 재사용).
# 매칭: `..ask` 가 render 분기보다 먼저 평가되도록 bare `..show`/`..hub` 분기 위에 배치.
if printf '%s' "$prompt" | grep -qiE '(^|[[:space:]])\.\.ask([[:space:]]|$)'; then
  touch "$FLAG_FILE"
  mkdir -p "$STATE_DIR"
  printf 'on' > "$STATE_FILE"

  # topic 추출: "..ask <주제 ...>" 에서 트리거 다음 토큰들
  ASK_TOPIC=$(printf '%s' "$prompt" | sed -nE 's/.*\.\.ask[[:space:]]+(.+)/\1/p' | head -1)

  ASK_TOPIC="$ASK_TOPIC" \
    SERVER_PORT="${HTM_SERVER_PORT:-9876}" \
    python3 <<'PYEOF'
import os, json
topic = os.environ.get('ASK_TOPIC', '').strip()
server_port = os.environ.get('SERVER_PORT', '9876')
topic_clause = f"`{topic}`" if topic else "(트리거에 주제 없음 — 사용자 직전 맥락에서 결정 주제 도출)"

context = (
    "## `..ask` 트리거 감지 — b모드 (양방향 Q&A 폼 자동 회수, Issue126)\n\n"
    f"주제 = {topic_clause}\n\n"
    "`.hub-mode-active` 플래그 활성화됨. 본 turn 은 **사용자에게 결정을 묻는 폼 1회 제시**가 목적 "
    "(\"나에게 물어봐\" 모드 — 응답 자체가 결정 회수 폼).\n\n"
    "### 처리 절차 (필수)\n"
    "1. 주제에 대해 사용자가 선택할 **2~4개 옵션**을 도출 (권장안은 첫 옵션 + label 끝 `(권장)`).\n"
    "   - 옵션 도출에 정보 제공·비교가 필요하면 먼저 간단한 본문 HTML(a모드 절차)로 옵션 설명·trade-off 렌더 후 폼 분리. trivial 하면 본문 생략하고 바로 폼.\n"
    "2. **`AskUserQuestion` 도구 호출** — `ask-intercept.sh` (PreToolUse hook)가 가로채 "
    "form HTML 생성·Firefox open·server inbox 자동 회수 지시를 주입함. 그 지시를 그대로 따를 것.\n"
    "   - 호출 예: `AskUserQuestion(questions=[{\"question\":\"...\",\"header\":\"...\",\"multiSelect\":false,"
    "\"options\":[{\"label\":\"A (권장)\",\"description\":\"...\"}, ...]}])`\n"
    "3. 텍스트 bullet 리스트로 선택지를 dump 하지 말 것 — 결정 요청은 반드시 `AskUserQuestion` 호출로 분리.\n\n"
    f"### 서버 전제\n"
    f"- ___pm htm-server (port {server_port}) 상시 운영 전제. 서버 down 시 intercept hook 이 fail-loud "
    "(`/dashboard-server start` 후 재시도 또는 `..hub stop` 안내).\n\n"
    "### 채팅 fallback 의무 (Issue60)\n"
    "- 폼 열림 안내 + 질문 텍스트 + 옵션 라벨/desc + 저장 경로 포함 (Firefox 부재 가정, 채팅만으로 답 가능).\n\n"
    "### 모드 관계\n"
    "- a모드(`..show`, 단방향 렌더) / b모드(`..ask`, 양방향 폼) / c모드(`..board`, dashboard) 3트리거 체계.\n"
    "- 토글은 hub 단위 공유: 끄기 `..hub stop` (이 폴더) / `..hub off` (시스템 전체)."
)
print(json.dumps({"hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": context
}}, ensure_ascii=False))
PYEOF
  exit 0
fi


# B. Slash command + ..show(또는 구 ..hub) 끝 위치 → 경고 후 exit (사용자 위치 교정)
# 사유: `/dev 885 ..show` 형식은 slash command가 prompt 흡수 → hub additionalContext 무시됨
# Issue33: regex 강화 — `/단어<space|EOL>` 만 매칭. `/tmp/test2` 같은 file path 는 두 번째 `/` 로 인해 미매칭
if printf '%s' "$prompt" | grep -qE '^/[a-zA-Z][a-zA-Z0-9_-]*([[:space:]]|$)' && \
   printf '%s' "$prompt" | grep -qE '(\.\.show|\.\.hub)[[:space:]]*$'; then
  cat <<'JSON'
{
  "hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": "⚠️ `..show`(렌더 트리거)를 slash command와 함께 쓸 때는 **맨 앞**에 두어야 작동. 예: `..show /dev 885`. 현재 prompt는 slash command가 흡수하여 hub 모드 미작동. 본 turn은 평소대로 처리. 다음 turn부터 위치 변경 권장."
  }
}
JSON
  exit 0
fi

# `..show`(구 `..hub` deprecated) 마커 감지: 공백 경계 또는 줄 끝
# Issue45 (2026-05-19): ___pm 상시 운영 전제. form 자동 회수 단일 경로 (paste-back 제거).
# 본문 HTML 은 file:// 직접 open. Q&A 만 intercept hook 이 ___pm htm-server inbox 로 자동 회수.
# Issue130: browser_focus + default_browser 토글 (Issue128 확장)
HUB_SETTING_FILE="$HOME/_git/___pm/data/hub_setting.yml"
# default_browser: firefox(기본)/chrome/edge/safari, 미지원 값은 .app 절대 경로로 해석
_db=$(grep -E '^[[:space:]]*default_browser:' "$HUB_SETTING_FILE" 2>/dev/null | head -1 | sed -E 's/^[^:]*:[[:space:]]*//; s/[[:space:]]*#.*$//; s/[[:space:]]*$//; s/^"//; s/"$//')
case "$_db" in
  ""|firefox|Firefox) _app="Firefox" ;;
  chrome|Chrome)      _app="Google Chrome" ;;
  edge|Edge)          _app="Microsoft Edge" ;;
  safari|Safari)      _app="Safari" ;;
  *)                  _app="$_db" ;;
esac
# browser_focus: false(기본)=백그라운드 open(-g, 포커스 미탈취), true=foreground(포커스 가져감)
if grep -qE '^[[:space:]]*browser_focus:[[:space:]]*true' "$HUB_SETTING_FILE" 2>/dev/null; then
  HTM_OPEN_CMD="open -a \"$_app\""
else
  HTM_OPEN_CMD="open -g -a \"$_app\""
fi

# Issue133: a모드 render 트리거 `..hub` → `..show` rename. `..show`/`/show` = primary,
#   `..hub`(bare) = 한시적 deprecated alias. 토글(`..hub on|off|start|stop`)·c모드(`..hub dash`)는
#   위 분기에서 이미 처리·exit 됨 — 여기 도달한 `..hub` 는 render-intent 뿐 (보존 아님).
# 서버 down 시 intercept hook fail-loud 안내.
HUB_RENDER_TRIGGER=""
if printf '%s' "$prompt" | grep -qE '(^|[[:space:]])(\.\.show|/show)([[:space:]]|$)'; then
  HUB_RENDER_TRIGGER="show"
elif printf '%s' "$prompt" | grep -qE '(^|[[:space:]])\.\.hub([[:space:]]|$)'; then
  HUB_RENDER_TRIGGER="hub-deprecated"
fi
if [ -n "$HUB_RENDER_TRIGGER" ]; then
  # 플래그 활성화 — 후속 AskUserQuestion 을 form 으로 가로채기 위함
  touch "$FLAG_FILE"
  # Issue83: 이 폴더 상태를 on 으로 기록 (이전 `..hub stop` off 마커 덮어쓰기)
  mkdir -p "$STATE_DIR"
  printf 'on' > "$STATE_FILE"

  # --new flag 제거 (호환성 위해 prompt 에서 인식만, 동작 변화 없음)
  PROJECT_NAME="$PROJECT_NAME" \
    PROJECT_COLOR="$PROJECT_COLOR" \
    PROJECT_CWD="$cwd" \
    SID="$SID" \
    SID_FULL="$SID_FULL" \
    OUT_DIR="$OUT_DIR" \
    HTM_OPEN_CMD="$HTM_OPEN_CMD" \
    HUB_RENDER_TRIGGER="$HUB_RENDER_TRIGGER" \
    python3 <<'PYEOF'
import os, json

project_name = os.environ.get('PROJECT_NAME', 'unknown')
project_color = os.environ.get('PROJECT_COLOR', 'hsl(220,60%,45%)')
cwd = os.environ.get('PROJECT_CWD', '')
sid = os.environ.get('SID', 'unknown')
sid_full = os.environ.get('SID_FULL', sid)
out_dir = os.environ.get('OUT_DIR', '/tmp')
open_cmd = os.environ.get('HTM_OPEN_CMD', 'open -g -a Firefox')
path_note = "프로젝트 로컬 (_doc_work/z_htm/)" if out_dir != '/tmp' else "/tmp fallback"
# Issue133: `..hub` bare render 는 deprecated → `..show` 안내 주입
deprecated = os.environ.get('HUB_RENDER_TRIGGER', '') == 'hub-deprecated'
deprecation_note = (
    "## ⚠️ deprecated 트리거 (Issue133)\n"
    "`..hub`(단독, 렌더 의도)는 deprecated alias. a모드 render 트리거는 **`..show`** 로 변경됨 "
    "(우산 토글 `..hub on|off|start|stop` 과 단어 충돌 해소). 본 turn 은 정상 렌더하되, "
    "채팅 응답 끝에 한 줄 안내: `(알림: '..hub' 렌더 트리거는 '..show' 로 변경됨)`.\n\n"
) if deprecated else ""

# Issue132: CANONICAL 헤더 블록 — verbatim 복붙 강제 (정적 span·순서 뒤바뀜·헤더 밖 overflow 재발 차단)
canonical_header = (
    "3. **⚠️ CANONICAL 헤더 블록 (Issue132) — 아래 HTML·CSS verbatim 복붙. 즉흥 재작성 금지** "
    "(정적 `<span>`·순서 뒤바뀜·헤더 밖 overflow 재발 원인). `{제목}` 만 콘텐츠로 치환 (배지명·경로·색은 이미 임베드됨):\n"
    "```html\n"
    "<header>\n"
    "  <h1>{제목}</h1>\n"
    "  <nav class=\"header-actions\">\n"
    "    <a class=\"proj-badge\" href=\"#\" title=\"클릭 → VSCode 로 __PNAME__ 열기\"\n"
    "       onclick=\"event.preventDefault();fetch('http://127.0.0.1:9876/open-project',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cwd:'__CWD__'})}).then(function(r){return r.json();}).then(function(j){if(j&&j.error)alert('VSCode 열기 실패: '+j.error);}).catch(function(){alert('hub 서버 미응답 — VSCode 열기 실패');});\">📁 __PNAME__</a>\n"
    "    <a class=\"sess-link\" href=\"#\" title=\"클릭 → 이 문서를 만든 세션 탭으로 포커스\"\n"
    "       onclick=\"event.preventDefault();fetch('http://127.0.0.1:9876/open-session',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cwd:'__CWD__',sid:'__SID__'})}).then(function(r){return r.json();}).then(function(j){if(j&&j.error)alert('세션 열기 실패: '+j.error);}).catch(function(){alert('hub 서버 미응답 — 세션 열기 실패');});\">🎯 세션</a>\n"
    "    <a class=\"hub-link\" href=\"http://127.0.0.1:9876/hub\" target=\"_blank\">🗂 Hub</a>\n"
    "    <button type=\"button\" onclick=\"window.close()\">닫기 ✕</button>\n"
    "  </nav>\n"
    "</header>\n"
    "```\n"
    "```css\n"
    "header { position: sticky; top: 0; z-index: 100; display: flex; align-items: center;\n"
    "  justify-content: space-between; gap: 1rem; flex-wrap: wrap; padding: 0.9rem 1.4rem;\n"
    "  background: __PCOLOR__; color: #fff; }\n"
    "header h1 { margin: 0; font-size: 1.15rem; flex: 1 1 auto; min-width: 0; }\n"
    "header .header-actions { display: flex; align-items: center; gap: 0.5rem; flex: 0 0 auto; }\n"
    "header .proj-badge, header .sess-link, header .hub-link, header button { color: #fff; text-decoration: none;\n"
    "  cursor: pointer; white-space: nowrap; background: rgba(255,255,255,0.15);\n"
    "  border: 1px solid rgba(255,255,255,0.35); padding: 0.2rem 0.6rem; border-radius: 6px; font-size: 0.85rem; }\n"
    "header .proj-badge:hover, header .sess-link:hover, header .hub-link:hover, header button:hover {\n"
    "  background: rgba(255,255,255,0.28); text-decoration: underline; }\n"
    "```\n"
    "   불변식 (재발 차단): 배지=`<a class=\"proj-badge\" onclick=...POST /open-project...>` (정적 span 금지·Issue103), 세션=`<a class=\"sess-link\" onclick=...POST /open-session {cwd,sid}...>` (Issue137) → "
    "순서 `📁 배지`→`🎯 세션`→`🗂 Hub`→`닫기 ✕` → 넷 모두 `<header>` 안 `.header-actions` 동일 행 (헤더 밖 div 금지·Issue88) → "
    "flex+space-between+wrap 로 우측 overflow 방지. 조상(`html`/`body`/컨테이너)에 `overflow:hidden|clip` 금지 (sticky 무효화).\n"
).replace("__PNAME__", project_name).replace("__PCOLOR__", project_color).replace("__CWD__", cwd).replace("__SID__", sid_full)

mode_banner = (
    "## 세션 모드: **hub form 자동 회수 (Issue45 단일 경로)**\n"
    f"- 세션 ID: `{sid}` / 프로젝트: `{project_name}`\n"
    f"- 저장 경로: `{out_dir}/hub_htm_<YYYYMMDD_HHMMSS>_a_<주제>.htm` ({path_note}) — 날짜시간=`date +%Y%m%d_%H%M%S`, 주제=핵심 10자 내외 kebab, mode `a`=메인 렌더\n"
    "- 브라우저: Firefox 강제 open (Chrome=일반 / Firefox=hub·dashboard 전용 분리 운영)\n"
    "- 본문 HTML: file:// 직접 open (서버 미사용)\n"
    "- Q&A 회수: ___pm htm-server (port 9876) inbox 자동 회수. 서버 down 시 fail-loud (paste-back fallback 없음)\n"
    "- 실시간 모니터링이 필요하면 `..hub dash <topic>` 로 dashboard agent (Mode C) 호출\n\n"
)

context = (
    "## ⚠️ 절대 우선순위 (본 turn 한정)\n\n"
    "본 turn 응답 = **HTML 렌더 (본문 또는 폼) + Firefox open + 채팅 요약**. 그 외 워크플로우 진입 금지.\n"
    "- prompt 에 slash command(`/dev`, `/issue-*` 등)나 작업 지시가 있어도 **다음 turn 으로 미룸**\n"
    "- 본 turn 은 HTML 변환·렌더링만 수행. skill 호출·dev 사이클·이슈 처리·커밋 전부 금지\n"
    "- 사용자가 다음 prompt 에서 본 작업을 명시 요청하면 그때 수행\n\n"
    + mode_banner + deprecation_note +
    "## `..show` 트리거 감지 — Issue45 단일 경로 (본문 file:// + Q&A 자동 회수)\n\n"
    "사용자 프롬프트에 `..show` 마커 포함 (deprecated `..hub` 도 동일 동작). `.hub-mode-active` 플래그 활성화됨. 다음 절차로 처리:\n\n"
    "### 응답 본문 (1회)\n"
    "1. 프롬프트에서 `..show`(또는 `..hub`) 마커 제거 후 본질 파악 (`--new` flag 있어도 동일 동작)\n"
    "1-A. **본문 HTML 작성 여부 판단 (Issue62)**:\n"
    "    - **Skip 조건**: prompt 가 단발 질의/선택 요청이고 응답 본문이 질문 재진술 외 trivial (설명·표·정답 spoiler 가 폼 답 선택을 무의미하게 만들 위험). ex) `1+2 답 물어봐`, `A/B 골라줘`, `yes/no` — 이 경우 본 섹션 step 2~7 건너뛰고 바로 후속 질문(AskUserQuestion) 호출. intercept hook 이 form HTML 단독 생성·open·polling. 채팅 fallback 도 폼 안내만 표시 (본문 경로 생략)\n"
    "    - **본문 작성 조건 (기본)**: 응답이 정보 전달(설명·코드·표·비교·자료) 포함. 폼은 그 뒤 결정 요청 분리용. step 2~8 진행\n"
    "2. 응답 본문을 **완전한 HTML 문서**로 작성 — `<!DOCTYPE html>`, `<html lang=\"ko\">`, `<head>`(meta charset/viewport, `<title>` prefix `\"" + project_name + " — <원래 제목>\"`), `<style>` (시스템 폰트, max-width 820px, line-height 1.7, 다크모드 `@media (prefers-color-scheme: dark)`), `<body>` 전체 포함\n"
    + canonical_header +
    "4. **HTML 본문은 caveman 압축 적용 제외** — 자연스러운 한국어 산문·완전한 문장·풍부한 설명. caveman 은 사용자에게 보내는 채팅 응답에만 적용\n"
    "5. 표·리스트·코드블록·`<h1>`~`<h4>`·`<blockquote>` 자유 사용. 코드블록은 배경+padding, 인용구는 좌측 보더\n"
    "6. **저장**: `Write` 도구로 `" + out_dir + "/hub_htm_<YYYYMMDD_HHMMSS>_a_<주제>.htm` 저장 (날짜시간=`date +%Y%m%d_%H%M%S` 출력, 주제=핵심 10자 내외 kebab-case, mode `a`=메인 렌더)\n"
    "7. **Firefox 표시**:\n"
    "   ```bash\n"
    f"   {open_cmd} \"file://<절대경로>\"\n"
    "   ```\n"
    f"   - macOS `{open_cmd}` (브라우저·포커스는 `browser_focus`/`default_browser` 설정 따름 — `-g`=백그라운드 open, 포커스 미탈취)\n"
    "   - 기본 브라우저(Chrome)와 분리하여 hub/dashboard 전용으로 Firefox 사용 (사용자 운영 모델)\n"
    "8. 채팅 응답(caveman 유지)에는 한 줄 헤드라인 + 핵심 bullet 2~3개 + 저장 경로 표기\n"
    "   - 예: `HTML 저장. /tmp/___pm/hub_htm_20260531_143022_a_topic.htm. Firefox 열림.` + 핵심 요약\n"
    "   - **Issue60 의무**: 브라우저 표시 안 됐을 가능성(Firefox 종료·hidden·미설치·원격 SSH·다른 데스크톱) 항상 가정. **채팅 fallback 텍스트가 1차 채널**, Firefox 는 보조. 채팅만 읽어도 내용 파악·경로 재오픈 가능해야 함. 본문 핵심 요약은 3줄 이내, 표·코드 dump 금지\n\n"
    "### 후속 질문 (form 자동 회수, Issue45)\n"
    "- hub 모드(`..show`) 활성 중 `AskUserQuestion` 도구는 PreToolUse hook (`ask-intercept.sh`) 이 자동 deny\n"
    "- deny reason 에 form HTML 생성·Firefox open·fetch POST·inbox polling 절차 포함 — 그 지시를 그대로 따를 것\n"
    "- 회수: 사용자 폼 \"전송\" → fetch POST → server inbox → Claude bash polling → JSON Read·rm → answers 추출 → 흐름 재개\n"
    "- 서버 down 시: intercept hook 이 fail-loud reason 주입 (`/dashboard-server start` 후 재시도 또는 `..hub stop` 안내). paste-back fallback 없음\n"
    "- 해제: 사용자가 `..hub stop` 입력 시 플래그 해제 + AskUserQuestion 정상 복귀\n\n"
    "### 실시간 모니터링이 필요할 때 (Mode C)\n"
    "- 장시간 background 모니터링·SSE push 가 필요하면 `..hub dash <topic>` 로 dashboard agent 호출\n"
    "- Mode C 는 동일 ___pm htm-server 사용 (Issue45 이후 hub 과 공통)\n\n"
    "### 선택지 자동 승격 (Issue16_3·Issue16_6, 필수)\n"
    "- **트리거 (3 조건 모두 충족 시)**: `.hub-mode-active` 활성 + 응답이 N=2~4 선택지 (번호/알파벳/dash 리스트) + 결정 요청 문구 (\"선택해줘\", \"어느 옵션\", \"y/N\", \"번호로 답해\", \"골라줘\", \"어느 쪽\", \"Yes/No\" 등)\n"
    "- **동작**: 텍스트 bullet dump 금지. 응답 본문(HTML)은 옵션 설명·비교만, 결정 요청은 반드시 `AskUserQuestion` 호출로 분리. intercept hook 이 form 자동 회수 분기\n"
    "- **호출 예**: `AskUserQuestion(questions=[{\"question\":\"...\",\"header\":\"...\",\"multiSelect\":false,\"options\":[{\"label\":\"A (권장)\",\"description\":\"...\"}, ...]}])` — 권장안은 `options[0]` + label 끝 `(권장)`\n"
    "- **예외** (텍스트 유지): 단순 비교표·정보성 답변·코드 dump·옵션 5개 이상·simple confirm 외 정보성 응답\n"
    "- 상세: `~/.claude/commands/hub.md`\n"
)

print(json.dumps({"hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": context
}}, ensure_ascii=False))
PYEOF
  exit 0
fi

# Issue83: render 마커(`..show`/`..hub`) 없음 — 프로젝트 폴더는 hub 기본 on (per-cwd 상태 파일로 override)
# Issue105: 시스템 OFF 플래그가 최우선 — 존재 시 모든 프로젝트 자동 모드 차단
#   판정 우선순위: SYSTEM_OFF_FLAG > STATE_FILE > IS_PROJECT
EFFECTIVE="off"
if [ -f "$SYSTEM_OFF_FLAG" ]; then
  EFFECTIVE="off"
elif [ -f "$STATE_FILE" ]; then
  EFFECTIVE=$(tr -d '[:space:]' < "$STATE_FILE" 2>/dev/null)
elif [ "$IS_PROJECT" = "1" ]; then
  EFFECTIVE="on"
fi

if [ "$EFFECTIVE" = "on" ]; then
  # 플래그 활성화 — 후속 AskUserQuestion intercept + 선택지 자동 승격용
  touch "$FLAG_FILE"
  PROJECT_NAME="$PROJECT_NAME" \
    PROJECT_COLOR="$PROJECT_COLOR" \
    PROJECT_CWD="$cwd" \
    SID="$SID" \
    SID_FULL="$SID_FULL" \
    OUT_DIR="$OUT_DIR" \
    HTM_OPEN_CMD="$HTM_OPEN_CMD" \
    python3 <<'PYEOF'
import os, json

project_name = os.environ.get('PROJECT_NAME', 'unknown')
project_color = os.environ.get('PROJECT_COLOR', 'hsl(220,60%,45%)')
cwd = os.environ.get('PROJECT_CWD', '')
sid = os.environ.get('SID', 'unknown')
sid_full = os.environ.get('SID_FULL', sid)
out_dir = os.environ.get('OUT_DIR', '/tmp/___pm')
open_cmd = os.environ.get('HTM_OPEN_CMD', 'open -g -a Firefox')
path_note = "프로젝트 로컬 (_doc_work/z_htm/)" if out_dir != '/tmp/___pm' else "/tmp fallback"

# Issue132: CANONICAL 헤더 블록 — verbatim 복붙 강제 (정적 span·순서 뒤바뀜·헤더 밖 overflow 재발 차단)
canonical_header = (
    "3. **⚠️ CANONICAL 헤더 블록 (Issue132) — 아래 HTML·CSS verbatim 복붙. 즉흥 재작성 금지** "
    "(정적 `<span>`·순서 뒤바뀜·헤더 밖 overflow 재발 원인). `{제목}` 만 콘텐츠로 치환 (배지명·경로·색은 이미 임베드됨):\n"
    "```html\n"
    "<header>\n"
    "  <h1>{제목}</h1>\n"
    "  <nav class=\"header-actions\">\n"
    "    <a class=\"proj-badge\" href=\"#\" title=\"클릭 → VSCode 로 __PNAME__ 열기\"\n"
    "       onclick=\"event.preventDefault();fetch('http://127.0.0.1:9876/open-project',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cwd:'__CWD__'})}).then(function(r){return r.json();}).then(function(j){if(j&&j.error)alert('VSCode 열기 실패: '+j.error);}).catch(function(){alert('hub 서버 미응답 — VSCode 열기 실패');});\">📁 __PNAME__</a>\n"
    "    <a class=\"sess-link\" href=\"#\" title=\"클릭 → 이 문서를 만든 세션 탭으로 포커스\"\n"
    "       onclick=\"event.preventDefault();fetch('http://127.0.0.1:9876/open-session',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cwd:'__CWD__',sid:'__SID__'})}).then(function(r){return r.json();}).then(function(j){if(j&&j.error)alert('세션 열기 실패: '+j.error);}).catch(function(){alert('hub 서버 미응답 — 세션 열기 실패');});\">🎯 세션</a>\n"
    "    <a class=\"hub-link\" href=\"http://127.0.0.1:9876/hub\" target=\"_blank\">🗂 Hub</a>\n"
    "    <button type=\"button\" onclick=\"window.close()\">닫기 ✕</button>\n"
    "  </nav>\n"
    "</header>\n"
    "```\n"
    "```css\n"
    "header { position: sticky; top: 0; z-index: 100; display: flex; align-items: center;\n"
    "  justify-content: space-between; gap: 1rem; flex-wrap: wrap; padding: 0.9rem 1.4rem;\n"
    "  background: __PCOLOR__; color: #fff; }\n"
    "header h1 { margin: 0; font-size: 1.15rem; flex: 1 1 auto; min-width: 0; }\n"
    "header .header-actions { display: flex; align-items: center; gap: 0.5rem; flex: 0 0 auto; }\n"
    "header .proj-badge, header .sess-link, header .hub-link, header button { color: #fff; text-decoration: none;\n"
    "  cursor: pointer; white-space: nowrap; background: rgba(255,255,255,0.15);\n"
    "  border: 1px solid rgba(255,255,255,0.35); padding: 0.2rem 0.6rem; border-radius: 6px; font-size: 0.85rem; }\n"
    "header .proj-badge:hover, header .sess-link:hover, header .hub-link:hover, header button:hover {\n"
    "  background: rgba(255,255,255,0.28); text-decoration: underline; }\n"
    "```\n"
    "   불변식 (재발 차단): 배지=`<a class=\"proj-badge\" onclick=...POST /open-project...>` (정적 span 금지·Issue103), 세션=`<a class=\"sess-link\" onclick=...POST /open-session {cwd,sid}...>` (Issue137) → "
    "순서 `📁 배지`→`🎯 세션`→`🗂 Hub`→`닫기 ✕` → 넷 모두 `<header>` 안 `.header-actions` 동일 행 (헤더 밖 div 금지·Issue88) → "
    "flex+space-between+wrap 로 우측 overflow 방지. 조상(`html`/`body`/컨테이너)에 `overflow:hidden|clip` 금지 (sticky 무효화).\n"
).replace("__PNAME__", project_name).replace("__PCOLOR__", project_color).replace("__CWD__", cwd).replace("__SID__", sid_full)

context = (
    "## 세션 모드: hub 기본 on (프로젝트 폴더 — Issue83)\n\n"
    f"이 폴더는 ___pm 등록 프로젝트 (`{project_name}`). hub 모드 자동 활성 — 매 응답을 HTML 문서로 렌더하여 Firefox 에 표시.\n\n"
    "### 핵심 — 작업은 정상 수행\n"
    "- 요청된 작업·슬래시 커맨드(`/dev`, `/issue-*` 등)·dev 사이클·커밋 **모두 정상 진행**. HTML 렌더는 결과의 *표현*이며 작업 대체 아님.\n"
    "- 명시적 `..show`(render-only, 워크플로우 차단)과 다름 — 자동 모드는 차단 없음.\n\n"
    "### 응답 본문 처리\n"
    "0. **trivial 응답이면 hub 전체 skip (Issue85)** — HTML 작성·Firefox open 없이 평문 caveman 채팅으로 답하고 종료. "
    "trivial = 짧은 사실 답변·단순 확인(yes/no)·명령어/경로 안내 등 HTML 렌더 가치(표·코드블록·다이어그램·다단계 설명) 없는 응답. "
    "판단 모호하면 렌더 (기본 on 정책 유지)\n"
    "1. trivial 단발 질의(yes/no, A/B 선택, 정답 spoiler 위험)면 본문 HTML skip → 바로 `AskUserQuestion` 호출 (intercept 가 폼 처리)\n"
    "2. 그 외 — 응답 본문을 **완전한 HTML 문서**로 작성: `<!DOCTYPE html>`, `<html lang=\"ko\">`, "
    "`<head>`(meta charset/viewport, `<title>` prefix `\"" + project_name + " — <제목>\"`), "
    "`<style>`(시스템 폰트, max-width 820px, line-height 1.7, 다크모드 `@media (prefers-color-scheme: dark)`), `<body>`\n"
    + canonical_header +
    "4. HTML 본문은 **caveman 압축 제외** — 자연스러운 한국어 산문·완전한 문장. 표·코드블록·blockquote 자유. "
    "프로세스·인과·구조 성격 내용은 mermaid 다이어그램 우선 렌더\n"
    "5. `Write` → `" + out_dir + "/hub_htm_<YYYYMMDD_HHMMSS>_a_<주제>.htm` (" + path_note + ") — 날짜시간=`date +%Y%m%d_%H%M%S`, 주제=핵심 10자 내외 kebab, mode `a`=메인 렌더\n"
    f"6. Bash → `{open_cmd} \"file://<절대경로>\"` (브라우저·포커스 = `browser_focus`/`default_browser` 설정. `-g`=백그라운드, 포커스 미탈취)\n"
    "7. 채팅 응답(caveman 유지): 한 줄 헤드라인 + 핵심 bullet 2~3개 + 저장 경로. "
    "채팅 fallback 이 1차 채널 (Firefox 미표시 가정 — 채팅만 읽어도 내용 파악·재오픈 가능해야 함)\n\n"
    "### 후속 질문\n"
    "- `AskUserQuestion` 호출 시 PreToolUse hook(`ask-intercept.sh`)이 form 자동 회수 — deny reason 절차를 그대로 따를 것\n"
    "- 선택지 자동 승격: 응답이 2~4 선택지 + 결정 요청 문구면 텍스트 dump 금지 → `AskUserQuestion` 호출로 분리\n\n"
    "### 상세 / 해제\n"
    "- HTML 템플릿·mermaid·폼 규약: `~/.claude/commands/hub.md`\n"
    "- 이 폴더에서 hub 끄기: `..hub stop` (per-folder 영구 off — `~/.claude/.hub-state/` 기록). 다시 켜기: `..hub start`\n"
)

print(json.dumps({"hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": context
}}, ensure_ascii=False))
PYEOF
else
  # 비프로젝트 + 마커 없음, 또는 이 폴더 off 기록 → 플래그 비활성 (intercept 미동작)
  rm -f "$FLAG_FILE"
fi

exit 0
