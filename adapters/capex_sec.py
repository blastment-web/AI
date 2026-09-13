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
ARCHIVE = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"
FILING_PAGE = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"

TARGETS = [{"key": "TESLA", "cik": "0001318605", "name": "Tesla, Inc."}]

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


def user_agent() -> str:
    return os.environ.get("SEC_USER_AGENT", "").strip()


def status() -> dict:
    ua = user_agent()
    if not ua or "@" not in ua:
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
            r = requests.get(url, headers={"User-Agent": user_agent(),
                                           "Accept": "application/json"}, timeout=40)
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
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    st = status()
    if not st["ready"]:
        print(f"SEC 미설정 — {st['reason']}")
        return 2
    recs = collect(Sec(), a.since)
    p = Path(a.out)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"evidence {len(recs)}건 → {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
