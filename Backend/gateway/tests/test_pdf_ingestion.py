from __future__ import annotations

import io

import pytest
from reportlab.pdfgen import canvas

from documents.models import SegmentType
from ingestion.errors import IngestionError
import ingestion.pdf as pdf_module
from ingestion.pdf import extract_pdf


def _build_pdf(pages: list[str]) -> bytes:
    buffer = io.BytesIO()
    pdf_canvas = canvas.Canvas(buffer)
    for page_text in pages:
        pdf_canvas.drawString(72, 700, page_text)
        pdf_canvas.showPage()
    pdf_canvas.save()
    return buffer.getvalue()


def test_extract_pdf_returns_full_text_and_page_count() -> None:
    pdf_bytes = _build_pdf(["First page content.", "Second page content."])

    full_text, segments, page_count = extract_pdf(pdf_bytes)

    assert page_count == 2
    assert "First page content." in full_text
    assert "Second page content." in full_text
    assert segments  # at least the page segments


def test_extract_pdf_page_segment_offsets_slice_back_correctly() -> None:
    pdf_bytes = _build_pdf(["First page content.", "Second page content."])

    full_text, segments, _ = extract_pdf(pdf_bytes)

    page_segments = [s for s in segments if s.segment_type == SegmentType.page]
    assert [s.page_number for s in page_segments] == [1, 2]
    for segment in page_segments:
        assert full_text[segment.char_start:segment.char_end] == segment.text


def test_extract_pdf_rejects_non_pdf_bytes() -> None:
    with pytest.raises(IngestionError):
        extract_pdf(b"this is definitely not a pdf")


def test_extract_pdf_falls_back_to_ocr_for_blank_pages(monkeypatch) -> None:
    # A page with no drawString calls has no extractable text layer.
    pdf_bytes = _build_pdf([""])

    monkeypatch.setattr(pdf_module, "_ocr_page", lambda _bytes, _page: "OCR'd content")

    full_text, segments, page_count = extract_pdf(pdf_bytes)

    assert page_count == 1
    assert "OCR'd content" in full_text
    page_segments = [s for s in segments if s.segment_type == SegmentType.page]
    assert page_segments[0].text == "OCR'd content"


def test_extract_pdf_raises_when_no_text_layer_and_ocr_yields_nothing(monkeypatch) -> None:
    pdf_bytes = _build_pdf([""])

    monkeypatch.setattr(pdf_module, "_ocr_page", lambda _bytes, _page: "")

    with pytest.raises(IngestionError):
        extract_pdf(pdf_bytes)


def test_ocr_page_degrades_gracefully_without_dependencies(monkeypatch) -> None:
    # Simulates poppler/tesseract not being installed: pdf2image import fails.
    import builtins

    real_import = builtins.__import__

    def blocking_import(name, *args, **kwargs):
        if name in {"pdf2image", "pytesseract"}:
            raise ImportError(f"No module named '{name}'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocking_import)

    assert pdf_module._ocr_page(b"irrelevant", 1) == ""
