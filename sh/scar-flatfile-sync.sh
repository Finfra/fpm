#!/usr/bin/env bash
# scar-flatfile-sync.sh — flat_file 배포 사본을 prj3 원본에서 재생성 (Issue388)
#
# 배경: data/claude_forNewServer/ 는 prj3(~/.claude) 글로벌 SCAR 의 **사본**이다. 사본 방식은
#   원본이 움직여도 아무 신호를 내지 않아 조용히 늙는다. 2026-08-16 실측에서 29개 중
#   1개만 원본과 일치했고, 10개는 원본에 그 경로가 아예 없었다(이동 5·폐기 5).
#   그런데 sh/check.sh 항목11 은 **매니페스트 ↔ 사본**만 대조하므로, 둘이 같이 늙으면
#   서로 일치해서 PASS 가 났다 — 원본을 보는 눈이 어디에도 없었던 것이 근본 원인이다.
#
# 원칙:
#   1. 원본은 prj3(~/.claude), 사본은 repo 안 배포 스냅샷. **단방향(prj3 → prj1)만** 수행한다.
#      prj3 파일은 절대 쓰지 않는다 (읽기 전용).
#   2. 인벤토리 SSOT 는 data/scar-manifest.yml 의 payloads.flat_file.files[] 다.
#      사본에만 있고 선언에 없는 파일은 orphan 으로 보고 삭제한다(배포되면 안 되는 잔재).
#   3. **원본에 없는 선언은 fail-loud.** 조용히 건너뛰면 매니페스트가 틀린 채로 굳는다 —
#      그것이 바로 이 스크립트가 존재하는 이유다.
#   4. 경로는 원본의 실제 위치를 보존한다(평탄화 금지). 함께 배포되는 CLAUDE.md 의
#      상대 링크가 대상 서버에서 살아 있어야 한다.
#
# 사용:
#   sh/scar-flatfile-sync.sh           # 사본 재생성
#   sh/scar-flatfile-sync.sh --check   # 표류 검사만 (변경 없음, 표류 시 exit 1)
#
# 종료코드: 0=동기 완료 / 일치   1=표류 검출(--check) 또는 원본 부재(fail-loud)
#
# 관련: data/scar-manifest.yml(SSOT) · sh/check.sh 항목12 · data/scar-manifest.md

set -u

REPO="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
YML="$REPO/data/scar-manifest.yml"
CHECK=0
[ "${1:-}" = "--check" ] && CHECK=1

say() { printf '[scar-flatfile] %s\n' "$*"; }

[ -f "$YML" ] || { say "🚨 매니페스트 없음: $YML"; exit 1; }

# 매니페스트 직독 (yq 무의존 — gen-install-manifest.sh 와 동일한 python3 만 사용 원칙).
#   install_manifest.sh(파생물) 를 쓰지 않는 이유: 매니페스트를 고친 뒤 사본을 재생성하기
#   전에는 파생물 생성기가 "선언한 파일이 디스크에 없음" 으로 실패한다(닭-달걀).
eval "$(python3 - "$YML" <<'PY'
import sys, re
txt = open(sys.argv[1], encoding='utf-8').read()
ff  = txt.split('  flat_file:', 1)[1]
def scalar(key, default=''):
    m = re.search(r'^\s{4}%s:\s*"?([^"\n#]+?)"?\s*(?:#.*)?$' % key, ff, re.M)
    return m.group(1).strip() if m else default
# files: 블록은 첫 비-항목 줄에서 끊는다. 끊지 않으면 뒤따르는 protect[]·
# protect_exceptions[] 항목까지 인벤토리로 빨려 들어간다(형식이 같은 `      - ` 이므로).
body  = ff.split('    files:\n', 1)[1]
files = []
for l in body.splitlines():
    if l.startswith('      - '):
        files.append(l[8:].strip().strip('"'))
    elif l.strip() and not l.lstrip().startswith('#'):
        break
print('SRC_REL=%s' % scalar('src_rel_repo'))
print('ORIGIN_REL=%s' % scalar('origin_rel_home', '.claude'))
print('FILES=(%s)' % ' '.join('"%s"' % f for f in files))
PY
)"

DST="$REPO/$SRC_REL"
ORIGIN="$HOME/$ORIGIN_REL"

[ -d "$ORIGIN" ] || { say "🚨 원본 없음: $ORIGIN"; exit 1; }
[ "${#FILES[@]}" -gt 0 ] || { say "🚨 files[] 파싱 결과 0건 — 매니페스트 형식 확인"; exit 1; }

missing=0 drifted=0 copied=0 orphan=0

# ── 1. 선언 → 원본 대조 · 동기 ────────────────────────────────
for rel in "${FILES[@]}"; do
    src="$ORIGIN/$rel"
    dst="$DST/$rel"
    if [ ! -f "$src" ]; then
        say "❌ 원본 부재: $rel  (이동·폐기됨 — scar-manifest.yml files[] 갱신 필요)"
        missing=$((missing+1))
        continue
    fi
    if [ -f "$dst" ] && cmp -s "$src" "$dst"; then
        continue
    fi
    drifted=$((drifted+1))
    if [ "$CHECK" -eq 1 ]; then
        say "⚠️ 표류: $rel"
    else
        mkdir -p "$(dirname "$dst")"
        cp "$src" "$dst"
        copied=$((copied+1))
    fi
done

# ── 2. 사본 → 선언 대조 (orphan) ──────────────────────────────
#   선언에서 빠졌는데 사본에 남은 파일은 폐기된 SCAR 다. 그대로 두면 계속 배포된다.
declared=" ${FILES[*]} "
while IFS= read -r f; do
    rel="${f#"$DST/"}"
    case "$declared" in
        *" $rel "*) ;;
        *)
            orphan=$((orphan+1))
            if [ "$CHECK" -eq 1 ]; then
                say "⚠️ orphan(선언 없음): $rel"
            else
                rm -f "$f"
                say "🗑  orphan 제거: $rel"
            fi
            ;;
    esac
done < <(find "$DST" -type f 2>/dev/null | sort)

[ "$CHECK" -eq 1 ] || find "$DST" -type d -empty -delete 2>/dev/null || true

# ── 결과 ──────────────────────────────────────────────────────
if [ "$CHECK" -eq 1 ]; then
    if [ "$missing" -eq 0 ] && [ "$drifted" -eq 0 ] && [ "$orphan" -eq 0 ]; then
        say "✅ 일치 — 선언 ${#FILES[@]}개, 원본 대비 표류 없음"
        exit 0
    fi
    say "🚨 표류 검출 — 원본부재 $missing · 내용상이 $drifted · orphan $orphan"
    say "   해소: sh/scar-flatfile-sync.sh (재생성). 원본부재는 scar-manifest.yml files[] 를 먼저 고친다"
    exit 1
fi

say "동기 완료 — 선언 ${#FILES[@]}개 · 복사 $copied · orphan 제거 $orphan"
if [ "$missing" -gt 0 ]; then
    say "🚨 원본 부재 $missing 건 — scar-manifest.yml files[] 갱신 필요 (사본은 그 항목만 미갱신)"
    exit 1
fi
exit 0
