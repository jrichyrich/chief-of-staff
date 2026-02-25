"""Tests for formatter.text — plain-text rendering helpers."""

from formatter.text import strip_ansi, status_text, priority_icon


class TestStripAnsi:
    def test_removes_ansi_codes(self):
        text = "[1mBold[0m normal"
        assert strip_ansi(text) == "Bold normal"

    def test_plain_text_unchanged(self):
        assert strip_ansi("hello world") == "hello world"

    def test_empty_string(self):
        assert strip_ansi("") == ""


class TestStatusText:
    def test_green(self):
        assert status_text("green") == "[GREEN]"

    def test_yellow(self):
        assert status_text("yellow") == "[YELLOW]"

    def test_mixed_case(self):
        assert status_text("Red") == "[RED]"


class TestPriorityIcon:
    def test_urgent(self):
        assert priority_icon("urgent") == "⚠"

    def test_unknown_defaults_to_bullet(self):
        assert priority_icon("unknown") == "●"

    def test_case_insensitive(self):
        assert priority_icon("HIGH") == "★"
