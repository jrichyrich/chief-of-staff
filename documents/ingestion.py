import hashlib
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from documents.store import DocumentStore

SUPPORTED_EXTENSIONS = {".txt", ".md", ".py", ".json", ".yaml", ".yml", ".pdf", ".docx"}


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    words = text.split()
    if len(words) <= chunk_size:
        return [text]

    chunks = []
    start = 0
    while start < len(words):
        end = start + chunk_size
        chunk = " ".join(words[start:end])
        chunks.append(chunk)
        start = end - overlap

    return chunks


def _load_pdf(file_path: Path) -> str:
    """Load text from a PDF file."""
    try:
        from pypdf import PdfReader
    except ImportError:
        raise ImportError("pypdf library is required for PDF support. Install with: pip install pypdf")

    reader = PdfReader(file_path)
    text_parts = []
    for page in reader.pages:
        page_text = page.extract_text()
        if page_text.strip():  # Only add non-empty pages
            text_parts.append(page_text)

    return "\n".join(text_parts)


def _load_docx(file_path: Path) -> str:
    """Load text from a DOCX file."""
    try:
        from docx import Document
    except ImportError:
        raise ImportError("python-docx library is required for DOCX support. Install with: pip install python-docx")

    doc = Document(file_path)
    text_parts = []

    # Extract paragraph text
    for paragraph in doc.paragraphs:
        if paragraph.text.strip():
            text_parts.append(paragraph.text)

    # Extract table text
    for table in doc.tables:
        for row in table.rows:
            row_text = " | ".join(cell.text.strip() for cell in row.cells if cell.text.strip())
            if row_text:
                text_parts.append(row_text)

    return "\n".join(text_parts)


def load_text_file(path: Path) -> str:
    """Load text from a file based on its extension."""
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        return _load_pdf(path)
    elif suffix == ".docx":
        return _load_docx(path)
    else:
        return path.read_text(encoding="utf-8")


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def ingest_path(path: Path, document_store: "DocumentStore") -> str:
    """Ingest a file or directory into the document store.

    Returns a summary string of what was ingested.
    """
    files = []

    if path.is_file():
        files = [path]
    elif path.is_dir():
        for ext in SUPPORTED_EXTENSIONS:
            files.extend(path.glob(f"**/*{ext}"))

    if not files:
        return f"No supported files found at {path}"

    total_chunks = 0
    for file in files:
        text = load_text_file(file)
        chunks = chunk_text(text)
        file_hash = content_hash(text)

        texts = []
        metadatas = []
        ids = []
        for i, chunk in enumerate(chunks):
            texts.append(chunk)
            metadatas.append({"source": str(file.name), "chunk_index": i})
            ids.append(f"{file_hash}_{i}")

        document_store.add_documents(texts=texts, metadatas=metadatas, ids=ids)
        total_chunks += len(chunks)

    return f"Ingested {len(files)} file(s), {total_chunks} chunks."
