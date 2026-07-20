from types import SimpleNamespace

import pytest
from langchain_core.documents import Document

from rag_alura.assistant import (
    DOCUMENT_NOT_FOUND_MESSAGE,
    WEB_NOT_FOUND_MESSAGE,
    DocumentAssistant,
)
from rag_alura.config import Settings
from rag_alura.knowledge_base import RetrievedChunk
from rag_alura.web_search import WebResult


class FakeKnowledgeBase:
    def __init__(self, results: list[RetrievedChunk]) -> None:
        self.results = results
        self.queries: list[str] = []

    def search(self, query: str) -> list[RetrievedChunk]:
        self.queries.append(query)
        return self.results


class FakeModel:
    def __init__(self, content: object) -> None:
        self.content = content
        self.calls: list[object] = []

    def invoke(self, messages: object) -> SimpleNamespace:
        self.calls.append(messages)
        return SimpleNamespace(content=self.content)


class FakeWebSearch:
    def __init__(self, results: list[WebResult]) -> None:
        self.results = results
        self.queries: list[str] = []

    def search(self, query: str) -> list[WebResult]:
        self.queries.append(query)
        return self.results


def assistant_settings(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    return Settings.from_env(tmp_path)


def document_chunk(source: str = "guide.pdf", page: int = 4) -> RetrievedChunk:
    return RetrievedChunk(
        Document(
            page_content="The backend uses Java 17 and Spring Boot 3.",
            metadata={"source": source, "locator": f"page {page}", "page": page},
        ),
        relevance=0.9,
    )


def test_document_answer_only_returns_citations_used_by_model(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    knowledge_base = FakeKnowledgeBase([document_chunk(), document_chunk("other.pdf", 8)])
    model = FakeModel("El back-end usa Java 17 y Spring Boot 3 [S1].")
    assistant = DocumentAssistant(
        assistant_settings(tmp_path, monkeypatch), knowledge_base, model=model
    )

    answer = assistant.answer_from_documents("¿Qué usa el backend?")

    assert answer.found is True
    assert answer.source_type == "documents"
    assert [citation.label for citation in answer.citations] == ["S1"]
    assert answer.citations[0].locator == "page 4"


def test_grouped_citation_labels_are_recognized(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    knowledge_base = FakeKnowledgeBase([document_chunk(), document_chunk("other.pdf", 8)])
    assistant = DocumentAssistant(
        assistant_settings(tmp_path, monkeypatch),
        knowledge_base,
        model=FakeModel("El back-end usa Java 17 y Spring Boot 3 [S1, S2]."),
    )

    answer = assistant.answer_from_documents("¿Qué usa el backend?")

    assert answer.found is True
    assert [citation.label for citation in answer.citations] == ["S1", "S2"]


def test_citation_carries_the_page_for_deep_linking(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assistant = DocumentAssistant(
        assistant_settings(tmp_path, monkeypatch),
        FakeKnowledgeBase([document_chunk("manual.pdf", 24)]),
        model=FakeModel("Necesita dos aprobaciones [S1]."),
    )

    answer = assistant.answer_from_documents("¿Cuántas aprobaciones?")

    assert answer.citations[0].page == 24


def test_citation_page_is_absent_for_sources_without_pages(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    chunk = RetrievedChunk(
        Document(page_content="producto: Mouse", metadata={"source": "ventas.csv", "row": 2}),
        relevance=0.9,
    )
    assistant = DocumentAssistant(
        assistant_settings(tmp_path, monkeypatch),
        FakeKnowledgeBase([chunk]),
        model=FakeModel("El producto es Mouse [S1]."),
    )

    answer = assistant.answer_from_documents("¿Qué producto?")

    assert answer.citations[0].page is None


def test_document_answer_rejects_unsupported_model_output(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assistant = DocumentAssistant(
        assistant_settings(tmp_path, monkeypatch),
        FakeKnowledgeBase([document_chunk()]),
        model=FakeModel("El back-end usa Java."),
    )

    answer = assistant.answer_from_documents("¿Qué usa?")

    assert answer.found is False
    assert answer.content == DOCUMENT_NOT_FOUND_MESSAGE


def test_no_retrieval_result_does_not_call_model(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = FakeModel("should not be called")
    assistant = DocumentAssistant(
        assistant_settings(tmp_path, monkeypatch), FakeKnowledgeBase([]), model=model
    )

    answer = assistant.answer_from_documents("¿Quién ganó el mundial?")

    assert answer.found is False
    assert model.calls == []


def test_previous_user_questions_are_added_to_retrieval_query(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    knowledge_base = FakeKnowledgeBase([document_chunk()])
    assistant = DocumentAssistant(
        assistant_settings(tmp_path, monkeypatch),
        knowledge_base,
        model=FakeModel("Usa Java [S1]."),
    )

    assistant.answer_from_documents(
        "¿Y el framework?",
        history=[
            {"role": "user", "content": "¿Qué lenguaje usa el backend?"},
            {"role": "assistant", "content": "Java [S1]."},
        ],
    )

    assert "¿Qué lenguaje usa el backend?" in knowledge_base.queries[0]
    assert "¿Y el framework?" in knowledge_base.queries[0]


def test_web_answer_is_separate_and_keeps_links(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    web_search = FakeWebSearch(
        [WebResult("Oracle documentation", "https://docs.oracle.com/example", "OCI example")]
    )
    assistant = DocumentAssistant(
        assistant_settings(tmp_path, monkeypatch),
        FakeKnowledgeBase([]),
        web_search=web_search,
        model=FakeModel("Según una consulta web pública, OCI ofrece Compute [W1]."),
    )

    answer = assistant.answer_from_web_after_consent("¿Qué ofrece OCI?")

    assert answer.found is True
    assert answer.source_type == "web"
    assert answer.citations[0].url == "https://docs.oracle.com/example"
    assert web_search.queries == ["¿Qué ofrece OCI?"]


def test_empty_web_results_return_clear_message(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = FakeModel("should not be called")
    assistant = DocumentAssistant(
        assistant_settings(tmp_path, monkeypatch),
        FakeKnowledgeBase([]),
        web_search=FakeWebSearch([]),
        model=model,
    )

    answer = assistant.answer_from_web_after_consent("unknown")

    assert answer.content == WEB_NOT_FOUND_MESSAGE
    assert answer.found is False
    assert model.calls == []


def test_list_content_blocks_are_converted_to_text(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assistant = DocumentAssistant(
        assistant_settings(tmp_path, monkeypatch),
        FakeKnowledgeBase([document_chunk()]),
        model=FakeModel([{"type": "text", "text": "Usa Java [S1]."}]),
    )

    answer = assistant.answer_from_documents("¿Qué usa?")

    assert answer.found is True
    assert answer.content == "Usa Java [S1]."
