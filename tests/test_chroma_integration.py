from pathlib import Path

import pytest
from langchain_chroma import Chroma
from langchain_core.embeddings import Embeddings

from rag_alura.config import Settings
from rag_alura.knowledge_base import KnowledgeBase


class KeywordEmbeddings(Embeddings):
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_query(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        normalized = text.lower()
        return [
            1.0 if "mouse" in normalized else 0.0,
            1.0 if "keyboard" in normalized else 0.0,
            0.1,
        ]


def test_chroma_indexes_and_retrieves_csv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RAG_CHUNK_SIZE", "200")
    monkeypatch.setenv("RAG_CHUNK_OVERLAP", "20")
    monkeypatch.setenv("RAG_MIN_RELEVANCE", "0")
    settings = Settings.from_env(tmp_path)
    vector_store = Chroma(
        collection_name="integration_test",
        embedding_function=KeywordEmbeddings(),
        persist_directory=str(tmp_path / "chroma-test"),
        collection_metadata={"hnsw:space": "cosine"},
    )
    knowledge_base = KnowledgeBase(settings, vector_store=vector_store)
    csv_path = tmp_path / "sales.csv"
    csv_path.write_text("product,total\nKeyboard,10\nMouse,25\n", encoding="utf-8")

    index_result = knowledge_base.index_file(csv_path)
    search_results = knowledge_base.search("Mouse sales")

    assert index_result.chunks == 2
    assert search_results
    assert search_results[0].document.metadata["source"] == "sales.csv"
