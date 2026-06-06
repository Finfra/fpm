---
name: README
description: htm-server hub registry 저장소 (Issue41)
date: 2026-05-20
---

# 용도

htm-server (`services/htm-server/server.py`) 의 hub 목록 SSOT. hub 는 이 폴더의 registry 파일에 등록된 항목만 노출하며, 다른 프로젝트 디렉토리를 스캔하지 않는다 (Issue41).

# 파일

| 파일                  | 내용                                                       |
| :-------------------- | :--------------------------------------------------------- |
| `htm-registry.json`   | htm 스킬 단발 출력(`claude-htm-*.html`) 등록 목록          |
| `dash-registry.json`  | dashboard 산출물(`*.dash.{json,yaml,yml}`) 등록 목록       |
| `hook-feed.json`      | hook 활동 피드 버퍼 영속본 (Issue42, newest-first, deque)  |

전 파일 gitignore (`data/hub/*.json`) — 런타임 상태. hub 설정 SSOT 는 git 추적되는 `data/hub_setting.yml`.

# 항목 스키마

registry (`{htm,dash}-registry.json`):

```json
{ "path": "<abs>", "cwd": "<abs|''>", "title": "...", "registered_at": 1779262223.0 }
```

활동 피드 (`hook-feed.json`, Issue42):

```json
{ "event": "Stop", "cwd": "<abs>", "cwd_hash": "abc12345", "name": "...", "color": "#ffffdd",
  "emoji": "🗓️🎯", "summary": "...", "detail": "...", "ts": 1779262223, "id": "1779262223000" }
```

# 갱신 주체

* `POST /register-doc` — 생산자(htm 스킬·dashboard runner)가 산출 시 등록
* `POST /hub-rescan` — hub `🔄 디스크 재스캔` 버튼이 등록 누락분 수거
* `POST /clear-done` · `/clear-htm-docs` — registry 항목 제거 (실제 파일은 보존)
* `POST /hook-event` — hook 이벤트를 `hook-feed.json` 활동 피드에 적재 (Issue42)

상세 설계: [`_doc_arch/hub_htm.md`](../../_doc_arch/hub_htm.md) `hub registry 모델` 섹션.
