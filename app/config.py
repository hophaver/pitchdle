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
# How much a guest's answer counts next to a signed-in player's (1.0), and the most of any card's crowd
# score guests together can make up once signed-in players have answered it. See scoring.vote_weights.
# Optional test account, created (or its password reset) on startup. Only it gets "Reset my data".
TEST_USERNAME = (os.environ.get("TEST_USERNAME") or "").strip()
TEST_PASSWORD = os.environ.get("TEST_PASSWORD") or ""
GUEST_WEIGHT = float(os.environ.get("GUEST_WEIGHT") or 0.5)
GUEST_MAX_SHARE = float(os.environ.get("GUEST_MAX_SHARE") or 0.4)
WEIGHTS_PATH = ROOT / "weights.json"
CRAWL_CACHE = ROOT / "data" / "crawl_cache"
STATIC_DIR = ROOT / "static"
