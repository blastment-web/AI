"""판정 기준 — TRL · 시간 격차 · 시급도.

이 파일이 세 숫자의 **유일한 근거**다. 화면의 설명 팝업도 여기서 생성한 JSON 을 읽는다.
기준을 바꾸려면 여기만 고치면 화면 설명까지 같이 바뀐다.

설계 원칙
  1. 관측 가능한 것만 쓴다. 추측을 숫자로 바꾸지 않는다.
  2. 모든 숫자는 "왜 그 값인가"를 한 줄로 설명할 수 있어야 한다.
  3. 근거가 약하면 등급을 낮추지 말고 '확인 필요'로 표시한다.
"""
from __future__ import annotations

GRADE_RANK = {"verified": 4, "strong": 3, "medium": 2, "weak": 1}
GRADE_LABEL = {"verified": "VERIFIED", "strong": "STRONG",
               "medium": "MEDIUM", "weak": "WEAK"}

# ── TRL ─────────────────────────────────────────────────────────────
# 경쟁사가 '어디까지 갔는가'를 관측된 근거로만 추정한다.
# 임원 보고 기준: 숫자 하나하나가 어떤 관측에서 나왔는지 말할 수 있어야 한다.
TRL_RULES = [
    (9, "양산 적용",      "양산 가동 확인(VERIFIED) 및 이종 소스 2종 이상 교차 검증"),
    (8, "양산 준비",      "양산 가동 확인(VERIFIED) 1건 또는 착공·양산일정(STRONG) 2건 이상"),
    (7, "파일럿 가동",    "파일럿 신설·착공 또는 양산일정 공식 발표(STRONG) 1건"),
    (6, "실증 완료",      "등록특허 공정조건 또는 기술세션 발표(MEDIUM) 2건 이상"),
    (5, "요소기술 확보",  "등록특허 공정조건 또는 기술세션 발표(MEDIUM) 1건"),
    (4, "출원 단계",      "공개특허(WEAK) 단독 관측"),
    (3, "미관측",        "근거 미확보 — 부재가 아닌 미확인 상태"),
]
TRL_CROSS_SOURCE_MIN = 8   # 이 값 이상은 서로 다른 소스 2종이 교차해야 부여


def estimate_trl(evidence: list[dict]) -> tuple[int, str]:
    """(TRL, 근거 한 줄). evidence 는 grade·type 을 가진 레코드 목록."""
    if not evidence:
        return 3, "근거 0건 — 미관측"
    n = {g: sum(1 for e in evidence if e.get("grade") == g)
         for g in GRADE_RANK}
    kinds = len({e.get("type") for e in evidence if e.get("type")})

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

    # 교차 확인 규칙 — 단일 소스로는 8 이상을 주지 않는다
    capped = False
    if trl >= TRL_CROSS_SOURCE_MIN and kinds < 2:
        trl, capped = 7, True

    parts = [f"{GRADE_LABEL[g]} {n[g]}건" for g in
             ("verified", "strong", "medium", "weak") if n[g]]
    why = " · ".join(parts) + f" · 소스 {kinds}종"
    if capped:
        why += " → 단일 소스 사유로 TRL 7 상한 적용"
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
    if pat > 0:
        return 4, f"관련 출원 {pat}건 — 착수 확인, 라인 적용 실적 없음"
    return 3, "4개 채널 전량 0건 — 미착수"


# ── 기술 격차 ────────────────────────────────────────────────────────
# TRL 한 단계를 올리는 데 걸리는 기간(년)과, '왜 그만큼 걸리는가'.
# 숫자만 보여 주면 체감이 오지 않는다. 각 단계에서 실제로 해야 하는 일을 함께 적는다.
# 기간은 배터리 공정기술의 통상치이며 사내 실적으로 보정할 수 있다.
TRL_STEPS = [
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

LAG_METHOD = ("경쟁사 도달 수준까지의 자사 소요기간 산정치임. "
              "단계별 수행 과업 상이로 소요기간 차등 적용함. "
              "후행 단계일수록 설비 투자 및 라인 정지 수반으로 기간 증가함.")


def time_gap(rival_trl: int, our_trl: int) -> tuple[float, str]:
    """(격차 년수, 계산 근거)."""
    if rival_trl <= our_trl:
        return 0.0, "격차 없음 — 자사 동일 또는 선행"
    steps, total = [], 0.0
    for t in range(our_trl, rival_trl):
        y = TRL_STEP_YEARS.get(t, 1.0)
        total += y
        steps.append(f"TRL{t}→{t+1} {y}년")
    return round(total, 1), " + ".join(steps) + f" = {round(total,1)}년"


def gap_breakdown(rival_trl: int, our_trl: int) -> list[dict]:
    """이 기술이 왜 그만큼 뒤졌는지를 단계별로 풀어 준다.

    '2단계 차이라 1.75년'은 임원에게 아무 말도 하지 않는다.
    '코터를 발주해 받는 데 1년, 라인 세워 수율 올리는 데 9개월'이라고 해야 한다.
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


# ── 시급도 ───────────────────────────────────────────────────────────
# 항목 다섯 개를 더하는 방식은 '왜 62점인가'에 답하지 못한다.
# 세 가지를 곱한다. 하나라도 0에 가까우면 전체가 낮아진다 — 곱셈이라야 그 성질이 산다.
#
#      시급도 = 얼마나 뒤졌나 × 몇 개사가 가졌나 × 근거가 얼마나 단단한가
#                 (1~5)          (1~5)             (1~5)          → 최대 125점
#
# 곱셈을 쓰는 이유: 아무리 뒤져도 경쟁사 1곳만 갖고 있고 근거가 약하면 급하지 않다.
# 덧셈이면 그런 경우도 중간 점수가 나와 순위가 흐려진다.
URGENCY_MAX = 125

URGENCY_FACTORS = [
    ("gap", "기술 격차", "경쟁사 대비 TRL 단계 차이", [
        (1, "격차 없음"), (2, "1단계"), (3, "2단계"), (4, "3단계"), (5, "4단계 이상")]),
    ("spread", "경쟁사 확산도", "보유 확인 경쟁사 수", [
        (1, "0개사"), (2, "1개사"), (3, "2개사"), (4, "3~4개사"), (5, "5개사 이상")]),
    ("proof", "근거 확실성", "최상위 근거 등급", [
        (1, "미관측"), (2, "WEAK — 공개특허"), (3, "MEDIUM — 등록특허·기술발표"),
        (4, "STRONG — 착공·양산일정"), (5, "VERIFIED — 양산 가동 확인")]),
]


def _score_gap(d: int) -> int:
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


def _score_proof(top_grade: str | None) -> int:
    return {"": 1, "weak": 2, "medium": 3, "strong": 4, "verified": 5}.get(
        top_grade or "", 1)


def urgency(rival_trl: int, our_trl: int, rivals_have: int, rivals_part: int,
            top_grade: str | None, recent_count: int, self_info: dict,
            total_rivals: int = 6) -> tuple[int, list[dict]]:
    """(시급도 0~125, 세 인자 내역). 세 인자를 곱한 값이 그대로 점수다."""
    d = max(0, rival_trl - our_trl)
    g = _score_gap(d)
    s = _score_spread(rivals_have, rivals_part)
    p = _score_proof(top_grade)

    rows = [
        {"k": "gap", "label": "기술 격차", "got": g, "max": 5,
         "why": f"자사 TRL {our_trl} → 경쟁사 {rival_trl} · {d}단계 차이"},
        {"k": "spread", "label": "경쟁사 확산도", "got": s, "max": 5,
         "why": f"보유 {rivals_have}개사 · 일부 보유 {rivals_part}개사"},
        {"k": "proof", "label": "근거 확실성", "got": p, "max": 5,
         "why": (GRADE_LABEL[top_grade] if top_grade else "미관측")},
    ]
    return g * s * p, rows


def urgency_formula(rows: list[dict]) -> str:
    """'4 × 3 × 5 = 60' — 화면에 그대로 쓰는 한 줄."""
    if not rows:
        return ""
    vals = [r["got"] for r in rows]
    total = 1
    for v in vals:
        total *= v
    return " × ".join(str(v) for v in vals) + f" = {total}"


# ── 보유 판정 ────────────────────────────────────────────────────────
HOLD_RULE = "STRONG 1건 · MEDIUM 2건 · WEAK 3건 이상 충족 시 '보유' 판정함."


def rival_holds(evidence: list[dict]) -> bool:
    n = {g: sum(1 for e in evidence if e.get("grade") == g) for g in GRADE_RANK}
    return n["verified"] >= 1 or n["strong"] >= 1 or n["medium"] >= 2 or n["weak"] >= 3


def criteria_doc() -> dict:
    """화면 팝업이 읽는 기준 설명. 코드와 설명이 어긋나지 않게 여기서 생성한다."""
    return {
        "trl": {
            "title": "TRL 산정 기준",
            "intro": "경쟁사 도달 수준은 관측 근거에 한정하여 추정함. 추정치 임의 부여 배제함. "
                     "판정의 핵심 기준은 특허이며, 설비투자 공시·기술발표는 보조 근거로 교차 검증에 한정 적용함.",
            "rows": [{"level": lv, "name": nm, "rule": rl} for lv, nm, rl in TRL_RULES],
            "note": f"TRL {TRL_CROSS_SOURCE_MIN} 이상은 특허·설비투자·기술발표 중 "
                    "이종 2종 교차 검증 시에만 부여함. 단일 소스 시 TRL 7 상한 적용함.",
        },
        "lag": {
            "title": "기술 격차 산정 기준",
            "intro": LAG_METHOD,
            "rows": [{"level": f"{y}년", "name": nm, "rule": why}
                     for _, _, y, nm, why in TRL_STEPS],
            "note": "자사 단계 산정 기준 — 전 라인 적용 9 · 파일럿 7 · 출원 단독 4 · 미착수 3. "
                    "소요기간은 배터리 공정기술 통상치 적용분이며, 사내 실적 데이터 확보 시 "
                    "해당 값으로 대체 적용 예정임.",
        },
        "urgency": {
            "title": "시급도 산정 기준",
            "intro": "3개 인자의 곱으로 산정함. 기술 격차 × 경쟁사 확산도 × 근거 확실성. "
                     "각 인자 1~5점 부여, 최대 125점임.",
            "formula": "시급도 = 기술 격차 × 경쟁사 확산도 × 근거 확실성",
            "factors": [
                {"key": k, "label": label, "measure": measure,
                 "scale": [{"score": sc, "means": mn} for sc, mn in scale]}
                for k, label, measure, scale in URGENCY_FACTORS
            ],
            "rows": [{"level": f"{sc}점", "name": label, "rule": mn}
                     for _, label, _, scale in URGENCY_FACTORS for sc, mn in scale],
            "note": "합산이 아닌 곱셈 적용 사유 — 3개 인자 중 1개라도 낮을 경우 대응 "
                    "우선순위에서 제외되어야 함. 격차가 크더라도 경쟁사 1개사 보유 및 "
                    "공개특허 수준 근거에 그칠 경우 즉시 대응 대상 아님. 합산 방식은 해당 건에도 "
                    "중간 점수를 부여하여 우선순위 변별력이 저하됨.",
        },
        "class": {
            "title": "기술 구분 기준",
            "intro": "자사 보유 여부를 1차 기준으로, 경쟁사 대비 수준을 2차 기준으로 구분함.",
            "rows": [{"level": name, "name": desc, "rule": ""}
                     for name, desc in TECH_CLASS.values()],
            "note": "'일부 보유' 표현은 판단 방향성이 불명확하여 미사용함. "
                    "구분 명칭에 경쟁사 대비 수준을 직접 반영함.",
        },
        "hold": {
            "title": "'보유' 판정 기준",
            "intro": HOLD_RULE,
            "rows": [
                {"level": "VERIFIED", "name": "양산 라인 가동 확인", "rule": "1차 출처(법정공시) 기준 확인"},
                {"level": "STRONG", "name": "착공·신설·양산일정", "rule": "파일럿 신설 또는 양산일정 공식 발표"},
                {"level": "MEDIUM", "name": "등록특허·기술세션", "rule": "등록특허 공정조건 또는 기술세션 발표"},
                {"level": "WEAK", "name": "공개특허·포스터", "rule": "출원 공개 또는 포스터·패널 언급"},
            ],
            "note": "근거 0건은 경쟁사 미보유가 아닌 미관측 상태를 의미함. 양자를 구분 표기함.",
        },
    }


# ── 기술 위치 — 동등 / 경합 / 열위 ────────────────────────────────────
# 임원 의사결정에 필요한 것은 "있다/없다"가 아니라 "경쟁사 대비 어디에 서 있나"다.
POSITION_RULES = [
    ("우위", "자사 선행", "자사 TRL 상위"),
    ("동등", "동일 수준", "TRL 동일"),
    ("경합", "1단계 격차", "TRL 1단계 차이"),
    ("열위", "후행", "TRL 2단계 이상 차이"),
]


# 화면에 쓰는 기술 구분. 자사 보유 여부가 먼저고, 그 안에서 경쟁사 대비 수준을 나눈다.
# 임원은 '일부 보유'가 좋다는 건지 나쁘다는 건지 모른다. 그래서 이름 자체에 답을 담는다.
TECH_CLASS = {
    "열위": ("열위 기술", "자사 미보유 · 경쟁사 보유 확인 — 최우선 보완 대상"),
    "동등-우위": ("동등 기술(우위)", "자사 일부 보유 · 경쟁사 대비 선행 — 격차 확대 추진"),
    "동등": ("동등 기술", "자사 일부 보유 · 경쟁사 동일 수준 — 선점 경쟁 구간"),
    "동등-열위": ("동등 기술(열위)", "자사 일부 보유 · 경쟁사 선행 — 추격 투자 필요"),
    "우위": ("우위 기술", "자사 라인 적용 · 경쟁사 대비 선행 — 우위 유지 관리"),
    "판정 불가": ("판정 불가", "경쟁사 근거 미확보 — 비교 판정 불가"),
}


def classify_tech(self_status: str, trl_diff: int) -> tuple[str, str, str]:
    """(구분 키, 화면 이름, 한 줄 정의).

    trl_diff = 경쟁사 TRL − 자사 TRL. 양수면 자사가 뒤진 것이다.
    """
    if self_status == "none":
        key = "열위"
    elif self_status == "part":
        key = "동등-열위" if trl_diff > 0 else "동등-우위" if trl_diff < 0 else "동등"
    else:                                     # have
        key = "우위" if trl_diff <= 0 else "동등-열위"
    name, desc = TECH_CLASS[key]
    return key, name, desc


def position(our_trl: int, rival_trl: int, self_status: str,
             self_evidence: int = 0, rival_source_kinds: int = 0,
             rival_evidence: int = 0) -> dict:
    """(위치 라벨, 화면 표기, 근거).

    비교의 비대칭에 주의한다. 자사는 라인 적용 여부를 알지만 경쟁사는
    특허밖에 못 본다. 경쟁사 근거가 특허뿐이면 그 TRL 은 실제보다 낮게
    잡히므로, '우위'라는 말을 그대로 쓰면 안 된다.
    """
    d = rival_trl - our_trl
    patent_only = rival_source_kinds <= 1

    if rival_evidence == 0:
        name, desc = TECH_CLASS["판정 불가"]
        return {
            "label": "판정 불가", "label_shown": "판정 불가",
            "caveat": "", "holding": _holding(self_status),
            "display": name, "tech_class": "판정 불가",
            "tech_name": name, "tech_desc": desc,
            "trl_diff": 0, "patent_only": False,
            "basis": "경쟁사 근거 0건 — 비교 판정 불가",
        }

    if d <= -1:
        label = "우위"
    elif d == 0:
        label = "동등"
    elif d == 1:
        label = "경합"
    else:
        label = "열위"

    # 경쟁사를 특허로만 봤다면 '우위·동등'은 과대평가일 수 있다.
    # 열위는 특허만으로도 이미 뒤진 것이므로 그대로 둔다.
    if patent_only and label in ("우위", "동등"):
        label_shown = label + "(특허 기준)"
        caveat = ("경쟁사 근거가 특허에 한정됨. 라인 적용 여부 미확인으로 "
                  "실제 수준은 상향 가능성 있음.")
    else:
        label_shown = label
        caveat = ""

    cls_key, cls_name, cls_desc = classify_tech(self_status, d)
    return {
        "label": label,
        "label_shown": label_shown,
        "holding": _holding(self_status),
        # 화면에 그대로 찍는 이름. '특허 일부 보유 (동등)' 같은 이중 표기를 쓰지 않는다.
        "display": cls_name,
        "tech_class": cls_key,
        "tech_name": cls_name,
        "tech_desc": cls_desc,
        "trl_diff": d,
        "patent_only": patent_only,
        "caveat": caveat,
        "basis": f"자사 TRL {our_trl} · 경쟁사 TRL {rival_trl} · {abs(d)}단계 차이",
    }


def _holding(self_status: str) -> str:
    if self_status == "have":
        return "특허 보유"
    if self_status == "part":
        return "특허 일부 보유"
    return "특허 미보유"
