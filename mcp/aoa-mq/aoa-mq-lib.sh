#!/usr/bin/env bash
# aoa-mq-lib.sh — aoa-mq 판정 단일 지점 라이브러리 (source 전용, 배선 없음), prj3#Issue770
#
# ⚠️ 글로벌 SCAR 변경 가드 (prj3#Issue46): 본 라이브러리는 aoa-mq 를 쓰는 모든 프로젝트가 공유.
#   cwd ≠ ~/.claude 면 즉시 수정 금지 → ~/.claude/Issue.md 이슈 등록 후 처리.
#   설계 SSOT: ~/.claude/_doc_arch/aoa-mq.md "대상 prj·승인 판정 (Issue770)"
#
# 왜 뽑았나 (Issue770 원인 ②③④):
#   같은 사실을 tick·helper·session-inbox·hub 가 각자 판정하면 갈라진다 — 이 저장소가 반복해 겪은
#   *한쪽만 갱신되어 갈라진 계약* 이다. 7.8 주석은 «[진행] = 승인» 이라 쓰고도 [컨펌] 을 제외했고,
#   넛지는 대상 prj 를 보지 않았고, 기동 cwd 는 고정이었다. 판정을 여기 한 곳에 둔다:
#     · 대상 prj      — aoa_mq_target (target 필드 → message 첫 prjN → source → 기본)
#     · 세션의 prj    — aoa_mq_project_of_cwd (가장 긴 접두 — prj0 `~` 가 모두를 삼키지 않게)
#     · 승인 술어     — aoa_mq_launch_blocked ([컨펌] 이면서 approved_ts 없음 → 차단)
#     · 기동 한 벌    — aoa_mq_prompt · aoa_mq_claude_bin · aoa_mq_hr_gate · aoa_mq_spawn
#
# 제약:
#   · **bash 3.2 호환** — tick 은 launchd 의 /bin/bash(3.2)로 돈다. 연관 배열·mapfile·${v,,} 금지
#   · **판정 함수는 외부 프로세스를 띄우지 않는다** — session-inbox 는 UserPromptSubmit 차단 경로(200ms)라
#     fork 하나가 곧 사용자 입력 지연이다. 파일 읽기는 내장 `read` 만 쓴다
#   · 번호 → 경로 SSOT 는 `~/_git/___pm/projects/{N}`(1줄 경로 — 글로벌 CLAUDE.md). 테스트는
#     AOA_MQ_PROJECTS_DIR 로 바꾼다. 디렉터리가 없는 머신(prj1 미클론)은 전부 «미상» 으로 떨어진다

# ── 프로젝트 표 (번호 ↔ 경로) — 1회 적재 ───────────────────────────────
AOA_MQ_PRJ_LOADED=0
AOA_MQ_PRJ_IDS=()
AOA_MQ_PRJ_PATHS=()

_aoa_mq_norm_path() { # $1=경로 → MQ_NP (~ 확장·끝 공백·끝 / 제거)
  local p="$1"
  p="${p%$'\r'}"
  p="${p%"${p##*[![:space:]]}"}"
  case "$p" in
    "~")   p="$HOME" ;;
    "~/"*) p="$HOME/${p#\~/}" ;;
  esac
  while [ "${#p}" -gt 1 ] && [ "${p%/}" != "$p" ]; do p="${p%/}"; done
  MQ_NP="$p"
}

aoa_mq_projects_load() {
  [ "$AOA_MQ_PRJ_LOADED" = 1 ] && return 0
  AOA_MQ_PRJ_LOADED=1
  local dir="${AOA_MQ_PROJECTS_DIR:-$HOME/_git/___pm/projects}" f n p
  [ -d "$dir" ] || return 0
  for f in "$dir"/*; do
    [ -f "$f" ] || continue
    n="${f##*/}"
    p=""
    IFS= read -r p < "$f" || [ -n "$p" ] || continue
    [ -n "$p" ] || continue
    _aoa_mq_norm_path "$p"
    AOA_MQ_PRJ_IDS[${#AOA_MQ_PRJ_IDS[@]}]="$n"
    AOA_MQ_PRJ_PATHS[${#AOA_MQ_PRJ_PATHS[@]}]="$MQ_NP"
  done
  return 0
}

aoa_mq_prj_path() { # $1=번호(prj 접두 허용) → MQ_PP. 없으면 return 1
  local n="${1#prj}" i=0
  MQ_PP=""
  aoa_mq_projects_load
  while [ "$i" -lt "${#AOA_MQ_PRJ_IDS[@]}" ]; do
    if [ "${AOA_MQ_PRJ_IDS[$i]}" = "$n" ]; then MQ_PP="${AOA_MQ_PRJ_PATHS[$i]}"; return 0; fi
    i=$((i+1))
  done
  return 1
}

# ── 대상 prj 판정 (Issue770 원인 ③④) ─────────────────────────────────
# 입력: $1=target 필드 $2=message $3=source
# 출력(전역): MQ_T_PRJ(prjN|"") · MQ_T_CWD(경로) · MQ_T_VIA(target|message|source|default) · MQ_T_RESOLVED(1|0)
#   · 미상이면 cwd = ${AOA_MQ_CWD:-~/.claude} — 종전 7.8 기동 cwd 그대로(회귀 없음)
#   · 명시 target 인데 매핑 없음 → VIA=target · RESOLVED=0 · CWD="" (폴백 금지 — 아래 ①)
#   · 소비처 정책(미상 항목을 넛지가 어떻게 싣나 등)은 설계 문서 표가 정한다 — 판정은 여기 하나
aoa_mq_target() {
  local tgt="$1" msg="$2" src="$3" x n
  local re_tok='(^|[^A-Za-z0-9_])prj([0-9]+[a-z]?)([^A-Za-z0-9_]|$)'
  local re_head='^prj([0-9]+[a-z]?)([^A-Za-z0-9_]|$)'
  MQ_T_PRJ=""; MQ_T_CWD=""; MQ_T_VIA="default"; MQ_T_RESOLVED=0
  # ① 명시 target — 매핑이 없어도 **다음 단으로 넘기지 않는다**. 명시한 대상을 두고 message·source 로
  #   다른 prj 를 고르면 엉뚱한 곳에서 기동한다. cwd 를 비워 두면 기동 쪽은 «경로 없음» 으로 멈춘다
  #   (enqueue 가 등록 시 매핑을 검증하므로 여기 오는 것은 매핑이 다른 머신뿐이다)
  if [ -n "$tgt" ]; then
    MQ_T_PRJ="prj${tgt#prj}"; MQ_T_VIA="target"
    if aoa_mq_prj_path "$tgt"; then MQ_T_CWD="$MQ_PP"; MQ_T_RESOLVED=1; fi
    return 0
  fi
  # ② message 의 첫 prjN 토큰 (prj16#Issue265 · «prj5 Issue95» 형태)
  if [[ $msg =~ $re_tok ]]; then
    n="${BASH_REMATCH[2]}"
    if aoa_mq_prj_path "$n"; then
      MQ_T_PRJ="prj$n"; MQ_T_CWD="$MQ_PP"; MQ_T_VIA="message"; MQ_T_RESOLVED=1; return 0
    fi
  fi
  # ③ source — `<누구>@<basename|prjN>` · `prjN…`
  x=""
  case "$src" in
    *@*)      x="${src##*@}" ;;
    prj[0-9]*) x="$src" ;;
  esac
  if [ -n "$x" ]; then
    if [[ $x =~ $re_head ]]; then
      n="${BASH_REMATCH[1]}"
      if aoa_mq_prj_path "$n"; then
        MQ_T_PRJ="prj$n"; MQ_T_CWD="$MQ_PP"; MQ_T_VIA="source"; MQ_T_RESOLVED=1; return 0
      fi
    else
      local i=0
      aoa_mq_projects_load
      while [ "$i" -lt "${#AOA_MQ_PRJ_PATHS[@]}" ]; do
        if [ "${AOA_MQ_PRJ_PATHS[$i]##*/}" = "$x" ]; then
          MQ_T_PRJ="prj${AOA_MQ_PRJ_IDS[$i]}"; MQ_T_CWD="${AOA_MQ_PRJ_PATHS[$i]}"
          MQ_T_VIA="source"; MQ_T_RESOLVED=1; return 0
        fi
        i=$((i+1))
      done
    fi
  fi
  # ④ 미상 — 종전 기동 cwd
  _aoa_mq_norm_path "${AOA_MQ_CWD:-$HOME/.claude}"
  MQ_T_CWD="$MQ_NP"
  return 0
}

# ── 세션이 속한 prj — 가장 긴 접두 (Issue770 넛지 범위) ────────────────
# 입력: $1=cwd → MQ_C_PRJ(prjN|"") · MQ_C_CWD(프로젝트 루트, 없으면 cwd 자체)
#   ⚠️ «접두면 매칭» 으로 끝내면 prj0(`~`)이 모든 세션을 삼킨다 — 가장 긴 것만 인정한다
# ── 대상 prj 값 검증 (enqueue --target · progress retarget 공용 — Issue925) ──────
# 형식 prj<N>[a-z] + 매핑 존재. 실패면 return 1, 사유는 MQ_TV_ERR. 조용히 받아 두면 판정 ①단이
#   «경로 없음» 으로 멈추거나(기동 안 함) 오타 항목이 아무 세션에도 닿지 않는다
aoa_mq_check_target() { # $1=prjN
  local t="$1" n
  MQ_TV_ERR=""
  case "$t" in
    prj[0-9]*) ;;
    *) MQ_TV_ERR="prj<N> 형식이 아니다 (받음: '$t')"; return 1 ;;
  esac
  n="${t#prj}"
  case "$n" in *[!0-9a-z]*|[!0-9]*) MQ_TV_ERR="prj<N> 형식이 아니다 (받음: '$t')"; return 1 ;; esac
  aoa_mq_prj_path "$n" || {
    MQ_TV_ERR="$t — 번호 매핑 없음(${AOA_MQ_PROJECTS_DIR:-$HOME/_git/___pm/projects}/$n). 번호 확인"; return 1; }
  return 0
}

aoa_mq_project_of_cwd() {
  local i=0 best=-1 bestlen=-1 p
  _aoa_mq_norm_path "$1"; local c="$MQ_NP"
  aoa_mq_projects_load
  while [ "$i" -lt "${#AOA_MQ_PRJ_PATHS[@]}" ]; do
    p="${AOA_MQ_PRJ_PATHS[$i]}"
    if [ "$c" = "$p" ] || [ "${c#"$p"/}" != "$c" ]; then
      if [ "${#p}" -gt "$bestlen" ]; then best=$i; bestlen=${#p}; fi
    fi
    i=$((i+1))
  done
  if [ "$best" -ge 0 ]; then
    MQ_C_PRJ="prj${AOA_MQ_PRJ_IDS[$best]}"; MQ_C_CWD="${AOA_MQ_PRJ_PATHS[$best]}"
  else
    MQ_C_PRJ=""; MQ_C_CWD="$c"
  fi
  return 0
}

# ── 승인 술어 (Issue770 원인 ② — 판정 단일 지점) ───────────────────────
# 기록은 tick `start`(사람의 [진행] 클릭) 1곳이 approved_ts 를 남긴다. 여기서는 읽기만 한다.
#   [컨펌] 은 «사람 전결» 이지만 [진행] 을 눌렀으면 **착수는 승인됐다**(사용자 결정 2026-09-28).
#   비가역 단계는 needs_human 에서 따로 승인받는다 — 기동 자체를 막을 이유가 아니다.
aoa_mq_is_confirm() { case "$1" in *"[컨펌]"*) return 0 ;; esac; return 1; }
aoa_mq_launch_blocked() { # $1=message $2=approved_ts → 0 이면 **차단**
  aoa_mq_is_confirm "$1" && [ -z "$2" ]
}

# ── 기동 한 벌 (tick 7.8 무인 기동 · helper launch 즉시 기동 공용) ───────
# 프롬프트는 여기서 **완성**한다 — `-p` 는 되묻지 못한다. 백틱을 쓰지 않는다(조립이 따옴표 안이면
#   명령 치환이 된다). 인자 배열로 넘기므로 message 본문은 셸을 거치지 않는다.
aoa_mq_prompt() { # $1=mode(auto|start) $2=id $3=message $4=source $5=경과시간(h) $6=사람 몫(1줄, 없으면 빈 값)
  local mode="$1" id="$2" msg="$3" src="$4" age="$5" need="$6" head
  if [ "$mode" = start ]; then
    head="사용자가 hub /mq 에서 [진행] 을 눌러 이 작업의 착수를 승인했고, 이 세션을 즉시 기동했다."
  else
    head="사용자가 hub /mq 에서 [진행] 을 눌러 착수를 승인한 뒤 ${age}시간 동안 아무 세션도 이 작업을 집지 않았다. 이 세션이 착수한다."
  fi
  printf '%s\n' "[aoa-mq 기동 — 항목 ${id}]" "$head" "" "## 작업" "$msg" ""
  if [ -n "$need" ]; then
    printf '%s\n' "## 사람 몫(needs_human — 아직 해소 안 됨)" "$need" ""
  fi
  printf '%s\n' \
    "## 규약" \
    "- 항목 id: ${id} · 발신: ${src}" \
    "- 사용자가 [진행]으로 착수 승인함 — 세션 가능 단계는 수행, 비가역 단계는 needs_human 에 올리고 멈춘다. 되묻지 않는다" \
    "- 사람의 결정·행동이 필요하면 산문으로 적고 턴을 끝내지 않는다 — MCP aoa_mq_progress 의 needs_human 인자(또는 bash ~/.claude/mcp/aoa-mq/aoa-mq-progress.sh need ${id} --text \"decide:… | act:…\")로 기록한다. decide: 는 결정, act: 는 사람의 물리 행동" \
    "- 외부 조건을 기다려야 하면 aoa_mq_progress 의 wait_for·recheck(또는 helper wait ${id} --for \"<조건>\" --recheck <시각>)로 대기 전환한다. 진행 중으로 방치하지 않는다" \
    "- 진행은 aoa_mq_progress 의 progress 로 남긴다. 끝나면 aoa_mq_ack 로 confirmed 종결하고 result 에 산출물을 적는다" \
    "- 아래는 사용자 승인 없이 실행 금지: 파일 파괴(rm -rf·대량 삭제)·git 파괴(reset --hard·push --force·branch -D)·외부 시스템 쓰기(배포·게시·결제·원격 동기화)·타 repo 커밋·타 prj 세션 기동 — 이것들이 곧 needs_human 이다"
}

aoa_mq_claude_bin() { # → MQ_CLAUDE_BIN. **실행으로 확인한다**(PATH 존재만 보는 가드가 launchd 에서 3일 죽은 Issue505 전례)
  MQ_CLAUDE_BIN="${AOA_MQ_CLAUDE_BIN:-}"
  [ -n "$MQ_CLAUDE_BIN" ] || MQ_CLAUDE_BIN="$(command -v claude 2>/dev/null)"
  [ -n "$MQ_CLAUDE_BIN" ] || MQ_CLAUDE_BIN="$HOME/.local/bin/claude"
  "$MQ_CLAUDE_BIN" --version >/dev/null 2>&1
}

aoa_mq_hr_gate() { # $1=로그 파일 → 0 통과 · 1 거부·오류 · 2 게이트 부재. **fail-closed** 는 호출부 몫
  local g="${AOA_MQ_HR_GATE:-$HOME/.claude/hooks/fbot-hr-gate.py}"
  [ -f "$g" ] || return 2
  python3 "$g" check --parent - --depth 0 >> "$1" 2>&1 || return 1
  return 0
}

aoa_mq_spawn() { # $1=cwd $2=id $3=prompt $4=로그 파일 [$5=작업 메시지 — 있으면 Jev 로 모델 선택] — MQ_CLAUDE_BIN 이 먼저 정해져 있어야 한다
  [ -d "$1" ] || return 1
  # prj3#Issue863_7 — 작업 메시지(사람이 [진행] 을 누른 항목 본문)로 모델을 고른다. pick 은 별칭 한 줄·실패해도 기본값(rc 0).
  #   별칭 밖 출력은 버린다(기동 줄 주입 방지). 메시지가 없으면 종전과 같다(settings 모델 상속)
  local _m="" _ma=()
  if [ -n "${5:-}" ]; then
    _m=$(python3 "${CLAUDE_DIR:-$HOME/.claude}/hooks/lib/selection.py" pick --question "$5" 2>/dev/null | head -1)
    case "$_m" in haiku|sonnet|opus) _ma=(--model "$_m") ;; *) _ma=() ;; esac
  fi
  # 봇 정체성 env 차단 (Issue679) — 호출자가 봇 세션이어도 자식이 그 봇을 결속하지 않게
  ( cd "$1" || exit 1
    _s="${CLAUDE_DIR:-$HOME/.claude}/hooks/fbot-env-scrub.sh"
    if [ -r "$_s" ]; then . "$_s" && fbot_env_scrub; fi
    # prj3#Issue859_2 — 권한 플래그는 fbot-org.py launch-flags 단일 지점. mq 세션은 자리 키(봇)가 없어 현행 플래그가 나온다.
    #   해소기 실행 불가면 빈 값 = claude 기본 권한(권한을 넓히는 쪽으로 실패하지 않는다)
    _pf=$(python3 "${CLAUDE_DIR:-$HOME/.claude}/hooks/fbot-org.py" launch-flags 2>/dev/null)
    # shellcheck disable=SC2086 — 플래그 한 줄을 단어로 나눠 넘긴다(해소기가 만든 값만)
    AOA_MQ_WAKE_ID="$2" nohup "$MQ_CLAUDE_BIN" $_pf ${_ma[@]+"${_ma[@]}"} -p "$3" >> "$4" 2>&1 & )
}
