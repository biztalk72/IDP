"""Ollama LLM client for summarization, OCR correction, and RAG Q&A."""

from __future__ import annotations

import logging

import httpx

from app.config import CONVERSATION_HISTORY_LIMIT, LLM_MODEL, OCR_LLM_MODEL, OLLAMA_BASE_URL

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(300.0, connect=10.0)


def _get_ocr_model() -> str:
    return OCR_LLM_MODEL if OCR_LLM_MODEL else LLM_MODEL


def _generate(prompt: str, system: str = "", model: str = "") -> str:
    """Call Ollama /api/generate and return the response text."""
    payload: dict = {
        "model": model or LLM_MODEL,
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


def correct_ocr_text(ocr_text: str) -> str:
    """Use LLM to correct OCR errors and restore formatting."""
    prompt = (
        "The following text was extracted via OCR and may contain errors. "
        "Fix spelling errors, broken words, and formatting issues. "
        "Reconstruct tables as markdown tables if applicable. "
        "Return ONLY the corrected text, nothing else.\n\n"
        f"OCR text:\n{ocr_text[:4000]}"
    )
    return _generate(prompt, system="You are an OCR post-processing assistant.",
                     model=_get_ocr_model())


def rag_answer(
    question: str,
    context_chunks: list[dict],
    conversation_history: list[dict] | None = None,
) -> str:
    """
    Answer a question using retrieved context chunks and optional conversation history.
    Each chunk dict has: text, document, page_number.
    conversation_history: list of {role, content} dicts.
    """
    context_parts: list[str] = []
    for i, chunk in enumerate(context_chunks, 1):
        context_parts.append(
            f"[Source {i}: {chunk['document']}, Page {chunk['page_number']}]\n{chunk['text']}"
        )
    context_str = "\n\n---\n\n".join(context_parts)

    # Build conversation context
    history_str = ""
    if conversation_history:
        recent = conversation_history[-CONVERSATION_HISTORY_LIMIT:]
        parts = []
        for msg in recent:
            role = "User" if msg["role"] == "user" else "Assistant"
            parts.append(f"{role}: {msg['content'][:500]}")
        history_str = "\n".join(parts)

    prompt = ""
    if history_str:
        prompt += f"Conversation history:\n{history_str}\n\n"

    prompt += (
        f"Question: {question}\n\n"
        f"Context from documents:\n\n{context_str}\n\n"
        "Instructions:\n"
        "- Answer the question based ONLY on the provided context.\n"
        "- Use markdown formatting: tables, bullet points, code blocks, headings as appropriate.\n"
        "- If the context contains numerical data, present it in a markdown table.\n"
        "- Cite your sources using [Source N] notation.\n"
        "- If the user asks for a graph or chart, output the data as a markdown table "
        "  AND add a line: GRAPH_REQUEST: {type} where type is bar/line/scatter/pie/histogram/3d_scatter/3d_surface.\n"
        "- If the context doesn't contain enough information, say so clearly.\n"
    )

    system = (
        "You are an intelligent document analysis assistant. "
        "Provide well-structured answers using markdown formatting. "
        "Always cite your sources. Consider the conversation history for context."
    )
    return _generate(prompt, system=system)


def generate_conversation_title(first_question: str) -> str:
    """Generate a short title for a conversation from the first question."""
    prompt = (
        "Generate a very short title (max 50 chars) for a conversation that starts with "
        f"this question. Return ONLY the title:\n\n{first_question[:200]}"
    )
    title = _generate(prompt)
    return title[:50] if title else first_question[:50]
