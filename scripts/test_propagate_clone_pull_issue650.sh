#!/usr/bin/env bash
# test_propagate_clone_pull_issue650.sh — 전파 페이로드 ① clone 갱신이 detached clone 에서도 되는지 + 헤드를 보고하는지 (Issue650)
#   zero-base 재구성은 태그를 detached 로 clone 한다. `git pull --ff-only` 는 추적 브랜치가 없어 실패하고,
#   같은 버전 번호로 재출고하면 clone_version 이 그대로라 갱신 실패가 성공처럼 보였다(2026-10-18 jma·fg1·jpc1 실측).
#   ① detached clone(구 커밋) → 전파 ① 블록 → clone_pull=ok · 헤드가 최신 커밋
#   ② 작업트리가 더러워 pull 이 막히면 clone_pull=FAIL 로 정직하게 알린다 (거짓 ok 금지)
#   ③ 어느 쪽이든 FPMR clone_head=<짧은 해시> 줄이 나온다 — 같은 버전에서도 갱신 여부가 보인다
# 대상 블록은 실물 페이로드에서 추출한다(재구현 금지).
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PAY="${1:-$HERE/fpm-consumer-propagate-payload.sh}"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
G() { git -C "$1" -c user.name=t -c user.email=t@t "${@:2}"; }
git init -q --bare -b main "$T/origin.git"
git clone -q "$T/origin.git" "$T/seed" 2>/dev/null
echo v1 > "$T/seed/f"; echo 0.8.3 > "$T/seed/VERSION"; G "$T/seed" add -A; G "$T/seed" commit -qm c1; G "$T/seed" tag v0.8.3; G "$T/seed" push -q origin main --tags
git clone -q --branch v0.8.3 "$T/origin.git" "$T/clone" 2>/dev/null     # detached
echo v2 > "$T/seed/f"; G "$T/seed" commit -qam c2; G "$T/seed" push -q origin main
NEW="$(G "$T/seed" rev-parse --short HEAD)"

# ① 블록 = «# ① clone» 주석부터 «# ② plugin 재설치» 직전까지
BLOCK="$(awk '/^# ① clone/{p=1} /^    # ② plugin/{exit} p{print}' "$PAY")"
[ -n "$BLOCK" ] || { echo "FAIL: 페이로드에서 ① clone 블록을 못 찾음"; exit 1; }
run() { FPM_DIR="$1" FPM_PROP_NO_INSTALL=0 bash -c "$BLOCK" 2>&1; }
# NO_INSTALL 분기 안이라 if 블록이 닫히도록 fi 보강
BLOCK="$BLOCK
fi"
fail=0
out="$(FPM_DIR="$T/clone" bash -c "$BLOCK")"
echo "$out" | grep -q 'clone_pull=ok' || { echo "FAIL: ① detached clone 갱신이 ok 아님: $out"; fail=1; }
head="$(G "$T/clone" rev-parse --short HEAD)"
[ "$head" = "$NEW" ] || { echo "FAIL: ① 헤드가 최신이 아님 (head=$head want=$NEW)"; fail=1; }
echo "$out" | grep -q "clone_head=$NEW" || { echo "FAIL: ③ clone_head 줄 없음/불일치: $out"; fail=1; }

# ② 더러운 작업트리
G "$T/seed" tag -f v0.8.3 >/dev/null 2>&1
git clone -q --branch v0.8.3 "$T/origin.git" "$T/clone2" 2>/dev/null
echo v3 > "$T/seed/f"; G "$T/seed" commit -qam c3; G "$T/seed" push -q origin main
echo dirty > "$T/clone2/f"
out2="$(FPM_DIR="$T/clone2" bash -c "$BLOCK")"
echo "$out2" | grep -q 'clone_pull=FAIL' || { echo "FAIL: ② 더러운 트리인데 FAIL 보고 아님: $out2"; fail=1; }
echo "$out2" | grep -q 'clone_head=' || { echo "FAIL: ③ 실패 때도 clone_head 줄이 있어야 함: $out2"; fail=1; }
# ④ 드라이버가 FPMR 줄의 =FAIL 을 ✅ 로 묻지 않는다 (정적)
DRV="$HERE/fpm-consumer-propagate.sh"
grep -q "grep -q -E '=FAIL'" "$DRV" || { echo "FAIL: ④ 드라이버가 =FAIL 줄을 실패로 세지 않음"; fail=1; }
[ "$fail" = 0 ] && echo "PASS: 전파 clone 갱신(detached)·헤드 보고"
exit "$fail"
