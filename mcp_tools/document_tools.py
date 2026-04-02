"""Document search and ingestion tools for the Chief of Staff MCP server."""

import json
import logging
import shutil
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
    async def search_documents(query: str, top_k: int = 5, include_summaries: bool = True) -> str:
        """Semantic search over ingested documents. Returns the most relevant chunks.

        Args:
            query: Natural language search query
            top_k: Number of results to return (default 5)
            include_summaries: If True, also return document summaries when available (default True)
        """
        document_store = state.document_store
        results = _retry_on_transient(document_store.search, query, top_k=top_k)

        response = {}

        # Include summaries if available and requested
        if include_summaries:
            summaries = _retry_on_transient(document_store.search_summaries, query, top_k=3)
            if summaries:
                response["summaries"] = summaries

        if not results and not response.get("summaries"):
            return json.dumps({"message": "No documents found. Ingest documents first.", "results": []})

        response["results"] = results
        return json.dumps(response)

    @mcp.tool()
    @tool_errors("Document ingestion error", expected=_EXPECTED)
    async def ingest_documents(path: str) -> str:
        """Ingest documents from a file or directory into the knowledge base for semantic search.
        Supports .txt, .md, .py, .json, .yaml, .pdf, .docx files.

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

    @mcp.tool()
    @tool_errors("Document list error", expected=_EXPECTED)
    async def list_documents() -> str:
        """Lists all unique source files in the document knowledge base with chunk counts.

        Returns a JSON list of documents with source filename and number of chunks.
        """
        document_store = state.document_store
        sources = _retry_on_transient(document_store.list_sources)

        if not sources:
            return json.dumps({"message": "No documents in the knowledge base.", "documents": []})

        return json.dumps({"documents": sources, "total": len(sources)})

    @mcp.tool()
    @tool_errors("Document delete error", expected=_EXPECTED)
    async def delete_document(source: str) -> str:
        """Delete a document and all its chunks from the knowledge base by source filename.

        Also removes the entry from _index.md if present.

        Args:
            source: The source filename to delete (as shown by list_documents)
        """
        document_store = state.document_store

        # Verify the source exists before deleting
        existing = _retry_on_transient(document_store.list_sources)
        source_names = [s["source"] for s in existing]
        if source not in source_names:
            return json.dumps({"error": f"Source '{source}' not found in knowledge base.", "available": source_names})

        _retry_on_transient(document_store.delete_by_source, source)
        logger.info(f"Deleted document chunks for source: {source}")

        # Attempt to update _index.md
        index_path = Path("/Users/jasricha/Library/CloudStorage/OneDrive-CHGHealthcare/Jarvis/_index.md")
        index_updated = False
        if index_path.exists():
            try:
                lines = index_path.read_text().splitlines(keepends=True)
                filtered = [line for line in lines if source not in line]
                if len(filtered) < len(lines):
                    index_path.write_text("".join(filtered))
                    index_updated = True
            except OSError as exc:
                logger.warning(f"Could not update _index.md: {exc}")

        return json.dumps({
            "message": f"Deleted all chunks for '{source}' from knowledge base.",
            "index_updated": index_updated,
        })

    @mcp.tool()
    @tool_errors("Document archive error", expected=_EXPECTED)
    async def archive_document(source: str, reason: str = "") -> str:
        """Archive a document: move the file on disk to _archive/, delete chunks from ChromaDB, and update _index.md.

        Searches for the file under the Jarvis output directory and moves it to an _archive/ subdirectory.

        Args:
            source: The source filename to archive (as shown by list_documents)
            reason: Optional reason for archiving
        """
        document_store = state.document_store
        jarvis_root = Path("/Users/jasricha/Library/CloudStorage/OneDrive-CHGHealthcare/Jarvis")

        # Find the file on disk
        matches = list(jarvis_root.rglob(source))
        # Exclude files already in _archive
        matches = [m for m in matches if "_archive" not in m.parts]

        if not matches:
            return json.dumps({"error": f"File '{source}' not found under {jarvis_root}"})

        src_path = matches[0]
        archive_dir = jarvis_root / "_archive"
        archive_dir.mkdir(parents=True, exist_ok=True)
        dest_path = archive_dir / src_path.name

        # Handle name collision in archive
        if dest_path.exists():
            stem = dest_path.stem
            suffix = dest_path.suffix
            counter = 1
            while dest_path.exists():
                dest_path = archive_dir / f"{stem}_{counter}{suffix}"
                counter += 1

        shutil.move(str(src_path), str(dest_path))
        logger.info(f"Archived {src_path} -> {dest_path}")

        # Delete chunks from ChromaDB
        _retry_on_transient(document_store.delete_by_source, source)
        logger.info(f"Deleted document chunks for archived source: {source}")

        # Update _index.md
        index_path = jarvis_root / "_index.md"
        index_updated = False
        if index_path.exists():
            try:
                lines = index_path.read_text().splitlines(keepends=True)
                filtered = [line for line in lines if source not in line]
                if len(filtered) < len(lines):
                    index_path.write_text("".join(filtered))
                    index_updated = True
            except OSError as exc:
                logger.warning(f"Could not update _index.md: {exc}")

        result = {
            "message": f"Archived '{source}'.",
            "old_path": str(src_path),
            "new_path": str(dest_path),
            "chunks_deleted": True,
            "index_updated": index_updated,
        }
        if reason:
            result["reason"] = reason
        return json.dumps(result)

    # Expose tool functions at module level for testing
    import sys
    module = sys.modules[__name__]
    module.search_documents = search_documents
    module.ingest_documents = ingest_documents
    module.list_documents = list_documents
    module.delete_document = delete_document
    module.archive_document = archive_document
