from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


class ConfigurationError(RuntimeError):
    """Raised when required application configuration is missing or invalid."""


def _integer(name: str, default: int, minimum: int = 1) -> int:
    raw_value = os.getenv(name, str(default))
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer.") from exc
    if value < minimum:
        raise ConfigurationError(f"{name} must be at least {minimum}.")
    return value


def _decimal(name: str, default: float, minimum: float, maximum: float) -> float:
    raw_value = os.getenv(name, str(default))
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be a number.") from exc
    if not minimum <= value <= maximum:
        raise ConfigurationError(f"{name} must be between {minimum} and {maximum}.")
    return value


@dataclass(frozen=True)
class Settings:
    root_dir: Path
    docs_dir: Path
    data_dir: Path
    uploads_dir: Path
    vector_dir: Path
    manifest_path: Path
    google_api_key: str
    chat_model: str
    embedding_model: str
    chunk_size: int
    chunk_overlap: int
    top_k: int
    minimum_relevance: float
    max_upload_bytes: int
    web_search_results: int
    embedding_batch_size: int
    embedding_max_retries: int
    embedding_retry_delay: float

    @classmethod
    def from_env(cls, root_dir: Path | None = None) -> Settings:
        root = (root_dir or Path.cwd()).resolve()
        load_dotenv(root / ".env")

        data_dir = Path(os.getenv("DATA_DIR", str(root / "data"))).resolve()
        chunk_size = _integer("RAG_CHUNK_SIZE", 1200, minimum=200)
        chunk_overlap = _integer("RAG_CHUNK_OVERLAP", 200, minimum=0)
        if chunk_overlap >= chunk_size:
            raise ConfigurationError("RAG_CHUNK_OVERLAP must be smaller than RAG_CHUNK_SIZE.")

        return cls(
            root_dir=root,
            docs_dir=Path(os.getenv("DOCS_DIR", str(root / "docs"))).resolve(),
            data_dir=data_dir,
            uploads_dir=data_dir / "uploads",
            vector_dir=data_dir / "chroma",
            manifest_path=data_dir / "manifest.json",
            google_api_key=os.getenv("GOOGLE_API_KEY", "").strip(),
            chat_model=os.getenv("GOOGLE_CHAT_MODEL", "gemini-3.1-flash-lite"),
            embedding_model=os.getenv(
                "GOOGLE_EMBEDDING_MODEL", "models/gemini-embedding-001"
            ),
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            top_k=_integer("RAG_TOP_K", 4),
            minimum_relevance=_decimal("RAG_MIN_RELEVANCE", 0.2, 0.0, 1.0),
            max_upload_bytes=_integer("MAX_UPLOAD_MB", 20) * 1024 * 1024,
            web_search_results=_integer("WEB_SEARCH_RESULTS", 5),
            embedding_batch_size=_integer("EMBEDDING_BATCH_SIZE", 50),
            embedding_max_retries=_integer("EMBEDDING_MAX_RETRIES", 5, minimum=0),
            embedding_retry_delay=_decimal("EMBEDDING_RETRY_DELAY", 20.0, 0.0, 300.0),
        )

    def prepare_directories(self) -> None:
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.vector_dir.mkdir(parents=True, exist_ok=True)

    def require_google_key(self) -> None:
        if not self.google_api_key:
            raise ConfigurationError(
                "GOOGLE_API_KEY is required. Create .env from .env.example and add the key."
            )
