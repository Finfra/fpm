---
title: projects-map
description: "Projects.md 의 \"# Project Map\" 섹션(구 표기 \"# 프로젝트 트리\" 도 허용)을 파싱해 프로젝트 간 관계도(Projects_map.htm)를 mermaid HTML 로 생성. hub 서버(/projects-map) 경유로 열어야 렌더됨. Issue_map 의 프로젝트 버전, prj1(___pm) 로컬 전용"
date: 2026-07-19
---

# 목적

`Projects.md` 는 전 프로젝트를 나열하지만 **어떤 프로젝트가 어디에 속하는지**는 표만으로 파악하기 어렵다. 본 스킬은 `Projects.md` 의 `# Project Map` 섹션(Issue294 rename — 구 `# Project Tree`·`# 프로젝트 트리` 도 파서 허용, 텍스트 인덴트 트리)을 소스로 `Projects_map.htm` 을 생성한다.

설계 근거는 [`_doc_arch/projects-map-design.md`](../../../_doc_arch/projects-map-design.md) 가 SSOT — 문법·완전성·토글·링크 사양 변경은 그 문서를 먼저 갱신할 것.

**prj1(`___pm`) 로컬 스킬이다** — `Projects.md` 자체가 `___pm` 전용 데이터라 글로벌 SCAR 화 불필요(issue-map 과의 핵심 차이).

# 트리거

* `python3 .claude/skills/projects-map/build_projects_map.py` 직접 실행
* "프로젝트 맵 갱신해줘", "Projects_map 다시 그려줘" (자연어, ___pm 루트에서)
* `Projects.md` 의 `# Project Map` 섹션 갱신 직후

# 실행

`___pm` 루트(= `Projects.md` 위치)에서 실행. 스크립트 자신의 위치로 루트를 자동 추론하므로 cwd 는 무관하나, 출력은 기본적으로 루트에 쓰인다.

```bash
python3 .claude/skills/projects-map/build_projects_map.py

# 경로 직접 지정
python3 .claude/skills/projects-map/build_projects_map.py --root ~/_git/___pm --projects Projects.md --out Projects_map.htm
```

생성 후 확인 — 목적에 따라 셋 중 하나:

| 보고 싶은 곳 | 방법 |
| :--- | :--- |
| **VSCode 탐색기 클릭** | `Projects_map.md` 클릭 → `⌘⇧V` (미리보기). `bierner.markdown-mermaid` 가 직접 렌더 — 서버·CDN 불요 |
| OS 브라우저 | `open "http://127.0.0.1:9876/projects-map"` |
| VSCode Simple Browser 패널 | `open "vscode://finfra.fpm-simple-browser/open?url=http%3A%2F%2F127.0.0.1%3A9876%2Fprojects-map"` |

`.md` 는 다이어그램·미할당 목록만 담은 읽기 전용 판이다. 필터·`cdf` 복사·활성 세션 배지가 필요하면 hub 판(`.htm`)을 열 것.

> ⚠️ `open Projects_map.htm`(= `file://`)로 열지 말 것. 맵 본체가 mermaid **원시 소스 텍스트**로 보인다. 파일에는 mermaid 런타임 로더가 없고, hub 서버가 serve 시점에 pinned UMD 를 주입하기 때문이다(Issue244). 파일의 결함이 아니라 설계된 의존이다.
>
> `/htm-doc?path=…` 범용 라우트도 쓸 수 없다 — `Projects_map.htm` 은 `_doc_work/htm/` 이 아니라 프로젝트 루트에 생성되어 `/register-doc` 대상이 아니며 `403 not a registered htm doc` 이 난다. 전용 라우트 `/projects-map` 만 유효하다.

# 토글

`data/projects_map_setting.yml` 의 `enabled` 키. `false` 면 생성기가 즉시 종료(no-op) — 기존 파일 보존, 콘솔에 스킵 사유만 출력. 파일 부재 시 `enabled: true` 로 간주(옵트아웃 방식).

# 입력 규약 (Projects.md)

* **속성 SSOT**: `### 📋 프로젝트` 표 — id·이름·경로·이모지·color
* **계층 SSOT**: `# Project Map` 섹션의 **펜스 없는** Main/Sub Map 마크다운 리스트 (Issue298 — 파서가 코드펜스를 무시하므로 펜스 유무 무관) — 2-space 인덴트, `- {id}. {emoji} {name}` (프로젝트 노드) 또는 `- {label}` (그룹 노드, id 없음)
* 트리 노드의 이모지·이름은 사람이 소스를 읽을 때를 위한 표기일 뿐 — 실제 렌더는 항상 표를 재조회함(트리와 표가 어긋나도 표가 이김)

# 완전성

표의 모든 id 가 트리에 없으면 생성 시 자동으로 `미할당` 그룹 노드 하위에 편입되고 콘솔에 경고가 뜬다. `Issue.md` 존재 여부는 포함 조건과 무관 — 소스가 애초 `Projects.md` 이므로 이 조건 자체가 발생하지 않는다.

# 노드 링크

| 요소 | 동작 |
| :--- | :--- |
| 프로젝트명 클릭 | `file://{경로}` — Finder(OS 기본 핸들러)로 오픈 |
| 🆚 클릭 | `vscode://file{경로}` — VSCode 오픈(`cdfv` 대응) |
| 📋 클릭 | `cdf {id}` 문자열 클립보드 복사(터미널 함수는 htm 안에서 직접 실행 불가) |
| 🟢·📊 클릭 | 그 프로젝트의 **활성 Claude Code 세션**으로 VSCode 포커스(`POST /open-session`). 🟢=일반 세션 · 📊=dashboard |
| 경로 없음(폴더 삭제·이동) | 링크 비활성화(취소선) + 툴팁 "경로 없음" |

# 활성 세션 배지 (Issue299)

노드·트리 항목·미할당 목록에 지금 살아 있는 세션을 아이콘으로 얹는다. 세션 1개 = 아이콘 1개이며, 제목은 hover 툴팁으로만 보여 준다(본문에 쓰면 노드가 부풀어 지도가 안 읽힘).

* 데이터는 hub `GET /boards` 의 `live_sessions` — 페이지가 열려 있는 동안 5초마다 갱신
* 빌드가 굽는 것은 `경로 → prj id` 매핑뿐. 세션 스냅샷은 박지 않는다(여는 즉시 stale)
* **hub serve 전제** — `file://` 로 직접 열면 상대경로 fetch 가 실패해 배지가 없다. 배지뿐 아니라 **맵 본체(mermaid)도 렌더되지 않는다**(런타임을 hub 가 주입하므로 — "사용법" 경고 참조). `/open-prj` 노드 링크와 같은 제약
* **배지가 흐려져 있으면** hub 응답이 2회 연속 끊긴 상태다(툴팁에 "최신 상태 아님"). 그 배지는 낡은 정보이므로 클릭해도 실패할 수 있다
* **클릭 실패 진단** — alert 에 HTTP status·서버 문구·요청 origin 이 그대로 나온다. `POST /open-session` 줄이 `/tmp/___pm/claude-htm-server/stdout.log` 에 **있으면** 서버 처리분, **없으면** 요청이 닿지 않은 것(주소 해석·네트워크)
* 설계 근거·SVG 오버레이 사유: [`_doc_arch/projects-map-design.md`](../../../_doc_arch/projects-map-design.md) "활성 세션 오버레이"

# 산출물

* `Projects_map.htm` — `Projects.md` 와 동일 폴더(`___pm` 루트). hub 판(상호작용 있음, 서버 경유 필수)
* `Projects_map.md` — 같은 폴더의 형제 파일. VSCode 마크다운 미리보기용 읽기 전용 판(다이어그램 + 미할당 목록). 서버·CDN 의존 0
* 마커 `PROJECTS-MAP:TREE`(교체). 수기 메모는 루트 `_note.md` 파일 SSOT (Issue305 — 구 `PROJECTS-MAP:NOTES` 보존 마커 폐기, 부재 시 고정 문구 폴백)
* 생성 산출물이므로 git 비추적 — `.gitignore` 에 `Projects_map.htm` 등록됨(`Issue_map.htm` 과 동일 정책)
* 페이지 자신은 외부 리소스를 요청하지 않는다(`href="http`·`src="http` 0건). 단 **자립 실행 파일은 아니다** — 맵 본체가 `<pre class="mermaid">` 로 저작되므로 hub 서버가 serve 시점에 주입하는 mermaid 런타임에 의존한다(Issue244). 빌드 타임 `mmdc` 비의존일 뿐 런타임 mermaid 의존이다

# 완료 조건

1. `python3 .claude/skills/projects-map/build_projects_map.py` 가 오류 없이 종료하고 `프로젝트 N건` 을 출력
2. `Projects_map.htm` 에 `href="http`·`src="http` 가 0건(외부 리소스 미사용)
3. 루트 `_note.md` 내용이 부제 아래 `<div id="note">` 로 렌더됨 (파일 부재 시 고정 문구 — Issue305)
4. 표의 id 전부가 트리에 존재하거나(0건 미할당) 미할당 편입 건수가 출력됨
5. hub 로 열었을 때(`http://127.0.0.1:9876/projects-map`) 활성 세션이 있는 프로젝트 노드에 배지가 뜨고 클릭이 `POST /open-session` 을 부름
6. 형제 `Projects_map.md` 가 함께 생성되고, VSCode 마크다운 미리보기(`⌘⇧V`)에서 다이어그램이 그려짐

# 제약

* 파서는 `Projects.md` 의 표(8열: id·명·한글명·Dmn·경로·설명·이모지·color)와 `# Project Map` 인덴트 리스트 형식을 신뢰한다 — 열 순서·인덴트 규칙이 바뀌면 파싱 실패 (코드펜스는 무시하므로 펜스 유무는 무관 — Issue298)
* 외부 의존 없음(Python 표준 라이브러리만)

# 참조

* [`_doc_arch/projects-map-design.md`](../../../_doc_arch/projects-map-design.md) — 설계 SSOT
* [`~/.claude/skills/issue-map/SKILL.md`](~/.claude/skills/issue-map/SKILL.md) — 패턴 원본
* [`Projects.md`](../../../Projects.md)
