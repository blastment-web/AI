"""CTI 로컬 백엔드.

  [브라우저] --fetch--> [이 서버] --서비스 계정 키--> [BigQuery]

키는 서버 프로세스 안에만 있고 브라우저로는 나가지 않는다.
브라우저는 검색어만 보내며, SQL 은 서버가 파라미터 바인딩으로 조립한다.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import cache, config
from .bq import (MAX_LIMIT, NotConfigured, QueryTooLarge, SearchParams, bq,
                 build_search_sql, parse_terms, row_to_card)

log = logging.getLogger("cti")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

app = FastAPI(title="CTI 경쟁기술 인텔리전스 API", version="1.0.0", docs_url="/api/docs")
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)

limiter = cache.RateLimiter(config.MAX_QUERIES_PER_MIN)


def err(status: int, code: str, message: str, **extra) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": code, "message": message, **extra})


def gb(n: int) -> float:
    return round(n / 1024 ** 3, 2)


# ── 상태 ────────────────────────────────────────────────────────────────
@app.get("/api/health")
def health():
    st = bq.status()
    return {
        "ok": True,
        "bigquery": "ready" if st["ready"] else "unconfigured",
        "reason": st["reason"],
        "project": config.PROJECT or None,
        "guards": {
            "max_scan_gb": config.MAX_SCAN_GB,
            "max_queries_per_min": config.MAX_QUERIES_PER_MIN,
            "cache_ttl_sec": config.CACHE_TTL_SEC,
        },
        "tree_snapshot": config.TREE_SNAPSHOT.exists(),
    }


# ── 기술트리 (기존 화면 계약) ───────────────────────────────────────────
@app.get("/api/tree")
def tree():
    """data/tree.json 스냅샷을 그대로 낸다.
    없으면 503 — 화면은 내장 목업으로 자동 폴백하도록 이미 만들어져 있다."""
    if not config.TREE_SNAPSHOT.exists():
        return err(503, "tree_snapshot_missing",
                   "data/tree.json 이 없습니다. 파이프라인 산출물을 두거나 화면의 USE_API 를 false 로 두십시오.")
    try:
        return json.loads(config.TREE_SNAPSHOT.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return err(500, "tree_snapshot_invalid", f"data/tree.json 파싱 실패: {e.msg}")


# ── 특허 검색 ───────────────────────────────────────────────────────────
def _params(q: str, mode: str, cpc: str, assignee: str, country: str,
            date_from: int, date_to: int, limit: int) -> SearchParams:
    return SearchParams(
        terms=parse_terms(q),
        mode="full" if mode == "full" else "title",
        cpc_prefix=(cpc or "").strip(),
        assignee=(assignee or "").strip(),
        countries=[c for c in (country or "").split(",") if c.strip()],
        date_from=date_from or 0,
        date_to=date_to or 0,
        limit=limit,
    )


@app.get("/api/patents/estimate")
def estimate(
    q: str = Query(..., description="검색어. \"큰따옴표\"로 구문 검색"),
    mode: str = Query("title", pattern="^(title|full)$"),
    cpc: str = "", assignee: str = "", country: str = "",
    date_from: int = 0, date_to: int = 0, limit: int = 20,
):
    """실행하지 않고 스캔 예상량만 본다 (dry-run, 과금 없음)."""
    p = _params(q, mode, cpc, assignee, country, date_from, date_to, limit)
    if not p.terms:
        return err(400, "empty_query", "검색어에서 유효한 단어를 찾지 못했습니다. 2자 이상으로 입력하십시오.")
    try:
        sql, params = build_search_sql(p)
        est = bq.estimate(sql, params)
    except NotConfigured as e:
        return err(503, "bigquery_unconfigured", str(e))
    except Exception as e:
        log.warning("estimate 실패: %s", type(e).__name__)
        return err(502, "bigquery_error", f"BigQuery 견적 실패: {type(e).__name__}")
    return {
        "terms": p.terms, "mode": p.mode,
        "estimated_bytes": est, "estimated_gb": gb(est),
        "cap_gb": config.MAX_SCAN_GB, "within_cap": est <= config.MAX_SCAN_BYTES,
    }


@app.get("/api/patents/search")
def search(
    q: str = Query(..., description="검색어. \"큰따옴표\"로 구문 검색"),
    mode: str = Query("title", pattern="^(title|full)$"),
    cpc: str = "", assignee: str = "", country: str = "",
    date_from: int = 0, date_to: int = 0,
    limit: int = Query(20, ge=1, le=MAX_LIMIT),
    nocache: bool = False,
):
    p = _params(q, mode, cpc, assignee, country, date_from, date_to, limit)
    if not p.terms:
        return err(400, "empty_query", "검색어에서 유효한 단어를 찾지 못했습니다. 2자 이상으로 입력하십시오.")

    try:
        sql, params = build_search_sql(p)
    except ValueError as e:
        return err(400, "bad_query", str(e))

    ck = cache.key_of({"sql": sql, "params": params})
    if not nocache:
        hit = cache.get(ck)
        if hit is not None:
            return {**hit, "cached": True}

    # 자격증명 확인을 레이트리밋보다 먼저. 설정 오류가 쿼리 쿼터를 깎으면 안 된다.
    st = bq.status()
    if not st["ready"]:
        return err(503, "bigquery_unconfigured", st["reason"])

    ok, wait = limiter.allow()
    if not ok:
        return err(429, "rate_limited",
                   f"분당 {config.MAX_QUERIES_PER_MIN}회 상한입니다. {wait}초 후 다시 시도하십시오.",
                   retry_after=wait)

    try:
        res = bq.run(sql, params)
    except NotConfigured as e:
        return err(503, "bigquery_unconfigured", str(e))
    except QueryTooLarge as e:
        return err(400, "scan_too_large",
                   f"스캔 예상량 {gb(e.estimated)}GB 가 상한 {gb(e.cap)}GB 를 넘어 실행하지 않았습니다. "
                   f"기간·국가·CPC 를 좁히거나 '제목만' 모드로 검색하십시오.",
                   estimated_gb=gb(e.estimated), cap_gb=gb(e.cap))
    except Exception as e:
        log.warning("search 실패: %s", type(e).__name__)
        return err(502, "bigquery_error", f"BigQuery 조회 실패: {type(e).__name__}")

    payload = {
        "query": q,
        "terms": p.terms,
        "mode": p.mode,
        "count": len(res["rows"]),
        "results": [row_to_card(r) for r in res["rows"]],
        "cost": {
            "estimated_gb": gb(res["estimated_bytes"]),
            "billed_gb": gb(res["billed_bytes"]),
            "bq_cache_hit": res["cache_hit"],
        },
        "cached": False,
    }
    cache.put(ck, payload)
    return payload


@app.delete("/api/cache")
def clear_cache():
    return {"cleared": cache.clear()}


# ── 정적 화면 ───────────────────────────────────────────────────────────
# API 라우트보다 뒤에 등록해야 /api/* 가 먼저 잡힌다.
@app.get("/")
def index():
    return FileResponse(config.ROOT / "index.html")


app.mount("/", StaticFiles(directory=str(config.ROOT), html=True), name="static")


def main():
    import uvicorn
    st = bq.status()
    log.info("BigQuery: %s%s", "ready" if st["ready"] else "unconfigured",
             "" if st["ready"] else f" ({st['reason']})")
    log.info("스캔 상한 %dGB · 분당 %d회 · 캐시 %d초",
             config.MAX_SCAN_GB, config.MAX_QUERIES_PER_MIN, config.CACHE_TTL_SEC)
    log.info("http://%s:%d 에서 화면을 여십시오.", config.HOST, config.PORT)
    uvicorn.run(app, host=config.HOST, port=config.PORT)


if __name__ == "__main__":
    main()
