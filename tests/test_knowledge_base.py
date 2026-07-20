from pathlib import Path

import pytest
from langchain_core.documents import Document

from rag_alura.config import Settings
from rag_alura.knowledge_base import KnowledgeBase


class FakeVectorStore:
    def __init__(self) -> None:
        self.added: list[tuple[list[Document], list[str]]] = []
        self.deleted: list[list[str]] = []
        self.search_results: list[tuple[Document, float]] = []

    def add_documents(self, documents: list[Document], ids: list[str]) -> None:
        self.added.append((documents, ids))

    def delete(self, ids: list[str]) -> None:
        self.deleted.append(ids)

    def similarity_search_with_relevance_scores(
        self, query: str, k: int
    ) -> list[tuple[Document, float]]:
        return self.search_results[:k]


def settings_for(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("RAG_CHUNK_SIZE", "200")
    monkeypatch.setenv("RAG_CHUNK_OVERLAP", "20")
    monkeypatch.setenv("RAG_MIN_RELEVANCE", "0.5")
    return Settings.from_env(tmp_path)


def test_indexing_same_content_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vector_store = FakeVectorStore()
    knowledge_base = KnowledgeBase(settings_for(tmp_path, monkeypatch), vector_store=vector_store)
    csv_path = tmp_path / "sales.csv"
    csv_path.write_text("product,total\nMouse,25\n", encoding="utf-8")

    first = knowledge_base.index_file(csv_path)
    second = knowledge_base.index_file(csv_path)

    assert first.status == "indexed"
    assert second.status == "unchanged"
    assert len(vector_store.added) == 1
    assert vector_store.deleted == []


def test_changed_source_replaces_previous_chunks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vector_store = FakeVectorStore()
    knowledge_base = KnowledgeBase(settings_for(tmp_path, monkeypatch), vector_store=vector_store)
    csv_path = tmp_path / "sales.csv"
    csv_path.write_text("product,total\nMouse,25\n", encoding="utf-8")
    knowledge_base.index_file(csv_path)
    old_ids = vector_store.added[0][1]

    csv_path.write_text("product,total\nMouse,30\n", encoding="utf-8")
    result = knowledge_base.index_file(csv_path)

    assert result.status == "indexed"
    assert vector_store.deleted == [old_ids]
    assert vector_store.added[1][1] != old_ids


def test_search_filters_low_relevance_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vector_store = FakeVectorStore()
    vector_store.search_results = [
        (Document(page_content="relevant", metadata={"source": "a.pdf"}), 0.9),
        (Document(page_content="noise", metadata={"source": "b.pdf"}), 0.2),
    ]
    knowledge_base = KnowledgeBase(settings_for(tmp_path, monkeypatch), vector_store=vector_store)

    results = knowledge_base.search("backend language")

    assert len(results) == 1
    assert results[0].document.page_content == "relevant"
    assert results[0].relevance == 0.9


class RateLimitedVectorStore(FakeVectorStore):
    def __init__(self, failures: int) -> None:
        super().__init__()
        self.remaining_failures = failures
        self.attempts = 0

    def add_documents(self, documents: list[Document], ids: list[str]) -> None:
        self.attempts += 1
        if self.remaining_failures > 0:
            self.remaining_failures -= 1
            raise RuntimeError("429 RESOURCE_EXHAUSTED: quota exceeded")
        super().add_documents(documents, ids)


def test_chunks_are_embedded_in_batches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EMBEDDING_BATCH_SIZE", "2")
    vector_store = FakeVectorStore()
    knowledge_base = KnowledgeBase(settings_for(tmp_path, monkeypatch), vector_store=vector_store)
    csv_path = tmp_path / "sales.csv"
    csv_path.write_text("product,total\nA,1\nB,2\nC,3\nD,4\nE,5\n", encoding="utf-8")

    result = knowledge_base.index_file(csv_path)

    assert result.chunks == 5
    assert len(vector_store.added) == 3
    assert [len(documents) for documents, _ in vector_store.added] == [2, 2, 1]


def test_rate_limited_batch_is_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EMBEDDING_RETRY_DELAY", "0")
    vector_store = RateLimitedVectorStore(failures=2)
    knowledge_base = KnowledgeBase(settings_for(tmp_path, monkeypatch), vector_store=vector_store)
    csv_path = tmp_path / "sales.csv"
    csv_path.write_text("product,total\nMouse,25\n", encoding="utf-8")

    result = knowledge_base.index_file(csv_path)

    assert result.status == "indexed"
    assert vector_store.attempts == 3


def test_non_rate_limit_errors_are_not_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EMBEDDING_RETRY_DELAY", "0")

    class BrokenVectorStore(FakeVectorStore):
        def __init__(self) -> None:
            super().__init__()
            self.attempts = 0

        def add_documents(self, documents: list[Document], ids: list[str]) -> None:
            self.attempts += 1
            raise RuntimeError("invalid api key")

    vector_store = BrokenVectorStore()
    knowledge_base = KnowledgeBase(settings_for(tmp_path, monkeypatch), vector_store=vector_store)
    csv_path = tmp_path / "sales.csv"
    csv_path.write_text("product,total\nMouse,25\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="invalid api key"):
        knowledge_base.index_file(csv_path)

    assert vector_store.attempts == 1


def test_manifest_recovers_from_invalid_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = settings_for(tmp_path, monkeypatch)
    settings.data_dir.mkdir(parents=True)
    settings.manifest_path.write_text("not-json", encoding="utf-8")

    knowledge_base = KnowledgeBase(settings, vector_store=FakeVectorStore())

    assert knowledge_base.list_sources() == []
