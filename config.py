import os
from pathlib import Path

BASE_DIR = Path(__file__).parent
AGENT_CONFIGS_DIR = BASE_DIR / "agent_configs"
PLAYBOOKS_DIR = BASE_DIR / "playbooks"
DATA_DIR = BASE_DIR / "data"
MEMORY_DB_PATH = DATA_DIR / "memory.db"
SESSION_BRAIN_PATH = DATA_DIR / "session_brain.md"
CHROMA_PERSIST_DIR = DATA_DIR / "chroma"

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
DEFAULT_MODEL = "claude-sonnet-4-5-20250929"
MODEL_TIERS = {
    "haiku": "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-5-20250929",
    "opus": "claude-opus-4-6",
}
DEFAULT_MODEL_TIER = "sonnet"

AGENT_TIMEOUT_SECONDS = 60
MAX_TOOL_ROUNDS = 25
from memory.models import FactCategory
VALID_FACT_CATEGORIES = frozenset(FactCategory)

SHAREPOINT_DOWNLOAD_DIR = DATA_DIR / "sharepoint-downloads"
OKR_DATA_DIR = DATA_DIR / "okr"
OKR_SPREADSHEET_DEFAULT = OKR_DATA_DIR / "2026_ISP_OKR_Master_Final.xlsx"
OKR_SHAREPOINT_URL = (
    "https://chgcloud.sharepoint.com/:x:/r/sites/ISPTeam/_layouts/15/Doc.aspx"
    "?sourcedoc=%7BDFD697F4-04F3-4583-BC4E-FC55BE913409%7D"
    "&file=2026_ISP_OKR_Master_Final.xlsx"
    "&action=default&mobileredirect=true&DefaultItemOpen=1"
)

# Webhook inbox settings
WEBHOOK_INBOX_DIR = DATA_DIR / "webhook-inbox"
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")

# Scheduler settings
SCHEDULER_ENABLED = os.environ.get("SCHEDULER_ENABLED", "true").strip().lower() not in {"0", "false", "no"}

# Daemon settings
DAEMON_TICK_INTERVAL_SECONDS = int(os.environ.get("DAEMON_TICK_INTERVAL_SECONDS", "60"))
DAEMON_LOG_FILE = DATA_DIR / "jarvis-daemon.log"

# Scheduler handler timeout (seconds). Handlers exceeding this are killed.
try:
    SCHEDULER_HANDLER_TIMEOUT_SECONDS = int(os.environ.get("SCHEDULER_HANDLER_TIMEOUT_SECONDS", "300"))
except ValueError:
    SCHEDULER_HANDLER_TIMEOUT_SECONDS = 300

# Parallel agent dispatch settings (0 = unlimited)
try:
    MAX_CONCURRENT_AGENT_DISPATCHES = max(0, int(os.environ.get("MAX_CONCURRENT_AGENT_DISPATCHES", "5")))
except ValueError:
    MAX_CONCURRENT_AGENT_DISPATCHES = 5

# Skill auto-creation settings
SKILL_SUGGESTION_THRESHOLD = 0.7
SKILL_MIN_OCCURRENCES = 5
SKILL_AUTO_EXECUTE_ENABLED = os.environ.get("SKILL_AUTO_EXECUTE_ENABLED", "false").strip().lower() in {"1", "true", "yes"}

# Proactive push notification settings
PROACTIVE_PUSH_ENABLED = os.environ.get("PROACTIVE_PUSH_ENABLED", "false").strip().lower() in {"1", "true", "yes"}
PROACTIVE_PUSH_THRESHOLD = os.environ.get("PROACTIVE_PUSH_THRESHOLD", "high").strip().lower()

# Webhook auto-dispatch settings
WEBHOOK_AUTO_DISPATCH_ENABLED = os.environ.get(
    "WEBHOOK_AUTO_DISPATCH_ENABLED", "false"
).strip().lower() in {"1", "true", "yes"}

# dispatch_agents orchestrator settings
DISPATCH_AGENTS_MAX_AGENTS = 10  # Hard cap on agents per dispatch
DISPATCH_AGENTS_MAX_RESULT_LENGTH = 5000  # Truncate per-agent result text
DISPATCH_AGENTS_WALL_CLOCK_TIMEOUT = 300  # Total dispatch timeout in seconds

# Calendar aliases: friendly names → {name, source} for disambiguation
# Lookup is case-insensitive. Resolves in _get_calendar_by_name().
CALENDAR_ALIASES = {
    "work": {"name": "CHG", "source": "Exchange"},
    "work calendar": {"name": "CHG", "source": "Exchange"},
    "chg": {"name": "CHG", "source": "Exchange"},
    "chg calendar": {"name": "CHG", "source": "Exchange"},
    "exchange": {"name": "CHG", "source": "Exchange"},
    "personal": {"name": "Calendar", "source": "iCloud"},
    "personal calendar": {"name": "Calendar", "source": "iCloud"},
}

# Unified connector routing state
CALENDAR_ROUTING_DB_PATH = DATA_DIR / "calendar-routing.db"
CALENDAR_REQUIRE_DUAL_READ = os.environ.get("CALENDAR_REQUIRE_DUAL_READ", "true").strip().lower() not in {"0", "false", "no"}

# Claude bridge settings for Microsoft 365 MCP connector access
CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
CLAUDE_MCP_CONFIG = os.environ.get("CLAUDE_MCP_CONFIG", "")
M365_BRIDGE_MODEL = os.environ.get("M365_BRIDGE_MODEL", "sonnet")
try:
    M365_BRIDGE_TIMEOUT_SECONDS = int(os.environ.get("M365_BRIDGE_TIMEOUT_SECONDS", "90"))
except ValueError:
    M365_BRIDGE_TIMEOUT_SECONDS = 90
try:
    M365_BRIDGE_DETECT_TIMEOUT_SECONDS = int(os.environ.get("M365_BRIDGE_DETECT_TIMEOUT_SECONDS", "5"))
except ValueError:
    M365_BRIDGE_DETECT_TIMEOUT_SECONDS = 5
