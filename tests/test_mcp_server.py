# tests/test_mcp_server.py
import pytest
from unittest.mock import patch, MagicMock


def test_mcp_server_imports():
    """Verify mcp_server module can be imported."""
    import mcp_server
    assert hasattr(mcp_server, "mcp")
    assert hasattr(mcp_server, "app_lifespan")


def test_mcp_server_has_tools():
    """Verify the MCP server registers the expected tools."""
    import mcp_server
    # FastMCP registers tools internally; check they exist by name
    tool_names = [t.name for t in mcp_server.mcp._tool_manager.list_tools()]
    assert "chief_of_staff_ask" in tool_names
    assert "ingest_documents" in tool_names


def test_mcp_server_has_resources():
    """Verify the MCP server registers the expected resources."""
    import mcp_server
    resource_manager = mcp_server.mcp._resource_manager

    # Concrete resources
    resources = resource_manager.list_resources()
    resource_uris = [str(r.uri) for r in resources]
    assert "memory://facts" in resource_uris
    assert "agents://list" in resource_uris

    # Resource templates
    templates = resource_manager.list_templates()
    template_uris = [str(t.uri_template) for t in templates]
    assert "memory://facts/{category}" in template_uris
