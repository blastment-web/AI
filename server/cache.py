"""쿼리 결과 로컬 캐시. BigQuery 는 스캔한 바이트만큼 과금되므로,
같은 검색을 다시 누르는 것만으로 돈이 나가지 않게 한다."""
import hashlib
import json
import time
from pathlib import Path
from typing import Any, Optional

from . import config


def key_of(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _path(key: str) -> Path:
    return config.CACHE_DIR / f"{key}.json"


def get(key: str, ttl: Optional[int] = None) -> Optional[Any]:
    ttl = config.CACHE_TTL_SEC if ttl is None else ttl
    f = _path(key)
    if not f.exists():
        return None
    try:
        blob = json.loads(f.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if ttl > 0 and time.time() - blob.get("at", 0) > ttl:
        return None
    return blob.get("value")


def put(key: str, value: Any) -> None:
    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _path(key).with_suffix(".tmp")
    tmp.write_text(json.dumps({"at": time.time(), "value": value},
                              ensure_ascii=False), encoding="utf-8")
    tmp.replace(_path(key))


def clear() -> int:
    if not config.CACHE_DIR.exists():
        return 0
    n = 0
    for f in config.CACHE_DIR.glob("*.json"):
        f.unlink()
        n += 1
    return n


class RateLimiter:
    """분당 쿼리 수 제한. 비용이 붙는 호출에만 건다."""

    def __init__(self, per_min: int):
        self.per_min = per_min
        self._hits: list[float] = []

    def allow(self) -> tuple[bool, int]:
        now = time.time()
        self._hits = [t for t in self._hits if now - t < 60]
        if len(self._hits) >= self.per_min:
            wait = max(1, int(60 - (now - self._hits[0])))
            return False, wait
        self._hits.append(now)
        return True, 0
