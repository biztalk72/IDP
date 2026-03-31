"""Ollama embedding client using mxbai-embed-large."""

from __future__ import annotations

import logging

import httpx

from app.config import EMBED_MODEL, OLLAMA_BASE_URL

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(120.0, connect=10.0)


def embed_texts(texts: list[str]) -> list[list[float]]:
    """
    Embed a batch of texts via Ollama /api/embed.
    Returns list of embedding vectors.
    """
    if not texts:
        return []

    with httpx.Client(timeout=_TIMEOUT) as client:
        resp = client.post(
            f"{OLLAMA_BASE_URL}/api/embed",
            json={"model": EMBED_MODEL, "input": texts},
        )
        resp.raise_for_status()
        data = resp.json()

    embeddings = data.get("embeddings", [])
    if len(embeddings) != len(texts):
        logger.warning("Expected %d embeddings, got %d", len(texts), len(embeddings))
    return embeddings


def embed_single(text: str) -> list[float]:
    """Embed a single text string."""
    results = embed_texts([text])
    return results[0] if results else []
