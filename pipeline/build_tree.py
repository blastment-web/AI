"""수집 데이터를 기술트리에 붙여 data/tree.json 을 만든다.

    data/tech_tree.json (사람이 만든 분류체계)
  + data/evidence*.jsonl (어댑터가 모은 근거)
  → data/tree.json (/api/tree 계약)

여기가 비어 있어서 화면의 '미보유 19건'이 표본을 늘려도 안 움직였다.
수집한 근거가 어느 기술 노드의 것인지 아무도 판정하지 않았기 때문이다.

매핑 방식 — LLM 없이 용어 매칭으로 1차 배정하고, 애매한 것은 '미배정'으로 남긴다.
억지로 붙이면 근거 없는 판정이 생기므로, 못 붙인 것은 못 붙였다고 표시한다.
"""
from __future__ import annotations

import argparse
import glob
import json
import re
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline import judge  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

RIVALS = ["CATL", "BYD", "SAMSUNG SDI", "SK ON", "TESLA", "PANASONIC"]
SELF_KEYS = {"LGES", "LG ENERGY SOLUTION", "엘지에너지솔루션"}

# 중국어·영어 근거를 한국어 노드명에 붙이기 위한 용어 다리.
# 노드명에 쓰인 한국어 용어 ← 같은 뜻의 다른 언어 표현
TERM_BRIDGE = {
    "전극": ["electrode", "电极"],
    "양극": ["cathode", "正极"],
    "음극": ["anode", "负极"],
    "코팅": ["coating", "涂布"],
    "건식": ["dry", "干法"],
    "무용매": ["solvent-free", "solventless", "无溶剂"],
    "건조": ["drying", "干燥"],
    "믹싱": ["mixing", "搅拌"],
    "슬러리": ["slurry", "浆料"],
    "압연": ["calendering", "calender", "辊压"],
    "롤프레스": ["roll press", "calendering", "辊压"],
    "슬리팅": ["slitting", "分切"],
    "노칭": ["notching", "模切"],
    "적층": ["stacking", "lamination", "叠片"],
    "스태킹": ["stacking", "叠片"],
    "와인딩": ["winding", "卷绕"],
    "화성": ["formation", "化成"],
    "에이징": ["aging", "老化"],
    "주액": ["electrolyte filling", "注液"],
    "분리막": ["separator", "隔膜"],
    "전해액": ["electrolyte", "电解液"],
    "파우치": ["pouch", "软包"],
    "원통": ["cylindrical", "圆柱"],
    "각형": ["prismatic", "方形"],
    "검사": ["inspection", "检测"],
    "용접": ["welding", "焊接"],
    "레이저": ["laser", "激光"],
    "비전": ["vision", "视觉"],
    "드라이룸": ["dry room", "干燥室"],
    "폐열": ["waste heat", "余热"],
    "물류": ["logistics", "物流"],
    "이차전지": ["secondary battery", "lithium battery", "电池", "锂电"],
    "배터리": ["battery", "电池"],
    "생산기지": ["production base", "生产基地", "产业基地"],
    "설비투자": ["capex", "投资建设"],
}

STOP = {"및", "등", "기반", "적용", "방법", "장치", "시스템", "공정", "기술",
        "the", "and", "for", "with", "of", "a", "an", "in", "to"}

# 배정을 두 단계로 나눈다.
#   용어 매칭만으로 특허를 특정 공정기술에 붙이는 것은 원래 불가능에 가깝다.
#   느슨하게 잡으면(2.0) 한 기술에 7,674건이 붙어 숫자가 무의미해지고,
#   빡빡하게 잡으면(8.0) 41,685건 중 228건만 남는다. 실측으로 확인한 값이다.
#   그래서 '판정에 쓰는 근거'와 '관련 가능성만 있는 것'을 분리한다.
JUDGE_SCORE = 8.0        # 이 점수 이상만 보유/TRL/격차 판정에 쓴다
RELATED_SCORE = 2.0      # 이 점수 이상은 '관련 가능성'으로만 표시하고 판정에 쓰지 않는다


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower().strip())


def node_terms(item: dict) -> list[tuple[str, float]]:
    """노드에서 뽑은 (용어, 가중치). 이름에서 나온 용어가 설명보다 무겁다."""
    out: list[tuple[str, float]] = []

    def add(text, w):
        for tok in re.split(r"[^0-9A-Za-z가-힣\-]+", text or ""):
            t = tok.strip().lower()
            if len(t) >= 2 and t not in STOP:
                out.append((t, w))

    add(item.get("n", ""), 3.0)
    add(item.get("en", ""), 3.0)
    add(item.get("d", "")[:120], 0.5)

    # 용어 다리 — 노드명에 한국어 용어가 있으면 외국어 표현도 같은 무게로 추가
    name = (item.get("n", "") or "")
    for ko, alts in TERM_BRIDGE.items():
        if ko in name:
            out.extend((a.lower(), 2.5) for a in alts)
    return out


def evidence_text(ev: dict) -> str:
    bits = [ev.get("ref", ""), ev.get("summary", ""),
            " ".join(ev.get("keywords") or [])]
    return norm(" ".join(b for b in bits if b))


def match_score(terms: list[tuple[str, float]], text: str) -> float:
    seen, score = set(), 0.0
    for t, w in terms:
        if t in seen:
            continue
        if t in text:
            seen.add(t)
            score += w
    return score


def load_evidence(paths: list[str]) -> list[dict]:
    out, seen = [], set()
    for p in paths:
        for line in Path(p).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            key = (r.get("source", ""),
                   r.get("application_number") or r.get("announcement_id")
                   or r.get("rcept_no") or r.get("ref", ""))
            if key in seen:
                continue
            seen.add(key)
            out.append(r)
    return out


def company_of(ev: dict) -> str:
    c = (ev.get("company") or "").upper()
    if c in SELF_KEYS or "엘지에너지솔루션" in (ev.get("company") or ""):
        return "LGES"
    return c if c in RIVALS else (ev.get("company") or "")


def build(tax: dict, evidence: list[dict], recent_days: int = 365) -> dict:
    nodes, unassigned = [], []
    cutoff = (date.today() - timedelta(days=recent_days)).isoformat()

    # 노드별 용어 사전 미리 계산
    flat = []
    for st in tax["stages"]:
        for g in st["g"]:
            for it in g["items"]:
                flat.append((st, g, it, node_terms(it)))

    buckets = defaultdict(list)          # 판정에 쓰는 근거
    related = defaultdict(list)          # 관련 가능성만 있는 것
    for ev in evidence:
        text = evidence_text(ev)
        best, best_score = None, 0.0
        for idx, (_, _, _, terms) in enumerate(flat):
            sc = match_score(terms, text)
            if sc > best_score:
                best, best_score = idx, sc
        if best is None:
            unassigned.append({**ev, "_score": 0})
        elif best_score >= JUDGE_SCORE:
            buckets[best].append(ev)
        elif best_score >= RELATED_SCORE:
            related[best].append(ev)
        else:
            unassigned.append({**ev, "_score": round(best_score, 1)})

    for idx, (st, g, it, _) in enumerate(flat):
        evs = buckets.get(idx, [])
        rel = related.get(idx, [])
        self_info = it.get("self", {})

        # 자사 근거와 경쟁사 근거를 분리
        rival_ev = [e for e in evs if company_of(e) in RIVALS]
        self_ev = [e for e in evs if company_of(e) == "LGES"]

        by_co = defaultdict(list)
        for e in rival_ev:
            by_co[company_of(e)].append(e)

        rivals = {}
        for co, lst in by_co.items():
            rivals[co] = {"status": "have" if judge.rival_holds(lst) else "part",
                          "evidence_count": len(lst)}

        rival_trl, trl_why = judge.estimate_trl(rival_ev)
        our_trl, our_why = judge.self_trl(self_info)
        gap_years, gap_why = judge.time_gap(rival_trl, our_trl)

        top = max(rival_ev, key=lambda e: judge.GRADE_RANK.get(e.get("grade", ""), 0),
                  default=None)
        recent = sum(1 for e in rival_ev if (e.get("date") or "") >= cutoff)
        score, breakdown = judge.urgency(
            rival_trl, our_trl,
            sum(1 for v in rivals.values() if v["status"] == "have"),
            sum(1 for v in rivals.values() if v["status"] == "part"),
            top.get("grade") if top else None, recent, self_info, len(RIVALS))

        nodes.append({
            "l1": st["n"], "l1_en": st.get("en", ""), "l2": g["n"],
            "name": it["n"], "name_en": it.get("en", ""),
            "desc": it.get("d", ""), "why": it.get("w", ""),
            "est_trl": rival_trl,
            "trl_basis": trl_why,
            "self": {"status": self_info.get("status", "none"),
                     "patents": self_info.get("pat", 0),
                     "line": self_info.get("line", 0),
                     "talks": self_info.get("talk", 0),
                     "project": self_info.get("prj", "—"),
                     "note": self_info.get("note", ""),
                     "trl": our_trl, "trl_basis": our_why,
                     "evidence_count": len(self_ev)},
            "rivals": rivals,
            "lag": ({"gap": judge.fmt_gap(gap_years),
                     "gap_years": gap_years,
                     "basis": gap_why,
                     "rival_milestone": f"경쟁사 TRL {rival_trl} — {trl_why}",
                     "self_state": f"자사 TRL {our_trl} — {our_why}"}
                    if gap_years > 0 else None),
            "urgency": {"score": score, "breakdown": breakdown},
            # 판정에 쓰지 않은 '관련 가능성' 건수. 화면에서 별도로 표기한다.
            "related_count": len(rel),
            "related_self": sum(1 for e in rel if company_of(e) == "LGES"),
            "related_rivals": sum(1 for e in rel if company_of(e) in RIVALS),
            # 목업의 자사 판정과 실제 특허가 어긋나는지 — 보고 전에 반드시 확인해야 한다
            "self_conflict": (self_info.get("status") == "none"
                              and (len(self_ev) + sum(1 for e in rel
                                                      if company_of(e) == "LGES")) > 0),
            "evidence": [{"type": e.get("type"), "company": company_of(e),
                          "date": e.get("date"), "ref": e.get("ref"),
                          "summary": (e.get("summary") or "")[:300],
                          "url": e.get("url", ""), "grade": e.get("grade"),
                          "source": e.get("source", ""),
                          "needs_review": bool(e.get("needs_review"))}
                         for e in sorted(evs, key=lambda x: x.get("date", ""),
                                         reverse=True)[:40]],
            "limit": it.get("limit", ""),
        })

    src_counts = defaultdict(int)
    for e in evidence:
        src_counts[e.get("source", "?")] += 1

    return {
        "collected_at": datetime.now().strftime("%Y-%m-%d %H:%M KST"),
        "criteria": judge.criteria_doc(),
        "sources": [{"name": k, "total": v} for k, v in sorted(src_counts.items())],
        "coverage": {
            "evidence_total": len(evidence),
            "assigned": sum(len(v) for v in buckets.values()),
            "related": sum(len(v) for v in related.values()),
            "unassigned": len(unassigned),
            "nodes_with_evidence": sum(1 for n in nodes if n["evidence"]),
            "nodes_total": len(nodes),
            "self_conflicts": sum(1 for n in nodes if n.get("self_conflict")),
            "note": ("판정에 쓴 근거는 용어가 강하게 일치한 것만입니다. "
                     "'관련'은 가능성만 있어 판정에 쓰지 않았습니다."),
        },
        "nodes": nodes,
        "unassigned_sample": unassigned[:20],
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="수집 근거를 기술트리에 매핑")
    ap.add_argument("--tax", default=str(DATA / "tech_tree.json"))
    ap.add_argument("--evidence", default=str(DATA / "evidence_*.jsonl"))
    ap.add_argument("--out", default=str(DATA / "tree.json"))
    a = ap.parse_args(argv)

    tax = json.loads(Path(a.tax).read_text(encoding="utf-8"))
    paths = sorted(p for p in glob.glob(a.evidence) if "_detail" not in p)
    if not paths:
        print("근거 파일이 없습니다. 어댑터를 먼저 실행하십시오.")
        return 1
    ev = load_evidence(paths)
    tree = build(tax, ev)
    Path(a.out).write_text(json.dumps(tree, ensure_ascii=False, indent=1),
                           encoding="utf-8")

    c = tree["coverage"]
    print(f"근거 {c['evidence_total']:,}건 → 판정에 사용 {c['assigned']:,}건 "
          f"/ 관련만 {c['related']:,}건 / 미배정 {c['unassigned']:,}건")
    print(f"목업 '미보유'인데 자사 특허가 있는 기술: {c['self_conflicts']}건 (확인 필요)")
    print(f"근거가 붙은 노드 {c['nodes_with_evidence']} / {c['nodes_total']}")
    # 화면과 같은 정의 — 경쟁사 중 최소 1곳이 '보유'여야 미보유로 센다.
    # 전부 '일부'뿐이면 경쟁사도 확실히 가진 것이 아니다.
    gaps = [n for n in tree["nodes"]
            if n["self"]["status"] == "none"
            and any(v.get("status") == "have" for v in n["rivals"].values())]
    ver = [n for n in gaps if n["est_trl"] >= 9]
    print(f"자사 미보유 {len(gaps)}건 · 그중 양산 확인(TRL9) {len(ver)}건")
    print(f"→ {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
