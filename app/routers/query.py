"""RAG query routes and conversation export endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from app.models import QueryRequest, QueryResponse, SourceRef, get_document
from app.services.exporter import QAEntry, export_markdown, export_pdf
from app.services.llm import rag_answer
from app.services.vectorstore import search

router = APIRouter(prefix="/query", tags=["query"])


@router.post("/", response_model=QueryResponse)
async def query_documents(req: QueryRequest):
    """Answer a question using RAG over indexed documents."""
    results = search(req.question, top_k=req.top_k)

    if not results:
        return QueryResponse(
            answer="No relevant documents found. Please upload and index documents first.",
            sources=[],
        )

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
            SourceRef(document=doc_name, page=r.page_number, chunk_text=r.text[:200])
        )

    answer = rag_answer(req.question, context_chunks)
    return QueryResponse(answer=answer, sources=sources)


# ---------------------------------------------------------------------------
# Export endpoints
# ---------------------------------------------------------------------------


class ExportRequest(QueryRequest):
    """Extends QueryRequest — the answer is generated then exported."""
    pass


@router.post("/export/markdown")
async def export_as_markdown(req: ExportRequest):
    """Answer the question and return the result as a downloadable Markdown file."""
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
    """Answer the question and return the result as a downloadable PDF."""
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
