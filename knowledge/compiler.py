"""Document summary compilation via LLM.

Generates concise summaries of ingested documents using Haiku,
storing them as additional ChromaDB entries alongside raw chunks.
"""

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

import anthropic

from config import MODEL_TIERS, ANTHROPIC_API_KEY

if TYPE_CHECKING:
    from documents.store import DocumentStore

logger = logging.getLogger(__name__)

_SUMMARY_PROMPT = """Summarize this document in 2-4 sentences. Focus on:
- What the document is about (topic, purpose)
- Key facts, decisions, or conclusions
- Who/what is involved

Be concise and factual. Do not include meta-commentary like "This document discusses..."

Document text:
{text}"""

_MIN_WORDS = 50
_MAX_INPUT_WORDS = 3000


def generate_summary(text: str) -> Optional[str]:
    """Generate a summary of the given text using Haiku.
    Returns the summary string, or None if text is too short, empty, or API fails.
    """
    if not text or not text.strip():
        return None
    words = text.split()
    if len(words) < _MIN_WORDS:
        return None
    truncated = " ".join(words[:_MAX_INPUT_WORDS])
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model=MODEL_TIERS["haiku"],
            max_tokens=512,
            messages=[{"role": "user", "content": _SUMMARY_PROMPT.format(text=truncated)}],
        )
        return response.content[0].text
    except Exception:
        logger.exception("Failed to generate document summary")
        return None


def compile_document_summary(text, source, file_hash, document_store):
    """Generate a summary and store it in the document store with doc_type="summary" metadata.
    Returns the summary text, or None if skipped.
    """
    summary = generate_summary(text)
    if summary is None:
        return None
    now = datetime.now(timezone.utc).isoformat()
    document_store.add_documents(
        texts=[summary],
        metadatas=[{"source": source, "doc_type": "summary", "chunk_index": -1, "created_at": now}],
        ids=[f"{file_hash}_summary"],
    )
    logger.info("Stored summary for %s (%d chars)", source, len(summary))
    return summary
