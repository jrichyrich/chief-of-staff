# Intent Map: find_my_open_slots Pipeline

## Chunk: MCP Tool Handler
- **Purpose**: Entry point for the find_my_open_slots MCP tool call
- **User-facing feature(s)**: Calendar availability analysis
- **Files**: mcp_tools/calendar_tools.py (lines 265-371)
- **Key functions**: find_my_open_slots()
- **Inputs**: start_date, end_date, duration_minutes, soft block config, provider_preference
- **Outputs**: JSON with slots array, formatted_text, count
- **Depends on**: Unified Calendar Service, Availability Engine
- **Risk level**: High

## Chunk: Availability Engine
- **Purpose**: Normalize events, classify soft/hard, compute available time gaps, format for sharing
- **Files**: scheduler/availability.py (501 lines)
- **Key functions**: normalize_event_for_scheduler(), classify_event_softness(), find_available_slots(), format_slots_for_sharing()
- **Inputs**: Raw event dicts, date range, duration filter, soft keywords
- **Outputs**: List of available slot dicts, formatted text
- **Depends on**: None (pure computation)
- **Risk level**: High

## Chunk: Unified Calendar + Routing
- **Purpose**: Facade across Apple + M365; dual-read policy, deduplication, ownership tracking
- **Files**: connectors/calendar_unified.py (490 lines), connectors/router.py (140 lines)
- **Key classes**: UnifiedCalendarService, ProviderRouter
- **Inputs**: Date range, provider_preference, require_all_success flag
- **Outputs**: Merged event list or error payload
- **Depends on**: Apple Provider, M365 Provider
- **Risk level**: High

## Chunk: M365 Provider Chain
- **Purpose**: Fetch M365/Outlook calendar data via Claude CLI subprocess
- **Files**: connectors/providers/m365_provider.py (189 lines), connectors/claude_m365_bridge.py (379 lines)
- **Key classes**: Microsoft365CalendarProvider, ClaudeM365Bridge
- **Inputs**: Date range, calendar names
- **Outputs**: List of event dicts or error payload
- **Depends on**: Claude CLI binary, M365 MCP connector
- **Risk level**: Critical

## Chunk: Apple Provider
- **Purpose**: Fetch Apple Calendar data via EventKit/PyObjC
- **Files**: connectors/providers/apple_provider.py (127 lines)
- **Key class**: AppleCalendarProvider
- **Inputs**: Date range, calendar names
- **Outputs**: List of event dicts
- **Depends on**: EventKit (PyObjC)
- **Risk level**: Low
