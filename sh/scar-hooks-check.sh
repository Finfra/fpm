#!/usr/bin/env bash
# scar-hooks-check.sh — 번들 hooks/ 사본의 표류 검사 (Issue412)
#
# 배경: Issue388 이 `flat_file` 에서 없앤 *"사본이 원본과 갈라져도 아무 신호가 없다"* 가
#   `plugin.hooks` 에는 남아 있었다. 배포 체인의 가장 상류라 여기서 누락되면 그 아래
#   순방향 전체가 낡은 것을 실어 나른다.
#
# ⚠️ **동기는 하지 않는다 — 검사 전용이다.** 왜 sync 모드를 두지 않는가:
#   번들 hooks 의 **쓰기 주체는 이미 scripts/fpm-bundle-sync.sh 하나**다
#   (`sync_dir_by_name "$BUNDLE/hooks" "$GLOBAL/hooks"`). 여기에 두 번째 writer 를 만들면
#   같은 대상에 판정 축이 둘 생기고, 그것이 Issue414 에서 교착을 만든 바로 그 구조다.
#   각 결손의 조치는 아래 메시지가 지목한다.
#
# 무엇을 보는가 — 기존 검사가 못 보는 세 구멍만 (bundle-sync 와 중복 없음):
#   A. 선언 → 디스크 : 선언했는데 번들에 파일이 없음.
#      ★ 이것이 핵심 구멍이다. bundle-sync 는 **번들 디렉토리를 순회**하므로 번들에서
#        파일이 사라지면 순회 대상 자체가 아니게 되어 "표류 없음" 을 낸다(2026-08-29 실측).
#        hooks.json 이 그 훅을 참조해도 배포본엔 파일이 없어 소비자 런타임에서 깨진다.
#   B. 디스크 → 선언 : 번들에 있는데 미선언(인벤토리 SSOT 결손).
#   C. 사본 ↔ 원본   : prj3 원본과 내용 상이 / 원본 부재.
#      내용 상이는 bundle-sync --check 도 잡지만, **원본 부재**는 못 잡는다
#      (`sync_file` 이 `[ -f "$src" ]` 로 조기 반환 = "번들 전용으로 간주"). 그래서
#      prj1 고유 자산과 폐기된 훅의 잔재(orphan)가 구분되지 않았다 — 그 판정 근거를
#      매니페스트의 hooks_bundle_only[] 로 명시화하고 여기서 대조한다.
#
# 정본 판정(Issue412 ①): **원본은 prj3(~/.claude/hooks), 번들은 사본.** 근거는
#   data/scar-manifest.yml 의 `hooks_origin_rel_home` 주석 참조. prj3 는 읽기 전용.
#
# 사용: sh/scar-hooks-check.sh [--quiet]
# 종료코드: 0=일치 / 1=표류 검출·매니페스트 오류
#
# 관련: data/scar-manifest.yml(SSOT) · sh/check.sh 항목 12-2 · scripts/fpm-bundle-sync.sh

set -u

REPO="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
YML="$REPO/data/scar-manifest.yml"
QUIET=0
[ "${1:-}" = "--quiet" ] && QUIET=1

say() { [ "$QUIET" -eq 1 ] || printf '[scar-hooks] %s\n' "$*"; }
err() { printf '[scar-hooks] %s\n' "$*"; }

[ -f "$YML" ] || { err "🚨 매니페스트 없음: $YML"; exit 1; }

# 매니페스트 직독 — scar-flatfile-sync.sh 와 같은 방식(yq 무의존, python3 만).
#   파생물 data/install_manifest.sh 를 쓰지 않는 이유도 같다: 매니페스트를 고친 직후
#   생성기가 아직 실패하는 구간이 있어 닭-달걀이 된다.
eval "$(python3 - "$YML" <<'PY'
import sys, re
txt = open(sys.argv[1], encoding='utf-8').read()
plg = txt.split('  plugin:', 1)[1].split('\n  flat_file:', 1)[0]

def seq(block, key, indent):
    """`{indent}{key}:` 아래의 `- ` 항목을 모은다. 주석·빈 줄은 건너뛰고,
       들여쓰기가 얕아지는 첫 줄에서 끊는다(다음 키로 새는 것 방지)."""
    m = re.search(r'^%s%s:\s*$' % (' ' * indent, key), block, re.M)
    if not m:
        return []
    out = []
    for line in block[m.end():].splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        stripped = line.lstrip()
        if stripped.startswith('- ') and (len(line) - len(stripped)) > indent:
            out.append(stripped[2:].split('#', 1)[0].strip().strip('"'))
        else:
            break
    return out

def scalar(key, indent):
    m = re.search(r'^%s%s:\s*"?([^"\n#]+?)"?\s*(?:#.*)?$' % (' ' * indent, key), plg, re.M)
    return m.group(1).strip() if m else ''

print('SRC_REL=%s'    % scalar('src_rel_repo', 4))
print('ORIGIN_REL=%s' % (scalar('hooks_origin_rel_home', 4) or '.claude/hooks'))
print('HOOKS=(%s)'      % ' '.join('"%s"' % h for h in seq(plg, 'hooks', 6)))
print('BUNDLE_ONLY=(%s)' % ' '.join('"%s"' % h for h in seq(plg, 'hooks_bundle_only', 4)))
PY
)"

BUNDLE="$REPO/$SRC_REL/hooks"
ORIGIN="$HOME/$ORIGIN_REL"

[ "${#HOOKS[@]}" -gt 0 ] || { err "🚨 hooks[] 파싱 결과 0건 — scar-manifest.yml 형식 확인"; exit 1; }
[ -d "$BUNDLE" ] || { err "🚨 번들 hooks 없음: $BUNDLE"; exit 1; }

missing=0 undecl=0 drifted=0 orphan=0

declared=" ${HOOKS[*]} "
bundle_only=" ${BUNDLE_ONLY[*]} "

# ── A. 선언 → 디스크 (번들에서 사라진 훅) ─────────────────────
for rel in "${HOOKS[@]}"; do
    [ -f "$BUNDLE/$rel" ] && continue
    err "❌ 선언했으나 번들에 없음: $rel"
    missing=$((missing+1))
done

# ── B. 디스크 → 선언 (미선언 훅) ──────────────────────────────
#   __pycache__ 는 실행 산출물이라 인벤토리 대상이 아니다.
while IFS= read -r rel; do
    case "$declared" in
        *" $rel "*) ;;
        *) err "❌ 번들에 있으나 yml 미선언: $rel"; undecl=$((undecl+1)) ;;
    esac
done < <(cd "$BUNDLE" && find . -type f -not -path './__pycache__/*' | sed 's|^\./||' | sort)

# ── C. 사본 ↔ prj3 원본 ───────────────────────────────────────
if [ ! -d "$ORIGIN" ]; then
    say "⚠️ prj3 원본 없음: $ORIGIN — 사본↔원본 대조 생략 (이 머신은 SCAR 원본 미보유)"
else
    for rel in "${HOOKS[@]}"; do
        [ -f "$BUNDLE/$rel" ] || continue          # A 가 이미 보고함
        case "$bundle_only" in
            *" $rel "*) continue ;;                # 번들 전용 — 원본이 없는 것이 정상
        esac
        if [ ! -f "$ORIGIN/$rel" ]; then
            err "❌ prj3 원본 부재: $rel  (폐기된 훅의 잔재인가, 번들 전용 자산인가?"
            err "     → 번들 전용이면 scar-manifest.yml hooks_bundle_only[] 에 추가,"
            err "       폐기분이면 번들 파일과 hooks[] 선언을 함께 제거)"
            orphan=$((orphan+1))
        elif ! cmp -s "$ORIGIN/$rel" "$BUNDLE/$rel"; then
            err "⚠️ 원본과 내용 상이: $rel"
            drifted=$((drifted+1))
        fi
    done
fi

# ── 결과 ──────────────────────────────────────────────────────
if [ "$missing" -eq 0 ] && [ "$undecl" -eq 0 ] && [ "$drifted" -eq 0 ] && [ "$orphan" -eq 0 ]; then
    say "✅ 일치 — 선언 ${#HOOKS[@]}개(번들 전용 ${#BUNDLE_ONLY[@]}개 제외 대조), 표류 없음"
    exit 0
fi
err "🚨 표류 검출 — 번들부재 $missing · 미선언 $undecl · 내용상이 $drifted · 원본부재 $orphan"
[ "$missing" -gt 0 ] && err "   번들부재 해소: cp ~/$ORIGIN_REL/<파일> $SRC_REL/hooks/  (신규 편입은 의도적 수동)"
[ "$undecl"  -gt 0 ] && err "   미선언 해소  : scar-manifest.yml payloads.plugin.scar.hooks[] 에 추가"
[ "$drifted" -gt 0 ] && err "   내용상이 해소: scripts/fpm-bundle-sync.sh  (번들 hooks 의 유일한 writer)"
exit 1
