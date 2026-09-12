"""DART 어댑터 오프라인 검증. 자격증명·네트워크 없이 돈다.

    .venv/bin/python tests/test_dart.py
"""
import io
import json
import os
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
FIX = ROOT / "tests" / "fixtures"

from adapters.capex_dart import (Dart, NotConfigured,  # noqa: E402
                                 clean_document_html, extract_keywords,
                                 fmt_date, matches_report, norm,
                                 parse_corpcode_zip, propose_grade, redact,
                                 resolve_targets, status, to_evidence,
                                 viewer_url)

FAKE_KEY = "abcdef0123456789abcdef0123456789abcdef01"   # 40자, 형식만 흉내


def _zip_corpcode() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("CORPCODE.xml", (FIX / "dart_corpcode.xml").read_bytes())
    return buf.getvalue()


def _list_fixture() -> dict:
    return json.loads((FIX / "dart_list.json").read_text(encoding="utf-8"))


# ── 키 취급 ────────────────────────────────────────────────────────
def test_status_without_key():
    os.environ.pop("DART_API_KEY", None)
    st = status()
    assert st["ready"] is False
    assert "DART_API_KEY" in st["reason"]


def test_status_rejects_short_key():
    os.environ["DART_API_KEY"] = "short"
    try:
        assert status()["ready"] is False
    finally:
        os.environ.pop("DART_API_KEY", None)


def test_redact_removes_key_from_url():
    """DART 는 키를 쿼리스트링으로 받는다. URL 로깅이 곧 키 유출이다."""
    url = f"https://opendart.fss.or.kr/api/list.json?crtfc_key={FAKE_KEY}&corp_code=00000001"
    out = redact(url)
    assert FAKE_KEY not in out
    assert "crtfc_key=***" in out
    assert "corp_code=00000001" in out          # 나머지 정보는 남아야 디버깅이 된다


def test_redact_removes_bare_key_anywhere():
    os.environ["DART_API_KEY"] = FAKE_KEY
    try:
        msg = f"연결 실패: 인증키 {FAKE_KEY} 로 시도함"
        assert FAKE_KEY not in redact(msg)
    finally:
        os.environ.pop("DART_API_KEY", None)


def test_client_without_key_raises_notconfigured():
    os.environ.pop("DART_API_KEY", None)
    try:
        Dart(key="")._require()
    except NotConfigured:
        return
    raise AssertionError("키 없이 호출이 통과했다")


# ── corp_code 해결 ─────────────────────────────────────────────────
def test_parse_corpcode_zip():
    corps = parse_corpcode_zip(_zip_corpcode())
    assert len(corps) == 5
    assert corps[0]["corp_code"] == "00000001"
    assert corps[0]["corp_name"] == "삼성에스디아이"


def test_resolve_targets_exact_match_wins():
    """'삼성에스디아이서비스' 같은 부분일치보다 완전일치가 앞서야 한다."""
    r = resolve_targets(parse_corpcode_zip(_zip_corpcode()))
    assert r["SAMSUNG SDI"]["corp_code"] == "00000001"
    assert r["SAMSUNG SDI"]["corp_name"] == "삼성에스디아이"
    assert r["SK ON"]["corp_code"] == "00000002"          # 비상장, 종목코드 없음
    assert r["LGES"]["corp_code"] == "00000003"
    # 사람이 확인할 수 있게 후보를 남긴다
    assert len(r["SAMSUNG SDI"]["candidates"]) >= 2


def test_resolve_targets_reports_unresolved():
    r = resolve_targets(parse_corpcode_zip(_zip_corpcode()),
                        [{"key": "NOPE", "aliases": ["없는회사"], "stock_code": ""}])
    assert r["NOPE"]["corp_code"] == ""
    assert r["NOPE"]["candidates"] == []


def test_norm_strips_legal_forms():
    assert norm("주식회사 삼성에스디아이") == norm("삼성에스디아이")
    assert norm("(주)엘지에너지솔루션") == norm("엘지에너지솔루션")


# ── 공시 필터 ──────────────────────────────────────────────────────
def test_report_filter_keeps_capex_only():
    """픽스처는 실호출에서 관측된 report_nm 이다."""
    rows = _list_fixture()["list"]
    kept = [r for r in rows if matches_report(r["report_nm"])]
    names = [r["report_nm"] for r in kept]
    assert "신규시설투자등" in names
    assert "유형자산취득결정(종속회사의주요경영사항)" in names
    assert "[기재정정]유형자산취득결정(종속회사의주요경영사항)" in names   # 정정본도 잡아야 한다
    assert len(kept) == 3


def test_report_filter_excludes_investment_judgment():
    """'투자판단관련주요경영사항'은 M&A·JV·공급계약을 담는 포괄 카테고리다.

    실호출 검증에서 이 패턴이 잡은 9건 중 7건이 합작법인 지분거래·공급계약이었다.
    다시 넣으면 노이즈가 되돌아오므로 회귀로 고정한다.
    """
    assert not matches_report("투자판단관련주요경영사항")
    assert not matches_report("투자설명서")            # 증권신고서 계열
    assert not matches_report("임원ㆍ주요주주특정증권등소유상황보고서")
    assert not matches_report("분기보고서 (2026.03)")


# ── evidence 변환 ──────────────────────────────────────────────────
def test_to_evidence_matches_tree_contract():
    """data/tree.sample.json 의 evidence 필드를 빠짐없이 채워야 한다."""
    contract = set(json.loads((ROOT / "data" / "tree.sample.json")
                              .read_text(encoding="utf-8"))["nodes"][0]["evidence"][0])
    rec = to_evidence(_list_fixture()["list"][0], "LGES")
    assert contract <= set(rec), f"누락 필드: {contract - set(rec)}"
    assert rec["type"] == "capex"
    assert rec["company"] == "LGES"
    assert rec["date"] == "2025-04-01"
    assert rec["ref"] == "유형자산취득결정(종속회사의주요경영사항)"
    assert rec["url"] == "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20250401000123"
    assert rec["rcept_no"] == "20250401000123"
    assert rec["source"] == "DART"


def test_fmt_date_and_url_edge_cases():
    assert fmt_date("20260211") == "2026-02-11"
    assert fmt_date("") == ""
    assert fmt_date("2026") == "2026"
    assert viewer_url("") == ""


def test_to_evidence_survives_missing_fields():
    rec = to_evidence({}, "SK ON")
    assert rec["company"] == "SK ON"
    assert rec["date"] == "" and rec["url"] == ""
    assert rec["needs_review"] is True


# ── 등급 제안 ──────────────────────────────────────────────────────
def test_grade_strong_on_new_construction():
    g, basis, review = propose_grade("신규 시설투자 등 — 신설 라인 착공 예정")
    assert g == "strong"
    assert basis and "신설" in basis


def test_grade_verified_always_needs_review():
    """VERIFIED 는 가장 강한 주장이라 규칙이 맞아도 사람이 확인해야 한다."""
    g, basis, review = propose_grade("기존 양산 가동 라인에 증설 투자")
    assert g == "verified"
    assert review is True, "VERIFIED 가 자동 확정되면 근거 없는 등급이 생긴다"
    assert basis


def test_grade_falls_back_to_weak_with_review():
    g, basis, review = propose_grade("특이사항 없음")
    assert g == "weak" and review is True and basis == ""


def test_keywords_extracted_for_node_mapping():
    kws = extract_keywords("전극 코팅 라인 및 건식 공정 설비 신설")
    assert "전극" in kws and "코팅" in kws and "건식" in kws
    assert extract_keywords("") == []


def test_no_tech_keyword_forces_review():
    """기술 키워드가 없으면 어느 노드에도 못 붙인다 — 등급이 맞아도 사람이 봐야 한다."""
    rec = to_evidence({"report_nm": "신규시설투자등", "rcept_dt": "20260211",
                       "rcept_no": "1"}, "SAMSUNG SDI")
    assert rec["grade"] == "strong"          # 규칙은 맞았지만
    assert rec["keywords"] == []
    assert rec["needs_review"] is True       # 노드 매핑이 불가하므로 확인 대상


def test_tech_keyword_allows_auto_pass():
    rec = to_evidence({"report_nm": "신규시설투자등", "rcept_dt": "20260211", "rcept_no": "1"},
                      "SAMSUNG SDI", detail_text="전극 코팅 라인 신설 투자")
    assert rec["grade"] == "strong"
    assert "전극" in rec["keywords"]
    assert rec["needs_review"] is False


# ── 원문 정제 ──────────────────────────────────────────────────────
def test_clean_document_strips_style_body():
    """실제 DART 공시는 앞머리에 대형 <style> 블록이 있다.

    태그만 지우면 CSS 가 요약문을 통째로 차지한다(실호출에서 확인된 결함).
    """
    raw = ('<html><head><style type="text/css">.xforms * { font-family: 돋움체;} '
           '.xforms table { font-size: 10px; }</style></head>'
           '<body><p>유형자산 취득결정</p><p>전극 코팅 라인 신설</p>'
           '<script>var a=1;</script></body></html>')
    out = clean_document_html(raw)
    assert "font-family" not in out
    assert "xforms" not in out
    assert "var a" not in out
    assert "유형자산 취득결정" in out
    assert "전극 코팅 라인 신설" in out


def test_clean_document_unescapes_entities():
    assert clean_document_html("<p>A&nbsp;B&amp;C</p>").replace("\xa0", " ") == "A B&C"
    assert clean_document_html("") == ""


# ── 응답 상태 처리 ─────────────────────────────────────────────────
def test_empty_response_is_not_an_error():
    data = json.loads((FIX / "dart_list_empty.json").read_text(encoding="utf-8"))
    assert data["status"] == "013"          # 어댑터는 이를 빈 목록으로 처리한다


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
