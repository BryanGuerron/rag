from pathlib import Path

from rag_alura.document_links import citation_href, publish_for_viewing


def source_document(directory: Path, name: str = "guia.pdf", body: bytes = b"%PDF-1.4") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_bytes(body)
    return path


def test_document_is_mirrored_into_the_static_directory(tmp_path: Path) -> None:
    document = source_document(tmp_path / "docs")
    static_dir = tmp_path / "static"

    published = publish_for_viewing(document, static_dir)

    assert published == static_dir / "guia.pdf"
    assert published.read_bytes() == document.read_bytes()


def test_unchanged_document_is_not_copied_again(tmp_path: Path) -> None:
    document = source_document(tmp_path / "docs")
    static_dir = tmp_path / "static"
    publish_for_viewing(document, static_dir)
    first_copy = (static_dir / "guia.pdf").stat().st_mtime_ns

    publish_for_viewing(document, static_dir)

    assert (static_dir / "guia.pdf").stat().st_mtime_ns == first_copy


def test_changed_document_replaces_the_mirror(tmp_path: Path) -> None:
    document = source_document(tmp_path / "docs")
    static_dir = tmp_path / "static"
    publish_for_viewing(document, static_dir)

    document.write_bytes(b"%PDF-1.4 contenido nuevo y mas largo")
    publish_for_viewing(document, static_dir)

    assert (static_dir / "guia.pdf").read_bytes() == document.read_bytes()


def test_href_anchors_the_exact_page(tmp_path: Path) -> None:
    static_dir = tmp_path / "static"
    publish_for_viewing(source_document(tmp_path / "docs"), static_dir)

    assert citation_href("guia.pdf", 24, static_dir) == "app/static/guia.pdf#page=24"


def test_href_without_page_has_no_anchor(tmp_path: Path) -> None:
    static_dir = tmp_path / "static"
    publish_for_viewing(source_document(tmp_path / "docs", "ventas.csv"), static_dir)

    assert citation_href("ventas.csv", None, static_dir) == "app/static/ventas.csv"


def test_href_escapes_characters_that_break_urls(tmp_path: Path) -> None:
    static_dir = tmp_path / "static"
    publish_for_viewing(source_document(tmp_path / "docs", "guia de estilo.pdf"), static_dir)

    assert citation_href("guia de estilo.pdf", 3, static_dir) == (
        "app/static/guia%20de%20estilo.pdf#page=3"
    )


def test_href_is_absent_when_the_document_was_never_published(tmp_path: Path) -> None:
    assert citation_href("ausente.pdf", 2, tmp_path / "static") is None


def test_href_rejects_paths_that_escape_the_static_directory(tmp_path: Path) -> None:
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    (tmp_path / "secreto.pdf").write_bytes(b"%PDF-1.4")

    assert citation_href("../secreto.pdf", 1, static_dir) is None
    assert citation_href("..\\secreto.pdf", 1, static_dir) is None
