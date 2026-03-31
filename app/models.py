"""Pydantic schemas and SQLite database helpers."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel

from app.config import SQLITE_DB

# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class DocumentMeta(BaseModel):
    id: str
    filename: str
    title: str
    summary: str
    page_count: int
    chunk_count: int
    status: str  # "processing", "ready", "error"
    created_at: str


class QueryRequest(BaseModel):
    question: str
    top_k: int = 5


class QueryResponse(BaseModel):
    answer: str
    sources: list[SourceRef]


class SourceRef(BaseModel):
    document: str
    page: int
    chunk_text: str


# Rebuild models that have forward references
QueryResponse.model_rebuild()


# ---------------------------------------------------------------------------
# SQLite helpers
# ---------------------------------------------------------------------------

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    title TEXT DEFAULT '',
    summary TEXT DEFAULT '',
    page_count INTEGER DEFAULT 0,
    chunk_count INTEGER DEFAULT 0,
    status TEXT DEFAULT 'processing',
    created_at TEXT NOT NULL
);
"""


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(SQLITE_DB))
    conn.row_factory = sqlite3.Row
    conn.execute(_CREATE_TABLE)
    conn.commit()
    return conn


def insert_document(
    doc_id: str,
    filename: str,
    page_count: int = 0,
    status: str = "processing",
) -> None:
    conn = get_db()
    conn.execute(
        "INSERT INTO documents (id, filename, page_count, status, created_at) VALUES (?, ?, ?, ?, ?)",
        (doc_id, filename, page_count, status, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()


def update_document(
    doc_id: str,
    *,
    title: Optional[str] = None,
    summary: Optional[str] = None,
    chunk_count: Optional[int] = None,
    status: Optional[str] = None,
) -> None:
    updates: list[str] = []
    values: list = []
    if title is not None:
        updates.append("title = ?")
        values.append(title)
    if summary is not None:
        updates.append("summary = ?")
        values.append(summary)
    if chunk_count is not None:
        updates.append("chunk_count = ?")
        values.append(chunk_count)
    if status is not None:
        updates.append("status = ?")
        values.append(status)
    if not updates:
        return
    values.append(doc_id)
    conn = get_db()
    conn.execute(f"UPDATE documents SET {', '.join(updates)} WHERE id = ?", values)
    conn.commit()
    conn.close()


def list_documents() -> list[DocumentMeta]:
    conn = get_db()
    rows = conn.execute("SELECT * FROM documents ORDER BY created_at DESC").fetchall()
    conn.close()
    return [DocumentMeta(**dict(r)) for r in rows]


def get_document(doc_id: str) -> Optional[DocumentMeta]:
    conn = get_db()
    row = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    conn.close()
    return DocumentMeta(**dict(row)) if row else None


def delete_document_record(doc_id: str) -> None:
    conn = get_db()
    conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
    conn.commit()
    conn.close()
