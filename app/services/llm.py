"""Ollama LLM client for summarization and RAG Q&A."""

from __future__ import annotations

import logging

import httpx

from app.config import LLM_MODEL, OLLAMA_BASE_URL

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(300.0, connect=10.0)


def _generate(prompt: str, system: str = "") -> str:
    """Call Ollama /api/generate and return the response text."""
    payload: dict = {
        "model": LLM_MODEL,
        "prompt": prompt,
        "stream": False,
    }
    if system:
        payload["system"] = system

    with httpx.Client(timeout=_TIMEOUT) as client:
        resp = client.post(f"{OLLAMA_BASE_URL}/api/generate", json=payload)
        resp.raise_for_status()
        data = resp.json()

    return data.get("response", "").strip()


def generate_title(text: str) -> str:
    """Generate a concise document title from the first ~2000 chars."""
    snippet = text[:2000]
    prompt = (
        "Based on the following document excerpt, generate a concise and descriptive title "
        "(max 100 characters). Return ONLY the title, nothing else.\n\n"
        f"Document excerpt:\n{snippet}"
    )
    return _generate(prompt, system="You are a document analysis assistant.")


def generate_summary(text: str) -> str:
    """Generate a brief summary of the document."""
    snippet = text[:4000]
    prompt = (
        "Summarize the following document in 2-3 sentences. "
        "Be concise and capture the main topics.\n\n"
        f"Document:\n{snippet}"
    )
    return _generate(prompt, system="You are a document analysis assistant.")


def rag_answer(question: str, context_chunks: list[dict]) -> str:
    """
    Answer a question using retrieved context chunks.
    Each chunk dict has: text, document, page_number.
    Returns a structured answer with markdown formatting.
    """
    context_parts: list[str] = []
    for i, chunk in enumerate(context_chunks, 1):
        context_parts.append(
            f"[Source {i}: {chunk['document']}, Page {chunk['page_number']}]\n{chunk['text']}"
        )
    context_str = "\n\n---\n\n".join(context_parts)

    prompt = (
        f"Question: {question}\n\n"
        f"Context from documents:\n\n{context_str}\n\n"
        "Instructions:\n"
        "- Answer the question based ONLY on the provided context.\n"
        "- Use markdown formatting: tables, bullet points, code blocks, headings as appropriate.\n"
        "- If the context contains numerical data, present it in a markdown table.\n"
        "- Cite your sources using [Source N] notation.\n"
        "- If the context doesn't contain enough information, say so clearly.\n"
    )

    system = (
        "You are an intelligent document analysis assistant. "
        "Provide well-structured answers using markdown formatting. "
        "Always cite your sources."
    )
    return _generate(prompt, system=system)
