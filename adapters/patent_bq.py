"""Google Patents(BigQuery) — 경쟁사 특허 대량 추출 어댑터.

기술명으로 검색하면 국내 중소기업 특허가 대부분 잡힌다(실측: 1,304건 중 경쟁사 66건).
경쟁사 판정을 하려면 **출원인으로 직접 끌어와야** 한다. 이 어댑터가 그 일을 한다.

비용 — 이 테이블은 파티셔닝이 없어 WHERE 절이 스캔량을 줄이지 않는다. 읽는 컬럼이
비용을 결정하므로 제목·출원인·날짜만 읽고 초록은 읽지 않는다(초록은 +153GB).
한 번 퍼오면 로컬에 쌓이므로 이후 조회는 공짜다.

법인명 분산 — 경쟁사 하나가 법인명 10개 이상으로 흩어져 있다(파나소닉 10+, CATL 5).
ASSIGNEE_PATTERNS 가 그 변형을 하나의 키로 묶는다. 이게 없으면 CATL 로 검색할 때
NINGDE CONTEMPORARY AMPEREX 20,819건을 통째로 놓친다.
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.bq import bq  # noqa: E402

TABLE = "`patents-public-data.patents.publications`"

# 법인명 변형 → 하나의 경쟁사 키. 실측(2026-09-12)으로 확인한 표기들.
ASSIGNEE_PATTERNS = {
    "CATL":        r"CONTEMPORARY AMPEREX|NINGDE CONTEMPORARY|宁德时代",
    "BYD":         r"\bBYD\b",
    "SAMSUNG SDI": r"SAMSUNG SDI",
    "SK ON":       r"SK ON|SK INNOVATION",
    "TESLA":       r"TESLA",
    "PANASONIC":   r"PANASONIC",
    "LGES":        r"LG ENERGY SOLUTION",
}

# 전지 관련 CPC 로 좁힌다. 스캔 비용은 늘지만(+14GB) 노이즈가 크게 줄어
# 한 번 퍼올 때 쓸모 있는 것만 담긴다.
BATTERY_CPC = ("H01M", "H01G", "C01B", "B60L")


RESEARCH = "`patents-public-data.google_patents_research.publications`"


def build_sql(since_year: int, limit: int, use_cpc: bool,
              with_citations: bool = False) -> str:
    pat = "|".join(f"(?:{v})" for v in ASSIGNEE_PATTERNS.values())
    cpc_join = (
        ",\n  (SELECT STRING_AGG(DISTINCT c.code, ',' ORDER BY c.code LIMIT 5)\n"
        "     FROM UNNEST(p.cpc) c) AS cpc_codes" if use_cpc else
        ",\n  CAST(NULL AS STRING) AS cpc_codes")
    cpc_where = ("\n  AND EXISTS(SELECT 1 FROM UNNEST(p.cpc) c WHERE "
                 + " OR ".join(f'STARTS_WITH(c.code, "{c}")' for c in BATTERY_CPC)
                 + ")") if use_cpc else ""
    if with_citations:
        # 피인용 수는 publications 테이블에 없다. research 테이블에서 붙인다.
        # LEFT JOIN 이므로 매칭되지 않는 건은 0 으로 남는다(피인용 0 과 구분 불가).
        return f"""
WITH pubs AS (
  SELECT
    p.publication_number,
    p.country_code,
    p.kind_code,
    p.publication_date,
    p.grant_date,
    p.family_id,
    (SELECT t.text FROM UNNEST(p.title_localized) t
      WHERE t.language IN ('en','EN') LIMIT 1) AS title_en,
    (SELECT STRING_AGG(DISTINCT a.name, ' | ' ORDER BY a.name LIMIT 3)
       FROM UNNEST(p.assignee_harmonized) a) AS assignees{cpc_join.replace(chr(10) + "  ", chr(10) + "    ")}
  FROM {TABLE} AS p
  WHERE EXISTS(
      SELECT 1 FROM UNNEST(p.assignee_harmonized) a
      WHERE REGEXP_CONTAINS(UPPER(a.name), r"{pat}"))
    AND p.publication_date >= {since_year}0101{cpc_where.replace(chr(10) + "  ", chr(10) + "    ")}
),
cites AS (
  SELECT publication_number, ARRAY_LENGTH(cited_by) AS cited_by_n
  FROM {RESEARCH}
)
SELECT pubs.*, IFNULL(cites.cited_by_n, 0) AS cited_by_n
FROM pubs LEFT JOIN cites USING (publication_number)
ORDER BY pubs.publication_date DESC
LIMIT {limit}
""".strip()
    return f"""
SELECT
  p.publication_number,
  p.country_code,
  p.kind_code,
  p.publication_date,
  p.grant_date,
  p.family_id,
  (SELECT t.text FROM UNNEST(p.title_localized) t
    WHERE t.language IN ('en','EN') LIMIT 1) AS title_en,
  (SELECT STRING_AGG(DISTINCT a.name, ' | ' ORDER BY a.name LIMIT 3)
     FROM UNNEST(p.assignee_harmonized) a) AS assignees{cpc_join}
FROM {TABLE} AS p
WHERE EXISTS(
    SELECT 1 FROM UNNEST(p.assignee_harmonized) a
    WHERE REGEXP_CONTAINS(UPPER(a.name), r"{pat}"))
  AND p.publication_date >= {since_year}0101{cpc_where}
ORDER BY p.publication_date DESC
LIMIT {limit}
""".strip()


def company_of(assignees: str) -> str:
    import re
    up = (assignees or "").upper()
    for key, pat in ASSIGNEE_PATTERNS.items():
        if re.search(pat, up):
            return key
    return (assignees or "").strip()


def fmt_date(v) -> str:
    s = str(v or "")
    return f"{s[0:4]}-{s[4:6]}-{s[6:8]}" if len(s) == 8 and s.isdigit() else ""


def to_evidence(row: dict) -> dict:
    pub = row.get("publication_number") or ""
    granted = bool(row.get("grant_date"))
    title = (row.get("title_en") or "").strip()
    # GRADE 사다리: 등록특허 = MEDIUM(구체적 공정 조건), 공개 = WEAK
    grade = "medium" if granted else "weak"
    return {
        "type": "patent",
        "company": company_of(row.get("assignees", "")),
        "date": fmt_date(row.get("grant_date") or row.get("publication_date")),
        "ref": pub,
        "summary": title[:300],
        "url": f"https://patents.google.com/patent/{pub}/en" if pub else "",
        "grade": grade,
        "assignees": (row.get("assignees") or "").strip(),
        "country": row.get("country_code", ""),
        "kind": row.get("kind_code", ""),
        "family_id": str(row.get("family_id") or ""),
        "cpc": row.get("cpc_codes") or "",
        "granted": granted,
        # 피인용 수 — 특허 영향력 지표. research 테이블 미매칭 시 None 으로 남긴다
        # ('피인용 0' 과 '확인 불가'를 구분해야 품질 가중을 잘못 주지 않는다).
        "cited_by": (int(row["cited_by_n"])
                     if row.get("cited_by_n") is not None else None),
        "keywords": [],
        # 초록·청구항을 읽지 않았으므로 MEDIUM 을 확정으로 보지 않는다
        "needs_review": granted,
        "source": "BigQuery",
        "collected_at": datetime.datetime.now(
            datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="BigQuery 경쟁사 특허 대량 추출")
    # LIMIT 은 BigQuery 비용과 무관하다(스캔량은 읽는 컬럼이 결정함).
    # 기존 4만 상한 때문에 최근 2년치만 남고 과거가 잘려 있었다.
    ap.add_argument("--since", type=int, default=2010, help="공개연도 하한")
    ap.add_argument("--limit", type=int, default=300000)
    ap.add_argument("--with-citations", action="store_true",
                    help="피인용 수 포함(+21.6GB, research 테이블 결합)")
    ap.add_argument("--max-scan-gb", type=float, default=0,
                    help="이 실행에 한해 스캔 상한을 올린다(견적을 보고 명시 승인할 때만)")
    ap.add_argument("--no-cpc", action="store_true", help="CPC 필터 끄기(비용 -14GB, 노이즈 증가)")
    ap.add_argument("--out", default="data/evidence_bq.jsonl")
    ap.add_argument("--estimate", action="store_true", help="dry-run 견적만 (과금 0)")
    a = ap.parse_args(argv)

    sql = build_sql(a.since, a.limit, not a.no_cpc, a.with_citations)
    GB = 1024 ** 3
    try:
        est = bq.estimate(sql, [])
    except Exception as e:
        print(f"견적 실패: {type(e).__name__}: {str(e)[:160]}")
        return 1
    print(f"스캔 예상 {est/GB:.2f} GB  (월 무료 1TB 기준 {est/GB/1024*100:.1f}% 소모)")
    if a.estimate:
        return 0

    # 상한은 사고 방지용이다. 견적을 보고 올리는 경우에만, 이 실행에 한해 연다.
    if a.max_scan_gb:
        from server import config
        if est > a.max_scan_gb * GB:
            print(f"승인한 상한 {a.max_scan_gb}GB 를 견적 {est/GB:.2f}GB 가 초과합니다. 중단합니다.")
            return 1
        config.MAX_SCAN_BYTES = int(a.max_scan_gb * GB)
        print(f"이 실행에 한해 스캔 상한 {a.max_scan_gb}GB 적용")

    try:
        res = bq.run(sql, [])
    except Exception as e:
        print(f"실행 실패: {type(e).__name__}: {str(e)[:200]}")
        return 1

    recs = [to_evidence(r) for r in res["rows"]]
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    import collections
    co = collections.Counter(r["company"] for r in recs)
    yrs = collections.Counter((r["date"] or "")[:4] for r in recs)
    cited = [r["cited_by"] for r in recs if r.get("cited_by")]
    print(f"청구 {res['billed_bytes']/GB:.2f} GB · {len(recs):,}건 → {a.out}")
    print(f"  공개연도 {min(y for y in yrs if y)}~{max(yrs)} · "
          f"피인용 확보 {len(cited):,}건")
    for k, v in co.most_common(10):
        print(f"  {k:14} {v:,}건")
    return 0


if __name__ == "__main__":
    sys.exit(main())
