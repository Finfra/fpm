// fpm-simple-browser — hub 렌더 문서를 VSCode Simple Browser 패널에 띄우는 URI 핸들러 (___pm Issue216).
//
// 메커니즘: VSCode 내장 `simpleBrowser.show` 명령은 외부 vscode:// URI·CLI 로 직접 호출 불가.
//   본 확장이 `vscode://finfra.fpm-simple-browser/open?url=<encoded>` URI 핸들러를 등록하고,
//   수신 시 url 파라미터를 꺼내 `simpleBrowser.show` 를 실행한다.
//   hub 서버의 POST /open-simple-browser 핸들러가 `open "vscode://..."` 로 본 URI 를 트리거한다.
//
// 허용 판정 (Issue471): hub 가 원격 접근용으로 광고하는 주소(MagicDNS 이름)를 종전 하드코딩
//   허용목록이 거부했다 — fpm 아이덴티티 조항 1(외부 링크는 hub URL)을 **지킬수록 깨지는** 지점.
//   주소를 여기서 만들지 않고 hub `/healthz` 의 `advertise_host` 를 물어서 받는다.
//   조회 실패 시 로컬 정적 목록만 남는다(fail-closed — 완화하지 않는다).

const vscode = require("vscode");

const HUB_HEALTHZ = "http://127.0.0.1:9876/healthz";
const STATIC_HOSTS = ["127.0.0.1", "localhost", "::1", "[::1]"];
const CACHE_TTL_MS = 60_000;

let _cache = { at: 0, hosts: [] };

/** hub 가 스스로 광고하는 호스트 1개를 받아 온다. 실패는 조용히 빈 배열(정적 목록만 유효). */
async function advertisedHosts() {
  const now = Date.now();
  if (now - _cache.at < CACHE_TTL_MS) return _cache.hosts;
  let hosts = [];
  try {
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), 1500);
    const res = await fetch(HUB_HEALTHZ, { signal: ctl.signal });
    clearTimeout(timer);
    if (res.ok) {
      const j = await res.json();
      // advertise_url(전체 URL) · advertise_host(호스트만) 어느 형태로 오든 호스트만 뽑는다.
      for (const key of ["advertise_host", "advertise_url"]) {
        const v = j && j[key];
        if (typeof v !== "string" || !v) continue;
        try {
          hosts.push(v.includes("://") ? new URL(v).hostname : v);
        } catch (_) { /* 형식 불량은 무시 — 없는 것으로 친다 */ }
      }
    }
  } catch (_) {
    // hub 미가동·타임아웃 — 정적 목록으로 동작한다. 여기서 완화하지 않는다.
  }
  _cache = { at: now, hosts: hosts.filter(Boolean) };
  return _cache.hosts;
}

/** 정규식이 아니라 URL 파서로 판정한다 — userinfo(`http://127.0.0.1@evil.com/`) 우회를 원천 차단. */
async function isAllowed(raw) {
  let u;
  try {
    u = new URL(raw);
  } catch (_) {
    return false;
  }
  if (u.protocol !== "http:" && u.protocol !== "https:") return false;
  if (u.username || u.password) return false;
  const host = u.hostname.toLowerCase();
  if (STATIC_HOSTS.includes(host)) return true;
  return (await advertisedHosts()).some((h) => h.toLowerCase() === host);
}

function activate(context) {
  context.subscriptions.push(
    vscode.window.registerUriHandler({
      async handleUri(uri) {
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
        // 보안: 로컬 hub + hub 가 광고하는 주소만 허용 (외부 임의 URL 차단).
        if (!(await isAllowed(url))) {
          vscode.window.showErrorMessage(
            "fpm-simple-browser: 허용되지 않은 URL — " + url +
            " (hub /healthz 의 advertise_host 로만 원격 주소가 허용됩니다)"
          );
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
