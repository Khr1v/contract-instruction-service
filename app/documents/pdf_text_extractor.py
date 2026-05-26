from __future__ import annotations

from pathlib import Path

import fitz

from app.documents.base import DocumentExtractor
from app.documents.quality import estimate_text_quality
from app.llm.schemas import CanonicalDocument, PageOrSection, SourceFormat


class PDFTextExtractor(DocumentExtractor):
    def __init__(self, source_format: SourceFormat = SourceFormat.PDF_TEXT) -> None:
        self.source_format = source_format

    def extract(self, file_path: str | Path, source_file_id: str, filename: str) -> CanonicalDocument:
        path = Path(file_path)
        warnings: list[str] = []
        pages: list[PageOrSection] = []
        text_parts: list[str] = []

        with fitz.open(path) as pdf:
            for index, page in enumerate(pdf, start=1):
                ref = f"page_{index}"
                text = page.get_text("text").strip()
                quality = estimate_text_quality(text, min_chars=350)
                page_warnings: list[str] = []
                if len(text) < 100:
                    page_warnings.append("На странице мало извлекаемого текста; возможен скан.")
                pages.append(
                    PageOrSection(
                        ref=ref,
                        title=f"Страница {index}",
                        text=text,
                        quality=quality,
                        warnings=page_warnings,
                    )
                )
                if page_warnings:
                    warnings.extend(f"{ref}: {warning}" for warning in page_warnings)
                if text:
                    text_parts.append(f"[{ref}]\n{text}")

            metadata = {"page_count": pdf.page_count}

        total_text = "\n\n".join(text_parts)
        quality_score = estimate_text_quality(total_text, min_chars=max(500, len(pages) * 250))
        if not total_text.strip():
            warnings.append("PDF не содержит извлекаемого текста.")
        elif quality_score < 0.5:
            warnings.append("Качество извлечения PDF-текста низкое; проверьте OCR/VLM.")

        return CanonicalDocument(
            source_file_id=source_file_id,
            filename=filename,
            source_format=self.source_format,
            document_text=total_text,
            pages_or_sections=pages,
            tables=[],
            metadata=metadata,
            extraction_warnings=warnings,
            quality_score=quality_score,
        )

