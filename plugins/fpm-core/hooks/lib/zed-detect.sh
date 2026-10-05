#!/bin/bash
# zed-detect.sh — Zed 세션 판정 공용 헬퍼 (source 전용, 실행 파일 아님)
#
# ⚠️ 글로벌 SCAR 변경 가드 (Issue46): 본 헬퍼는 모든 프로젝트가 공유. cwd ≠ ~/.claude
#   면 즉시 수정 금지 → ~/.claude/Issue.md 이슈 등록 후 처리. 설계 SSOT:
#   ~/_git/___pm/_doc_arch/editor-abstraction-design.md. 절차: ~/.claude/rules/global-scar-change-rules.md
#
# Issue289: Zed 는 VSCode 확장이 아니라 ACP 브리지(@agentclientprotocol/claude-agent-acp)로
#   Claude Code 를 붙인다 → ~/.claude/ide/*.lock 미생성 + CLAUDE_CODE_ENTRYPOINT=sdk-ts.
#   유일하게 남는 결정적 신호는 **부모 프로세스 체인**:
#     Zed.app → npm exec @agentclientprotocol/claude-agent-acp → node .bin/claude-agent-acp → claude
#
# 비용 가드: ps 조회는 SessionStart 1회만. 판정 결과는 마커 파일로 캐시하고
#   매 렌더(fpm-hub-trigger)에서는 마커 존재 여부만 본다(ps 재조회 금지).

# 주입구 ZED_MARKER_DIR 는 테스트 전용(prj3#Issue912) — 운영에선 설정하지 않는다
ZED_MARKER_DIR="${ZED_MARKER_DIR:-$HOME/.claude/.zed-sessions}"

# zed_detect_by_proc <start_pid> → rc 0 = Zed 세션
#   조상 체인을 최대 12단계 거슬러 올라가며 claude-agent-acp / Zed.app 을 찾는다.
zed_detect_by_proc() {
  local pid="$1" depth=0 line ppid cmd
  case "$pid" in ''|*[!0-9]*) return 1 ;; esac
  while [ "$depth" -lt 12 ] && [ -n "$pid" ] && [ "$pid" != "0" ] && [ "$pid" != "1" ]; do
    line=$(ps -o ppid=,command= -p "$pid" 2>/dev/null) || return 1
    [ -z "$line" ] && return 1
    ppid=$(printf '%s' "$line" | awk '{print $1}')
    cmd=$(printf '%s' "$line" | cut -d' ' -f2-)
    case "$cmd" in
      *claude-agent-acp*|*Zed.app*|*/zed\ *|*/zed) return 0 ;;
    esac
    pid="$ppid"
    depth=$((depth + 1))
  done
  return 1
}

# zed_marker_path <sid> → 마커 경로 (파일명 안전화)
zed_marker_path() {
  local sid
  sid=$(printf '%s' "$1" | tr -c 'A-Za-z0-9-' '-')
  printf '%s/%s' "$ZED_MARKER_DIR" "$sid"
}

# zed_mark <sid> — Zed 세션 마커 기록 + 7일 초과 마커 prune
zed_mark() {
  [ -n "$1" ] || return 0
  mkdir -p "$ZED_MARKER_DIR" 2>/dev/null || return 0
  : > "$(zed_marker_path "$1")" 2>/dev/null
  find "$ZED_MARKER_DIR" -type f -mtime +7 -delete 2>/dev/null
}

# zed_is_marked <sid> → rc 0 = 캐시된 Zed 세션 (ps 조회 없음)
#   prj3#Issue912: 외부 exec 0 — 매 AskUserQuestion 의 무음 경로(Issue845 하한 가드)에서 불린다.
#   zed_marker_path 의 `tr -c` 와 같은 안전화를 bash 치환으로 한다(서브셸·tr 없음).
zed_is_marked() {
  [ -n "$1" ] || return 1
  [ -f "$ZED_MARKER_DIR/${1//[^A-Za-z0-9-]/-}" ]
}
