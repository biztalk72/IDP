"""Document management routes: upload, list, delete, page thumbnail."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from threading import Thread

import fitz  # PyMuPDF — used for page thumbnails
from fastapi import APIRouter, HTTPException, UploadFile

from app.config import DATA_DIR, UPLOAD_MAX_SIZE_MB
from app.models import (
    DocumentMeta,
    delete_document_record,
    get_document,
    list_documents,
)
from app.services.indexer import index_document
from app.services.vectorstore import delete_doc_chunks

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/upload", response_model=dict)
async def upload_document(file: UploadFile):
    """Upload a PDF and start async indexing."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    content = await file.read()
    if len(content) > UPLOAD_MAX_SIZE_MB * 1024 * 1024:
        raise HTTPException(status_code=400, detail=f"File exceeds {UPLOAD_MAX_SIZE_MB}MB limit")

    dest = DATA_DIR / file.filename
    dest.write_bytes(content)

    # Run indexing in background thread to avoid blocking
    def _run():
        try:
            index_document(dest)
        except Exception:
            logger.exception("Background indexing failed for %s", file.filename)

    Thread(target=_run, daemon=True).start()

    return {"message": f"Uploaded {file.filename}. Indexing started.", "filename": file.filename}


@router.get("/", response_model=list[DocumentMeta])
async def list_docs():
    """List all indexed documents."""
    return list_documents()


@router.get("/{doc_id}", response_model=DocumentMeta)
async def get_doc(doc_id: str):
    """Get a single document's metadata."""
    doc = get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.delete("/{doc_id}")
async def delete_doc(doc_id: str):
    """Delete a document and its vectors."""
    doc = get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Delete vector chunks
    delete_doc_chunks(doc_id)

    # Delete file
    pdf_path = DATA_DIR / doc.filename
    if pdf_path.exists():
        pdf_path.unlink()

    # Delete DB record
    delete_document_record(doc_id)

    return {"message": f"Deleted {doc.filename}"}


@router.get("/{doc_id}/page/{page_num}/thumbnail")
async def page_thumbnail(doc_id: str, page_num: int):
    """Render a PDF page as a PNG thumbnail for multimodal display."""
    from fastapi.responses import Response

    doc = get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    pdf_path = DATA_DIR / doc.filename
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF file not found on disk")

    pdf_doc = fitz.open(str(pdf_path))
    if page_num < 1 or page_num > len(pdf_doc):
        pdf_doc.close()
        raise HTTPException(status_code=400, detail="Invalid page number")

    page = pdf_doc[page_num - 1]
    pix = page.get_pixmap(dpi=150)
    png_bytes = pix.tobytes("png")
    pdf_doc.close()

    return Response(content=png_bytes, media_type="image/png")
