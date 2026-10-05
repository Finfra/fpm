#!/bin/bash
# claude-pid.sh — hub live 등록용 claude 세션 pid 산출 공용 헬퍼 (source 전용, 실행 파일 아님)
#
# ⚠️ 글로벌 SCAR 변경 가드 (Issue46): 본 헬퍼는 모든 프로젝트가 공유. cwd ≠ ~/.claude
#   면 즉시 수정 금지 → ~/.claude/Issue.md 이슈 등록 후 처리. 설계 SSOT:
#   ~/_git/___pm/_doc_arch/hub_live_session.md. 절차: ~/.claude/rules/global-scar-change-rules.md
#
# Issue428 (prj1#Issue341 일반화): stdin JSON 의 pid·훅 $PPID 를 그대로 믿으면 안 된다.
#   일부 환경(Linux/VSCode 확장·macOS native-binary)에서 그 값이 장수 claude 세션이 아니라
#   훅을 스폰한 **단기 wrapper/subprocess pid** 다. 그 pid 로 /session/register 하면 등록
#   직후 pid 가 죽어 서버 _collect_live_sessions 가 세션을 terminal 로 강등 →
#   살아있는 세션이 hub 활성 세션 카드에서 사라진다(prj9a 실측: 생존 4세션 중 2개만 표시).
#
#   원래 fpm-hub-session-register.sh(SessionStart)에만 있던 보정을 본 lib 로 추출해
#   topic.sh(UserPromptSubmit)·model.sh(Stop·PostToolUse) 재등록 경로에도 동일 적용한다
#   — 판정 단일 지점. 재등록은 서버에서 live_pid 를 무조건 덮어쓰므로(server.py
#   _handle_session_register) 한 곳이라도 오염 pid 를 보내면 좋은 pid 가 교체된다.
#
# 비용 가드: ps 조회는 체인 최대 10단계 × 프로세스당 2회. 등록 훅은 전부
#   fire-and-forget 경로라 차단성 아님. 비해당 이벤트에서는 source 자체가 안 일어난다.

_fpm_pid_alive() { kill -0 "$1" 2>/dev/null; }

_fpm_ppid_of() { ps -o ppid= -p "$1" 2>/dev/null | tr -d ' '; }

# comm basename 이 claude 계열이거나, args 가 claude 배포본 cli.js/native-binary 를 실행
# 중이면 세션 프로세스.
#   ⚠️ args 에 "claude" 문자열만 보고 판정하면 안 된다 — `zsh -c source ~/.claude/...`
#      같은 무관 프로세스가 걸린다(실측 오탐).
_fpm_is_claude_proc() {
  _c=$(ps -o comm= -p "$1" 2>/dev/null); _c=${_c##*/}
  case "$_c" in claude|claude-code) return 0 ;; esac
  case "$(ps -o args= -p "$1" 2>/dev/null)" in
    *claude*cli.js*|*claude-code*|*native-binary/claude*) return 0 ;;
  esac
  return 1
}

# fpm_resolve_claude_pid <candidate_pid> <hook_ppid> → stdout: 산출 pid
#   1) candidate 가 정수 아니거나 사망 → hook_ppid 로 대체
#   2) 부모 체인을 최대 10단계 타고 올라가 claude 세션 프로세스를 찾으면 승격
#   3) 못 찾으면 1) 결과 그대로 (기존 fallback 동작 유지)
fpm_resolve_claude_pid() {
  _fpm_resolve_into "$1" "$2"
  printf '%s' "$_FPM_PID"
}

# _fpm_resolve_into <candidate_pid> <hook_ppid> — 위와 같은 판정, 결과를 현재 셸 변수로:
#   _FPM_PID(산출 pid) · _FPM_PROMOTED(1 = 체인에서 claude 세션 프로세스를 찾았다)
_fpm_resolve_into() {
  _pid="$1"; _hook_ppid="$2"; _FPM_PROMOTED=0
  case "$_pid" in ''|*[!0-9]*) _pid="$_hook_ppid" ;; esac
  _fpm_pid_alive "$_pid" || _pid="$_hook_ppid"
  _p="$_pid"; _i=0
  while [ -n "$_p" ] && [ "$_p" != "0" ] && [ "$_p" != "1" ] && [ "$_i" -lt 10 ]; do
    if _fpm_is_claude_proc "$_p"; then _pid="$_p"; _FPM_PROMOTED=1; break; fi
    _p=$(_fpm_ppid_of "$_p"); _i=$((_i + 1))
  done
  _FPM_PID="$_pid"
}

# fpm_claude_pid_cached_into <sid> <candidate_pid> <hook_ppid> → 현재 셸 변수 _FPM_PID
#   Issue803: 매 프롬프트 체인을 타던 ps(4~5회)를 세션별 캐시로. 한 세션의 claude 프로세스는
#   세션 내내 같으므로 체인 결과는 같다 — 판정 결과 동등.
#   * 캐시는 **승격에 성공했을 때만** 쓴다 — fallback(hook_ppid)은 단명 wrapper 라 재사용하면
#     Issue428 이 재발한다
#   * 적중 검증: kill -0(내장) + claude 프로세스 판정(ps 1회) — 세션 종료 후 pid 가 남의
#     프로세스로 재사용된 경우를 걸러낸다. 실패하면 캐시를 버리고 체인을 다시 탄다
#   * `$(…)` 로 부르면 결과 변수가 부모로 안 올라온다 — 현재 셸에서 부르고 _FPM_PID 를 읽는다
#   캐시 위치 `${TMPDIR}/___pm/claude-pid/<sid>` (hub-context 캐시와 같은 뿌리, 재부팅 시 소멸)
fpm_claude_pid_cached_into() {
  _fpm_sid="$1"; _fpm_cf=""
  case "$_fpm_sid" in
    ''|*[!A-Za-z0-9_-]*) ;;   # 경로로 쓸 수 없는 sid → 캐시 없이
    *) _fpm_cf="${TMPDIR:-/tmp}/___pm/claude-pid/$_fpm_sid" ;;
  esac
  if [ -n "$_fpm_cf" ] && [ -s "$_fpm_cf" ]; then
    _fpm_c=""; read -r _fpm_c < "$_fpm_cf" 2>/dev/null
    case "$_fpm_c" in
      ''|*[!0-9]*) ;;
      *) if _fpm_pid_alive "$_fpm_c" && _fpm_is_claude_proc "$_fpm_c"; then
           _FPM_PID="$_fpm_c"; _FPM_PROMOTED=1; return 0
         fi ;;
    esac
  fi
  _fpm_resolve_into "$2" "$3"
  if [ "$_FPM_PROMOTED" = 1 ] && [ -n "$_fpm_cf" ]; then
    [ -d "${_fpm_cf%/*}" ] || mkdir -p "${_fpm_cf%/*}" 2>/dev/null
    printf '%s\n' "$_FPM_PID" > "$_fpm_cf.$$" 2>/dev/null && mv -f "$_fpm_cf.$$" "$_fpm_cf" 2>/dev/null \
      || rm -f "$_fpm_cf.$$" 2>/dev/null
  fi
  return 0
}
