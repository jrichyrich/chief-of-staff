"""Tests for formatter.dashboard multi-panel grid layouts."""

from formatter.dashboard import render


class TestDashboardRender:
    """Tests for the render() function."""

    def test_basic_dashboard(self):
        """Multiple panels should include title and all panel titles."""
        result = render(
            title="Daily Status",
            panels=[
                {"title": "Schedule", "content": "8:30 AM  ePMLT"},
                {"title": "Notes", "content": "No notes today."},
            ],
            mode="plain",
        )
        assert "Daily Status" in result
        assert "Schedule" in result
        assert "8:30 AM  ePMLT" in result
        assert "Notes" in result
        assert "No notes today." in result

    def test_dashboard_plain_no_ansi(self):
        """Plain mode should produce output with no ANSI escape codes."""
        result = render(
            title="Report",
            panels=[{"title": "Section", "content": "data"}],
            mode="plain",
        )
        assert "\x1b" not in result
        assert "Report" in result

    def test_dashboard_terminal_has_ansi(self):
        """Terminal mode should produce output containing ANSI escape codes."""
        result = render(
            title="Report",
            panels=[{"title": "Section", "content": "data"}],
            mode="terminal",
        )
        assert "\x1b" in result

    def test_empty_panels_returns_empty(self):
        """An empty panels list should return an empty string."""
        result = render(title="Empty", panels=[])
        assert result == ""

    def test_single_panel(self):
        """A single panel should render with its title and content."""
        result = render(
            title="Single",
            panels=[{"title": "Only Panel", "content": "Hello world"}],
            mode="plain",
        )
        assert "Single" in result
        assert "Only Panel" in result
        assert "Hello world" in result
