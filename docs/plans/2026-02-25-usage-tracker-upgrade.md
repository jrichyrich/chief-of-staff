# Usage Tracker Upgrade — Rich Tool Analytics

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Transform the tool usage tracker from a simple counter (`tool_name + "auto"`) into a rich analytics system that captures argument patterns, individual invocations with timestamps, success/failure, and duration — then expose it via a `get_tool_statistics` MCP tool.

**Architecture:** Four phases, each independently testable. Phase 1 extracts meaningful query patterns from tool arguments at the middleware layer. Phase 2 adds a temporal `tool_usage_log` table for per-invocation data. Phase 3 upgrades the pattern detector to leverage richer data. Phase 4 adds a `get_tool_statistics` MCP tool so stats are queryable without raw SQL.

**Tech Stack:** Python 3, SQLite, FastMCP, pytest, `@pytest.mark.asyncio`

---

## Phase 1: Smart Argument Extraction

Replace the hardcoded `_QUERY_PATTERN = "auto"` with logic that extracts a meaningful summary from tool arguments. This is the highest-impact single change.

### Task 1: Define the argument extraction function

**Files:**
- Modify: `mcp_tools/usage_tracker.py`
- Test: `tests/test_usage_tracker.py`

**Step 1: Write the failing test**

Add to `tests/test_usage_tracker.py`:

```python
from mcp_tools.usage_tracker import _extract_query_pattern


class TestExtractQueryPattern:
    """Tests for _extract_query_pattern argument summarizer."""

    def test_returns_auto_for_empty_args(self):
        assert _extract_query_pattern("list_locations", {}) == "auto"
        assert _extract_query_pattern("list_locations", None) == "auto"

    def test_extracts_query_field(self):
        assert _extract_query_pattern("query_memory", {"query": "backlog"}) == "backlog"

    def test_extracts_name_field(self):
        assert _extract_query_pattern("get_agent", {"name": "researcher"}) == "researcher"

    def test_extracts_tool_name_field(self):
        assert _extract_query_pattern("record_tool_usage", {"tool_name": "search_mail"}) == "search_mail"

    def test_extracts_query_pattern_field(self):
        assert _extract_query_pattern("record_tool_usage", {"query_pattern": "weekly meeting"}) == "weekly meeting"

    def test_prefers_query_over_name(self):
        assert _extract_query_pattern("some_tool", {"query": "foo", "name": "bar"}) == "foo"

    def test_extracts_title_field(self):
        assert _extract_query_pattern("create_decision", {"title": "hire contractor"}) == "hire contractor"

    def test_extracts_canonical_name_field(self):
        assert _extract_query_pattern("get_identity", {"canonical_name": "John Smith"}) == "John Smith"

    def test_extracts_recipient_from_to_field(self):
        assert _extract_query_pattern("send_imessage_reply", {"to": "+15551234567", "body": "hello"}) == "+15551234567"

    def test_truncates_long_values(self):
        long_val = "x" * 200
        result = _extract_query_pattern("query_memory", {"query": long_val})
        assert len(result) <= 100

    def test_falls_back_to_auto_for_non_string_args(self):
        assert _extract_query_pattern("some_tool", {"limit": 10, "enabled": True}) == "auto"

    def test_extracts_start_date_as_fallback(self):
        result = _extract_query_pattern("get_calendar_events", {"start_date": "2026-02-25", "end_date": "2026-02-26"})
        assert "2026-02-25" in result
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_usage_tracker.py::TestExtractQueryPattern -v`
Expected: FAIL — `ImportError: cannot import name '_extract_query_pattern'`

**Step 3: Implement `_extract_query_pattern`**

In `mcp_tools/usage_tracker.py`, add this function before `install_usage_tracker`:

```python
# Ordered priority of argument keys to extract as query_pattern
_PATTERN_KEYS = (
    "query",
    "query_pattern",
    "tool_name",
    "name",
    "title",
    "canonical_name",
    "to",
    "task",
    "organization_name",
    "start_date",
    "mailbox",
    "calendar_name",
    "agent_name",
    "event_id",
    "message_id",
    "suggestion_id",
    "chat_identifier",
    "recipient_type",
)

_MAX_PATTERN_LEN = 100


def _extract_query_pattern(tool_name: str, arguments: dict | None) -> str:
    """Extract a meaningful query pattern from tool arguments.

    Walks _PATTERN_KEYS in priority order and returns the first
    non-empty string value found, truncated to _MAX_PATTERN_LEN.
    Falls back to "auto" if no meaningful string argument is found.
    """
    if not arguments:
        return "auto"
    for key in _PATTERN_KEYS:
        val = arguments.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()[:_MAX_PATTERN_LEN]
    return "auto"
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_usage_tracker.py::TestExtractQueryPattern -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add mcp_tools/usage_tracker.py tests/test_usage_tracker.py
git commit -m "feat: add _extract_query_pattern for smart arg extraction"
```

---

### Task 2: Wire extraction into the middleware

**Files:**
- Modify: `mcp_tools/usage_tracker.py`
- Test: `tests/test_usage_tracker.py`

**Step 1: Write the failing test**

Add to `TestUsageTracker` in `tests/test_usage_tracker.py`:

```python
@pytest.mark.asyncio
async def test_tracks_query_argument(self, tracked_mcp, memory_store):
    """Tools with a 'query' arg should record the query value, not 'auto'."""
    await tracked_mcp.call_tool("query_memory", {"query": "weekly priorities"})

    patterns = memory_store.get_skill_usage_patterns()
    qm = [p for p in patterns if p["tool_name"] == "query_memory"]
    assert any(p["query_pattern"] == "weekly priorities" for p in qm)

@pytest.mark.asyncio
async def test_no_args_still_tracks_auto(self, tracked_mcp, memory_store):
    """Tools with no meaningful args should still record 'auto'."""
    await tracked_mcp.call_tool("list_locations", {})

    patterns = memory_store.get_skill_usage_patterns()
    loc = [p for p in patterns if p["tool_name"] == "list_locations"]
    assert any(p["query_pattern"] == "auto" for p in loc)
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_usage_tracker.py::TestUsageTracker::test_tracks_query_argument -v`
Expected: FAIL — `query_pattern` is still `"auto"` for everything

**Step 3: Update `tracked_call_tool` in `install_usage_tracker`**

In `mcp_tools/usage_tracker.py`, change the `tracked_call_tool` function:

Replace:
```python
async def tracked_call_tool(name, arguments):
    # Record usage before calling the tool
    if name not in _EXCLUDED_TOOLS:
        try:
            memory_store = state.memory_store
            if memory_store is not None:
                memory_store.record_skill_usage(name, _QUERY_PATTERN)
        except Exception:
            logger.debug("Failed to record usage for %s", name, exc_info=True)

    return await original_call_tool(name, arguments)
```

With:
```python
async def tracked_call_tool(name, arguments):
    # Record usage before calling the tool
    if name not in _EXCLUDED_TOOLS:
        try:
            memory_store = state.memory_store
            if memory_store is not None:
                pattern = _extract_query_pattern(name, arguments)
                memory_store.record_skill_usage(name, pattern)
        except Exception:
            logger.debug("Failed to record usage for %s", name, exc_info=True)

    return await original_call_tool(name, arguments)
```

Remove the `_QUERY_PATTERN = "auto"` constant (no longer needed — `_extract_query_pattern` returns `"auto"` as its fallback).

**Step 4: Run full tracker test suite**

Run: `pytest tests/test_usage_tracker.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add mcp_tools/usage_tracker.py tests/test_usage_tracker.py
git commit -m "feat: wire smart arg extraction into usage tracker middleware"
```

---

## Phase 2: Temporal Invocation Log

Add a `tool_usage_log` table that stores every individual invocation (not aggregated). This enables time-series analysis, session correlation, and failure tracking.

### Task 3: Add `tool_usage_log` table to MemoryStore

**Files:**
- Modify: `memory/store.py` (schema + methods)
- Modify: `memory/models.py` (new dataclass)
- Test: `tests/test_usage_tracker.py`

**Step 1: Write the failing test**

Add a new test class in `tests/test_usage_tracker.py`:

```python
class TestToolUsageLog:
    """Tests for the tool_usage_log table."""

    def test_log_invocation(self, memory_store):
        memory_store.log_tool_invocation(
            tool_name="query_memory",
            query_pattern="backlog",
            success=True,
            duration_ms=42,
            session_id="sess-001",
        )
        rows = memory_store.get_tool_usage_log(tool_name="query_memory")
        assert len(rows) == 1
        assert rows[0]["tool_name"] == "query_memory"
        assert rows[0]["query_pattern"] == "backlog"
        assert rows[0]["success"] is True
        assert rows[0]["duration_ms"] == 42
        assert rows[0]["session_id"] == "sess-001"

    def test_multiple_invocations_stored_separately(self, memory_store):
        for i in range(3):
            memory_store.log_tool_invocation(
                tool_name="search_mail",
                query_pattern=f"query-{i}",
                success=True,
                duration_ms=10 * i,
            )
        rows = memory_store.get_tool_usage_log(tool_name="search_mail")
        assert len(rows) == 3

    def test_log_with_defaults(self, memory_store):
        memory_store.log_tool_invocation(tool_name="list_locations")
        rows = memory_store.get_tool_usage_log(tool_name="list_locations")
        assert len(rows) == 1
        assert rows[0]["query_pattern"] == "auto"
        assert rows[0]["success"] is True
        assert rows[0]["duration_ms"] is None
        assert rows[0]["session_id"] is None

    def test_get_log_with_limit(self, memory_store):
        for i in range(10):
            memory_store.log_tool_invocation(tool_name="search_mail", query_pattern=f"q{i}")
        rows = memory_store.get_tool_usage_log(tool_name="search_mail", limit=5)
        assert len(rows) == 5

    def test_get_log_all_tools(self, memory_store):
        memory_store.log_tool_invocation(tool_name="query_memory")
        memory_store.log_tool_invocation(tool_name="search_mail")
        rows = memory_store.get_tool_usage_log()
        assert len(rows) == 2

    def test_get_tool_stats_summary(self, memory_store):
        memory_store.log_tool_invocation(tool_name="query_memory", success=True, duration_ms=10)
        memory_store.log_tool_invocation(tool_name="query_memory", success=True, duration_ms=20)
        memory_store.log_tool_invocation(tool_name="query_memory", success=False, duration_ms=5)
        memory_store.log_tool_invocation(tool_name="search_mail", success=True, duration_ms=30)

        stats = memory_store.get_tool_stats_summary()
        assert len(stats) == 2

        qm = next(s for s in stats if s["tool_name"] == "query_memory")
        assert qm["total_calls"] == 3
        assert qm["success_count"] == 2
        assert qm["failure_count"] == 1
        assert qm["avg_duration_ms"] == pytest.approx(11.67, abs=0.1)
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_usage_tracker.py::TestToolUsageLog -v`
Expected: FAIL — `AttributeError: 'MemoryStore' has no attribute 'log_tool_invocation'`

**Step 3: Add the table schema**

In `memory/store.py`, add after the existing `skill_usage` CREATE TABLE (around line 143):

```sql
CREATE TABLE IF NOT EXISTS tool_usage_log (
    id INTEGER PRIMARY KEY,
    tool_name TEXT NOT NULL,
    query_pattern TEXT NOT NULL DEFAULT 'auto',
    success INTEGER NOT NULL DEFAULT 1,
    duration_ms INTEGER,
    session_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_tool_usage_log_tool ON tool_usage_log(tool_name);
CREATE INDEX IF NOT EXISTS idx_tool_usage_log_created ON tool_usage_log(created_at);
```

**Step 4: Add `log_tool_invocation` and `get_tool_usage_log` methods**

In `memory/store.py`, add after the existing `get_skill_usage_patterns` method:

```python
def log_tool_invocation(
    self,
    tool_name: str,
    query_pattern: str = "auto",
    success: bool = True,
    duration_ms: int | None = None,
    session_id: str | None = None,
) -> None:
    """Log a single tool invocation to the temporal log table."""
    now = datetime.now().isoformat()
    self.conn.execute(
        """INSERT INTO tool_usage_log
           (tool_name, query_pattern, success, duration_ms, session_id, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (tool_name, query_pattern, int(success), duration_ms, session_id, now),
    )
    self.conn.commit()

def get_tool_usage_log(
    self,
    tool_name: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """Retrieve invocation log entries, optionally filtered by tool name."""
    if tool_name:
        rows = self.conn.execute(
            "SELECT * FROM tool_usage_log WHERE tool_name=? ORDER BY created_at DESC LIMIT ?",
            (tool_name, limit),
        ).fetchall()
    else:
        rows = self.conn.execute(
            "SELECT * FROM tool_usage_log ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [
        {
            "id": row["id"],
            "tool_name": row["tool_name"],
            "query_pattern": row["query_pattern"],
            "success": bool(row["success"]),
            "duration_ms": row["duration_ms"],
            "session_id": row["session_id"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]

def get_tool_stats_summary(self) -> list[dict]:
    """Aggregate tool usage stats from the invocation log."""
    rows = self.conn.execute(
        """SELECT
               tool_name,
               COUNT(*) as total_calls,
               SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as success_count,
               SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as failure_count,
               AVG(CASE WHEN duration_ms IS NOT NULL THEN duration_ms END) as avg_duration_ms,
               MIN(created_at) as first_used,
               MAX(created_at) as last_used
           FROM tool_usage_log
           GROUP BY tool_name
           ORDER BY total_calls DESC"""
    ).fetchall()
    return [
        {
            "tool_name": row["tool_name"],
            "total_calls": row["total_calls"],
            "success_count": row["success_count"],
            "failure_count": row["failure_count"],
            "avg_duration_ms": round(row["avg_duration_ms"], 2) if row["avg_duration_ms"] else None,
            "first_used": row["first_used"],
            "last_used": row["last_used"],
        }
        for row in rows
    ]
```

**Step 5: Run tests to verify they pass**

Run: `pytest tests/test_usage_tracker.py::TestToolUsageLog -v`
Expected: ALL PASS

**Step 6: Commit**

```bash
git add memory/store.py tests/test_usage_tracker.py
git commit -m "feat: add tool_usage_log table for temporal invocation tracking"
```

---

### Task 4: Wire the invocation log into the middleware

**Files:**
- Modify: `mcp_tools/usage_tracker.py`
- Test: `tests/test_usage_tracker.py`

**Step 1: Write the failing test**

Add to `TestUsageTracker` in `tests/test_usage_tracker.py`:

```python
@pytest.mark.asyncio
async def test_invocation_logged_to_temporal_table(self, tracked_mcp, memory_store):
    """Each tool call should create a row in tool_usage_log."""
    await tracked_mcp.call_tool("list_locations", {})
    await tracked_mcp.call_tool("list_locations", {})

    log = memory_store.get_tool_usage_log(tool_name="list_locations")
    assert len(log) == 2  # Two separate rows, not aggregated
    assert all(row["success"] is True for row in log)

@pytest.mark.asyncio
async def test_invocation_log_captures_duration(self, tracked_mcp, memory_store):
    """Invocation log should include duration_ms."""
    await tracked_mcp.call_tool("list_locations", {})

    log = memory_store.get_tool_usage_log(tool_name="list_locations")
    assert len(log) == 1
    assert log[0]["duration_ms"] is not None
    assert log[0]["duration_ms"] >= 0

@pytest.mark.asyncio
async def test_invocation_log_records_failure(self, tracked_mcp, memory_store):
    """Failed tool calls should be logged with success=False."""
    try:
        await tracked_mcp.call_tool("nonexistent_tool", {})
    except Exception:
        pass

    log = memory_store.get_tool_usage_log(tool_name="nonexistent_tool")
    assert len(log) == 1
    assert log[0]["success"] is False
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_usage_tracker.py::TestUsageTracker::test_invocation_logged_to_temporal_table -v`
Expected: FAIL — `get_tool_usage_log` returns 0 rows

**Step 3: Update the middleware to log invocations**

In `mcp_tools/usage_tracker.py`, update `tracked_call_tool`:

```python
import time

# ... inside install_usage_tracker ...

    @functools.wraps(original_call_tool)
    async def tracked_call_tool(name, arguments):
        if name not in _EXCLUDED_TOOLS:
            pattern = _extract_query_pattern(name, arguments)

            # Record aggregated usage (existing behavior)
            try:
                memory_store = state.memory_store
                if memory_store is not None:
                    memory_store.record_skill_usage(name, pattern)
            except Exception:
                logger.debug("Failed to record usage for %s", name, exc_info=True)

            # Execute tool and log individual invocation
            start = time.monotonic()
            success = True
            try:
                result = await original_call_tool(name, arguments)
                return result
            except Exception:
                success = False
                raise
            finally:
                duration_ms = int((time.monotonic() - start) * 1000)
                try:
                    memory_store = state.memory_store
                    if memory_store is not None:
                        memory_store.log_tool_invocation(
                            tool_name=name,
                            query_pattern=pattern,
                            success=success,
                            duration_ms=duration_ms,
                        )
                except Exception:
                    logger.debug("Failed to log invocation for %s", name, exc_info=True)
        else:
            return await original_call_tool(name, arguments)
```

Note: this restructures the function so that excluded tools skip both tracking and logging, while non-excluded tools get the full treatment. The `try/finally` ensures we log even on failure.

**Step 4: Run full tracker test suite**

Run: `pytest tests/test_usage_tracker.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add mcp_tools/usage_tracker.py tests/test_usage_tracker.py
git commit -m "feat: wire temporal invocation logging into tracker middleware"
```

---

## Phase 3: Expose `get_tool_statistics` MCP Tool

Add a new MCP tool so usage stats are queryable interactively without raw SQL.

### Task 5: Add `get_tool_statistics` tool

**Files:**
- Modify: `mcp_tools/skill_tools.py`
- Test: `tests/test_usage_tracker.py`

**Step 1: Write the failing test**

Add to `tests/test_usage_tracker.py`:

```python
import json


class TestGetToolStatistics:
    """Tests for the get_tool_statistics MCP tool."""

    @pytest.fixture
    def setup_state(self, memory_store):
        import mcp_server
        mcp_server._state.memory_store = memory_store
        yield mcp_server._state
        mcp_server._state.clear()

    @pytest.mark.asyncio
    async def test_returns_summary_stats(self, setup_state, memory_store):
        from mcp_tools.skill_tools import get_tool_statistics

        # Seed some log data
        memory_store.log_tool_invocation("query_memory", "backlog", True, 10)
        memory_store.log_tool_invocation("query_memory", "OKR", True, 20)
        memory_store.log_tool_invocation("search_mail", "budget", True, 50)

        result = json.loads(await get_tool_statistics())
        assert result["total_unique_tools"] == 2
        assert result["total_invocations"] == 3
        assert len(result["tools"]) == 2
        qm = next(t for t in result["tools"] if t["tool_name"] == "query_memory")
        assert qm["total_calls"] == 2

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_data(self, setup_state):
        from mcp_tools.skill_tools import get_tool_statistics

        result = json.loads(await get_tool_statistics())
        assert result["total_unique_tools"] == 0
        assert result["total_invocations"] == 0
        assert result["tools"] == []

    @pytest.mark.asyncio
    async def test_includes_top_patterns(self, setup_state, memory_store):
        from mcp_tools.skill_tools import get_tool_statistics

        memory_store.log_tool_invocation("query_memory", "backlog", True, 10)
        memory_store.log_tool_invocation("query_memory", "backlog", True, 15)
        memory_store.log_tool_invocation("query_memory", "OKR", True, 20)

        result = json.loads(await get_tool_statistics(tool_name="query_memory"))
        assert "top_patterns" in result
        patterns = result["top_patterns"]
        assert len(patterns) >= 1
        # "backlog" used twice should be first
        assert patterns[0]["query_pattern"] == "backlog"
        assert patterns[0]["count"] == 2
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_usage_tracker.py::TestGetToolStatistics -v`
Expected: FAIL — `ImportError: cannot import name 'get_tool_statistics'`

**Step 3: Add `get_tool_statistics` tool**

In `mcp_tools/skill_tools.py`, add inside the `register()` function (after `auto_execute_skills`):

```python
@mcp.tool()
async def get_tool_statistics(tool_name: str = "") -> str:
    """Get usage statistics for Jarvis MCP tools.

    Returns aggregated stats from the invocation log: call counts,
    success/failure rates, average duration, and top query patterns.

    Args:
        tool_name: Optional — filter to a specific tool for detailed breakdown.
                   If empty, returns summary across all tools.
    """
    memory_store = state.memory_store
    try:
        stats = memory_store.get_tool_stats_summary()

        if tool_name:
            stats = [s for s in stats if s["tool_name"] == tool_name]
            # Get top patterns for the specific tool
            log = memory_store.get_tool_usage_log(tool_name=tool_name, limit=500)
            pattern_counts: dict[str, int] = {}
            for entry in log:
                p = entry["query_pattern"]
                pattern_counts[p] = pattern_counts.get(p, 0) + 1
            top_patterns = sorted(
                [{"query_pattern": k, "count": v} for k, v in pattern_counts.items()],
                key=lambda x: x["count"],
                reverse=True,
            )[:20]
            return json.dumps({
                "tool_name": tool_name,
                "total_unique_tools": len(stats),
                "total_invocations": sum(s["total_calls"] for s in stats),
                "tools": stats,
                "top_patterns": top_patterns,
            })

        total_invocations = sum(s["total_calls"] for s in stats)
        return json.dumps({
            "total_unique_tools": len(stats),
            "total_invocations": total_invocations,
            "tools": stats,
        })
    except Exception as e:
        logger.exception("Error getting tool statistics")
        return json.dumps({"error": f"Failed to get statistics: {e}"})
```

Also add `get_tool_statistics` to the module-level export block at the bottom of `register()`:

```python
module.get_tool_statistics = get_tool_statistics
```

**Step 4: Add `get_tool_statistics` to the exclusion list**

In `mcp_tools/usage_tracker.py`, add `"get_tool_statistics"` to `_EXCLUDED_TOOLS`:

```python
_EXCLUDED_TOOLS = frozenset({
    "record_tool_usage",
    "analyze_skill_patterns",
    "list_skill_suggestions",
    "auto_create_skill",
    "auto_execute_skills",
    "get_tool_statistics",
})
```

**Step 5: Run tests to verify they pass**

Run: `pytest tests/test_usage_tracker.py::TestGetToolStatistics -v`
Expected: ALL PASS

**Step 6: Run full test suite**

Run: `pytest tests/test_usage_tracker.py -v`
Expected: ALL PASS

**Step 7: Commit**

```bash
git add mcp_tools/skill_tools.py mcp_tools/usage_tracker.py tests/test_usage_tracker.py
git commit -m "feat: add get_tool_statistics MCP tool for usage analytics"
```

---

## Phase 4: Upgrade Pattern Detector

Now that `query_pattern` has real values, the pattern detector can cluster meaningfully.

### Task 6: Add `get_top_patterns_by_tool` to MemoryStore

**Files:**
- Modify: `memory/store.py`
- Test: `tests/test_usage_tracker.py`

**Step 1: Write the failing test**

Add to `TestToolUsageLog`:

```python
def test_get_top_patterns_by_tool(self, memory_store):
    memory_store.log_tool_invocation("query_memory", "backlog")
    memory_store.log_tool_invocation("query_memory", "backlog")
    memory_store.log_tool_invocation("query_memory", "OKR")
    memory_store.log_tool_invocation("search_mail", "budget")

    patterns = memory_store.get_top_patterns_by_tool(limit_per_tool=5)
    assert "query_memory" in patterns
    assert "search_mail" in patterns
    assert patterns["query_memory"][0]["pattern"] == "backlog"
    assert patterns["query_memory"][0]["count"] == 2
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_usage_tracker.py::TestToolUsageLog::test_get_top_patterns_by_tool -v`
Expected: FAIL — `AttributeError`

**Step 3: Implement the method**

In `memory/store.py`, add after `get_tool_stats_summary`:

```python
def get_top_patterns_by_tool(self, limit_per_tool: int = 10) -> dict[str, list[dict]]:
    """Get top query patterns grouped by tool name from the invocation log."""
    rows = self.conn.execute(
        """SELECT tool_name, query_pattern, COUNT(*) as count
           FROM tool_usage_log
           WHERE query_pattern != 'auto'
           GROUP BY tool_name, query_pattern
           ORDER BY tool_name, count DESC"""
    ).fetchall()

    result: dict[str, list[dict]] = {}
    for row in rows:
        tool = row["tool_name"]
        if tool not in result:
            result[tool] = []
        if len(result[tool]) < limit_per_tool:
            result[tool].append({"pattern": row["query_pattern"], "count": row["count"]})
    return result
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_usage_tracker.py::TestToolUsageLog::test_get_top_patterns_by_tool -v`
Expected: PASS

**Step 5: Commit**

```bash
git add memory/store.py tests/test_usage_tracker.py
git commit -m "feat: add get_top_patterns_by_tool query method"
```

---

### Task 7: Update pattern detector to use invocation log

**Files:**
- Modify: `skills/pattern_detector.py`
- Test: `tests/test_pattern_detector.py` (create if needed, or add to existing)

**Step 1: Write the failing test**

Add to `tests/test_usage_tracker.py`:

```python
class TestPatternDetectorWithLog:
    """Tests for pattern detection using the invocation log."""

    def test_detect_patterns_from_log(self, memory_store):
        from skills.pattern_detector import PatternDetector

        # Create enough invocations to trigger pattern detection
        for _ in range(6):
            memory_store.log_tool_invocation("query_memory", "backlog")
        for _ in range(4):
            memory_store.log_tool_invocation("query_memory", "OKR")
        # Also seed the aggregated skill_usage table
        for _ in range(6):
            memory_store.record_skill_usage("query_memory", "backlog")
        for _ in range(4):
            memory_store.record_skill_usage("query_memory", "OKR")

        detector = PatternDetector(memory_store)
        patterns = detector.detect_patterns(min_occurrences=5, confidence_threshold=0.5)
        assert len(patterns) >= 1
        # Should find the query_memory pattern
        tool_names = [p["tool_name"] for p in patterns]
        assert "query_memory" in tool_names
```

**Step 2: Run test to verify it passes (or update if needed)**

Run: `pytest tests/test_usage_tracker.py::TestPatternDetectorWithLog -v`

If it passes already (the existing pattern detector works with the richer data in `skill_usage`), great — the detector already benefits from Phase 1's smart extraction. If not, adjust thresholds.

**Step 3: Commit**

```bash
git add tests/test_usage_tracker.py
git commit -m "test: validate pattern detector works with enriched usage data"
```

---

## Phase 5: Final Verification

### Task 8: Full test suite + integration check

**Step 1: Run the full test suite**

Run: `pytest tests/test_usage_tracker.py -v`
Expected: ALL PASS

**Step 2: Run the broader project test suite**

Run: `pytest --timeout=30 -x`
Expected: ALL PASS — no regressions

**Step 3: Verify the schema migration**

The new `tool_usage_log` table uses `CREATE TABLE IF NOT EXISTS`, so existing databases will get the new table on next startup. No migration script needed.

**Step 4: Commit any remaining changes**

```bash
git add -A
git commit -m "feat: complete usage tracker upgrade — rich analytics"
```

---

## Summary of Changes

| File | Change |
|------|--------|
| `mcp_tools/usage_tracker.py` | Add `_extract_query_pattern()`, `_PATTERN_KEYS`, update middleware to extract patterns + log invocations with duration/success |
| `memory/store.py` | Add `tool_usage_log` table, `log_tool_invocation()`, `get_tool_usage_log()`, `get_tool_stats_summary()`, `get_top_patterns_by_tool()` |
| `mcp_tools/skill_tools.py` | Add `get_tool_statistics` MCP tool |
| `tests/test_usage_tracker.py` | Add `TestExtractQueryPattern`, `TestToolUsageLog`, `TestGetToolStatistics`, `TestPatternDetectorWithLog` test classes |

## What This Enables

After implementation, asking "Jarvis, what are the tool usage statistics?" will return:
- Total unique tools used and invocation counts
- Per-tool breakdown: call count, success rate, avg duration
- Top query patterns per tool (e.g., "query_memory is most often used for 'backlog', 'OKR', 'weekly priorities'")
- Time-series data for trend analysis
- Failure tracking to identify flaky tools
