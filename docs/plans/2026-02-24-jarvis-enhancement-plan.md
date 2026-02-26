# Jarvis Enhancement Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add four capabilities to Jarvis: Channel Routing (safety tiers + situational delivery), Session Brain (persistent context across sessions), Proactive Engine Enhancement (push-based intelligence), and Team Playbooks (YAML-defined parallel workstreams).

**Architecture:** Build bottom-up -- Channel Routing first (delivery foundation), then Session Brain (context persistence), then Proactive Engine (consumes both), then Playbooks (mostly independent). Each component adds a new module and MCP tools, following the existing `register(mcp, state)` pattern.

**Tech Stack:** Python 3.11+, SQLite (MemoryStore), FastMCP, PyObjC (macOS), Playwright (Teams), YAML (playbook definitions).

**Design doc:** `docs/plans/2026-02-24-jarvis-enhancement-design.md`

---

## Task 1: Channel Router -- Safety Tier Model

**Files:**
- Create: `channels/routing.py`
- Test: `tests/test_channel_routing.py`

**Step 1: Write the failing test**

```python
# tests/test_channel_routing.py
"""Tests for channel routing: safety tiers, channel selection, time-of-day awareness."""

import pytest
from channels.routing import (
    SafetyTier,
    determine_safety_tier,
    select_channel,
)


class TestSafetyTier:
    def test_self_recipient_returns_tier1(self):
        tier = determine_safety_tier(recipient_type="self")
        assert tier == SafetyTier.AUTO_SEND

    def test_known_internal_returns_tier2(self):
        tier = determine_safety_tier(recipient_type="internal")
        assert tier == SafetyTier.CONFIRM

    def test_external_returns_tier3(self):
        tier = determine_safety_tier(recipient_type="external")
        assert tier == SafetyTier.DRAFT_ONLY

    def test_sensitive_topic_bumps_tier(self):
        tier = determine_safety_tier(recipient_type="internal", sensitive=True)
        assert tier == SafetyTier.DRAFT_ONLY

    def test_first_contact_returns_tier3(self):
        tier = determine_safety_tier(recipient_type="internal", first_contact=True)
        assert tier == SafetyTier.DRAFT_ONLY

    def test_override_auto(self):
        tier = determine_safety_tier(recipient_type="internal", override="auto")
        assert tier == SafetyTier.AUTO_SEND

    def test_override_draft_only(self):
        tier = determine_safety_tier(recipient_type="self", override="draft_only")
        assert tier == SafetyTier.DRAFT_ONLY


class TestSelectChannel:
    def test_self_urgent_returns_imessage(self):
        channel = select_channel(recipient_type="self", urgency="urgent")
        assert channel == "imessage"

    def test_self_informational_returns_email(self):
        channel = select_channel(recipient_type="self", urgency="informational")
        assert channel == "email"

    def test_self_ephemeral_returns_notification(self):
        channel = select_channel(recipient_type="self", urgency="ephemeral")
        assert channel == "notification"

    def test_internal_work_hours_informal_returns_teams(self):
        channel = select_channel(
            recipient_type="internal", urgency="informal", work_hours=True,
        )
        assert channel == "teams"

    def test_internal_work_hours_formal_returns_email(self):
        channel = select_channel(
            recipient_type="internal", urgency="formal", work_hours=True,
        )
        assert channel == "email"

    def test_external_always_email(self):
        channel = select_channel(recipient_type="external", urgency="urgent")
        assert channel == "email"

    def test_off_hours_internal_urgent_returns_imessage(self):
        channel = select_channel(
            recipient_type="internal", urgency="urgent", work_hours=False,
        )
        assert channel == "imessage"

    def test_off_hours_internal_non_urgent_returns_queued(self):
        channel = select_channel(
            recipient_type="internal", urgency="informational", work_hours=False,
        )
        assert channel == "queued"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_channel_routing.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'channels.routing'`

**Step 3: Write minimal implementation**

```python
# channels/routing.py
"""Channel routing: safety tiers and channel selection for outbound messages."""

from __future__ import annotations

import enum
from datetime import datetime


class SafetyTier(enum.Enum):
    AUTO_SEND = "auto_send"       # Tier 1: no confirmation
    CONFIRM = "confirm"           # Tier 2: preview + approve
    DRAFT_ONLY = "draft_only"     # Tier 3: human sends manually


# Keywords that bump a message to a higher safety tier
_SENSITIVE_TOPICS = frozenset({
    "legal", "hr", "security", "financial", "termination",
    "compliance", "confidential", "hipaa", "pii",
})


def determine_safety_tier(
    *,
    recipient_type: str,                    # "self", "internal", "external"
    sensitive: bool = False,
    first_contact: bool = False,
    override: str | None = None,            # "auto", "confirm", "draft_only"
) -> SafetyTier:
    """Determine the safety tier for an outbound message.

    Args:
        recipient_type: "self", "internal", or "external".
        sensitive: True if the topic is sensitive (legal, HR, etc.).
        first_contact: True if this is the first message to the recipient.
        override: Explicit tier override from playbook or user preference.
    """
    if override:
        mapping = {
            "auto": SafetyTier.AUTO_SEND,
            "confirm": SafetyTier.CONFIRM,
            "draft_only": SafetyTier.DRAFT_ONLY,
        }
        return mapping.get(override, SafetyTier.CONFIRM)

    # Base tier from recipient type
    base = {
        "self": SafetyTier.AUTO_SEND,
        "internal": SafetyTier.CONFIRM,
        "external": SafetyTier.DRAFT_ONLY,
    }.get(recipient_type, SafetyTier.DRAFT_ONLY)

    # Bump up for sensitive topics or first contact
    if sensitive or first_contact:
        if base == SafetyTier.AUTO_SEND:
            return SafetyTier.CONFIRM
        return SafetyTier.DRAFT_ONLY

    return base


def is_sensitive_topic(text: str) -> bool:
    """Check if text contains sensitive topic keywords."""
    lower = text.lower()
    return any(kw in lower for kw in _SENSITIVE_TOPICS)


def select_channel(
    *,
    recipient_type: str,                    # "self", "internal", "external"
    urgency: str = "informational",         # "urgent", "informational", "formal", "informal", "ephemeral"
    work_hours: bool = True,
) -> str:
    """Select the best delivery channel based on recipient, urgency, and time.

    Returns one of: "email", "imessage", "teams", "notification", "queued".
    """
    if recipient_type == "self":
        return {
            "urgent": "imessage",
            "ephemeral": "notification",
        }.get(urgency, "email")

    if recipient_type == "external":
        return "email"

    # Internal recipients
    if not work_hours:
        if urgency == "urgent":
            return "imessage"
        return "queued"

    # Work hours, internal
    if urgency in ("formal",):
        return "email"
    if urgency in ("informal", "urgent"):
        return "teams"
    return "email"


def is_work_hours(now: datetime | None = None) -> bool:
    """Check if current time is within work hours (8am-6pm weekdays)."""
    now = now or datetime.now()
    if now.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    return 8 <= now.hour < 18
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_channel_routing.py -v`
Expected: PASS (all 11 tests)

**Step 5: Commit**

```bash
git add channels/routing.py tests/test_channel_routing.py
git commit -m "feat: add channel routing with safety tiers and channel selection"
```

---

## Task 2: Teams Delivery Adapter

**Files:**
- Modify: `scheduler/delivery.py:20,107-111`
- Test: `tests/test_delivery.py` (extend)

**Step 1: Write the failing test**

Add to `tests/test_delivery.py`:

```python
from scheduler.delivery import TeamsDeliveryAdapter

class TestTeamsDeliveryAdapter:
    @patch("scheduler.delivery.TeamsDeliveryAdapter._get_poster")
    def test_deliver_with_target(self, mock_poster_fn):
        mock_poster = MagicMock()
        mock_poster.prepare_message.return_value = {"status": "prepared"}
        mock_poster.send_prepared.return_value = {"status": "sent"}
        mock_poster_fn.return_value = mock_poster

        adapter = TeamsDeliveryAdapter()
        result = adapter.deliver(
            "Hello team", {"target": "General"}, task_name="test"
        )
        assert result["status"] == "delivered"
        assert result["channel"] == "teams"
        mock_poster.prepare_message.assert_called_once()

    @patch("scheduler.delivery.TeamsDeliveryAdapter._get_poster")
    def test_deliver_no_target_returns_error(self, mock_poster_fn):
        adapter = TeamsDeliveryAdapter()
        result = adapter.deliver("Hello", {}, task_name="test")
        assert result["status"] == "error"

    def test_teams_in_valid_channels(self):
        assert "teams" in VALID_CHANNELS

    def test_get_delivery_adapter_teams(self):
        adapter = get_delivery_adapter("teams")
        assert isinstance(adapter, TeamsDeliveryAdapter)
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_delivery.py::TestTeamsDeliveryAdapter -v`
Expected: FAIL with `ImportError: cannot import name 'TeamsDeliveryAdapter'`

**Step 3: Write minimal implementation**

In `scheduler/delivery.py`, add after `NotificationDeliveryAdapter` (after line 104):

```python
class TeamsDeliveryAdapter(DeliveryAdapter):
    """Deliver task results via Microsoft Teams (Playwright browser)."""

    def _get_poster(self):
        from browser.teams_poster import PlaywrightTeamsPoster
        from browser.manager import TeamsBrowserManager
        return PlaywrightTeamsPoster(manager=TeamsBrowserManager())

    def deliver(self, result_text: str, config: dict, task_name: str = "") -> dict:
        target = config.get("target", "")
        if not target:
            return {"status": "error", "error": "No target in delivery_config.target"}

        template_vars = _build_template_vars(result_text, task_name)
        body_template = config.get("body_template", "$result")
        body = Template(body_template).safe_substitute(template_vars)

        auto_send = config.get("auto_send", True)
        poster = self._get_poster()
        result = poster.prepare_message(target=target, message=body)
        if auto_send:
            result = poster.send_prepared()
        return {"status": "delivered", "channel": "teams", "detail": result}
```

Update `VALID_CHANNELS` (line 20):
```python
VALID_CHANNELS = frozenset({"email", "imessage", "notification", "teams"})
```

Update `_ADAPTERS` dict (line 107-111):
```python
_ADAPTERS: dict[str, type[DeliveryAdapter]] = {
    "email": EmailDeliveryAdapter,
    "imessage": IMessageDeliveryAdapter,
    "notification": NotificationDeliveryAdapter,
    "teams": TeamsDeliveryAdapter,
}
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_delivery.py::TestTeamsDeliveryAdapter -v`
Expected: PASS

**Step 5: Commit**

```bash
git add scheduler/delivery.py tests/test_delivery.py
git commit -m "feat: add Teams delivery adapter to scheduler delivery system"
```

---

## Task 3: Channel Routing MCP Tool

**Files:**
- Create: `mcp_tools/routing_tools.py`
- Modify: `mcp_server.py:194-237` (add import and register call)
- Modify: `mcp_tools/state.py:36-51` (no changes needed -- routing is stateless)
- Test: `tests/test_routing_tools.py`

**Step 1: Write the failing test**

```python
# tests/test_routing_tools.py
"""Tests for channel routing MCP tools."""

import json
import pytest

import mcp_server  # trigger registration
from mcp_tools.routing_tools import route_message


@pytest.fixture
def state():
    from mcp_tools.state import ServerState
    return ServerState()


class TestRouteMessage:
    @pytest.mark.asyncio
    async def test_self_recipient(self):
        result = json.loads(await route_message(
            recipient_type="self",
            urgency="informational",
        ))
        assert result["safety_tier"] == "auto_send"
        assert result["channel"] == "email"

    @pytest.mark.asyncio
    async def test_external_recipient(self):
        result = json.loads(await route_message(
            recipient_type="external",
        ))
        assert result["safety_tier"] == "draft_only"
        assert result["channel"] == "email"

    @pytest.mark.asyncio
    async def test_sensitive_bumps_tier(self):
        result = json.loads(await route_message(
            recipient_type="internal",
            sensitive=True,
        ))
        assert result["safety_tier"] == "draft_only"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_routing_tools.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mcp_tools.routing_tools'`

**Step 3: Write minimal implementation**

```python
# mcp_tools/routing_tools.py
"""Channel routing tools for the Chief of Staff MCP server."""

import json
import logging
import sys

logger = logging.getLogger("jarvis-mcp")


def register(mcp, state):
    """Register channel routing tools with the FastMCP server."""

    @mcp.tool()
    async def route_message(
        recipient_type: str,
        urgency: str = "informational",
        sensitive: bool = False,
        first_contact: bool = False,
        override: str = "",
    ) -> str:
        """Determine the safety tier and delivery channel for an outbound message.

        Use this before sending any message to determine whether it should be
        auto-sent, confirmed first, or left as a draft for the user.

        Args:
            recipient_type: "self", "internal", or "external"
            urgency: "urgent", "informational", "formal", "informal", "ephemeral"
            sensitive: True if topic involves legal, HR, security, financial, etc.
            first_contact: True if this is the first message to this recipient
            override: Explicit tier override: "auto", "confirm", or "draft_only"
        """
        from channels.routing import (
            SafetyTier,
            determine_safety_tier,
            is_work_hours,
            select_channel,
        )

        tier = determine_safety_tier(
            recipient_type=recipient_type,
            sensitive=sensitive,
            first_contact=first_contact,
            override=override or None,
        )
        channel = select_channel(
            recipient_type=recipient_type,
            urgency=urgency,
            work_hours=is_work_hours(),
        )

        return json.dumps({
            "safety_tier": tier.value,
            "channel": channel,
            "recipient_type": recipient_type,
            "urgency": urgency,
            "work_hours": is_work_hours(),
        })

    # Expose for testing
    module = sys.modules[__name__]
    module.route_message = route_message
```

Add to `mcp_server.py` -- import (after line 214):
```python
    routing_tools,
```

Register (after line 237):
```python
routing_tools.register(mcp, _state)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_routing_tools.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add mcp_tools/routing_tools.py tests/test_routing_tools.py mcp_server.py
git commit -m "feat: add route_message MCP tool for safety tier and channel selection"
```

---

## Task 4: Session Brain -- Core Model and File I/O

**Files:**
- Create: `session/brain.py`
- Test: `tests/test_session_brain.py`

**Step 1: Write the failing test**

```python
# tests/test_session_brain.py
"""Tests for Session Brain: persistent cross-session context."""

import pytest
from pathlib import Path
from session.brain import SessionBrain


@pytest.fixture
def brain_path(tmp_path):
    return tmp_path / "session_brain.md"


@pytest.fixture
def brain(brain_path):
    return SessionBrain(brain_path)


class TestSessionBrainInit:
    def test_creates_empty_brain_file(self, brain, brain_path):
        brain.save()
        assert brain_path.exists()
        content = brain_path.read_text()
        assert "# Session Brain" in content

    def test_load_existing_brain(self, brain, brain_path):
        brain.add_workstream("Project X", "active", "In progress")
        brain.save()
        loaded = SessionBrain(brain_path)
        loaded.load()
        assert len(loaded.workstreams) == 1
        assert loaded.workstreams[0]["name"] == "Project X"


class TestWorkstreams:
    def test_add_workstream(self, brain):
        brain.add_workstream("Project X", "active", "Working on phase 1")
        assert len(brain.workstreams) == 1
        assert brain.workstreams[0]["status"] == "active"

    def test_update_workstream_status(self, brain):
        brain.add_workstream("Project X", "active", "Phase 1")
        brain.update_workstream("Project X", status="completed", context="Done")
        assert brain.workstreams[0]["status"] == "completed"

    def test_update_nonexistent_workstream_adds_it(self, brain):
        brain.update_workstream("New Project", status="active", context="Just started")
        assert len(brain.workstreams) == 1


class TestActionItems:
    def test_add_action_item(self, brain):
        brain.add_action_item("Fix the bug", source="session")
        assert len(brain.action_items) == 1
        assert brain.action_items[0]["text"] == "Fix the bug"
        assert brain.action_items[0]["done"] is False

    def test_complete_action_item(self, brain):
        brain.add_action_item("Fix the bug")
        brain.complete_action_item("Fix the bug")
        assert brain.action_items[0]["done"] is True

    def test_complete_nonexistent_is_noop(self, brain):
        brain.complete_action_item("Nonexistent")  # no error


class TestDecisions:
    def test_add_decision(self, brain):
        brain.add_decision("Use Approach C for enhancement")
        assert len(brain.decisions) == 1

    def test_decisions_have_date(self, brain):
        brain.add_decision("Chose Python")
        assert "date" in brain.decisions[0]


class TestPeopleContext:
    def test_add_person(self, brain):
        brain.add_person("Maria Torres", "CIO, Alex's manager")
        assert len(brain.people) == 1

    def test_update_person(self, brain):
        brain.add_person("Maria", "CIO")
        brain.add_person("Maria", "CIO, Alex's manager")
        assert len(brain.people) == 1
        assert "Alex's manager" in brain.people[0]["context"]


class TestHandoffNotes:
    def test_add_handoff_note(self, brain):
        brain.add_handoff_note("M365 write not available")
        assert len(brain.handoff_notes) == 1

    def test_no_duplicate_notes(self, brain):
        brain.add_handoff_note("M365 write not available")
        brain.add_handoff_note("M365 write not available")
        assert len(brain.handoff_notes) == 1


class TestRoundTrip:
    def test_save_and_load_preserves_all_data(self, brain, brain_path):
        brain.add_workstream("Project X", "active", "Phase 1")
        brain.add_action_item("Fix bug", source="email")
        brain.add_decision("Use Python 3.11")
        brain.add_person("Alice", "Engineer")
        brain.add_handoff_note("Run tests before deploy")
        brain.save()

        loaded = SessionBrain(brain_path)
        loaded.load()
        assert len(loaded.workstreams) == 1
        assert len(loaded.action_items) == 1
        assert len(loaded.decisions) == 1
        assert len(loaded.people) == 1
        assert len(loaded.handoff_notes) == 1


class TestRender:
    def test_render_contains_all_sections(self, brain):
        brain.add_workstream("Project X", "active", "Phase 1")
        brain.add_action_item("Fix bug")
        brain.add_decision("Use Python")
        brain.add_person("Alice", "Engineer")
        brain.add_handoff_note("Always test")
        text = brain.render()
        assert "## Active Workstreams" in text
        assert "## Open Action Items" in text
        assert "## Recent Decisions" in text
        assert "## Key People Context" in text
        assert "## Session Handoff Notes" in text
        assert "Project X" in text
        assert "Fix bug" in text
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_session_brain.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'session.brain'`

**Step 3: Write minimal implementation**

```python
# session/brain.py
"""Session Brain: persistent cross-session context document.

Maintains a human-readable markdown file with workstreams, action items,
decisions, people context, and handoff notes that carry across sessions.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_SECTION_PATTERN = re.compile(r"^## (.+)$", re.MULTILINE)


class SessionBrain:
    """Manages persistent session context in a markdown file."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.workstreams: list[dict] = []
        self.action_items: list[dict] = []
        self.decisions: list[dict] = []
        self.people: list[dict] = []
        self.handoff_notes: list[str] = []
        self._last_updated: str = ""

    def load(self) -> None:
        """Load brain state from the markdown file."""
        if not self.path.exists():
            return
        text = self.path.read_text(encoding="utf-8")
        self._parse(text)

    def save(self) -> None:
        """Save brain state to the markdown file."""
        self._last_updated = datetime.now().isoformat()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(self.render(), encoding="utf-8")

    # --- Mutation methods ---

    def add_workstream(self, name: str, status: str, context: str) -> None:
        for ws in self.workstreams:
            if ws["name"] == name:
                ws["status"] = status
                ws["context"] = context
                return
        self.workstreams.append({"name": name, "status": status, "context": context})

    def update_workstream(self, name: str, *, status: str, context: str) -> None:
        self.add_workstream(name, status, context)

    def add_action_item(self, text: str, source: str = "") -> None:
        self.action_items.append({
            "text": text,
            "done": False,
            "source": source,
            "added": datetime.now().strftime("%Y-%m-%d"),
        })

    def complete_action_item(self, text: str) -> None:
        for item in self.action_items:
            if item["text"] == text:
                item["done"] = True
                return

    def add_decision(self, summary: str) -> None:
        self.decisions.append({
            "date": datetime.now().strftime("%Y-%m-%d"),
            "summary": summary,
        })

    def add_person(self, name: str, context: str) -> None:
        for p in self.people:
            if p["name"] == name:
                p["context"] = context
                return
        self.people.append({"name": name, "context": context})

    def add_handoff_note(self, note: str) -> None:
        if note not in self.handoff_notes:
            self.handoff_notes.append(note)

    # --- Rendering ---

    def render(self) -> str:
        """Render the brain as a markdown document."""
        lines = [
            "# Session Brain",
            f"Last updated: {self._last_updated or datetime.now().isoformat()}",
            "",
        ]

        lines.append("## Active Workstreams")
        if self.workstreams:
            for ws in self.workstreams:
                lines.append(f"- {ws['name']}: {ws['status'].upper()} - {ws['context']}")
        else:
            lines.append("- (none)")
        lines.append("")

        lines.append("## Open Action Items")
        if self.action_items:
            for item in self.action_items:
                check = "x" if item["done"] else " "
                source = f" ({item['source']}, {item['added']})" if item.get("source") else f" ({item['added']})"
                lines.append(f"- [{check}] {item['text']}{source}")
        else:
            lines.append("- (none)")
        lines.append("")

        lines.append("## Recent Decisions")
        if self.decisions:
            for d in self.decisions:
                lines.append(f"- {d['date']}: {d['summary']}")
        else:
            lines.append("- (none)")
        lines.append("")

        lines.append("## Key People Context")
        if self.people:
            for p in self.people:
                lines.append(f"- {p['name']}: {p['context']}")
        else:
            lines.append("- (none)")
        lines.append("")

        lines.append("## Session Handoff Notes")
        if self.handoff_notes:
            for note in self.handoff_notes:
                lines.append(f"- {note}")
        else:
            lines.append("- (none)")
        lines.append("")

        return "\n".join(lines)

    # --- Parsing ---

    def _parse(self, text: str) -> None:
        """Parse a rendered Session Brain markdown file back into structured data."""
        sections: dict[str, list[str]] = {}
        current_section = ""
        for line in text.splitlines():
            match = _SECTION_PATTERN.match(line)
            if match:
                current_section = match.group(1).strip()
                sections[current_section] = []
            elif current_section and line.startswith("- "):
                sections[current_section].append(line[2:].strip())

        # Parse workstreams
        self.workstreams = []
        for item in sections.get("Active Workstreams", []):
            if item == "(none)":
                continue
            parts = item.split(":", 1)
            if len(parts) == 2:
                name = parts[0].strip()
                rest = parts[1].strip()
                status_ctx = rest.split(" - ", 1)
                status = status_ctx[0].strip().lower()
                context = status_ctx[1].strip() if len(status_ctx) > 1 else ""
                self.workstreams.append({"name": name, "status": status, "context": context})

        # Parse action items
        self.action_items = []
        for item in sections.get("Open Action Items", []):
            if item == "(none)":
                continue
            done = item.startswith("[x]")
            text_part = re.sub(r"^\[[ x]\]\s*", "", item)
            # Extract source and date from parenthetical
            source_match = re.search(r"\(([^)]+)\)$", text_part)
            source = ""
            added = ""
            if source_match:
                text_part = text_part[:source_match.start()].strip()
                parts = source_match.group(1).split(", ")
                if len(parts) == 2:
                    source, added = parts
                elif len(parts) == 1:
                    added = parts[0]
            self.action_items.append({
                "text": text_part,
                "done": done,
                "source": source,
                "added": added,
            })

        # Parse decisions
        self.decisions = []
        for item in sections.get("Recent Decisions", []):
            if item == "(none)":
                continue
            parts = item.split(":", 1)
            if len(parts) == 2:
                self.decisions.append({
                    "date": parts[0].strip(),
                    "summary": parts[1].strip(),
                })

        # Parse people
        self.people = []
        for item in sections.get("Key People Context", []):
            if item == "(none)":
                continue
            parts = item.split(":", 1)
            if len(parts) == 2:
                self.people.append({
                    "name": parts[0].strip(),
                    "context": parts[1].strip(),
                })

        # Parse handoff notes
        self.handoff_notes = []
        for item in sections.get("Session Handoff Notes", []):
            if item != "(none)":
                self.handoff_notes.append(item)

    # --- Convenience ---

    def to_dict(self) -> dict:
        """Return brain state as a dictionary."""
        return {
            "last_updated": self._last_updated,
            "workstreams": self.workstreams,
            "action_items": self.action_items,
            "decisions": self.decisions,
            "people": self.people,
            "handoff_notes": self.handoff_notes,
        }
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_session_brain.py -v`
Expected: PASS (all 15 tests)

**Step 5: Commit**

```bash
git add session/brain.py tests/test_session_brain.py
git commit -m "feat: add Session Brain for persistent cross-session context"
```

---

## Task 5: Session Brain -- MCP Tools

**Files:**
- Create: `mcp_tools/brain_tools.py`
- Modify: `mcp_server.py:121-122` (init SessionBrain in lifespan)
- Modify: `mcp_tools/state.py:51` (add `session_brain` field)
- Modify: `config.py` (add `SESSION_BRAIN_PATH`)
- Test: `tests/test_brain_tools.py`

**Step 1: Write the failing test**

```python
# tests/test_brain_tools.py
"""Tests for Session Brain MCP tools."""

import json
import pytest

import mcp_server  # trigger registration
from mcp_tools.brain_tools import (
    get_session_brain,
    update_session_brain,
)
from mcp_tools.state import ServerState
from session.brain import SessionBrain


@pytest.fixture
def brain(tmp_path):
    return SessionBrain(tmp_path / "session_brain.md")


@pytest.fixture
def state(brain):
    s = ServerState()
    s.session_brain = brain
    return s


class TestGetSessionBrain:
    @pytest.mark.asyncio
    async def test_returns_empty_brain(self, brain, monkeypatch):
        import mcp_tools.brain_tools as mod
        monkeypatch.setattr(mod, "_get_brain", lambda: brain)
        result = json.loads(await get_session_brain())
        assert result["workstreams"] == []
        assert result["action_items"] == []

    @pytest.mark.asyncio
    async def test_returns_populated_brain(self, brain, monkeypatch):
        import mcp_tools.brain_tools as mod
        brain.add_workstream("Project X", "active", "Phase 1")
        brain.add_action_item("Fix bug")
        monkeypatch.setattr(mod, "_get_brain", lambda: brain)
        result = json.loads(await get_session_brain())
        assert len(result["workstreams"]) == 1
        assert len(result["action_items"]) == 1


class TestUpdateSessionBrain:
    @pytest.mark.asyncio
    async def test_add_workstream(self, brain, monkeypatch):
        import mcp_tools.brain_tools as mod
        monkeypatch.setattr(mod, "_get_brain", lambda: brain)
        result = json.loads(await update_session_brain(
            action="add_workstream",
            data=json.dumps({"name": "Project X", "status": "active", "context": "Phase 1"}),
        ))
        assert result["status"] == "updated"
        assert len(brain.workstreams) == 1

    @pytest.mark.asyncio
    async def test_add_action_item(self, brain, monkeypatch):
        import mcp_tools.brain_tools as mod
        monkeypatch.setattr(mod, "_get_brain", lambda: brain)
        result = json.loads(await update_session_brain(
            action="add_action_item",
            data=json.dumps({"text": "Fix the bug", "source": "email"}),
        ))
        assert result["status"] == "updated"
        assert len(brain.action_items) == 1

    @pytest.mark.asyncio
    async def test_complete_action_item(self, brain, monkeypatch):
        import mcp_tools.brain_tools as mod
        brain.add_action_item("Fix bug")
        monkeypatch.setattr(mod, "_get_brain", lambda: brain)
        result = json.loads(await update_session_brain(
            action="complete_action_item",
            data=json.dumps({"text": "Fix bug"}),
        ))
        assert result["status"] == "updated"
        assert brain.action_items[0]["done"] is True

    @pytest.mark.asyncio
    async def test_invalid_action_returns_error(self, brain, monkeypatch):
        import mcp_tools.brain_tools as mod
        monkeypatch.setattr(mod, "_get_brain", lambda: brain)
        result = json.loads(await update_session_brain(
            action="invalid_action",
            data="{}",
        ))
        assert "error" in result
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_brain_tools.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mcp_tools.brain_tools'`

**Step 3: Write minimal implementation**

Add to `config.py` (after line 8):
```python
SESSION_BRAIN_PATH = DATA_DIR / "session_brain.md"
```

Add to `mcp_tools/state.py` field (after line 51):
```python
    session_brain: Any = None
```

Also update `clear()` method in `state.py` to include:
```python
        self.session_brain = None
```

```python
# mcp_tools/brain_tools.py
"""Session Brain tools for the Chief of Staff MCP server."""

import json
import logging
import sys

logger = logging.getLogger("jarvis-mcp")

_state_ref = None


def _get_brain():
    """Get the session brain from state (allows monkeypatching in tests)."""
    if _state_ref and _state_ref.session_brain:
        return _state_ref.session_brain
    return None


def register(mcp, state):
    """Register Session Brain tools with the FastMCP server."""
    global _state_ref
    _state_ref = state

    @mcp.tool()
    async def get_session_brain() -> str:
        """Get the current Session Brain -- persistent cross-session context.

        Returns the full brain state: active workstreams, open action items,
        recent decisions, key people context, and session handoff notes.
        This is loaded at session start and carries context across conversations.
        """
        brain = _get_brain()
        if brain is None:
            return json.dumps({"error": "Session brain not initialized"})
        brain.load()
        return json.dumps(brain.to_dict())

    @mcp.tool()
    async def update_session_brain(action: str, data: str) -> str:
        """Update the Session Brain with new information.

        Args:
            action: One of: add_workstream, update_workstream, add_action_item,
                    complete_action_item, add_decision, add_person, add_handoff_note
            data: JSON string with action-specific fields:
                - add_workstream: {"name", "status", "context"}
                - add_action_item: {"text", "source"?}
                - complete_action_item: {"text"}
                - add_decision: {"summary"}
                - add_person: {"name", "context"}
                - add_handoff_note: {"note"}
        """
        brain = _get_brain()
        if brain is None:
            return json.dumps({"error": "Session brain not initialized"})

        try:
            params = json.loads(data)
        except json.JSONDecodeError as e:
            return json.dumps({"error": f"Invalid JSON in data: {e}"})

        actions = {
            "add_workstream": lambda p: brain.add_workstream(
                p["name"], p["status"], p["context"],
            ),
            "update_workstream": lambda p: brain.update_workstream(
                p["name"], status=p["status"], context=p["context"],
            ),
            "add_action_item": lambda p: brain.add_action_item(
                p["text"], source=p.get("source", ""),
            ),
            "complete_action_item": lambda p: brain.complete_action_item(p["text"]),
            "add_decision": lambda p: brain.add_decision(p["summary"]),
            "add_person": lambda p: brain.add_person(p["name"], p["context"]),
            "add_handoff_note": lambda p: brain.add_handoff_note(p["note"]),
        }

        handler = actions.get(action)
        if handler is None:
            return json.dumps({"error": f"Unknown action: {action}. Valid: {list(actions.keys())}"})

        try:
            handler(params)
            brain.save()
            return json.dumps({"status": "updated", "action": action})
        except (KeyError, TypeError) as e:
            return json.dumps({"error": f"Missing required field: {e}"})

    # Expose for testing
    module = sys.modules[__name__]
    module.get_session_brain = get_session_brain
    module.update_session_brain = update_session_brain
```

Add to `mcp_server.py` lifespan (after line 122):
```python
    # Initialize session brain
    from session.brain import SessionBrain
    _state.session_brain = SessionBrain(app_config.SESSION_BRAIN_PATH)
    _state.session_brain.load()
```

Add import and register in `mcp_server.py` (alongside other modules):
```python
    brain_tools,
```
```python
brain_tools.register(mcp, _state)
```

Also reset in lifespan cleanup:
```python
        _state.session_brain = None
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_brain_tools.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add config.py mcp_tools/state.py mcp_tools/brain_tools.py session/brain.py mcp_server.py tests/test_brain_tools.py
git commit -m "feat: add Session Brain MCP tools (get/update) with lifespan integration"
```

---

## Task 6: Session Manager -- Wire Flush to Session Brain

**Files:**
- Modify: `session/manager.py:41-45,106-177`
- Test: `tests/test_session_manager.py` (extend)

**Step 1: Write the failing test**

Add to `tests/test_session_manager.py`:

```python
from session.brain import SessionBrain

class TestFlushUpdatesSessionBrain:
    def test_flush_stores_decisions_in_brain(self, tmp_path):
        store = MemoryStore(tmp_path / "test.db")
        brain = SessionBrain(tmp_path / "brain.md")
        mgr = SessionManager(store, session_brain=brain)
        mgr.track_interaction("assistant", "We decided to use Python 3.11")
        mgr.flush()
        assert len(brain.decisions) >= 1
        store.close()

    def test_flush_stores_action_items_in_brain(self, tmp_path):
        store = MemoryStore(tmp_path / "test.db")
        brain = SessionBrain(tmp_path / "brain.md")
        mgr = SessionManager(store, session_brain=brain)
        mgr.track_interaction("assistant", "TODO: file the IC3 report")
        mgr.flush()
        assert len(brain.action_items) >= 1
        store.close()

    def test_flush_saves_brain_to_disk(self, tmp_path):
        store = MemoryStore(tmp_path / "test.db")
        brain_path = tmp_path / "brain.md"
        brain = SessionBrain(brain_path)
        mgr = SessionManager(store, session_brain=brain)
        mgr.track_interaction("assistant", "We decided to use Python")
        mgr.flush()
        assert brain_path.exists()
        store.close()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_session_manager.py::TestFlushUpdatesSessionBrain -v`
Expected: FAIL with `TypeError: SessionManager.__init__() got an unexpected keyword argument 'session_brain'`

**Step 3: Write minimal implementation**

Modify `session/manager.py`:

Constructor (line 41-45) -- add `session_brain` parameter:
```python
    def __init__(self, memory_store: MemoryStore, session_id: Optional[str] = None, session_brain=None):
        self.memory_store = memory_store
        self.session_id = session_id or str(uuid.uuid4())
        self._buffer: list[Interaction] = []
        self._created_at = datetime.now().isoformat()
        self._session_brain = session_brain
```

In `flush()` method (after line 170, before the return), add:
```python
        # Update session brain if available
        if self._session_brain is not None:
            for content in extracted["decisions"]:
                self._session_brain.add_decision(content[:200])
            for content in extracted["action_items"]:
                self._session_brain.add_action_item(content[:200], source="session_flush")
            self._session_brain.save()
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_session_manager.py::TestFlushUpdatesSessionBrain -v`
Expected: PASS

Also run existing tests to ensure no regressions:
Run: `pytest tests/test_session_manager.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add session/manager.py tests/test_session_manager.py
git commit -m "feat: wire session flush to Session Brain for cross-session persistence"
```

Update `mcp_server.py` lifespan to pass brain to session manager (line 122):
```python
    _state.session_manager = SessionManager(memory_store, session_brain=_state.session_brain)
```

```bash
git add mcp_server.py
git commit -m "fix: pass session brain to session manager in lifespan"
```

---

## Task 7: Proactive Engine -- Session Brain Checks

**Files:**
- Modify: `proactive/engine.py:17-35`
- Test: `tests/test_proactive_engine.py` (extend)

**Step 1: Write the failing test**

Add to `tests/test_proactive_engine.py`:

```python
from session.brain import SessionBrain

class TestSessionBrainChecks:
    def test_stale_workstream_suggestion(self, memory_store, tmp_path):
        brain = SessionBrain(tmp_path / "brain.md")
        brain.add_workstream("Stale project", "wait/hold", "Waiting on response")
        # Fake the date to 6 days ago by manipulating the workstream
        engine = ProactiveSuggestionEngine(memory_store, session_brain=brain)
        # The check should find workstreams -- even fresh ones are surfaced as nudges
        suggestions = engine._check_session_brain_items()
        # Should return nudges for open action items and workstreams
        assert isinstance(suggestions, list)

    def test_open_action_items_suggestion(self, memory_store, tmp_path):
        brain = SessionBrain(tmp_path / "brain.md")
        brain.add_action_item("File IC3 report", source="email")
        brain.add_action_item("Review PR", source="session")
        engine = ProactiveSuggestionEngine(memory_store, session_brain=brain)
        suggestions = engine._check_session_brain_items()
        # Should find 2 open action items
        found = [s for s in suggestions if "action item" in s.title.lower()]
        assert len(found) >= 1

    def test_no_brain_returns_empty(self, memory_store):
        engine = ProactiveSuggestionEngine(memory_store, session_brain=None)
        suggestions = engine._check_session_brain_items()
        assert suggestions == []
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_proactive_engine.py::TestSessionBrainChecks -v`
Expected: FAIL with `TypeError: ProactiveSuggestionEngine.__init__() got an unexpected keyword argument 'session_brain'`

**Step 3: Write minimal implementation**

Modify `proactive/engine.py`:

Constructor (line 18-21):
```python
    def __init__(self, memory_store: MemoryStore, session_health=None, session_manager=None, session_brain=None):
        self.memory_store = memory_store
        self.session_health = session_health
        self.session_manager = session_manager
        self.session_brain = session_brain
```

Add to `generate_suggestions()` (after line 32, before the sort):
```python
        suggestions.extend(self._check_session_brain_items())
```

Add new method (after `_check_session_unflushed_items`):
```python
    def _check_session_brain_items(self) -> list[Suggestion]:
        """Surface open action items and active workstreams from Session Brain."""
        if self.session_brain is None:
            return []
        results = []
        open_items = [a for a in self.session_brain.action_items if not a.get("done")]
        if open_items:
            item_list = ", ".join(a["text"][:50] for a in open_items[:5])
            results.append(Suggestion(
                category="session",
                priority="medium",
                title=f"{len(open_items)} open action item(s) from previous sessions",
                description=f"Items: {item_list}",
                action="get_session_brain",
            ))
        active_ws = [w for w in self.session_brain.workstreams if w.get("status") not in ("completed", "cancelled")]
        if active_ws:
            ws_list = ", ".join(w["name"] for w in active_ws[:5])
            results.append(Suggestion(
                category="session",
                priority="low",
                title=f"{len(active_ws)} active workstream(s)",
                description=f"Workstreams: {ws_list}",
                action="get_session_brain",
            ))
        return results
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_proactive_engine.py -v`
Expected: All PASS (new and existing)

**Step 5: Commit**

```bash
git add proactive/engine.py tests/test_proactive_engine.py
git commit -m "feat: add Session Brain checks to proactive suggestion engine"
```

---

## Task 8: Proactive Engine -- Push via Delivery Channels

**Files:**
- Modify: `proactive/engine.py:188-215`
- Test: `tests/test_proactive_push_and_auto_exec.py` (extend)

**Step 1: Write the failing test**

Add to `tests/test_proactive_push_and_auto_exec.py`:

```python
class TestPushViaDeliveryChannels:
    @patch("scheduler.delivery.deliver_result")
    def test_push_via_email(self, mock_deliver, memory_store):
        mock_deliver.return_value = {"status": "delivered"}
        engine = ProactiveSuggestionEngine(memory_store)
        suggestions = [Suggestion(
            category="delegation",
            priority="high",
            title="Overdue task",
            description="Task X is 3 days overdue",
            action="check_overdue_delegations",
        )]
        results = engine.push_via_channel(
            suggestions, channel="email",
            config={"to": ["jason@test.com"]},
        )
        assert len(results) == 1
        mock_deliver.assert_called_once()

    @patch("scheduler.delivery.deliver_result")
    def test_push_filters_by_threshold(self, mock_deliver, memory_store):
        mock_deliver.return_value = {"status": "delivered"}
        engine = ProactiveSuggestionEngine(memory_store)
        suggestions = [
            Suggestion(category="delegation", priority="high",
                       title="High", description="", action=""),
            Suggestion(category="skill", priority="low",
                       title="Low", description="", action=""),
        ]
        results = engine.push_via_channel(
            suggestions, channel="email",
            config={"to": ["jason@test.com"]},
            push_threshold="high",
        )
        assert len(results) == 1  # only high priority pushed
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_proactive_push_and_auto_exec.py::TestPushViaDeliveryChannels -v`
Expected: FAIL with `AttributeError: 'ProactiveSuggestionEngine' object has no attribute 'push_via_channel'`

**Step 3: Write minimal implementation**

Add to `proactive/engine.py` (after `push_suggestions` method):

```python
    def push_via_channel(
        self,
        suggestions: list[Suggestion],
        channel: str,
        config: dict,
        push_threshold: str = "high",
    ) -> list[dict]:
        """Push suggestions via a delivery channel (email, imessage, teams, notification).

        Args:
            suggestions: List of Suggestion objects to potentially push.
            channel: Delivery channel name.
            config: Channel-specific config (e.g. {"to": ["email@example.com"]}).
            push_threshold: Minimum priority to push.

        Returns:
            List of delivery result dicts for pushed suggestions.
        """
        from scheduler.delivery import deliver_result

        threshold_val = PRIORITY_ORDER.get(push_threshold, 0)
        results = []
        for s in suggestions:
            if PRIORITY_ORDER.get(s.priority, 3) <= threshold_val:
                text = f"[{s.category.upper()}] {s.title}\n{s.description}"
                result = deliver_result(channel, config, text, task_name=f"proactive_{s.category}")
                results.append(result)
                logger.debug("Pushed %s via %s: %s", s.title, channel, result)
        return results
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_proactive_push_and_auto_exec.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add proactive/engine.py tests/test_proactive_push_and_auto_exec.py
git commit -m "feat: add push_via_channel to proactive engine for multi-channel delivery"
```

---

## Task 9: Proactive Engine -- Session Start Nudges

**Files:**
- Modify: `proactive/engine.py`
- Modify: `mcp_tools/proactive_tools.py`
- Test: `tests/test_proactive_tools.py` (extend)

**Step 1: Write the failing test**

Add to `tests/test_proactive_tools.py`:

```python
class TestGetSessionNudges:
    @pytest.mark.asyncio
    async def test_returns_nudges_from_brain(self, monkeypatch, memory_store, tmp_path):
        from session.brain import SessionBrain
        brain = SessionBrain(tmp_path / "brain.md")
        brain.add_action_item("Fix bug", source="email")
        brain.add_workstream("Project X", "active", "Phase 1")

        import mcp_tools.proactive_tools as mod
        mock_state = MagicMock()
        mock_state.memory_store = memory_store
        mock_state.session_health = None
        mock_state.session_manager = None
        mock_state.session_brain = brain

        # Need to test the tool function has access to session_brain
        from proactive.engine import ProactiveSuggestionEngine
        engine = ProactiveSuggestionEngine(memory_store, session_brain=brain)
        nudges = engine._check_session_brain_items()
        assert len(nudges) >= 1
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_proactive_tools.py::TestGetSessionNudges -v`
Expected: PASS (this uses the method added in Task 7)

**Step 3: Update proactive_tools.py to pass session_brain**

Modify `mcp_tools/proactive_tools.py` line 24 to include session_brain:
```python
            engine = ProactiveSuggestionEngine(
                memory_store,
                session_health=state.session_health,
                session_manager=state.session_manager,
                session_brain=getattr(state, "session_brain", None),
            )
```

**Step 4: Run all proactive tests**

Run: `pytest tests/test_proactive_tools.py tests/test_proactive_engine.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add mcp_tools/proactive_tools.py tests/test_proactive_tools.py
git commit -m "feat: pass session brain to proactive engine from MCP tools"
```

---

## Task 10: Team Playbooks -- YAML Schema and Loader

**Files:**
- Create: `playbooks/__init__.py`
- Create: `playbooks/loader.py`
- Test: `tests/test_playbook_loader.py`

**Step 1: Write the failing test**

```python
# tests/test_playbook_loader.py
"""Tests for playbook YAML loading and validation."""

import pytest
from pathlib import Path
from playbooks.loader import Playbook, PlaybookLoader, Workstream


@pytest.fixture
def playbook_dir(tmp_path):
    return tmp_path / "playbooks"


@pytest.fixture
def sample_yaml(playbook_dir):
    playbook_dir.mkdir()
    content = """\
name: meeting_prep
description: Prepare briefing materials for an upcoming meeting
inputs:
  - meeting_subject
  - attendees
workstreams:
  - name: email_context
    prompt: "Search email for threads involving $attendees"
  - name: document_context
    prompt: "Search Confluence for $meeting_subject"
    condition: "depth == thorough"
synthesis:
  prompt: "Combine workstream results into a briefing"
delivery:
  default: inline
  options:
    - email
    - teams
"""
    path = playbook_dir / "meeting_prep.yaml"
    path.write_text(content)
    return path


class TestPlaybookModel:
    def test_playbook_has_required_fields(self):
        p = Playbook(
            name="test",
            description="A test playbook",
            inputs=["topic"],
            workstreams=[Workstream(name="ws1", prompt="Do something with $topic")],
        )
        assert p.name == "test"
        assert len(p.workstreams) == 1

    def test_workstream_with_condition(self):
        ws = Workstream(name="ws1", prompt="Search", condition="depth == thorough")
        assert ws.condition == "depth == thorough"


class TestPlaybookLoader:
    def test_load_from_directory(self, sample_yaml, playbook_dir):
        loader = PlaybookLoader(playbook_dir)
        playbooks = loader.list_playbooks()
        assert len(playbooks) == 1
        assert playbooks[0] == "meeting_prep"

    def test_get_playbook(self, sample_yaml, playbook_dir):
        loader = PlaybookLoader(playbook_dir)
        pb = loader.get_playbook("meeting_prep")
        assert pb.name == "meeting_prep"
        assert len(pb.workstreams) == 2
        assert pb.workstreams[0].name == "email_context"
        assert pb.synthesis_prompt == "Combine workstream results into a briefing"
        assert pb.delivery_default == "inline"

    def test_get_nonexistent_returns_none(self, playbook_dir):
        playbook_dir.mkdir(exist_ok=True)
        loader = PlaybookLoader(playbook_dir)
        assert loader.get_playbook("nonexistent") is None

    def test_load_validates_required_fields(self, playbook_dir):
        playbook_dir.mkdir(exist_ok=True)
        bad = playbook_dir / "bad.yaml"
        bad.write_text("name: bad\n")
        loader = PlaybookLoader(playbook_dir)
        pb = loader.get_playbook("bad")
        assert pb is None  # missing required fields

    def test_substitute_inputs(self, sample_yaml, playbook_dir):
        loader = PlaybookLoader(playbook_dir)
        pb = loader.get_playbook("meeting_prep")
        resolved = pb.resolve_inputs({
            "meeting_subject": "Q1 Review",
            "attendees": "Alice, Bob",
        })
        assert "Alice, Bob" in resolved.workstreams[0].prompt
        assert "Q1 Review" in resolved.workstreams[1].prompt

    def test_workstream_condition_filtering(self, sample_yaml, playbook_dir):
        loader = PlaybookLoader(playbook_dir)
        pb = loader.get_playbook("meeting_prep")
        # Without the condition met, filtering should exclude conditional workstreams
        active = pb.active_workstreams(context={})
        assert len(active) == 1  # only email_context (no condition)

        active = pb.active_workstreams(context={"depth": "thorough"})
        assert len(active) == 2  # both
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_playbook_loader.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'playbooks'`

**Step 3: Write minimal implementation**

```python
# playbooks/__init__.py
```

```python
# playbooks/loader.py
"""Playbook loader: reads YAML playbook definitions for parallel workstream dispatch."""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
from pathlib import Path
from string import Template
from typing import Optional

import yaml

logger = logging.getLogger(__name__)


@dataclass
class Workstream:
    name: str
    prompt: str
    condition: str = ""


@dataclass
class Playbook:
    name: str
    description: str
    inputs: list[str] = field(default_factory=list)
    workstreams: list[Workstream] = field(default_factory=list)
    synthesis_prompt: str = ""
    delivery_default: str = "inline"
    delivery_options: list[str] = field(default_factory=list)

    def resolve_inputs(self, values: dict[str, str]) -> Playbook:
        """Return a new Playbook with $variables substituted in prompts."""
        resolved = copy.deepcopy(self)
        for ws in resolved.workstreams:
            ws.prompt = Template(ws.prompt).safe_substitute(values)
        if resolved.synthesis_prompt:
            resolved.synthesis_prompt = Template(resolved.synthesis_prompt).safe_substitute(values)
        return resolved

    def active_workstreams(self, context: dict | None = None) -> list[Workstream]:
        """Return workstreams whose conditions are met by the given context."""
        context = context or {}
        result = []
        for ws in self.workstreams:
            if not ws.condition:
                result.append(ws)
            elif _evaluate_condition(ws.condition, context):
                result.append(ws)
        return result


def _evaluate_condition(condition: str, context: dict) -> bool:
    """Evaluate a simple 'key == value' condition against context."""
    if "==" in condition:
        parts = condition.split("==", 1)
        key = parts[0].strip()
        value = parts[1].strip()
        return str(context.get(key, "")).strip() == value
    return False


class PlaybookLoader:
    """Loads playbook YAML files from a directory."""

    def __init__(self, playbooks_dir: Path | str):
        self.playbooks_dir = Path(playbooks_dir)

    def list_playbooks(self) -> list[str]:
        """Return names of all available playbooks."""
        if not self.playbooks_dir.exists():
            return []
        names = []
        for path in sorted(self.playbooks_dir.glob("*.yaml")):
            names.append(path.stem)
        for path in sorted(self.playbooks_dir.glob("*.yml")):
            if path.stem not in names:
                names.append(path.stem)
        return names

    def get_playbook(self, name: str) -> Optional[Playbook]:
        """Load a playbook by name. Returns None if not found or invalid."""
        for ext in (".yaml", ".yml"):
            path = self.playbooks_dir / f"{name}{ext}"
            if path.exists():
                return self._load_file(path)
        return None

    def _load_file(self, path: Path) -> Optional[Playbook]:
        """Parse a YAML file into a Playbook."""
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            logger.warning("Failed to parse playbook %s: %s", path, e)
            return None

        if not isinstance(data, dict):
            return None

        name = data.get("name")
        description = data.get("description", "")
        workstreams_raw = data.get("workstreams", [])

        if not name or not workstreams_raw:
            logger.warning("Playbook %s missing required fields (name, workstreams)", path)
            return None

        workstreams = []
        for ws_data in workstreams_raw:
            if isinstance(ws_data, dict) and "name" in ws_data and "prompt" in ws_data:
                workstreams.append(Workstream(
                    name=ws_data["name"],
                    prompt=ws_data["prompt"],
                    condition=ws_data.get("condition", ""),
                ))

        synthesis = data.get("synthesis", {})
        delivery = data.get("delivery", {})

        return Playbook(
            name=name,
            description=description,
            inputs=data.get("inputs", []),
            workstreams=workstreams,
            synthesis_prompt=synthesis.get("prompt", "") if isinstance(synthesis, dict) else "",
            delivery_default=delivery.get("default", "inline") if isinstance(delivery, dict) else "inline",
            delivery_options=delivery.get("options", []) if isinstance(delivery, dict) else [],
        )
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_playbook_loader.py -v`
Expected: PASS (all 8 tests)

**Step 5: Commit**

```bash
git add playbooks/__init__.py playbooks/loader.py tests/test_playbook_loader.py
git commit -m "feat: add playbook YAML loader with input substitution and condition filtering"
```

---

## Task 11: Team Playbooks -- Example YAML Files

**Files:**
- Create: `playbooks/meeting_prep.yaml`
- Create: `playbooks/expert_research.yaml`
- Create: `playbooks/software_dev_team.yaml`
- Create: `playbooks/daily_briefing.yaml`
- Test: `tests/test_playbook_loader.py` (extend with validation test)

**Step 1: Write the failing test**

Add to `tests/test_playbook_loader.py`:

```python
import config as app_config

class TestBuiltInPlaybooks:
    """Validate all YAML playbooks in the playbooks/ directory."""

    def test_all_playbooks_load_successfully(self):
        playbooks_dir = app_config.BASE_DIR / "playbooks"
        if not playbooks_dir.exists():
            pytest.skip("No playbooks directory")
        loader = PlaybookLoader(playbooks_dir)
        names = loader.list_playbooks()
        assert len(names) >= 4, f"Expected at least 4 playbooks, got {names}"
        for name in names:
            pb = loader.get_playbook(name)
            assert pb is not None, f"Playbook {name} failed to load"
            assert pb.name == name
            assert len(pb.workstreams) >= 1
            assert pb.description

    def test_meeting_prep_has_expected_workstreams(self):
        playbooks_dir = app_config.BASE_DIR / "playbooks"
        loader = PlaybookLoader(playbooks_dir)
        pb = loader.get_playbook("meeting_prep")
        assert pb is not None
        ws_names = [w.name for w in pb.workstreams]
        assert "email_context" in ws_names
        assert "calendar_context" in ws_names

    def test_daily_briefing_has_expected_workstreams(self):
        playbooks_dir = app_config.BASE_DIR / "playbooks"
        loader = PlaybookLoader(playbooks_dir)
        pb = loader.get_playbook("daily_briefing")
        assert pb is not None
        assert len(pb.workstreams) >= 4
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_playbook_loader.py::TestBuiltInPlaybooks -v`
Expected: FAIL (playbooks directory doesn't exist or has fewer than 4 files)

**Step 3: Create the playbook YAML files**

Create the `playbooks/` directory (at project root), then create each file:

```yaml
# playbooks/meeting_prep.yaml
name: meeting_prep
description: Prepare briefing materials for an upcoming meeting
inputs:
  - meeting_subject
  - meeting_time
  - attendees
workstreams:
  - name: email_context
    prompt: |
      Search M365 email for all threads involving $attendees
      related to $meeting_subject in the last 30 days.
      Extract key discussion points, decisions, and open questions.
  - name: document_context
    prompt: |
      Search Confluence for pages related to $meeting_subject.
      Also search Jarvis documents for relevant ingested files.
      Summarize key findings and link to source pages.
  - name: decision_history
    prompt: |
      Query Jarvis memory for decisions and delegations involving $attendees
      or related to $meeting_subject. Note any overdue items.
  - name: calendar_context
    prompt: |
      Find previous meetings with $attendees in the last 30 days
      and upcoming meetings in the next 7 days.
      Note patterns, frequency, and related topics.
synthesis:
  prompt: |
    Combine all workstream results into a meeting briefing:
    1. Meeting context (subject, time, attendees)
    2. Recent email threads and key points
    3. Relevant documents and findings
    4. Decision/delegation history with attendees
    5. Previous meeting patterns
    6. Suggested talking points and open questions
delivery:
  default: inline
  options:
    - email
    - teams
    - confluence
```

```yaml
# playbooks/expert_research.yaml
name: expert_research
description: Deep parallel research on a topic across all available sources
inputs:
  - topic
  - context
  - depth
workstreams:
  - name: memory_analyst
    prompt: |
      Query Jarvis memory for everything related to $topic.
      Include facts, decisions, delegations, and past conversations.
      Identify what we already know vs gaps.
  - name: document_researcher
    prompt: |
      Search ingested documents and Confluence for $topic.
      Extract key findings, dates, stakeholders, and open questions.
  - name: email_intel
    prompt: |
      Search M365 email and Teams messages for $topic.
      Find recent threads, action items, commitments made.
  - name: calendar_context
    prompt: |
      Find meetings related to $topic in the last 30 days and next 14 days.
      Note attendees, patterns, and upcoming deadlines.
  - name: identity_mapper
    prompt: |
      Identify all people connected to $topic across all channels.
      Use identity linking to build a complete stakeholder map.
  - name: web_researcher
    condition: "depth == thorough"
    prompt: |
      Search the web for external context on $topic.
      Industry trends, competitor moves, regulatory changes.
synthesis:
  prompt: |
    You are a senior analyst. Combine all workstream results into:
    1. Executive summary (3 bullets)
    2. What we know (with sources)
    3. What we don't know (gaps)
    4. Stakeholder map
    5. Recommended next steps
    Context for this research: $context
delivery:
  default: inline
  options:
    - email
    - teams
    - confluence
```

```yaml
# playbooks/software_dev_team.yaml
name: software_dev_team
description: Parallel code analysis, review, and planning for a development task
inputs:
  - task
  - scope
workstreams:
  - name: architect
    prompt: |
      Analyze the architecture relevant to: $task
      Scope: $scope
      Map module dependencies, identify integration points,
      flag coupling risks. Review CLAUDE.md and architecture docs.
  - name: code_reviewer
    prompt: |
      Review current code in $scope for:
      - Patterns and conventions used
      - Test coverage gaps
      - Security concerns (OWASP top 10)
      - Performance bottlenecks
      Related to: $task
  - name: test_analyst
    prompt: |
      Examine existing tests for $scope.
      Identify: what's tested, what's not, edge cases missing,
      test patterns used. Run pytest on relevant test files.
  - name: dependency_scanner
    prompt: |
      Check how $scope connects to the rest of the system.
      Find all callers, importers, and downstream consumers.
      Flag breaking change risks for: $task
  - name: docs_checker
    prompt: |
      Check if documentation matches current code for $scope.
      Find stale docstrings, missing tool references,
      outdated architecture diagrams.
synthesis:
  prompt: |
    You are a tech lead. Combine all findings into:
    1. Architecture assessment
    2. Risk areas
    3. Implementation plan (ordered steps)
    4. Test plan
    5. Documentation updates needed
    Task: $task
delivery:
  default: inline
  options:
    - confluence
```

```yaml
# playbooks/daily_briefing.yaml
name: daily_briefing
description: Comprehensive daily briefing from all sources
inputs:
  - briefing_date
  - email_recipient
workstreams:
  - name: calendar_review
    prompt: |
      Get all calendar events for $briefing_date from both
      M365 (Outlook) and Apple Calendar. List each event with
      time, title, attendees, and location.
  - name: email_digest
    prompt: |
      Search M365 email for messages from the last 24 hours.
      Identify action items, questions needing response, and
      important updates. Group by urgency.
  - name: teams_digest
    prompt: |
      Search Teams messages from the last 24 hours for DMs,
      mentions, and important thread updates.
  - name: imessage_digest
    prompt: |
      Check recent iMessages for any work-related or
      important personal messages from the last 24 hours.
  - name: memory_review
    prompt: |
      Check Jarvis memory for: overdue delegations, upcoming
      deadlines (next 3 days), pending decisions, and open
      action items from the Session Brain.
  - name: reminders_check
    prompt: |
      List all incomplete reminders, especially those due
      today or overdue.
synthesis:
  prompt: |
    Create a daily briefing for $briefing_date:
    1. Today's Schedule (chronological)
    2. Action Items Requiring Attention (urgent first)
    3. Email Summary (grouped by priority)
    4. Teams/Messages Highlights
    5. Open Delegations & Deadlines
    6. Reminders Due Today
    Keep it concise. Flag anything that needs immediate action.
delivery:
  default: email
  options:
    - email
    - inline
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_playbook_loader.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add playbooks/ tests/test_playbook_loader.py
git commit -m "feat: add 4 built-in playbooks: meeting_prep, expert_research, software_dev_team, daily_briefing"
```

---

## Task 12: Team Playbooks -- MCP Tools

**Files:**
- Create: `mcp_tools/playbook_tools.py`
- Modify: `mcp_server.py` (add import and register)
- Modify: `config.py` (add `PLAYBOOKS_DIR`)
- Test: `tests/test_playbook_tools.py`

**Step 1: Write the failing test**

```python
# tests/test_playbook_tools.py
"""Tests for playbook MCP tools."""

import json
import pytest
from pathlib import Path

import mcp_server  # trigger registration
from mcp_tools.playbook_tools import list_playbooks, get_playbook


@pytest.fixture
def playbook_dir(tmp_path):
    d = tmp_path / "playbooks"
    d.mkdir()
    (d / "test_playbook.yaml").write_text("""\
name: test_playbook
description: A test playbook
inputs:
  - topic
workstreams:
  - name: researcher
    prompt: "Research $topic"
synthesis:
  prompt: "Summarize findings about $topic"
delivery:
  default: inline
""")
    return d


class TestListPlaybooks:
    @pytest.mark.asyncio
    async def test_lists_available_playbooks(self, playbook_dir, monkeypatch):
        import mcp_tools.playbook_tools as mod
        monkeypatch.setattr(mod, "_get_loader_dir", lambda: playbook_dir)
        result = json.loads(await list_playbooks())
        assert "test_playbook" in result["playbooks"]
        assert result["count"] >= 1


class TestGetPlaybook:
    @pytest.mark.asyncio
    async def test_get_existing_playbook(self, playbook_dir, monkeypatch):
        import mcp_tools.playbook_tools as mod
        monkeypatch.setattr(mod, "_get_loader_dir", lambda: playbook_dir)
        result = json.loads(await get_playbook("test_playbook"))
        assert result["name"] == "test_playbook"
        assert len(result["workstreams"]) == 1
        assert result["inputs"] == ["topic"]

    @pytest.mark.asyncio
    async def test_get_nonexistent_playbook(self, playbook_dir, monkeypatch):
        import mcp_tools.playbook_tools as mod
        monkeypatch.setattr(mod, "_get_loader_dir", lambda: playbook_dir)
        result = json.loads(await get_playbook("nonexistent"))
        assert "error" in result
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_playbook_tools.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mcp_tools.playbook_tools'`

**Step 3: Write minimal implementation**

Add to `config.py` (after line 5):
```python
PLAYBOOKS_DIR = BASE_DIR / "playbooks"
```

```python
# mcp_tools/playbook_tools.py
"""Playbook tools for the Chief of Staff MCP server."""

import json
import logging
import sys
from pathlib import Path

import config as app_config

logger = logging.getLogger("jarvis-mcp")


def _get_loader_dir() -> Path:
    """Get the playbooks directory (allows monkeypatching in tests)."""
    return app_config.PLAYBOOKS_DIR


def register(mcp, state):
    """Register playbook tools with the FastMCP server."""

    @mcp.tool()
    async def list_playbooks() -> str:
        """List all available team playbooks.

        Playbooks define parallel workstreams that fan out across multiple
        data sources and agents, then synthesize results. Use get_playbook
        to see details of a specific playbook before running it.
        """
        from playbooks.loader import PlaybookLoader

        loader = PlaybookLoader(_get_loader_dir())
        names = loader.list_playbooks()
        descriptions = {}
        for name in names:
            pb = loader.get_playbook(name)
            if pb:
                descriptions[name] = pb.description
        return json.dumps({
            "playbooks": names,
            "descriptions": descriptions,
            "count": len(names),
        })

    @mcp.tool()
    async def get_playbook(name: str) -> str:
        """Get details of a specific playbook including its workstreams and inputs.

        Args:
            name: The playbook name (e.g. "meeting_prep", "expert_research")
        """
        from playbooks.loader import PlaybookLoader

        loader = PlaybookLoader(_get_loader_dir())
        pb = loader.get_playbook(name)
        if pb is None:
            return json.dumps({"error": f"Playbook '{name}' not found"})
        return json.dumps({
            "name": pb.name,
            "description": pb.description,
            "inputs": pb.inputs,
            "workstreams": [
                {"name": ws.name, "prompt": ws.prompt, "condition": ws.condition}
                for ws in pb.workstreams
            ],
            "synthesis_prompt": pb.synthesis_prompt,
            "delivery_default": pb.delivery_default,
            "delivery_options": pb.delivery_options,
        })

    # Expose for testing
    module = sys.modules[__name__]
    module.list_playbooks = list_playbooks
    module.get_playbook = get_playbook
```

Add to `mcp_server.py` imports and registration:
```python
    playbook_tools,
```
```python
playbook_tools.register(mcp, _state)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_playbook_tools.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add config.py mcp_tools/playbook_tools.py mcp_server.py tests/test_playbook_tools.py
git commit -m "feat: add list_playbooks and get_playbook MCP tools"
```

---

## Task 13: Config and Documentation Updates

**Files:**
- Modify: `config.py` (verify all new env vars are present)
- Modify: `CLAUDE.md` (add new modules to tables)
- Modify: `docs/tools-reference.md` (add new tools)
- Modify: `docs/architecture.md` (add new components)

**Step 1: Verify config.py has all needed additions**

Ensure these lines exist in `config.py`:
```python
SESSION_BRAIN_PATH = DATA_DIR / "session_brain.md"
PLAYBOOKS_DIR = BASE_DIR / "playbooks"
```

These were added in previous tasks. Verify and add any missing.

**Step 2: Update CLAUDE.md**

Add new modules to the MCP Server Structure table:
```
| `mcp_tools/routing_tools.py` | Channel routing: safety tiers and delivery channel selection |
| `mcp_tools/brain_tools.py` | Session Brain: persistent cross-session context |
| `mcp_tools/playbook_tools.py` | Team playbooks: list and inspect parallel workstream definitions |
```

Add to Module Map:
```
| `channels/routing.py` | Safety tier determination and channel selection for outbound messages |
| `session/brain.py` | Session Brain: markdown-based persistent context document |
| `playbooks/loader.py` | YAML playbook loader with input substitution and condition evaluation |
```

**Step 3: Update docs/tools-reference.md**

Add sections for new tools:
- Channel Routing Tools: `route_message`
- Session Brain Tools: `get_session_brain`, `update_session_brain`
- Playbook Tools: `list_playbooks`, `get_playbook`

Update tool count to 105 (99 + 6 new).

**Step 4: Update docs/architecture.md**

Add new sections:
- Session Brain: lifecycle, persistence, integration with SessionManager
- Channel Routing: safety tiers, channel selection, time-of-day awareness
- Team Playbooks: YAML schema, loader, execution model

**Step 5: Commit**

```bash
git add config.py CLAUDE.md docs/tools-reference.md docs/architecture.md
git commit -m "docs: update documentation for channel routing, session brain, and playbooks"
```

---

## Task 14: Full Integration Test

**Files:**
- Test: run full test suite

**Step 1: Run the full test suite**

Run: `pytest`
Expected: All tests pass (existing + new)

**Step 2: Check for import issues**

Run: `python -c "import mcp_server"`
Expected: No errors

**Step 3: Verify MCP server starts**

Run: `timeout 5 jarvis-mcp 2>&1 || true`
Expected: "Jarvis MCP server initialized" in output (server starts, then times out on stdin)

**Step 4: Fix any failures, then commit**

```bash
git add -A
git commit -m "fix: resolve integration issues from enhancement implementation"
```

---

## Summary

| Task | Component | New Files | Tests |
|------|-----------|-----------|-------|
| 1 | Channel Router: safety tiers | `channels/routing.py` | `tests/test_channel_routing.py` |
| 2 | Teams delivery adapter | (modify `scheduler/delivery.py`) | extend `tests/test_delivery.py` |
| 3 | Channel routing MCP tool | `mcp_tools/routing_tools.py` | `tests/test_routing_tools.py` |
| 4 | Session Brain: core model | `session/brain.py` | `tests/test_session_brain.py` |
| 5 | Session Brain: MCP tools | `mcp_tools/brain_tools.py` | `tests/test_brain_tools.py` |
| 6 | Session Manager: wire flush | (modify `session/manager.py`) | extend `tests/test_session_manager.py` |
| 7 | Proactive: brain checks | (modify `proactive/engine.py`) | extend `tests/test_proactive_engine.py` |
| 8 | Proactive: push via channels | (modify `proactive/engine.py`) | extend `tests/test_proactive_push_and_auto_exec.py` |
| 9 | Proactive: session nudges | (modify `mcp_tools/proactive_tools.py`) | extend `tests/test_proactive_tools.py` |
| 10 | Playbooks: YAML loader | `playbooks/loader.py` | `tests/test_playbook_loader.py` |
| 11 | Playbooks: example YAMLs | 4 YAML files | extend `tests/test_playbook_loader.py` |
| 12 | Playbooks: MCP tools | `mcp_tools/playbook_tools.py` | `tests/test_playbook_tools.py` |
| 13 | Config + docs | (modify existing) | — |
| 14 | Integration test | — | full `pytest` |

**Total: ~105 tools (99 existing + 6 new), 14 tasks, TDD throughout.**
