# tests/test_hook_registry.py
"""Tests for the plugin hook / lifecycle system."""

import json
import os
import time

import pytest
import yaml

# Trigger mcp_server registration before importing tool functions
import mcp_server  # noqa: F401

from hooks.registry import HookRegistry, build_tool_context, EVENT_TYPES, extract_transformed_args
from hooks.builtin import audit_log_hook, timing_before_hook, timing_after_hook, _timing_store


# ---------------------------------------------------------------------------
# HookRegistry core
# ---------------------------------------------------------------------------

class TestHookRegistryBasics:
    def test_register_and_fire(self):
        reg = HookRegistry()
        calls = []
        reg.register_hook("before_tool_call", lambda ctx: calls.append(ctx))
        results = reg.fire_hooks("before_tool_call", {"tool_name": "store_fact"})
        assert len(results) == 1
        assert len(calls) == 1
        assert calls[0]["tool_name"] == "store_fact"

    def test_fire_returns_callback_results(self):
        reg = HookRegistry()
        reg.register_hook("after_tool_call", lambda ctx: ctx.get("tool_name"))
        results = reg.fire_hooks("after_tool_call", {"tool_name": "query_memory"})
        assert results == ["query_memory"]

    def test_register_invalid_event_type(self):
        reg = HookRegistry()
        with pytest.raises(ValueError, match="Unknown event type"):
            reg.register_hook("invalid_event", lambda ctx: None)

    def test_fire_invalid_event_type(self):
        reg = HookRegistry()
        with pytest.raises(ValueError, match="Unknown event type"):
            reg.fire_hooks("invalid_event", {})

    def test_no_hooks_returns_empty(self):
        reg = HookRegistry()
        results = reg.fire_hooks("before_tool_call", {"tool_name": "x"})
        assert results == []

    def test_clear(self):
        reg = HookRegistry()
        reg.register_hook("before_tool_call", lambda ctx: "a")
        reg.clear()
        assert reg.fire_hooks("before_tool_call", {}) == []

    def test_all_event_types_supported(self):
        reg = HookRegistry()
        for et in EVENT_TYPES:
            reg.register_hook(et, lambda ctx: "ok")
            results = reg.fire_hooks(et, {})
            assert results == ["ok"]


class TestHookPriority:
    def test_lower_priority_runs_first(self):
        reg = HookRegistry()
        order = []
        reg.register_hook("before_tool_call", lambda ctx: order.append("b"), priority=200)
        reg.register_hook("before_tool_call", lambda ctx: order.append("a"), priority=50)
        reg.fire_hooks("before_tool_call", {})
        assert order == ["a", "b"]

    def test_same_priority_preserves_insertion_order(self):
        reg = HookRegistry()
        order = []
        reg.register_hook("before_tool_call", lambda ctx: order.append("first"), priority=100)
        reg.register_hook("before_tool_call", lambda ctx: order.append("second"), priority=100)
        reg.fire_hooks("before_tool_call", {})
        assert order == ["first", "second"]


class TestHookEnabled:
    def test_disabled_hook_not_fired(self):
        reg = HookRegistry()
        reg.register_hook("before_tool_call", lambda ctx: "should_not_run", enabled=False)
        results = reg.fire_hooks("before_tool_call", {})
        assert results == []

    def test_enabled_hook_fires(self):
        reg = HookRegistry()
        reg.register_hook("before_tool_call", lambda ctx: "runs", enabled=True)
        results = reg.fire_hooks("before_tool_call", {})
        assert results == ["runs"]

    def test_toggle_enabled_at_runtime(self):
        reg = HookRegistry()
        reg.register_hook("before_tool_call", lambda ctx: "val", name="toggler", enabled=False)
        assert reg.fire_hooks("before_tool_call", {}) == []
        # Enable at runtime
        for h in reg.get_hooks("before_tool_call"):
            if h["name"] == "toggler":
                h["enabled"] = True
        assert reg.fire_hooks("before_tool_call", {}) == ["val"]


class TestHookErrorIsolation:
    def test_failing_hook_does_not_break_others(self):
        reg = HookRegistry()
        reg.register_hook("before_tool_call", lambda ctx: 1 / 0, priority=10, name="bad")
        reg.register_hook("before_tool_call", lambda ctx: "ok", priority=20, name="good")
        results = reg.fire_hooks("before_tool_call", {})
        assert len(results) == 2
        assert results[0] is None  # failed hook
        assert results[1] == "ok"

    def test_failing_hook_logged(self, caplog):
        reg = HookRegistry()
        reg.register_hook("before_tool_call", lambda ctx: 1 / 0, name="divzero")
        with caplog.at_level("ERROR", logger="jarvis-mcp.hooks"):
            reg.fire_hooks("before_tool_call", {})
        assert "divzero" in caplog.text

    def test_context_copy_isolation(self):
        """Each hook receives its own copy; mutations don't leak."""
        reg = HookRegistry()

        def mutator(ctx):
            ctx["extra"] = "added"
            return ctx

        def reader(ctx):
            return ctx.get("extra")

        reg.register_hook("before_tool_call", mutator, priority=1)
        reg.register_hook("before_tool_call", reader, priority=2)
        results = reg.fire_hooks("before_tool_call", {"tool_name": "test"})
        assert results[0]["extra"] == "added"
        assert results[1] is None  # reader didn't see the mutation


class TestGetHooks:
    def test_get_hooks_returns_list(self):
        reg = HookRegistry()
        reg.register_hook("session_start", lambda ctx: None, name="h1")
        hooks = reg.get_hooks("session_start")
        assert len(hooks) == 1
        assert hooks[0]["name"] == "h1"

    def test_get_hooks_invalid_event(self):
        reg = HookRegistry()
        with pytest.raises(ValueError):
            reg.get_hooks("bad_event")


# ---------------------------------------------------------------------------
# YAML config loading
# ---------------------------------------------------------------------------

class TestYAMLConfigLoading:
    def test_load_builtin_config(self, tmp_path):
        config_dir = tmp_path / "configs"
        config_dir.mkdir()
        config = [
            {
                "event_type": "before_tool_call",
                "name": "audit_before",
                "handler": "hooks.builtin.audit_log_hook",
                "priority": 10,
                "enabled": True,
            }
        ]
        (config_dir / "test.yaml").write_text(yaml.dump(config))

        reg = HookRegistry()
        loaded = reg.load_configs(config_dir)
        assert loaded == 1
        hooks = reg.get_hooks("before_tool_call")
        assert len(hooks) == 1
        assert hooks[0]["name"] == "audit_before"
        assert hooks[0]["priority"] == 10

    def test_load_multiple_configs(self, tmp_path):
        config_dir = tmp_path / "configs"
        config_dir.mkdir()
        config = [
            {"event_type": "before_tool_call", "name": "h1", "handler": "hooks.builtin.audit_log_hook"},
            {"event_type": "after_tool_call", "name": "h2", "handler": "hooks.builtin.audit_log_hook"},
        ]
        (config_dir / "multi.yaml").write_text(yaml.dump(config))

        reg = HookRegistry()
        loaded = reg.load_configs(config_dir)
        assert loaded == 2

    def test_load_missing_directory(self, tmp_path):
        reg = HookRegistry()
        loaded = reg.load_configs(tmp_path / "nonexistent")
        assert loaded == 0

    def test_load_skips_invalid_entries(self, tmp_path):
        config_dir = tmp_path / "configs"
        config_dir.mkdir()
        config = [
            {"event_type": "before_tool_call"},  # missing handler
            {"handler": "hooks.builtin.audit_log_hook"},  # missing event_type
            {"event_type": "before_tool_call", "handler": "no.such.module.func"},  # bad import
        ]
        (config_dir / "bad.yaml").write_text(yaml.dump(config))

        reg = HookRegistry()
        loaded = reg.load_configs(config_dir)
        assert loaded == 0

    def test_load_non_list_yaml(self, tmp_path):
        config_dir = tmp_path / "configs"
        config_dir.mkdir()
        (config_dir / "notlist.yaml").write_text("key: value\n")

        reg = HookRegistry()
        loaded = reg.load_configs(config_dir)
        assert loaded == 0

    def test_load_disabled_hooks(self, tmp_path):
        config_dir = tmp_path / "configs"
        config_dir.mkdir()
        config = [
            {
                "event_type": "before_tool_call",
                "name": "disabled_hook",
                "handler": "hooks.builtin.audit_log_hook",
                "enabled": False,
            }
        ]
        (config_dir / "disabled.yaml").write_text(yaml.dump(config))

        reg = HookRegistry()
        loaded = reg.load_configs(config_dir)
        assert loaded == 1
        hooks = reg.get_hooks("before_tool_call")
        assert hooks[0]["enabled"] is False
        assert reg.fire_hooks("before_tool_call", {}) == []


# ---------------------------------------------------------------------------
# build_tool_context helper
# ---------------------------------------------------------------------------

class TestBuildToolContext:
    def test_before_context(self):
        ctx = build_tool_context(tool_name="store_fact", tool_args={"key": "v"})
        assert ctx["tool_name"] == "store_fact"
        assert ctx["tool_args"] == {"key": "v"}
        assert ctx["agent_name"] == ""
        assert "timestamp" in ctx
        assert "result" not in ctx

    def test_after_context(self):
        ctx = build_tool_context(
            tool_name="query_memory",
            tool_args={"query": "test"},
            agent_name="researcher",
            result={"results": []},
        )
        assert ctx["agent_name"] == "researcher"
        assert ctx["result"] == {"results": []}

    def test_timestamp_is_iso_utc(self):
        ctx = build_tool_context(tool_name="x", tool_args={})
        # Should parse as ISO 8601 with UTC offset
        assert "+00:00" in ctx["timestamp"] or "Z" in ctx["timestamp"]


# ---------------------------------------------------------------------------
# Arg transformation via before_tool_call hooks
# ---------------------------------------------------------------------------

class TestArgTransformation:
    """Tests for before_tool_call hooks that modify tool_args."""

    def test_before_hook_can_modify_args(self):
        reg = HookRegistry()

        def uppercase_body(ctx):
            args = ctx.get("tool_args", {})
            if "body" in args:
                args["body"] = args["body"].upper()
            return {"tool_args": args}

        reg.register_hook("before_tool_call", uppercase_body)
        context = {"tool_name": "send_email", "tool_args": {"body": "hello"}}
        results = reg.fire_hooks("before_tool_call", context)
        assert results[0]["tool_args"]["body"] == "HELLO"

    def test_before_hook_returning_none_is_noop(self):
        reg = HookRegistry()
        reg.register_hook("before_tool_call", lambda ctx: None)
        context = {"tool_name": "send_email", "tool_args": {"body": "hello"}}
        results = reg.fire_hooks("before_tool_call", context)
        assert results == [None]

    def test_extract_transformed_args_helper(self):
        reg = HookRegistry()

        def rewriter(ctx):
            args = dict(ctx.get("tool_args", {}))
            args["body"] = "rewritten"
            return {"tool_args": args}

        reg.register_hook("before_tool_call", rewriter)
        context = {"tool_name": "send_email", "tool_args": {"body": "original"}}
        results = reg.fire_hooks("before_tool_call", context)
        transformed = extract_transformed_args(results)
        assert transformed is not None
        assert transformed["body"] == "rewritten"

    def test_extract_transformed_args_no_transforms(self):
        reg = HookRegistry()
        reg.register_hook("before_tool_call", lambda ctx: None)
        results = reg.fire_hooks("before_tool_call", {"tool_args": {"body": "hi"}})
        transformed = extract_transformed_args(results)
        assert transformed is None

    def test_after_hook_return_not_treated_as_transform(self):
        """after_tool_call hooks should not transform args."""
        reg = HookRegistry()
        reg.register_hook("after_tool_call", lambda ctx: {"tool_args": {"body": "bad"}})
        results = reg.fire_hooks("after_tool_call", {"tool_args": {"body": "ok"}})
        # Returns are just informational, not transforms
        assert results[0]["tool_args"]["body"] == "bad"


# ---------------------------------------------------------------------------
# Built-in hooks
# ---------------------------------------------------------------------------

class TestAuditLogHook:
    def test_before_writes_jsonl(self, tmp_path, monkeypatch):
        log_path = tmp_path / "audit.jsonl"
        monkeypatch.setattr("hooks.builtin.AUDIT_LOG_PATH", log_path)

        ctx = build_tool_context(tool_name="store_fact", tool_args={"key": "name", "value": "Jason"})
        result = audit_log_hook(ctx)

        assert result["event"] == "before_tool_call"
        assert result["tool_name"] == "store_fact"

        lines = log_path.read_text().strip().split("\n")
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["tool_name"] == "store_fact"
        assert entry["tool_args"]["key"] == "name"

    def test_after_writes_jsonl(self, tmp_path, monkeypatch):
        log_path = tmp_path / "audit.jsonl"
        monkeypatch.setattr("hooks.builtin.AUDIT_LOG_PATH", log_path)

        ctx = build_tool_context(
            tool_name="query_memory",
            tool_args={"query": "test"},
            result={"results": [{"key": "name"}]},
        )
        result = audit_log_hook(ctx)

        assert result["event"] == "after_tool_call"
        lines = log_path.read_text().strip().split("\n")
        entry = json.loads(lines[0])
        assert "result_preview" in entry
        assert "tool_args" not in entry

    def test_result_truncation(self, tmp_path, monkeypatch):
        log_path = tmp_path / "audit.jsonl"
        monkeypatch.setattr("hooks.builtin.AUDIT_LOG_PATH", log_path)

        ctx = build_tool_context(
            tool_name="query_memory",
            tool_args={},
            result="x" * 1000,
        )
        audit_log_hook(ctx)

        entry = json.loads(log_path.read_text().strip())
        assert entry["result_preview"].endswith("...[truncated]")
        assert len(entry["result_preview"]) < 600

    def test_creates_parent_dirs(self, tmp_path, monkeypatch):
        log_path = tmp_path / "sub" / "dir" / "audit.jsonl"
        monkeypatch.setattr("hooks.builtin.AUDIT_LOG_PATH", log_path)

        ctx = build_tool_context(tool_name="x", tool_args={})
        audit_log_hook(ctx)
        assert log_path.exists()


class TestTimingHooks:
    def test_timing_roundtrip(self):
        _timing_store.clear()
        ts = "2026-01-01T00:00:00+00:00"
        before_ctx = {"timestamp": ts, "tool_name": "store_fact"}
        timing_before_hook(before_ctx)
        assert ts in _timing_store

        # Simulate some elapsed time
        time.sleep(0.01)

        after_ctx = {"timestamp": ts, "tool_name": "store_fact"}
        result = timing_after_hook(after_ctx)
        assert result is not None
        assert result["tool_name"] == "store_fact"
        assert result["elapsed_seconds"] >= 0.0
        assert ts not in _timing_store  # cleaned up

    def test_timing_after_without_before(self):
        _timing_store.clear()
        result = timing_after_hook({"timestamp": "no-match", "tool_name": "x"})
        assert result is None


# ---------------------------------------------------------------------------
# Integration: agent base.py hook firing
# ---------------------------------------------------------------------------

class TestAgentHookIntegration:
    def test_handle_tool_call_fires_hooks(self, tmp_path):
        from agents.base import BaseExpertAgent
        from agents.registry import AgentConfig
        from memory.store import MemoryStore
        from documents.store import DocumentStore

        memory_store = MemoryStore(tmp_path / "test.db")
        doc_store = DocumentStore(persist_dir=tmp_path / "chroma")

        config = AgentConfig(
            name="test-agent",
            description="test",
            system_prompt="You are a test agent.",
            capabilities=["memory_read"],
            max_tokens=1024,
        )

        hook_reg = HookRegistry()
        before_calls = []
        after_calls = []
        hook_reg.register_hook("before_tool_call", lambda ctx: before_calls.append(ctx))
        hook_reg.register_hook("after_tool_call", lambda ctx: after_calls.append(ctx))

        agent = BaseExpertAgent(
            config=config,
            memory_store=memory_store,
            document_store=doc_store,
            hook_registry=hook_reg,
        )

        result = agent._handle_tool_call("query_memory", {"query": "test"})

        assert len(before_calls) == 1
        assert before_calls[0]["tool_name"] == "query_memory"
        assert before_calls[0]["agent_name"] == "test-agent"
        assert "timestamp" in before_calls[0]

        assert len(after_calls) == 1
        assert after_calls[0]["tool_name"] == "query_memory"
        assert "result" in after_calls[0]
        # Timestamps match for timing correlation
        assert after_calls[0]["timestamp"] == before_calls[0]["timestamp"]

        memory_store.close()

    def test_hooks_fire_on_denied_tool(self, tmp_path):
        from agents.base import BaseExpertAgent
        from agents.registry import AgentConfig
        from memory.store import MemoryStore
        from documents.store import DocumentStore

        memory_store = MemoryStore(tmp_path / "test.db")
        doc_store = DocumentStore(persist_dir=tmp_path / "chroma")

        config = AgentConfig(
            name="test-agent",
            description="test",
            system_prompt="You are a test agent.",
            capabilities=[],  # no capabilities
            max_tokens=1024,
        )

        hook_reg = HookRegistry()
        after_calls = []
        hook_reg.register_hook("after_tool_call", lambda ctx: after_calls.append(ctx))

        agent = BaseExpertAgent(
            config=config,
            memory_store=memory_store,
            document_store=doc_store,
            hook_registry=hook_reg,
        )

        result = agent._handle_tool_call("query_memory", {"query": "test"})
        assert "error" in result
        assert "not permitted" in result["error"]

        # after_tool_call still fires for denied tools
        assert len(after_calls) == 1
        assert "error" in after_calls[0]["result"]

        memory_store.close()

    def test_no_hook_registry_is_safe(self, tmp_path):
        """Agent with no hook_registry should work without errors."""
        from agents.base import BaseExpertAgent
        from agents.registry import AgentConfig
        from memory.store import MemoryStore
        from documents.store import DocumentStore

        memory_store = MemoryStore(tmp_path / "test.db")
        doc_store = DocumentStore(persist_dir=tmp_path / "chroma")

        config = AgentConfig(
            name="test-agent",
            description="test",
            system_prompt="Test",
            capabilities=["memory_read"],
            max_tokens=1024,
        )

        agent = BaseExpertAgent(
            config=config,
            memory_store=memory_store,
            document_store=doc_store,
            # hook_registry not passed — defaults to None
        )

        result = agent._handle_tool_call("query_memory", {"query": "test"})
        # Should work fine without hooks
        assert isinstance(result, (dict, list))

        memory_store.close()

    def test_hook_failure_does_not_break_tool_call(self, tmp_path):
        """A failing hook must not prevent the tool from executing."""
        from agents.base import BaseExpertAgent
        from agents.registry import AgentConfig
        from memory.store import MemoryStore
        from documents.store import DocumentStore

        memory_store = MemoryStore(tmp_path / "test.db")
        doc_store = DocumentStore(persist_dir=tmp_path / "chroma")

        config = AgentConfig(
            name="test-agent",
            description="test",
            system_prompt="Test",
            capabilities=["memory_read"],
            max_tokens=1024,
        )

        hook_reg = HookRegistry()
        hook_reg.register_hook("before_tool_call", lambda ctx: 1 / 0, name="crasher")

        agent = BaseExpertAgent(
            config=config,
            memory_store=memory_store,
            document_store=doc_store,
            hook_registry=hook_reg,
        )

        # Tool should still execute despite hook failure
        result = agent._handle_tool_call("query_memory", {"query": "test"})
        assert isinstance(result, (dict, list))

        memory_store.close()


# ---------------------------------------------------------------------------
# ServerState integration
# ---------------------------------------------------------------------------

class TestServerStateHookRegistry:
    def test_hook_registry_on_state(self):
        from mcp_tools.state import ServerState

        state = ServerState()
        assert state.hook_registry is None

        reg = HookRegistry()
        state.hook_registry = reg
        assert state.hook_registry is reg

        state.clear()
        assert state.hook_registry is None

    def test_dict_style_access(self):
        from mcp_tools.state import ServerState

        state = ServerState()
        reg = HookRegistry()
        state["hook_registry"] = reg
        assert state["hook_registry"] is reg
