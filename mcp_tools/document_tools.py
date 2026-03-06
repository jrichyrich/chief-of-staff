"""Document search and ingestion tools for the Chief of Staff MCP server."""

import json
import logging
import sqlite3
from pathlib import Path

from documents.ingestion import ingest_path as _ingest_path
from .decorators import tool_errors
from .state import _retry_on_transient

logger = logging.getLogger("jarvis-mcp")

_EXPECTED = (sqlite3.OperationalError, ValueError, KeyError)


def register(mcp, state):
    """Register document tools with the FastMCP server."""

    @mcp.tool()
    @tool_errors("Document search error", expected=_EXPECTED)
    async def search_documents(query: str, top_k: int = 5) -> str:
        """Semantic search over ingested documents. Returns the most relevant chunks.

        Args:
            query: Natural language search query
            top_k: Number of results to return (default 5)
        """
        document_store = state.document_store
        results = _retry_on_transient(document_store.search, query, top_k=top_k)

        if not results:
            return json.dumps({"message": "No documents found. Ingest documents first.", "results": []})

        return json.dumps({"results": results})

    @mcp.tool()
    @tool_errors("Document ingestion error", expected=_EXPECTED)
    async def ingest_documents(path: str) -> str:
        """Ingest documents from a file or directory into the knowledge base for semantic search.
        Supports .txt, .md, .py, .json, .yaml files.

        Args:
            path: Absolute path to a file or directory to ingest
        """
        document_store = state.document_store
        target = Path(path).resolve()

        # Security: prevent path traversal outside allowed directories
        allowed_roots = state.allowed_ingest_roots
        if allowed_roots is None:
            allowed_roots = [
                Path.home() / "Documents",
                Path.home() / "Desktop",
                Path.home() / "Downloads",
            ]
        resolved_roots = [root.resolve() for root in allowed_roots]
        if not any(target.is_relative_to(root) for root in resolved_roots):
            roots_str = ", ".join(str(r) for r in resolved_roots)
            return f"Access denied: path must be within allowed directories: {roots_str}"

        if not target.exists():
            return f"Path not found: {path}"

        result = _ingest_path(target, document_store)
        logger.info(f"Ingested from {path}: {result}")
        return result

    # Expose tool functions at module level for testing
    import sys
    module = sys.modules[__name__]
    module.search_documents = search_documents
    module.ingest_documents = ingest_documents
