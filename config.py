import os
from pathlib import Path

BASE_DIR = Path(__file__).parent
AGENT_CONFIGS_DIR = BASE_DIR / "agent_configs"
DATA_DIR = BASE_DIR / "data"
MEMORY_DB_PATH = DATA_DIR / "memory.db"
CHROMA_PERSIST_DIR = DATA_DIR / "chroma"

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
DEFAULT_MODEL = "claude-sonnet-4-5-20250929"
CHIEF_MODEL = "claude-sonnet-4-5-20250929"

AGENT_TIMEOUT_SECONDS = 60
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50
