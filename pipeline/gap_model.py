"""V6 기술 격차 추정 모델 — 특허·공시·기술발표 3축 대리 지표(Proxy Metric).

[모델 채택 배경]
· 경쟁사 실제 수율·제조원가·양산 실적은 비공개 정보로 확보 불가함.
· 확보 가능 데이터는 특허(정량 축), 설비투자 공시(실행 의지 축),
  대외 기술발표(목표 스펙 축) 3종에 한정됨.
· 3축을 각각 대리 지표로 환산 후 가중 결합하여 격차를 추정함.

[핵심 가정 — 임원 보고 시 반드시 함께 제시할 것]
  가정 1. 특허 출원은 양산 의사결정에 3~5년 선행함.
          → 특허 선점 시점 격차를 R&D 선행 격차의 대리 지표로 사용함.
  가정 2. 다국 출원·등록 특허는 방어용 출원 대비 사업화 의지가 높음.
          → 패밀리 국가 수 및 등록 여부로 품질 가중 적용함.
  가정 3. 설비투자 공시는 이사회 의결 사항으로 발표 스펙 대비 신뢰도 높음.
          단, 과거 실적상 일정 지연 발생하므로 지연 계수 적용함.
  가정 4. 대외 기술발표는 마케팅 목적 과장 가능성 상존함.
          → 마케팅 보정 계수 적용 후 기준 시나리오에 반영함.

[본 모델이 산출하지 않는 것 — 한계 명시]
· 경쟁사 실제 수율·불량률·제조원가: 데이터 부재로 미산출함.
· 본 모델은 '경쟁사 절대 진도'가 아닌 '관측 가능 범위 내 상대 격차'를 산출함.
"""
from __future__ import annotations

import math
import re
from datetime import date

# ── 축 가중치 ────────────────────────────────────────────────────────
# 특허를 핵심 축으로 둔다. 공시·발표는 보조 축이며 교차 검증 용도다.
# 가용한 축만 남겨 가중치를 재정규화하므로, 축이 빠져도 합은 항상 1이 된다.
AXIS_WEIGHT = {"rnd": 0.55, "sop": 0.30, "spec": 0.15}
AXIS_LABEL = {"rnd": "R&D 선행 격차", "sop": "양산 진입 격차", "spec": "스펙 수준 격차"}
AXIS_SOURCE = {"rnd": "특허", "sop": "설비투자 공시", "spec": "대외 기술발표"}

# ── 보정 계수 ────────────────────────────────────────────────────────
# 마케팅성 과장 보정 — 발표 스펙의 실제 달성 수준을 0.75 로 본다.
# 근거: 배터리 업계 Tech Day 발표 목표 스펙과 실제 양산 스펙 간 통상 괴리 수준.
#       사내 실적 데이터 확보 시 해당 값으로 대체 적용할 것.
MARKETING_DISCOUNT = 0.75
# 양산 일정 지연 계수 — 공시된 준공·가동 시점 대비 실제 소요를 1.35 배로 본다.
SCHEDULE_SLIP = 1.35
# 단일 축만 산출된 경우 보수 시나리오 가산율. 교차 검증 부재분을 여유로 흡수한다.
SINGLE_AXIS_MARGIN = 0.20

# ── 격차 환산 상수 ───────────────────────────────────────────────────
# 축 격차(개월)를 실행 소요기간의 조정 계수로 환산할 때의 기준 폭.
# 관측창이 2년(2025~2026)에서 16년(2010~2026)으로 넓어져 36개월로 올렸다.
# 24개월로 두면 실제 선점 격차 대부분이 상한에 붙어 변별력이 사라진다.
NORM_MONTHS = 36.0
# 선점 시점 격차의 상한(개월). 5년을 넘는 선점은 5년으로 본다 —
# 그 이상 벌어지면 어차피 '구조적 열위'이며 숫자를 더 키울 의미가 없다.
LEAD_CLAMP_MONTHS = 60.0
# '본격 착수 시점'의 기준 — 품질 가중 누적이 이 비율을 넘긴 시점.
# 최초 1건의 날짜를 쓰면 우연히 오래된 출원 하나가 격차 전체를 결정한다.
ONSET_QUANTILE = 0.25
# 조정 계수 상·하한. 대리 지표가 실행 소요기간 추정을 과도하게 흔들지 않도록 제한한다.
ADJ_MIN, ADJ_MAX = 0.70, 1.60
# 신뢰도 구간별 밴드 폭 — 기준 시나리오 대비 보수 시나리오의 추가 여유.
CONF_BAND = {"high": 0.15, "mid": 0.25, "low": 0.40}
CONF_LABEL = {"high": "상", "mid": "중", "low": "하"}

# ── 특허 품질 가중 ───────────────────────────────────────────────────
# 단순 건수 비교는 방어용 출원과 사업화 특허를 구분하지 못한다.
# 패밀리 국가 수(해외 출원 비용 부담 의지)와 등록 여부(심사 통과)로 보정한다.
GRANT_WEIGHT = {True: 1.4, False: 1.0}
GRADE_WEIGHT = {"verified": 1.5, "strong": 1.3, "medium": 1.1, "weak": 1.0}
# 피인용 수 → 영향력 가중. 후속 출원이 많이 인용한 특허일수록 업계 기준이 된 것이다.
# 상한 1.8 — 피인용만으로 순위가 뒤집히지 않게 막는다.
# 미확보(None)는 1.0 중립. '피인용 0' 과 '확인 불가'를 같게 취급하지 않는다.
CITED_CAP = 1.8
# 최신성 반감기 — 3년 지난 근거는 가중치 절반으로 본다.
HALFLIFE_YEARS = 3.0


def cited_weight(n: int | None) -> float:
    """피인용 수 → 영향력 가중. 미확보 시 1.0(중립)."""
    if n is None:
        return 1.0
    if n <= 0:
        return 0.9          # 확인했는데 0회 — 소폭 감산
    return min(CITED_CAP, 1.0 + 0.16 * math.log2(1 + n))


def breadth_weight(countries: int) -> float:
    """패밀리 국가 수 → 사업화 의지 가중. 단일국 출원은 방어용 가능성이 높다."""
    if countries >= 5:
        return 1.6
    if countries >= 3:
        return 1.3
    if countries >= 2:
        return 1.0
    return 0.6


def _year(s: str) -> float:
    m = re.match(r"(\d{4})-(\d{2})", s or "")
    if not m:
        return 0.0
    return int(m.group(1)) + (int(m.group(2)) - 1) / 12.0


def recency_weight(d: str, today: float | None = None) -> float:
    y = _year(d)
    if not y:
        return 0.5
    now = today if today is not None else _year(date.today().isoformat())
    age = max(0.0, now - y)
    return 0.5 ** (age / HALFLIFE_YEARS)


def _months(a: float, b: float) -> float:
    """a 가 b 보다 얼마나 앞서는가(개월). 음수면 뒤진 것."""
    return (b - a) * 12.0


# ── 패밀리 병합 ──────────────────────────────────────────────────────
def merge_families(evs: list[dict]) -> list[dict]:
    """동일 발명의 국가별 중복 계상을 제거함.

    실측(2026-09-13): BigQuery 추출분 40,000건이 패밀리 기준 20,787건으로 집계됨
    (1.92배 중복). 병합 미적용 시 다국 출원 기업의 특허 규모가 약 2배 과대 산출됨.
    """
    fams: dict[str, dict] = {}
    loose: list[dict] = []
    for e in evs:
        fid = e.get("family_id")
        if not fid:
            loose.append({**e, "_countries": 1, "_members": 1})
            continue
        f = fams.get(fid)
        if f is None:
            fams[fid] = {**e, "_cset": {e.get("country") or "?"}, "_members": 1,
                         "_granted": bool(e.get("granted")),
                         "_cited": e.get("cited_by")}
        else:
            f["_cset"].add(e.get("country") or "?")
            f["_members"] += 1
            f["_granted"] = f["_granted"] or bool(e.get("granted"))
            # 패밀리 대표 피인용은 구성원 중 최대값. 같은 발명이므로 가장 많이
            # 인용된 관할의 값이 그 발명의 영향력이다.
            c = e.get("cited_by")
            if c is not None:
                f["_cited"] = c if f.get("_cited") is None else max(f["_cited"], c)
            # 패밀리 대표일은 최초 관측일 — 선점 시점의 대리 지표임.
            if (e.get("date") or "9999") < (f.get("date") or "9999"):
                f["date"] = e.get("date")
    out = [{**f, "_countries": len(f["_cset"]), "granted": f["_granted"],
            "cited_by": f.get("_cited")}
           for f in fams.values()]
    return out + loose


def patent_strength(evs: list[dict], today: float | None = None) -> tuple[float, dict]:
    """(품질 가중 합, 내역). 건수가 아닌 '사업화 의지가 실린 출원량'을 산출함."""
    fam = merge_families([e for e in evs if e.get("type") == "patent"])
    total = 0.0
    granted = multi = 0
    first = ""
    for f in fam:
        total += (GRADE_WEIGHT.get(f.get("grade") or "weak", 1.0)
                  * breadth_weight(int(f.get("_countries") or 1))
                  * GRANT_WEIGHT[bool(f.get("granted"))]
                  * cited_weight(f.get("cited_by"))
                  * recency_weight(f.get("date") or "", today))
        granted += bool(f.get("granted"))
        multi += int(f.get("_countries") or 1) >= 2
        d = f.get("date") or ""
        if d and (not first or d < first):
            first = d
    cited = [f.get("cited_by") for f in fam if f.get("cited_by")]

    # 본격 착수 시점 — 오래된 순으로 누적해 전체 가중의 ONSET_QUANTILE 을 넘긴 날짜.
    onset = ""
    if total > 0:
        acc = 0.0
        for f in sorted(fam, key=lambda x: x.get("date") or "9999"):
            acc += (GRADE_WEIGHT.get(f.get("grade") or "weak", 1.0)
                    * breadth_weight(int(f.get("_countries") or 1))
                    * GRANT_WEIGHT[bool(f.get("granted"))]
                    * cited_weight(f.get("cited_by"))
                    * recency_weight(f.get("date") or "", today))
            if acc >= total * ONSET_QUANTILE:
                onset = f.get("date") or ""
                break

    return total, {"families": len(fam), "records": len(evs), "granted": granted,
                   "multi_country": multi, "first_date": first, "onset_date": onset,
                   "cited_known": len(cited), "cited_max": max(cited) if cited else 0}


# ── 축 1. R&D 선행 격차 (특허) ───────────────────────────────────────
def axis_rnd(rival_ev: list[dict], self_ev: list[dict],
             today: float | None = None) -> dict:
    """특허 선점 시점 + 품질 가중 출원량으로 R&D 선행 격차를 개월 단위 산출함."""
    r_w, r_i = patent_strength(rival_ev, today)
    s_w, s_i = patent_strength(self_ev, today)
    if r_i["families"] == 0:
        return {"key": "rnd", "available": False, "months": 0.0, "conf": 0.0,
                "basis": "경쟁사 특허 미관측 — 산출 불가"}

    # (a) 선점 시점 격차 — 경쟁사가 자사보다 얼마나 먼저 '본격 착수'했는가.
    #     최초 1건이 아니라 품질 가중 누적 25% 시점을 쓴다. 표본 1건의 우연으로
    #     전 노드가 상한에 붙는 것을 막는다(실측: 최초일 기준 시 52/52 노드 포화).
    lead = 0.0
    r_on, s_on = r_i.get("onset_date"), s_i.get("onset_date")
    if r_on and s_on:
        lead = _months(_year(r_on), _year(s_on))
    elif r_on:
        # 자사 출원 자체가 미관측 — 상한을 그대로 격차로 본다.
        lead = LEAD_CLAMP_MONTHS
    lead = max(-LEAD_CLAMP_MONTHS, min(LEAD_CLAMP_MONTHS, lead))

    # (b) 규모 격차 — 로그 환산. 품질 가중 출원량 2배 차이를 6개월로 본다.
    scale = 6.0 * math.log2((r_w + 1.0) / (s_w + 1.0))
    scale = max(-NORM_MONTHS, min(NORM_MONTHS, scale))

    months = max(0.0, 0.5 * lead + 0.5 * scale)

    # 신뢰도 — 패밀리 수, 다국 출원 비율, 등록 비율로 판정함.
    n = r_i["families"]
    q = (r_i["multi_country"] + r_i["granted"]) / max(1, 2 * n)
    conf = min(1.0, (min(n, 10) / 10.0) * 0.6 + q * 0.4)
    return {
        "key": "rnd", "available": True, "months": round(months, 1),
        "conf": round(conf, 2),
        "lead_months": round(lead, 1), "scale_months": round(scale, 1),
        "rival_onset": r_i.get("onset_date", ""), "self_onset": s_i.get("onset_date", ""),
        "rival": r_i, "self": s_i,
        "rival_weight": round(r_w, 1), "self_weight": round(s_w, 1),
        "basis": (f"경쟁사 패밀리 {n}건(다국 {r_i['multi_country']} · 등록 "
                  f"{r_i['granted']}"
                  + (f" · 최다 피인용 {r_i['cited_max']}회"
                     if r_i.get("cited_max") else "")
                  + f") 대비 자사 {s_i['families']}건 · "
                  + (f"본격 착수 {r_on or '—'} vs 자사 {s_on or '미착수'} "
                     f"({lead:+.0f}개월) · ")
                  + f"규모 {scale:+.0f}개월"),
    }


# ── 축 2. 양산 진입 격차 (설비투자 공시) ─────────────────────────────
# 공시 본문에서 투자 규모·준공 시점이 추출되면 그 값으로 SOP 를 추정한다.
# 추출 불가 시 공시의 존재·등급·최신성만으로 '양산 준비 착수 신호'로 낮춰 반영한다.
# 실측(2026-09-13): cninfo·DART 목록 API 는 제목만 제공하여 금액·시기 추출률 0%.
#                   DART 본문(detail) 확보분에 한해 추출 가능함.
AMOUNT_PAT = [
    (r"(\d[\d,\.]*)\s*조\s*(?:(\d[\d,\.]*)\s*억)?\s*원", "KRW_JO"),
    (r"(\d[\d,\.]*)\s*억\s*원", "KRW_EOK"),
    (r"(\d[\d,\.]*)\s*亿元", "CNY_YI"),
    (r"\$\s?(\d[\d,\.]*)\s*(?:billion|bn)", "USD_B"),
]
SOP_PAT = [
    r"(20\d{2})\s*[년年][^\n]{0,10}?(?:양산|가동|준공|완공|投产|竣工|量产)",
    r"(?:양산|가동|준공|완공|投产|竣工|量产)[^\n]{0,10}?(20\d{2})\s*[년年]?",
]
# 공시 등급별 양산 준비 신호 강도(개월). 본문 미확보 시의 대체 지표임.
SOP_SIGNAL = {"verified": 18.0, "strong": 12.0, "medium": 6.0, "weak": 3.0}


def amount_factor(eok: float) -> float:
    """투자 규모 → 신호 배수. 1,000억원을 1.0 으로 두고 로그로 키운다.

    라인 신설급(조 단위)과 부대설비급(백억 단위)을 같은 신호로 볼 수 없다.
    상한 2.0 — 금액만으로 격차가 무한정 커지지 않게 막는다.
    """
    if eok <= 0:
        return 1.0
    return max(0.7, min(2.0, 1.0 + 0.25 * math.log2(max(eok, 100.0) / 1000.0)))
# 환산 기준 — 1 亿元 ≈ 190억원(190원/위안), $1B ≈ 1.3조원(1,300원/$).
# 1 亿元 = 1e8 위안 × 190원 = 1.9e10원 = 190억원. 1,900 은 10배 오류였다.
CNY_TO_EOK = 190.0
USD_B_TO_EOK = 13000.0


# 설비투자 문맥을 가리키는 말. 금액이 이 말 근처에 있어야 라인 투자로 본다.
INVEST_CUE = re.compile(
    r"투자|시설|증설|신설|설비|공장|생산능력|투자建|投资|建设|产能|扩产|capex", re.I)
# 라인 투자로 인정하는 하한(억원). 이보다 작으면 기부·소송가액 등일 가능성이 높다.
CAPEX_FLOOR_EOK = 300.0


def _amount_all(text: str) -> list[tuple[float, int]]:
    """본문에서 찾은 (억원 환산액, 위치) 전량."""
    out = []
    for pat, kind in AMOUNT_PAT:
        for m in re.finditer(pat, text):
            try:
                v = float(m.group(1).replace(",", ""))
            except (ValueError, AttributeError):
                continue
            if kind == "KRW_JO":
                extra = 0.0
                if m.lastindex and m.lastindex >= 2 and m.group(2):
                    extra = float(m.group(2).replace(",", ""))
                v = v * 10000 + extra
            elif kind == "CNY_YI":
                v *= CNY_TO_EOK
            elif kind == "USD_B":
                v *= USD_B_TO_EOK
            out.append((v, m.start()))
    return out


def _amount_krw_eok(text: str) -> float:
    """공시 본문에서 투자 규모를 억원 단위로 추출함. 미추출 시 0.

    본문에 나오는 첫 숫자를 그대로 쓰면 기부금·소송가액 같은 것이 잡힌다
    (실측: '기타경영사항(자율공시)'에서 8억·11억이 투자 규모로 집계됨).
    ① 투자 문맥 인근(±80자)의 금액을 우선하고, ② 그중 최대값을 택한다.
       설비투자 공시는 대표 투자 규모를 본문에 명시하므로 최대값이 그것이다.
    """
    hits = _amount_all(text)
    if not hits:
        return 0.0
    cues = [m.start() for m in INVEST_CUE.finditer(text)]
    near = [v for v, pos in hits
            if any(abs(pos - c) <= 80 for c in cues)]
    pool = near or [v for v, _ in hits]
    best = max(pool)
    return best if best >= CAPEX_FLOOR_EOK else 0.0


def _sop_year(text: str) -> int:
    """공시 본문에서 양산·준공 예정 연도를 추출함. 미추출 시 0."""
    for pat in SOP_PAT:
        m = re.search(pat, text)
        if m:
            y = int(m.group(1))
            if 2015 <= y <= 2040:
                return y
    return 0


def capex_text(e: dict) -> str:
    """공시 1건에서 판정에 쓸 전체 텍스트. body(전문) > summary(400자) 순으로 본다."""
    return " ".join(x for x in (e.get("body"), e.get("summary"), e.get("ref")) if x)


# 전사 단위 근거의 신뢰도 상한. 공장 투자 공시는 '이 공정기술'의 증거가 아니라
# '이 회사의 양산 진입 역량'의 증거다. 특허 축을 넘어서지 못하게 눌러 둔다.
COMPANY_SCOPE_CONF_CAP = 0.5


def axis_sop(rival_ev: list[dict], self_ev: list[dict],
             today: float | None = None,
             company_capex: list[dict] | None = None,
             self_company_capex: list[dict] | None = None) -> dict:
    """설비투자 공시로 양산 준비(SOP) 진입 격차를 산출함.

    설비투자 공시는 공장 단위 정보라 개별 공정기술 노드에 배정되지 않는다
    (실측: 590건 전량 미배정). 노드에 억지로 붙이면 근거 날조가 되므로,
    company_capex 로 '전사 단위 근거'임을 명시해 받아 따로 표기한다.
    """
    rc = [e for e in rival_ev if e.get("type") == "capex"]
    scope = "node"
    if not rc and company_capex:
        rc = [e for e in company_capex if e.get("type") == "capex"]
        scope = "company"
        self_ev = self_company_capex or self_ev
    if not rc:
        return {"key": "sop", "available": False, "months": 0.0, "conf": 0.0,
                "basis": "경쟁사 설비투자 공시 미관측 — 산출 불가"}
    now = today if today is not None else _year(date.today().isoformat())

    amounts, sops, signal = [], [], 0.0
    for e in rc:
        txt = capex_text(e)
        a = _amount_krw_eok(txt)
        if a:
            amounts.append(a)
        y = _sop_year(txt)
        if y:
            sops.append(y)
        signal = max(signal, SOP_SIGNAL.get(e.get("grade") or "weak", 3.0)
                     * recency_weight(e.get("date") or "", now))

    # 3단계로 나눈다. 원천마다 확보되는 정보가 다르기 때문이다.
    #   ① 준공·양산 시점 확보  — DART 본문에서 확인됨
    #   ② 투자 규모만 확보     — cninfo(CATL) 이사회 공고는 시점을 적지 않음(실측 0/23)
    #   ③ 본문 미확보          — 공시 존재만으로 약한 신호
    structured = bool(sops)
    if structured:
        # 공시된 최단 양산 시점까지의 잔여 개월. 이미 지난 시점이면 0(진입 완료).
        nearest = min(sops)
        rival_to_sop = max(0.0, (nearest - now) * 12.0)
        self_sops = []
        for e in self_ev:
            if e.get("type") != "capex":
                continue
            y = _sop_year(capex_text(e))
            if y:
                self_sops.append(y)
        self_to_sop = (max(0.0, (min(self_sops) - now) * 12.0)
                       if self_sops else NORM_MONTHS)
        months = max(0.0, self_to_sop - rival_to_sop)
        conf = 0.7
        basis = f"공시 기준 최단 양산 시점 {nearest}년 · 자사 대비 {months:.0f}개월 선행"
        if amounts:
            basis += f" · 투자 규모 {max(amounts):,.0f}억원"
    elif amounts:
        # 투자 규모는 확보됐으나 준공 시점이 공시에 없음. 규모로 신호 강도를 조정함.
        top = max(amounts)
        months = signal * amount_factor(top)
        conf = 0.5
        basis = (f"공시 {len(rc)}건 · 최대 투자 규모 {top:,.0f}억원 확보. "
                 f"준공·양산 시점은 공시 본문에 미기재되어 투자 규모 기준으로 "
                 f"신호 강도만 조정 적용함.")
    else:
        # 본문 미확보 — 공시 존재 자체를 약한 신호로만 반영함.
        months = signal
        conf = 0.35
        basis = (f"공시 {len(rc)}건 관측(본문 미확보) — 양산 준비 착수 신호로만 "
                 f"반영함. 투자 규모·준공 시점 미추출로 신뢰도 '하' 적용함.")

    if scope == "company":
        # 전사 근거임을 숨기지 않는다. 신뢰도도 그만큼만 준다.
        conf = min(conf, COMPANY_SCOPE_CONF_CAP)
        basis = "전사 단위 근거(개별 공정기술 배정 불가) — " + basis
    return {"key": "sop", "available": True, "months": round(months, 1),
            "conf": conf, "structured": structured, "count": len(rc),
            "scope": scope,
            "amount_eok": round(max(amounts)) if amounts else 0,
            "sop_year": min(sops) if sops else 0, "basis": basis}


# ── 축 3. 스펙 수준 격차 (대외 기술발표) ─────────────────────────────
# 발표 스펙은 목표치이며 양산 스펙이 아니다. 마케팅 보정 계수를 적용해 반영한다.
SPEC_PAT = [
    (r"(\d[\d\.]*)\s*Wh/kg", "energy"),
    (r"(\d[\d\.]*)\s*Wh/L", "energy_v"),
    (r"(\d[\d\.]*)\s*C\b", "crate"),
    (r"(\d[\d\.]*)\s*분\s*(?:급속)?충전", "charge"),
]
# 스펙 초과율 100% 를 이 개월 수로 환산함. 목표 성능 갭 → 기간 변환 계수임.
SPEC_MONTH_PER_100PCT = 18.0
TALK_TYPES = ("paper", "talk", "conference")


def axis_spec(rival_ev: list[dict], self_spec: dict | None,
              today: float | None = None) -> dict:
    """발표 목표 스펙과 자사 현행 스펙의 성능 갭을 개월로 환산함."""
    talks = [e for e in rival_ev if e.get("type") in TALK_TYPES]
    if not talks:
        return {"key": "spec", "available": False, "months": 0.0, "conf": 0.0,
                "basis": "경쟁사 대외 기술발표 미관측 — 산출 불가"}

    found = []
    for e in talks:
        txt = (e.get("summary") or "") + " " + (e.get("ref") or "")
        for pat, kind in SPEC_PAT:
            m = re.search(pat, txt, re.I)
            if m:
                found.append((kind, float(m.group(1))))

    gaps = []
    if found and self_spec:
        for kind, val in found:
            cur = float(self_spec.get(kind) or 0)
            if cur > 0 and val > cur:
                gaps.append((val - cur) / cur)

    if not gaps:
        # 수치 미추출 — 발표 건수·최신성만 약한 신호로 반영함.
        sig = max((recency_weight(e.get("date") or "", today) for e in talks),
                  default=0.0) * 6.0
        return {"key": "spec", "available": True, "months": round(sig, 1),
                "conf": 0.25, "structured": False, "count": len(talks),
                "basis": (f"기술발표 {len(talks)}건 관측 · 목표 스펙 수치 미추출 — "
                          f"발표 활동 강도만 반영함. 마케팅 보정 계수 "
                          f"{MARKETING_DISCOUNT} 적용 대상임.")}

    ratio = max(gaps)
    months = ratio * SPEC_MONTH_PER_100PCT
    return {"key": "spec", "available": True, "months": round(months, 1),
            "conf": 0.5, "structured": True, "count": len(talks),
            "basis": (f"발표 목표 스펙 대비 자사 현행 스펙 격차 {ratio*100:.0f}% — "
                      f"마케팅 보정 계수 {MARKETING_DISCOUNT} 적용 전 값임.")}


# ── 결합 — 기준(Base) / 보수(Conservative) 듀얼 트랙 ──────────────────
def combine(axes: list[dict], execution_years: float) -> dict:
    """3축 결과를 실행 소요기간에 결합하여 듀얼 트랙 격차를 산출함.

    · 기준(Base)        : 공시·발표 축에 보정 계수 적용 — 마케팅성 과장 배제분.
    · 보수(Conservative): 공시·발표를 액면가 수용 + 불확실성 여유 가산분.
    · 양자 차이 = '발표 의존도'. 차이가 클수록 경쟁사 공개 정보 의존도가 높음.
    """
    live = [a for a in axes if a.get("available")]
    if not live:
        band = CONF_BAND["low"]
        return {"base_years": round(execution_years, 1),
                "cons_years": round(execution_years * (1 + band), 1),
                "adj_base": 1.0, "adj_cons": 1.0, "band": band,
                "conf": "low", "conf_score": 0.0, "live_axes": 0, "axes": axes,
                "vapor_exposure": round(execution_years * band, 1),
                "note": "3축 전량 미산출 — 실행 소요기간만 제시하며 신뢰도 '하' 적용함."}

    wsum = sum(AXIS_WEIGHT[a["key"]] for a in live)
    disc = {"rnd": 1.0, "sop": 1.0 / SCHEDULE_SLIP, "spec": MARKETING_DISCOUNT}

    def adj(discounted: bool) -> float:
        acc = 0.0
        for a in live:
            w = AXIS_WEIGHT[a["key"]] / wsum
            m = a["months"] * (disc[a["key"]] if discounted else 1.0)
            acc += w * (m / NORM_MONTHS)
        return max(ADJ_MIN, min(ADJ_MAX, 1.0 + acc))

    adj_base, adj_cons = adj(True), adj(False)

    conf_score = sum(AXIS_WEIGHT[a["key"]] / wsum * a["conf"] for a in live)
    if len(live) >= 2 and conf_score >= 0.6:
        conf = "high"
    elif conf_score >= 0.35:
        conf = "mid"
    else:
        conf = "low"
    band = CONF_BAND[conf]
    if len(live) == 1:
        band += SINGLE_AXIS_MARGIN      # 교차 검증 부재분 여유

    base = execution_years * adj_base
    cons = execution_years * adj_cons * (1 + band)
    return {
        "base_years": round(base, 1), "cons_years": round(cons, 1),
        "adj_base": round(adj_base, 2), "adj_cons": round(adj_cons, 2),
        "band": round(band, 2), "conf": conf, "conf_score": round(conf_score, 2),
        "live_axes": len(live), "axes": axes,
        # 보정 전후 차이 = 경쟁사 발표·공시에 의존한 비중
        "vapor_exposure": round(max(0.0, cons - base), 1),
        "note": (f"가용 축 {len(live)}/3 · 신뢰도 '{CONF_LABEL[conf]}' · "
                 f"보수 시나리오 여유 {band*100:.0f}% 적용함."),
    }


def _by_company(evs: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for e in evs:
        out.setdefault(e.get("_co") or e.get("company") or "?", []).append(e)
    return out


def leading_rival(rival_ev: list[dict], self_ev: list[dict],
                  today: float | None = None) -> tuple[str, dict]:
    """(선두 경쟁사, 해당 사 기준 R&D 축). 격차가 가장 큰 1사를 선두로 본다.

    6사 근거를 합산하면 '누가 앞섰는가'가 사라지고, 합산 규모가 자사 규모에
    눌려 격차가 평탄해진다. 대응 대상을 특정하려면 선두 1사를 지목해야 한다.
    """
    best_name, best = "", None
    for co, evs in _by_company(rival_ev).items():
        a = axis_rnd(evs, self_ev, today)
        if not a.get("available"):
            continue
        if best is None or a["months"] > best["months"]:
            best_name, best = co, a
    if best is None:
        return "", axis_rnd(rival_ev, self_ev, today)
    return best_name, best


def estimate(rival_ev: list[dict], self_ev: list[dict], execution_years: float,
             self_spec: dict | None = None, today: float | None = None,
             company_capex: dict | None = None,
             self_company_capex: list[dict] | None = None) -> dict:
    """노드 1개에 대한 3축 격차 추정. build_tree 진입점임."""
    # 축 1 은 선두 경쟁사 기준으로 산출한다(합산 시 격차가 상쇄되어 소멸함).
    leader, rnd = leading_rival(rival_ev, self_ev, today)
    if leader:
        rnd = {**rnd, "leader": leader,
               "basis": f"선두 {leader} 기준 — " + rnd.get("basis", "")}
    # 축 2·3 도 선두 1사 기준으로 맞춘다. 축마다 비교 대상이 다르면 합산이 성립하지 않는다.
    scope = _by_company(rival_ev).get(leader, rival_ev) if leader else rival_ev
    # 선두사의 전사 설비투자를 함께 넘긴다. 노드에 배정된 공시가 없을 때만 쓰인다.
    co_cap = (company_capex or {}).get(leader, []) if leader else []
    axes = [rnd,
            axis_sop(scope, self_ev, today, co_cap, self_company_capex),
            axis_spec(scope, self_spec, today)]
    out = combine(axes, execution_years)
    out["leader"] = leader
    out["axis_rows"] = [{
        "key": a["key"], "label": AXIS_LABEL[a["key"]],
        "source": AXIS_SOURCE[a["key"]], "weight": AXIS_WEIGHT[a["key"]],
        "available": a.get("available", False), "months": a.get("months", 0.0),
        "conf": a.get("conf", 0.0), "basis": a.get("basis", ""),
    } for a in axes]
    return out


MODEL_DOC = {
    "title": "기술 격차 추정 모델 (V6)",
    "intro": ("경쟁사 수율·원가·양산 실적은 비공개로 확보 불가함. 확보 가능한 특허·"
              "설비투자 공시·대외 기술발표 3축을 대리 지표로 환산하여 격차를 추정함. "
              "각 축에 보정 계수를 적용한 기준 시나리오와 액면가 수용 보수 시나리오를 "
              "병행 산출함."),
    "rows": [
        {"level": "축 1 · 특허", "name": "R&D 선행 격차 (가중 55%)",
         "rule": "패밀리 병합 후 선점 시점 격차와 품질 가중 출원량을 개월로 환산함. "
                 "패밀리 국가 수·등록 여부·피인용 수·최신성으로 방어용 출원분을 "
                 "감산함."},
        {"level": "축 2 · 공시", "name": "양산 진입 격차 (가중 30%)",
         "rule": "설비투자 공시의 투자 규모·준공 시점으로 SOP 진입 시점을 추정함. "
                 f"과거 일정 지연 실적 반영하여 지연 계수 {SCHEDULE_SLIP} 적용함."},
        {"level": "축 3 · 발표", "name": "스펙 수준 격차 (가중 15%)",
         "rule": "발표 목표 스펙과 자사 현행 스펙의 성능 갭을 환산함. "
                 f"마케팅성 과장 보정 계수 {MARKETING_DISCOUNT} 적용함."},
        {"level": "결합", "name": "기준 / 보수 듀얼 트랙",
         "rule": "기준 = 보정 계수 적용분. 보수 = 공시·발표 액면가 수용 + 불확실성 "
                 "여유 가산분. 양자 차이는 경쟁사 공개 정보 의존도를 의미함."},
    ],
    "note": ("미가용 축은 가중치에서 제외 후 재정규화하며, 가용 축 1개 시 보수 "
             f"시나리오에 {SINGLE_AXIS_MARGIN*100:.0f}% 여유를 가산함. "
             "수율·원가 등 비공개 지표는 본 모델 산출 대상 아님을 명시함."),
}
