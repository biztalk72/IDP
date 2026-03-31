"""IDP — Intelligent Document Processing — Streamlit Frontend."""

from __future__ import annotations

import io
import json
import os
import re
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
# Session state init
# ---------------------------------------------------------------------------

if "messages" not in st.session_state:
    st.session_state.messages = []
if "conversation_id" not in st.session_state:
    st.session_state.conversation_id = None
if "conversations" not in st.session_state:
    st.session_state.conversations = []


def load_conversations():
    try:
        st.session_state.conversations = api("get", "/conversations/").json()
    except Exception:
        st.session_state.conversations = []


def load_conversation_messages(conv_id: str):
    try:
        msgs = api("get", f"/conversations/{conv_id}/messages").json()
        st.session_state.messages = [
            {"role": m["role"], "content": m["content"],
             "sources": json.loads(m.get("sources_json", "[]"))}
            for m in msgs
        ]
        st.session_state.conversation_id = conv_id
    except Exception:
        st.session_state.messages = []


# ---------------------------------------------------------------------------
# Sidebar navigation
# ---------------------------------------------------------------------------

st.sidebar.title("📄 IDP")
page = st.sidebar.radio("Navigate", ["Chat", "Library", "Upload"], index=0)


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
                resp = api("post", "/documents/upload",
                           files={"file": (f.name, f.read(), "application/pdf")})
                data = resp.json()
                st.success(data.get("message", "Uploaded"))

    st.info("After uploading, switch to **Library** to monitor indexing status.")


# =========================================================================
# LIBRARY PAGE
# =========================================================================

elif page == "Library":
    st.header("Document Library")

    # Controls
    col_refresh, col_sort, col_filter = st.columns([1, 2, 2])
    with col_refresh:
        if st.button("🔄 Refresh"):
            st.rerun()
    with col_sort:
        sort_by = st.selectbox("Sort by", ["created_at", "title", "filename", "page_count"],
                               index=0)
        order = st.selectbox("Order", ["desc", "asc"], index=0)
    with col_filter:
        status_filter = st.selectbox("Status", ["all", "ready", "processing", "error"], index=0)

    try:
        params = {"sort_by": sort_by, "order": order}
        if status_filter != "all":
            params["status"] = status_filter
        docs = api("get", "/documents/", params=params).json()
    except Exception as e:
        st.error(f"Failed to fetch documents: {e}")
        docs = []

    if not docs:
        st.info("No documents indexed yet. Upload PDFs first.")
    else:
        for doc in docs:
            status_icon = {"ready": "✅", "processing": "⏳", "error": "❌"}.get(
                doc["status"], "❓"
            )
            version_label = f" (v{doc.get('version', 1)})" if doc.get("version", 1) > 1 else ""
            with st.expander(
                f"{status_icon} {doc.get('title') or doc['filename']}{version_label}"
            ):
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.markdown(f"**Filename:** `{doc['filename']}`")
                    st.markdown(
                        f"**Pages:** {doc['page_count']}  |  "
                        f"**Chunks:** {doc['chunk_count']}  |  "
                        f"**Version:** {doc.get('version', 1)}  |  "
                        f"**Status:** {doc['status']}"
                    )
                    if doc.get("summary"):
                        st.markdown(f"**Summary:** {doc['summary']}")
                with col2:
                    if st.button("🔄 Reindex", key=f"reidx_{doc['id']}"):
                        try:
                            api("post", f"/documents/{doc['id']}/reindex")
                            st.success("Reindexing started")
                        except Exception as e:
                            st.error(str(e))
                    if st.button("🗑 Delete", key=f"del_{doc['id']}"):
                        try:
                            api("delete", f"/documents/{doc['id']}")
                            st.success(f"Deleted {doc['filename']}")
                            time.sleep(0.5)
                            st.rerun()
                        except Exception as e:
                            st.error(str(e))


# =========================================================================
# CHAT PAGE
# =========================================================================

elif page == "Chat":
    # --- Conversation sidebar ---
    st.sidebar.markdown("---")
    st.sidebar.subheader("💬 Conversations")

    if st.sidebar.button("➕ New Conversation"):
        st.session_state.messages = []
        st.session_state.conversation_id = None
        st.rerun()

    load_conversations()
    for conv in st.session_state.conversations:
        label = conv.get("title", "Untitled")[:40]
        is_active = st.session_state.conversation_id == conv["id"]
        btn_label = f"{'▶ ' if is_active else ''}{label}"
        if st.sidebar.button(btn_label, key=f"conv_{conv['id']}"):
            load_conversation_messages(conv["id"])
            st.rerun()

    # --- Main chat area ---
    st.header("Document Q&A")

    # Display chat history
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            if msg["role"] == "assistant":
                content = msg["content"]

                # Check for GRAPH_REQUEST
                graph_match = re.search(r"GRAPH_REQUEST:\s*(\w+)", content)
                display_content = re.sub(r"GRAPH_REQUEST:\s*\w+", "", content).strip()

                st.markdown(display_content, unsafe_allow_html=False)

                # Render graph if requested
                if graph_match:
                    _render_graph(display_content, graph_match.group(1))

                # Table export buttons
                _render_table_exports(display_content)

                # Show source page thumbnails
                if msg.get("sources"):
                    _render_sources(msg["sources"])
            else:
                st.markdown(msg["content"])

    # Chat input
    question = st.chat_input("Ask a question about your documents... ")

    if question:
        st.session_state.messages.append({"role": "user", "content": question})
        with st.chat_message("user"):
            st.markdown(question)

        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                try:
                    payload = {"question": question, "top_k": 5}
                    if st.session_state.conversation_id:
                        payload["conversation_id"] = st.session_state.conversation_id

                    resp = api("post", "/query/", json=payload)
                    data = resp.json()
                    answer = data.get("answer", "No answer received.")
                    sources = data.get("sources", [])
                    conv_id = data.get("conversation_id", "")

                    if conv_id:
                        st.session_state.conversation_id = conv_id

                    # Check for GRAPH_REQUEST
                    graph_match = re.search(r"GRAPH_REQUEST:\s*(\w+)", answer)
                    display_answer = re.sub(r"GRAPH_REQUEST:\s*\w+", "", answer).strip()

                    st.markdown(display_answer, unsafe_allow_html=False)

                    if graph_match:
                        _render_graph(display_answer, graph_match.group(1))

                    _render_table_exports(display_answer)

                    if sources:
                        _render_sources(sources)

                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": answer,
                        "sources": sources,
                    })

                except Exception as e:
                    st.error(f"Query failed: {e}")

    # --- Export sidebar ---
    if st.session_state.messages:
        st.sidebar.markdown("---")
        st.sidebar.subheader("Export")

        if st.sidebar.button("📝 Download Markdown"):
            _export_conversation("markdown")

        if st.sidebar.button("📄 Download PDF"):
            _export_conversation("pdf")

        if st.sidebar.button("🧹 Clear Chat"):
            st.session_state.messages = []
            st.session_state.conversation_id = None
            st.rerun()


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _render_sources(sources: list[dict]):
    """Render source references with page thumbnails."""
    with st.expander("📎 Source References", expanded=False):
        for src in sources:
            col_thumb, col_info = st.columns([1, 3])
            with col_thumb:
                doc_id = src.get("doc_id", "")
                page = src.get("page", 0)
                if doc_id and page:
                    try:
                        thumb_url = f"{API_BASE}/documents/{doc_id}/page/{page}/thumbnail"
                        st.image(thumb_url, width=150, caption=f"Page {page}")
                    except Exception:
                        st.caption(f"📄 Page {page}")
                else:
                    st.caption(f"📄 Page {page}")
            with col_info:
                st.markdown(f"**{src.get('document', '?')}** — Page {page}")
                st.caption(src.get("chunk_text", "")[:300])


def _render_graph(text: str, graph_type: str):
    """Parse markdown tables and render as Plotly graph."""
    try:
        import plotly.express as px
        import plotly.graph_objects as go
        import pandas as pd

        tables = _extract_tables_from_md(text)
        if not tables:
            return

        df = pd.DataFrame(tables[0][1:], columns=tables[0][0])
        # Try to convert numeric columns
        for col in df.columns:
            try:
                df[col] = pd.to_numeric(df[col])
            except (ValueError, TypeError):
                pass

        numeric_cols = df.select_dtypes(include="number").columns.tolist()
        non_numeric = [c for c in df.columns if c not in numeric_cols]

        x_col = non_numeric[0] if non_numeric else df.columns[0]
        y_cols = numeric_cols if numeric_cols else [df.columns[1]] if len(df.columns) > 1 else []

        fig = None
        if graph_type in ("bar",):
            fig = px.bar(df, x=x_col, y=y_cols[0] if y_cols else df.columns[1])
        elif graph_type in ("line",):
            fig = px.line(df, x=x_col, y=y_cols[0] if y_cols else df.columns[1])
        elif graph_type in ("scatter",):
            y = y_cols[0] if y_cols else df.columns[1]
            fig = px.scatter(df, x=x_col, y=y)
        elif graph_type in ("pie",):
            fig = px.pie(df, names=x_col, values=y_cols[0] if y_cols else df.columns[1])
        elif graph_type in ("histogram",):
            fig = px.histogram(df, x=y_cols[0] if y_cols else df.columns[0])
        elif graph_type in ("3d_scatter",) and len(numeric_cols) >= 3:
            fig = px.scatter_3d(df, x=numeric_cols[0], y=numeric_cols[1], z=numeric_cols[2])
        elif graph_type in ("3d_surface",) and len(numeric_cols) >= 1:
            fig = go.Figure(data=[go.Surface(z=df[numeric_cols].values)])
        else:
            fig = px.bar(df, x=x_col, y=y_cols[0] if y_cols else df.columns[1])

        if fig:
            st.plotly_chart(fig, use_container_width=True)
            # Download button for graph
            try:
                buf = io.BytesIO()
                fig.write_image(buf, format="png", width=800, height=500)
                st.download_button("📊 Download Graph (PNG)", buf.getvalue(),
                                   "graph.png", "image/png")
            except Exception:
                pass  # kaleido not available
    except Exception as e:
        st.caption(f"Could not render graph: {e}")


def _render_table_exports(text: str):
    """Show Excel/CSV export buttons if text contains markdown tables."""
    tables = _extract_tables_from_md(text)
    if not tables:
        return

    col1, col2 = st.columns(2)
    table = tables[0]
    with col1:
        csv_text = _table_to_csv(table)
        st.download_button("📋 Download CSV", csv_text, "table.csv", "text/csv",
                           key=f"csv_{hash(csv_text)}")
    with col2:
        xlsx = _table_to_xlsx(table)
        st.download_button("📊 Download Excel", xlsx, "table.xlsx",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           key=f"xlsx_{hash(str(table))}")


def _extract_tables_from_md(text: str) -> list[list[list[str]]]:
    """Extract markdown tables as list of rows."""
    tables: list[list[list[str]]] = []
    lines = text.split("\n")
    current: list[list[str]] = []
    for line in lines:
        s = line.strip()
        if "|" in s and s.startswith("|"):
            if re.match(r"^\|[\s\-:|]+\|$", s):
                continue
            cells = [c.strip() for c in s.split("|")[1:-1]]
            if cells:
                current.append(cells)
        else:
            if current:
                tables.append(current)
                current = []
    if current:
        tables.append(current)
    return tables


def _table_to_csv(table: list[list[str]]) -> str:
    import csv as _csv
    buf = io.StringIO()
    w = _csv.writer(buf)
    for row in table:
        w.writerow(row)
    return buf.getvalue()


def _table_to_xlsx(table: list[list[str]]) -> bytes:
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    for row in table:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _export_conversation(fmt: str):
    """Export the last Q&A pair."""
    pairs = _build_qa_pairs()
    if not pairs:
        st.sidebar.warning("No Q&A to export")
        return
    last = pairs[-1]
    try:
        if fmt == "markdown":
            resp = api("post", "/query/export/markdown",
                       json={"question": last["question"], "top_k": 5,
                             "conversation_id": st.session_state.conversation_id})
            st.sidebar.download_button("⬇️ Save .md", data=resp.content,
                                       file_name="idp_report.md", mime="text/markdown")
        elif fmt == "pdf":
            resp = api("post", "/query/export/pdf",
                       json={"question": last["question"], "top_k": 5,
                             "conversation_id": st.session_state.conversation_id})
            st.sidebar.download_button("⬇️ Save .pdf", data=resp.content,
                                       file_name="idp_report.pdf", mime="application/pdf")
    except Exception as e:
        st.sidebar.error(str(e))


def _build_qa_pairs() -> list[dict]:
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
