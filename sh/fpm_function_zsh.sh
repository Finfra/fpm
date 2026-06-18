# shellcheck shell=bash disable=all
# sh/fpm_function_zsh.sh — zsh 전용 구현 (fpm_function.sh 가 zsh 일 때만 source)
#
# 분리 이유: 본 함수는 zsh 글롭/확장(setopt·<->·${(@s:|:)}·${(L)}·중첩 ${${}})을 사용.
#   bash 가 fpm_function.sh 를 source 하면 `<->` 가 [[ ]] 내 리다이렉션으로 오인되어
#   parse error(syntax error near `<-')로 전체 로드가 중단됨. fpm.sh:24 와 동일하게,
#   zsh 전용 구문을 bash 파서로부터 격리하기 위해 별도 파일로 분리.
# bash 는 본 파일을 source 하지 않음 — fpm_function.sh 의 bash 분기에서 동등 fallback 정의.

# _cdfn_resolve : 텍스트 부분일치 → 단일 프로젝트 id 를 stdout 으로 반환
#   매칭 소스 = $FPM_BASE/Projects.md 테이블의 프로젝트명·한국어명칭·경로 (대소문자 무시)
#   매치 0개 → 메시지(stderr)+return 1 / 1개 → id 출력 / 다수 → choose from list 선택 후 id 출력
_cdfn_resolve() {
    setopt local_options extended_glob   # <-> 숫자 glob·## 트림 — KM 등 비인터랙티브 zsh 대비
    local q="$1"
    [[ -z "$q" ]] && { echo "Usage: cdf*n <text>  (프로젝트명/한글명/경로 부분일치)" >&2; return 1; }
    local proj_md="${FPM_BASE}/Projects.md"
    [[ -f "$proj_md" ]] || { echo "Error: $proj_md not found" >&2; return 1; }

    # 순수 zsh 파싱 (외부 awk/tr 의존 제거 — 일부 인터랙티브 zsh 설정에서 함수 내 awk 가
    # 단일 명령으로 오파싱되는 문제 회피). Projects.md 표를 '|' 로 split, 숫자 id 행만 매칭.
    local ql="${q:l}"          # zsh 소문자 변환
    local -a hits=()           # 원소: "<id>\t<표시문자열>"
    local line id eng kor pth hay
    local -a cols
    while IFS= read -r line; do
        [[ "$line" == \|* ]] || continue            # 표 행만
        cols=("${(@s:|:)line}")                      # '|' 로 split
        # cols: [1]="" [2]=id [3]=프로젝트명 [4]=한국어명 [5]=Dmn [6]=경로 ...
        id="${${cols[2]##[[:space:]]##}%%[[:space:]]##}"
        [[ "$id" == <-> ]] || continue               # 숫자 id 행만
        eng="${${cols[3]##[[:space:]]##}%%[[:space:]]##}"
        kor="${${cols[4]##[[:space:]]##}%%[[:space:]]##}"
        pth="${${cols[6]//\`/}##[[:space:]]##}"; pth="${pth%%[[:space:]]##}"
        hay="${(L)eng} ${(L)kor} ${(L)pth}"
        [[ "$hay" == *"$ql"* ]] && hits+=("${id}"$'\t'"${id}  ${eng}  (${kor})  ${pth}")
    done < "$proj_md"

    local n=${#hits[@]}
    if (( n == 0 )); then
        echo "❌ no match: $q" >&2; return 1
    elif (( n == 1 )); then
        printf '%s' "${hits[1]%%$'\t'*}"; return 0
    else
        # 다수 매치 → 네이티브 선택창 (표시문자열만 노출, 선택분의 앞 id 반환)
        local menu_file="/tmp/.cdfn_menu_$$" picked
        printf '%s\n' "${hits[@]#*$'\t'}" > "$menu_file"
        picked=$(osascript \
            -e 'set t to do shell script "cat '"$menu_file"'"' \
            -e 'set L to paragraphs of t' \
            -e 'set c to choose from list L with prompt "여러 개 매치 — 프로젝트 선택" without multiple selections allowed' \
            -e 'if c is false then return ""' \
            -e 'return item 1 of c' 2>/dev/null)
        command rm -f "$menu_file"
        [[ -z "$picked" ]] && { echo "취소됨" >&2; return 1; }
        printf '%s' "${picked%% *}"; return 0
    fi
}
