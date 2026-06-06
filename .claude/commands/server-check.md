---
title: server-check
description: Check status of favorite SSH servers listed in Servers.md
date: 2026-06-03
---

Check SSH connectivity for favorite servers defined in project `Servers.md`. Servers.md 표(`| id | Name | ssh alias | ... |`)를 파싱하여 **id 순**으로 점검하고, 결과를 id 포함 표로 출력한다.

## Usage

```bash
/server-check              # Servers.md 중 check=O 행만 (id 순)
/server-check jma jm4      # 특정 서버만 (Name 기준, check 무시)
```

## Implementation

```bash
#!/bin/bash

servers_file="$PWD/Servers.md"
[ -f "$servers_file" ] || { echo "Error: $servers_file not found"; exit 1; }

# Servers.md 표 파싱: '| id | Name | ssh alias | ... | check |' 행만 추출 → "id:Name"
# (id 가 숫자인 데이터 행만; 헤더/구분선 제외). Name 컬럼 = ~/.ssh/config alias.
# check 컬럼 인덱스를 헤더에서 동적 탐지 → 값이 'O' 인 행만 대상 (컬럼 부재 시 전체 통과).
rows=$(awk -F'|' '
  function trim(s){ gsub(/^[ \t]+|[ \t]+$/,"",s); return s }
  chk==0 { for(i=1;i<=NF;i++) if(tolower(trim($i))=="check") chk=i }
  $2 ~ /^[[:space:]]*[0-9]+[[:space:]]*$/ {
    if (chk>0 && trim($chk)!="O") next
    print trim($2)":"trim($3)
  }' "$servers_file")

# 인자 있으면 해당 Name 만 필터
if [ $# -gt 0 ]; then
  filt=""
  for want in "$@"; do
    line=$(printf "%s\n" "$rows" | awk -F: -v n="$want" '$2==n')
    [ -n "$line" ] && filt="$filt$line"$'\n'
  done
  rows="$filt"
fi

echo "=== Server Status Check (id순) ==="
echo

# 병렬 점검 — id 별 임시파일에 결과 기록 (cold 핸드셰이크 false DOWN 방지: ConnectTimeout 4s)
tmpd=$(mktemp -d)
while IFS=: read -r id name; do
  [ -z "$id" ] && continue
  ( r=$(timeout 6 ssh -o ConnectTimeout=4 -o LogLevel=ERROR "$name" hostname 2>/dev/null)
    if [ -n "$r" ]; then echo "$id|$name|✅|$r"; else echo "$id|$name|❌|DOWN"; fi
  ) > "$tmpd/$(printf '%03d' "$id")" &
done <<< "$rows"
wait

printf "%-3s %-7s %-3s %s\n" "id" "srv" "" "host"
for f in $(ls "$tmpd" | sort -n); do
  IFS='|' read -r id name st host < "$tmpd/$f"
  printf "%-3s %-7s %-3s %s\n" "$id" "$name" "$st" "$host"
done
rm -rf "$tmpd"

echo
echo "Source: $servers_file"
```

## Details

- **id 순 출력 + id 포함** — Servers.md 표를 파싱하므로 서버 추가/삭제가 자동 반영(하드코딩 목록 없음)
- **check 컬럼 필터** — `check` 값이 `O` 인 행만 점검. 헤더에서 `check` 컬럼 위치를 동적 탐지하므로 컬럼 순서 변경에 강함. `check` 컬럼이 없으면 전체 점검(하위 호환)
- **병렬 점검** — id별 임시파일 수집 후 id 순 정렬 출력 (속도 + 순서 동시 확보)
- **ConnectTimeout 4s / timeout 6s** — 절전 복귀·cold 핸드셰이크의 false DOWN 완화 (기존 2s 는 정상 서버를 DOWN 오판하는 사례 있었음)
- Name 컬럼 = `~/.ssh/config` alias 기준
