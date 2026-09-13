"""판정 기준 — 기술 구분 · TRL · 근거 등급 · 기술 격차 · 시급도.

이 파일이 다섯 기준의 **유일한 근거**다. 화면의 설명 팝업도 여기서 생성한 JSON 을 읽는다.
기준을 바꾸려면 여기만 고치면 화면 설명까지 같이 바뀐다.

[V6 개정 배경 — 제한된 데이터 환경 대응]
경쟁사 실제 수율·제조원가·양산 실적은 확보 불가함. 확보 가능 데이터는 특허·설비투자
공시·대외 기술발표 3종에 한정됨. V5 까지의 기준은 아래 3개 취약점을 내포하였음.

  취약점 1. 특허 단순 건수 집계 — 방어용 출원과 사업화 특허를 미구분함.
           동일 발명의 국가별 중복 계상으로 다국 출원 기업이 약 2배 과대 산출됨.
           → 패밀리 병합 및 품질 가중(국가 수·등록 여부·최신성) 적용함.

  취약점 2. 발표·공시 액면가 수용 — Tech Day 발표 1건으로 TRL 7(파일럿 가동) 부여됨.
           마케팅성 과장 및 일정 지연 미반영, 경과 기간 무관하게 동일 가중 적용됨.
           → 특허 교차 검증 요건 및 신호 소멸 규칙 신설, 보정 계수 적용함.

  취약점 3. 단일 점추정 제시 — 신뢰구간 부재로 '왜 N년인가' 방어 불가함.
           → 기준/보수 듀얼 트랙 및 신뢰도 등급 병행 제시함.

설계 원칙
  1. 관측 가능한 것만 사용함. 추측을 숫자로 변환하지 않음.
  2. 모든 숫자는 산출 근거를 1줄로 제시 가능해야 함.
  3. 근거 미확보 시 등급 하향이 아닌 '확인 필요'로 표기함.
"""
from __future__ import annotations

from pipeline import gap_model

GRADE_RANK = {"verified": 4, "strong": 3, "medium": 2, "weak": 1}
GRADE_LABEL = {"verified": "VERIFIED", "strong": "STRONG",
               "medium": "MEDIUM", "weak": "WEAK"}

PATENT_TYPES = ("patent",)
TALK_TYPES = ("paper", "talk", "conference")

# ── 근거 등급 — 유효 근거 산정 ───────────────────────────────────────
# V5 까지는 수집 건수를 그대로 셌다. 그 결과 두 가지가 섞였다.
#   · 같은 발명을 6개국에 낸 것이 6건으로 집계됨(실측 중복률 1.92배).
#   · 2019년 발표 1건과 2026년 양산 착공이 동일 가중으로 집계됨.
# V6 는 '유효 근거'를 따로 산정한다. 패밀리 1건 = 1표, 경과 기간은 반감기로 감산한다.
SIGNAL_DECAY_YEARS = 4.0   # 후속 관측 없는 발표·공시는 이 기간 경과 시 신호 소멸로 간주함


def effective_evidence(evs: list[dict], today: float | None = None) -> dict:
    """판정에 실제 사용하는 근거 내역을 산정함.

    반환 — records(원본 건수) · families(패밀리 병합 건수) · counts(등급별 유효 건수)
           · kinds(소스 종류 수) · quality(다국·등록 건수) · fresh(최신 신호 유무)
    """
    pats = [e for e in evs if e.get("type") in PATENT_TYPES]
    others = [e for e in evs if e.get("type") not in PATENT_TYPES]
    fams = gap_model.merge_families(pats)

    counts = {g: 0 for g in GRADE_RANK}
    for f in fams:
        counts[f.get("grade") or "weak"] = counts.get(f.get("grade") or "weak", 0) + 1

    # 발표·공시는 경과 기간을 본다. 신호가 소멸한 건은 등급을 1단계 내린다.
    stale = 0
    for e in others:
        g = e.get("grade") or "weak"
        w = gap_model.recency_weight(e.get("date") or "", today)
        if w < 0.5 ** (SIGNAL_DECAY_YEARS / gap_model.HALFLIFE_YEARS):
            stale += 1
            g = {"verified": "strong", "strong": "medium",
                 "medium": "weak", "weak": "weak"}[g]
        counts[g] = counts.get(g, 0) + 1

    multi = sum(1 for f in fams if int(f.get("_countries") or 1) >= 2)
    granted = sum(1 for f in fams if f.get("granted"))
    kinds = len({e.get("type") for e in evs if e.get("type")})
    return {"records": len(evs), "families": len(fams), "counts": counts,
            "kinds": kinds, "multi_country": multi, "granted": granted,
            "patent_families": len(fams), "stale": stale,
            "has_patent": bool(fams), "talks": len([e for e in others
                                                    if e.get("type") in TALK_TYPES]),
            "capex": len([e for e in others if e.get("type") == "capex"])}


# ── TRL ─────────────────────────────────────────────────────────────
# 경쟁사가 '어디까지 갔는가'를 관측된 근거로만 추정한다.
# 임원 보고 기준: 숫자 하나하나가 어떤 관측에서 나왔는지 제시 가능해야 한다.
TRL_RULES = [
    (9, "양산 적용",      "양산 가동 확인(VERIFIED) 및 이종 소스 2종 이상 교차 검증"),
    (8, "양산 준비",      "양산 가동 확인(VERIFIED) 1건 또는 착공·양산일정(STRONG) 2건 이상"),
    (7, "파일럿 가동",    "파일럿 신설·착공 또는 양산일정 공식 발표(STRONG) 1건 "
                          "＋ 동일 기술 특허 패밀리 병행 관측"),
    (6, "실증 완료",      "등록특허 공정조건 또는 기술세션 발표(MEDIUM) 2건 이상"),
    (5, "요소기술 확보",  "등록특허 공정조건 또는 기술세션 발표(MEDIUM) 1건"),
    (4, "출원 단계",      "공개특허(WEAK) 단독 관측"),
    (3, "미관측",        "근거 미확보 — 부재가 아닌 미확인 상태"),
]
TRL_CROSS_SOURCE_MIN = 8   # 이 값 이상은 서로 다른 소스 2종이 교차해야 부여함
TRL_PATENT_BACKED_MIN = 7  # 이 값 이상은 특허 패밀리 병행 관측이 있어야 부여함


def estimate_trl(evidence: list[dict], today: float | None = None) -> tuple[int, str]:
    """(TRL, 근거 1줄). 유효 근거 기준으로 산정하며 2개 상한 규칙을 적용함."""
    if not evidence:
        return 3, "근거 0건 — 미관측"
    eff = effective_evidence(evidence, today)
    n, kinds = eff["counts"], eff["kinds"]

    if n["verified"] >= 1 and kinds >= 2:
        trl = 9
    elif n["verified"] >= 1 or n["strong"] >= 2:
        trl = 8
    elif n["strong"] >= 1:
        trl = 7
    elif n["medium"] >= 2:
        trl = 6
    elif n["medium"] >= 1:
        trl = 5
    else:
        trl = 4

    caps = []
    # 상한 1 — 교차 검증. 단일 소스로는 8 이상을 부여하지 않음.
    if trl >= TRL_CROSS_SOURCE_MIN and kinds < 2:
        trl, _ = 7, caps.append("단일 소스 사유 TRL 7 상한")
    # 상한 2 — 마케팅성 발표 방어. 특허 뒷받침 없는 발표·공시만으로
    #          '파일럿 가동' 이상을 부여하지 않음. V6 신설 규칙임.
    if trl >= TRL_PATENT_BACKED_MIN and not eff["has_patent"]:
        trl, _ = 6, caps.append("특허 미관측 사유 TRL 6 상한(발표 단독 판정 배제)")

    parts = [f"{GRADE_LABEL[g]} {n[g]}건" for g in
             ("verified", "strong", "medium", "weak") if n.get(g)]
    why = " · ".join(parts) + f" · 소스 {kinds}종"
    if eff["records"] != eff["families"] + eff["capex"] + eff["talks"]:
        why += f" · 패밀리 병합 {eff['records']}→{eff['families']}건"
    if eff["stale"]:
        why += f" · 신호 소멸 {eff['stale']}건 등급 하향"
    if caps:
        why += " → " + " / ".join(caps) + " 적용"
    return trl, why


# ── 자사 TRL ─────────────────────────────────────────────────────────
SELF_TRL = {
    "have": (9, "전 라인 양산 적용"),
    "part": (7, "파일럿·일부 라인 적용"),
}


def self_trl(self_info: dict) -> tuple[int, str]:
    st = (self_info or {}).get("status", "none")
    if st in SELF_TRL:
        return SELF_TRL[st]
    pat = int((self_info or {}).get("pat") or 0)
    if st == "unknown":
        # 신규 편입 기술 — 보유 현황 미확인. '미착수'로 단정하지 않는다.
        # 단정하면 없는 격차가 생기고, 그 격차가 우선순위를 왜곡한다.
        return 4, "자사 보유 현황 미확인 — 생산기술혁신센터 확인 필요"
    if pat > 0:
        return 4, f"관련 출원 {pat}건 — 착수 확인, 라인 적용 실적 없음"
    return 3, "4개 채널 전량 0건 — 미착수"


# ── 기술 격차 ────────────────────────────────────────────────────────
# 격차는 두 층으로 나눈다.
#   ① 실행 소요기간 — 자사가 경쟁사 수준에 도달하기 위해 수행해야 할 과업의 누적 기간.
#   ② 3축 관측 보정 — 특허·공시·발표에서 관측된 선행 정도로 ①을 조정한 값.
# 임원이 묻는 것은 "왜 N년인가"다. ①은 과업으로, ②는 관측 근거로 답한다.
TRL_STEPS = [
    (3, 4, 1.0,  "미착수 → 출원 단계",
     "선행기술 조사 및 개념 검증. 요소기술 탐색과 출원 준비에 기간 소요."),
    (4, 5, 0.5,  "요소기술 확보 → 실증",
     "랩 스케일 공정조건 도출 및 재현. 신규 설비 투자 미수반으로 최단 소요."),
    (5, 6, 0.75, "실증 → 검증 완료",
     "파일럿 설비 임차·개조를 통한 조건 재현. 설비 확보 기간 소요."),
    (6, 7, 1.0,  "검증 → 파일럿 가동",
     "전용 설비 발주 필요. 코터·프레스 등 핵심 설비 납기 6~12개월 소요."),
    (7, 8, 1.25, "파일럿 → 양산 준비",
     "양산 라인 개조 및 수율 안정화. 라인 정지에 따른 생산 손실 수반."),
    (8, 9, 1.5,  "양산 준비 → 전 라인 양산",
     "전 공장 확대 적용 및 고객 품질 승인. 승인 절차만 6개월 이상 소요."),
]
TRL_STEP_YEARS = {a: y for a, _, y, _, _ in TRL_STEPS}
TRL_STEP_WHY = {a: (nm, why) for a, _, _, nm, why in TRL_STEPS}

LAG_METHOD = ("경쟁사 도달 수준까지의 자사 소요기간 산정치임. 단계별 수행 과업 상이로 "
              "소요기간 차등 적용함. 산정치에 특허·공시·발표 3축 관측 보정을 적용하여 "
              "기준/보수 듀얼 트랙으로 제시함. 경쟁사 수율·원가는 비공개로 미반영함.")


def execution_years(rival_trl: int, our_trl: int) -> tuple[float, str]:
    """(실행 소요기간, 산출식). 자사가 수행해야 할 과업의 누적 기간임."""
    if rival_trl <= our_trl:
        return 0.0, "격차 없음 — 자사 동일 또는 선행"
    steps, total = [], 0.0
    for t in range(our_trl, rival_trl):
        y = TRL_STEP_YEARS.get(t, 1.0)
        total += y
        steps.append(f"TRL{t}→{t+1} {y}년")
    return round(total, 1), " + ".join(steps) + f" = {round(total, 1)}년"


# 하위 호환 — V5 까지 사용하던 이름임.
time_gap = execution_years


def gap_breakdown(rival_trl: int, our_trl: int) -> list[dict]:
    """격차를 단계별 수행 과업으로 분해함.

    '2단계 차이로 1.75년'은 의사결정에 기여하지 않음.
    '코터 발주·입고 1년, 라인 정지 수율 안정화 9개월'로 제시해야 함.
    """
    if rival_trl <= our_trl:
        return []
    out = []
    for t in range(our_trl, rival_trl):
        name, why = TRL_STEP_WHY.get(t, ("", ""))
        out.append({"from": t, "to": t + 1, "years": TRL_STEP_YEARS.get(t, 1.0),
                    "name": name, "why": why})
    return out


def fmt_gap(years: float) -> str:
    return "—" if years <= 0 else f"약 {years:g}년"


def fmt_band(base: float, cons: float) -> str:
    """'약 2.5~3.4년' — 듀얼 트랙을 화면에 그대로 쓰는 1줄임."""
    if base <= 0 and cons <= 0:
        return "—"
    if abs(cons - base) < 0.05:
        return f"약 {base:g}년"
    return f"약 {base:g}~{cons:g}년"


# ── 시급도 ───────────────────────────────────────────────────────────
#      시급도 = 기술 격차 × 경쟁사 확산도 × 근거 확실성
#                 (1~5)      (1~5)          (1~5)          → 최대 125점
#
# 곱셈 적용 사유: 3개 인자 중 1개라도 낮으면 대응 우선순위에서 제외되어야 함.
# 격차가 크더라도 경쟁사 1개사 보유 및 공개특허 수준 근거에 그칠 경우 즉시 대응 대상 아님.
#
# V6 개정 — 3개 인자의 입력값을 전량 품질 보정분으로 교체함.
#   · 격차   : TRL 단순 차이 → 3축 보정 기준 시나리오 연수
#   · 확산도 : 보유 경쟁사 수 → 패밀리 병합·품질 가중 통과 경쟁사 수
#   · 확실성 : 최상위 등급 → 최상위 등급 × 모델 신뢰도 등급
URGENCY_MAX = 125

URGENCY_FACTORS = [
    ("gap", "기술 격차", "3축 보정 기준 시나리오 연수", [
        (1, "격차 없음"), (2, "1년 미만"), (3, "1~2년"),
        (4, "2~3.5년"), (5, "3.5년 초과")]),
    ("spread", "경쟁사 확산도", "품질 기준 통과 보유 경쟁사 수", [
        (1, "0개사"), (2, "1개사"), (3, "2개사"), (4, "3~4개사"), (5, "5개사 이상")]),
    ("proof", "근거 확실성", "최상위 근거 등급 × 모델 신뢰도", [
        (1, "미관측 또는 신뢰도 '하'"), (2, "WEAK — 공개특허"),
        (3, "MEDIUM — 등록특허·기술발표"), (4, "STRONG — 착공·양산일정"),
        (5, "VERIFIED — 양산 가동 확인 ＋ 신뢰도 '상'")]),
]

# 신뢰도 등급별 근거 확실성 상한. 신뢰도 '하'인 판정에 5점을 부여하지 않는다.
CONF_PROOF_CAP = {"high": 5, "mid": 4, "low": 2}


def _score_gap_years(years: float) -> int:
    if years <= 0:
        return 1
    if years < 1.0:
        return 2
    if years < 2.0:
        return 3
    if years < 3.5:
        return 4
    return 5


def _score_gap(d: int) -> int:
    """하위 호환 — TRL 단계 차이 기반 산정식임."""
    return 1 if d <= 0 else min(5, d + 1)


def _score_spread(rivals_have: int, rivals_part: int) -> int:
    n = rivals_have + 0.5 * rivals_part
    if n <= 0:
        return 1
    if n < 2:
        return 2
    if n < 3:
        return 3
    if n < 5:
        return 4
    return 5


def _score_proof(top_grade: str | None, conf: str = "high") -> int:
    base = {"": 1, "weak": 2, "medium": 3, "strong": 4, "verified": 5}.get(
        top_grade or "", 1)
    return min(base, CONF_PROOF_CAP.get(conf, 5))


def urgency(rival_trl: int, our_trl: int, rivals_have: int, rivals_part: int,
            top_grade: str | None, recent_count: int, self_info: dict,
            total_rivals: int = 6, gap_years: float | None = None,
            conf: str = "high") -> tuple[int, list[dict]]:
    """(시급도 0~125, 3개 인자 내역). 3개 인자의 곱이 그대로 점수임."""
    d = max(0, rival_trl - our_trl)
    years = gap_years if gap_years is not None else execution_years(rival_trl, our_trl)[0]
    g = _score_gap_years(years)
    s = _score_spread(rivals_have, rivals_part)
    p = _score_proof(top_grade, conf)

    conf_ko = gap_model.CONF_LABEL.get(conf, "중")
    rows = [
        {"k": "gap", "label": "기술 격차", "got": g, "max": 5,
         "why": f"3축 보정 기준 {years:g}년 · 자사 TRL {our_trl} → 경쟁사 {rival_trl}"
                f"({d}단계)"},
        {"k": "spread", "label": "경쟁사 확산도", "got": s, "max": 5,
         "why": f"보유 {rivals_have}개사 · 일부 보유 {rivals_part}개사 "
                f"(패밀리 병합·품질 가중 적용분)"},
        {"k": "proof", "label": "근거 확실성", "got": p, "max": 5,
         "why": (f"{GRADE_LABEL[top_grade] if top_grade else '미관측'} · "
                 f"모델 신뢰도 '{conf_ko}'"
                 + (f" → {CONF_PROOF_CAP[conf]}점 상한 적용"
                    if top_grade and _score_proof(top_grade, "high") > p else ""))},
    ]
    return g * s * p, rows


def urgency_formula(rows: list[dict]) -> str:
    """'4 × 3 × 5 = 60' — 화면에 그대로 쓰는 1줄임."""
    if not rows:
        return ""
    vals = [r["got"] for r in rows]
    total = 1
    for v in vals:
        total *= v
    return " × ".join(str(v) for v in vals) + f" = {total}"


# ── 보유 판정 ────────────────────────────────────────────────────────
# V5 까지는 공개특허 3건이면 '보유'였다. 같은 발명을 3개국에 낸 것도 3건으로 집계되어,
# 방어용 출원 1건이 '보유'로 판정되는 사례가 발생하였음.
# V6 는 패밀리 병합 후 품질 요건을 추가함.
HOLD_RULE = ("패밀리 병합 후 판정함. VERIFIED·STRONG 1건, MEDIUM 2건, 또는 "
             "WEAK 3건 이상 충족 시 '보유' 판정함. 단, WEAK 단독 충족 시 "
             "다국 출원 또는 등록 특허 1건 이상을 추가 요건으로 적용함.")


def rival_holds(evidence: list[dict], today: float | None = None) -> bool:
    """'보유' 판정. 방어용 단일국 공개출원 누적만으로는 보유로 인정하지 않음."""
    if not evidence:
        return False
    eff = effective_evidence(evidence, today)
    n = eff["counts"]
    if n.get("verified", 0) >= 1 or n.get("strong", 0) >= 1:
        return True
    if n.get("medium", 0) >= 2:
        return True
    if n.get("weak", 0) >= 3:
        # 품질 요건 — 다국 출원 또는 등록 이력이 있어야 사업화 의지로 인정함.
        return eff["multi_country"] >= 1 or eff["granted"] >= 1
    return False


def criteria_doc() -> dict:
    """화면 팝업이 읽는 기준 설명. 코드와 설명이 어긋나지 않도록 여기서 생성함."""
    return {
        "model": gap_model.MODEL_DOC,
        "trl": {
            "title": "TRL 산정 기준",
            "intro": "경쟁사 도달 수준은 관측 근거에 한정하여 추정함. 추정치 임의 부여 "
                     "배제함. 판정의 핵심 기준은 특허이며, 설비투자 공시·기술발표는 "
                     "보조 근거로 교차 검증에 한정 적용함.",
            "rows": [{"level": lv, "name": nm, "rule": rl} for lv, nm, rl in TRL_RULES],
            "note": f"상한 2종 적용함. ① TRL {TRL_CROSS_SOURCE_MIN} 이상은 특허·"
                    "설비투자·기술발표 중 이종 2종 교차 검증 시에만 부여하며, 단일 "
                    f"소스 시 TRL 7 상한 적용함. ② TRL {TRL_PATENT_BACKED_MIN} 이상은 "
                    "동일 기술 특허 패밀리 병행 관측을 요건으로 하며, 발표·공시 단독 "
                    "관측 시 TRL 6 상한 적용함(마케팅성 발표 단독 판정 배제 목적). "
                    f"후속 관측 없이 {SIGNAL_DECAY_YEARS:g}년 경과한 발표·공시는 "
                    "등급 1단계 하향 적용함.",
        },
        "lag": {
            "title": "기술 격차 산정 기준",
            "intro": LAG_METHOD,
            # 소요기간이 긴 단계부터 제시함. 가장 무거운 단계를 먼저 보여야 한다.
            "rows": [{"level": f"{y}년", "name": nm, "rule": why}
                     for _, _, y, nm, why in sorted(TRL_STEPS, key=lambda r: -r[2])],
            "note": "자사 단계 산정 기준 — 전 라인 적용 9 · 파일럿 7 · 출원 단독 4 · "
                    "미착수 3. 소요기간은 배터리 공정기술 통상치 적용분이며, 사내 실적 "
                    "데이터 확보 시 해당 값으로 대체 적용 예정임. 기준 시나리오는 "
                    f"발표·공시에 보정 계수(마케팅 {gap_model.MARKETING_DISCOUNT} · "
                    f"일정 지연 {gap_model.SCHEDULE_SLIP})를 적용한 값이며, 보수 "
                    "시나리오는 액면가 수용 및 불확실성 여유 가산분임.",
        },
        "urgency": {
            "title": "시급도 산정 기준",
            "intro": "3개 인자의 곱으로 산정함. 기술 격차 × 경쟁사 확산도 × 근거 "
                     "확실성. 각 인자 1~5점 부여, 최대 125점임.",
            "formula": "시급도 = 기술 격차 × 경쟁사 확산도 × 근거 확실성",
            "factors": [
                {"key": k, "label": label, "measure": measure,
                 "scale": [{"score": sc, "means": mn} for sc, mn in scale]}
                for k, label, measure, scale in URGENCY_FACTORS
            ],
            # 5점부터 1점 순으로 제시함. 높은 점수가 위에 와야 우선순위가 먼저 읽힌다.
            "rows": [{"level": f"{sc}점", "name": label, "rule": mn}
                     for _, label, _, scale in URGENCY_FACTORS
                     for sc, mn in sorted(scale, key=lambda r: -r[0])],
            "note": "합산이 아닌 곱셈 적용 사유 — 3개 인자 중 1개라도 낮을 경우 대응 "
                    "우선순위에서 제외되어야 함. 격차가 크더라도 경쟁사 1개사 보유 및 "
                    "공개특허 수준 근거에 그칠 경우 즉시 대응 대상 아님. 합산 방식은 "
                    "해당 건에도 중간 점수를 부여하여 우선순위 변별력이 저하됨. "
                    "근거 확실성은 모델 신뢰도 등급으로 상한 적용함(신뢰도 '하' 2점 · "
                    "'중' 4점 상한).",
            "bands": [
                {"min": 100, "label": "즉시 착수",
                 "rule": "3개 인자 전량 4점 이상 — 당기 즉시 대응 대상임"},
                {"min": 64, "label": "계획 반영",
                 "rule": "3개 인자 평균 4점 — 당기 투자 계획 반영 대상임"},
                {"min": 27, "label": "검토 착수",
                 "rule": "3개 인자 전량 3점 이상 — 검토 착수 기준선임"},
                {"min": 0, "label": "관찰",
                 "rule": "1개 이상 인자가 낮음 — 정기 관찰 대상임"},
            ],
            "band_note": "기준선은 인자 점수에서 직접 도출함 — 전량 3점 27점 · 전량 4점 "
                         "64점 · 전량 5점 125점임. 27점 미만은 3개 인자 중 1개 이상이 "
                         "낮다는 의미이므로 즉시 대응 대상에서 제외함.",
        },
        "class": {
            "title": "기술 구분 기준",
            "intro": "자사 보유 여부를 1차 기준으로, 경쟁사 대비 수준을 2차 기준으로 "
                     "구분함. 각 구분에 모델 신뢰도 등급을 병기함.",
            # 자사 영향도 높은 순으로 제시함. TECH_CLASS 선언 순서가 그대로 표시 순서임.
            "rows": [{"level": name, "name": desc,
                      "rule": TECH_CLASS_RULE.get(key, "")}
                     for key, (name, desc) in TECH_CLASS.items()],
            "note": "'일부 보유' 표현은 판단 방향성이 불명확하여 미사용함. 구분 명칭에 "
                    "경쟁사 대비 수준을 직접 반영함. 경쟁사 근거가 특허에 한정된 경우 "
                    "'우위·동등' 판정은 과대평가 가능성이 있어 별도 표기함. "
                    "'확인 필요'와 '근거 부족'은 미확보 대상이 상호 반대임 — 전자는 자사 "
                    "보유 현황이, 후자는 경쟁사 근거가 미확보 상태임. 전자는 사내 확인으로, "
                    "후자는 조사 확대로 해소함.",
        },
        "hold": {
            "title": "'보유' 판정 기준",
            "intro": HOLD_RULE,
            "rows": [
                {"level": "VERIFIED", "name": "양산 라인 가동 확인",
                 "rule": "1차 출처(법정공시) 기준 확인"},
                {"level": "STRONG", "name": "착공·신설·양산일정",
                 "rule": "파일럿 신설 또는 양산일정 공식 발표"},
                {"level": "MEDIUM", "name": "등록특허·기술세션",
                 "rule": "등록특허 공정조건 또는 기술세션 발표"},
                {"level": "WEAK", "name": "공개특허·포스터",
                 "rule": "출원 공개 또는 포스터·패널 언급"},
            ],
            "note": "근거 0건은 경쟁사 미보유가 아닌 미관측 상태를 의미함. 양자를 구분 "
                    "표기함. 동일 발명의 국가별 출원은 패밀리 병합하여 1건으로 계상함"
                    "(실측 중복률 1.92배).",
        },
    }


# ── 기술 구분 ────────────────────────────────────────────────────────
POSITION_RULES = [
    ("우위", "자사 선행", "자사 TRL 상위"),
    ("동등", "동일 수준", "TRL 동일"),
    ("경합", "1단계 격차", "TRL 1단계 차이"),
    ("열위", "후행", "TRL 2단계 이상 차이"),
]

# 화면에 쓰는 기술 구분. 자사 보유 여부가 1차, 경쟁사 대비 수준이 2차 기준임.
# '일부 보유'는 판단 방향성이 불명확하므로 구분 명칭에 수준을 직접 반영함.
# 나열 순서 = 자사 영향도 높은 순. 화면 음영이 한 방향으로 진해지도록 맞춘다.
# 이전에는 '동등(우위)' 다음에 '동등(열위)'가 와서 음영이 두 갈래로 갈라져 보였다.
TECH_CLASS = {
    "열위": ("열위 기술", "자사 미보유 · 경쟁사 보유 확인 — 최우선 보완 대상"),
    "동등-열위": ("동등 기술(열위)", "자사 일부 보유 · 경쟁사 선행 — 추격 투자 필요"),
    "동등": ("동등 기술", "자사 일부 보유 · 경쟁사 동일 수준 — 선점 경쟁 구간"),
    "동등-우위": ("동등 기술(우위)", "자사 일부 보유 · 경쟁사 대비 선행 — 격차 확대 추진"),
    "우위": ("우위 기술", "자사 라인 적용 · 경쟁사 대비 선행 — 우위 유지 관리"),
    # 아래 둘은 '모르는 쪽'이 서로 반대다.
    #   확인 필요 — 경쟁사는 관측됐고 자사 쪽이 비었다 → 사내 확인으로 풀린다
    #   근거 부족 — 자사는 확인됐고 경쟁사 쪽이 비었다 → 조사 확대로 풀린다
    "확인 필요": ("확인 필요",
                "경쟁사 근거 확보 · 자사 보유 현황 미확인 — 생산기술혁신센터 확인 대상"),
    "판정 불가": ("근거 부족",
                "자사 현황 확인 · 경쟁사 근거 미확보 — 경쟁사 조사 확대 대상"),
}

# 구분별 부여 조건. 화면 표의 '부여 조건' 칸이 비어 있어 무엇으로 갈리는지 알 수 없었다.
TECH_CLASS_RULE = {
    "열위": "자사 보유 근거 0건 ＋ 경쟁사 '보유' 판정 1개사 이상",
    "동등-열위": "자사 일부 보유 ＋ 경쟁사 TRL 이 자사보다 높음",
    "동등": "자사 일부 보유 ＋ 경쟁사 TRL 이 자사와 동일",
    "동등-우위": "자사 일부 보유 ＋ 경쟁사 TRL 이 자사보다 낮음",
    "우위": "자사 라인 적용 ＋ 경쟁사 TRL 이 자사 이하",
    "확인 필요": "경쟁사 근거 1건 이상 ＋ 자사 보유 현황 미입력 — 사내 확인 시 판정 가능",
    "판정 불가": "자사 보유 현황 입력됨 ＋ 경쟁사 근거 0건 — 조사 확대 시 판정 가능",
}


def classify_tech(self_status: str, trl_diff: int) -> tuple[str, str, str]:
    """(구분 키, 화면 이름, 1줄 정의).

    trl_diff = 경쟁사 TRL − 자사 TRL. 양수면 자사 후행임.
    """
    if self_status == "unknown":
        key = "확인 필요"
    elif self_status == "none":
        key = "열위"
    elif self_status == "part":
        key = "동등-열위" if trl_diff > 0 else "동등-우위" if trl_diff < 0 else "동등"
    else:                                     # have
        key = "우위" if trl_diff <= 0 else "동등-열위"
    name, desc = TECH_CLASS[key]
    return key, name, desc


def position(our_trl: int, rival_trl: int, self_status: str,
             self_evidence: int = 0, rival_source_kinds: int = 0,
             rival_evidence: int = 0, conf: str = "high",
             conf_score: float = 0.0) -> dict:
    """기술 구분 판정. 비교의 비대칭을 명시적으로 표기함.

    자사는 라인 적용 여부를 확인 가능하나, 경쟁사는 특허 관측에 한정됨.
    경쟁사 근거가 특허 단독인 경우 해당 TRL 은 실제 대비 하향 산출되므로,
    '우위·동등' 판정에 과대평가 가능성을 병기함.
    """
    d = rival_trl - our_trl
    patent_only = rival_source_kinds <= 1
    conf_ko = gap_model.CONF_LABEL.get(conf, "중")

    if rival_evidence == 0:
        name, desc = TECH_CLASS["판정 불가"]
        return {
            "label": "판정 불가", "label_shown": "근거 부족",
            "caveat": "", "holding": _holding(self_status),
            "display": name, "tech_class": "판정 불가",
            "tech_name": name, "tech_desc": desc,
            "trl_diff": 0, "patent_only": False,
            "conf": "low", "conf_label": "하", "conf_score": 0.0,
            "basis": "경쟁사 근거 0건 — 자사 현황은 확인되었으나 비교 대상 미관측",
        }

    if d <= -1:
        label = "우위"
    elif d == 0:
        label = "동등"
    elif d == 1:
        label = "경합"
    else:
        label = "열위"

    # 경쟁사를 특허로만 관측한 경우 '우위·동등'은 과대평가 가능성이 있음.
    # 열위는 특허 관측만으로 이미 후행이 확인되므로 그대로 유지함.
    if patent_only and label in ("우위", "동등"):
        label_shown = label + "(특허 기준)"
        caveat = ("경쟁사 근거가 특허에 한정됨. 라인 적용 여부 미확인으로 "
                  "실제 수준은 상향 가능성 있음.")
    else:
        label_shown = label
        caveat = ""
    if conf == "low" and not caveat:
        caveat = "모델 신뢰도 '하' — 가용 축 부족으로 재검증 필요함."

    cls_key, cls_name, cls_desc = classify_tech(self_status, d)
    if cls_key == "확인 필요" and not caveat:
        caveat = ("자사 보유 현황 미확인 상태임. 격차 수치는 자사 미보유 가정하의 "
                  "상한값이며, 생산기술혁신센터 확인 후 재산정 필요함.")
    return {
        "label": label,
        "label_shown": label_shown,
        "holding": _holding(self_status),
        # 화면에 그대로 표기하는 이름. '특허 일부 보유 (동등)' 식 이중 표기 미사용함.
        "display": cls_name,
        "tech_class": cls_key,
        "tech_name": cls_name,
        "tech_desc": cls_desc,
        "trl_diff": d,
        "patent_only": patent_only,
        "caveat": caveat,
        "conf": conf, "conf_label": conf_ko, "conf_score": conf_score,
        "basis": f"자사 TRL {our_trl} · 경쟁사 TRL {rival_trl} · {abs(d)}단계 차이 · "
                 f"모델 신뢰도 '{conf_ko}'",
    }


def _holding(self_status: str) -> str:
    if self_status == "have":
        return "특허 보유"
    if self_status == "part":
        return "특허 일부 보유"
    if self_status == "unknown":
        return "보유 현황 미확인"
    return "특허 미보유"
