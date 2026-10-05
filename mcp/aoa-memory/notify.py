#!/usr/bin/env python3
"""aoa-memory 완료 통지 — 가속 B (UserPromptSubmit hook 주입) · prj5 Issue68 B-3 · 대상 한정 prj3#Issue938

⚠️ 설계 SSOT: ~/_git/___common/_doc_arch/aoa-memory-design.md "## 완료 통지 경로"

왜 hook 주입인가 (주체 제약)
  `SendMessage` 는 **Claude 세션의 도구**다. python worker·stdio MCP 서버는 그것을 부를 수
  없다(prj5#Issue64·65 확정 — `~/.bin/fpm-do` 가 zsh 에서 막힌 것과 동일 제약, 언어만 다르다).
  따라서 worker·서버가 끝낸 잡의 통지는 push 가 아니라 **세션의 다음 턴 진입 컨텍스트에
  실어 보내는 것**으로 성립시킨다. 이것이 가속 B 다.
  * 가속 A(`SendMessage`)는 **완료 주체가 Claude 세션인 잡**(위임 워커)에만 해당한다.
  * 영속 계층(`job` 테이블)은 통지로 지우지 않는다 — 세션이 죽으면 메시지도 hook 도 닿지 않는다.
    종결 행의 정리는 보존 기간 뒤 `worker.py gc --jobs` 의 몫이다.

동작 — «구독 행 소비» (Issue938 — 종전 «종결 전수 + 전달 표식 TTL» 을 대체)
  세션이 `learn_index` 로 큐에 넣은 잡은 `kv(ns='notify-want')` 구독 행을 남긴다(store.notify_subscribe).
  여기서는 **구독 행이 있고 · 배치 kind(store.BATCH_JOB_KINDS)이며 · 종결(done/failed)된** 잡만 **한 번에 묶어**
  출력(건당 발신 금지 — 수신 세션의 컨텍스트를 소모한다)하고, 전달한 구독 행을 **지운다**.
  * 대상이 아닌 것 — `fbot_*` 원장·`sel_event`·스케줄러(fbot-tick)가 30분마다 만드는 consolidation. 이들은 구독이 없다
    (Issue938 실측: 종전엔 종결 행 전수를 보아 24h 316회 주입, 그 중 fbot_event·sel_event·fbot_request 가 전부).
  * 재통지 없음 — 전달 표식을 두지 않으니 **TTL 만료 뒤 재통지**(종전 결함 ③, 30일 후 576건)가 구조적으로 불가하다.
    구독 행 TTL 은 «오래 안 읽혔으면 알릴 필요가 없다» 는 만료일 뿐이다.
  * 비용 — 구독 행(ns 접두 PK 범위)에서 job PK 로 조인한다. job 을 상태 인덱스로 훑지 않는다(종전 15k행 중 96% IN 스캔
    + TEMP B-TREE, 6.8~7.9ms).
  * 한 번에 20건 상한 — 초과분은 다음 프롬프트에 나간다(전달분만 지우므로 유실 없음).

fail-soft
  스토어가 없거나 읽기에 실패하면 **아무 것도 출력하지 않고 0 으로 끝난다**. 통지 실패가
  사용자 턴을 막아서는 안 된다. 단 구독 행 삭제가 실패하면 다음 턴에 다시 고지된다(중복 고지
  > 유실 — 통지는 유실을 발신자가 감지할 수 없는 계층이다).

등록
  `hooks/dispatch-userpromptsubmit.sh` 의 병렬 자식 #5 로 배선돼 있다(Issue409 — `AOA_HOME` 우선·번들 사본 폴백).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

LIMIT = 20

# 통지 쿼리 — kind 목록은 store.BATCH_JOB_KINDS 한 곳에서 온다(GC 와 같은 집합). `{kinds}` 자리표시자만 치환한다.
SELECT_SQL_TMPL = (
    "SELECT j.id, j.store, j.kind, j.status, j.result FROM kv w "
    "JOIN job j ON j.id = w.key "
    "WHERE w.ns = ? AND (w.expires_at IS NULL OR w.expires_at > ?) "
    "AND j.status IN ('done','failed') AND j.kind IN ({kinds}) "
    "ORDER BY j.created_at LIMIT %d" % LIMIT
)


def select_sql():
    """통지 SELECT 완성형 — kind 자리표시자를 store.BATCH_JOB_KINDS 개수만큼 채운다(테스트가 EXPLAIN 한다)."""
    import store as S
    return SELECT_SQL_TMPL.format(kinds=",".join("?" * len(S.BATCH_JOB_KINDS)))


def select_args(now):
    import store as S
    return (S.NOTIFY_WANT_NS, now) + tuple(S.BATCH_JOB_KINDS)


def main() -> int:
    try:
        import store as S
        if not os.path.exists(S.REGISTRY_DB):
            return 0
        with S.connect(S.REGISTRY_DB) as c:
            now = S.now()
            rows = c.execute(select_sql(), select_args(now)).fetchall()
            if not rows:
                return 0

            lines = ["[aoa-memory] 종결된 배치 잡 %d건 — 결과 회수 가능" % len(rows)]
            for r in rows:
                head = (r["result"] or "").strip().splitlines()
                lines.append("* %s (%s/%s) → %s%s" % (
                    r["id"], r["store"], r["kind"], r["status"],
                    " — " + head[0][:120] if head else ""))
            lines.append("상세는 `job_get(id=...)` 으로 조회한다.")
            sys.stdout.write("\n".join(lines) + "\n")

            try:                     # 구독 행 삭제 실패는 중복 고지로 흡수한다(유실보다 낫다)
                c.execute("BEGIN IMMEDIATE")
                c.executemany("DELETE FROM kv WHERE ns = ? AND key = ?",
                              [(S.NOTIFY_WANT_NS, r["id"]) for r in rows])
                c.commit()
            except Exception:
                pass
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
