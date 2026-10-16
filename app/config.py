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


def _csv(value: str | None) -> list[str]:
    return [part.strip() for part in (value or "").split(",") if part.strip()]


DB_PATH = os.environ.get("DB_PATH") or str(ROOT / "data" / "pitchdle.db")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD") or "admin"
BASE_URL = (os.environ.get("BASE_URL") or "").rstrip("/")
LIVE_SECONDS = int(os.environ.get("LIVE_SECONDS") or 25)
MIN_VOTES = int(os.environ.get("MIN_VOTES") or 5)
# Optional test account, created (or its password reset) on startup. Only it gets "Reset my data".
TEST_USERNAME = (os.environ.get("TEST_USERNAME") or "").strip()
TEST_PASSWORD = os.environ.get("TEST_PASSWORD") or ""
# Optional test moderator, created (or its password reset) on startup like the test account. Keep it off
# anything public: moderators see every sign-up's details.
TEST_MODERATOR_USERNAME = (os.environ.get("TEST_MODERATOR_USERNAME") or "").strip()
TEST_MODERATOR_PASSWORD = os.environ.get("TEST_MODERATOR_PASSWORD") or ""
# How much a guest's answer counts next to a signed-in player's (1.0), and the most of any card's crowd
# score guests together can make up once signed-in players have answered it. See scoring.vote_weights.
GUEST_WEIGHT = float(os.environ.get("GUEST_WEIGHT") or 0.5)
GUEST_MAX_SHARE = float(os.environ.get("GUEST_MAX_SHARE") or 0.4)
# How much a member's answer counts with a high- or low-priority badge (no badge is 1.0, muted is 0).
HIGH_PRIORITY_WEIGHT = max(0.0, float(os.environ.get("HIGH_PRIORITY_WEIGHT") or 2.0))
LOW_PRIORITY_WEIGHT = max(0.0, float(os.environ.get("LOW_PRIORITY_WEIGHT") or 0.5))
WEIGHTS_PATH = ROOT / "weights.json"
CRAWL_CACHE = ROOT / "data" / "crawl_cache"
STATIC_DIR = ROOT / "static"

# Demo shows the seeded sample companies; live shows real ones. This is only the starting mode for a
# fresh database: after that the admin toggle decides (stored in the settings table).
APP_MODE = "live" if (os.environ.get("APP_MODE") or "").strip().lower() == "live" else "demo"
# Live-mode discovery: which real startups to look for, and how many. Found startups land on the host
# dashboard and join the game only once the host activates them.
DISCOVER_AUTO = (os.environ.get("DISCOVER_AUTO") or "1").strip().lower() not in ("0", "false", "no", "off")
DISCOVER_FIELDS = _csv(os.environ.get("DISCOVER_FIELDS") or "ocean tech,blue economy,aquaculture")
DISCOVER_REGION = (os.environ.get("DISCOVER_REGION") or "").strip()
DISCOVER_DEPTH = max(1, min(10, int(os.environ.get("DISCOVER_DEPTH") or 3)))
DISCOVER_MAX = max(1, int(os.environ.get("DISCOVER_MAX") or 10))
DISCOVER_EXCLUDE = [w.lower() for w in _csv(os.environ.get("DISCOVER_EXCLUDE"))]
