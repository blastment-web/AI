"""BigQuery `patents-public-data` 조회 계층.

이 모듈이 지키는 두 가지:
  1. 클라이언트가 보낸 문자열은 절대 SQL 에 문자열 결합하지 않는다 (전량 쿼리 파라미터).
  2. 실행 전 dry-run 으로 스캔량을 재고, 상한을 넘으면 실행하지 않는다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from . import config

TABLE = "`patents-public-data.patents.publications`"
MAX_TERMS = 5
MAX_LIMIT = 100

# 검색어에서 허용할 문자. 파라미터 바인딩으로 주입은 이미 막히지만,
# 와일드카드 남용으로 스캔량이 폭주하는 것을 앞단에서 줄인다.
_TERM_CLEAN = re.compile(r"[^0-9a-z가-힣\s\-\+/\.]")


class QueryTooLarge(Exception):
    def __init__(self, estimated: int, cap: int):
        self.estimated = estimated
        self.cap = cap
        super().__init__("스캔 예상량이 상한을 초과")


class NotConfigured(Exception):
    pass


@dataclass
class SearchParams:
    terms: list[str]
    mode: str = "title"            # title | full  (full 은 초록까지 스캔 = 고비용)
    cpc_prefix: str = ""           # 예: H01M
    assignee: str = ""
    countries: list[str] = field(default_factory=list)
    date_from: int = 0             # YYYYMMDD
    date_to: int = 0
    limit: int = 20


def parse_terms(q: str) -> list[str]:
    """따옴표 구문은 한 덩어리로, 나머지는 공백 분리."""
    q = (q or "").lower().strip()
    phrases = re.findall(r'"([^"]+)"', q)
    rest = re.sub(r'"[^"]*"', " ", q)
    words = [w for w in rest.split() if len(w) >= 2]
    out: list[str] = []
    for t in phrases + words:
        t = _TERM_CLEAN.sub(" ", t).strip()
        t = re.sub(r"\s+", " ", t)
        if len(t) >= 2 and t not in out:
            out.append(t)
    return out[:MAX_TERMS]


def build_search_sql(p: SearchParams) -> tuple[str, list[dict]]:
    """(sql, 파라미터 목록) 반환. 파라미터는 main 에서 BigQuery 타입으로 변환한다."""
    if not p.terms:
        raise ValueError("검색어가 비어 있습니다.")

    params: list[dict] = []
    where: list[str] = []

    for i, term in enumerate(p.terms):
        name = f"t{i}"
        params.append({"name": name, "type": "STRING", "value": term})
        title_hit = (
            f"EXISTS(SELECT 1 FROM UNNEST(p.title_localized) t "
            f"WHERE t.language IN ('en','EN') AND STRPOS(LOWER(t.text), @{name}) > 0)"
        )
        if p.mode == "full":
            abs_hit = (
                f"EXISTS(SELECT 1 FROM UNNEST(p.abstract_localized) a "
                f"WHERE a.language IN ('en','EN') AND STRPOS(LOWER(a.text), @{name}) > 0)"
            )
            where.append(f"({title_hit} OR {abs_hit})")
        else:
            where.append(title_hit)

    if p.cpc_prefix:
        params.append({"name": "cpc", "type": "STRING", "value": p.cpc_prefix.upper()})
        where.append("EXISTS(SELECT 1 FROM UNNEST(p.cpc) c WHERE STARTS_WITH(c.code, @cpc))")

    if p.assignee:
        params.append({"name": "asg", "type": "STRING", "value": p.assignee.lower()})
        where.append(
            "EXISTS(SELECT 1 FROM UNNEST(p.assignee_harmonized) a "
            "WHERE STRPOS(LOWER(a.name), @asg) > 0)"
        )

    if p.countries:
        params.append({"name": "cc", "type": "ARRAY<STRING>",
                       "value": [c.upper() for c in p.countries]})
        where.append("p.country_code IN UNNEST(@cc)")

    if p.date_from:
        params.append({"name": "dfrom", "type": "INT64", "value": p.date_from})
        where.append("p.publication_date >= @dfrom")
    if p.date_to:
        params.append({"name": "dto", "type": "INT64", "value": p.date_to})
        where.append("p.publication_date <= @dto")

    params.append({"name": "lim", "type": "INT64",
                   "value": max(1, min(p.limit, MAX_LIMIT))})

    # 초록은 full 모드에서만 SELECT 한다. BigQuery 는 읽은 '컬럼'만큼 과금하므로
    # 이 한 줄이 title 모드의 비용을 한 자릿수 GB 대로 끌어내린다.
    abstract_col = (
        "(SELECT SUBSTR(a.text, 0, 400) FROM UNNEST(p.abstract_localized) a "
        "WHERE a.language IN ('en','EN') LIMIT 1) AS abstract_en,"
        if p.mode == "full" else "CAST(NULL AS STRING) AS abstract_en,"
    )

    sql = f"""
SELECT
  p.publication_number,
  p.country_code,
  p.kind_code,
  p.publication_date,
  p.filing_date,
  p.grant_date,
  p.family_id,
  (SELECT t.text FROM UNNEST(p.title_localized) t
    WHERE t.language IN ('en','EN') LIMIT 1) AS title_en,
  {abstract_col}
  (SELECT STRING_AGG(DISTINCT a.name, ' | ' ORDER BY a.name LIMIT 4)
     FROM UNNEST(p.assignee_harmonized) a) AS assignees,
  (SELECT STRING_AGG(DISTINCT c.code, ', ' ORDER BY c.code LIMIT 6)
     FROM UNNEST(p.cpc) c) AS cpc_codes
FROM {TABLE} AS p
WHERE {' AND '.join(where)}
ORDER BY p.publication_date DESC
LIMIT @lim
""".strip()
    return sql, params


def fmt_date(v: Optional[int]) -> str:
    """BigQuery 특허 테이블의 날짜는 INT64 YYYYMMDD 이고 0 이 '없음'을 뜻한다."""
    if not v:
        return ""
    s = str(v)
    return f"{s[0:4]}-{s[4:6]}-{s[6:8]}" if len(s) == 8 else s


def patent_url(pub_no: str) -> str:
    return f"https://patents.google.com/patent/{pub_no}/en" if pub_no else ""


def row_to_card(r: dict) -> dict:
    """BigQuery row → 화면 카드 1장."""
    pub = r.get("publication_number") or ""
    return {
        "publication_number": pub,
        "title": (r.get("title_en") or "").strip(),
        "abstract": (r.get("abstract_en") or "").strip(),
        "assignees": (r.get("assignees") or "").strip(),
        "cpc": (r.get("cpc_codes") or "").strip(),
        "country": r.get("country_code") or "",
        "kind": r.get("kind_code") or "",
        "family_id": r.get("family_id") or "",
        "publication_date": fmt_date(r.get("publication_date")),
        "filing_date": fmt_date(r.get("filing_date")),
        "grant_date": fmt_date(r.get("grant_date")),
        "granted": bool(r.get("grant_date")),
        "url": patent_url(pub),
    }


class BQ:
    """google-cloud-bigquery 는 지연 임포트한다.
    라이브러리나 키가 없어도 서버는 뜨고, 화면과 /api/health 는 정상 동작해야 한다."""

    def __init__(self):
        self._client = None
        self._error = ""

    def status(self) -> dict:
        cred = config.credentials_status()
        if not cred["ok"]:
            return {"ready": False, "reason": cred["reason"]}
        try:
            import google.cloud.bigquery  # noqa: F401
        except ImportError:
            return {"ready": False,
                    "reason": "google-cloud-bigquery 미설치 (pip install -r server/requirements.txt)"}
        if self._error:
            return {"ready": False, "reason": self._error}
        return {"ready": True, "reason": ""}

    def client(self):
        if self._client is not None:
            return self._client
        st = self.status()
        if not st["ready"]:
            raise NotConfigured(st["reason"])
        from google.cloud import bigquery
        try:
            self._client = bigquery.Client(project=config.PROJECT)
        except Exception as e:                     # 키 손상·권한 오류 등
            self._error = f"BigQuery 클라이언트 초기화 실패: {type(e).__name__}"
            raise NotConfigured(self._error) from None
        return self._client

    @staticmethod
    def _to_bq_params(params: list[dict]):
        from google.cloud import bigquery
        out = []
        for p in params:
            if p["type"].startswith("ARRAY<"):
                inner = p["type"][6:-1]
                out.append(bigquery.ArrayQueryParameter(p["name"], inner, p["value"]))
            else:
                out.append(bigquery.ScalarQueryParameter(p["name"], p["type"], p["value"]))
        return out

    def estimate(self, sql: str, params: list[dict]) -> int:
        """dry-run. 과금 없이 스캔 예상 바이트만 받아온다."""
        from google.cloud import bigquery
        cfg = bigquery.QueryJobConfig(
            dry_run=True, use_query_cache=False,
            query_parameters=self._to_bq_params(params))
        job = self.client().query(sql, job_config=cfg)
        return int(job.total_bytes_processed or 0)

    def run(self, sql: str, params: list[dict]) -> dict:
        """견적 → 상한 검사 → 실행. 상한 초과 시 QueryTooLarge."""
        from google.cloud import bigquery
        est = self.estimate(sql, params)
        if est > config.MAX_SCAN_BYTES:
            raise QueryTooLarge(est, config.MAX_SCAN_BYTES)

        cfg = bigquery.QueryJobConfig(
            use_query_cache=True,
            maximum_bytes_billed=config.MAX_SCAN_BYTES,   # 서버측 하드 캡 (이중 안전장치)
            query_parameters=self._to_bq_params(params))
        job = self.client().query(sql, job_config=cfg)
        rows = [dict(r) for r in job.result()]
        return {
            "rows": rows,
            "estimated_bytes": est,
            "billed_bytes": int(job.total_bytes_billed or 0),
            "cache_hit": bool(job.cache_hit),
        }


bq = BQ()
