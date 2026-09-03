"""환경변수 기반 설정. 키 파일 경로는 담되 키 내용은 절대 읽지 않는다."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    """.env 가 있으면 읽어 os.environ 에 채운다(이미 있는 값은 덮지 않음)."""
    f = ROOT / ".env"
    if not f.exists():
        return
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


_load_dotenv()


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


CREDENTIALS = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
PROJECT = os.environ.get("GCP_PROJECT", "")

MAX_SCAN_GB = _int("MAX_SCAN_GB", 20)
MAX_QUERIES_PER_MIN = _int("MAX_QUERIES_PER_MIN", 10)
CACHE_TTL_SEC = _int("CACHE_TTL_SEC", 86400)

HOST = os.environ.get("HOST", "127.0.0.1")
PORT = _int("PORT", 8000)
CORS_ORIGINS = [o.strip() for o in os.environ.get(
    "CORS_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000,null").split(",") if o.strip()]

CACHE_DIR = ROOT / ".cache"
TREE_SNAPSHOT = ROOT / "data" / "tree.json"

MAX_SCAN_BYTES = MAX_SCAN_GB * 1024 ** 3


def credentials_status() -> dict:
    """키 '경로'의 존재 여부만 본다. 파일 내용은 열지 않는다."""
    if not CREDENTIALS:
        return {"ok": False, "reason": "GOOGLE_APPLICATION_CREDENTIALS 미설정"}
    if not Path(CREDENTIALS).exists():
        return {"ok": False, "reason": f"키 파일을 찾을 수 없음: {CREDENTIALS}"}
    if not PROJECT:
        return {"ok": False, "reason": "GCP_PROJECT 미설정 (쿼리 비용이 청구될 프로젝트 ID)"}
    return {"ok": True, "reason": ""}
