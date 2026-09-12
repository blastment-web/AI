"""KIPRIS 어댑터 오프라인 검증. 네트워크·키 없이 돈다."""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from adapters.patent_kipris import (KiprisError, detail_url,  # noqa: E402
                                    extract_keywords, fmt_date, map_company,
                                    parse_items, redact, status, to_evidence)

FAKE_KEY = "ZZfakekipriskey1234567890abcdefZZ1234567890ab"

# 실호출(2026-09-12)에서 받은 응답 구조 그대로. 태그는 PascalCase.
SAMPLE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<response>
  <header><resultCode>00</resultCode><resultMsg>success</resultMsg></header>
  <body><items>
    <PatentUtilityInfo>
      <Applicant>주식회사 엘지에너지솔루션</Applicant>
      <ApplicationDate>20240726</ApplicationDate>
      <ApplicationNumber>1020240099189</ApplicationNumber>
      <Abstract>이차전지 건식 전극 형성장치. 활물질판과 집전체 사이의 합지를 위한 롤러들.</Abstract>
      <InventionName>이차전지 건식 전극 형성장치</InventionName>
      <InternationalpatentclassificationNumber>H01M 4/04|B30B 3/04</InternationalpatentclassificationNumber>
      <OpeningDate>20260203</OpeningDate>
      <OpeningNumber>1020260016111</OpeningNumber>
      <PublicNumber></PublicNumber>
      <PublicDate>20260904</PublicDate>
      <RegistrationDate>20260831</RegistrationDate>
      <RegistrationNumber>1030140260000</RegistrationNumber>
      <RegistrationStatus>등록</RegistrationStatus>
    </PatentUtilityInfo>
    <PatentUtilityInfo>
      <Applicant>나노인텍 주식회사</Applicant>
      <ApplicationDate>20241126</ApplicationDate>
      <ApplicationNumber>1020240170849</ApplicationNumber>
      <Abstract>AI 분석을 통한 건식전극코팅 공정 최적화 시스템.</Abstract>
      <InventionName>건식전극코팅 공정 최적화 시스템</InventionName>
      <InternationalpatentclassificationNumber>H01M 4/04</InternationalpatentclassificationNumber>
      <OpeningDate>20250610</OpeningDate>
      <OpeningNumber>1020250083264</OpeningNumber>
      <PublicNumber></PublicNumber>
      <PublicDate></PublicDate>
      <RegistrationDate></RegistrationDate>
      <RegistrationNumber></RegistrationNumber>
      <RegistrationStatus>공개</RegistrationStatus>
    </PatentUtilityInfo>
    <TotalSearchCount>88306</TotalSearchCount>
    <SearchStartNumber>1</SearchStartNumber>
  </items></body>
</response>"""

ERROR_XML = """<?xml version="1.0" encoding="UTF-8"?>
<response><header><resultCode>30</resultCode>
<resultMsg>SERVICE_KEY_IS_NOT_REGISTERED_ERROR</resultMsg></header></response>"""


def test_parse_items_pascal_case():
    items, total = parse_items(SAMPLE_XML)
    assert total == 88306
    assert len(items) == 2
    assert items[0]["InventionName"] == "이차전지 건식 전극 형성장치"
    assert items[0]["RegistrationStatus"] == "등록"


def test_parse_items_raises_on_error_code():
    try:
        parse_items(ERROR_XML)
    except KiprisError as e:
        assert "30" in str(e)
        return
    raise AssertionError("오류 코드가 통과했다")


def test_registration_status_maps_to_grade_ladder():
    """GRADE 사다리: 등록 = MEDIUM(구체적 공정 조건), 공개 = WEAK."""
    items, _ = parse_items(SAMPLE_XML)
    assert to_evidence(items[0])["grade"] == "medium"    # 등록
    assert to_evidence(items[1])["grade"] == "weak"      # 공개


def test_registered_patent_still_needs_review():
    """초록만 읽고 MEDIUM 을 확정하면 청구항 없이 등급을 준 것이 된다."""
    items, _ = parse_items(SAMPLE_XML)
    rec = to_evidence(items[0])
    assert rec["grade"] == "medium"
    assert rec["needs_review"] is True


def test_to_evidence_matches_tree_contract():
    contract = set(json.loads((ROOT / "data" / "tree.sample.json")
                              .read_text(encoding="utf-8"))["nodes"][0]["evidence"][0])
    items, _ = parse_items(SAMPLE_XML)
    rec = to_evidence(items[0])
    assert contract <= set(rec), f"누락 필드: {contract - set(rec)}"
    assert rec["type"] == "patent"
    assert rec["company"] == "LGES"
    assert rec["date"] == "2026-08-31"                    # 등록일 우선
    assert rec["ref"] == "1030140260000"
    assert rec["source"] == "KIPRIS"
    assert "1020240099189" in rec["url"]


def test_company_mapping():
    assert map_company("주식회사 엘지에너지솔루션") == "LGES"
    assert map_company("삼성에스디아이 주식회사") == "SAMSUNG SDI"
    assert map_company("에스케이온 주식회사") == "SK ON"
    assert map_company("나노인텍 주식회사") == "나노인텍 주식회사"   # 미매칭은 원문 유지


def test_date_fallback_chain():
    """등록일 없으면 공개일, 그것도 없으면 출원일."""
    items, _ = parse_items(SAMPLE_XML)
    assert to_evidence(items[1])["date"] == "2025-06-10"   # 공개일
    assert fmt_date("") == "" and fmt_date("2026") == ""


def test_keywords_and_urls():
    assert "건식" in extract_keywords("이차전지 건식 전극 형성장치")
    assert extract_keywords("") == []
    assert detail_url("1020240099189").endswith("applno=1020240099189")
    assert detail_url("") == ""


def test_redact_hides_access_key():
    """KIPRIS 도 키를 쿼리스트링으로 받는다. URL 로깅이 곧 키 유출이다."""
    os.environ["KIPRIS_API_KEY"] = FAKE_KEY
    try:
        url = f"{'http://plus.kipris.or.kr/x'}?word=a&accessKey={FAKE_KEY}"
        out = redact(url)
        assert FAKE_KEY not in out and "accessKey=***" in out
        assert FAKE_KEY not in redact(f"오류: 키 {FAKE_KEY} 로 시도")
    finally:
        os.environ.pop("KIPRIS_API_KEY", None)


def test_status_without_key():
    os.environ.pop("KIPRIS_API_KEY", None)
    st = status()
    assert st["ready"] is False and "KIPRIS_API_KEY" in st["reason"]


def test_to_evidence_survives_missing_fields():
    rec = to_evidence({})
    assert rec["type"] == "patent"
    assert rec["date"] == "" and rec["url"] == ""
    assert rec["needs_review"] is True


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ok   {name}")
            except Exception as e:
                fails += 1
                print(f"  FAIL {name}: {type(e).__name__}: {e}")
    print("실패 없음" if not fails else f"{fails}건 실패")
    sys.exit(1 if fails else 0)
