"""Text chunking with page-number metadata preservation."""

from __future__ import annotations

from dataclasses import dataclass

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import CHUNK_OVERLAP, CHUNK_SIZE
from app.services.extractor import ExtractionResult


@dataclass
class Chunk:
    text: str
    chunk_index: int
    page_number: int
    doc_id: str = ""


def chunk_document(extraction: ExtractionResult, doc_id: str = "") -> list[Chunk]:
    """
    Split extracted pages into overlapping chunks.
    Each chunk retains the page number it originated from.
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""],
    )

    chunks: list[Chunk] = []
    idx = 0
    for page in extraction.pages:
        if not page.text.strip():
            continue
        page_chunks = splitter.split_text(page.text)
        for text in page_chunks:
            chunks.append(
                Chunk(
                    text=text,
                    chunk_index=idx,
                    page_number=page.page_number,
                    doc_id=doc_id,
                )
            )
            idx += 1

    return chunks
