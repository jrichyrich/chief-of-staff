# ADR-003: Capability-Gated Agent Tool Access

## Status

Accepted (2026-02-12)

## Context

Expert agents are semi-autonomous: they run their own tool-use loops with Claude, executing multiple tool calls before producing a final response. Without access control, any agent could read/write any data store, send emails, or modify calendars.

We needed a mechanism to:
- Restrict agents to only the tools relevant to their domain
- Make permissions declarative and auditable
- Allow new capabilities to be added without modifying agent code
- Validate configs at load time (not at runtime)

## Decision

Agents declare capabilities in their YAML config files. The `CapabilitiesRegistry` maps capability names to specific tool schemas. At execution time, `get_tools_for_capabilities()` returns only the tool schemas matching declared capabilities.

### Capability Model

```yaml
# Example agent config
name: meeting_prep
capabilities:
  - memory_read
  - calendar_read
  - mail_read
```

Each capability maps to one or more tools:
- `memory_read` -> `query_memory`
- `calendar_read` -> `get_calendar_events`, `search_calendar_events`
- `mail_read` -> `get_mail_messages`, `get_mail_message`, `search_mail`, `get_unread_count`

### Enforcement

1. **Schema filtering**: `BaseExpertAgent.get_tools()` only returns tool schemas for declared capabilities. Claude never sees tool definitions it cannot use.
2. **Runtime boundary check**: `_handle_tool_call()` verifies the tool name is in the allowed set before dispatch. This catches edge cases where Claude hallucinates an undeclared tool name.
3. **Validation at load time**: `validate_capabilities()` rejects unknown capability names when loading YAML configs.

### 34 Capabilities

Currently 26 implemented capabilities with runtime tool mappings, plus 8 legacy capabilities (web_search, code_analysis, writing, editing, data_analysis, planning, file_operations, code_execution) accepted for config compatibility but without local tool mappings.

## Consequences

**Benefits:**
- Least-privilege access -- agents cannot access tools outside their declared scope
- Declarative configuration -- capabilities are visible in YAML without reading code
- Composable -- agents can combine any set of capabilities
- Auditable -- the full capability-to-tool mapping is defined in one file

**Tradeoffs:**
- New tools require updating the capabilities registry (TOOL_SCHEMAS + CAPABILITY_DEFINITIONS)
- Legacy capabilities with no tool mapping are accepted but do nothing at runtime
- Tool schemas are duplicated between the capabilities registry and MCP tool definitions (the agent-facing schemas in `capabilities/registry.py` are separate from the MCP-facing `@mcp.tool()` definitions)

## Related

- `capabilities/registry.py` -- CapabilityDefinition, TOOL_SCHEMAS, get_tools_for_capabilities
- `agents/base.py` -- BaseExpertAgent capability enforcement
- `agents/registry.py` -- AgentConfig with capabilities list
- `agent_configs/*.yaml` -- 34 agent configuration files
