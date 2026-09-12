"""cninfo 어댑터 오프라인 검증. 네트워크 없이 돈다.

    .venv\\Scripts\\python.exe tests\\test_cninfo.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from adapters.capex_cninfo import (extract_keywords, fmt_date,  # noqa: E402
                                   is_capex, pdf_url, propose_grade,
                                   strip_highlight, to_evidence, viewer_url)

# 실호출(2026-09-12)에서 관측된 실제 공고 제목
REAL_CAPEX = [
    "关于投资建设匈牙利时代新能源电池产业基地项目的公告",
    "关于投资建设洛阳新能源电池生产基地项目的公告",
    "关于投资建设济宁新能源电池产业基地项目的公告",
    "关于控股子公司投资建设邦普一体化新材料产业项目的公告",
    "关于控股子公司在印度尼西亚投资建设动力电池产业链项目的公告",
]
REAL_NOISE = [
    "《对外投资管理制度》（2025年12月修订）",
    "关于2026年半年度募集资金存放与使用情况的专项报告",
    "宁德时代新能源科技股份有限公司2026年面向专业投资者公开发行科技创新公司债券（第二期）募集说明书",
    "关于首次回购公司A股股份的公告",
    "关于2022年股票期权与限制性股票激励计划部分股票期权注销完成的公告",
    "第四届董事会第十九次会议决议公告",
    "H股公告（翌日披露报表）",
    "上海市通力律师事务所关于宁德时代新能源科技股份有限公司2022年股票期权的法律意见书",
]


def test_capex_filter_keeps_real_announcements():
    for t in REAL_CAPEX:
        assert is_capex(t), f"설비투자 공고를 놓쳤다: {t}"


def test_capex_filter_drops_real_noise():
    """'投资'만으로 거르면 회사채·펀드·내부규정이 섞인다(실호출에서 확인)."""
    for t in REAL_NOISE:
        assert not is_capex(t), f"노이즈가 통과했다: {t}"


def test_exclude_beats_include():
    """제외 패턴이 포함 패턴보다 우선해야 한다."""
    assert not is_capex("《对外投资管理制度》关于投资建设的规定")


def test_grade_strong_on_construction():
    g, basis, review = propose_grade("关于投资建设匈牙利时代新能源电池产业基地项目的公告")
    assert g == "strong" and basis


def test_grade_verified_always_needs_review():
    g, basis, review = propose_grade("洛阳基地正式投产的公告")
    assert g == "verified"
    assert review is True, "VERIFIED 자동 확정은 근거 없는 등급을 만든다"


def test_grade_falls_back_to_weak():
    g, basis, review = propose_grade("기타 공고")
    assert g == "weak" and review is True


def test_keywords_extracted():
    kws = extract_keywords("关于投资建设匈牙利时代新能源电池产业基地项目的公告")
    assert "电池" in kws and "产业基地" in kws
    assert extract_keywords("") == []


def test_strip_highlight():
    assert strip_highlight("关于<em>投资</em>建设") == "关于投资建设"
    assert strip_highlight("") == ""


def test_fmt_date_from_epoch_ms():
    assert fmt_date(1660320000000).startswith("2022-08")
    assert fmt_date(0) == "" and fmt_date(None) == ""


def test_urls():
    assert pdf_url("finalpage/2022-08-13/1214282839.PDF").startswith(
        "http://static.cninfo.com.cn/")
    assert pdf_url("") == ""
    assert "announcementId=123" in viewer_url("123", "GD165627", "300750")
    assert viewer_url("", "GD165627", "300750") == ""


def test_to_evidence_matches_tree_contract():
    import json
    contract = set(json.loads((ROOT / "data" / "tree.sample.json")
                              .read_text(encoding="utf-8"))["nodes"][0]["evidence"][0])
    ann = {"announcementTitle": "关于投资建设匈牙利时代新能源电池产业基地项目的公告",
           "announcementId": "1214282839", "announcementTime": 1660320000000,
           "secCode": "300750", "secName": "宁德时代",
           "adjunctUrl": "finalpage/2022-08-13/1214282839.PDF"}
    rec = to_evidence(ann, "CATL", "GD165627", "300750")
    assert contract <= set(rec), f"누락 필드: {contract - set(rec)}"
    assert rec["type"] == "capex" and rec["company"] == "CATL"
    assert rec["grade"] == "strong"
    assert rec["source"] == "cninfo"
    assert rec["needs_review"] is False        # 기술 키워드가 있으므로
    assert rec["pdf_url"].endswith(".PDF")


def test_to_evidence_no_keyword_forces_review():
    ann = {"announcementTitle": "关于投资建设办公楼项目的公告",
           "announcementId": "1", "announcementTime": 1660320000000}
    rec = to_evidence(ann, "CATL", "GD165627", "300750")
    assert rec["keywords"] == []
    assert rec["needs_review"] is True


def test_to_evidence_survives_missing_fields():
    rec = to_evidence({}, "BYD", "gshk0001211", "002594")
    assert rec["company"] == "BYD"
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
