"""Server state and retry helper for MCP tools."""

import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


@dataclass
class SessionHealth:
    """Tracks session activity for checkpoint suggestions."""
    tool_call_count: int = 0
    session_start: str = ""
    last_checkpoint: str = ""

    def __post_init__(self):
        if not self.session_start:
            self.session_start = datetime.now().isoformat()

    def record_tool_call(self):
        self.tool_call_count += 1

    def record_checkpoint(self):
        self.last_checkpoint = datetime.now().isoformat()

    def to_dict(self) -> dict:
        return {
            "tool_call_count": self.tool_call_count,
            "session_start": self.session_start,
            "last_checkpoint": self.last_checkpoint or None,
        }


@dataclass
class ServerState:
    """Module-level state populated by the lifespan manager."""
    memory_store: Any = None
    document_store: Any = None
    agent_registry: Any = None
    apple_calendar_store: Any = None
    m365_bridge: Any = None
    calendar_store: Any = None
    reminder_store: Any = None
    mail_store: Any = None
    messages_store: Any = None
    okr_store: Any = None
    hook_registry: Any = None
    allowed_ingest_roots: Optional[list] = None
    session_health: SessionHealth = field(default_factory=SessionHealth)
    session_manager: Any = None
    session_brain: Any = None

    def update(self, values: dict) -> None:
        """Update state from a dictionary (for backward compatibility with tests)."""
        for key, value in values.items():
            if hasattr(self, key):
                setattr(self, key, value)

    def clear(self) -> None:
        """Clear all state (for backward compatibility with tests)."""
        self.memory_store = None
        self.document_store = None
        self.agent_registry = None
        self.apple_calendar_store = None
        self.m365_bridge = None
        self.calendar_store = None
        self.reminder_store = None
        self.mail_store = None
        self.messages_store = None
        self.okr_store = None
        self.hook_registry = None
        self.allowed_ingest_roots = None
        self.session_health = SessionHealth()
        self.session_manager = None
        self.session_brain = None

    def __setitem__(self, key: str, value: Any) -> None:
        """Dict-style assignment (for backward compatibility with tests)."""
        if hasattr(self, key):
            setattr(self, key, value)
        else:
            raise KeyError(f"ServerState has no attribute '{key}'")

    def __getitem__(self, key: str) -> Any:
        """Dict-style access (for backward compatibility with tests)."""
        if hasattr(self, key):
            return getattr(self, key)
        else:
            raise KeyError(f"ServerState has no attribute '{key}'")

    def pop(self, key: str, default: Any = None) -> Any:
        """Dict-style pop (for backward compatibility with tests)."""
        if hasattr(self, key):
            value = getattr(self, key)
            setattr(self, key, None)
            return value
        return default


def _retry_on_transient(func, *args, max_retries=2, **kwargs):
    """Simple retry wrapper for database/external operations with transient failures."""
    for attempt in range(max_retries + 1):
        try:
            return func(*args, **kwargs)
        except (sqlite3.OperationalError, OSError) as e:
            if attempt == max_retries:
                raise
            time.sleep(0.5 * (attempt + 1))
