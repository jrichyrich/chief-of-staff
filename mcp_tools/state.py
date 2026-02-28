"""Server state and retry helper for MCP tools."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field, fields as dataclass_fields
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from agents.registry import AgentRegistry
    from apple_calendar.eventkit import CalendarStore
    from apple_mail.mail import MailStore
    from apple_messages.messages import MessageStore
    from apple_reminders.eventkit import ReminderStore
    from connectors.calendar_unified import UnifiedCalendarService
    from connectors.claude_m365_bridge import ClaudeM365Bridge
    from documents.store import DocumentStore
    from hooks.registry import HookRegistry
    from memory.store import MemoryStore
    from okr.store import OKRStore
    from session.brain import SessionBrain
    from session.manager import SessionManager


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

    def minutes_since_checkpoint(self) -> float:
        if self.last_checkpoint is None or self.last_checkpoint == "":
            return float('inf')
        delta = datetime.now() - datetime.fromisoformat(self.last_checkpoint)
        return delta.total_seconds() / 60

    def to_dict(self) -> dict:
        return {
            "tool_call_count": self.tool_call_count,
            "session_start": self.session_start,
            "last_checkpoint": self.last_checkpoint or None,
        }


@dataclass
class ServerState:
    """Module-level state populated by the lifespan manager."""
    memory_store: Optional[MemoryStore] = None
    document_store: Optional[DocumentStore] = None
    agent_registry: Optional[AgentRegistry] = None
    apple_calendar_store: Optional[CalendarStore] = None
    m365_bridge: Optional[ClaudeM365Bridge] = None
    calendar_store: Optional[UnifiedCalendarService] = None
    reminder_store: Optional[ReminderStore] = None
    mail_store: Optional[MailStore] = None
    messages_store: Optional[MessageStore] = None
    okr_store: Optional[OKRStore] = None
    hook_registry: Optional[HookRegistry] = None
    allowed_ingest_roots: Optional[list[Path]] = None
    session_health: SessionHealth = field(default_factory=SessionHealth)
    session_manager: Optional[SessionManager] = None
    session_brain: Optional[SessionBrain] = None

    @staticmethod
    def _field_names() -> frozenset[str]:
        """Return the set of declared dataclass field names."""
        return frozenset(f.name for f in dataclass_fields(ServerState))

    def update(self, values: dict) -> None:
        """Update state from a dictionary (for backward compatibility with tests)."""
        valid = self._field_names()
        for key, value in values.items():
            if key in valid:
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
        if key in self._field_names():
            setattr(self, key, value)
        else:
            raise KeyError(f"ServerState has no field '{key}'")

    def __getitem__(self, key: str) -> Any:
        """Dict-style access (for backward compatibility with tests)."""
        if key in self._field_names():
            return getattr(self, key)
        else:
            raise KeyError(f"ServerState has no field '{key}'")

    def pop(self, key: str, default: Any = None) -> Any:
        """Dict-style pop (for backward compatibility with tests)."""
        if key in self._field_names():
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
