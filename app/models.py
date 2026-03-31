"""Pydantic schemas and SQLite database helpers."""

from __future__ import annotations

import json
import sqlite3
import uuid
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
    version: int = 1
    parent_id: str = ""
    created_at: str


class QueryRequest(BaseModel):
    question: str
    top_k: int = 5
    conversation_id: Optional[str] = None


class QueryResponse(BaseModel):
    answer: str
    sources: list[SourceRef]
    conversation_id: str = ""


class SourceRef(BaseModel):
    document: str
    doc_id: str = ""
    page: int
    chunk_text: str


class ConversationMeta(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str


class MessageMeta(BaseModel):
    id: str
    conversation_id: str
    role: str  # "user" or "assistant"
    content: str
    sources_json: str = "[]"
    created_at: str


# Rebuild models that have forward references
QueryResponse.model_rebuild()


# ---------------------------------------------------------------------------
# SQLite helpers
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    title TEXT DEFAULT '',
    summary TEXT DEFAULT '',
    page_count INTEGER DEFAULT 0,
    chunk_count INTEGER DEFAULT 0,
    status TEXT DEFAULT 'processing',
    version INTEGER DEFAULT 1,
    parent_id TEXT DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    title TEXT DEFAULT 'New Conversation',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    sources_json TEXT DEFAULT '[]',
    created_at TEXT NOT NULL,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);
"""


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(SQLITE_DB))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    for stmt in _SCHEMA.strip().split(";"):
        stmt = stmt.strip()
        if stmt:
            conn.execute(stmt)
    conn.commit()
    return conn


# --- Document helpers ---


def insert_document(
    doc_id: str,
    filename: str,
    page_count: int = 0,
    status: str = "processing",
    version: int = 1,
    parent_id: str = "",
) -> None:
    conn = get_db()
    conn.execute(
        "INSERT INTO documents (id, filename, page_count, status, version, parent_id, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (doc_id, filename, page_count, status, version, parent_id,
         datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()


def update_document(
    doc_id: str,
    *,
    title: Optional[str] = None,
    summary: Optional[str] = None,
    chunk_count: Optional[int] = None,
    page_count: Optional[int] = None,
    status: Optional[str] = None,
) -> None:
    updates: list[str] = []
    values: list = []
    for col, val in [("title", title), ("summary", summary),
                     ("chunk_count", chunk_count), ("page_count", page_count),
                     ("status", status)]:
        if val is not None:
            updates.append(f"{col} = ?")
            values.append(val)
    if not updates:
        return
    values.append(doc_id)
    conn = get_db()
    conn.execute(f"UPDATE documents SET {', '.join(updates)} WHERE id = ?", values)
    conn.commit()
    conn.close()


def list_documents(
    sort_by: str = "created_at",
    order: str = "desc",
    status: Optional[str] = None,
) -> list[DocumentMeta]:
    allowed_sort = {"title", "filename", "created_at", "page_count", "status"}
    if sort_by not in allowed_sort:
        sort_by = "created_at"
    order_sql = "DESC" if order.lower() == "desc" else "ASC"

    conn = get_db()
    query = "SELECT * FROM documents"
    params: list = []
    if status:
        query += " WHERE status = ?"
        params.append(status)
    query += f" ORDER BY {sort_by} {order_sql}"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [DocumentMeta(**dict(r)) for r in rows]


def get_document(doc_id: str) -> Optional[DocumentMeta]:
    conn = get_db()
    row = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    conn.close()
    return DocumentMeta(**dict(row)) if row else None


def get_document_versions(filename: str) -> list[DocumentMeta]:
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM documents WHERE filename = ? ORDER BY version DESC",
        (filename,),
    ).fetchall()
    conn.close()
    return [DocumentMeta(**dict(r)) for r in rows]


def get_latest_version(filename: str) -> int:
    conn = get_db()
    row = conn.execute(
        "SELECT MAX(version) as max_ver FROM documents WHERE filename = ?",
        (filename,),
    ).fetchone()
    conn.close()
    return (row["max_ver"] or 0) if row else 0


def delete_document_record(doc_id: str) -> None:
    conn = get_db()
    conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
    conn.commit()
    conn.close()


# --- Conversation helpers ---


def create_conversation(title: str = "New Conversation") -> ConversationMeta:
    conv_id = uuid.uuid4().hex[:12]
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    conn.execute(
        "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (conv_id, title, now, now),
    )
    conn.commit()
    conn.close()
    return ConversationMeta(id=conv_id, title=title, created_at=now, updated_at=now)


def list_conversations() -> list[ConversationMeta]:
    conn = get_db()
    rows = conn.execute("SELECT * FROM conversations ORDER BY updated_at DESC").fetchall()
    conn.close()
    return [ConversationMeta(**dict(r)) for r in rows]


def get_conversation(conv_id: str) -> Optional[ConversationMeta]:
    conn = get_db()
    row = conn.execute("SELECT * FROM conversations WHERE id = ?", (conv_id,)).fetchone()
    conn.close()
    return ConversationMeta(**dict(row)) if row else None


def update_conversation_title(conv_id: str, title: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    conn.execute(
        "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
        (title, now, conv_id),
    )
    conn.commit()
    conn.close()


def delete_conversation(conv_id: str) -> None:
    conn = get_db()
    conn.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
    conn.commit()
    conn.close()


# --- Message helpers ---


def add_message(
    conversation_id: str,
    role: str,
    content: str,
    sources: Optional[list[dict]] = None,
) -> MessageMeta:
    msg_id = uuid.uuid4().hex[:12]
    now = datetime.now(timezone.utc).isoformat()
    sources_json = json.dumps(sources or [], ensure_ascii=False)
    conn = get_db()
    conn.execute(
        "INSERT INTO messages (id, conversation_id, role, content, sources_json, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (msg_id, conversation_id, role, content, sources_json, now),
    )
    conn.execute(
        "UPDATE conversations SET updated_at = ? WHERE id = ?",
        (now, conversation_id),
    )
    conn.commit()
    conn.close()
    return MessageMeta(
        id=msg_id, conversation_id=conversation_id, role=role,
        content=content, sources_json=sources_json, created_at=now,
    )


def get_messages(conversation_id: str, limit: int = 100) -> list[MessageMeta]:
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at ASC LIMIT ?",
        (conversation_id, limit),
    ).fetchall()
    conn.close()
    return [MessageMeta(**dict(r)) for r in rows]
