"""Tests for SessionHealth tracking."""

from datetime import datetime

import pytest

from mcp_tools.state import SessionHealth


class TestSessionHealth:
    def test_defaults(self):
        health = SessionHealth()
        assert health.tool_call_count == 0
        assert health.session_start != ""
        assert health.last_checkpoint == ""

    def test_record_tool_call(self):
        health = SessionHealth()
        assert health.tool_call_count == 0
        health.record_tool_call()
        assert health.tool_call_count == 1
        health.record_tool_call()
        assert health.tool_call_count == 2

    def test_record_checkpoint(self):
        health = SessionHealth()
        assert health.last_checkpoint == ""
        health.record_checkpoint()
        assert health.last_checkpoint != ""
        # Should be parseable as ISO datetime
        parsed = datetime.fromisoformat(health.last_checkpoint)
        assert isinstance(parsed, datetime)

    def test_to_dict(self):
        health = SessionHealth(tool_call_count=5)
        d = health.to_dict()
        assert d["tool_call_count"] == 5
        assert "session_start" in d
        assert "last_checkpoint" in d

    def test_to_dict_no_checkpoint(self):
        health = SessionHealth()
        d = health.to_dict()
        # Empty string last_checkpoint is normalized to None in to_dict
        assert d["last_checkpoint"] is None

    def test_session_start_auto_set(self):
        health = SessionHealth()
        parsed = datetime.fromisoformat(health.session_start)
        assert isinstance(parsed, datetime)
