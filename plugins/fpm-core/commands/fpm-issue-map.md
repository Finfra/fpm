---
name: fpm-issue-map
description: "Issue.md → Issue_map.htm 이슈 의존 관계도 재생성 (issue-map 스킬 실행)"
date: 2026.07.29
---

> ⚠️ **글로벌 SCAR 변경 가드** (Issue46)
>
> 본 커맨드는 모든 프로젝트가 공유. 즉흥 수정 금지.
>
> * cwd ≠ `~/.claude/` → 즉시 수정 금지, `~/.claude/Issue.md` 이슈 등록 후 별도 세션에서 처리
> * 영속 설계 SSOT: [`skills/issue-map/SKILL.md`](../skills/issue-map/SKILL.md)
> * 절차: `~/.claude/rules/global-scar-change-rules.md`

# 동작

현재 프로젝트의 nPTiR 루트에서 [issue-map 스킬](../skills/issue-map/SKILL.md)의 생성기를 실행하여 `Issue_map.htm` 을 최신 `Issue.md` 기준으로 재생성한다.

생성기 경로는 **플러그인 번들 → 글로벌 SCAR 2단계**로 해석한다(Issue316). 경로 하드코딩은 플러그인 전용 설치 환경에서 영구 실패하므로 금지. resolver SSOT: [`skills/issue-map/SKILL.md`](../skills/issue-map/SKILL.md) "생성기 경로 해석".

```bash
BIM=""
for c in "${CLAUDE_PLUGIN_ROOT:-/nonexistent}/skills/fpm-issue-map/build_issue_map.py" \
         "$HOME/.claude/skills/issue-map/build_issue_map.py"; do
  [ -f "$c" ] && { BIM="$c"; break; }
done
[ -n "$BIM" ] || { echo "issue-map 생성기 없음 (플러그인·글로벌 양쪽 부재) — 중단"; exit 1; }

python3 "$BIM"
```

생성 성공 시 이슈 건수·파일 크기를 보고하고, 요청이 있으면 브라우저로 연다.

```bash
open -a Firefox "file://$PWD/Issue_map.htm"
```

# 인자

| 인자 | 동작 |
| :--- | :--- |
| (없음) | `Issue.md` → `Issue_map.htm` 재생성 (정리 완료 이슈는 그래프에서 생략) |
| `check` | `--check` 로 파싱 결과만 출력 (파일 미생성). 형식 오류 진단용 |
| `all` | `--all` — 정리 완료 이슈까지 전량 그래프에 표시 |
| `deadlock` | `--deadlock` — 타 prj 선행 목록 + 교착(순환 대기) 진단만 출력 (파일 미생성) |
| `no-cross` | `--no-cross` — 타 prj 조회 없이 생성 (오프라인·속도 우선) |
| `open` | 재생성 후 Firefox 로 열기 |

"교착 아니야?", "왜 안 풀려?", "뭘 기다리는 거야" 류 질문에는 `deadlock` 을 먼저 돌린다 — 각 prj `Issue.md` 를 사람이 열어 볼 필요 없이 🔴 교착 / 🟡 미확인 / 🟢 단순 대기 를 한 줄로 답한다.

```bash
python3 "$BIM" --deadlock   # $BIM 은 위 resolver 로 확정
```

# 실행 전 확인

* 현재 디렉토리가 nPTiR 루트(`Issue.md` 위치)인지 — 아니면 스크립트가 즉시 실패한다
* `mmdc` 설치 여부 — 미설치 시 `npm i -g @mermaid-js/mermaid-cli`

# 보고 형식

* 생성 결과 1줄: 파일 경로 · 크기 · 이슈 건수 · 완료 건수
* 새로 차단 해제된 이슈(선행이 이번에 완료된 이슈)가 있으면 함께 알림
* 파싱에서 누락된 이슈가 의심되면 `--check` 결과를 함께 제시
* **교착 검출(🔴) 또는 타 prj 미확인(⚠️) 이 나오면 조용히 넘기지 말고 함께 보고** — 미확인은 대개 `depends` 표기 오타이거나 `~/_git/___pm/projects/` 에 매핑이 없는 prj 다

# 주의

* `Issue_map.htm` 은 **생성 산출물**이다. 직접 편집한 내용은 다음 실행에서 사라지며, 예외적으로 `ISSUE-MAP:NOTES` 구간만 보존된다
* `Issue_map.htm` 은 git 추적 대상이 아니다 — `_doc_work` 를 ignore 하는 프로젝트는 `.gitignore` 에 추가 (prj1#Issue286)
* 단계 그룹 배치는 프로젝트 루트의 `data/issue_stage_map.json` 에서 관리한다(선택 파일). 쓰는 프로젝트는 신규 이슈 등록 시 함께 추가할 것 (누락 시 그룹 밖에 그려짐)
