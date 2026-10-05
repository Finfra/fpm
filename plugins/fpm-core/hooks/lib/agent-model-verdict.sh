#!/usr/bin/env bash
# agent-model-verdict.sh — Agent 호출 Fable 거부 판정 **단일 지점** (source 전용 라이브러리), prj3#Issue849
#
# ⚠️ 글로벌 SCAR 변경 가드 (Issue46): cwd ≠ ~/.claude 면 즉시 수정 금지 → ~/.claude/Issue.md 이슈 등록 후 처리.
#   배선 색인: ~/.claude/_doc_arch/hook-arch.md · 설계: ~/.claude/_doc_arch/claude-model-rules.md «Fable 허용 목록»
#
# 왜 라이브러리인가(hook-rules 규칙5·8): PreToolUse(Agent) 에는 hook 이 여럿 걸려 **병렬**로 돈다. 거부는
#   agent-model-guard.sh 가 내지만, 형제(fbot-agent-bind·fbot-agent-map)는 그 사실을 모른 채 결속·대기열 적재를
#   남긴다(codex plan 점검 지적 1). 순서에 기대지 않고 **같은 판정을 각자 읽게** 한다.
#
# 사용: . "$HOOKS/lib/agent-model-verdict.sh"; if reason=$(agent_model_verdict "$input"); then … 거부 …; fi
#   rc 0 = 거부(사유를 stdout) · rc 1 = 통과. `"model": "fable"` 패턴이 없으면 빌트인 판정만(fork 0).
#   정책 파일이 없거나 깨지면 허용 목록 0(거부 쪽). python3 부재·JSON 파싱 실패는 통과(fail-open).

agent_model_verdict() {
  local in="$1" r
  [[ "$in" == *'"fable"'* ]] || return 1
  [[ "$in" =~ \"model\"[[:space:]]*:[[:space:]]*\"fable\" ]] || return 1
  command -v python3 >/dev/null 2>&1 || return 1
  r=$(printf '%s' "$in" | python3 -c '
import json, os, sys
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)
if d.get("tool_name") != "Agent":
    sys.exit(0)
ti = d.get("tool_input") or {}
if ti.get("model") != "fable":
    sys.exit(0)
st = ti.get("subagent_type") or "general-purpose"
allowed = set()
try:
    import yaml
    with open(os.path.expanduser("~/.claude/data/model-tier.yml"), encoding="utf-8") as fh:
        p = yaml.safe_load(fh) or {}
    a = (p.get("fable_allowed") or {}).get("agents") or []
    allowed = set(a) if isinstance(a, list) else set()
except Exception:
    allowed = set()
if st not in allowed:
    print(f"Fable 은 허용 목록(~/.claude/data/model-tier.yml fable_allowed.agents) 밖 agent 에 쓰지 않는다: {st} "
          "— 허용 목록 0 (사용자 결정 2026-10-02 · prj3#Issue849). model 을 빼거나(frontmatter 기본값) sonnet·opus 로 "
          "다시 호출할 것. Fable 이 꼭 필요하면 사람이 메인 세션을 /model fable 로 바꿔 직접 수행한다.")
' 2>/dev/null) || return 1
  [ -n "$r" ] || return 1
  printf '%s' "$r"
  return 0
}
