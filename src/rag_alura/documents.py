from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import pandas as pd
from langchain_core.documents import Document
from pypdf import PdfReader
from pypdf.errors import PdfReadError

ALLOWED_SUFFIXES = {".pdf", ".csv"}


class DocumentProcessingError(ValueError):
    """Raised when an uploaded document cannot be safely processed."""


def sanitize_filename(filename: str) -> str:
    basename = Path(filename.replace("\\", "/")).name
    stem = unicodedata.normalize("NFKD", Path(basename).stem)
    ascii_stem = stem.encode("ascii", "ignore").decode("ascii")
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", ascii_stem).strip("._-")
    suffix = Path(basename).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise DocumentProcessingError("Only PDF and CSV files are supported.")
    if not safe_stem:
        safe_stem = "document"
    return f"{safe_stem}{suffix}"


def save_uploaded_file(
    filename: str,
    content: bytes,
    destination: Path,
    max_bytes: int,
) -> Path:
    if not content:
        raise DocumentProcessingError("The uploaded file is empty.")
    if len(content) > max_bytes:
        max_megabytes = max_bytes // (1024 * 1024)
        raise DocumentProcessingError(f"The file exceeds the {max_megabytes} MB limit.")

    destination.mkdir(parents=True, exist_ok=True)
    output_path = destination / sanitize_filename(filename)
    temporary_path = output_path.with_suffix(f"{output_path.suffix}.tmp")
    temporary_path.write_bytes(content)
    temporary_path.replace(output_path)
    return output_path


class DocumentLoader:
    def load(self, path: Path) -> list[Document]:
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            return self._load_pdf(path)
        if suffix == ".csv":
            return self._load_csv(path)
        raise DocumentProcessingError(f"Unsupported file type: {suffix or 'unknown'}.")

    def _load_pdf(self, path: Path) -> list[Document]:
        try:
            reader = PdfReader(path)
            if reader.is_encrypted and reader.decrypt("") == 0:
                raise DocumentProcessingError("Password-protected PDFs are not supported.")
        except (PdfReadError, OSError) as exc:
            raise DocumentProcessingError(f"Could not read PDF '{path.name}'.") from exc

        documents: list[Document] = []
        for page_number, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            if not text:
                continue
            documents.append(
                Document(
                    page_content=text,
                    metadata={
                        "source": path.name,
                        "source_path": str(path.resolve()),
                        "kind": "pdf",
                        "page": page_number,
                        "locator": f"page {page_number}",
                    },
                )
            )

        if not documents:
            raise DocumentProcessingError(
                f"PDF '{path.name}' has no extractable text. Scanned PDFs require OCR."
            )
        return documents

    def _load_csv(self, path: Path) -> list[Document]:
        frame = self._read_csv(path)
        if frame.empty:
            raise DocumentProcessingError(f"CSV '{path.name}' has no data rows.")

        documents: list[Document] = []
        for position, (_, row) in enumerate(frame.iterrows(), start=2):
            values = {str(column): str(value).strip() for column, value in row.items()}
            if not any(values.values()):
                continue
            content = "\n".join(f"{column}: {value}" for column, value in values.items())
            documents.append(
                Document(
                    page_content=content,
                    metadata={
                        "source": path.name,
                        "source_path": str(path.resolve()),
                        "kind": "csv",
                        "row": position,
                        "locator": f"row {position}",
                    },
                )
            )

        if not documents:
            raise DocumentProcessingError(f"CSV '{path.name}' has no usable data rows.")
        return documents

    @staticmethod
    def _read_csv(path: Path) -> pd.DataFrame:
        last_error: UnicodeDecodeError | None = None
        for encoding in ("utf-8-sig", "utf-8", "latin-1"):
            try:
                return pd.read_csv(
                    path,
                    dtype=str,
                    keep_default_na=False,
                    encoding=encoding,
                    on_bad_lines="error",
                )
            except UnicodeDecodeError as exc:
                last_error = exc
            except (pd.errors.ParserError, OSError) as exc:
                raise DocumentProcessingError(f"Could not parse CSV '{path.name}'.") from exc
        raise DocumentProcessingError(f"Could not decode CSV '{path.name}'.") from last_error


def supported_files(directory: Path) -> list[Path]:
    if not directory.exists():
        return []
    return sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in ALLOWED_SUFFIXES
    )
