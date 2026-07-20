from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import streamlit as st

from rag_alura.assistant import AssistantAnswer, DocumentAssistant
from rag_alura.config import ConfigurationError, Settings
from rag_alura.document_links import citation_href, publish_for_viewing
from rag_alura.documents import DocumentProcessingError, save_uploaded_file, supported_files
from rag_alura.knowledge_base import KnowledgeBase
from rag_alura.web_search import WebSearchError

# Empresa ficticia del corpus de demostración, no la autoría de la aplicación.
COMPANY = "Santo Pegasus Soluciones"
PRODUCT = "Archivo Vivo"
THEME_PATH = Path(__file__).parent / "assets" / "theme.css"

# Streamlit solo publica archivos desde ./static (server.enableStaticServing).
# Los documentos viven en docs/ y data/uploads/, así que se replican aquí para
# poder enlazarlos; el original sigue siendo la fuente de verdad del índice.
STATIC_DIR = Path(__file__).parent / "static"

# Ninguna línea supera los tres espacios de sangría: con cuatro o más,
# Markdown la trataría como bloque de código en lugar de HTML.
BRAND_MARK = """
<svg class="sp-brand__mark" width="34" height="34" viewBox="0 0 34 34" fill="none" role="img"
 aria-label="Santo Pegasus Soluciones">
 <defs>
 <linearGradient id="sp-grad" x1="2" y1="2" x2="32" y2="32" gradientUnits="userSpaceOnUse">
 <stop stop-color="#22d3ee"/><stop offset=".5" stop-color="#38bdf8"/>
 <stop offset="1" stop-color="#8b5cf6"/>
 </linearGradient>
 </defs>
 <path d="M17 2.4 30 9.7v14.6L17 31.6 4 24.3V9.7z" stroke="url(#sp-grad)" stroke-width="1.2"
 opacity=".45"/>
 <path d="M9.5 23 22 10.5" stroke="url(#sp-grad)" stroke-width="2.1" stroke-linecap="round"/>
 <path d="M13.6 24.4 24.4 13.6" stroke="url(#sp-grad)" stroke-width="1.6"
 stroke-linecap="round" opacity=".72"/>
 <path d="M18.2 25.2 25.6 17.8" stroke="url(#sp-grad)" stroke-width="1.2"
 stroke-linecap="round" opacity=".45"/>
 <circle cx="22.4" cy="10.2" r="2.5" fill="url(#sp-grad)"/>
</svg>
"""

st.set_page_config(
    page_title=f"{COMPANY} · {PRODUCT}",
    page_icon="◆",
    layout="centered",
    initial_sidebar_state="expanded",
)


def load_theme() -> None:
    """Inyecta la hoja de estilos de marca; la app sigue siendo usable sin ella."""
    try:
        css = THEME_PATH.read_text(encoding="utf-8")
    except OSError:
        return
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def render_brand() -> None:
    # Sin sangría a propósito: Markdown convierte en bloque de código toda
    # línea con cuatro o más espacios iniciales, incluso dentro de HTML.
    st.markdown(
        "\n".join(
            [
                '<div class="sp-brand">',
                BRAND_MARK.strip(),
                "<div>",
                f'<div class="sp-brand__name">{COMPANY}</div>',
                '<div class="sp-brand__tag">Microservicios · IA · Nube OCI</div>',
                "</div>",
                "</div>",
            ]
        ),
        unsafe_allow_html=True,
    )


def render_chips(chips: list[str]) -> None:
    items = "".join(
        f'<span class="sp-chip"><span class="sp-chip__dot"></span>{chip}</span>' for chip in chips
    )
    st.markdown(f'<div class="sp-chips">{items}</div>', unsafe_allow_html=True)


load_theme()


@st.cache_resource(show_spinner=False)
def build_services() -> tuple[Settings, KnowledgeBase, DocumentAssistant, list[str]]:
    settings = Settings.from_env()
    settings.require_google_key()
    knowledge_base = KnowledgeBase(settings)
    startup_errors: list[str] = []
    for path in [*supported_files(settings.docs_dir), *supported_files(settings.uploads_dir)]:
        try:
            knowledge_base.index_file(path)
            publish_for_viewing(path, STATIC_DIR)
        except Exception as exc:
            startup_errors.append(f"{path.name}: {exc}")
    assistant = DocumentAssistant(settings, knowledge_base)
    return settings, knowledge_base, assistant, startup_errors


def message_from_answer(answer: AssistantAnswer) -> dict[str, object]:
    return {
        "role": "assistant",
        "content": answer.content,
        "citations": [asdict(citation) for citation in answer.citations],
        "source_type": answer.source_type,
    }


def render_citations(message: dict[str, object]) -> None:
    citations = message.get("citations") or []
    if not citations:
        return
    source_type = message.get("source_type")
    label = "Fuentes web consultadas" if source_type == "web" else "Fuentes documentales"
    with st.expander(label):
        for citation in citations:
            if citation.get("url"):
                st.markdown(f"- **[{citation['label']}]** [{citation['title']}]({citation['url']})")
                continue

            title = str(citation["title"])
            locator = str(citation.get("locator") or "")
            href = citation_href(title, citation.get("page"), STATIC_DIR)
            suffix = f", {locator}" if locator else ""
            if href:
                # Sin sangría: Markdown trataría el HTML como bloque de código.
                st.markdown(
                    f'<div class="sp-cite">'
                    f'<span class="sp-cite__label">[{citation["label"]}]</span> '
                    f'<a class="sp-cite__link" href="{href}" target="_blank" '
                    f'rel="noopener">{title}</a>{suffix}'
                    f"</div>",
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(f"- **[{citation['label']}]** `{title}`{suffix}")


def render_history() -> None:
    for message in st.session_state.messages:
        with st.chat_message(str(message["role"])):
            st.markdown(str(message["content"]))
            render_citations(message)


try:
    settings, knowledge_base, assistant, startup_errors = build_services()
except ConfigurationError as exc:
    st.error(str(exc))
    st.code("copy .env.example .env\n# Add GOOGLE_API_KEY to .env", language="bash")
    st.stop()
except Exception as exc:
    st.error(f"No se pudo iniciar la base de conocimiento: {exc}")
    st.stop()

st.session_state.setdefault("messages", [])
st.session_state.setdefault("pending_external_query", None)

with st.sidebar:
    render_brand()
    st.markdown('<p class="eyebrow">Base de conocimiento</p>', unsafe_allow_html=True)
    st.header("Biblioteca")
    st.caption("Los archivos quedan indexados en el volumen persistente de la aplicación.")

    with st.form("document_upload", clear_on_submit=True):
        uploads = st.file_uploader(
            "Agregar documentos",
            type=["pdf", "csv"],
            accept_multiple_files=True,
            help="PDF con texto seleccionable o CSV con encabezados.",
        )
        submitted = st.form_submit_button("Guardar e indexar", type="primary")

    if submitted:
        if not uploads:
            st.warning("Selecciona al menos un archivo.")
        for upload in uploads or []:
            try:
                path = save_uploaded_file(
                    upload.name,
                    upload.getvalue(),
                    settings.uploads_dir,
                    settings.max_upload_bytes,
                )
                with st.spinner(f"Indexando {path.name}..."):
                    result = knowledge_base.index_file(path)
                publish_for_viewing(path, STATIC_DIR)
                if result.status == "unchanged":
                    st.info(f"{result.source} ya estaba actualizado.")
                else:
                    st.success(f"{result.source}: {result.chunks} fragmentos indexados.")
            except (DocumentProcessingError, OSError, ValueError) as exc:
                st.error(f"{upload.name}: {exc}")
            except Exception as exc:
                st.error(f"No se pudo indexar {upload.name}: {exc}")

    sources = knowledge_base.list_sources()
    st.metric("Documentos indexados", len(sources))
    for source in sources:
        st.markdown(
            f'<span class="source-pill">{source["source"]} · {source["chunks"]} partes</span>',
            unsafe_allow_html=True,
        )

    if startup_errors:
        with st.expander("Errores de indexación inicial"):
            for error in startup_errors:
                st.error(error)

st.markdown('<p class="eyebrow">RAG documental con trazabilidad</p>', unsafe_allow_html=True)
st.markdown(f'<h1 class="sp-hero">{PRODUCT}</h1>', unsafe_allow_html=True)
st.markdown(
    '<p class="sp-lede">Respuestas fundamentadas exclusivamente en tus documentos. '
    "Cada afirmación señala el archivo y la ubicación exacta que la respaldan; "
    "sin evidencia, el asistente lo declara en lugar de improvisar.</p>",
    unsafe_allow_html=True,
)

render_chips(
    [
        f"{len(knowledge_base.list_sources())} documentos indexados",
        f"Modelo {settings.chat_model}",
        f"Top-{settings.top_k} fragmentos",
    ]
)

if not st.session_state.messages:
    st.info(
        "Prueba con: ¿Qué tecnologías usa el back-end? o "
        "¿Cuántas aprobaciones necesita un Pull Request?"
    )

render_history()

pending_query = st.session_state.pending_external_query
if pending_query:
    st.warning("La respuesta no está en los documentos. La web solo se consulta con tu permiso.")
    consent_column, decline_column = st.columns(2)
    if consent_column.button("Buscar en la web", type="primary", use_container_width=True):
        try:
            with st.spinner("Consultando fuentes públicas..."):
                web_answer = assistant.answer_from_web_after_consent(pending_query)
            st.session_state.messages.append(message_from_answer(web_answer))
        except WebSearchError as exc:
            st.session_state.messages.append(
                {"role": "assistant", "content": str(exc), "citations": [], "source_type": "web"}
            )
        finally:
            st.session_state.pending_external_query = None
        st.rerun()
    if decline_column.button("No, mantener solo documentos", use_container_width=True):
        st.session_state.pending_external_query = None
        st.rerun()

prompt = st.chat_input(
    "Escribe una pregunta sobre tus documentos",
    disabled=bool(st.session_state.pending_external_query),
)
if prompt:
    history = [
        {"role": str(message["role"]), "content": str(message["content"])}
        for message in st.session_state.messages[-6:]
    ]
    st.session_state.messages.append({"role": "user", "content": prompt})
    try:
        with st.spinner("Buscando evidencia en los documentos..."):
            answer = assistant.answer_from_documents(prompt, history)
        st.session_state.messages.append(message_from_answer(answer))
        if not answer.found:
            st.session_state.pending_external_query = prompt
    except Exception as exc:
        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": f"No pude procesar la pregunta: {exc}",
                "citations": [],
                "source_type": "documents",
            }
        )
    st.rerun()

st.markdown(
    f'<div class="sp-footer">Corpus de demostración · {COMPANY}, '
    "empresa ficticia usada como escenario de ejemplo</div>",
    unsafe_allow_html=True,
)
