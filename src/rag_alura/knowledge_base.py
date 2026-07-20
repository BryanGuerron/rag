from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from rag_alura.config import Settings
from rag_alura.documents import DocumentLoader, supported_files


def _is_rate_limited(error: Exception) -> bool:
    message = str(error).lower()
    return "429" in message or "resource_exhausted" in message or "quota" in message


@dataclass(frozen=True)
class IndexResult:
    source: str
    chunks: int
    status: str


@dataclass(frozen=True)
class RetrievedChunk:
    document: Document
    relevance: float


class Manifest:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._data = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "sources": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {"version": 1, "sources": {}}
        if not isinstance(data.get("sources"), dict):
            return {"version": 1, "sources": {}}
        return data

    def get(self, source_key: str) -> dict[str, Any] | None:
        return self._data["sources"].get(source_key)

    def set(self, source_key: str, record: dict[str, Any]) -> None:
        self._data["sources"][source_key] = record
        self._save()

    def sources(self) -> list[dict[str, Any]]:
        return sorted(self._data["sources"].values(), key=lambda item: item["source"])

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.path.with_suffix(".tmp")
        temporary_path.write_text(
            json.dumps(self._data, ensure_ascii=True, indent=2), encoding="utf-8"
        )
        temporary_path.replace(self.path)


class KnowledgeBase:
    def __init__(
        self,
        settings: Settings,
        vector_store: Any | None = None,
        loader: DocumentLoader | None = None,
    ) -> None:
        self.settings = settings
        self.settings.prepare_directories()
        self.loader = loader or DocumentLoader()
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
            add_start_index=True,
        )
        self.manifest = Manifest(settings.manifest_path)
        self.vector_store = vector_store or self._create_vector_store()

    def _create_vector_store(self) -> Chroma:
        self.settings.require_google_key()
        embeddings = GoogleGenerativeAIEmbeddings(
            model=self.settings.embedding_model,
            google_api_key=self.settings.google_api_key,
        )
        return Chroma(
            collection_name="rag_alura_documents",
            embedding_function=embeddings,
            persist_directory=str(self.settings.vector_dir),
            collection_metadata={"hnsw:space": "cosine"},
        )

    def index_file(self, path: Path) -> IndexResult:
        path = path.resolve()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        source_key = self._source_key(path)
        existing = self.manifest.get(source_key)
        if existing and existing.get("digest") == digest:
            return IndexResult(path.name, int(existing["chunks"]), "unchanged")

        pages_or_rows = self.loader.load(path)
        chunks = self.splitter.split_documents(pages_or_rows)
        if not chunks:
            return IndexResult(path.name, 0, "empty")

        chunk_ids = [
            hashlib.sha256(f"{source_key}:{digest}:{position}".encode()).hexdigest()
            for position in range(len(chunks))
        ]
        self._add_documents_in_batches(chunks, chunk_ids)

        if existing and existing.get("ids"):
            self.vector_store.delete(ids=existing["ids"])

        self.manifest.set(
            source_key,
            {
                "source": path.name,
                "source_key": source_key,
                "digest": digest,
                "chunks": len(chunks),
                "ids": chunk_ids,
                "kind": path.suffix.lower().lstrip("."),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        return IndexResult(path.name, len(chunks), "indexed")

    def _add_documents_in_batches(
        self, chunks: list[Document], chunk_ids: list[str]
    ) -> None:
        size = self.settings.embedding_batch_size
        for start in range(0, len(chunks), size):
            self._add_batch_with_retry(
                chunks[start : start + size], chunk_ids[start : start + size]
            )

    def _add_batch_with_retry(self, batch: list[Document], batch_ids: list[str]) -> None:
        delay = self.settings.embedding_retry_delay
        for attempt in range(self.settings.embedding_max_retries + 1):
            try:
                self.vector_store.add_documents(documents=batch, ids=batch_ids)
                return
            except Exception as exc:
                if attempt == self.settings.embedding_max_retries or not _is_rate_limited(exc):
                    raise
                time.sleep(delay)
                delay *= 2

    def index_directories(self, *directories: Path) -> list[IndexResult]:
        results: list[IndexResult] = []
        for directory in directories:
            for path in supported_files(directory):
                results.append(self.index_file(path))
        return results

    def search(self, query: str) -> list[RetrievedChunk]:
        if not query.strip():
            return []
        results = self.vector_store.similarity_search_with_relevance_scores(
            query,
            k=self.settings.top_k,
        )
        return [
            RetrievedChunk(document=document, relevance=float(score))
            for document, score in results
            if float(score) >= self.settings.minimum_relevance
        ]

    def list_sources(self) -> list[dict[str, Any]]:
        return self.manifest.sources()

    def _source_key(self, path: Path) -> str:
        try:
            return path.relative_to(self.settings.root_dir).as_posix()
        except ValueError:
            return path.as_posix()
