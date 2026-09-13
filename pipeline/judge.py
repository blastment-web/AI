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
    (9, "양산 중",        "양산 가동 확인(VERIFIED) + 서로 다른 소스 2종 이상"),
    (8, "양산 준비·초기",  "양산 가동 확인(VERIFIED) 1건, 또는 착공·양산일정(STRONG) 2건 이상"),
    (7, "파일럿 가동",     "파일럿 신설·착공 또는 양산일정 공식 언급(STRONG) 1건"),
    (6, "실증·검증",      "등록특허의 공정조건 또는 기술세션 발표(MEDIUM) 2건 이상"),
    (5, "요소기술 확보",   "등록특허의 공정조건 또는 기술세션 발표(MEDIUM) 1건"),
    (4, "출원 단계",      "공개특허(WEAK)만 관측됨"),
    (3, "미관측",        "수집된 근거 없음 — '없다'가 아니라 '못 봤다'"),
]
TRL_CROSS_SOURCE_MIN = 8   # 이 값 이상은 서로 다른 소스 2종이 교차해야 부여


def estimate_trl(evidence: list[dict]) -> tuple[int, str]:
    """(TRL, 근거 한 줄). evidence 는 grade·type 을 가진 레코드 목록."""
    if not evidence:
        return 3, "수집된 근거 0건 — 미관측"
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
        why += " → 단일 소스라 TRL 7로 제한"
    return trl, why


# ── 자사 TRL ─────────────────────────────────────────────────────────
SELF_TRL = {
    "have": (9, "양산 전 라인 적용"),
    "part": (7, "파일럿·일부 라인 적용"),
}


def self_trl(self_info: dict) -> tuple[int, str]:
    st = (self_info or {}).get("status", "none")
    if st in SELF_TRL:
        return SELF_TRL[st]
    pat = int((self_info or {}).get("pat") or 0)
    if pat > 0:
        return 4, f"관련 출원 {pat}건 — 착수는 했으나 라인 적용 없음"
    return 3, "4개 채널 모두 0 — 미착수"


# ── 기술 격차 ────────────────────────────────────────────────────────
# TRL 한 단계를 올리는 데 걸리는 기간(년)과, '왜 그만큼 걸리는가'.
# 숫자만 보여 주면 체감이 오지 않는다. 각 단계에서 실제로 해야 하는 일을 함께 적는다.
# 기간은 배터리 공정기술의 통상치이며 사내 실적으로 보정할 수 있다.
TRL_STEPS = [
    (4, 5, 0.5,  "요소기술 확보 → 실증",
     "랩 스케일에서 공정조건을 찾아 재현한다. 장비를 새로 사지 않아 가장 빠르다."),
    (5, 6, 0.75, "실증 → 검증 완료",
     "파일럿 장비를 빌리거나 개조해 조건을 재현한다. 장비 확보에 시간이 걸린다."),
    (6, 7, 1.0,  "검증 → 파일럿 가동",
     "전용 장비를 발주한다. 코터·프레스 같은 핵심 설비의 납기가 6~12개월이다."),
    (7, 8, 1.25, "파일럿 → 양산 준비",
     "양산 라인을 개조하고 수율을 올린다. 라인을 세워야 하므로 생산 손실이 따른다."),
    (8, 9, 1.5,  "양산 준비 → 전 라인 양산",
     "전 공장으로 넓히고 고객 품질 승인을 받는다. 승인 절차만 6개월 이상이다."),
]
TRL_STEP_YEARS = {a: y for a, _, y, _, _ in TRL_STEPS}
TRL_STEP_WHY = {a: (nm, why) for a, _, _, nm, why in TRL_STEPS}

LAG_METHOD = ("경쟁사가 도달한 단계까지 자사가 올라가는 데 걸리는 기간입니다. "
              "단계마다 해야 할 일이 달라서 걸리는 기간도 다릅니다. "
              "뒤 단계일수록 장비를 사고 라인을 세워야 해서 오래 걸립니다.")


def time_gap(rival_trl: int, our_trl: int) -> tuple[float, str]:
    """(격차 년수, 계산 근거)."""
    if rival_trl <= our_trl:
        return 0.0, "격차 없음 — 자사가 같거나 앞섬"
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
    ("gap", "얼마나 뒤졌나", "TRL 단계 차이", [
        (1, "차이 없음"), (2, "1단계"), (3, "2단계"), (4, "3단계"), (5, "4단계 이상")]),
    ("spread", "몇 개사가 가졌나", "보유가 확인된 경쟁사 수", [
        (1, "0개사"), (2, "1개사"), (3, "2개사"), (4, "3~4개사"), (5, "5개사 이상")]),
    ("proof", "근거가 단단한가", "가장 강한 근거의 등급", [
        (1, "미관측"), (2, "WEAK — 공개특허"), (3, "MEDIUM — 등록특허·발표"),
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
        {"k": "gap", "label": "얼마나 뒤졌나", "got": g, "max": 5,
         "why": f"TRL {our_trl} → {rival_trl} · {d}단계 차이"},
        {"k": "spread", "label": "몇 개사가 가졌나", "got": s, "max": 5,
         "why": f"보유 {rivals_have}개사 + 일부 {rivals_part}개사"},
        {"k": "proof", "label": "근거가 단단한가", "got": p, "max": 5,
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
HOLD_RULE = "STRONG 1건 · MEDIUM 2건 · WEAK 3건 이상이면 '보유'로 본다."


def rival_holds(evidence: list[dict]) -> bool:
    n = {g: sum(1 for e in evidence if e.get("grade") == g) for g in GRADE_RANK}
    return n["verified"] >= 1 or n["strong"] >= 1 or n["medium"] >= 2 or n["weak"] >= 3


def criteria_doc() -> dict:
    """화면 팝업이 읽는 기준 설명. 코드와 설명이 어긋나지 않게 여기서 생성한다."""
    return {
        "trl": {
            "title": "TRL 을 어떻게 정했는가",
            "intro": "경쟁사가 어디까지 갔는지를 관측된 근거만으로 추정합니다. 추측은 넣지 않습니다.",
            "rows": [{"level": lv, "name": nm, "rule": rl} for lv, nm, rl in TRL_RULES],
            "note": f"TRL {TRL_CROSS_SOURCE_MIN} 이상은 특허·설비투자·발표 중 "
                    "서로 다른 2종이 교차 확인될 때만 부여합니다. 한 종류만 있으면 7로 제한합니다.",
        },
        "lag": {
            "title": "기술 격차를 어떻게 계산했는가",
            "intro": LAG_METHOD,
            "rows": [{"level": f"{y}년", "name": nm, "rule": why}
                     for _, _, y, nm, why in TRL_STEPS],
            "note": "자사 단계는 라인 적용=9, 파일럿=7, 출원만 있음=4, 미착수=3 으로 봅니다. "
                    "기간은 배터리 공정기술 통상치입니다. 사내 실제 소요기간이 있으면 "
                    "그 값으로 바꿔야 더 정확해집니다.",
        },
        "urgency": {
            "title": "시급도를 어떻게 매겼는가",
            "intro": "세 가지를 곱합니다. 얼마나 뒤졌나 × 몇 개사가 가졌나 × "
                     "근거가 단단한가. 각 1~5점이므로 최대 125점입니다.",
            "formula": "시급도 = 얼마나 뒤졌나 × 몇 개사가 가졌나 × 근거가 단단한가",
            "factors": [
                {"key": k, "label": label, "measure": measure,
                 "scale": [{"score": sc, "means": mn} for sc, mn in scale]}
                for k, label, measure, scale in URGENCY_FACTORS
            ],
            "rows": [{"level": f"{sc}점", "name": label, "rule": mn}
                     for _, label, _, scale in URGENCY_FACTORS for sc, mn in scale],
            "note": "더하지 않고 곱하는 이유는, 셋 중 하나라도 약하면 급한 일이 아니기 "
                    "때문입니다. 아무리 뒤져 있어도 경쟁사 한 곳만 갖고 있고 근거가 "
                    "공개특허뿐이면 지금 손댈 일이 아닙니다. 더하기로는 그런 건도 "
                    "중간 점수가 나와 순위가 흐려집니다.",
        },
        "class": {
            "title": "기술 구분을 어떻게 나눴는가",
            "intro": "자사가 가졌는지를 먼저 보고, 그다음 경쟁사보다 앞서는지를 봅니다.",
            "rows": [{"level": name, "name": desc, "rule": ""}
                     for name, desc in TECH_CLASS.values()],
            "note": "'일부 보유'라는 말은 좋은 건지 나쁜 건지 알 수 없어 쓰지 않습니다. "
                    "이름 안에 경쟁사 대비 수준을 함께 담았습니다.",
        },
        "hold": {
            "title": "'보유'를 어떻게 판정했는가",
            "intro": HOLD_RULE,
            "rows": [
                {"level": "VERIFIED", "name": "양산 라인 가동 확인", "rule": "1차 출처(공시·법정공시)로 확인"},
                {"level": "STRONG", "name": "착공·신설·양산일정", "rule": "파일럿 신설 또는 양산 일정 공식 언급"},
                {"level": "MEDIUM", "name": "등록특허·기술세션", "rule": "등록특허의 공정조건 또는 기술세션 발표"},
                {"level": "WEAK", "name": "공개특허·포스터", "rule": "출원 공개 또는 포스터·패널 언급"},
            ],
            "note": "근거 0건은 '경쟁사가 없다'가 아니라 '관측되지 않았다'입니다. 둘을 구분해 표기합니다.",
        },
    }


# ── 기술 위치 — 동등 / 경합 / 열위 ────────────────────────────────────
# 임원 의사결정에 필요한 것은 "있다/없다"가 아니라 "경쟁사 대비 어디에 서 있나"다.
POSITION_RULES = [
    ("우위", "자사가 경쟁사보다 앞선다", "자사 TRL 이 더 높다"),
    ("동등", "경쟁사와 같은 수준이다", "TRL 이 같다"),
    ("경합", "한 단계 차이로 쫓기거나 쫓는다", "TRL 1단계 차이"),
    ("열위", "뒤처져 있다", "TRL 2단계 이상 차이"),
]


# 화면에 쓰는 기술 구분. 자사 보유 여부가 먼저고, 그 안에서 경쟁사 대비 수준을 나눈다.
# 임원은 '일부 보유'가 좋다는 건지 나쁘다는 건지 모른다. 그래서 이름 자체에 답을 담는다.
TECH_CLASS = {
    "열위": ("열위 기술", "자사에는 없고 경쟁사는 가진 기술"),
    "동등-우위": ("동등 기술(우위)", "자사도 일부 가졌고, 경쟁사보다 앞선 기술"),
    "동등": ("동등 기술", "자사도 일부 가졌고, 경쟁사와 같은 수준인 기술"),
    "동등-열위": ("동등 기술(열위)", "자사도 일부 가졌지만, 경쟁사가 더 앞선 기술"),
    "우위": ("우위 기술", "자사가 라인에 적용했고 경쟁사보다 앞선 기술"),
    "판정 불가": ("판정 불가", "경쟁사 근거가 없어 비교할 수 없는 기술"),
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
            "basis": "경쟁사 근거 0건 — 비교할 수 없다",
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
        caveat = ("경쟁사는 특허만 관측됐다. 라인 적용 여부를 모르므로 "
                  "실제로는 더 앞서 있을 수 있다.")
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
