from pathlib import Path
from typing import Optional

import chromadb
from chromadb.config import Settings


class DocumentStore:
    def __init__(self, persist_dir: Path):
        self.client = chromadb.Client(Settings(
            persist_directory=str(persist_dir),
            is_persistent=True,
            anonymized_telemetry=False,
        ))
        self.collection = self.client.get_or_create_collection(
            name="chief_of_staff_docs",
            metadata={"hnsw:space": "cosine"},
        )

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
