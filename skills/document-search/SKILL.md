---
name: document-search
description: Use when the user wants to ingest files into a knowledge base or search previously ingested documents for relevant information
---

# Document Search

## Overview

Ingest documents into a vector database and perform semantic search to find relevant content. Supports .txt, .md, .py, .json, .yaml files.

## When to Use

- User wants to add files to the knowledge base ("Ingest this folder", "Add these docs")
- User asks questions that might be answered by ingested documents
- User wants to search their document collection

## Available Tools

| Tool | Purpose | Key Args |
|------|---------|----------|
| `ingest_documents` | Add files to knowledge base | path (file or directory) |
| `search_documents` | Semantic search over documents | query, top_k (default 5) |

## Pattern

**Ingestion:**
1. Get the file or directory path from the user
2. Call `ingest_documents` with the absolute path
3. Report how many files and chunks were ingested

**Search:**
1. Formulate a natural language query from the user's question
2. Call `search_documents` with the query
3. Present the most relevant chunks with source attribution

## Common Mistakes

- Using relative paths — always use absolute paths for ingestion
- Not ingesting before searching — remind the user to ingest documents first if search returns empty
- Searching with overly specific queries — use broader terms for better semantic matching
