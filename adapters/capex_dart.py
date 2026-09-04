"""DART 오픈API — 경쟁사 설비투자 공시 수집 어댑터.

    [이 어댑터] --crtfc_key--> [opendart.fss.or.kr] --> evidence 레코드(JSONL)

출력은 data/tree.sample.json 의 evidence 계약(type·company·date·ref·summary·url·grade)을
그대로 따르고, 출처 추적용 필드를 덧붙인다.

등급은 '제안'만 한다. GRADE 사다리의 VERIFIED 는 "양산 라인 가동이 1차 출처로 확인됨"인데
이걸 키워드 매칭으로 자동 확정하면 docs/COVERAGE.md §4 가 지적한 근거 없는 등급이 또 생긴다.
따라서 판단 근거 구절을 grade_basis 에 싣고, 확신이 없거나 VERIFIED 를 제안한 건은
needs_review=true 로 표시해 사람이 확인하게 한다.
"""
from __future__ import annotations

import argparse
import io
import json
import logging
import os
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import cache, config  # noqa: E402  (import 시 .env 를 읽는다)

log = logging.getLogger("dart")

BASE = "https://opendart.fss.or.kr/api"
VIEWER = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={}"
CORPCODE_TTL = 30 * 24 * 3600          # 고유번호 파일은 자주 바뀌지 않는다
MAX_PAGE_COUNT = 100                   # DART 페이지당 상한

# DART 응답 status 코드. 오픈API 문서 기준이며 실호출로는 아직 대조하지 못했다.
STATUS_MSG = {
    "000": "정상",
    "010": "등록되지 않은 인증키",
    "011": "사용할 수 없는 인증키",
    "012": "접근할 수 없는 IP",
    "013": "조회된 데이터 없음",
    "014": "파일이 존재하지 않음",
    "020": "요청 제한 초과",
    "021": "조회 가능한 회사 개수 초과",
    "100": "부적절한 필드 값",
    "800": "시스템 점검 중",
    "900": "정의되지 않은 오류",
    "901": "사용자 계정의 개인정보 보유기간 만료",
}

# 계보상 DART 가 담당하는 KR 기업. 상호는 DART 등록명이 통칭과 달라 별칭으로 찾는다.
TARGETS = [
    {"key": "SAMSUNG SDI", "aliases": ["삼성에스디아이", "삼성SDI"], "stock_code": "006400"},
    {"key": "SK ON",       "aliases": ["에스케이온", "SK온"],        "stock_code": ""},
    {"key": "LGES",        "aliases": ["엘지에너지솔루션", "LG에너지솔루션"], "stock_code": "373220"},
]

# 시설투자 성격의 공시만 남기는 1차 필터 (report_nm 대상)
REPORT_PATTERNS = [r"신규\s*시설\s*투자", r"시설\s*투자", r"유형자산\s*(취득|양수)", r"투자\s*판단"]

# 등급 제안 규칙. GRADE 사다리(index.html)의 capex 정의를 그대로 옮긴 것.
GRADE_RULES = [
    ("verified", [r"양산\s*가동", r"가동\s*중", r"양산\s*개시", r"기존\s*라인.{0,10}증설", r"상업\s*생산"]),
    ("strong",   [r"신설", r"착공", r"증설", r"발주", r"신규\s*시설\s*투자", r"양산\s*(예정|일정|목표)"]),
]

# 노드 매핑 단계에 넘길 기술 키워드 (매핑 자체는 이 어댑터 범위 밖)
TECH_KEYWORDS = [
    "전극", "양극", "음극", "슬러리", "믹싱", "코팅", "건식", "무용매", "건조", "압연", "롤프레스",
    "슬리팅", "노칭", "적층", "스태킹", "와인딩", "조립", "화성", "에이징", "주액", "디게싱",
    "드라이룸", "파우치", "원통", "각형", "46파이", "4680", "분리막", "전해액", "CTP", "CTC",
    "LFP", "NCM", "전고체", "리튬", "배터리", "이차전지", "셀", "모듈", "팩",
]


class NotConfigured(Exception):
    """키가 없거나 쓸 수 없는 상태."""


def redact(text: str) -> str:
    """로그·오류에 인증키가 새지 않게 지운다.

    DART 는 키를 쿼리스트링으로 받으므로 URL 을 그대로 찍으면 그대로 노출된다.
    """
    if not text:
        return text
    text = re.sub(r"(crtfc_key=)[^&\s\"']+", r"\1***", text)
    key = os.environ.get("DART_API_KEY", "")
    if key and len(key) >= 8:
        text = text.replace(key, "***")
    return text


def status() -> dict:
    """키 유무만 본다. 값 자체는 어디에도 싣지 않는다."""
    key = os.environ.get("DART_API_KEY", "")
    if not key:
        return {"ready": False,
                "reason": "DART_API_KEY 미설정 — server/.env.example 을 .env 로 복사해 채우십시오."}
    if len(key) < 20:
        return {"ready": False, "reason": "DART_API_KEY 형식이 이상합니다(40자 내외여야 합니다)."}
    return {"ready": True, "reason": ""}


def norm(name: str) -> str:
    """상호 비교용 정규화 — 공백·법인격 표기·대소문자 차이를 없앤다."""
    s = (name or "").strip()
    for junk in ("주식회사", "(주)", "㈜", " ", "\t", "　"):
        s = s.replace(junk, "")
    return s.lower()


def fmt_date(yyyymmdd: str) -> str:
    s = (yyyymmdd or "").strip()
    return f"{s[0:4]}-{s[4:6]}-{s[6:8]}" if len(s) == 8 and s.isdigit() else s


def viewer_url(rcept_no: str) -> str:
    return VIEWER.format(rcept_no) if rcept_no else ""


def matches_report(report_nm: str) -> bool:
    return any(re.search(p, report_nm or "") for p in REPORT_PATTERNS)


def extract_keywords(text: str) -> list[str]:
    t = text or ""
    return [k for k in TECH_KEYWORDS if k in t]


def propose_grade(text: str) -> tuple[str, str, bool]:
    """(등급, 판단 근거 구절, 사람 확인 필요 여부).

    VERIFIED 는 가장 강한 주장이므로 규칙이 맞아도 항상 확인 대상으로 남긴다.
    """
    t = text or ""
    for grade, patterns in GRADE_RULES:
        for p in patterns:
            m = re.search(p, t)
            if m:
                lo, hi = max(0, m.start() - 30), min(len(t), m.end() + 30)
                basis = t[lo:hi].replace("\n", " ").strip()
                return grade, basis, grade == "verified"
    return "weak", "", True


def to_evidence(row: dict, company_key: str, detail_text: str = "") -> dict:
    """DART list.json 의 한 행 → evidence 레코드."""
    report_nm = (row.get("report_nm") or "").strip()
    corp_name = (row.get("corp_name") or "").strip()
    rcept_no = (row.get("rcept_no") or "").strip()
    basis_text = f"{report_nm} {detail_text}".strip()
    grade, basis, review = propose_grade(basis_text)
    keywords = extract_keywords(basis_text)
    # 기술 키워드가 하나도 없으면 어느 기술 노드에도 붙일 수 없다.
    # 등급 규칙이 맞았더라도 사람이 봐야 하므로 확인 대상으로 남긴다.
    if not keywords:
        review = True
    summary = detail_text.strip() or report_nm
    return {
        # tree.sample.json 의 evidence 계약
        "type": "capex",
        "company": company_key,
        "date": fmt_date(row.get("rcept_dt", "")),
        "ref": report_nm,
        "summary": summary[:400],
        "url": viewer_url(rcept_no),
        "grade": grade,
        # 출처 추적용
        "rcept_no": rcept_no,
        "corp_name": corp_name,
        "grade_basis": basis,
        "keywords": keywords,
        "needs_review": review,
        "source": "DART",
        "collected_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def parse_corpcode_zip(blob: bytes) -> list[dict]:
    """corpCode.xml ZIP → [{corp_code, corp_name, stock_code}]."""
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        names = [n for n in z.namelist() if n.lower().endswith(".xml")]
        if not names:
            raise ValueError("ZIP 안에 XML 이 없습니다.")
        xml = z.read(names[0])
    root = ET.fromstring(xml)
    out = []
    for el in root.iter("list"):
        out.append({
            "corp_code": (el.findtext("corp_code") or "").strip(),
            "corp_name": (el.findtext("corp_name") or "").strip(),
            "stock_code": (el.findtext("stock_code") or "").strip(),
        })
    return out


def resolve_targets(corps: list[dict], targets: list[dict] = None) -> dict:
    """별칭·종목코드로 corp_code 를 찾는다. 후보를 모두 돌려줘 사람이 확인할 수 있게 한다."""
    targets = targets or TARGETS
    by_stock = {c["stock_code"]: c for c in corps if c.get("stock_code")}
    resolved = {}
    for t in targets:
        hit = None
        if t.get("stock_code") and t["stock_code"] in by_stock:
            hit = by_stock[t["stock_code"]]
        cands = []
        aliases = [norm(a) for a in t["aliases"]]
        for c in corps:
            n = norm(c["corp_name"])
            if any(n == a for a in aliases):
                cands.insert(0, c)          # 완전 일치 우선
            elif any(a in n for a in aliases):
                cands.append(c)
        if hit is None and cands:
            hit = cands[0]
        resolved[t["key"]] = {
            "corp_code": hit["corp_code"] if hit else "",
            "corp_name": hit["corp_name"] if hit else "",
            "stock_code": hit.get("stock_code", "") if hit else "",
            "candidates": [{"corp_code": c["corp_code"], "corp_name": c["corp_name"],
                            "stock_code": c["stock_code"]} for c in cands[:5]],
        }
    return resolved


class Dart:
    """DART 오픈API 클라이언트. 캐시·호출제한·키 마스킹을 포함한다."""

    def __init__(self, key: Optional[str] = None, per_min: int = 30):
        self._key = key if key is not None else os.environ.get("DART_API_KEY", "")
        self._limiter = cache.RateLimiter(per_min)

    def _require(self):
        st = status() if self._key == os.environ.get("DART_API_KEY", "") else {"ready": bool(self._key)}
        if not st.get("ready"):
            raise NotConfigured(st.get("reason", "DART_API_KEY 없음"))

    def _get(self, path: str, params: dict, binary: bool = False, ttl: Optional[int] = None):
        import requests

        self._require()
        ck = cache.key_of({"p": path, "q": {k: v for k, v in params.items() if k != "crtfc_key"}})
        if not binary:
            hit = cache.get(ck, ttl)
            if hit is not None:
                return hit

        ok, wait = self._limiter.allow()
        if not ok:
            raise RuntimeError(f"호출 빈도 제한 — {wait}초 후 다시 시도하십시오.")

        url = f"{BASE}/{path}"
        try:
            res = requests.get(url, params={**params, "crtfc_key": self._key}, timeout=30)
            res.raise_for_status()
        except Exception as e:                       # 네트워크·HTTP 오류
            raise RuntimeError(redact(f"DART 호출 실패({path}): {type(e).__name__} {e}")) from None

        if binary:
            return res.content
        try:
            data = res.json()
        except ValueError:
            raise RuntimeError(f"DART 응답이 JSON 이 아닙니다({path}).") from None

        code = str(data.get("status", ""))
        if code == "013":                            # 데이터 없음은 오류가 아니다
            return {"status": "013", "list": []}
        if code and code != "000":
            raise RuntimeError(f"DART 오류 {code} — {STATUS_MSG.get(code, data.get('message',''))}")
        cache.put(ck, data)
        return data

    def corp_codes(self) -> list[dict]:
        blob = self._get("corpCode.xml", {}, binary=True)
        return parse_corpcode_zip(blob)

    def filings(self, corp_code: str, bgn_de: str, end_de: str,
                pblntf_ty: str = "", max_pages: int = 5) -> list[dict]:
        """공시 목록. pblntf_ty 는 기본 미지정 — 코드를 확인하기 전까지 추측해 좁히지 않는다."""
        rows, page = [], 1
        while page <= max_pages:
            params = {"corp_code": corp_code, "bgn_de": bgn_de, "end_de": end_de,
                      "page_no": page, "page_count": MAX_PAGE_COUNT}
            if pblntf_ty:
                params["pblntf_ty"] = pblntf_ty
            data = self._get("list.json", params)
            batch = data.get("list") or []
            rows.extend(batch)
            total_page = int(data.get("total_page") or 1)
            if page >= total_page or not batch:
                break
            page += 1
        return rows

    def document_text(self, rcept_no: str) -> str:
        """공시 원문에서 텍스트만 뽑는다.

        document.xml 의 내부 구조를 실호출로 확인하지 못했으므로 기본 경로에서는 쓰지 않는다
        (--with-detail 로만 켠다). 태그를 걷어내고 평문만 남기는 보수적 처리.
        """
        blob = self._get("document.xml", {"rcept_no": rcept_no}, binary=True)
        try:
            with zipfile.ZipFile(io.BytesIO(blob)) as z:
                names = [n for n in z.namelist() if n.lower().endswith((".xml", ".html", ".htm"))]
                raw = z.read(names[0]).decode("utf-8", "ignore") if names else ""
        except zipfile.BadZipFile:
            raw = blob.decode("utf-8", "ignore")
        text = re.sub(r"<[^>]+>", " ", raw)
        return re.sub(r"\s+", " ", text).strip()


def collect(client: Dart, bgn_de: str, end_de: str, targets: list[dict] = None,
            with_detail: bool = False, pblntf_ty: str = "") -> tuple[list[dict], dict]:
    targets = targets or TARGETS
    resolved = resolve_targets(client.corp_codes(), targets)
    out = []
    for t in targets:
        info = resolved.get(t["key"], {})
        code = info.get("corp_code")
        if not code:
            log.warning("corp_code 미해결 — %s (별칭: %s)", t["key"], ", ".join(t["aliases"]))
            continue
        rows = client.filings(code, bgn_de, end_de, pblntf_ty)
        kept = [r for r in rows if matches_report(r.get("report_nm", ""))]
        log.info("%s (%s): 공시 %d건 중 시설투자 %d건",
                 t["key"], info.get("corp_name", ""), len(rows), len(kept))
        for r in kept:
            detail = ""
            if with_detail:
                try:
                    detail = client.document_text(r.get("rcept_no", ""))[:2000]
                except Exception as e:
                    log.warning("원문 조회 실패 %s: %s", r.get("rcept_no"), redact(str(e)))
            out.append(to_evidence(r, t["key"], detail))
    return out, resolved


def write_jsonl(records: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="DART 설비투자 공시 수집")
    ap.add_argument("--from", dest="bgn", default="", help="시작일 YYYYMMDD 또는 YYYY-MM-DD")
    ap.add_argument("--to", dest="end", default="", help="종료일")
    ap.add_argument("--out", default="data/evidence_dart.jsonl")
    ap.add_argument("--pblntf-ty", default="", help="공시유형 코드(확인된 경우에만 지정)")
    ap.add_argument("--with-detail", action="store_true",
                    help="공시 원문까지 받아 요약·등급 근거를 보강(추가 호출 발생)")
    ap.add_argument("--list-targets", action="store_true", help="corp_code 해결 결과만 출력")
    ap.add_argument("--from-fixture", default="",
                    help="키 없이 list.json 응답 파일로 변환만 시험")
    ap.add_argument("--company", default="SAMSUNG SDI", help="--from-fixture 사용 시 기업 키")
    a = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    # 키 없이 변환 로직만 돌려보는 경로
    if a.from_fixture:
        data = json.loads(Path(a.from_fixture).read_text(encoding="utf-8"))
        rows = data.get("list") or []
        kept = [r for r in rows if matches_report(r.get("report_nm", ""))]
        recs = [to_evidence(r, a.company) for r in kept]
        print(f"공시 {len(rows)}건 → 시설투자 {len(kept)}건 → evidence {len(recs)}건")
        for r in recs:
            print(json.dumps(r, ensure_ascii=False, indent=2))
        return 0

    st = status()
    if not st["ready"]:
        print(f"DART 미설정 — {st['reason']}")
        print("  키 없이 변환만 시험하려면: --from-fixture tests/fixtures/dart_list.json")
        return 2

    client = Dart()

    def d8(s, default):
        s = (s or "").replace("-", "")
        return s if len(s) == 8 and s.isdigit() else default

    today = datetime.now().strftime("%Y%m%d")
    bgn = d8(a.bgn, f"{int(today[:4])-1}{today[4:]}")
    end = d8(a.end, today)

    # 네트워크를 타는 구간은 전부 여기서 감싼다. 트레이스백이 그대로 나가면
    # 앞으로 추가될 경로에서 마스킹되지 않은 문자열이 새어나갈 수 있다.
    try:
        if a.list_targets:
            print(json.dumps(resolve_targets(client.corp_codes()),
                             ensure_ascii=False, indent=2))
            return 0
        recs, resolved = collect(client, bgn, end, with_detail=a.with_detail,
                                 pblntf_ty=a.pblntf_ty)
    except NotConfigured as e:
        print(redact(f"DART 미설정 — {e}"))
        return 2
    except Exception as e:
        print(redact(f"수집 실패: {e}"))
        return 1

    write_jsonl(recs, Path(a.out))
    review = sum(1 for r in recs if r["needs_review"])
    print(f"evidence {len(recs)}건 → {a.out}")
    print(f"  사람 확인 필요: {review}건 (VERIFIED 제안분과 규칙 미매칭분)")
    for k, v in resolved.items():
        print(f"  {k}: corp_code={v['corp_code'] or '미해결'} ({v['corp_name']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
