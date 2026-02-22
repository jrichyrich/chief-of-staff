---
description: "Store a fact about yourself in persistent memory"
argument-hint: "[fact to remember]"
---

The user wants to store a fact in their persistent memory. Parse their input to extract:
- **category**: One of 'personal', 'preference', 'work', 'relationship', 'backlog'
- **key**: A short label for the fact
- **value**: The fact itself

Then call the `store_fact` MCP tool with these values. Confirm what was stored.

If the input is a location (address, place), use `store_location` instead.
