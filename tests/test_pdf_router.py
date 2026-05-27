from __future__ import annotations

import fitz
from docx import Document

from app.documents.doc_converter import LegacyDocConverter
from app.documents.router import DocumentRouter
from app.llm.schemas import SourceFormat


class FakeLegacyDocConverter(LegacyDocConverter):
    def __init__(self, converted_path):
        self.converted_path = converted_path

    def convert_doc_to_docx(self, source_path):
        return self.converted_path


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


def test_router_converts_legacy_doc_before_docx_extraction(tmp_path):
    original_path = tmp_path / "contract.doc"
    original_path.write_bytes(b"legacy doc placeholder")
    converted_path = tmp_path / "contract.docx"
    document = Document()
    document.add_paragraph("Договор из старого Word")
    document.save(converted_path)

    router = DocumentRouter(legacy_doc_converter=FakeLegacyDocConverter(converted_path))
    result = router.route(original_path)
    canonical = router.extract(original_path, source_file_id="doc-1", filename="contract.doc")

    assert result.source_format == SourceFormat.DOCX
    assert canonical.filename == "contract.docx"
    assert "Договор из старого Word" in canonical.document_text
