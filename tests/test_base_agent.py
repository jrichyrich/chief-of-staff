# tests/test_base_agent.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from agents.base import BaseExpertAgent, MAX_TOOL_ROUNDS
from agents.registry import AgentConfig
from memory.store import MemoryStore
from documents.store import DocumentStore


@pytest.fixture
def agent_config():
    return AgentConfig(
        name="test_agent",
        description="A test agent",
        system_prompt="You are a test agent. Be helpful.",
        capabilities=["memory_read", "document_search"],
        temperature=0.3,
        max_tokens=4096,
    )


@pytest.fixture
def memory_store(tmp_path):
    store = MemoryStore(tmp_path / "test.db")
    yield store
    store.close()


@pytest.fixture
def doc_store(tmp_path):
    return DocumentStore(persist_dir=tmp_path / "chroma")


class TestBaseExpertAgent:
    def test_agent_creation(self, agent_config, memory_store, doc_store):
        agent = BaseExpertAgent(
            config=agent_config,
            memory_store=memory_store,
            document_store=doc_store,
        )
        assert agent.name == "test_agent"
        assert agent.config.temperature == 0.3

    def test_agent_builds_system_prompt(self, agent_config, memory_store, doc_store):
        agent = BaseExpertAgent(
            config=agent_config,
            memory_store=memory_store,
            document_store=doc_store,
        )
        system = agent.build_system_prompt()
        assert "You are a test agent" in system

    def test_agent_gets_tools_from_capabilities(self, agent_config, memory_store, doc_store):
        agent = BaseExpertAgent(
            config=agent_config,
            memory_store=memory_store,
            document_store=doc_store,
        )
        tools = agent.get_tools()
        tool_names = [t["name"] for t in tools]
        assert "query_memory" in tool_names
        assert "search_documents" in tool_names
        # memory_write not in capabilities, so store_memory should not be present
        assert "store_memory" not in tool_names

    @pytest.mark.asyncio
    async def test_agent_execute_calls_api(self, agent_config, memory_store, doc_store):
        agent = BaseExpertAgent(
            config=agent_config,
            memory_store=memory_store,
            document_store=doc_store,
        )
        mock_response = MagicMock()
        mock_response.content = [MagicMock(type="text", text="Test response")]
        mock_response.stop_reason = "end_turn"

        with patch.object(agent, "_call_api", new_callable=AsyncMock, return_value=mock_response):
            result = await agent.execute("Hello, test agent")
            assert result == "Test response"

    @pytest.mark.asyncio
    async def test_agent_respects_max_tool_rounds(self, agent_config, memory_store, doc_store):
        """Agent should stop after MAX_TOOL_ROUNDS to prevent infinite loops."""
        agent = BaseExpertAgent(
            config=agent_config,
            memory_store=memory_store,
            document_store=doc_store,
        )
        # Response that always requests another tool call
        mock_tool_block = MagicMock(type="tool_use", name="query_memory", id="test_id")
        mock_tool_block.input = {"query": "test"}
        mock_response = MagicMock()
        mock_response.content = [mock_tool_block]
        mock_response.stop_reason = "tool_use"

        with patch.object(agent, "_call_api", new_callable=AsyncMock, return_value=mock_response):
            result = await agent.execute("Loop forever")
            assert "maximum tool rounds" in result.lower()

    def test_uses_async_client(self, agent_config, memory_store, doc_store):
        """Agent should use AsyncAnthropic for true async execution."""
        import anthropic
        agent = BaseExpertAgent(
            config=agent_config,
            memory_store=memory_store,
            document_store=doc_store,
        )
        assert isinstance(agent.client, anthropic.AsyncAnthropic)


class TestCalendarCapability:
    """Tests for the calendar_read capability in BaseExpertAgent."""

    @pytest.fixture
    def calendar_config(self):
        return AgentConfig(
            name="briefing_agent",
            description="Agent with calendar access",
            system_prompt="You are a briefing agent.",
            capabilities=["memory_read", "calendar_read"],
        )

    @pytest.fixture
    def calendar_store(self):
        store = MagicMock()
        store.get_events.return_value = [
            {"title": "Standup", "start": "2025-02-14T09:00:00", "end": "2025-02-14T09:30:00"},
            {"title": "1:1 with Boss", "start": "2025-02-14T10:00:00", "end": "2025-02-14T10:30:00"},
        ]
        store.search_events.return_value = [
            {"title": "RBAC Review", "start": "2025-02-14T14:00:00", "end": "2025-02-14T15:00:00"},
        ]
        return store

    def test_calendar_read_provides_tools(self, calendar_config, memory_store, doc_store, calendar_store):
        agent = BaseExpertAgent(
            config=calendar_config,
            memory_store=memory_store,
            document_store=doc_store,
            calendar_store=calendar_store,
        )
        tools = agent.get_tools()
        tool_names = [t["name"] for t in tools]
        assert "get_calendar_events" in tool_names
        assert "search_calendar_events" in tool_names
        assert "query_memory" in tool_names

    def test_calendar_read_tool_schemas(self, calendar_config, memory_store, doc_store, calendar_store):
        agent = BaseExpertAgent(
            config=calendar_config,
            memory_store=memory_store,
            document_store=doc_store,
            calendar_store=calendar_store,
        )
        tools = agent.get_tools()
        get_events = next(t for t in tools if t["name"] == "get_calendar_events")
        assert "start_date" in get_events["input_schema"]["properties"]
        assert "end_date" in get_events["input_schema"]["properties"]
        assert set(get_events["input_schema"]["required"]) == {"start_date", "end_date"}

        search = next(t for t in tools if t["name"] == "search_calendar_events")
        assert "query" in search["input_schema"]["properties"]
        assert search["input_schema"]["required"] == ["query"]

    def test_no_calendar_tools_without_capability(self, agent_config, memory_store, doc_store, calendar_store):
        """Agent without calendar_read should not get calendar tools."""
        agent = BaseExpertAgent(
            config=agent_config,
            memory_store=memory_store,
            document_store=doc_store,
            calendar_store=calendar_store,
        )
        tool_names = [t["name"] for t in agent.get_tools()]
        assert "get_calendar_events" not in tool_names
        assert "search_calendar_events" not in tool_names

    def test_handle_get_calendar_events(self, calendar_config, memory_store, doc_store, calendar_store):
        agent = BaseExpertAgent(
            config=calendar_config,
            memory_store=memory_store,
            document_store=doc_store,
            calendar_store=calendar_store,
        )
        result = agent._handle_tool_call("get_calendar_events", {
            "start_date": "2025-02-14",
            "end_date": "2025-02-15",
        })
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["title"] == "Standup"
        calendar_store.get_events.assert_called_once()

    def test_handle_get_calendar_events_with_calendar_filter(self, calendar_config, memory_store, doc_store, calendar_store):
        agent = BaseExpertAgent(
            config=calendar_config,
            memory_store=memory_store,
            document_store=doc_store,
            calendar_store=calendar_store,
        )
        agent._handle_tool_call("get_calendar_events", {
            "start_date": "2025-02-14",
            "end_date": "2025-02-15",
            "calendar_name": "Work",
        })
        args = calendar_store.get_events.call_args
        assert args[0][2] == ["Work"]  # calendar_names parameter

    def test_handle_search_calendar_events(self, calendar_config, memory_store, doc_store, calendar_store):
        agent = BaseExpertAgent(
            config=calendar_config,
            memory_store=memory_store,
            document_store=doc_store,
            calendar_store=calendar_store,
        )
        result = agent._handle_tool_call("search_calendar_events", {
            "query": "RBAC",
        })
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["title"] == "RBAC Review"
        calendar_store.search_events.assert_called_once()

    def test_handle_search_with_date_range(self, calendar_config, memory_store, doc_store, calendar_store):
        agent = BaseExpertAgent(
            config=calendar_config,
            memory_store=memory_store,
            document_store=doc_store,
            calendar_store=calendar_store,
        )
        agent._handle_tool_call("search_calendar_events", {
            "query": "RBAC",
            "start_date": "2025-02-10",
            "end_date": "2025-02-20",
        })
        args = calendar_store.search_events.call_args
        assert args[0][0] == "RBAC"

    def test_calendar_tools_error_without_store(self, calendar_config, memory_store, doc_store):
        """Calendar tools should return error when no calendar_store is provided."""
        agent = BaseExpertAgent(
            config=calendar_config,
            memory_store=memory_store,
            document_store=doc_store,
            calendar_store=None,
        )
        result = agent._handle_tool_call("get_calendar_events", {
            "start_date": "2025-02-14",
            "end_date": "2025-02-15",
        })
        assert "error" in result
        assert "Calendar not available" in result["error"]

        result = agent._handle_tool_call("search_calendar_events", {"query": "test"})
        assert "error" in result
        assert "Calendar not available" in result["error"]

    @pytest.mark.asyncio
    async def test_agent_execute_with_calendar_tool(self, calendar_config, memory_store, doc_store, calendar_store):
        """Full execute loop: agent calls get_calendar_events then produces text."""
        agent = BaseExpertAgent(
            config=calendar_config,
            memory_store=memory_store,
            document_store=doc_store,
            calendar_store=calendar_store,
        )

        # First API call returns tool_use, second returns text
        # Note: MagicMock(name=...) sets internal _mock_name, not a .name attribute.
        # Must set .name separately so block.name returns the string.
        tool_block = MagicMock(type="tool_use", id="cal_1")
        tool_block.name = "get_calendar_events"
        tool_block.input = {"start_date": "2025-02-14", "end_date": "2025-02-15"}
        tool_response = MagicMock(stop_reason="tool_use", content=[tool_block])

        text_response = MagicMock(
            stop_reason="end_turn",
            content=[MagicMock(type="text", text="You have 2 meetings today.")],
        )

        with patch.object(agent, "_call_api", new_callable=AsyncMock, side_effect=[tool_response, text_response]):
            result = await agent.execute("What's on my calendar today?")
            assert result == "You have 2 meetings today."
            calendar_store.get_events.assert_called_once()
