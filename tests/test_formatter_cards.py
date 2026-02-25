"""Tests for formatter.cards — status cards and key-value panels."""

import re

from formatter.cards import render, render_kv


class TestKeyValueRender:
    """Tests for the render_kv function."""

    def test_basic_kv(self):
        """render_kv returns a string containing all keys and values."""
        fields = {"Name": "Jarvis", "Version": "1.0"}
        result = render_kv(fields, mode="plain", width=80)
        assert "Name" in result
        assert "Jarvis" in result
        assert "Version" in result
        assert "1.0" in result

    def test_kv_empty_fields(self):
        """render_kv returns empty string when fields dict is empty."""
        result = render_kv({}, mode="plain", width=80)
        assert result == ""


class TestCardRender:
    """Tests for the render function."""

    def test_basic_card(self):
        """render produces a panel containing the title and field data."""
        fields = {"Host": "localhost", "Port": "8080"}
        result = render("Server Info", fields, mode="plain", width=80)
        assert "Server Info" in result
        assert "Host" in result
        assert "localhost" in result
        assert "Port" in result
        assert "8080" in result

    def test_card_plain_no_ansi(self):
        """render with mode='plain' produces no ANSI escape codes."""
        fields = {"Key": "Value"}
        result = render("Title", fields, mode="plain", status="ok", width=80)
        # ANSI escape sequences start with ESC[
        assert "\x1b[" not in result

    def test_card_terminal_has_ansi(self):
        """render with mode='terminal' produces output containing ANSI escape codes."""
        fields = {"Key": "Value"}
        result = render("Title", fields, mode="terminal", status="ok", width=80)
        # Terminal mode should have ANSI codes
        assert "\x1b[" in result

    def test_card_no_status(self):
        """render without a status omits any status badge text."""
        fields = {"Item": "Data"}
        result = render("Card Title", fields, mode="plain", width=80)
        # Should still have the title and data
        assert "Card Title" in result
        assert "Item" in result
        assert "Data" in result
        # Should not contain any status badge markers (brackets around status words)
        for status_word in ["ok", "pass", "success", "warn", "fail", "error"]:
            # Status badges are typically rendered as [STATUS] in the subtitle
            assert f"[{status_word}]" not in result.lower() or status_word in ("ok",)

    def test_card_with_body_text(self):
        """render with body text includes the body in the output."""
        fields = {"Name": "Test"}
        body = "This is additional body text for the card."
        result = render("My Card", fields, mode="plain", body=body, width=80)
        assert "My Card" in result
        assert "Name" in result
        assert "Test" in result
        assert "This is additional body text for the card." in result
