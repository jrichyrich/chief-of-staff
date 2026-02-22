#!/bin/bash
# SessionStart hook: provides context on startup, resume, clear, and compact events.
# On compact events, reminds Claude to recover checkpointed context.

# Read stdin to detect event type (if available)
INPUT=$(cat 2>/dev/null || echo "{}")
EVENT_TYPE=$(echo "$INPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('session_type','startup'))" 2>/dev/null || echo "startup")

# Reset tool call counter on any session start
echo "0" > /tmp/jarvis_tool_call_count 2>/dev/null

if [ "$EVENT_TYPE" = "compact" ]; then
    cat << 'EOF'
{
  "hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": "Chief of Staff plugin is active. Context was just compacted.\n\nIMPORTANT: Run query_memory('session_checkpoint') to recover any checkpointed session context. Also run get_session_health() to see current session metrics.\n\nAvailable MCP tools: store_fact, query_memory, checkpoint_session, get_session_health, search_documents, list_agents, and more."
  }
}
EOF
else
    cat << 'EOF'
{
  "hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": "Chief of Staff plugin is active. You have access to persistent memory, document search, and agent management tools via MCP:\n\n- Memory: store_fact, query_memory, store_location, list_locations, checkpoint_session, get_session_health\n- Documents: ingest_documents, search_documents\n- Agents: list_agents, get_agent, create_agent\n\nProactively use query_memory at the start of conversations to recall relevant facts about the user. Use get_session_health to check if a checkpoint is recommended."
  }
}
EOF
fi
