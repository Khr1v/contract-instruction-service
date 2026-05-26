from __future__ import annotations

from pathlib import Path

import fitz

from app.documents.base import DocumentExtractor
from app.documents.pdf_ocr_extractor import OCRProvider, StubOCRProvider
from app.documents.quality import estimate_text_quality
from app.llm.prompts import OCR_PAGE_PROMPT
from app.llm.schemas import CanonicalDocument, PageOrSection, SourceFormat


class PDFMixedExtractor(DocumentExtractor):
    """Extract digital pages directly and route low-text pages to OCR/VLM."""

    def __init__(
        self,
        ocr_provider: OCRProvider | None = None,
        min_text_chars_per_page: int = 100,
        dpi: int = 180,
        max_pages: int = 40,
    ) -> None:
        self.ocr_provider = ocr_provider or StubOCRProvider()
        self.min_text_chars_per_page = min_text_chars_per_page
        self.dpi = dpi
        self.max_pages = max_pages

    def extract(self, file_path: str | Path, source_file_id: str, filename: str) -> CanonicalDocument:
        path = Path(file_path)
        warnings: list[str] = []
        pages: list[PageOrSection] = []
        text_parts: list[str] = []
        zoom = self.dpi / 72
        matrix = fitz.Matrix(zoom, zoom)

        with fitz.open(path) as pdf:
            for index, page in enumerate(pdf, start=1):
                if index > self.max_pages:
                    warnings.append(f"PDF содержит больше {self.max_pages} страниц; оставшиеся страницы не распознаны.")
                    break
                ref = f"page_{index}"
                text = page.get_text("text").strip()
                page_warnings: list[str] = []
                if len(text) < self.min_text_chars_per_page:
                    pixmap = page.get_pixmap(matrix=matrix, alpha=False)
                    image_bytes = pixmap.tobytes("png")
                    ocr_text, ocr_warnings = self.ocr_provider.extract_page_text(image_bytes, ref, OCR_PAGE_PROMPT)
                    page_warnings.extend(ocr_warnings)
                    warnings.extend(ocr_warnings)
                    text = ocr_text.strip()
                quality = estimate_text_quality(text, min_chars=350)
                if not text:
                    page_warnings.append("Страница не была распознана; требуется OCR/VLM или ручная проверка.")
                    warnings.append(f"{ref}: Страница не была распознана; требуется OCR/VLM или ручная проверка.")
                pages.append(
                    PageOrSection(
                        ref=ref,
                        title=f"Страница {index}",
                        text=text,
                        quality=quality,
                        warnings=page_warnings,
                    )
                )
                if text:
                    text_parts.append(f"[{ref}]\n{text}")
            metadata = {"page_count": pdf.page_count, "ocr_dpi": self.dpi}

        document_text = "\n\n".join(text_parts)
        quality_score = estimate_text_quality(document_text, min_chars=max(500, len(pages) * 250))
        return CanonicalDocument(
            source_file_id=source_file_id,
            filename=filename,
            source_format=SourceFormat.PDF_MIXED,
            document_text=document_text,
            pages_or_sections=pages,
            tables=[],
            metadata=metadata,
            extraction_warnings=warnings,
            quality_score=quality_score,
        )
