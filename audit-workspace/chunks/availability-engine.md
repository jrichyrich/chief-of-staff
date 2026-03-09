# Chunk Audit: availability-engine

**User-facing feature**: Calendar availability analysis (find_my_open_slots)
**Risk Level**: High
**Files Audited**: `scheduler/availability.py` (501 lines), `tests/test_scheduler.py` (997 lines), caller `mcp_tools/calendar_tools.py` (lines 265-362)
**Status**: Complete — core algorithm is sound but has two critical defects in how it classifies events

## Purpose (as understood from reading the code)

This module normalizes calendar events from Apple Calendar and Microsoft 365 into a unified format, classifies each as a "soft" (movable) or "hard" (fixed) block, then computes available time gaps within daily working-hour windows. It also provides a human-readable formatter for sharing availability text. The algorithm itself (gap computation, block merging, timezone conversion) is correct and well-tested. The defects are in the classification layer and its integration with the MCP tool caller.

## Runtime Probe Results

- **Tests found**: Yes — 38 tests in `tests/test_scheduler.py`
- **Tests run**: 38 passed, 0 failed
- **Import/load check**: OK
- **Type check**: Not applicable (no mypy/pyright in CI)
- **Edge case probes**: Confirmed two critical bugs and one crash path (details below)
- **Key observation**: The production bug ("events not blocked") is caused by two interacting defects: (1) `user_email` is never passed from the MCP tool, causing ANY attendee's tentative status to make the whole event soft, and (2) the `showAs` field from M365 is normalized but never used in softness classification, creating an invisible gap.

## Dimension Assessments

### Implemented

All four public functions are fully implemented with real logic:
- `normalize_event_for_scheduler` (lines 13-125): Handles Apple and M365 field name differences, nested M365 structures, attendee format conversion. Complete.
- `classify_event_softness` (lines 128-216): Keyword matching on title/notes, Apple status==3, M365 responseStatus for attendee-level tentative. Complete but missing event-level `showAs` check.
- `find_available_slots` (lines 219-439): Full day iteration, error filtering, cancelled/declined/free skipping, all-day handling, timezone conversion, block merging, gap computation. Complete.
- `format_slots_for_sharing` (lines 442-501): Date grouping, time range formatting, timezone abbreviation. Complete.

No stubs, no TODOs, no unreachable code.

### Correct

Two confirmed correctness bugs:

**Bug 1 — `user_email` never passed from MCP tool (CRITICAL)**:
The `find_my_open_slots` MCP tool at `calendar_tools.py:352-362` calls `find_available_slots()` without passing `user_email`. This means `classify_event_softness` checks ALL attendees for tentative status (line 185-193). If ANY attendee on ANY meeting has `responseStatus` containing "tentative" (e.g., `tentativelyAccepted`), the entire event is classified as soft and treated as available time. In production, this means a meeting like "CISO Subcommittee" where one invitee tentatively accepted would be incorrectly shown as open.

Confirmed via runtime probe:
```
Event with one tentativelyAccepted attendee, user_email=None:
  is_soft=True, reason=Attendee marked tentative
Event with user_email=bob@example.com (accepted):
  is_soft=False, reason=No soft indicators found
```

**Bug 2 — `showAs` field ignored in softness classification (WARNING)**:
M365 events have a `showAs` field with values `free`, `busy`, `tentative`, `oof`. The normalizer preserves it (line 64), and `find_available_slots` skips `showAs=free` (line 312), but `classify_event_softness` does NOT examine the `showAs` field at all. An M365 event with `showAs=tentative` (organizer set it as tentative) is treated as a hard block because:
- Title "CISO Subcommittee" has no soft keywords
- `showAs=tentative` is not checked by classify_event_softness
- It's NOT `free` so it's not skipped

This is inconsistent: the word "tentative" is in the default soft_keywords list (line 159), but that only matches against title/notes, not the `showAs` field. Whether `showAs=tentative` should be soft is a design decision, but the current behavior is inconsistent and undocumented.

**Bug 3 — `showAs=oof` not handled for OOO blocking (MINOR)**:
When `block_ooo_all_day=True`, the code checks `_OOO_KEYWORDS` against the event title (line 327). But M365 all-day OOF events may have `showAs=oof` without "OOO" in the title. This field is not checked, so some OOF events could slip through.

### Efficient

No efficiency issues. The algorithm is O(E log E) per day (sort + merge), which is appropriate for typical calendar loads (< 50 events/day). No redundant computation, no unnecessary copies.

### Robust

- **Non-dict events crash**: Passing `None`, integers, or strings in the events list causes `AttributeError` at `normalize_event_for_scheduler` (line 31: `event.get("uid")`). The error payload filter (lines 278-283) only catches dicts with an "error" key. Non-dict items are not filtered. Confirmed: `find_available_slots(events=[None, 42], ...)` raises `AttributeError`.

- **Empty dict input OK**: `normalize_event_for_scheduler({})` returns a valid dict with empty/falsy defaults. No crash.

- **Timezone handling is defensive**: Unknown timezone names in `start_tz`/`end_tz` fall back to user timezone via try/except (lines 360-365). Good.

- **Unparseable times handled**: `ValueError`/`TypeError` on `fromisoformat` is caught and the event is skipped with a debug log (lines 346-353). Good.

- **Zero-duration and reversed events skipped**: Line 382 catches `event_start >= event_end`. Good.

### Architecture

- **Clean separation**: Pure computation module with no I/O, no database, no external calls. Highly testable.
- **Good composability**: `normalize_event_for_scheduler` and `classify_event_softness` are independently callable and tested.
- **Variable scoping smell**: `format_slots_for_sharing` line 495 uses `start_dt` leaked from the `for slot in date_slots` inner loop. Safe because `date_slots` is always non-empty, but fragile and confusing to read.
- **Hardcoded timezone**: "America/Denver" is the default everywhere but is configurable via parameter. Acceptable.
- **No coupling issues**: The module has zero imports beyond stdlib. Clean dependency boundary.

## Findings

### Critical

- **`calendar_tools.py:352-362`** — `user_email` is never passed from `find_my_open_slots` to `find_available_slots`. When `user_email=None`, `classify_event_softness` checks ALL attendees for tentative status. If any attendee on a meeting has `responseStatus` containing "tentative" (e.g., `tentativelyAccepted`), the meeting is classified as soft and shown as available time. This is the root cause of the production bug where meetings like "CISO Subcommittee" appeared as open slots. Fix: add `user_email` parameter to `find_my_open_slots` MCP tool and pass it through, or retrieve it from session/identity context.

- **`availability.py:128-216`** — `classify_event_softness` does not examine the normalized `show_as` field. An event with `showAs=tentative` (M365 organizer-set) is not classified as soft via this path, but the word "tentative" IS a default soft keyword that only matches title/notes. This creates a confusing inconsistency: `showAs=tentative` on the event is ignored, but "tentative" in the title triggers soft classification. The `showAs` field should be explicitly handled in the classification logic (either as a soft signal or explicitly documented as not relevant).

### Warning

- **`availability.py:278-283`** — Error payload filter only catches `dict` items with an `"error"` key. Non-dict items (None, int, str, bool) in the events list will crash `normalize_event_for_scheduler` with `AttributeError`. The filter should also skip non-dict items: `if not isinstance(event, dict): continue`.

- **`availability.py:324-330`** — OOO all-day blocking only checks title keywords (`_OOO_KEYWORDS`), not the M365 `showAs=oof` field. An all-day OOF event with a title like "Jason Richardson" (common M365 pattern for OOF blocks) would not be caught.

- **`calendar_tools.py:265`** — `find_my_open_slots` MCP tool has no `user_email` parameter at all. The function signature should accept it (with a sensible default from session context or stored identity) so that tentative classification is user-scoped.

### Note

- `format_slots_for_sharing` line 495 uses `start_dt` leaked from an inner for-loop. Safe but fragile — would break if refactored to allow empty `date_slots`.
- The `%-I` strftime format (line 489) is a GNU extension that works on macOS/Linux but not Windows. Acceptable for this macOS-only deployment.
- 38 tests cover the core algorithm well, but no test covers the `user_email=None` + `tentativelyAccepted` attendee scenario that caused the production bug. A regression test should be added.
- No test covers `showAs=tentative` event-level behavior in `find_available_slots`.

## Verdict

The core gap-computation algorithm is correct and well-tested — it properly normalizes events, merges overlapping blocks, clips to working hours, and computes available slots. The production bug is NOT in the algorithm itself but in two classification-layer defects: (1) `user_email` is never passed from the MCP tool, causing any attendee's tentative response to wrongly mark the whole event as soft/available, and (2) the `showAs` field from M365 is preserved but never consulted during softness classification. The most urgent fix is wiring `user_email` through from `find_my_open_slots` to `find_available_slots` — this alone would prevent the class of bugs where other people's tentative responses cause your meetings to disappear from availability.
