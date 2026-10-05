#!/bin/bash
# test_run_remote.sh — Issue543 M3 회귀 테스트 (tdd playlist #43 release-run-remote)
#
# 출고 재생목록 4·5행(native-*)의 실행 수단 tdd/run-remote.sh 가 «머신 불가» 를 PASS 로
#   흘리지 않고, 원격을 더럽히지 않으며, 후보 트리만(이력 없이) 보내는지 검증한다.
#   ① 정상 → rc 0 · result=pass · 원격 임시 디렉토리 잔존 0 · 로그 회수
#   ② ssh 무응답 + 기동 명령 없음 → rc 3 partial (PASS 로 새지 않음)
#   ③ ssh 무응답 + 기동 명령 실패 → rc 3 partial
#   ④ ssh 무응답 → 기동 명령 → 응답 → rc 0 (기동 경로)
#   ⑤ 원격 실행 중 연결 끊김 → rc 3 partial + 원격 정리 수행
#   ⑥ 원격 테스트 실패 → rc 1 · 원격 정리 ⑦ 샌드박스 install 실패 → rc 1
#   ⑧ 입력 오류(--machine 없음·명부에 없는 id) → rc 2 ⑨ planned 머신 → rc 3
#   ⑩ 원격 clone 은 이력 1커밋·트리 = 후보 트리 ⑪ 로컬 설정의 ssh 대상 사용 + 출력에 대상 이름 없음
#   ⑫ --candidate 로 과거 커밋을 고르면 그 트리를 보낸다
#   ⑬ 원격 실행은 FPM_TDD_NATIVE_REMOTE=1 을 내보낸다 ⑭ 케이스 bundle-in-sync 는 그 표식에서 skip
#      (원격 머신의 ~/.claude 는 저작 라이브 소스가 아니다 — jma 는 9/1 부분 사본이라 DRIFT 로 FAIL 했다)
#
# 격리: 가짜 ssh·scp(원격 = 로컬 임시 디렉토리) + 스텁 스크립트를 담은 fixture repo.
#   실 ssh·실 머신 무접촉. 실행: bash scripts/test_run_remote.sh   (수 초)
set -u

# R1 하네스(sh/release-candidate-run.sh)가 FPM_RELEASE_CANDIDATE=<본 저장소 SHA> 를 주입한다 — run-remote.sh 가
#   그 값을 후보로 읽어 fixture repo 에 없는 SHA 를 해석하다 rc 2 로 20건이 죽었다(Issue598). 케이스는 상속 문맥 없이 돈다.
unset FPM_RELEASE_CANDIDATE FPM_RELEASE_MAIN_REPO FPM_RELEASE_GATE_STATE FPM_RELEASE_EVIDENCE_DIR

REPO="$(cd "$(dirname "$0")/.." && pwd)"
S="$REPO/tdd/run-remote.sh"
SB="$(mktemp -d "${TMPDIR:-/tmp}/run-remote-test.XXXXXX")"
trap 'rm -rf "$SB"' EXIT
PASS=0; FAIL=0
ok()   { PASS=$((PASS + 1)); echo "  ok   $1"; }
fail() { FAIL=$((FAIL + 1)); echo "  FAIL $1"; }
check() { if [ "$2" = "$3" ]; then ok "$1"; else fail "$1 (want='$3' got='$2')"; fi; }
has()   { case "$2" in *"$3"*) ok "$1" ;; *) fail "$1 (출력에 '$3' 없음)"; printf '%s\n' "$2" | tail -6 | sed 's/^/       /' ;; esac; }
hasnt() { case "$2" in *"$3"*) fail "$1 (출력에 '$3' 있음)" ;; *) ok "$1" ;; esac; }

echo "[test_run_remote]"
[ -f "$S" ] || { fail "대상 존재: tdd/run-remote.sh"; echo "── PASS $PASS / FAIL $FAIL"; exit 1; }
ok "대상 존재: tdd/run-remote.sh"

# ── fixture repo: 명부 + 스텁(run-tdd·install·check·uninstall) ──
FX="$SB/fx"; mkdir -p "$FX/tdd" "$FX/sh"
cat >"$FX/tdd/machines.yml" <<'EOF'
machines:
  - id: laptop
    platform: macos
    status: active
  - id: gpu-server
    platform: linux
    status: active
  - id: win11
    platform: windows
    status: planned
EOF
# 스텁은 repo 안 표식 파일로 실패를 흉내 낸다 — 원격(=clone) 쪽에서 읽혀야 하므로 커밋 대상이다
cat >"$FX/tdd/run-tdd.sh" <<'EOF'
#!/bin/bash
echo "stub run-tdd native=${FPM_TDD_NATIVE_REMOTE:-}"; [ -f "$(dirname "$0")/.fail" ] && { echo "FAIL stub-case"; exit 1; }; exit 0
EOF
cat >"$FX/sh/install.sh" <<'EOF'
#!/bin/bash
[ -f "$(dirname "$0")/.fail-install" ] && exit 1; echo "# fpm" >> "$HOME/.zshrc"
EOF
printf '#!/bin/bash\ngrep -q "# fpm" "$HOME/.zshrc"\n' >"$FX/sh/check.sh"
printf '#!/bin/bash\n: > "$HOME/.zshrc"\n' >"$FX/sh/uninstall.sh"
chmod +x "$FX"/tdd/*.sh "$FX"/sh/*.sh
printf 'results/\n' >"$FX/tdd/.gitignore"
g() { git -C "$FX" -c core.hooksPath=/dev/null -c user.name=t -c user.email=t@t -c commit.gpgsign=false "$@"; }
g init -q && g add -A && g commit -qm base
OLD_SHA="$(g rev-parse HEAD)"; OLD_TREE="$(g rev-parse HEAD^{tree})"
echo "v2" >"$FX/tdd/v2.txt"; g add -A && g commit -qm v2
HEAD_TREE="$(g rev-parse HEAD^{tree})"

# ── 가짜 ssh·scp: 옵션을 건너뛰고 원격 명령을 로컬에서 돌린다 ──
BIN="$SB/bin"; mkdir -p "$BIN"
cat >"$BIN/ssh" <<'EOF'
#!/bin/bash
while [ $# -gt 0 ]; do case "$1" in -o) shift 2 ;; -*) shift ;; *) break ;; esac; done
target="$1"; shift; cmd="$*"
echo "ssh $target :: $cmd" >>"$FAKE_LOG"
case "${FAKE_SSH_MODE:-up}" in
  down) exit 255 ;;
  wake) [ -f "$FAKE_WAKE_FLAG" ] || exit 255 ;;
  drop) case "$cmd" in *"bash -s"*) exit 255 ;; esac ;;
esac
[ -n "$cmd" ] || exit 0
exec bash -c "$cmd"
EOF
cat >"$BIN/scp" <<'EOF'
#!/bin/bash
while [ $# -gt 0 ]; do case "$1" in -o) shift 2 ;; -*) shift ;; *) break ;; esac; done
echo "scp $*" >>"$FAKE_LOG"
[ "${FAKE_SSH_MODE:-up}" = down ] && exit 1
src="${1#*:}"; dst="${2#*:}"
bash -c "cp $src \"$dst\""
EOF
chmod +x "$BIN/ssh" "$BIN/scp"

RT="$SB/remote-tmp"; mkdir -p "$RT"
CONF="$SB/remote.local.sh"
printf 'FPM_TDD_SSH_laptop=secret-host-xyz\n' >"$CONF"
run() {  # 인자 = run-remote.sh 인자. 결과: OUT·RC
    : >"$SB/fake.log"
    OUT="$(env TMPDIR="$RT" FAKE_LOG="$SB/fake.log" FAKE_WAKE_FLAG="$SB/woke" \
        FPM_TDD_SSH_BIN="$BIN/ssh" FPM_TDD_SCP_BIN="$BIN/scp" \
        FPM_TDD_REMOTE_CONF="$CONF" FPM_TDD_RESULTS_DIR="$SB/results" \
        FPM_TDD_WAKE_POLL=1 FPM_TDD_WAKE_TIMEOUT=4 \
        bash "$S" --repo "$FX" "$@" 2>&1)"; RC=$?
}
leftover() { ls -d "$RT"/fpm-remote.* 2>/dev/null | wc -l | tr -d ' '; }

# ① 정상
FAKE_SSH_MODE=up run --machine laptop
check "① 정상 → rc 0" "$RC" "0"
has "① result=pass" "$OUT" "result=pass"
check "① 원격 임시 디렉토리 잔존 0" "$(leftover)" "0"
check "① 로그 회수(tdd.log)" "$(ls "$SB"/results/*/tdd.log 2>/dev/null | wc -l | tr -d ' ')" "1"
# ⑬ 원격 실행 표식
grep -q "native=1" "$SB"/results/*/tdd.log 2>/dev/null && ok "⑬ 원격 실행이 FPM_TDD_NATIVE_REMOTE=1 을 내보냄" || fail "⑬ FPM_TDD_NATIVE_REMOTE 미전달"
# ⑩ 이력 없음 · 트리 일치
has "⑩ 원격 이력 1커밋" "$OUT" "history=1"
has "⑩ 원격 트리 = 후보 트리" "$OUT" "tree=ok"
# ⑪ 로컬 설정 대상 · 출력 비노출
case "$(cat "$SB/fake.log")" in *"ssh secret-host-xyz"*) ok "⑪ 로컬 설정의 ssh 대상 사용" ;; *) fail "⑪ 로컬 설정의 ssh 대상 사용" ;; esac
hasnt "⑪ 출력에 ssh 대상 이름 없음" "$OUT" "secret-host-xyz"

# ② 무응답 · 기동 명령 없음
FAKE_SSH_MODE=down run --machine laptop
check "② 무응답·기동 없음 → rc 3" "$RC" "3"
has "② result=partial" "$OUT" "result=partial"
hasnt "② PASS 로 새지 않음" "$OUT" "result=pass"

# ③ 기동 명령 실패
printf 'FPM_TDD_SSH_laptop=secret-host-xyz\nFPM_TDD_WAKE_laptop="false"\n' >"$CONF"
FAKE_SSH_MODE=down run --machine laptop
check "③ 기동 명령 실패 → rc 3" "$RC" "3"
has "③ result=partial" "$OUT" "result=partial"

# ④ 기동 → 응답
rm -f "$SB/woke"
printf 'FPM_TDD_SSH_laptop=secret-host-xyz\nFPM_TDD_WAKE_laptop="touch %s"\n' "$SB/woke" >"$CONF"
FAKE_SSH_MODE=wake run --machine laptop
check "④ 기동 후 응답 → rc 0" "$RC" "0"
printf 'FPM_TDD_SSH_laptop=secret-host-xyz\n' >"$CONF"

# ⑤ 중도 끊김
FAKE_SSH_MODE=drop run --machine laptop
check "⑤ 원격 실행 중 끊김 → rc 3" "$RC" "3"
has "⑤ result=partial" "$OUT" "result=partial"
check "⑤ 원격 정리 수행(잔존 0)" "$(leftover)" "0"

# ⑥ 원격 테스트 실패
touch "$FX/tdd/.fail"; g add -A && g commit -qm fail-tdd
FAKE_SSH_MODE=up run --machine laptop
check "⑥ 원격 테스트 실패 → rc 1" "$RC" "1"
has "⑥ result=fail" "$OUT" "result=fail"
check "⑥ 원격 정리(잔존 0)" "$(leftover)" "0"
g rm -q tdd/.fail && g commit -qm unfail

# ⑦ 샌드박스 install 실패
touch "$FX/sh/.fail-install"; g add -A && g commit -qm fail-install
FAKE_SSH_MODE=up run --machine laptop
check "⑦ 샌드박스 install 실패 → rc 1" "$RC" "1"
has "⑦ sandbox_fail 보고" "$OUT" "sandbox_fail="
g rm -q sh/.fail-install && g commit -qm unfail2

# ⑧ 입력 오류
FAKE_SSH_MODE=up run
check "⑧ --machine 없음 → rc 2" "$RC" "2"
FAKE_SSH_MODE=up run --machine nosuch
check "⑧ 명부에 없는 id → rc 2" "$RC" "2"

# ⑨ planned
FAKE_SSH_MODE=up run --machine win11
check "⑨ planned 머신 → rc 3" "$RC" "3"
has "⑨ 사유에 status=planned" "$OUT" "planned"

# ⑫ --candidate 과거 커밋
FAKE_SSH_MODE=up run --machine gpu-server --candidate "$OLD_SHA"
check "⑫ --candidate 과거 커밋 → rc 0" "$RC" "0"
has "⑫ 후보 식별자 = 과거 커밋" "$OUT" "candidate=${OLD_SHA:0:7}"
has "⑫ 과거 트리 전송(tree=ok)" "$OUT" "tree=ok"
[ "$OLD_TREE" != "$HEAD_TREE" ] && ok "⑫ fixture 전제: 과거·HEAD 트리 상이" || fail "⑫ fixture 전제"

# ⑭ 케이스 bundle-in-sync — 원격 표식에서 skip (실 repo 의 케이스를 그대로 돌린다)
run="$(python3 -c '
import sys, yaml
for c in yaml.safe_load(open(sys.argv[1]))["cases"]:
    if c["id"] == "bundle-in-sync": print(c["run"])' "$REPO/tdd/cases/deploy.yml" 2>/dev/null)"
if [ -z "$run" ]; then fail "⑭ 케이스 추출 실패"; else
    out="$(env REPO_DIR="$REPO" FPM_TDD_NATIVE_REMOTE=1 bash -c "$run" 2>/dev/null)"
    case "$out" in skip*) ok "⑭ bundle-in-sync 가 원격 표식에서 skip" ;; *) fail "⑭ bundle-in-sync → '$out' (skip 기대)" ;; esac
fi

echo "── PASS $PASS / FAIL $FAIL"
[ "$FAIL" -eq 0 ]
