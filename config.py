import os
from pathlib import Path

BASE_DIR = Path(__file__).parent
AGENT_CONFIGS_DIR = BASE_DIR / "agent_configs"
DATA_DIR = BASE_DIR / "data"
MEMORY_DB_PATH = DATA_DIR / "memory.db"
CHROMA_PERSIST_DIR = DATA_DIR / "chroma"

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
DEFAULT_MODEL = "claude-sonnet-4-5-20250929"

AGENT_TIMEOUT_SECONDS = 60
MAX_TOOL_ROUNDS = 25
VALID_FACT_CATEGORIES = {"personal", "preference", "work", "relationship", "backlog"}

OKR_DATA_DIR = DATA_DIR / "okr"
OKR_SPREADSHEET_DEFAULT = OKR_DATA_DIR / "2026_ISP_OKR_Master_Final.xlsx"

# Webhook inbox settings
WEBHOOK_INBOX_DIR = DATA_DIR / "webhook-inbox"
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")

# Scheduler settings
SCHEDULER_ENABLED = os.environ.get("SCHEDULER_ENABLED", "true").strip().lower() not in {"0", "false", "no"}

# Skill auto-creation settings
SKILL_SUGGESTION_THRESHOLD = 0.7
SKILL_MIN_OCCURRENCES = 5

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
