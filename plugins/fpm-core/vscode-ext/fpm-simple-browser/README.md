# fPm Simple Browser Bridge

hub 렌더 문서(`/htm-doc?path=...`)를 VSCode **Simple Browser** 패널에 띄우기 위한 최소 URI 핸들러 확장. ___pm Issue216.

## 왜 필요한가

VSCode 내장 `simpleBrowser.show` 명령은 외부에서 직접 호출할 수 없음:

* `code` CLI 에 명령 실행 옵션 없음
* `vscode://` URI 의 `command:` 핸들러는 외부 트리거 차단
* claude-code 등 설치 확장도 Simple Browser 연동 URI 미노출

→ 자체 URI 핸들러를 등록하는 확장이 유일한 견고 경로.

## 동작

1. hub 서버 `POST /open-simple-browser` (body `{path}`) 수신 → register-doc 화이트리스트 검증
2. 서버가 `open "vscode://finfra.fpm-simple-browser/open?url=<htm-doc URL>"` 실행
3. 본 확장의 `handleUri` 가 `url` 추출 → `simpleBrowser.show` 실행 → 패널 표시

URL 은 `127.0.0.1` / `localhost` / `host-1.local` 호스트만 허용(외부 임의 URL 차단).

## 설치

```bash
bash install.sh
```

vsce 로 `.vsix` 패키징 후 `code --install-extension` 으로 설치. 설치 후 VSCode **창 새로고침**(Cmd+R 또는 "Developer: Reload Window") 1회 필요.

## 수동 검증

```bash
open "vscode://finfra.fpm-simple-browser/open?url=http%3A%2F%2F127.0.0.1%3A9876%2Fhtm-doc%3Fpath%3D%2Fabs%2Fdoc.htm%26_shell%3D1"
```

→ VSCode Simple Browser 패널에 문서 표시되면 정상.
