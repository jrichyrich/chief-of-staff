# Calendar Subsystem — Intent Map

## Overview
Dual-provider calendar facade (~3,400 LOC across 9 source files) routing calendar operations across Apple EventKit and Microsoft 365 (via Claude CLI bridge). Provides CRUD, search, availability analysis, and event ownership tracking.

---

### Chunk: mcp-tool-layer
- **Purpose**: Expose calendar operations as MCP tools for Claude Code/Desktop
- **Files**: `mcp_tools/calendar_tools.py` (495 lines)
- **Key functions**: `register()`, `list_calendars`, `get_calendar_events`, `create_calendar_event`, `update_calendar_event`, `delete_calendar_event`, `search_calendar_events`, `find_my_open_slots`, `find_group_availability`
- **Inputs**: MCP tool call parameters (dates, calendar names, provider preferences)
- **Outputs**: JSON strings with results/errors
- **Depends on**: Unified Calendar Service, Availability Engine, config
- **Risk level**: Medium

### Chunk: unified-calendar-service
- **Purpose**: Dual-provider facade with event ownership tracking and deduplication
- **Files**: `connectors/calendar_unified.py` (567 lines)
- **Key functions**: `UnifiedCalendarService`, `_read_from_providers`, `_resolve_write_provider`, `_dedupe_events`, `_upsert_ownership`, `_lookup_ownership`
- **Depends on**: Provider Router, Provider implementations, SQLite
- **Risk level**: High

### Chunk: provider-router
- **Purpose**: Policy-based provider selection for reads and writes
- **Files**: `connectors/router.py` (140 lines), `connectors/provider_base.py` (65 lines)
- **Key functions**: `ProviderRouter`, `RouteDecision`, `CalendarProvider` (ABC), `normalize_provider_name`
- **Risk level**: High

### Chunk: apple-calendar-backend
- **Purpose**: macOS EventKit calendar CRUD via PyObjC
- **Files**: `apple_calendar/eventkit.py` (422 lines), `connectors/providers/apple_provider.py` (128 lines)
- **Key functions**: `CalendarStore`, `AppleCalendarProvider`, `_event_to_dict`, `_find_event_by_uid`
- **Risk level**: Medium

### Chunk: m365-bridge
- **Purpose**: Microsoft 365 calendar access via Claude CLI subprocess with structured output
- **Files**: `connectors/claude_m365_bridge.py` (412 lines), `connectors/providers/m365_provider.py` (204 lines)
- **Key functions**: `ClaudeM365Bridge`, `Microsoft365CalendarProvider`, `_invoke_structured`, `_sanitize_for_prompt`
- **Risk level**: High

### Chunk: availability-engine
- **Purpose**: Find open calendar slots by analyzing events, classifying soft/hard blocks
- **Files**: `scheduler/availability.py` (523 lines)
- **Key functions**: `find_available_slots`, `normalize_event_for_scheduler`, `classify_event_softness`, `format_slots_for_sharing`
- **Risk level**: Medium

## Feature Map

| Feature | Chunks | Risk |
|---------|--------|------|
| List calendars | mcp-tool-layer, unified-calendar-service, provider-router, apple-backend, m365-bridge | Medium |
| Get/search events | mcp-tool-layer, unified-calendar-service, provider-router, apple-backend, m365-bridge | High |
| Create/update/delete events | mcp-tool-layer, unified-calendar-service, provider-router, apple-backend, m365-bridge | High |
| Find my open slots | mcp-tool-layer, availability-engine, unified-calendar-service | Medium |
| Find group availability | mcp-tool-layer (guidance only) | Low |
| Event ownership tracking | unified-calendar-service (SQLite) | High |
| Provider routing & fallback | provider-router, unified-calendar-service | High |
| Event deduplication | unified-calendar-service | Medium |
