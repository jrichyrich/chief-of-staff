# tests/conftest.py
"""Shared test fixtures — imported automatically by pytest from every test module."""

import pytest

from memory.store import MemoryStore
from documents.store import DocumentStore
from agents.registry import AgentRegistry


@pytest.fixture(scope="session", autouse=True)
def mcp_server_registered():
    """Trigger mcp_server.register() calls once per session."""
    import mcp_server  # noqa: F401


@pytest.fixture
def memory_store(tmp_path):
    store = MemoryStore(tmp_path / "test.db")
    yield store
    store.close()


@pytest.fixture
def document_store(tmp_path):
    return DocumentStore(str(tmp_path / "chroma"))


@pytest.fixture
def agent_registry(tmp_path):
    configs_dir = tmp_path / "configs"
    configs_dir.mkdir()
    return AgentRegistry(configs_dir)


@pytest.fixture
def inbox_dir(tmp_path):
    d = tmp_path / "inbox"
    d.mkdir()
    return d
