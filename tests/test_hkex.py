"""HKEX 어댑터 오프라인 검증. 네트워크 없이 돈다.

    .venv\\Scripts\\python.exe tests\\test_hkex.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from adapters.capex_hkex import (doc_url, extract_keywords, fmt_date,  # noqa: E402
                                 is_capex, is_wrapper, month_slices,
                                 parse_rows, propose_grade, to_evidence)

fails = []


def ck(name, cond, extra=""):
    print(("  ok   " if cond else "  FAIL ") + name + (f"  {extra}" if extra else ""))
    if not cond:
        fails.append(name)


# 실호출(2026-09-13)에서 관측된 실제 제목
REAL_CAPEX = [
    "關於投資建設洛陽新能源電池生產基地項目的公告",
    "CONSTRUCTION OF NEW BATTERY PRODUCTION BASE",
    "DISCLOSEABLE TRANSACTION IN RELATION TO ACQUISITION",
    "关于扩产的公告",
]
REAL_NOT_CAPEX = [
    "CLOSURE OF REGISTER OF MEMBERS",
    "MONTHLY RETURN OF EQUITY ISSUER ON MOVEMENTS IN SECURITIES",
    "自願公告2026年8月產銷快報",                    # 월간 정기공시 — 되풀이
    "關於2026年半年度募集資金存放與使用情況的專項報告",   # 조달자금 사용처 보고
    "比亞迪股份有限公司公司債券2021年度受托管理事務報告",
    "2022 THIRD QUARTERLY REPORT",
    "NOTICE OF EXTRAORDINARY GENERAL MEETING",
]

print("-- is_capex --")
for t in REAL_CAPEX:
    ck(f"설비투자로 인식: {t[:32]}", is_capex(t))
for t in REAL_NOT_CAPEX:
    ck(f"설비투자 아님: {t[:32]}", not is_capex(t))

print("-- is_wrapper --")
ck("海外監管公告 는 포장지", is_wrapper("海外監管公告"))
ck("简体 海外监管公告 도 포장지", is_wrapper("海外监管公告"))
ck("영문 표기도 포장지", is_wrapper("OVERSEAS REGULATORY ANNOUNCEMENT"))
ck("일반 제목은 포장지 아님", not is_wrapper("CONSTRUCTION OF NEW PLANT"))
ck("포장지는 제목만으로 설비투자 판정하지 않는다", not is_capex("海外監管公告"))

print("-- fmt_date --")
ck("HKEX 날짜 변환", fmt_date("Release Time: 30/12/2022 22:39") == "2022-12-30",
   fmt_date("Release Time: 30/12/2022 22:39"))
ck("빈 값 안전", fmt_date("") == "")
ck("형식 불일치 안전", fmt_date("2022-12-30") == "")

print("-- doc_url --")
ck("상대경로에 호스트 붙음",
   doc_url("/listedco/x.pdf") == "https://www1.hkexnews.hk/listedco/x.pdf")
ck("절대경로는 그대로", doc_url("https://a/b.pdf") == "https://a/b.pdf")
ck("빈 값 안전", doc_url("") == "")

print("-- month_slices --")
sl = month_slices("20220101", "20220315")
ck("3개 구간", len(sl) == 3, str(sl))
ck("첫 구간 시작", sl[0][0] == "20220101")
ck("마지막 구간 끝이 end 를 넘지 않음", sl[-1][1] == "20220315", sl[-1][1])
ck("2월 말일 처리", sl[1] == ("20220201", "20220228"), str(sl[1]))
ck("한 달만이면 1구간", len(month_slices("20220105", "20220120")) == 1)

print("-- parse_rows --")
HTML = """<table><tr><th>x</th></tr>
<tr><td class="release-time">Release Time: 30/12/2022 22:39</td>
    <td data-code="01211" data-shortname="BYD COMPANY"></td>
    <td><a href="/listedco/listconews/sehk/2022/1230/x.pdf">CONSTRUCTION OF NEW PLANT</a></td></tr>
<tr><td>링크 없는 행</td></tr></table>"""
rows = parse_rows(HTML)
ck("링크 있는 행만 파싱", len(rows) == 1, f"{len(rows)}행")
ck("제목 추출", rows[0]["title"] == "CONSTRUCTION OF NEW PLANT", rows[0]["title"])
ck("경로 추출", rows[0]["href"].endswith("x.pdf"))
ck("날짜 추출", "30/12/2022" in rows[0]["time"], rows[0]["time"])
ck("빈 HTML 안전", parse_rows("") == [])

print("-- propose_grade --")
g, basis, review = propose_grade("The plant has commenced production in Q1")
ck("가동 확인은 verified", g == "verified", g)
ck("verified 는 항상 사람 확인", review)
g2, _, _ = propose_grade("CONSTRUCTION OF new battery plant")
ck("착공은 strong", g2 == "strong", g2)
g3, _, r3 = propose_grade("무관한 제목")
ck("근거 없으면 weak", g3 == "weak", g3)
ck("weak 도 사람 확인", r3)

print("-- to_evidence 계약 --")
rec = to_evidence({"time": "Release Time: 30/12/2022 22:39", "code": "01211",
                   "name": "BYD COMPANY", "title": "CONSTRUCTION OF NEW BATTERY PLANT",
                   "href": "/listedco/x.pdf"}, "BYD")
for k in ("type", "company", "date", "ref", "summary", "url", "grade", "source"):
    ck(f"계약 필드 {k}", k in rec)
ck("type=capex", rec["type"] == "capex")
ck("source=HKEX", rec["source"] == "HKEX")
ck("date 정규화", rec["date"] == "2022-12-30", rec["date"])
ck("기술 키워드 추출", "battery" in rec["keywords"], str(rec["keywords"]))
ck("url 완성", rec["url"].startswith("https://"), rec["url"])

print("-- 빈 입력에도 죽지 않는다 --")
rec2 = to_evidence({}, "BYD")
ck("빈 행 처리", rec2["type"] == "capex" and rec2["date"] == "")
ck("키워드 없으면 확인 대상", rec2["needs_review"])

print()
print("실패 없음" if not fails else f"실패: {fails}")
sys.exit(1 if fails else 0)
