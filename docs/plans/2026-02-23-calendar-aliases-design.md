# Calendar Aliases Design

**Date:** 2026-02-23
**Status:** Approved

## Problem

Both iCloud and Exchange have a calendar named "Calendar". The EventKit method `_get_calendar_by_name()` returns the first match (iCloud), so events intended for Exchange land on the wrong calendar. Write operations (`create_calendar_event`) lack a `source_filter` parameter to disambiguate.

## Solution

A `CALENDAR_ALIASES` dict in `config.py` maps friendly names (e.g. "work", "chg", "exchange") to `{name, source}` pairs. `_get_calendar_by_name()` resolves aliases with case-insensitive lookup and matches by both calendar name and source account.

## Config (`config.py`)

```python
CALENDAR_ALIASES = {
    "work": {"name": "Calendar", "source": "Exchange"},
    "work calendar": {"name": "Calendar", "source": "Exchange"},
    "chg": {"name": "Calendar", "source": "Exchange"},
    "chg calendar": {"name": "Calendar", "source": "Exchange"},
    "exchange": {"name": "Calendar", "source": "Exchange"},
    "personal": {"name": "Calendar", "source": "iCloud"},
    "personal calendar": {"name": "Calendar", "source": "iCloud"},
}
```

Lookup is case-insensitive: `CALENDAR_ALIASES.get(name.strip().lower())`.

## EventKit Change (`apple_calendar/eventkit.py`)

- `_get_calendar_by_name(name)` becomes `_get_calendar_by_name(name, source=None)`
- First checks if `name` is an alias key (case-insensitive) -> extracts real name + source
- When `source` is set, matches both `cal.title() == name` AND `cal.source().title() == source`
- When `source` is None, preserves current first-match behavior (backward compatible)

## Scope

- **Files changed:** `config.py`, `apple_calendar/eventkit.py`
- **No changes needed in:** `apple_provider.py`, `calendar_unified.py`, `calendar_tools.py`
- Alias resolution is transparent at the EventKit layer; all callers benefit automatically

## Testing

- Alias resolves to correct calendar when two calendars share the same name
- Case-insensitive: "Work", "work", "WORK" all resolve the same
- Non-alias names work unchanged (backward compatible)
- Unknown alias falls through to name-only match
