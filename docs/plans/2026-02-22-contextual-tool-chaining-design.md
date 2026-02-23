# Contextual Tool Chaining (Person Enrichment) — Design

**Date**: 2026-02-22
**Status**: Approved
**Backlog**: jarvis_backlog_016_contextual_tool_chaining

## Problem

When a user asks about a person, Claude must make 5-6 sequential tool calls to build a complete picture: identity resolution, memory facts, delegations, decisions, iMessage history, email search. Each round-trip adds latency. The data sources are independent and could be fetched in parallel.

## Design

### New MCP Tool: `enrich_person`

A single tool in `mcp_tools/enrichment.py` that takes a person's name and returns a consolidated profile. Fetches from 6 data sources in parallel using `asyncio.gather`. Each source is error-isolated.

### Input

```python
enrich_person(name: str, days_back: int = 7)
```

- `name`: Person's canonical name or search query
- `days_back`: How far back to search communications (default 7 days)

### Data Sources

| Section | Source | Method | Cap |
|---------|--------|--------|-----|
| `identities` | MemoryStore | `search_identity(name)` | 10 |
| `facts` | MemoryStore | `query_memory(name)` via `rank_facts` | 10 |
| `delegations` | MemoryStore | `list_delegations(delegated_to=name)` | 10 |
| `decisions` | MemoryStore | `search_decisions(name)` | 10 |
| `recent_messages` | iMessage | `search(name, minutes=days_back*1440)` | 10 |
| `recent_emails` | Mail | `search_messages(name, limit=10)` | 10 |

All fetched in parallel via `asyncio.gather`. Each wrapped in try/except — failures produce empty results, never break the tool.

### Response Schema

```json
{
  "name": "Jane Smith",
  "identities": [{"provider": "...", "provider_id": "...", "email": "..."}],
  "facts": [{"category": "...", "key": "...", "value": "..."}],
  "delegations": [{"task": "...", "due_date": "...", "priority": "..."}],
  "decisions": [{"title": "...", "status": "...", "created_at": "..."}],
  "recent_messages": [{"sender": "...", "text": "...", "date": "..."}],
  "recent_emails": [{"subject": "...", "from": "...", "date": "..."}]
}
```

Empty sections omitted.

### Error Handling

Each data source independently try/excepted. If iMessage or Mail is unavailable (non-macOS), that section is silently skipped. The tool never fails entirely.

### Registration

`mcp_server.py` imports and registers the new module alongside existing tool modules.

### Exclusions

- No calendar enrichment (requires date range, slow via unified provider)
- No meeting or project enrichment (future backlog items)
- No caching layer
- No changes to existing tools

## Files Modified

| File | Change |
|------|--------|
| `mcp_tools/enrichment.py` | New module: `enrich_person` tool |
| `mcp_server.py` | Register enrichment module |
| `tests/test_enrichment.py` | Tests for person enrichment |
