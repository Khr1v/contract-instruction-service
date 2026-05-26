from __future__ import annotations

import fitz

from app.documents.router import DocumentRouter
from app.llm.schemas import SourceFormat


def test_pdf_router_detects_digital_pdf(tmp_path):
    path = tmp_path / "digital.pdf"
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "Договор оказания услуг " * 20)
    pdf.save(path)
    pdf.close()

    result = DocumentRouter(min_text_chars_per_page=50).route(path)

    assert result.source_format == SourceFormat.PDF_TEXT


def test_pdf_router_detects_scanned_like_pdf(tmp_path):
    path = tmp_path / "scan.pdf"
    pdf = fitz.open()
    pdf.new_page()
    pdf.save(path)
    pdf.close()

    result = DocumentRouter(min_text_chars_per_page=50).route(path)

    assert result.source_format == SourceFormat.PDF_SCAN


def test_pdf_router_detects_mixed_pdf(tmp_path):
    path = tmp_path / "mixed.pdf"
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "Договор оказания услуг " * 20)
    pdf.new_page()
    pdf.save(path)
    pdf.close()

    result = DocumentRouter(min_text_chars_per_page=50).route(path)

    assert result.source_format == SourceFormat.PDF_MIXED
