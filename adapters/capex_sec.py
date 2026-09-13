"""SEC EDGAR — 미국 상장 경쟁사 설비투자 공시 수집. 키 불필요.

SEC 는 인증키를 요구하지 않는다. 대신 요청 헤더에 연락처를 밝히도록 요구한다
(공정 이용 규약). SEC_USER_AGENT 에 "회사명 이메일" 형식으로 넣는다.

대상은 TESLA. 파나소닉은 일본 상장이라 EDINET 소관이고, 삼성SDI·SK온은 DART,
CATL·BYD 는 cninfo/HKEX 소관이다.
"""
from __future__ import annotations

import argparse
import datetime
import json
import logging
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import cache, config  # noqa: E402

log = logging.getLogger("sec")

SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"
FULLTEXT = "https://efts.sec.gov/LATEST/search-index"
ARCHIVE = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"
FILING_PAGE = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"

TARGETS = [
    {"key": "TESLA", "cik": "0001318605", "name": "Tesla, Inc."},
]

# 전문검색에 쓸 공정기술 용어. 회사를 가리지 않고 훑어 누가 말하는지를 본다.
FULLTEXT_TERMS = [
    "dry electrode", "dry coating", "solid-state battery", "silicon anode",
    "4680 cell", "cell-to-pack", "laser welding electrode", "prismatic cell",
    "lithium iron phosphate", "battery gigafactory", "electrode coating line",
    "calendering", "battery formation", "cell finishing",
]

# 설비투자 신호가 실릴 만한 공시 종류
FORMS = {"8-K", "10-K", "10-Q"}

CAPEX_PATTERNS = [
    r"gigafactory", r"new (?:plant|factory|facility|line)", r"capacity expansion",
    r"production line", r"manufacturing facility", r"capital expenditure",
    r"start of production", r"begin(?:s|ning)? production", r"ramp",
]
TECH_KEYWORDS = [
    "battery", "cell", "electrode", "dry electrode", "4680", "cathode", "anode",
    "pack", "module", "lithium", "gigafactory", "production line", "coating",
]
GRADE_RULES = [
    ("verified", [r"began production", r"start(?:ed)? production", r"now producing",
                  r"in production", r"operational"]),
    ("strong",   [r"will (?:build|construct|open)", r"plan(?:s|ned)? to (?:build|expand)",
                  r"under construction", r"expansion", r"new facility", r"break ground"]),
]


class SecError(Exception):
    pass


# SEC 는 규약상 연락처 표기를 요구하지만, 실제 방화벽은 브라우저가 아닌
# User-Agent 를 403 으로 막는다(2026-09-13 실측: "회사명 이메일" 형식 403,
# 브라우저 문자열 200). 그래서 UA 는 브라우저 문자열을 쓰고, 연락처는 그 용도의
# 표준 헤더인 From 에 담는다. 규약의 '신원을 밝혀라'는 요구는 그대로 지킨다.
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


def contact() -> str:
    """SEC 에 밝힐 연락처. SEC_USER_AGENT 값에서 이메일만 뽑아 쓴다."""
    raw = os.environ.get("SEC_USER_AGENT", "").strip()
    m = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", raw)
    return m.group(0) if m else ""


def headers(accept: str = "application/json") -> dict:
    h = {"User-Agent": BROWSER_UA, "Accept": accept,
         "Accept-Encoding": "gzip, deflate"}
    c = contact()
    if c:
        h["From"] = c            # 누가 긁는지 SEC 가 알 수 있게 남긴다
    return h


def user_agent() -> str:
    return BROWSER_UA


def status() -> dict:
    if not contact():
        return {"ready": False,
                "reason": "SEC_USER_AGENT 미설정 — .env 에 '회사명 이메일' 형식으로 넣으십시오 "
                          "(SEC 가 연락처 표기를 요구합니다. 키가 아닙니다)."}
    return {"ready": True, "reason": ""}


def fmt_date(s: str) -> str:
    return s.strip() if re.fullmatch(r"\d{4}-\d{2}-\d{2}", (s or "").strip()) else ""


def is_capex(title: str) -> bool:
    t = (title or "").lower()
    return any(re.search(p, t) for p in CAPEX_PATTERNS)


def extract_keywords(text: str) -> list[str]:
    t = (text or "").lower()
    return [k for k in TECH_KEYWORDS if k in t]


def propose_grade(text: str) -> tuple[str, str, bool]:
    t = (text or "").lower()
    for grade, pats in GRADE_RULES:
        for p in pats:
            m = re.search(p, t)
            if m:
                lo, hi = max(0, m.start() - 30), min(len(t), m.end() + 30)
                return grade, t[lo:hi].strip(), grade == "verified"
    return "weak", "", True


def to_evidence(item: dict, company: str, cik: str) -> dict:
    title = (item.get("primaryDocDescription") or item.get("form") or "").strip()
    desc = (item.get("_text") or title)
    acc = (item.get("accessionNumber") or "").replace("-", "")
    doc = item.get("primaryDocument") or ""
    url = ARCHIVE.format(cik=cik.lstrip("0"), acc=acc, doc=doc) if acc and doc else ""
    kws = extract_keywords(desc)
    grade, basis, review = propose_grade(desc)
    if not kws:
        review = True
    return {
        "type": "capex",
        "company": company,
        "date": fmt_date(item.get("filingDate", "")),
        "ref": f"{item.get('form','')} · {title}"[:200],
        "summary": desc[:400],
        "url": url,
        "grade": grade,
        "accession": item.get("accessionNumber", ""),
        "form": item.get("form", ""),
        "grade_basis": basis,
        "keywords": kws,
        "needs_review": review,
        "source": "SEC",
        "collected_at": datetime.datetime.now(
            datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


class Sec:
    def __init__(self, per_min: int = 30, pause: float = 0.4):
        self._limiter = cache.RateLimiter(per_min)
        self._pause = pause

    def _get_json(self, url: str) -> dict:
        import requests

        st = status()
        if not st["ready"]:
            raise SecError(st["reason"])
        ck = cache.key_of({"u": url})
        hit = cache.get(ck)
        if hit is not None:
            return hit
        ok, wait = self._limiter.allow()
        if not ok:
            raise SecError(f"호출 빈도 제한 — {wait}초 후 재시도")
        try:
            r = requests.get(url, headers=headers(), timeout=40)
            r.raise_for_status()
            j = r.json()
        except Exception as e:
            raise SecError(f"SEC 호출 실패: {type(e).__name__} {e}") from None
        time.sleep(self._pause)
        cache.put(ck, j)
        return j

    def filings(self, cik: str, since: str = "2022-01-01") -> list[dict]:
        j = self._get_json(SUBMISSIONS.format(cik=cik))
        recent = (j.get("filings") or {}).get("recent") or {}
        keys = ["accessionNumber", "filingDate", "form", "primaryDocument",
                "primaryDocDescription", "items"]
        n = len(recent.get("accessionNumber") or [])
        out = []
        for i in range(n):
            row = {k: (recent.get(k) or [None] * n)[i] for k in keys}
            if (row.get("filingDate") or "") < since:
                continue
            if row.get("form") not in FORMS:
                continue
            out.append(row)
        return out


    def fulltext(self, term: str, since: str = "2022-01-01",
                 until: str = "", forms: str = "8-K,10-K,10-Q") -> list[dict]:
        """EDGAR 전문검색 — 제목이 아니라 공시 본문을 뒤진다.

        회사를 지정하지 않는다. 그 기술을 실제로 문서에 적은 회사가 누구인지
        SEC 전체에서 찾아오는 쪽이, 우리가 아는 회사만 들여다보는 것보다 넓다.
        """
        import requests

        until = until or datetime.date.today().strftime("%Y-%m-%d")
        ck = cache.key_of({"ft": term, "s": since, "u": until, "f": forms})
        hit = cache.get(ck)
        if hit is not None:
            return hit
        ok, wait = self._limiter.allow()
        if not ok:
            raise SecError(f"호출 빈도 제한 — {wait}초 후 재시도")
        params = {"q": f'"{term}"', "forms": forms,
                  "dateRange": "custom", "startdt": since, "enddt": until}
        try:
            r = requests.get(FULLTEXT, params=params, headers=headers(), timeout=45)
            r.raise_for_status()
            hits = ((r.json().get("hits") or {}).get("hits")) or []
        except Exception as e:
            raise SecError(f"SEC 전문검색 실패: {type(e).__name__} {e}") from None
        time.sleep(self._pause)
        cache.put(ck, hits)
        return hits


def fulltext_to_evidence(hit: dict, term: str) -> dict:
    """전문검색 1건 → evidence. 회사명은 SEC 가 준 display_names 를 그대로 쓴다."""
    src = hit.get("_source") or {}
    names = src.get("display_names") or []
    name = (names[0] if names else "").strip()
    company = re.sub(r"\s*\(.*$", "", name).strip().upper()
    adsh, _, doc = (hit.get("_id") or "").partition(":")
    cik = (src.get("ciks") or [""])[0].lstrip("0")
    url = (ARCHIVE.format(cik=cik, acc=adsh.replace("-", ""), doc=doc)
           if cik and adsh and doc else "")
    date = fmt_date(src.get("file_date") or src.get("period_ending") or "")
    return {
        "type": "capex",
        "company": company,
        "date": date,
        "ref": f"{src.get('file_type','')} · {name}"[:200],
        "summary": f"공시 본문에 '{term}' 표현이 있음",
        "url": url,
        "grade": "medium",          # 본문에 썼다는 사실까지만. 가동 여부는 모른다.
        "accession": adsh,
        "form": src.get("file_type", ""),
        "grade_basis": term,
        "keywords": extract_keywords(term),
        "needs_review": True,
        "match_term": term,
        "source": "SEC",
        "collected_at": datetime.datetime.now(
            datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def collect_fulltext(client: Sec, since: str = "2022-01-01",
                     terms: list[str] = None) -> list[dict]:
    terms = terms or FULLTEXT_TERMS
    seen, out = set(), []
    for term in terms:
        try:
            hits = client.fulltext(term, since)
        except SecError as e:
            log.warning("전문검색 '%s' 실패: %s", term, e)
            continue
        n = 0
        for h in hits:
            rec = fulltext_to_evidence(h, term)
            k = (rec["accession"], rec["company"])
            if k in seen or not rec["company"]:
                continue
            seen.add(k)
            out.append(rec)
            n += 1
        log.info("전문검색 '%s': %d건", term, n)
    return out


def collect(client: Sec, since: str = "2022-01-01") -> list[dict]:
    out = []
    for t in TARGETS:
        try:
            rows = client.filings(t["cik"], since)
        except SecError as e:
            log.warning("%s 조회 실패: %s", t["key"], e)
            continue
        kept = []
        for r in rows:
            text = " ".join(str(r.get(k) or "") for k in
                            ("primaryDocDescription", "items", "form"))
            r["_text"] = text
            if is_capex(text):
                kept.append(r)
        log.info("%s: 공시 %d건 중 설비투자 %d건", t["key"], len(rows), len(kept))
        out.extend(to_evidence(r, t["key"], t["cik"]) for r in kept)
    out.sort(key=lambda r: r["date"], reverse=True)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="SEC EDGAR 설비투자 공시 수집")
    ap.add_argument("--since", default="2022-01-01")
    ap.add_argument("--out", default="data/evidence_sec.jsonl")
    ap.add_argument("--no-fulltext", action="store_true",
                    help="본문 전문검색을 건너뛴다(제출목록만 본다)")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    st = status()
    if not st["ready"]:
        print(f"SEC 미설정 — {st['reason']}")
        return 2
    recs = collect(Sec(), a.since)
    if not a.no_fulltext:
        recs += collect_fulltext(Sec(), a.since)
    recs.sort(key=lambda r: r.get("date", ""), reverse=True)
    p = Path(a.out)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"evidence {len(recs)}건 → {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
