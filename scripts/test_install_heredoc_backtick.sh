#!/bin/bash
# test_install_heredoc_backtick.sh — Issue567 회귀 테스트 (tdd playlist #45 install-heredoc-no-exec)
#
# sh/install.sh «5. 안내» 는 $REPO_DIR 전개 때문에 따옴표 없는 heredoc 이다. 거기 적힌
#   `python3 server.py` 백틱이 **호출한 셸의 cwd 에서 실행**됐다(M3 네이티브 실측 jma·fg1 둘 다).
#   server.py 가 있는 곳에서 설치하면 hub 가 포그라운드로 떠 설치가 멈춘다.
#   ① server.py 스텁(표식 파일 생성)이 있는 cwd 에서 샌드박스 install → 스텁 미실행
#   ② 안내 출력에 `python3 server.py` 가 문자 그대로 남는다
#   ③ 정적 검사: sh/*.sh 의 따옴표 없는 heredoc 본문에 이스케이프 안 된 백틱 0
#
# 격리: 임시 HOME + --no-scar --no-mcp. 실 ~/.zshrc·플러그인 무접촉. 실행: bash scripts/test_install_heredoc_backtick.sh
set -u

REPO="$(cd "$(dirname "$0")/.." && pwd)"
SB="$(mktemp -d "${TMPDIR:-/tmp}/heredoc-bt-test.XXXXXX")"
trap 'rm -rf "$SB"' EXIT
PASS=0; FAIL=0
ok()   { PASS=$((PASS + 1)); echo "  ok   $1"; }
fail() { FAIL=$((FAIL + 1)); echo "  FAIL $1"; }

echo "[test_install_heredoc_backtick]"

# ①② 스텁이 있는 cwd 에서 설치
CWD="$SB/cwd"; H="$SB/home"; mkdir -p "$CWD" "$H"; : >"$H/.zshrc"
printf 'open("%s/EXECUTED", "w").write("x")\n' "$SB" >"$CWD/server.py"
out="$(cd "$CWD" && env HOME="$H" FPM_BACKUP_DIR="$H/backup" bash "$REPO/sh/install.sh" --no-scar --no-mcp 2>&1)"; rc=$?
[ "$rc" -eq 0 ] && ok "① 샌드박스 install rc 0" || fail "① 샌드박스 install rc $rc"
[ -e "$SB/EXECUTED" ] && fail "① 안내 heredoc 이 cwd 의 server.py 를 실행했다" || ok "① cwd 의 server.py 를 실행하지 않음"
case "$out" in *'`python3 server.py`'*) ok "② 안내에 \`python3 server.py\` 문자 그대로" ;; *) fail "② 안내 문구에서 명령이 빠짐(백틱 치환)" ;; esac

# ③ 정적 검사 — 코드 줄의 따옴표 없는 heredoc 만 대상(주석 속 '<<' 는 heredoc 이 아니다)
bad="$(python3 - "$REPO" <<'PY'
import re, glob, os, sys
root = sys.argv[1]
out = []
for f in sorted(glob.glob(os.path.join(root, "sh", "*.sh"))):
    L = open(f, errors="ignore").read().split("\n")
    i = 0
    while i < len(L):
        code = L[i].split("#", 1)[0] if not L[i].lstrip().startswith("#") else ""
        m = re.search(r"(?<!<)<<-?\s*([A-Za-z_]\w*)\b", code)
        if m:
            d, j = m.group(1), i + 1
            while j < len(L) and L[j].strip() != d:
                if re.search(r"(?<!\\)`", L[j]):
                    out.append(f"{os.path.relpath(f, root)}:{j+1}")
                j += 1
            i = j
        i += 1
print("\n".join(out))
PY
)"
[ -z "$bad" ] && ok "③ sh/*.sh 따옴표 없는 heredoc 에 비이스케이프 백틱 0" || fail "③ 비이스케이프 백틱: $(echo $bad)"

echo "── PASS $PASS / FAIL $FAIL"
[ "$FAIL" -eq 0 ]
