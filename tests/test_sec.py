"""SEC 어댑터 오프라인 검증. 네트워크 없이 돈다."""
import os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from adapters.capex_sec import (BROWSER_UA, contact, extract_keywords,  # noqa: E402
                                fmt_date, fulltext_to_evidence, headers,
                                is_capex, propose_grade, status)

fails = []


def ck(name, cond, extra=""):
    print(("  ok   " if cond else "  FAIL ") + name + (f"  {extra}" if extra else ""))
    if not cond:
        fails.append(name)


print("-- 헤더: 방화벽은 통과하고 신원은 밝힌다 --")
os.environ["SEC_USER_AGENT"] = "LGES-CTI-research blastment@naver.com"
h = headers()
ck("UA 는 브라우저 문자열", h["User-Agent"] == BROWSER_UA, h["User-Agent"][:40])
ck("연락처는 From 헤더에", h.get("From") == "blastment@naver.com", str(h.get("From")))
ck("이메일만 뽑아낸다", contact() == "blastment@naver.com", contact())
ck("설정되면 ready", status()["ready"])

os.environ["SEC_USER_AGENT"] = ""
ck("미설정이면 not ready", not status()["ready"])
ck("미설정이면 From 헤더 없음", "From" not in headers())
os.environ["SEC_USER_AGENT"] = "LGES-CTI-research blastment@naver.com"

print("-- 전문검색 결과 → evidence --")
HIT = {
    "_id": "0001318605-25-000123:form8-k.htm",
    "_source": {"ciks": ["0001318605"],
                "display_names": ["Tesla, Inc.  (TSLA)"],
                "file_type": "8-K", "file_date": "2025-04-02"},
}
rec = fulltext_to_evidence(HIT, "dry electrode")
for k in ("type", "company", "date", "ref", "summary", "url", "grade", "source"):
    ck(f"계약 필드 {k}", k in rec)
ck("회사명에서 티커 괄호 제거", rec["company"] == "TESLA, INC.", rec["company"])
ck("source=SEC", rec["source"] == "SEC")
ck("등급은 medium (본문 언급까지만)", rec["grade"] == "medium", rec["grade"])
ck("항상 사람 확인", rec["needs_review"])
ck("날짜", rec["date"] == "2025-04-02", rec["date"])
ck("원문 링크에 CIK 앞 0 제거", "/1318605/" in rec["url"], rec["url"])
ck("원문 링크에 접수번호(하이픈 제거)", "000131860525000123" in rec["url"], rec["url"])
ck("검색어 기록", rec["match_term"] == "dry electrode")

print("-- 빈 입력에도 죽지 않는다 --")
r2 = fulltext_to_evidence({}, "x")
ck("빈 결과 처리", r2["type"] == "capex" and r2["company"] == "")
ck("링크 없으면 빈 문자열", r2["url"] == "")

print("-- 기존 순수 함수 --")
ck("날짜 형식 검사", fmt_date("2025-04-02") == "2025-04-02")
ck("잘못된 날짜는 빈 값", fmt_date("04/02/2025") == "")
ck("capex 제목 인식", is_capex("New gigafactory announcement"))
ck("무관한 제목 제외", not is_capex("Quarterly dividend declaration"))
ck("기술 키워드 추출", "battery" in extract_keywords("battery plant"))
g, _, review = propose_grade("began production at the new line")
ck("가동은 verified", g == "verified", g)
ck("verified 는 사람 확인", review)

print()
print("실패 없음" if not fails else f"실패: {fails}")
sys.exit(1 if fails else 0)
