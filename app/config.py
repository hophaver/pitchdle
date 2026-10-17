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
MIN_VOTES = int(os.environ.get("MIN_VOTES") or 5)
# Optional test account, created (or its password reset) on startup. Only it gets "Reset my data".
TEST_USERNAME = (os.environ.get("TEST_USERNAME") or "").strip()
TEST_PASSWORD = os.environ.get("TEST_PASSWORD") or ""
# Optional test moderator, created (or its password reset) on startup like the test account. Keep it off
# anything public: moderators see every sign-up's details.
TEST_MODERATOR_USERNAME = (os.environ.get("TEST_MODERATOR_USERNAME") or "").strip()
TEST_MODERATOR_PASSWORD = os.environ.get("TEST_MODERATOR_PASSWORD") or ""
# How much a guest's answer counts next to a player account's (1.0), and the most of any card's crowd
# score guests together can make up once members have answered it. See scoring.vote_weights.
GUEST_WEIGHT = float(os.environ.get("GUEST_WEIGHT") or 0.5)
GUEST_MAX_SHARE = float(os.environ.get("GUEST_MAX_SHARE") or 0.4)
# How much an investor account's answer counts next to a player account's (1.0).
INVESTOR_WEIGHT = max(0.0, float(os.environ.get("INVESTOR_WEIGHT") or 2.0))
# A badge multiplies a member's weight: high or low priority (no badge is ×1, muted is 0).
HIGH_PRIORITY_WEIGHT = max(0.0, float(os.environ.get("HIGH_PRIORITY_WEIGHT") or 2.0))
LOW_PRIORITY_WEIGHT = max(0.0, float(os.environ.get("LOW_PRIORITY_WEIGHT") or 0.5))
# Outside reads, run from Admin and never on the game's path: AI models rate each startup, and AI searches
# read what people say about it on social media. One OpenRouter key runs all three models; otherwise each needs
# its own key, and a model without one is skipped.
OPENROUTER_API_KEY = (os.environ.get("OPENROUTER_API_KEY") or "").strip()
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY") or ""
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY") or ""
XAI_API_KEY = os.environ.get("XAI_API_KEY") or ""
# Blank means the default for the route in use (see reads.MODELS): OpenRouter names models differently.
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL") or ""
GPT_MODEL = os.environ.get("GPT_MODEL") or ""
GROK_MODEL = os.environ.get("GROK_MODEL") or ""
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
# Your own words or names to skip: whole words, matched against the name and the headline.
DISCOVER_EXCLUDE = [w.lower() for w in _csv(os.environ.get("DISCOVER_EXCLUDE"))]
# Words that make a *name* a fund, publisher or lab rather than a startup ("Blue Ocean Capital", "Ocean News").
# Whole words of the name only, so "Fundbox" or a headline mentioning "a seed fund" still pass.
DISCOVER_EXCLUDE_NAMES = [w.lower() for w in _csv(os.environ.get("DISCOVER_EXCLUDE_NAMES") or
                          "fund,funds,capital,ventures,venture partners,vc,angels,investors,investments,holdings,"
                          "equity,publisher,publishing,news,magazine,journal,podcast,laboratory,institute,university,"
                          "foundation,association,accelerator,incubator,summit,conference,awards")]
# Never rated as startups, whatever .env says: the event's partners, and the publishers and databases that
# headline parsing picks up as names. Matched against the name and the website's domain.
EXCLUDE_ALWAYS = ["redstone", "a'pelago", "techcrunch", "crunchbase", "sifted", "dealroom", "pitchbook",
                  "eu-startups", "tech.eu", "arcticstartup", "maddyness", "silicon canals", "venturebeat",
                  "the next web", "business insider", "reuters", "bloomberg", "forbes", "yahoo finance",
                  "startup.info", "tracxn", "cb insights"]
# Optional: the OpenRouter key above also does every AI task but the reviews, all on OPENROUTER_MODEL (pick a
# cheap one): screening discovery hits, writing found startups' game cards, and filling each real startup's profile
# (raised, investors, stages, vision, country) and evidence scores from its website and news. Without a key, found
# startups keep their headline as the pitch, an empty profile and no evidence. The reviews (AI ratings and social
# media) run on CLAUDE_MODEL / GPT_MODEL / GROK_MODEL above.
OPENROUTER_MODEL = (os.environ.get("OPENROUTER_MODEL") or "anthropic/claude-haiku-5.5").strip()
