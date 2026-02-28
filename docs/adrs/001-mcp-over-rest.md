# ADR-001: MCP over REST API for Claude Integration

## Status

Accepted (2026-02-12)

## Context

Jarvis needs to expose tools to Claude Code and Claude Desktop. Two integration approaches were considered:

1. **REST API** -- HTTP server with endpoint-per-tool, requiring custom client code in Claude configurations
2. **Model Context Protocol (MCP)** -- Anthropic's standardized protocol for tool exposure via stdio JSON-RPC

## Decision

We chose MCP with stdio transport as the primary integration mechanism.

The server is implemented using the `mcp` Python SDK's `FastMCP` class, which handles JSON-RPC framing, tool registration, and resource exposure over stdin/stdout.

## Consequences

**Benefits:**
- Native integration with Claude Code and Claude Desktop without custom client code
- Tools automatically appear in the host Claude's tool palette
- stdio transport eliminates network configuration, TLS, and authentication concerns
- MCP resources provide read-only views (facts, agents, session brain)
- The DXT packaging format (`mcpb pack`) enables one-click Claude Desktop installation

**Tradeoffs:**
- The server is single-process, single-connection (one Claude session at a time per server instance)
- All logging must go to stderr (stdout is the JSON-RPC channel)
- No HTTP endpoints for external webhook receipt (solved by file-drop inbox pattern instead)
- Testing requires importing `mcp_server` to trigger registration before importing tool functions

## Related

- `mcp_server.py` -- Entry point
- `manifest.json` -- DXT package manifest
- `pyproject.toml` -- `jarvis-mcp` console script entry point
