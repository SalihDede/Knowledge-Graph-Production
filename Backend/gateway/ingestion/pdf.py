from __future__ import annotations

import io
import logging

from pypdf import PdfReader

from documents.models import SegmentType
from documents.normalization import normalize_text
from documents.service import SegmentInput

from .errors import IngestionError
from .segmentation import iter_paragraphs_with_offsets

logger = logging.getLogger(__name__)


def _ocr_page(pdf_bytes: bytes, page_number: int) -> str:
    """Renders a single page to an image and OCRs it. Scanned/image-only PDF
    pages have no extractable text layer, so this is the fallback for those.
    Missing OCR system dependencies (poppler/tesseract) degrade to an empty
    string for that page rather than failing the whole document."""
    try:
        from pdf2image import convert_from_bytes
        import pytesseract
    except ImportError:
        logger.warning("OCR dependencies not installed; leaving page %s blank", page_number)
        return ""

    try:
        images = convert_from_bytes(pdf_bytes, first_page=page_number, last_page=page_number)
        if not images:
            return ""
        return pytesseract.image_to_string(images[0], lang="tur+eng")
    except Exception:
        logger.warning("OCR failed for page %s", page_number, exc_info=True)
        return ""


def extract_pdf(pdf_bytes: bytes) -> tuple[str, list[SegmentInput], int]:
    """Extracts text from a PDF, falling back to OCR for pages with no text
    layer. Returns (normalized_full_text, segments, page_count). Segments
    include one "page" row per page plus "paragraph" rows within it, all with
    char offsets into the returned full text."""
    if not pdf_bytes.startswith(b"%PDF-"):
        raise IngestionError("Dosya geçerli bir PDF değil (magic-byte doğrulaması başarısız)")

    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
    except Exception as exc:
        raise IngestionError("PDF okunamadı; dosya bozuk olabilir") from exc

    page_count = len(reader.pages)
    if page_count == 0:
        raise IngestionError("PDF içinde sayfa bulunamadı")

    normalized_pages: list[str] = []
    for index, page in enumerate(reader.pages, start=1):
        try:
            raw_text = (page.extract_text() or "").strip()
        except Exception:
            raw_text = ""

        if not raw_text:
            raw_text = _ocr_page(pdf_bytes, index).strip()

        normalized_pages.append(normalize_text(raw_text))

    full_text = "\n\n".join(normalized_pages)
    if not full_text.strip():
        raise IngestionError("PDF içinde okunabilir metin bulunamadı (OCR sonrası da boş)")

    segments: list[SegmentInput] = []
    ordinal = 0
    cursor = 0
    for page_number, page_text in enumerate(normalized_pages, start=1):
        page_start = cursor
        page_end = page_start + len(page_text)
        segments.append(SegmentInput(
            segment_type=SegmentType.page,
            page_number=page_number,
            ordinal=ordinal,
            text=page_text,
            char_start=page_start,
            char_end=page_end,
        ))
        ordinal += 1

        for paragraph_text, local_start, local_end in iter_paragraphs_with_offsets(page_text):
            segments.append(SegmentInput(
                segment_type=SegmentType.paragraph,
                page_number=page_number,
                ordinal=ordinal,
                text=paragraph_text,
                char_start=page_start + local_start,
                char_end=page_start + local_end,
            ))
            ordinal += 1

        cursor = page_end + 2  # length of the "\n\n" joiner between pages

    return full_text, segments, page_count
