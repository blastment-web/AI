"""HKEX(홍콩거래소) 공시 — 중국 경쟁사 설비투자 수집 어댑터. 키 불필요.

    [이 어댑터] --(키 불필요)--> [www1.hkexnews.hk] --> evidence 레코드(JSONL)

왜 HKEX 인가:
  BYD 는 선전(002594) 상장이지만 cninfo 가 돌려주는 orgId 가 'gshk0001211' 로
  홍콩 소속이고, 실제로 어떤 키워드로도 cninfo 에서 설비투자 공고가 잡히지 않는다.
  CATL 은 2025-05 홍콩 2차 상장(03750) 이후 공시가 홍콩으로도 나온다.
  즉 중국 경쟁사 설비투자의 실제 원천은 cninfo 만이 아니라 여기다.

요청 형식(2026-09-13 실측으로 확정):
  검색은 titlesearch.xhtml 에 대한 평범한 POST 다. 세 가지가 어긋나면 조용히
  0건이 돌아온다 — 눈에 보이는 오류가 없으므로 여기 적어 둔다.
    · 날짜 필드 이름은 from/to 이고 형식은 YYYYMMDD 다(fromDate/toDate 아님).
    · documentType·t1code·t2Gcode·t2code 는 빈 문자열이어야 한다. -1 을 넣으면 0건.
    · stockId 는 activestock_sehk_e.json 의 'i' 값이다(종목코드가 아니다).
  titleSearchServlet.do 는 검색 후 '더 보기' 전용이라 단독 호출은 늘 0건이다.
"""
from __future__ import annotations

import argparse
import datetime
import io
import json
import logging
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import cache  # noqa: E402

log = logging.getLogger("hkex")

SEARCH_URL = "https://www1.hkexnews.hk/search/titlesearch.xhtml"
STOCKLIST_URL = "https://www1.hkexnews.hk/ncms/script/eds/activestock_sehk_e.json"
DOC_BASE = "https://www1.hkexnews.hk"

BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# stock_id 는 activestock_sehk_e.json 의 'i'. resolve_stock_ids() 로 검증할 수 있다.
TARGETS = [
    {"key": "BYD", "code": "01211", "stock_id": "2696", "name": "BYD COMPANY"},
    {"key": "CATL", "code": "03750", "stock_id": "1000259940", "name": "CATL"},
]

# 설비투자 신호. HKEX 공시 제목은 영문 대문자라 대소문자를 무시하고 본다.
CAPEX_PATTERNS = [
    r"production\s+(?:base|facility|capacity|line)", r"manufacturing\s+base",
    r"new\s+(?:plant|factory|facility)", r"capacity\s+expansion", r"expansion\s+project",
    r"construction\s+of", r"investment\s+in\s+.{0,30}(?:project|base|plant)",
    r"establishment\s+of\s+.{0,30}(?:subsidiary|joint venture|company)",
    r"discloseable\s+transaction", r"capital\s+(?:expenditure|increase)",
    r"battery\s+(?:project|plant|base)", r"gigafactory",
    # 중문 공시 제목 — cninfo 에서 정확도가 검증된 표현을 그대로 쓴다
    r"投資建設", r"投资建设", r"生產基地", r"生产基地", r"產業基地", r"产业基地",
    r"擴產", r"扩产", r"新增產能", r"新增产能", r"製造基地", r"制造基地",
]

# 본문이 PDF 안에 있어 제목만으로는 알 수 없는 포장지 공시.
# 내용은 A주(cninfo) 공시의 사본이므로 cninfo 수집분과 중복이다. 세지 않는다.
WRAPPER_TITLES = [r"海外監管公告", r"海外监管公告", r"overseas regulatory announcement"]

# 제목에 이게 있으면 설비투자가 아니다 — 지분·배당·인사·정기공시 잡음
EXCLUDE_PATTERNS = [
    r"closure of register", r"notice of .{0,20}meeting", r"proxy form",
    r"poll results", r"change (?:of|in) director", r"share ?buy-?back",
    r"monthly return", r"next day disclosure", r"dividend",
    r"connected transaction.{0,20}annual cap", r"grant of .{0,15}options",
    r"appointment|resignation|retirement", r"interim report|annual report",
    r"證券變動月報表", r"证券变动月报表", r"股東(?:週|周)年大會", r"股东大会",
    r"季度報告", r"季度报告", r"業績", r"业绩", r"翌日披露",
    r"產銷快報", r"产销快报",     # 월간 생산·판매 정기공시 — 되풀이라 설비투자가 아니다
    r"受托管理事務報告", r"受托管理事务报告", r"債券", r"债券",
    # 募集资金 보고서는 조달자금의 '사용처 보고'라 본문에 投资建设 이 섞인다.
    # 새 투자 결정이 아니므로 설비투자로 세면 안 된다.
    r"募集資金", r"募集资金", r"專項報告", r"专项报告", r"三方監管", r"三方监管",
]

TECH_KEYWORDS = [
    "battery", "cell", "electrode", "cathode", "anode", "lithium", "sodium",
    "energy storage", "power battery", "blade battery", "pack", "module",
    "lfp", "iron phosphate", "solid-state", "gigafactory", "new energy",
]

GRADE_RULES = [
    ("verified", [r"commenced production", r"put into (?:operation|production)",
                  r"commenced operation", r"completion of construction"]),
    ("strong", [r"construction of", r"investment in", r"expansion",
                r"establishment of", r"proposed .{0,20}(?:investment|construction)"]),
]


class HkexError(Exception):
    pass


# ── 순수 함수 (테스트 대상) ──────────────────────────────────────────
def is_wrapper(title: str) -> bool:
    """제목이 포장지뿐이라 내용을 알 수 없는 공시인가."""
    return any(re.search(p, title or "", re.I) for p in WRAPPER_TITLES)


def is_capex(title: str) -> bool:
    """설비투자 공시인가. 제외 패턴이 먼저 걸리면 무조건 탈락."""
    t = (title or "").strip()
    if not t or is_wrapper(t):
        return False
    if any(re.search(p, t, re.I) for p in EXCLUDE_PATTERNS):
        return False
    return any(re.search(p, t, re.I) for p in CAPEX_PATTERNS)


def fmt_date(s: str) -> str:
    """HKEX 는 '13/09/2026 16:30' 형식으로 준다 → 'YYYY-MM-DD'."""
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", s or "")
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else ""


def doc_url(href: str) -> str:
    if not href:
        return ""
    return href if href.startswith("http") else DOC_BASE + href


def extract_keywords(text: str) -> list[str]:
    t = (text or "").lower()
    return [k for k in TECH_KEYWORDS if k in t]


def propose_grade(text: str) -> tuple[str, str, bool]:
    """(등급, 근거 구절, 사람 확인 필요 여부). VERIFIED 는 늘 사람이 본다."""
    t = text or ""
    for grade, pats in GRADE_RULES:
        for p in pats:
            m = re.search(p, t, re.I)
            if m:
                lo, hi = max(0, m.start() - 25), min(len(t), m.end() + 45)
                return grade, t[lo:hi].replace("\n", " ").strip(), grade == "verified"
    return "weak", "", True


def parse_rows(html: str) -> list[dict]:
    """결과 표에서 (공시시각, 종목코드, 종목명, 제목, 링크) 를 뽑는다."""
    out = []
    for block in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        link = re.search(r'href="(/listedco/listconews/[^"]+)"[^>]*>(.*?)</a>', block, re.S)
        if not link:
            continue

        def cell(name):
            m = re.search(r'data-%s="([^"]*)"' % name, block)
            return m.group(1).strip() if m else ""

        title = re.sub(r"<[^>]+>", " ", link.group(2))
        title = re.sub(r"\s+", " ", title).strip()
        rel = re.search(r'release-time[^>]*>(.*?)</td>', block, re.S)
        raw_time = re.sub(r"<[^>]+>", " ", rel.group(1)) if rel else ""
        out.append({
            "time": cell("date") or re.sub(r"\s+", " ", raw_time).strip(),
            "code": cell("code"), "name": cell("shortname"),
            "title": title, "href": link.group(1),
        })
    return out


def pdf_text(blob: bytes, max_pages: int = 6) -> str:
    """공시 PDF 에서 본문을 뽑는다. 실패하면 빈 문자열."""
    try:
        import pypdf
    except ImportError:
        return ""
    try:
        rd = pypdf.PdfReader(io.BytesIO(blob))
        return "".join((p.extract_text() or "") for p in rd.pages[:max_pages])
    except Exception:
        return ""


def to_evidence(row: dict, company_key: str, body: str = "") -> dict:
    title = row.get("title", "")
    text = f"{title} {body}".strip()
    kws = extract_keywords(text)
    grade, basis, review = propose_grade(text)
    if not kws:
        review = True
    return {
        "type": "capex",
        "company": company_key,
        "date": fmt_date(row.get("time", "")),
        "ref": (row.get("real_title") or title)[:200],
        "summary": (row.get("real_title") or title)[:400],
        "url": doc_url(row.get("href", "")),
        "grade": grade,
        "sec_code": row.get("code", ""),
        "sec_name": row.get("name", ""),
        "grade_basis": basis,
        "keywords": kws,
        "needs_review": review,
        "source": "HKEX",
        "collected_at": datetime.datetime.now(
            datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


# ── HTTP 계층 ───────────────────────────────────────────────────────
class Hkex:
    """공시검색 클라이언트. 키가 없으므로 예의 있는 호출이 유일한 제약이다."""

    def __init__(self, per_min: int = 30, pause: float = 1.0):
        self._limiter = cache.RateLimiter(per_min)
        self._pause = pause
        self._session = None

    def _sess(self):
        import requests
        if self._session is None:
            s = requests.Session()
            s.headers.update({"User-Agent": BROWSER_UA,
                              "Referer": SEARCH_URL + "?lang=en"})
            s.get(SEARCH_URL, params={"lang": "en"}, timeout=40)
            self._session = s
        return self._session

    def search(self, stock_id: str, bgn: str, end: str, title: str = "",
               lang: str = "en") -> list[dict]:
        """stock_id 의 공시 목록. bgn/end 는 YYYYMMDD.

        한 번의 검색이 100건에서 잘린다. 호출부가 월 단위로 잘라 부른다.
        """
        ck = cache.key_of({"hk": stock_id, "b": bgn, "e": end, "t": title, "l": lang})
        hit = cache.get(ck)
        if hit is not None:
            return hit
        ok, wait = self._limiter.allow()
        if not ok:
            raise HkexError(f"호출 빈도 제한 — {wait}초 후 재시도하십시오.")
        data = {
            "lang": lang.upper(), "category": "0", "market": "SEHK",
            "searchType": "1" if stock_id else "0",
            # 아래 넷은 반드시 빈 문자열. -1 을 넣으면 조용히 0건이 온다.
            "documentType": "", "t1code": "", "t2Gcode": "", "t2code": "",
            "stockId": stock_id, "from": bgn, "to": end,
            "MB-Daterange": "0", "title": title,
        }
        try:
            r = self._sess().post(SEARCH_URL, params={"lang": lang}, data=data, timeout=60)
            r.raise_for_status()
            rows = parse_rows(r.text)
        except Exception as e:
            raise HkexError(f"HKEX 호출 실패: {type(e).__name__} {e}") from None
        time.sleep(self._pause)
        cache.put(ck, rows)
        return rows

    def resolve_stock_ids(self) -> dict:
        """activestock_sehk_e.json 으로 종목코드 → stock_id 를 확인한다."""
        import requests
        try:
            r = requests.get(STOCKLIST_URL, headers={"User-Agent": BROWSER_UA}, timeout=60)
            r.raise_for_status()
            rows = json.loads(r.content.decode("utf-8-sig"))
        except Exception as e:
            raise HkexError(f"종목 매핑 조회 실패: {type(e).__name__} {e}") from None
        want = {t["code"] for t in TARGETS}
        return {x["c"]: {"stock_id": str(x["i"]), "name": x.get("n", "")}
                for x in rows if x.get("c") in want}


def month_slices(bgn: str, end: str) -> list[tuple[str, str]]:
    """[bgn, end] 를 월 단위 구간으로 자른다. 검색 1회 100건 상한을 피한다."""
    out = []
    y, m = int(bgn[:4]), int(bgn[4:6])
    while f"{y}{m:02d}01" <= end:
        lo = max(bgn, f"{y}{m:02d}01")
        ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
        last = (datetime.date(ny, nm, 1) - datetime.timedelta(days=1)).strftime("%Y%m%d")
        hi = min(end, last)
        if lo <= hi:
            out.append((lo, hi))
        y, m = ny, nm
    return out


# 포장지 PDF 안에서 A주 원공고의 제목을 찾는다. 표기가 여러 갈래라 넓게 잡는다.
REAL_TITLE_RE = re.compile(
    r"(?:刊發|刊发|登載|登载|披露)之?\s*[「“\"']([^」”\"']{6,140})"
    r"|(?:比亞迪股份有限公司|比亚迪股份有限公司)\s*[\r\n]+\s*((?:關於|关于)[^\r\n]{6,140})")


def deep_scan(client: Hkex, rows: list[dict], company_key: str,
              limit: int = 0) -> list[dict]:
    """포장지 공시의 PDF 본문을 열어 설비투자인지 본다.

    BYD 는 홍콩 공시 제목이 거의 전부 '海外監管公告' 라 제목만으로는 아무것도
    알 수 없다. 본문은 A주 공고 전문을 그대로 담고 있으므로 여기서 판별한다.
    cninfo 가 BYD 에 대해 0건인 이유가 이것이라, 이 경로가 BYD 의 유일한 원천이다.
    """
    import requests

    sess = requests.Session()
    sess.headers.update({"User-Agent": BROWSER_UA})
    out = []
    todo = [r for r in rows if is_wrapper(r.get("title", ""))]
    if limit:
        todo = todo[:limit]
    for i, r in enumerate(todo, 1):
        url = doc_url(r.get("href", ""))
        if not url.lower().endswith(".pdf"):
            continue
        ck = cache.key_of({"pdf": url})
        body = cache.get(ck, ttl=0)
        if body is None:
            try:
                blob = sess.get(url, timeout=90).content
            except Exception as e:
                log.warning("PDF 내려받기 실패 %s: %s", url[-28:], type(e).__name__)
                continue
            body = pdf_text(blob)
            cache.put(ck, body)
            time.sleep(0.5)
        if not body:
            continue
        m = REAL_TITLE_RE.search(body)
        real = (m.group(1) or m.group(2) or "").strip() if m else ""
        # 제목이 드러나면 제목으로 판정하고, 아니면 본문 전체를 훑는다.
        # 면책 문구가 앞머리를 채우므로 앞부분만 보면 놓친다.
        if not is_capex(real or body):
            continue
        row = dict(r)
        row["real_title"] = real or (r.get("title") or "")
        out.append(to_evidence(row, company_key, body[:2000]))
        if i % 50 == 0:
            log.info("  %s 포장지 %d/%d 확인 — 설비투자 %d건",
                     company_key, i, len(todo), len(out))
    log.info("%s 포장지 %d건 확인 → 설비투자 %d건", company_key, len(todo), len(out))
    return out


def collect(client: Hkex, bgn: str, end: str, targets: list[dict] = None,
            langs: tuple = ("en", "zh"), deep: bool = False,
            deep_limit: int = 0) -> list[dict]:
    """월 단위로 잘라, 영문·중문 양쪽을 훑는다.

    BYD 는 영문면 제목이 대부분 '海外監管公告' 포장지라 중문면을 봐야 내용이 보인다.
    """
    targets = targets or TARGETS
    slices = month_slices(bgn, end)
    seen, out = set(), []
    for t in targets:
        found = total = wrapped = 0
        wrappers = []
        for lo, hi in slices:
            for lang in langs:
                try:
                    rows = client.search(t["stock_id"], lo, hi, lang=lang)
                except HkexError as e:
                    log.warning("%s %s~%s(%s) 조회 실패: %s", t["key"], lo, hi, lang, e)
                    continue
                total += len(rows)
                for r in rows:
                    title = r.get("title", "")
                    if is_wrapper(title):
                        wrapped += 1
                        if lang == "zh":
                            wrappers.append(r)
                        continue
                    if not is_capex(title):
                        continue
                    key = (t["key"], r.get("href", ""))
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append(to_evidence(r, t["key"]))
                    found += 1
        log.info("%s (%s): 공시 %d건 중 제목으로 설비투자 %d건 · 포장지 %d건",
                 t["key"], t["name"], total, found, wrapped)
        if deep and wrappers:
            seen_href = {h for _, h in seen}
            deep_rows = [r for r in wrappers if r.get("href") not in seen_href]
            for rec in deep_scan(client, deep_rows, t["key"], deep_limit):
                out.append(rec)
                found += 1
    out.sort(key=lambda r: r["date"], reverse=True)
    return out


def write_jsonl(records: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="HKEX 설비투자 공시 수집")
    ap.add_argument("--from", dest="bgn", default="20200101")
    ap.add_argument("--to", dest="end", default=datetime.date.today().strftime("%Y%m%d"))
    ap.add_argument("--out", default="data/evidence_hkex.jsonl")
    ap.add_argument("--verify-ids", action="store_true", help="종목 id 를 원천과 대조만 한다")
    ap.add_argument("--deep", action="store_true",
                    help="'海外監管公告' PDF 본문까지 연다(BYD 는 이게 유일한 경로)")
    ap.add_argument("--deep-limit", type=int, default=0, help="본문 확인 건수 상한(0=전부)")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    client = Hkex()
    if a.verify_ids:
        print(json.dumps(client.resolve_stock_ids(), ensure_ascii=False, indent=2))
        return 0
    recs = collect(client, a.bgn, a.end, deep=a.deep, deep_limit=a.deep_limit)
    write_jsonl(recs, Path(a.out))
    print(f"evidence {len(recs)}건 → {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
