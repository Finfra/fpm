---
name: fpm-hub
description: 요청을 HTML 문서로 렌더링하여 Firefox에 표시. Q&A 폼은 ___pm htm-server 로 자동 회수 (Issue45 단일 경로).
date: 2026-05-19
---

> ⚠️ **글로벌 SCAR 변경 가드 (Issue46)**: 본 커맨드는 모든 프로젝트가 공유. cwd ≠ `~/.claude/` 면 즉시 수정 금지 → `~/.claude/Issue.md` 이슈 등록 후 처리. 영속 설계 SSOT: `~/.claude/_doc_arch/hub-mode-arch.md`. 절차: `~/.claude/rules/global-scar-change-rules.md`

# /hub — HTML 결과 렌더 (Issue45 단일 모드)

> **Issue133**: a모드 render 트리거가 `..hub`/`/hub` → **`..show`/`/show`** 로 rename 됨 (우산명 `hub` 와 충돌 해소). `/hub <요청>`·`..hub <요청>` 는 한시적 deprecated alias (동작 동일 + `..show` 안내 첨부). 우산 토글 `/hub on|off|start|stop`·`..hub …` 는 `hub` 유지. 본 커맨드 문서는 `/show` 슬래시(`commands/show.md`)가 참조하는 렌더 절차 SSOT.

요청을 처리한 결과를 완전한 HTML 문서로 작성하여 Firefox 로 자동 표시함. 본문 HTML 은 `file://` 직접 open. Q&A 폼은 ___pm htm-server (port 9876) 로 fetch POST → inbox → bash polling 자동 회수.

* **전제**: ___pm htm-server 상시 운영 (___pm 프로젝트가 lifecycle 책임)
* **서버 down 시**: intercept hook 이 fail-loud — 사용자에게 `/dashboard-server start` 후 재시도 또는 `..hub stop` 안내. paste-back fallback 없음 (Issue45 제거)

Chrome 은 일반 브라우저로 유지, Firefox 는 hub·dashboard 전용으로 분리 운영.

**저장 경로 결정 (Issue21)**:
* 프로젝트 루트(`cwd`)에 `_doc_work/z_htm/` 폴더 존재 → `{cwd}/_doc_work/z_htm/hub_htm_{YYYYMMDD_HHMMSS}_a_{주제}.htm` (영속화)
* 폴더 없음 → `/tmp/___pm/hub_htm_{YYYYMMDD_HHMMSS}_a_{주제}.htm` (휘발 fallback, Issue64 — `/tmp` 평면 흩어짐 방지)
* 파일명 규약 (Issue123): `hub_htm_{YYYYMMDD_HHMMSS}_{mode}_{주제}.htm` — 날짜시간=`date +%Y%m%d_%H%M%S`, mode `a`=메인 렌더·`b`=ask 폼·`c`=auto 폼(Mode D), 주제=핵심 10자 내외 kebab-case

자연어 트리거 `..show` 와 동일한 동작 (Issue133 — 구 `..hub` 는 deprecated alias). 명시적 슬래시(`/show`) 사용 시 더 안정적.

## `/hub on` · `/hub off` — 자동 모드 토글 (Issue86)

`/hub on` / `/hub off` (또는 자연어 `..hub on` / `..hub off`)는 **렌더링 명령이 아니라 폴더별 hub 자동 모드(Issue83) 토글**.

* `ARGUMENTS` 가 `on` 또는 `off` 면 — `fpm-hub-trigger.sh` (UserPromptSubmit hook)가 이미 `~/.claude/.hub-state/<hash>` 상태 파일을 전환함. 본 커맨드는 **렌더·폼·Firefox open 절차 전부 skip**. 한 줄로 상태 확인만 출력하고 종료.
* `on` → 다음 턴부터 매 응답 자동 HTML 렌더 (trivial 응답은 Issue85 로 skip)
* `off` → 프로젝트 폴더라도 자동 렌더 안 함 (`..hub stop` 과 동일 효과)
* 인자 없는 `/show` 또는 `/show <요청>` 은 HTML 렌더 (아래 절차). `/hub <요청>` 도 deprecated alias 로 동일 동작
* bare `..show <요청>` 은 render-only(워크플로우 차단) 모드 — 우산 토글 `..hub on`/`..hub start` 와 구분됨 (Issue133)

## Mode 분리 (Issue45, 2026-05-19)

| 영역             | 본 커맨드 (`/hub`, Mode B)                 | dashboard agent (`..hub dash`, Mode C) | Mode D 자동 폼 (Issue43)              |
| :--------------- | :----------------------------------------- | :------------------------------------- | :------------------------------------ |
| 진입             | `..hub` + AskUserQuestion intercept        | `..hub dash <topic>` agent dispatch    | Stop hook 마커 자동 감지              |
| 본문 HTML        | Firefox `file://` 직접 open                | Firefox stable URL (서버 SPA shell)    | Firefox `file://` 직접 open           |
| Q&A 회수         | form fetch POST → server inbox → polling   | SSE 단방향 push                        | form fetch POST → server inbox → polling |
| ___pm htm-server | **필수** (실패 시 fail-loud)               | **필수** (실패 시 1회 안내 후 중단)    | **필수** (실패 시 fail-loud)          |
| 적합 시나리오     | 단발 응답, 1~5 다단계 질문                 | 장시간 모니터링, 실시간 갱신           | AskUserQuestion 미호출 자유 응답 N개  |

* 실시간 모니터링·SSE 가 필요하면 `..hub dash <topic>` 으로 dashboard agent 호출 (Mode C, 자매 SCAR)
* AskUserQuestion 호출 없이 사용자 자유 응답 N개를 회수하려면 응답 본문에 Mode D 마커(v1 sentinel 쌍) 삽입 (아래 섹션 참조)

## Mode D 자동 폼 마커 (Issue43 도입, Issue48 sentinel 강화 — 2026-05-19)

### 사용 시나리오

* info-filler 등 agent 가 자유 텍스트 N개 응답을 요구하는 경우
* `AskUserQuestion` 도구는 옵션 `minItems: 2` 강제라 free-text only 미지원
* 응답 본문에 v1 sentinel 쌍 마커 1회 삽입 → `fpm-ask-marker-detect.sh` (Stop hook) 가 자동 감지 → form HTML 생성·Firefox open·polling 지시 주입

### sentinel 토큰 (v1)

본 hook 은 다음 두 토큰을 그대로 매칭. 토큰 외 텍스트 무관:

* BEGIN 토큰: `htm-form:auto:v1:BEGIN`
* END 토큰: `htm-form:auto:v1:END`

쌍 구조 필수 (BEGIN/END 둘 다 매칭되어야 hook 발동). 단일 BEGIN/END 만 있으면 hook 무동작.

### 마커 schema (구조)

응답 본문 어디든 1회 삽입. HTML comment 1개 안에 BEGIN/END 쌍 + JSON body:

```
<!-- {BEGIN}
{
  "title": "강의 기획 Info 입력",
  "questions": [
    {
      "question": "강의 핵심 가치(value proposition)는?",
      "header": "Q1",
      "type": "freetext",
      "placeholder": "예: 30분 안에 ..."
    },
    {
      "question": "주요 타겟은?",
      "header": "Q2",
      "type": "select",
      "multiSelect": false,
      "options": [
        {"label": "초급", "description": "프로그래밍 입문자"},
        {"label": "중급", "description": "1-3년차 개발자"}
      ]
    }
  ]
}
{END} -->
```

위 예시의 `{BEGIN}`·`{END}` placeholder 는 실제 사용 시 위 sentinel 토큰으로 치환. 본 문서가 placeholder 표기를 쓰는 이유는 코드 펜스 내부 sentinel 노출이 hook 을 트리거하기 때문 (Issue48 회귀 회피).

### 필드 규약

| 필드 | 필수 | 설명 |
| :--- | :---: | :--- |
| `title` | ❌ | 폼 페이지 제목 (생략 시 hook 이 기본값 사용) |
| `questions[]` | ✅ | 최소 1개. 빈 배열 시 schema 위반 |
| `questions[].question` | ✅ | 사용자에게 보일 질문 텍스트 |
| `questions[].type` | ✅ | `"freetext"` 또는 `"select"` |
| `questions[].header` | ❌ | 카드 헤더 라벨 (생략 시 자동 인덱스) |
| `questions[].placeholder` | ❌ | freetext 전용 |
| `questions[].multiSelect` | ❌ | select 전용 (기본 false) |
| `questions[].options[]` | select 시 ✅ | `{label, description}` 객체 배열 |

### 동작 흐름

1. Claude 응답 본문에 v1 sentinel 쌍 마커 작성 + 응답 종료
2. Stop hook (`fpm-ask-marker-detect.sh`) 발동:
    - `.hub-mode-active` 플래그 없음 → 무동작
    - 플래그 있음 + BEGIN/END 매칭 → JSON 파싱·schema 검증 → server healthz/register → reason 주입 (`decision: "block"`)
3. Claude 다음 turn:
    - reason 의 지시대로 form HTML 작성 (각 카드: freetext/select 분기)
    - Write → `_doc_work/z_htm/hub_htm_<YYYYMMDD_HHMMSS>_c_<주제>.htm` (mode c=auto 폼)
    - Bash → `open -g -a Firefox`
    - 채팅 안내 + inbox polling
4. 사용자 폼 작성 → "전송" → server inbox → Claude 회수 → 흐름 재개

### 중복 트리거 방지

* 마커 처리 후 응답 본문에 sentinel 쌍 다시 작성 금지 (재트리거됨)
* `stop_hook_active: true` 시 hook 자체 skip
* 결과 보고 텍스트만 작성

### 실패 케이스

| 케이스 | 동작 |
| :--- | :--- |
| 마커 JSON syntax error | hook reason 에 에러 메시지·schema 안내 |
| schema 위반 (questions 누락 등) | hook reason 에 위반 필드 명시 |
| 서버 down (healthz ≠ 200) | hook reason 에 `/dashboard-server start` 또는 `..hub stop` 안내 |
| `.hub-mode-active` 없음 | hook 즉시 exit 0 |
| 단일 BEGIN 또는 단일 END 만 | 미매칭 (정규식 쌍 매칭 강제) → hook exit 0 |

### sentinel 노출 가이드 (Issue48)

응답 본문에 sentinel 토큰을 **코드 예시·문서 노출 목적**으로 적을 때:

* **권장**: `{BEGIN}` / `{END}` placeholder 표기 후 별도 줄에 실제 토큰 1회 명시 (본 문서 패턴)
* **대안**: sentinel 양옆을 가시 분리자 (zero-width space, `<...>` placeholder 등) 로 감싸 정규식 회피
* **금지**: 코드 펜스 내부에 sentinel 쌍 원문 그대로 노출 (hook 매칭됨)

본 문서·hook 헤더 주석 등 SSOT 자체에서 sentinel 노출이 불가피한 경우 응답 turn 이 아닌 file Write 인자에 적힘 → transcript text content 가 아니므로 hook 매칭 안 됨. 단 응답 텍스트 본문에는 노출 금지.

## 채팅 응답 표시 규칙 (Phase 8 / Issue40 / Issue60 — 채팅이 1차 채널)

> **Issue60 핵심 원칙**: Firefox 표시 실패(종료·hidden·미설치·SSE 끊김·다른 데스크톱·원격 SSH) 가능성을 항상 가정. **채팅 텍스트가 1차 채널**, 브라우저는 보조 채널. 채팅만 읽어도 결과 파악·재오픈 가능해야 함.

`..show` 처리(구 `..hub`) 후 사용자에게 보내는 **모든** 채팅 응답에는 **반드시 다음 세 요소를 포함**할 것:

1. **한 줄 헤드라인** — 이번 turn 에 무엇이 표시되었는지 (mode A/B, 본질 요지)
2. **내용 핵심 요약 (3줄 이내, Issue60 의무)** — 표·코드 dump 금지. caveman 압축된 핵심 사실 bullet 2~3개. Firefox 부재 가정 하에 채팅만으로 결과 파악 가능해야 함
3. **저장 경로 / stable URL — raw URL 형식 (Issue104)** — 형식: `📁 file://{abs_path}` (Mode A) / `🌐 http://{stable_url}` (Mode B/C). raw URL 그대로 노출 — 사용자가 클릭 시 즉시 브라우저 open (VSCode·IDE·iTerm 모두 file://·http:// 자동 링크화). 마크다운 링크 `[basename](url)` 형식 금지 (path 가시성 손실). bare 절대경로(`📁 /Users/...`) 단독 노출도 금지 (`file://` prefix 없으면 클릭 불가). Mode B/C stable URL 은 token 포함 전체 유지 (임의 제거 금지)

**사유 (Issue60)**: Firefox 표시 실패 패턴이 빈번함 — (a) 사용자가 다른 작업·창에 집중해 변화 인지 못 함, (b) Firefox 강제 종료·hidden·미설치, (c) 원격 SSH·다른 데스크톱·다른 모니터, (d) SSE 끊김. 채팅에 명시적 요약·경로/URL 이 있어야 (1) 무슨 일이 일어났는지 즉시 파악, (2) 창 닫혔으면 경로·URL 로 직접 재오픈, (3) GUI 단절 환경에서도 텍스트만으로 결과 도달.

**표시 형식 (단방향 응답, caveman 호환 권장 패턴)**:

```
HTML 저장. Firefox 열림.

- {핵심 사실 1}
- {핵심 사실 2}
- {핵심 사실 3 (선택)}

📁 file:///tmp/___pm/hub_htm_20260531_143022_a_topic.htm
```

ex)

```
부동산 5대 트렌드 표 렌더. Firefox 열림.

- 표 5행 + 다크모드 적용
- 헤더 색상 = 프로젝트 컬러
- 닫기 버튼 우측 상단

📁 file:///Users/.../proj/_doc_work/z_htm/hub_htm_20260531_143022_a_realestate.htm
```

### Q&A intercept 시 추가 fallback 의무 (Issue40)

AskUserQuestion intercept (form 자동 회수) 시점에는 위 3요소에 **다음 항목을 추가 의무로** 포함하여 Firefox 부재·실패 환경에서도 사용자가 채팅만으로 답할 수 있도록 함:

4. **질문 텍스트** — `question` 전체 (압축 금지)
5. **옵션 라벨 + 1줄 desc** — `options[].label : description` 형식
    * 옵션 ≤4 개: 모든 옵션을 bullet 로 나열
    * 옵션 5개 이상: 라벨만 압축 표기 (desc 생략)
6. **채팅 답변 방법 안내** — `"A/B/C/D 번호 입력 또는 자유 텍스트 paste 모두 가능"`

**표시 형식 (Q&A intercept fallback)**:

```
질문 폼 열림. "전송" 클릭 → 자동 회수 대기.

질문: {question 전체}

- A) {label1} : {desc 1줄}
- B) {label2} : {desc 1줄}
- C) {label3} : {desc 1줄}

📁 file:///Users/.../hub_htm_{YYYYMMDD_HHMMSS}_b_{주제}.htm

답변: Firefox 폼 사용. 브라우저 안 떠 있으면 채팅에 "A" / "B" / 자유 텍스트 입력해도 됨.
```

옵션 5+ 시:

```
질문 폼 열림. "전송" 클릭 → 자동 회수 대기.

질문: {question}

옵션: A) {label1} · B) {label2} · C) {label3} · D) {label4} · E) {label5} ...

📁 file://{abs_path}

답변: 폼 사용 또는 채팅에 라벨/번호 입력.
```

**사유**: Firefox 강제 종료, 다른 데스크톱, 원격 SSH 세션, 사용자가 브라우저 변화 미인지 등 GUI 단절 상황 빈번. 채팅 fallback 이 옵션 정보까지 포함해야 사용자가 답을 채팅에 직접 paste 하는 우회 동선 가능.

7. **Polling timeout 후 안내 (Issue61)** — `timeout 600` 회수 명령이 만료된 후에는 Claude turn 이 이미 종료. 이 시점에 사용자가 폼 "전송" 을 누르면 server inbox 에는 적재되지만 Claude 는 회수 불가 → silent loss. 타임아웃 만료를 채팅에 알릴 때 다음 양식을 함께 표시:

```
⚠️ 폼 '전송' 버튼은 더 이상 회수 안 됨 (Claude polling 10분 만료). 채팅에 JSON paste 부탁:

[{"question":"Q1 텍스트","answers":["선택값1"]}, {"question":"Q2 텍스트","answers":["선택값2"]}]

(간소화 허용: 'Q1: A, Q2: B' 자유 텍스트도 OK)
```

폼 자체 status 메시지에도 "전송 완료" 표시 후 작은 글씨로 동일 경고를 첨부하여 사용자가 늦은 전송이 회수되지 않을 수 있음을 인지시킴 (`hooks/fpm-ask-intercept.sh` submit handler).

## 사용

```
/show {요청 내용}
```

ex)
- `/show 2026년 부동산 시장 5대 트렌드를 표로 정리`
- `/show React useEffect와 useLayoutEffect 차이점 비교표`
- `/show Python asyncio 기본 패턴 코드 예제 모음`

(구 `/hub {요청}`·`..hub {요청}` 도 deprecated alias 로 동일 동작 — Issue133)

## 처리 절차

1. `$ARGUMENTS` 가 비어있으면 사용자에게 요청 확인 후 종료 (HTML 만들 내용 없음)
2. **본문 HTML 작성 여부 판단 (Issue62)**:
    - **Skip 조건 (본문 HTML 생략, 폼만 생성)**: 사용자 prompt 가 단발 질의/선택 요청이고, 응답 본문이 질문 재진술 외 trivial(설명·표·정답 spoiler 가 폼 답 선택을 무의미하게 만들 위험) 한 경우
        * ex) `..show 1+2 답 물어봐`, `..show A/B 골라줘`, `..show 이거 yes/no`
        * 본문 작성 생략 → 바로 `AskUserQuestion` 호출 → intercept hook 이 form HTML 단독 생성·open·polling
        * 채팅 fallback 도 폼 안내(질문·옵션·경로)만 표시
    - **본문 작성 조건 (기본, 본문+폼 2 파일)**: 응답이 정보 전달(설명·코드·표·비교·자료)을 포함하며, 폼은 그 뒤 결정 요청 분리에 쓰이는 경우
        * 응답 본문을 **완전한 HTML 문서**로 작성 (아래 step 4-7)
3. **HTML 본문은 caveman 압축 적용 제외** — 자연스러운 한국어 산문·완전한 문장·풍부한 설명 사용. caveman 은 채팅 응답에만 적용
4. HTML 템플릿 요구사항 (필수):
    - `<!DOCTYPE html>`, `<html lang="ko">`, `<meta charset="utf-8">`, viewport meta
    - **`<title>` 필수 prefix (Issue22)**: `"{프로젝트명} — <원래 제목>"` 형식 (브라우저 탭 구분)
    - 시스템 폰트: `-apple-system, BlinkMacSystemFont, "Apple SD Gothic Neo", "Noto Sans KR", sans-serif`
    - 본문 컨테이너: `max-width: 820px; margin: 0 auto; padding: 0 1.5rem 2rem 1.5rem`
    - `line-height: 1.7`, 표 `border-collapse: collapse` + 헤더 배경, 코드블록 배경+패딩, 인용구 좌측 보더
    - **흰색 배경 고정 (Issue58)**: `--bg: #ffffff`, `--fg: #1a1a1a` 고정 사용. `@media (prefers-color-scheme: dark)` override **금지** — OS 다크모드와 무관하게 항상 흰 배경으로 렌더링 (다중 탭 일관성)
    - 표/리스트/코드블록/헤더 계층 적극 활용
    - **다이어그램 런타임 (Issue82)**: 프로세스·인과·구조 내용을 mermaid 다이어그램으로 렌더하기 위해 `<head>` 에 CDN + init 1회 삽입. 상세 규칙·매핑은 아래 "다이어그램 우선 렌더" 섹션 참조
        ```html
        <script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>
        <script>mermaid.initialize({ startOnLoad: true, theme: 'neutral' });</script>
        ```
        * `.mermaid` 블록 CSS: `margin: 1.5rem auto; text-align: center` — max-width 820px 컨테이너 내 중앙 정렬
        * `theme: 'neutral'` 고정 — Issue58 흰 배경 정책 호환 (다크 테마 금지)
    - **프로젝트 식별 헤더 + 닫기 버튼 (Issue22, Issue58 컬러 정책 갱신)**:
        * 최상단 `<header>` 배경에 PROJECT_COLOR 적용. PROJECT_COLOR 결정 규칙 (Issue58):
            1. `~/_git/___pm/Projects.md` 의 `📋 프로젝트` 테이블에서 현재 `cwd` 와 일치하는 행 찾기 (경로 컬럼: `~` 확장 후 비교)
            2. 일치 행의 `peacock.color` 컬럼 hex 값 사용 (ex: `#f0d5cc` for `~/.claude`)
            3. 일치 행이 없으면 fallback `hsl(hue, 60%, 45%)` (hue = cwd md5 hash 앞 4자 % 360)
        * peacock.color 는 파스텔 톤이므로 헤더 텍스트 색은 `#1a1a1a` (어두운 글자) 사용. 닫기 버튼도 `background: rgba(0,0,0,0.08); color: #1a1a1a; border: 1px solid rgba(0,0,0,0.15)` 등 어두운 글자 대비로 설정
        * **⚠️ CANONICAL 헤더 블록 (Issue132) — 아래 HTML·CSS 를 verbatim 복붙하고 placeholder 2개만 치환**. 즉흥 재작성 금지 (정적 `<span>`·순서 뒤바뀜·헤더 밖 overflow 재발 원인). 치환: `{프로젝트명}`(ex `.claude`) · `{cwd 절대경로}`(ex `$HOME/.claude`, Projects.md 등록 경로와 정확히 일치해야 서버 화이트리스트 통과) · `{session_id}`(🎯 세션 버튼 — 현재 세션 ID. hook 경유 시 자동 임베드, 수동 작성 시 hook 입력 `session_id`. 부재 시 cwd_hash fallback → 워크스페이스만 open). `{제목}` 만 콘텐츠별로 채움. 색은 아래 `:root --project-color` (위 PROJECT_COLOR 규칙) 가 결정.
            ```html
            <header>
              <h1>{제목}</h1>
              <nav class="header-actions">
                <a class="proj-badge" href="#" title="클릭 → VSCode 로 {프로젝트명} 열기"
                   onclick="event.preventDefault();fetch('http://127.0.0.1:9876/open-project',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cwd:'{cwd 절대경로}'})}).then(function(r){return r.json();}).then(function(j){if(j&&j.error)alert('VSCode 열기 실패: '+j.error);}).catch(function(){alert('hub 서버 미응답 — VSCode 열기 실패');});">📁 {프로젝트명}</a>
                <a class="sess-link" href="#" title="클릭 → 이 문서를 만든 세션 탭으로 포커스"
                   onclick="event.preventDefault();fetch('http://127.0.0.1:9876/open-session',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cwd:'{cwd 절대경로}',sid:'{session_id}'})}).then(function(r){return r.json();}).then(function(j){if(j&&j.error)alert('세션 열기 실패: '+j.error);}).catch(function(){alert('hub 서버 미응답 — 세션 열기 실패');});">🎯 세션</a>
                <a class="hub-link" href="http://127.0.0.1:9876/hub" target="_blank">🗂 Hub</a>
                <button type="button" onclick="window.close()">닫기 ✕</button>
              </nav>
            </header>
            ```
            ```css
            header {
              position: sticky; top: 0; z-index: 100;
              display: flex; align-items: center; justify-content: space-between;
              gap: 1rem; flex-wrap: wrap;        /* 좁은 폭: 헤더 밖 overflow 대신 줄바꿈 */
              padding: 0.9rem 1.4rem;
              background: var(--project-color);   /* 불투명 필수 — sticky 시 본문 비침 방지 */
              color: #1a1a1a;                     /* peacock 파스텔 → 어두운 글자 (Issue58) */
            }
            header h1 { margin: 0; font-size: 1.15rem; flex: 1 1 auto; min-width: 0; }
            header .header-actions {
              display: flex; align-items: center; gap: 0.5rem; flex: 0 0 auto;
            }
            header .proj-badge, header .sess-link, header .hub-link, header button {
              color: #1a1a1a; text-decoration: none; cursor: pointer; white-space: nowrap;
              background: rgba(0,0,0,0.08); border: 1px solid rgba(0,0,0,0.15);
              padding: 0.2rem 0.6rem; border-radius: 6px; font-size: 0.85rem;
            }
            header .proj-badge:hover, header .sess-link:hover, header .hub-link:hover, header button:hover {
              background: rgba(0,0,0,0.16); text-decoration: underline;
            }
            ```
            * **블록 불변식 (재발 차단)**: (1) 배지 = `<a class="proj-badge" onclick=...POST /open-project...>` — 정적 `<span>` 금지(Issue103, 클릭 시 VSCode 프로젝트 열기). 세션 = `<a class="sess-link" onclick=...POST /open-session {cwd,sid}...>`(Issue137, 클릭 시 이 문서를 만든 세션 탭 포커스 — `sid` 미치환 시 워크스페이스만 graceful degrade). (2) 순서 = `📁 배지` → `🎯 세션` → `🗂 Hub` → `닫기 ✕`. (3) 배지·세션·Hub·닫기 넷 모두 `<header>` 바 **안** `.header-actions` 동일 행 — 헤더 **밖** `.proj-name` div 금지(Issue88, sticky 단일 블록 고정). (4) `display:flex; justify-content:space-between` + `flex-wrap` → 우측 overflow 방지. (5) `<header>` 자체가 `position:sticky; top:0`(Issue74).
            * **sticky 무효화 방지**: 조상 요소(`html`, `body`, 본문 컨테이너)에 `overflow: hidden` / `overflow: clip` 금지 — sticky 컨텍스트를 깨뜨려 헤더가 다시 스크롤됨.
            * 서버가 `Access-Control-Allow-Origin: null` 을 보내므로 file://(origin null) htm 에서도 fetch 허용. 성공 시 무음(VSCode 가시적 open), 실패(서버 미가동·비등록 경로) 시 `alert` fail-loud. endpoint = `/hub` 활성 세션 카드와 동일(Issue101/Issue42).
    - **컬러 영역 자식 인라인 요소 contrast (Issue16_4, Issue58 갱신)**:
        * 컬러 배경 컨테이너(`header`, `.callout`, `.info-box`, `.note-box`, `.warn-box`, `.tip-box` 등)는 자식 인라인 요소의 `color`를 **반드시 명시**해야 함. peacock.color 가 파스텔 톤이므로 헤더 글자색은 어두운 톤(`#1a1a1a`) 기본 사용, 진한 컬러 배경 박스(callout 등)는 기존 흰 글자 패턴 유지
        * 사유: `<code>` 는 자체 배경(`var(--code-bg)` ≈ 흰색)을 갖지만 `color` 는 상속 → 부모 흰색 상속 시 **흰 배경 + 흰 글자 invisible 버그** (selection 시에만 보임)
        * 권장 패턴 (callout/info-box 모든 변종에 동일 적용):
            ```css
            .callout code, .info-box code, .note-box code, .warn-box code, .tip-box code,
            header code {
              color: var(--fg);
              background: rgba(255,255,255,0.92);
              padding: 0.05rem 0.35rem;
              border-radius: 3px;
            }
            .callout a, .info-box a, .note-box a, .warn-box a, .tip-box a,
            header a {
              color: #fff;
              text-decoration: underline;
            }
            .callout strong, .info-box strong, .note-box strong, .warn-box strong, .tip-box strong,
            header strong {
              color: #fff;
            }
            .callout em, .info-box em, .note-box em, .warn-box em, .tip-box em,
            header em {
              color: rgba(255,255,255,0.9);
            }
            ```
        * 자가 검증: 컬러 배경 박스 추가 시 자식 `code`/`a`/`strong`/`em` 색 명시 누락 여부 확인
5. Write 도구로 `{OUT_DIR}/hub_htm_{YYYYMMDD_HHMMSS}_a_{주제}.htm` 저장 (날짜시간=`date +%Y%m%d_%H%M%S`, 주제=핵심 10자 내외 kebab, mode a=메인 렌더) — `OUT_DIR` 은 `_doc_work/z_htm/` 존재 시 그 경로, 아니면 `/tmp/___pm` (Issue64 — `/tmp` 평면 흩어짐 방지)
6. Bash 로 Firefox 표시 (**Firefox 강제, Chrome 금지**):
   ```bash
   open -g -a "Firefox" "file://<절대경로>"
   ```
   - **브라우저·포커스는 `~/_git/___pm/data/hub_setting.yml` 의 `default_browser`·`browser_focus` 가 결정 (Issue130)** — hook 이 grep 하여 실제 명령을 주입. 위는 기본값(`default_browser: firefox`, `browser_focus: false`) 예시
   - `default_browser`: firefox(기본)/chrome/edge/safari 또는 .app 절대 경로. 매핑 — firefox→`Firefox`, chrome→`Google Chrome`, edge→`Microsoft Edge`, safari→`Safari`
   - **`-a "<브라우저>"` 명시 필수**. `open "file://..."` 단독 호출 금지 — macOS 기본 브라우저로 폴백되어 설정 무시됨
   - **`-g` 플래그 (Issue128)**: `browser_focus: false`(기본) 시 백그라운드 open — **포커스 탈취 안 함**. 다른 앱 입력 중 hub 렌더가 끼어들어 입력이 끊기는 문제 방지. `true` 면 `-g` 제거(foreground)
   - `xdg-open`, `python -m webbrowser` 등 우회 호출 금지 (설정 무시)
   - `open -g -a "<브라우저>"` 는 기존 인스턴스 재사용 + 새 탭 추가 (포커스는 현재 앱 유지)
   - 운영 모델: Chrome=일반 / Firefox=hub·dashboard 전용 분리가 기본 권장 (사용자 설정 SSOT — `_doc_arch/hub-mode-arch.md`)
   - Firefox 미설치 환경에서만 예외 — 이 경우 사용자에게 보고 후 대안 합의
7. **hub registry 등록 (Issue69)** — 본문 HTML 을 ___pm htm-server hub 에 등록 (___pm Issue41 로 hub 가 디렉토리 스캔을 폐기 → 생산자 등록 필수):
   ```bash
   curl -s --max-time 3 -X POST http://127.0.0.1:9876/register-doc \
     -H 'Content-Type: application/json' \
     -d '{"type":"htm","path":"<본문 HTML 절대경로>","cwd":"<프로젝트 루트 절대경로>","title":"<HTML title>"}' >/dev/null 2>&1 || true
   ```
   - `path` = step 5 에서 Write 한 절대경로, `cwd` = 프로젝트 루트(`cwd`), `title` = `<title>` 태그 값
   - 서버 미가동 시 curl 실패 → 무시 (**fail-soft** — hub 본 기능 차단 금지). 등록 누락분은 hub `🔄 디스크 재스캔` 버튼으로 수거 가능
   - 등록 대상은 본문 HTML(mode a) + B모드 질문 폼(mode b, `hub_htm_*_b_*.htm`, Issue80). Mode D 폼(mode c, `hub_htm_*_c_*.htm`)만 transient 산출물이므로 등록 제외
   - 엔드포인트 SSOT: `~/_git/___pm/_doc_arch/hub_htm.md` `POST /register-doc` 섹션
   - **Issue73/Issue80**: PostToolUse hook `~/.claude/hooks/fpm-hub-doc-register.sh` 가 `*/_doc_work/z_htm/hub_htm_*_*.htm`(`_c_` auto 제외) Write 시 동일 등록을 자동 수행. 본 step 의 수동 curl 은 hook 미작동 환경(서버 down·hook 미설치) 대비 fallback. 중복 등록은 server 측 동일 path dedup 처리
8. 채팅 응답(caveman 형식)에는 한 줄 헤드라인 + 핵심 bullet 2~3개 + 저장 경로 표기 (위 "채팅 응답 표시 규칙" 참조)

## 다이어그램 우선 렌더 (Issue82)

HTML 본문 작성 시 **프로세스·인과관계·구조** 성격의 내용은 긴 산문·중첩 리스트 대신 mermaid 다이어그램으로 렌더한다. 시각화가 가독성을 높이는 부분을 적극 다이어그램화하여 텍스트로 길게 늘어지는 것을 막는다.

### 적용 원칙

* 본문 작성 중 한 덩어리의 내용이 **순서·흐름·관계·계층**을 담고 있으면 먼저 "다이어그램으로 표현 가능한가" 를 판단
* 가능하면 mermaid 다이어그램을 1차 표현으로 사용. 다이어그램만으로 불명확한 부분만 1~2문장 보조 설명 병기
* 다이어그램화가 부적합한 내용(아래 제외표)은 기존대로 표·리스트·산문 유지
* 채팅 응답(caveman)에는 다이어그램 미적용 — HTML 본문 전용

### 다이어그램 본문 작성

mermaid 런타임은 step 4 에서 `<head>` 에 삽입됨. 다이어그램은 `<pre class="mermaid">` 안에 mermaid 문법 그대로 작성:

```html
<pre class="mermaid">
flowchart TD
    A[요청 수신] --> B{hub 모드 활성?}
    B -->|예| C[HTML 본문 작성]
    B -->|아니오| D[평소 응답]
    C --> E[Firefox open]
</pre>
```

* CDN 로드 실패(오프라인) 시 mermaid 문법 원문이 `<pre>` 로 노출 → graceful degradation, 핵심 정보 손실 없음

### 콘텐츠 유형 → 다이어그램 매핑

| 콘텐츠 유형              | 판정 신호                          | mermaid 다이어그램                       |
| :----------------------- | :--------------------------------- | :--------------------------------------- |
| 프로세스·절차·워크플로우 | 단계 순서, "먼저~ 다음~ 마지막~"   | `flowchart TD` / `sequenceDiagram`       |
| 인과관계·의존성·영향     | "A 때문에 B", "A→B 유발", 선후관계 | `flowchart LR` (화살표 = 인과)           |
| 구조·구성·계층·분류      | 부분-전체, 트리, 카테고리          | `flowchart` / `classDiagram` / `mindmap` |
| 상태 전이                | 상태 A→B 전환 + 전환 조건          | `stateDiagram-v2`                        |
| 시간순·이력·로드맵       | 날짜·버전별 사건 나열              | `timeline` / `gitGraph`                  |
| 엔티티 관계·데이터 모델  | 1:N, 테이블 간 관계                | `erDiagram`                              |
| 시스템 상호작용          | 컴포넌트 간 메시지·호출 흐름       | `sequenceDiagram`                        |

### 다이어그램화 제외 (텍스트·표 유지)

| 케이스                       | 사유                              |
| :--------------------------- | :-------------------------------- |
| 단순 비교·속성 나열          | 표가 더 명확                      |
| 코드·로그·명령 출력          | 다이어그램 부적합                 |
| 서술형 설명·정의·배경        | 산문이 적합                       |
| 노드 15개 초과 복잡 그래프   | 가독성 저하 → 분할 또는 표로 대체  |
| 순서·관계 없는 평면 목록     | bullet 유지                       |

### 작성 규칙

* mermaid 문법·다이어그램 유형 선택 기준은 [`~/.claude/skills/mermaid-diagram/mermaid-rules.md`](../skills/mermaid-diagram/mermaid-rules.md) 참조
* 노드 라벨 한국어 허용. 특수문자(`()`, `[]`, `:`, `"` 등) 포함 시 라벨을 `"..."` 로 감쌈
* 다이어그램 1개당 노드 **3~12개 권장**. 초과 시 다이어그램을 의미 단위로 분할
* 한 본문에 다이어그램 여러 개 허용 — 프로세스 1개 + 구조 1개 식으로 섹션별 배치

## 레포트 패턴 (Issue92)

**다항목 비교·카탈로그성 응답**(여러 항목·옵션·산출물을 나란히 설명하는 응답)은 본문 구조를 자유 산문에 맡기지 말고 아래 4단 골격으로 작성한다. 매 응답 구조가 달라져 생기는 품질 편차를 막고, 읽는 사람이 요약 → 상세 → 재현 순으로 빠르게 훑을 수 있게 한다.

### 적용 대상

* **적용**: 여러 항목·도구·옵션·산출물을 비교하거나 나열하는 카탈로그성 응답 (ex: 스킬 목록 설명, 다중 파일 변경 보고, 옵션 비교, 렌더 결과 모음)
* **미적용**: 단발 단순 응답. trivial skip·mermaid 우선·자유 산문 규칙은 그대로 유지. 단일 주제 서술이면 4단 골격을 강제하지 않음

### 4단 골격

1. **도입 단락** — 무엇을 다루는 레포트인지 1~2문장으로 명시하고, 핵심 입력(명령·요청·소스)을 짧은 예시로 보여준다.
2. **항목 요약 표** — 다루는 항목 전체를 한 표로 압축한다. 열은 `항목명 · 용도 · 속성` 기본 구성. 상태·분류는 배지(`<span class="badge">`)로 표기 가능.
3. **항목별 섹션** — 각 항목을 `<h2>` 제목으로 연다. 항목마다 입력 코드블록(`<pre>`)과, 결과를 보여줄 `<figure>`(캡처·도해 이미지 + `<figcaption>` 한 줄 설명)를 배치한다. 이미지가 없으면 `<figure>` 는 생략하되 코드블록은 유지한다.
4. **"확인 방법" 블록** — 본문 끝에 `<blockquote>` 로 재현 명령·산출물 경로·재사용 방법을 모은다. 읽는 사람이 레포트 내용을 직접 확인·재현할 수 있는 단서를 제공한다.

### 골격 예시 (HTML)

```html
<p>3개 캡처 스킬의 출력 형식을 비교한다. 입력 예: <code>/capture-m</code>, <code>/capture-w</code>.</p>

<table>
  <thead><tr><th>항목</th><th>용도</th><th>속성</th></tr></thead>
  <tbody>
    <tr><td>capture-m</td><td>macOS 앱 UI 캡처</td><td><span class="badge">screencapture -l</span></td></tr>
    <!-- ... -->
  </tbody>
</table>

<h2>capture-m</h2>
<pre>/capture-m --window MainWindow</pre>
<figure>
  <img src="..." alt="capture-m 산출물">
  <figcaption>MainWindow 단일 윈도우 캡처 결과</figcaption>
</figure>

<blockquote>
  <strong>확인 방법</strong><br>
  재현: <code>/capture-m --window MainWindow</code><br>
  산출물: <code>_doc_work/z_capture/*.png</code>
</blockquote>
```

* 표·코드블록·figure·blockquote 는 step 4 의 기존 스타일 토대를 그대로 사용. 레포트 패턴은 본문 *구조*만 규정하며 스타일·헤더·다크 정책을 바꾸지 않는다.
* 다이어그램 우선 렌더 규칙과 병행 — 항목별 섹션 안에서 프로세스·구조 성격 내용은 mermaid 로 렌더해도 된다.

## Caveman 모드 상호작용

- HTML 본문 = 코드/문서 컨텐츠로 취급. caveman 압축 규칙 "Code blocks unchanged" 적용
- 채팅 응답(보고)은 caveman 유지: `HTML 저장. Firefox 열림.` + 요약 bullet
- caveman OFF 상태면 채팅도 일반 문체

## Mode C: Live Dashboard — 별도 agent 로 분리됨

Mode C(Live Dashboard) 본문은 dashboard agent 로 분리됨. 본 커맨드(`/hub`) 는 HTML 응답 + form 자동 회수 Q&A 만 담당.

| 호출                  | 처리 SCAR                                                            |
| :-------------------- | :------------------------------------------------------------------- |
| `..board <topic>` (Issue126) | `fpm-hub-trigger.sh` UserPromptSubmit hook 이 자동 dashboard agent 호출 (c모드 단일 단어 트리거) |
| `..hub dash <topic>` / `..dashboard <topic>` | 하위호환 별칭 (Issue41) — deprecation 예정                  |
| `/dashboard <topic>`  | 명시적 wrapper 커맨드 (`~/.claude/commands/fpm-dashboard.md`)             |

dashboard agent 본문 SSOT: [`~/.claude/agents/fpm-dashboard.md`](../agents/fpm-dashboard.md)
dashboard 서버 lifecycle wrapper: [`~/.claude/commands/fpm-dashboard-server.md`](fpm-dashboard-server.md)

서버 (`htm-server` daemon, ___pm 소유) 는 dashboard agent 단독 클라이언트. hub 스킬 (본 커맨드) 은 서버 미사용.

## 트리거 비교

### 3모드 단일 단어 트리거 (Issue126)

| 모드 | 트리거          | 역할                          | 처리 hook/SCAR                          |
| :--- | :-------------- | :---------------------------- | :-------------------------------------- |
| a    | `..show` / `/show` (구 `..hub`/`/hub` deprecated, Issue133) | 단방향 HTML 렌더 | `fpm-hub-trigger.sh` → 본문 HTML            |
| b    | `..ask <주제>`  | 양방향 Q&A 폼 ("나에게 물어봐") | `fpm-hub-trigger.sh` (플래그 touch) → `AskUserQuestion` → `fpm-ask-intercept.sh` form 자동 회수 |
| c    | `..board <topic>` | dashboard agent (실시간 모니터링) | `fpm-hub-trigger.sh` → dashboard agent dispatch |

* **b모드 `..ask`**: 플래그를 touch 한 뒤 Claude 가 `AskUserQuestion` 을 호출하면 intercept hook 이 동일 form 회수 경로로 처리. `..ask` 트리거 없이 자동 모드 중 `AskUserQuestion` 만으로도 진입 가능 (트리거는 명시 진입점).
* **c모드 `..board`**: 별칭 `..hub dash` / `..dashboard` / `/dashboard` 하위호환 유지 (deprecation 예정 — 즉시 제거 금지).
* **토글은 모드 무관 hub 단위 공유**: `..hub stop`/`start` (프로젝트), `..hub off`/`on` (시스템). `..ask`/`..board` 독립 토글 없음.

### 활성화·안정성

| 방식       | 활성화           | 안정성             |
| :--------- | :--------------- | :----------------- |
| `/show`   | 명시적 슬래시    | 높음 (의도 명확)   |
| `..show`  | 프롬프트 내 마커 | UserPromptSubmit hook 이 지시 주입 (구 `..hub` deprecated) |
| `..ask`   | 프롬프트 내 마커 | b모드 명시 진입 — intercept form 회수 |
| `..board` | 프롬프트 내 마커 | c모드 명시 진입 — dashboard agent     |

## 양방향 Q&A (form 자동 회수) — Issue45

`..show` 트리거(구 `..hub`)가 발동되면 `~/.claude/.hub-mode-active` 플래그 파일이 생성되어 양방향 모드 활성. 후속 `AskUserQuestion` 호출은 `fpm-ask-intercept.sh` (PreToolUse hook) 가 가로채 form HTML 생성 + ___pm htm-server inbox 자동 회수 지시를 주입.

### 동작 원리

1. **단방향 응답**: 첫 응답 본문은 위 절차대로 HTML 문서로 렌더링
2. **AskUserQuestion 가로채기**: intercept hook 이 healthz + `/register` 판정 → **deny + form 자동 회수 지시 주입**
3. **Form HTML 생성**: deny reason 에 포함된 질문 JSON + answer_url + cwd_hash 로 Claude 가 form HTML 생성·저장·Firefox open
4. **자동 회수**: 사용자 폼 작성 → "전송" 버튼 → JS fetch POST → server inbox → Claude bash polling → 답변 파일 Read → answers 추출 → 흐름 재개
5. **서버 실패 시**: deny + fail-loud 안내 (`/dashboard-server start` 후 재시도 또는 `..hub stop`). paste-back fallback 없음 (Issue45 제거)
6. **해제**: `..hub stop` 또는 `..hub off` 입력 시 플래그 삭제, AskUserQuestion 정상 복귀

### 선택지 자동 승격 (Issue16_3) — form 자동 전환

**원칙**: hub 모드(`..show`) 활성 상태에서 사용자에게 객관식 선택지를 제시하여 결정 입력을 받아야 하는 경우, 텍스트 bullet 리스트 dump 대신 **반드시 `AskUserQuestion` 도구를 호출**한다. intercept hook 이 자동으로 form 으로 분기하여 Firefox 폼 표시 + 서버 자동 회수까지 무인 진행.

#### 트리거 (3 조건 모두 충족 시 발동)

| # | 조건 | 판정 신호 |
| :-: | :--- | :--- |
| 1 | hub 모드 활성 | `~/.claude/.hub-mode-active` 존재 (intercept hook 이 자동 감지) |
| 2 | 응답이 N개 선택지 제시 | 번호 매긴 옵션 리스트 (`1.`/`2.`/`3.` 또는 `A.`/`B.`/`C.` 또는 `- 옵션 1` `- 옵션 2`) — 2~4개 |
| 3 | 결정 요청 문구 포함 | "선택해줘", "어느 옵션", "y/N", "번호로 답해", "선택하세요", "골라줘", "어떤 방식", "어느 쪽", "Yes/No" 등 사용자 결정 요청 표현 |

#### 매핑 규칙

응답 본문에 옵션 리스트가 자연스럽게 들어가는 경우라도, **결정 요청은 별도로 `AskUserQuestion` 호출**로 분리한다:

| 응답 본문 | 도구 호출 |
| :--- | :--- |
| 옵션 설명·비교표·trade-off 요약 (HTML) | `AskUserQuestion` 은 question + 옵션 label 만 (압축) |
| 단일 선택 (radio) | `multiSelect: false` |
| 다중 선택 가능 (체크박스) | `multiSelect: true` |
| 각 옵션의 설명 | `options[].description` 에 1~2문장 |
| 권장안 명시 | 권장 옵션을 `options[0]` + label 끝에 `(권장)` |

#### 호출 예시

```python
AskUserQuestion(questions=[{
  "question": "다음 어떤 방식으로 처리할까?",
  "header": "처리 방식",
  "multiSelect": False,
  "options": [
    {"label": "옵션 A (권장)", "description": "장점·trade-off 1문장"},
    {"label": "옵션 B",       "description": "장점·trade-off 1문장"},
    {"label": "옵션 C",       "description": "장점·trade-off 1문장"}
  ]
}])
```

intercept hook 이 deny + form 자동 회수 reason 주입 → Claude 가 form HTML 생성·Firefox open → 사용자 폼 작성·전송 → server inbox → Claude bash polling → 흐름 재개.

#### 예외 (트리거 미발동, 텍스트 응답 그대로 유지)

| 케이스 | 사유 |
| :--- | :--- |
| 단순 비교표·후보 나열 (결정 요청 없음) | 사용자가 정보만 원함 |
| 정보성 답변 (질문 답변, 설명, 가이드) | 결정 요구 없음 |
| 코드 출력·진단 결과·로그 dump | 선택지 아님 |
| 옵션 5개 이상 | AskUserQuestion 최대 4 options 한계 — 텍스트로 dump 후 사용자 자유 응답 |
| 단순 confirm (변경 적용 yes/no) | AskUserQuestion 2 options 로 정형화 권장 (예외 아님 — 발동 권장) |

#### 비-hub 모드

hub 모드 미활성(`.hub-mode-active` 없음) → 본 규칙 적용 안 함. AskUserQuestion 호출은 평소대로 채팅 UI 에 표시.

### Form HTML 템플릿 요구사항

기본 HTML 템플릿(시스템 폰트·다크모드·max-width 820px) 위에 form 컨트롤 + fetch POST 추가. 폼 JS 는 SSOT `~/.claude/hooks/fpm-ask-form-template.js` 단일 출처 (Issue68) — intercept hook 이 `{ANSWER_URL}` 치환 완료본을 reason 에 인라인 주입함.

```html
<form id="qa-form">
  <fieldset class="q-card" data-question="질문 텍스트">
    <legend>질문 텍스트</legend>
    <!-- multiSelect: false → radio, true → checkbox -->
    <label><input type="radio" name="q1" value="옵션A"> 옵션A</label>
    <label><input type="radio" name="q1" value="옵션B"> 옵션B</label>
    <label>기타: <input type="text" class="q-other" placeholder="직접 입력"></label>
  </fieldset>
  <!-- 추가 fieldset 반복 -->
  <div class="btn-row">
    <button type="button" id="submit-btn">전송</button>
    <button type="button" id="submit-close-btn">전송 후 닫기</button>
    <button type="button" id="submit-session-btn">전송 후 해당 세션으로</button>
    <button type="button" onclick="window.close()">닫기 ✕</button>
  </div>
  <div id="status"></div>
</form>

<script>
/* JS 템플릿 SSOT (Issue68): ~/.claude/hooks/fpm-ask-form-template.js
   - hub 모드 활성 시: ask-intercept hook 이 reason 에 `{ANSWER_URL}` 치환 완료본 JS 를
     직접 주입함 → hook 이 준 JS 를 그대로 이 위치에 삽입 (htm.md 별도 참조 불필요).
   - hook 미경유로 직접 폼을 작성하는 경우: 위 SSOT 파일을 Read 하여 `{ANSWER_URL}` 를
     실제 answer 엔드포인트(`http://127.0.0.1:9876/answer?cwd=<enc>&token=<token>`)로,
     `{OPEN_PROJECT_URL}` 를 `http://127.0.0.1:9876/open-project` 로,
     `{PROJECT_CWD_JSON}` 를 cwd 의 JSON 문자열(따옴표 포함)로 치환 후 이 위치에 삽입 (Issue132 — 전송 후 해당 세션으로 버튼).
   collectAnswers/submitAnswers/이벤트 바인딩은 SSOT 파일이 단일 출처 — 여기 인라인 복제 금지. */
</script>
```

### 활성 조건 (Issue45)

1. `..show` 트리거 또는 `/show` 발동 (모드 플래그 set; 구 `..hub`/`/hub` deprecated alias)
2. `curl http://127.0.0.1:9876/healthz` → 200
3. `POST /register?cwd=<abs>` → token + cwd_hash 회수 성공

조건 1+2+3 모두 만족 시 form 자동 회수 분기. 2 또는 3 실패 시 intercept hook 이 fail-loud reason 주입 (사용자가 서버 시작 또는 모드 해제 선택).

### 동작 흐름

```
사용자: "..show <요청>"   (구 "..hub <요청>" deprecated alias)
   ↓
[Claude] 본문 HTML 작성 → file:// Firefox open
   ↓
[Claude] AskUserQuestion 도구 호출
   ↓
[intercept hook] healthz 200 + /register 성공 → form 자동 회수 지시 주입
                 healthz 실패         → fail-loud 안내 + 사용자 선택 대기
   ↓
[Claude] form HTML 생성 (전송 버튼) → file:// Firefox open
   ↓
[사용자] 폼 작성 → "전송" 클릭 → JS fetch POST
   ↓
[Server] /answer 받음 → /tmp/___pm/claude-htm-inbox/{cwd_hash}/{sid}/{ts}.json 저장 (Issue90 sid 격리)
   ↓
[Claude] bash polling (sid 서브폴더 우선 + flat fallback) → json 발견 → Read → 파싱 → rm → 흐름 재개
```

### 파일 경로 규칙 (Issue21)

- 응답 본문 HTML (mode a): `{OUT_DIR}/hub_htm_{YYYYMMDD_HHMMSS}_a_{주제}.htm`
- 질문 폼 HTML (mode b): `{OUT_DIR}/hub_htm_{YYYYMMDD_HHMMSS}_b_{주제}.htm`
- auto 폼 HTML (mode c, Mode D): `{OUT_DIR}/hub_htm_{YYYYMMDD_HHMMSS}_c_{주제}.htm`
- 날짜시간=`date +%Y%m%d_%H%M%S`, 주제=핵심 10자 내외 kebab-case (공백·특수문자 `-` 치환)
- `OUT_DIR` 결정: `cwd/_doc_work/z_htm/` 존재 시 거기, 없으면 `/tmp/___pm` (Issue64 — `/tmp` 평면 흩어짐 방지. hook 이 자동 판정 후 reason 에 주입)

### CORS / 보안

* file:// → http://127.0.0.1:9876 fetch POST: 서버가 `Access-Control-Allow-Origin: null` 응답 (file:// origin 허용)
* UUID 토큰 query param 필수 검증 (누락·불일치 401)
* 토큰 파일 mode 0600
* 요청 크기 1MB 제한
* 127.0.0.1 바인딩 (외부 접근 차단)

### 관련 산출물

- `~/.claude/hooks/fpm-hub-trigger.sh` (UserPromptSubmit, `..show` 감지[구 `..hub` deprecated] + 플래그 touch + 본문 HTML 지시 주입)
- `~/.claude/hooks/fpm-ask-intercept.sh` (PreToolUse matcher=AskUserQuestion, healthz 판정 + form 자동 회수 지시 또는 fail-loud)
- `~/.claude/.hub-mode-active` (플래그 파일, 빈 파일이면 활성)
- `${CLAUDE_PLUGIN_ROOT}/services/hub/server.py` — `/healthz`, `/register`, `/answer` endpoint (플러그인 번들, `/dashboard-server` 가 lifecycle 관리)
- `/tmp/___pm/claude-htm-inbox/{cwd_hash}/{sid}/{ts}.json` — 답변 파일 (Issue90 sid 서브폴더 세션 격리, Claude Read 후 삭제)
- `/dashboard-server start|stop|status|restart` — 서버 lifecycle wrapper

## 분리 이력

* Issue18 (2026-05-17): Mode A paste-back 초기 구현
* Issue19 (2026-05-17): Mode B 로컬 서버 자동 회수 추가
* Issue27/28 (2026-05-18): Stable URL POST 모델로 Mode A/B 통합
* Issue36 (2026-05-19): Mode C(dashboard) 별도 스킬·커맨드로 분리
* Issue37 (2026-05-19): hub 스킬 ___pm 서버 **필수** 의존 제거. Mode A only 로 단순화
* Issue38 (2026-05-19): Mode B 자동 회수 부활 (dashboard-server 옵셔널 공유 클라이언트). 서버 미실행 시 Mode A fallback 보장
* **Issue45 (2026-05-19, 본 변경)**: ___pm 프로젝트가 htm-server 상시 운영을 책임지는 환경 전제 → Mode A paste-back fallback 제거. form 자동 회수 단일 경로 + 서버 down 시 fail-loud 안내로 단순화
* **Issue58 (2026-05-19)**: hub/dashboard 배경 흰색 고정. `@media (prefers-color-scheme: dark)` override 금지. 프로젝트 헤더 컬러는 `~/_git/___pm/Projects.md` `peacock.color` 컬럼 참조 (cwd 경로 매칭, fallback `hsl(hue, 60%, 45%)`)
