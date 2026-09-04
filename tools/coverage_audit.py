#!/usr/bin/env python3
"""수집 커버리지 감사.

index.html 의 근거 레코드를 화면이 선언한 출처 계보(originOf) 규칙으로 라우팅해,
어느 어댑터가 어느 근거를 책임지는지와 그중 몇 건이 실제로 수집 가능한지를 센다.
docs/COVERAGE.md 의 모든 수치가 이 스크립트 출력이다.

    python3 tools/coverage_audit.py            # 사람이 읽는 보고서
    python3 tools/coverage_audit.py --md       # docs/COVERAGE.md 용 표
"""
import argparse
import collections
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

# ── index.html 의 originOf() 와 동일한 분류 ──────────────────────────
KR = {"SAMSUNG SDI", "SK ON"}
CN = {"CATL", "BYD"}
JP = {"PANASONIC"}
US = {"TESLA"}
NATIONALITY = {"CATL": "CN", "BYD": "CN", "SAMSUNG SDI": "KR",
               "SK ON": "KR", "TESLA": "US", "PANASONIC": "JP"}

# 어댑터 구현 상태 — 사용자가 제시한 구성표 기준
STATUS = {
    "KIPRIS":            "구현",
    "EPO OPS":           "구현",
    "SEC EDGAR":         "구현",
    "DART":              "구현",
    "Google Patents(BQ)": "미구현",
    "cninfo 파싱":        "미구현",
    "컨퍼런스 프로그램 파싱": "미구현(OpenAlex 대체)",
    "EDINET/TDnet":      "구성표 누락",
}

# 각 원천이 청구항 수준까지 주는 관할 / 서지 수준까지 주는 관할
CLAIMS = {"KIPRIS": {"KR"},
          "EPO OPS": {"EP", "WO"},
          "Google Patents(BQ)": {"US", "CN", "JP", "KR", "EP", "WO"}}
BIBLIO = {"KIPRIS": {"KR"},
          "EPO OPS": {"EP", "WO", "US", "CN", "JP", "KR"},
          "Google Patents(BQ)": {"US", "CN", "JP", "KR", "EP", "WO"}}

EV_RE = re.compile(
    r'\{t:"(patent|capex|conf)",w:"([A-Z ]+)",d:"([\d-]+)",'
    r's:"([^"]*)",x:"([^"]*)",g:"(\w+)"\}')


def route(kind, company):
    """originOf() 와 같은 규칙으로 원천을 고른다."""
    if kind == "patent":
        if company in KR:
            return "KIPRIS"
        if company in CN:
            return "Google Patents(BQ)"
        return "EPO OPS"
    if kind == "capex":
        if company in US:
            return "SEC EDGAR"
        if company in KR:
            return "DART"
        if company in JP:
            return "EDINET/TDnet"
        return "cninfo 파싱"
    return "컨퍼런스 프로그램 파싱"


def authority(ref):
    """문헌번호에서 발행관할을 읽는다 (기업 국적이 아니라 공개된 곳)."""
    r = ref.upper().lstrip()
    for prefix in ("WO", "US", "CN", "JP", "KR", "EP"):
        if r.startswith(prefix):
            return prefix
    return "?"


def load():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    rows = [dict(kind=k, who=w, date=d, ref=s, text=x, grade=g)
            for k, w, d, s, x, g in EV_RE.findall(html)]
    if not rows:
        sys.exit("근거 레코드를 찾지 못했습니다. index.html 의 ev 형식이 바뀌었는지 확인하십시오.")
    for r in rows:
        r["route"] = route(r["kind"], r["who"])
        r["status"] = STATUS[r["route"]]
        r["collectible"] = r["status"] == "구현"
    return rows


def report(rows, md=False):
    total = len(rows)
    ok = sum(1 for r in rows if r["collectible"])
    bar = "|" if md else ""

    def table(head, body):
        if md:
            print("\n| " + " | ".join(head) + " |")
            print("|" + "|".join("---" for _ in head) + "|")
            for line in body:
                print("| " + " | ".join(str(c) for c in line) + " |")
        else:
            print("\n" + "  ".join(f"{h:<22}" for h in head))
            print("-" * 92)
            for line in body:
                print("  ".join(f"{str(c):<22}" for c in line))

    print(f"\n### 1. 어댑터별 귀속 — 근거 {total}건")
    body = []
    by = collections.Counter(r["route"] for r in rows)
    for src, n in by.most_common():
        g = collections.Counter(r["grade"] for r in rows if r["route"] == src)
        gs = " · ".join(f"{k} {v}" for k, v in
                        sorted(g.items(), key=lambda x: -x[1]))
        body.append([src, n, STATUS[src], gs])
    table(["라우팅 대상", "건수", "상태", "등급 분포"], body)
    print(f"\n수집 가능 {ok}건 ({ok/total*100:.0f}%) / 불가 {total-ok}건 ({(total-ok)/total*100:.0f}%)")

    print("\n### 2. 신호 유형별")
    body = []
    for kind, label in (("patent", "특허"), ("capex", "설비투자"), ("conf", "컨퍼런스")):
        sub = [r for r in rows if r["kind"] == kind]
        n = sum(1 for r in sub if r["collectible"])
        body.append([label, len(sub), n, f"{n/len(sub)*100:.0f}%"])
    table(["유형", "총건수", "수집가능", "비율"], body)

    print("\n### 3. 고등급(VERIFIED/STRONG) 근거의 수집 가능 여부")
    hi = [r for r in rows if r["grade"] in ("verified", "strong")]
    hok = [r for r in hi if r["collectible"]]
    print(f"\n고등급 {len(hi)}건 중 수집 가능 {len(hok)}건 / **불가 {len(hi)-len(hok)}건**")
    miss = collections.Counter(r["route"] for r in hi if not r["collectible"])
    for src, n in miss.most_common():
        print(f"  - {src}: {n}건")

    print("\n### 4. 특허 — 발행관할과 청구항 확보 여부")
    pats = [r for r in rows if r["kind"] == "patent"]
    body, unreach = [], []
    for r in pats:
        a = authority(r["ref"])
        has_claims = a in CLAIMS[r["route"]]
        has_biblio = a in BIBLIO[r["route"]]
        mark = "○ 청구항" if has_claims else ("△ 서지만" if has_biblio else "✘ 미포함")
        if not has_claims:
            unreach.append(r)
        body.append([r["who"], r["ref"][:24], a, r["route"], r["grade"], mark])
    table(["기업", "문헌", "발행관할", "라우팅 대상", "등급", "확보 수준"], body)
    print(f"\n특허 {len(pats)}건 중 청구항 확보 불가 **{len(unreach)}건 "
          f"({len(unreach)/len(pats)*100:.0f}%)**")
    g = collections.Counter(r["grade"] for r in unreach)
    print("  미확보분 등급: " + " · ".join(f"{k} {v}건" for k, v in g.most_common()))
    for r in unreach:
        if r["grade"] != "weak":
            print(f"  ⚠ 규칙 위반 — {r['who']} {r['ref']} 에 {r['grade'].upper()} 부여됨. "
                  f"근거인 청구항을 가져올 경로가 없음")

    print("\n### 5. 관할 분포 (기업 국적이 아니라 공개된 곳 기준)")
    by_auth = collections.Counter(authority(r["ref"]) for r in pats)
    print("  " + " · ".join(f"{a} {n}건" for a, n in by_auth.most_common()))
    cross = [r for r in pats if NATIONALITY[r["who"]] != authority(r["ref"])]
    print(f"  기업 국적 ≠ 발행관할: {len(cross)}/{len(pats)}건 "
          f"({len(cross)/len(pats)*100:.0f}%)")

    print("\n### 6. 컨퍼런스 출처 실물")
    for src in sorted({r["ref"] for r in rows if r["kind"] == "conf"}):
        print(f"  - {src}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", action="store_true", help="마크다운 표로 출력")
    report(load(), ap.parse_args().md)
