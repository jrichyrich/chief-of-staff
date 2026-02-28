from pathlib import Path
from typing import Optional

import chromadb
from chromadb.config import Settings


COLLECTION_NAME = "jarvis_docs"
_OLD_COLLECTION_NAME = "chief_of_staff_docs"


class DocumentStore:
    def __init__(self, persist_dir: Path):
        self.client = chromadb.Client(Settings(
            persist_directory=str(persist_dir),
            is_persistent=True,
            anonymized_telemetry=False,
        ))
        self._migrate_collection_name()
        self.collection = self.client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )

    def _migrate_collection_name(self) -> None:
        """Rename legacy collection from chief_of_staff_docs to jarvis_docs."""
        existing = {c.name for c in self.client.list_collections()}
        if _OLD_COLLECTION_NAME in existing and COLLECTION_NAME not in existing:
            old = self.client.get_collection(_OLD_COLLECTION_NAME)
            old.modify(name=COLLECTION_NAME)

    def add_documents(
        self,
        texts: list[str],
        metadatas: list[dict],
        ids: list[str],
    ) -> None:
        self.collection.add(documents=texts, metadatas=metadatas, ids=ids)

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        if self.collection.count() == 0:
            return []
        results = self.collection.query(query_texts=[query], n_results=top_k)
        output = []
        for i in range(len(results["documents"][0])):
            output.append({
                "text": results["documents"][0][i],
                "metadata": results["metadatas"][0][i],
                "distance": results["distances"][0][i] if results.get("distances") else None,
            })
        return output
