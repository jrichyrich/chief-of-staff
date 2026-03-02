# Workflow Brittleness & End-to-End Process Gaps

**Task #4 Analysis** — Comprehensive investigation of fragile workflows, ordering dependencies, and failure cascades.

---

## Executive Summary

The chief-of-staff system has **critical brittleness** in six areas:

1. **Silent failures** — Many workflows catch exceptions and log them but don't propagate failures, leaving callers unaware
2. **Ordering dependencies without enforcement** — Multi-step workflows assume strict ordering but have no validation
3. **Partial success masquerade** — Workflows succeed even when key steps fail (e.g., task execution succeeds even if delivery fails)
4. **External state assumptions** — Workflows assume platform availability (macOS Mail, Excel format, M365 auth) without runtime validation
5. **Truncation/degradation without signaling** — Data is silently truncated (tool results, delegation lists) with no indicator
6. **Timing-dependent state races** — Concurrent invocations can corrupt shared state (processed file, calendar routing database)

---

## 1. Agent Tool-Use Loop — Silent Failure Modes

**File:** `agents/base.py`

### Issue 1.1: MAX_TOOL_ROUNDS Cap Is Indistinguishable From Success
**Line 83-134** — Agent loops up to 25 rounds. If it hits the cap without producing text, it returns:
```python
return "[Agent reached maximum tool rounds without producing a final response]"
```

**Problem:** Callers (e.g., webhook dispatcher) receive this as a regular response. They can't distinguish between:
- Agent successfully completed a task
- Agent got stuck in a loop and timed out

**Impact:** If an agent is misconfigured and loops endlessly, users won't know it's broken—they'll get a string response that looks normal.

**Test case:** Create agent with tool that always requests the same query. Hits round 25 → returns "[Agent reached...]" → caller treats as success.

---

### Issue 1.2: Tool Result Truncation Is Silent
**Line 108-109**
```python
if len(result_str) > MAX_TOOL_RESULT_LENGTH:
    result_str = result_str[:MAX_TOOL_RESULT_LENGTH] + "... [truncated]"
```

**Problem:** Results > 10KB are truncated. The truncation marker is inside the JSON result, making it easy to miss.

**Impact:** If a calendar query returns thousands of events, only the first ~10KB is included. Agent never knows critical events were dropped.

**Example:** `search_calendar_events` returns 500 events (50KB), truncated to 10KB. Agent sees "[truncated]" but continues processing as if it has complete data.

---

### Issue 1.3: Loop Detection Warning Is Ignored
**Line 96-112** — Detects repetitive tool calls and appends a warning:
```python
if signal == "warning":
    result_str += "\n[SYSTEM: You are repeating the same tool call. Try a different approach.]"
```

**Problem:** Claude sees the warning but is not forced to stop. It might ignore the warning and make the same call again.

**Impact:** If an agent misunderstands a tool, it can loop for ~25 rounds while appending warnings, instead of failing fast.

---

### Issue 1.4: Tool Failures Return Error Dict, Don't Fail the Agent
**Line 106-118** — Tool execution failure:
```python
result = self._handle_tool_call(block.name, block.input)
result_str = json.dumps(result)
# result might be {"error": "..."} but agent continues
```

**Problem:** `_handle_tool_call` catches exceptions and returns `{"error": "..."}`. The agent treats errors as regular results and continues.

**Impact:** If a tool crashes (e.g., memory store is corrupted), the agent gets an error response and continues, potentially making worse decisions based on the error.

**Scenario:** Agent calls `create_decision`, database is locked, gets `{"error": "database locked"}`. Agent continues, doesn't know decision wasn't created.

---

### Issue 1.5: Hook Failures Are Silent
**Line 152-159**
```python
def _fire_hooks(self, event_type: str, context: dict) -> list:
    if self.hook_registry is None:
        return []
    try:
        return self.hook_registry.fire_hooks(event_type, context)
    except Exception:
        return []
```

**Problem:** If a before_tool_call hook crashes, exception is swallowed. Agent runs with original (untransformed) arguments.

**Impact:** If a hook is supposed to rate-limit tool calls or transform arguments, and it crashes, the agent never knows and runs with invalid state.

---

## 2. Scheduler Engine — Execution Success ≠ Delivery Success

**File:** `scheduler/engine.py`

### Issue 2.1: Task Marked "Executed" Even If Handler Fails
**Line 405-456** — Task execution flow:
```python
def _execute_task(self, task, now: datetime) -> dict:
    task_result = {"task_id": task.id, "name": task.name}
    try:
        handler_result = execute_handler(...)  # Line 414
        # Calculate next run (line 423)
        next_run = calculate_next_run(...)
        # Update task (line 426-431)
        self.memory_store.update_scheduled_task(
            task.id,
            last_run_at=now.isoformat(),
            next_run_at=next_run,
            last_result=handler_result,
        )
        task_result["status"] = "executed"
    except Exception as e:
        # Still update last_run_at (line 448-455)
        self.memory_store.update_scheduled_task(
            task.id,
            last_run_at=now.isoformat(),
            last_result=json.dumps({"status": "error", "error": error_msg}),
        )
```

**Problem:** Whether handler succeeds or fails, `last_run_at` is always updated. There's no retry mechanism. If a handler fails once, the task won't run again until the next scheduled time—it won't retry immediately.

**Impact:** If a daily task fails at 8am, it won't run again until tomorrow 8am, even if the failure was transient (e.g., network hiccup).

---

### Issue 2.2: Delivery Failure Doesn't Fail Task Execution
**Line 436-439**
```python
# Deliver result if a delivery channel is configured
if getattr(task, "delivery_channel", None):
    delivery_result = self._deliver(task, handler_result)
    task_result["delivery"] = delivery_result
```

**Problem:** Delivery happens AFTER the task is already marked as executed. If delivery fails, the handler result is lost. Task status is still "executed".

**Impact:** A scheduled morning brief executes successfully, handler produces perfect JSON, but email delivery fails. Task is marked "executed", nobody knows the email never arrived.

**Scenario:** Task `get_calendar_events` → produces 100KB JSON → delivery tries to format as email → email service crashes → task still marked "executed" but user gets nothing.

---

### Issue 2.3: Next Run Calculation Can Fail Silently
**Line 422-423**
```python
handler_result = execute_handler(...)
task_result["result"] = handler_result

# Calculate next run
next_run = calculate_next_run(task.schedule_type, task.schedule_config, from_time=now)
```

**Problem:** If `calculate_next_run` throws (e.g., invalid cron expression), the exception is caught at line 441. The task is updated but `next_run_at` is never set.

**Impact:** Task runs successfully but has no scheduled next run. It'll stay in the due list forever, running repeatedly.

---

## 3. Webhook Event Dispatcher — Unbounded Dispatch, No Timeout

**File:** `webhook/dispatcher.py`

### Issue 3.1: Event Matched to >50 Rules Gets Truncated Silently
**Line 81-88**
```python
matched_rules = self.memory_store.match_event_rules(source, event_type)
if not matched_rules:
    logger.info("No matching event rules for source=%s type=%s", source, event_type)
    return []

# Guard against unbounded fan-out from too many matching rules
max_rules = 50
if len(matched_rules) > max_rules:
    logger.warning(
        "Event matched %d rules (cap=%d), truncating for source=%s type=%s",
        len(matched_rules), max_rules, source, event_type,
    )
    matched_rules = matched_rules[:max_rules]
```

**Problem:** If an event matches 100 rules, only 50 are processed. No indication in the dispatch result that some rules were skipped.

**Impact:** A critical GitHub webhook event might match multiple rules (one per team), but only 50 teams get notified. Teams 51+ never know about the event.

---

### Issue 3.2: Agent Execution Has No Per-Dispatch Timeout
**Line 175-182**
```python
# Triage: classify complexity and potentially downgrade model.
try:
    effective_config = await asyncio.to_thread(
        classify_and_resolve, agent_config, agent_input
    )
except Exception:
    effective_config = agent_config

# Execute the agent
from agents.base import BaseExpertAgent
agent = BaseExpertAgent(...)
result_text = await agent.execute(agent_input)
```

**Problem:** Agent execution (line 182) has no timeout. If an agent hangs for 10 minutes, the webhook dispatcher blocks for 10 minutes.

**Impact:** One webhook event with a broken agent can hang the entire dispatcher, preventing other events from being processed.

---

### Issue 3.3: Delivery Failures Are Invisible to Caller
**Line 186-207**
```python
delivery_status = None
delivery_channel = rule.get("delivery_channel")
if delivery_channel:
    delivery_config_raw = rule.get("delivery_config")
    delivery_config = {}
    if delivery_config_raw:
        try:
            delivery_config = json.loads(delivery_config_raw) if isinstance(delivery_config_raw, str) else delivery_config_raw
        except (json.JSONDecodeError, TypeError):
            pass
    try:
        deliver = self._get_delivery_fn()
        delivery_status = deliver(
            delivery_channel,
            delivery_config,
            result_text,
            task_name=rule_name,
        )
    except Exception as e:
        logger.error("Delivery failed for rule '%s': %s", rule_name, e)
        delivery_status = {"status": "error", "error": str(e)}

logger.info(
    "Dispatched rule='%s' agent='%s' status=success duration=%.3fs",
    rule_name, agent_name, duration,
)

return {
    "rule_name": rule_name,
    "agent_name": agent_name,
    "status": "success",  # <-- marked success even if delivery failed
    "result_text": result_text,
    "duration_seconds": duration,
    "delivery_status": delivery_status,
}
```

**Problem:** Dispatch returns `status: "success"` even if delivery failed. The `delivery_status` field might have an error, but it's not surfaced in the top-level status.

**Impact:** Caller checks `status == "success"` and moves on. Never checks `delivery_status` field. Result is never delivered but appears successful.

---

## 4. Proactive Engine — State/Timing Dependencies

**File:** `proactive/engine.py` + `session/manager.py`

### Issue 4.1: Skill Suggestions Are Unvalidated
**Line 39-50** (proactive/engine.py)
```python
def _check_skill_suggestions(self) -> list[Suggestion]:
    pending = self.memory_store.list_skill_suggestions(status="pending")
    results = []
    for s in pending:
        results.append(Suggestion(
            category="skill",
            priority="medium",
            title=f"New skill suggestion: {s.suggested_name or 'unnamed'}",
            description=s.description,
            action="auto_create_skill",
            created_at=s.created_at or "",
        ))
    return results
```

**Problem:** Skill suggestions are created by pattern detector with no validation that the suggested capabilities exist or will work.

**Impact:** Skill suggestions for capabilities like `web_search` (which is marked `implemented=False` in capabilities/registry.py) are still suggested. User tries to create the agent and it crashes at runtime.

---

### Issue 4.2: Session Extraction Patterns Are Fragile
**Line 27-35** (session/manager.py)
```python
_DECISION_PATTERNS = re.compile(
    r"\b(decided|decision|agreed|will do)\b", re.IGNORECASE
)
_ACTION_PATTERNS = re.compile(
    r"\b(TODO|action item|need to|should)\b", re.IGNORECASE
)
_FACT_PATTERNS = re.compile(
    r"\b(important|note that|remember)\b", re.IGNORECASE
)
```

**Problem:** Extraction depends on exact keyword matches. If Claude uses different language ("we resolved to...", "you must...", "key insight: ..."), extraction fails.

**Impact:** Session contains important decisions but they're classified as "general" instead of "decision". Flush stores them with lower confidence. Restore misses them.

**Scenario:** Agent says "We determined that X is critical" → not matched by any pattern → stored as general fact with 0 confidence → restore skips it.

---

### Issue 4.3: Checkpoint Can Fail Midway, Leaving Inconsistent State
**Line 107-186** (session/manager.py)
```python
def flush(self, priority_threshold: str = "all") -> dict:
    extracted = self.extract_structured_data()
    # ... store decisions (line 126-135)
    # ... store action items (line 138-148)
    # ... store key facts (line 151-161)
    # Store session summary (line 164-171)
    entry = ContextEntry(...)
    self.memory_store.store_context(entry)

    # Update session brain (line 174-179)
    if self._session_brain is not None:
        for content in extracted["decisions"]:
            self._session_brain.add_decision(content[:200])
        # ...
        self._session_brain.save()

    return {...}
```

**Problem:** No transaction/atomic guarantee. If `store_context` fails, some facts are persisted but session brain isn't updated. Inconsistent state.

**Impact:** Facts are flushed, context entry fails, session brain never saves. Next restore gets orphaned facts with no session context.

---

## 5. OKR Refresh Workflow — Excel Format Brittleness

**File:** `okr/parser.py`

### Issue 5.1: Parser Is Hardcoded to Cell Positions
**Line 86-94** (parse objectives)
```python
objectives.append(
    Objective(
        okr_id=_cell_str(cells[0]),           # Column A
        name=_cell_str(cells[1]),              # Column B
        statement=_cell_str(cells[2]),         # Column C
        owner=_cell_str(cells[3]),             # Column D
        team=_cell_str(cells[4]),              # Column E
        year=_cell_str(cells[5]),              # Column F
        status=_cell_str(cells[7]),            # Column H (skips G!)
        pct_complete=_cell_pct(cells[8]),      # Column I
    )
)
```

**Problem:** Parser is hardcoded to exact cell indices. If Excel is updated and a column is inserted/removed, parser silently reads wrong data.

**Examples of brittleness:**
- Insert a column before "status" → status now reads from wrong column
- Rename header "year" → parser still reads column F regardless of header
- Delete a column → parser gets IndexError (unhandled) or reads adjacent column

**Impact:** After a minor Excel update, OKR data is corrupted but still parses. Queries return wrong status values, wrong teams, etc. Nobody notices until decisions are made on bad data.

---

### Issue 5.2: No Schema Validation or Existence Checks
**Line 58-61**
```python
try:
    objectives = _parse_objectives(wb["Objectives"])
    key_results = _parse_key_results(wb["Key Results"])
    initiatives = _parse_initiatives(wb["Initiatives"])
finally:
    wb.close()
```

**Problem:** No check that the tabs exist. If someone renames "Objectives" to "OKRs", `wb["Objectives"]` throws KeyError (unhandled).

**Problem:** No check that expected columns exist. If "year" column is deleted, parser silently reads garbage.

**Impact:** Excel format changes → unhandled exception OR silent data corruption.

---

## 6. Session Checkpoint/Restore — Consistency Loss

**File:** `session/manager.py`

### Issue 6.1: Restore Uses Prefix Search That Can Fail
**Line 225-264** (restore_from_checkpoint)
```python
def restore_from_checkpoint(self, session_id: str) -> dict:
    entries = self.memory_store.list_context(session_id=session_id, limit=10)
    # Search for facts created by session flush (keyed with session_ prefix)
    decision_facts = self.memory_store.search_facts("session_decision")
    action_facts = self.memory_store.search_facts("session_action")
    fact_facts = self.memory_store.search_facts("session_fact")
```

**Problem:** Searches are by prefix ("session_decision"). If a flush creates facts with a different prefix or key format, restore won't find them.

**Impact:** Flush stored facts with key `session_decision_20250227_120000_0`, but restore searches for prefix "session_decision" and finds nothing due to timestamp format mismatch.

---

### Issue 6.2: De-Duplication By ID Can Lose Data
**Line 236-242**
```python
seen_ids = set()
unique_facts = []
for f in all_facts:
    if f.id not in seen_ids:
        seen_ids.add(f.id)
        unique_facts.append(f)
```

**Problem:** De-duplication discards duplicates. If two facts have the same ID (collision or bug), only one is kept.

**Impact:** Session had 10 decisions, 5 are duplicates in DB, restore returns only 6 unique decisions.

---

## 7. Daily Briefing Workflow — Source Failure Cascade

**Implicit in Memory** and `mcp_tools/` architecture.

### Issue 7.1: One Source Failure Aborts Entire Briefing
**Pattern:** Daily briefing must query M365 Calendar, Apple Calendar, Email, Teams, iMessages in parallel.

**Problem:** If ANY source fails:
- M365 auth expired → returns 401 → exception propagates → briefing aborts
- Apple Calendar unavailable → returns empty list (not an error) → briefing succeeds but incomplete
- Network timeout on Teams search → exception caught, empty results → briefing partial

**No retry, no fallback, no "best effort" mode that returns partial data with indicators of what failed.**

**Impact:** User's morning briefing fails silently or returns incomplete data with no indication of missing sources.

---

### Issue 7.2: Provider Routing Database Can Corrupt
**Pattern:** Calendar system routes events between Apple/M365 providers.

**File:** `connectors/router.py` (implied) — maintains `calendar-routing.db`

**Problem:** No locking. If two concurrent sessions query/update routing, database can be corrupted.

**Impact:** Event ownership gets confused. Personal calendar event assigned to M365 work calendar, or vice versa.

---

## 8. Inbox Monitor Script — Shell Orchestration Brittleness

**File:** `scripts/inbox-monitor.sh`

### Issue 8.1: No Concurrency Lock
**Line 30** (inbox-monitor.sh)
```bash
PROCESSED_FILE="${INBOX_MONITOR_PROCESSED_FILE:-${DATA_DIR}/inbox-processed.json}"
```

**Problem:** Script reads/appends to this JSON file. No file locking. If cron invokes the script twice concurrently (e.g., network latency causes first invocation to hang), both read the same file, both process the same messages, both write back → file corruption.

**Impact:** iMessage commands get processed twice (duplicate tasks created, duplicate decisions logged).

---

### Issue 8.2: Retry Logic Doesn't Back Off
**Line 34** (implied in script structure)
```bash
MAX_RETRIES=2
```

**Problem:** No exponential backoff. If Claude is rate-limited, script retries immediately, gets rate-limited again, wastes quota.

**Impact:** User sends 100 iMessage commands → script retries all 100 immediately → hits Claude rate limit → subsequent inbox runs fail.

---

### Issue 8.3: Ordering Dependency: iMessage → Claude → Database
**Implicit in script flow:**
1. Read iMessages (can be stale, partial)
2. Call Claude with MCP config (config might be outdated)
3. Process returned commands (create tasks, decisions, etc.)

**Problem:** If step 1 reads stale data (hasn't synced yet), step 3 creates stale tasks. If step 2 fails midway, step 3 creates partial state.

**Impact:** User sends "create task" at 8:00, script runs at 8:05, iMessage history hasn't synced yet, task created with wrong timestamp.

---

## 9. Capability System — Runtime Discovery Brittleness

**File:** `capabilities/registry.py`

### Issue 9.1: Capabilities Validate But Tools May Not Exist at Runtime
**Line 939-959** (get_tools_for_capabilities)
```python
def get_tools_for_capabilities(capabilities: Iterable[str] | None) -> list[dict]:
    validated = validate_capabilities(capabilities)
    tools: list[dict] = []
    seen_tool_names: set[str] = set()

    for capability_name in validated:
        definition = CAPABILITY_DEFINITIONS[capability_name]
        for tool_name in definition.tool_names:
            if tool_name in seen_tool_names:
                continue
            schema = TOOL_SCHEMAS.get(tool_name)
            if schema is None:
                continue  # Silently skip missing tool
            tools.append(deepcopy(schema))
            seen_tool_names.add(tool_name)

    return tools
```

**Problem:** Schema validation passes, but:
- Capability `mail_write` assumes Apple Mail is available (macOS only)
- Capability `calendar_read` assumes Apple Calendar or M365 calendar exists
- Both are checked at runtime only when tools are called

**Impact:** Agent is created with `mail_write` capability on Linux, gets the tool schema, calls `send_email`, crashes with ImportError.

---

### Issue 9.2: Legacy Capabilities Are Still Suggested
**Line 856-896**
```python
"web_search": CapabilityDefinition(
    name="web_search",
    description="Legacy capability for web lookup (no local runtime tool mapping yet)",
    implemented=False,
),
```

**Problem:** Marked `implemented=False` but still in CAPABILITY_DEFINITIONS. Agents can be created with `web_search`, will crash at runtime with "Unknown tool: web_search".

**Impact:** Skill suggestions suggest `web_search` capability. Agent is auto-created with it. User runs agent, gets "tool not found" error.

---

## 10. Critical Ordering Dependencies Without Enforcement

### Dependency Chain 1: Task Execution → Next Run → Delivery
**File:** `scheduler/engine.py`, `_execute_task` method

**Sequence:**
1. Execute handler → produces result
2. Calculate next run → determines when to run again
3. Update task in DB → persist both result and next_run
4. Deliver result → send to user

**Problem:** Steps are sequential but have no transaction guarantees.
- Step 2 fails (invalid cron) → step 3 uses wrong next_run
- Step 4 fails (network down) → steps 1-3 succeeded but user gets nothing

**No enforcement:** Each step assumes previous succeeded. No validation.

**Fix:** Make execution and delivery truly decoupled. Store result, THEN attempt delivery in a separate, retriable step.

---

### Dependency Chain 2: Event Rule Matching → Agent Loading → Input Formatting → Execution → Delivery
**File:** `webhook/dispatcher.py`, `_dispatch_single` method

**Sequence:**
1. Load agent config → fails if agent doesn't exist
2. Format input → uses template variables
3. Execute agent → runs for up to 25 rounds
4. Deliver result → sends via email/teams/notification

**Problem:** Step 1 failure prevents rest of chain from running. If agent is deleted, event is never retried.

**No enforcement:** No check that all matched rules can actually execute. No fallback if agent loads but is broken.

---

### Dependency Chain 3: Agent Memory + Shared Memory → System Prompt → API Call
**File:** `agents/base.py`, `build_system_prompt` and `execute` methods

**Sequence:**
1. Fetch agent memory (line 53) — exception caught, continues
2. Fetch shared namespace memories (line 65) — exception caught, continues
3. Build system prompt with injected memories
4. Call API with system prompt

**Problem:** Steps 1-2 fail silently. Agent runs with incomplete context. No indication that memories were missing.

**No enforcement:** No validation that memory fetch succeeded. No differentiation between "no memories" and "memory store crashed".

---

## Recommendations

### Critical Fixes (Do First)

1. **Add timeout to agent execution** (`agents/base.py:182`) — 30-60 second timeout per dispatch
2. **Make delivery failures block task success** (`scheduler/engine.py:437-439`) — move delivery into try block, fail task if delivery fails
3. **Add file locking to processed file** (`scripts/inbox-monitor.sh:30`) — use fcntl or write temp + rename
4. **Validate OKR Excel before parsing** (`okr/parser.py:58-61`) — check tabs exist, check column headers match expected, validate row count

### High Priority

5. **Add schema validation to Excel parser** — validate required columns before reading data
6. **Implement retriable delivery queue** — separate task execution from delivery, allow delivery to be retried
7. **Add circuit breaker to webhook dispatcher** — fail gracefully if >N rules matched, don't process all 50
8. **Validate agent existence before dispatch** — check agent config loads before queuing event for dispatch
9. **Make session flush atomic** — use transaction for storing facts + context + brain updates

### Medium Priority

10. **Add retry with exponential backoff** to inbox-monitor script
11. **Document provider_preference defaults** — calendar system should document that "both" queries all providers
12. **Implement "best effort" daily briefing mode** — allow partial results with indicators of what failed
13. **Validate capabilities at agent creation time** — check that all tool names actually exist in TOOL_SCHEMAS
14. **Add timeout to webhook event dispatcher** — per-dispatch timeout, not per-agent

### Low Priority But Important

15. Improve session extraction patterns (ML-based instead of regex)
16. Add rate limiting to scheduled task handler
17. Implement alerting when tasks reach MAX_TOOL_ROUNDS
18. Add telemetry to detect silent truncations
19. Document "macOS only" capabilities more prominently

---

## Appendix: Severity Matrix

| Issue | Component | Severity | Likelihood | Impact |
|-------|-----------|----------|-----------|--------|
| Silent MAX_TOOL_ROUNDS | agents/base.py | HIGH | MEDIUM | Agent appears successful when stuck |
| Delivery != Execution | scheduler/engine.py | CRITICAL | HIGH | Users never notified of task results |
| Excel format brittleness | okr/parser.py | CRITICAL | MEDIUM | OKR data corruption after Excel update |
| No concurrency lock | inbox-monitor.sh | CRITICAL | MEDIUM | Duplicate task processing |
| One source failure = briefing fail | Daily briefing workflow | HIGH | HIGH | Morning briefing is unusable if any source fails |
| Event rule truncation | webhook/dispatcher.py | MEDIUM | LOW | Some teams miss important events (>50 rules) |
| Session flush inconsistency | session/manager.py | MEDIUM | LOW | Orphaned facts, inconsistent state |
| Capability doesn't match tool | capabilities/registry.py | MEDIUM | MEDIUM | Agent crashes at runtime on Linux |

---

**Report Generated:** 2026-02-27
**Analysis Scope:** End-to-end workflow failure modes and brittleness patterns
