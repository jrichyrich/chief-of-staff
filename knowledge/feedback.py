"""Output feedback — extract key findings from generated documents and store as facts.

When Jarvis generates a document (weekly brief, analysis, meeting prep),
this module extracts the 3-5 most important findings and stores them as
facts so they persist in the knowledge base for future queries.
"""

import logging
from typing import TYPE_CHECKING

import anthropic

from config import MODEL_TIERS, ANTHROPIC_API_KEY

if TYPE_CHECKING:
    from memory.store import MemoryStore

logger = logging.getLogger(__name__)

_EXTRACT_PROMPT = """Extract the 3-5 most important findings, decisions, or status updates from this document.
Return them as a simple bulleted list (one bullet per finding).
Each bullet should be a single, self-contained sentence.
Focus on facts that would be useful to recall in future conversations.
Do NOT include meta-commentary or formatting instructions.

Document:
{text}"""

_MIN_WORDS = 50
_MAX_INPUT_WORDS = 4000


def extract_and_store_findings(
    document_text: str,
    source: str,
    memory_store: "MemoryStore",
) -> list[str]:
    """Extract key findings from a document and store them as facts.

    Args:
        document_text: Full text of the generated document.
        source: Identifier (e.g., "weekly_cio_brief_2026-04-01").
        memory_store: MemoryStore for fact storage.

    Returns:
        List of extracted finding strings, or empty list on failure.
    """
    if not document_text or len(document_text.split()) < _MIN_WORDS:
        return []

    truncated = " ".join(document_text.split()[:_MAX_INPUT_WORDS])

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model=MODEL_TIERS["haiku"],
            max_tokens=512,
            messages=[{"role": "user", "content": _EXTRACT_PROMPT.format(text=truncated)}],
        )
        raw_output = response.content[0].text
    except Exception:
        logger.exception("Failed to extract findings from document")
        return []

    # Parse bullet points
    findings = []
    for line in raw_output.strip().splitlines():
        line = line.strip().lstrip("-•*").strip()
        if line:
            findings.append(line)

    # Store each finding as a fact (cap at 5)
    from memory.models import Fact

    for i, finding in enumerate(findings[:5]):
        fact = Fact(
            category="work",
            key=f"{source}_finding_{i}",
            value=finding,
            confidence=0.7,
            source=f"output_feedback:{source}",
        )
        try:
            memory_store.store_fact(fact)
        except Exception:
            logger.warning("Failed to store finding %d from %s", i, source, exc_info=True)

    return findings
