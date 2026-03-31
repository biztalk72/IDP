"""Document management routes: upload, list, delete, versioning, page resources."""

from __future__ import annotations

import logging
from pathlib import Path
from threading import Thread
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, UploadFile
from fastapi.responses import Response

from app.config import DATA_DIR, UPLOAD_MAX_SIZE_MB
from app.models import (
    DocumentMeta,
    delete_document_record,
    get_document,
    get_document_versions,
    get_latest_version,
    list_documents,
)
from app.services.indexer import index_document
from app.services.vectorstore import delete_doc_chunks

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/upload", response_model=dict)
async def upload_document(file: UploadFile):
    """Upload a PDF with automatic versioning and start async indexing."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    content = await file.read()
    if len(content) > UPLOAD_MAX_SIZE_MB * 1024 * 1024:
        raise HTTPException(status_code=400, detail=f"File exceeds {UPLOAD_MAX_SIZE_MB}MB limit")

    dest = DATA_DIR / file.filename
    dest.write_bytes(content)

    # Determine version
    latest_ver = get_latest_version(file.filename)
    new_version = latest_ver + 1
    # Find parent_id (first version's doc_id)
    parent_id = ""
    if latest_ver > 0:
        versions = get_document_versions(file.filename)
        if versions:
            parent_id = versions[-1].id  # oldest version

    def _run():
        try:
            index_document(dest, version=new_version, parent_id=parent_id)
        except Exception:
            logger.exception("Background indexing failed for %s", file.filename)

    Thread(target=_run, daemon=True).start()

    return {
        "message": f"Uploaded {file.filename} (v{new_version}). Indexing started.",
        "filename": file.filename,
        "version": new_version,
    }


@router.get("/", response_model=list[DocumentMeta])
async def list_docs(
    sort_by: str = Query("created_at", description="Sort field"),
    order: str = Query("desc", description="asc or desc"),
    status: Optional[str] = Query(None, description="Filter by status"),
):
    """List documents with sorting and filtering."""
    return list_documents(sort_by=sort_by, order=order, status=status)


@router.get("/{doc_id}", response_model=DocumentMeta)
async def get_doc(doc_id: str):
    doc = get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.get("/{doc_id}/versions", response_model=list[DocumentMeta])
async def get_versions(doc_id: str):
    """List all versions of a document."""
    doc = get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return get_document_versions(doc.filename)


@router.post("/{doc_id}/reindex")
async def reindex_doc(doc_id: str):
    """Re-run indexing on an existing document."""
    doc = get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    pdf_path = DATA_DIR / doc.filename
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF file not found on disk")

    # Delete old vectors
    delete_doc_chunks(doc_id)

    def _run():
        try:
            from app.models import update_document
            update_document(doc_id, status="processing")
            from app.services.extractor import extract_pdf
            from app.services.chunker import chunk_document
            from app.services.vectorstore import add_chunks
            from app.services.llm import generate_title, generate_summary

            extraction = extract_pdf(pdf_path)
            chunks = chunk_document(extraction, doc_id=doc_id)
            add_chunks(chunks)
            title = generate_title(extraction.full_text)
            summary = generate_summary(extraction.full_text)
            update_document(
                doc_id, title=title, summary=summary,
                chunk_count=len(chunks), page_count=extraction.page_count,
                status="ready",
            )
        except Exception:
            logger.exception("Reindex failed for %s", doc_id)
            from app.models import update_document
            update_document(doc_id, status="error")

    Thread(target=_run, daemon=True).start()
    return {"message": f"Reindexing {doc.filename}"}


@router.delete("/{doc_id}")
async def delete_doc(doc_id: str):
    doc = get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    delete_doc_chunks(doc_id)
    pdf_path = DATA_DIR / doc.filename
    # Only delete file if no other versions reference it
    other_versions = get_document_versions(doc.filename)
    if len(other_versions) <= 1 and pdf_path.exists():
        pdf_path.unlink()
    delete_document_record(doc_id)
    return {"message": f"Deleted {doc.filename} (v{doc.version})"}


@router.post("/bulk-delete")
async def bulk_delete(doc_ids: list[str]):
    """Delete multiple documents at once."""
    deleted = []
    for doc_id in doc_ids:
        doc = get_document(doc_id)
        if doc:
            delete_doc_chunks(doc_id)
            delete_document_record(doc_id)
            deleted.append(doc_id)
    return {"deleted": deleted}


@router.get("/{doc_id}/page/{page_num}/thumbnail")
async def page_thumbnail(doc_id: str, page_num: int):
    doc = get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    pdf_path = DATA_DIR / doc.filename
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF file not found on disk")

    from app.services.extractor import get_page_image_bytes
    try:
        png_bytes = get_page_image_bytes(pdf_path, page_num)
    except (IndexError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid page number")

    return Response(content=png_bytes, media_type="image/png")


@router.get("/{doc_id}/page/{page_num}/images")
async def page_images(doc_id: str, page_num: int, index: int = Query(0)):
    """Get an embedded image from a PDF page by index."""
    doc = get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    pdf_path = DATA_DIR / doc.filename
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF file not found")

    from app.services.extractor import extract_page_images
    images = extract_page_images(pdf_path, page_num)
    if index >= len(images):
        raise HTTPException(status_code=404, detail="Image not found")

    return Response(content=images[index], media_type="image/png")
