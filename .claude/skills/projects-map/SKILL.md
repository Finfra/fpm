---
title: projects-map
description: Projects.md 의 "# 프로젝트 트리" 섹션을 파싱해 프로젝트 간 관계도(Projects_map.htm)를 자립형 HTML 로 생성. Issue_map 의 프로젝트 버전, prj1(___pm) 로컬 전용
date: 2026-07-19
---

# 목적

`Projects.md` 는 전 프로젝트를 나열하지만 **어떤 프로젝트가 어디에 속하는지**는 표만으로 파악하기 어렵다. 본 스킬은 `Projects.md` 의 신설 `# 프로젝트 트리` 섹션(텍스트 인덴트 트리)을 소스로 `Projects_map.htm` 을 생성한다.

설계 근거는 [`_doc_arch/projects-map-design.md`](../../../_doc_arch/projects-map-design.md) 가 SSOT — 문법·완전성·토글·링크 사양 변경은 그 문서를 먼저 갱신할 것.

**prj1(`___pm`) 로컬 스킬이다** — `Projects.md` 자체가 `___pm` 전용 데이터라 글로벌 SCAR 화 불필요(issue-map 과의 핵심 차이).

# 트리거

* `python3 .claude/skills/projects-map/build_projects_map.py` 직접 실행
* "프로젝트 맵 갱신해줘", "Projects_map 다시 그려줘" (자연어, ___pm 루트에서)
* `Projects.md` 의 `# 프로젝트 트리` 섹션 갱신 직후

# 실행

`___pm` 루트(= `Projects.md` 위치)에서 실행. 스크립트 자신의 위치로 루트를 자동 추론하므로 cwd 는 무관하나, 출력은 기본적으로 루트에 쓰인다.

```bash
python3 .claude/skills/projects-map/build_projects_map.py

# 경로 직접 지정
python3 .claude/skills/projects-map/build_projects_map.py --root ~/_git/___pm --projects Projects.md --out Projects_map.htm
```

생성 후 확인:

```bash
open Projects_map.htm
```

# 토글

`data/projects_map_setting.yml` 의 `enabled` 키. `false` 면 생성기가 즉시 종료(no-op) — 기존 파일 보존, 콘솔에 스킵 사유만 출력. 파일 부재 시 `enabled: true` 로 간주(옵트아웃 방식).

# 입력 규약 (Projects.md)

* **속성 SSOT**: `### 📋 프로젝트` 표 — id·이름·경로·이모지·color
* **계층 SSOT**: `# 프로젝트 트리` 섹션의 fenced code block(````markdown` ... ` ``` `) — 2-space 인덴트, `- {id}. {emoji} {name}` (프로젝트 노드) 또는 `- {label}` (그룹 노드, id 없음)
* 트리 노드의 이모지·이름은 사람이 소스를 읽을 때를 위한 표기일 뿐 — 실제 렌더는 항상 표를 재조회함(트리와 표가 어긋나도 표가 이김)

# 완전성

표의 모든 id 가 트리에 없으면 생성 시 자동으로 `미분류` 그룹 노드 하위에 편입되고 콘솔에 경고가 뜬다. `Issue.md` 존재 여부는 포함 조건과 무관 — 소스가 애초 `Projects.md` 이므로 이 조건 자체가 발생하지 않는다.

# 노드 링크

| 요소 | 동작 |
| :--- | :--- |
| 프로젝트명 클릭 | `file://{경로}` — Finder(OS 기본 핸들러)로 오픈 |
| 🆚 클릭 | `vscode://file{경로}` — VSCode 오픈(`cdfv` 대응) |
| 📋 클릭 | `cdf {id}` 문자열 클립보드 복사(터미널 함수는 htm 안에서 직접 실행 불가) |
| 경로 없음(폴더 삭제·이동) | 링크 비활성화(취소선) + 툴팁 "경로 없음" |

# 산출물

* `Projects_map.htm` — `Projects.md` 와 동일 폴더(`___pm` 루트)
* 마커 `PROJECTS-MAP:TREE`(교체) / `PROJECTS-MAP:NOTES`(재생성 시 보존 — 수기 메모는 이 구간에)
* 생성 산출물이므로 git 비추적 — `.gitignore` 에 `Projects_map.htm` 등록됨(`Issue_map.htm` 과 동일 정책)
* 외부 리소스 요청 0건(파일 하나로 완결) — Mermaid/`mmdc` 비의존

# 완료 조건

1. `python3 .claude/skills/projects-map/build_projects_map.py` 가 오류 없이 종료하고 `프로젝트 N건` 을 출력
2. `Projects_map.htm` 에 `href="http`·`src="http` 가 0건(외부 리소스 미사용)
3. 이전 파일의 `PROJECTS-MAP:NOTES` 내용이 보존됨
4. 표의 id 전부가 트리에 존재하거나(0건 미분류) 미분류 편입 건수가 출력됨

# 제약

* 파서는 `Projects.md` 의 표(8열: id·명·한글명·Dmn·경로·설명·이모지·color)와 `# 프로젝트 트리` fenced block 형식을 신뢰한다 — 열 순서·펜스 여부가 바뀌면 파싱 실패
* 외부 의존 없음(Python 표준 라이브러리만)

# 참조

* [`_doc_arch/projects-map-design.md`](../../../_doc_arch/projects-map-design.md) — 설계 SSOT
* [`~/.claude/skills/issue-map/SKILL.md`](~/.claude/skills/issue-map/SKILL.md) — 패턴 원본
* [`Projects.md`](../../../Projects.md)
