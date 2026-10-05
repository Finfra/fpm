#!/bin/bash
# test_claude_bin_resolve.sh — Issue564 회귀 테스트 (tdd playlist #44 claude-bin-resolve)
#
# claude CLI 판정이 7곳으로 갈려, 공식 설치 경로 `~/.local/bin/claude` 가 비대화 PATH 에 없으면
#   install.sh 가 SCAR·MCP 배선을 «셸-only» 로 오판해 건너뛰고 성공을 보고했다(jma 실측).
#   해석 단일 지점 sh/fpm-claude-bin.sh 가 후보를 찾고, 7곳이 모두 그것을 쓰는지 검증한다.
#   ① ~/.local/bin ② ~/.claude/local ③ nvm 최신 — PATH 밖이어도 찾는다
#   ④ PATH 에 있으면 PATH 쪽이 먼저 ⑤ 실행 불가 파일은 후보가 아니다 · 전멸 rc 1
#   ⑥ 찾으면 PATH 앞에 붙여 `command -v claude` 가 통한다(호출부 무변경의 근거)
#   ⑦ CLI 모드: 경로 출력 rc 0 / 전멸 시 무출력 rc 1 ⑧ FPM_CLAUDE_PATH_ONLY=1 → PATH 만
#   ⑨ PATH 밖 claude 만 있는 샌드박스에서 install.sh 가 SCAR 를 건너뛰지 않는다
#   ⑩ check.sh·uninstall.sh 도 같은 샌드박스에서 claude 를 찾는다
#   ⑪ 케이스 core.yml:claude-cli-available 이 같은 샌드박스에서 ok
#
# 격리: 임시 HOME + claude 디렉토리를 뺀 PATH + 호출을 기록하는 스텁 claude. 실 ~/.claude 무접촉.
# 실행: bash scripts/test_claude_bin_resolve.sh   (수 초)
set -u

REPO="$(cd "$(dirname "$0")/.." && pwd)"
R="$REPO/sh/fpm-claude-bin.sh"
SB="$(mktemp -d "${TMPDIR:-/tmp}/claude-bin-test.XXXXXX")"
trap 'rm -rf "$SB"' EXIT
PASS=0; FAIL=0
ok()   { PASS=$((PASS + 1)); echo "  ok   $1"; }
fail() { FAIL=$((FAIL + 1)); echo "  FAIL $1"; }
check() { if [ "$2" = "$3" ]; then ok "$1"; else fail "$1 (want='$3' got='$2')"; fi; }

echo "[test_claude_bin_resolve]"
[ -f "$R" ] && ok "대상 존재: sh/fpm-claude-bin.sh" || fail "대상 존재: sh/fpm-claude-bin.sh"

# claude 가 든 디렉토리를 PATH 에서 뺀다(나머지 도구는 보존) — release-check A-1 과 같은 방식
NOCLAUDE="$PATH"
while cb="$(PATH="$NOCLAUDE" command -v claude 2>/dev/null)" && [ -n "$cb" ]; do
    NOCLAUDE="$(printf '%s' "$NOCLAUDE" | tr ':' '\n' | grep -vxF "$(dirname "$cb")" | paste -sd ':' -)"
done
# 이 머신의 시스템 경로에 claude 가 있으면 ⑤ 전멸 판정은 성립하지 않는다 — 전제로 드러낸다
SYS=""; for p in /opt/homebrew/bin/claude /usr/local/bin/claude /usr/bin/claude; do [ -x "$p" ] && SYS="$p"; done

stub() {  # $1 = 설치 경로 — 호출 인자를 기록하는 가짜 claude
    mkdir -p "$(dirname "$1")"
    cat >"$1" <<EOF
#!/bin/bash
echo "\$*" >>"$SB/claude.log"
case "\$*" in "mcp get"*) exit 1 ;; esac
exit 0
EOF
    chmod +x "$1"
}
resolve() {  # $1 = HOME, $2 = PATH → "rc|FPM_CLAUDE_BIN|command -v claude"
    env -i HOME="$1" PATH="$2" ${3:+FPM_CLAUDE_PATH_ONLY=$3} bash -c '
        . "'"$R"'" 2>/dev/null || { echo "noload||"; exit; }
        fpm_resolve_claude; rc=$?
        echo "$rc|${FPM_CLAUDE_BIN:-}|$(command -v claude 2>/dev/null)"'
}

# ①
H="$SB/h1"; stub "$H/.local/bin/claude"
check "① ~/.local/bin (PATH 밖)" "$(resolve "$H" "$NOCLAUDE" | cut -d'|' -f1,2)" "0|$H/.local/bin/claude"
# ⑥
check "⑥ 찾은 뒤 command -v claude 통함" "$(resolve "$H" "$NOCLAUDE" | cut -d'|' -f3)" "$H/.local/bin/claude"
# ②
H="$SB/h2"; stub "$H/.claude/local/claude"
check "② ~/.claude/local" "$(resolve "$H" "$NOCLAUDE" | cut -d'|' -f1,2)" "0|$H/.claude/local/claude"
# ③ nvm — 여러 버전이면 최신
H="$SB/h3"; stub "$H/.nvm/versions/node/v18.2.0/bin/claude"; stub "$H/.nvm/versions/node/v20.11.1/bin/claude"
check "③ nvm 최신 버전" "$(resolve "$H" "$NOCLAUDE" | cut -d'|' -f1,2)" "0|$H/.nvm/versions/node/v20.11.1/bin/claude"
# ④ PATH 우선
H="$SB/h4"; stub "$H/.local/bin/claude"; stub "$SB/pathbin/claude"
check "④ PATH 쪽이 먼저" "$(resolve "$H" "$SB/pathbin:$NOCLAUDE" | cut -d'|' -f1,2)" "0|$SB/pathbin/claude"
# ⑤ 실행 불가 · 전멸
H="$SB/h5"; mkdir -p "$H/.local/bin"; printf '#!/bin/bash\n' >"$H/.local/bin/claude"; chmod -x "$H/.local/bin/claude"
if [ -z "$SYS" ]; then
    check "⑤ 실행 불가 파일 제외 → 전멸 rc 1" "$(resolve "$H" "$NOCLAUDE" | cut -d'|' -f1,2)" "1|"
else
    echo "  skip ⑤ 이 머신 시스템 경로에 claude 존재($SYS) — 전멸 판정 불가"
fi
# ⑧ PATH 만
H="$SB/h8"; stub "$H/.local/bin/claude"
check "⑧ FPM_CLAUDE_PATH_ONLY=1 → PATH 밖 무시" "$(resolve "$H" "$NOCLAUDE" 1 | cut -d'|' -f1,2)" "1|"
# ⑦ CLI 모드
out="$(env -i HOME="$SB/h1" PATH="$NOCLAUDE" bash "$R" 2>/dev/null)"; rc=$?
check "⑦ CLI 모드 → 경로 출력 rc 0" "$rc|$out" "0|$SB/h1/.local/bin/claude"
out="$(env -i HOME="$SB/h8" PATH="$NOCLAUDE" FPM_CLAUDE_PATH_ONLY=1 bash "$R" 2>/dev/null)"; rc=$?
check "⑦ CLI 모드 전멸 → 무출력 rc 1" "$rc|$out" "1|"

# ⑨⑩⑪ 실행체 — claude 가 ~/.local/bin 에만 있는 샌드박스
# Issue585: HOME 만 바꾸면 AOA_MEMORY_DIR 이 운영값으로 상속돼 bootstrap 이 운영 aoa 폴더에 쓴다 — 데이터 루트도 샌드박스로
H="$SB/hi"; mkdir -p "$H"; : >"$H/.zshrc"; stub "$H/.local/bin/claude"; : >"$SB/claude.log"
out="$(env HOME="$H" FPM_BACKUP_DIR="$H/backup" AOA_MEMORY_DIR="$H/.claude/data/aoa" AOA_MQ_DIR="$H/.claude/data/aoa/mq" PATH="$NOCLAUDE" bash "$REPO/sh/install.sh" 2>&1)"
case "$out" in *"미발견"*) fail "⑨ install.sh 가 claude 를 «미발견» 으로 오판" ;; *) ok "⑨ install.sh 가 «미발견» 을 말하지 않음" ;; esac
grep -q "plugin install\|plugin update" "$SB/claude.log" && ok "⑨ install.sh 가 플러그인 설치·갱신 호출" || fail "⑨ install.sh 플러그인 설치 호출 없음"
grep -q "^mcp add" "$SB/claude.log" && ok "⑨ install.sh 가 MCP 배선 호출" || fail "⑨ install.sh MCP 배선 호출 없음"

out="$(env HOME="$H" FPM_BACKUP_DIR="$H/backup" AOA_MEMORY_DIR="$H/.claude/data/aoa" AOA_MQ_DIR="$H/.claude/data/aoa/mq" PATH="$NOCLAUDE" bash "$REPO/sh/check.sh" 2>&1)"
case "$out" in *"claude CLI 존재"*) ok "⑩ check.sh 가 claude 를 찾음" ;; *) fail "⑩ check.sh 가 claude 를 못 찾음" ;; esac
: >"$SB/claude.log"
out="$(env HOME="$H" FPM_BACKUP_DIR="$H/backup" AOA_MEMORY_DIR="$H/.claude/data/aoa" AOA_MQ_DIR="$H/.claude/data/aoa/mq" PATH="$NOCLAUDE" bash "$REPO/sh/uninstall.sh" 2>&1)"
grep -q "^plugin list" "$SB/claude.log" && ok "⑩ uninstall.sh 가 claude 를 호출" || fail "⑩ uninstall.sh 가 claude 를 호출하지 않음"

run="$(python3 -c '
import sys, yaml
for c in yaml.safe_load(open(sys.argv[1]))["cases"]:
    if c["id"] == "claude-cli-available": print(c["run"])' "$REPO/tdd/cases/core.yml" 2>/dev/null)"
if [ -z "$run" ]; then
    fail "⑪ 케이스 추출 실패(pyyaml·케이스 id)"
else
    out="$(env -i HOME="$H" PATH="$NOCLAUDE" REPO_DIR="$REPO" bash -c "$run" 2>/dev/null)"
    case "$out" in *ok*) ok "⑪ 케이스 claude-cli-available → ok" ;; *) fail "⑪ 케이스 claude-cli-available → '$out'" ;; esac
fi

echo "── PASS $PASS / FAIL $FAIL"
[ "$FAIL" -eq 0 ]
