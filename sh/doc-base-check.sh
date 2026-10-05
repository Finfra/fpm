#!/usr/bin/env bash
# doc-base-check.sh — 문서 추적 선언 ↔ 실태 대조 (2축: `_doc_base/` Issue477 · docs 6항목 Issue497)
#
# 왜 필요한가: 구 규칙(`_doc_base gitignore ⟺ remote origin`)은 **검사 수단이 없어서**
#   조용히 무너졌다. 2026-09-05 전수 조사에서 실태가 3분기로 갈렸다 —
#   PUBLIC 인데 추적 1건, PRIVATE 인데 미추적 8건(백업 0), PRIVATE 인데 추적 3건.
#   각 프로젝트가 다른 이유로 결정했고 그 이유가 아무 데도 적혀 있지 않았다.
#   판정을 명시 선언으로 옮긴 이상, **선언이 지켜지는지 보는 눈**이 함께 있어야 한다.
#
# 축2 — docs 6항목 (Issue497, 2026-09-20)
#   선언  : 같은 파일의 `docs: track|ignore`   실태: Issue.md·CLAUDE.md·_doc_arch/ 추적 여부
#     track  + tracked    → OK
#     ignore + untracked  → OK
#     track  + untracked  → 🚨 유실 위험 (선언은 열라는데 .gitignore 가 막고 있다)
#     ignore + tracked    → 🚨 선언과 실태 불일치 (gitignore 는 이미 추적된 파일에 효력 없음)
#     미선언              → ⏳ 보류. ⚠️ 기본값이 축1과 **반대**다 — docs 의 안전측은 «추적» 이다
#       (유출 위험이 낮고 유실 위험이 높다. 실태도 추적 33 : ignore 10 으로 추적이 다수)
#
# 판정 (SSOT: _doc_arch/gitignore-policy.md "# `_doc_base/` 예외 — 명시 선언 규칙")
#   선언  : .claude/doc-base.yml 의 `tracking: allow|deny`
#   실태  : git ls-files _doc_base/ 가 1건 이상이면 tracked
#     allow + tracked   → OK
#     deny  + untracked → OK
#     deny  + tracked   → 🚨 위반(유출면) — 선언은 닫으라는데 열려 있다
#     allow + untracked → 🚨 위반(백업 0) — 열라고 선언했는데 .gitignore 가 막고 있다
#     미선언            → ⏳ 판정 보류 (위반 아님) — 아래 참조
#   `_doc_base/` 가 없거나 파일 0 인 repo 는 무관(skip) — "미사용 repo 는 무관" 조항
#
# 🔴 **미선언은 위반이 아니다** — 적용 기본값과 검사 기본값을 분리한다
#   신규 적용(pm-new/pm-update)에서 미선언은 `deny`(안전측)로 **동작**한다. 그러나 그것을
#   기존 repo **검사**에까지 적용하면, 구 규칙에서 정답이던 상태가 하룻밤에 위반으로 뒤집힌다:
#   origin 없는 repo 는 구 규칙상 "미ignore(추적)" 이 정답이었는데(prj3·videoMaker·CBT·
#   Karabiner 등 8건), 미선언=deny 로 읽으면 전부 🚨 가 된다. **정상 상태를 위반으로 읽는
#   게이트는 곧 무시된다** — Issue480 이 정확히 그 실패였다.
#   ⇒ 미선언은 제3 상태(⏳)로 세고 exit code 에 넣지 않는다. 선언이 채워질수록 ⏳ 가 줄고,
#      그 수 자체가 마이그레이션 진척 지표다. 나중에 조이려면 `--strict` 로 위반 취급한다.
#
# 사용: sh/doc-base-check.sh [--all] [--strict] [<repo>]
#         (기본)   현재 repo 판정
#         --all    ___pm 등록 프로젝트 전수 (읽기 전용 — 타 repo 를 수정하지 않는다)
#         --strict 미선언도 위반으로 (마이그레이션 완료 후 조일 때)
# exit: 0=정합, 1=위반
set -uo pipefail

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
PM_BASE="${FPM_BASE:-$(cd "$SELF_DIR/.." && pwd)}"
MODE="one"; TARGET=""; STRICT=0
while [ $# -gt 0 ]; do
  case "$1" in
    --all) MODE="all"; shift ;;
    --strict) STRICT=1; shift ;;
    -h|--help) echo "usage: sh/doc-base-check.sh [--all] [--strict] [<repo>]"; exit 0 ;;
    *) TARGET="$1"; shift ;;
  esac
done

viol=0; checked=0; undecl=0; dchecked=0; dundecl=0

# 선언 읽기 — yaml 파서 의존을 만들지 않는다(키 하나짜리 스칼라다).
#   주석·인라인 주석·따옴표를 벗기고 첫 매치만 쓴다.
decl_of() {  # $1=repo  → allow | deny | none
  local f="$1/.claude/doc-base.yml" v
  [ -f "$f" ] || { echo "none"; return 0; }
  v="$(sed -n 's/^[[:space:]]*tracking:[[:space:]]*\([A-Za-z]*\).*/\1/p' "$f" | head -1)"
  case "$v" in
    allow|deny) echo "$v" ;;
    *) echo "none" ;;   # 오타·빈 값은 선언으로 치지 않는다(조용한 오독보다 미선언이 낫다)
  esac
}

docs_decl_of() {  # $1=repo  → track | ignore | none   (Issue497)
  local f="$1/.claude/doc-base.yml" v
  [ -f "$f" ] || { echo "none"; return 0; }
  v="$(sed -n 's/^[[:space:]]*docs:[[:space:]]*\([A-Za-z]*\).*/\1/p' "$f" | head -1)"
  case "$v" in
    track|ignore) echo "$v" ;;
    *) echo "none" ;;
  esac
}

# docs 실태: 6항목 중 «존재하는» 것만 본다. 하나라도 추적 중이면 tracked 로 센다 —
#   부분 추적(ex: Issue.md 만 추적)은 «열려 있다» 쪽이 사실에 가깝다.
check_docs() {  # $1=repo  $2=라벨   (Issue497)
  local repo="$1" label="$2" decl tracked present item
  git -C "$repo" rev-parse --git-dir >/dev/null 2>&1 || return 0
  present=0; tracked=0
  for item in Issue.md CLAUDE.md noteForHuman.md _doc_arch _doc_work .claude; do
    [ -e "$repo/$item" ] || continue
    present=$((present + 1))
    [ "$(git -C "$repo" ls-files -- "$item" 2>/dev/null | head -1)" ] && tracked=$((tracked + 1))
  done
  [ "$present" -gt 0 ] || return 0
  decl="$(docs_decl_of "$repo")"
  dchecked=$((dchecked + 1))
  if [ "$decl" = "none" ]; then
    dundecl=$((dundecl + 1))
    printf '  ⏳ %-40s [docs] 미선언 · 추적 %s/%s — 미선언 기본값은 «추적»(Issue497)\n' "$label" "$tracked" "$present"
    [ "$STRICT" -eq 1 ] && viol=$((viol + 1))
  elif [ "$decl" = "track" ] && [ "$tracked" -gt 0 ]; then
    printf '  ✅ %-40s [docs] track  · 추적 %s/%s\n' "$label" "$tracked" "$present"
  elif [ "$decl" = "ignore" ] && [ "$tracked" -eq 0 ]; then
    printf '  ✅ %-40s [docs] ignore · 추적 0 (항목 %s)\n' "$label" "$present"
  elif [ "$decl" = "track" ]; then
    printf '  🚨 %-40s [docs] track 인데 추적 0 (항목 %s) — 버전이력·백업 0. 해소: .gitignore 의 docs 라인 제거 후 add\n' "$label" "$present"
    viol=$((viol + 1))
  else
    printf '  🚨 %-40s [docs] ignore 인데 %s 항목이 추적 중 — 선언과 실태 불일치. gitignore 는 추적분에 효력이 없다\n' "$label" "$tracked"
    viol=$((viol + 1))
  fi
}

check_one() {  # $1=repo  $2=라벨
  local repo="$1" label="$2" files tracked decl
  [ -d "$repo/_doc_base" ] || return 0
  files=$(find "$repo/_doc_base" -type f 2>/dev/null | wc -l | tr -d ' ')
  [ "${files:-0}" -gt 0 ] || return 0
  git -C "$repo" rev-parse --git-dir >/dev/null 2>&1 || return 0
  tracked=$(git -C "$repo" ls-files _doc_base/ 2>/dev/null | wc -l | tr -d ' ')
  decl="$(decl_of "$repo")"
  checked=$((checked + 1))
  if [ "$decl" = "none" ]; then
    undecl=$((undecl + 1))
    if [ "$tracked" -gt 0 ]; then
      printf '  ⏳ %-40s 미선언 · 현재 tracked %s/%s — .claude/doc-base.yml 에 tracking 을 적을 것\n' "$label" "$tracked" "$files"
    else
      printf '  ⏳ %-40s 미선언 · 현재 untracked (files %s) — 백업 경로 확인 후 tracking 을 적을 것\n' "$label" "$files"
    fi
    [ "$STRICT" -eq 1 ] && viol=$((viol + 1))
  elif [ "$decl" = "allow" ] && [ "$tracked" -gt 0 ]; then
    printf '  ✅ %-40s allow · tracked %s/%s\n' "$label" "$tracked" "$files"
  elif [ "$decl" = "deny" ] && [ "$tracked" -eq 0 ]; then
    printf '  ✅ %-40s deny  · untracked (files %s)\n' "$label" "$files"
  elif [ "$decl" = "deny" ]; then
    printf '  🚨 %-40s deny 인데 %s 파일이 추적 중 — 유출면. 해소: git rm -r --cached _doc_base/ + .gitignore 확인\n' "$label" "$tracked"
    viol=$((viol + 1))
  else
    printf '  🚨 %-40s allow 인데 추적 0 (files %s) — 백업 없음. 해소: .gitignore 의 _doc_base/ 라인 제거 후 add\n' "$label" "$files"
    viol=$((viol + 1))
  fi
}

if [ "$MODE" = "all" ]; then
  echo "[doc-base] 등록 프로젝트 전수 대조 (읽기 전용)"
  for n in $(ls "$PM_BASE/projects" 2>/dev/null | sort -n); do
    p="$(cat "$PM_BASE/projects/$n" 2>/dev/null)"; p="${p/#\~/$HOME}"
    [ -n "$p" ] && [ -d "$p" ] || continue
    check_one "$p" "$n ${p/#$HOME/~}"
    check_docs "$p" "$n ${p/#$HOME/~}"
  done
else
  repo="${TARGET:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
  echo "[doc-base] ${repo/#$HOME/~}"
  check_one "$repo" "${repo/#$HOME/~}"
  check_docs "$repo" "${repo/#$HOME/~}"
fi

if [ "$checked" -eq 0 ] && [ "$dchecked" -eq 0 ]; then
  echo "[doc-base] 대상 없음 (_doc_base·docs 미사용) — 무관"
  exit 0
fi
if [ "$viol" -gt 0 ]; then
  echo "[doc-base] 🚨 불일치 $viol 건 — base 검사 $checked (미선언 $undecl) · docs 검사 $dchecked (미선언 $dundecl)"
  exit 1
fi
if [ "$undecl" -gt 0 ] || [ "$dundecl" -gt 0 ]; then
  echo "[doc-base] ✅ 선언분 전부 정합 · ⏳ 미선언 base $undecl · docs $dundecl (위반 아님 — 마이그레이션 잔여)"
  exit 0
fi
echo "[doc-base] 정합 — base $checked 건 · docs $dchecked 건"
exit 0
