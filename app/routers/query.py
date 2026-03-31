"""RAG query routes with conversation support and export endpoints."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from app.models import (
    QueryRequest,
    QueryResponse,
    SourceRef,
    add_message,
    create_conversation,
    get_conversation,
    get_document,
    get_messages,
    update_conversation_title,
)
from app.services.exporter import (
    QAEntry,
    export_markdown,
    export_pdf,
    extract_markdown_tables,
    table_to_csv,
    table_to_excel,
)
from app.services.llm import generate_conversation_title, rag_answer
from app.services.vectorstore import search

router = APIRouter(prefix="/query", tags=["query"])


@router.post("/", response_model=QueryResponse)
async def query_documents(req: QueryRequest):
    """Answer a question using RAG with optional conversation context."""
    # Handle conversation
    conv_id = req.conversation_id
    conversation_history: list[dict] = []

    if conv_id:
        conv = get_conversation(conv_id)
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")
        msgs = get_messages(conv_id)
        conversation_history = [{"role": m.role, "content": m.content} for m in msgs]
    else:
        # Create new conversation
        conv = create_conversation()
        conv_id = conv.id

    # Persist user message
    add_message(conv_id, "user", req.question)

    # Search for relevant chunks
    results = search(req.question, top_k=req.top_k)

    if not results:
        answer = "No relevant documents found. Please upload and index documents first."
        add_message(conv_id, "assistant", answer)
        return QueryResponse(answer=answer, sources=[], conversation_id=conv_id)

    # Build context for LLM
    context_chunks: list[dict] = []
    sources: list[SourceRef] = []
    for r in results:
        doc = get_document(r.doc_id)
        doc_name = doc.filename if doc else r.doc_id
        context_chunks.append(
            {"text": r.text, "document": doc_name, "page_number": r.page_number}
        )
        sources.append(
            SourceRef(document=doc_name, doc_id=r.doc_id,
                      page=r.page_number, chunk_text=r.text[:200])
        )

    answer = rag_answer(req.question, context_chunks,
                        conversation_history=conversation_history)

    # Persist assistant message with sources
    add_message(conv_id, "assistant", answer,
                sources=[s.model_dump() for s in sources])

    # Auto-generate conversation title from first question
    if len(conversation_history) == 0:
        try:
            title = generate_conversation_title(req.question)
            update_conversation_title(conv_id, title)
        except Exception:
            pass

    return QueryResponse(answer=answer, sources=sources, conversation_id=conv_id)


# ---------------------------------------------------------------------------
# Export endpoints
# ---------------------------------------------------------------------------


class ExportRequest(QueryRequest):
    pass


@router.post("/export/markdown")
async def export_as_markdown(req: ExportRequest):
    qa_resp = await query_documents(req)
    entry = QAEntry(
        question=req.question,
        answer=qa_resp.answer,
        sources=[s.model_dump() for s in qa_resp.sources],
    )
    md_text = export_markdown([entry])
    return Response(
        content=md_text.encode("utf-8"),
        media_type="text/markdown",
        headers={"Content-Disposition": "attachment; filename=idp_report.md"},
    )


@router.post("/export/pdf")
async def export_as_pdf(req: ExportRequest):
    qa_resp = await query_documents(req)
    entry = QAEntry(
        question=req.question,
        answer=qa_resp.answer,
        sources=[s.model_dump() for s in qa_resp.sources],
    )
    pdf_bytes = export_pdf([entry])
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=idp_report.pdf"},
    )


@router.post("/export/csv")
async def export_table_csv(req: ExportRequest):
    """Extract tables from the answer and export as CSV."""
    qa_resp = await query_documents(req)
    tables = extract_markdown_tables(qa_resp.answer)
    if not tables:
        raise HTTPException(status_code=404, detail="No tables found in the answer")
    csv_text = table_to_csv(tables[0])
    return Response(
        content=csv_text.encode("utf-8"),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=idp_table.csv"},
    )


@router.post("/export/excel")
async def export_table_excel(req: ExportRequest):
    """Extract tables from the answer and export as Excel."""
    qa_resp = await query_documents(req)
    tables = extract_markdown_tables(qa_resp.answer)
    if not tables:
        raise HTTPException(status_code=404, detail="No tables found in the answer")
    xlsx_bytes = table_to_excel(tables[0])
    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=idp_table.xlsx"},
    )
