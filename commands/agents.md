---
description: "List, view, or create expert agent configurations"
argument-hint: "[list | create <name> | view <name>]"
---

The user wants to manage expert agents. Based on their input:

- **list** or no arguments: Call `list_agents` to show all configured agents
- **view <name>**: Call `get_agent` with the agent name to show full details
- **create <name>**: Guide the user through creating a new agent by asking for description, system prompt, and capabilities, then call `create_agent`

Present results in a clear, organized format.
