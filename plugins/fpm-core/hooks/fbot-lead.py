#!/usr/bin/env python3
"""fbot 팀장핀봇(lead) 판정 코어 (Issue436_3 s3 — 단계 3·4·5·6).

계약: ~/.claude/_doc_arch/fbot-arch.md §조직(팀장핀봇 임무·수요측 가드) ·
      §워크플로우 어댑터(nPTiR/칸반 — 코어 중립) · §호출 경계(스폰=HR 게이트 경유,
      `[컨펌]` 응답 승인은 사람 전용) · §작업 기록(F4 — 봇 전용 작업 대장 금지).
      어댑터 설정 위치는 s3 확정(2026-08-24): 프로젝트 `.claude/fbot.yml`
      `workflow: nptir|kanban` (파일·키 부재 = nptir). 계약 참조만 하며 재결정하지 않는다.

CLI
    pending  [--cwd DIR]
        issue-map `--json` 소비 → 펜딩 큐 뷰(startable/blocked 분류) 출력.
        펜딩 큐 = Issue.md·issue-map 의 **파생 뷰**다 — 별도 작업 대장 파일을 만들지
        않는다(F4). `--json` 부재·실패 시 fail-loud(빈 목록으로 오독 금지).
        칸반 어댑터면 pull 안내 + WIP 잔여(= 수요측 동시 상한 그대로)를 함께 표시 —
        판정 코어는 어댑터 중립, 표시만 갈린다.
    dispatch (--issue ID | --topic TEXT) --role ROLE [--cwd DIR] [--bot-id ID] [--loan-key KEY] [--dry-run]
        배분 **요청**: ① 수요측 가드 판정(동시·같은 일 반복·되풀이 속도·배분자 백스톱·연속 실패 — 단일 지점. 월 상한은 알림 전용)
        ② 통과 시 HR 게이트 `hire` 호출로 워커 봇 채용까지(스폰 집행은 fpm-do/Agent
        몫 — 여기서는 채용+배분 기록. 게이트 없는 스폰 경로 금지)
        ③ bot_id=fbot-lead 귀속으로 registry.job 에 배분 기록(kind=fbot_dispatch).
        착수 가능 판정은 pending(issue-map) 소관 — 여기서 재판정하지 않는다.
    watch    [--cwd DIR]
        진행 감시: 배분 기록 vs bot.state·lease_expires 대조 → 적체 2종 판정
        (A: 미배분 startable 적체 — --cwd 지정 시만, issue-map 필요 /
         B: 배분 후 진행 신호 없음 — bot 부재·퇴근·lease 만료)
        → 재시도 카운트(상한 RETRY_LIMIT — opus 룰 §2) → 초과 시 에스컬레이션:
        aoa-mq enqueue helper `--alert` 호출(직접 큐 파일 Write 금지).
        진입 시 `sweep`(완료 감지)을 **선행**한다.
    sweep    [--dry-run]
        완료 감지(Issue438 ④): 배분 워커가 `checkout` + 그 봇의 `fbot_session` job 이
        done(배분 생성 이후) 이면 배분 완료 → job status=done 갱신. 완료는 **로그**라 mq 에
        싣지 않는다(prj3#Issue750) — fbot-map 타임라인·hub SSE·daily 보고가 받는다.
        watch 는 이 스윕을 **선행** 실행한다 —
        완료한 워커도 퇴근 상태라 순서를 바꾸면 정상 완료가 거짓 에스컬레이션이 된다.
    status
        이번 달 배분 수·상한·활성 배분 목록 + **취소 집계**(이번 달 건수·최근 5건
        사유). 취소는 `done` 과 합산하지 않는다 — 성과가 아니다(Issue446).

설계 원칙 (fbot-state.py·fbot-hr-gate.py 승계)
* 표준 라이브러리만 사용(무의존). policy.yml·fbot.yml 은 평탄 키라 정규식으로 읽는다.
* fail-loud: issue-map 부재·policy 키 부재·미정의 어댑터 값 전부 명시 에러 + exit != 0.
* 상한 수치는 aoa policy.yml `fbot_dispatch_*` 2키가 SSOT — 하드코딩 금지.
* 배분 원장: registry.kv ns=`fbot:dispatch` key=YYYY-MM — HR 예산 원장(ns=fbot:budget)과
  같은 패턴. 신규 월 키 생성이 곧 리셋(리셋 잡 없음). 증분은 BEGIN IMMEDIATE 재검증.
* ⚠️ mq `[컨펌]` 응답 승인 호출 절대 금지 — 봇은 enqueue·리마인드·snooze **제안까지만**
  (`[컨펌]` 처리는 사람 전용 — 계약 §호출 경계). 본 코드에 해당 호출 경로가 없다.
* `AOA_MEMORY_DIR` env 존중(fbot-state.py 와 동일 방식).
"""

import argparse
import glob
import json
import os
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
import unicodedata
import uuid

# 경로 계약 (Issue450) — env 가 정식 설정. 미설정 시 제품 중립 기본(prj5 미클론 머신 대응).
DEFAULT_AOA_DIR = os.path.join(os.path.expanduser("~"), ".claude", "data", "aoa")

# issue-map 이미터 (s3 확장 ① — 파서 재사용, htm 스크레이핑 금지)
ISSUE_MAP_PY = os.path.join(
    os.path.expanduser("~"), ".claude", "skills", "issue-map", "build_issue_map.py"
)

# prj 해소 resolver (prj3#Issue479) — 계약 §기존 규약 접점 "projects map".
#   ⚠️ 파일 값 = projects 디렉토리 **절대경로 그 자체**다. 추가 `/projects` join 금지
#      (fpm MCP `_base_dir()` 와 동일 구현 — 개인 경로 하드코딩 폴백도 금지).
PM_BASE_FILE = os.path.join(os.path.expanduser("~"), ".info", "__pmBasePath.txt")

# HR 게이트 (스폰 판정 단일 SSOT — 판정 로직 중복 구현 금지)
TASKMGR_ID = "fbot-lead"
HR_GATE_PY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fbot-hr-gate.py")

# aoa-mq 등록 helper (직접 큐 파일 Write 금지 — helper 경유만)
MQ_ENQUEUE_SH = os.path.join(
    os.path.expanduser("~"), ".claude", "mcp", "aoa-mq", "aoa-mq-enqueue.sh"
)
# prj3#Issue947 — mq helper 호출 상한(초). 넘으면 프로세스 그룹째 끊고 실패로 올린다(tick 을 붙잡지 않게).
#   «완료 미확인» 포기 표지의 고착 창 하한(UNCONF_GIVEUP_STALE_MIN_S)보다 충분히 짧아야 한다 — 진행 중인 경보를 다른 sweep 이
#   고착으로 오인해 이중 경보하지 않게. 정상 enqueue 는 1초 안쪽
MQ_ALERT_TIMEOUT_S = 60

BOT_ID = "fbot-lead"  # 배분자 **기본값** (F4). prj3#Issue538 로 prj별 PM 이 생기면서

# prj3#Issue608 → prj3#Issue757 F — 배분 계층. 총괄이 직접 부릴 수 있는 상대다.
#   종전(Issue608)엔 관리자 전부(`lead`·`hr`·`scout`·`chief`)였으나, *"총괄은 팀장과만 대화한다 —
#   인사·발굴·설계·QA 를 부리는 것은 팀장"*(사용자 지시 2026-09-28)으로 **팀장과 동급 총괄**로 좁혔다.
#   실측(2026-09-28 원장): 총괄 배분 176건 중 팀장 174 · 발굴 직행 2 — 운영은 이미 이 모양이었다.
#   워커 role 을 열거하지 않는 이유는 그대로다 — 직능은 발굴로 계속 늘어난다. **허용 목록만 고정**한다.
CHIEF_TARGET_ROLES = ("lead",)
#   ⚠️ 동급 총괄(나래↔미르)과는 **배분이 아니라 대화**다(인박스·머신 간 outbox). `--role chief` 로컬 배분은
#   상비 총괄을 가리키지 못하고 `fbot-chief-<이슈>` 워커를 새로 채용할 뿐이다(plan 재점검 지적 4).


def chief_target_reject(dispatcher_role, target_role):
    """총괄의 배분 대상 판정 — 거부 사유 문자열 또는 None (prj3#Issue757 F, 판정 단일 지점).

    총괄이 아닌 배분자(팀장 등)는 대상 role 을 가리지 않는다 — 팀장이 인사·발굴·워커를 부리는 것이
    임무다. PM 부재·퇴근은 거부 사유가 아니다: `--role lead` 가 그 prj 팀장을 해소해 없으면 HR 게이트로
    자동 채용하고(Issue692) 퇴근 중이면 기상시킨다 — 총괄이 인사핀봇을 부를 일이 없다.
    """
    if (dispatcher_role or "") != "chief" or (target_role or "") in CHIEF_TARGET_ROLES:
        return None
    return (f"총괄은 팀장에게만 배분한다 (대상 role={target_role}). 동급 총괄과는 인박스로 대화한다. "
            f"인사·발굴·설계·QA 를 부리는 것은 그 prj 의 팀장이다 — "
            f"--role lead --cwd <prj 경로> --topic '<요지>' 로 배분하면 팀장이 없을 때는 자동 채용, "
            f"퇴근 중이면 기상한다. 자리 밖 인력은 팀장이 총괄에 요청하면 총괄이 차용·생성으로 푼다(Issue757)")
#   배분자가 여럿이 됐다 — `dispatch --by` 로 지정하지 않으면 이 전역 봇이 배분자다.
#   ⚠️ 예산·상한 원장 키는 **전역 합산 그대로**다(아래 dispatch 주석 참조).

# policy.yml 필수 키 2종 (s3 편입분 — 수요측 가드) — 로드 실패 시 fail-loud
POLICY_KEYS = ("fbot_dispatch_monthly_limit", "fbot_dispatch_concurrent_limit")
# prj3#Issue613 — 배분자별 상한은 **선택 키**다. 부재 시 기본값으로 돈다(fail-soft) —
#   필수로 두면 policy 미갱신 머신에서 배분이 통째로 막힌다.
# prj3#Issue696 — 패턴 가드 3종도 같은 이유로 선택 키다. 기본값은 **여기 한 곳**에만 둔다
#   (정본 수치는 policy.yml · 부재 시에만 이 값). 값의 근거는 policy.yml 주석이 답한다.
OPTIONAL_POLICY_DEFAULTS = {
    "fbot_dispatch_actor_limit": 10,
    "fbot_dispatch_issue_repeat_limit": 4,
    "fbot_dispatch_fail_streak_limit": 3,
    "fbot_dispatch_pattern_window_hours": 24,
    # prj3#Issue755 — 전역 `fbot_dispatch_hourly_limit` 를 두 키로 대체했다(폭주 판별)
    "fbot_dispatch_repeat_hourly_limit": 5,
    "fbot_dispatch_actor_hourly_limit": 40,
}
# prj3#Issue814 — 출근 유예(분). `dispatch --spawn` 뒤 이 시간 안에 출근 이벤트가 없으면 watch 적체.
#   선택 키 — 부재 시 기본값. 패턴 가드가 아니라 OPTIONAL_POLICY_DEFAULTS 에 섞지 않는다(status 출력 분류).
CHECKIN_GRACE_KEY = "fbot_checkin_grace_minutes"
CHECKIN_GRACE_DEFAULT_MIN = 5
# prj3#Issue947 — «완료 미확인» 재통지 상한·백오프(`unconfirmed_notify_policy`). 선택 키 — 부재 시 아래 기본값(정본 수치는
#   policy.yml). 패턴 가드가 아니라 OPTIONAL_POLICY_DEFAULTS 에 섞지 않는다(CHECKIN_GRACE 와 같은 이유 — status 출력 분류).
UNCONF_NOTIFY_LIMIT_KEY = "fbot_unconfirmed_notify_limit"
UNCONF_NOTIFY_LIMIT_DEFAULT = 5
UNCONF_NOTIFY_BACKOFF_KEY = "fbot_unconfirmed_notify_backoff_minutes"
UNCONF_NOTIFY_BACKOFF_DEFAULT_MIN = 30   # = sweep 주기(worker tick 30분 — fbot-worker-plist.sh)
# 포기 표지 고착 판정 하한(초) — 표지만 있고 경보 기록이 없는 행을 «고착» 으로 볼 최소 경과. 창 = max(백오프 기준, 이 값).
#   정상 경로는 표지 직후 수 초 안에 경보 id 를 쓴다 — 정책 백오프를 아주 작게 둬도 경보 진행 중인 표지를 다시 집지 않게
UNCONF_GIVEUP_STALE_MIN_S = 600
# 포기·경보 대상 판정(`unconfirmed_notify_state`) — 상한 도달(`exhausted`) + 표지 고착 재경보(`stale`) + 경보 실패 뒤 백오프 경과(`alert_retry`)
GIVE_UP_STATES = ("exhausted", "stale", "alert_retry")
# 출근으로 치는 이벤트 — 새 봇은 register 기본 state=checkin 이라 출근 훅의 checkin 전이가 막히고
#   `state:working` 만 남는다(fbot-checkin.sh). 둘 중 하나면 세션이 떴다.
CHECKIN_EVENTS = ("state:checkin", "state:working")
# 서킷브레이커가 «실패» 로 세는 종결 상태 — done 이 하나라도 끼면 연속이 끊긴다
FAIL_STATUSES = ("reaped", "cancelled")
# prj3#Issue952 — `cancel --verdict` 닫힌 라벨. gate_failed = 정상 게이트가 막아 취소한 것 — 스폰·lease 결함이 아니라
#   서킷브레이커가 세지 않는다. cancelled_obsolete(기본값)는 명시 취소 전체라 계속 센다
CANCEL_VERDICTS = ("cancelled_obsolete", "gate_failed")
BREAKER_EXEMPT_VERDICTS = ("gate_failed",)

DISPATCH_NS = "fbot:dispatch"  # registry.kv 배분 원장 네임스페이스 (HR ns=fbot:budget 과 분리)
JOB_KIND = "fbot_dispatch"     # registry.job 배분 기록 kind
# prj3#Issue612 — 분업 우회 기록. **배분과 kind 를 섞지 않는다**: 섞으면 우회가 배분 실적으로
#   잡혀 조직 판정(부하·결원)이 정확히 반대로 읽는다(취소를 완료와 분리한 것과 같은 이유).
SOLO_JOB_KIND = "fbot_solo"
SESSION_JOB_KIND = "fbot_session"  # 퇴근 훅(fbot-checkout.sh)이 남기는 세션 기록 kind
# 통지 워터마크 — 배분에 매이지 않은 봇 세션 완료를 어디까지 알렸는지(Issue438 ④ 명세 정합).
#   배분 완료는 job status 전이가 곧 중복 방지지만, 세션 완료는 그 보장이 없어 워터마크가 필요하다.
NOTIFY_NS = "fbot:notify"
NOTIFY_SESSION_KEY = "session_watermark"

# 재시도 상한 — opus-4-8-execution-rules §2 (2회 연속 실패 시 보고·대기). 정책 수치가
# 아니라 실행 규칙 상수라 policy.yml 에 넣지 않는다.
RETRY_LIMIT = 2

# 워크플로우 어댑터 허용값 (계약 §워크플로우 어댑터 — 표준 2종)
ADAPTERS = ("nptir", "kanban")

CIRCLED = {1: "①", 2: "②"}


class FbotError(Exception):
    """fail-loud 용 — 인프라·입력 오류. stderr + exit 2."""


class Reject(Exception):
    """수요측 가드 거부 — 판정 번호 + 사유. exit 1."""

    def __init__(self, n: int, reason: str):
        self.n = n
        self.reason = reason
        super().__init__(f"{self._label()}: {reason}")

    def _label(self) -> str:
        """메시지 머리 — 하위 거부(PlacementReject)가 라벨만 바꾼다(prj3#Issue945)."""
        return f"수요측 판정 {CIRCLED[self.n]} 거부"


class PlacementReject(Reject):
    """배치 판정 거부 — 차용(`loan_reject`)·채용 사다리(`hire_ladder_verdict`)·⓪ cross(남의 prj 일). exit 1 은 종전 그대로.

    수요측 가드(①)가 아니다 — 종전엔 `Reject(1)` 로 나가 «수요측 판정 ① 거부» 라벨을 달아, 받는 팀장이 동시·반복·속도 가드에
    걸린 줄로 읽었다(prj3#Issue945). `n` 은 호출자 계약(rc·`e.n == 1`)을 지키려 1 로 둔다. 사유는 안내 명령을 싣는다 —
    받는 쪽(`spawn_dispatch` 등)이 자르지 않는다."""

    def __init__(self, reason: str):
        super().__init__(1, reason)

    def _label(self) -> str:
        return "배치 판정 거부(인력 확보 사다리)"


# ── 경로·정책·어댑터 ────────────────────────────────────────────────────────

def aoa_dir() -> str:
    return os.environ.get("AOA_MEMORY_DIR") or DEFAULT_AOA_DIR


def registry_path() -> str:
    p = os.path.join(aoa_dir(), "registry.db")
    if not os.path.exists(p):
        raise FbotError(f"레지스트리 DB 없음: {p} (AOA_MEMORY_DIR 확인)")
    return p


def load_policy() -> dict:
    """aoa policy.yml 의 fbot_dispatch_* 2키 로드. 파일·키 부재 = fail-loud (기본값 폴백 금지)."""
    # prj3#Issue626 — **정책 수치의 정본은 prj3** 다. 데이터(registry.db·learn.db)는 용량 때문에
    #   prj5 에 남지만(zshenv 명시 결정) 수치는 prj3 소관이다. 폴백 순서가 핵심이다:
    #   ⓐ `aoa_dir()` 에 있으면 그것 — **테스트가 픽스처에 쓴 policy 를 계속 읽는다**
    #   ⓑ 없으면 prj3. 운영에서는 prj5 사본을 걷었으므로 여기로 온다
    #   순서를 뒤집으면 테스트가 운영 policy 를 읽어 픽스처가 무력해진다.
    #   ⓒ prj3#Issue696 — 그것도 없으면 배포 기본값 `policy_org.yml`(hook-say-setting `_org` 관례).
    #      aoa_dir 쪽에는 _org 를 찾지 않는다 — 테스트 픽스처가 운영 기본값에 오염되지 않게.
    path = os.path.join(aoa_dir(), "policy.yml")
    if not os.path.exists(path):
        for _name in ("policy.yml", "policy_org.yml"):
            _p3 = os.path.join(os.path.expanduser("~"), ".claude", "data", "aoa", _name)
            if os.path.exists(_p3):
                path = _p3
                break
    if not os.path.exists(path):
        raise FbotError(f"policy 로드 실패 — 파일 없음: {path}")
    pol = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            m = re.match(r"^(fbot_[a-z_]+):\s*(\d+)", line)
            if m:
                pol[m.group(1)] = int(m.group(2))
    missing = [k for k in POLICY_KEYS if k not in pol]
    if missing:
        raise FbotError(f"policy 로드 실패 — {path} 에 키 부재: {', '.join(missing)}")
    bad = [k for k in POLICY_KEYS if pol[k] <= 0]
    if bad:
        raise FbotError(f"policy 값 불량(양수 아님): {', '.join(f'{k}={pol[k]}' for k in bad)}")
    return pol


def pm_projects_dir():
    """projects/ 디렉토리 절대경로. 부재·빈 값은 None (fpm MCP `_base_dir()` 동형)."""
    if not os.path.isfile(PM_BASE_FILE):
        return None
    with open(PM_BASE_FILE, encoding="utf-8") as fh:
        raw = fh.read().strip()
    return os.path.expanduser(os.path.expandvars(raw)) if raw else None


def resolve_prj(cwd: str, base=None):
    """cwd → 등록 prj 번호. **최장 prefix 일치**(hub `_resolve_project_root` 와 동일 정책).

    왜 fail-loud 가 아닌가 — `prj` 는 주 담당을 가리키는 **메타 필드**이고, 미등록 경로에서의
    배분은 정당하다(s3 실증이 `/tmp/fbot-s3/demo-prj` 에서 돈다). 해소 실패로 배분 자체를
    막으면 가용성 손실이 더 크다. 대신 **조용히 넘어가지 않는다** — resolver 부재는 stderr
    경고를 낸다(설정 사고와 정상적인 미등록을 구분하기 위함).

    ⚠️ **한계**: `bot.prj` 가 INT 라 `42a` 같은 **비숫자 prj 는 담을 수 없다.** 그런 경로는
       상위 숫자 프로젝트로 귀속된다(실측: `42a`=Projects_deck 은 `42`=m2slide 의 하위라
       42 로 잡힌다). 정확한 귀속이 필요해지면 스키마 축 확장이 선행 조건이다.
    """
    if base is None:
        base = pm_projects_dir()
    if not base or not os.path.isdir(base):
        print(f"[fbot-lead] ⚠️ prj resolver 없음({PM_BASE_FILE}) — prj 미기록으로 진행",
              file=sys.stderr)
        return None

    target = os.path.realpath(os.path.expanduser(cwd))
    best_num, best_len = None, -1
    for name in os.listdir(base):
        if not name.isdigit():
            continue  # `42a`·README 등 — INT 컬럼에 못 담는다(위 한계 주석)
        entry = os.path.join(base, name)
        if not os.path.isfile(entry):
            continue
        with open(entry, encoding="utf-8") as fh:
            raw = fh.read().strip()
        if not raw:
            continue
        root = os.path.realpath(os.path.expanduser(raw))
        # 경계 검사 — 순수 문자열 prefix 로 보면 `…/m2slide-other` 가 `…/m2slide` 에 걸린다
        if target == root or target.startswith(root.rstrip(os.sep) + os.sep):
            if len(root) > best_len:
                best_num, best_len = int(name), len(root)
    return best_num


def load_workflow(cwd: str) -> str:
    """프로젝트 `.claude/fbot.yml` 의 `workflow:` 키 (s3 확정 — per-prj 선택값).

    파일·키 부재 = 기본 nptir. 미정의 값은 fail-loud — 어댑터 오독으로 흐름이
    갈라지는 것을 막는다(silent 기본값 강등 금지).
    """
    path = os.path.join(cwd, ".claude", "fbot.yml")
    if not os.path.exists(path):
        return "nptir"
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            m = re.match(r"^workflow:\s*(\S+)", line)
            if m:
                val = m.group(1)
                if val not in ADAPTERS:
                    raise FbotError(
                        f"미정의 워크플로우 어댑터: {val!r} ({path}) — 허용값 {', '.join(ADAPTERS)}"
                    )
                return val
    return "nptir"


# ── issue-map 소비 (판정 재료 — 재판정 금지) ────────────────────────────────

def load_issue_map(cwd: str) -> dict:
    """issue-map `--json` 실행·파싱. 부재·실패는 전부 fail-loud — 빈 목록으로 오독 금지.

    판정(startable/blocked_by)은 issue-map 소유다 — 여기서는 소비만 한다.
    """
    if not os.path.exists(ISSUE_MAP_PY):
        raise FbotError(f"issue-map 스크립트 없음: {ISSUE_MAP_PY}")
    proc = subprocess.run(
        [sys.executable, ISSUE_MAP_PY, "--json"],
        cwd=cwd, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise FbotError(
            f"issue-map --json 실패(exit {proc.returncode}) — 판정불가, 빈 큐로 오독 금지: "
            f"{(proc.stderr or proc.stdout).strip().splitlines()[-1] if (proc.stderr or proc.stdout).strip() else '출력 없음'}"
        )
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise FbotError(f"issue-map --json 출력 파싱 실패 — 판정불가: {e}")
    for key in ("root", "issues"):
        if key not in data:
            raise FbotError(f"issue-map --json 스키마 위반 — {key!r} 필드 부재")
    return data


TERMINAL_RE = re.compile(r"완료|취소")  # 종결 섹션은 펜딩 뷰에서 제외 (뷰 필터일 뿐 판정 아님)


def classify(issues: list) -> tuple[list, list]:
    """펜딩 이슈를 startable/blocked 로 분류 — issue-map 의 startable 판정을 그대로 쓴다."""
    startable, blocked = [], []
    for it in issues:
        if TERMINAL_RE.search(str(it.get("section", ""))) or TERMINAL_RE.search(str(it.get("state", ""))):
            continue
        (startable if it.get("startable") else blocked).append(it)
    return startable, blocked


# ── DB ──────────────────────────────────────────────────────────────────────

def connect() -> sqlite3.Connection:
    con = sqlite3.connect(registry_path(), timeout=10, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=5000")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def month_key(now: float | None = None) -> str:
    return time.strftime("%Y-%m", time.localtime(now if now is not None else time.time()))


def dispatched_this_month(con: sqlite3.Connection, month: str) -> int:
    row = con.execute(
        "SELECT value FROM kv WHERE ns = ? AND key = ?", (DISPATCH_NS, month)
    ).fetchone()
    return int(row["value"]) if row is not None else 0


def active_dispatches(con: sqlite3.Connection) -> list:
    """미종결 fbot_dispatch job 전체 (open=진행, blocked=사람 ACK 대기, logged=사후 기록).

    ⚠️ 동시 상한(WIP) 판정은 호출측이 `status=="open"` 만 필터한다 — blocked 는
    사람 판단 대기라 WIP 슬롯을 점유하지 않는 것이 의도(s3 QA 발견 ② 명문화).

    prj3#Issue514 (2026-09-03) — **`logged` 를 미종결로 확정하고 여기 편입한다.**
      `logged` 는 `fbot-state.py dispatch-record` 가 남기는 **사후 기록**이다(이슈 번호 없는
      크로스 프로젝트 작업 등, `lead dispatch` 를 쓸 수 없는 경로). 종전에는 이 술어에
      없어서 **어떤 자동 경로로도 닫히지 않았다** — `status` 에 안 보이고(`active_dispatches: []`)
      `sweep` 도 감지하지 못해(`detected: 0`) 사람이 손으로 정리해야 했다.
      실측 2026-09-03: 나래의 리서치봇 2기가 정상 완료·퇴근했는데 배분 2건이 `logged` 로 잔류.

      🔴 **WIP 는 여전히 점유하지 않는다.** `logged` 는 *이미 일어난 일* 의 기록이지 슬롯
      예약이 아니다(`dispatch-record` 가 상한 판정을 두지 않는 것과 같은 이유). 호출측
      필터가 `=="open"` 이므로 편입해도 동시 상한은 불변이다 — 보이게만 만든다.

    prj3#Issue686 (2026-09-26) — **`deferred`(명시 보류)도 미종결로 편입한다.** 봇이 스스로
      뒤로 미룬 일은 종전 원장에 표현 수단이 없어 보드가 파생 판정으로만 추정했다.
      편입 이유는 `logged` 와 같다 — 보이고(`status`), 닫을 수 있어야(`close`·`cancel`) 한다.
      🔴 WIP 미점유(호출측 `=="open"` 필터) · 정체 감시 제외(`watch` 도 `open` 만 본다) ·
      **sweep 은 완료로 보지 않는다**(`detect_completions` 가 명시 제외 — 미룬 일이 끝났을 리 없다).

    prj3#Issue795 — 술어는 fbot-state `LINEAGE_LIVE` 단일 지점을 읽는다. 여기와 계보가 따로 적혀
      있어 `deferred` 편입(prj3#Issue686)이 이쪽만 갱신됐다 — 보류 배분이 계보·출근 후보에서 빠졌다.
    """
    live = _lineage_live()
    rows = con.execute(
        "SELECT * FROM job WHERE kind = ? AND status IN (" + ",".join("?" * len(live)) + ")"
        " ORDER BY created_at",
        (JOB_KIND,) + tuple(live),
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["payload"] = json.loads(d["payload"]) if d["payload"] else {}
        except json.JSONDecodeError:
            d["payload"] = {"raw": d["payload"]}
        out.append(d)
    return out


def cancelled_dispatches(con: sqlite3.Connection) -> list:
    """취소(cancelled) 배분 전체 — 종결분이라 `active_dispatches` 가 보지 않는 축이다.

    왜 별도 함수인가 (Issue446) — `cancel` 경로 신설로 `cancelled` 상태가 생겼으나 관측이
    따라오지 않아 원장에만 존재하고 어느 뷰에도 안 나왔다. ⚠️ **`done` 과 합산 금지** —
    분리한 이유가 "취소를 성과로 집계하지 않는 것" 이다(cmd_cancel 주석 참조).

    시각 키가 2종인 것은 이력 때문이다: `cancel` 명령이 쓰는 `cancelled_at` 과, 명령
    신설 이전에 총괄핀봇이 직접 UPDATE 로 화해한 건의 `swept_at`. 둘 다 없으면 생성
    시각으로 떨어진다 — 시각 부재를 "취소 없음" 으로 읽지 않기 위한 폴백이다.
    주체 키도 같은 이유로 `cancelled_by`/`detected_by` 2종을 본다.
    """
    rows = con.execute(
        "SELECT * FROM job WHERE kind = ? AND status = 'cancelled' ORDER BY created_at",
        (JOB_KIND,),
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        for k in ("payload", "result"):
            try:
                d[k] = json.loads(d[k]) if d[k] else {}
            except json.JSONDecodeError:
                d[k] = {"raw": d[k]}
        res = d["result"]
        d["cancelled_at"] = res.get("cancelled_at") or res.get("swept_at") or d["created_at"]
        d["cancelled_by"] = res.get("cancelled_by") or res.get("detected_by") or "unknown"
        out.append(d)
    out.sort(key=lambda d: d["cancelled_at"])
    return out


def _state_mod():
    """fbot-state.py 의 record_event/notify_hub_event 재사용 (prj3#Issue575). 부재·실패는 조용히 None."""
    try:
        import importlib.util
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fbot-state.py")
        spec = importlib.util.spec_from_file_location("fbot_state", path)
        mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


_STATE_MOD = None


def _state_required(what):
    """fbot-state 모듈 — 적재 실패는 fail-loud(`what` = 읽으려던 것). 단일 지점 어휘는 사본 폴백을 두지 않는다."""
    global _STATE_MOD
    if _STATE_MOD is None:
        _STATE_MOD = _state_mod() or False
    if not _STATE_MOD:
        raise FbotError(f"fbot-state.py 적재 실패 — {what} 를 읽을 수 없다")
    return _STATE_MOD


def _lineage_live():
    """미종결 배분 술어 — fbot-state `LINEAGE_LIVE` 단일 지점(prj3#Issue795). 적재 실패는 fail-loud —
    사본 폴백을 두면 두 술어가 다시 갈라진다."""
    return _state_required("미종결 배분 술어(LINEAGE_LIVE)").LINEAGE_LIVE


def _unconfirmed():
    """«완료 미확인» 어휘 — fbot-state `UNCONFIRMED` 단일 지점(prj3#Issue929). 배분 `blocked_by` 사유·payload 키·
    인박스 통지 kind 가 같은 값이다(fbot-inbox `close_fulfilled`·fbot-manual-review 도 같은 곳을 읽는다)."""
    return _state_required("«완료 미확인» 어휘(UNCONFIRMED)").UNCONFIRMED


def _report_statuses():
    """워커 보고의 명시 status 어휘 — fbot-state `REPORT_STATUSES` 단일 지점(fbot-inbox `defer --status` 검증과 같은 값)."""
    return _state_required("보고 status 어휘(REPORT_STATUSES)").REPORT_STATUSES


def _canon_issue(text):
    """이슈 식별자 기록 형식 — fbot-state `canon_issue` 단일 지점 재사용(prj3#Issue761: 맨 숫자 `727` → `Issue` 접두).
    모듈은 한 번만 적재한다(sweep 이 배분마다 부른다). 적재 실패는 원문 그대로 — 종전 동작."""
    global _STATE_MOD
    if _STATE_MOD is None:
        _STATE_MOD = _state_mod() or False
    try:
        return _STATE_MOD.canon_issue(text) if _STATE_MOD else (text or "")
    except Exception:
        return text or ""


def _ev(con, bot, etype, detail="", ref=""):
    m = _state_mod()
    if m:
        try:
            m.record_event(con, bot, etype, detail, ref)
        except Exception:
            pass


def _ev_notify(bot, etype, ref=""):
    m = _state_mod()
    if m:
        try:
            m.notify_hub_event(bot, etype, ref)
        except Exception:
            pass


def emit(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


# ── 수요측 가드 (판정 단일 지점 — dispatch·dry-run 공용) ────────────────────

def _opt(pol, key):
    v = pol.get(key)
    return v if v else OPTIONAL_POLICY_DEFAULTS[key]


def work_key(prj, ident, role) -> tuple:
    """prj3#Issue755 — «같은 일» 의 판정 키 `(prj, 정규화 식별자, 직능)`.

    직능을 넣는 이유: 한 이슈를 lead·planner·advisor·qa·contractor 가 나눠 받는 **단계 분업**은
      서로 다른 일이다 — 종전 설계가 «Issue415 7회 루프» 로 읽은 것이 실측상 이것이었다.
    식별자는 NFKC·소문자·공백/구두점 접기로 정규화한다 — 표기만 다른 재배분을 새 일로 오판하지 않는다.
    """
    s = unicodedata.normalize("NFKC", ident or "").lower()
    return (prj, re.sub(r"[\W_]+", " ", s).strip(), role or "")


def _verify_breaker_ack(con, ack_id: str, counted: list) -> str:
    """prj3#Issue952 — 서킷브레이커 «원인 확정 후 해제» 증적 검증. 통과면 "", 아니면 거부 사유.

    ack 배분 = kind fbot_dispatch·done · 셈에 든 가장 오래된 실패 이후 생성 · issue/topic/`parent_dispatch_id` 가
    셈에 든 실패 id(전체 또는 꼬리 8자리)를 참조. 배분자 일치는 요구하지 않는다(조사는 보통 총괄 명의).
    """
    row = con.execute("SELECT status, payload, created_at FROM job WHERE kind = ? AND id = ?",
                      (JOB_KIND, ack_id)).fetchone()
    if not row:
        return f"{ack_id} 는 배분 기록에 없다"
    if row["status"] != "done":
        return f"{ack_id} 는 done 이 아니다({row['status']}) — 조사 배분이 끝나야 증적이다"
    if row["created_at"] <= min(c["created_at"] for c in counted):
        return f"{ack_id} 는 셈에 든 가장 오래된 실패보다 먼저 만든 배분이다 — 원인 확정 증적이 아니다"
    try:
        pl = json.loads(row["payload"] or "{}")
    except (TypeError, ValueError):
        pl = {}
    text = " ".join(str(pl.get(k) or "") for k in ("issue", "topic", "parent_dispatch_id"))
    ids = [c["id"] for c in counted]
    if not any(i in text or i.rsplit("-", 1)[-1] in text for i in ids):
        return f"{ack_id} 의 issue/topic/parent_dispatch_id 가 셈에 든 실패 id({', '.join(ids)})를 참조하지 않는다"
    return ""


def judge_demand_guard(con, pol, actor: str = "", ident: str = "", prj=None, role=None,
                       now: int | None = None, breaker_ack: str | None = None) -> dict:
    """수요측 폭주 가드. HR 공급측 가드(세션 수)와 2중 차단 — 계약 §조직.

    ⓐ 동시 배분 상한 — 전역 + 배분자별 (활성 open fbot_dispatch job 수) — **자원** 한계
    ⓑ 같은 일 반복 — 같은 일 키(prj·식별자·직능)를 창 안에 N회 넘게 배분하지 않는다
    ⓒ 연속 실패 서킷브레이커 — 배분자의 창 안 최근 N건이 전부 reaped/cancelled 면 정지
    ⓓ 되풀이 속도 — 배분자가 최근 1시간에 «이미 배분한 일» 을 다시 보낸 수
    ⓔ 배분자 백스톱 — 배분자의 최근 1시간 전체 배분 수(새 일처럼 보이는 연발을 받친다)

    prj3#Issue696 — **월 배분 상한은 차단하지 않는다**(알림 전용 — `cmd_dispatch` 가 도달 시 mq).
      월 누적은 폭주와 정상 몰림을 구별하지 못해, 9월에만 세 번 상향됐다(30→60→70→100).
    prj3#Issue755 — **폭주 판별은 건수가 아니라 «같은 일의 되풀이»** 다. 종전 ⓓ 는 배분자·일과
      무관한 전역 1시간 건수(20)라 도입 이튿날부터 팬아웃(9/27 prj 20곳)·테스트 웨이브(9/28)가
      한도를 채워 남의 정상 배분까지 막았다. 원장 248건 중 238건이 서로 다른 일이었고 속도형
      폭주는 0건이었다 — 새 일로 퍼지는 것은 팬아웃이고, 자원 한계는 ⓐ 가 이미 막는다.
    """
    now = int(now if now is not None else time.time())
    month = month_key(now)
    m_limit = pol["fbot_dispatch_monthly_limit"]
    spent = dispatched_this_month(con, month)
    c_limit = pol["fbot_dispatch_concurrent_limit"]
    active = [j for j in active_dispatches(con) if j["status"] == "open"]

    # prj3#Issue613 — ⓒ **유령은 슬롯을 먹지 않는다.** 워커가 대장에 없으면 `sweep` 이
    #   영원히 못 닫아 슬롯을 무기한 점유한다(실측: `fbot-taskmgr-claude` 배분이 4일 점유).
    #   상한은 *지금 도는 몸체* 를 세려는 것이지 닫히지 않는 기록을 세려는 것이 아니다.
    known = {r[0] for r in con.execute("SELECT bot_id FROM bot")}
    ghosts = [j for j in active
              if (j.get("payload") or {}).get("worker_bot_id") not in known]
    active = [j for j in active if j not in ghosts]

    # prj3#Issue613 — ⓐ **축을 가른다.** 종전에는 상위→하위와 하위→더하위가 같은 전역
    #   카운터를 써서, *내가 일을 받았다는 사실이 내가 일을 내려보낼 슬롯을 먹었다*.
    #   Issue612 가 배분을 **의무**로 만든 뒤 이 충돌이 상시화됐다(팀장이 qa 에 배분하려는
    #   순간 거부 — 규칙이 요구하는 행동을 게이트가 막는다). 폭주 가드의 취지는
    #   *"동시에 몇 개의 몸체가 도는가"* 이므로 **배분자별 상한 + 전역 상한** 2단이면 취지가 산다.
    by = _opt(pol, "fbot_dispatch_actor_limit")
    actor = actor or ""
    # prj3#Issue688 — 배분자는 **`job.owner`** 가 정본이다(`dispatch` 가 owner 에만 쓴다).
    #   종전에는 payload.by 를 읽어 실측 전건이 None → 이 상한이 한 번도 발동하지 않았다.
    mine = [j for j in active if j.get("owner") == actor] if actor else []
    if actor and len(mine) >= by:
        raise Reject(2, f"배분자 동시 상한 도달 — {actor} 의 활성 배분 {len(mine)}건 ≥ 상한 {by}건. "
                        f"자기 배분을 먼저 sweep/cancel 하거나 상한(fbot_dispatch_actor_limit)을 조정한다")
    if len(active) >= c_limit:
        raise Reject(2, f"동시 배분 상한 도달 — 활성 배분 {len(active)}건 ≥ 상한 {c_limit}건"
                        + (f" (유령 {len(ghosts)}건은 제외했다)" if ghosts else ""))

    # ── 패턴 가드 (prj3#Issue696) — 창 안의 배분 기록 전체(종결 포함)를 본다 ──
    win_h = _opt(pol, "fbot_dispatch_pattern_window_hours")
    recent = [dict(r) for r in con.execute(
        "SELECT id, status, payload, result, owner, created_at FROM job"
        " WHERE kind = ? AND created_at >= ? ORDER BY created_at DESC",
        (JOB_KIND, now - win_h * 3600))]
    for r in recent:
        try:
            r["payload"] = json.loads(r["payload"] or "{}")
        except (TypeError, ValueError):
            r["payload"] = {}
        r["result"] = _json_or_empty(r["result"])

    # prj3#Issue755 — 창 안 기록을 오래된 것부터 훑어 «되풀이»(앞선 같은 일 키가 창 안에 있음)를
    #   표시한다. 창 밖 선행은 보지 않는다 — 하루 지난 재배분은 새 라운드다(ⓑ 와 같은 창).
    seen = set()
    for r in reversed(recent):                       # recent 는 DESC
        p = r["payload"]
        k = work_key(p.get("prj"), p.get("issue"), p.get("role"))
        r["repeat"] = k in seen
        seen.add(k)
    key = work_key(prj, ident, role)
    is_repeat = bool(ident) and key in seen
    hour = [r for r in recent if r["created_at"] >= now - 3600]
    last_hour = len(hour)   # 전역 — 관측값일 뿐 판정에 쓰지 않는다(Issue755)

    # ⓑ 같은 일 반복 — 한 일을 창 안에 r_limit 번 배분했으면 거부. 식별자가 없으면 건너뛴다.
    #   prj3#Issue755 — 키에 직능을 넣었다. 종전(prj·식별자)은 5단계 정상 파이프라인도 막았다.
    r_limit = _opt(pol, "fbot_dispatch_issue_repeat_limit")
    same = 0
    if ident:
        same = sum(1 for r in recent
                   if work_key(r["payload"].get("prj"), r["payload"].get("issue"),
                               r["payload"].get("role")) == key)
        if same >= r_limit:
            raise Reject(1, f"같은 일 재배분 상한 도달 — prj{prj} '{ident[:60]}'({role or '-'}) 를 "
                            f"최근 {win_h}시간에 {same}건 배분했다(상한 {r_limit}). 반복 원인을 사람이 판단한다")

    # ⓓ 되풀이 속도 — 여러 일을 돌아가며 다시 보내는 루프(키마다 ⓑ 미달)를 잡는다. **이번 배분이
    #   되풀이일 때만** 막는다 — 같은 배분자라도 새 일은 새 수요다. 남의 되풀이는 세지 않는다.
    rep_limit = _opt(pol, "fbot_dispatch_repeat_hourly_limit")
    reps = sum(1 for r in hour if r["owner"] == actor and r["repeat"]) if actor else 0
    if actor and is_repeat and reps >= rep_limit:
        raise Reject(1, f"되풀이 속도 상한 도달 — {actor} 가 최근 1시간에 이미 배분한 일을 다시 보낸 것이 "
                        f"{reps}건이다(상한 {rep_limit}). 같은 일을 도는 루프인지 확인한다 — "
                        f"새 일은 이 가드에 걸리지 않는다(fbot_dispatch_repeat_hourly_limit)")

    # ⓔ 배분자 백스톱 — 문구만 바꿔 새 일처럼 보이는 연발을 받친다. 배분자 동시 상한(ⓐ) 아래에서
    #   이 수에 닿으려면 몸체 평균 수명이 60×동시/백스톱 분 이하여야 한다 — 정상 작업의 모양이 아니다.
    #   **배분자별**이다(Issue613 교훈): 한 배분자(테스트 포함)의 연발이 남의 배분을 막지 않는다.
    a_limit = _opt(pol, "fbot_dispatch_actor_hourly_limit")
    mine_hour = sum(1 for r in hour if r["owner"] == actor) if actor else 0
    if actor and mine_hour >= a_limit:
        raise Reject(2, f"배분자 시간당 백스톱 도달 — {actor} 가 최근 1시간 {mine_hour}건 배분(상한 {a_limit}). "
                        f"서로 다른 일이라도 이 속도면 몸체가 비정상적으로 빨리 끝나고 있다 — 문구만 바꾼 "
                        f"루프인지 확인한다. 다른 배분자는 막지 않는다(fbot_dispatch_actor_hourly_limit)")

    # ⓒ 연속 실패 — 배분자의 창 안 최근 N건이 전부 실패면 정지. done 1건이면 끊기고,
    #   창을 벗어나면 자동 해제된다(사람이 원인을 고칠 시간). 진행 중(open 등)은 세지 않는다.
    #   prj3#Issue819 — hub 원클릭 회수분(`RECLAIM_CALLERS`)은 세지도 끊지도 않는다. 원장 청소이지
    #   스폰·lease 결함의 신호가 아니다(2026-09-29 실측: 회수 5건이 팀장 배분을 막았다).
    f_limit = _opt(pol, "fbot_dispatch_fail_streak_limit")
    streak = 0
    counted = []
    ack_used = None
    if actor:
        for r in recent:
            if r["owner"] != actor:
                continue
            # prj3#Issue952 — breaker_ack 로 열린 배분은 상태와 무관하게 연속을 끊는다(그 뒤 새 3연속은 재차단)
            if r["payload"].get("breaker_ack"):
                break
            # prj3#Issue788_2 — reap 이 이슈 미완료 배분을 `reaped` 대신 `blocked(worker_died)` 로 둔다. lease 사망이라는
            #   신호는 같으므로 reap 발은 실패로 센다(회수 발 worker_died 는 청소라 세지 않는다 — `RECLAIM_CALLERS`)
            died = (r["status"] == "blocked" and r["payload"].get("blocked_by") == "worker_died"
                    and (r["payload"].get("worker_died") or {}).get("by") == "reap")
            if not died and r["status"] not in FAIL_STATUSES + ("done",):
                continue
            if r["status"] == "cancelled" and r["result"].get("cancelled_by") in RECLAIM_CALLERS:
                continue
            # prj3#Issue952 — 정상 게이트 차단 취소(gate_failed)는 스폰·lease 결함 신호가 아니다
            if r["status"] == "cancelled" and r["result"].get("verdict") in BREAKER_EXEMPT_VERDICTS:
                continue
            if r["status"] == "done":
                break
            streak += 1
            counted.append(r)
        if streak >= f_limit:
            if breaker_ack:
                why = _verify_breaker_ack(con, breaker_ack, counted)
                if why:
                    raise Reject(2, f"--breaker-ack 거부 — {why}")
                ack_used = breaker_ack
            else:
                raise Reject(1, f"연속 실패 서킷브레이커 — {actor} 의 최근 배분 {streak}건이 연달아 "
                                f"reaped/cancelled 다(상한 {f_limit}). 스폰·lease 결함부터 확인한다. "
                                f"{win_h}시간 창을 벗어나거나 done 이 생기면 자동 해제. 원인 조사가 끝났다면 "
                                f"그 조사 배분(done)을 `dispatch --breaker-ack <job_id>` 로 연결해 푼다")

    return {"month": month, "spent": spent, "monthly_limit": m_limit,
            "monthly_over": spent >= m_limit,
            "active": len(active), "concurrent_limit": c_limit,
            "actor": actor, "actor_active": len(mine), "actor_limit": by,
            "ghosts_excluded": len(ghosts),
            "last_hour": last_hour, "repeat": is_repeat,
            "repeat_last_hour": reps, "repeat_hourly_limit": rep_limit,
            "actor_last_hour": mine_hour, "actor_hourly_limit": a_limit,
            "issue_repeat": same, "issue_repeat_limit": r_limit,
            "fail_streak": streak, "fail_streak_limit": f_limit, "breaker_ack": ack_used}


# ── mq alert 발신 (helper 경유 — 제안까지만, 사람 응답 대기) ────────────────

def mq_alert(message: str) -> str:
    """aoa-mq 에 alert 등록. 직접 큐 파일 Write 금지 — helper 경유만.

    사람 판단이 필요한 **이벤트**(watch 적체 에스컬레이션·쿼터 차단·월 배분 기준 도달·
    «완료 미확인» 통지 포기 — prj3#Issue947)의 발신구다. 완료(sweep)는 로그라 여기로 오지 않는다(prj3#Issue750). 여기서 끝이다 —
    등록된 건의 후속 처리(`[컨펌]` ACK 포함)는 사람 몫이다(계약 §호출 경계).
    ⚠️ 호출측은 **건당 1회가 아니라 묶음 1회**로 부른다 (Issue399 규약: 통지 1회·묶음).
    """
    if not os.path.exists(MQ_ENQUEUE_SH):
        raise FbotError(f"aoa-mq enqueue helper 없음: {MQ_ENQUEUE_SH}")
    # prj3#Issue947 — 상한 MQ_ALERT_TIMEOUT_S. helper 를 새 세션(프로세스 그룹)으로 띄워 넘으면 그룹째 끊는다 —
    #   `run(timeout=)` 만으로는 helper 의 자식이 출력 파이프를 쥔 채 남아 회수 대기가 끝나지 않는다
    proc = subprocess.Popen(
        # from_bot 전용 필드 사용 (s4 표준 — source 는 helper 기본값 유지, 봇 귀속은 from_bot)
        [MQ_ENQUEUE_SH, "--message", message, "--alert", "--source", BOT_ID, "--from-bot", BOT_ID],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True,
    )
    try:
        out, err = proc.communicate(timeout=MQ_ALERT_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            proc.kill()
        proc.communicate()
        raise FbotError(f"에스컬레이션 enqueue 시간 초과({MQ_ALERT_TIMEOUT_S}초) — helper 를 끊었다")
    if proc.returncode != 0:
        raise FbotError(
            f"에스컬레이션 enqueue 실패(exit {proc.returncode}): "
            f"{(err or out).strip()}"
        )
    return out.strip()


# ── 완료 감지·통지 (Issue438 ④ — 상태 전이 시점 통지) ──────────────────────

# 완료 판정(`ISSUE_HASH_RE`·`issue_completed_in`)은 공유 모듈 lib/issue-completion.py 한 곳이다 (prj3#Issue944).
#   `sh/issue-tx.py` 의 완료 표기 경고가 sweep 과 같은 판정을 쓰도록 뽑았다 — 규칙과 근거(prj3#Issue693_2·790)는 그쪽.
#   이 모듈의 이름은 그대로 내보낸다 — fbot-state(`lead.issue_completed_in`)·테스트 대역 주입(`m.issue_completed_in = …`)이 쓴다.
#   적재는 **처음 쓸 때** 한다(fbot-ident·selection 과 같은 방식) — lib 가 깨져도 완료 판정을 안 쓰는 서브커맨드와
#   fbot-state `_lead_mod()`(적재 실패를 삼키고 worker_died 재배분을 끈다)가 함께 죽지 않게 한다.
_ISSUE_COMPLETION = None


def _issue_completion():
    global _ISSUE_COMPLETION
    if _ISSUE_COMPLETION is None:
        import importlib.util
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib/issue-completion.py")
        spec = importlib.util.spec_from_file_location("fbot_issue_completion", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _ISSUE_COMPLETION = mod
    return _ISSUE_COMPLETION


def issue_completed_in(cwd, issue):
    return _issue_completion().issue_completed_in(cwd, issue)


def __getattr__(name):   # PEP 562 — `lead.ISSUE_HASH_RE` 도 지연 적재로 내보낸다
    if name == "ISSUE_HASH_RE":
        return _issue_completion().ISSUE_HASH_RE
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _json_or_empty(text) -> dict:
    try:
        v = json.loads(text or "{}")
    except (ValueError, TypeError):
        return {}
    return v if isinstance(v, dict) else {}


def session_token_usage(payload: dict) -> dict:
    """워커 세션의 **Claude 쪽** 토큰 합계 — 배분 완료 기록에 싣는다 (prj3#Issue699_2).

    왜 — 비용 원장(`data/codex/usage.jsonl`)에는 codex 토큰만 남아 «외부에 맡겨 얼마나
    아꼈나» 를 잴 반대편 숫자가 없었다. 세션 기록(`fbot_session.payload.session_id`)으로
    transcript 를 찾아 assistant 메시지 usage 를 더한다.
    ⚠️ 스트리밍은 같은 `message.id` 를 content block 마다 되풀이한다 — id 로 한 번만 센다.
    ⚠️ agent 형태(`source=agent-done`)는 session_id 가 **부모** 세션이라 분리할 수 없다 —
       부모 합계를 워커 몫으로 적으면 거짓이므로 `unmeasured` 로 남긴다.
    반환 status: ok · missing(transcript 없음) · unmeasured(측정 불가 — reason 동반).
    """
    sid = (payload or {}).get("session_id") or ""
    if not sid:
        return {"status": "unmeasured", "reason": "세션 기록에 session_id 없음"}
    if (payload or {}).get("source") == "agent-done":
        return {"status": "unmeasured", "reason": "agent 형태 — session_id 가 부모 세션이라 분리 불가"}
    root = os.environ.get("FBOT_TRANSCRIPT_ROOT") or os.path.expanduser("~/.claude/projects")
    hits = glob.glob(os.path.join(glob.escape(root), "*", glob.escape(sid) + ".jsonl"))
    if not hits:
        return {"status": "missing", "session_id": sid}
    seen, counted, tot = set(), 0, {"input": 0, "output": 0, "cache_creation": 0, "cache_read": 0}
    try:
        with open(hits[0], encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                msg = d.get("message") if isinstance(d, dict) else None
                u = msg.get("usage") if isinstance(msg, dict) else None
                if not isinstance(u, dict):
                    continue
                mid = msg.get("id")
                if mid:
                    if mid in seen:
                        continue
                    seen.add(mid)
                tot["input"] += int(u.get("input_tokens") or 0)
                tot["output"] += int(u.get("output_tokens") or 0)
                tot["cache_creation"] += int(u.get("cache_creation_input_tokens") or 0)
                tot["cache_read"] += int(u.get("cache_read_input_tokens") or 0)
                counted += 1
    except OSError as e:
        return {"status": "unmeasured", "reason": f"transcript 읽기 실패: {e}"}
    if not counted:
        # 파일은 찾았는데 usage 가 1건도 없다 — 0 토큰이 아니라 **측정 실패**다(codex 3회차 medium)
        return {"status": "unmeasured", "reason": "transcript 에 usage 행 없음", "session_id": sid}
    return {"status": "ok", **tot, "total": sum(tot.values()), "messages": counted}


def detect_completions(con: sqlite3.Connection) -> list:
    """미종결 배분 중 **완료된 것**을 골라낸다 — `detect_closures` 의 completed 만.

    판정(계약 Issue438 ④): 배분의 워커 봇이 `checkout` 이고, 그 봇 귀속
    `fbot_session` job(status=done — 퇴근 훅이 남긴다)이 **배분 생성 이후**에
    존재하면 배분 완료다.

    ⚠️ `created_at >= 배분 시각` 조건이 핵심이다 — 같은 bot_id 로 재배분한 경우
    직전 배분의 낡은 세션 기록이 새 배분을 완료로 오판하는 것을 막는다.
    ⚠️ reap(lease 만료 강제 퇴근)은 세션 기록을 남기지 않는다 — 즉 **퇴근 상태만으로는
    완료가 아니다**. 그 경우는 watch 의 적체 B 판정으로 남는다(오판 금지).
    🔧 prj3#Issue929 — topic 배분은 퇴근만으로 완료가 아니다. 산출 증적(`topic_evidence`)이 없으면
    «완료 미확인»(`verdict: unconfirmed`)이라 여기서는 빠진다 — brief «완료 감지» 가 그것을 완료로 세지 않게.
    """
    return [c for c in detect_closures(con) if c["verdict"] == "completed"]


# prj3#Issue929 — blocked 하위 사유: 워커는 퇴근(세션 done)했으나 topic 배분의 산출 증적이 없다.
#   `question`(Issue749)·`worker_died`(prj3#Issue788_2) 와 같은 축이다 — WIP 미점유(호출측 `open` 필터)·watch 적체 B 밖(open 만)·
#   매니저 부모 보류(`CHILD_LIVE`)·`close`/`cancel` 로 정리. 증적이 뒤늦게 오면 다음 sweep 이 completed 로 올린다.
#   어휘(`unconfirmed`·보고 status)는 fbot-state 단일 지점을 읽는다 — `_unconfirmed()`·`_report_statuses()`
REQUEST_KIND = "fbot_request"            # fbot-inbox.py KIND — 워커 상향 보고(defer)가 실리는 원장 kind
HASH_PROBE_MAX = 12                      # 배분 1건당 커밋 대조 상한 — 미확인 배분은 sweep 마다 재평가된다
GIT_PROBE_SECS = 5


def worker_reports(con: sqlite3.Connection, job: dict, since: int) -> list:
    """배분 `job` 에 대한 **워커의 상향 보고** — `since` 이후, 생성 순 (prj3#Issue929).

    짝 = 인박스 `fbot_request` 중 `from` = 워커 · (`corr_id` = 배분 id 또는 `dispatch_id` = 배분 id). defer 는 활성 배분 id 를
    `corr_id` 로 달고, 기원 요청으로 간 보고는 `dispatch_id` 로 잇는다(fbot-inbox `defer`). `nodelegate_records` 와 같은 짝이다.
    질문(`question`)은 진행 중 결정 요구라 완료 보고가 아니다.
    """
    wid = (job.get("payload") or {}).get("worker_bot_id")
    if not wid:
        return []
    out = []
    skip = ("question", _unconfirmed())
    for r in con.execute(
            "SELECT id, payload, created_at FROM job WHERE kind = ? AND created_at >= ?"
            " AND json_extract(payload, '$.from') = ?"
            " AND (json_extract(payload, '$.corr_id') = ? OR json_extract(payload, '$.dispatch_id') = ?)"
            " ORDER BY created_at, rowid", (REQUEST_KIND, since, wid, job["id"], job["id"])).fetchall():
        pl = _json_or_empty(r["payload"])
        if pl.get("kind") in skip:
            continue
        out.append({"id": r["id"], "at": r["created_at"], "body": str(pl.get("body") or ""),
                    "status": pl.get("report_status")})
    return out


def _git_env() -> dict:
    """상속된 GIT_DIR 류를 걷은 env — 훅 안에서 불리면 호출측 repo 를 가리킨다."""
    return {k: v for k, v in os.environ.items() if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")}


def _git_fail(e) -> str:
    if isinstance(e, subprocess.TimeoutExpired):
        return f"시간 초과 {GIT_PROBE_SECS}s"
    return f"{type(e).__name__}: {e}"[:120]


def _git_probe(cwd: str):
    """`cwd` 가 git 으로 **조회되는가** — `(True, None)` 또는 `(False, 사유)` (prj3#Issue929 검토 ⑤).
    비repo·safe.directory 거부(dubious ownership)·시간 초과·git 부재를 «해시가 repo 에 없다» 와 가른다 —
    둘을 한 문구로 내면 매니저가 «워커가 거짓 해시를 냈다» 로 오진한다."""
    try:
        r = subprocess.run(["git", "-C", os.path.expanduser(cwd), "rev-parse", "--git-dir"],
                           capture_output=True, text=True, timeout=GIT_PROBE_SECS, env=_git_env())
    except (OSError, subprocess.SubprocessError) as e:
        return False, _git_fail(e)
    if r.returncode != 0:
        msg = (r.stderr or "").strip().splitlines()
        return False, (msg[-1] if msg else f"rc={r.returncode}")[:120]
    return True, None


def _commit_time(cwd: str, h: str):
    """`cwd` repo 의 커밋 `h` 시각 — 반환 `(epoch | None, 조회 실패 사유 | None)`.
    `(None, None)` = 조회는 됐고 그 커밋이 없다(rc≠0). `(None, 사유)` = 시간 초과·실행 실패·출력 해석 불가 — 판정 불가다."""
    try:
        r = subprocess.run(["git", "-C", os.path.expanduser(cwd), "show", "-s", "--format=%ct", h + "^{commit}", "--"],
                           capture_output=True, text=True, timeout=GIT_PROBE_SECS, env=_git_env())
    except (OSError, subprocess.SubprocessError) as e:
        return None, _git_fail(e)
    if r.returncode != 0:
        return None, None
    try:
        return int(r.stdout.strip().splitlines()[-1]), None
    except (ValueError, IndexError):
        return None, f"출력 해석 불가: {r.stdout.strip()[:60]!r}"


def _fresh_path(path: str, cwd: str, since: int) -> bool:
    """선언 산출이 실재하고 배분(재개·reopen) 이후 갱신됐는가 — 전부터 있던 파일은 이번 산출이 아니다."""
    p = os.path.expanduser(path)
    if not os.path.isabs(p) and cwd:
        p = os.path.join(os.path.expanduser(cwd), p)
    try:
        mtime = os.path.getmtime(p)
    except OSError:
        return False
    # prj3#Issue959 ② — 추적·무변경 파일의 내용은 **마지막 커밋** 때 정해졌다. mtime 은 checkout·restore 로도 움직이고(정방향 오인),
    #   reopen 전에 쓰고 뒤에 커밋한 산출은 mtime 이 낡아 보인다(역방향 오인 — `1a7060b8`). 추적·수정 중·미추적·git 실패는 종전 mtime.
    d, name = os.path.dirname(p) or ".", os.path.basename(p)
    try:
        def _git(*a):
            return subprocess.run(["git", "-C", d, *a], capture_output=True, text=True, timeout=GIT_PROBE_SECS, env=_git_env())
        if _git("ls-files", "--error-unmatch", "--", name).returncode == 0:
            st = _git("status", "--porcelain", "--", name)
            if st.returncode == 0 and not st.stdout.strip():
                lg = _git("log", "-1", "--format=%ct", "--", name)
                if lg.returncode == 0 and lg.stdout.strip():
                    return int(lg.stdout.strip().splitlines()[-1]) >= since
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    return mtime >= since


def done_evidenced(status, payload, result) -> bool:
    """`done` 이 **증적 있는 완료**인가 — 미룬 배분 승격(`promote_deferred`)의 판정 단일 지점 (prj3#Issue929 ②).

    topic 배분은 `result.evidence` 가 있어야 한다 — sweep 은 증적을 찾아야 completed 로 닫고(`topic_evidence`),
    `close` 는 `--evidence` 를 강제한다. 증적 없는 topic done(Issue929 이전 sweep 이 남긴 거짓 완료 포함)은 승격 근거가 아니다.
    이슈 배분·구 기록(ident_kind 없음)·사후 기록은 종전대로 done 이면 충분하다 — 이슈 완료 대조가 독립 증거다.
    """
    if status != "done":
        return False
    pl = payload if isinstance(payload, dict) else _json_or_empty(payload)
    if pl.get("ident_kind") != "topic":
        return True
    res = result if isinstance(result, dict) else _json_or_empty(result)
    return bool(res.get("evidence"))


def topic_evidence(con: sqlite3.Connection, job: dict, since: int, closing=frozenset()):
    """topic 배분의 **산출 증적** — 판정 단일 지점 (prj3#Issue929 ①). 반환 `(evidence | None, 사유)`.
    `closing` = 이번 sweep 에서 이미 completed 로 판정된 배분 id(`detect_closures`) — ⓔ 가 아직 커밋 전(open)인 자식을 센다.

    왜 필요한가 (2026-10-04 실측 Issue823 ③): topic 배분은 대조할 이슈가 없어 «워커 퇴근 + 세션 done» 만으로
      completed 가 됐다. 워커가 «완료하지 못했다» 고 보고하고 퇴근해도 done 이었고(`fbotdisp-1791105699-e4ca5e1d`·
      `…8e2b6ddc`), 그 done 이 미룬 배분을 조기 승격했다(`…f95b5876`). 산출 deck-review.md 는 끝내 없었다.
    판정 (앞에서부터, 처음 걸리는 것):
      ⓐ 워커 보고의 **명시 status**(`defer --status`) 중 마지막이 done 이 아니면 미확인 — 워커 본인의 말이 가장 강하다
      ⓑ 배분이 산출을 선언했으면(`dispatch --expect PATH`) 전부 실재·배분 뒤 갱신이어야 한다 — 계약이라 회신·해시로 메우지 못한다
      ⓒ 명시 status=done → 증적(report)
      ⓓ 보고 본문의 커밋 해시가 대상 repo 에 있고 **커밋 시각 ≥ since** → 증적(commit). 배분 전 커밋은 선례 인용이다
      ⓔ 매니저 배분 — 하위 배분 중 증적 있는 done(또는 **이번 회차 completed** = `closing`)이 있으면 증적(children).
         자식이 남아 있으면 애초에 보류된다(Issue781). 자식이 같은 회차에 닫히면 DB 는 아직 open 이라 `closing` 이 그것을 센다
    ⚠️ 본문에 적힌 **경로**는 증적이 아니다 — 실측 «미완» 보고도 `.md.draft` 를 언급했다. 산출 경로는 `--expect` 로 선언한다.
    ⚠️ `EVIDENCE_HASH_RE` 는 fbot id 의 hex 꼬리(`fbotreq-…-c59ad182`)도 잡는다 — repo 대조가 그것을 거른다.
    사유는 «git 조회 실패»(비repo·safe.directory·시간 초과)·«repo 에 없거나 배분 전 커밋»·«해시 없음» 을 가른다(검토 ⑤).
    """
    pl = job.get("payload") or {}
    reps = worker_reports(con, job, since)
    stated = [r for r in reps if r["status"] in _report_statuses()]
    last = stated[-1] if stated else None
    if last and last["status"] != "done":
        return None, f"워커 회신 status={last['status']} ({last['id']})"
    expect = [p for p in (pl.get("expect") or []) if isinstance(p, str) and p]
    if expect:
        missing = [p for p in expect if not _fresh_path(p, pl.get("cwd") or "", since)]
        if missing:
            return None, "선언 산출 부재·배분 뒤 갱신 없음: " + ", ".join(missing[:3])
        return {"kind": "expect", "paths": expect}, ""
    if last:
        return {"kind": "report", "request_id": last["id"]}, ""
    cwd = pl.get("cwd")
    hashes, seen = [], set()   # 최근 보고부터 — (해시, 보고 id)
    for r in reversed(reps):
        for h in EVIDENCE_HASH_RE.findall(r["body"]):
            if h.lower() in seen or len(hashes) >= HASH_PROBE_MAX:
                continue
            seen.add(h.lower())
            hashes.append((h, r["id"]))
    git_err = None
    if cwd and hashes:
        ok, git_err = _git_probe(cwd)
        if ok:
            for h, rid in hashes:
                ct, err = _commit_time(cwd, h)
                if err:
                    git_err = err   # 판정 불가 — «없다» 로 단정하지 않는다. 같은 원인이 반복될 것이라 더 묻지 않는다
                    break
                if ct is not None and ct >= since:
                    return {"kind": "commit", "hash": h, "request_id": rid}, ""
    if _is_nonexec(pl.get("role")):
        kids = [r["id"] for r in con.execute(
            "SELECT id, status, payload, result FROM job WHERE kind = ?"
            " AND json_extract(payload, '$.parent_dispatch_id') = ?", (JOB_KIND, job["id"])).fetchall()
            if r["id"] in closing or done_evidenced(r["status"], r["payload"], r["result"])]
        if kids:
            return {"kind": "children", "dispatches": kids[:10]}, ""
    if not reps:
        return None, "워커 보고 없음"
    if hashes:
        if not cwd:
            return None, "배분 cwd 없음 — 보고의 커밋 해시를 대조할 repo 를 모른다"
        if git_err:
            return None, f"커밋 대조 불가 — git 조회 실패({git_err})"
        return None, f"보고의 커밋 해시 {len(hashes)}개가 대상 repo 에 없거나 배분 전 커밋이다"
    return None, "보고에 증적 없음 — 명시 status·선언 산출·커밋 해시 없음(본문 경로는 증적 아님)"


def _dispatch_since(job: dict) -> int:
    """배분의 **증거 시작 시각** — 생성 · 마지막 재개(Issue815) · reopen(Issue929 ③, **topic 배분만**) 중 가장 늦은 것.

    reopen 은 `session_job_id` 를 `reopened_from` 으로 옮겨 claimed 집합에서 빠지게 한다. since 가 생성 시각 그대로면
    거짓 완료를 낸 바로 그 세션이 다시 증거가 돼 재종결됐다 — topic 배분은 reopen 이전의 세션·보고를 증거에서 뺀다.
    ⚠️ 이슈 배분에는 걸지 않는다(검토 ②) — 완료 섹션 대조가 독립 증거라 세션은 «워커가 퇴근했다» 는 것만 말한다.
      reopen 시각을 걸면 이슈가 이미 완료인 배분(reaped 뒤 reopen 실측 형태)이 새 세션 전까지 영구 open 이 된다.
      구 기록(ident_kind 없음)도 종전 그대로다(소급 판정 변경 없음 — 같은 세션으로 재종결될 수 있다).
    """
    pl = job.get("payload") or {}
    res = _json_or_empty(job.get("result")) if not isinstance(job.get("result"), dict) else job["result"]
    reopened = int(res.get("reopened_at") or 0) if pl.get("ident_kind") == "topic" else 0
    return max([job["created_at"], reopened]
               + [h.get("resumed_at") or 0 for h in pl.get("defer_history") or []])


def detect_closures(con: sqlite3.Connection, exclude=()) -> list:
    """미종결 배분 중 **워커 퇴근으로 닫을 후보** — `verdict` 로 completed·unconfirmed 를 가른다 (prj3#Issue929).

    completed = 종전 완료(이슈 배분은 완료 섹션 대조, topic 배분은 산출 증적 `topic_evidence`, 구 기록은 세션).
    unconfirmed = topic 배분인데 증적이 없다 — sweep 이 `blocked(unconfirmed)` 로 두고 defer 와 같은 상향 사슬의 매니저 인박스에 올린다.
    이미 `blocked(unconfirmed)` 인 배분은 재평가해 증적이 생겼을 때만 completed 로 낸다(여기서는 다시 내지 않는다 — 실패한 통지의 재시도는 sweep `unnotified_unconfirmed` 몫).
    `exclude` = 판정에서 뺄 배분 id — 명시 `cancel` 의 대상(취소 직전 sweep 이 그것을 먼저 닫지 않게, Issue929 ③).
      계보 구조(부모 보류·다음 배분 창)에는 남긴다 — 취소가 확정되기 전 부모를 먼저 닫지 않는다.
    """
    found = []
    # 🔴 배분↔세션 1:1 (prj3#Issue751_7) — «배분 이후 가장 최근 세션» 은 배분이 하나일 때만 맞다. 같은 봇에
    #   연속 배분 T1·T2 가 있으면 T2 의 세션 하나가 T1 까지 닫았다(Issue753 실측 fbotjob-1790552419).
    #   배분을 생성 순으로 돌며 ① 이미 다른 배분이 가져간 세션은 빼고 ② 같은 워커의 **다음 배분 생성 전까지**
    #   (그 배분의 창)에서 마지막 세션을 고른다 — 한 배분의 세션이 여럿이면(질문 재개) 종전대로 마지막.
    #   창이 비면(다음 배분이 생긴 뒤에 끝난 세션) 가장 이른 미사용 세션 — 겹친 배분이 영구 미종결로 남지 않게.
    #   남는 세션이 없으면 topic 배분은 닫지 않는다(증거 없음). 이슈 배분은 이슈 완료가 독립 증거라 공유를 허용한다.
    claimed = {
        r["sid"] for r in con.execute(
            "SELECT json_extract(result, '$.session_job_id') AS sid FROM job"
            " WHERE kind = ? AND result IS NOT NULL", (JOB_KIND,)).fetchall()
        if r["sid"]
    }
    active = sorted(active_dispatches(con), key=lambda j: (j["created_at"], j["id"]))
    # prj3#Issue929 — 미확인 배분이 물고 있는 세션은 그 배분 것이다. 다른 배분이 가져가 닫지 못하게 한다
    unconf_claim = {}
    uc = _unconfirmed()
    for j in active:
        jp = j["payload"] or {}
        if j["status"] == "blocked" and jp.get("blocked_by") == uc:
            sid = (jp.get(uc) or {}).get("session_job_id")
            if sid:
                unconf_claim[sid] = j["id"]
    # prj3#Issue781 — 자식이 남은 매니저 배분은 건너뛴다. 자식이 이번 회차에 닫히면 부모도 같은 회차에 닫히도록
    #   고정점까지 반복한다(사슬 깊이만큼 — 한 회차에 새로 잡히는 것이 없으면 끝).
    #   `handled` = 이번 sweep 에서 판정이 끝난 배분 · `closing` = 그중 completed — 부모 보류는 closing 만 푼다
    #   (미확인 자식은 `CHILD_LIVE` 인 blocked 로 남으므로 부모를 닫지 않는다).
    handled, closing = set(exclude), set()
    while True:
        holding = parents_with_live_children(active, closing)
        before = len(found)
        _detect_pass(con, active, claimed, holding, handled, closing, found, unconf_claim)
        if len(found) == before:
            break
    return found


def _detect_pass(con, active, claimed, holding, handled, closing, found, unconf_claim):
    """`detect_closures` 의 한 회차 — 판정 본문(아래 주석은 그대로 계약이다)."""
    for i, job in enumerate(active):
        if job["id"] in handled:
            continue
        if job["status"] == "deferred":
            continue   # prj3#Issue686 — 보류는 완료 후보가 아니다. 재개(`resume`) 후 판정한다
        if job["id"] in holding:
            continue   # prj3#Issue781 — 매니저 배분은 자식 배분이 전부 끝난 뒤에야 완료다(팀장 퇴근 즉시 닫지 않는다)
        if job["status"] == "blocked" and (job["payload"] or {}).get("blocked_by") == "question":
            continue   # prj3#Issue749 — 질문하고 정상 종료한 몸체다. 답이 와서 재개·재기동된 뒤 판정한다
        wid = job["payload"].get("worker_bot_id")
        if not wid:
            continue
        bot = con.execute("SELECT state FROM bot WHERE bot_id = ?", (wid,)).fetchone()
        if bot is None or bot["state"] != "checkout":
            continue
        # prj3#Issue815 — resume 된 배분은 **마지막 재개 이후** 세션만 증거다. 보류 전·보류 중의 세션은 다른 일의 것이다
        #   (실측 `fbotdisp-1790627956-0cbc6cb0` — resume 12초 뒤 resume 전 세션으로 done → 집행 스폰이 그림자 행)
        # prj3#Issue929 ③ — reopen 된 배분은 **reopen 이후** 세션만 증거다(`_dispatch_since`)
        since = _dispatch_since(job)
        rows = con.execute(
            "SELECT id, created_at, payload FROM job"
            " WHERE kind = ? AND status = 'done' AND owner = ? AND created_at >= ?"
            " ORDER BY created_at, id",
            (SESSION_JOB_KIND, wid, since),
        ).fetchall()
        free = [r for r in rows if r["id"] not in claimed and unconf_claim.get(r["id"], job["id"]) == job["id"]]
        nxt = next((j["created_at"] for j in active[i + 1:]
                    if (j["payload"] or {}).get("worker_bot_id") == wid), None)
        in_win = [r for r in free if nxt is None or r["created_at"] < nxt]
        row = in_win[-1] if in_win else (free[0] if free else None)
        if row is None and rows and (job["payload"] or {}).get("ident_kind") == "issue":
            row = rows[-1]   # 이슈 배분 — 아래 이슈 완료 대조가 독립 증거다(한 세션이 이슈 둘을 끝낼 수 있다)
        if row is None:
            continue
        # 🔴 배분 단위 확인 (prj3#Issue644 ⑥ — 2026-09-19 거짓 완료 실발생 대응)
        #   위 판정은 **세션 단위**다. 한 워커가 배분 3건을 물고 있으면 세션 done 기록
        #   하나가 셋 모두를 만족시켜 **끝나지 않은 배분까지 done 으로 닫힌다**.
        #   실측: 배분 639·640·636 이 같은 `fbotjob-…c5791a29` 로 일괄 completed 처리됐고
        #   실제 완료는 639 하나였다. 원장이 «했다» 고 답하니 사람이 사후에 발견해야 했다.
        #   그래서 이슈 배분은 **그 이슈가 실제로 완료 섹션에 있는지**를 따로 본다.
        #   ⚠️ 판정 불가(None)는 미완료로 보지 않는다 — 닫지도 않지만 오탐도 내지 않는다.
        #   🔧 prj3#Issue929 — topic 배분(`ident_kind == "topic"`)은 산출 증적(`topic_evidence`)을 본다. 종전엔 «대조할 대상이
        #   없다» 며 세션만으로 닫았고, 워커 «미완» 회신 뒤 퇴근도 completed 였다. 증적이 없으면 unconfirmed 로 낸다.
        #   ident_kind 가 없는 구 기록·사후 기록(`logged`)은 종전 판정 그대로다(소급 추정 금지).
        pl = job["payload"]
        evidence = None
        if pl.get("ident_kind") == "issue":
            # prj3#Issue761 — 구 기록은 맨 숫자(`727`)다. `727:` 헤더는 없으니 대조가 영원히 미완료였다
            canon = _canon_issue(pl.get("issue") or "")
            verdict = issue_completed_in(pl.get("cwd"), canon)
            if verdict is not True:
                continue
            evidence = {"kind": "issue", "issue": canon}
        elif pl.get("ident_kind") == "topic":
            evidence, why = topic_evidence(con, job, since, closing)
            if evidence is None:
                uc = _unconfirmed()
                claimed.add(row["id"])
                handled.add(job["id"])
                if job["status"] == "blocked" and pl.get("blocked_by") == uc:
                    continue   # 이미 미확인 — 증적이 올 때까지 둔다. 실패한 통지의 재시도는 sweep 몫(`unnotified_unconfirmed`)
                found.append({
                    "verdict": uc, "job_id": job["id"], "from_status": job["status"],
                    "issue": pl.get("issue"), "role": pl.get("role"), "owner": job.get("owner"),
                    "worker_bot_id": wid, "session_job_id": row["id"], "completed_at": row["created_at"],
                    "reason": why,
                })
                continue
        claimed.add(row["id"])
        handled.add(job["id"])
        closing.add(job["id"])
        found.append({
            "verdict": "completed", "job_id": job["id"], "from_status": job["status"],
            "issue": job["payload"].get("issue"), "role": job["payload"].get("role"),
            "worker_bot_id": wid, "session_job_id": row["id"],
            "completed_at": row["created_at"], "evidence": evidence,
            "claude_tokens": session_token_usage(_json_or_empty(row["payload"])),
        })


# prj3#Issue781 — 매니저 배분을 살아 있게 하는 자식 술어. 스펙은 open·blocked·deferred(`logged` 는 사후 기록이라 제외 —
#   Issue815 그림자 행이 부모를 영구 미종결로 만들지 않게).
CHILD_LIVE = ("open", "blocked", "deferred")


def ambiguous_parent_candidates(child: dict, dispatches: list) -> list:
    """모호 자식(`parent_ambiguous`)의 **후보 부모 배분 전부** — 판정 단일 지점 (prj3#Issue781 부수 · Issue827 재사용).

    배분자가 미종결 배분 2건+ 를 물고 있으면 fbot-state `dispatch_lineage` 는 부모를 고르지 않는다. 후보 = `dispatches` 중
    그 배분자(`child.owner`)를 워커로 둔 **매니저(nonexec) 배분** 가운데 자식보다 앞선 것(자기 자신 제외).
    계보가 확정된 자식(`parent_dispatch_id` 있음)이나 모호 표시가 없는 자식은 빈 목록 — 추정하지 않는다.
    레코드 모양은 `active_dispatches` 와 같다(`id`·`owner`·`payload`·`created_at`).
    호출처: `parents_with_live_children`(부모를 늦게 닫는 쪽) · `nodelegate_records`(후보 전부를 «위임» 으로 세는 쪽).
    """
    pl = child.get("payload") or {}
    if pl.get("parent_dispatch_id") or not pl.get("parent_ambiguous"):
        return []
    return [p for p in dispatches
            if p["id"] != child["id"] and _is_nonexec((p.get("payload") or {}).get("role"))
            and (p.get("payload") or {}).get("worker_bot_id") == child.get("owner")
            and p["created_at"] <= child["created_at"]]


def parents_with_live_children(active: list, closing: set = frozenset()) -> set:
    """계보상 **미종결 자식(손자 포함)** 을 둔 매니저(nonexec) 배분의 id 집합 (prj3#Issue781).

    왜 필요한가 (2026-09-29 00:33~00:40 실측, 5분 안에 5건) — 팀장 몸체는 워커에 배분만 하고 턴을 끝낸다
    (defer·checkout). 종전 `detect_completions` 는 «워커 퇴근 + 세션 done» 만 보므로 팀장 배분이 **그 즉시**
    `completed` 로 닫혔다(`fbotdisp-1790609595-186bbebc` — 자식 `…e940fc63` open 인 채). 부모가 먼저 닫히면
    ① 총괄 동시 상한(actor)이 부모만 세어 실효 무력화 ② 부모 종결을 기다리는 상위 수합이 조기 착수 ③ 완료 통지 오판.
    매니저 배분의 «완료» 는 자식이 끝나고 결과가 상향된 뒤다 — 자식 전부 종결 후 **다음 sweep** 에서 닫힌다.

    판정: `payload.parent_dispatch_id` 로 부모→자식을 잇고, 매니저 배분마다 후손을 걸어 `CHILD_LIVE` 인 것이 하나라도
    있으면 잡는다. 계보 기록은 fbot-state `dispatch_lineage` 단일 지점(Issue739) — 여기서는 읽기만 한다.
    구 레코드(계보 없음)는 자식으로 보이지 않으므로 종전 판정 그대로다(소급 추정 금지).
    ⚠️ 워커(비관리직) 배분은 대상이 아니다 — 워커는 배분하지 않으므로 자식이 있을 리 없고, 있어도 종전 판정.
    `closing` 은 **이번 sweep 에서 이미 완료로 잡힌** 배분 — 자식이 이번 회차에 닫히면 부모도 같은 회차에
    닫힌다(총괄 → 팀장 → 워커 사슬이 회차마다 한 층씩 닫히지 않게, `detect_completions` 가 고정점까지 반복).
    """
    kids = {}
    for j in active:
        pid = (j.get("payload") or {}).get("parent_dispatch_id")
        if pid and pid != j["id"]:
            kids.setdefault(pid, []).append(j)
    # 모호 자식 (Issue781 부수 — `parent_ambiguous`) — 배분자가 미종결 배분 2건+ 를 물고 있으면 계보 판정이 고르지 않는다
    #   (fbot-state `dispatch_lineage`). 실측 2026-09-29: 팀장 `fbot-lead-claude` 가 총괄 배분 2건을 동시에 물어 워커
    #   배분 5건이 전부 부모 없음이었다. 고르지 않은 자식은 **후보 전부**(그 배분자를 워커로 둔, 자식보다 앞선 매니저 배분)를
    #   붙잡는다 — 틀린 쪽으로 닫는 것보다 자식이 끝날 때까지 늦게 닫는 것이 안전하다. 원장에 부모를 적지는 않는다(추정 금지).
    for j in active:
        for p in ambiguous_parent_candidates(j, active):
            kids.setdefault(p["id"], []).append(j)
    out = set()
    for j in active:
        if not _is_nonexec((j.get("payload") or {}).get("role")):
            continue
        stack, seen = list(kids.get(j["id"], [])), set()
        while stack:
            k = stack.pop()
            if k["id"] in seen:
                continue
            seen.add(k["id"])
            if k["status"] in CHILD_LIVE and k["id"] not in closing:
                out.add(j["id"])
                break
            stack.extend(kids.get(k["id"], []))
    return out


def last_session_end(con: sqlite3.Connection, wid: str, since: int):
    """워커의 `since` 이후 **마지막 세션 기록**과 그 종료 사유 (prj3#Issue743).

    판정은 하지 않는다 — 퇴근 훅이 `lib/session-end.py` 로 판정해 `fbot_session` 에 적은 것을
    읽기만 한다(판정 단일 지점). 쿼터로 죽은 세션은 `status='failed'` + `payload.end_reason='quota'`.
    구 기록(end_reason 없음)은 `None` 으로 돌려준다 — 모르는 것을 normal 로 지어내지 않는다.
    """
    row = con.execute(
        "SELECT id, status, payload, created_at FROM job"
        " WHERE kind = ? AND owner = ? AND created_at >= ?"
        " ORDER BY created_at DESC, rowid DESC LIMIT 1",
        (SESSION_JOB_KIND, wid, since),
    ).fetchone()
    if row is None:
        return None
    pl = _json_or_empty(row["payload"])
    return {"session_job_id": row["id"], "status": row["status"], "at": row["created_at"],
            "end_reason": pl.get("end_reason"), "resets_at": pl.get("resets_at"),
            "limit_type": pl.get("limit_type"), "error": pl.get("error")}


def _hhmm(epoch) -> str:
    return time.strftime("%H:%M", time.localtime(epoch)) if epoch else "미상"


def session_watermark(con: sqlite3.Connection) -> int:
    """세션 완료 통지 워터마크. 부재 시 **오늘 자정**으로 출발한다.

    왜 0 이 아닌가 — 0 이면 첫 실행에서 과거 전체(누적 세션 기록)를 한꺼번에 알린다.
    왜 '지금'이 아닌가 — 그러면 오늘 이미 끝난 작업을 영영 못 알린다. 자정이 그 사이다.
    """
    row = con.execute("SELECT value FROM kv WHERE ns = ? AND key = ?",
                      (NOTIFY_NS, NOTIFY_SESSION_KEY)).fetchone()
    if row is not None:
        try:
            return int(row["value"])
        except (TypeError, ValueError):
            pass
    return int(time.mktime(time.strptime(time.strftime("%Y-%m-%d"), "%Y-%m-%d")))


def detect_session_completions(con: sqlite3.Connection, watermark: int) -> list:
    """**배분에 매이지 않은** 봇 세션 완료를 골라낸다 (Issue438 ④).

    왜 필요한가 (2026-08-26 실측) — `detect_completions()` 는 `active_dispatches` 만 돈다.
    즉 lead 로 배분된 작업만 완료가 통지된다. 그런데 봇을 fpm-do 로 **직접 위임**하면
    배분 원장에 없으므로, 봇이 일을 끝내도 **아무도 알리지 않는다**. 나래의 prj61 검토가
    정확히 그랬고 사람이 폴링해서야 알았다 — Issue438 이 없애려던 상황 그 자체다.

    계약 ④ 는 "배분 완료·QA 판정 등 **상태 전이 시점**에 통지" 다. 판정의 기준은
    배분 원장이 아니라 **봇이 일을 마쳤는가** 여야 한다.

    중복 방지: 배분 완료는 job status 전이가 구조적 보장이 되지만, 세션 기록은 done 인 채로
    남으므로 워터마크로 막는다. 배분으로 이미 통지된 세션은 `session_job_id` 역참조로 뺀다.
    """
    rows = con.execute(
        "SELECT id, owner, created_at FROM job"
        " WHERE kind = ? AND status = 'done' AND created_at > ?"
        " ORDER BY created_at",
        (SESSION_JOB_KIND, watermark),
    ).fetchall()
    if not rows:
        return []
    claimed = {
        r["sid"] for r in con.execute(
            "SELECT json_extract(result, '$.session_job_id') AS sid FROM job"
            " WHERE kind = ? AND result IS NOT NULL", (JOB_KIND,)).fetchall()
        if r["sid"]
    }
    out = []
    for r in rows:
        if r["id"] in claimed:
            continue   # 배분 완료로 이미 통지된 세션 — 두 번 알리지 않는다
        bot = con.execute("SELECT title, current_task FROM bot WHERE bot_id = ?",
                          (r["owner"],)).fetchone()
        out.append({
            "session_job_id": r["id"], "bot_id": r["owner"],
            "title": (bot["title"] if bot else None) or r["owner"],
            "task": (bot["current_task"] if bot else None) or "",
            "completed_at": r["created_at"],
        })
    return out


def open_human_gates(con: sqlite3.Connection, dispatch_id: str) -> list:
    """선행 배분 계보에 걸린 **열린 사람 결정** 요청 id 목록 (prj3#Issue953 ①).

    왜 필요한가 (2026-10-05 prj5#Issue112): 선행 배분이 증적 있는 done 이어도 같은 계보에서 매니저가 «수락 + 사람 결정 대기»
      (`reply --needs-human`)로 답해 두었으면 그 결정이 닫히기 전에 미룬 배분을 열면 안 된다 — 결정이 요청 result 에만 남아
      원장 상태로는 안 이어졌고, 승격이 결정을 앞질렀다.
    계보 = 선행 `dispatch_id` + 후손(`payload.parent_dispatch_id` 로 이어진 하위 배분 전체). 게이트 = `fbot_request` 중
      status `open` · `result.needs_human` 이 있고 `corr_id`(또는 `dispatch_id`)가 계보에 속하는 것(fbot-inbox `reply`·`_raise_to_human`).
    ⚠️ 회신 result 로 보류를 **추론**하지 않는다 — done 회신은 단순 수령에도 쓰여 거짓 보류가 된다. 사람 결정 표지만 본다.
    """
    lineage = {dispatch_id}
    frontier = [dispatch_id]
    for _ in range(8):   # 상한 — 계보 깊이(체인 상한과 같은 자릿수) 안에서 끝난다
        if not frontier:
            break
        marks = ",".join("?" * len(frontier))
        nxt = [r[0] for r in con.execute(
            "SELECT id FROM job WHERE kind = ? AND json_extract(payload, '$.parent_dispatch_id') IN (" + marks + ")",
            (JOB_KIND, *frontier)).fetchall() if r[0] not in lineage]
        lineage.update(nxt)
        frontier = nxt
    marks = ",".join("?" * len(lineage))
    ids = tuple(sorted(lineage))
    return [r[0] for r in con.execute(
        "SELECT id FROM job WHERE kind = ? AND status = 'open'"
        " AND json_extract(result, '$.needs_human') IS NOT NULL"
        " AND (json_extract(payload, '$.corr_id') IN (" + marks + ") OR json_extract(payload, '$.dispatch_id') IN (" + marks + "))"
        " ORDER BY created_at, id", (REQUEST_KIND, *ids, *ids)).fetchall()]


def promote_deferred(con: sqlite3.Connection, dry_run: bool = False, extra_done=(), held_out=None) -> list:
    """미룬 배분 승격 — 선행 배분이 `done` 이 된 `deferred` 행을 `open` 으로 당긴다 (prj3#Issue861).

    왜 필요한가 (2026-10-02 실측): 총괄·팀장이 순차 배분으로 뒤로 미룬 일(`prj1#Issue588` 등)이 원장 어디에도 없어
      몸체가 끝나자 45분간 미배분이었다. sweep 은 원장만 본다 — 미룬 일을 `dispatch --deferred-until <job_id>` 로 적어 두면
      sweep 이 선행의 done 을 보고 이 함수로 당긴다. 몸체 생존에 기대지 않는 것이 핵심이다.
    ⚠️ 대상은 `payload.deferred_until_job` 이 있는 행뿐이다 — 수동 보류(`defer`)는 자동 재개하지 않는다(Issue686 계약).
    ⚠️ 선행이 원장에 없거나 `done` 이 아니면(취소·미종결) 열지 않는다 — 선행이 사라진 일을 조용히 시작하지 않는다.
      deferred 로 남아 보드에 보이고 사람·매니저가 `resume`/`cancel` 로 정한다.
    🔧 prj3#Issue929 ② — 선행의 done 은 **증적 있는 done**(`done_evidenced`)이어야 한다. topic 선행이 산출 없이 done 으로
      닫혀 미룬 ②가 «전제 불일치» 로 조기 승격됐다(2026-10-04 `…f95b5876`). 선행이 «완료 미확인»(blocked)이면 당연히 열지 않고,
      매니저가 `close --evidence` 로 확정하면 다음 sweep 이 당긴다.
    🔧 prj3#Issue953 ① — 선행 계보에 **열린 사람 결정**(`open_human_gates`)이 있으면 증적 있는 done 이어도 당기지 않는다.
      보류분은 `held_out`(호출측 리스트)에 `{job_id, until_job, held_by}` 로 싣고, 적용 모드면 `payload.promote_held_by` 에 남긴다 —
      결정 요청이 닫힌 뒤 다음 sweep 이 승격한다.
    ⚠️ 전역 동시 상한(`resume` 과 같은 셈)을 넘기면 남은 자리만큼만 당긴다 — 나머지는 다음 sweep.
    `extra_done` = 이번 sweep 에서 막 done 이 되는 선행 id(dry-run 에서 미리 보이게). 열린 행은 이 함수가 채용·기동하지 않는다 —
      `spawn_pending` 표지만 남기고, 몸체는 tick 의 `spawn --pending`(`spawn_pending`)이 세운다 (prj3#Issue904).
      sweep 은 무인 주기에 얹는 최소 부작용 단위라 프로세스 기동을 싣지 않는다.
    """
    rows = con.execute("SELECT * FROM job WHERE kind = ? AND status = 'deferred' ORDER BY created_at",
                       (JOB_KIND,)).fetchall()
    ready = []
    for r in rows:
        try:
            pl = json.loads(r["payload"]) if r["payload"] else {}
        except json.JSONDecodeError:
            continue
        pre = pl.get("deferred_until_job")
        if not pre:
            continue
        prow = con.execute("SELECT status, payload, result FROM job WHERE id = ?", (pre,)).fetchone()
        if (prow is not None and done_evidenced(prow["status"], prow["payload"], prow["result"])) or pre in extra_done:
            gates = open_human_gates(con, pre)
            if gates:
                if held_out is not None:
                    held_out.append({"job_id": r["id"], "issue": pl.get("issue"), "until_job": pre, "held_by": gates})
                if not dry_run and pl.get("promote_held_by") != gates:
                    pl["promote_held_by"] = gates
                    con.execute("UPDATE job SET payload = ? WHERE id = ? AND status = 'deferred'",
                                (json.dumps(pl, ensure_ascii=False), r["id"]))
                continue
            ready.append((r, pl, pre))
    if not ready:
        return []
    try:
        pol = load_policy()
        known = {x[0] for x in con.execute("SELECT bot_id FROM bot")}
        live = [j for j in active_dispatches(con) if j["status"] == "open"
                and (j.get("payload") or {}).get("worker_bot_id") in known]
        room = max(pol["fbot_dispatch_concurrent_limit"] - len(live), 0)
        ready = ready[:room]
    except Exception as _e:   # 정책 판독 실패가 승격을 막지 않는다 — 상한 없이 진행하되 드러낸다
        print(f"[fbot-lead] 미룬 배분 승격 상한 판독 실패(상한 없이 진행): {_e}", file=sys.stderr)
    out = [{"job_id": r["id"], "issue": pl.get("issue"), "role": pl.get("role"),
            "worker_bot_id": pl.get("worker_bot_id"), "until_job": pre} for r, pl, pre in ready]
    if dry_run or not ready:
        return out
    now = int(time.time())
    applied = []
    con.execute("BEGIN IMMEDIATE")
    for (r, pl, pre), o in zip(ready, out):
        hist = {k[len("deferred_"):]: pl.pop(k) for k in
                ("deferred_reason", "deferred_until", "deferred_by", "deferred_at") if k in pl}
        pl.pop("deferred_until_job", None)
        pl.pop("promote_held_by", None)            # prj3#Issue953 ① — 홀드 해제(결정 요청이 닫혔다)
        pl["spawn_pending"] = True                 # prj3#Issue904 — 몸체 기동 대기 표지(tick `spawn --pending` 이 걷는다)
        hist.update({"until_job": pre, "resumed_by": BOT_ID, "resumed_at": now})
        pl.setdefault("defer_history", []).append(hist)
        _ev(con, BOT_ID, "resume", f"{r['id']}: 선행 {pre} 완료 — 미룬 배분 승격"[:120], r["id"])
        cur = con.execute("UPDATE job SET status = 'open', payload = ? WHERE id = ? AND status = 'deferred'",
                          (json.dumps(pl, ensure_ascii=False), r["id"]))
        if cur.rowcount == 1:
            applied.append(o)
    con.execute("COMMIT")
    return applied


def run_sweep(dry_run: bool = False, exclude=()) -> dict:
    """완료 감지 → job status=done 갱신 → hub SSE. **완료는 mq 로 통지하지 않는다** (prj3#Issue750) — 예외는 사람 판단이
    필요한 이벤트인 «완료 미확인» 통지 포기 경보 1회뿐이다(prj3#Issue947, 아래).

    완료는 사람이 조치할 것이 없는 **로그**다. 종전(Issue438 ④)엔 묶음 1회 mq alert 를
    보냈으나, 묶음이 sweep 1회 안에서만 성립해 팬아웃 배분에서는 tick 마다 1건씩 쌓였다
    (2026-09-27 실측: mq 미종결 20건 중 17건). 진짜 [컨펌]·에스컬레이션이 그 사이에 묻힌다.
    완료의 자리는 원장 전이(이 함수) + fbot-map 타임라인 + daily 보고의 «완료» 절이다.
    mq 에는 사람 판단이 필요한 **이벤트**만 간다 — 적체 에스컬레이션·쿼터 차단(watch).
    반환 `message` 는 로그·디버그용으로 유지한다(`enqueued` 는 항상 None).

    🔧 prj3#Issue929 — **완료 미확인**(topic 배분·산출 증적 없음)은 done 이 아니라 `blocked(unconfirmed)` 로 두고
      defer 와 같은 상향 사슬의 매니저 인박스에 올린다(`_notify_unconfirmed` — 적재만, 기동 없음: sweep 은 무인 주기의 최소 부작용 단위다.
      퇴근 매니저는 tick 의 `wake-pending` 이 깨운다). 반환 `unconfirmed` 는 **이번 회차에 새로** 미확인이 된 것.
      통지 결과는 `payload.unconfirmed` 에 남긴다 — 성공 `notified_request_id`·`notified_to`·`notified_at`, 실패
      `notify_attempts`·`notify_error`. 성공 기록이 없는 미확인은 이후 sweep 이 다시 통지한다(`unconfirmed_renotify` — 배분당
      성공 1회. 종전엔 blocked 전이 뒤 통지가 실패하면 조건부 UPDATE 가 재진입을 막아 영구 누락이었다 — 검토 ③).
      `exclude` = 판정에서 뺄 배분 id(명시 `cancel` 대상 — `detect_closures`).
    🔧 prj3#Issue947 — 재통지는 **상한·지수 백오프**를 둔다(`unconfirmed_notify_state`). 받을 매니저가 영구히 없으면 종전엔
      sweep 마다 같은 실패를 되풀이했다. 실패 k번 뒤 다음 시도는 `backoff × 2^(k-1)` 뒤, 누적 실패가 상한(policy
      `fbot_unconfirmed_notify_limit`)에 닿으면 재통지를 멈추고 mq 경보 **묶음**(`_give_up_unconfirmed` — 표지
      `notify_gave_up_at`. 정상 배분당 1회, 경보 실패·표지 고착이면 백오프 뒤 재경보). 반환 `unconfirmed_gave_up` = 이번 회차에 포기·경보한 배분(dry-run 은 포기 예정분, 경보 없음 —
      표지만 남고 결과 기록이 없는 고착 행의 재경보 `notify_state: stale` · 경보 실패 뒤 백오프가 지난 재경보 `alert_retry` 포함).
      증적 재평가(`detect_closures`)는 이 표지와 무관하다 — 포기 뒤에도 회신·커밋이 오면 completed 로 닫힌다.
    """
    now = int(time.time())
    con = connect()
    try:
        closures = detect_closures(con, exclude=exclude)
        uc = _unconfirmed()
        done = [c for c in closures if c["verdict"] == "completed"]
        unconf = [c for c in closures if c["verdict"] == uc]
        npol = unconfirmed_notify_policy()   # prj3#Issue947 — (상한, 백오프 초) 회차당 1회 판독
        nskip = {c["job_id"] for c in closures} | set(exclude or ())
        renotify = unnotified_unconfirmed(con, skip=nskip, now=now, policy=npol)
        exhausted = unnotified_unconfirmed(con, skip=nskip, now=now, policy=npol, want=GIVE_UP_STATES)
        wm = session_watermark(con)
        # prj3#Issue750 — 이번 sweep 에서 배분을 닫는 세션은 «봇 작업 완료» 로 또 세지 않는다.
        #   detect_session_completions 의 claimed 역참조는 **이미 기록된** 배분 result 만 보므로,
        #   같은 회차에 닫히는 배분의 세션이 두 번 잡혔다(실문구 «배분 완료 1건 — (이슈) /
        #   봇 작업 완료 1건 — claude 팀장핀봇»). 미확인 배분의 세션도 그 배분 몫이다(Issue929).
        claimed_now = {c["session_job_id"] for c in closures}
        sessions = [x for x in detect_session_completions(con, wm)
                    if x["session_job_id"] not in claimed_now]
        if dry_run or not (done or unconf or sessions or renotify or exhausted):
            # prj3#Issue861 — 선행이 close 등 sweep 밖에서 done 이 된 미룬 배분도 여기서 당긴다
            held = []
            resumed = promote_deferred(con, dry_run=dry_run, extra_done={c["job_id"] for c in done}, held_out=held)
            return {"detected": len(done), "completed": done,
                    "unconfirmed_detected": len(unconf), "unconfirmed": unconf,
                    "unconfirmed_renotify": renotify, "unconfirmed_gave_up": exhausted,
                    "sessions_detected": len(sessions), "sessions": sessions,
                    "resumed": resumed, "held": held,
                    "watermark": wm, "enqueued": None,
                    "mode": "dry-run" if dry_run else "apply"}
        con.execute("BEGIN IMMEDIATE")
        for c in done:
            _ev(con, c.get("worker_bot_id") or BOT_ID, "done", f"완료 판정: {(c.get('issue') or '')[:80]}", c.get("job_id") or "")   # prj3#Issue575
            con.execute(
                "UPDATE job SET status = 'done', blocked_since = NULL, result = ?"
                # prj3#Issue514 — `logged`(사후 기록분)도 완료로 닫는다. 종결 경로가 없어
                #   영구 잔류하던 것이 이 술어의 누락이었다.
                " WHERE id = ? AND status IN ('open','blocked','logged')",
                (json.dumps({"verdict": "completed", "detected_by": BOT_ID,
                             "session_job_id": c["session_job_id"],
                             "evidence": c.get("evidence"),               # prj3#Issue929 — 무엇이 완료를 보증했나
                             "claude_tokens": c.get("claude_tokens"),     # prj3#Issue699_2
                             "from_status": c["from_status"], "swept_at": now},
                            ensure_ascii=False), c["job_id"]),
            )
        applied_unconf = []
        for c in unconf:
            # prj3#Issue929 — result 는 건드리지 않는다(종결이 아니다). 사유·세션은 payload 에 남긴다 — hub 보드는 blocked 를
            #   ⛔ 게이트로 그린다(교착·완료로 오분류 없음). 조건부 UPDATE 가 **지금 blocked(unconfirmed)** 인 행의 재전이를 막는다(멱등).
            #   검토 ④ — 술어는 status 와 함께 본다. blocked_by 만 보면 미확인 → close → reopen 으로 open 이 된 배분에 남은
            #   낡은 사유가 새 미확인 전이를 막아 open 인 채 통지도 없었다. 새 전이는 `payload.unconfirmed` 를 통째로 바꾼다(통지 기록 초기화)
            cur = con.execute(
                "UPDATE job SET status = 'blocked', blocked_since = ?,"
                " payload = json_set(payload, '$.blocked_by', ?, '$." + uc + "', json(?))"
                " WHERE id = ? AND status IN ('open','blocked','logged')"
                " AND NOT (status = 'blocked' AND COALESCE(json_extract(payload, '$.blocked_by'), '') = ?)",
                (now, uc,
                 json.dumps({"session_job_id": c["session_job_id"], "at": now, "reason": c.get("reason"),
                             "from_status": c["from_status"], "detected_by": BOT_ID}, ensure_ascii=False),
                 c["job_id"], uc))
            if cur.rowcount == 1:
                _ev(con, c.get("worker_bot_id") or BOT_ID, "blocked",
                    f"{c['job_id']}: 완료 미확인 — {c.get('reason') or ''}"[:120], c["job_id"])
                applied_unconf.append(c)
        unconf = applied_unconf
        release_loans(con, [c["job_id"] for c in done])   # prj3#Issue757 T13 — 작업 종결 시 차용 자동 해제
        # 워터마크는 같은 트랜잭션에서 전진시킨다 — 다음 sweep 이 같은 세션을 다시 세지 않는다.
        if sessions:
            newest = max(x["completed_at"] for x in sessions)
            con.execute(
                "INSERT INTO kv (ns, key, value, expires_at, updated_at, updated_by)"
                " VALUES (?,?,?,NULL,?,?)"
                " ON CONFLICT(ns, key) DO UPDATE SET"
                "   value = excluded.value, updated_at = excluded.updated_at",
                (NOTIFY_NS, NOTIFY_SESSION_KEY, str(newest), now, BOT_ID),
            )
        con.execute("COMMIT")
        held = []
        resumed = promote_deferred(con, held_out=held)   # prj3#Issue861 — 이번 회차 done 을 반영한 뒤 미룬 배분 승격
    finally:
        con.close()

    # prj3#Issue773 ③ — 배분이 처리한 인박스 요청(`dispatch --request`)도 닫는다. 판정은 fbot-inbox `close_fulfilled`
    #   (연결 배분이 전부 끝났고 done 이 하나 이상일 때만). 실패해도 배분 종결은 되돌리지 않는다 — stderr 로 드러낸다
    if done:
        try:
            _inbox_mod().close_fulfilled([c.get("job_id") for c in done])
        except Exception as _e:
            print(f"[fbot-lead] 요청 종결 실패(배분 종결은 유지): {_e}", file=sys.stderr)
    # hub SSE 는 커밋 **후** — 보드가 빈 원장을 읽지 않게(notify_hub_event 계약). best-effort 다:
    #   완료의 정본은 방금 커밋한 원장 전이이고, SSE 가 빠져도 fbot-map 은 다음 로드에 읽는다.
    for c in done:
        _ev_notify(c.get("worker_bot_id") or BOT_ID, "done", c.get("job_id") or "")
    for c in unconf:
        c["notified"] = _notify_unconfirmed(c)
        _ev_notify(c.get("worker_bot_id") or BOT_ID, "blocked", c.get("job_id") or "")
    for c in renotify:
        c["notified"] = _notify_unconfirmed(c)
    _record_notices(unconf + renotify)
    # prj3#Issue947 — 기록 **뒤**에 본다: 이번 회차 실패로 상한에 닿은 배분도 같은 회차에 포기·경보한다(다음 sweep 까지 미루지 않는다)
    gave_up = _give_up_unconfirmed(npol[0], skip=set(exclude or ()), base_s=npol[1])
    parts = []
    if done:
        parts.append("배분 완료 {}건 — {}".format(len(done), " · ".join(
            f"{c['issue'] or '?'}({c['role'] or '?'}/{c['worker_bot_id']})"
            + ("[에스컬레이션 해소]" if c["from_status"] == "blocked" else "")
            for c in done)))
    if unconf:
        parts.append("완료 미확인 {}건 — {}".format(len(unconf), " · ".join(
            f"{c['issue'] or '?'}({c['role'] or '?'}/{c['worker_bot_id']})" for c in unconf)))
    if renotify:
        parts.append("완료 미확인 재통지 {}건 — {}".format(len(renotify), " · ".join(
            f"{c['job_id']}({'ok' if (c.get('notified') or {}).get('ok') else '실패'})" for c in renotify)))
    if gave_up:
        parts.append("완료 미확인 통지 포기 {}건 — {}".format(len(gave_up), " · ".join(
            f"{c['job_id']}({'경보 실패 — 백오프 뒤 재경보' if c.get('alert_error') else 'mq 경보'}"
            + {"stale": " · 표지 고착 재경보", "alert_retry": " · 경보 재시도"}.get(c.get("notify_state"), "") + ")"
            for c in gave_up)))
    if sessions:
        parts.append("봇 작업 완료 {}건 — {}".format(len(sessions), " · ".join(
            f"{x['title']}" + (f": {x['task'][:40]}" if x["task"] else "")
            for x in sessions)))
    if resumed:
        parts.append("미룬 배분 승격 {}건 — {}".format(len(resumed), " · ".join(
            f"{x['issue'] or '?'}({x['role'] or '?'}) ← {x['until_job']}" for x in resumed)))
    msg = "[fbot-lead] " + " / ".join(parts)
    return {"detected": len(done), "completed": done,
            "unconfirmed_detected": len(unconf), "unconfirmed": unconf, "unconfirmed_renotify": renotify,
            "unconfirmed_gave_up": gave_up,
            "sessions_detected": len(sessions), "sessions": sessions, "resumed": resumed, "held": held,
            "watermark": wm, "enqueued": None, "message": msg, "mode": "apply"}


def unconfirmed_notify_policy(pol=None) -> tuple:
    """«완료 미확인» 재통지 `(상한 회수, 백오프 기준 초)` — 판독 단일 지점 (prj3#Issue947).

    `pol` 생략 시 `load_policy()`. 판독 실패는 sweep 을 멈추지 않는다 — 기본값으로 돌고 stderr 로 드러낸다
    (`promote_deferred` 상한 판독과 같은 축: 정책 파일 하나가 완료 판정 전체를 세우면 안 된다).
    """
    if pol is None:
        try:
            pol = load_policy()
        except Exception as e:
            print(f"[fbot-lead] 미확인 재통지 정책 판독 실패(기본값 {UNCONF_NOTIFY_LIMIT_DEFAULT}회·"
                  f"{UNCONF_NOTIFY_BACKOFF_DEFAULT_MIN}분으로 진행): {e}", file=sys.stderr)
            pol = {}
    limit = pol.get(UNCONF_NOTIFY_LIMIT_KEY) or UNCONF_NOTIFY_LIMIT_DEFAULT
    base = pol.get(UNCONF_NOTIFY_BACKOFF_KEY) or UNCONF_NOTIFY_BACKOFF_DEFAULT_MIN
    return int(limit), int(base) * 60


def unconfirmed_backoff_window(k: int, base_s: int) -> int:
    """실패 k(≥1)번 뒤 다음 시도까지(초) — `base_s × 2^(k-1) − base_s//2` (prj3#Issue947, 백오프 식 단일 지점).

    반 주기 여유를 뺀다(틱 지터: 30분 틱의 다음 회차 sweep 이 29분대에 와도 그 회차가 시도한다 — 여유가 없으면 창이 사실상
    한 주기씩 밀린다). 재통지(`notify_*`)와 경보 재시도(`notify_alert_*`)가 같은 식을 쓴다. ⚠️ SQL 짝은 `_give_up_unconfirmed`
    선점 술어(`? * (1 << (k - 1)) - ? / 2`) — 식을 바꾸면 함께 바꾼다."""
    return base_s * (2 ** (max(k, 1) - 1)) - base_s // 2


def unconfirmed_notify_state(u: dict, now: int, limit: int, base_s: int) -> str:
    """통지 성공 기록이 없는 미확인 배분의 재통지·경보 판정 (prj3#Issue947, 판정 단일 지점).

    `u` = 배분 `payload.unconfirmed`. 앞에서부터 처음 걸리는 것:
      ⓐ 포기 표지 `notify_gave_up_at` 이 있으면 통지는 끝났다(포기는 최종 — 상한을 올려도 되살리지 않는다). 남은 일은 경보:
         · 경보 기록 `notify_alert_id` 있음 → `gave_up` (빈 문자열도 기록이다 — helper stdout 이 빌 수 있다)
         · 마지막 선점의 경보가 실패로 기록됨(`notify_alert_failed_at` ≥ 표지) → 경보 재시도도 같은 지수 백오프
           (`unconfirmed_backoff_window(notify_alert_attempts)`) — 창 밖 `alert_retry`(재경보 대상) · 창 안 `alert_backoff`.
           helper 가 영구히 실패해도 sweep 마다 쓰기·호출이 되풀이되지 않는다
         · 결과 기록 없음 — 표지가 고착 창(`max(base_s, UNCONF_GIVEUP_STALE_MIN_S)`)보다 오래면 `stale`(선점 뒤 경보 전에 죽었거나
           결과 기록 쓰기가 실패한 행 — 재경보 대상), 창 안이면 경보가 진행 중일 수 있어 `gave_up`(이중 경보 방지)
      ⓑ 누적 실패 `notify_attempts` ≥ `limit` → `exhausted` (재통지 중단 · 포기·경보 대상 — `_give_up_unconfirmed`)
      ⓒ 실패 k(≥1)번 뒤 다음 시도는 마지막 시도(`notify_failed_at`, 없으면 전이 시각 `at`)로부터 `unconfirmed_backoff_window(k)` 뒤
         — sweep 주기의 1·2·4·8배(반 주기 여유). 창 안이면 `backoff`
      ⓓ 그 밖(시도 기록 없음 포함) → `due`
    재경보 대상(`GIVE_UP_STATES`) = `exhausted`·`stale`·`alert_retry`. ⚠️ `_give_up_unconfirmed` 선점 술어가 이 판정을 SQL 로 다시 본다 — 함께 바꾼다.
    시각 기준이 sweep 횟수가 아닌 이유: sweep 은 tick 말고도 매니저가 배분 뒤 손으로 돈다 — 횟수로 세면 수동 sweep 몇 번에 상한이 탄다.
    ⚠️ 통지에만 걸린다 — 증적 재평가(`detect_closures`)는 이 판정을 보지 않는다(포기 뒤에도 회신·커밋이 오면 completed).
    """
    g = u.get("notify_gave_up_at")
    if g is not None:
        if u.get("notify_alert_id") is not None:
            return "gave_up"
        g = int(g)
        fa = u.get("notify_alert_failed_at")
        if fa is not None and int(fa) >= g:
            ka = int(u.get("notify_alert_attempts") or 0)
            return "alert_retry" if now - int(fa) >= unconfirmed_backoff_window(ka, base_s) else "alert_backoff"
        return "stale" if now - g >= max(base_s, UNCONF_GIVEUP_STALE_MIN_S) else "gave_up"
    k = int(u.get("notify_attempts") or 0)
    if k >= limit:
        return "exhausted"
    if k <= 0:
        return "due"
    last = int(u.get("notify_failed_at") or u.get("at") or 0)
    return "due" if now - last >= unconfirmed_backoff_window(k, base_s) else "backoff"


def unnotified_unconfirmed(con: sqlite3.Connection, skip=(), now=None, policy=None, want=("due",)) -> list:
    """`blocked(unconfirmed)` 인데 통지 성공 기록(`payload.unconfirmed.notified_request_id`)이 없는 배분 — 재통지 대상 (검토 ③).

    워커 상태·세션과 무관하게 원장만 본다 — 재평가(`detect_closures`)는 워커가 퇴근 상태일 때만 돌아, 거기에 묶으면
    워커가 다른 일로 출근해 있는 동안 재통지가 밀린다. `skip` = 이번 회차 판정이 끝난 배분(completed·신규 미확인)·cancel 대상.
    🔧 prj3#Issue947 — `want` = 돌려줄 재통지 판정(`unconfirmed_notify_state`). 기본 `due`(지금 보낼 것) — 백오프 창 안·상한
      도달·포기분은 빠진다. `GIVE_UP_STATES`(`exhausted`·`stale`·`alert_retry`)면 포기·경보 대상. `policy` = `(상한, 백오프 초)`(생략 시 `unconfirmed_notify_policy()`).
    레코드 모양은 `detect_closures` 의 unconfirmed 와 같다(+ `renotify: True`·`notify_state`·`notify_error`)."""
    uc = _unconfirmed()
    now = int(time.time()) if now is None else now
    limit, base_s = policy if policy is not None else unconfirmed_notify_policy()
    out = []
    for r in con.execute(
            "SELECT id, owner, payload FROM job WHERE kind = ? AND status = 'blocked'"
            " AND json_extract(payload, '$.blocked_by') = ?"
            " AND json_extract(payload, '$." + uc + ".notified_request_id') IS NULL"
            " ORDER BY created_at, id", (JOB_KIND, uc)).fetchall():
        if r["id"] in skip:
            continue
        pl = _json_or_empty(r["payload"])
        u = pl.get(uc) or {}
        state = unconfirmed_notify_state(u, now, limit, base_s)
        if state not in want:
            continue
        out.append({"verdict": uc, "renotify": True, "job_id": r["id"], "from_status": "blocked",
                    "issue": pl.get("issue"), "role": pl.get("role"), "owner": r["owner"],
                    "worker_bot_id": pl.get("worker_bot_id"), "session_job_id": u.get("session_job_id"),
                    "reason": u.get("reason"), "attempts": int(u.get("notify_attempts") or 0),
                    "notify_state": state, "notify_error": u.get("notify_error"),
                    "alert_attempts": int(u.get("notify_alert_attempts") or 0)})
    return out


def _give_up_unconfirmed(limit: int, skip=(), base_s=None) -> list:
    """재통지 상한에 닿은 미확인 배분 — 재통지를 멈추고 mq 경보 **묶음 1회** (prj3#Issue947).

    받을 매니저가 영구히 없으면(배분자·부모가 대장에서 빠짐 — 퇴사·이름 변경) 인박스 통지는 끝내 성공하지 못한다. 사람에게
    한 번 드러내고(배분 id·통지 오류·미확인 사유·정리 명령) 그 배분의 통지는 끝낸다. 대상 = 판정 `GIVE_UP_STATES`. 순서:
      ① 표지 `payload.unconfirmed.notify_gave_up_at` 를 조건부 UPDATE 로 먼저 세운다(선점 — 값 = 이번 회차 시각, 결과 기록의 짝 키).
         동시 sweep(tick·수동)이 같은 배분을 두 번 올리지 않게. 후보 SELECT 는 트랜잭션 밖이라 술어가 판정 ⓐⓑ 를 SQL 로 **다시** 본다:
         · 새 포기 — 표지 없음 ∧ `notify_attempts` ≥ `limit` (그 사이 close → reopen → 새 전이가 끼면 집지 않는다)
         · 경보 재시도 — 경보 기록 없음 ∧ 마지막 선점의 실패 기록(`notify_alert_failed_at` ≥ 표지) ∧ 경보 백오프 경과
         · 고착 — 경보 기록 없음 ∧ 결과 기록 없음 ∧ 표지가 고착 창보다 오래됨(경보 진행 중인 다른 sweep 의 표지를 가로채지 않는다)
      ② 세운 것만 묶어 `mq_alert` 1회(Issue399 규약 — 건당이 아니라 묶음) → 성공은 `notify_alert_id` 기록
      ③ 경보가 실패하면(시간 초과 포함 — `MQ_ALERT_TIMEOUT_S`) **표지는 둔다**(포기는 최종 — 상한을 올려도 재통지로 돌아가지
         않는다) — `notify_alert_error`·`notify_alert_failed_at`·`notify_alert_attempts`(누적)를 남기고 stderr 1줄. 재경보는
         재통지와 같은 지수 백오프 뒤(`alert_retry`) — helper 가 영구히 실패해도 sweep 마다 되풀이하지 않는다(조용히 삼키지도 않는다)
    ①과 ② 사이에 죽거나 ②·③의 결과 기록이 실패하면 «표지 有·결과 기록 無» 가 남는다 — 판정이 고착 창 뒤 `stale` 로 다시 내고
    여기서 경보만 마저 낸다(침묵 방지 — 경보는 성공했는데 id 기록만 실패한 행은 한 번 더 올라갈 수 있다: 침묵보다 중복).
    표지는 `payload.unconfirmed` 안이라 새 미확인 전이(close → reopen → 재퇴근)가 통째로 바꿔 초기화한다.
    완료 판정과 무관하다 — `detect_closures` 는 이 표지를 보지 않는다. 반환 = 이번 회차에 포기·재경보한 배분(+ `alert`·`alert_error`).
    `base_s` = 백오프 기준 초(경보 백오프·고착 창 산정 — 생략 시 `unconfirmed_notify_policy()`)."""
    uc = _unconfirmed()
    base = "$." + uc
    now = int(time.time())
    if base_s is None:
        base_s = unconfirmed_notify_policy()[1]
    stale_s = max(base_s, UNCONF_GIVEUP_STALE_MIN_S)
    try:
        con = connect()
    except Exception as e:
        print(f"[fbot-lead] 미확인 통지 포기 판정 실패(연결): {e}", file=sys.stderr)
        return []

    def jx(k):
        return "json_extract(payload, '" + base + "." + k + "')"
    g, aid, afa = jx("notify_gave_up_at"), jx("notify_alert_id"), jx("notify_alert_failed_at")
    claimed = []
    try:
        cands = unnotified_unconfirmed(con, skip=skip, now=now, policy=(limit, base_s), want=GIVE_UP_STATES)
        if cands:
            con.execute("BEGIN IMMEDIATE")
            for c in cands:
                cur = con.execute(
                    "UPDATE job SET payload = json_set(payload, '" + base + ".notify_gave_up_at', ?)"
                    " WHERE id = ? AND kind = ? AND status = 'blocked' AND json_extract(payload, '$.blocked_by') = ?"
                    " AND " + jx("notified_request_id") + " IS NULL"
                    " AND ((" + g + " IS NULL AND COALESCE(" + jx("notify_attempts") + ", 0) >= ?)"
                    # 경보 재시도 — 백오프 식은 unconfirmed_backoff_window 의 SQL 짝(? * 2^(k-1) − ? / 2)
                    "   OR (" + g + " IS NOT NULL AND " + aid + " IS NULL AND COALESCE(" + afa + ", -1) >= " + g +
                    "       AND ? - " + afa + " >= ? * (1 << (max(COALESCE(" + jx("notify_alert_attempts") + ", 0), 1) - 1)) - ? / 2)"
                    "   OR (" + aid + " IS NULL AND " + g + " <= ? AND COALESCE(" + afa + ", -1) < " + g + "))",
                    (now, c["job_id"], JOB_KIND, uc, limit, now, base_s, base_s, now - stale_s))
                if cur.rowcount == 1:
                    claimed.append(c)
            con.execute("COMMIT")
    except Exception as e:
        try:
            con.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        print(f"[fbot-lead] 미확인 통지 포기 표지 실패(다음 sweep 재시도): {e}", file=sys.stderr)
        return []
    finally:
        con.close()
    if not claimed:
        return []
    tag = {"stale": " [표지 고착 재경보 — 앞선 포기의 경보 결과 기록 없음]"}
    lines = [f"[fbot-lead] 완료 미확인 통지 포기 {len(claimed)}건 — 인박스 통지가 재통지 상한({limit}회)까지 실패해 재통지를 멈췄다"
             f"(받을 매니저 부재 등). 원장은 blocked(unconfirmed) 그대로 — 증적이 오면 sweep 이 completed 로 닫는다. 사람 판단 필요:"]
    for c in claimed:
        lines.append(f"· {c['job_id']} ({c.get('issue') or '?'} · {c.get('role') or '?'}/{c.get('worker_bot_id') or '?'},"
                     f" 배분자 {c.get('owner') or '?'}) — 통지 {c.get('attempts', '?')}회 실패: {c.get('notify_error') or '?'}"
                     f" · 미확인 사유: {c.get('reason') or '?'}"
                     + (f" [경보 재시도 — 앞선 경보 {c.get('alert_attempts') or '?'}회 실패]" if c.get("notify_state") == "alert_retry"
                        else tag.get(c.get("notify_state"), "")))
    lines.append("정리: python3 ~/.claude/hooks/fbot-lead.py close --job-id <id> --evidence \"<커밋 해시·산출 경로>\""
                 " | cancel --job-id <id> --reason \"<사유>\" (다시 시킬 일이면 cancel 뒤 dispatch)")
    try:
        alert_id, err = mq_alert("\n".join(lines)), None
    except Exception as e:
        alert_id, err = None, f"{type(e).__name__}: {e}"
    try:
        con = connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            for c in claimed:
                guard = " WHERE id = ? AND kind = ? AND " + g + " = ?"   # 이번 선점의 표지가 그대로인 행만(그 사이 새 전이면 건드리지 않는다)
                if err is None:
                    con.execute("UPDATE job SET payload = json_set(payload, '" + base + ".notify_alert_id', ?)" + guard,
                                (alert_id, c["job_id"], JOB_KIND, now))
                else:
                    con.execute("UPDATE job SET payload = json_set(payload, '" + base + ".notify_alert_error', ?, '"
                                + base + ".notify_alert_failed_at', ?, '" + base + ".notify_alert_attempts',"
                                " COALESCE(" + jx("notify_alert_attempts") + ", 0) + 1)" + guard,
                                (err[:200], now, c["job_id"], JOB_KIND, now))
            con.execute("COMMIT")
        finally:
            con.close()
    except Exception as e:
        print(f"[fbot-lead] 미확인 통지 포기 결과 기록 실패(고착 창 뒤 sweep 이 다시 경보): {e}", file=sys.stderr)
    if err is not None:
        print(f"[fbot-lead] 미확인 통지 포기 경보 실패 — 표지는 두고 백오프 뒤 sweep 이 다시 경보: {err}", file=sys.stderr)
    for c in claimed:
        c.update({"gave_up_at": now, "alert": alert_id, "alert_error": err})
    return claimed


def _record_notices(items: list) -> None:
    """통지 결과를 배분 `payload.unconfirmed` 에 남긴다 — 재통지 판정(`unnotified_unconfirmed`)의 근거.
    지금도 blocked(unconfirmed) 인 행만 고친다(그 사이 close·cancel 된 배분은 건드리지 않는다). 실패는 stderr —
    통지 자체는 이미 일어났고, 기록이 빠지면 다음 sweep 이 한 번 더 보낼 뿐이다(같은 본문·corr 가 open 이고
    `SEND_DEDUP_WINDOW` 창 안이면 인박스 `send` 멱등이 흡수 — prj3#Issue892)."""
    if not items:
        return
    uc = _unconfirmed()
    base = "$." + uc
    now = int(time.time())
    try:
        con = connect()
    except Exception as e:
        print(f"[fbot-lead] 통지 기록 실패(연결): {e}", file=sys.stderr)
        return
    try:
        con.execute("BEGIN IMMEDIATE")
        for c in items:
            n = c.get("notified") or {}
            guard = " WHERE id = ? AND kind = ? AND status = 'blocked' AND json_extract(payload, '$.blocked_by') = ?"
            if n.get("ok"):
                con.execute("UPDATE job SET payload = json_set(payload, '" + base + ".notified_request_id', ?, '"
                            + base + ".notified_to', ?, '" + base + ".notified_route', ?, '" + base + ".notified_at', ?)"
                            + guard, (n.get("request_id"), n.get("to"), n.get("route"), now, c["job_id"], JOB_KIND, uc))
            else:
                con.execute("UPDATE job SET payload = json_set(payload, '" + base + ".notify_attempts',"
                            " COALESCE(json_extract(payload, '" + base + ".notify_attempts'), 0) + 1, '"
                            + base + ".notify_error', ?, '" + base + ".notify_failed_at', ?)" + guard,
                            (str(n.get("error") or "?")[:200], now, c["job_id"], JOB_KIND, uc))
        con.execute("COMMIT")
    except Exception as e:
        try:
            con.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        print(f"[fbot-lead] 통지 기록 실패: {e}", file=sys.stderr)
    finally:
        con.close()


def _notify_unconfirmed(c: dict) -> dict:
    """«완료 미확인» 을 인박스에 올린다 (prj3#Issue929 ①) — 실패해도 원장 전이는 유지(stderr · `_record_notices` 가 남긴다).

    수신자 해소는 fbot-inbox `notify_unconfirmed` 단일 지점 — 워커 보고(`defer`)와 **같은 상향 사슬**(배분자 → 워커의 부모 →
    워커 팀의 팀장 → 총괄, 받을 수 없는 매니저는 건너뜀)이다. 여기서 수신자를 따로 고르면 defer 와 갈라진다(검토 ③).
    발신은 sweep(봇·세션 없음)이라 사람 지시로 읽히지 않는다. `spawn=False` — sweep 은 무인 주기라 몸체를 띄우지 않는다.
    퇴근 매니저는 tick `wake-pending` 이 깨우고, 30분 넘게 답이 없으면 `escalate` 가 mq 로 올린다.
    본문에 정리 명령 셋(close·cancel·재배분)을 싣는다.
    """
    jid, wid = c["job_id"], c.get("worker_bot_id") or "?"
    body = (f"[완료 미확인] 배분 {jid} ({c.get('issue') or '?'} · {c.get('role') or '?'}/{wid}) — 워커는 퇴근했으나 "
            f"산출 증적이 없다: {c.get('reason') or '?'}. 원장은 blocked(unconfirmed) 로 두었다(완료로 세지 않음).\n"
            f"- 산출을 확인했으면: python3 ~/.claude/hooks/fbot-lead.py close --job-id {jid} --evidence \"<커밋 해시·산출 경로>\"\n"
            f"- 무의미해졌으면: python3 ~/.claude/hooks/fbot-lead.py cancel --job-id {jid} --reason \"<사유>\"\n"
            f"- 다시 시킬 일이면: cancel 뒤 dispatch --topic … (산출을 --expect PATH 로 선언)\n"
            f"- 결정·확인을 기다리며 미룰 일이면: python3 ~/.claude/hooks/fbot-lead.py defer --job-id {jid} --reason \"<사유>\" "
            f"(close 는 선행 완료로 오인돼 종속 배분을 승격시킨다)")
    extra = {"dispatch_id": jid, "worker_bot_id": wid, "session_job_id": c.get("session_job_id")}
    try:
        out = _inbox_mod().notify_unconfirmed(jid, body, extra)
    except Exception as e:
        out = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    if out.get("ok"):
        return {"ok": True, "to": out.get("to"), "route": out.get("route"), "request_id": out.get("id")}
    print(f"[fbot-lead] 완료 미확인 통지 실패({jid}): {out.get('error')} — 백오프 뒤 sweep 이 재시도"
          f"(상한 도달 시 mq 경보 — prj3#Issue947)", file=sys.stderr)
    return {"ok": False, "error": out.get("error"), "tried": out.get("tried") or []}


def cmd_session_end(args) -> int:
    """워커의 `--since` 이후 마지막 세션 종료 사유 조회 (prj3#Issue743 — fpm-do 감시용).

    fpm-do 는 워커 pane 이 죽었을 때 이것으로 «쿼터로 죽었나» 를 묻는다. 재판정은 없다 —
    퇴근 훅이 원장에 적은 것을 그대로 돌려준다. 세션 기록이 아직 없으면 `end: null`.
    """
    con = connect()
    try:
        end = last_session_end(con, args.worker, args.since)
    finally:
        con.close()
    emit({"ok": True, "action": "session-end", "worker": args.worker, "since": args.since, "end": end})
    return 0


def cmd_sweep(args) -> int:
    """완료 감지 스윕 — 상태 전이 시점 통지의 진입점(tick worker 주기 편입)."""
    out = run_sweep(dry_run=args.dry_run)
    emit({"ok": True, "action": "sweep", **out})
    return 0


def _close_requests(applied, by):
    """수동 종결(close·cancel) 뒤 연결 인박스 요청 종결 — 판정은 fbot-inbox `close_fulfilled` 한 곳(prj3#Issue816).
    sweep 만 부르면 마지막 배분이 수동으로 닫힌 요청이 영구 open 이 된다. 실패해도 배분 종결은 유지(stderr)."""
    if not applied:
        return
    try:
        _inbox_mod().close_fulfilled([r["job_id"] for r in applied], by=by)
    except Exception as _e:
        print(f"[fbot-lead] 요청 종결 실패(배분 종결은 유지): {_e}", file=sys.stderr)


def cmd_cancel(args) -> int:
    """배분 취소 — 완료가 아니라 **무의미해진 배분의 명시 종결**이다.

    왜 필요한가 (2026-08-26 실측 — 총괄핀봇 처분건):
      `detect_completions()` 는 reap(lease 만료 강제 퇴근)된 워커를 완료로 보지 않는다.
      세션 done 기록이 없으니 보수적으로 남기는 것이 **옳다**(오판 금지 — 그 주석 참조).
      빠져 있던 것은 그 다음이다: 배분이 **다른 주체가 일을 끝내버려 무의미해진** 경우
      종결할 경로가 없어 `open`/`blocked` 로 영구 잔류한다. `open` 은 동시 상한(WIP)을
      포화시켜 **신규 배분을 전면 차단**한다 — 실측에서 3/3 포화로 조직이 멈춰 있었다.
      경로가 없으니 총괄핀봇이 registry.db 를 직접 UPDATE 했다. 그 우회를 없애는 것이 본 명령이다.

    ⚠️ 완료(`sweep`)와 취소(`cancel`)는 **다른 사건**이다. 취소는 워커가 일을 했다고 주장하지
      않으며, status 를 `done` 이 아니라 `cancelled` 로 둔다 — `done` 에 섞으면 `/fbot` 의
      "오늘 완료 N건" 집계가 오염된다(취소가 성과로 잡힌다).
    ⚠️ `--reason` 필수 — 근거 없는 원장 정리를 금지한다. 누가·왜 지웠는지 남지 않는 취소는
      나중에 "이 배분은 왜 사라졌나" 를 되짚을 수 없다.
    ⚠️ mq 통지 없음 — 취소는 사람·총괄이 **알고서 명시 호출**하는 사건이라 되알림이 노이즈다
      (sweep 의 통지는 무인 주기가 발견한 사건이라 성격이 다르다).

    🔧 prj3#Issue819 — **취소 전 sweep 1회.** hub fbot-map 「⏳ 원클릭 회수」가 완료-미수령 4건(Issue.md ✅+해시)과
      진행 중 1건을 `cancelled_obsolete` 로 굳혔다(2026-09-29 07:07 실측). cancelled 는 terminal 이라 완료 hash 가
      취소 행으로 남았다. 이제 sweep 이 완료로 판정한 건은 done 으로 먼저 빠지고 `swept` 로 보고된다(오류 아님).
      **회수 모드**(`--reclaim` 또는 `RECLAIM_CALLERS` 주체)는 남은 건을 한 번 더 가른다(`_reclaim_action`) —
      이슈 완료면 done(completed_external) · 이슈 미완료+워커 퇴근이면 `blocked(worker_died)`(재배분 경로 —
      reap 사망 처리 계획과 같은 상태) · 그 밖·두 번째 회수는 종전대로 취소. 명시 취소(회수 아님)는 판정을 바꾸지 않는다.
    🔧 prj3#Issue929 ③ — 명시 취소(회수 아님)는 취소 대상 **topic 배분**을 그 sweep 에서 **뺀다**(`run_sweep(exclude=…)`) — 대상은 cancelled 다.
      이슈 배분은 종전대로(완료 섹션 대조가 독립 증거 — 끝났으면 done 으로 먼저 빠진다).
      «완료 미확인»(`blocked(unconfirmed)`) 배분도 이 경로로 정리한다.
    """
    reclaim = bool(getattr(args, "reclaim", False)) or args.by in RECLAIM_CALLERS

    def _hit(j_id, issue):
        return (args.job_id and j_id == args.job_id) or (args.issue and issue == args.issue)

    # prj3#Issue929 ③ — **명시 취소**의 대상은 취소 직전 sweep 에서 뺀다. 종전엔 그 sweep 이 대상을 먼저 completed 로
    #   닫아 «취소» 가 «완료» 로 바뀌었다(취소가 성과로 집계되고 미룬 배분이 승격). 취소는 주체가 알고서 내린 판단이다.
    #   회수 모드는 종전대로 포함한다 — 원장만 안 닫힌 완료-미수령을 치우는 클릭이라 완료가 먼저다(prj3#Issue819 H1).
    #   제외는 **topic 배분만** — 이슈 배분은 완료 섹션 대조가 독립 증거라 종전대로 직전 sweep 이 완료를 먼저 닫는다
    #   (끝난 이슈 작업이 «취소» 로 굳고 그 선행의 미룬 배분이 막히지 않게).
    exclude = ()
    if not reclaim:
        _c = connect()
        try:
            exclude = tuple(j["id"] for j in active_dispatches(_c)
                            if j["payload"].get("ident_kind") == "topic" and _hit(j["id"], j["payload"].get("issue")))
        finally:
            _c.close()
    sw = run_sweep(dry_run=args.dry_run, exclude=exclude)
    swept = [{"job_id": c["job_id"], "issue": c.get("issue"), "worker_bot_id": c.get("worker_bot_id"),
              "session_job_id": c.get("session_job_id")}
             for c in sw.get("completed") or [] if _hit(c["job_id"], c.get("issue"))]
    swept_ids = {c["job_id"] for c in swept}
    con = connect()
    try:
        targets = [j for j in active_dispatches(con)
                   if _hit(j["id"], j["payload"].get("issue")) and j["id"] not in swept_ids]
        if not targets and not swept:
            key = args.job_id or args.issue
            # Reject 는 **수요측 가드 판정 번호** 전용이다(①~⑤) — 취소 대상 부재는 그 축이 아니다.
            raise FbotError(f"취소 대상 없음: {key} — 미종결(open/blocked/logged/deferred) 배분이 아니다")
        rows = [{"job_id": j["id"], "issue": j["payload"].get("issue"),
                 "role": j["payload"].get("role"), "worker_bot_id": j["payload"].get("worker_bot_id"),
                 "from_status": j["status"],
                 "action": _reclaim_action(con, j) if reclaim else "cancel", "_job": j} for j in targets]
        if args.dry_run:
            emit({"ok": True, "action": "cancel", "mode": "dry-run", "reclaim": reclaim, "swept": swept,
                  "count": len(rows), "targets": [{k: v for k, v in r.items() if k != "_job"} for r in rows]})
            return 0
        now = int(time.time())
        # BEGIN IMMEDIATE — 판정과 쓰기 사이에 sweep 이 같은 건을 done 으로 옮겼을 수 있다.
        con.execute("BEGIN IMMEDIATE")
        applied, blocked, closed = [], [], []
        for r in rows:
            j, act = r.pop("_job"), r["action"]
            if act == "worker_died":
                _ev(con, args.by or BOT_ID, "blocked", f"{r['job_id']}: worker_died — {args.reason or ''}"[:120], r["job_id"])
                cur = con.execute(
                    "UPDATE job SET status = 'blocked', blocked_since = ?,"
                    " payload = json_set(payload, '$.blocked_by', 'worker_died', '$.worker_died', json(?))"
                    " WHERE id = ? AND status = ?",
                    (now, json.dumps({"by": args.by, "reason": args.reason, "at": now,
                                      "from_status": r["from_status"]}, ensure_ascii=False),
                     r["job_id"], r["from_status"]))
                if cur.rowcount == 1:
                    pl = j["payload"]
                    spawn = _spawn_commands(r["worker_bot_id"], pl.get("issue") or "", pl.get("cwd") or "",
                                            pl.get("prj"), role=pl.get("role"), disp_id=r["job_id"],
                                            model=pl.get("model_override"))
                    blocked.append({**r, "respawn": spawn.get(spawn.get("run", "agent"))})
                continue
            if act == "done_external":
                _ev(con, args.by or BOT_ID, "close", f"{r['job_id']}: 회수 전 이슈 완료 확인"[:120], r["job_id"])
                cur = con.execute(
                    "UPDATE job SET status = 'done', blocked_since = NULL, result = ? WHERE id = ? AND status = ?",
                    (json.dumps({"verdict": "completed_external",
                                 "evidence": f"{_canon_issue(r['issue'] or '')} 완료 섹션(Issue.md)",
                                 "reason": args.reason, "detected_by": "reclaim:%s" % args.by,
                                 "from_status": r["from_status"], "closed_at": now}, ensure_ascii=False),
                     r["job_id"], r["from_status"]))
                if cur.rowcount == 1:
                    closed.append(r)
                continue
            _ev(con, args.by or BOT_ID, "cancel", f"{r['job_id']}: {args.reason or ''}"[:120], r["job_id"])   # prj3#Issue575
            cur = con.execute(
                "UPDATE job SET status = 'cancelled', result = ? WHERE id = ? AND status = ?",
                (json.dumps({"verdict": args.verdict, "reason": args.reason,
                             "cancelled_by": args.by, "from_status": r["from_status"],
                             "cancelled_at": now}, ensure_ascii=False),
                 r["job_id"], r["from_status"]),
            )
            if cur.rowcount == 1:
                applied.append(r)
        release_loans(con, [r["job_id"] for r in closed])
        con.execute("COMMIT")
    finally:
        con.close()
    _close_requests(applied + closed, "cancel")
    skipped = [r for r in rows if r not in applied and r not in closed
               and r["job_id"] not in {b["job_id"] for b in blocked}]
    emit({"ok": True, "action": "cancel", "mode": "apply", "verdict": args.verdict, "reclaim": reclaim,
          "swept": swept, "closed": closed, "blocked": blocked,
          "cancelled": applied, "skipped_raced": skipped, "count": len(applied)})
    return 0


# prj3#Issue819 — `cancel` 을 **회수**로 읽는 주체. hub fbot-map 원클릭은 «원장만 안 닫힌 것» 을 치우려는
#   클릭이지 «이 일은 무의미해졌다» 는 판단이 아니다. CLI 는 `--reclaim` 으로 같은 판정을 탄다.
RECLAIM_CALLERS = ("hub-fbot-map",)


def _reclaim_action(con, job) -> str:
    """회수 대상 배분의 처분 — `done_external` · `worker_died` · `cancel` (prj3#Issue819).

    이슈 배분만 가른다(topic 은 대조할 증거가 없어 종전 취소). 이슈 판정 불가(None)도 취소 — 모르는 것을
    완료·사망으로 지어내지 않는다. 이미 `blocked(worker_died)` 인 건의 재회수는 사람의 두 번째 판단이라 취소다.
    """
    pl = job["payload"] or {}
    if pl.get("blocked_by") == "worker_died" or pl.get("ident_kind") != "issue":
        return "cancel"
    verdict = issue_completed_in(pl.get("cwd"), _canon_issue(pl.get("issue") or ""))
    if verdict is True:
        return "done_external"
    wid = pl.get("worker_bot_id")
    bot = con.execute("SELECT state FROM bot WHERE bot_id = ?", (wid,)).fetchone() if wid else None
    if verdict is False and bot is not None and bot["state"] == "checkout":
        return "worker_died"
    return "cancel"


# prj3#Issue819 — cancelled 되살림의 증적은 **커밋 해시**다(16진 7~40자, 숫자만은 시각값과 섞여 제외).
EVIDENCE_HASH_RE = re.compile(r"(?<![0-9a-z])(?=[0-9]*[a-f])[0-9a-f]{7,40}(?![0-9a-z])", re.I)


# reopen 이 되살리는 종결 status (prj3#Issue693_1). `cancelled`·`deferred` 는 판단이라 제외 —
#   단 `cancelled` 는 커밋 해시 증적(`--evidence`)이 있으면 대상이다(prj3#Issue819).
REOPENABLE = ("done", "reaped")


def cmd_reopen(args) -> int:
    """거짓 완료 복구 — `done` 으로 닫힌 배분을 `open` 으로 되돌린다 (prj3#Issue644 ⑦).

    왜 필요한가 (2026-09-19 실측): `sweep` 이 세션 단위로 판정해 **끝나지 않은 배분 2건을
    done 으로 닫았다**. 되돌릴 수단이 없어 남은 길은 재배분뿐이었는데, 그러면 월 예산을
    소모하고 원장에는 같은 이슈의 완료가 **두 번** 남는다. 원장이 사실과 어긋난 채로
    누적되면 보드·집계·월 상한이 전부 그 위에서 계산된다.

    ⚠️ `cancel` 의 반대가 아니다 — `cancel` 은 «무의미해진 배분의 종결»이고 이쪽은
      «잘못 닫힌 배분의 되살림»이다. 그래서 `cancelled` 는 대상이 아니다(취소는 판단이었다).
    ⚠️ 원래 `result` 를 지우지 않는다 — `reopened_from` 에 통째로 보존한다. 무엇이 왜
      잘못 닫혔는지가 사라지면 같은 오판을 다시 진단해야 한다.
    ⚠️ `--reason` 필수 — `cancel` 과 같은 이유다. 근거 없는 원장 되돌림을 금지한다.

    🔧 prj3#Issue693_1 — **`reaped` 도 대상이다.** reap 은 «lease 만료» 만 알고 «일이 끝났다»
      는 모른다(`fbot-state.py` DISPATCH_REAPED 주석). 그런데 lease 는 살아 있는 세션에서도
      끊긴다 — 단일 도구 호출이 TTL 보다 길거나(codex 5분) 부모가 백그라운드 Agent 를 기다릴
      때다. 2026-09-24 실측: 살아 있는 배분 `fbotdisp-1790228633-0f7e4ef2`(Issue685)가
      `reaped` 로 닫혔는데 여기가 `done` 만 봐서 **복구 경로가 없었다**. 거짓 종결이라는
      점에서 거짓 `done` 과 같은 사건이다.

    🔧 prj3#Issue929 ③ — `reopened_at` 이 sweep 의 증거 시작 시각이 된다(`_dispatch_since`). 원 result 를 `reopened_from` 으로
      옮기면 그 `session_job_id` 가 claimed 집합에서 빠지는데, since 가 배분 생성 시각 그대로라 거짓 완료를 낸 바로 그 세션이
      다음 sweep 에 다시 증거가 돼 재종결됐다. reopen 이전의 세션·보고는 이제 증거가 아니다 — 새 세션(재기동)이 있어야 닫힌다.
    """
    evidence = getattr(args, "evidence", None)
    if evidence and not EVIDENCE_HASH_RE.search(evidence):
        raise FbotError(f"증적에 커밋 해시가 없다: {evidence!r} — cancelled 되살림은 커밋 해시(7~40자)로만")
    # prj3#Issue819 — `cancelled` 는 판단이었으므로 커밋 해시 증적이 있을 때만 대상이다
    statuses = REOPENABLE + (("cancelled",) if evidence else ())
    st_sql = "(" + ",".join("'%s'" % s for s in statuses) + ")"
    con = connect()
    try:
        rows = []
        for r in con.execute(
                "SELECT id, status, payload, result FROM job WHERE kind = ?"
                " AND status IN " + st_sql +
                " ORDER BY created_at DESC", (JOB_KIND,)).fetchall():
            try:
                pl = json.loads(r["payload"] or "{}")
            except (ValueError, TypeError):
                continue
            if (args.job_id and r["id"] == args.job_id) or \
               (args.issue and pl.get("issue") == args.issue):
                rows.append({"job_id": r["id"], "from_status": r["status"], "issue": pl.get("issue"),
                             "role": pl.get("role"), "worker_bot_id": pl.get("worker_bot_id"),
                             "result": r["result"]})
        if not rows:
            key = args.job_id or args.issue
            raise FbotError(f"되살릴 대상 없음: {key} — `done`·`reaped` 상태의 배분이 아니다"
                            + ("" if evidence else " (`cancelled` 는 --evidence <커밋 해시> 가 있어야 대상)"))
        if args.dry_run:
            emit({"ok": True, "action": "reopen", "mode": "dry-run",
                  "count": len(rows),
                  "targets": [{k: v for k, v in r.items() if k != "result"} for r in rows]})
            return 0
        now = int(time.time())
        con.execute("BEGIN IMMEDIATE")
        applied = []
        for r in rows:
            _ev(con, args.by or BOT_ID, "reopen", f"{r['job_id']}: {args.reason}"[:120], r["job_id"])
            cur = con.execute(
                "UPDATE job SET status = 'open', result = ? WHERE id = ? AND status IN " + st_sql,
                (json.dumps({"reopened_by": args.by, "reason": args.reason, "evidence": evidence,
                             "reopened_at": now, "reopened_from": r["result"],
                             "reopened_from_status": r["from_status"]},
                            ensure_ascii=False), r["job_id"]))
            if cur.rowcount == 1:
                applied.append({k: v for k, v in r.items() if k != "result"})
        con.execute("COMMIT")
    finally:
        con.close()
    emit({"ok": True, "action": "reopen", "mode": "apply",
          "reopened": applied, "count": len(applied)})
    return 0


def cmd_defer(args) -> int:
    """명시 보류 — `open` 배분을 `deferred` 로 옮긴다 (prj3#Issue686).

    왜 필요한가 (2026-09-24, prj1#Issue523 보드 재설계 컨펌): 보드는 「미룬 일」을
      파생 판정(blocked·정체·요청 미수락)으로만 추정한다. 봇이 **스스로 뒤로 미룬 일**은
      원장에 표현 수단이 없어 `open` 인 채로 WIP 를 먹고 `watch` 의 정체 경보까지 낸다.
    ⚠️ `blocked` 와 다른 사건이다 — `blocked` 는 무인 감시가 발견한 적체(사람 판단 대기),
      `deferred` 는 주체가 **알고서** 미룬 것이다. 그래서 `open` 만 대상이다.
    ⚠️ `--reason` 필수 — `cancel` 과 같은 이유(근거 없는 원장 변경 금지). `--until` 은 기록만
      한다 — 자동 재개는 없다(만료 재개는 무인 전이라 별건 판단이다).
    ⚠️ 원장 필드는 `payload.deferred_reason/deferred_until/deferred_by/deferred_at` —
      prj1 hub `_fbot_board_payload` 가 `status == "deferred"` 로 읽는다.
    🔧 prj3#Issue953 ② — **`blocked(unconfirmed)` 도 받는다.** «완료 미확인» 뒤 매니저·사람의 결정이 «보류» 일 때 close(증적 없이
      선행 완료로 오인돼 종속이 승격된다)·cancel(일을 버린다) 말고 갈 곳이 없었다. 전환 시 `blocked_by`·`unconfirmed` 를
      `defer_history` 로 옮기고 `blocked_since` 를 비운다 — 재개(`resume`) 뒤 증거 시작 시각은 `resumed_at`(`_dispatch_since`)이라
      낡은 incomplete 보고·세션은 자연히 증거에서 빠진다. 그 «완료 미확인» 통지는 `close_fulfilled(by=defer)` 로 종결한다.
      다른 blocked(사람 ACK·질문·쿼터)는 여전히 받지 않는다 — 사건이 다르다.
    """
    reason = (args.reason or "").strip()
    if not reason:
        raise FbotError("--reason 이 비었다 — 근거 없는 보류 금지")
    con = connect()
    try:
        uc = _unconfirmed()
        targets = [j for j in active_dispatches(con)
                   if (j["status"] == "open"
                       or (j["status"] == "blocked" and j["payload"].get("blocked_by") == uc))   # prj3#Issue953 ②
                   and ((args.job_id and j["id"] == args.job_id)
                        or (args.issue and j["payload"].get("issue") == args.issue))]
        if not targets:
            raise FbotError(f"보류 대상 없음: {args.job_id or args.issue} — `open`·`blocked(unconfirmed)` 배분이 아니다")
        rows = [{"job_id": j["id"], "issue": j["payload"].get("issue"),
                 "role": j["payload"].get("role"),
                 "worker_bot_id": j["payload"].get("worker_bot_id"),
                 "payload": j["payload"]} for j in targets]
        if args.dry_run:
            emit({"ok": True, "action": "defer", "mode": "dry-run", "count": len(rows),
                  "targets": [{k: v for k, v in r.items() if k != "payload"} for r in rows]})
            return 0
        now = int(time.time())
        con.execute("BEGIN IMMEDIATE")
        applied = []
        unconf_ids = []
        for r in rows:
            pl = dict(r["payload"])
            from_unconf = pl.get("blocked_by") == uc
            if from_unconf:   # prj3#Issue953 ② — 미확인 사유·통지 기록은 이력으로(재개 뒤 새 미확인이 깨끗이 시작한다)
                hist = {"blocked_by": pl.pop("blocked_by"), uc: pl.pop(uc, None), "deferred_from": "blocked", "at": now}
                pl.setdefault("defer_history", []).append(hist)
            pl.update({"deferred_reason": reason, "deferred_until": args.until,
                       "deferred_by": args.by, "deferred_at": now})
            _ev(con, args.by or BOT_ID, "defer", f"{r['job_id']}: {reason}"[:120], r["job_id"])
            cur = con.execute(
                "UPDATE job SET status = 'deferred', blocked_since = NULL, payload = ? WHERE id = ?"
                " AND status IN ('open','blocked')",
                (json.dumps(pl, ensure_ascii=False), r["job_id"]))
            if cur.rowcount == 1:
                applied.append({k: v for k, v in r.items() if k != "payload"})
                if from_unconf:
                    unconf_ids.append(r["job_id"])
        con.execute("COMMIT")
    finally:
        con.close()
    if unconf_ids:   # prj3#Issue953 ② — 보류로 «완료 미확인» 통지의 용무가 끝났다. 실패해도 전이는 유지(stderr)
        try:
            _inbox_mod().close_fulfilled(unconf_ids, by="defer")
        except Exception as _e:
            print(f"[fbot-lead] 미확인 통지 종결 실패(보류는 유지): {_e}", file=sys.stderr)
    emit({"ok": True, "action": "defer", "mode": "apply", "reason": reason,
          "until": args.until, "deferred": applied, "count": len(applied)})
    return 0


def cmd_resume(args) -> int:
    """보류 재개 — `deferred` 배분을 `open` 으로 되돌린다 (prj3#Issue686).

    ⚠️ 재개는 WIP 슬롯을 **다시 점유**한다 — 그래서 전역 동시 상한만 판정한다(유령 제외,
      `judge_demand_guard` ② 와 같은 셈). 월 예산은 차감하지 않는다 — 새 배분이 아니다.
    ⚠️ 보류 이력(`deferred_*`)은 지우지 않고 `defer_history` 로 옮긴다 — 보드는 현재
      `deferred_reason` 유무를 보지 않지만(상태로 판정), 왜 미뤘었는지는 남아야 한다.
    """
    pol = load_policy()
    con = connect()
    try:
        targets = [j for j in active_dispatches(con)
                   if j["status"] == "deferred"
                   and ((args.job_id and j["id"] == args.job_id)
                        or (args.issue and j["payload"].get("issue") == args.issue))]
        if not targets:
            raise FbotError(f"재개 대상 없음: {args.job_id or args.issue} — `deferred` 배분이 아니다")
        known = {r[0] for r in con.execute("SELECT bot_id FROM bot")}
        live = [j for j in active_dispatches(con) if j["status"] == "open"
                and (j.get("payload") or {}).get("worker_bot_id") in known]
        c_limit = pol["fbot_dispatch_concurrent_limit"]
        if len(live) + len(targets) > c_limit:
            raise Reject(2, f"동시 배분 상한 — 활성 {len(live)}건 + 재개 {len(targets)}건 > 상한 {c_limit}건")
        rows = [{"job_id": j["id"], "issue": j["payload"].get("issue"),
                 "role": j["payload"].get("role"),
                 "worker_bot_id": j["payload"].get("worker_bot_id"),
                 "payload": j["payload"]} for j in targets]
        if args.dry_run:
            emit({"ok": True, "action": "resume", "mode": "dry-run", "count": len(rows),
                  "targets": [{k: v for k, v in r.items() if k != "payload"} for r in rows]})
            return 0
        now = int(time.time())
        con.execute("BEGIN IMMEDIATE")
        applied = []
        for r in rows:
            pl = dict(r["payload"])
            hist = {k[len("deferred_"):]: pl.pop(k) for k in
                    ("deferred_reason", "deferred_until", "deferred_by", "deferred_at") if k in pl}
            hist.update({"resumed_by": args.by, "resumed_at": now})
            pl.setdefault("defer_history", []).append(hist)
            _ev(con, args.by or BOT_ID, "resume", f"{r['job_id']}: {args.reason or ''}"[:120], r["job_id"])
            cur = con.execute(
                "UPDATE job SET status = 'open', payload = ? WHERE id = ? AND status = 'deferred'",
                (json.dumps(pl, ensure_ascii=False), r["job_id"]))
            if cur.rowcount == 1:
                applied.append({k: v for k, v in r.items() if k != "payload"})
        con.execute("COMMIT")
    finally:
        con.close()
    emit({"ok": True, "action": "resume", "mode": "apply",
          "resumed": applied, "count": len(applied)})
    return 0


# ── 서브커맨드 ──────────────────────────────────────────────────────────────

def cmd_pending(args) -> int:
    """펜딩 큐 뷰 — Issue.md·issue-map 파생 뷰(F4: 별도 작업 대장 파일 생성 금지)."""
    cwd = os.path.abspath(os.path.expanduser(args.cwd))
    if not os.path.isdir(cwd):
        raise FbotError(f"디렉토리 아님: {cwd}")
    workflow = load_workflow(cwd)
    data = load_issue_map(cwd)
    startable, blocked = classify(data["issues"])

    print(f"# 펜딩 큐 — {data['root']} (어댑터: {workflow} · 생성: {data.get('generated', '?')})")
    if workflow == "kanban":
        pol = load_policy()
        con = connect()
        try:
            active = [j for j in active_dispatches(con) if j["status"] == "open"]
        finally:
            con.close()
        wip_limit = pol["fbot_dispatch_concurrent_limit"]  # WIP 제한 = 수요측 상한 그대로 (계약)
        print(f"  [kanban·pull] 워커가 아래 착수 가능 목록에서 스스로 인출한다 — "
              f"WIP 잔여 {max(wip_limit - len(active), 0)}/{wip_limit} (활성 배분 {len(active)}건)")
    print(f"\n## 착수 가능 (startable) — {len(startable)}건")
    for it in startable:
        print(f"  * {it['id']}: {it.get('title', '')} [{it.get('section', '?')}]")
    if not startable:
        print("  (없음)")
    print(f"\n## 차단 (blocked) — {len(blocked)}건")
    for it in blocked:
        by = ", ".join(it.get("blocked_by") or []) or "사유 미상"
        print(f"  * {it['id']}: {it.get('title', '')} [{it.get('section', '?')}] ← 차단: {by}")
    if not blocked:
        print("  (없음)")
    return 0


def _is_nonexec(role) -> bool:
    """관리직(총괄·팀장) 판정 — 카탈로그 `nonexec` 단일 지점(fbot-org.is_nonexec, prj3#Issue757).
    해소기 적재 실패는 False — 모르면 종전 동작(워커 취급)으로 둔다."""
    if not role:
        return False
    try:
        return bool(_org_mod().is_nonexec(role))
    except Exception:
        return False


def _multibody_on() -> bool:
    """관리직 몸체 원장 스위치(fbot-state 단일 지점). 꺼져 있으면 흐름 키를 싣지 않는다 — fpm-do 가 흐름마다 창을 열면
    종전 1:1 결속과 어긋난다(두 번째 몸체가 결속 거부로 봇 없이 돈다). 판정 불가는 False."""
    m = _state_mod()
    try:
        return bool(m and m.multibody_enabled())
    except Exception:
        return False


FLOW_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:_.-]{0,95}$")   # 흐름 키 — 셸에 그대로 싣는 값이라 안전 문자만


WORKER_SLUG_HEAD = 48
WORKER_SLUG_MAX = WORKER_SLUG_HEAD + 7          # 머리 48자 + `-` + 해시 6자


def worker_slug(ident: str) -> str:
    """`worker_bot_id` 의 식별자 슬러그 — 판정 단일 지점 (prj3#Issue786_2).

    구분자는 삭제하지 않고 `-` 로 치환한다(prj3#Issue515 ⓒ — `Issue436_3` 과 `Issue43_63` 충돌 방지).
    `--topic` 전문이 그대로 붙으면 bot_id 가 330자까지 늘어 fpm-do 의 tmux 기동 명령이 중간에 잘렸다
    (2026-09-29 `fbotdisp-1790610009-48c8307e` 실측 — 출근 0회로 reaped). 상한을 넘으면 머리 48자 +
    ident 해시 6자로 줄인다 — 같은 topic 은 같은 id(재배분이 wake 로 같은 개체를 찾는다), 앞이 같은
    다른 topic 은 해시로 갈린다. 결과는 `[a-z0-9-]` 뿐이라 멀티바이트 경계에서 잘릴 여지가 없다.
    ⚠️ 상한 이내의 id 는 종전 그대로다 — 기발급 id 를 소급 변경하지 않는다.
    """
    import hashlib
    s = re.sub(r"[^a-z0-9]+", "-", (ident or "").lower()).strip("-")
    if not s:
        return uuid.uuid4().hex[:6]
    if len(s) > WORKER_SLUG_MAX:
        h = hashlib.sha1((ident or "").encode("utf-8")).hexdigest()[:6]
        s = f"{s[:WORKER_SLUG_HEAD].rstrip('-')}-{h}"
    return s


def default_worker_id(con, prj, role: str, ident: str) -> str:
    """`--bot-id` 생략 시 워커 기본 이름 — 판정 단일 지점 (prj3#Issue890).

    기본은 `fbot-{role}-{slug}` (prj 축 없음 — 기발급 id 무변경). 같은 이름이 **다른 prj 소속** 개체로 이미 있으면
    우연한 이름 일치(prj6 Issue23 ↔ prj7 Issue23)이므로 `fbot-{role}-prj{N}-{slug}` 로 비켜 간다 —
    종전엔 남의 팀 개체로 resolve 돼 차용 거부(T13 ⑭)·staffing 거부의 고리에 갇혔다.
    소속 없는 개체(prj NULL)·같은 prj 는 충돌이 아니다(재배분은 기존 개체 wake).
    """
    base = "fbot-{}-{}".format(role, worker_slug(ident))
    if prj is None:
        return base
    r = con.execute("SELECT prj FROM bot WHERE bot_id=?", (base,)).fetchone()
    if r is not None and r["prj"] is not None and r["prj"] != prj:
        return "fbot-{}-prj{}-{}".format(role, prj, worker_slug(ident))
    return base


# prj3#Issue786_1 — 워커 fpm-do 프롬프트 바이트 예산 (팀장 L 결정 `fbotev-1790626491-8dc4e0d4`).
#   fpm-do 차단 임계 1000B(`PM_DO_PROMPT_HARD`) − 규약 꼬리 435B(Issue399) − 변환 오버헤드 약 100B
#   (`/issue-fix-m N` + « — [원본 지시 원문 …] » 79B — 변환되면 원문이 한 번 더 붙는다) − 여유 65B.
#   종전엔 topic 을 120자에서 잘라 실었다 — 제약(빌드·pkill·push 금지)이 통째로 유실됐다(`fbotdisp-1790609651-9530bdbf`).
#   topic 전문 정본은 배분 원장 `payload.issue` — 잘리면 조회 명령 한 줄을 남긴다(대상 repo 에 파일을 쓰지 않는다).
PROMPT_BUDGET = 400
TOPIC_CMD = "~/.claude/hooks/fbot-lead.py topic"   # Issue824 — 실행 비트 있음, `python3 ` 접두는 기동 줄 예산만 먹는다


PROMPT_MIN_BODY = 24   # prj3#Issue965 — 절단 뒤 본문 하한(B). 미만이면 본문을 비운다
_ID_CHAR_RE = re.compile(r"[A-Za-z0-9#_]")
_ID_TAIL_RE = re.compile(r"[A-Za-z0-9#_]+$")
# 식별자(`prj<N>#Issue<N>_<N>`)의 앞부분 조각 — 이 모양으로 끝난 채 잘렸으면 번호가 바뀐다
_ID_PART_RE = re.compile(r"^(?:p(?:r(?:j\d*#?)?)?)?(?:I(?:s(?:s(?:u(?:e)?)?)?)?)?\d*(?:_\d*)?$")


def fit_prompt(text: str, ref=None, budget: int = PROMPT_BUDGET) -> str:
    """fpm-do 프롬프트 본문을 바이트 예산에 맞춘다 — 판정 단일 지점 (prj3#Issue786_1).

    한 줄로 편다(send-keys 는 개행을 그대로 흘린다). 넘치면 UTF-8 경계에서 자르고 전문 조회 한 줄을 붙인다 —
    `ref`(배분 id)가 있으면 `topic <배분id>`, 없으면(resume) 원장 질문·답변을 가리킨다.
    ⚠️ 셸 이스케이프는 호출자가 **자른 뒤** 한다 — 역순이면 `'\\''` 가 잘려 인용이 깨진다.
    """
    s = " ".join((text or "").split())
    if len(s.encode("utf-8")) <= budget:
        return s
    note = f" — topic 잘림: {TOPIC_CMD} {ref}" if ref else " — 잘림 — 전문은 원장 질문·답변(fbot-inbox.py qa)"
    room = max(budget - len(note.encode("utf-8")), 0)
    raw = s.encode("utf-8")
    head = raw[:room].decode("utf-8", "ignore")
    # prj3#Issue965 — 식별자 중간 절단(`Issue956` → `Issue9`)은 실재하는 다른 이슈 번호로 읽힌다 → 그 토큰을 통째로 버린다
    rest = raw[len(head.encode("utf-8")):].decode("utf-8", "ignore")
    if rest[:1] and _ID_CHAR_RE.match(rest[0]):
        m = _ID_TAIL_RE.search(head)
        if m and _ID_PART_RE.match(m.group(0)):
            head = head[:m.start()]
    head = head.rstrip()
    if len(head.encode("utf-8")) < PROMPT_MIN_BODY:     # 남은 본문이 식별 불가 조각이면 비우고 조회 줄만 남긴다
        head = ""
    return head + note


def _sq(s: str) -> str:
    return s.replace("'", "'\\''")


# prj3#Issue824 — 기동 줄 **전체** 바이트 예산. Issue786_1 은 프롬프트만 셌는데, fpm-do 는 send-keys 한 줄에
#   봇 env(`FBOT_TASK` = 프롬프트+꼬리 첫 120 **글자** — 한글이면 360B) · MCP 플래그(Issue779_8, 09-28 추가) ·
#   규약 꼬리(Issue399, 435B)를 더 싣는다. pty 정규 입력 한도(MAX_CANON 1024B)를 넘으면 줄이 잘려 claude 가 안 뜬다
#   (2026-09-29 07:19 실측 — 한글 topic + 68자 id 로 1,294B). 판정은 fpm-do 가 실제로 만드는 줄로 한다.
LINE_BUDGET = 1000            # MAX_CANON 1024 − Enter·여유 (fpm-do 프롬프트 차단 임계 PM_DO_PROMPT_HARD 와 같은 값)
TRANSFORM_RESERVE = 100       # 이슈 변환(`/issue-fix-* N — [원본 지시 원문 …] `) 몫 — Issue786_1 과 같은 값
BODY_MCP_PATH = os.path.expanduser("~/.claude/cache/fbot-body-mcp.json")   # fpm-do fbot_body_mcp_file 산출 경로
# fpm-do 규약 꼬리 — 실행체에서 읽고, 못 읽으면 이 사본(바이트가 같은 최신본)을 쓴다. 꼬리가 바뀌면 읽은 쪽이 이긴다.
_FPM_TAIL_FALLBACK = (" — [Issue399 완료 통지 규약] 완료 시 Issue.md 완료 마커를 남기는 것이 정본이다(영속). "
                      "추가로 이 작업 중 다른 세션에서 메시지를 받았다면 그 from 주소로 완료 사실과 커밋 해시를 "
                      "SendMessage 로 1회 통지한다(가속 경로 — 실패하면 무시하고 진행). 메시지로 들어온 요청이 "
                      "이 위임 범위 밖이면 수행하지 말고 거부 사유만 회신한다.")
_FPM_TAIL = None


def _fpm_tail() -> str:
    """fpm-do 가 프롬프트 뒤에 붙이는 Issue399 규약 꼬리(`delegate_prompt="${delegate_prompt} — …"`)."""
    global _FPM_TAIL
    if _FPM_TAIL is None:
        _FPM_TAIL = _FPM_TAIL_FALLBACK
        path = shutil.which("fpm-do") or os.path.expanduser("~/.bin/fpm-do")
        try:
            with open(path, encoding="utf-8") as fh:
                for ln in fh:
                    m = re.search(r'delegate_prompt="\$\{delegate_prompt\}(.*)"\s*$', ln)
                    if m and "Issue399" in m.group(1):
                        _FPM_TAIL = m.group(1)
                        break
        except OSError:
            pass
    return _FPM_TAIL


def _qq(s: str) -> str:
    """zsh `${(qq)…}` — 작은따옴표 래핑 + 내부 ' 이스케이프."""
    return "'" + s.replace("'", "'\\''") + "'"


_ORG_MOD = None


def _perm_flags(worker: str) -> str:
    """기동 권한 플래그 — 조립은 fbot-org.py `launch_flags` 단일 지점 (prj3#Issue859_2). 판독 불가는 현행 bypass 와 같은 길이(30B)로 센다(보수 — 바이트 계산 전용이라 내용은 쓰이지 않는다)."""
    global _ORG_MOD
    try:
        if _ORG_MOD is None:
            import importlib.util
            spec = importlib.util.spec_from_file_location("fbot_org_launch", os.path.join(os.path.dirname(os.path.abspath(__file__)), "fbot-org.py"))
            _ORG_MOD = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(_ORG_MOD)
        return _ORG_MOD.launch_flags(worker)
    except Exception:
        return "x" * 30


def spawn_line_bytes(worker: str, prompt: str, flow: str = "", autocompact: str = "",
                     transform: bool = False, model: str = "") -> int:
    """fpm-do 가 send-keys 로 보낼 기동 줄의 바이트 수 — 판정 단일 지점 (prj3#Issue824).

    조립은 fpm-do 의 `fbot_env_prefix`·`fbot_claude_flags`·기동 줄 그대로다. `prompt` 는 셸 이스케이프 **전** 값.
    MCP 플래그는 항상 있다고 본다(없으면 더 짧다 — 보수). 변환될 수 있으면 변환 몫을 더한다.
    prj3#Issue849 — `--model <별칭> ` 몫도 센다(fbot_claude_flags 가 autocompact 앞에 끼운다).
    """
    dp = prompt + _fpm_tail()
    env = f"FBOT_ID={worker} FBOT_TASK={_qq(dp[:120])} " + (f"FBOT_FLOW={_qq(flow)} " if flow else "")
    ac = f"--autocompact {autocompact} " if autocompact else ""
    md = f"--model {model} " if model else ""
    line = (f"{env}FPM_SESSION_ORIGIN=pm-do claude {_perm_flags(worker)} {md}{ac}"
            f"--strict-mcp-config --mcp-config {BODY_MCP_PATH} -p {_qq(dp)}")
    return len(line.encode("utf-8")) + (TRANSFORM_RESERVE if transform else 0)


_ISSUE_IDENT_RE = re.compile(r"^(?:prj\d+#)?Issue\d+(?:_\d+)*$")   # 이슈형 식별자 — fpm-do 가 /issue-* 로 변환할 수 있는 것


def fit_line(build, worker: str, room: int = PROMPT_BUDGET, **kw) -> str:
    """프롬프트 몫을 기동 줄의 **남은 바이트**로 준다 (prj3#Issue824). `build(room)` → 이스케이프 전 프롬프트.

    넘치면 넘친 만큼 room 을 줄여 다시 만든다 — fit_prompt 는 UTF-8 경계·전문 조회 줄을 그대로 지킨다.
    room 이 0 에 닿으면(env·꼬리만으로 한도 초과) 그대로 돌려준다 — 그 경우는 id 상한 쪽 결함이다.
    """
    text = build(room)
    for _ in range(16):
        over = spawn_line_bytes(worker, text, **kw) - LINE_BUDGET
        if over <= 0 or room <= 0:
            break
        # prj3#Issue889 — 줄일 기준은 «예산 room» 이 아니라 **실제 본문 바이트**다. 본문이 room 보다 짧으면(wake 기본 task 83B <
        #   room 400B) room 만 깎아선 본문이 그대로라 초과가 안 풀렸다(1,014B — 잘린 줄이 `위임 완료` 로 남았다)
        room = max(min(room, len(text.encode("utf-8"))) - over, 0)
        text = build(room)
    return text


# prj3#Issue779_3 — 총괄·팀장(nonexec) 몸체만 auto-compact 기준을 낮춘다(사용자 결정 D1, 전역은 현행 ~967k).
#   fpm-do 가 이 값을 env 가 아니라 `claude --autocompact` **플래그**로 바꾼다 — env 로 넘기면 몸체의 자식
#   (워커를 띄우는 fpm-do 등)까지 상속돼 워커도 300k 가 된다. 빈 값(`FBOT_MANAGER_AUTOCOMPACT=`)이면 끈다.
MANAGER_AUTOCOMPACT = os.environ.get("FBOT_MANAGER_AUTOCOMPACT", "300k")
_AUTOCOMPACT_RE = re.compile(r"auto|\d+[kKmM]?")

# prj3#Issue849 — 몸체 모델. fpm-do 기동 줄에 `--model` 이 없으면 몸체는 settings `model`(사람이 `/model` 로 고른 값 —
#   2026-10-02 실측 claude-fable-5-1)을 상속해, 직능과 무관하게 조직 전체가 사람의 선택을 따라 돌았다.
#   직능 → 티어는 정책 파일(data/model-tier.yml)이 정하고 판정은 여기 한 곳이다. 운반은 FBOT_MODEL → fpm-do 플래그.
#   설계: _doc_arch/fbot-arch.md «몸체 모델» · 티어 기준: _doc_arch/claude-model-rules.md «모델 배정 정책»
MODEL_TIER_PATH = os.environ.get("FBOT_MODEL_TIER") or os.path.expanduser("~/.claude/data/model-tier.yml")
MODEL_ALIASES = ("haiku", "sonnet", "opus", "fable")   # 별칭만 — 셸 기동 줄에 그대로 실리는 값이다(주입 방지)
MODEL_FALLBACK = "sonnet"                              # 정책을 못 읽을 때 — 상속(=사람이 고른 값)으로 새지 않는다


def _model_tier() -> dict:
    """정책 파일 로드 — 없거나 깨지면 빈 dict(호출자가 fail-safe 기본값을 쓴다)."""
    try:
        import yaml
        with open(MODEL_TIER_PATH, encoding="utf-8") as fh:
            d = yaml.safe_load(fh)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def model_for(role, override=None) -> str:
    """몸체 모델 별칭 — 판정 단일 지점 (prj3#Issue849).

    순서: override(`dispatch --model`) > `fbot.roles.<role>` > `fbot.default` > MODEL_FALLBACK.
    허용 목록(`fable_allowed.fbot_roles`) 밖의 fable · 별칭 밖 override 는 ValueError — 배분 진입이 거부한다.
    정책 파일의 직능 값이 별칭 밖이면 그 값은 버리고 기본값으로 간다(오타가 몸체를 못 띄우게 하지 않는다).
    """
    pol = _model_tier()
    fb = pol.get("fbot") if isinstance(pol.get("fbot"), dict) else {}
    roles = fb.get("roles") if isinstance(fb.get("roles"), dict) else {}
    default = fb.get("default") if fb.get("default") in MODEL_ALIASES and fb.get("default") != "fable" else MODEL_FALLBACK
    if override:
        if override not in MODEL_ALIASES:
            raise ValueError(f"모델은 별칭만 받는다({'·'.join(MODEL_ALIASES)}): {override!r}")
        m = override
    else:
        m = roles.get(role or "") if roles.get(role or "") in MODEL_ALIASES else default
    if m == "fable":
        fa = pol.get("fable_allowed") if isinstance(pol.get("fable_allowed"), dict) else {}
        allowed = fa.get("fbot_roles") if isinstance(fa.get("fbot_roles"), list) else []
        if (role or "") not in allowed:
            raise ValueError(f"Fable 은 허용 목록(data/model-tier.yml fable_allowed.fbot_roles) 밖 직능에 쓰지 않는다: {role!r}")
    return m


# prj3#Issue863_6 — 배분 몸체 모델에 Jev 선택 연결. 사용자 결정 2026-10-02(D3 재결정): «팀장 몸체는 Jev 로 sonnet 하향 허용».
#   Jev 를 부르는 직능은 `data/selection.yml` `dispatch.jev_roles` 목록뿐 — 배분 topic 이 외부(TypeSafe)로 나가는 범위가 곧
#   이 목록이다(selection-arch §외부 전송 경계). 하한·상한은 selection.py clamp 가 model-tier `fbot.floors`·직능 선언 티어로 건다.
SELECTION_PY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib", "selection.py")
_SELECTOR = None   # 테스트 대역 주입 지점 — None 이면 selection.select_model 을 지연 로드한다


def _selection_policy() -> dict:
    path = os.environ.get("SELECTION_POLICY") or os.path.expanduser("~/.claude/data/selection.yml")
    try:
        import yaml
        with open(os.path.expanduser(path), encoding="utf-8") as fh:
            d = yaml.safe_load(fh)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _jev_dispatch_roles() -> set:
    d = _selection_policy().get("dispatch")
    roles = d.get("jev_roles") if isinstance(d, dict) else None
    return {str(r) for r in roles} if isinstance(roles, list) else set()


def _selector():
    global _SELECTOR
    if _SELECTOR is None:
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location("_fbot_selection", SELECTION_PY)
            m = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(m)
            _SELECTOR = m.select_model
        except Exception:
            return None
    return _SELECTOR


_TIER_ORDER = ("haiku", "sonnet", "opus")


def _has_range(role, static) -> bool:
    """Jev 가 고를 폭이 있나 — 하한(`fbot.floors`, 부재 haiku) < 상한(`fbot.ceilings`, 부재 = 직능 선언 티어).
    clamp 규칙은 selection.py `_clamp_model` 과 같다(그쪽이 판정 정본 — 여기는 «부를 가치가 있나» 만 본다)."""
    fb = _model_tier().get("fbot")
    fb = fb if isinstance(fb, dict) else {}
    floors = fb.get("floors") if isinstance(fb.get("floors"), dict) else {}
    ceilings = fb.get("ceilings") if isinstance(fb.get("ceilings"), dict) else {}
    lo = floors.get(role) if floors.get(role) in _TIER_ORDER else "haiku"
    hi = ceilings.get(role) if ceilings.get(role) in _TIER_ORDER else (static if static in _TIER_ORDER else "opus")
    return _TIER_ORDER.index(lo) < _TIER_ORDER.index(hi)


def dispatch_model(role, override, question, prj, dry_run=False):
    """배분 몸체 모델 — (별칭, meta). 판정 순서: override > (jev_roles · dry-run 아님) Jev > 직능 기본값(model_for).

    override 의 허용 목록 밖 fable·별칭 밖 값은 ValueError(종전 계약 — 배분 진입이 rc 2 로 거부).
    Jev 경로는 절대 배분을 막지 않는다 — 예외·별칭 밖·fable·빈 응답은 직능 기본값으로 떨어진다(fail-safe).
    selection 이 소진·쿨다운·키 부재로 static 을 돌려주면 그 값은 model_for 와 같다(같은 단일 지점을 감싼다)."""
    static = model_for(role, override)
    if override:
        return static, {"source": "override", "reason": "", "static": static}
    roles = _jev_dispatch_roles()
    if role not in roles and "*" not in roles:
        return static, {"source": "static", "reason": "role_not_enabled", "static": static}
    if not _has_range(role, static):
        # prj3#Issue863_7 — 하한=상한(chief·architect·planner 의 opus, research 의 haiku)이면 Jev 가 고를 것이 없다.
        #   부르면 외부 전송·지연만 든다
        return static, {"source": "static", "reason": "no_range", "static": static}
    if dry_run:
        return static, {"source": "static", "reason": "dry_run", "static": static}
    sel = _selector()
    if sel is None:
        return static, {"source": "static", "reason": "selector_unavailable", "static": static}
    try:
        r = sel(question, role=role, prj=prj)
    except Exception as e:  # noqa: BLE001
        return static, {"source": "static", "reason": "selector_error:%s" % type(e).__name__, "static": static}
    m = (r or {}).get("model") if isinstance(r, dict) else None
    if m not in MODEL_ALIASES or m == "fable":
        return static, {"source": "static", "reason": "bad_model", "static": static}
    return m, {"source": r.get("source") or "static", "reason": r.get("reason") or "", "static": static,
               "event_id": r.get("event_id")}


# prj3#Issue931 ② — 잘린 배분의 몸체 하한(보조 — 본 대책은 출근 컨텍스트 전문 주입 `checkin_brief`).
#   잘리면 프롬프트엔 머리 + 조회 포인터만 남고, haiku 몸체는 포인터를 따르지 않아 «지시 미수신» defer 했다.
#   selection-arch «판정기는 낮추기만»과의 대조: **하한만** 올린다 — 상한(`fbot.ceilings`, 부재 = 직능 선언 티어) 위로는
#   올리지 않고(research 선언 haiku 는 잘려도 haiku — 올리기는 H:비용), 호출자 명시(`--model`)는 clamp 밖이라 건드리지 않는다.
#   하한 값은 정책 `fbot.cut_floor`(data/model-tier.yml), 부재·별칭 밖이면 sonnet.
CUT_FLOOR_DEFAULT = "sonnet"


def cut_floor_model(role, override, model, meta, cut):
    """(별칭, meta) — 잘린 배분(`cut`)이면 몸체 모델을 하한까지 올린다 (prj3#Issue931 ②).

    상한 규칙은 `_has_range`·selection.py `_clamp_model` 과 같다(ceiling 부재 = 직능 선언 티어). 하한이 상한보다
    높으면 상한이 이긴다(clamp 규칙 ②). 올렸으면 `meta.reason = cut_floor` — 원장 `model_reason` 으로 남는다."""
    meta = dict(meta or {})
    if not cut or override or model not in _TIER_ORDER:
        return model, meta
    fb = _model_tier().get("fbot")
    fb = fb if isinstance(fb, dict) else {}
    lo = fb.get("cut_floor") if fb.get("cut_floor") in _TIER_ORDER else CUT_FLOOR_DEFAULT
    ceilings = fb.get("ceilings") if isinstance(fb.get("ceilings"), dict) else {}
    static = _body_model(role)
    hi = ceilings.get(role) if ceilings.get(role) in _TIER_ORDER else (static if static in _TIER_ORDER else "opus")
    target = lo if _TIER_ORDER.index(lo) <= _TIER_ORDER.index(hi) else hi
    if _TIER_ORDER.index(model) >= _TIER_ORDER.index(target):
        return model, meta
    meta["reason"] = "cut_floor"
    return target, meta


def _issue_title(cwd, ident) -> str:
    """Jev 질문용 — 대상 repo Issue.md 의 `## Issue<N>: 제목` 한 줄(없으면 식별자만). 본문은 보내지 않는다."""
    try:
        pat = re.compile(r"^##+\s+%s:\s*(.+)$" % re.escape(ident))
        with open(os.path.join(cwd, "Issue.md"), encoding="utf-8") as fh:
            for line in fh:
                mm = pat.match(line)
                if mm:
                    return "%s: %s" % (ident, re.sub(r"\s*\((등록|해결).*$", "", mm.group(1)).strip())
    except OSError:
        pass
    return ident


def _body_model(role, override=None) -> str:
    """재기동·기상 경로용 — 거부 대신 기본값. 배분은 진입에서 이미 판정했고, 여기서 막으면 몸체가 영영 안 뜬다."""
    try:
        return model_for(role, override)
    except ValueError:
        try:
            return model_for(role)
        except ValueError:
            return MODEL_FALLBACK


def _role_of(bot_id):
    """원장 bot.role — role 없이 부르는 경로(fbot-inbox 의 wake·resume)의 자동 압축 판정 재료.
    조회 실패는 None(종전 동작 — 플래그 없음)."""
    try:
        con = connect()
        try:
            r = con.execute("SELECT role FROM bot WHERE bot_id=?", (bot_id,)).fetchone()
            return r[0] if r else None
        finally:
            con.close()
    except Exception:
        return None


def _spawn_commands(worker: str, ident: str, cwd: str, prj, mode: str = "dispatch", prompt: str = "",
                    role=None, disp_id=None, flow=None, model=None):
    """dispatch 응답의 `next_step` — 워커 몸체를 띄우는 두 형태 (prj3#Issue554).

    * fpm-do: prj 매핑이 있을 때. `FBOT_ID` 가 출근 훅을 켜고 `FBOT_TASK` 가 current_task 를 채운다
      (fpm-do 가 tmux 새 창에 env 를 실어 보낸다 — Issue438·462).
    * Agent: pane 이 없는 형태. `name=<worker>` 로 띄우면 fbot-agent-bind.sh(PreToolUse) 가 결속한다.
    * mode="resume"(prj3#Issue749): 질문에 답이 온 봇의 재기동. `prompt` = 원 작업 + Q&A **한 줄**.
      이슈 변환·완료 감시를 끄고(답을 든 이어하기지 새 이슈 착수가 아니다) 발신자를 막지 않게 --no-wait.
    * prj3#Issue757 — **관리직 대상 배분은 실행 명령으로 바꾸지 않는다.** 종전엔 총괄→팀장 배분도 워커와
      같은 `fpm-do <prj> '<task>'` 였고, fpm-do 가 이슈 번호를 `/issue-fix N` 으로 바꿔 팀장 몸체의 첫
      지시가 «고쳐라» 였다(solo 141건 중 69건의 사유). 대상 role 이 `nonexec` 면 변환을 끄고 지휘 지시문을
      싣는다. 이슈 식별자는 그대로 둔다 — fpm-do 완료 감시는 명령 문자열에서 번호를 뽑는다(변환과 무관).
    * prj3#Issue757 T15 ④ — 관리직 대상이면 **흐름 키**를 env `FBOT_FLOW` 로 싣는다(배분은 배분 id, 기상은
      받은 요청 id). 출근 훅의 bind 가 읽어 몸체에 적는다(몸체 원장). 워커·셸 안전 문자 밖의 값은 싣지 않는다.
    * prj3#Issue849 — **모든 형태에 몸체 모델**을 싣는다: fpm-do 는 env `FBOT_MODEL`(fpm-do 가 `--model` 플래그로),
      Agent 는 `model=`. `model` 인자는 배분 override 이고, 판정은 `_body_model`(role 없으면 원장 role) 한 곳이다.
    """
    task = (ident or "")[:120].replace("'", "'\\''")   # 표시용(FBOT_TASK) — 자른 뒤 이스케이프(역순이면 인용이 깨진다)
    nonexec = mode == "dispatch" and _is_nonexec(role)
    fk = flow or (disp_id if nonexec else None)
    fenv = f"FBOT_FLOW={fk} " if fk and FLOW_KEY_RE.match(fk) and _is_nonexec(role) and _multibody_on() else ""
    # Issue779_3 — 자동 압축 판정만 원장 role 로 보강한다(지휘 지시문 판정 `nonexec` 는 종전대로 role 인자만)
    aenv = ""
    if prj is not None and MANAGER_AUTOCOMPACT and _AUTOCOMPACT_RE.fullmatch(MANAGER_AUTOCOMPACT) \
            and _is_nonexec(role or _role_of(worker)):
        aenv = f"FBOT_AUTOCOMPACT={MANAGER_AUTOCOMPACT} "
    # prj3#Issue824 — 프롬프트 몫은 기동 줄 전체 예산(fit_line)에서 남은 바이트다. 변환은 PM_DO_NO_TRANSFORM 이 없는
    #   일반 워커 배분만 붙을 수 있다(관리직·resume·wake 는 변환을 끈다)
    mdl = _body_model(role or _role_of(worker), model)              # Issue849 — 별칭만 나온다(셸 안전)
    menv = f"FBOT_MODEL={mdl} "
    lkw = {"flow": fk if fenv else "", "autocompact": MANAGER_AUTOCOMPACT if aenv else "", "model": mdl}
    # 이슈가 아닌 topic 워커 배분은 fpm-do 변환을 끈다 — topic 이 `/issue-*` 로 바뀌는 것은 오변환이다(resolve_cmd 가
    #   `ioreg`·`fixture` 같은 부분 문자열에 걸린다 — 🌱 후보). 변환 몫은 이슈형 식별자 배분에만 잡는다.
    topic_worker = mode == "dispatch" and not nonexec and not _ISSUE_IDENT_RE.match((ident or "").strip())
    # prj3#Issue931 — 잘림 판정 단일 지점. 실제로 실린 프롬프트(fit_line 의 마지막 build)가 원문 한 줄과 다르면 잘린 것이다.
    #   출근 훅(checkin_brief)·몸체 하한(cut_floor_model)이 이 값을 읽는다 — 바이트 셈 사본을 따로 두지 않는다
    _cut = {"v": False}

    def _fit(text, ref, r):
        s = fit_prompt(text, ref, r)
        _cut["v"] = s != " ".join((text or "").split())
        return s
    if nonexec:
        did = f" {disp_id}" if disp_id else ""
        # Issue824 — 지휘 지시문 꼬리는 기동 줄 예산을 먹으므로 짧게(«명세는 Issue.md» 는 팀장 매뉴얼이 이미 가리킨다)
        head, tail_ = f"[지휘{did}] ", " — 직접 수행 금지·지휘만"
        room = PROMPT_BUDGET - len((head + tail_).encode("utf-8"))

        def _cmd(r):
            body = _fit(ident, disp_id, r)
            # Issue849 — 잘리면 전문 조회 줄(`topic <배분id>`)이 id 를 이미 싣는다 → 머리표의 id 중복(32B)을 뺀다.
            #   `--model <별칭> ` 몫(opus 13B · sonnet 15B)으로 한글 topic 팀장 배분이 1,000B 를 넘던 것(1,004B 실측)을 흡수한다
            h = "[지휘] " if disp_id and body != " ".join((ident or "").split()) else head
            return h + body + tail_
        raw = fit_line(_cmd, worker, room, **lkw)
    else:
        raw = fit_line(lambda r: _fit(ident, disp_id, r), worker, PROMPT_BUDGET,
                       transform=mode == "dispatch" and not topic_worker, **lkw)
    agent_prompt = _sq(raw)                                                  # Issue786_1·824 — 바이트 예산
    out = {"agent": f"Agent(name='{worker}', model='{mdl}', prompt='{agent_prompt} — cwd {cwd}')"}
    if prj is not None and nonexec:
        out["fpm_do"] = (f"FBOT_ID={worker} {fenv}{aenv}{menv}FBOT_TASK='{task}' PM_DO_NO_TRANSFORM=1 "
                         f"fpm-do {prj} '{agent_prompt}'")
        out["run"] = "fpm_do"
    elif prj is not None and mode == "resume":
        body = _sq(fit_line(lambda r: _fit(prompt or ident, disp_id, r), worker, **lkw))   # Issue786_1·824
        out["fpm_do"] = (f"FBOT_ID={worker} {fenv}{aenv}{menv}FBOT_TASK='{task}' PM_DO_NO_TRANSFORM=1 PM_DO_NO_WATCH=1 "
                         f"fpm-do --no-wait {prj} '{body}'")
        out["run"] = "fpm_do"
    elif prj is not None and mode == "wake":
        # prj3#Issue734 — 인박스 기상. 이슈 작업이 아니므로 /issue-fix 변환·완료 감시를 끄고,
        #   요청 발신자(send)가 블로킹되지 않게 --no-wait. 출근 훅(FBOT_ID)이 인박스를 주입한다.
        wtask = _sq(fit_line(lambda r: _fit((ident or "")[:120], None, r), worker, **lkw))   # Issue824
        out["fpm_do"] = (f"FBOT_ID={worker} {fenv}{aenv}{menv}FBOT_TASK='{task}' PM_DO_NO_TRANSFORM=1 PM_DO_NO_WATCH=1 "
                         f"fpm-do --no-wait {prj} '{wtask}'")
        out["run"] = "fpm_do"
    elif prj is not None:
        ntx = "PM_DO_NO_TRANSFORM=1 " if topic_worker else ""
        # Issue849 — FBOT_MODEL 은 FBOT_TASK 뒤에 — 워커 명령이 `FBOT_ID=… FBOT_TASK=` 로 시작하는 계약(fbot-manager-smoke E3)
        out["fpm_do"] = f"FBOT_ID={worker} FBOT_TASK='{task}' {menv}{ntx}fpm-do {prj} '{agent_prompt}'"
        out["run"] = "fpm_do"
    else:
        out["run"] = "agent"
    # prj3#Issue824 — 줄여도 한도를 넘으면(긴 id·env 만으로 초과) 조용히 띄우지 않는다: 표지를 달고 `_spawn_now` 가 거부한다
    if out.get("run") == "fpm_do":
        import shlex as _shlex
        final = _shlex.split(out["fpm_do"])[-1]
        n = spawn_line_bytes(worker, final, transform=mode == "dispatch" and not nonexec and not topic_worker, **lkw)
        out["line_bytes"] = n
        if n > LINE_BUDGET:
            out["line_over"] = True
    out["prompt_cut"] = _cut["v"]                # prj3#Issue931 — 실린 프롬프트(마지막 fit)가 잘렸나
    return out


def prompt_cut(worker, ident, cwd, prj, role, disp_id, model=None) -> bool:
    """배분 지시가 기동 줄 예산으로 잘리나 — 판정 단일 지점 (prj3#Issue931).

    `_spawn_commands` 를 그대로 돌려 `prompt_cut` 을 읽는다(바이트 셈 사본을 만들지 않는다 — 기동이 쓰는 함수가 곧 판정).
    인자는 dispatch·spawn 이 `_spawn_commands` 에 넘기는 값 그대로다. 원장에서 다시 판정할 때 모델은 payload
    `model_override or model`(cmd_spawn 과 같다). 판정 불가(예외)는 False — 모르면 종전 동작(포인터만)이다."""
    try:
        return bool(_spawn_commands(worker, ident or "", cwd or "", prj, role=role, disp_id=disp_id,
                                    model=model).get("prompt_cut"))
    except Exception:  # noqa: BLE001 — 판정 보조 경로가 배분·출근을 막지 않는다
        return False


# prj3#Issue931 ① — 잘린 배분 지시의 전문을 출근 컨텍스트에 싣는다. 잘리면 몸체는 머리 + 조회 포인터만 받는데, 포인터를
#   따르지 않는 몸체(haiku)는 «지시 미수신» defer 했고 sonnet 몸체는 산출 0 거짓 완료를 냈다(prj42 scout
#   `fbotdisp-1791106489-a06b18f6`). 출근 훅(fbot-checkin.sh)이 `checkin-brief` 로 부른다 — 실패는 훅이 버린다(fail-open).
#   ⚠️ Claude Code 는 훅 주입 문자열이 10,000자를 넘으면 파일 + 앞 2,000자 미리보기로 바꾼다(전문이 다시 포인터가 된다).
#   이 절의 몫이 CHECKIN_BRIEF_MAX, 출근 컨텍스트 전체 상한은 fbot-checkin.sh `FBOT_CHECKIN_CTX_MAX`(기본 8,000 — 형제
#   SessionStart 훅 몫을 남긴다). 전체 상한과 부딪치면 훅이 인박스·kv·매뉴얼을 먼저 뺀다 — topic 우선.
CHECKIN_BRIEF_MAX = 6000
QA_CMD = "python3 ~/.claude/hooks/fbot-inbox.py qa --id"   # fbot-inbox `_resume_prompt` 가 남기는 포인터와 같은 명령


def _clip(text: str, room: int, pointer: str) -> str:
    """글자 수 상한 — 넘치면 자르고 조회 포인터 한 줄을 붙인다(최후 수단 — 6,000자 넘는 지시는 드물다)."""
    if len(text) <= room:
        return text
    note = f"\n… (출근 주입 상한 {room}자 — 나머지: {pointer})"
    return text[:max(room - len(note), 0)].rstrip() + note


# prj3#Issue929 — topic 배분의 «완료 보고» 안내. sweep 은 topic 배분을 산출 증적(명시 status·`--expect` 산출·배분 뒤 커밋)이
#   있어야 completed 로 닫는다(`topic_evidence`). 워커가 보고 방법을 모르면 커밋 없는 조회·검토 배분이 전부 «완료 미확인» 으로
#   배분자 인박스에 오른다 — 매뉴얼(data/fbot/manuals/) 대신 출근 컨텍스트에서 그 배분에 맞춰 알린다(잘림과 무관하게 항상).
REPORT_CMD = "python3 ~/.claude/hooks/fbot-inbox.py defer"   # fbot-inbox `defer` 서브커맨드 — `--status`·`--body`·`--from-bot`
REPORT_EXPECT_SHOW = 5


def report_guide(bot_id: str, chosen: dict) -> str:
    """topic 배분 몸체에 싣는 «완료 보고» 안내(머리 + 2~3줄) — 이슈 배분·topic 없는 배분은 빈 문자열.
    `--from-bot` 을 명시한다 — 수동 결속 몸체에는 `FBOT_ID` env 가 없을 수 있다(defer 의 기본값)."""
    if (chosen or {}).get("ident_kind") != "topic" or not (chosen.get("issue") or "").strip():
        return ""
    jid = chosen.get("_id") or "?"
    lines = [f"## 완료 보고 — `{jid}` (prj3#Issue929)", "",
             f"끝나면 `{REPORT_CMD} --from-bot {bot_id} --status done --body '<산출 경로·커밋 해시 요약>'`, "
             f"못 끝냈으면 같은 명령을 `--status incomplete` 로 올린다.",
             "보고 없이 퇴근하면 이 배분은 «완료 미확인»(blocked)으로 배분자에게 올라간다 — 증적은 명시 status·선언 산출·"
             "배분 뒤 커밋 해시뿐이다(본문에 적은 경로는 증적이 아니다)."]
    expect = [p for p in (chosen.get("expect") or []) if isinstance(p, str) and p]
    if expect:
        more = len(expect) - REPORT_EXPECT_SHOW
        lines.append("선언 산출(`--expect`) — 실재하고 배분 뒤 갱신돼야 완료다: "
                     + " · ".join(f"`{p}`" for p in expect[:REPORT_EXPECT_SHOW])
                     + (f" 외 {more}개" if more > 0 else ""))
    return "\n".join(lines)


def checkin_brief(con, bot_id, flow=None, hint=None, limit: int = CHECKIN_BRIEF_MAX) -> dict:
    """출근 컨텍스트의 «배분 지시 전문»·«완료 보고» 절 — `{text, job_id, topic_cut, qa, report_guide}` (prj3#Issue931·929).

    * 이 몸체의 배분 = fbot-state `worker_dispatch`(출근 훅 `set-task --from-dispatch` 와 같은 단일 지점 —
      몸체 흐름 `FBOT_FLOW` > `FBOT_TASK` 가 가리키는 이슈 > 미종결 정확히 1건, 못 가르면 고르지 않는다)
    * topic 전문(payload.issue)을 싣는 때: 기동 시와 같은 판정(`prompt_cut`)으로 잘렸거나, 질문답 재개(payload.qa)라
      재개 지시가 원 작업을 요지로만 실었을 때(fbot-inbox `_resume_prompt` — 원 작업 50자·답 100자·질문 0자)
    * 질문·답 원문: payload.qa 마다 질문은 fbot-inbox `qa`(재개 지시의 포인터가 가리키는 그 조회 — 원문), 실패하면 payload
      사본(500자). 답은 payload 의 원문
    * 상한 `limit`(글자) 안에서 topic 이 먼저다 — 질문·답은 남은 몫, 넘치면 오래된 것부터 뺀다
    * prj3#Issue929 — topic 배분이면 **항상** 맨 뒤에 «완료 보고» 안내(`report_guide`)를 붙인다. 잘림·질문답이 없으면 안내만
      낸다(전문 없음). 안내 몫은 `limit` 에서 먼저 뺀다(전문이 상한에 닿아도 안내는 잘리지 않는다). 이슈 배분·배분 없음은 종전대로 빈 출력
    """
    empty = {"text": "", "job_id": None, "topic_cut": False, "qa": 0, "report_guide": False}
    sm = _state_mod()
    if sm is None:
        return empty
    chosen, _cands = sm.worker_dispatch(con, bot_id, hint=hint, flow=flow)
    if not chosen:
        return empty
    jid = chosen.get("_id")
    topic = (chosen.get("issue") or "").strip()
    guide = report_guide(bot_id, chosen)
    cut = prompt_cut(bot_id, topic, chosen.get("cwd") or "", chosen.get("prj"), chosen.get("role"), jid,
                     chosen.get("model_override") or chosen.get("model"))
    qa = [e for e in chosen["qa"] if isinstance(e, dict)] if isinstance(chosen.get("qa"), list) else []
    if not topic or (not cut and not qa):
        return dict(empty, job_id=jid, text=guide, report_guide=bool(guide))
    limit = limit - (len(guide) + 2 if guide else 0)   # 안내 몫을 먼저 뺀다 — 아래 전문·질문답이 남은 몫을 나눈다
    why = ("기동 지시(`-p`)는 기동 줄 바이트 예산으로 **잘렸다**" if cut
           else "질문 답변 재개 지시는 원 작업을 **요지로만** 실었다")
    text = _clip(f"## 배분 지시 전문 — `{jid}` (prj3#Issue931)\n\n{why}. 아래가 원장 정본(배분 payload) 전문이다 — "
                 f"잘린 지시·조회 포인터가 아니라 **이것을 따른다**.\n\n{topic}", limit, f"{TOPIC_CMD} {jid}")
    if qa:
        try:
            ib = _inbox_mod()
        except Exception:  # noqa: BLE001 — 원문 조회 실패는 payload 사본으로
            ib = None
        blocks = []
        for e in qa:
            qid = e.get("qid") or ""
            q = e.get("q") or ""
            try:
                r = ib.qa(qid) if (ib is not None and qid) else None
                if r and r.get("ok") and r.get("question"):
                    q = r["question"]
            except Exception:  # noqa: BLE001
                pass
            st = "답" if (e.get("status") or "done") == "done" else "답하지 않기로 함"
            blocks.append(f"### `{qid or '?'}` — {st}\n\n- 질문: {q}\n- 답: {e.get('a') or ''}")
        qhead = ("\n\n## 질문·답 원문 — 이 배분에서 받은 답 (prj3#Issue931)\n\n재개 지시는 답 요지만 싣는다 — "
                 "아래가 원장 원문이다(마지막이 최근).")
        room = limit - len(text)
        dropped = 0
        while len(blocks) > 1 and len(qhead) + len("\n\n".join(blocks)) + 80 > room:
            blocks.pop(0)                                   # 오래된 것부터 — 최근 답이 이 재개의 이유다
            dropped += 1
        if dropped:
            qhead += f" 앞선 {dropped}건은 상한으로 생략 — `{QA_CMD} <질문 id>`"
        if room > 0:
            text += _clip(qhead + "\n\n" + "\n\n".join(blocks), room, f"{QA_CMD} {qa[-1].get('qid') or '?'}")
    if guide:
        text += "\n\n" + guide
    return {"text": text, "job_id": jid, "topic_cut": cut, "qa": len(qa), "report_guide": bool(guide)}


def cmd_checkin_brief(args) -> int:
    """출근 훅 전용 (prj3#Issue931·929) — 이 몸체 배분의 지시 전문·완료 보고 절을 평문으로(실을 것이 없으면 빈 출력).
    흐름·단서는 출근 훅과 같은 env(`FBOT_FLOW`·`FBOT_TASK`)에서 읽는다. 오류는 rc≠0 — 훅이 출력째 버린다(fail-open)."""
    bot = args.bot_id or os.environ.get("FBOT_ID") or ""
    if not bot:
        return 0
    con = connect()
    try:
        r = checkin_brief(con, bot, flow=os.environ.get("FBOT_FLOW") or None,
                          hint=os.environ.get("FBOT_TASK") or None)
    finally:
        con.close()
    if getattr(args, "json", False):
        emit(r)
    elif r["text"]:
        print(r["text"])
    return 0


_ORG_MOD = None
_INBOX_MOD = None


def _inbox_mod():
    """fbot-inbox.py — `requester_of`(의뢰 세션 판정 단일 지점, prj3#Issue749)를 재사용한다."""
    global _INBOX_MOD
    if _INBOX_MOD is None:
        import importlib.util as _il
        _sp = _il.spec_from_file_location(
            "fbot_inbox", os.path.join(os.path.dirname(os.path.abspath(__file__)), "fbot-inbox.py"))
        _im = _il.module_from_spec(_sp); _sp.loader.exec_module(_im)
        _INBOX_MOD = _im
    return _INBOX_MOD


def _org_mod():
    """fbot-org.py 를 한 번만 적재한다 — 팀장 판정(`pm_bot`)·조직 선언(`resolve`)·prj 경로(`prj_path`)의
    단일 원천. 테스트는 `_ORG_MOD` 에 스텁을 꽂는다. 적재 실패는 호출 측이 잡는다 — 여기서 None 을
    돌려주면 "조직 없음" 과 구분되지 않는다."""
    global _ORG_MOD
    if _ORG_MOD is None:
        import importlib.util as _il
        _sp = _il.spec_from_file_location(
            "fbot_org", os.path.join(os.path.dirname(os.path.abspath(__file__)), "fbot-org.py"))
        _om = _il.module_from_spec(_sp); _sp.loader.exec_module(_om)
        _ORG_MOD = _om
    return _ORG_MOD


def lead_prj_name(prj):
    """prj3#Issue731 — 팀장 호칭·채용 id 슬러그에 쓰는 **prj 이름 단일 지점**. 해소 순서:
      ① 조직 선언(`data/fbot/org/{prj}.yml`) title
      ② `projects/{prj}` 경로의 basename — 사람이 부르는 폴더명. 호출자가 `--bot-id fbot-lead-stt` 로
         넣던 바로 그 이름이다
      ③ `prj{N}`
    ②가 없으면 미선언 prj 는 전부 `prj44 팀장핀봇` 이 된다 — 번호는 이름이 아니다."""
    om = _org_mod()
    try:
        t = (om.resolve(prj) or {}).get("title")
    except Exception:
        t = None
    if not t:
        try:
            p = om.prj_path(prj)
        except Exception:
            p = None
        if p:
            t = os.path.basename(os.path.normpath(p))
    return t or f"prj{prj}"


def lead_hire_title(prj, name=None):
    """팀장 호칭 = `{prj명} 팀장핀봇` (Issue692 규칙의 단일 표현). `name` 을 주면 재해소하지 않는다."""
    return f"{name or lead_prj_name(prj)} 팀장핀봇"


def hire_title(role, prj, ident):
    """채용 호칭 단일 지점 (prj3#Issue731). **lead 는 `--bot-id` 유무·`--topic` 과 무관하게 팀장 호칭**이다.

    종전엔 `--bot-id` 명시 경로가 `resolve_lead_target` 을 건너뛰어(`not args.bot_id` 조건) 워커 템플릿
    `{ident} 담당 lead 워커` 로 떨어졌고, `ident` 가 `--topic` 원문이라 작업 문구 전문이 호칭이 됐다
    (2026-09-27 26 prj 웨이브 — 팀장 17명이 `TDD 첫 실행 — … 담당 lead 워커`). topic 은 job payload 에만
    남는다. prj 없는 lead(전역봇)와 워커는 종전 템플릿 그대로다.
    """
    if role == "lead" and prj is not None:
        return lead_hire_title(prj)
    return f"{ident} 담당 {role} 워커"


def resolve_lead_target(prj):
    """prj3#Issue692 — lead 배분 대상 해소. 반환 `(bot_id, hire_title)`.

    **팀장(lead)은 prj 당 하나**다. 종전엔 `--bot-id` 없이 lead 로 배분하면 이슈명으로 id 를 만들어
    (`fbot-lead-issue4`) 그 prj 에 팀장이 있어도 **새로 채용**했다 → prj60 에 팀장 2명, 이름은
    «Issue4 담당 lead 워커». 판정은 fbot-org.py `pm_bot`(팀장 판정 단일 지점, Issue689)에 묻는다.
      · 기존 팀장 있음 → `(그 bot_id, None)` — 호출 측이 wake 한다
      · 없음 → `("fbot-lead-{prj명}", "{prj명} 팀장핀봇")` — 채용
      · 해소기 부재·실패 → `(None, None)` — 종전 규칙(배분을 막지 않는다)
    prj3#Issue731 — prj명은 `lead_prj_name` 한 곳이 준다(채용 id 슬러그와 호칭이 한 원천).
    """
    try:
        pm = _org_mod().pm_bot(prj)
    except Exception:
        return None, None
    if pm:
        return pm, None
    t = lead_prj_name(prj)
    return "fbot-lead-" + (re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-") or str(prj)), lead_hire_title(prj, t)

# ── 인력 확보 사다리 ② — 차용·생성 (prj3#Issue757 T13) ─────────────────────────────
#   사용자 결정 ③(2026-09-28): *«팀에 핀봇이 없으면 총괄이 다른 팀에서 가져오거나 생성한다 — prj42 슬라이드 핀봇을
#   다른 프로젝트에서 쓰도록 총괄이 연결»*. 차용은 **기록**이다: 소속·자리·기록 귀속은 원 팀 그대로이고, 요청 팀장이
#   그 기록을 근거로 배분한다(plan 열린 질문 13 ⓐ). 기록 없는 타 팀 개체 배분은 `loan_reject` 가 막는다(⑭).
LOAN_KIND = "fbot_loan"
LOAN_DAYS_DEFAULT = 7
EMPLOYMENT_LABELS = {"employed": "재직", "suspended": "정직", "leave": "휴직", "terminated": "해고"}   # 표시용 — 정본 fbot-state EMPLOYMENT_LABEL


def _row(con, bot_id):
    return con.execute("SELECT bot_id, role, prj, parent_bot_id, career FROM bot WHERE bot_id=?", (bot_id,)).fetchone()


def _seat_of(con, bot_id):
    """개체 자리(`seat_id`) — 팀 소속 판정(`team_prj`) 재료. 열 부재(구 스키마)·행 부재는 None."""
    if "seat_id" not in {c[1] for c in con.execute("PRAGMA table_info(bot)")}:
        return None
    row = con.execute("SELECT seat_id FROM bot WHERE bot_id=?", (bot_id,)).fetchone()
    return row[0] if row else None


_LOAN_KEY_CHAR = re.compile(r"[A-Za-z0-9_-]")   # 키 접두 경계 — `_names_bot` 과 같은 ASCII 식별자 문자


def loan_key_match(key, ident, loan_key=None) -> bool:
    """차용 일 키 대조 — 판정 단일 지점 (Issue933). `loan_reject` 만 부른다.

    · 키 없는 차용 — 만료 전 그 팀장의 배분 전부(종전)
    · 배분이 차용 키를 따로 밝혔으면(`dispatch --loan-key` → payload `loan_key`) 그 값과 정확 일치만 — topic 은 보지 않는다
    · 밝히지 않았으면 키가 배분 식별자(topic·issue)의 **접두** — 정확 일치(종전 계약)는 그 특수형. 종전엔 정확 일치만 허가해
      범위 지시(«원본 무수정·리포트만»)를 topic 에 붙이면 거부됐고, 키 그대로 배분하면 그 지시가 워커 프롬프트에서 빠졌다
      (prj6 Issue823 실증②). 키 끝과 다음 글자가 둘 다 식별자 문자면 접두가 아니다 — `deck823` 키가 `deck8234` 에 걸리지 않게
    """
    key = (key or "").strip()
    if not key:
        return True
    lk = (loan_key or "").strip()
    if lk:
        return lk == key
    ident = (ident or "").strip()
    if ident == key:
        return True
    if not ident.startswith(key):
        return False
    return not (_LOAN_KEY_CHAR.match(key[-1]) and _LOAN_KEY_CHAR.match(ident[len(key)]))


def _loan_key_arg(key) -> str:
    """안내문용 `--loan-key <키>` — 공백·한글 키도 그대로 붙여 넣을 수 있게 셸 인용 (Issue933)."""
    import shlex as _shlex
    return "--loan-key " + _shlex.quote(str(key))


def loan_reject(con, dispatcher, bot_id, ident, now, loan_key=None):
    """다른 prj 의 비관리직 개체 배분 판정 — (거부 사유 | None, 차용 id | None).

    대상: 관리직 아님 · prj 소속 있음 · 배분자 prj 와 다름(재점검 지적 3 — 총괄 → 팀장·본사 봇 배분은 대상 밖).
    유효 차용 = `fbot_loan` open · 빌리는 팀장 = 배분자 · 같은 봇 · 만료 전 · 일 키 대조 통과(`loan_key_match` — Issue933).
    dispatch(실배분·dry-run)·spawn·seat_pick 이 모두 이 함수로 판정한다 — 판정이 갈리면 dry-run 이 실배분을 예측하지 못한다."""
    r = _row(con, bot_id)
    if not r or _is_nonexec(r["role"]) or r["prj"] is None:
        return None, None
    d = _row(con, dispatcher)
    dprj = None
    if d is not None:
        # 배분자의 팀 — «팀 소속» 판정은 fbot-org `team_prj` 한 곳(prj3#Issue945 추출). 본사 개체의 팀 = 본사 몸체 prj
        #   (`_hq.yml` — prj3#Issue734): 본사 팀장이 prj3 워커를 부르는 것은 타 팀 차용이 아니다. ⓪ cross 와 같은 규칙이다
        try:
            dprj = _org_mod().team_prj(d["prj"], _seat_of(con, dispatcher))
        except Exception:  # noqa: BLE001 — 해소기 부재는 prj 열(종전 개체 축)
            dprj = d["prj"]
    if d is not None and dprj == r["prj"]:
        return None, None
    keyed = []                                    # Issue933 — 그 봇의 유효 차용이 있는데 일 키만 안 맞는 것
    for j in con.execute("SELECT id, payload FROM job WHERE kind=? AND status='open' AND owner=? ORDER BY created_at DESC",
                         (LOAN_KIND, dispatcher)).fetchall():
        try:
            pl = json.loads(j["payload"] or "{}")
        except ValueError:
            continue
        if pl.get("bot") == bot_id and int(pl.get("expires_at") or 0) > now:
            if loan_key_match(pl.get("key"), ident, loan_key):
                return None, j["id"]
            keyed.append((j["id"], str(pl.get("key"))))
    if keyed:
        lid, key = keyed[0]
        how = (f"밝힌 차용 키 {loan_key.strip()!r} 와 다르다" if (loan_key or "").strip()
               else "배분 식별자(topic·issue)가 그 키로 시작하지 않는다")
        return (f"{bot_id} 차용({lid})은 일 키 {key!r} 에만 유효하다 — {how}(Issue933). "
                f"그 일이면 topic 을 키로 시작하거나 dispatch {_loan_key_arg(key)} 로 밝힌다 · 다른 일이면 총괄에 차용을 다시 요청한다"), None
    return (f"{bot_id} 는 prj{r['prj']} 팀 개체다 — 차용 기록 없이 다른 팀 개체를 부를 수 없다(prj3#Issue757 사다리 ②). "
            f"총괄에 인력 요청: python3 ~/.claude/hooks/fbot-inbox.py staffing --by {dispatcher} --role {r['role']} "
            f"--body \"<요지>\" — 총괄이 소유 팀장 동의를 받아 차용을 잇는다"), None


def release_loans(con, dispatch_ids):
    """배분 종결 → 그 배분이 쓴 차용을 해제한다(«작업 종결 시 자동 해제»). 호출자의 트랜잭션 안에서 부른다."""
    n = 0
    for did in dispatch_ids or []:
        row = con.execute("SELECT payload FROM job WHERE id=? AND kind=?", (did, JOB_KIND)).fetchone()
        try:
            lid = json.loads(row["payload"] or "{}").get("loan_id") if row else None
        except ValueError:
            lid = None
        if lid:
            n += con.execute("UPDATE job SET status='released', result=? WHERE id=? AND kind=? AND status='open'",
                             (json.dumps({"released_by": "dispatch-closed", "dispatch": did, "at": int(time.time())}),
                              lid, LOAN_KIND)).rowcount
    return n


def _ident_mod():
    """봇 신원 대조 판정 단일 지점(hooks/lib/fbot-ident.py, prj3#Issue832) — `FBOT_ID == --by` 를 복제하지 않는다."""
    import importlib.util as _il
    _sp = _il.spec_from_file_location(
        "fbot_ident", os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib", "fbot-ident.py"))
    _m = _il.module_from_spec(_sp); _sp.loader.exec_module(_m)
    return _m


def _require_chief(con, by, what):
    """상비 총괄 본인 확인 — 호출 세션(FBOT_ID) = --by · role=chief · parent 없음 · 해고 아님."""
    err = _ident_mod().impersonation_error(by, what)
    if err:
        raise Reject(2, err)
    r = _row(con, by)
    if not r or r["role"] != "chief" or r["parent_bot_id"] or r["career"] == "terminated":
        raise Reject(2, f"{what} 는 상비 총괄만 — {by} 는 자격 없음")
    return r


def _reply_staffing(req_id, verdict, body, by):
    if not req_id:
        return None
    out = _inbox_mod().reply(req_id, "done", body, by, spawn=False, verdict=verdict)
    if not out.get("ok"):
        print(f"[fbot-lead] 인력 요청 응답 실패({req_id}): {out.get('error')}", file=sys.stderr)
    return out


def _names_bot(pl, bot_id):
    """동의 요청이 그 봇에 관한 것인가 — `payload.bot` 일치 또는 본문에 봇 id 가 **단어로** 있음(`S4` 가 `S42` 에 걸리지 않게)."""
    if not isinstance(pl, dict) or not bot_id:
        return False
    if pl.get("bot") == bot_id:
        return True
    # 경계는 ASCII 만 — 한글 조사가 바로 붙는 «S42를» 도 언급이다(\w 는 한글을 포함한다)
    return re.search(r"(?<![A-Za-z0-9_-])" + re.escape(bot_id) + r"(?![A-Za-z0-9_-])", str(pl.get("body") or "")) is not None


def cmd_loan(args) -> int:
    """차용 기록 — 총괄이 다른 팀 개체를 요청 팀장에게 잇는다(C 결정). 배분은 요청 팀장이 한다."""
    now = int(time.time())
    con = connect()
    try:
        _require_chief(con, args.by, "차용 기록")
        b = _row(con, args.bot)
        if not b:
            raise Reject(1, f"대장에 없는 봇: {args.bot}")
        if _is_nonexec(b["role"]) or b["prj"] is None:
            raise Reject(1, f"{args.bot} 은 차용 대상이 아니다 — 관리직·본사 개체는 차용하지 않는다")
        # prj3#Issue822 — 재직(employed)만 잇는다. 휴직·정직을 이으면 dispatch 의 HR wake 가 휴직을 풀어 인사 판정을
        #   무력화한다. 판정은 fbot-org `loanable` 한 곳(find_role·ladder_step 과 같은 술어)
        _has_emp = "employment" in {r[1] for r in con.execute("PRAGMA table_info(bot)")}
        _emp = con.execute("SELECT %s, career FROM bot WHERE bot_id=?" % ("employment" if _has_emp else "NULL"),
                           (args.bot,)).fetchone()
        _om = _org_mod()
        if not _om.loanable(_emp[0], _emp[1]):
            _e = _om.effective_employment(_emp[0], _emp[1])
            raise Reject(1, f"{args.bot} 은 {EMPLOYMENT_LABELS.get(_e, _e)} 상태다 — 차용은 재직 개체만 잇는다"
                            f"(prj3#Issue822). 복귀는 인사 판정(fbot-state.py employment)이 먼저다 · 후보는 fbot-org.py find --role {b['role']}")
        t = _row(con, args.to)
        if not t or t["role"] != "lead":
            raise Reject(1, f"빌리는 쪽은 팀장이어야 한다: {args.to}")
        if t["prj"] == b["prj"]:
            raise Reject(1, "같은 팀 개체다 — 차용이 아니라 배분이다")
        owners = {b["parent_bot_id"]} | {r["bot_id"] for r in con.execute(
            "SELECT bot_id FROM bot WHERE role='lead' AND prj=? AND career != 'terminated'", (b["prj"],)).fetchall()}
        c = con.execute("SELECT owner, payload, result FROM job WHERE id=? AND kind='fbot_request'", (args.consent or "",)).fetchone()
        try:
            cres = json.loads(c["result"] or "{}") if c else {}
        except ValueError:
            cres = {}
        if not c or c["owner"] not in owners - {None}:
            raise Reject(2, f"소유 팀장 동의 요청이 아니다: {args.consent} — prj{b['prj']} 팀장({', '.join(sorted(o for o in owners if o))})에게 "
                            "인박스로 묻고 그 요청 id 를 넘긴다")
        if cres.get("status") not in ("accepted", "done"):
            raise Reject(2, f"소유 팀장 동의가 없다(응답 {cres.get('status')}) — 동의(accepted) 뒤에 잇는다")
        # prj3#Issue832 — «누가 무엇에 동의했나» 를 증명한다: 응답자가 소유 팀장이고, 그 요청이 이 봇에 관한 것이어야 한다.
        #   종전엔 소유 팀장 앞 요청이 accepted 이기만 하면 통과했다(응답자·대상 무검사 — 무관한 요청의 동의가 차용 근거가 됐다)
        if cres.get("by") not in owners - {None}:
            raise Reject(2, f"동의 응답자가 소유 팀장이 아니다(응답자 {cres.get('by')!r}) — prj{b['prj']} 팀장이 직접 답한 동의만 근거다")
        try:
            cpl = json.loads(c["payload"] or "{}")
        except ValueError:
            cpl = {}
        if not _names_bot(cpl, args.bot):
            raise Reject(2, f"동의 요청이 {args.bot} 에 관한 것이 아니다 — 본문 또는 payload.bot 에 대상 봇 id 를 적어 묻는다")
        lid = f"fbotloan-{now}-{uuid.uuid4().hex[:8]}"
        days = int(getattr(args, "days", None) or LOAN_DAYS_DEFAULT)
        pl = {"bot": args.bot, "role": b["role"], "from_prj": b["prj"], "to_lead": args.to, "to_prj": t["prj"],
              "key": (getattr(args, "key", "") or "").strip(), "expires_at": now + days * 86400,
              "decided_by": args.by, "consent": args.consent, "reason": (args.reason or "").strip(),
              "request": getattr(args, "request", None)}
        con.execute("BEGIN IMMEDIATE")
        con.execute("INSERT INTO job (id, store, kind, status, payload, result, attempts, owner, lease_until, blocked_since, created_at)"
                    " VALUES (?,?,?,?,?,NULL,0,?,NULL,NULL,?)",
                    (lid, "fbot", LOAN_KIND, "open", json.dumps(pl, ensure_ascii=False), args.to, now))
        _ev(con, args.by, "decision", f"[C] 차용 {args.bot}(prj{b['prj']}) → {args.to}: {pl['reason']}"[:300], lid)
        con.execute("COMMIT")
    finally:
        con.close()
    # Issue933 — 키 있는 차용은 배분 식별자가 그 키로 시작하거나 --loan-key 로 밝혀야 통과한다. 안내에 대조 방법을 싣는다
    kx = f" {_loan_key_arg(pl['key'])}" if pl["key"] else ""
    _reply_staffing(getattr(args, "request", None), "loan",
                    f"차용 연결 {args.bot}(prj{b['prj']}) — {lid} · 배분은 fbot-lead.py dispatch --by {args.to} --bot-id {args.bot} --role {b['role']}{kx}",
                    args.by)
    emit({"ok": True, "action": "loan", "loan_id": lid, **pl,
          "next": f"요청 팀장이 배분한다: fbot-lead.py dispatch --by {args.to} --bot-id {args.bot} --role {b['role']}{kx} …"})
    return 0


def _cross_verdict(prj, role, by):
    """dispatch 입구의 ⓪ cross 판정 (prj3#Issue945) — fbot-org `ladder_step(by=…)` 의 맨 앞 단(`cross_step`)만 부른다.

    `ladder_step` 전체(자리·직능 탐색 — 조직 선언 전수 해소)는 dispatch 입구에서 필요 없다 — ⓪ 은 같은 함수 `cross_step` 으로
    판정하고 나머지 단은 배치 판정(`_place_worker` → `hire_ladder_verdict`)이 종전대로 탄다. 해소기 부재·예외는 None
    (배분을 막지 않는다 — fail-soft)."""
    try:
        _c = connect()                            # 배분 원장과 같은 대장을 본다(배분자 행·그 prj 팀장 행)
        try:
            return _org_mod().cross_step(prj, role, by, con=_c)
        finally:
            _c.close()
    except Exception as e:  # noqa: BLE001
        print(f"[fbot-lead] ⓪ cross 판정 불가(배분은 진행): {str(e)[:160]}", file=sys.stderr)
        return None


def hire_ladder_verdict(prj, role, dispatcher, drole):
    """dispatch 채용 경로의 사다리 판정 단일 지점 (prj3#Issue821 — plan 열린 질문 4 판정, L).

    반환 `{reject: 사유|None, seat: 자리 주소|None, parent: parent_bot_id, step}`. 판정 한 줄은 사다리와 같다 —
    **자리 안이면 팀장, 자리 밖이면 총괄, 카탈로그 밖이면 발굴**. 종전 HR hire 는 카탈로그·깊이·상주만 봐서
    자리 밖 직능도 채용됐고(사다리 ② 건너뜀), 채용 개체가 `seat_id` NULL 이라 공석 표시가 남았다.
      · 관리직 직능 — 판정 대상 밖(팀장 해소·자리 결속은 `resolve_lead_target`·HR 게이트 `_bind_lead_seat` 몫)
      · 카탈로그 밖·아카이브 — 거부 + 발굴 경로(ⓐ — `fbot-icon` 안내가 아니라 `dispatch --role scout`)
      · 전역(prj 없음)·조직 선언 없는 prj — 종전 허용(선언이 없으면 자리 판정 불가 — 선언 도입 전 prj 보호)
      · 자리 안 — 허용 + 그 자리 `seat_id`(ⓒ). 공석을 먼저, 다 차 있으면 첫 자리(겸원 — 워커는 일마다 1:1 개체다)
      · 자리 밖이지만 본사 자리 직능(발굴 등 `_hq.yml`) — 전역 단일 직능이라 prj 자리 판정 대상 밖
      · 자리 밖 — 거부 + 총괄 인력 요청(`fbot-inbox.py staffing`). 총괄의 차용·생성이 끝나면 자리·차용 기록이 생겨 통과
    parent = **배분한 팀장**(ⓑ — `staff-create` 와 같은 규칙). 배분자가 팀장이 아니면 종전 전역 배분자.
      · ⓪ 남의 prj 일(prj3#Issue945) — 거부 + 그 prj 팀장 인박스. 종전엔 팀 대조가 없어 한가한 대상 prj 개체가 없으면
        **남의 prj 자리에 배분자 팀장을 parent 로 채용**했다(prj3 자리 · parent=prj42 팀장 — 격리 실측). 판정은
        `ladder_step(by=…)` → `cross_step` 한 곳 — dispatch 입구·staffing 과 같다. dispatch 입구가 먼저 거르므로 여기는
        원장에 이미 있는 배분의 `spawn` 과 직접 호출의 최종 방어다
    해소기 부재·예외는 종전 동작 — 배분을 막지 않는다(`resolve_lead_target` 과 같은 fail-soft)."""
    out = {"reject": None, "seat": None, "parent": TASKMGR_ID, "step": None}
    try:
        om = _org_mod()
        if om.is_manager(role):
            return dict(out, step="manager")
        out["parent"] = dispatcher if drole == "lead" else TASKMGR_ID
        st = om.ladder_step(prj, role, by=dispatcher)
    except Exception as e:  # noqa: BLE001 — 해소 실패는 판정 불가일 뿐 거부 근거가 아니다
        return dict(out, step="unresolved", note=str(e)[:120])
    out["step"] = st.get("step")
    if st.get("step") == "cross":
        return dict(out, reject=st.get("reason"), lead=st.get("to"))
    if st.get("step") == "scout":
        return dict(out, reject=(
            f"미등재(또는 아카이브) 직능 {role} — 카탈로그 밖이다(인력 확보 사다리 ③ · prj3#Issue821). 채용이 아니라 발굴이 먼저다: "
            f"python3 ~/.claude/hooks/fbot-lead.py dispatch --by {dispatcher} --role scout --cwd <prj 경로> "
            f"--topic \"{role} 직능 신설\" — 발굴핀봇이 직능을 등재하고 요청 prj 자리에 먼저 세운다"))
    if prj is None or st.get("declared") is False:
        return out
    if st.get("step") == "team":
        seats = st.get("seats") or []
        con = connect()
        try:
            cols = {r[1] for r in con.execute("PRAGMA table_info(bot)")}
            taken = {r[0] for r in con.execute(
                "SELECT seat_id FROM bot WHERE seat_id IS NOT NULL AND career != 'terminated'"
                + (" AND COALESCE(employment,'') != 'terminated'" if "employment" in cols else ""))} \
                if "seat_id" in cols else set()
        finally:
            con.close()
        free = [a for a in seats if a not in taken]
        return dict(out, seat=(free or seats or [None])[0])
    try:
        hq = {s.get("role") for s in (om.resolve(None).get("seats") or [])}
    except Exception:  # noqa: BLE001
        hq = set()
    if role in hq:
        return dict(out, step="hq")
    cands = [c.get("bot_id") for c in st.get("candidates") or []]
    return dict(out, reject=(
        f"{role} 은 prj{prj} 조직 선언의 자리 밖이다(인력 확보 사다리 ② · prj3#Issue821). 팀장은 자리 밖 직능을 채용하지 않는다 — "
        f"총괄에 인력 요청: python3 ~/.claude/hooks/fbot-inbox.py staffing --by {dispatcher} --role {role} --body \"<요지>\" "
        f"— 총괄이 차용(loan) 또는 생성(staff-create — 자리 추가)을 마치면 그 개체·자리로 다시 배분한다"
        + (f" · 다른 팀 재직 후보: {', '.join(cands[:5])}" if cands else "")))


SEAT_PICK_STATES = ("checkout", "waiting_input")      # cold·수신대기 — working·checkin·waiting_child 는 몸체가 일하는 중
DISPATCH_OPEN_STATUSES = ("open", "blocked", "deferred")   # 미종결 배분 — 이 개체의 몸체 몫이 아직 남았다
SEAT_MIN_PROMPT = 120   # prj3#Issue903 — 자리 재사용 후보가 최소한 이만큼의 프롬프트는 실을 수 있어야 한다(기동 줄 한도 판정용)


def _loaned_bots(con, dispatcher, now) -> set:
    """배분자 앞 open·만료 전 차용 기록의 봇 — seat_pick 이 «차용 개체가 후보에서 빠진 사유» 를 알릴 대상 (Issue933).
    유효성(일 키) 판정이 아니다 — 판정은 `loan_reject` 한 곳. 알림 재료일 뿐이라 조회 실패는 빈 집합(선택을 막지 않는다)."""
    out = set()
    try:
        rows = con.execute("SELECT payload FROM job WHERE kind=? AND status='open' AND owner=?",
                           (LOAN_KIND, dispatcher)).fetchall()
    except sqlite3.Error:
        return out
    for j in rows:
        try:
            pl = json.loads(j[0] or "{}")
            if pl.get("bot") and int(pl.get("expires_at") or 0) > now:
                out.add(pl["bot"])
        except (ValueError, TypeError, AttributeError):
            continue
    return out


def _seat_skip_note(bot_id, why):
    """차용 개체가 seat_pick 후보에서 빠질 때 사유 1줄 (Issue933) — 종전엔 조용히 빼고 새 워커 채용으로 빠졌다."""
    line = " ".join(str(why).split())
    print(f"[fbot-lead] seat_pick: 차용 개체 {bot_id} 후보 제외 — {line[:300]}", file=sys.stderr)


def seat_pick(con, prj, role, dispatcher, ident, now, loan_key=None):
    """`--bot-id` 생략 배분의 자리 개체 선택 — 판정 단일 지점 (prj3#Issue838 · 총괄 C 결정 2026-09-29).

    반환 `{bot_id, via: seat|loan, loan_id}` 또는 None(종전 채용). 종전엔 이슈명으로 새 id 를 만들어 **항상 채용**했다 →
    총괄이 `staff-create`·`loan` 으로 만든(잇는) 개체가 배분 0(운영 관측: prj55·58 생성 개체 뒤 새 워커 3명 채용).
      · 후보 — 같은 직능 · 재직(`loanable` — 휴직·정직·해고 제외) · (그 prj 소속 + 그 prj 자리 `seat_id`) 또는
        배분자 앞 유효 차용(판정은 `loan_reject` 한 곳 — 일 키 `loan_key` 도 그대로 넘긴다, Issue933)
      · 한가함 — state `checkout`(cold)·`waiting_input` + 미종결 배분 없음(워커 1:1 — 배분 1 = 몸체 1)
      · 순서 — cold 먼저(wake 가 확실히 허가) · 자기 팀 자리 먼저 · 오래된 개체 먼저
      · Issue933 — 배분자 앞 차용 기록이 있는 타 팀 개체가 후보에서 빠지면 stderr 에 사유 1줄(`_seat_skip_note`)
    관리직(팀장 해소는 `resolve_lead_target`)·prj 미해소는 대상 밖. 해소기 예외는 None(배분을 막지 않는다)."""
    if prj is None:
        return None
    try:
        om = _org_mod()
        if om.is_manager(role):
            return None
        cols = {r[1] for r in con.execute("PRAGMA table_info(bot)")}
        if "seat_id" not in cols:
            return None
        emp = "employment" if "employment" in cols else "NULL"
        rows = con.execute(f"SELECT bot_id, prj, seat_id, state, career, {emp} AS employment FROM bot"
                           " WHERE role=? AND career != 'terminated' ORDER BY created_at, bot_id", (role,)).fetchall()
        busy = {r[0] for r in con.execute(
            "SELECT json_extract(payload,'$.worker_bot_id') FROM job WHERE kind=? AND status IN ({})".format(
                ",".join("?" * len(DISPATCH_OPEN_STATUSES))), (JOB_KIND, *DISPATCH_OPEN_STATUSES))}
        lent = _loaned_bots(con, dispatcher, now)
        picks = []
        for r in rows:
            loaned = r["bot_id"] in lent and r["prj"] is not None and r["prj"] != prj
            if r["state"] not in SEAT_PICK_STATES or r["bot_id"] in busy or not om.loanable(r["employment"], r["career"]):
                if loaned:
                    _seat_skip_note(r["bot_id"], f"state {r['state']}" if r["state"] not in SEAT_PICK_STATES
                                    else "미종결 배분 보유(워커 1:1)" if r["bot_id"] in busy else "재직 아님(휴직·정직)")
                continue
            # prj3#Issue903 — 기동 줄 길이 가드(Issue824)와 같은 판정(spawn_line_bytes)으로 긴 id 개체를 후보에서 뺀다.
            #   종전엔 id 가 길어 줄이 1,000B 를 넘는 개체를 골라 spawn 이 거부되고 배분만 open 으로 남았다(1026B 실측)
            if spawn_line_bytes(r["bot_id"], "x" * SEAT_MIN_PROMPT, transform=True, model="sonnet") > LINE_BUDGET:
                if loaned:
                    _seat_skip_note(r["bot_id"], f"기동 줄 {LINE_BUDGET}B 초과(id 길이 — prj3#Issue903)")
                continue
            if r["prj"] == prj and str(r["seat_id"] or "").startswith(f"{prj}/"):
                picks.append((r["state"] != "checkout", 0, {"bot_id": r["bot_id"], "via": "seat", "loan_id": None}))
                continue
            if r["prj"] is not None and r["prj"] != prj:
                why, lid = loan_reject(con, dispatcher, r["bot_id"], ident, now, loan_key)
                if why is None and lid:
                    picks.append((r["state"] != "checkout", 1, {"bot_id": r["bot_id"], "via": "loan", "loan_id": lid}))
                elif loaned and why:
                    _seat_skip_note(r["bot_id"], why)
    except Exception:  # noqa: BLE001 — 선택 실패는 종전 채용일 뿐 거부 근거가 아니다
        return None
    return min(picks, key=lambda p: p[:2])[2] if picks else None


def _hr_gate_run(argv):
    """HR 게이트 호출 seam (prj3#Issue904) — 배치 판정 `_place_worker` 의 wake·hire. 테스트가 바꿔 끼운다."""
    return subprocess.run([sys.executable, HR_GATE_PY] + list(argv), capture_output=True, text=True)


def _hire(bot_id, role, title, parent, prj, state=None):
    """HR 게이트 채용 — 테스트는 이 함수를 바꿔 끼운다(게이트 없는 스폰 금지 원칙은 게이트 쪽이 지킨다).
    `state`: 초기 state — 배분 동반 채용은 None(게이트 기본 checkin, 곧 세션이 뜬다) · 몸체 없는 생성은 "checkout" (Issue796)."""
    cmd = [sys.executable, HR_GATE_PY, "hire", "--bot-id", bot_id, "--role", role, "--title", title, "--parent", parent]
    if prj is not None:
        cmd += ["--prj", str(prj)]
    if state:
        cmd += ["--state", state]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise FbotError(f"HR 게이트 채용 거부·실패(exit {r.returncode}): {(r.stderr or r.stdout).strip()}")
    return {"ok": True}


def cmd_staff_create(args) -> int:
    """생성 — 카탈로그 직능인데 쓸 개체가 없으면 요청 팀 자리를 더하고 HR 게이트로 채용한다(parent = 요청 팀장).
    총괄은 **배분하지 않는다** — 채용까지이고, 일은 요청 팀장이 배분한다."""
    con = connect()
    try:
        _require_chief(con, args.by, "생성")
        t = _row(con, args.to)
        if not t or t["role"] != "lead" or t["prj"] != args.prj:
            raise Reject(1, f"요청 팀장이 prj{args.prj} 팀장이 아니다: {args.to}")
        base = f"fbot-{args.role}-prj{args.prj}"
        bot_id, k = base, 1
        while _row(con, bot_id):
            k += 1
            bot_id = f"{base}-{k}"
    finally:
        con.close()
    seat = _org_mod().add_seat(args.prj, args.role, dept=getattr(args, "dept", None) or "dev", apply=True,
                               note=f"총괄 생성 — {args.to} 인력 요청")
    if not seat.get("ok"):
        raise Reject(1, f"자리 추가 실패: {seat.get('error')}")
    # prj3#Issue796 결정(L) ② — 생성은 세션 없는 채용이라 cold(checkout) 로 적는다. checkin 으로 적으면 팀장의 첫
    #   dispatch 를 HR wake 가 «이미 활동 중(점유 free)» 으로 거절해 lease 만료까지 배분이 막힌다(2026-09-29 prj55 실측)
    _hire(bot_id, args.role, hire_title(args.role, args.prj, f"prj{args.prj}"), args.to, args.prj, state="checkout")
    # prj3#Issue821 ⓒ — 생성 개체는 방금 더한 자리에 앉힌다(운영 관측 2026-09-29: prj55·58 생성 개체 seat_id NULL).
    #   자리 판정·기록은 fbot-org `bind` 소유 · 실패해도 채용은 유효(fail-soft) — 결과에 남긴다
    try:
        seat["bind"] = _org_mod().bind(bot_id, seat.get("seat_id") or "", prj=args.prj, apply=True)
    except Exception as e:  # noqa: BLE001
        seat["bind"] = {"ok": False, "error": f"자리 결속 실패: {e}"}
    _reply_staffing(getattr(args, "request", None), "created",
                    f"생성 {bot_id}(prj{args.prj} {seat.get('seat_id')}) — 배분은 fbot-lead.py dispatch --by {args.to} --bot-id {bot_id} --role {args.role}",
                    args.by)
    emit({"ok": True, "action": "staff-create", "bot_id": bot_id, "seat": seat, "parent": args.to,
          "next": f"요청 팀장이 배분한다: fbot-lead.py dispatch --by {args.to} --bot-id {bot_id} --role {args.role} …"})
    return 0


def _expect_paths(args, cwd) -> list:
    """`dispatch --expect PATH` → 절대경로 목록 (prj3#Issue929). 상대경로는 배분 cwd 기준 — 판정 시점 cwd 와 갈리지 않게."""
    base = os.path.expanduser(cwd or "")
    out = []
    for p in getattr(args, "expect", None) or []:
        p = os.path.expanduser((p or "").strip())
        if not p:
            continue
        p = os.path.normpath(p if os.path.isabs(p) or not base else os.path.join(base, p))
        if p not in out:
            out.append(p)
    return out


def _record_deferred_dispatch(args, ident, ident_kind, body_model, mmeta, mo, cwd, workflow, prj,
                              dispatcher, lead_target) -> int:
    """`dispatch --deferred-until <job_id>` — 미룬 배분을 `deferred` 로 원장에 적는다 (prj3#Issue861).

    가드·배분자·계층 판정은 호출 전에 끝났다. 여기서는 **채용·기상·기동을 하지 않는다** — 같은 봇 몸체 동시 기동의 흐름 잠금
    충돌(Issue843 계열)을 피해 미룬 것이다. 승격(`promote_deferred`)은 `spawn_pending` 표지를 남기고, 몸체는 tick 의
    `spawn --pending` 이 dispatch 와 같은 배치 판정(`_place_worker`)으로 세운다(prj3#Issue904 — 종전 «매니저의 다음 기상» 은
    집행 경로가 없어 «워커 봇 레코드 부재» 로 정체했다).
    월 배분 원장은 올리지 않는다 — 실제 배분(기동)이 아니다. WIP 도 점유하지 않는다(`deferred` 는 호출측 `open` 필터 밖).
    """
    pre = args.deferred_until
    con = connect()
    try:
        prow = con.execute("SELECT status FROM job WHERE id = ? AND kind = ?", (pre, JOB_KIND)).fetchone()
    finally:
        con.close()
    if prow is None:
        raise Reject(2, f"--deferred-until 선행 배분이 원장에 없다: {pre}")
    if prow["status"] in ("cancelled", "reaped"):
        raise Reject(2, f"--deferred-until 선행 배분이 이미 {prow['status']} — 기다릴 이유가 없다: {pre}")
    bot_id = args.bot_id or lead_target[0]
    if not bot_id:
        _c = connect()
        try:
            bot_id = default_worker_id(_c, prj, args.role, ident)
        finally:
            _c.close()
    now = int(time.time())
    job_id = f"fbotdisp-{now}-{uuid.uuid4().hex[:8]}"
    payload = {"issue": ident, "ident_kind": ident_kind, "role": args.role, "model": body_model,
               "worker_bot_id": bot_id, "cwd": cwd, "workflow": workflow, "prj": prj,
               "deferred_reason": f"순차 배분 — 선행 {pre} 완료 후", "deferred_until_job": pre,
               "deferred_by": dispatcher, "deferred_at": now,
               "bot_explicit": bool(args.bot_id)}    # prj3#Issue904 — spawn 이 dispatch 와 같은 자리 개체 선택(seat_pick) 여부를 재현한다
    _lk = (getattr(args, "loan_key", None) or "").strip()
    if _lk:                                          # Issue933 — 승격 뒤 spawn 이 같은 차용 키로 판정한다
        payload["loan_key"] = _lk
    if mo:
        payload["model_override"] = mo
    payload["model_source"] = mmeta.get("source")
    payload["model_reason"] = mmeta.get("reason")
    if getattr(args, "request", None):
        payload["request_id"] = args.request
    if _expect_paths(args, cwd):                  # prj3#Issue929 — 승격 뒤 sweep 이 산출 증적으로 대조한다
        payload["expect"] = _expect_paths(args, cwd)
    _sm = _state_mod()
    if _sm is not None:
        payload.update(_sm.body_stamp())
    con = connect()
    try:
        try:
            _req = ({"session": args.requester_session, "via": "explicit", "ref": None, "ambiguous": False}
                    if getattr(args, "requester_session", None)
                    else _inbox_mod().requester_of(con, dispatcher, env=os.environ))
        except Exception as _e:
            print(f"[fbot-lead] requester 판정 실패(미룸은 진행): {_e}", file=sys.stderr)
            _req = None
        if _req:
            payload.update({"requester_session": _req["session"], "requester_via": _req["via"]})
            if _req.get("ref"):
                payload["requester_ref"] = _req["ref"]
        if _sm is not None:
            payload.update(_sm.lineage_fields(
                _sm.dispatch_lineage(con, dispatcher, getattr(args, "parent_dispatch", None),
                                     os.environ.get("FBOT_FLOW") or None), job_id))
        con.execute("BEGIN IMMEDIATE")
        con.execute(
            "INSERT INTO job (id, store, kind, status, payload, result, attempts,"
            " owner, lease_until, blocked_since, created_at)"
            " VALUES (?,?,?,?,?,NULL,0,?,NULL,NULL,?)",
            (job_id, "fbot", JOB_KIND, "deferred", json.dumps(payload, ensure_ascii=False), dispatcher, now))
        _ev(con, dispatcher, "defer", f"{ident[:60]} ← 선행 {pre}", job_id)
        con.execute("COMMIT")
    finally:
        con.close()
    emit({"ok": True, "action": "dispatch", "verdict": "허가", "placement": "deferred",
          "issue": ident, "role": args.role, "worker_bot_id": bot_id, "dispatched_by": dispatcher,
          "job_id": job_id, "deferred_until_job": pre,
          "next": "채용·기동 없음 — 선행 배분 done 을 sweep 이 보면 open 으로 당기고 tick 이 `spawn --pending` 으로 몸체를 세운다"})
    return 0


def _place_worker(prj, role, ident, dispatcher, drole, bot_id=None, explicit=False, lead_bot=None, job_id=None,
                  loan_key=None, dry_run=False) -> dict:
    """배분 몸체 배치 판정 단일 지점 — 기존 개체 wake(·몸체 추가) 또는 HR 게이트 채용 (prj3#Issue904 추출).

    `dispatch` 와 `spawn`(원장에 이미 있는 open 배분)이 같은 함수를 탄다. 종전엔 이 판정이 cmd_dispatch 안에만 있어
    승격된 미룬 배분의 몸체를 세울 길이 없었다(«워커 봇 레코드 부재» 정체 — 2026-10-03 882·887·864).
    `explicit` = 호출자가 bot_id 를 지정했나(자리 개체 선택 생략) · `lead_bot` = 팀장 해소 결과 · `job_id` = 이미 기록된
    배분 id(spawn) — None 이면 새로 발급한다. 반환 `{bot_id, placement, job_id, loan_id, loan_from, seat, picked}`.
    거부·실패는 Reject·FbotError 로 올린다(메시지는 종전 dispatch 그대로).
    Issue933 — `loan_key` = 배분이 밝힌 차용 일 키(`dispatch --loan-key` · payload `loan_key`) — 차용 판정(`loan_reject`)·
    자리 개체 선택에 그대로 넘긴다. `dry_run` = **HR 게이트 호출 직전까지** 같은 판정(자리 개체 선택·직능 대조·차용·채용 사다리)을
    하고 예측 배치(`wake`·`hire`)를 돌려준다 — 종전 dry-run 은 이 함수를 건너뛰고 «허가» 를 돌려줘 실배분과 판정이 갈렸다.
    게이트의 wake 거절·몸체 추가 여부는 dry-run 이 예측하지 않는다(게이트 무접촉).
    """
    # slug 는 구분자를 **삭제하지 않고 치환**한다 (prj3#Issue515 ⓒ) — 삭제하면
    #   `Issue436_3` → `fbot-research-issue4363` 이 되어 `Issue43_63` 과 같은 bot_id 로
    #   충돌한다. 치환하면 `issue436-3` / `issue43-63` 으로 갈라진다.
    #   ⚠️ 기존에 발급된 id 는 소급 변경하지 않는다(대장·원장 참조가 깨진다).
    #   `--topic` 도 같은 치환 규칙을 탄다 — 자유 문자열이라 공백·한글이 섞이지만
    #   `[^a-z0-9]+` 치환이 전부 `-` 로 접어 주고, 남는 게 없으면 uuid 로 떨어진다.
    #   길이 상한(머리 48자 + 해시)은 prj3#Issue786_2 — 규칙은 worker_slug 한 곳.
    if not bot_id:
        _c = connect()
        try:
            bot_id = default_worker_id(_c, prj, role, ident)   # prj3#Issue890 — 타 팀 개체와의 이름 일치는 prj 축으로 비킨다
        finally:
            _c.close()
    # prj3#Issue692 — lead 는 prj 당 하나: 기존 팀장이면 wake, 없으면 prj명으로 채용(resolve_lead_target)
    if lead_bot:
        bot_id = lead_bot
    # prj3#Issue838 — `--bot-id` 생략이면 한가한 자리 개체(생성·차용분)를 먼저 깨운다. 판정은 seat_pick 한 곳
    hire_bot_id, picked = bot_id, None
    if not explicit and not lead_bot:
        _c = connect()
        try:   # 같은 일의 기존 워커(이슈명 id)가 이미 있으면 종전대로 그 개체를 깨운다 — 자리 선택은 새 채용 대신일 때만
            if not _c.execute("SELECT 1 FROM bot WHERE bot_id=?", (bot_id,)).fetchone():
                picked = seat_pick(_c, prj, role, dispatcher, ident, int(time.time()), loan_key=loan_key)
        finally:
            _c.close()
        if picked:
            bot_id = picked["bot_id"]
    # prj3#Issue554 — **이미 등록된 개체**(prj PM·상비봇)에 배분하면 채용이 아니라 **재기동(wake)** 이다.
    #   종전엔 무조건 hire 라 "중복 bot_id" 로 거부됐다(2026-09-06 실측: 중역 → PM 배분이 이 자리에서
    #   막혀 체인이 원장에 남을 수 없었다). `checkout` 은 cold 다(계약 §상태 기계 ⓓ) — 배분 도착이 곧
    #   wake 트리거이고, 집행체는 hire 의 형제 `wake`(상주 상한만 판정·예산 무차감)다.
    _c = connect()
    try:
        existing = _c.execute("SELECT role, career FROM bot WHERE bot_id=?", (bot_id,)).fetchone()
    finally:
        _c.close()
    loan_id = lfrom = hire_seat = placement = None
    if existing:
        if existing["role"] != role:
            raise Reject(1, f"배분 대상 {bot_id} 의 role 은 {existing['role']} — --role {role} 과 다르다")
        # prj3#Issue757 T13 ⑭ — 다른 팀 개체는 차용 기록이 있어야 부른다(총괄 → 팀장·본사 봇은 대상 밖)
        _c = connect()
        try:
            _why, loan_id = loan_reject(_c, dispatcher, bot_id, ident, int(time.time()), loan_key)
            lfrom = (_row(_c, bot_id) or {"prj": None})["prj"] if loan_id else None
        finally:
            _c.close()
        if _why:
            raise PlacementReject(_why)           # prj3#Issue945 — 배치 판정 라벨(수요측 ① 아님)
        if dry_run:                               # Issue933 — 게이트 wake 직전까지가 dry-run 의 판정이다
            return {"bot_id": bot_id, "placement": "wake", "job_id": None, "loan_id": loan_id,
                    "loan_from": lfrom, "seat": None, "picked": picked}
        # prj3#Issue757 J — 관리직 대상이면 **이 배분 id 가 흐름**이다. 살아 있는 관리직도 새 흐름이면 게이트가
        #   «몸체 추가» 를 판정한다(상한·흐름 잠금). 종전엔 흐름을 넘기지 않아 바쁜 팀장·총괄에 대한 배분이
        #   «이미 활동 중» 으로 중단됐다(2026-09-29 codex-arch-checker high). id 는 배분 기록과 같은 값을 쓴다
        jid = job_id or f"fbotdisp-{int(time.time())}-{uuid.uuid4().hex[:8]}"
        gflow = ["--flow", jid] if (_is_nonexec(role) and _multibody_on()) else []
        gate = _hr_gate_run(["wake", "--bot", bot_id] + gflow)
        if gate.returncode != 0 and picked:
            # prj3#Issue838 — 자동 선택 개체를 게이트가 거절하면(수신대기 몸체가 아직 살아 있음 등) 종전 채용으로 물러선다
            picked = dict(picked, fallback=f"wake 거절(exit {gate.returncode}): {(gate.stderr or gate.stdout).strip()[:200]}")
            bot_id, existing, loan_id = hire_bot_id, None, None
        elif gate.returncode != 0:
            raise FbotError(
                f"HR 게이트 재기동 거부·실패(exit {gate.returncode}) — 배분 중단: "
                f"{(gate.stderr or gate.stdout).strip()}"
            )
        else:
            try:
                _g = json.loads(gate.stdout or "{}")
            except ValueError:
                _g = {}
            placement = "body_add" if _g.get("body_add") else "wake"
            job_id = jid
    if not existing:
        # prj3#Issue821 — 채용 경로의 사다리 판정(자리 밖 거부·발굴 안내·parent·seat_id)은 hire_ladder_verdict 한 곳
        ladder = hire_ladder_verdict(prj, role, dispatcher, drole)
        if ladder["reject"]:
            raise PlacementReject(ladder["reject"])
        if dry_run:                               # Issue933 — 게이트 hire 직전까지가 dry-run 의 판정이다(자리 결속 없음)
            return {"bot_id": bot_id, "placement": "hire", "job_id": None, "loan_id": None,
                    "loan_from": None, "seat": ladder["seat"], "picked": picked}
        hire_argv = ["hire", "--bot-id", bot_id, "--role", role,
                     # prj3#Issue731 — 호칭은 hire_title 한 곳. lead 는 --bot-id 명시라도 팀장 호칭이다
                     "--title", hire_title(role, prj, ident),
                     # 체인 기록 필수 — parent 는 깊이 판정(④)의 데이터 원천 (계약 F1 parent_bot_id)
                     #   prj3#Issue821 ⓑ — parent = 배분한 팀장(staff-create 와 같은 규칙). 팀장 아닌 배분자는 종전 전역
                     "--parent", ladder["parent"]]
        if prj is not None:
            # 미해소는 --prj 를 아예 넘기지 않는다 — 게이트가 "전역봇(NULL)" 로 해석한다
            hire_argv += ["--prj", str(prj)]
        hire = _hr_gate_run(hire_argv)
        if hire.returncode != 0:
            raise FbotError(
                f"HR 게이트 채용 거부·실패(exit {hire.returncode}) — 배분 중단: "
                f"{(hire.stderr or hire.stdout).strip()}"
            )
        placement = "hire"
        if ladder["seat"]:                        # prj3#Issue821 ⓒ — 자리 안 채용은 그 자리에 앉힌다(bind 소유 · fail-soft)
            try:
                hire_seat = _org_mod().bind(bot_id, ladder["seat"], prj=prj, apply=True)
            except Exception as e:  # noqa: BLE001
                hire_seat = {"ok": False, "error": f"자리 결속 실패: {e}"}
        # wake·body_add 는 게이트에 흐름으로 넘긴 id 를 그대로 쓴다 — 채용(물러섬 포함)은 새로 발급(spawn 은 기록된 id)
        job_id = job_id or f"fbotdisp-{int(time.time())}-{uuid.uuid4().hex[:8]}"
    return {"bot_id": bot_id, "placement": placement, "job_id": job_id, "loan_id": loan_id,
            "loan_from": lfrom, "seat": hire_seat, "picked": picked}


def spawn_dispatch(job_id, by=None, unattended=False) -> dict:
    """원장에 이미 있는 open 배분의 몸체를 세운다 — 배치(`_place_worker`) → next_step → 기동 → spawned_at (prj3#Issue904).

    왜 필요한가 (2026-10-03 실측): `promote_deferred` 가 open 으로 당긴 배분 3건(882 `881eeeb3`·887 `d2a4314b`·864 `05f0369c`)이
      채용·기동 없이 «워커 봇 레코드 부재» 로 정체했다. 몸체를 세우는 판정이 `cmd_dispatch` 안에만 있어 팀장이 cancel·재배분으로
      우회했고, 그때마다 배분자 시간당 백스톱을 썼다.
    ⚠️ 새 배분이 아니다 — 수요측 가드(`judge_demand_guard`)·월 원장은 건드리지 않는다. 전역 동시 상한만 본다(`resume` 과 같은 셈, 자기 제외).
    ⚠️ 살아 있는 몸체 판정은 HR 게이트(wake) 한 곳 — 여기서 다시 하지 않는다.
    ⚠️ 배치는 됐는데 기동만 실패한 행(`spawn_placed_at`·`spawned_at` 없음)은 재시도 때 배치를 건너뛴다 — 방금 채용한 개체는
      checkin 이라 wake 가 «이미 활동 중» 으로 거절한다.
    `unattended`(tick `--pending`) — Agent 형태(prj 미해소)는 무인으로 띄울 수 없어 배치 전에 `drop` 으로 돌려준다.
    반환 `{ok, job_id, worker_bot_id, placement, next_step, spawned}` · 실패는 `ok: False` + `error`(+ `wait`·`drop`).
    입력 오류(배분 없음·open 아님)는 Reject.
    """
    by = by or BOT_ID
    con = connect()
    try:
        row = con.execute("SELECT * FROM job WHERE id = ? AND kind = ?", (job_id, JOB_KIND)).fetchone()
        if row is None:
            raise Reject(1, f"배분 없음: {job_id}")
        if row["status"] != "open":
            raise Reject(1, f"open 배분이 아니다({row['status']}): {job_id} — 미룬 배분은 승격(sweep)·resume 뒤에 기동한다")
        pl = json.loads(row["payload"] or "{}")
        dispatcher = row["owner"]
        drow = con.execute("SELECT role FROM bot WHERE bot_id=?", (dispatcher,)).fetchone()
        drole = (drow["role"] or "") if drow else ""
        known = {r[0] for r in con.execute("SELECT bot_id FROM bot")}
        live = [j for j in active_dispatches(con) if j["status"] == "open" and j["id"] != job_id
                and (j.get("payload") or {}).get("worker_bot_id") in known]
    finally:
        con.close()
    role, ident, prj = pl.get("role"), pl.get("issue") or "", pl.get("prj")
    base = {"job_id": job_id, "issue": ident, "role": role, "worker_bot_id": pl.get("worker_bot_id")}
    if unattended and prj is None:
        return dict(base, ok=False, drop=True, error="prj 미해소 — Agent 형태라 무인 기동 불가(`spawn --job-id` 로 next_step.agent 회수)")
    c_limit = load_policy()["fbot_dispatch_concurrent_limit"]
    if len(live) + 1 > c_limit:
        return dict(base, ok=False, wait=True, error=f"동시 배분 상한 — 활성 {len(live)}건 + 이 배분 > 상한 {c_limit}건")
    wid = pl.get("worker_bot_id")
    if pl.get("spawn_placed_at") and not pl.get("spawned_at") and wid in known:
        pw = {"bot_id": wid, "placement": pl.get("placement"), "loan_id": None, "loan_from": None, "seat": None, "picked": None}
    else:
        explicit = bool(pl.get("bot_explicit"))
        lead_target = (resolve_lead_target(prj) if role == "lead" and prj is not None and not explicit else (None, None))
        try:
            pw = _place_worker(prj, role, ident, dispatcher, drole, bot_id=wid, explicit=explicit,
                               lead_bot=lead_target[0], job_id=job_id,
                               loan_key=pl.get("loan_key"))   # Issue933 — dispatch 가 밝힌 차용 키로 같은 판정
        except (Reject, FbotError) as e:
            # prj3#Issue945 검토 S5 — 배치 거부 사유는 갈 곳(그 prj 팀장 인박스 명령)을 끝에 싣는다. 300자 절단이 운영 id
            #   길이에서 그 명령을 잘랐다(⓪ 사유 332자+). 배치 거부는 전문, 그 밖(인프라 오류 등)은 종전 절단
            return dict(base, ok=False, error=str(e) if isinstance(e, PlacementReject) else str(e)[:300])
    wid = pw["bot_id"]
    next_step = _spawn_commands(wid, ident, pl.get("cwd") or "", prj, role=role, disp_id=job_id,
                                model=pl.get("model_override") or pl.get("model"))
    spawned = _spawn_now(next_step)
    now = int(time.time())
    con = connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        cur = con.execute("SELECT payload FROM job WHERE id = ?", (job_id,)).fetchone()
        p2 = json.loads(cur["payload"] or "{}")
        p2.update({"worker_bot_id": wid, "placement": pw["placement"], "spawn_placed_at": p2.get("spawn_placed_at") or now})
        if pw["loan_id"]:
            p2.update({"loan_id": pw["loan_id"], "loan_from": pw["loan_from"]})
        if spawned.get("ok"):
            p2["spawned_at"] = now                 # prj3#Issue814 — watch 출근 유예의 기준 시각
        con.execute("UPDATE job SET payload = ? WHERE id = ?", (json.dumps(p2, ensure_ascii=False), job_id))
        _ev(con, by, "spawn", f"{job_id} → {wid} ({pw['placement']}){'' if spawned.get('ok') else ' 기동 실패'}"[:120], job_id)
        _ev(con, wid, "assigned", f"← {dispatcher}: {ident[:80]}", job_id)
        con.execute("COMMIT")
    finally:
        con.close()
    res = dict(base, ok=bool(spawned.get("ok")), worker_bot_id=wid, placement=pw["placement"],
               next_step=next_step, spawned=spawned)
    if pw["seat"] is not None:
        res["seat"] = pw["seat"]
    if pw["picked"]:
        res["seat_pick"] = pw["picked"]
    if not spawned.get("ok"):
        res["error"] = str(spawned.get("reason") or spawned.get("error") or spawned)[:200]
        if next_step.get("run") != "fpm_do":
            res["drop"] = True                     # Agent 형태 — 무인 재시도로는 안 뜬다
    return res


def spawn_pending(by=None, dry_run=False) -> list:
    """`spawn_pending` 표지가 있는 open 배분을 전부 기동한다 — tick worker 가 sweep 뒤에 돈다 (prj3#Issue904).

    표지는 `promote_deferred` 가 승격과 함께 남긴다. 결과별 처리(판정은 이 함수 한 곳):
      · 성공 → 표지 해제 · 동시 상한(`wait`) → 표지 유지·시도 미계수(다음 tick)
      · 무인 불가(`drop` — Agent 형태)·입력 오류(open 아님) → 표지 해제 + `spawn_gave_up`
      · 그 밖의 실패 → `spawn_attempts` +1, `RETRY_LIMIT` 에 이르면 표지 해제 + `spawn_gave_up` — 그 뒤는 watch 적체가 드러낸다
    """
    con = connect()
    try:
        rows = [j for j in active_dispatches(con)
                if j["status"] == "open" and (j.get("payload") or {}).get("spawn_pending")]
    finally:
        con.close()
    if dry_run:
        return [{"job_id": j["id"], "issue": j["payload"].get("issue"), "role": j["payload"].get("role"),
                 "worker_bot_id": j["payload"].get("worker_bot_id")} for j in rows]
    out = []
    for j in rows:
        try:
            r = spawn_dispatch(j["id"], by=by, unattended=True)
        except Reject as e:
            r = {"job_id": j["id"], "ok": False, "drop": True, "error": e.reason}
        con = connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            cur = con.execute("SELECT payload FROM job WHERE id = ?", (j["id"],)).fetchone()
            p2 = json.loads(cur["payload"] or "{}") if cur else {}
            if r.get("ok"):
                p2.pop("spawn_pending", None)
            elif not r.get("wait"):
                n = int(p2.get("spawn_attempts") or 0) + (0 if r.get("drop") else 1)
                p2["spawn_attempts"] = n
                p2["spawn_error"] = str(r.get("error") or "")[:200]
                if r.get("drop") or n >= RETRY_LIMIT:
                    p2.pop("spawn_pending", None)
                    p2["spawn_gave_up"] = int(time.time())
            if cur:
                con.execute("UPDATE job SET payload = ? WHERE id = ?", (json.dumps(p2, ensure_ascii=False), j["id"]))
            con.execute("COMMIT")
        finally:
            con.close()
        out.append({k: v for k, v in r.items() if k != "next_step"})
    return out


def cmd_spawn(args) -> int:
    """open 배분 몸체 기동 (prj3#Issue904) — `--pending`(승격 표지 전부, tick) 또는 `--job-id`(한 건, 매니저·사람)."""
    if args.pending:
        rows = spawn_pending(by=args.by, dry_run=args.dry_run)
        emit({"ok": True, "action": "spawn", "mode": "dry-run" if args.dry_run else "apply",
              ("targets" if args.dry_run else "spawned"): rows, "count": len(rows)})
        return 0
    if args.dry_run:
        con = connect()
        try:
            r = con.execute("SELECT status, payload FROM job WHERE id = ? AND kind = ?", (args.job_id, JOB_KIND)).fetchone()
        finally:
            con.close()
        if not r:
            raise Reject(1, f"배분 없음: {args.job_id}")
        p = json.loads(r["payload"] or "{}")
        emit({"ok": r["status"] == "open", "action": "spawn", "mode": "dry-run", "job_id": args.job_id,
              "status": r["status"], "worker_bot_id": p.get("worker_bot_id"), "role": p.get("role"), "prj": p.get("prj")})
        return 0
    res = spawn_dispatch(args.job_id, by=args.by)
    emit(dict(res, action="spawn"))
    # Agent 형태(prj 미해소)는 실패가 아니다 — dispatch 와 같이 next_step.agent 를 호출자가 Agent 도구로 띄운다
    return 0 if res.get("ok") or (res.get("next_step") or {}).get("run") == "agent" else 2


def cmd_dispatch(args) -> int:
    """배분 요청 — ① 수요측 가드 ② HR 게이트 hire(채용) ③ 배분 기록(F4).

    스폰 **집행**은 fpm-do/Agent 몫이다 — 여기서는 채용과 기록까지만.
    착수 가능 판정은 pending(issue-map)이 재료다 — 배분 요청은 그 판정을 재현하지 않는다.
    """
    # Issue526 — 식별자 축을 넓힌다. 단일 `--issue` 가 없는 작업(크로스 프로젝트 조사 등)이
    #   정규 경로를 못 써서 `dispatch-record` 로 우회하던 것이 `logged` 의 발생 원인이었다.
    #   ⚠️ payload 키는 `issue` 그대로 둔다 — status/sweep/queue 등 소비처 9곳이 전부
    #   `payload.get("issue")` 를 읽는다. 키를 바꾸면 그 전부가 조용히 빈 값을 보게 된다.
    #   구분이 필요하면 `ident_kind` 를 본다.
    # prj3#Issue874 — 동시 지정은 topic 이 payload·워커 프롬프트 어디에도 안 남고 버려진다(2026-09-29 scout draft 재작성
    #   지시 유실 실발생 `fbotdisp-1790634781-d5f9e19b`). payload.issue 계약(위)을 지키려 부가 지시 보존 대신 거부한다
    if args.issue and (getattr(args, "topic", None) or "").strip():
        raise Reject(2, "--issue 와 --topic 은 동시에 줄 수 없다 — topic 이 워커에 전달되지 않고 버려진다. "
                        "지시를 전하려면 이슈 본문(`* 상세`)에 적거나 --topic 만 쓴다")
    ident = (args.issue or getattr(args, "topic", None) or "").strip()
    if not ident:
        raise Reject(2, "배분 식별자가 없다 — --issue 또는 --topic 중 하나는 필수다")
    ident_kind = "issue" if args.issue else "topic"
    if args.issue:
        # prj3#Issue761 — `--issue 727`(맨 숫자)을 그대로 적으면 sweep 대조(`Issue<N>:` 헤더)·중복 판정·이슈맵이
        #   전부 빗나가 open 이 영구 잔류하고 fpm-do 사후 기록이 두 번째 줄로 붙었다. 기록 형식으로 적는다
        ident = _canon_issue(ident)
    # prj3#Issue849 — 몸체 모델 판정은 가드·채용·기록 **전**에 한다. 허용 목록 밖 fable·별칭 밖 값이면
    #   배분 행을 남기지 않고 거부한다(rc 2 — 입력 오류). 통과한 값은 payload 에 남아 재스폰이 같은 override 를 쓴다
    _mo = getattr(args, "model", None)
    try:
        body_model = model_for(args.role, _mo)
    except ValueError as e:
        raise Reject(2, str(e))

    cwd = os.path.abspath(os.path.expanduser(args.cwd))
    workflow = load_workflow(cwd)
    # prj 해소 (prj3#Issue479) — cwd 는 workflow 만 해소하고 prj 는 버려지고 있었다. 그 결과
    #   전 봇이 prj=NULL 로 등록되어 "어느 prj 담당인가" 를 물을 수 없었다(2026-08-31 실측 13/13).
    prj = resolve_prj(cwd)
    # prj3#Issue945 — 인력 확보 사다리 ⓪ cross: 팀장이 **남의 prj 일**을 시키면 그 prj 팀장 인박스로 보낸다.
    #   대상 prj 를 cwd 로 확정한 직후 — 자리 개체 선택(`seat_pick`)·차용(`loan_reject`)·채용 사다리가 그 prj 자리를 «내 팀
    #   자리» 로 잘못 고르기 전이고, Jev 모델 판정(외부 호출)·수요측 가드보다 앞이다. 판정은 fbot-org `cross_step` 한 곳 —
    #   `staffing`·`hire_ladder_verdict` 가 `ladder_step(by=…)` 로 같은 함수를 탄다. dry-run·미룬 배분도 여기서 같은 거부
    _xs = _cross_verdict(prj, args.role, getattr(args, "by", None) or BOT_ID)
    if _xs:
        raise PlacementReject(_xs["reason"])
    # prj3#Issue863_6 — `--model` 이 없고 직능이 정책 `dispatch.jev_roles` 에 있으면 Jev 가 몸체 모델을 고른다(위 model_for 는
    #   입력 검증·기본값). 질문 = topic, 이슈 배분은 대상 repo 의 이슈 제목 한 줄. dry-run 은 부르지 않는다(기록 없음 계약)
    _q = ident if ident_kind == "topic" else _issue_title(cwd, ident)
    body_model, _mmeta = dispatch_model(args.role, _mo, _q, prj, dry_run=bool(getattr(args, "dry_run", False)))
    pol = load_policy()
    _actor = getattr(args, "by", None) or BOT_ID   # prj3#Issue613 — 배분자별 축
    con = connect()
    try:
        guard = judge_demand_guard(con, pol, _actor, ident, prj, role=args.role,
                                   breaker_ack=getattr(args, "breaker_ack", None))  # ① 통과 못 하면 Reject → exit 1
    finally:
        con.close()

    # prj3#Issue538: 배분자 실재 확인. `job.owner_id` 가 `bot(bot_id)` FK 라 없는 봇이면
    #   INSERT 가 실패한다. **dry-run 보다 앞**에 둔다 — dry-run 의 계약이 "가드 판정까지"
    #   (Issue933 — 게이트 호출 직전의 배치 판정까지 확장)이고 배분자 실재는 가드의 일부다. 뒤에 두면 dry-run 이 없는 배분자를 허가한다.
    #   ⚠️ sqlite3.Connection 의 `with` 는 트랜잭션 컨텍스트일 뿐 커넥션을 닫지 않는다.
    dispatcher = getattr(args, "by", None) or BOT_ID
    _c = connect()
    try:
        _drow = _c.execute("SELECT role FROM bot WHERE bot_id=?", (dispatcher,)).fetchone()
        if not _drow:
            raise Reject(1, f"배분자가 대장에 없다: {dispatcher} (채용이 먼저다)")
        # prj3#Issue608 — **계층 건너뛰기 금지** (사용자 지적 2026-09-09):
        #   *"회장이나 사장이 말단 사원에게 일을 시키는 꼴이다. 전체 구조를 아는 관리자가 시켜야 한다."*
        #   prj3#Issue757 F — 총괄의 상대는 **팀장(과 동급 총괄)뿐**이다. 판정은 `chief_target_reject` 한 곳.
        _drole = (_drow[0] or "") if not isinstance(_drow, dict) else (_drow["role"] or "")
        _why = chief_target_reject(_drole, args.role or "")
        if _why:
            raise Reject(1, _why)
        # prj3#Issue773 ③ — 이 배분이 처리하는 인박스 요청. 판정은 fbot-inbox `request_link_error` 한 곳
        if getattr(args, "request", None):
            _rerr = _inbox_mod().request_link_error(_c, args.request, dispatcher)
            if _rerr:
                raise Reject(1, _rerr)
    finally:
        _c.close()

    lead_target = (resolve_lead_target(prj) if args.role == "lead" and prj is not None
                   and not args.bot_id else (None, None))
    # Issue933 — 차용 일 키를 topic 과 분리한다. 기록(payload `loan_key`)은 spawn·재스폰이 같은 키로 판정하게 하려는 것
    loan_key = (getattr(args, "loan_key", None) or "").strip() or None
    if args.dry_run:
        # Issue933 — 실배분과 같은 배치 판정(_place_worker)을 게이트 호출 직전까지 탄다. 거부는 실배분과 같은 Reject(rc 1).
        #   미룬 배분은 기록 시점에 배치하지 않으므로(승격 뒤 spawn 이 배치) dry-run 도 배치를 보지 않는다
        pv = None
        if not getattr(args, "deferred_until", None):
            pv = _place_worker(prj, args.role, ident, dispatcher, _drole, bot_id=args.bot_id,
                               explicit=bool(args.bot_id), lead_bot=lead_target[0], loan_key=loan_key, dry_run=True)
        emit({"ok": True, "action": "dispatch", "mode": "dry-run", "verdict": "허가",
              "dispatched_by": dispatcher,
              "issue": ident, "ident_kind": ident_kind, "role": args.role,
              "workflow": workflow, "prj": prj, "guard": guard,
              **({"deferred_until": args.deferred_until} if getattr(args, "deferred_until", None) else {}),
              # Issue692 — lead 배분이 누구에게 가는지(기존 팀장 wake / 신규 채용 이름)를 미리 보인다
              **({"lead_target": {"bot_id": lead_target[0],
                                  "hire_title": lead_target[1]}} if lead_target[0] else {}),
              **({"worker_bot_id": pv["bot_id"], "placement": pv["placement"],
                  **({"loan_id": pv["loan_id"], "loan_from": pv["loan_from"]} if pv["loan_id"] else {}),
                  **({"seat": pv["seat"]} if pv["seat"] else {}),
                  **({"seat_pick": pv["picked"]} if pv["picked"] else {})} if pv else {}),
              **({"loan_key": loan_key} if loan_key else {})})
        return 0

    if getattr(args, "deferred_until", None):
        return _record_deferred_dispatch(args, ident, ident_kind, body_model, _mmeta, _mo, cwd, workflow, prj,
                                         dispatcher, lead_target)

    # ② HR 게이트 경유 배치 — 게이트 없는 스폰 경로 금지 (계약 §호출 경계). 판정은 _place_worker 한 곳(prj3#Issue904 — spawn 공용)
    pw = _place_worker(prj, args.role, ident, dispatcher, _drole, bot_id=args.bot_id,
                       explicit=bool(args.bot_id), lead_bot=lead_target[0], loan_key=loan_key)
    bot_id, placement, job_id = pw["bot_id"], pw["placement"], pw["job_id"]
    loan_id, _lfrom, hire_seat, picked = pw["loan_id"], pw["loan_from"], pw["seat"], pw["picked"]

    # ③ 배분 기록 — bot_id=fbot-lead 귀속(F4) + 원장 증분(BEGIN IMMEDIATE 재검증)
    now = int(time.time())
    # prj3#Issue931 ② — 잘린 배분의 몸체 하한. 잘림은 워커 id 가 정해진 **뒤**에야 판정된다(기동 줄 길이가 id 에 달렸다) —
    #   판정은 기동과 같은 함수(prompt_cut → _spawn_commands). `--model` 명시면 판정하지 않는다(clamp 밖)
    body_model, _mmeta = cut_floor_model(args.role, _mo, body_model, _mmeta, not _mo and prompt_cut(
        bot_id, ident, cwd, prj, args.role, job_id, body_model))
    # 계약 §레지스트리 스키마: "어느 prj 일을 했나" 는 **작업 기록**이 답한다 — bot.prj(주 담당)와
    #   축이 다르므로 배분 원장에도 남긴다(겸임은 기록 레벨에서 표현된다).
    payload = {"issue": ident, "ident_kind": ident_kind, "role": args.role, "model": body_model,
               "worker_bot_id": bot_id, "cwd": cwd, "workflow": workflow, "prj": prj}
    if _mo:                                       # prj3#Issue849 — 재스폰(worker_died·quota·resume)이 같은 override 를 쓴다
        payload["model_override"] = _mo
    payload["model_source"] = _mmeta.get("source")   # prj3#Issue863_6 — override·jev·static
    payload["model_reason"] = _mmeta.get("reason")
    if _mmeta.get("event_id"):                    # prj3#Issue863_2 — 선택 기록(sel_event)과 배분 결과를 잇는 키(selection.py stats)
        payload["sel_event"] = _mmeta["event_id"]
    _msrc = _mmeta.get("source")
    if _msrc == "jev" and not _mo:                # 재기동·기상은 재판정하지 않는다 — 고른 모델을 override 자리에 남긴다
        payload["model_override"] = body_model
    if getattr(args, "request", None):            # prj3#Issue773 ③ — sweep 이 이 배분을 닫으면 요청도 닫힌다
        payload["request_id"] = args.request
    if _expect_paths(args, cwd):                  # prj3#Issue929 — 산출 계약. sweep 이 topic 배분 완료 증적으로 대조한다
        payload["expect"] = _expect_paths(args, cwd)
    if loan_id:                                   # prj3#Issue757 T13 — 차용 배분: 소속은 원 팀 그대로, 기록만 잇는다
        payload.update({"loan_id": loan_id, "loan_from": _lfrom})
    if loan_key:                                  # Issue933 — 재스폰·spawn 이 같은 차용 키로 판정한다
        payload["loan_key"] = loan_key
    if guard.get("breaker_ack"):                  # prj3#Issue952 — 서킷브레이커 해제 증적. streak 루프가 여기서 끊는다
        payload["breaker_ack"] = guard["breaker_ack"]
    _sm = _state_mod()                            # prj3#Issue757 T15 ⑥ — 어느 몸체(세션·흐름)가 배분했나
    if _sm is not None:
        payload.update(_sm.body_stamp())
    con = connect()
    try:
        # prj3#Issue749 — «사람에게 의뢰를 받은 세션» 기록. 워커의 질문이 이 세션으로 올라간다.
        #   판정은 fbot-inbox.py requester_of 단일 지점(사람 세션 env > 받은 배분 상속 > 인박스 요청).
        _req = None
        if getattr(args, "requester_session", None):
            _req = {"session": args.requester_session, "via": "explicit", "ref": None, "ambiguous": False}
        else:
            try:
                _req = _inbox_mod().requester_of(con, dispatcher, env=os.environ)
            except Exception as _e:   # 기록 실패가 배분을 막지 않는다 — 질문 시점에 계보로 다시 판정한다
                print(f"[fbot-lead] requester 판정 실패(배분은 진행): {_e}", file=sys.stderr)
        if _req:
            payload.update({"requester_session": _req["session"], "requester_via": _req["via"]})
            if _req.get("ref"):
                payload["requester_ref"] = _req["ref"]
            if _req.get("ambiguous"):
                payload["requester_ambiguous"] = True
        # prj3#Issue739 M1-2 — 배분 계보. 판정은 fbot-state `dispatch_lineage` 단일 지점(dispatch-record 와 같은 규칙):
        #   명시 --parent-dispatch > 몸체 흐름 FBOT_FLOW(T15) > 배분자가 worker 인 미종결 배분 1건 > root · 2건+ 는 고르지 않는다
        if _sm is not None:
            payload.update(_sm.lineage_fields(
                _sm.dispatch_lineage(con, dispatcher, getattr(args, "parent_dispatch", None),
                                     os.environ.get("FBOT_FLOW") or None), job_id))   # root_dispatch_id 는 부모 없으면 자기 id
        # 쓰기 도중 예외는 close 시 미커밋 트랜잭션이 자동 폐기된다(원자성 유지).
        # prj3#Issue696 — 월 상한 재검증 거부는 없앴다(월 상한은 알림 전용). 원장 증분은 유지 —
        #   비용 추세를 보는 계기판이다.
        con.execute("BEGIN IMMEDIATE")
        month = month_key()
        con.execute(
            "INSERT INTO kv (ns, key, value, expires_at, updated_at, updated_by)"
            " VALUES (?,?,?,NULL,?,?)"
            " ON CONFLICT(ns, key) DO UPDATE SET"
            "   value = CAST(CAST(value AS INT) + 1 AS TEXT), updated_at = excluded.updated_at",
            (DISPATCH_NS, month, "1", now, BOT_ID),
        )
        # prj3#Issue538: `owner` 는 **배분자**다. 전역 하나로 고정하면 prj PM 이 배분해도
        #   원장에는 전역 봇이 시킨 것으로 남아 **총괄→PM→워커 체인이 원리적으로
        #   기록될 수 없다**(실측: dispatch 1건이 전부 taskmgr owner).
        # ⚠️ 예산·상한 원장 키(DISPATCH_NS)는 위에서 **BOT_ID 로 전역 합산**한다 —
        #   배분자별로 갈리면 PM 을 늘리는 것만으로 3중 폭주 가드를 우회할 수 있다.
        con.execute(
            "INSERT INTO job (id, store, kind, status, payload, result, attempts,"
            " owner, lease_until, blocked_since, created_at)"
            " VALUES (?,?,?,?,?,NULL,0,?,NULL,NULL,?)",
            (job_id, "fbot", JOB_KIND, "open", json.dumps(payload, ensure_ascii=False),
             dispatcher, now),
        )
        _ev(con, dispatcher, "dispatch", f"→ {bot_id}: {ident[:80]}", job_id)     # prj3#Issue575
        _ev(con, bot_id, "assigned", f"← {dispatcher}: {ident[:80]}", job_id)
        con.execute("COMMIT")
        _ev_notify(dispatcher, "dispatch", job_id)
        spent_after = dispatched_this_month(con, month)
    finally:
        con.close()

    # prj3#Issue696 — 월 상한 **도달 알림**(차단 아님). 증분이 락 안에서 1씩 오르므로
    #   정확히 상한과 같아지는 배분은 달마다 하나뿐이다 — 별도 중복 억제 원장이 필요 없다.
    m_limit = pol["fbot_dispatch_monthly_limit"]
    if spent_after == m_limit:
        try:
            mq_alert(f"fbot 월 배분 {month} {spent_after}건 — 알림 기준 {m_limit}건 도달(차단 아님). "
                     f"비용 추세 확인용. 폭주 차단은 동시·같은 일 반복·되풀이 속도·배분자 백스톱·연속 실패 가드가 맡는다")
        except Exception as _e:  # 알림 실패가 배분을 되돌리지 않는다 — 이미 기록됐다
            print(f"[fbot-lead] 월 배분 알림 실패: {_e}", file=sys.stderr)

    # prj3#Issue538: 조직 부활 — **깨우는 것은 시간이 아니라 일이다.**
    #   집행 지점을 배분 1곳에 둔다. 조직도 렌더나 hub 요청이 부활시키면 관측이 상태를
    #   바꾸는 것이라 원장이 거짓말을 시작한다. 실패해도 배분을 막지 않는다(fail-soft) —
    #   조직 기능은 표시 계층이고 배분은 작업 계층이다.
    woke = None
    if prj is not None:
        try:
            import importlib.util as _il
            _op = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fbot-org.py")
            if os.path.exists(_op):
                _sp = _il.spec_from_file_location("fbot_org", _op)
                _m = _il.module_from_spec(_sp); _sp.loader.exec_module(_m)
                _r = _m.wake(prj, reason=f"배분 {job_id}")
                woke = bool(_r.get("changed"))
        except Exception as _e:
            log(f"org wake(prj={prj}) skipped: {_e}") if "log" in dir() else None

    # prj3#Issue554 — 집행 명령을 응답에 싣는다. 매뉴얼이 명령을 복제하면 낡는다;
    #   배분자는 이 값을 **그대로 실행**한다. 실행하지 않으면 워커는 출근 0회로 reap 된다
    #   (2026-09-06 실측: 배분 2건 전부 reaped, session_id NULL).
    res = {
        "ok": True, "action": "dispatch", "verdict": "허가",
        "issue": args.issue, "role": args.role, "worker_bot_id": bot_id,
        "dispatched_by": dispatcher, "placement": placement,
        "job_id": job_id, "workflow": workflow, "org_woke": woke,
        "ledger": {"ns": DISPATCH_NS, "month": month, "spent": spent_after,
                   "limit": pol["fbot_dispatch_monthly_limit"]},
        "next": "스폰 집행은 fpm-do/Agent 몫 — 본 기록은 채용+배분까지 (계약 §호출 경계)",
        "next_step": _spawn_commands(bot_id, ident, cwd, prj, role=args.role, disp_id=job_id, model=_mo or body_model),
    }
    if hire_seat is not None:                     # prj3#Issue821 ⓒ
        res["seat"] = hire_seat
    if picked:                                    # prj3#Issue838 — 자리 개체 선택(via seat|loan · 물러섬 사유)
        res["seat_pick"] = picked
    # prj3#Issue779_8 — --spawn 이면 fpm-do 기동까지 이 호출에서 끝낸다(별도 도구 호출 1회 절약)
    if getattr(args, "spawn", False):
        res["spawned"] = _spawn_now(res["next_step"])
        # prj3#Issue903 — fpm-do 형태인데 기동이 실패했으면 배분을 자동 취소한다(Agent 형태 «직접 띄울 것» 은 실패가 아니다)
        if not res["spawned"].get("ok") and (res["next_step"] or {}).get("run") == "fpm_do":
            try:
                if _cancel_failed_spawn(job_id, dispatcher, res["spawned"]):
                    res["spawned"]["cancelled"] = True
                    res["next"] = (f"spawn 실패 — 배분 {job_id} 자동 취소(spawn_failed): "
                                   f"{str(res['spawned'].get('reason') or res['spawned'].get('error') or '')[:100]}")
            except Exception as _e:  # noqa: BLE001 — 취소 실패는 보고만(배분 기록은 이미 있다)
                res["spawned"]["cancel_error"] = str(_e)[:100]
        if res["spawned"].get("ok"):
            res["next"] = "기동 완료(분리 실행) — 수령은 sweep"
            # prj3#Issue814 — 출근 유예의 기준 시각. watch 가 이 뒤 N분 내 출근 이벤트가 없으면 적체로 드러낸다
            con = connect()
            try:
                con.execute("UPDATE job SET payload = json_set(payload, '$.spawned_at', ?) WHERE id = ?",
                            (int(time.time()), job_id))
                con.commit()
            finally:
                con.close()
    emit(res)
    return 0


def _checked_in_since(con, wid, since) -> bool:
    """`since` 이후 워커의 출근 이벤트(CHECKIN_EVENTS) 유무 (prj3#Issue814). 이벤트 원장은 fbot-state `record_event`."""
    ph = ",".join("?" * len(CHECKIN_EVENTS))
    return con.execute(
        f"SELECT 1 FROM job WHERE kind = 'fbot_event' AND owner = ? AND created_at >= ?"
        f" AND json_extract(payload, '$.type') IN ({ph}) LIMIT 1",
        (wid, since, *CHECKIN_EVENTS)).fetchone() is not None


def cmd_watch(args) -> int:
    """진행 감시 — **완료 스윕 선행** → 적체 2종 판정 → 재시도 카운트 → 초과 시 에스컬레이션.

    ⚠️ 순서가 계약이다. 완료한 워커도 `checkout` 이라 적체 B 와 겉모습이 같다 —
    스윕을 뒤에 두면 정상 완료가 먼저 에스컬레이션되어 거짓 경보가 된다.
    """
    pol = load_policy()
    now = int(time.time())
    swept = run_sweep(dry_run=False)   # 선행 — 완료분은 done 으로 빠져 적체 판정 대상에서 제외
    stalls, retried, escalated, quota_blocked = [], [], [], []
    grace = pol.get(CHECKIN_GRACE_KEY) or CHECKIN_GRACE_DEFAULT_MIN   # prj3#Issue814

    con = connect()
    try:
        # ── 적체 B: 배분 후 진행 신호 없음 (bot 부재·퇴근·lease 만료·스폰 뒤 출근 무기록 — Issue814) ──
        for job in [j for j in active_dispatches(con) if j["status"] == "open"]:
            wid = job["payload"].get("worker_bot_id")
            bot = con.execute("SELECT * FROM bot WHERE bot_id = ?", (wid,)).fetchone() if wid else None
            spawned_at = job["payload"].get("spawned_at")
            kind = "no_progress"
            if job["payload"].get("spawn_pending"):
                # prj3#Issue904 — 승격 배분의 기동 대기. tick `spawn --pending` 몫이라 재시도를 태우지 않는다(상한 뒤 표지가 걷히면 아래로)
                stalls.append({"kind": "spawn_pending", "job_id": job["id"],
                               "reason": f"승격 배분 기동 대기 — tick `spawn --pending`: {wid}"})
                continue
            if bot is None:
                reason = f"워커 봇 레코드 부재: {wid} — 조치: fbot-lead.py spawn --job-id {job['id']} (prj3#Issue904)"
            elif bot["state"] == "checkout":
                reason = f"워커 봇 퇴근 상태(작업 미완): {wid} — 조치: fbot-hr-gate.py wake --bot {wid} (Issue498)"
            elif bot["lease_expires"] is not None and bot["lease_expires"] < now:
                reason = f"워커 봇 lease 만료({now - bot['lease_expires']}초 경과): {wid}"
            elif spawned_at and now - int(spawned_at) > grace * 60 \
                    and not _checked_in_since(con, wid, job["created_at"]):
                # prj3#Issue814 — 스폰 3초 창은 통과했으나 세션이 안 뜬 워커. 봇은 register 기본(checkin·lease 2h)이라
                #   위 세 갈래에 안 걸려 reap 까지 안 보였다. 아래 재시도·에스컬레이션을 그대로 탄다
                reason = (f"워커 출근 무기록 — 스폰 {(now - int(spawned_at)) // 60}분 경과(유예 {grace}분)"
                          f"·state:checkin 없음: {wid}")
                kind = "no_checkin"
            else:
                continue  # 진행 신호 정상
            # prj3#Issue743 — 쿼터로 죽은 워커는 **재시도가 무의미하다**(해소 전엔 다시 띄워도 같다).
            #   재시도 카운트를 태우지 않고 즉시 blocked + 사유·해소 시각을 원장에 남긴다.
            #   쿼터는 모든 세션에 동시에 걸리므로 알림은 아래에서 **묶음 1회**다.
            end = last_session_end(con, wid, job["created_at"]) if wid else None
            if end and end.get("end_reason") == "quota":
                pl = job["payload"]
                quota = {"resets_at": end.get("resets_at"), "limit_type": end.get("limit_type"),
                         "session_job_id": end["session_job_id"], "detected_at": now}
                con.execute(
                    "UPDATE job SET status = 'blocked', blocked_since = ?,"
                    " payload = json_set(payload, '$.quota', json(?)) WHERE id = ? AND status = 'open'",
                    (now, json.dumps(quota), job["id"]),
                )
                spawn = _spawn_commands(wid, pl.get("issue") or pl.get("topic") or "", pl.get("cwd") or "",
                                        pl.get("prj"), role=pl.get("role"), disp_id=job["id"],
                                        model=pl.get("model_override"))
                quota_blocked.append({"job_id": job["id"], "issue": pl.get("issue") or pl.get("topic"),
                                      "worker_bot_id": wid, **quota,
                                      "respawn": spawn.get(spawn.get("run", "agent"))})
                stalls.append({"kind": "quota", "job_id": job["id"],
                               "reason": f"쿼터 소진 종료({end.get('limit_type') or '?'}, 해소 {_hhmm(end.get('resets_at'))}): {wid}"})
                continue
            if end and end.get("end_reason") == "api_error":
                reason += f" · 마지막 세션 API 오류({end.get('error') or '?'})"
            attempts = (job["attempts"] or 0) + 1
            if attempts > RETRY_LIMIT:
                # 재시도 상한 초과 → 에스컬레이션(1회) + blocked 전환(반복 alert 방지)
                msg = (f"[fbot-lead] 배분 적체 에스컬레이션 — job {job['id']} "
                       f"(이슈 {job['payload'].get('issue', '?')}): {reason}. "
                       f"재시도 {RETRY_LIMIT}회 초과 — 사람 판단 필요")
                enq = mq_alert(msg)
                con.execute(
                    "UPDATE job SET status = 'blocked', blocked_since = ?, attempts = ? WHERE id = ?",
                    (now, attempts, job["id"]),
                )
                escalated.append({"job_id": job["id"], "reason": reason, "enqueued": enq})
            else:
                con.execute("UPDATE job SET attempts = ? WHERE id = ?", (attempts, job["id"]))
                retried.append({"job_id": job["id"], "reason": reason,
                                "attempts": attempts, "limit": RETRY_LIMIT})
            stalls.append({"kind": kind, "job_id": job["id"], "reason": reason})

        # ── 적체 A: 미배분 startable 적체 (--cwd 지정 시만 — issue-map 필요) ──
        idle_pending = None
        if args.cwd is not None:
            cwd = os.path.abspath(os.path.expanduser(args.cwd))
            data = load_issue_map(cwd)  # 부재·실패 시 fail-loud
            startable, _ = classify(data["issues"])
            dispatched_ids = {j["payload"].get("issue")
                              for j in active_dispatches(con)}
            idle_pending = []
            for it in startable:
                if it["id"] in dispatched_ids:
                    con.execute("DELETE FROM kv WHERE ns = ? AND key = ?",
                                (DISPATCH_NS, f"idle:{data['root']}:{it['id']}"))
                    continue
                key = f"idle:{data['root']}:{it['id']}"
                row = con.execute("SELECT value FROM kv WHERE ns = ? AND key = ?",
                                  (DISPATCH_NS, key)).fetchone()
                seen = (int(row["value"]) if row else 0) + 1
                con.execute(
                    "INSERT INTO kv (ns, key, value, expires_at, updated_at, updated_by)"
                    " VALUES (?,?,?,NULL,?,?)"
                    " ON CONFLICT(ns, key) DO UPDATE SET value = excluded.value,"
                    " updated_at = excluded.updated_at",
                    (DISPATCH_NS, key, str(seen), now, BOT_ID),
                )
                item = {"issue": it["id"], "watch_count": seen, "limit": RETRY_LIMIT}
                if seen == RETRY_LIMIT + 1:  # 상한 초과 첫 관측에서만 1회 alert
                    msg = (f"[fbot-lead] 미배분 적체 에스컬레이션 — {data['root']} "
                           f"이슈 {it['id']} 이(가) 착수 가능 상태로 감시 {seen}회 연속 미배분. "
                           f"배분 또는 보류 판단 필요")
                    item["enqueued"] = mq_alert(msg)
                    escalated.append({"issue": it["id"], "reason": "미배분 적체",
                                      "enqueued": item["enqueued"]})
                idle_pending.append(item)
                stalls.append({"kind": "undispatched", "issue": it["id"], "seen": seen})
        else:
            idle_note = "미배분 적체 판정 생략 — --cwd 미지정(issue-map 대상 프로젝트 없음)"
    finally:
        con.close()

    # prj3#Issue743 — 쿼터 종료 묶음 통지 1회. 커밋(connection close) **후** 발신한다 —
    #   쓰기가 실패한 건을 알리지 않는다(sweep 과 같은 순서). blocked 는 다음 watch 의
    #   대상(open)이 아니므로 재통지는 구조적으로 없다.
    quota_enq = None
    if quota_blocked:
        resets = sorted({q["resets_at"] for q in quota_blocked if q.get("resets_at")})
        msg = ("[fbot-lead] 쿼터 소진으로 워커 종료 {}건 — {} · 해소 {}. 쿼터 해소 후 재위임: {}".format(
            len(quota_blocked),
            " · ".join(f"{q['issue'] or '?'}({q['worker_bot_id']})" for q in quota_blocked),
            ", ".join(_hhmm(r) for r in resets) or "미상",
            " / ".join(q["respawn"] for q in quota_blocked if q.get("respawn"))))
        quota_enq = mq_alert(msg)
        escalated.append({"kind": "quota", "count": len(quota_blocked), "enqueued": quota_enq})

    out = {"ok": True, "action": "watch", "now": now,
           "swept": {"detected": swept["detected"], "enqueued": swept["enqueued"],
                     "unconfirmed": swept.get("unconfirmed_detected", 0),   # prj3#Issue929 — 완료 미확인(배분자 인박스 행)
                     "gave_up": len(swept.get("unconfirmed_gave_up") or [])},   # prj3#Issue947 — 미확인 통지 포기·고착 재경보(mq 경보)
           "stall_count": len(stalls), "stalls": stalls,
           "retried": retried, "escalated": escalated, "quota_blocked": quota_blocked}
    if args.cwd is not None:
        out["undispatched_startable"] = idle_pending
    else:
        out["note"] = idle_note
    emit(out)
    return 0


def cmd_close(args) -> int:
    """**외부 증적으로 확정된 완료**를 원장에 반영한다 (prj3#Issue514, prj3#Issue495 예외의 경로화).

    왜 필요한가 — `sweep` 의 완료 판정은 원장 안의 증거(`fbot_session` done + 워커 `checkout`)
      를 요구한다. 그것이 옳다: 원장 밖 주장으로 완료를 찍으면 원장이 거짓말을 하기 시작한다.
      그런데 **증거가 원장에서 사라지는 경로가 실재**한다 —
        ⓐ prj3#Issue495: Agent 형태 봇이 퇴근 훅을 못 받아 세션 기록을 아예 못 남긴 경우
        ⓑ prj3#Issue514: 워커를 **해고**하면서 그 봇 행·세션 기록이 함께 지워진 경우(2026-09-03 실측)
      두 경우 모두 일은 **끝났고** 커밋·리포트라는 외부 증적이 있는데, `sweep` 은 영원히 못 닫고
      `cancel` 은 완료를 "무의미해짐" 으로 적어 거짓이 된다.

    🔴 prj3#Issue495 는 이 상황에서 **직접 UPDATE 를 1회 집행**하고 이렇게 적었다 —
      *"같은 상황이 재발하면 예외가 아니라 경로 부재의 신호로 읽는다."* 재발했다(prj3#Issue514).
      그래서 예외를 반복하는 대신 **경로를 만든다**. 이것이 그 경로다.

    ⚠️ `--evidence` 필수 — 원장 밖 증거를 원장 안에 **박아 둔다**(커밋 해시·리포트 경로·이슈).
      증적 없는 close 는 `sweep` 의 판정 규율을 우회하는 뒷문이 될 뿐이다.
    ⚠️ `verdict` 는 `completed_external` 로 `sweep` 의 `completed` 와 **구분**한다 — 나중에
      *"이 완료는 무엇이 보증했나"* 를 물을 수 있어야 한다.
    ⚠️ mq 통지 없음 — `cancel` 과 같은 이유다(사람이 알고서 명시 호출하는 사건).
    🔧 prj3#Issue819 — `--job-id` 로 지목한 **`cancelled`** 도 커밋 해시 증적이면 닫는다. 완료된 일이 회수로
      취소 행에 굳은 경우(hub 원클릭 실측)의 복구 경로다. 취소 기록은 `cancelled_from` 에 통째로 보존한다.
    """
    con = connect()
    try:
        targets = [j for j in active_dispatches(con)
                   if (args.job_id and j["id"] == args.job_id)
                   or (args.issue and j["payload"].get("issue") == args.issue)
                   or (args.worker and j["payload"].get("worker_bot_id") == args.worker)]
        prior = {}
        if not targets and args.job_id:
            r = con.execute("SELECT id, status, payload, result FROM job WHERE kind = ? AND id = ?"
                            " AND status = 'cancelled'", (JOB_KIND, args.job_id)).fetchone()
            if r is not None:
                if not EVIDENCE_HASH_RE.search(args.evidence or ""):
                    raise FbotError(f"cancelled 배분 {args.job_id} 은 커밋 해시 증적으로만 닫는다 — "
                                    f"--evidence {args.evidence!r} 에 해시(7~40자)가 없다")
                targets = [{"id": r["id"], "status": r["status"], "payload": _json_or_empty(r["payload"])}]
                prior[r["id"]] = _json_or_empty(r["result"])
        if not targets:
            key = args.job_id or args.issue or args.worker
            raise FbotError(f"종결 대상 없음: {key} — 미종결(open/blocked/logged/deferred) 배분이 아니다"
                            " (cancelled 는 --job-id 로 지목)")
        rows = [{"job_id": j["id"], "issue": j["payload"].get("issue"),
                 "role": j["payload"].get("role"),
                 "worker_bot_id": j["payload"].get("worker_bot_id"),
                 "from_status": j["status"]} for j in targets]
        if args.dry_run:
            emit({"ok": True, "action": "close", "mode": "dry-run",
                  "count": len(rows), "targets": rows, "evidence": args.evidence})
            return 0
        now = int(time.time())
        con.execute("BEGIN IMMEDIATE")
        applied = []
        for r in rows:
            _ev(con, args.by or BOT_ID, "close", f"{r.get('id','')}: {args.evidence or ''}"[:120], r.get("id",""))   # prj3#Issue575
            cur = con.execute(
                "UPDATE job SET status = 'done', blocked_since = NULL, result = ?"
                " WHERE id = ? AND status = ?",
                (json.dumps({"verdict": "completed_external",
                             "evidence": args.evidence, "reason": args.reason,
                             "detected_by": "manual:%s" % args.by,
                             "from_status": r["from_status"], "closed_at": now,
                             **({"cancelled_from": prior[r["job_id"]]} if r["job_id"] in prior else {})},
                            ensure_ascii=False),
                 r["job_id"], r["from_status"]),
            )
            if cur.rowcount == 1:
                applied.append(r)
        release_loans(con, [r["job_id"] for r in applied])   # prj3#Issue757 T13 — 작업 종결 시 차용 자동 해제
        con.execute("COMMIT")
    finally:
        con.close()
    _close_requests(applied, "close")
    skipped = [r for r in rows if r not in applied]
    emit({"ok": True, "action": "close", "mode": "apply", "verdict": "completed_external",
          "evidence": args.evidence, "closed": applied,
          "skipped_raced": skipped, "count": len(applied)})
    return 0


SOLO_APPROVAL_KIND = "fbot_solo_approval"   # prj3#Issue757 C — 사람 세션이 남기는 직접 수행 승인
SOLO_APPROVAL_TTL = 86400                    # 승인 유효 24시간 — 오래된 승인으로 창을 이어 붙이지 못하게(codex 리뷰 1차)


def _session_bound() -> str:
    """Issue830 — 사람 세션 판정은 fbot-state 단일 지점을 재사용한다."""
    global _STATE_MOD
    if _STATE_MOD is None:
        _STATE_MOD = _state_mod() or False
    if not _STATE_MOD:
        raise FbotError("fbot-state.py 적재 실패 — 사람 세션 판정을 수행할 수 없다")
    try:
        return _STATE_MOD.human_session_rejection()
    except _STATE_MOD.FbotError as e:
        raise FbotError(str(e))


def cmd_solo_approve(args) -> int:
    """사람의 직접 수행 승인 — **사람 세션 전용** 기록 (prj3#Issue757 C).

    왜 원장인가 (codex 리뷰 1차 — 추가 확인분, 2026-09-28): 1차 구현은 mq `[컨펌] [H:방침]` 의 confirmed 를 승인으로 셌다. 그러나
      mq ACK 는 주체를 기록하지 않아(`aoa_mq_ack` 는 어느 세션이든 부른다) 사람의 승인임을 증명하지 못하고,
      `-p` 로 뜬 팀장은 mq 를 거치지 않는다(Issue749 — 질문은 평문으로 올라간다). 그래서 승인은 질문을 받은
      **사람 세션이 원장에 남긴다**. 봇 세션은 여기서(FBOT_ID·세션 결속) 한 번, 쓰기 가드에서 한 번 막힌다."""
    _why = _session_bound()
    if _why:
        raise Reject(2, f"{_why} — 사람 승인은 결속 없는 사람 세션에서만 남긴다")
    reason = (args.reason or "").strip()
    if len(reason) < 8:
        raise Reject(2, "승인 사유가 너무 짧다(8자 이상) — 감사에서 읽히는 문장으로")
    con = connect()
    try:
        row = con.execute("SELECT role FROM bot WHERE bot_id=?", (args.bot,)).fetchone()
        if not row:
            raise Reject(1, f"대장에 없는 봇이다: {args.bot}")
        now = int(time.time())
        sid = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
        jid = f"fbotappr-{now}-{uuid.uuid4().hex[:8]}"
        con.execute("BEGIN IMMEDIATE")
        con.execute(
            "INSERT INTO job (id, store, kind, status, payload, result, attempts,"
            " owner, lease_until, blocked_since, created_at)"
            " VALUES (?,?,?,?,?,NULL,0,?,NULL,NULL,?)",
            (jid, "fbot", SOLO_APPROVAL_KIND, "open",
             json.dumps({"bot": args.bot, "reason": reason, "session": sid}, ensure_ascii=False),
             ("human:" + sid) if sid else "human", now))
        _ev(con, args.bot, "solo-approval", reason[:80], jid)
        con.execute("COMMIT")
    finally:
        con.close()
    emit({"ok": True, "action": "solo-approve", "approval_id": jid, "bot": args.bot, "reason": reason,
          "note": f"이 id 를 그 봇에게 답으로 돌려준다 — solo --approved-by {jid} (그 봇 전용·1회·24시간)"})
    return 0


def _use_solo_approval(con, approval_id, by, now) -> None:
    """승인 검증 + «사용됨» 전이 — 호출자의 트랜잭션 안에서 부른다(1회용 보장). 아니면 Reject."""
    approval_id = (approval_id or "").strip()
    if not approval_id:
        raise Reject(2, "solo 는 사람 승인이 있어야 한다 — --approved-by <승인 id> 필수. 팀장은 일을 직접 하지 않는다"
                        "(prj3#Issue757): 자리 안의 일은 dispatch, 자리 밖이면 총괄에 인력 요청. 그래도 직접 해야 하면"
                        " 평문으로 묻고 턴을 끝낸다 — 사람이 승인하면 그 세션이 solo-approve 로 남긴 id 가 답으로 온다")
    row = con.execute("SELECT status, payload, created_at FROM job WHERE id=? AND kind=?",
                      (approval_id, SOLO_APPROVAL_KIND)).fetchone()
    if not row:
        raise Reject(2, f"승인 기록이 없다: {approval_id} — 없는 id 로는 직접 수행할 수 없다")
    try:
        pl = json.loads(row[1] or "{}")
    except ValueError:
        pl = {}
    if pl.get("bot") != by:
        raise Reject(2, f"다른 봇의 승인이다({pl.get('bot')}) — 승인은 그 봇 전용이다")
    if row[0] != "open":
        raise Reject(2, f"이미 쓴 승인이다({approval_id}) — 승인은 1회용이다")
    if now - int(row[2] or 0) > SOLO_APPROVAL_TTL:
        raise Reject(2, f"승인이 만료됐다({approval_id}, 24시간) — 새 승인을 받는다")
    con.execute("UPDATE job SET status='used', result=? WHERE id=?",
                (json.dumps({"used_at": now}), approval_id))


def cmd_solo(args) -> int:
    """분업 우회 기록 — 팀장이 **직접 수행하는 사유**를 원장에 남긴다 (prj3#Issue612 → prj3#Issue757 C 사람 승인).

    🔧 **prj3#Issue757 C 개정** — 사유만으로는 통과하지 않는다. `--approved-by` 가 사람 세션이 남긴 승인
      (`solo-approve` — 그 봇 전용·1회·24시간)이어야 하고, 쓰기 가드는 payload 의 `approved_by` 가 있는 solo 만
      창 안 통과로 센다. 아래 «왜 필요한가» 는 종전 근거다 — 우회로 자체는 남기되 결정권을 사람에게 옮겼다.

    왜 필요한가:
      Issue612 는 *"직능 자리가 있으면 배분 의무"* 를 확정하고 [`fbot-writeguard.sh`](fbot-writeguard.sh)
      로 집행한다. 그런데 **모든 직접 수행이 위반은 아니다** — 자리 없는 일(조직 선언에 없는 직능),
      워커를 띄우는 비용이 작업보다 큰 한 줄 수정, 배분 자체를 성립시키기 위한 선행 작업이 있다.
      우회로가 없으면 가드가 팀장의 손을 통째로 묶고, 묶인 가드는 곧 꺼진다(prj1#Issue480 실패형).

    ⚠️ **우회는 무료가 아니다 — 사유가 원장에 남는다.** 그래서 감사에서 *"이 팀장은 배분 0건에
      우회 12건"* 이 보인다. 가드가 막는 것은 직접 수행이 아니라 **말없는 직접 수행**이다.
    ⚠️ 배분(`fbot_dispatch`)과 **kind 를 분리**한다. 같은 kind 로 섞으면 우회가 배분 실적으로
      잡혀 조직 판정(HR 부하·발굴 필요)이 정확히 반대로 읽는다 — 취소를 완료와 분리한 것과 같은 이유.
    ⚠️ 예산(`kv fbot:dispatch`)은 차감하지 않는다. 우회는 워커를 띄우지 않으므로 스폰 비용이 없다.
    """
    by = getattr(args, "by", None) or os.environ.get("FBOT_ID", "") or BOT_ID
    reason = (args.reason or "").strip()
    if len(reason) < 8:
        raise Reject(2, "우회 사유가 너무 짧다(8자 이상) — 감사에서 읽히지 않는 사유는 사유가 아니다")
    approved = (getattr(args, "approved_by", None) or "").strip()
    cwd = os.path.abspath(os.path.expanduser(args.cwd))
    prj = resolve_prj(cwd)
    con = connect()
    try:
        row = con.execute("SELECT role FROM bot WHERE bot_id=?", (by,)).fetchone()
        if not row:
            raise Reject(1, f"우회 주체가 대장에 없다: {by} (결속·채용이 먼저다)")
        role = row["role"] if not isinstance(row, tuple) else row[0]
        now = int(time.time())
        job_id = f"fbotsolo-{now}-{uuid.uuid4().hex[:8]}"
        payload = {"reason": reason, "scope": (args.scope or "").strip(),
                   "role": role, "cwd": cwd, "prj": prj, "approved_by": approved}
        con.execute("BEGIN IMMEDIATE")
        try:
            _use_solo_approval(con, approved, by, now)   # prj3#Issue757 C — 검증·사용됨 전이를 기록과 한 트랜잭션에
        except Reject:
            con.execute("ROLLBACK")
            raise
        con.execute(
            "INSERT INTO job (id, store, kind, status, payload, result, attempts,"
            " owner, lease_until, blocked_since, created_at)"
            " VALUES (?,?,?,?,?,NULL,0,?,NULL,NULL,?)",
            (job_id, "fbot", SOLO_JOB_KIND, "logged",
             json.dumps(payload, ensure_ascii=False), by, now),
        )
        _ev(con, by, "solo", f"{(args.scope or '')[:40]}: {reason[:80]}", job_id)
        con.execute("COMMIT")
    finally:
        con.close()
    emit({"ok": True, "action": "solo", "job_id": job_id, "by": by, "role": role,
          "reason": reason, "scope": payload["scope"], "prj": prj, "cwd": cwd,
          "approved_by": payload["approved_by"],
          "note": "사람 승인 직접 수행 — 쓰기 가드가 창(기본 6시간) 안에서 통과시킨다(prj3#Issue757 C)"})
    return 0


def solo_records(con: sqlite3.Connection) -> list:
    """우회 기록 조회 — 감사용(status 가 배분·취소와 **나란히** 보여준다)."""
    rows = con.execute(
        "SELECT id, owner, payload, created_at FROM job WHERE kind = ? ORDER BY created_at",
        (SOLO_JOB_KIND,),
    ).fetchall()
    out = []
    for r in rows:
        try:
            payload = json.loads(r["payload"] or "{}")
        except (ValueError, TypeError):
            payload = {}
        out.append({"id": r["id"], "owner": r["owner"], "payload": payload,
                    "created_at": r["created_at"]})
    return out


def nodelegate_records(con: sqlite3.Connection) -> dict:
    """감사 축 «배분 0 보고» (prj3#Issue757 E) — 관리직이 받은 일을 아무에게도 시키지 않고 결과를 올린 건.

    *"실작업인가"* 는 판정 영역이라 기계가 가를 수 없다. 대신 원장 사실 셋을 조인한다:
      ① 관리직(카탈로그 `nonexec`)이 받은 배분 D(`payload.worker_bot_id` = 그 봇)
      ② 그 봇의 상향 보고 — `fbot_request` 중 `from` = 그 봇 · `corr_id` = D (defer 가 배분 id 를 단다)
      ③ D 이후 첫 보고까지 그 봇이 낸 하위 배분
    판정 (prj3#Issue827 — 짝 1순위를 Issue739 계보로):
      ⓐ ③ 중 **계보가 D 를 가리키는** 하위가 있으면 **위임** — `parent_dispatch_id` = D · `requester_ref` = D ·
         모호 자식(`parent_ambiguous`)은 후보 배분 전부(`ambiguous_parent_candidates` — Issue781 과 같은 규칙)
      ⓑ 없으면 종전 일 키 — 같은 일 키(`payload.issue`) 하위가 있으면 **위임** · 하위가 0건이면 **nodelegate**
      ⓒ 둘 다 없으면 **unknown** — 키가 다른(계보가 남을 가리키는) 하위만 있거나 D 의 키가 비면(인박스 기상 등).
      같은 팀장의 병행 작업이 서로를 가리지 않게 계보·일 키 어느 쪽으로도 안 이어지면 확정하지 않는다(codex plan 점검 medium 3).
      topic 지휘 배분(일 키 없음)도 ⓐ 로 위임이 선다 — 실측 `fbotdisp-1790632081-fcc1bb87`(하위 9건 `requester_ref`).
    """
    roles = {r[0]: r[1] for r in con.execute("SELECT bot_id, role FROM bot")}
    disp = []
    for r in con.execute("SELECT id, owner, payload, created_at FROM job WHERE kind = ? ORDER BY created_at",
                         (JOB_KIND,)):
        try:
            pl = json.loads(r[2] or "{}")
        except (ValueError, TypeError):
            pl = {}
        disp.append({"id": r[0], "owner": r[1], "pl": pl, "at": r[3],
                     "payload": pl, "created_at": r[3]})     # `ambiguous_parent_candidates` 레코드 모양
    reports = {}
    for r in con.execute("SELECT payload, created_at FROM job WHERE kind = 'fbot_request' ORDER BY created_at"):
        try:
            pl = json.loads(r[0] or "{}")
        except (ValueError, TypeError):
            continue
        key = (pl.get("from") or "", pl.get("corr_id") or "")
        if key[0] and key[1] and key not in reports:
            reports[key] = r[1]
    out = {"nodelegate": [], "unknown": [], "delegated": 0}
    for d in disp:
        bot = d["pl"].get("worker_bot_id") or ""
        if not bot or not _is_nonexec(roles.get(bot)):
            continue
        rep_at = reports.get((bot, d["id"]))
        if rep_at is None:
            continue
        key = (d["pl"].get("issue") or "").strip()
        kids = [k for k in disp if k["owner"] == bot and d["at"] <= k["at"] <= rep_at and k["id"] != d["id"]]
        item = {"job_id": d["id"], "bot": bot, "issue": key, "dispatcher": d["owner"],
                "received_at": d["at"], "reported_at": rep_at}
        lineage = [k for k in kids
                   if d["id"] in (k["pl"].get("parent_dispatch_id"), k["pl"].get("requester_ref"))
                   or any(p["id"] == d["id"] for p in ambiguous_parent_candidates(k, disp))]
        if lineage or (key and any((k["pl"].get("issue") or "").strip() == key for k in kids)):
            out["delegated"] += 1
        elif key and not kids:
            out["nodelegate"].append(item)
        else:
            out["unknown"].append(item)
    return out


# ── brief (prj3#Issue779_7) ─────────────────────────────────────────────────
# 관리 조회는 `status`(JSON 1.6KB)·`fbot-state get`·`list`·`fbot-inbox pending` 을 조합해 읽었다 — 4일 약 250회.
# 호출 1회는 그 시점 컨텍스트 전체를 다시 읽으므로, 봇 기준으로 필요한 것만 **한 번에·30줄 이내** 텍스트로 낸다.

def _age(ts) -> str:
    s = max(int(time.time()) - int(ts or 0), 0)
    return f"{s // 60}분" if s < 3600 else (f"{s // 3600}시간" if s < 86400 else f"{s // 86400}일")


def _disp_line(j) -> str:
    pl = j.get("payload") or {}
    what = pl.get("issue") or pl.get("topic") or "?"
    return (f"- {j['id']} {what} → {pl.get('worker_bot_id') or '?'}({pl.get('role') or '?'}) "
            f"{j['status']} · {_age(j.get('created_at'))} 전")


def brief_lines(con, bot_id=None, limit=30) -> list:
    """봇 기준 상태 요약 — 나·내가 낸 배분·내게 온 배분·인박스·완료 감지. bot_id 가 없으면 조직 요약."""
    acts = active_dispatches(con)
    try:
        done_ids = {d.get("job_id") or d.get("id") for d in detect_completions(con)}
    except Exception:
        done_ids = set()
    out = []
    if bot_id:
        b = con.execute("SELECT * FROM bot WHERE bot_id=?", (bot_id,)).fetchone()
        if not b:
            return [f"대장에 없는 봇: {bot_id}"]
        b = dict(b)
        out.append(f"# {bot_id} — {b.get('role')}·{b.get('state')} · 현재 작업: {b.get('current_task') or '(없음)'}")
        mine = [j for j in acts if j.get("owner") == bot_id]
        out.append(f"## 내가 낸 배분 {len(mine)}건" + (f" · 완료 감지 {len([j for j in mine if j['id'] in done_ids])}건 → sweep"
                                                   if any(j["id"] in done_ids for j in mine) else ""))
        out += [_disp_line(j) for j in mine[:8]]
        got = [j for j in acts if (j.get("payload") or {}).get("worker_bot_id") == bot_id]
        if got:
            out.append(f"## 내게 온 배분 {len(got)}건")
            out += [_disp_line(j) for j in got[:5]]
        try:
            _pd = _inbox_mod().pending(bot_id=bot_id, limit=5) or {}
            items, dsp = _pd.get("items") or [], _pd.get("dispatching") or []
        except Exception as e:
            items, dsp, out = [], [], out + [f"## 인박스 — 조회 실패: {str(e)[:80]}"]
        if items:
            out.append(f"## 인박스 미처리 {len(items)}건 (reply 로 답한다)")
            out += [f"- {it['id']} ← {it.get('from') or it.get('from_session') or '?'} [{it.get('kind') or 'ask'}]: "
                    f"{(it.get('body') or '').strip()[:80]}" for it in items]
        if dsp:   # prj3#Issue816 — 넛지에서 빠진 요청. 연결 배분이 닫히면 sweep·close 가 요청도 닫는다
            out.append(f"## 인박스 배분 중 {len(dsp)}건: " + " · ".join(f"{x['id']} → {x['dispatch']}" for x in dsp[:5]))
    else:
        work = con.execute("SELECT bot_id, role, state, current_task FROM bot WHERE state<>'checkout'"
                           " ORDER BY role, bot_id").fetchall()
        out.append(f"# 조직 — 근무 중 {len(work)} · 열린 배분 {len(acts)} · 완료 감지 {len(done_ids & {j['id'] for j in acts})} → sweep")
        out += [f"- {r['bot_id']}({r['role']}·{r['state']}): {(r['current_task'] or '')[:60]}" for r in work[:12]]
        if acts:
            out.append("## 열린 배분 (최근)")
            out += [_disp_line(j) for j in acts[-10:]]
    return out[:limit]


def cmd_brief(args) -> int:
    con = connect()
    try:
        for ln in brief_lines(con, args.bot or os.environ.get("FBOT_ID") or None):
            print(ln)
    finally:
        con.close()
    return 0


# prj3#Issue786_2 부수 — fpm-do 즉시 실패(가드 거부·경로 오류) 확인 창(팀장 L 결정 `fbotev-1790626491-8dc4e0d4`).
#   이 창 안에 비0 으로 끝나면 `spawned.ok=false`. 출근 무기록 감지는 watch 몫이다(여기서 기다리지 않는다).
SPAWN_PROBE_SECS = 3


def _cancel_failed_spawn(job_id, by, spawned) -> bool:
    """spawn 실패 배분을 `cancelled`(spawn_failed)로 닫는다 (prj3#Issue903) — 기록만 있고 몸체가 없는 open 잔류 방지.
    출근 전(open)인 배분만 대상이라 이미 움직인 배분은 건드리지 않는다. 취소하면 True."""
    con = connect()
    try:
        _ev(con, by or BOT_ID, "cancel", f"{job_id}: spawn_failed"[:120], job_id)
        cur = con.execute(
            "UPDATE job SET status = 'cancelled', result = ? WHERE id = ? AND status = 'open'",
            (json.dumps({"verdict": "spawn_failed", "reason": "spawn_failed: " + str(
                (spawned or {}).get("reason") or (spawned or {}).get("error") or spawned)[:200],
                "cancelled_by": by, "from_status": "open", "cancelled_at": int(time.time())},
                ensure_ascii=False), job_id))
        con.commit()
        return cur.rowcount == 1
    finally:
        con.close()


def _spawn_now(next_step) -> dict:
    """`dispatch --spawn` (prj3#Issue779_8) — next_step 이 fpm-do 면 **같은 호출 안에서** 분리 실행한다.

    종전엔 배분자가 next_step 을 별도 도구 호출로 실행했다(4일 57회 — 그 앞 `which fpm-do` 확인까지).
    실행을 잊으면 워커는 출근 0회로 reap 되기도 했다(Issue554). 집행은 인박스 기상과 같은 단일 지점
    `fbot-inbox._run_spawn`(분리 실행·상속 봇 env 차단·로그). Agent 형태는 Claude 의 Agent 도구로만
    띄울 수 있어 그대로 돌려준다.
    """
    if (next_step or {}).get("run") != "fpm_do":
        return {"ok": False, "reason": "Agent 형태 — next_step.agent 를 Agent 도구로 띄울 것"}
    if next_step.get("line_over"):   # prj3#Issue824 — 잘릴 줄을 send-keys 하면 claude 가 안 뜬 채 무신호로 남는다
        return {"ok": False, "reason": f"기동 줄 {next_step.get('line_bytes')}B > 한도 {LINE_BUDGET}B — "
                                       "topic·워커 id 를 줄여 다시 배분할 것 (prj3#Issue824)"}
    try:
        return _inbox_mod()._run_spawn(next_step["fpm_do"], probe_secs=SPAWN_PROBE_SECS)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def cmd_topic(args) -> int:
    """배분 식별자 전문 조회 (prj3#Issue786_1) — `fit_prompt` 가 남긴 «topic 잘림» 줄이 가리키는 정본(payload.issue)."""
    con = connect()
    try:
        r = con.execute("SELECT payload FROM job WHERE id = ? AND kind = ?", (args.job_id, JOB_KIND)).fetchone()
    finally:
        con.close()
    if not r:
        raise Reject(1, f"배분 없음: {args.job_id}")
    pl = json.loads(r[0] or "{}")
    emit({"ok": True, "action": "topic", "job_id": args.job_id,
          "ident_kind": pl.get("ident_kind"), "topic": pl.get("issue")})
    return 0


def cmd_status(args) -> int:
    """이번 달 배분 수·상한·활성 배분 목록 + 취소 집계(Issue446 — 완료와 분리)."""
    pol = load_policy()
    month = month_key()
    con = connect()
    try:
        spent = dispatched_this_month(con, month)
        actives = active_dispatches(con)
        cancels = cancelled_dispatches(con)
        solos = solo_records(con)
        nodel = nodelegate_records(con)
    finally:
        con.close()
    month_solos = [s for s in solos if month_key(s["created_at"]) == month]
    # 취소는 **별도 축**이다 — dispatch.spent(예산 차감분)에서 빼지도, done 에 더하지도
    #   않는다. 예산은 이미 쓴 것이고 성과는 아니다. 그 둘을 동시에 성립시키는 유일한
    #   표현이 "따로 세어 따로 보여주기" 다 (Issue446).
    month_cancels = [c for c in cancels if month_key(c["cancelled_at"]) == month]
    emit({
        "ok": True, "action": "status", "month": month,
        "dispatch": {"ns": DISPATCH_NS, "spent": spent,
                     "limit": pol["fbot_dispatch_monthly_limit"],
                     "remaining": max(pol["fbot_dispatch_monthly_limit"] - spent, 0),
                     # prj3#Issue696 — 월 상한은 알림 기준이다. remaining 0 이어도 배분은 된다
                     "blocking": False},
        "concurrent": {"active": len([j for j in actives if j["status"] == "open"]),
                       "limit": pol["fbot_dispatch_concurrent_limit"],
                       "actor_limit": _opt(pol, "fbot_dispatch_actor_limit")},
        "pattern_guards": {k: _opt(pol, k) for k in OPTIONAL_POLICY_DEFAULTS
                           if k != "fbot_dispatch_actor_limit"},
        "active_dispatches": [
            {"job_id": j["id"], "status": j["status"], "attempts": j["attempts"],
             "issue": j["payload"].get("issue"), "role": j["payload"].get("role"),
             "worker_bot_id": j["payload"].get("worker_bot_id"),
             "created_at": j["created_at"], "blocked_since": j["blocked_since"],
             "deferred_reason": j["payload"].get("deferred_reason"),   # Issue686
             "quota": j["payload"].get("quota")}                       # Issue743 — 쿼터 종료 blocked
            for j in actives
        ],
        "cancelled": {
            "total": len(cancels), "month": len(month_cancels),
            # 사유는 `cancel --reason` 이 강제해 원장에 이미 있다 — 여기서 지어내지 않는다.
            "recent": [
                {"job_id": c["id"], "issue": c["payload"].get("issue"),
                 "role": c["payload"].get("role"),
                 "worker_bot_id": c["payload"].get("worker_bot_id"),
                 "verdict": c["result"].get("verdict"), "reason": c["result"].get("reason"),
                 "cancelled_by": c["cancelled_by"], "cancelled_at": c["cancelled_at"]}
                for c in cancels[-5:][::-1]
            ],
        },
        # prj3#Issue612 — 분업 우회 감사축. 배분과 **나란히** 보여야 비율이 읽힌다:
        #   배분 0 · 우회 12 는 조항이 지켜지지 않는다는 신호이고, 그것을 보는 자리가 여기다.
        "solo": {
            "total": len(solos), "month": len(month_solos),
            "by_bot": {b: len([s for s in month_solos if s["owner"] == b])
                       for b in sorted({s["owner"] for s in month_solos})},
            "recent": [
                {"job_id": s["id"], "by": s["owner"],
                 "reason": s["payload"].get("reason"), "scope": s["payload"].get("scope"),
                 "prj": s["payload"].get("prj"), "created_at": s["created_at"]}
                for s in solos[-5:][::-1]
            ],
        },
        # prj3#Issue757 E — «배분 0 보고». solo(우회 사유 기록)가 사라져도 직접 수행은 여기서 드러난다
        "nodelegate": {
            "total": len(nodel["nodelegate"]), "unknown": len(nodel["unknown"]),
            "delegated": nodel["delegated"],
            "by_bot": {b: len([x for x in nodel["nodelegate"] if x["bot"] == b])
                       for b in sorted({x["bot"] for x in nodel["nodelegate"]})},
            "recent": nodel["nodelegate"][-5:][::-1],
        },
    })
    return 0


# ── CLI ─────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="fbot-lead.py",
        description="fbot 팀장핀봇 판정 코어 (Issue436_3 s3) — 계약 fbot-arch.md §조직·§워크플로우 어댑터",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("pending", help="펜딩 큐 뷰 — issue-map --json 파생(startable/blocked)")
    sp.add_argument("--cwd", default=os.getcwd(), help="대상 프로젝트 루트(기본 현재 디렉토리)")
    sp.set_defaults(func=cmd_pending)

    sp = sub.add_parser("dispatch", help="배분 요청 — 수요측 가드 → HR hire → 배분 기록")
    # Issue526 — 둘 중 하나는 필수(cmd_dispatch 가 검증). required=True 를 풀되
    #   argparse 상호배타 그룹은 쓰지 않는다 — 둘 다 준 경우 --issue 우선이 자연스럽고,
    #   그룹으로 막으면 스크립트가 두 값을 모두 넘기던 기존 호출이 깨진다.
    sp.add_argument("--issue", default=None, help="이슈 ID (ex: Issue12)")
    sp.add_argument("--topic", default=None,
                    help="이슈 없는 배분의 주제 (ex: '크로스 prj 시급도 조사'). --issue 와 둘 중 하나 필수(동시 지정 거부 — Issue874)")
    sp.add_argument("--parent-dispatch", default=None,
                    help="부모 배분 id(이 배분을 낳은 배분) — 생략 시 계보 자동 판정. "
                         "--parent 는 채용의 부모 봇이라 이름을 가른다 (prj3#Issue739 M1-2)")
    sp.add_argument("--role", required=True, help="워커 role (카탈로그 등재값 — HR 게이트가 검증)")
    sp.add_argument("--cwd", default=os.getcwd(), help="대상 프로젝트 루트(기본 현재 디렉토리)")
    sp.add_argument("--bot-id", default=None, help="워커 bot_id 지정(생략 시 fbot-{role}-{issue} 자동)")
    sp.add_argument("--deferred-until", default=None, metavar="JOB_ID",
                    help="미룬 배분 — 채용·기동 없이 deferred 로 적고, sweep 이 선행 배분 JOB_ID 의 done 을 보고 open 으로 당긴다 (Issue861)")
    sp.add_argument("--loan-key", default=None,
                    help="차용 일 키 — 차용 기록(loan --key)과 이 값으로 대조한다(topic 에 범위 지시를 자유롭게 붙인다). "
                         "생략 시 키가 배분 식별자(topic·issue)의 접두면 통과 (Issue933)")
    sp.add_argument("--breaker-ack", default=None, metavar="JOB_ID",
                    help="연속 실패 서킷브레이커 해제 증적 — 원인 조사가 끝난 done 배분 id. 셈에 든 실패 id 를 issue/topic/"
                         "parent_dispatch_id 로 참조하고 가장 오래된 실패보다 뒤에 만든 것이어야 통과 (prj3#Issue952)")
    sp.add_argument("--dry-run", action="store_true",
                    help="가드 + 배치 판정(자리 개체·직능·차용·채용 사다리)까지만 — 게이트 호출·채용·기록 없음 (Issue933)")
    sp.add_argument("--by", default=BOT_ID,
                   help="배분자 bot_id (기본: 전역 팀장핀봇). prj PM 이 자기 이름으로 "
                        "배분하려면 지정 — 그래야 조직도에 총괄→PM→워커 체인이 그려진다")
    sp.add_argument("--requester-session", default=None,
                    help="워커 질문을 받을 사람 세션 id 를 명시 (생략 시 자동 판정 — Issue749 requester_of)")
    sp.add_argument("--request", default=None,
                    help="이 배분이 처리하는 인박스 요청 id(자기 앞 열린 요청) — sweep 이 배분을 닫으면 요청도 닫힌다 (prj3#Issue773)")
    sp.add_argument("--expect", action="append", default=None, metavar="PATH",
                    help="이 배분의 산출 경로(반복 가능, --cwd 기준) — sweep 은 전부 실재·배분 뒤 갱신일 때만 topic 배분을 "
                         "완료로 닫는다. 없으면 «완료 미확인» (prj3#Issue929)")
    sp.add_argument("--spawn", action="store_true",
                    help="next_step 이 fpm-do 면 이 호출에서 분리 실행까지 한다 — 별도 호출 불요 (prj3#Issue779_8)")
    sp.add_argument("--model", default=None,
                    help="이번 배분만 몸체 모델을 바꾼다 — 별칭(haiku·sonnet·opus). 생략 시 직능 기본값"
                         "(data/model-tier.yml). fable 은 허용 목록 밖이면 거부 (prj3#Issue849)")
    sp.set_defaults(func=cmd_dispatch)

    sp = sub.add_parser("spawn", help="open 배분 몸체 기동 — 승격된 미룬 배분(spawn_pending)·몸체 없는 배분 (prj3#Issue904)")
    g = sp.add_mutually_exclusive_group(required=True)
    g.add_argument("--job-id", default=None, help="배분 job id 한 건 — 배치 판정(dispatch 와 같음)·기동")
    g.add_argument("--pending", action="store_true", help="spawn_pending 표지 행 전부 — tick worker 가 sweep 뒤에 돈다")
    sp.add_argument("--by", default=os.environ.get("FBOT_ID", "") or BOT_ID, help="기동 주체 bot_id(이벤트 기록용)")
    sp.add_argument("--dry-run", action="store_true", help="대상 조회까지만 — 채용·기동 없음")
    sp.set_defaults(func=cmd_spawn)

    sp = sub.add_parser("watch", help="진행 감시 — 적체 2종 → 재시도 → 에스컬레이션(mq alert)")
    sp.add_argument("--cwd", default=None, help="지정 시 미배분 startable 적체(A)도 판정")
    sp.set_defaults(func=cmd_watch)

    sp = sub.add_parser("session-end", help="워커 마지막 세션의 종료 사유(quota·api_error·interrupted·normal) 조회 — fpm-do 감시용 (Issue743)")
    sp.add_argument("--worker", required=True, help="워커 bot_id")
    sp.add_argument("--since", type=int, default=0, help="이 시각(epoch 초) 이후 세션만")
    sp.set_defaults(func=cmd_session_end)

    sp = sub.add_parser("sweep", help="완료 감지 — 워커 퇴근+세션 done 배분을 done 처리 + 묶음 통지 1회")
    sp.add_argument("--dry-run", action="store_true", help="감지까지만 — 갱신·통지 없음")
    sp.set_defaults(func=cmd_sweep)

    sp = sub.add_parser("close", help="외부 증적으로 확정된 완료를 원장에 반영(prj3#Issue514 — sweep 이 못 닫는 건)")
    g = sp.add_mutually_exclusive_group(required=True)
    g.add_argument("--job-id", default=None, help="배분 job id 지정")
    g.add_argument("--issue", default=None, help="이슈 ID 로 지정")
    g.add_argument("--worker", default=None, help="워커 bot_id 로 지정")
    sp.add_argument("--evidence", required=True,
                    help="원장 밖 증적(필수) — 커밋 해시·리포트 경로·이슈 번호")
    sp.add_argument("--reason", default="", help="보충 설명(선택)")
    sp.add_argument("--by", default=os.environ.get("FBOT_ID", "human"), help="종결 주체(기본 $FBOT_ID)")
    sp.add_argument("--dry-run", action="store_true", help="대상 조회까지만 — 갱신 없음")
    sp.set_defaults(func=cmd_close)

    sp = sub.add_parser("cancel", help="배분 취소 — 무의미해진 배분을 사유와 함께 명시 종결(완료 아님)")
    g = sp.add_mutually_exclusive_group(required=True)
    g.add_argument("--job-id", default=None, help="배분 job id 지정")
    g.add_argument("--issue", default=None, help="이슈 ID 로 지정 (ex: Issue329 — 동일 이슈 전건)")
    sp.add_argument("--reason", required=True, help="취소 사유(필수) — 근거 없는 원장 정리 금지")
    sp.add_argument("--verdict", default="cancelled_obsolete", choices=CANCEL_VERDICTS,
                    help="판정 라벨(기본 cancelled_obsolete). gate_failed = 정상 게이트 차단 취소 — 서킷브레이커가 세지 않는다 (prj3#Issue952)")
    sp.add_argument("--reclaim", action="store_true",
                    help="회수 모드 — 이슈 완료면 done·미완료+워커 퇴근이면 blocked(worker_died) (prj3#Issue819, hub 원클릭은 기본)")
    sp.add_argument("--by", default=os.environ.get("FBOT_ID", "human"), help="취소 주체 bot_id(기본 $FBOT_ID)")
    sp.add_argument("--dry-run", action="store_true", help="대상 조회까지만 — 갱신 없음")
    sp.set_defaults(func=cmd_cancel)

    sp = sub.add_parser("reopen", help="거짓 종결 복구 — done·reaped 로 잘못 닫힌 배분을 open 으로 되돌린다 (Issue644·Issue693_1)")
    g = sp.add_mutually_exclusive_group(required=True)
    g.add_argument("--job-id", default=None, help="배분 job id 지정")
    g.add_argument("--issue", default=None, help="이슈 ID 로 지정 (동일 이슈 전건)")
    sp.add_argument("--reason", required=True, help="되살림 사유(필수) — 근거 없는 원장 되돌림 금지")
    sp.add_argument("--evidence", default=None,
                    help="커밋 해시 증적 — 있으면 cancelled 도 되살린다 (prj3#Issue819)")
    sp.add_argument("--by", default=os.environ.get("FBOT_ID", "human"), help="되살림 주체 bot_id(기본 $FBOT_ID)")
    sp.add_argument("--dry-run", action="store_true", help="대상 조회까지만 — 갱신 없음")
    sp.set_defaults(func=cmd_reopen)

    sp = sub.add_parser("defer", help="명시 보류 — open·blocked(unconfirmed) 배분을 deferred 로(WIP·정체 판정 제외, sweep 완료 아님) (Issue686·953)")
    g = sp.add_mutually_exclusive_group(required=True)
    g.add_argument("--job-id", default=None, help="배분 job id 지정")
    g.add_argument("--issue", default=None, help="이슈 ID 로 지정 (동일 이슈의 open 배분 전건)")
    sp.add_argument("--reason", required=True, help="보류 사유(필수) — 근거 없는 원장 변경 금지")
    sp.add_argument("--until", type=int, default=None, help="재개 예정 시각(epoch 초, 기록만 — 자동 재개 없음)")
    sp.add_argument("--by", default=os.environ.get("FBOT_ID", "human"), help="보류 주체 bot_id(기본 $FBOT_ID)")
    sp.add_argument("--dry-run", action="store_true", help="대상 조회까지만 — 갱신 없음")
    sp.set_defaults(func=cmd_defer)

    sp = sub.add_parser("resume", help="보류 재개 — deferred 배분을 open 으로(전역 동시 상한 판정) (Issue686)")
    g = sp.add_mutually_exclusive_group(required=True)
    g.add_argument("--job-id", default=None, help="배분 job id 지정")
    g.add_argument("--issue", default=None, help="이슈 ID 로 지정 (동일 이슈의 deferred 배분 전건)")
    sp.add_argument("--reason", default="", help="재개 사유(선택)")
    sp.add_argument("--by", default=os.environ.get("FBOT_ID", "human"), help="재개 주체 bot_id(기본 $FBOT_ID)")
    sp.add_argument("--dry-run", action="store_true", help="대상 조회까지만 — 갱신 없음")
    sp.set_defaults(func=cmd_resume)

    sp = sub.add_parser("solo", help="사람 승인 직접 수행 기록 — solo-approve 승인 id 필수 (prj3#Issue757 C)")
    sp.add_argument("--reason", required=True,
                    help="직접 수행 사유(필수·8자 이상) — 감사에서 읽히는 문장으로")
    sp.add_argument("--approved-by", dest="approved_by", default=None,
                    help="사람 세션이 solo-approve 로 남긴 승인 id (필수 — 그 봇 전용·1회·24시간)")
    sp.add_argument("--scope", default="", help="대상 요지(선택 — 어떤 작업을 직접 했는가)")
    sp.add_argument("--cwd", default=os.getcwd(), help="대상 프로젝트 루트(기본 현재 디렉토리)")
    sp.add_argument("--by", default=os.environ.get("FBOT_ID", "") or BOT_ID,
                    help="우회 주체 bot_id(기본 $FBOT_ID)")
    sp.set_defaults(func=cmd_solo)

    sp = sub.add_parser("loan", help="차용 기록 — 총괄이 다른 팀 개체를 요청 팀장에게 잇는다 (prj3#Issue757 T13)")
    sp.add_argument("--by", default=os.environ.get("FBOT_ID", ""), help="상비 총괄 bot_id(본인 세션)")
    sp.add_argument("--bot", required=True, help="빌려 줄 개체(다른 prj 의 비관리직)")
    sp.add_argument("--to", required=True, help="빌리는 팀장 bot_id")
    sp.add_argument("--consent", required=True, help="소유 팀장 동의 인박스 요청 id (accepted 응답)")
    sp.add_argument("--reason", required=True)
    sp.add_argument("--key", default="",
                    help="이 일 키에만 유효 — 배분 식별자(topic·issue)가 이 키로 시작하거나 dispatch --loan-key 가 같을 때 "
                         "(Issue933). 생략 시 만료까지 이 팀장의 배분 전부")
    sp.add_argument("--days", type=int, default=LOAN_DAYS_DEFAULT)
    sp.add_argument("--request", default=None, help="인력 요청 id — verdict=loan 으로 닫는다")
    sp.set_defaults(func=cmd_loan)

    sp = sub.add_parser("staff-create", help="생성 — 요청 prj 자리 추가 + HR 게이트 채용(parent=요청 팀장) (prj3#Issue757 T13)")
    sp.add_argument("--by", default=os.environ.get("FBOT_ID", ""))
    sp.add_argument("--prj", type=int, required=True)
    sp.add_argument("--role", required=True)
    sp.add_argument("--to", required=True, help="요청 팀장 bot_id(채용 parent)")
    sp.add_argument("--dept", default="dev")
    sp.add_argument("--request", default=None, help="인력 요청 id — verdict=created 로 닫는다")
    sp.set_defaults(func=cmd_staff_create)

    sp = sub.add_parser("solo-approve", help="사람의 직접 수행 승인 기록 — 사람 세션 전용 (prj3#Issue757 C)")
    sp.add_argument("--bot", required=True, help="승인 대상 bot_id (그 봇만 쓸 수 있다)")
    sp.add_argument("--reason", required=True, help="승인 사유(필수·8자 이상)")
    sp.set_defaults(func=cmd_solo_approve)

    sp = sub.add_parser("status", help="이번 달 배분 수·상한·활성 배분 목록 + 취소 집계(완료와 분리)")
    sp.set_defaults(func=cmd_status)

    sp = sub.add_parser("topic", help="배분 식별자(topic) 전문 조회 — 워커 프롬프트가 바이트 예산으로 잘렸을 때 (prj3#Issue786_1)")
    sp.add_argument("job_id", help="배분 id (fbotdisp-…)")
    sp.set_defaults(func=cmd_topic)

    sp = sub.add_parser("checkin-brief",
                        help="출근 훅 전용 — 잘린 배분 지시의 topic 전문·질문답 원문 절(없으면 빈 출력) (prj3#Issue931)")
    sp.add_argument("--bot-id", default=None, help="몸체 bot_id (생략 시 FBOT_ID)")
    sp.add_argument("--json", action="store_true", help="판정 결과(job_id·topic_cut·qa)까지 JSON 으로")
    sp.set_defaults(func=cmd_checkin_brief)

    sp = sub.add_parser("brief", help="봇 기준 한 번에 30줄 — 나·내가 낸 배분·내게 온 배분·인박스·완료 감지 (prj3#Issue779_7)")
    sp.add_argument("--bot", default=None, help="bot_id (생략 시 FBOT_ID, 그것도 없으면 조직 요약)")
    sp.set_defaults(func=cmd_brief)

    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except Reject as e:
        print(str(e), file=sys.stderr)
        return 1
    except FbotError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 2
    except sqlite3.Error as e:
        print(f"❌ DB 오류: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
