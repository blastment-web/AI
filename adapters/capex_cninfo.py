"""巨潮资讯(cninfo) — 중국 경쟁사 설비투자 공고 수집 어댑터.

    [이 어댑터] --(키 불필요)--> [www.cninfo.com.cn] --> evidence 레코드(JSONL)

DART 어댑터(capex_dart.py)와 같은 evidence 계약을 따른다. 인증키가 없는 대신
공식 API 가 아니라 웹 프런트가 쓰는 공고검색 엔드포인트를 호출하므로,
요청 간격을 두고 예의 있게 접근한다.

실호출 검증(2026-09-12)에서 확인한 것:
  - '投资建设'(투자건설) 이 설비투자 공고를 잡는 유일하게 정확한 키워드다.
    '投资'만 쓰면 회사채 발행·투자펀드가 섞이고, '产能'·'扩产'·'工厂' 는 0건이다.
  - CATL 은 2022~2023 에 6건이 있고 2024 년 이후로는 없다.
  - BYD 는 어떤 키워드로도 0건이다. 선전 상장이지만 orgId 가 홍콩(gshk0001211)
    이어서 공고가 HKEX 로 빠지는 것으로 보인다. §커버리지 한계 참조.
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
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import cache, config  # noqa: E402

log = logging.getLogger("cninfo")

QUERY_URL = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
STOCK_MAP_URL = "http://www.cninfo.com.cn/new/data/szse_stock.json"
PDF_BASE = "http://static.cninfo.com.cn/"
VIEWER = "http://www.cninfo.com.cn/new/disclosure/detail?announcementId={}&orgId={}&stockCode={}"

HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) CTI-research/1.0",
    "Referer": "http://www.cninfo.com.cn/new/commonUrl?url=disclosure/list/notice",
    "Accept": "application/json, text/plain, */*",
}

# 계보상 cninfo 가 담당하는 CN 기업. orgId 는 szse_stock.json 에서 확인한 실제 값.
TARGETS = [
    {"key": "CATL", "code": "300750", "org_id": "GD165627",   "name": "宁德时代"},
    {"key": "BYD",  "code": "002594", "org_id": "gshk0001211", "name": "比亚迪"},
]

# 설비투자 공고만 남기는 필터. 실호출 검증 결과 '投资建设' 이 정확도가 가장 높다.
CAPEX_PATTERNS = [r"投资建设", r"建设.{0,6}(基地|项目|产线)", r"生产基地",
                  r"扩产", r"新增产能", r"产能.{0,4}项目"]

# 제목에 이것이 들어가면 설비투자가 아니다 (회사채·펀드·내부규정 등)
EXCLUDE_PATTERNS = [r"管理制度", r"债券", r"募集资金.{0,10}(报告|协议|核查|鉴证)",
                    r"法律意见", r"核查意见", r"股票期权", r"限制性股票",
                    r"股东会", r"董事会决议", r"月报表", r"回购"]

# 노드 매핑 단계로 넘길 기술 키워드 (중국어 + 영문)
TECH_KEYWORDS = [
    "电池", "锂电", "正极", "负极", "隔膜", "电解液", "电芯", "模组", "电池包",
    "涂布", "辊压", "分切", "叠片", "卷绕", "化成", "干燥", "搅拌", "注液",
    "磷酸铁锂", "三元", "固态", "钠离子", "储能", "动力电池", "产业基地",
    "一体化", "新材料", "回收",
]

# 등급 제안 규칙 — index.html 의 GRADE 사다리(capex 정의)를 중국어 표현으로 옮긴 것
GRADE_RULES = [
    ("verified", [r"投产", r"已建成", r"量产", r"竣工", r"正式投运"]),
    ("strong",   [r"投资建设", r"开工", r"新建", r"扩建", r"拟投资", r"签署.{0,8}协议"]),
]


class CninfoError(Exception):
    pass


# ── 순수 함수 (테스트 대상) ──────────────────────────────────────────
def is_capex(title: str) -> bool:
    """설비투자 공고인가. 제외 패턴이 먼저 걸리면 무조건 탈락."""
    t = title or ""
    if any(re.search(p, t) for p in EXCLUDE_PATTERNS):
        return False
    return any(re.search(p, t) for p in CAPEX_PATTERNS)


def fmt_date(ms: Optional[int]) -> str:
    if not ms:
        return ""
    return datetime.datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d")


def strip_highlight(title: str) -> str:
    """isHLtitle=true 일 때 섞여 들어오는 <em> 강조 태그를 제거한다."""
    return re.sub(r"</?em>", "", title or "").strip()


def pdf_url(adjunct_url: str) -> str:
    return PDF_BASE + adjunct_url if adjunct_url else ""


def viewer_url(ann_id: str, org_id: str, code: str) -> str:
    return VIEWER.format(ann_id, org_id, code) if ann_id else ""


def extract_keywords(text: str) -> list[str]:
    t = text or ""
    return [k for k in TECH_KEYWORDS if k in t]


def propose_grade(text: str) -> tuple[str, str, bool]:
    """(등급, 근거 구절, 사람 확인 필요 여부).

    DART 어댑터와 같은 원칙 — VERIFIED 는 가장 강한 주장이므로 규칙이 맞아도
    항상 사람 확인 대상으로 남긴다.
    """
    t = text or ""
    for grade, patterns in GRADE_RULES:
        for p in patterns:
            m = re.search(p, t)
            if m:
                lo, hi = max(0, m.start() - 25), min(len(t), m.end() + 25)
                return grade, t[lo:hi].replace("\n", " ").strip(), grade == "verified"
    return "weak", "", True


def to_evidence(ann: dict, company_key: str, org_id: str, code: str) -> dict:
    title = strip_highlight(ann.get("announcementTitle", ""))
    ann_id = str(ann.get("announcementId") or "")
    keywords = extract_keywords(title)
    grade, basis, review = propose_grade(title)
    if not keywords:          # 노드에 붙일 수 없으면 사람이 봐야 한다
        review = True
    return {
        # tree.sample.json 의 evidence 계약
        "type": "capex",
        "company": company_key,
        "date": fmt_date(ann.get("announcementTime")),
        "ref": title,
        "summary": title,
        "url": viewer_url(ann_id, org_id, code),
        "grade": grade,
        # 출처 추적용
        "announcement_id": ann_id,
        "sec_code": ann.get("secCode", ""),
        "sec_name": ann.get("secName", ""),
        "pdf_url": pdf_url(ann.get("adjunctUrl", "")),
        "grade_basis": basis,
        "keywords": keywords,
        "needs_review": review,
        "source": "cninfo",
        "collected_at": datetime.datetime.now(
            datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


# ── HTTP 계층 ───────────────────────────────────────────────────────
class Cninfo:
    """공고검색 클라이언트. 인증키가 없으므로 예의 있는 호출이 유일한 제약이다."""

    def __init__(self, per_min: int = 20, pause: float = 0.7):
        self._limiter = cache.RateLimiter(per_min)
        self._pause = pause

    def query(self, stock: str, se_date: str, searchkey: str = "",
              page: int = 1, size: int = 50, column: str = "szse") -> dict:
        import requests

        ck = cache.key_of({"s": stock, "d": se_date, "k": searchkey,
                           "p": page, "n": size, "c": column})
        hit = cache.get(ck)
        if hit is not None:
            return hit

        ok, wait = self._limiter.allow()
        if not ok:
            raise CninfoError(f"호출 빈도 제한 — {wait}초 후 재시도하십시오.")

        data = {"pageNum": page, "pageSize": size, "column": column,
                "tabName": "fulltext", "plate": "", "stock": stock,
                "searchkey": searchkey, "secid": "", "category": "",
                "trade": "", "seDate": se_date, "sortName": "", "sortType": "",
                "isHLtitle": "false"}
        try:
            r = requests.post(QUERY_URL, headers=HEADERS, data=data, timeout=40)
            r.raise_for_status()
            j = r.json()
        except Exception as e:
            raise CninfoError(f"cninfo 호출 실패: {type(e).__name__} {e}") from None
        time.sleep(self._pause)
        cache.put(ck, j)
        return j

    def announcements(self, stock: str, se_date: str, searchkey: str = "",
                      max_pages: int = 10) -> list[dict]:
        out, page = [], 1
        while page <= max_pages:
            j = self.query(stock, se_date, searchkey, page=page)
            batch = j.get("announcements") or []
            out.extend(batch)
            total = int(j.get("totalAnnouncement") or 0)
            if len(out) >= total or not batch:
                break
            page += 1
        return out

    def resolve_org_ids(self) -> dict:
        """szse_stock.json 으로 종목코드 → orgId 를 확인한다(하드코딩 값 검증용)."""
        import requests

        try:
            r = requests.get(STOCK_MAP_URL, headers={"User-Agent": HEADERS["User-Agent"]},
                             timeout=40)
            r.raise_for_status()
            rows = r.json().get("stockList") or []
        except Exception as e:
            raise CninfoError(f"종목 매핑 조회 실패: {type(e).__name__} {e}") from None
        want = {t["code"] for t in TARGETS}
        return {x["code"]: {"org_id": x.get("orgId", ""), "name": x.get("zwjc", "")}
                for x in rows if x.get("code") in want}


def collect(client: Cninfo, bgn: str, end: str, keywords: list[str] = None,
            targets: list[dict] = None) -> list[dict]:
    """키워드별로 훑어 합치고 announcementId 로 중복 제거한다."""
    targets = targets or TARGETS
    keywords = keywords or ["投资建设", "建设", "生产基地", "扩产"]
    se = f"{bgn}~{end}"
    seen, out = set(), []
    for t in targets:
        stock = f"{t['code']},{t['org_id']}"
        found = 0
        for kw in keywords:
            try:
                anns = client.announcements(stock, se, kw)
            except CninfoError as e:
                log.warning("%s / '%s' 조회 실패: %s", t["key"], kw, e)
                continue
            for a in anns:
                aid = str(a.get("announcementId") or "")
                if aid in seen:
                    continue
                title = strip_highlight(a.get("announcementTitle", ""))
                if not is_capex(title):
                    continue
                seen.add(aid)
                out.append(to_evidence(a, t["key"], t["org_id"], t["code"]))
                found += 1
        log.info("%s (%s): 설비투자 공고 %d건", t["key"], t["name"], found)
    out.sort(key=lambda r: r["date"], reverse=True)
    return out


def write_jsonl(records: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="cninfo 중국 경쟁사 설비투자 공고 수집")
    ap.add_argument("--from", dest="bgn", default="2022-01-01")
    ap.add_argument("--to", dest="end",
                    default=datetime.date.today().strftime("%Y-%m-%d"))
    ap.add_argument("--out", default="data/evidence_cninfo.jsonl")
    ap.add_argument("--check-org", action="store_true",
                    help="하드코딩된 orgId 가 현재도 맞는지 확인")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    client = Cninfo()
    if a.check_org:
        try:
            print(json.dumps(client.resolve_org_ids(), ensure_ascii=False, indent=2))
        except CninfoError as e:
            print(e)
            return 1
        return 0

    recs = collect(client, a.bgn, a.end)
    write_jsonl(recs, Path(a.out))
    review = sum(1 for r in recs if r["needs_review"])
    print(f"evidence {len(recs)}건 → {a.out}")
    print(f"  사람 확인 필요: {review}건")
    if not recs:
        print("  수집 0건 — 기간을 넓히거나 키워드를 확인하십시오.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
