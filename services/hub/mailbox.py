"""mailbox — 세션 transcript tail → 메일박스 적재 (Issue353_2 M2-a, arch C안).

hub 가 메일서버, 브라우저가 수신 클라이언트다. 서버는 세션 transcript(JSONL)를
증분 tail 해 **블록 단위 append-only 로그**로 쌓고, 브라우저는 `?since=<seq>` 커서로
찾아간다. 푸시(SSE)는 비채택 — 끊어질 연결이 없으므로 재연결·half-dead·서버 재시작
유실이 전부 소멸하고, 복구는 "다음 poll" 이라 복구 로직 자체가 없다.

# 설계 불변식

* **메일박스는 파생 캐시다.** 진실은 transcript 파일 — 서버가 재시작하면 재파싱으로
  언제든 재구성된다. "메일박스 유실"이라는 개념이 없다.
* **seq 는 파일 append 순서 기준.** timestamp 순서로 정렬하지 않는다 — M0 실측에서
  파일 내 엔트리 순서가 timestamp 와 비단조인 구간이 확인됐다(sidechain·hook 계열
  추정). 시각으로 정렬하면 블록 순서가 뒤틀린다. ts 는 표시용 보조다.
* **적재 대상은 assistant 텍스트 + 도구 이름뿐** (보안·프라이버시 불변식):
    - `text` 블록 → 그대로 적재 (렌더 대상)
    - `tool_use` 블록 → **도구 이름만** activity 로 적재. 인자는 적재하지 않는다
    - `tool_result`·`thinking` → **적재하지 않는다**. 도구 출력에는 파일 내용·자격증명·
      명령 출력이 섞이며, 라이브 뷰는 원격(tailscale)에서도 열리는 표면이다
    - 사용자 프롬프트 → 턴 경계 마커 + 발췌. 노출 수준은 기존 hub 세션 카드
      (`_session_first_prompt`)와 동일하다
* **partial write 안전**: 개행으로 완결된 라인만 파싱하고 커서도 **거기까지만** 전진한다.
  미완결 꼬리는 버퍼에 들지 않고 버리며, 다음 sync 가 같은 위치부터 다시 읽어 그때
  완성된 줄을 만난다 — 버퍼·rollback 이 없으므로 어긋날 여지 자체가 없다.
* **epoch(세대)**: 파일이 truncate·교체되면 세대를 올린다. 클라이언트의 `since` 가 세대
  불일치거나 보유 범위를 벗어나면 `205 Reset` → 클라가 DOM 을 비우고 전체 재동기화한다.
"""
import json
import os
import re
import threading
import time
from collections import deque

# 세션당 메모리 보유 블록 수. 초과분은 버려도 무방하다 — 진실은 파일이고,
# 클라이언트가 그보다 과거를 요구하면 205 Reset 으로 전체 재동기화시킨다.
RETENTION_BLOCKS = 800
# 세션 메일박스 TTL(초). 마지막 접근 이후 이 시간이 지나면 정리한다.
MAILBOX_TTL = 6 * 3600
# 한 번의 sync 에서 읽을 최대 바이트 (거대 tool_result 로 인한 스파이크 차단)
MAX_READ_CHUNK = 4 * 1024 * 1024
# 프롬프트·텍스트 발췌 상한
PROMPT_EXCERPT = 160

_lock = threading.Lock()
_boxes = {}          # (cwd_hash, sid) -> SessionMailbox
_epoch_seed = int(time.time())
# 세대 카운터 — 시각만으로 만들면 같은 초에 두 번 갱신될 때 값이 겹쳐
# 클라이언트가 재동기화 시점을 놓친다(파일 교체가 연속으로 일어나는 경우).
_gen_lock = threading.Lock()
_gen_counter = 0


def _next_generation() -> int:
    global _gen_counter
    with _gen_lock:
        _gen_counter += 1
        return _gen_counter


def _now() -> float:
    return time.time()


class SessionMailbox:
    """한 세션의 transcript tail 상태 + 블록 로그."""

    def __init__(self, key, path):
        self.key = key
        self.path = path
        self.epoch = f"{_epoch_seed}-{_next_generation()}"
        self.offset = 0          # 파일 내 파싱 완료 **바이트** 지점 (완결 라인까지만 전진)
        self.blocks = deque(maxlen=RETENTION_BLOCKS)
        self.max_seq = 0
        self.min_seq = 0         # 보유 중인 가장 오래된 seq (retention 밖 판정용)
        self.last_size = -1
        self.last_mtime = -1.0
        self.last_access = _now()
        self.turn_active = False  # 마지막 엔트리가 사용자 프롬프트 이후인가

    # ── tail ────────────────────────────────────────────────────────────
    def _stat(self):
        try:
            st = os.stat(self.path)
            return st.st_size, st.st_mtime
        except OSError:
            return None, None

    def changed(self) -> bool:
        """무변경 poll 을 파일 read 없이 판정한다 (stat 1회 + 정수 비교)."""
        size, mtime = self._stat()
        if size is None:
            return False
        return size != self.last_size or mtime != self.last_mtime

    def sync(self) -> int:
        """변경분을 읽어 블록으로 적재. 새로 추가된 블록 수를 반환."""
        size, mtime = self._stat()
        if size is None:
            return 0
        if size < self.offset:
            # truncate·파일 교체 — 세대를 올리고 처음부터 다시 읽는다
            self._reset_generation()
            size, mtime = self._stat()
            if size is None:
                return 0
        if size == self.last_size and mtime == self.last_mtime:
            return 0
        added = 0
        # ⚠️ 바이너리로 읽는다 — 텍스트 모드 `tell()` 은 디코더 상태를 인코딩한 opaque
        #   값이라 바이트 오프셋 산술(truncate 판정)에 쓸 수 없다.
        try:
            with open(self.path, "rb") as f:
                f.seek(self.offset)
                chunk = f.read(MAX_READ_CHUNK)
        except OSError:
            return 0
        if not chunk:
            self.last_size, self.last_mtime = size, mtime
            return 0
        # partial write 안전 — **커서를 완결 라인까지만 전진**시킨다. 미완결 꼬리는
        # 버퍼에 들고 있지 않고 그냥 버리며, 다음 sync 가 같은 위치부터 다시 읽어
        # 그때 완성된 줄을 만난다. 별도 버퍼·rollback 이 없으므로 어긋날 여지가 없고,
        # 멀티바이트 문자가 청크 경계에서 잘려도 U+FFFD 로 확정되지 않는다.
        cut = chunk.rfind(b"\n")
        if cut < 0:
            # 완결 라인이 하나도 없음 — 커서 유지, 다음 기회에 재시도
            self.last_size, self.last_mtime = size, mtime
            return 0
        complete, _tail = chunk[:cut + 1], chunk[cut + 1:]
        for raw in complete.split(b"\n"):
            if not raw.strip():
                continue
            added += self._ingest_line(raw.decode("utf-8", "replace"))
        self.offset += len(complete)
        self.last_size = size
        self.last_mtime = mtime
        return added

    def _reset_generation(self):
        self.epoch = f"{_epoch_seed}-{_next_generation()}"
        self.offset = 0
        self.blocks.clear()
        self.max_seq = 0
        self.min_seq = 0
        self.last_size = -1
        self.last_mtime = -1.0

    def _ingest_line(self, line: str) -> int:
        """JSONL 한 줄 → 블록 0..N개 적재. 파싱 실패는 조용히 skip(다음 줄 계속).

        파싱 실패한 줄을 drop 해도 커서가 그 지점을 지나므로 재시도는 없다 —
        완결된 줄인데 JSON 이 깨졌다면 재시도해도 같은 결과이기 때문이다.
        미완결 줄은 애초에 여기 오지 않는다(buf 에 보류).
        """
        try:
            e = json.loads(line)
        except Exception:
            return 0
        if not isinstance(e, dict):
            return 0
        if e.get("isSidechain"):
            return 0   # subagent 대화 — 메인 뷰 대상 아님
        typ = e.get("type")
        msg = e.get("message") or {}
        content = msg.get("content")
        ts = e.get("timestamp") or ""
        added = 0
        if typ == "user":
            # tool_result 를 담은 user 엔트리는 **적재하지 않는다** (도구 출력 미노출)
            if isinstance(content, list):
                if any(isinstance(b, dict) and b.get("type") == "tool_result"
                       for b in content):
                    return 0
                text = " ".join(b.get("text", "") for b in content
                                if isinstance(b, dict) and b.get("type") == "text")
            elif isinstance(content, str):
                text = content
            else:
                return 0
            if _is_injected_context(text):
                return 0   # 사람이 친 프롬프트가 아니라 하네스 주입 블록
            excerpt = _clean_excerpt(text)
            if not excerpt:
                return 0
            self._append("turn", excerpt, ts)
            self.turn_active = True
            return 1
        if typ != "assistant" or not isinstance(content, list):
            return 0
        for b in content:
            if not isinstance(b, dict):
                continue
            bt = b.get("type")
            if bt == "text":
                t = b.get("text") or ""
                if t.strip():
                    self._append("text", t, ts)
                    added += 1
            elif bt == "tool_use":
                # 도구 **이름만** — 인자는 파일 경로·명령·프롬프트를 담아 적재 대상 아님
                name = b.get("name") or "tool"
                self._append("activity", str(name), ts)
                added += 1
            # thinking·tool_result 등 그 외 타입은 적재하지 않는다
        return added

    def _append(self, kind: str, text: str, ts: str):
        self.max_seq += 1
        if len(self.blocks) == self.blocks.maxlen and self.blocks:
            # deque 가 밀어낸 만큼 보유 하한이 올라간다
            self.min_seq = self.blocks[0]["seq"] + 1
        self.blocks.append({"seq": self.max_seq, "kind": kind, "text": text, "ts": ts})
        if self.min_seq == 0:
            self.min_seq = 1

    # ── pull ────────────────────────────────────────────────────────────
    def read_since(self, since: int, epoch: str):
        """(status, payload) 반환.

        * `205` — 세대 불일치 또는 보유 범위를 벗어난 커서 → 클라가 전체 재동기화
        * `304` — 신규 블록 없음
        * `200` — 증분 블록 목록
        """
        self.last_access = _now()
        if epoch and epoch != self.epoch:
            return 205, {"epoch": self.epoch, "reason": "epoch mismatch"}
        if since > self.max_seq:
            # 서버가 되감긴 경우(파일 교체 등) — 클라 커서가 미래를 가리킴
            return 205, {"epoch": self.epoch, "reason": "cursor ahead of server"}
        # since=0 은 **신규 클라이언트**(처음부터 달라)다 — retention 밖이어도 205 가
        # 아니라 200 으로 보유분 전체 + `min_seq` 를 준다. 클라는 min_seq > 1 이면
        # "이전 내용 생략됨"을 표시하면 되고, 재동기화를 반복할 이유가 없다.
        # 반면 since > 0 인데 보유 하한보다 낮으면 그 사이 블록이 유실됐다는 뜻이라 205.
        if since and self.min_seq and since + 1 < self.min_seq:
            return 205, {"epoch": self.epoch, "reason": "cursor below retention"}
        if since >= self.max_seq:
            return 304, {"epoch": self.epoch, "max_seq": self.max_seq}
        out = [b for b in self.blocks if b["seq"] > since]
        return 200, {
            "epoch": self.epoch,
            "max_seq": self.max_seq,
            "min_seq": self.min_seq,
            "turn_active": self.turn_active,
            "blocks": out,
        }


# 하네스가 user 엔트리로 밀어 넣는 주입 블록 — 사람이 친 프롬프트가 아니므로
# 턴 경계로 세지 않는다. 이것을 걸러야 라이브 뷰의 턴 구분이 실제 대화와 일치한다.
_INJECTED_PREFIXES = (
    "<system-reminder", "<ide_opened_file", "<ide_selection", "<command-message",
    "<command-name", "<command-args", "<local-command-stdout", "<local-command-caveat",
    "<user-prompt-submit-hook", "caveat: the messages below",
)


def _is_injected_context(text: str) -> bool:
    t = (text or "").lstrip()
    low = t[:64].lower()
    return any(low.startswith(p) for p in _INJECTED_PREFIXES)


_EXCERPT_STRIP = re.compile(r"<[^>]+>|```[\s\S]*?```")


def _clean_excerpt(text: str) -> str:
    """프롬프트 발췌 — 태그·코드펜스 제거 후 1줄 정규화."""
    if not text:
        return ""
    t = _EXCERPT_STRIP.sub(" ", text)
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) > PROMPT_EXCERPT:
        t = t[:PROMPT_EXCERPT].rstrip() + "…"
    return t


# ── 레지스트리 ──────────────────────────────────────────────────────────
def get_box(cwd_hash: str, sid: str, path: str):
    """세션 메일박스 획득(없으면 생성). path 가 바뀌면 세대를 새로 연다."""
    key = (cwd_hash, sid)
    with _lock:
        box = _boxes.get(key)
        if box is None:
            box = SessionMailbox(key, path)
            _boxes[key] = box
        elif box.path != path:
            box.path = path
            box._reset_generation()
        return box


def gc(now: float = None) -> int:
    """TTL 지난 메일박스 정리. 반환값은 제거 개수."""
    now = now or _now()
    removed = 0
    with _lock:
        for key in [k for k, b in _boxes.items()
                    if now - b.last_access > MAILBOX_TTL]:
            _boxes.pop(key, None)
            removed += 1
    return removed


# GC 최소 간격(초). poll 은 초당 여러 번 올 수 있으므로 매번 전수 스캔하지 않는다.
GC_MIN_INTERVAL = 300
_last_gc = 0.0


def maybe_gc(now: float = None) -> int:
    """poll 경로에서 부르는 저비용 GC (Issue357).

    별도 타이머 스레드를 만들지 않는다 — 메일박스는 **라이브 뷰를 볼 때만** 생기므로,
    그 뷰를 폴링하는 경로에 얹는 것이 대상 유무와 정확히 대응한다(안 쓰면 정리할 것도
    없다). `_prune_htm_registry()` 의 TTL 가드와 같은 패턴이며, 간격 내 호출은
    부동소수 비교 1회로 끝난다.
    """
    global _last_gc
    now = now or _now()
    if now - _last_gc < GC_MIN_INTERVAL:
        return 0
    _last_gc = now
    return gc(now)


def stats() -> dict:
    with _lock:
        return {
            "sessions": len(_boxes),
            "blocks": sum(len(b.blocks) for b in _boxes.values()),
        }
