"""PDF text extraction with OCR fallback for scanned documents."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)

# Minimum characters per page to consider it "text-bearing"
TEXT_DENSITY_THRESHOLD = 30


@dataclass
class PageResult:
    page_number: int
    text: str
    method: str  # "native" or "ocr"


@dataclass
class ExtractionResult:
    filename: str
    page_count: int
    pages: list[PageResult] = field(default_factory=list)
    full_text: str = ""

    def build_full_text(self) -> None:
        self.full_text = "\n\n".join(p.text for p in self.pages if p.text.strip())


def _extract_native(doc: fitz.Document) -> list[PageResult]:
    """Extract text from native (non-scanned) PDF pages."""
    results: list[PageResult] = []
    for i, page in enumerate(doc):
        text = page.get_text("text")
        results.append(PageResult(page_number=i + 1, text=text.strip(), method="native"))
    return results


def _ocr_page(pdf_path: Path, page_number: int) -> str:
    """Run Tesseract OCR on a single page via pdf2image."""
    try:
        from pdf2image import convert_from_path
        import pytesseract
    except ImportError:
        logger.warning("pdf2image or pytesseract not installed; skipping OCR")
        return ""

    images = convert_from_path(
        str(pdf_path), first_page=page_number, last_page=page_number, dpi=300
    )
    if not images:
        return ""
    return pytesseract.image_to_string(images[0])


def extract_pdf(pdf_path: Path) -> ExtractionResult:
    """
    Extract text from a PDF file.

    Strategy:
    1. Try native text extraction with PyMuPDF.
    2. For pages with very little text (below threshold), fall back to OCR.
    """
    doc = fitz.open(str(pdf_path))
    page_count = len(doc)
    native_pages = _extract_native(doc)
    doc.close()

    final_pages: list[PageResult] = []
    for page in native_pages:
        if len(page.text) >= TEXT_DENSITY_THRESHOLD:
            final_pages.append(page)
        else:
            logger.info("Page %d has low text density, running OCR", page.page_number)
            ocr_text = _ocr_page(pdf_path, page.page_number)
            final_pages.append(
                PageResult(
                    page_number=page.page_number,
                    text=ocr_text.strip(),
                    method="ocr",
                )
            )

    result = ExtractionResult(
        filename=pdf_path.name,
        page_count=page_count,
        pages=final_pages,
    )
    result.build_full_text()
    return result
