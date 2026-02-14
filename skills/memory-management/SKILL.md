---
name: memory-management
description: Use when the user shares personal information, preferences, work details, or relationships that should be remembered across sessions, or when they ask to recall previously stored facts
---

# Memory Management

## Overview

Persist and retrieve facts about the user using the Chief of Staff memory tools. Facts survive across sessions and are organized by category.

## When to Use

- User shares personal info ("My name is...", "I work at...", "I prefer...")
- User asks to remember something ("Remember that...", "Save this...")
- User asks about previously stored info ("What's my...", "Do you remember...")
- User mentions a location worth saving ("My office is at...")

## Available Tools

| Tool | Purpose | Key Args |
|------|---------|----------|
| `store_fact` | Save a fact | category, key, value |
| `query_memory` | Search/retrieve facts | query, category (optional) |
| `store_location` | Save a place | name, address, notes |
| `list_locations` | List saved places | (none) |

## Categories

- **personal**: Name, birthday, family, hobbies
- **preference**: Favorite things, communication style, work preferences
- **work**: Job title, company, projects, skills
- **relationship**: Colleagues, contacts, team members

## Pattern

1. Detect when the user shares memorable information
2. Extract category, key, and value
3. Call `store_fact` or `store_location`
4. Confirm what was stored

For retrieval:
1. Identify what the user wants to recall
2. Call `query_memory` with search term or category filter
3. Present results clearly

## Common Mistakes

- Storing vague keys like "info" — use specific keys like "job_title", "favorite_color"
- Forgetting to search before storing — check if a fact already exists to avoid duplicates
- Not using categories — always categorize facts for organized retrieval
