#!/usr/bin/env bash
# fpm-ship-verify.sh — 출고 1건 = 소비자 3대 배포 검증 1회 (Issue609)
#
# 왜 — 출고가 «미러 push» 로 끝나면 소비자 3대(jpc1 Windows·fg1 Linux·jma macOS)의 실제 동작은
#   출고 뒤 사람 눈으로 잡힌다(0.8.3 무결성 FAIL 3/3 · jpc1 hub «Loading…»). 런북 S6(설치·재기동)
#   다음에 이 명령으로 ③ check.sh 무결성 · ④ /healthz·/boards 200 · 설치 버전 = 출고 버전을
#   머신별로 판정하고 증거를 고정한다. ⑤ P1 은 scripts/fpm-post-release.sh · ⑥ 화면은 ego(런북 S7).
#
# 사용: bash scripts/fpm-ship-verify.sh --tag v0.8.3 [--host jma] [--host fg1] [--host jpc1:win] [--out <dir>]
#   --host 생략 시 기본 3대. `:win` = 원격 셸이 cmd 라 Git Bash 를 명시 호출한다
#   --port N          hub 포트(기본 9876)
#   --local-probe URL 원격 대신 URL 하나에 ④ 판정만 돌린다(fixture 검증용 — 구 hub 가 FAIL 로 잡히는지)
#   --propagate       검증 앞에 소비자 전파 표준 명령(scripts/fpm-consumer-propagate.sh — ①재설치·②hub 재기동)을 먼저 돌린다 (Issue613)
#   --judge-only      원격을 부르지 않고 <out>/evidence/state-<host>.log 와 <out>/post-<host>.log 로 판정만 다시 한다
#   --skip-p1 / --skip-shots   ⑤ P1 · ⑥ 캡처 판정을 명시 생략한다(표에 skip 으로 드러남 — 조용히 빠지지 않는다)
#   --fixtures        FAIL 경로(구 hub /boards 404·plugin 불일치·integrity FAIL·clone 불일치·P1 FAIL·캡처 없음)를 스스로 돌려
#                     전부 rc=1 임을 확인하고 <out>/evidence/fixture-<ver>.log 로 보존한다 (판정식이 PASS 하드코딩이 아님을 증명)
#   ⑤ P1 = <out>/post-<host>.log (scripts/fpm-post-release.sh 산출) — 비예외 FAIL 0 이어야 PASS. 예외는 jpc1(Windows)의 symlink-support 단독뿐
#   ⑥ 캡처 = <out>/evidence/shots/hub-<host>.png 실재(캡처 자체는 수동 허용 — 런북 S7)
#   증거: <out>/evidence/state-<host>.log + 요약 <out>/evidence/ship-verify_<ver>.md (기본 out = _doc_work/_release/v<ver>)
# exit: 0 전 머신 PASS · 1 하나라도 FAIL · 2 인자 오류
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
PAYLOAD="$HERE/fpm-ship-verify-payload.sh"
WIN_BASH='"C:\Program Files\Git\bin\bash.exe"'

TAG=""; OUT=""; PORT=9876; PROBE=""; HOSTS=(); JUDGE_ONLY=0; SKIP_P1=0; SKIP_SHOTS=0; PROPAGATE=0; FIXTURES=0
while [ $# -gt 0 ]; do
    case "$1" in
        --tag) TAG="${2:-}"; shift 2 ;;
        --host) HOSTS+=("${2:-}"); shift 2 ;;
        --out) OUT="${2:-}"; shift 2 ;;
        --port) PORT="${2:-}"; shift 2 ;;
        --local-probe) PROBE="${2:-}"; shift 2 ;;
        --judge-only) JUDGE_ONLY=1; shift ;;
        --skip-p1) SKIP_P1=1; shift ;;
        --skip-shots) SKIP_SHOTS=1; shift ;;
        --propagate) PROPAGATE=1; shift ;;
        --fixtures) FIXTURES=1; shift ;;
        -h|--help) sed -n '2,24p' "$0"; exit 0 ;;
        *) echo "❌ 알 수 없는 인자: $1" >&2; exit 2 ;;
    esac
done
[ -n "$TAG" ] || { echo "❌ --tag 필수 (ex) --tag v0.8.3)" >&2; exit 2; }
[ "$JUDGE_ONLY" = 1 ] || [ "$FIXTURES" = 1 ] || [ -f "$PAYLOAD" ] || { echo "❌ 페이로드 없음: $PAYLOAD" >&2; exit 2; }
VER="${TAG#v}"
OUT="${OUT:-$REPO/_doc_work/_release/v$VER}"
EV="$OUT/evidence"; mkdir -p "$EV"

# ── --fixtures: FAIL 경로를 스스로 돌린다 (Issue613 a) ─────────────────────────
#   합성 증거를 만들어 이 스크립트의 --judge-only 로 판정시킨다 — 판정식을 재구현하지 않고 **같은 코드 경로**를 탄다.
if [ "$FIXTURES" = 1 ]; then
    FX="$(mktemp -d "${TMPDIR:-/tmp}/ship-verify-fx.XXXXXX")"; trap 'rm -rf "$FX"' EXIT
    FLOG="$EV/fixture-$VER.log"; : > "$FLOG"; bad=0
    mkfx() {   # mkfx <name> <host> — 정상 증거 한 벌
        local d="$FX/$1" h="$2"; mkdir -p "$d/evidence/shots"
        printf 'FPMR host=%s os=Linux\nFPMR plugin=%s\nFPMR clone=abc1234 clone_version=%s\nFPMR integrity=PASS\nFPMR healthz=200 boards=200\nFPMR ssh_rc=0\n' "$h" "$VER" "$VER" > "$d/evidence/state-$h.log"
        printf 'FPMR host=%s\nFPMR tdd_rc=0\nFPMR sandbox_fail=0\nFPMR rc=0\n' "$h" > "$d/post-$h.log"
        echo png > "$d/evidence/shots/hub-$h.png"
    }
    fxrun() {  # fxrun <name> <기대 rc> <설명> — mkfx + 변이(stdin 함수명) 뒤 판정
        local name="$1" want="$2" desc="$3" mut="$4" d="$FX/$1" rc verdict
        mkfx "$name" fx; [ -n "$mut" ] && "$mut" "$d"
        bash "$0" --tag "$TAG" --judge-only --host fx --out "$d" >"$d/out.txt" 2>&1; rc=$?
        [ "$rc" = "$want" ] && verdict=OK || { verdict=BAD; bad=1; }
        echo "fixture $name — $desc: rc=$rc (기대 $want) $verdict" | tee -a "$FLOG"
    }
    m_old_hub()  { sed -i.bak 's/boards=200/boards=404/' "$1/evidence/state-fx.log"; }
    m_plugin()   { sed -i.bak 's/^FPMR plugin=.*/FPMR plugin=0.0.1/' "$1/evidence/state-fx.log"; }
    m_integrity(){ sed -i.bak 's/integrity=PASS/integrity=FAIL/' "$1/evidence/state-fx.log"; }
    m_clone()    { sed -i.bak 's/clone_version=[0-9.]*/clone_version=0.0.1/' "$1/evidence/state-fx.log"; }
    m_p1()       { printf 'FPMR tdd_rc=1\n  ❌ some-case   x\nFPMR sandbox_fail=0\nFPMR rc=1\n' > "$1/post-fx.log"; }
    m_shot()     { rm -f "$1/evidence/shots/hub-fx.png"; }
    echo "# fixture-$VER — $(date '+%Y-%m-%d %H:%M:%S') · scripts/fpm-ship-verify.sh --fixtures (Issue613)" | tee -a "$FLOG"
    fxrun control   0 "대조군(전부 정상)"            ""
    fxrun old-hub   1 "구 hub /boards 404"           m_old_hub
    fxrun plugin    1 "plugin 버전 불일치"           m_plugin
    fxrun integrity 1 "integrity FAIL"               m_integrity
    fxrun clone     1 "clone_version 불일치"         m_clone
    fxrun p1-fail   1 "P1 비예외 FAIL"               m_p1
    fxrun no-shot   1 "hub 홈 캡처 없음"             m_shot
    [ "$bad" = 0 ] && echo "✅ fixture 전부 기대대로 — FAIL 경로 6종 rc=1 · 대조군 rc=0" | tee -a "$FLOG" || echo "❌ 기대와 다른 fixture 가 있다 — 판정식 결함" | tee -a "$FLOG"
    exit "$bad"
fi

kv() { awk -v k="$2" '$1=="FPMR"{for(i=2;i<=NF;i++) if(index($i,k"=")==1){print substr($i,length(k)+2); exit}}' "$1" 2>/dev/null; }

probe_local() {   # ④ 만 — fixture 용. 원격 페이로드와 같은 판정식
    local base="$1" log="$EV/state-local.log" h b
    h=$(curl -s -o /dev/null -m 8 -w '%{http_code}' "$base/healthz" 2>/dev/null || echo 000)
    b=$(curl -s -o /dev/null -m 8 -w '%{http_code}' "$base/boards" 2>/dev/null || echo 000)
    { echo "FPMR host=local-probe os=$(uname -s)"; echo "FPMR plugin=$VER clone_version=$VER"; echo "FPMR integrity=PASS"; echo "FPMR healthz=$h boards=$b"; } > "$log"
}

run_host() {   # $1 = host[:win]
    local spec="$1" h="${1%%:*}" log="$EV/state-${1%%:*}.log" rc
    if [ "$spec" != "$h" ] && [ "${spec#*:}" = "win" ]; then
        ssh "$h" "$WIN_BASH -l -s -- $PORT" < "$PAYLOAD" 2>&1 | grep -v -E "post-quantum|store now|upgraded|fpm.sh: No such" > "$log"
        rc=${PIPESTATUS[0]}
    else
        ssh -x "$h" "export PATH=\$HOME/.local/bin:/opt/homebrew/bin:\$PATH; bash -s -- $PORT" < "$PAYLOAD" 2>&1 | grep -v -E "post-quantum|store now|upgraded" > "$log"
        rc=${PIPESTATUS[0]}
    fi
    echo "FPMR ssh_rc=$rc" >> "$log"
}

prop_fail=0
if [ -n "$PROBE" ]; then
    probe_local "$PROBE"; HOSTS=(local); SKIP_P1=1; SKIP_SHOTS=1   # fixture 전용 — ④ 만 본다
else
    [ ${#HOSTS[@]} -gt 0 ] || HOSTS=(jma fg1 jpc1:win)
    if [ "$JUDGE_ONLY" = 1 ]; then
        echo "▶ ship-verify (judge-only) — $TAG · 머신 ${HOSTS[*]} · 증거 $EV"
    else
        if [ "$PROPAGATE" = 1 ]; then   # Issue613 c — ①재설치·②hub 재기동을 표준 명령 호출로 결합
            echo "▶ 전파(표준 명령) — fpm-consumer-propagate.sh"
            ph=(); for s in "${HOSTS[@]}"; do ph+=(--host "$s"); done
            bash "$HERE/fpm-consumer-propagate.sh" --tag "$TAG" --out "$OUT" --port "$PORT" "${ph[@]}" || prop_fail=1
        fi
        echo "▶ ship-verify — $TAG · 머신 ${HOSTS[*]} · 증거 $EV"
        for s in "${HOSTS[@]}"; do run_host "$s" & done
        wait
    fi
fi

# ⑤ P1 판정 — <out>/post-<host>.log. 출력: P1_V(PASS|FAIL|skip) P1_N(비예외 FAIL 수 또는 사유)
#   예외는 Windows(jpc1·MINGW)의 symlink-support 단독뿐 — Issue609 명세. 같은 항목이 다른 머신에서 나면 예외가 아니다.
p1_judge() {   # $1 host  $2 os
    local h="$1" os="$2" log="$OUT/post-$1.log" n=0 ex=0 name tdd sf
    P1_V=PASS; P1_N=0
    if [ "$SKIP_P1" = 1 ]; then P1_V=skip; P1_N=-; return; fi
    [ -f "$log" ] || { P1_V=FAIL; P1_N="로그없음"; return; }
    while IFS= read -r name; do
        if [ "$name" = "symlink-support" ] && { [ "$h" = jpc1 ] || [[ "$os" == MINGW* ]] || [[ "$os" == MSYS* ]]; }; then ex=$((ex + 1)); else n=$((n + 1)); fi
    done < <(sed 's/\x1b\[[0-9;]*m//g' "$log" | awk '/^  ❌ /{print $2}')
    tdd=$(kv "$log" tdd_rc); sf=$(kv "$log" sandbox_fail)
    [ -n "$tdd" ] || n=$((n + 1))                                  # TDD 가 끝까지 안 돈 로그
    if [ -n "$sf" ]; then n=$((n + sf)); else n=$((n + 1)); fi    # 샌드박스 단계 미도달
    grep -q "FPMR clone=fail" "$log" && n=$((n + 1))
    if [ -n "$tdd" ] && [ "$tdd" != 0 ] && [ "$n" = 0 ] && [ "$ex" = 0 ]; then n=1; fi   # 실패인데 항목명을 못 찾음
    P1_N="$n"; [ "$ex" -gt 0 ] && [ "$n" = 0 ] && P1_N="0(예외 $ex)"
    [ "$n" = 0 ] || P1_V=FAIL
}

fail=0
SUM="$EV/ship-verify_$VER.md"
{
    echo "---"
    echo "name: ship-verify_$VER"
    echo "description: \"출고 $TAG 소비자 3대 실기동 검증 — 설치 버전·무결성·healthz·boards (scripts/fpm-ship-verify.sh, Issue609)\""
    echo "date: $(date +%Y.%m.%d)"
    echo "---"
    echo
    echo "| 머신 | OS | plugin | clone | 무결성 | healthz | boards | P1(FAIL) | 캡처 | 판정 |"
    echo "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |"
    for s in "${HOSTS[@]}"; do
        h="${s%%:*}"; log="$EV/state-$h.log"
        pl=$(kv "$log" plugin); cv=$(kv "$log" clone_version); ig=$(kv "$log" integrity)
        hz=$(kv "$log" healthz); bd=$(kv "$log" boards); os=$(kv "$log" os)
        v=PASS
        [ "$pl" = "$VER" ] || v=FAIL
        [ "$cv" = "$VER" ] || v=FAIL    # Issue613: clone 이 출고 버전이 아니면 hub 는 구 코드를 서빙한다
        [ "$ig" = PASS ] || v=FAIL
        [ "$hz" = 200 ] && [ "$bd" = 200 ] || v=FAIL
        p1_judge "$h" "$os"; [ "$P1_V" = FAIL ] && v=FAIL
        if [ "$SKIP_SHOTS" = 1 ]; then sh_v=skip
        elif [ -s "$EV/shots/hub-$h.png" ]; then sh_v=있음
        else sh_v=없음; v=FAIL; fi
        [ "$v" = PASS ] || fail=1
        echo "| $h | ${os:-?} | ${pl:-?} | ${cv:-?} | ${ig:-?} | ${hz:-?} | ${bd:-?} | $P1_V($P1_N) | $sh_v | $v |"
    done
    echo
    [ "$prop_fail" = 0 ] || echo "* ⚠️ 소비자 전파(--propagate) 실패 머신이 있다 — evidence/propagate-<host>.log"
    [ "$fail" = 0 ] && echo "**전 머신 PASS**" || echo "**FAIL 있음 — 출고를 «완료» 로 닫지 않는다 (Issue609)**"
} > "$SUM"
cat "$SUM"
[ "$prop_fail" = 0 ] || fail=1
exit "$fail"
