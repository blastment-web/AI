"""index.html 에 data/tree.json 을 내장해 단일 파일 산출물을 만든다.

    python -m pipeline.render_html

화면을 파일로 그냥 열면(file://) 브라우저가 로컬 JSON 을 fetch 하지 못한다.
임원 보고 자리에서는 서버를 띄우지 않고 파일만 여는 경우가 대부분이므로,
데이터를 HTML 안에 넣어 자체 완결형으로 만든다.

원본 index.html 은 건드리지 않고 dist/ 에 결과를 쓴다.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLACEHOLDER = "const TREE_DATA = null;"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="실데이터를 내장한 HTML 생성")
    ap.add_argument("--src", default=str(ROOT / "index.html"))
    ap.add_argument("--data", default=str(ROOT / "data" / "tree.json"))
    ap.add_argument("--out", default=str(ROOT / "dist" / "index.html"))
    a = ap.parse_args(argv)

    html = Path(a.src).read_text(encoding="utf-8")
    if PLACEHOLDER not in html:
        print(f"자리표시자를 찾지 못했습니다: {PLACEHOLDER}")
        return 1

    tree = json.loads(Path(a.data).read_text(encoding="utf-8"))
    # 미배정 샘플은 화면에 쓰지 않으므로 뺀다(파일 크기 절약)
    tree.pop("unassigned_sample", None)

    blob = json.dumps(tree, ensure_ascii=False, separators=(",", ":"))
    # </script> 가 데이터에 들어가면 스크립트 블록이 조기 종료된다
    blob = blob.replace("</", "<\\/")
    html = html.replace(PLACEHOLDER, f"const TREE_DATA = {blob};")

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")

    c = tree.get("coverage", {})
    size = out.stat().st_size / 1024
    print(f"생성: {out}  ({size:,.0f} KB)")
    print(f"  근거 {c.get('evidence_total',0):,}건 · 배정 {c.get('assigned',0):,}건 "
          f"· 근거가 붙은 기술 {c.get('nodes_with_evidence',0)}/{c.get('nodes_total',0)}")
    print(f"  수집 시각 {tree.get('collected_at','')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
