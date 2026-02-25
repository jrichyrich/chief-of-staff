# Formatter Integration Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Wire the formatter module into delivery adapters, MCP tool responses, and daily brief composition so all Jarvis output surfaces use rich formatting.

**Architecture:** Four independent workstreams that can execute in parallel. Each adds formatter calls to an existing subsystem: (1) delivery adapters render briefs in plain mode, (2) brief data helpers transform raw API data into brief-compatible structures, (3) key MCP tools gain an optional `formatted` response alongside JSON, (4) the daily brief gains OKR/delegation/decision sub-components.

**Tech Stack:** Python 3.11, rich>=13.0, formatter module (tables, cards, brief, dashboard, text), pytest with @pytest.mark.asyncio

---

## Dependency Map

```
Task 1 (delivery) ─── independent
Task 2 (brief helpers) ─── independent
Task 3 (MCP formatted responses) ─── depends on Task 2 for delegation/decision helpers
Task 4 (brief enhancements) ─── depends on Task 2 for data helpers
```

**Parallel groups:**
- **Wave 1:** Tasks 1 + 2 (fully independent)
- **Wave 2:** Tasks 3 + 4 (both depend on Task 2, but independent of each other)

---

### Task 1: Integrate formatter with delivery adapters

**Files:**
- Modify: `scheduler/delivery.py:151-175`
- Test: `tests/test_delivery.py`

**Context:** `deliver_result()` receives `result_text` (a string) and passes it to adapters. When the result_text is JSON containing brief-like keys (`date`, `calendar`, `action_items`), we should render it through `formatter.brief.render_daily(mode="plain")` before delivery. This gives email/iMessage/notification recipients a nicely structured brief instead of raw JSON.

**Step 1: Write the failing test**

Add to `tests/test_delivery.py`:

```python
class TestFormattedDelivery:
    """Tests for formatter-aware delivery."""

    def test_deliver_result_formats_brief_json(self):
        """When result_text is JSON with brief keys, render via formatter."""
        import json
        brief_data = json.dumps({
            "date": "2026-02-25",
            "calendar": [{"time": "9 AM", "event": "Standup", "status": "Teams"}],
            "action_items": [{"priority": "high", "text": "Review PR"}],
        })
        with patch("scheduler.delivery.get_delivery_adapter") as mock_get:
            mock_adapter = MagicMock()
            mock_adapter.deliver.return_value = {"status": "delivered"}
            mock_get.return_value = mock_adapter

            deliver_result("email", {}, brief_data, "daily_brief")

            delivered_text = mock_adapter.deliver.call_args[0][0]
            # Should be formatted, not raw JSON
            assert "DAILY BRIEFING" in delivered_text or "CALENDAR" in delivered_text
            assert "Standup" in delivered_text
            # Should NOT be raw JSON
            assert '"calendar"' not in delivered_text

    def test_deliver_result_passes_plain_text_through(self):
        """Non-JSON result_text passes through unchanged (after humanize)."""
        with patch("scheduler.delivery.get_delivery_adapter") as mock_get:
            mock_adapter = MagicMock()
            mock_adapter.deliver.return_value = {"status": "delivered"}
            mock_get.return_value = mock_adapter

            deliver_result("email", {}, "Simple text result", "task_name")

            delivered_text = mock_adapter.deliver.call_args[0][0]
            assert "Simple text result" in delivered_text

    def test_deliver_result_handles_non_brief_json(self):
        """JSON without brief keys passes through as-is."""
        import json
        data = json.dumps({"status": "ok", "count": 5})
        with patch("scheduler.delivery.get_delivery_adapter") as mock_get:
            mock_adapter = MagicMock()
            mock_adapter.deliver.return_value = {"status": "delivered"}
            mock_get.return_value = mock_adapter

            deliver_result("email", {}, data, "other_task")

            delivered_text = mock_adapter.deliver.call_args[0][0]
            # Should still be the original text (humanized), not formatted as brief
            assert "DAILY BRIEFING" not in delivered_text
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_delivery.py::TestFormattedDelivery -v`
Expected: FAIL — `TestFormattedDelivery` class not found or assertion errors

**Step 3: Implement `_maybe_format_brief()` in `scheduler/delivery.py`**

Add this function before `deliver_result()`:

```python
def _maybe_format_brief(result_text: str) -> str:
    """If result_text is JSON with daily-brief keys, render via formatter.

    Returns the original text unchanged if it's not brief-like JSON.
    """
    import json as _json
    try:
        data = _json.loads(result_text)
    except (ValueError, TypeError):
        return result_text

    # Check for brief-like keys
    brief_keys = {"date", "calendar", "action_items", "conflicts", "email_highlights", "personal"}
    if not isinstance(data, dict) or not (brief_keys & set(data.keys())):
        return result_text

    try:
        from formatter.brief import render_daily
        rendered = render_daily(**data, mode="plain")
        return rendered if rendered else result_text
    except Exception:
        logger.debug("Failed to format brief, using raw text", exc_info=True)
        return result_text
```

Then modify `deliver_result()` to call it:

```python
def deliver_result(channel, config, result_text, task_name=""):
    adapter = get_delivery_adapter(channel)
    if adapter is None:
        logger.warning("Unknown delivery channel '%s' for task '%s'", channel, task_name)
        return {"status": "error", "error": f"Unknown delivery channel: {channel}"}

    try:
        result_text = _maybe_format_brief(result_text)
        result_text = humanize(result_text)
        return adapter.deliver(result_text, config or {}, task_name)
    except Exception as e:
        logger.error("Delivery failed for task '%s' via '%s': %s", task_name, channel, e)
        return {"status": "error", "error": str(e)}
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_delivery.py -v`
Expected: All tests pass including new ones

**Step 5: Commit**

```bash
git add scheduler/delivery.py tests/test_delivery.py
git commit -m "feat: render brief-like JSON through formatter in delivery adapters"
```

---

### Task 2: Add brief data helpers (`formatter/data_helpers.py`)

**Files:**
- Create: `formatter/data_helpers.py`
- Create: `tests/test_formatter_data_helpers.py`

**Context:** Raw data from MCP tools (calendar events, delegations, decisions, OKR results) comes as lists of dicts with varying schemas. This module transforms raw API data into the TypedDict structures expected by `formatter.brief` and `formatter.tables`. This decouples the formatter from specific API response shapes.

**Step 1: Write the failing tests**

Create `tests/test_formatter_data_helpers.py`:

```python
"""Tests for formatter.data_helpers — raw API data to formatter structures."""

import pytest
from formatter.data_helpers import (
    calendar_events_to_entries,
    delegations_to_table_data,
    decisions_to_table_data,
    delegations_to_summary,
    decisions_to_summary,
)


class TestCalendarEventsToEntries:
    def test_basic_conversion(self):
        """Convert raw calendar events to CalendarEntry format."""
        raw_events = [
            {
                "title": "ePMLT Stand-up",
                "start": "2026-02-25T08:30:00",
                "end": "2026-02-25T09:00:00",
                "status": "confirmed",
                "location": "Zoom",
            },
            {
                "title": "1:1 with Shawn",
                "start": "2026-02-25T10:00:00",
                "end": "2026-02-25T10:30:00",
                "status": "tentative",
            },
        ]
        entries = calendar_events_to_entries(raw_events)
        assert len(entries) == 2
        assert entries[0]["event"] == "ePMLT Stand-up"
        assert "8:30" in entries[0]["time"]
        assert entries[0]["status"] == "confirmed"

    def test_empty_events(self):
        assert calendar_events_to_entries([]) == []

    def test_missing_fields_handled(self):
        """Events with missing optional fields don't crash."""
        raw = [{"title": "Quick chat", "start": "2026-02-25T14:00:00"}]
        entries = calendar_events_to_entries(raw)
        assert len(entries) == 1
        assert entries[0]["event"] == "Quick chat"


class TestDelegationsToTableData:
    def test_basic_conversion(self):
        """Convert raw delegation dicts to table columns + rows."""
        raw = [
            {
                "task": "Review RBAC proposal",
                "delegated_to": "Shawn",
                "priority": "high",
                "status": "active",
                "due_date": "2026-03-01",
            },
            {
                "task": "Close Statuspage ticket",
                "delegated_to": "Ken",
                "priority": "medium",
                "status": "active",
                "due_date": "",
            },
        ]
        columns, rows = delegations_to_table_data(raw)
        assert "Task" in columns
        assert "Assigned To" in columns
        assert len(rows) == 2
        assert "Shawn" in rows[0]

    def test_empty_delegations(self):
        columns, rows = delegations_to_table_data([])
        assert rows == []


class TestDecisionsToTableData:
    def test_basic_conversion(self):
        raw = [
            {
                "title": "Approve RBAC rollout",
                "status": "pending_execution",
                "owner": "Jason",
                "follow_up_date": "2026-03-01",
            },
        ]
        columns, rows = decisions_to_table_data(raw)
        assert "Decision" in columns
        assert len(rows) == 1
        assert "Approve RBAC rollout" in rows[0]

    def test_empty_decisions(self):
        columns, rows = decisions_to_table_data([])
        assert rows == []


class TestSummaryHelpers:
    def test_delegations_to_summary(self):
        raw = [
            {"task": "A", "status": "active", "priority": "high"},
            {"task": "B", "status": "active", "priority": "medium"},
            {"task": "C", "status": "completed", "priority": "low"},
        ]
        summary = delegations_to_summary(raw)
        assert "2 active" in summary
        assert "1 high" in summary or "high" in summary.lower()

    def test_delegations_to_summary_empty(self):
        assert delegations_to_summary([]) == ""

    def test_decisions_to_summary(self):
        raw = [
            {"title": "X", "status": "pending_execution"},
            {"title": "Y", "status": "pending_execution"},
            {"title": "Z", "status": "executed"},
        ]
        summary = decisions_to_summary(raw)
        assert "2 pending" in summary

    def test_decisions_to_summary_empty(self):
        assert decisions_to_summary([]) == ""
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_formatter_data_helpers.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'formatter.data_helpers'`

**Step 3: Implement `formatter/data_helpers.py`**

```python
"""Transform raw API data into formatter-compatible structures.

Converts raw calendar events, delegations, decisions, and OKR data from
MCP tool responses into the TypedDict structures expected by formatter
modules (brief, tables, cards).
"""

from datetime import datetime
from typing import Sequence

from formatter.types import CalendarEntry


def _format_time(iso_str: str) -> str:
    """Convert ISO datetime string to human-readable time like '8:30 AM'."""
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt.strftime("%-I:%M %p").lstrip("0")
    except (ValueError, TypeError):
        return iso_str


def calendar_events_to_entries(events: Sequence[dict]) -> list[CalendarEntry]:
    """Convert raw calendar event dicts to CalendarEntry format.

    Args:
        events: Raw event dicts from calendar tools (keys: title, start, end, status, location).

    Returns:
        List of CalendarEntry dicts with time, event, status keys.
    """
    entries: list[CalendarEntry] = []
    for ev in events:
        entry: CalendarEntry = {
            "time": _format_time(ev.get("start", "")),
            "event": ev.get("title", ev.get("summary", "")),
            "status": ev.get("status", ""),
        }
        entries.append(entry)
    return entries


def delegations_to_table_data(
    delegations: Sequence[dict],
) -> tuple[list[str], list[tuple[str, ...]]]:
    """Convert raw delegation dicts to table columns and rows.

    Returns:
        (columns, rows) tuple for formatter.tables.render().
    """
    columns = ["Task", "Assigned To", "Priority", "Status", "Due"]
    rows = []
    for d in delegations:
        rows.append((
            d.get("task", ""),
            d.get("delegated_to", ""),
            d.get("priority", ""),
            d.get("status", ""),
            d.get("due_date", ""),
        ))
    return columns, rows


def decisions_to_table_data(
    decisions: Sequence[dict],
) -> tuple[list[str], list[tuple[str, ...]]]:
    """Convert raw decision dicts to table columns and rows.

    Returns:
        (columns, rows) tuple for formatter.tables.render().
    """
    columns = ["Decision", "Status", "Owner", "Follow-up"]
    rows = []
    for d in decisions:
        rows.append((
            d.get("title", ""),
            d.get("status", ""),
            d.get("owner", ""),
            d.get("follow_up_date", ""),
        ))
    return columns, rows


def delegations_to_summary(delegations: Sequence[dict]) -> str:
    """Produce a one-line summary of delegations for the daily brief.

    Returns:
        Summary string like '3 active (1 high, 1 overdue)' or empty string.
    """
    if not delegations:
        return ""

    active = [d for d in delegations if d.get("status") == "active"]
    high = [d for d in active if d.get("priority") in ("high", "critical")]

    parts = [f"{len(active)} active"]
    if high:
        parts.append(f"{len(high)} high priority")
    return ", ".join(parts)


def decisions_to_summary(decisions: Sequence[dict]) -> str:
    """Produce a one-line summary of decisions for the daily brief.

    Returns:
        Summary string like '2 pending, 1 executed' or empty string.
    """
    if not decisions:
        return ""

    pending = [d for d in decisions if d.get("status") == "pending_execution"]
    parts = [f"{len(pending)} pending"]
    return ", ".join(parts)
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_formatter_data_helpers.py -v`
Expected: All 10 tests PASS

**Step 5: Commit**

```bash
git add formatter/data_helpers.py tests/test_formatter_data_helpers.py
git commit -m "feat: add data helpers to transform raw API data for formatter"
```

---

### Task 3: Add formatted output to key MCP tools

**Files:**
- Modify: `mcp_tools/lifecycle_tools.py`
- Modify: `mcp_tools/okr_tools.py`
- Create: `tests/test_formatted_mcp_responses.py`

**Context:** MCP tools like `list_delegations`, `list_pending_decisions`, `check_alerts`, and `query_okr_status` currently return raw JSON. We add a `formatted` key to their responses containing a pre-rendered table/card string that Claude can display directly. This avoids requiring a second `format_table` call for common operations.

**Step 1: Write the failing tests**

Create `tests/test_formatted_mcp_responses.py`:

```python
"""Tests for formatted output in MCP tool responses."""

import json
import pytest
from unittest.mock import MagicMock

import mcp_server  # noqa: F401 — trigger register() calls
from mcp_tools.lifecycle_tools import list_delegations, list_pending_decisions, check_alerts
from mcp_tools.okr_tools import query_okr_status


@pytest.fixture
def mock_memory_store():
    store = MagicMock()
    return store


@pytest.fixture
def lifecycle_state(mock_memory_store):
    mcp_server._state.memory_store = mock_memory_store
    yield mock_memory_store
    mcp_server._state.memory_store = None


class TestListDelegationsFormatted:
    @pytest.mark.asyncio
    async def test_includes_formatted_key(self, lifecycle_state):
        from tools.lifecycle import list_delegations as raw_list
        lifecycle_state.return_value = None

        # Mock the lifecycle function to return sample data
        import tools.lifecycle as lc
        original = lc.list_delegations
        lc.list_delegations = lambda store, **kw: {
            "results": [
                {"task": "Review RBAC", "delegated_to": "Shawn", "priority": "high", "status": "active", "due_date": "2026-03-01"},
            ]
        }
        try:
            result = await list_delegations()
            parsed = json.loads(result)
            assert "formatted" in parsed
            assert "Review RBAC" in parsed["formatted"]
            assert "Shawn" in parsed["formatted"]
        finally:
            lc.list_delegations = original

    @pytest.mark.asyncio
    async def test_empty_delegations_no_formatted(self, lifecycle_state):
        import tools.lifecycle as lc
        original = lc.list_delegations
        lc.list_delegations = lambda store, **kw: {"results": []}
        try:
            result = await list_delegations()
            parsed = json.loads(result)
            assert parsed.get("formatted", "") == ""
        finally:
            lc.list_delegations = original


class TestListPendingDecisionsFormatted:
    @pytest.mark.asyncio
    async def test_includes_formatted_key(self, lifecycle_state):
        import tools.lifecycle as lc
        original = lc.list_pending_decisions
        lc.list_pending_decisions = lambda store: {
            "results": [
                {"title": "Approve rollout", "status": "pending_execution", "owner": "Jason", "follow_up_date": "2026-03-01"},
            ]
        }
        try:
            result = await list_pending_decisions()
            parsed = json.loads(result)
            assert "formatted" in parsed
            assert "Approve rollout" in parsed["formatted"]
        finally:
            lc.list_pending_decisions = original


class TestCheckAlertsFormatted:
    @pytest.mark.asyncio
    async def test_includes_formatted_key(self, lifecycle_state):
        import tools.lifecycle as lc
        original = lc.check_alerts
        lc.check_alerts = lambda store: {
            "alerts": [
                {"type": "overdue_delegation", "message": "Review RBAC is overdue"},
            ],
            "count": 1,
        }
        try:
            result = await check_alerts()
            parsed = json.loads(result)
            assert "formatted" in parsed
            assert "overdue" in parsed["formatted"].lower() or "RBAC" in parsed["formatted"]
        finally:
            lc.check_alerts = original


class TestQueryOkrFormatted:
    @pytest.mark.asyncio
    async def test_includes_formatted_key(self):
        mock_store = MagicMock()
        mock_store.query.return_value = {
            "results": [
                {"initiative": "RBAC rollout", "team": "IAM", "status": "At Risk", "progress": "5%"},
            ]
        }
        mcp_server._state.okr_store = mock_store
        try:
            result = await query_okr_status(query="RBAC")
            parsed = json.loads(result)
            assert "formatted" in parsed
            assert "RBAC" in parsed["formatted"]
        finally:
            mcp_server._state.okr_store = None
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_formatted_mcp_responses.py -v`
Expected: FAIL — no `formatted` key in responses

**Step 3: Add formatting to `mcp_tools/lifecycle_tools.py`**

Add a helper at the top of `register()`:

```python
def _format_delegations(results):
    """Add formatted table to delegation results."""
    try:
        from formatter.data_helpers import delegations_to_table_data
        from formatter.tables import render
        items = results.get("results", [])
        if not items:
            results["formatted"] = ""
            return results
        columns, rows = delegations_to_table_data(items)
        results["formatted"] = render(columns=columns, rows=rows, title="Delegations", mode="plain")
    except Exception:
        results["formatted"] = ""
    return results

def _format_decisions(results):
    """Add formatted table to decision results."""
    try:
        from formatter.data_helpers import decisions_to_table_data
        from formatter.tables import render
        items = results.get("results", [])
        if not items:
            results["formatted"] = ""
            return results
        columns, rows = decisions_to_table_data(items)
        results["formatted"] = render(columns=columns, rows=rows, title="Decisions", mode="plain")
    except Exception:
        results["formatted"] = ""
    return results

def _format_alerts(results):
    """Add formatted text to alert results."""
    try:
        from formatter.cards import render as render_card
        alerts = results.get("alerts", [])
        if not alerts:
            results["formatted"] = ""
            return results
        fields = {}
        for i, alert in enumerate(alerts):
            fields[f"Alert {i+1}"] = alert.get("message", str(alert))
        results["formatted"] = render_card(
            title="Active Alerts",
            fields=fields,
            status="red" if len(alerts) > 0 else "green",
            mode="plain",
        )
    except Exception:
        results["formatted"] = ""
    return results
```

Then wrap the return values:
- `list_delegations`: `return json.dumps(_format_delegations(lifecycle_tools.list_delegations(...)))`
- `list_pending_decisions`: `return json.dumps(_format_decisions(lifecycle_tools.list_pending_decisions(...)))`
- `check_alerts`: `return json.dumps(_format_alerts(lifecycle_tools.check_alerts(...)))`

**Step 4: Add formatting to `mcp_tools/okr_tools.py`**

Add a helper inside `register()`:

```python
def _format_okr_results(results):
    """Add formatted table to OKR query results."""
    try:
        from formatter.tables import render
        items = results.get("results", [])
        if not items:
            results["formatted"] = ""
            return results
        columns = ["Initiative", "Team", "Status", "Progress"]
        rows = []
        for item in items:
            rows.append((
                item.get("initiative", item.get("name", "")),
                item.get("team", ""),
                item.get("status", ""),
                item.get("progress", ""),
            ))
        results["formatted"] = render(columns=columns, rows=rows, title="OKR Status", mode="plain")
    except Exception:
        results["formatted"] = ""
    return results
```

Then wrap `query_okr_status` when `summary_only` is False:
```python
results = okr_store.query(...)
return json.dumps(_format_okr_results(results))
```

**Step 5: Run tests to verify they pass**

Run: `pytest tests/test_formatted_mcp_responses.py -v`
Expected: All tests PASS

**Step 6: Run existing tests to verify no regressions**

Run: `pytest tests/test_tools_lifecycle.py tests/test_mcp_okr.py -v`
Expected: All existing tests still pass

**Step 7: Commit**

```bash
git add mcp_tools/lifecycle_tools.py mcp_tools/okr_tools.py tests/test_formatted_mcp_responses.py
git commit -m "feat: add formatted output to delegation, decision, alert, and OKR tools"
```

---

### Task 4: Enhance daily brief with delegation/decision/OKR sub-components

**Files:**
- Modify: `formatter/brief.py:135-244`
- Modify: `tests/test_formatter_brief.py`

**Context:** The current `render_daily()` accepts `delegations` and `decisions` as pre-formatted strings. We enhance it to also accept structured delegation/decision data (lists of dicts) and render them as rich tables within the brief. We also add an optional `okr_highlights` parameter for OKR status cards.

**Step 1: Write the failing tests**

Add to `tests/test_formatter_brief.py`:

```python
class TestBriefEnhancements:
    """Tests for enhanced brief with structured delegations/decisions/OKR."""

    def test_structured_delegations(self):
        """Structured delegation data renders as a table in the brief."""
        result = render_daily(
            date="2026-02-25",
            calendar=[{"time": "9 AM", "event": "Standup", "status": "Teams"}],
            delegation_items=[
                {"task": "Review RBAC", "delegated_to": "Shawn", "priority": "high", "status": "active"},
            ],
            mode="plain",
            width=120,
        )
        assert "DELEGATIONS" in result
        assert "Review RBAC" in result
        assert "Shawn" in result

    def test_structured_decisions(self):
        """Structured decision data renders as a table in the brief."""
        result = render_daily(
            date="2026-02-25",
            calendar=[{"time": "9 AM", "event": "Standup", "status": "Teams"}],
            decision_items=[
                {"title": "Approve rollout", "status": "pending_execution", "owner": "Jason"},
            ],
            mode="plain",
            width=120,
        )
        assert "DECISIONS" in result
        assert "Approve rollout" in result

    def test_okr_highlights(self):
        """OKR highlights render as a section in the brief."""
        result = render_daily(
            date="2026-02-25",
            calendar=[{"time": "9 AM", "event": "Standup", "status": "Teams"}],
            okr_highlights=[
                {"initiative": "RBAC rollout", "team": "IAM", "status": "At Risk", "progress": "5%"},
            ],
            mode="plain",
            width=120,
        )
        assert "OKR" in result
        assert "RBAC rollout" in result
        assert "At Risk" in result or "5%" in result

    def test_structured_and_string_delegations_coexist(self):
        """String delegations param still works alongside new structured param."""
        result = render_daily(
            date="2026-02-25",
            calendar=[{"time": "9 AM", "event": "Standup", "status": "Teams"}],
            delegations="2 active delegations",
            mode="plain",
        )
        assert "DELEGATIONS" in result
        assert "2 active delegations" in result

    def test_all_enhanced_sections(self):
        """All new structured sections render together."""
        result = render_daily(
            date="2026-02-25",
            calendar=[{"time": "9 AM", "event": "Standup", "status": "Teams"}],
            delegation_items=[
                {"task": "Task A", "delegated_to": "Alice", "priority": "high", "status": "active"},
            ],
            decision_items=[
                {"title": "Decision X", "status": "pending_execution", "owner": "Bob"},
            ],
            okr_highlights=[
                {"initiative": "OKR item", "team": "SecOps", "status": "On Track", "progress": "80%"},
            ],
            mode="plain",
            width=120,
        )
        assert "DELEGATIONS" in result
        assert "DECISIONS" in result
        assert "OKR" in result
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_formatter_brief.py::TestBriefEnhancements -v`
Expected: FAIL — `render_daily()` got unexpected keyword argument 'delegation_items'

**Step 3: Enhance `formatter/brief.py`**

Add new builder functions:

```python
def _build_delegation_table(items: Sequence[dict]) -> Table:
    """Build a rich Table for structured delegation data."""
    table = Table(box=INNER_BOX, expand=True, show_edge=False)
    table.add_column("Task", style="white")
    table.add_column("Assigned To", style="cyan", no_wrap=True)
    table.add_column("Priority", style="dim")
    table.add_column("Status", style="dim")
    for item in items:
        table.add_row(
            item.get("task", ""),
            item.get("delegated_to", ""),
            item.get("priority", ""),
            item.get("status", ""),
        )
    return table


def _build_decision_table(items: Sequence[dict]) -> Table:
    """Build a rich Table for structured decision data."""
    table = Table(box=INNER_BOX, expand=True, show_edge=False)
    table.add_column("Decision", style="white")
    table.add_column("Status", style="dim")
    table.add_column("Owner", style="cyan", no_wrap=True)
    for item in items:
        table.add_row(
            item.get("title", ""),
            item.get("status", ""),
            item.get("owner", ""),
        )
    return table


def _build_okr_table(items: Sequence[dict]) -> Table:
    """Build a rich Table for OKR highlights."""
    table = Table(box=INNER_BOX, expand=True, show_edge=False)
    table.add_column("Initiative", style="white")
    table.add_column("Team", style="cyan", no_wrap=True)
    table.add_column("Status", style="dim")
    table.add_column("Progress", style="dim")
    for item in items:
        table.add_row(
            item.get("initiative", item.get("name", "")),
            item.get("team", ""),
            item.get("status", ""),
            item.get("progress", ""),
        )
    return table
```

Update `render_daily()` signature to add new optional parameters:

```python
def render_daily(
    date: str,
    calendar: Optional[Sequence[CalendarEntry]] = None,
    action_items: Optional[Sequence[ActionItem]] = None,
    conflicts: Optional[Sequence[Conflict]] = None,
    email_highlights: Optional[Sequence[EmailHighlight]] = None,
    personal: Optional[Sequence[str]] = None,
    delegations: Optional[str] = None,
    decisions: Optional[str] = None,
    delegation_items: Optional[Sequence[dict]] = None,
    decision_items: Optional[Sequence[dict]] = None,
    okr_highlights: Optional[Sequence[dict]] = None,
    mode: str = "terminal",
    width: int = 80,
) -> str:
```

Add new sections after the existing delegations/decisions sections (before the `if not sections` check):

```python
    # Structured delegations (table) — takes priority over string form
    if delegation_items:
        table = _build_delegation_table(delegation_items)
        sections.append(
            Panel(table, title="[bold]DELEGATIONS[/bold]", title_align="left", box=BOX)
        )
    elif delegations:
        sections.append(
            Panel(Text(f"  {delegations}"), title="[bold]DELEGATIONS[/bold]", title_align="left", box=BOX)
        )

    # Structured decisions (table) — takes priority over string form
    if decision_items:
        table = _build_decision_table(decision_items)
        sections.append(
            Panel(table, title="[bold]DECISIONS[/bold]", title_align="left", box=BOX)
        )
    elif decisions:
        sections.append(
            Panel(Text(f"  {decisions}"), title="[bold]DECISIONS[/bold]", title_align="left", box=BOX)
        )

    # OKR highlights
    if okr_highlights:
        table = _build_okr_table(okr_highlights)
        sections.append(
            Panel(table, title="[bold]OKR HIGHLIGHTS[/bold]", title_align="left", box=BOX)
        )
```

**Important:** Remove the existing separate `if delegations:` and `if decisions:` blocks and replace with the combined logic above.

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_formatter_brief.py -v`
Expected: All tests pass (existing + new)

**Step 5: Update `mcp_tools/formatter_tools.py` to pass new params**

The `format_brief` MCP tool uses `render_daily(**parsed, mode=mode)`. Since we added new optional params, any JSON data with `delegation_items`, `decision_items`, or `okr_highlights` keys will automatically be passed through. No code change needed — just verify:

Run: `pytest tests/test_formatter_tools.py -v`
Expected: All tests still pass

**Step 6: Commit**

```bash
git add formatter/brief.py tests/test_formatter_brief.py
git commit -m "feat: add structured delegation/decision/OKR sections to daily brief"
```

---

## Execution Summary

| Task | Files | Tests | Parallel Group |
|------|-------|-------|----------------|
| 1. Delivery integration | `scheduler/delivery.py` | 3 new | Wave 1 |
| 2. Brief data helpers | `formatter/data_helpers.py` | 10 new | Wave 1 |
| 3. MCP formatted responses | `mcp_tools/lifecycle_tools.py`, `mcp_tools/okr_tools.py` | 5 new | Wave 2 |
| 4. Brief enhancements | `formatter/brief.py` | 5 new | Wave 2 |

**Total: ~23 new tests across 4 workstreams.**

**Wave 1** (Tasks 1 + 2): Fully independent, run in parallel.
**Wave 2** (Tasks 3 + 4): Both depend on Task 2's `data_helpers.py`, run in parallel after Task 2 completes.
