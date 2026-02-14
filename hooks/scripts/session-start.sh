#!/bin/bash
cat << 'EOF'
{
  "hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": "Chief of Staff plugin is active. You have access to persistent memory, document search, and agent management tools via MCP:\n\n- Memory: store_fact, query_memory, store_location, list_locations\n- Documents: ingest_documents, search_documents\n- Agents: list_agents, get_agent, create_agent\n\nSlash commands: /chief (main), /remember (store facts), /recall (search memory), /agents (manage agents)\n\nProactively use query_memory at the start of conversations to recall relevant facts about the user."
  }
}
EOF
