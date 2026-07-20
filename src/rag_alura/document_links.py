"""Publicación de documentos para poder abrirlos desde una cita.

Streamlit solo sirve archivos colocados en el directorio ``static`` contiguo al
script (``server.enableStaticServing``). Los documentos indexados viven en
``docs/`` y ``data/uploads/``, así que se replican allí. El original sigue
siendo la fuente de verdad del índice; la copia existe únicamente para el
navegador.

Sin dependencias de Streamlit: así el comportamiento puede probarse sin
levantar la aplicación.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from urllib.parse import quote

STATIC_ROUTE = "app/static"


def publish_for_viewing(path: Path, static_dir: Path) -> Path | None:
    """Replica el documento y devuelve la copia, o ``None`` si no se pudo."""
    try:
        static_dir.mkdir(parents=True, exist_ok=True)
        target = static_dir / path.name
        source = path.stat()
        if target.exists():
            mirrored = target.stat()
            if mirrored.st_size == source.st_size and mirrored.st_mtime >= source.st_mtime:
                return target
        shutil.copy2(path, target)
        return target
    except OSError:
        # La cita cae a texto plano, que es el comportamiento previo a esta
        # función. Un fallo al copiar no justifica interrumpir la aplicación.
        return None


def citation_href(title: str, page: int | None, static_dir: Path) -> str | None:
    """Enlace al documento publicado, anclado a la página cuando se conoce.

    La ruta es relativa para que siga funcionando si la aplicación se sirve
    bajo un ``baseUrlPath``.
    """
    if not title or "/" in title or "\\" in title:
        return None
    if not (static_dir / title).is_file():
        return None
    href = f"{STATIC_ROUTE}/{quote(title)}"
    return f"{href}#page={page}" if page and page > 0 else href
