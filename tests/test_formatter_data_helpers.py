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

    def test_summary_fallback(self):
        """Falls back to 'summary' key when 'title' is missing."""
        raw = [{"summary": "Team sync", "start": "2026-02-25T09:00:00"}]
        entries = calendar_events_to_entries(raw)
        assert entries[0]["event"] == "Team sync"

    def test_invalid_start_time(self):
        """Non-ISO start time passes through as-is."""
        raw = [{"title": "Event", "start": "not-a-date"}]
        entries = calendar_events_to_entries(raw)
        assert entries[0]["time"] == "not-a-date"


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
