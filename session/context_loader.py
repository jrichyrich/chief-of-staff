"""Proactive session context loader.

Fetches contextual data from multiple sources concurrently at server startup,
with per-source timeout and error isolation. Results are cached on ServerState
so the first get_session_status call returns rich data instantly.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from session.context_config import ContextLoaderConfig

if TYPE_CHECKING:
    from mcp_tools.state import ServerState

logger = logging.getLogger("jarvis-mcp")


@dataclass
class SessionContext:
    """Cached session context bundle."""

    loaded_at: str = ""
    calendar_events: list[dict] = field(default_factory=list)
    unread_mail_count: int = 0
    overdue_delegations: list[dict] = field(default_factory=list)
    pending_decisions: list[dict] = field(default_factory=list)
    due_reminders: list[dict] = field(default_factory=list)
    session_brain_summary: dict = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)
    _ttl_minutes: int = 15

    def to_dict(self) -> dict:
        return {
            "loaded_at": self.loaded_at,
            "calendar_events": self.calendar_events,
            "unread_mail_count": self.unread_mail_count,
            "overdue_delegations": self.overdue_delegations,
            "pending_decisions": self.pending_decisions,
            "due_reminders": self.due_reminders,
            "session_brain_summary": self.session_brain_summary,
            "errors": self.errors,
        }

    @property
    def is_stale(self) -> bool:
        """True if loaded_at is more than TTL minutes ago."""
        if not self.loaded_at:
            return True
        try:
            loaded = datetime.fromisoformat(self.loaded_at)
            return (datetime.now() - loaded) > timedelta(minutes=self._ttl_minutes)
        except (ValueError, TypeError):
            return True


# ---------------------------------------------------------------------------
# Individual source fetchers
# ---------------------------------------------------------------------------

def _fetch_calendar(state: ServerState) -> list[dict]:
    """Fetch today's calendar events from all providers."""
    if state.calendar_store is None:
        return []
    now = datetime.now()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    events = state.calendar_store.get_events(
        start_dt=start,
        end_dt=end,
        provider_preference="both",
    )
    # Cap at 50 events
    return events[:50]


def _fetch_mail_count(state: ServerState) -> int:
    """Sum unread mail counts across all mailboxes."""
    if state.mail_store is None:
        return 0
    mailboxes = state.mail_store.list_mailboxes()
    total = 0
    for mb in mailboxes:
        count = mb.get("unread_count", 0)
        if isinstance(count, int):
            total += count
    return total


def _fetch_overdue_delegations(state: ServerState) -> list[dict]:
    """Fetch active delegations past their due date."""
    if state.memory_store is None:
        return []
    delegations = state.memory_store.list_overdue_delegations()
    return [
        {
            "id": d.id,
            "task": d.task,
            "delegated_to": d.delegated_to,
            "due_date": d.due_date,
            "priority": str(d.priority),
        }
        for d in delegations
    ]


def _fetch_pending_decisions(state: ServerState) -> list[dict]:
    """Fetch decisions in pending_execution status."""
    if state.memory_store is None:
        return []
    from memory.models import DecisionStatus
    decisions = state.memory_store.list_decisions_by_status(
        DecisionStatus.pending_execution,
    )
    return [
        {
            "id": d.id,
            "title": d.title,
            "owner": d.owner,
            "follow_up_date": d.follow_up_date,
        }
        for d in decisions
    ]


def _fetch_due_reminders(state: ServerState) -> list[dict]:
    """Fetch incomplete reminders due today or overdue."""
    if state.reminder_store is None:
        return []
    try:
        reminders = state.reminder_store.list_reminders(completed=False)
    except Exception:
        return []
    today = datetime.now().date()
    due = []
    for r in reminders:
        due_date_str = r.get("due_date") or r.get("dueDate")
        if due_date_str:
            try:
                rd = datetime.fromisoformat(due_date_str).date()
                if rd <= today:
                    due.append(r)
            except (ValueError, TypeError):
                continue
    return due


def _fetch_brain_summary(state: ServerState) -> dict:
    """Extract open items and active workstreams from the session brain."""
    if state.session_brain is None:
        return {}
    brain_data = state.session_brain.to_dict()
    # Filter to active workstreams and open action items only
    return {
        "active_workstreams": brain_data.get("workstreams", []),
        "open_action_items": [
            item for item in brain_data.get("action_items", [])
            if not item.get("done")
        ],
        "recent_decisions": brain_data.get("decisions", [])[-5:],
        "handoff_notes": brain_data.get("handoff_notes", []),
    }


# ---------------------------------------------------------------------------
# Main loader
# ---------------------------------------------------------------------------

# Maps source name -> (fetcher_function, result_field_on_SessionContext)
_SOURCE_FETCHERS: dict[str, tuple] = {
    "calendar": (_fetch_calendar, "calendar_events"),
    "mail": (_fetch_mail_count, "unread_mail_count"),
    "delegations": (_fetch_overdue_delegations, "overdue_delegations"),
    "decisions": (_fetch_pending_decisions, "pending_decisions"),
    "reminders": (_fetch_due_reminders, "due_reminders"),
    "brain": (_fetch_brain_summary, "session_brain_summary"),
}


def load_session_context(
    state: ServerState,
    config: ContextLoaderConfig | None = None,
) -> SessionContext:
    """Fetch context from all enabled sources concurrently.

    Uses ThreadPoolExecutor for concurrency since most backends
    (EventKit, AppleScript, SQLite) are synchronous. Each source
    gets its own timeout via concurrent.futures.
    """
    if config is None:
        config = ContextLoaderConfig()

    ctx = SessionContext(
        loaded_at=datetime.now().isoformat(),
        _ttl_minutes=config.ttl_minutes,
    )

    if not config.enabled:
        return ctx

    # Determine which sources to fetch
    enabled_sources = {
        name: info
        for name, info in _SOURCE_FETCHERS.items()
        if config.sources.get(name, True)
    }

    if not enabled_sources:
        return ctx

    timeout = config.per_source_timeout_seconds

    with ThreadPoolExecutor(max_workers=len(enabled_sources)) as pool:
        futures = {}
        for source_name, (fetcher, _field) in enabled_sources.items():
            futures[source_name] = pool.submit(fetcher, state)

        for source_name, future in futures.items():
            _fetcher, field_name = enabled_sources[source_name]
            try:
                result = future.result(timeout=timeout)
                setattr(ctx, field_name, result)
            except FuturesTimeoutError:
                ctx.errors[source_name] = f"Timeout after {timeout}s"
                logger.warning("Context fetch timed out: %s", source_name)
            except Exception as exc:
                ctx.errors[source_name] = str(exc)
                logger.warning("Context fetch failed: %s — %s", source_name, exc)

    return ctx
