# Naming Consolidation Analysis: "Chief of Staff" → "Jarvis"

**Date:** 2026-02-27
**Task:** Catalog all references to consolidate from dual MCP naming to single "jarvis" namespace
**Status:** Complete scan — 4 naming variants traced across ~800 references

---

## Executive Summary

The codebase currently uses **two parallel naming systems**:

1. **"Jarvis"** — Primary MCP server name, display name, agent identifier, logger names
2. **"Chief of Staff"** — Project description, documentation, some tool names

### Current State
- **MCP Server Instance:** `"jarvis"` (mcp_server.py line 202)
- **Tool Names:** Mix of `mcp__jarvis__*` and `mcp__chief-of-staff__*` prefixes
- **Desktop Extension:** `manifest.json` registers as `"jarvis"` display name `"Jarvis"`
- **ChromaDB Collection:** `"chief_of_staff_docs"` (documents/store.py:16)

### Impact Scope
**~800 total references** across:
- 5 functional reference types (code, config, scripts, tests, env vars)
- 40+ documentation/comment references
- Multiple configuration files
- Shell scripts and automation

---

## Findings by Naming Variant

### 1. "chief-of-staff" (Hyphenated) — 15 References

**Functional References (require code changes):**

| File | Line | Context | Type |
|------|------|---------|------|
| `hooks/scripts/post-tool-checkpoint-reminder.sh` | 17 | `mcp__chief-of-staff__checkpoint_session` | Tool name (functional) |
| `scripts/inbox-monitor.sh` | 143 | Grep pattern: `(chief-of-staff\|jarvis)` | Shell logic (functional) |

**Configuration/Documentation:**

| File | Line | Context | Type |
|------|------|---------|------|
| `agent_configs/report_builder.yaml` | 41 | `Jarvis -- Chief of Staff` (user-facing text) | Agent config (doc) |
| `manifest.json` | 6 | Deprecated in description | DXT manifest (doc) |
| `.env.example` | 1 | Header: `Chief of Staff (Jarvis)` | Env template (doc) |
| `docs/` files | Multiple | Historical references | Documentation |
| Worktrees | Multiple | Old agent work (`agent-*` dirs) | Archived (can ignore) |

**Test Files:**

| File | Line | Context | Type |
|------|------|---------|------|
| `tests/test_security_input_sanitization.py` | 103 | Test data: `"chief-of-staff"` | Test fixture (functional) |

---

### 2. "chief_of_staff" (Underscored) — 200+ References

**Functional References (code changes needed):**

| File | Line(s) | Context | Type |
|-------|---------|---------|------|
| `documents/store.py` | 16 | ChromaDB collection: `name="chief_of_staff_docs"` | **Critical** — used at runtime |
| `docs/agents.md` | 80, 94, 358 | Field name in YAML: `created_by: chief_of_staff` | Schema documentation |
| `pyproject.toml` | 8 | `description = "... Chief of Staff managing..."` | Package metadata |
| `skills/memory-management/SKILL.md` | 10 | `Chief of Staff memory tools` | Skill documentation |

**Configuration/Schema References:**

- Agent YAML configs reference `created_by: chief_of_staff` field (documentation only — field name might stay the same)
- Many docstrings and comments use underscored form for code identifiers

**Pattern in codebase:**
- Used in collection names (ChromaDB)
- Used in documentation field names
- Never used as a tool prefix (tools are `mcp__jarvis__*` or `mcp__chief-of-staff__*`)

---

### 3. "Chief of Staff" (Title Case) — 300+ References

**Display/Branding References (low functional impact):**

| File | Context | Type |
|------|---------|------|
| `README.md` | Title, descriptions, feature summaries | **User-facing** (update for consistency) |
| `CLAUDE.md` | Project description, system intro | **Architect docs** (update for clarity) |
| `manifest.json` | `description` field | DXT manifest |
| `mcp_server.py` | Docstring: `"Chief of Staff MCP Server"` | Code comments |
| `mcp_tools/*.py` | Module docstrings (20+ files) | Code documentation |
| Documentation (`docs/`) | Headers, descriptions, examples | User documentation |

**Impact Assessment:**
- These are mostly **documentation and display strings**
- Functional impact is **low** (no code logic depends on this text)
- Update for **clarity and consistency** with "Jarvis" branding

---

### 4. "Jarvis" / "jarvis" (Primary) — 250+ References

**Functional References (already deployed):**

| File | Line | Context | Type |
|------|------|---------|------|
| `mcp_server.py` | 39, 169, 197, 202 | Logger: `logging.getLogger("jarvis-mcp")` | **Current system** (keep as-is) |
| `mcp_server.py` | 202 | MCP instance: `FastMCP("jarvis", ...)` | **Current system** (keep as-is) |
| `config.py` | 44 | `DAEMON_LOG_FILE = DATA_DIR / "jarvis-daemon.log"` | File paths (keep as-is) |
| `manifest.json` | 3, 99-100 | `"name": "jarvis"`, `"display_name": "Jarvis"` | DXT registration (keep as-is) |
| `session/manager.py` | 169 | `agent="jarvis"` | Context field (keep as-is) |

**Shell Scripts (working as-is):**

| File | Line | Context |
|------|------|---------|
| `scripts/inbox-monitor.sh` | 143 | Already checks both: `(chief-of-staff\|jarvis)` |
| Other shell scripts | Multiple | Log file references, env vars |

**Documentation/Logger Names:**

| File | Reference | Type |
|------|-----------|------|
| Many `mcp_tools/*.py` | `logger = logging.getLogger("jarvis-mcp")` | Consistent (20+ loggers) |
| README.md | "Jarvis" branding throughout | User-facing |
| docs/ | "Jarvis" in examples and guides | User documentation |

---

## Consolidation Plan: Key Changes Needed

### 1. **Highest Priority** (System-Breaking)

**Change Tool Name Prefix:**
```bash
# Before: mcp__chief-of-staff__checkpoint_session
# After: mcp__jarvis__checkpoint_session

hooks/scripts/post-tool-checkpoint-reminder.sh:17
if [ "$TOOL_NAME" = "mcp__jarvis__checkpoint_session" ]; then
```

**Update ChromaDB Collection Name:**
```python
# documents/store.py:16
# Before: name="chief_of_staff_docs"
# After: name="jarvis_docs"  (or keep as-is for backward compat with migration)
```

**Update Shell Script Grep Pattern:**
```bash
# scripts/inbox-monitor.sh:143
# Keep as fallback OR simplify to just "jarvis:" if old tooling is gone
if echo "${MCP_LIST_OUTPUT}" | grep -Eiq "jarvis:.*connected"; then
```

### 2. **High Priority** (Documentation/Configuration)

| File | Change | Impact |
|------|--------|--------|
| `README.md` | Keep "Chief of Staff (Jarvis)" or simplify to "Jarvis" | Branding consistency |
| `CLAUDE.md` | Update project description | Internal documentation |
| `manifest.json` | `description` field | User-facing in Claude Desktop |
| `pyproject.toml` | Update package description | Minor impact (PyPI metadata) |
| Test data | `tests/test_security_input_sanitization.py:103` | Test fixture cleanup |

### 3. **Low Priority** (Code Comments)

| Category | Count | Action |
|----------|-------|--------|
| Module docstrings (mcp_tools/) | ~20 files | Update "Chief of Staff MCP" → "Jarvis MCP" |
| Agent YAML schema docs | 3 files | Update examples showing `created_by` field |
| Skill documentation | 2 files | Update "Chief of Staff" references |

---

## Files Requiring Changes (by Category)

### Code Changes (Functional)
1. **hooks/scripts/post-tool-checkpoint-reminder.sh** — Tool name prefix
2. **documents/store.py** — ChromaDB collection name
3. **scripts/inbox-monitor.sh** — Grep pattern (fallback support)

### Configuration Changes
1. **manifest.json** — Description field
2. **pyproject.toml** — Package metadata
3. **CLAUDE.md** — Architecture documentation
4. **README.md** — User-facing documentation

### Documentation Updates
1. **docs/agents.md** — Schema documentation (created_by field)
2. **docs/setup-guide.md** — Setup instructions
3. **docs/how-to-guides.md** — User guides (update "Jarvis:" examples)
4. **docs/inbox-monitor-setup.md** — Feature documentation
5. **agent_configs/*.yaml** — System prompt descriptions
6. **.env.example** — Environment template
7. **skills/\*/SKILL.md** — Skill documentation (3 files)

### Comment/Docstring Updates (~20 files)
- **mcp_tools/\*.py** — Module docstrings
- **Other modules** — Incidental references

### Test Files
1. **tests/test_security_input_sanitization.py:103** — Update test data

---

## Backward Compatibility Considerations

### Old Tool Names Still in Use?
- Check if any user configs or scripts still reference `mcp__chief-of-staff__*` tools
- **Recommendation:** Support both names during transition period:
  ```python
  # In mcp_server.py, register tools under BOTH names for backward compat
  @mcp.tool(name="mcp__jarvis__checkpoint_session")
  @mcp.tool(name="mcp__chief-of-staff__checkpoint_session")  # deprecated
  def checkpoint_session(...):
  ```

### ChromaDB Collection Migration
- Existing systems may have data in `"chief_of_staff_docs"` collection
- **Option 1:** Keep old collection name, read from both during transition
- **Option 2:** Migrate data in a startup script before creating new collection
- **Option 3:** Create new collection at different name, leave old one for reference

### Shell Script Compatibility
- `scripts/inbox-monitor.sh` already handles both names (`(chief-of-staff|jarvis)`)
- Can continue to support both during deprecation period

---

## Summary: What Stays vs. What Changes

| Aspect | Current | After Consolidation | Notes |
|--------|---------|---------------------|-------|
| **MCP server name** | `"jarvis"` | `"jarvis"` | ✅ No change (already primary) |
| **Tool prefix** | `mcp__jarvis__*`, `mcp__chief-of-staff__*` | `mcp__jarvis__*` only | ⚠️ Support both in transition |
| **Logger names** | `"jarvis-mcp"` | `"jarvis-mcp"` | ✅ Already consistent |
| **ChromaDB collection** | `"chief_of_staff_docs"` | `"jarvis_docs"` | ⚠️ Plan migration |
| **Display name** | "Jarvis" (branding) | "Jarvis" | ✅ Already primary |
| **Project description** | "Chief of Staff (Jarvis)" | "Jarvis" or "Chief of Staff Agent" | 📝 Update for clarity |
| **Documentation** | Mixed "Chief of Staff" / "Jarvis" | Unified to "Jarvis" | 📝 Consistency pass |
| **LaunchD job names** | `com.chg.jarvis-scheduler` | Keep as-is | ✅ No change |

---

## Complete File List for Review

**Files that need changes (prioritized):**

1. `hooks/scripts/post-tool-checkpoint-reminder.sh` — Tool name
2. `documents/store.py` — Collection name
3. `scripts/inbox-monitor.sh` — Pattern (optional if deprecating old names)
4. `manifest.json` — Description
5. `CLAUDE.md` — Project description
6. `README.md` — User documentation
7. `pyproject.toml` — Package metadata
8. `docs/agents.md` — Schema documentation
9. `.env.example` — Template
10. All `mcp_tools/*.py` — Module docstrings (~20 files)
11. `agent_configs/*.yaml` — System prompts (3-5 files)
12. `skills/*/SKILL.md` — Skill documentation (3 files)
13. `tests/test_security_input_sanitization.py` — Test data
14. Additional docs: `docs/setup-guide.md`, `docs/how-to-guides.md`, `docs/inbox-monitor-setup.md`, etc.

**Worktrees (can ignore):**
- `.claude/worktrees/agent-*` — Old agent work, not part of main codebase

---

## Notes for Implementation

1. **Git Strategy:** Create feature branch `feat/consolidate-naming-to-jarvis` or similar
2. **Testing:** Update any tests that validate tool names or MCP server naming
3. **Migration Window:** Consider supporting both old and new tool names during rollout
4. **User Communication:** Document change in CHANGELOG and update installation guides
5. **ChromaDB Data:** Decide on migration strategy (keep old collection, migrate, or deprecate)

---

## References

- Total references scanned: ~800 across all file types
- Functional references (code): ~15 instances
- Configuration references: ~50 instances
- Documentation/comment references: ~735 instances
- No single point of failure — changes can be staged systematically
