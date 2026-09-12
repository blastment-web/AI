"""증분 수집 — 돌릴 때마다 같은 것을 다시 가져오지 않는다.

    python -m pipeline.collect            # 새 것만 가져와 누적
    python -m pipeline.collect --full     # 상태를 무시하고 전부 다시

핵심 장치 두 가지
  1. data/state.json 에 소스별 마지막 수집 시점과 이미 본 ID를 기록한다.
  2. 저장은 항상 '병합'이다. 기존 파일을 덮어쓰지 않고 새 것만 추가하며,
     같은 ID 가 다시 오면 first_seen 을 유지한 채 내용만 갱신한다.

검색어는 기술트리의 노드 이름을 그대로 쓴다. 우리가 판정해야 할 대상이
57개 기술이므로, 그 이름으로 찾는 것이 가장 정확한 표본이 된다.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
STATE = DATA / "state.json"

log = logging.getLogger("collect")


# ── 상태 ─────────────────────────────────────────────────────────────
def load_state() -> dict:
    if STATE.exists():
        try:
            return json.loads(STATE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"sources": {}}


def save_state(st: dict) -> None:
    st["updated_at"] = datetime.now().isoformat(timespec="seconds")
    DATA.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")


def ev_id(r: dict) -> str:
    """근거 1건의 안정적인 식별자. 재실행해도 같은 값이어야 한다."""
    return "|".join([
        r.get("source", "?"),
        str(r.get("application_number") or r.get("announcement_id")
            or r.get("rcept_no") or r.get("ref", "")),
    ])


def merge_jsonl(path: Path, new_records: list[dict]) -> tuple[int, int]:
    """기존 파일과 병합. (새로 추가된 건수, 전체 건수)."""
    existing: dict[str, dict] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            existing[ev_id(r)] = r

    added = 0
    today = date.today().isoformat()
    for r in new_records:
        k = ev_id(r)
        if k in existing:
            r["first_seen"] = existing[k].get("first_seen", today)
            existing[k] = r                      # 내용은 최신으로 갱신
        else:
            r["first_seen"] = today
            existing[k] = r
            added += 1

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in sorted(existing.values(), key=lambda x: x.get("date", ""), reverse=True):
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return added, len(existing)


def node_queries(limit: int | None = None) -> list[str]:
    """기술트리 노드 이름을 검색어로 쓴다."""
    tax = json.loads((DATA / "tech_tree.json").read_text(encoding="utf-8"))
    out = []
    for st in tax["stages"]:
        for g in st["g"]:
            for it in g["items"]:
                name = it["n"]
                # 괄호 안 보조설명은 검색에 방해가 된다
                name = name.split("(")[0].strip()
                if name and name not in out:
                    out.append(name)
    return out[:limit] if limit else out


# ── 소스별 수집 ──────────────────────────────────────────────────────
def collect_kipris(state: dict, full: bool, rows: int, max_terms: int | None) -> dict:
    from adapters.patent_kipris import Kipris, status, to_evidence

    st = status()
    if not st["ready"]:
        return {"skipped": st["reason"]}
    client = Kipris()
    done = set() if full else set(state["sources"].get("KIPRIS", {}).get("terms_done", []))
    terms = [t for t in node_queries(max_terms) if t not in done]
    if not terms:
        return {"added": 0, "note": "새 검색어 없음 — 모든 노드를 이미 훑었습니다"}

    recs, used = [], []
    for t in terms:
        try:
            items, total = client.search_word(t, rows=rows, page=1)
        except Exception as e:
            log.warning("KIPRIS '%s' 실패: %s", t, e)
            continue
        recs.extend(to_evidence(it) for it in items)
        used.append(t)
        log.info("KIPRIS '%s' → %d건 (원천 %s건)", t, len(items), f"{total:,}")

    added, total_now = merge_jsonl(DATA / "evidence_kipris.jsonl", recs)
    state["sources"].setdefault("KIPRIS", {})
    state["sources"]["KIPRIS"]["terms_done"] = sorted(set(list(done) + used))
    state["sources"]["KIPRIS"]["last_run"] = datetime.now().isoformat(timespec="seconds")
    state["sources"]["KIPRIS"]["total"] = total_now
    return {"added": added, "total": total_now, "terms": len(used)}


def collect_cninfo(state: dict, full: bool) -> dict:
    from adapters.capex_cninfo import Cninfo, collect

    prev = state["sources"].get("cninfo", {})
    bgn = "2020-01-01" if (full or not prev) else prev.get("last_date", "2020-01-01")
    recs = collect(Cninfo(), bgn, date.today().isoformat())
    added, total_now = merge_jsonl(DATA / "evidence_cninfo.jsonl", recs)
    state["sources"].setdefault("cninfo", {})
    state["sources"]["cninfo"].update(
        last_run=datetime.now().isoformat(timespec="seconds"),
        last_date=bgn, total=total_now)
    return {"added": added, "total": total_now}


def collect_dart(state: dict, full: bool) -> dict:
    from adapters.capex_dart import Dart, collect, status

    st = status()
    if not st["ready"]:
        return {"skipped": st["reason"]}
    prev = state["sources"].get("DART", {})
    bgn = "20200101" if (full or not prev) else prev.get("last_date", "20200101")
    recs, _ = collect(Dart(), bgn, date.today().strftime("%Y%m%d"), with_detail=True)
    added, total_now = merge_jsonl(DATA / "evidence_dart.jsonl", recs)
    state["sources"].setdefault("DART", {})
    state["sources"]["DART"].update(
        last_run=datetime.now().isoformat(timespec="seconds"),
        last_date=bgn, total=total_now)
    return {"added": added, "total": total_now}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="증분 수집")
    ap.add_argument("--full", action="store_true", help="상태 무시하고 전부 다시")
    ap.add_argument("--rows", type=int, default=50, help="KIPRIS 검색어당 건수")
    ap.add_argument("--terms", type=int, default=None, help="KIPRIS 검색어 개수 제한")
    ap.add_argument("--only", default="", help="kipris|cninfo|dart 중 하나만")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    state = load_state()
    jobs = {"kipris": lambda: collect_kipris(state, a.full, a.rows, a.terms),
            "cninfo": lambda: collect_cninfo(state, a.full),
            "dart":   lambda: collect_dart(state, a.full)}
    if a.only:
        jobs = {a.only: jobs[a.only]}

    print("=== 증분 수집 ===")
    for name, fn in jobs.items():
        try:
            r = fn()
        except Exception as e:
            r = {"error": f"{type(e).__name__}: {e}"}
        if "skipped" in r:
            print(f"  {name:8} 건너뜀 — {r['skipped']}")
        elif "error" in r:
            print(f"  {name:8} 실패 — {r['error']}")
        else:
            note = f" ({r['note']})" if r.get("note") else ""
            print(f"  {name:8} 새로 {r.get('added',0):>4}건 추가 · 누적 {r.get('total',0):,}건{note}")
    save_state(state)
    print(f"상태 저장 → {STATE.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
