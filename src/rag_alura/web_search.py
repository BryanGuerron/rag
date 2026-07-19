from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from ddgs import DDGS


class WebSearchError(RuntimeError):
    """Raised when the public web search provider is unavailable."""


@dataclass(frozen=True)
class WebResult:
    title: str
    url: str
    snippet: str


class PublicWebSearch:
    def __init__(self, max_results: int = 5) -> None:
        self.max_results = max_results

    def search(self, query: str) -> list[WebResult]:
        if not query.strip():
            return []
        try:
            raw_results = DDGS().text(query, max_results=self.max_results)
        except Exception as exc:
            raise WebSearchError("The public web search is temporarily unavailable.") from exc

        results: list[WebResult] = []
        seen_urls: set[str] = set()
        for item in raw_results:
            url = str(item.get("href") or item.get("url") or "").strip()
            if not self._is_public_url(url) or url in seen_urls:
                continue
            seen_urls.add(url)
            results.append(
                WebResult(
                    title=str(item.get("title") or url).strip(),
                    url=url,
                    snippet=str(item.get("body") or item.get("snippet") or "").strip(),
                )
            )
        return results

    @staticmethod
    def _is_public_url(url: str) -> bool:
        parsed = urlparse(url)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
