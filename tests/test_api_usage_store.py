# tests/test_api_usage_store.py
"""Tests for ApiUsageStore — the agent_api_log table and query methods."""
import sqlite3
from pathlib import Path

import pytest

from memory.store import MemoryStore


@pytest.fixture
def store(tmp_path):
    db_path = tmp_path / "test.db"
    return MemoryStore(db_path)


class TestLogApiCall:
    def test_insert_and_retrieve(self, store):
        store.log_api_call(
            model_id="claude-sonnet-4-5-20250929",
            input_tokens=100,
            output_tokens=50,
            duration_ms=500,
            agent_name="research",
            caller="base_agent",
        )
        rows = store.get_api_usage_log()
        assert len(rows) == 1
        row = rows[0]
        assert row["model_id"] == "claude-sonnet-4-5-20250929"
        assert row["input_tokens"] == 100
        assert row["output_tokens"] == 50
        assert row["duration_ms"] == 500
        assert row["agent_name"] == "research"
        assert row["caller"] == "base_agent"

    def test_minimal_fields(self, store):
        """Only required fields — defaults should fill the rest."""
        store.log_api_call(
            model_id="claude-haiku-4-5-20251001",
            input_tokens=10,
            output_tokens=5,
        )
        rows = store.get_api_usage_log()
        assert len(rows) == 1
        row = rows[0]
        assert row["cache_creation_input_tokens"] == 0
        assert row["cache_read_input_tokens"] == 0
        assert row["duration_ms"] is None
        assert row["agent_name"] is None
        assert row["caller"] == "unknown"
        assert row["session_id"] is None

    def test_cache_tokens(self, store):
        store.log_api_call(
            model_id="claude-sonnet-4-5-20250929",
            input_tokens=200,
            output_tokens=100,
            cache_creation_input_tokens=50,
            cache_read_input_tokens=150,
        )
        row = store.get_api_usage_log()[0]
        assert row["cache_creation_input_tokens"] == 50
        assert row["cache_read_input_tokens"] == 150

    def test_multiple_inserts(self, store):
        for i in range(5):
            store.log_api_call(
                model_id="claude-haiku-4-5-20251001",
                input_tokens=10 * (i + 1),
                output_tokens=5 * (i + 1),
                caller="base_agent",
            )
        rows = store.get_api_usage_log()
        assert len(rows) == 5


class TestGetApiUsageSummary:
    def test_group_by_model(self, store):
        store.log_api_call(model_id="model-a", input_tokens=100, output_tokens=50, caller="base_agent")
        store.log_api_call(model_id="model-a", input_tokens=200, output_tokens=100, caller="base_agent")
        store.log_api_call(model_id="model-b", input_tokens=50, output_tokens=25, caller="triage")
        rows = store.get_api_usage_summary()
        # model-a has 2 calls, model-b has 1
        model_a = [r for r in rows if r["model_id"] == "model-a"]
        assert len(model_a) == 1
        assert model_a[0]["call_count"] == 2
        assert model_a[0]["total_input_tokens"] == 300
        assert model_a[0]["total_output_tokens"] == 150

    def test_group_by_agent(self, store):
        store.log_api_call(model_id="m", input_tokens=10, output_tokens=5, agent_name="agent-a")
        store.log_api_call(model_id="m", input_tokens=20, output_tokens=10, agent_name="agent-b")
        rows = store.get_api_usage_summary()
        assert len(rows) == 2
        agents = {r["agent_name"] for r in rows}
        assert agents == {"agent-a", "agent-b"}

    def test_filter_by_agent(self, store):
        store.log_api_call(model_id="m", input_tokens=10, output_tokens=5, agent_name="a")
        store.log_api_call(model_id="m", input_tokens=20, output_tokens=10, agent_name="b")
        rows = store.get_api_usage_summary(agent_name="a")
        assert len(rows) == 1
        assert rows[0]["agent_name"] == "a"

    def test_filter_by_model(self, store):
        store.log_api_call(model_id="fast", input_tokens=10, output_tokens=5)
        store.log_api_call(model_id="slow", input_tokens=100, output_tokens=50)
        rows = store.get_api_usage_summary(model="fast")
        assert len(rows) == 1
        assert rows[0]["model_id"] == "fast"

    def test_filter_by_since(self, store):
        store.log_api_call(model_id="m", input_tokens=10, output_tokens=5)
        # Filter with a future date should return nothing
        rows = store.get_api_usage_summary(since="2099-01-01")
        assert len(rows) == 0

    def test_avg_duration(self, store):
        store.log_api_call(model_id="m", input_tokens=10, output_tokens=5, duration_ms=100)
        store.log_api_call(model_id="m", input_tokens=10, output_tokens=5, duration_ms=200)
        rows = store.get_api_usage_summary()
        assert rows[0]["avg_duration_ms"] == 150.0

    def test_empty_table(self, store):
        rows = store.get_api_usage_summary()
        assert rows == []


class TestGetApiUsageLog:
    def test_filter_by_caller(self, store):
        store.log_api_call(model_id="m", input_tokens=10, output_tokens=5, caller="base_agent")
        store.log_api_call(model_id="m", input_tokens=10, output_tokens=5, caller="triage")
        rows = store.get_api_usage_log(caller="triage")
        assert len(rows) == 1
        assert rows[0]["caller"] == "triage"

    def test_filter_by_model(self, store):
        store.log_api_call(model_id="fast", input_tokens=10, output_tokens=5)
        store.log_api_call(model_id="slow", input_tokens=10, output_tokens=5)
        rows = store.get_api_usage_log(model="fast")
        assert len(rows) == 1

    def test_limit(self, store):
        for _ in range(10):
            store.log_api_call(model_id="m", input_tokens=10, output_tokens=5)
        rows = store.get_api_usage_log(limit=3)
        assert len(rows) == 3

    def test_newest_first(self, store):
        store.log_api_call(model_id="m", input_tokens=1, output_tokens=1, caller="first")
        store.log_api_call(model_id="m", input_tokens=2, output_tokens=2, caller="second")
        rows = store.get_api_usage_log()
        # Newest (second) should be first
        assert rows[0]["caller"] == "second"
        assert rows[1]["caller"] == "first"

    def test_combined_filters(self, store):
        store.log_api_call(model_id="m1", input_tokens=10, output_tokens=5, agent_name="a", caller="base_agent")
        store.log_api_call(model_id="m2", input_tokens=10, output_tokens=5, agent_name="a", caller="triage")
        store.log_api_call(model_id="m1", input_tokens=10, output_tokens=5, agent_name="b", caller="base_agent")
        rows = store.get_api_usage_log(model="m1", agent_name="a", caller="base_agent")
        assert len(rows) == 1
