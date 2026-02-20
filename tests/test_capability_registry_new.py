# tests/test_capability_registry_new.py
"""Tests for new capability registry entries: agent_memory, channel, proactive, webhook, scheduler, skill."""

import json

import pytest

from capabilities.registry import (
    CAPABILITY_DEFINITIONS,
    TOOL_SCHEMAS,
    get_capability_names,
    get_tools_for_capabilities,
    validate_capabilities,
)


class TestNewCapabilityDefinitions:
    """Verify all new capabilities are properly defined."""

    @pytest.mark.parametrize("cap_name", [
        "agent_memory_read",
        "agent_memory_write",
        "channel_read",
        "proactive_read",
        "webhook_read",
        "webhook_write",
        "scheduler_read",
        "scheduler_write",
        "skill_read",
        "skill_write",
    ])
    def test_capability_exists(self, cap_name):
        assert cap_name in CAPABILITY_DEFINITIONS
        defn = CAPABILITY_DEFINITIONS[cap_name]
        assert defn.implemented is True
        assert len(defn.tool_names) > 0
        assert defn.description

    @pytest.mark.parametrize("cap_name", [
        "agent_memory_read",
        "agent_memory_write",
        "channel_read",
        "proactive_read",
        "webhook_read",
        "webhook_write",
        "scheduler_read",
        "scheduler_write",
        "skill_read",
        "skill_write",
    ])
    def test_capability_validates(self, cap_name):
        result = validate_capabilities([cap_name])
        assert result == [cap_name]

    @pytest.mark.parametrize("cap_name", [
        "agent_memory_read",
        "agent_memory_write",
        "channel_read",
        "proactive_read",
        "webhook_read",
        "webhook_write",
        "scheduler_read",
        "scheduler_write",
        "skill_read",
        "skill_write",
    ])
    def test_capability_in_names_list(self, cap_name):
        all_names = get_capability_names()
        assert cap_name in all_names


class TestNewToolSchemas:
    """Verify all new tool schemas exist and have required fields."""

    @pytest.mark.parametrize("tool_name", [
        "get_agent_memory",
        "clear_agent_memory",
        "list_inbound_events",
        "get_event_summary",
        "get_proactive_suggestions",
        "dismiss_suggestion",
        "list_webhook_events",
        "get_webhook_event",
        "process_webhook_event",
        "list_scheduled_tasks",
        "get_scheduler_status",
        "create_scheduled_task",
        "update_scheduled_task",
        "delete_scheduled_task",
        "run_scheduled_task",
        "list_skill_suggestions",
        "record_tool_usage",
        "analyze_skill_patterns",
        "auto_create_skill",
    ])
    def test_tool_schema_exists(self, tool_name):
        assert tool_name in TOOL_SCHEMAS
        schema = TOOL_SCHEMAS[tool_name]
        assert schema["name"] == tool_name
        assert "description" in schema
        assert "input_schema" in schema
        assert schema["input_schema"]["type"] == "object"


class TestNewCapabilityToolMappings:
    """Verify each new capability maps to the correct tools."""

    def test_agent_memory_read_tools(self):
        tools = get_tools_for_capabilities(["agent_memory_read"])
        names = {t["name"] for t in tools}
        assert names == {"get_agent_memory"}

    def test_agent_memory_write_tools(self):
        tools = get_tools_for_capabilities(["agent_memory_write"])
        names = {t["name"] for t in tools}
        assert names == {"clear_agent_memory"}

    def test_channel_read_tools(self):
        tools = get_tools_for_capabilities(["channel_read"])
        names = {t["name"] for t in tools}
        assert names == {"list_inbound_events", "get_event_summary"}

    def test_proactive_read_tools(self):
        tools = get_tools_for_capabilities(["proactive_read"])
        names = {t["name"] for t in tools}
        assert names == {"get_proactive_suggestions", "dismiss_suggestion"}

    def test_webhook_read_tools(self):
        tools = get_tools_for_capabilities(["webhook_read"])
        names = {t["name"] for t in tools}
        assert names == {"list_webhook_events", "get_webhook_event"}

    def test_webhook_write_tools(self):
        tools = get_tools_for_capabilities(["webhook_write"])
        names = {t["name"] for t in tools}
        assert names == {"process_webhook_event"}

    def test_scheduler_read_tools(self):
        tools = get_tools_for_capabilities(["scheduler_read"])
        names = {t["name"] for t in tools}
        assert names == {"list_scheduled_tasks", "get_scheduler_status"}

    def test_scheduler_write_tools(self):
        tools = get_tools_for_capabilities(["scheduler_write"])
        names = {t["name"] for t in tools}
        assert names == {"create_scheduled_task", "update_scheduled_task", "delete_scheduled_task", "run_scheduled_task"}

    def test_skill_read_tools(self):
        tools = get_tools_for_capabilities(["skill_read"])
        names = {t["name"] for t in tools}
        assert names == {"list_skill_suggestions"}

    def test_skill_write_tools(self):
        tools = get_tools_for_capabilities(["skill_write"])
        names = {t["name"] for t in tools}
        assert names == {"record_tool_usage", "analyze_skill_patterns", "auto_create_skill"}

    def test_combined_capabilities_no_duplicates(self):
        tools = get_tools_for_capabilities(["scheduler_read", "scheduler_write"])
        names = [t["name"] for t in tools]
        # list_scheduled_tasks appears in both, should only appear once
        assert names.count("list_scheduled_tasks") == 1

    def test_all_new_tool_schemas_referenced(self):
        """Every tool schema for new capabilities should be reachable via at least one capability."""
        new_tool_names = {
            "get_agent_memory", "clear_agent_memory",
            "list_inbound_events", "get_event_summary",
            "get_proactive_suggestions", "dismiss_suggestion",
            "list_webhook_events", "get_webhook_event", "process_webhook_event",
            "list_scheduled_tasks", "get_scheduler_status",
            "create_scheduled_task", "update_scheduled_task", "delete_scheduled_task", "run_scheduled_task",
            "list_skill_suggestions", "record_tool_usage", "analyze_skill_patterns", "auto_create_skill",
        }
        reachable = set()
        for defn in CAPABILITY_DEFINITIONS.values():
            for tn in defn.tool_names:
                if tn in new_tool_names:
                    reachable.add(tn)
        assert reachable == new_tool_names


class TestSchedulerBootstrap:
    """Verify scheduler default task seeding in mcp_server lifespan."""

    def test_get_scheduled_task_by_name(self, tmp_path):
        from memory.store import MemoryStore
        from memory.models import ScheduledTask

        store = MemoryStore(tmp_path / "test.db")
        try:
            # Initially no task
            assert store.get_scheduled_task_by_name("alert_eval") is None

            # Store a task
            task = ScheduledTask(
                name="alert_eval",
                handler_type="alert_eval",
                schedule_type="interval",
                schedule_config='{"hours": 2}',
                next_run_at="2026-01-01T00:00:00",
            )
            store.store_scheduled_task(task)

            # Now it should be found
            found = store.get_scheduled_task_by_name("alert_eval")
            assert found is not None
            assert found.name == "alert_eval"
            assert found.handler_type == "alert_eval"

            # Non-existent name still returns None
            assert store.get_scheduled_task_by_name("nonexistent") is None
        finally:
            store.close()

    def test_bootstrap_seeds_default_tasks(self, tmp_path):
        """Simulate the bootstrap logic and verify tasks are seeded."""
        from memory.store import MemoryStore
        from memory.models import ScheduledTask
        from scheduler.engine import calculate_next_run

        store = MemoryStore(tmp_path / "test.db")
        try:
            default_tasks = [
                ScheduledTask(
                    name="alert_eval",
                    handler_type="alert_eval",
                    schedule_type="interval",
                    schedule_config='{"hours": 2}',
                ),
                ScheduledTask(
                    name="webhook_poll",
                    handler_type="webhook_poll",
                    schedule_type="interval",
                    schedule_config='{"minutes": 5}',
                ),
                ScheduledTask(
                    name="skill_analysis",
                    handler_type="skill_analysis",
                    schedule_type="interval",
                    schedule_config='{"hours": 24}',
                ),
            ]
            for dt in default_tasks:
                if store.get_scheduled_task_by_name(dt.name) is None:
                    dt.next_run_at = calculate_next_run(dt.schedule_type, dt.schedule_config)
                    store.store_scheduled_task(dt)

            tasks = store.list_scheduled_tasks()
            assert len(tasks) == 3
            names = {t.name for t in tasks}
            assert names == {"alert_eval", "webhook_poll", "skill_analysis"}

            for t in tasks:
                assert t.enabled is True
                assert t.next_run_at is not None
        finally:
            store.close()

    def test_bootstrap_idempotent(self, tmp_path):
        """Running bootstrap twice should not duplicate tasks."""
        from memory.store import MemoryStore
        from memory.models import ScheduledTask
        from scheduler.engine import calculate_next_run

        store = MemoryStore(tmp_path / "test.db")
        try:
            default_tasks = [
                ScheduledTask(
                    name="alert_eval",
                    handler_type="alert_eval",
                    schedule_type="interval",
                    schedule_config='{"hours": 2}',
                ),
            ]

            # Run twice
            for _ in range(2):
                for dt in default_tasks:
                    if store.get_scheduled_task_by_name(dt.name) is None:
                        dt.next_run_at = calculate_next_run(dt.schedule_type, dt.schedule_config)
                        store.store_scheduled_task(dt)

            tasks = store.list_scheduled_tasks()
            assert len(tasks) == 1
        finally:
            store.close()

    def test_bootstrap_skips_existing_task(self, tmp_path):
        """If a task already exists, bootstrap should not overwrite it."""
        from memory.store import MemoryStore
        from memory.models import ScheduledTask
        from scheduler.engine import calculate_next_run

        store = MemoryStore(tmp_path / "test.db")
        try:
            # Pre-create a task with custom config
            custom = ScheduledTask(
                name="alert_eval",
                handler_type="alert_eval",
                schedule_type="interval",
                schedule_config='{"hours": 4}',
                description="Custom config",
                next_run_at="2099-01-01T00:00:00",
            )
            store.store_scheduled_task(custom)

            # Bootstrap should skip it
            default = ScheduledTask(
                name="alert_eval",
                handler_type="alert_eval",
                schedule_type="interval",
                schedule_config='{"hours": 2}',
            )
            if store.get_scheduled_task_by_name(default.name) is None:
                default.next_run_at = calculate_next_run(default.schedule_type, default.schedule_config)
                store.store_scheduled_task(default)

            found = store.get_scheduled_task_by_name("alert_eval")
            assert found.schedule_config == '{"hours": 4}'
            assert found.description == "Custom config"
        finally:
            store.close()
