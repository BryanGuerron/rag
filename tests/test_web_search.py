import pytest

from rag_alura.web_search import PublicWebSearch, WebSearchError


def test_web_search_filters_invalid_and_duplicate_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    raw_results = [
        {"title": "One", "href": "https://example.com/one", "body": "First"},
        {"title": "Duplicate", "href": "https://example.com/one", "body": "Again"},
        {"title": "Invalid", "href": "javascript:alert(1)", "body": "Bad"},
    ]

    class FakeDDGS:
        @staticmethod
        def text(query: str, max_results: int):
            return raw_results

    monkeypatch.setattr("rag_alura.web_search.DDGS", FakeDDGS)

    results = PublicWebSearch(max_results=3).search("test")

    assert len(results) == 1
    assert results[0].url == "https://example.com/one"


def test_web_search_wraps_provider_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    class BrokenDDGS:
        @staticmethod
        def text(query: str, max_results: int):
            raise OSError("offline")

    monkeypatch.setattr("rag_alura.web_search.DDGS", BrokenDDGS)

    with pytest.raises(WebSearchError, match="temporarily unavailable"):
        PublicWebSearch().search("test")


def test_empty_query_skips_provider() -> None:
    assert PublicWebSearch().search("  ") == []
