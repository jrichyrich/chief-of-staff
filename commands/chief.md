---
description: "Ask your Chief of Staff - manages memory, documents, and expert agents"
---

You have access to the Chief of Staff plugin tools via MCP. Use the appropriate tools based on the user's request:

- **Memory**: Use `store_fact` to remember things, `query_memory` to recall facts, `store_location` to save places, `list_locations` to see saved places
- **Documents**: Use `ingest_documents` to add files to the knowledge base, `search_documents` to find relevant content
- **Agents**: Use `list_agents` to see available experts, `get_agent` for details, `create_agent` to define new expert agents

Process the user's request using these tools. If they ask to remember something, store it. If they ask to find something, search for it. If they need an expert, check or create one.
