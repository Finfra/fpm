#!/usr/bin/env bash
# scar-export.sh — fPm SCAR(fpm-core) → Cursor·Codex·Gemini export (Issue234 T7)
#
# fpm-core 번들의 commands·skills·agents 를 타 AI 코딩 툴 포맷으로 단방향 export.
#   codex  → AGENTS.md / gemini → GEMINI.md / cursor → .cursor/rules/*.mdc
#
# 사용법: scar-export.sh [--target codex|gemini|cursor|all] [--out DIR] [--full]
# 설계 SSOT: _doc_work/plan/scar-crosstool-export_plan.md
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
exec python3 "$HERE/scar-export/emit.py" "$@"
