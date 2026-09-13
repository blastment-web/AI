"""판정 기준(TRL·기술 격차·시급도·기술 구분) 검증. 네트워크 없이 돈다.

    .venv\\Scripts\\python.exe tests\\test_judge.py

이 파일이 지키는 것은 '숫자가 얼마냐'가 아니라 '기준과 화면 설명이 어긋나지 않느냐'다.
judge.py 를 고치면 여기가 먼저 깨져야 한다.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline import judge as J  # noqa: E402

fails = []


def ck(name, cond, extra=""):
    print(("  ok   " if cond else "  FAIL ") + name + (f"  {extra}" if extra else ""))
    if not cond:
        fails.append(name)


print("-- 시급도: 곱셈이어야 한다 --")
s1, r1 = J.urgency(9, 4, 5, 1, "verified", 3, {})
ck("세 인자만 쓴다", len(r1) == 3, str([x["k"] for x in r1]))
ck("만점은 곱한 값", s1 == 125, str(s1))
prod = r1[0]["got"] * r1[1]["got"] * r1[2]["got"]
ck("점수 = 세 인자의 곱", s1 == prod, f"{s1} vs {prod}")
ck("공식 문자열", J.urgency_formula(r1) == "5 × 5 × 5 = 125", J.urgency_formula(r1))

s2, r2 = J.urgency(6, 6, 0, 0, None, 0, {})
ck("아무것도 없으면 최저 1점", s2 == 1, str(s2))

# 곱셈의 핵심 성질: 하나가 약하면 전체가 낮아진다
s3, _ = J.urgency(9, 3, 1, 0, "weak", 0, {})   # 격차는 크지만 1개사·약한 근거
s4, _ = J.urgency(7, 6, 5, 0, "verified", 0, {})  # 격차는 작지만 5개사·강한 근거
ck("격차만 커도 낮게 나온다", s3 < 30, str(s3))
ck("확산·근거가 강하면 격차가 작아도 올라간다", s4 > s3, f"{s4} vs {s3}")
ck("최대 범위 안에 있다", 1 <= s1 <= J.URGENCY_MAX and 1 <= s4 <= J.URGENCY_MAX)

print("-- 기술 구분 --")
cases = [
    ("none", 3, "열위 기술"),
    ("none", 0, "열위 기술"),
    ("part", 2, "동등 기술(열위)"),
    ("part", 0, "동등 기술"),
    ("part", -1, "동등 기술(우위)"),
    ("have", 0, "우위 기술"),
    ("have", -2, "우위 기술"),
    ("have", 2, "동등 기술(열위)"),
]
for st, d, want in cases:
    _, name, desc = J.classify_tech(st, d)
    ck(f"{st}/차이{d} → {want}", name == want, name)
    ck(f"  정의가 비어 있지 않다 ({want})", bool(desc.strip()))

print("-- '일부 보유' 라는 말을 쓰지 않는다 --")
for name, desc in J.TECH_CLASS.values():
    ck(f"이름에 '일부 보유' 없음: {name}", "일부 보유" not in name)
    ck(f"이름에 '일부 확보' 없음: {name}", "일부 확보" not in name)

print("-- 기술 격차: 단계마다 이유가 붙는다 --")
steps = J.gap_breakdown(9, 4)
ck("4→9 는 5단계", len(steps) == 5, str(len(steps)))
ck("합이 time_gap 과 같다",
   abs(sum(x["years"] for x in steps) - J.time_gap(9, 4)[0]) < 1e-6)
for x in steps:
    ck(f"TRL{x['from']}→{x['to']} 에 '하는 일'이 있다", bool(x["name"].strip()))
    ck(f"TRL{x['from']}→{x['to']} 에 '왜 걸리는지'가 있다", len(x["why"].strip()) > 10)
ck("뒤 단계일수록 오래 걸린다",
   all(steps[i]["years"] <= steps[i + 1]["years"] for i in range(len(steps) - 1)))
ck("앞서 있으면 단계가 없다", J.gap_breakdown(4, 9) == [])

print("-- position 이 구분 정보를 싣는다 --")
p = J.position(3, 8, "none", rival_source_kinds=1, rival_evidence=5)
for k in ("tech_class", "tech_name", "tech_desc", "display", "label"):
    ck(f"position 에 {k}", k in p)
ck("display 가 기술 구분 이름", p["display"] == p["tech_name"], p["display"])
ck("열위로 판정", p["tech_name"] == "열위 기술", p["tech_name"])

p2 = J.position(9, 5, "have", rival_source_kinds=1, rival_evidence=5)
ck("특허만 관측되면 단서를 단다", bool(p2["caveat"]), p2["caveat"][:40])
p3 = J.position(9, 5, "have", rival_source_kinds=2, rival_evidence=5)
ck("소스 2종이면 단서 없음", not p3["caveat"])

p4 = J.position(9, 3, "none", rival_evidence=0)
ck("경쟁사 근거 0건이면 판정 불가", p4["label"] == "판정 불가", p4["label"])
ck("판정 불가에도 tech_name 이 있다", bool(p4.get("tech_name")))

print("-- criteria_doc: 화면 설명이 코드와 같은 곳에서 나온다 --")
doc = J.criteria_doc()
for key in ("trl", "lag", "urgency", "class", "hold"):
    ck(f"설명 항목 {key}", key in doc)
    ck(f"  {key} 에 제목", bool(doc[key].get("title")))
    ck(f"  {key} 에 표", len(doc[key].get("rows") or []) > 0)
ck("격차 설명 줄 수 = 실제 단계 수",
   len(doc["lag"]["rows"]) == len(J.TRL_STEPS), str(len(doc["lag"]["rows"])))
ck("시급도 설명에 곱셈식", "×" in doc["urgency"].get("formula", ""),
   doc["urgency"].get("formula", ""))
ck("시급도 인자 3개", len(doc["urgency"].get("factors") or []) == 3)

print("-- 팝업 문구에 마크다운이 섞이지 않는다 --")
for key, c in doc.items():
    ck(f"{key} intro 에 ** 없음", "**" not in (c.get("intro") or ""),
       (c.get("intro") or "")[:40])
    ck(f"{key} note 에 ** 없음", "**" not in (c.get("note") or ""))

print("-- TRL: 단일 소스로는 8 이상을 주지 않는다 --")
one = [{"grade": "verified", "type": "patent"}]
trl, why = J.estimate_trl(one)
ck("단일 소스는 7로 제한", trl == 7, f"{trl} / {why}")
two = [{"grade": "verified", "type": "patent"}, {"grade": "medium", "type": "capex"}]
ck("소스 2종이면 9", J.estimate_trl(two)[0] == 9, str(J.estimate_trl(two)[0]))
ck("근거 없으면 3(미관측)", J.estimate_trl([])[0] == 3)

print("-- V6 ①: 특허 뒷받침 없는 발표는 TRL 7 이상을 받지 못한다 --")
talk_only = [{"grade": "strong", "type": "capex", "date": "2026-06"}]
t1, w1 = J.estimate_trl(talk_only, today=2026.7)
ck("공시 단독 STRONG 1건 → TRL 6 상한", t1 == 6, f"{t1} / {w1}")
ck("상한 사유를 근거 문구에 남긴다", "특허 미관측" in w1, w1)
backed = talk_only + [{"grade": "weak", "type": "patent", "family_id": "F1",
                       "country": "CN", "date": "2026-01"}]
ck("특허가 붙으면 TRL 7 부여", J.estimate_trl(backed, today=2026.7)[0] == 7,
   str(J.estimate_trl(backed, today=2026.7)[0]))

print("-- V6 ②: 후속 관측 없이 오래된 발표는 등급이 내려간다 --")
stale = [{"grade": "strong", "type": "capex", "date": "2019-01"},
         {"grade": "weak", "type": "patent", "family_id": "F1", "country": "CN",
          "date": "2026-01"}]
t2, w2 = J.estimate_trl(stale, today=2026.7)
ck("2019년 STRONG 은 MEDIUM 으로 하향", "신호 소멸" in w2, w2)
ck("하향 결과 TRL 7 미만", t2 < 7, str(t2))

print("-- V6 ③: 보유 판정에 패밀리 병합과 품질 요건이 적용된다 --")
one_family = [{"grade": "weak", "type": "patent", "family_id": "F1",
               "country": c, "date": "2026-01"} for c in ("CN", "US", "EP")]
ck("같은 발명 3개국 출원은 '보유' 아님", not J.rival_holds(one_family, today=2026.7))
three_single = [{"grade": "weak", "type": "patent", "family_id": f"F{i}",
                 "country": "CN", "date": "2026-01"} for i in range(3)]
ck("단일국 공개출원 3건도 '보유' 아님(품질 요건 미충족)",
   not J.rival_holds(three_single, today=2026.7))
three_quality = three_single + [{"grade": "weak", "type": "patent",
                                 "family_id": "F9", "country": "CN",
                                 "date": "2026-01", "granted": True}]
ck("등록 특허가 섞이면 '보유'", J.rival_holds(three_quality, today=2026.7))
ck("STRONG 1건이면 즉시 '보유'",
   J.rival_holds([{"grade": "strong", "type": "capex", "date": "2026-06"}],
                 today=2026.7))
ck("근거 0건은 '보유' 아님", not J.rival_holds([]))

print("-- V6 ④: 시급도 입력값이 3축 보정분으로 바뀐다 --")
s_hi, r_hi = J.urgency(9, 4, 5, 1, "verified", 3, {}, gap_years=4.0, conf="high")
s_lo, r_lo = J.urgency(9, 4, 5, 1, "verified", 3, {}, gap_years=4.0, conf="low")
ck("신뢰도 '하'는 근거 확실성에 상한 적용", r_lo[2]["got"] <= J.CONF_PROOF_CAP["low"],
   str(r_lo[2]["got"]))
ck("신뢰도가 낮으면 점수가 내려간다", s_lo < s_hi, f"{s_lo} vs {s_hi}")
ck("격차 인자는 연수 기준", "3축 보정 기준 4년" in r_hi[0]["why"], r_hi[0]["why"])
ck("상한 적용 사실을 문구로 남긴다", "상한" in r_lo[2]["why"], r_lo[2]["why"])
s_short, _ = J.urgency(9, 4, 5, 1, "verified", 3, {}, gap_years=0.5, conf="high")
ck("격차가 짧으면 점수도 낮다", s_short < s_hi, f"{s_short} vs {s_hi}")

print("-- V6 ⑤: 듀얼 트랙 표기 --")
ck("밴드 문구", J.fmt_band(2.5, 3.4) == "약 2.5~3.4년", J.fmt_band(2.5, 3.4))
ck("차이 없으면 단일 표기", J.fmt_band(2.5, 2.5) == "약 2.5년", J.fmt_band(2.5, 2.5))
ck("격차 없으면 —", J.fmt_band(0, 0) == "—")
ck("time_gap 은 execution_years 의 별칭", J.time_gap is J.execution_years)

print("-- V6 ⑥: 기준 문서에 모델과 방어 논리가 실린다 --")
doc = J.criteria_doc()
ck("모델 항목 추가", "model" in doc and len(doc["model"]["rows"]) == 4)
ck("TRL 기준에 특허 뒷받침 규칙 명시", "TRL 6 상한" in doc["trl"]["note"],
   doc["trl"]["note"][-60:])
ck("격차 기준에 보정 계수 명시", "마케팅" in doc["lag"]["note"])
ck("시급도 기준에 신뢰도 상한 명시", "신뢰도" in doc["urgency"]["note"])
ck("보유 기준에 패밀리 병합 명시", "패밀리 병합" in doc["hold"]["note"])

print("-- V6 ⑦: 신뢰도가 기술 구분에 병기된다 --")
p = J.position(4, 9, "none", rival_source_kinds=2, rival_evidence=5, conf="low",
               conf_score=0.2)
ck("신뢰도 라벨", p["conf_label"] == "하", p["conf_label"])
ck("신뢰도 '하'는 재검증 문구", "재검증" in p["caveat"], p["caveat"])
ck("판정 근거에 신뢰도 포함", "신뢰도" in p["basis"], p["basis"])
p2 = J.position(4, 9, "none", rival_source_kinds=1, rival_evidence=5, conf="high")
ck("특허 단독 관측은 열위 판정을 유지", p2["tech_class"] == "열위")
p3 = J.position(9, 4, "have", rival_source_kinds=1, rival_evidence=5, conf="high")
ck("특허 단독 관측의 '우위'는 과대평가 가능성 병기",
   "특허 기준" in p3["label_shown"], p3["label_shown"])

print()
print("실패 없음" if not fails else f"실패: {fails}")
sys.exit(1 if fails else 0)
