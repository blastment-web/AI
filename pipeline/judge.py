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


# ── 시간 격차 ────────────────────────────────────────────────────────
# TRL 한 단계를 올리는 데 걸리는 기간(년). 뒤로 갈수록 길어진다.
# 배터리 공정기술의 통상적인 단계 소요를 기준으로 잡은 값이며, 회사 실적으로 보정할 수 있다.
TRL_STEP_YEARS = {4: 0.5, 5: 0.75, 6: 1.0, 7: 1.25, 8: 1.5}
LAG_METHOD = ("경쟁사가 도달한 TRL 에서 자사 TRL 을 뺀 뒤, 구간별 소요기간을 더한다. "
              "단계마다 기간이 다르다 — 뒤 단계일수록 오래 걸린다.")


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


def fmt_gap(years: float) -> str:
    return "—" if years <= 0 else f"약 {years:g}년"


# ── 시급도 ───────────────────────────────────────────────────────────
# 100점 만점. 각 항목이 무엇을 재는지 한 줄로 말할 수 있어야 한다.
URGENCY_SPEC = [
    ("gap",    35, "격차 크기",   "TRL 차이가 클수록 높다. 5단계 이상이면 만점"),
    ("spread", 25, "경쟁사 확산", "몇 개사가 보유했는가. 업계 표준이 되면 만점"),
    ("proof",  20, "근거 강도",   "최고 근거 등급. VERIFIED 면 만점"),
    ("recent", 10, "최근 움직임", "최근 12개월 신호 수. 3건 이상이면 만점"),
    ("hole",   10, "자사 공백",   "특허·라인·발표·과제 4채널 중 빈 개수"),
]


def urgency(rival_trl: int, our_trl: int, rivals_have: int, rivals_part: int,
            top_grade: str | None, recent_count: int, self_info: dict,
            total_rivals: int = 6) -> tuple[int, list[dict]]:
    """(시급도 0~100, 항목별 내역)."""
    rows = []

    d = max(0, rival_trl - our_trl)
    gap = min(35, round(35 * min(d, 5) / 5))
    rows.append({"k": "gap", "label": "격차 크기", "max": 35, "got": gap,
                 "why": f"TRL {our_trl} → {rival_trl} · {d}단계 차이"})

    weight = rivals_have + 0.5 * rivals_part
    spread = min(25, round(25 * min(weight, total_rivals) / total_rivals))
    rows.append({"k": "spread", "label": "경쟁사 확산", "max": 25, "got": spread,
                 "why": f"보유 {rivals_have}사 + 일부 {rivals_part}사 / 추적 {total_rivals}사"})

    gr = GRADE_RANK.get(top_grade or "", 0)
    proof = round(20 * gr / 4)
    rows.append({"k": "proof", "label": "근거 강도", "max": 20, "got": proof,
                 "why": (GRADE_LABEL[top_grade] if top_grade else "미관측")})

    rec = min(10, round(10 * min(recent_count, 3) / 3))
    rows.append({"k": "recent", "label": "최근 움직임", "max": 10, "got": rec,
                 "why": f"최근 12개월 신호 {recent_count}건"})

    si = self_info or {}
    holes = sum(1 for key in ("pat", "line", "talk", "prj")
                if not si.get(key) or si.get(key) in (0, "0", "없음", "—"))
    hole = min(10, round(10 * holes / 4))
    rows.append({"k": "hole", "label": "자사 공백", "max": 10, "got": hole,
                 "why": f"4개 채널 중 {holes}개 비어 있음"})

    return sum(r["got"] for r in rows), rows


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
            "intro": "경쟁사가 어디까지 갔는지를 **관측된 근거만으로** 추정합니다. 추측은 넣지 않습니다.",
            "rows": [{"level": lv, "name": nm, "rule": rl} for lv, nm, rl in TRL_RULES],
            "note": f"TRL {TRL_CROSS_SOURCE_MIN} 이상은 특허·설비투자·발표 중 "
                    "서로 다른 2종이 교차 확인될 때만 부여합니다. 한 종류만 있으면 7로 제한합니다.",
        },
        "lag": {
            "title": "시간 격차를 어떻게 계산했는가",
            "intro": LAG_METHOD,
            "rows": [{"level": f"TRL {t} → {t+1}", "name": f"{y}년", "rule": ""}
                     for t, y in sorted(TRL_STEP_YEARS.items())],
            "note": "자사 TRL 은 보유=9, 일부=7, 출원만 있음=4, 미착수=3 으로 봅니다. "
                    "단계별 소요기간은 배터리 공정기술 통상치이며 사내 실적으로 보정할 수 있습니다.",
        },
        "urgency": {
            "title": "시급도 점수를 어떻게 매겼는가",
            "intro": "100점 만점. 다섯 항목의 합이며 각 항목은 관측값에서 바로 계산됩니다.",
            "rows": [{"level": f"{mx}점", "name": label, "rule": desc}
                     for _, mx, label, desc in URGENCY_SPEC],
            "note": "점수는 순위를 매기기 위한 것이지 절대적 위험도가 아닙니다. "
                    "같은 점수대는 사람이 사업 맥락으로 다시 판단해야 합니다.",
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
        return {
            "label": "판정 불가", "label_shown": "판정 불가",
            "caveat": "", "holding": _holding(self_status),
            "display": f"{_holding(self_status)} (판정 불가)",
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

    return {
        "label": label,
        "label_shown": label_shown,
        "holding": _holding(self_status),
        "display": f"{_holding(self_status)} ({label_shown})",
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
