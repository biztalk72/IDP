"""ChromaDB vector store for document chunk storage and retrieval."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import chromadb

from app.config import CHROMA_DIR, TOP_K
from app.services.chunker import Chunk
from app.services.embedder import embed_single, embed_texts

logger = logging.getLogger(__name__)

COLLECTION_NAME = "idp_documents"


def _get_client() -> chromadb.PersistentClient:
    return chromadb.PersistentClient(path=str(CHROMA_DIR))


def _get_collection() -> chromadb.Collection:
    client = _get_client()
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


@dataclass
class SearchResult:
    text: str
    doc_id: str
    page_number: int
    chunk_index: int
    distance: float


def add_chunks(chunks: list[Chunk]) -> None:
    """Add document chunks to the vector store."""
    if not chunks:
        return

    collection = _get_collection()
    texts = [c.text for c in chunks]
    embeddings = embed_texts(texts)

    ids = [f"{c.doc_id}_chunk_{c.chunk_index}" for c in chunks]
    metadatas = [
        {
            "doc_id": c.doc_id,
            "page_number": c.page_number,
            "chunk_index": c.chunk_index,
        }
        for c in chunks
    ]

    # ChromaDB has a batch limit; insert in batches of 100
    batch_size = 100
    for i in range(0, len(chunks), batch_size):
        end = i + batch_size
        collection.add(
            ids=ids[i:end],
            embeddings=embeddings[i:end],
            documents=texts[i:end],
            metadatas=metadatas[i:end],
        )

    logger.info("Added %d chunks to vector store", len(chunks))


def search(query: str, top_k: int = TOP_K, doc_id: str | None = None) -> list[SearchResult]:
    """Search for similar chunks. Optionally filter by doc_id."""
    collection = _get_collection()
    query_embedding = embed_single(query)

    where_filter = {"doc_id": doc_id} if doc_id else None

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        where=where_filter,
        include=["documents", "metadatas", "distances"],
    )

    search_results: list[SearchResult] = []
    if results and results["documents"]:
        for doc, meta, dist in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            search_results.append(
                SearchResult(
                    text=doc,
                    doc_id=meta["doc_id"],
                    page_number=meta["page_number"],
                    chunk_index=meta["chunk_index"],
                    distance=dist,
                )
            )
    return search_results


def delete_doc_chunks(doc_id: str) -> None:
    """Delete all chunks belonging to a document."""
    collection = _get_collection()
    try:
        collection.delete(where={"doc_id": doc_id})
        logger.info("Deleted chunks for doc_id=%s", doc_id)
    except Exception as e:
        logger.warning("Error deleting chunks for %s: %s", doc_id, e)
