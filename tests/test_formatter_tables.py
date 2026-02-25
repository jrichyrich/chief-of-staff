"""Tests for formatter.tables — dual-mode table rendering."""

import sys
import os

# Ensure project root is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from formatter.tables import render


class TestBasicTable:
    """Test basic table rendering."""

    def test_basic_table_contains_all_data(self):
        """All column headers and cell values appear in rendered output."""
        columns = ['Name', 'Age', 'City']
        rows = [
            ['Alice', '30', 'Portland'],
            ['Bob', '25', 'Seattle'],
        ]
        result = render(columns, rows, mode='plain')
        for col in columns:
            assert col in result, f'Column header {col!r} not found in output'
        for row in rows:
            for cell in row:
                assert cell in result, f'Cell value {cell!r} not found in output'


class TestModes:
    """Test terminal vs plain mode output."""

    def test_plain_mode_has_no_ansi(self):
        """Plain mode output must contain no ANSI escape sequences."""
        columns = ['Status', 'Item']
        rows = [['OK', 'Widget']]
        result = render(columns, rows, mode='plain')
        assert '[' not in result, (
            f'ANSI escape found in plain mode output: {result!r}'
        )

    def test_terminal_mode_has_ansi(self):
        """Terminal mode output must contain ANSI escape sequences."""
        columns = ['Status', 'Item']
        rows = [['OK', 'Widget']]
        result = render(columns, rows, mode='terminal')
        assert '[' in result, (
            f'No ANSI escape found in terminal mode output: {result!r}'
        )


class TestEdgeCases:
    """Test edge cases and special inputs."""

    def test_empty_rows_returns_empty_string(self):
        """Empty row list returns empty string — no table rendered."""
        result = render(['A', 'B'], [], mode='plain')
        assert result == ''

    def test_no_title(self):
        """Table with no title still renders correctly."""
        result = render(['Col'], [['val']], mode='plain', title=None)
        assert 'Col' in result
        assert 'val' in result

    def test_title_appears_in_output(self):
        """When a title is supplied it appears in the rendered output."""
        result = render(['Col'], [['val']], mode='plain', title='My Table')
        assert 'My Table' in result

    def test_unicode_content(self):
        """Unicode characters in columns and cells are preserved."""
        columns = ['Emoji', 'CJK']
        rows = [['🚀', '你好']]
        result = render(columns, rows, mode='plain')
        assert '🚀' in result
        assert '你好' in result

    def test_column_count_matches_row_length(self):
        """Rows shorter than the column list are padded, not crashed."""
        columns = ['A', 'B', 'C']
        rows = [['only_one']]  # row has 1 value but 3 columns
        result = render(columns, rows, mode='plain')
        assert 'only_one' in result
        # Should not raise — short rows are padded with empty strings
        assert 'A' in result
        assert 'B' in result
        assert 'C' in result
