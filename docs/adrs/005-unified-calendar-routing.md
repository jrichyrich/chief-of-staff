# ADR-005: Unified Calendar with Provider Routing

## Status

Accepted (2026-02-23)

## Context

The user has events spread across Apple Calendar (personal, via iCloud) and Microsoft 365 (work, via Exchange). Availability checks require querying both providers. Write operations need to route to the correct provider based on the calendar and event ownership.

Challenges:
- The same meeting may appear in both providers (Exchange sync)
- Write operations must target the authoritative provider to avoid conflicts
- Provider availability varies (M365 requires Claude CLI bridge; Apple requires EventKit)
- Calendar names are ambiguous ("Calendar" exists in both providers)

## Decision

Introduce a **UnifiedCalendarService** facade with a **ProviderRouter** policy engine and an **ownership database**.

### Architecture

```
calendar_tools.py -> UnifiedCalendarService -> ProviderRouter -> [Apple, M365]
                                            -> OwnershipDB (calendar-routing.db)
```

### Read Routing

- Default (`auto`): query both connected providers
- Explicit (`apple`, `microsoft_365`, `both`): query specified provider(s) with fallback
- **Dual-read policy** (`CALENDAR_REQUIRE_DUAL_READ=true`): if both providers are connected, both must succeed for the response to be valid

### Write Routing

Resolution order:
1. **Explicit target_provider** -- Use if specified
2. **Prefixed UID** (`microsoft_365:abc123`) -- Extract provider from UID format
3. **Ownership DB lookup** -- Check `calendar-routing.db` for known event ownership
4. **Calendar name heuristic** -- Work-related keywords route to M365
5. **Default** -- Personal-first safety (route to Apple)

### Event Deduplication

Events are deduplicated by iCal UID (primary) or by title+start+end tuple (fallback). This prevents the same Exchange-synced event from appearing twice.

### Ownership Tracking

A separate SQLite database (`data/calendar-routing.db`) tracks which provider owns each event via a `unified_uid -> (provider, native_id)` mapping, updated on every read and write.

## Consequences

**Benefits:**
- Users see a single unified calendar view without knowing which provider owns each event
- Availability checks automatically query all providers
- Write operations reliably target the authoritative provider
- Deduplication eliminates duplicate events from Exchange sync
- The ownership DB persists provider knowledge across sessions

**Tradeoffs:**
- Dual-read policy can cause read failures if one provider is temporarily unavailable
- The ClaudeM365Bridge adds latency (subprocess + LLM call for each M365 operation)
- Calendar name heuristics are fragile (hardcoded keywords like "work", "exchange", "corp")
- The separate ownership DB must stay in sync with actual provider state

## Related

- `connectors/calendar_unified.py` -- UnifiedCalendarService
- `connectors/router.py` -- ProviderRouter
- `connectors/claude_m365_bridge.py` -- M365 bridge
- `connectors/providers/` -- Provider adapters
- `config.py` -- CALENDAR_ALIASES, CALENDAR_ROUTING_DB_PATH, CALENDAR_REQUIRE_DUAL_READ
