"""OpenAlex 어댑터 오프라인 검증. 네트워크 없이 돈다."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from adapters.conf_openalex import (affiliations, companies_in,  # noqa: E402
                                    is_conference, to_evidence, venue_of, work_url)

fails = []


def ck(name, cond, extra=""):
    print(("  ok   " if cond else "  FAIL ") + name + (f"  {extra}" if extra else ""))
    if not cond:
        fails.append(name)


W = {
    "id": "https://openalex.org/W123", "doi": "https://doi.org/10.1/x",
    "display_name": "Dry electrode processing for lithium-ion cells",
    "publication_date": "2025-03-01", "type": "article", "cited_by_count": 7,
    "primary_location": {"source": {"display_name": "Journal of Power Sources",
                                    "type": "journal"}},
    "authorships": [
        {"raw_affiliation_strings": ["LG Energy Solution, Daejeon, Korea"],
         "institutions": [{"display_name": "LG Energy Solution"}]},
        {"raw_affiliation_strings": ["Seoul National University"], "institutions": []},
    ],
}

print("-- 소속에서 회사 가려내기 --")
ck("소속 문자열 수집", len(affiliations(W)) == 3, str(len(affiliations(W))))
ck("LGES 인식", companies_in(W) == ["LGES"], str(companies_in(W)))

def co(auth):
    return companies_in({"authorships": [{"raw_affiliation_strings": [auth],
                                          "institutions": []}]})

ck("삼성SDI 인식", co("Samsung SDI Co., Ltd.") == ["SAMSUNG SDI"])
ck("CATL 정식명 인식", co("Contemporary Amperex Technology Co. Ltd") == ["CATL"])
ck("파나소닉 인식", co("Panasonic Corporation") == ["PANASONIC"])
ck("무관한 소속은 빈 목록", co("Seoul National University") == [])
# 'Tesla' 는 체코 동명 회사가 있어 정식 표기만 받는다
ck("Tesla, Inc. 는 인식", co("Tesla, Inc., Palo Alto") == ["TESLA"])
ck("체코 Tesla 는 제외", co("Tesla Praha, Czechia") == [], str(co("Tesla Praha, Czechia")))

print("-- 학회 여부 --")
ck("저널은 학회 아님", not is_conference(W))
conf = {**W, "type": "proceedings-article"}
ck("프로시딩은 학회", is_conference(conf))
ck("빈 입력 안전", not is_conference({}))

print("-- 부가 정보 --")
ck("학술지명", venue_of(W) == "Journal of Power Sources", venue_of(W))
ck("DOI 링크", work_url(W) == "https://doi.org/10.1/x")
ck("DOI 없으면 대체 링크", work_url({"id": "https://openalex.org/W9",
                                     "primary_location": {}}) == "https://openalex.org/W9")

print("-- evidence 계약 --")
rec = to_evidence(W, "LGES", "dry electrode")
for k in ("type", "company", "date", "ref", "summary", "url", "grade", "source"):
    ck(f"계약 필드 {k}", k in rec)
ck("type=paper (특허와 다른 소스 종류)", rec["type"] == "paper", rec["type"])
ck("source=OpenAlex", rec["source"] == "OpenAlex")
ck("등급 상한은 medium", rec["grade"] == "medium", rec["grade"])
ck("항상 사람 확인 대상", rec["needs_review"])
ck("날짜 그대로", rec["date"] == "2025-03-01")

print("-- 빈 입력에도 죽지 않는다 --")
r2 = to_evidence({}, "CATL", "x")
ck("빈 논문 처리", r2["type"] == "paper" and r2["date"] == "")
ck("소속 없으면 빈 목록", companies_in({}) == [])

print()
print("실패 없음" if not fails else f"실패: {fails}")
sys.exit(1 if fails else 0)
