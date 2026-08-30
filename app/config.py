"""Configuration. Everything that might differ between the hackathon sandbox
and a real deployment lives here, driven by environment variables."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
STATIC_DIR = ROOT / "static"
PACKS_DIR = ROOT / "app" / "rules" / "packs"

# Load .env from the project root regardless of where uvicorn is invoked from.
try:
    from dotenv import load_dotenv as _load_dotenv
    _env_path = ROOT / ".env"
    if not _env_path.exists():
        _example = ROOT / ".env.example"
        if _example.exists():
            import shutil as _shutil
            _shutil.copy(_example, _env_path)
    # override=True so .env always wins over any stale env vars from a previous
    # session (e.g. an empty FORTYGUARD_API_KEY exported in the shell earlier).
    _load_dotenv(dotenv_path=_env_path, override=True)
except ImportError:
    pass


def _b(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


def _i(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


# --- FortyGuard Temperature API -------------------------------------------
# Confirmed from FortyGuard's published sample: POST https://api.fortyguard.com/v1/heatmap
# with an "api-key" header and a polygon_aoi + date_time + granularity body,
# returning data.activity_id for an async submit-and-poll flow.
# The poll path and the exact result schema are NOT published, so both are
# configurable and the response parser is deliberately tolerant.
# Run `python -m tools.probe_api` once you have a key to print the real shapes.
def _fg_key() -> str:
    """Read fresh from env each call so dotenv override takes effect."""
    return os.getenv("FORTYGUARD_API_KEY", "").strip()

FG_API_KEY = _fg_key()  # snapshot at import; providers/__init__.py calls _fg_key() directly
FG_BASE_URL = os.getenv("FG_BASE_URL", "https://api.fortyguard.com/v1").rstrip("/")
FG_SUBMIT_PATH = os.getenv("FG_SUBMIT_PATH", "/heatmap")
FG_POLL_PATH = os.getenv("FG_POLL_PATH", "/status/{activity_id}")
FG_AUTH_HEADER = os.getenv("FG_AUTH_HEADER", "api-key")
FG_UNITS = os.getenv("FG_UNITS", "c").lower()  # "c" or "f" as returned by the API
FG_GRANULARITY = _i("FG_GRANULARITY", 100)  # metres per cell
FG_AOI_SIDE_M = _i("FG_AOI_SIDE_M", 200)  # worksite bounding box side length
# Fallback box used only when the first request completes with zero tiles.
# Set equal to (or below) FG_AOI_SIDE_M to disable the retry.
FG_AOI_RETRY_M = _i("FG_AOI_RETRY_M", 1000)
FG_FILTER_CURRENT = _i("FG_FILTER_CURRENT", 1)
FG_FILTER_FORECAST = _i("FG_FILTER_FORECAST", 2)
FG_FILTER_HISTORICAL = _i("FG_FILTER_HISTORICAL", 3)
FG_POLL_TIMEOUT_S = _i("FG_POLL_TIMEOUT_S", 90)
FG_POLL_INTERVAL_S = _i("FG_POLL_INTERVAL_S", 3)

# --- Data mode -------------------------------------------------------------
# auto  : use the live API when a key is present, otherwise replay
# live  : force live (errors loudly without a key)
# replay: force the offline synthetic provider
DATA_MODE = os.getenv("DATA_MODE", "auto").lower()


def resolved_mode() -> str:
    # Always fall back to replay when the API key is absent — even if DATA_MODE=live.
    # Without a key the FortyGuard provider raises immediately, so there's no
    # point trying; replay gives a working demo instead of a wall of errors.
    if DATA_MODE == "replay":
        return "replay"
    return "live" if _fg_key() else "replay"


def is_replay() -> bool:
    return resolved_mode() == "replay"


# --- Agent -----------------------------------------------------------------
POLL_ENABLED = _b("POLL_ENABLED", "false")
POLL_INTERVAL_S = _i("POLL_INTERVAL_S", 21600)  # 6h default — 30 heatmap/day limit
LOOKAHEAD_HOURS = _i("LOOKAHEAD_HOURS", 0)  # 0 = current only; saves API quota
HEARTBEAT_MINUTES = _i("HEARTBEAT_MINUTES", 60)

# --- Notifications ---------------------------------------------------------
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "").strip()
NOTIFY_CONSOLE = _b("NOTIFY_CONSOLE", "true")

# --- Storage ---------------------------------------------------------------
# On Vercel (and other serverless platforms) the filesystem is read-only
# except for /tmp. Fall back to /tmp/scorched.db automatically.
_default_db = "/tmp/scorched.db" if os.getenv("VERCEL") or os.getenv("VERCEL_ENV") else str(ROOT / "scorched.db")
DB_PATH = os.getenv("DB_PATH", _default_db)

# --- Station baseline ------------------------------------------------------
# api.weather.gov is free, keyless, and gives the official observation station
# nearest a coordinate. It requires a User-Agent with contact info.
NWS_BASE = os.getenv("NWS_BASE", "https://api.weather.gov")
NWS_USER_AGENT = os.getenv(
    "NWS_USER_AGENT", "Scorched/0.1 (hackathon build; contact: team@example.com)"
)

PRODUCT_NAME = "HeatShield"
PRODUCT_TAGLINE = "Predict. Act. Prove. — worksite heat intelligence powered by FortyGuard"
