"""OpenAlex — 경쟁사의 기술 발표·논문 수집 어댑터. 키 불필요.

    [이 어댑터] --(키 불필요)--> [api.openalex.org] --> evidence 레코드(JSONL)

왜 필요한가:
  지금까지 경쟁사 근거는 사실상 특허 하나뿐이었다. 그래서 판정이 늘
  '특허 기준' 단서를 달고 나왔다(judge.position 의 patent_only). 논문·학회 발표가
  붙으면 서로 다른 소스 2종이 되어 TRL 8 이상을 줄 수 있고, 단서도 떨어진다.

  CIBF·AABC 같은 산업 컨퍼런스는 공개 API 가 없다. 대신 OpenAlex 는 학회
  프로시딩과 저널을 함께 색인하고, 키 없이 쓸 수 있으며, 저자 소속 문자열을
  그대로 검색할 수 있다. 경쟁사 연구소가 어느 공정기술을 쓰고 있는지는
  여기에 먼저 나타난다.

주의(2026-09-13 실측):
  · institutions 검색으로 회사를 찾으면 안 된다. LG에너지솔루션·삼성SDI 는
    기관 레코드가 없고, 'Tesla' 는 체코의 동명 회사가 잡힌다.
    raw_affiliation_strings.search 로 소속 문자열을 직접 보는 쪽이 정확하다.
  · 소속 문자열만으로 거르면 'SK On' 이 본문의 'SK on ...' 에 걸려 3,414건이
    된다. 반드시 기술어 검색과 교차해서 쓴다.
"""
from __future__ import annotations

import argparse
import datetime
import json
import logging
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import cache  # noqa: E402

log = logging.getLogger("openalex")

API = "https://api.openalex.org/works"
CONTACT = "blastment@naver.com"          # OpenAlex 예의 규약(polite pool) — 키가 아니다

# 소속 문자열로 경쟁사를 가려낸다. 오탐이 많은 짧은 이름은 문맥을 함께 요구한다.
COMPANY_PATTERNS = {
    "LGES":        r"LG\s*Energy\s*Solution|LG\s*Chem",
    "SAMSUNG SDI": r"Samsung\s*SDI",
    "SK ON":       r"SK\s*On\b|SK\s*Innovation|SK\s*Energy",
    "CATL":        r"Contemporary\s*Amperex|CATL\b|Ningde\s*Times",
    "BYD":         r"\bBYD\b",
    "PANASONIC":   r"Panasonic",
    "TESLA":       r"Tesla,?\s*Inc|Tesla\s*Motors",
}

# 학술 근거는 '했다'가 아니라 '한다고 썼다'까지다. 사다리상 MEDIUM 이 상한이다.
DEFAULT_GRADE = "medium"


class OpenAlexError(Exception):
    pass


# ── 순수 함수 (테스트 대상) ──────────────────────────────────────────
def affiliations(work: dict) -> list[str]:
    """저자별 소속 문자열을 모은다(기관 레코드 + 원문 문자열 양쪽)."""
    out = []
    for a in work.get("authorships") or []:
        out.extend(a.get("raw_affiliation_strings") or [])
        for i in a.get("institutions") or []:
            if i.get("display_name"):
                out.append(i["display_name"])
    return out


def companies_in(work: dict) -> list[str]:
    """이 논문에 이름이 올라간 경쟁사들."""
    blob = " ; ".join(affiliations(work))
    return [k for k, p in COMPANY_PATTERNS.items() if re.search(p, blob, re.I)]


def venue_of(work: dict) -> str:
    loc = work.get("primary_location") or {}
    src = loc.get("source") or {}
    return (src.get("display_name") or "").strip()


def is_conference(work: dict) -> bool:
    t = (work.get("type") or "").lower()
    loc = work.get("primary_location") or {}
    src = loc.get("source") or {}
    return t in ("proceedings-article", "proceedings") or \
        (src.get("type") or "").lower() == "conference"


def work_url(work: dict) -> str:
    doi = work.get("doi") or ""
    if doi:
        return doi if doi.startswith("http") else f"https://doi.org/{doi}"
    loc = work.get("primary_location") or {}
    return loc.get("landing_page_url") or work.get("id") or ""


def to_evidence(work: dict, company: str, term: str) -> dict:
    title = (work.get("display_name") or "").strip()
    venue = venue_of(work)
    conf = is_conference(work)
    return {
        # tree.sample.json 의 evidence 계약. type 을 'paper' 로 두면
        # judge 가 특허와 다른 소스 종류로 세어 준다.
        "type": "paper",
        "company": company,
        "date": (work.get("publication_date") or ""),
        "ref": f"{'학회발표' if conf else '논문'} · {venue}"[:200],
        "summary": title[:400],
        "url": work_url(work),
        "grade": DEFAULT_GRADE,
        "venue": venue,
        "is_conference": conf,
        "cited_by": work.get("cited_by_count", 0),
        "openalex_id": (work.get("id") or "").rsplit("/", 1)[-1],
        "grade_basis": f"'{term}' 주제로 {venue or '학술지'} 에 발표",
        "keywords": [term],
        "needs_review": True,
        "match_term": term,
        "source": "OpenAlex",
        "collected_at": datetime.datetime.now(
            datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


# ── HTTP 계층 ───────────────────────────────────────────────────────
class OpenAlex:
    """키가 없다. mailto 를 밝히면 OpenAlex 가 별도 큐(polite pool)로 받아 준다."""

    def __init__(self, per_min: int = 45, pause: float = 0.8):
        self._limiter = cache.RateLimiter(per_min)
        self._pause = pause

    def search(self, term: str, since: str = "2020-01-01",
               per_page: int = 100, pages: int = 2) -> list[dict]:
        import requests

        ck = cache.key_of({"oa": term, "s": since, "n": per_page, "p": pages})
        hit = cache.get(ck)
        if hit is not None:
            return hit
        out = []
        for page in range(1, pages + 1):
            ok, wait = self._limiter.allow()
            if not ok:
                raise OpenAlexError(f"호출 빈도 제한 — {wait}초 후 재시도하십시오.")
            params = {
                "search": term,
                "filter": f"from_publication_date:{since}",
                "per-page": per_page, "page": page, "mailto": CONTACT,
                "select": ("id,doi,display_name,publication_date,type,"
                           "primary_location,authorships,cited_by_count"),
            }
            # 429 는 흔하다. 몇 초 물러섰다가 다시 청한다.
            batch, last = None, None
            for attempt in range(4):
                try:
                    r = requests.get(API, params=params, headers={
                        "User-Agent": f"LGES-CTI-research (mailto:{CONTACT})"}, timeout=45)
                    if r.status_code == 429:
                        time.sleep(2 * (attempt + 1))
                        last = "429 Too Many Requests"
                        continue
                    r.raise_for_status()
                    batch = r.json().get("results") or []
                    break
                except Exception as e:
                    last = f"{type(e).__name__} {e}"
                    time.sleep(1 + attempt)
            if batch is None:
                raise OpenAlexError(f"OpenAlex 호출 실패: {last}")
            out.extend(batch)
            time.sleep(self._pause)
            if len(batch) < per_page:
                break
        cache.put(ck, out)
        return out


def load_terms(tax_path: str = "data/tech_tree.json") -> list[str]:
    """57개 노드의 영문 표기를 검색어로 쓴다. 화면의 기술 목록과 어긋나지 않게 한다."""
    tax = json.loads(Path(tax_path).read_text(encoding="utf-8"))
    terms = []
    for st in tax["stages"]:
        for g in st["g"]:
            for it in g["items"]:
                en = (it.get("en") or "").strip()
                if en:
                    terms.append(en)
    return terms


def collect(client: OpenAlex, terms: list[str], since: str = "2020-01-01",
            pages: int = 2) -> list[dict]:
    """기술어로 훑고, 저자 소속에 경쟁사가 있는 것만 남긴다."""
    seen, out = set(), []
    for term in terms:
        try:
            works = client.search(f"{term} battery", since=since, pages=pages)
        except OpenAlexError as e:
            log.warning("'%s' 조회 실패: %s", term, e)
            continue
        n = 0
        for w in works:
            cos = companies_in(w)
            if not cos:
                continue
            for co in cos:
                key = (co, (w.get("id") or ""))
                if key in seen:
                    continue
                seen.add(key)
                out.append(to_evidence(w, co, term))
                n += 1
        log.info("'%s': 논문 %d건 중 경쟁사 %d건", term, len(works), n)
    out.sort(key=lambda r: r.get("date", ""), reverse=True)
    return out


def write_jsonl(records: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="OpenAlex 학회·논문 근거 수집")
    ap.add_argument("--since", default="2020-01-01")
    ap.add_argument("--pages", type=int, default=2, help="기술어당 최대 페이지(100건 단위)")
    ap.add_argument("--out", default="data/evidence_openalex.jsonl")
    ap.add_argument("--tax", default="data/tech_tree.json")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    terms = load_terms(a.tax)
    recs = collect(OpenAlex(), terms, a.since, a.pages)
    write_jsonl(recs, Path(a.out))
    conf = sum(1 for r in recs if r.get("is_conference"))
    print(f"evidence {len(recs)}건 (학회발표 {conf}건) → {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
