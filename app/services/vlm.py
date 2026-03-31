"""Vision-Language Model client via Ollama for image understanding."""

from __future__ import annotations

import base64
import logging
from pathlib import Path

import httpx

from app.config import OLLAMA_BASE_URL, VLM_MODEL

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(300.0, connect=10.0)


def _image_to_base64(image_path: Path) -> str:
    """Read an image file and return its base64 encoding."""
    return base64.b64encode(image_path.read_bytes()).decode("utf-8")


def _bytes_to_base64(data: bytes) -> str:
    return base64.b64encode(data).decode("utf-8")


def vlm_describe_page(image_bytes: bytes, prompt: str = "") -> str:
    """
    Send a page image to the VLM and get a text description.
    Uses Ollama /api/chat with image support.
    """
    if not prompt:
        prompt = (
            "Extract all text content from this document page image. "
            "Preserve the structure: tables as markdown tables, lists as bullet points, "
            "headings as markdown headings. If there are charts or diagrams, describe them. "
            "Return ONLY the extracted content, no commentary."
        )

    b64 = _bytes_to_base64(image_bytes)

    payload = {
        "model": VLM_MODEL,
        "messages": [
            {
                "role": "user",
                "content": prompt,
                "images": [b64],
            }
        ],
        "stream": False,
    }

    try:
        with httpx.Client(timeout=_TIMEOUT) as client:
            resp = client.post(f"{OLLAMA_BASE_URL}/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()
        return data.get("message", {}).get("content", "").strip()
    except Exception as e:
        logger.error("VLM inference failed: %s", e)
        return ""


def vlm_extract_images_info(image_bytes: bytes) -> str:
    """Ask VLM to describe embedded charts/diagrams in a page image."""
    prompt = (
        "Analyze this document page image. "
        "If there are any charts, graphs, diagrams, or photos, "
        "describe each one in detail including data values if visible. "
        "If there are no images/charts, respond with 'NO_IMAGES'."
    )
    return vlm_describe_page(image_bytes, prompt)
