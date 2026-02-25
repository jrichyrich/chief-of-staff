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


class TestFormatDate:
    """Tests for _format_date helper."""

    def test_format_date_basic(self):
        assert _format_date("2026-02-25") == "Wednesday, February 25, 2026"

    def test_format_date_single_digit_day(self):
        assert _format_date("2026-07-04") == "Saturday, July 4, 2026"

    def test_format_date_new_year(self):
        assert _format_date("2026-01-01") == "Thursday, January 1, 2026"
