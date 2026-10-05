#!/usr/bin/env python3
"""decision-question.py — «사람에게 결정을 묻는 평문 질문» 판정 단일 지점 (prj3#Issue749)

⚠️ 글로벌 SCAR 변경 가드 (Issue46): 본 파일은 모든 프로젝트가 공유. cwd ≠ ~/.claude 면
  즉시 수정 금지 → ~/.claude/Issue.md 이슈 등록 후 처리. 설계 SSOT: ~/.claude/_doc_arch/fbot-manager.md
  «§질문 상향 중계» · 절차: ~/.claude/rules/global-scar-change-rules.md

소비처 두 곳이 **같은 판정**을 쓴다 — 복제하면 한쪽만 갱신돼 갈라진다(장애 대응 원칙 «판정 단일 지점»).
  ① `hooks/fpm-ask-question-guard.sh` (Stop) — hub on 폴더의 사람 세션이 평문으로 물으면 AskUserQuestion 재호출 지시
  ② `hooks/fbot-inbox.py defer` — pm-do `-p` 봇 몸체의 마지막 말이 질문이면 `kind=question` 으로 의뢰 세션에 중계

판정(보수적 — 오탐 회피, Issue72 휴리스틱 승계):
  anchor: `?` 가 있고 결정 요청 문구가 있어야 한다
  + 둘 중 하나: (A) 선택지 2~4개 — 줄머리 번호·문자·bullet **또는 한 줄 안 `1) … 2) …`** (Issue749 추가 —
      봇 몸체는 선택지를 한 줄에 쓰는 일이 잦다: 재현 원문 «어느 쪽으로 할까? 1) 메모리 2) 디스크 — 선택해 주면…»)
    (B) 짧은 응답(≤800자) + `?` 종결
  code fence 안은 제외 · hub Mode D 마커가 있으면 폼이 정당 처리하므로 질문 아님

CLI:
  decision-question.py --transcript <jsonl>   # 질문이면 FIRE 출력(가드용)
  decision-question.py --text "<본문>" --json  # {"question":…, "signal":…, "options":[…]}
"""
import json
import os
import re
import sys

MODE_D_MARKER = "htm-form:auto:v1:BEGIN"
SHORT_MAX = 800

# 결정 요청 문구 (anchor). hub 선택지 자동 승격 조건 3 + binary confirm 보강 (Issue72) + 봇 몸체 표현 (Issue749)
DECISION_PHRASES = (
    "선택해", "선택하세요", "선택할", "어느 옵션", "어느 쪽", "어느 것",
    "어떤 방식", "어떤 걸", "어떤 것", "골라", "번호로", "둘 중", "중 선택",
    "y/n", "yes/no", "a/b", "진행할까", "커밋할까", "할까요", "할까?",
    "할까 ", "하시겠", "어떻게 할까", "계속할까", "적용할까", "만들까",
    # Issue749 — 봇이 판단을 사람에게 넘기는 표현
    "확인이 필요", "정해 주", "결정해 주", "알려 주", "알려주",
)

_LINE_OPT = re.compile(r"(?m)^\s*(?:\d+[.)]|[A-Da-d][.)]|[-*])\s+(\S.*)$")
# 한 줄 안 번호 선택지 — `1)` 형만 본다(`1.` 은 버전·문장 번호와 겹친다)
_INLINE_OPT = re.compile(r"(?:(?<=\s)|^)([1-9])\)\s*")


def last_assistant_text(path):
    """transcript JSONL 의 마지막 assistant 텍스트(텍스트 블록 결합, 도구·thinking 제외). 없으면 ""."""
    last = ""
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            for ln in f:
                if '"assistant"' not in ln:
                    continue
                try:
                    d = json.loads(ln)
                except ValueError:
                    continue
                if d.get("type") != "assistant":
                    continue
                c = (d.get("message") or {}).get("content")
                if isinstance(c, str):
                    txt = c.strip()
                elif isinstance(c, list):
                    txt = "\n".join((b.get("text") or "") for b in c
                                    if isinstance(b, dict) and b.get("type") == "text").strip()
                else:
                    txt = ""
                if txt:
                    last = txt
    except OSError:
        return ""
    return last


def _inline_options(text):
    """한 줄 안 `1) A 2) B` — 1부터 연속 번호 2~4개일 때만 선택지로 본다."""
    for line in text.splitlines():
        ms = list(_INLINE_OPT.finditer(line))
        if len(ms) < 2:
            continue
        nums = [int(m.group(1)) for m in ms]
        if nums != list(range(1, len(nums) + 1)) or not 2 <= len(nums) <= 4:
            continue
        opts = []
        for i, m in enumerate(ms):
            end = ms[i + 1].start() if i + 1 < len(ms) else len(line)
            seg = line[m.end():end]
            seg = re.split(r"\s[—–-]\s|[.?？,]\s|[.?？]$", seg, maxsplit=1)[0]
            opts.append(seg.strip())
        if all(opts):
            return opts
    return []


def judge(text):
    """반환 `{"question": bool, "signal": "strong"|"binary"|"", "options": [...]}`."""
    out = {"question": False, "signal": "", "options": []}
    stripped = (text or "").strip()
    if not stripped or MODE_D_MARKER in stripped:
        return out
    analysis = re.sub(r"```.*?```", "", stripped, flags=re.DOTALL)
    if "?" not in analysis and "？" not in analysis:
        return out
    low = analysis.lower()
    if not any(p in low for p in DECISION_PHRASES):
        return out
    line_opts = [m.group(1).strip() for m in _LINE_OPT.finditer(analysis)]
    opts = line_opts if 2 <= len(line_opts) <= 4 else _inline_options(analysis)
    if opts:
        out.update(question=True, signal="strong", options=opts)
        return out
    if re.search("[?？]\\s*$", analysis.rstrip()) and len(stripped) <= SHORT_MAX:
        out.update(question=True, signal="binary")
    return out


SHADOW_TAIL = 800   # Jev 에 보내는 끝 부분 — 결정 질문은 응답 끝에 있다


def shadow(text, verdict=None):
    """Jev shadow 판정(prj3#Issue863_11) — `?` 가 있는 응답만 분리 프로세스로 띄우고 바로 돌아온다(Stop 을 기다리게 하지 않는다).

    판정은 바뀌지 않는다 — static 은 이 모듈의 휴리스틱 결과(yes/no)이고 Jev 는 원장 기록만 남긴다(kind `reply.decision_question`).
    키워드 밖 결정 질문(미탐)·설명형 `?` 종결(오탐)을 실측해 enforce 를 판정하는 재료다. 어떤 실패도 호출자를 막지 않는다."""
    try:
        stripped = (text or "").strip()
        if not stripped or MODE_D_MARKER in stripped:
            return False
        analysis = re.sub(r"```.*?```", "", stripped, flags=re.DOTALL)
        if "?" not in analysis and "？" not in analysis:
            return False
        if verdict is None:
            verdict = judge(text)
        import importlib.util
        here = os.path.dirname(os.path.realpath(__file__))
        spec = importlib.util.spec_from_file_location("_dq_selection", os.path.join(here, "selection.py"))
        sel = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sel)
        return sel.spawn_shadow("reply.decision_question", analysis.strip()[-SHADOW_TAIL:],
                                static="yes" if verdict.get("question") else "no")
    except Exception:
        return False


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="평문 결정 질문 판정 (Issue749 단일 지점)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--transcript")
    g.add_argument("--text")
    ap.add_argument("--json", action="store_true", help="판정 전체를 JSON 으로")
    a = ap.parse_args(argv)
    text = a.text if a.text is not None else (
        last_assistant_text(a.transcript) if a.transcript and os.path.exists(a.transcript) else "")
    v = judge(text)
    shadow(text, v)          # prj3#Issue863_11 — 분리 기동, 판정 불변
    if a.json:
        print(json.dumps(v, ensure_ascii=False))
    elif v["question"]:
        print("FIRE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
