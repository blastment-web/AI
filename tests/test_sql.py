"""GCP 자격증명 없이 돌아가는 검증. SQL 조립과 파싱만 본다.
    실행:  .venv/bin/python -m pytest tests -q     (또는 .venv/bin/python tests/test_sql.py)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.bq import (BQ, SearchParams, build_search_sql, fmt_date,  # noqa: E402
                       parse_terms, patent_url, row_to_card)


def test_parse_terms():
    assert parse_terms('dry electrode') == ['dry', 'electrode']
    assert parse_terms('"solvent free" PTFE') == ['solvent free', 'ptfe']
    assert parse_terms('a  b') == []                    # 1자 단어는 모두 버린다
    assert parse_terms('') == []
    assert len(parse_terms('a1 b2 c3 d4 e5 f6 g7')) == 5   # MAX_TERMS
    # 특수문자는 제거, 같은 단어는 한 번만 남는다
    assert parse_terms("drop'; DROP TABLE x--") == ['drop', 'table', 'x--']


def test_no_user_string_reaches_sql():
    """사용자 입력은 SQL 본문에 절대 나타나지 않고 파라미터로만 간다."""
    evil = "x' OR 1=1 --"
    sql, params = build_search_sql(SearchParams(terms=[evil], assignee=evil))
    assert evil not in sql
    assert "OR 1=1" not in sql
    assert any(p["value"] == evil for p in params)


def test_title_mode_does_not_read_abstract():
    """title 모드가 초록 컬럼을 건드리면 비용 설계가 무너진다."""
    sql, _ = build_search_sql(SearchParams(terms=['dry'], mode='title'))
    assert 'abstract_localized' not in sql
    assert 'CAST(NULL AS STRING) AS abstract_en' in sql

    sql_full, _ = build_search_sql(SearchParams(terms=['dry'], mode='full'))
    assert 'abstract_localized' in sql_full


def test_filters_and_limit():
    p = SearchParams(terms=['ptfe', 'fibrillation'], mode='full', cpc_prefix='h01m',
                     assignee='tesla', countries=['us', 'kr'],
                     date_from=20240101, date_to=20261231, limit=500)
    sql, params = build_search_sql(p)
    by = {x["name"]: x for x in params}
    assert by['cpc']['value'] == 'H01M'                  # 대문자 정규화
    assert by['cc']['value'] == ['US', 'KR']
    assert by['cc']['type'] == 'ARRAY<STRING>'
    assert by['lim']['value'] == 100                     # MAX_LIMIT 로 절삭
    assert sql.count('STRPOS') == 5                      # 2 term × (제목+초록) + assignee
    assert 'STARTS_WITH(c.code, @cpc)' in sql
    assert 'p.publication_date >= @dfrom' in sql


def test_empty_terms_rejected():
    try:
        build_search_sql(SearchParams(terms=[]))
    except ValueError:
        return
    raise AssertionError("빈 검색어가 통과했다")


def test_bq_param_conversion():
    """ARRAY 파라미터가 ArrayQueryParameter 로 변환되는지."""
    from google.cloud import bigquery
    out = BQ._to_bq_params([
        {"name": "t0", "type": "STRING", "value": "dry"},
        {"name": "cc", "type": "ARRAY<STRING>", "value": ["US"]},
        {"name": "lim", "type": "INT64", "value": 20},
    ])
    assert isinstance(out[0], bigquery.ScalarQueryParameter)
    assert isinstance(out[1], bigquery.ArrayQueryParameter)
    assert out[1].array_type == "STRING"
    assert out[2].value == 20


def test_row_to_card():
    card = row_to_card({
        "publication_number": "US-11987442-B2", "country_code": "US", "kind_code": "B2",
        "publication_date": 20260122, "filing_date": 20240301, "grant_date": 20260122,
        "title_en": "Dry electrode film lamination", "abstract_en": None,
        "assignees": "TESLA INC", "cpc_codes": "H01M4/04", "family_id": "F1",
    })
    assert card["publication_date"] == "2026-01-22"
    assert card["granted"] is True
    assert card["url"] == "https://patents.google.com/patent/US-11987442-B2/en"
    assert card["abstract"] == ""

    assert fmt_date(0) == "" and fmt_date(None) == ""
    assert row_to_card({"grant_date": 0})["granted"] is False
    assert patent_url("") == ""


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
