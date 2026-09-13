"""LLM 판독 계층 (V5) — 규칙이 못 가른 것만 LLM 에게 묻는다.

V4 와 V5 의 차이는 이 파일 하나다. 나머지 구조는 같다.

    V4:  CPC 국제분류 + 특징 용어 규칙          (무료·결정적·설명 가능)
    V5:  위 규칙 + 애매한 것만 LLM 재판독       (유료·문맥 이해)

왜 '전부' LLM 에 안 맡기는가
  근거가 42,000건이다. 전부 보내면 돈도 시간도 크게 든다. 그리고 그럴 필요가 없다.
  CPC 가 딱 맞고 용어도 맞는 건('확정') 이미 답이 정해져 있다. LLM 을 불러도 같은
  답이 나온다. 정말 판단이 필요한 건 CPC 는 맞는데 용어가 안 맞거나('관련'),
  아무 데도 안 붙은 것('미배정')이다. 거기만 보낸다.

  실측(2026-09-13) 기준 42,071건 중 LLM 이 필요한 건 약 31,000건이고,
  그중에서도 기술과 무관한 게 대부분이라 1차 걸러내면 크게 줄어든다.

키가 없으면
  규칙 판독 결과를 그대로 돌려주고 status() 가 '미연결'을 알린다.
  화면은 그 상태를 숨기지 않고 '규칙 판독만 적용됨'이라고 적는다.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline import classifier as rule  # noqa: E402
from server import cache  # noqa: E402

log = logging.getLogger("classifier_llm")

MODEL = os.environ.get("CTI_LLM_MODEL", "claude-sonnet-5")
MAX_ITEMS = int(os.environ.get("CTI_LLM_MAX_ITEMS", "4000"))
BATCH = 20

# LLM 에게 넘길 대상. '확정'은 이미 답이 정해져 있어 보내지 않는다.
ASK_CONF = {"관련", "미배정"}

_asked = 0


def status() -> dict:
    """키 유무만 본다. 값은 어디에도 싣지 않는다."""
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        return {"ready": False, "mode": "규칙 판독만",
                "reason": "ANTHROPIC_API_KEY 미설정 — .env 에 넣으면 LLM 재판독이 켜집니다."}
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return {"ready": False, "mode": "규칙 판독만",
                "reason": "anthropic 패키지 없음 — pip install anthropic"}
    return {"ready": True, "mode": f"규칙 + LLM 재판독 ({MODEL})", "reason": ""}


def _key(ev: dict) -> str:
    raw = (ev.get("ref", "") or "") + "|" + (ev.get("summary", "") or "")
    return "llm:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


PROMPT = """당신은 배터리 공정기술 분석가입니다.
아래 특허·공시·논문이 어느 공정기술에 속하는지 판별하십시오.

기술 목록(이 중 하나만 고르거나, 해당 없으면 NONE):
{nodes}

판별 규칙:
- 그 기술을 실제로 다루는 문서일 때만 고르십시오.
- 단어가 겹친다는 이유로 고르지 마십시오.
- 애매하면 NONE 을 고르십시오. 억지로 배정하지 마십시오.

문서:
{docs}

각 문서마다 한 줄씩, 다음 형식으로만 답하십시오. 다른 말은 쓰지 마십시오.
<번호>|<기술 이름 또는 NONE>|<확신도 0~100>|<20자 이내 근거>"""


def _ask(client, items: list[tuple[int, dict]], node_names: list[str]) -> dict:
    """LLM 에 한 묶음을 묻는다. {원본 index: (name, conf, why)}."""
    docs = "\n".join(
        f"{i+1}. {(ev.get('ref') or '')[:90]} / {(ev.get('summary') or '')[:220]}"
        for i, (_, ev) in enumerate(items))
    msg = PROMPT.format(nodes="\n".join(f"- {n}" for n in node_names), docs=docs)
    try:
        r = client.messages.create(
            model=MODEL, max_tokens=1500,
            messages=[{"role": "user", "content": msg}])
        text = "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
    except Exception as e:
        log.warning("LLM 호출 실패: %s %s", type(e).__name__, str(e)[:90])
        return {}

    valid = set(node_names)
    out = {}
    for line in text.splitlines():
        m = re.match(r"\s*(\d+)\s*\|\s*([^|]+?)\s*\|\s*(\d+)\s*\|\s*(.*)", line)
        if not m:
            continue
        pos = int(m.group(1)) - 1
        name, conf, why = m.group(2).strip(), int(m.group(3)), m.group(4).strip()
        if pos < 0 or pos >= len(items):
            continue
        if name.upper() == "NONE" or name not in valid:
            continue
        out[items[pos][0]] = (name, conf, why)
    return out


def classify_all(evidence: list[dict], node_names: list[str]) -> list[tuple]:
    """근거 전체를 판독한다. 규칙을 먼저 돌리고, 애매한 것만 LLM 에 묻는다.

    반환은 classifier.classify 와 같은 (name, conf, score, why) 의 목록이다.
    """
    global _asked
    base = [rule.classify(ev, node_names) for ev in evidence]

    st = status()
    if not st["ready"]:
        log.info("LLM 미연결 — 규칙 판독만 적용 (%s)", st["reason"])
        return base

    import anthropic
    client = anthropic.Anthropic()

    # 물어볼 것만 고른다. 텍스트가 너무 짧으면 물어도 답이 안 나온다.
    todo = [(i, ev) for i, (ev, (_, conf, _, _)) in enumerate(zip(evidence, base))
            if conf in ASK_CONF and len((ev.get("summary") or "")) > 40]
    log.info("LLM 재판독 대상 %d건 / 전체 %d건", len(todo), len(evidence))
    todo = todo[:MAX_ITEMS]

    pending = []
    for i, ev in todo:
        hit = cache.get(_key(ev), ttl=0)
        if hit is not None:
            if hit:
                base[i] = (hit[0], "확정(LLM)", float(hit[1]), "LLM: " + hit[2])
            continue
        pending.append((i, ev))

    for b in range(0, len(pending), BATCH):
        chunk = pending[b:b + BATCH]
        got = _ask(client, chunk, node_names)
        _asked += 1
        for i, ev in chunk:
            r = got.get(i)
            cache.put(_key(ev), list(r) if r else [])
            if r:
                base[i] = (r[0], "확정(LLM)", float(r[1]), "LLM: " + r[2])
        if (b // BATCH) % 10 == 0:
            log.info("  LLM 판독 %d/%d", b, len(pending))

    return base


def stats_header() -> str:
    st = status()
    if not st["ready"]:
        return rule.stats_header() + f"  (LLM 미연결: {st['reason']})"
    return (f"판독 근거: CPC/IPC 국제분류 + 특징 용어로 1차 판독한 뒤, "
            f"규칙이 가르지 못한 건만 {MODEL} 가 문맥을 읽고 재판독한다. "
            f"LLM 호출 {_asked}회.")
