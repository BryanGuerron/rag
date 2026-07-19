from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from rag_alura.config import Settings
from rag_alura.documents import DocumentLoader, supported_files


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
        self.settings.require_openai_key()
        embeddings = OpenAIEmbeddings(
            model=self.settings.embedding_model,
            api_key=self.settings.openai_api_key,
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
        self.vector_store.add_documents(documents=chunks, ids=chunk_ids)

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
