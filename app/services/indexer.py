"""Document indexing pipeline — orchestrates extraction, chunking, embedding, and metadata."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from app.models import insert_document, update_document
from app.services.chunker import chunk_document
from app.services.extractor import extract_pdf
from app.services.llm import generate_summary, generate_title
from app.services.vectorstore import add_chunks

logger = logging.getLogger(__name__)


def index_document(pdf_path: Path, version: int = 1, parent_id: str = "") -> str:
    """
    Full indexing pipeline for a single PDF:
    1. Create DB record (status=processing)
    2. Extract text (native + OCR + LLM/VLM adaptive)
    3. Chunk the text
    4. Embed and store in vector DB
    5. Generate title & summary via LLM
    6. Update DB record (status=ready)

    Returns the document ID.
    """
    doc_id = uuid.uuid4().hex[:12]
    filename = pdf_path.name

    # Step 1: Create initial record
    insert_document(doc_id=doc_id, filename=filename, status="processing",
                    version=version, parent_id=parent_id)
    logger.info("Indexing %s as doc_id=%s", filename, doc_id)

    try:
        # Step 2: Extract text
        extraction = extract_pdf(pdf_path)
        logger.info(
            "Extracted %d pages from %s (%d chars)",
            extraction.page_count,
            filename,
            len(extraction.full_text),
        )

        # Step 3: Chunk
        chunks = chunk_document(extraction, doc_id=doc_id)
        logger.info("Created %d chunks", len(chunks))

        # Step 4: Embed and store
        add_chunks(chunks)

        # Step 5: Generate metadata via LLM
        title = generate_title(extraction.full_text)
        summary = generate_summary(extraction.full_text)

        # Step 6: Update record
        update_document(
            doc_id,
            title=title,
            summary=summary,
            chunk_count=len(chunks),
            page_count=extraction.page_count,
            status="ready",
        )

        logger.info("Successfully indexed %s: '%s'", filename, title)

    except Exception as e:
        logger.exception("Failed to index %s: %s", filename, e)
        update_document(doc_id, status="error")
        raise

    return doc_id
