"""Runtime configuration from environment variables, optionally loaded from a .env file."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path = ROOT / ".env") -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


_load_dotenv()

DB_PATH = os.environ.get("DB_PATH") or str(ROOT / "data" / "pitchdle.db")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD") or "admin"
BASE_URL = (os.environ.get("BASE_URL") or "").rstrip("/")
LIVE_SECONDS = int(os.environ.get("LIVE_SECONDS") or 25)
MIN_VOTES = int(os.environ.get("MIN_VOTES") or 5)
WEIGHTS_PATH = ROOT / "weights.json"
CRAWL_CACHE = ROOT / "data" / "crawl_cache"
STATIC_DIR = ROOT / "static"
