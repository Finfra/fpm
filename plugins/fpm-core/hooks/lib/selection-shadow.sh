#!/usr/bin/env bash
# selection-shadow.sh — hook 용 Jev shadow 판정 분리 기동 (prj3#Issue863_17)
#
# ⚠️ 글로벌 SCAR 변경 가드 (Issue46): cwd ≠ ~/.claude 면 즉시 수정 금지 → ~/.claude/Issue.md 이슈 등록 후 처리.
#   설계 SSOT: ~/.claude/_doc_arch/selection-arch.md §범용 판정 진입점 «동기 hook 은 직접 부르지 않는다»
#
# 왜 — UPS·Stop hook 은 지연 예산(200ms) 안에서 끝나야 한다. Jev 왕복(약 200~400ms)을 기다리지 않도록
#   `selection.py shadow` 를 서브셸 백그라운드로 띄우고 바로 돌아온다. 가드(꺼짐·격리 원장·mode off)와 캐시는
#   파이썬 쪽(`shadow`)이 본다 — 여기는 기동만 한다. 결과는 원장 기록뿐이고 hook 출력은 바뀌지 않는다.
#
# 사용: . selection-shadow.sh; sel_shadow <kind> <text> <static> [cache-key]
#   대역 SELECTION_SPAWN_CMD(테스트) — 지정하면 `python3 selection.py` 대신 그 실행 파일을 같은 인자로 부른다.

_SEL_PY="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)/selection.py"

sel_shadow() {
  local kind="$1" text="$2" static="$3" key="${4:-}"
  [ -n "$kind" ] && [ -n "$text" ] || return 0
  if [ -n "${SELECTION_SPAWN_CMD:-}" ]; then
    ( "$SELECTION_SPAWN_CMD" shadow --kind "$kind" --text "$text" --static "$static" ${key:+--cache-key "$key"} \
        </dev/null >/dev/null 2>&1 & )
  else
    ( python3 "$_SEL_PY" shadow --kind "$kind" --text "$text" --static "$static" ${key:+--cache-key "$key"} \
        </dev/null >/dev/null 2>&1 & )
  fi
  return 0
}
