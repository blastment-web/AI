"""KIPRIS Plus — 국내 특허·실용신안 수집 어댑터.

    [이 어댑터] --accessKey--> [plus.kipris.or.kr] --> evidence 레코드(JSONL)

실호출 검증(2026-09-12)에서 확인한 것:
  - **인증 파라미터명은 `accessKey` 다.** 공공데이터 관례인 `ServiceKey` 를 쓰면
    resultCode=30 SERVICE_KEY_IS_NOT_REGISTERED_ERROR 가 돌아온다. 키 문제가 아니다.
  - 응답 XML 태그는 PascalCase 다 (`InventionName`, `ApplicationDate`, …).
  - 총 건수 태그는 `TotalSearchCount` 이며 items 안, 마지막 항목 뒤에 온다.
  - `RegistrationStatus` 가 '등록'/'공개'로 와서 GRADE 사다리에 그대로 대응된다.
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
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import cache, config  # noqa: E402

log = logging.getLogger("kipris")

BASE = "http://plus.kipris.or.kr/openapi/rest/patUtiModInfoSearchSevice"
DETAIL = "http://kpat.kipris.or.kr/kpat/biblioa.do?method=biblioFrame&applno={}"
MAX_ROWS = 100                      # KIPRIS 페이지당 상한

# 계보상 KIPRIS 가 담당하는 KR 관할. 외국 기업의 국내 출원도 함께 잡힌다.
APPLICANT_ALIASES = {
    "LGES":        ["엘지에너지솔루션", "주식회사 엘지에너지솔루션", "LG에너지솔루션"],
    "SAMSUNG SDI": ["삼성에스디아이", "삼성SDI"],
    "SK ON":       ["에스케이온", "SK온"],
    "CATL":        ["컨템포러리 엠퍼렉스 테크놀로지", "닝더스다이"],
    "PANASONIC":   ["파나소닉"],
    "TESLA":       ["테슬라"],
}

# GRADE 사다리(index.html)의 특허 정의를 KIPRIS 상태값에 대응시킨 것.
#   MEDIUM = 등록특허의 구체적 공정 조건  /  WEAK = 공개특허(출원)
STATUS_GRADE = {"등록": "medium", "공개": "weak", "소멸": "weak", "거절": "weak"}

TECH_KEYWORDS = [
    "전극", "양극", "음극", "슬러리", "믹싱", "코팅", "건식", "무용매", "건조",
    "압연", "롤프레스", "슬리팅", "노칭", "적층", "스태킹", "와인딩", "화성",
    "에이징", "주액", "분리막", "전해액", "이차전지", "리튬", "전고체", "배터리",
    "셀", "모듈", "팩", "집전체", "바인더", "도전재",
]


class KiprisError(Exception):
    pass


def redact(text: str) -> str:
    key = os.environ.get("KIPRIS_API_KEY", "")
    out = re.sub(r"(accessKey=)[^&\s\"']+", r"\1***", text or "")
    return out.replace(key, "***") if key and len(key) >= 8 else out


def status() -> dict:
    key = os.environ.get("KIPRIS_API_KEY", "")
    if not key:
        return {"ready": False, "reason": "KIPRIS_API_KEY 미설정 — .env 에 채우십시오."}
    return {"ready": True, "reason": ""}


# ── 순수 함수 ────────────────────────────────────────────────────────
def fmt_date(yyyymmdd: str) -> str:
    s = (yyyymmdd or "").strip()
    return f"{s[0:4]}-{s[4:6]}-{s[6:8]}" if len(s) == 8 and s.isdigit() else ""


def detail_url(appl_no: str) -> str:
    return DETAIL.format(appl_no) if appl_no else ""


def extract_keywords(text: str) -> list[str]:
    t = text or ""
    return [k for k in TECH_KEYWORDS if k in t]


def map_company(applicant: str) -> str:
    """출원인 문자열 → 추적 대상 키. 못 맞추면 원문을 그대로 돌려준다."""
    a = (applicant or "").replace(" ", "")
    for key, aliases in APPLICANT_ALIASES.items():
        if any(al.replace(" ", "") in a for al in aliases):
            return key
    return (applicant or "").strip()


def parse_items(xml_text: str) -> tuple[list[dict], int]:
    """KIPRIS XML → (레코드 목록, 총 건수). 태그는 PascalCase."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        raise KiprisError(f"XML 파싱 실패: {e}") from None
    code = root.findtext(".//resultCode") or ""
    if code and code != "00":
        msg = root.findtext(".//resultMsg") or ""
        raise KiprisError(f"KIPRIS 오류 {code} — {msg}")
    total = int(root.findtext(".//TotalSearchCount") or 0)
    out = []
    for el in root.iter("PatentUtilityInfo"):
        out.append({t: (el.findtext(t) or "").strip() for t in (
            "Applicant", "ApplicationDate", "ApplicationNumber", "Abstract",
            "InventionName", "InternationalpatentclassificationNumber",
            "OpeningDate", "OpeningNumber", "PublicDate", "RegistrationDate",
            "RegistrationNumber", "RegistrationStatus")})
    return out, total


def to_evidence(item: dict, company_key: str = "") -> dict:
    st = item.get("RegistrationStatus", "")
    grade = STATUS_GRADE.get(st, "weak")
    title = item.get("InventionName", "")
    abstract = item.get("Abstract", "")
    appl_no = item.get("ApplicationNumber", "")
    reg_no = item.get("RegistrationNumber", "")
    keywords = extract_keywords(f"{title} {abstract}")
    # 등록특허라도 청구항을 읽지 않았다면 '구체적 공정 조건'을 확인한 것이 아니다.
    # 초록만으로 MEDIUM 을 확정하지 않고 사람 확인 대상으로 남긴다.
    review = (grade != "weak") or (not keywords)
    date = (fmt_date(item.get("RegistrationDate", ""))
            or fmt_date(item.get("OpeningDate", ""))
            or fmt_date(item.get("ApplicationDate", "")))
    return {
        # tree.sample.json 의 evidence 계약
        "type": "patent",
        "company": company_key or map_company(item.get("Applicant", "")),
        "date": date,
        "ref": (reg_no or appl_no),
        "summary": (title + (" — " + abstract[:200] if abstract else ""))[:400],
        "url": detail_url(appl_no),
        "grade": grade,
        # 출처 추적용
        "applicant": item.get("Applicant", ""),
        "application_number": appl_no,
        "registration_number": reg_no,
        "registration_status": st,
        "ipc": item.get("InternationalpatentclassificationNumber", ""),
        "application_date": fmt_date(item.get("ApplicationDate", "")),
        "keywords": keywords,
        "needs_review": review,
        "source": "KIPRIS",
        "collected_at": datetime.datetime.now(
            datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


# ── HTTP 계층 ────────────────────────────────────────────────────────
class Kipris:
    def __init__(self, per_min: int = 30, pause: float = 0.4):
        self._key = os.environ.get("KIPRIS_API_KEY", "")
        self._limiter = cache.RateLimiter(per_min)
        self._pause = pause

    def _get(self, path: str, params: dict) -> str:
        import requests

        if not self._key:
            raise KiprisError(status()["reason"])
        ck = cache.key_of({"p": path, "q": params})
        hit = cache.get(ck)
        if hit is not None:
            return hit
        ok, wait = self._limiter.allow()
        if not ok:
            raise KiprisError(f"호출 빈도 제한 — {wait}초 후 재시도하십시오.")
        try:
            r = requests.get(f"{BASE}/{path}",
                             params={**params, "accessKey": self._key}, timeout=60)
            r.raise_for_status()
            body = r.text
        except Exception as e:
            raise KiprisError(redact(f"KIPRIS 호출 실패({path}): {type(e).__name__} {e}")) from None
        time.sleep(self._pause)
        cache.put(ck, body)
        return body

    def search_word(self, word: str, rows: int = 30, page: int = 1) -> tuple[list[dict], int]:
        body = self._get("freeSearchInfo",
                         {"word": word, "numOfRows": min(rows, MAX_ROWS), "pageNo": page})
        return parse_items(body)

    def search_applicant(self, name: str, rows: int = 30, page: int = 1
                         ) -> tuple[list[dict], int]:
        body = self._get("applicantNameSearchInfo",
                         {"applicantName": name, "numOfRows": min(rows, MAX_ROWS),
                          "pageNo": page, "patent": "true", "utility": "true"})
        return parse_items(body)

    def count(self, word: str) -> int:
        _, total = self.search_word(word, rows=1, page=1)
        return total


def collect_by_words(client: Kipris, words: list[str], pages: int = 1,
                     rows: int = 50) -> list[dict]:
    """기술어로 훑어 모은다. 출원번호로 중복 제거."""
    seen, out = set(), []
    for w in words:
        for page in range(1, pages + 1):
            try:
                items, total = client.search_word(w, rows=rows, page=page)
            except KiprisError as e:
                log.warning("'%s' p%d 실패: %s", w, page, e)
                break
            for it in items:
                appl = it.get("ApplicationNumber", "")
                if not appl or appl in seen:
                    continue
                seen.add(appl)
                out.append(to_evidence(it))
            if not items:
                break
        log.info("'%s': 누적 %d건", w, len(out))
    out.sort(key=lambda r: r["date"], reverse=True)
    return out


def write_jsonl(records: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="KIPRIS 국내 특허 수집")
    ap.add_argument("--words", default="건식 전극,무용매 전극,전극 코팅,이차전지 적층",
                    help="쉼표로 구분한 검색어")
    ap.add_argument("--pages", type=int, default=1)
    ap.add_argument("--rows", type=int, default=50)
    ap.add_argument("--out", default="data/evidence_kipris.jsonl")
    ap.add_argument("--counts", action="store_true", help="검색어별 총 건수만 출력")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    st = status()
    if not st["ready"]:
        print(f"KIPRIS 미설정 — {st['reason']}")
        return 2

    client = Kipris()
    words = [w.strip() for w in a.words.split(",") if w.strip()]
    try:
        if a.counts:
            for w in words:
                print(f"  '{w}': {client.count(w):,}건")
            return 0
        recs = collect_by_words(client, words, pages=a.pages, rows=a.rows)
    except KiprisError as e:
        print(redact(str(e)))
        return 1

    write_jsonl(recs, Path(a.out))
    review = sum(1 for r in recs if r["needs_review"])
    reg = sum(1 for r in recs if r["registration_status"] == "등록")
    print(f"evidence {len(recs)}건 → {a.out}")
    print(f"  등록 {reg}건 / 공개 {len(recs)-reg}건 · 사람 확인 필요 {review}건")
    return 0


if __name__ == "__main__":
    sys.exit(main())
