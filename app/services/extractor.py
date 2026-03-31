"""PDF text extraction with adaptive pipeline: Native → OCR → OCR+LLM → OCR+VLM."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import fitz  # PyMuPDF

from app.config import TEXT_DENSITY_THRESHOLD, OCR_QUALITY_THRESHOLD

logger = logging.getLogger(__name__)


@dataclass
class PageResult:
    page_number: int
    text: str
    method: str  # "native", "ocr", "ocr+llm", "ocr+vlm"


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


def _llm_correct_ocr(ocr_text: str) -> str:
    """Use LLM to post-process and correct OCR output."""
    try:
        from app.services.llm import correct_ocr_text
        return correct_ocr_text(ocr_text)
    except Exception as e:
        logger.warning("LLM OCR correction failed: %s", e)
        return ocr_text


def _vlm_extract_page(pdf_path: Path, page_number: int) -> str:
    """Use VLM to extract content from a page image."""
    try:
        doc = fitz.open(str(pdf_path))
        page = doc[page_number - 1]
        pix = page.get_pixmap(dpi=200)
        image_bytes = pix.tobytes("png")
        doc.close()

        from app.services.vlm import vlm_describe_page
        return vlm_describe_page(image_bytes)
    except Exception as e:
        logger.warning("VLM extraction failed for page %d: %s", page_number, e)
        return ""


def extract_pdf(pdf_path: Path) -> ExtractionResult:
    """
    Extract text from a PDF file using adaptive strategy per page:

    1. Native text density ≥ TEXT_DENSITY_THRESHOLD → use native text
    2. Run OCR; if OCR text density ≥ OCR_QUALITY_THRESHOLD → use OCR (+ LLM correction)
    3. If OCR text density < OCR_QUALITY_THRESHOLD → use VLM
    """
    doc = fitz.open(str(pdf_path))
    page_count = len(doc)
    native_pages = _extract_native(doc)
    doc.close()

    final_pages: list[PageResult] = []
    for page in native_pages:
        # Strategy 1: native text is good enough
        if len(page.text) >= TEXT_DENSITY_THRESHOLD:
            final_pages.append(page)
            continue

        # Strategy 2: try OCR
        logger.info("Page %d: low native text (%d chars), running OCR",
                    page.page_number, len(page.text))
        ocr_text = _ocr_page(pdf_path, page.page_number)

        if len(ocr_text.strip()) >= OCR_QUALITY_THRESHOLD:
            # OCR produced reasonable text — optionally correct with LLM
            corrected = _llm_correct_ocr(ocr_text.strip())
            method = "ocr+llm" if corrected != ocr_text.strip() else "ocr"
            final_pages.append(
                PageResult(page_number=page.page_number, text=corrected, method=method)
            )
            continue

        # Strategy 3: OCR failed — use VLM
        logger.info("Page %d: OCR low quality (%d chars), trying VLM",
                    page.page_number, len(ocr_text.strip()))
        vlm_text = _vlm_extract_page(pdf_path, page.page_number)
        if vlm_text:
            final_pages.append(
                PageResult(page_number=page.page_number, text=vlm_text, method="ocr+vlm")
            )
        else:
            # Fallback: use whatever OCR gave us
            final_pages.append(
                PageResult(page_number=page.page_number, text=ocr_text.strip(), method="ocr")
            )

    result = ExtractionResult(
        filename=pdf_path.name,
        page_count=page_count,
        pages=final_pages,
    )
    result.build_full_text()
    return result


def get_page_image_bytes(pdf_path: Path, page_number: int, dpi: int = 150) -> bytes:
    """Render a PDF page as PNG bytes."""
    doc = fitz.open(str(pdf_path))
    page = doc[page_number - 1]
    pix = page.get_pixmap(dpi=dpi)
    png_bytes = pix.tobytes("png")
    doc.close()
    return png_bytes


def extract_page_images(pdf_path: Path, page_number: int) -> list[bytes]:
    """Extract embedded images from a specific PDF page."""
    images: list[bytes] = []
    doc = fitz.open(str(pdf_path))
    page = doc[page_number - 1]
    for img_info in page.get_images(full=True):
        xref = img_info[0]
        base_image = doc.extract_image(xref)
        if base_image and base_image.get("image"):
            images.append(base_image["image"])
    doc.close()
    return images
