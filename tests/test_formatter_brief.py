"""Tests for formatter.brief — daily brief composition."""

import pytest
from formatter.brief import render_daily, _format_date


# --- Fixtures / sample data ---

SAMPLE_CALENDAR = [
    {"time": "8:30 AM", "event": "ePMLT Stand-up", "status": "confirmed"},
    {"time": "10:00 AM", "event": "1:1 with Shawn", "status": "tentative"},
]

SAMPLE_ACTIONS = [
    {"priority": "urgent", "text": "Review RBAC proposal"},
    {"priority": "high", "text": "Send OKR update"},
    {"priority": "low", "text": "Update wiki pages"},
]

SAMPLE_CONFLICTS = [
    {"time": "2:00 PM", "a": "Design Review", "b": "Sprint Retro"},
]

SAMPLE_EMAILS = [
    {"sender": "Mike T.", "subject": "Budget approval needed", "tag": "action"},
    {"sender": "HR Team", "subject": "Benefits enrollment reminder", "tag": "fyi"},
]

SAMPLE_PERSONAL = [
    "Pick up dry cleaning",
    "Call dentist for appointment",
]


class TestRenderDaily:
    """Tests for render_daily composition function."""

    def test_full_brief(self):
        """All sections populated — assert all content appears in output."""
        result = render_daily(
            date="2026-02-25",
            calendar=SAMPLE_CALENDAR,
            action_items=SAMPLE_ACTIONS,
            conflicts=SAMPLE_CONFLICTS,
            email_highlights=SAMPLE_EMAILS,
            personal=SAMPLE_PERSONAL,
            delegations="2 active delegations",
            decisions="1 pending decision",
            mode="plain",
            width=100,
        )

        # Header
        assert "DAILY BRIEFING" in result
        assert "Wednesday, February 25, 2026" in result

        # Calendar section
        assert "CALENDAR" in result
        assert "ePMLT Stand-up" in result
        assert "1:1 with Shawn" in result
        assert "8:30 AM" in result

        # Action items
        assert "ACTION ITEMS" in result
        assert "Review RBAC proposal" in result
        assert "Send OKR update" in result

        # Conflicts
        assert "CONFLICTS" in result
        assert "Design Review" in result
        assert "Sprint Retro" in result

        # Email highlights
        assert "EMAIL HIGHLIGHTS" in result
        assert "Mike T." in result
        assert "Budget approval needed" in result

        # Personal
        assert "PERSONAL" in result
        assert "Pick up dry cleaning" in result

        # Delegations and decisions
        assert "DELEGATIONS" in result
        assert "2 active delegations" in result
        assert "DECISIONS" in result
        assert "1 pending decision" in result

    def test_brief_plain_no_ansi(self):
        """Plain mode output contains no ANSI escape sequences."""
        result = render_daily(
            date="2026-02-25",
            calendar=SAMPLE_CALENDAR,
            action_items=SAMPLE_ACTIONS,
            mode="plain",
            width=80,
        )
        # ANSI escape sequences start with ESC ()
        assert "" not in result
        # Should still have content
        assert "ePMLT Stand-up" in result

    def test_brief_empty_sections_omitted(self):
        """All sections empty — returns empty string, no section headers."""
        result = render_daily(
            date="2026-02-25",
            mode="plain",
            width=80,
        )
        assert result == ""

    def test_brief_only_calendar(self):
        """Only calendar populated — only CALENDAR section present."""
        result = render_daily(
            date="2026-02-25",
            calendar=SAMPLE_CALENDAR,
            mode="plain",
            width=80,
        )
        assert "CALENDAR" in result
        assert "ePMLT Stand-up" in result
        # Other sections should not appear
        assert "ACTION ITEMS" not in result
        assert "CONFLICTS" not in result
        assert "EMAIL HIGHLIGHTS" not in result
        assert "PERSONAL" not in result
        assert "DELEGATIONS" not in result
        assert "DECISIONS" not in result

    def test_brief_date_formatting(self):
        """Human-readable date appears in header."""
        result = render_daily(
            date="2026-07-04",
            calendar=SAMPLE_CALENDAR,
            mode="plain",
            width=80,
        )
        assert "Saturday, July 4, 2026" in result


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

    def test_structured_delegation_items_override_string(self):
        """Structured delegation_items take priority over string delegations."""
        result = render_daily(
            date="2026-02-25",
            calendar=[{"time": "9 AM", "event": "Standup", "status": "Teams"}],
            delegations="old string form",
            delegation_items=[
                {"task": "New task", "delegated_to": "Alice", "priority": "high", "status": "active"},
            ],
            mode="plain",
            width=120,
        )
        assert "New task" in result
        assert "Alice" in result
        # String form should not appear since structured takes priority
        assert "old string form" not in result

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


class TestStringCoercion:
    """Tests for graceful coercion when plain strings are passed instead of dicts."""

    def test_action_items_as_plain_strings(self):
        """Plain strings in action_items get wrapped as medium-priority dicts."""
        result = render_daily(
            date="2026-02-25",
            action_items=["Review RBAC proposal", "Send OKR update"],
            mode="plain",
            width=80,
        )
        assert "ACTION ITEMS" in result
        assert "Review RBAC proposal" in result
        assert "Send OKR update" in result

    def test_action_items_mixed_strings_and_dicts(self):
        """Mix of strings and dicts both render correctly."""
        result = render_daily(
            date="2026-02-25",
            action_items=[
                "Plain string item",
                {"priority": "high", "text": "Dict item"},
            ],
            mode="plain",
            width=80,
        )
        assert "Plain string item" in result
        assert "Dict item" in result

    def test_conflicts_as_plain_strings(self):
        """Plain strings in conflicts render as-is."""
        result = render_daily(
            date="2026-02-25",
            conflicts=["8:00-10:00: Meeting A vs Meeting B"],
            mode="plain",
            width=80,
        )
        assert "CONFLICTS" in result
        assert "Meeting A vs Meeting B" in result

    def test_conflicts_mixed_strings_and_dicts(self):
        """Mix of string and dict conflicts both render."""
        result = render_daily(
            date="2026-02-25",
            conflicts=[
                "Plain conflict description",
                {"time": "2:00 PM", "a": "Design Review", "b": "Sprint Retro"},
            ],
            mode="plain",
            width=80,
        )
        assert "Plain conflict description" in result
        assert "Design Review" in result

    def test_email_highlights_as_plain_strings(self):
        """Plain strings in email_highlights render in subject column."""
        result = render_daily(
            date="2026-02-25",
            email_highlights=["Check Outlook for work email"],
            mode="plain",
            width=80,
        )
        assert "EMAIL HIGHLIGHTS" in result
        assert "Check Outlook for work email" in result

    def test_email_highlights_mixed_strings_and_dicts(self):
        """Mix of string and dict email highlights both render."""
        result = render_daily(
            date="2026-02-25",
            email_highlights=[
                "Plain email note",
                {"sender": "Mike T.", "subject": "Budget approval", "tag": "action"},
            ],
            mode="plain",
            width=80,
        )
        assert "Plain email note" in result
        assert "Mike T." in result
        assert "Budget approval" in result

    def test_calendar_as_plain_strings(self):
        """Plain strings in calendar render in the event column."""
        result = render_daily(
            date="2026-02-25",
            calendar=["9:00 AM - Team standup", "10:00 AM - 1:1 with Shawn"],
            mode="plain",
            width=80,
        )
        assert "CALENDAR" in result
        assert "Team standup" in result
        assert "1:1 with Shawn" in result

    def test_human_readable_date_coerced(self):
        """Human-readable date string is accepted and passed through."""
        result = render_daily(
            date="Wednesday, February 25, 2026",
            calendar=[{"time": "9 AM", "event": "Standup", "status": ""}],
            mode="plain",
            width=80,
        )
        assert "DAILY BRIEFING" in result
        assert "Wednesday, February 25, 2026" in result


class TestFormatDate:
    """Tests for _format_date helper."""

    def test_format_date_basic(self):
        assert _format_date("2026-02-25") == "Wednesday, February 25, 2026"

    def test_format_date_single_digit_day(self):
        assert _format_date("2026-07-04") == "Saturday, July 4, 2026"

    def test_format_date_new_year(self):
        assert _format_date("2026-01-01") == "Thursday, January 1, 2026"
