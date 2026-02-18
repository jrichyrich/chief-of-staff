# tests/test_security_input_sanitization.py
"""Tests for input sanitization: osascript escaping and memory category validation."""
import pytest
from unittest.mock import MagicMock

from apple_notifications.notifier import _escape_osascript
from config import VALID_FACT_CATEGORIES
from memory.store import MemoryStore
from tools.executor import execute_store_memory


@pytest.fixture
def memory_store(tmp_path):
    store = MemoryStore(tmp_path / "test.db")
    yield store
    store.close()


# ---------------------------------------------------------------------------
# _escape_osascript: escape special characters for AppleScript strings
# ---------------------------------------------------------------------------

class TestEscapeOsascript:
    """The _escape_osascript function must neutralize characters that could
    break out of AppleScript string literals or inject control sequences."""

    def test_escapes_backslash(self):
        assert _escape_osascript("a\\b") == "a\\\\b"

    def test_escapes_double_quote(self):
        assert _escape_osascript('say "hello"') == 'say \\"hello\\"'

    def test_escapes_newline(self):
        assert _escape_osascript("line1\nline2") == "line1\\nline2"

    def test_escapes_carriage_return(self):
        assert _escape_osascript("line1\rline2") == "line1\\rline2"

    def test_escapes_tab(self):
        assert _escape_osascript("col1\tcol2") == "col1\\tcol2"

    def test_escapes_all_five_chars_combined(self):
        """String containing all 5 special characters should be fully escaped."""
        raw = 'a\\b"c\nd\re\tf'
        escaped = _escape_osascript(raw)
        assert escaped == 'a\\\\b\\"c\\nd\\re\\tf'

    def test_empty_string_passes_through(self):
        assert _escape_osascript("") == ""

    def test_plain_string_unchanged(self):
        plain = "Hello World 123 !@#$%^&*()"
        assert _escape_osascript(plain) == plain

    def test_escape_order_matters(self):
        """Backslash must be escaped first to avoid double-escaping."""
        # If we have a literal \n (backslash + n), it should become \\n
        # But a real newline char should become \n
        raw_backslash_n = "a\\nb"  # literal \n in the string
        escaped = _escape_osascript(raw_backslash_n)
        # \ becomes \\, then n stays n → "a\\nb"
        assert escaped == "a\\\\nb"

    def test_injection_attempt_via_quotes(self):
        """An injection like `" & do shell script "rm -rf /"` should be safely escaped."""
        malicious = '" & do shell script "rm -rf /" & "'
        escaped = _escape_osascript(malicious)
        assert '\\"' in escaped
        # No unescaped quotes remain
        # After escaping, the string should not contain bare "
        parts = escaped.split('\\"')
        for part in parts:
            assert '"' not in part


# ---------------------------------------------------------------------------
# execute_store_memory: category validation
# ---------------------------------------------------------------------------

class TestStoreMemoryCategoryValidation:
    """execute_store_memory must reject categories not in VALID_FACT_CATEGORIES."""

    def test_rejects_invalid_category_admin(self, memory_store):
        result = execute_store_memory(memory_store, "admin", "key", "value")
        assert "error" in result
        assert "Invalid category" in result["error"]
        assert "admin" in result["error"]

    def test_rejects_invalid_category_system(self, memory_store):
        result = execute_store_memory(memory_store, "system", "key", "value")
        assert "error" in result
        assert "Invalid category" in result["error"]

    def test_rejects_invalid_category_empty(self, memory_store):
        result = execute_store_memory(memory_store, "", "key", "value")
        assert "error" in result

    def test_rejects_invalid_category_with_path_traversal(self, memory_store):
        result = execute_store_memory(memory_store, "../etc/passwd", "key", "value")
        assert "error" in result

    def test_accepts_valid_category_work(self, memory_store):
        result = execute_store_memory(memory_store, "work", "project", "chief-of-staff")
        assert result.get("status") == "stored"

    def test_accepts_valid_category_personal(self, memory_store):
        result = execute_store_memory(memory_store, "personal", "name", "Alice")
        assert result.get("status") == "stored"

    def test_accepts_valid_category_preference(self, memory_store):
        result = execute_store_memory(memory_store, "preference", "theme", "dark")
        assert result.get("status") == "stored"

    def test_accepts_valid_category_relationship(self, memory_store):
        result = execute_store_memory(memory_store, "relationship", "manager", "Bob")
        assert result.get("status") == "stored"

    def test_accepts_valid_category_backlog(self, memory_store):
        result = execute_store_memory(memory_store, "backlog", "item", "fix bug")
        assert result.get("status") == "stored"

    def test_all_valid_categories_accepted(self, memory_store):
        """Every category in VALID_FACT_CATEGORIES should be accepted."""
        for cat in VALID_FACT_CATEGORIES:
            result = execute_store_memory(memory_store, cat, f"key_{cat}", "value")
            assert result.get("status") == "stored", f"Category '{cat}' was rejected"

    def test_error_message_lists_valid_categories(self, memory_store):
        """Error message should tell the caller which categories are valid."""
        result = execute_store_memory(memory_store, "bogus", "key", "value")
        for cat in VALID_FACT_CATEGORIES:
            assert cat in result["error"]
