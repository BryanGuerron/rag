from pathlib import Path

import pytest

from rag_alura.config import ConfigurationError, Settings


def test_settings_builds_project_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATA_DIR", raising=False)
    monkeypatch.setenv("RAG_CHUNK_SIZE", "800")
    monkeypatch.setenv("RAG_CHUNK_OVERLAP", "100")

    settings = Settings.from_env(tmp_path)

    assert settings.docs_dir == tmp_path / "docs"
    assert settings.uploads_dir == tmp_path / "data" / "uploads"
    assert settings.chunk_size == 800


def test_settings_rejects_overlap_larger_than_chunk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RAG_CHUNK_SIZE", "300")
    monkeypatch.setenv("RAG_CHUNK_OVERLAP", "300")

    with pytest.raises(ConfigurationError, match="smaller"):
        Settings.from_env(tmp_path)


def test_openai_key_is_required_for_model_operations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    settings = Settings.from_env(tmp_path)

    with pytest.raises(ConfigurationError, match="OPENAI_API_KEY"):
        settings.require_openai_key()
