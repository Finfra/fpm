---
name: pm-check
description: 등록 프로젝트의 nPTiR 필수 폴더(특히 _doc_work/z_htm) 무결성 검사·자동 생성. hub 403 dead link 예방책.
date: 2026-07-09
---

# 용도

등록된 프로젝트(`projects/{번호}`)의 nPTiR 필수 폴더 존재를 검사하고, 없으면 생성한다.
특히 **`_doc_work/z_htm/`** 부재는 hub 렌더 산출물이 `/tmp/___pm` 로 fallback → register 훅
미매칭 → `/htm-doc` 403 dead link 를 유발하므로, 본 커맨드가 사전 방지한다.

> 근본 배경: hub 트리거(`~/.claude/hooks/fpm-hub-trigger.sh`)는 `$cwd/_doc_work/z_htm/` 존재 시만
> 프로젝트 로컬에 저장하고, register 훅(`fpm-hub-doc-register`)은 z_htm 경로만 등록한다. 두 훅의
> 계약이 z_htm 존재를 전제하므로, 모든 등록 프로젝트에 z_htm 을 보장하는 것이 예방책이다.

# 호출

```
/pm-check [번호|all]
```

* 인자 없음 또는 `all` → 등록된 모든 프로젝트 검사
* `번호` → 해당 프로젝트만 검사 (ex: `/pm-check 5`)

# 검사 대상 필수 폴더

| 폴더 | 사유 |
| :--- | :--- |
| `_doc_work/plan`   | nPTiR plan 산출물 |
| `_doc_work/tasks`  | nPTiR task 산출물 (복수형 고정) |
| `_doc_work/report` | nPTiR report 산출물 |
| `_doc_work/z_done` | 완료 이슈 산출물 아카이브 |
| `_doc_work/z_htm`  | **hub 렌더 산출물 저장·자동 등록 (403 예방)** |
| `_doc_arch`        | 영속 설계 문서 SSOT |

# 실행 절차

1. `projects/` 인덱스에서 대상 프로젝트 경로 수집 (`~` → `$HOME` 전개)
2. 각 프로젝트마다 위 필수 폴더 존재 확인
3. **부재 폴더는 `mkdir -p` 로 즉시 생성** (파괴적 작업 아님 — 승인 불요)
4. 프로젝트별 생성/정상 결과를 표로 보고

```bash
# 대상 결정: 인자 없으면 전체
ARG="${1:-all}"
BASE="$HOME/_git/___pm/projects"
# z_htm 는 hub 폴더 — fpm 설치 or ~/_git/___pm 존재 시에만 필수에 포함 (비-fpm 환경엔 불요)
if [ -d "$HOME/_git/___pm" ] || command -v fpm >/dev/null 2>&1; then
  REQUIRED=(_doc_work/plan _doc_work/tasks _doc_work/report _doc_work/z_done _doc_work/z_htm _doc_arch)
else
  REQUIRED=(_doc_work/plan _doc_work/tasks _doc_work/report _doc_work/z_done _doc_arch)
fi
# 제외: 0=home(~, nPTiR 워크스페이스 아님), 7/25/26=publish 미러(_doc_work 추가 시 미러 오염)
SKIP="0 7 25 26"

if [ "$ARG" = "all" ]; then
  NUMS=$(ls "$BASE" 2>/dev/null | grep -E '^[0-9]+$' | sort -n)
else
  NUMS="$ARG"   # 명시 지정 시 SKIP 무시 (사용자 의도 우선)
fi

for n in $NUMS; do
  if [ "$ARG" = "all" ]; then
    case " $SKIP " in *" $n "*) echo "prj$n: 제외(home/미러) — skip"; continue;; esac
  fi
  f="$BASE/$n"
  [ -f "$f" ] || { echo "prj$n: 인덱스 파일 없음 — skip"; continue; }
  p=$(sed 's#^~#'"$HOME"'#' "$f")
  [ -d "$p" ] || { echo "prj$n: 경로 부재($p) — skip"; continue; }
  created=""
  for d in "${REQUIRED[@]}"; do
    if [ ! -d "$p/$d" ]; then
      mkdir -p "$p/$d" && created="$created ${d##*/}"
    fi
  done
  if [ -n "$created" ]; then
    echo "prj$n ($p): 생성 →$created"
  else
    echo "prj$n ($p): OK"
  fi
done
```

* **제외 정책**: `all` 검사 시 `SKIP="0 7 25 26"` 는 자동 제외. 명시 번호(`/pm-check 7`)는 제외 무시 —
  사용자가 콕 집으면 의도로 간주해 생성. home(prj0)·publish 미러(prj7/25/26)는 nPTiR 워크스페이스가
  아니므로 z_htm 을 만들지 않는다 (미러는 `_doc_work` 추가 시 공개 미러로 새어나갈 위험).

# 보고 형식

```
| prj | 경로 | 결과 |
| :-- | :--- | :--- |
| 5   | ~/_git/___common | 생성: _doc_work/z_htm |
| 7   | ~/_git/__all/fpm | OK |
```

* 생성이 발생한 프로젝트는 별도 강조
* 인덱스 파일·경로 부재 프로젝트는 skip 로 명시 (오류 아님)

# 실행 제약 (Opus 4.8)

* 대상 프로젝트 **최대 60개** (전체 등록 규모). 초과 시 분할.
* `mkdir -p` 만 수행 — 기존 파일·폴더 **절대 삭제·덮어쓰기 금지**.
* 검사 후 실제 hub 렌더는 트리거가 담당 — 본 커맨드는 폴더 보장까지만.

# 연관

* 근본 원인·서버 안내: `services/hub/server.py` `_send_htm_doc_tmp_hint` (/tmp fallback 403 → HTML 안내)
* scaffold SSOT: `.claude/skills/pm/SKILL.md` 멱등 처리 매트릭스 (신규·adopt 시 z_htm 생성)
* hub 훅 계약: `~/.claude/hooks/fpm-hub-trigger.sh`, `~/.claude/hooks/fpm-hub-doc-register.sh`
