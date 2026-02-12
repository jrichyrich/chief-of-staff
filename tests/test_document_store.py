import pytest
from pathlib import Path
from documents.store import DocumentStore
from documents.ingestion import chunk_text, load_text_file


@pytest.fixture
def doc_store(tmp_path):
    store = DocumentStore(persist_dir=tmp_path / "chroma")
    yield store


class TestDocumentStore:
    def test_add_and_search(self, doc_store):
        doc_store.add_documents(
            texts=["Python is a programming language", "The weather is sunny today"],
            metadatas=[{"source": "doc1.txt"}, {"source": "doc2.txt"}],
            ids=["chunk_1", "chunk_2"],
        )
        results = doc_store.search("programming", top_k=1)
        assert len(results) == 1
        assert "Python" in results[0]["text"]

    def test_search_returns_metadata(self, doc_store):
        doc_store.add_documents(
            texts=["Claude is an AI assistant"],
            metadatas=[{"source": "ai.txt", "page": 1}],
            ids=["chunk_1"],
        )
        results = doc_store.search("AI assistant", top_k=1)
        assert results[0]["metadata"]["source"] == "ai.txt"

    def test_search_empty_store(self, doc_store):
        results = doc_store.search("anything", top_k=5)
        assert results == []

    def test_search_top_k(self, doc_store):
        texts = [f"Document number {i}" for i in range(10)]
        metadatas = [{"source": f"doc_{i}.txt"} for i in range(10)]
        ids = [f"chunk_{i}" for i in range(10)]
        doc_store.add_documents(texts=texts, metadatas=metadatas, ids=ids)
        results = doc_store.search("Document", top_k=3)
        assert len(results) == 3


class TestChunking:
    def test_chunk_short_text(self):
        chunks = chunk_text("Hello world", chunk_size=100, overlap=10)
        assert len(chunks) == 1
        assert chunks[0] == "Hello world"

    def test_chunk_long_text(self):
        words = ["word"] * 200
        text = " ".join(words)
        chunks = chunk_text(text, chunk_size=50, overlap=10)
        assert len(chunks) > 1
        for chunk in chunks:
            assert len(chunk.split()) <= 50

    def test_chunk_overlap(self):
        words = [f"word{i}" for i in range(100)]
        text = " ".join(words)
        chunks = chunk_text(text, chunk_size=30, overlap=5)
        assert len(chunks) >= 2
        # Overlap means end of chunk N shares words with start of chunk N+1
        first_end_words = chunks[0].split()[-5:]
        second_start_words = chunks[1].split()[:5]
        assert first_end_words == second_start_words


class TestIngestion:
    def test_load_text_file(self, tmp_path):
        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello, this is a test document.")
        text = load_text_file(test_file)
        assert text == "Hello, this is a test document."

    def test_load_markdown_file(self, tmp_path):
        test_file = tmp_path / "test.md"
        test_file.write_text("# Title\n\nSome content here.")
        text = load_text_file(test_file)
        assert "Title" in text
        assert "Some content here." in text
