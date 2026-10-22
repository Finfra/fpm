#!/usr/bin/env bash
# sh/fpm-launcher-check.sh — 사용자 dotfile 의 alias 가 fpm 경로 런처 이름과 겹치는지 보고 (Issue653)
#
# 묻는 것: *"fpm 런처(v vn vw z zn za zw)보다 먼저 정의된 사용자 alias 가 있는가."*
#   있으면 fpm_editors.sh 는 사용자 정의를 존중해 런처를 만들지 않는다 (조용히 양보).
#   설치자가 «왜 v 가 fpm 것이 아닌지» 알 수 있도록 설치 시점에 한 번 알린다. 읽기 전용 — dotfile 을 고치지 않는다.
#   (alias v=vscode 처럼 같은 뜻이면 지워도 되지만, z 점프 플러그인처럼 다른 뜻이면 사용자 판단이다.)
#
# 사용: bash sh/fpm-launcher-check.sh [dotfile ...]   (인자 없으면 홈의 쉘 설정 파일 전부)
# 출력: 겹침이 없으면 무출력. 있으면 `file:줄: alias …` 목록과 안내. exit 항상 0 (설치를 막지 않는다)
set -u

if [ $# -gt 0 ]; then
    FILES=("$@")
else
    FILES=("$HOME/.zshrc" "$HOME/.bashrc" "$HOME/.zsh_aliases" "$HOME/.bash_aliases" "$HOME/.sh_aliases" "$HOME/.aliases")
fi

hits=""
for f in "${FILES[@]}"; do
    [ -f "$f" ] || continue
    out="$(grep -nE '^[[:space:]]*alias[[:space:]]+(v|vn|vw|z|zn|za|zw)=' "$f" 2>/dev/null)" || continue
    while IFS= read -r line; do hits="${hits}  ${f}:${line}"$'\n'; done <<< "$out"
done

[ -n "$hits" ] || exit 0
printf 'ℹ️  fpm 경로 런처(v/vn/vw/z/zn/za/zw)와 이름이 같은 사용자 alias 가 있다 — alias 가 우선하므로 fpm 런처는 정의되지 않는다:\n%s' "$hits"
printf '   fpm 런처를 쓰려면 위 줄을 지우고 새 쉘을 연다 (data/editor.yml 의 default_editor 를 따른다).\n'
exit 0
