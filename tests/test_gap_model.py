"""V6 3축 격차 모델 검증. 네트워크 없이 돈다.

    .venv\\Scripts\\python.exe tests\\test_gap_model.py

이 파일이 지키는 것은 '숫자가 얼마냐'가 아니라 제한된 데이터 환경에서
모델이 지켜야 할 성질이다. 아래 4가지가 깨지면 임원 앞에서 방어할 수 없다.

  ① 패밀리 병합 — 같은 발명을 여러 나라에 낸 것이 여러 건으로 세어지면 안 된다.
  ② 품질 가중   — 단일국 공개출원 더미가 다국 등록특허를 이기면 안 된다.
  ③ 발표 방어   — 발표·공시만으로 격차가 특허 근거보다 커지면 안 된다.
  ④ 듀얼 트랙   — 보수 시나리오가 기준 시나리오보다 작아지면 안 된다.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline import gap_model as G  # noqa: E402

fails = []


def ck(name, cond, extra=""):
    print(("  ok   " if cond else "  FAIL ") + name + (f"  {extra}" if extra else ""))
    if not cond:
        fails.append(name)


def pat(fid, country, date="2025-06", grade="weak", granted=False):
    return {"type": "patent", "family_id": fid, "country": country, "date": date,
            "grade": grade, "granted": granted}


NOW = 2026.7      # 시점을 고정한다. 오늘 날짜에 따라 결과가 흔들리면 검증이 안 된다.

print("-- ① 패밀리 병합: 같은 발명은 1건이다 --")
same = [pat("F1", c) for c in ("CN", "US", "EP", "JP", "KR", "DE")]
ck("6개국 출원 → 패밀리 1건", len(G.merge_families(same)) == 1,
   f"{len(G.merge_families(same))}건")
ck("패밀리 국가 수 6", G.merge_families(same)[0]["_countries"] == 6)
diff = [pat(f"F{i}", "CN") for i in range(6)]
ck("서로 다른 발명 6건은 6건", len(G.merge_families(diff)) == 6)
ck("family_id 없으면 병합하지 않는다",
   len(G.merge_families([{"type": "patent", "date": "2025-01"}] * 3)) == 3)

print("-- 패밀리 대표일은 최초 관측일이다(선점 시점 대리 지표) --")
spread = [pat("F1", "CN", "2025-09"), pat("F1", "US", "2025-02"),
          pat("F1", "EP", "2026-01")]
ck("최초일로 대표", G.merge_families(spread)[0]["date"] == "2025-02",
   G.merge_families(spread)[0]["date"])
ck("한 나라라도 등록이면 등록 처리",
   G.merge_families([pat("F1", "CN"), pat("F1", "US", granted=True)])[0]["granted"])

print("-- ② 품질 가중: 방어용 출원 더미가 이기면 안 된다 --")
defensive = [pat(f"D{i}", "CN") for i in range(8)]            # 단일국 공개 8건
serious = [pat("S1", c, granted=True) for c in ("CN", "US", "EP", "JP", "KR")]
w_def, i_def = G.patent_strength(defensive, NOW)
w_ser, i_ser = G.patent_strength(serious, NOW)
ck("방어용 8건 vs 사업화 1패밀리 — 건수는 8:1",
   i_def["families"] == 8 and i_ser["families"] == 1,
   f"{i_def['families']}:{i_ser['families']}")
ck("단일국 가중 0.6 < 5개국 가중 1.6",
   G.breadth_weight(1) < G.breadth_weight(2) < G.breadth_weight(3) < G.breadth_weight(5))
ck("등록이 공개보다 무겁다", G.GRANT_WEIGHT[True] > G.GRANT_WEIGHT[False])
ck("사업화 1패밀리 가중이 방어용 1건보다 높다", w_ser > w_def / 8,
   f"{w_ser:.2f} vs {w_def/8:.2f}")

print("-- 최신성: 오래된 근거는 감산된다 --")
ck("반감기 3년", abs(G.recency_weight("2023-09", 2026.7) - 0.5) < 0.08,
   f"{G.recency_weight('2023-09', 2026.7):.2f}")
ck("최근이 과거보다 무겁다",
   G.recency_weight("2026-06", NOW) > G.recency_weight("2020-06", NOW))
ck("날짜 없으면 중립 0.5", G.recency_weight("", NOW) == 0.5)

print("-- 축 1. R&D 선행 격차 --")
a = G.axis_rnd([pat("R1", "CN", "2025-01")], [pat("S1", "KR", "2026-06")], NOW)
ck("경쟁사가 앞서면 양수", a["available"] and a["months"] > 0, str(a["months"]))
b = G.axis_rnd([pat("R1", "CN", "2026-06")], [pat(f"S{i}", "KR", "2025-01")
                                              for i in range(9)], NOW)
ck("자사가 앞서면 0으로 하한", b["months"] == 0, str(b["months"]))
ck("경쟁사 특허 없으면 산출 불가", not G.axis_rnd([], [pat("S1", "KR")], NOW)["available"])
ck("자사 특허 0건이면 관측창 전체를 격차로",
   G.axis_rnd([pat("R1", "CN", "2025-01")], [], NOW)["lead_months"] == G.NORM_MONTHS)

print("-- 축 2. 양산 진입 격차: 공시 본문이 있으면 SOP 를 뽑는다 --")
cap = [{"type": "capex", "grade": "strong", "date": "2026-03",
        "summary": "2028년 하반기 양산 가동 예정", "ref": "투자 3조 5000억원 규모"}]
s = G.axis_sop(cap, [], NOW)
ck("SOP 연도 추출", s["sop_year"] == 2028, str(s["sop_year"]))
ck("투자 규모 추출(억원)", s["amount_eok"] == 35000, str(s["amount_eok"]))
ck("본문 확보 시 신뢰도 상향", s["structured"] and s["conf"] >= 0.7, str(s["conf"]))
bare = G.axis_sop([{"type": "capex", "grade": "strong", "date": "2026-03",
                    "summary": "생산기지 투자 공고", "ref": ""}], [], NOW)
ck("본문 미확보 시 약한 신호로만", not bare["structured"] and bare["conf"] <= 0.35,
   str(bare["conf"]))
ck("본문 미확보 근거 문구에 한계 명시", "본문 미확보" in bare["basis"])
ck("공시 없으면 산출 불가", not G.axis_sop([], [], NOW)["available"])
ck("위안화 환산", G._amount_krw_eok("投资 50 亿元") == 50 * G.CNY_TO_EOK)

print("-- ③ 발표 방어: 마케팅 보정 계수가 실제로 적용된다 --")
talk = [{"type": "paper", "grade": "medium", "date": "2026-06",
         "summary": "400 Wh/kg cell demonstrated", "ref": ""}]
sp = G.axis_spec(talk, {"energy": 200}, NOW)
ck("스펙 수치 추출 시 구조화", sp["structured"], str(sp))
ck("스펙 갭이 격차로 환산", sp["months"] > 0, str(sp["months"]))
ck("수치 없으면 활동 강도만", not G.axis_spec(
    [{"type": "paper", "grade": "medium", "date": "2026-06", "summary": "리뷰", "ref": ""}],
    {"energy": 200}, NOW)["structured"])
ck("발표 없으면 산출 불가", not G.axis_spec([], None, NOW)["available"])
ck("마케팅 계수는 1 미만", 0 < G.MARKETING_DISCOUNT < 1, str(G.MARKETING_DISCOUNT))
ck("일정 지연 계수는 1 초과", G.SCHEDULE_SLIP > 1, str(G.SCHEDULE_SLIP))

# 발표만 있는 경우와 특허가 함께 있는 경우 — 발표 단독이 더 높게 나오면 안 된다
only_talk = G.estimate(talk, [], 2.0, self_spec={"energy": 200}, today=NOW)
with_pat = G.estimate(talk + [pat("R1", "CN", "2025-01", granted=True)], [],
                      2.0, self_spec={"energy": 200}, today=NOW)
ck("발표 단독은 신뢰도가 낮다", only_talk["conf"] in ("low", "mid"), only_talk["conf"])
ck("발표 단독은 축 1개 → 보수 여유 가산",
   only_talk["band"] >= G.CONF_BAND[only_talk["conf"]] + G.SINGLE_AXIS_MARGIN - 1e-9,
   f"band={only_talk['band']}")
ck("특허가 붙으면 가용 축이 늘어난다", with_pat["live_axes"] > only_talk["live_axes"],
   f"{with_pat['live_axes']} vs {only_talk['live_axes']}")

print("-- ④ 듀얼 트랙: 보수는 항상 기준 이상이다 --")
cases = [
    ([], [], 0.0),
    ([pat("R1", "CN")], [], 1.0),
    (talk, [], 2.25),
    (cap + talk + [pat("R1", "CN", granted=True)], [pat("S1", "KR")], 3.5),
]
ok = True
for riv, mine, ex in cases:
    r = G.estimate(riv, mine, ex, self_spec={"energy": 200}, today=NOW)
    if r["cons_years"] < r["base_years"] - 1e-9:
        ok = False
        print(f"       역전: base={r['base_years']} cons={r['cons_years']}")
ck("전 경우에서 보수 ≥ 기준", ok)

full = G.estimate(cap + talk + [pat("R1", "CN", granted=True)], [pat("S1", "KR")],
                  3.5, self_spec={"energy": 200}, today=NOW)
ck("가용 축 3개면 3", full["live_axes"] == 3, str(full["live_axes"]))
ck("조정 계수 상·하한 준수", G.ADJ_MIN <= full["adj_base"] <= G.ADJ_MAX,
   str(full["adj_base"]))
ck("발표 의존도 = 보수 − 기준",
   abs(full["vapor_exposure"] - (full["cons_years"] - full["base_years"])) < 0.15,
   f"{full['vapor_exposure']} vs {full['cons_years']-full['base_years']:.1f}")

print("-- 축 전량 미산출: 모델이 조용히 0 을 만들지 않는다 --")
none = G.estimate([], [], 2.25, today=NOW)
ck("실행 소요기간은 유지(표시용 소수 1자리 반올림)",
   abs(none["base_years"] - 2.25) <= 0.06, str(none["base_years"]))
ck("신뢰도 '하'", none["conf"] == "low")
ck("보수 시나리오는 더 길다", none["cons_years"] > none["base_years"])
ck("한계를 문구로 남긴다", "미산출" in none["note"], none["note"])

print("-- 가중치 재정규화 --")
ck("3축 가중 합 1.0", abs(sum(G.AXIS_WEIGHT.values()) - 1.0) < 1e-9)
ck("특허가 최대 가중",
   G.AXIS_WEIGHT["rnd"] == max(G.AXIS_WEIGHT.values()), str(G.AXIS_WEIGHT))
one_axis = G.estimate([pat("R1", "CN")], [], 2.0, today=NOW)
ck("축 1개여도 조정 계수는 상·하한 안", G.ADJ_MIN <= one_axis["adj_base"] <= G.ADJ_MAX)

print("-- 모델 설명 문서(화면 팝업이 읽는다) --")
d = G.MODEL_DOC
ck("제목 있음", bool(d.get("title")))
ck("3축 + 결합 = 4행", len(d["rows"]) == 4, str(len(d["rows"])))
ck("가정과 한계가 모듈 문서에 명시", "수율" in G.__doc__ and "미산출" in G.__doc__)
ck("팝업 문구에 마크다운 없음",
   all("**" not in (d.get(k) or "") for k in ("intro", "note")))
print("-- 개조식 종결(임원 보고 어조) --")
tails = [d["intro"], d["note"]] + [r["rule"] for r in d["rows"]]
ck("전 문구 명사형 종결", all(t.rstrip().endswith(("함.", "임.", "음.", "함", "임"))
                              for t in tails),
   "; ".join(t[-12:] for t in tails if not t.rstrip().endswith(("함.", "임.", "음."))))

print()
print("실패 없음" if not fails else f"실패: {fails}")
sys.exit(1 if fails else 0)
