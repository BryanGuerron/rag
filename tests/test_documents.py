from pathlib import Path

import pytest

from rag_alura.documents import (
    DocumentLoader,
    DocumentProcessingError,
    sanitize_filename,
    save_uploaded_file,
    supported_files,
)


def test_csv_rows_keep_source_and_spreadsheet_row(tmp_path: Path) -> None:
    csv_path = tmp_path / "sales.csv"
    csv_path.write_text("product,total\nKeyboard,10\nMouse,25\n", encoding="utf-8")

    documents = DocumentLoader().load(csv_path)

    assert len(documents) == 2
    assert documents[0].metadata["source"] == "sales.csv"
    assert documents[0].metadata["row"] == 2
    assert documents[1].metadata["locator"] == "row 3"
    assert "product: Mouse" in documents[1].page_content


def test_empty_csv_is_rejected(tmp_path: Path) -> None:
    csv_path = tmp_path / "empty.csv"
    csv_path.write_text("name,total\n", encoding="utf-8")

    with pytest.raises(DocumentProcessingError, match="no data rows"):
        DocumentLoader().load(csv_path)


def test_pdf_pages_without_text_are_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Page:
        def __init__(self, text: str | None) -> None:
            self.text = text

        def extract_text(self) -> str | None:
            return self.text

    class Reader:
        is_encrypted = False
        pages = [Page(None), Page("Backend uses Java 17.")]

    monkeypatch.setattr("rag_alura.documents.PdfReader", lambda _: Reader())
    path = tmp_path / "guide.pdf"
    path.write_bytes(b"fake")

    documents = DocumentLoader().load(path)

    assert len(documents) == 1
    assert documents[0].metadata["page"] == 2
    assert documents[0].metadata["locator"] == "page 2"


def test_scanned_pdf_without_text_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Page:
        @staticmethod
        def extract_text() -> None:
            return None

    class Reader:
        is_encrypted = False
        pages = [Page()]

    monkeypatch.setattr("rag_alura.documents.PdfReader", lambda _: Reader())
    path = tmp_path / "scan.pdf"
    path.write_bytes(b"fake")

    with pytest.raises(DocumentProcessingError, match="require OCR"):
        DocumentLoader().load(path)


def test_uploaded_filename_is_sanitized_and_confined(tmp_path: Path) -> None:
    path = save_uploaded_file("../../Política interna.PDF", b"content", tmp_path, 100)

    assert path == tmp_path / "Politica_interna.pdf"
    assert path.read_bytes() == b"content"


def test_upload_size_and_type_are_validated(tmp_path: Path) -> None:
    with pytest.raises(DocumentProcessingError, match="exceeds"):
        save_uploaded_file("data.csv", b"1234", tmp_path, 3)
    with pytest.raises(DocumentProcessingError, match="Only PDF and CSV"):
        sanitize_filename("notes.txt")


def test_supported_files_ignores_other_entries(tmp_path: Path) -> None:
    (tmp_path / "a.pdf").write_bytes(b"pdf")
    (tmp_path / "b.CSV").write_text("a\n1", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("ignore", encoding="utf-8")

    assert [path.name for path in supported_files(tmp_path)] == ["a.pdf", "b.CSV"]
