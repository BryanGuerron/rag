"""Protege el marcado HTML embebido en la interfaz.

Markdown convierte en bloque de código toda línea con cuatro o más espacios
iniciales. Cuando eso le ocurre al HTML de marca, Streamlit muestra las
etiquetas crudas en pantalla sin fallar ni registrar ningún error, así que la
única defensa posible es una prueba sobre el código fuente.
"""

from __future__ import annotations

import re
from pathlib import Path

APP_SOURCE = Path(__file__).resolve().parents[1] / "app.py"
MAX_INDENT = 3


def html_literal_lines() -> list[tuple[int, str]]:
    source = APP_SOURCE.read_text(encoding="utf-8")
    offending: list[tuple[int, str]] = []
    for block in re.findall(r'"""(.*?)"""', source, re.S):
        if "<" not in block:
            continue
        start = source.index(block)
        first_line = source[:start].count("\n") + 1
        for offset, line in enumerate(block.splitlines()):
            if line.strip().startswith("<"):
                offending.append((first_line + offset, line))
    return offending


def test_embedded_html_is_never_indented_as_a_code_block() -> None:
    too_deep = [
        (number, line)
        for number, line in html_literal_lines()
        if len(line) - len(line.lstrip(" ")) > MAX_INDENT
    ]

    assert not too_deep, (
        "Estas líneas de HTML se renderizarían como bloque de código: "
        + "; ".join(f"app.py:{number} {line.strip()[:40]!r}" for number, line in too_deep)
    )


def test_brand_markup_is_present() -> None:
    source = APP_SOURCE.read_text(encoding="utf-8")

    assert 'class="sp-brand__name"' in source
    assert "<svg" in source
