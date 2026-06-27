// fpm-simple-browser — hub 렌더 문서를 VSCode Simple Browser 패널에 띄우는 URI 핸들러 (___pm Issue216).
//
// 메커니즘: VSCode 내장 `simpleBrowser.show` 명령은 외부 vscode:// URI·CLI 로 직접 호출 불가.
//   본 확장이 `vscode://finfra.fpm-simple-browser/open?url=<encoded>` URI 핸들러를 등록하고,
//   수신 시 url 파라미터를 꺼내 `simpleBrowser.show` 를 실행한다.
//   hub 서버의 POST /open-simple-browser 핸들러가 `open "vscode://..."` 로 본 URI 를 트리거한다.

const vscode = require("vscode");

function activate(context) {
  context.subscriptions.push(
    vscode.window.registerUriHandler({
      handleUri(uri) {
        // uri 예: vscode://finfra.fpm-simple-browser/open?url=http%3A%2F%2F127.0.0.1%3A9876%2Fhtm-doc%3Fpath%3D...
        let url = "";
        try {
          const params = new URLSearchParams(uri.query);
          url = params.get("url") || "";
        } catch (e) {
          vscode.window.showErrorMessage("fpm-simple-browser: URI 파싱 실패 — " + e.message);
          return;
        }
        if (!url) {
          vscode.window.showErrorMessage("fpm-simple-browser: url 파라미터 누락");
          return;
        }
        // 보안: localhost hub 서버 문서만 허용 (외부 임의 URL 차단).
        if (!/^https?:\/\/(127\.0\.0\.1|localhost|jm4\.local)(:\d+)?\//.test(url)) {
          vscode.window.showErrorMessage("fpm-simple-browser: 허용되지 않은 URL — " + url);
          return;
        }
        vscode.commands.executeCommand("simpleBrowser.show", url).then(
          () => {},
          (err) => vscode.window.showErrorMessage("fpm-simple-browser: simpleBrowser.show 실패 — " + err)
        );
      },
    })
  );
}

function deactivate() {}

module.exports = { activate, deactivate };
