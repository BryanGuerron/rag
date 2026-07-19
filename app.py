from __future__ import annotations

from dataclasses import asdict

import streamlit as st

from rag_alura.assistant import AssistantAnswer, DocumentAssistant
from rag_alura.config import ConfigurationError, Settings
from rag_alura.documents import DocumentProcessingError, save_uploaded_file, supported_files
from rag_alura.knowledge_base import KnowledgeBase
from rag_alura.web_search import WebSearchError

st.set_page_config(
    page_title="Archivo Vivo",
    page_icon="AV",
    layout="centered",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    :root {
        --ink: #17211b;
        --paper: #f4f1e8;
        --accent: #1f6b4f;
        --line: #d6d0c1;
    }
    .stApp { background: var(--paper); color: var(--ink); }
    [data-testid="stSidebar"] { background: #e8e4d8; border-right: 1px solid var(--line); }
    h1, h2, h3 { font-family: Georgia, 'Times New Roman', serif; letter-spacing: -0.02em; }
    .eyebrow { color: var(--accent); font-size: .75rem; font-weight: 700; letter-spacing: .15em; }
    .source-pill {
        display: inline-block; padding: .15rem .45rem; margin: .1rem;
        border: 1px solid var(--line); border-radius: 999px; font-size: .75rem;
    }
    [data-testid="stChatMessage"] {
        background: rgba(255,255,255,.38); border: 1px solid var(--line); border-radius: 4px;
    }
    .stButton > button { border-radius: 2px; font-weight: 650; }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_resource(show_spinner=False)
def build_services() -> tuple[Settings, KnowledgeBase, DocumentAssistant, list[str]]:
    settings = Settings.from_env()
    settings.require_openai_key()
    knowledge_base = KnowledgeBase(settings)
    startup_errors: list[str] = []
    for path in [*supported_files(settings.docs_dir), *supported_files(settings.uploads_dir)]:
        try:
            knowledge_base.index_file(path)
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
            else:
                locator = f", {citation['locator']}" if citation.get("locator") else ""
                st.markdown(f"- **[{citation['label']}]** `{citation['title']}`{locator}")


def render_history() -> None:
    for message in st.session_state.messages:
        with st.chat_message(str(message["role"])):
            st.markdown(str(message["content"]))
            render_citations(message)


try:
    settings, knowledge_base, assistant, startup_errors = build_services()
except ConfigurationError as exc:
    st.error(str(exc))
    st.code("copy .env.example .env\n# Add OPENAI_API_KEY to .env", language="bash")
    st.stop()
except Exception as exc:
    st.error(f"No se pudo iniciar la base de conocimiento: {exc}")
    st.stop()

st.session_state.setdefault("messages", [])
st.session_state.setdefault("pending_external_query", None)

with st.sidebar:
    st.markdown('<p class="eyebrow">BASE DE CONOCIMIENTO</p>', unsafe_allow_html=True)
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

st.markdown('<p class="eyebrow">RAG DOCUMENTAL CON FUENTES</p>', unsafe_allow_html=True)
st.title("Archivo Vivo")
st.write(
    "Pregunta sobre los documentos. Cada respuesta debe señalar el archivo y la ubicación "
    "que la fundamentan."
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
