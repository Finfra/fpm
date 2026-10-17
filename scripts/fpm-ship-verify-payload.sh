#!/usr/bin/env bash
# fpm-ship-verify-payload.sh — 출고 3대 실기동 검증 원격 페이로드 (Issue609 ③④ + 상태 수집)
#
# 소비자 머신에서 ssh 표준입력으로 실행된다 — 드라이버 scripts/fpm-ship-verify.sh 가 보낸다.
# 읽기 전용: 설치·재기동은 하지 않는다(① ②는 런북 S6 — 이 단계는 그 결과를 판정만 한다).
# 출력 계약: `FPMR key=value` 줄이 드라이버의 판정 재료다.
# 사용: ssh <host> 'bash -s -- <port>' < scripts/fpm-ship-verify-payload.sh
set -uo pipefail
PORT="${1:-9876}"
FPM_DIR="${FPM_CLONE:-$HOME/_git/fpm}"
echo "FPMR host=$(hostname) os=$(uname -s)"
pv=$(claude plugin list 2>/dev/null | tr -d '\r' | awk '/fpm-core@/{f=1} f&&/Version:/{print $2; exit}')
echo "FPMR plugin=${pv:-?}"
echo "FPMR clone=$(git -C "$FPM_DIR" rev-parse --short HEAD 2>/dev/null || echo ?) clone_version=$(cat "$FPM_DIR/VERSION" 2>/dev/null | tr -d '\r' || echo ?)"
# ③ 무결성 — check.sh 의 «설치본 무결성» FAIL 행만 본다(rc 마커 같은 환경 FAIL 은 별도 줄로 남긴다)
out=$(bash "$FPM_DIR/sh/check.sh" 2>&1 | sed 's/\x1b\[[0-9;]*m//g')
echo "$out" | grep -E "무결성|결과:" | sed 's/^/FPMT /'
if echo "$out" | grep -q "무결성 불일치"; then echo "FPMR integrity=FAIL"; else echo "FPMR integrity=PASS"; fi
echo "FPMR check_summary=$(echo "$out" | grep -m1 '결과:' | tr -s ' ')"
# ④ /healthz·/boards 200 — hub 상주 판정. /boards 는 구 hub 가 404 로 답한다(Issue609)
code() { curl -s -o /dev/null -m 8 -w '%{http_code}' "http://127.0.0.1:$PORT$1" 2>/dev/null || echo 000; }
echo "FPMR healthz=$(code /healthz) boards=$(code /boards)"
