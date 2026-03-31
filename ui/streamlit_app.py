"""IDP — Intelligent Document Processing — Streamlit Frontend."""

from __future__ import annotations

import os
import time

import requests
import streamlit as st

API_BASE = os.getenv("API_BASE", "http://localhost:8000")

st.set_page_config(page_title="IDP — Document Processing", page_icon="📄", layout="wide")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def api(method: str, path: str, **kwargs):
    url = f"{API_BASE}{path}"
    resp = getattr(requests, method)(url, **kwargs)
    resp.raise_for_status()
    return resp


# ---------------------------------------------------------------------------
# Sidebar navigation
# ---------------------------------------------------------------------------

st.sidebar.title("📄 IDP")
page = st.sidebar.radio("Navigate", ["Upload", "Library", "Chat"], index=2)


# =========================================================================
# UPLOAD PAGE
# =========================================================================

if page == "Upload":
    st.header("Upload Documents")
    uploaded = st.file_uploader(
        "Drop PDF files here", type=["pdf"], accept_multiple_files=True
    )

    if uploaded:
        for f in uploaded:
            with st.spinner(f"Uploading {f.name}..."):
                resp = api("post", "/documents/upload", files={"file": (f.name, f.read(), "application/pdf")})
                data = resp.json()
                st.success(data.get("message", "Uploaded"))

    st.info("After uploading, switch to **Library** to monitor indexing status.")


# =========================================================================
# LIBRARY PAGE
# =========================================================================

elif page == "Library":
    st.header("Document Library")

    if st.button("🔄 Refresh"):
        st.rerun()

    try:
        docs = api("get", "/documents/").json()
    except Exception as e:
        st.error(f"Failed to fetch documents: {e}")
        docs = []

    if not docs:
        st.info("No documents indexed yet. Upload PDFs first.")
    else:
        for doc in docs:
            status_icon = {"ready": "✅", "processing": "⏳", "error": "❌"}.get(doc["status"], "❓")
            with st.expander(f"{status_icon} {doc.get('title') or doc['filename']}"):
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.markdown(f"**Filename:** `{doc['filename']}`")
                    st.markdown(f"**Pages:** {doc['page_count']}  |  **Chunks:** {doc['chunk_count']}  |  **Status:** {doc['status']}")
                    if doc.get("summary"):
                        st.markdown(f"**Summary:** {doc['summary']}")
                with col2:
                    if st.button("🗑 Delete", key=f"del_{doc['id']}"):
                        try:
                            api("delete", f"/documents/{doc['id']}")
                            st.success(f"Deleted {doc['filename']}")
                            time.sleep(0.5)
                            st.rerun()
                        except Exception as e:
                            st.error(str(e))


# =========================================================================
# CHAT PAGE — Enhanced multimodal output
# =========================================================================

elif page == "Chat":
    st.header("Document Q&A")

    # Session state for chat history
    if "messages" not in st.session_state:
        st.session_state.messages = []

    # Display chat history
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            if msg["role"] == "assistant":
                # Render markdown with full support (tables, code blocks, math)
                st.markdown(msg["content"], unsafe_allow_html=False)

                # Show source page thumbnails if available
                if msg.get("sources"):
                    with st.expander("📎 Source References", expanded=False):
                        for src in msg["sources"]:
                            col_thumb, col_info = st.columns([1, 3])
                            with col_thumb:
                                # Try to load page thumbnail
                                try:
                                    thumb_url = f"{API_BASE}/documents/{src.get('doc_id', '')}/page/{src['page']}/thumbnail"
                                    st.image(thumb_url, width=150, caption=f"Page {src['page']}")
                                except Exception:
                                    st.caption(f"📄 Page {src['page']}")
                            with col_info:
                                st.markdown(f"**{src['document']}** — Page {src['page']}")
                                st.caption(src.get("chunk_text", "")[:300])
            else:
                st.markdown(msg["content"])

    # Chat input
    question = st.chat_input("Ask a question about your documents...")

    if question:
        # Add user message
        st.session_state.messages.append({"role": "user", "content": question})
        with st.chat_message("user"):
            st.markdown(question)

        # Get answer
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                try:
                    resp = api("post", "/query/", json={"question": question, "top_k": 5})
                    data = resp.json()
                    answer = data.get("answer", "No answer received.")
                    sources = data.get("sources", [])

                    # Render answer with full markdown support
                    st.markdown(answer, unsafe_allow_html=False)

                    # Show source page thumbnails
                    if sources:
                        with st.expander("📎 Source References", expanded=True):
                            for src in sources:
                                col_thumb, col_info = st.columns([1, 3])
                                with col_info:
                                    st.markdown(f"**{src['document']}** — Page {src['page']}")
                                    st.caption(src.get("chunk_text", "")[:300])

                    # Store in session
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": answer,
                        "sources": sources,
                    })

                except Exception as e:
                    st.error(f"Query failed: {e}")

    # ---------------------------------------------------------------------------
    # Export sidebar
    # ---------------------------------------------------------------------------
    if st.session_state.messages:
        st.sidebar.markdown("---")
        st.sidebar.subheader("Export Conversation")

        if st.sidebar.button("📝 Download Markdown"):
            # Build Q&A pairs from chat history
            qa_pairs = _build_qa_pairs()
            if qa_pairs:
                try:
                    resp = api(
                        "post",
                        "/query/export/markdown",
                        json={"question": qa_pairs[-1]["question"], "top_k": 5},
                    )
                    st.sidebar.download_button(
                        "⬇️ Save .md",
                        data=resp.content,
                        file_name="idp_report.md",
                        mime="text/markdown",
                    )
                except Exception as e:
                    st.sidebar.error(str(e))

        if st.sidebar.button("📄 Download PDF"):
            qa_pairs = _build_qa_pairs()
            if qa_pairs:
                try:
                    resp = api(
                        "post",
                        "/query/export/pdf",
                        json={"question": qa_pairs[-1]["question"], "top_k": 5},
                    )
                    st.sidebar.download_button(
                        "⬇️ Save .pdf",
                        data=resp.content,
                        file_name="idp_report.pdf",
                        mime="application/pdf",
                    )
                except Exception as e:
                    st.sidebar.error(str(e))

        if st.sidebar.button("🧹 Clear Chat"):
            st.session_state.messages = []
            st.rerun()


def _build_qa_pairs() -> list[dict]:
    """Extract Q&A pairs from session messages."""
    pairs: list[dict] = []
    msgs = st.session_state.get("messages", [])
    i = 0
    while i < len(msgs) - 1:
        if msgs[i]["role"] == "user" and msgs[i + 1]["role"] == "assistant":
            pairs.append({"question": msgs[i]["content"], "answer": msgs[i + 1]["content"]})
            i += 2
        else:
            i += 1
    return pairs
