from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import fitz

from app.documents.base import DocumentExtractor
from app.documents.docx_extractor import DOCXExtractor
from app.documents.pdf_mixed_extractor import PDFMixedExtractor
from app.documents.pdf_ocr_extractor import PDFOCRExtractor
from app.documents.pdf_text_extractor import PDFTextExtractor
from app.llm.schemas import CanonicalDocument, SourceFormat


@dataclass(frozen=True)
class RoutingResult:
    source_format: SourceFormat
    extractor: DocumentExtractor | None
    reason: str


class DocumentRouter:
    def __init__(
        self,
        docx_extractor: DOCXExtractor | None = None,
        pdf_text_extractor: PDFTextExtractor | None = None,
        pdf_ocr_extractor: PDFOCRExtractor | None = None,
        pdf_mixed_extractor: PDFMixedExtractor | None = None,
        min_text_chars_per_page: int = 100,
    ) -> None:
        self.docx_extractor = docx_extractor or DOCXExtractor()
        self.pdf_text_extractor = pdf_text_extractor or PDFTextExtractor()
        self.pdf_ocr_extractor = pdf_ocr_extractor or PDFOCRExtractor()
        self.pdf_mixed_extractor = pdf_mixed_extractor or PDFMixedExtractor(
            min_text_chars_per_page=min_text_chars_per_page
        )
        self.min_text_chars_per_page = min_text_chars_per_page

    def route(self, file_path: str | Path) -> RoutingResult:
        path = Path(file_path)
        suffix = path.suffix.lower()
        if suffix == ".docx":
            return RoutingResult(SourceFormat.DOCX, self.docx_extractor, "DOCX extension")
        if suffix != ".pdf":
            return RoutingResult(SourceFormat.UNSUPPORTED, None, f"Unsupported extension: {suffix}")

        page_text_lengths = self._pdf_page_text_lengths(path)
        if not page_text_lengths:
            return RoutingResult(SourceFormat.PDF_SCAN, self.pdf_ocr_extractor, "PDF has no pages or no text")

        text_pages = sum(length >= self.min_text_chars_per_page for length in page_text_lengths)
        total_pages = len(page_text_lengths)
        if text_pages == total_pages:
            return RoutingResult(SourceFormat.PDF_TEXT, self.pdf_text_extractor, "All PDF pages have extractable text")
        if text_pages == 0:
            return RoutingResult(SourceFormat.PDF_SCAN, self.pdf_ocr_extractor, "No PDF pages have enough text")

        return RoutingResult(
            SourceFormat.PDF_MIXED,
            self.pdf_mixed_extractor,
            f"PDF has mixed text/scanned pages: {text_pages}/{total_pages} text pages",
        )

    def extract(self, file_path: str | Path, source_file_id: str, filename: str) -> CanonicalDocument:
        result = self.route(file_path)
        if result.extractor is None:
            raise ValueError(result.reason)
        return result.extractor.extract(file_path, source_file_id=source_file_id, filename=filename)

    def _pdf_page_text_lengths(self, path: Path) -> list[int]:
        lengths: list[int] = []
        with fitz.open(path) as pdf:
            for page in pdf:
                text = page.get_text("text").strip()
                lengths.append(len(text))
        return lengths
