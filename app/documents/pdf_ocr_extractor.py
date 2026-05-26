from __future__ import annotations

from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextvars import copy_context
from pathlib import Path
from typing import Protocol

import fitz

from app.documents.base import DocumentExtractor
from app.llm.prompts import OCR_PAGE_PROMPT
from app.llm.schemas import CanonicalDocument, PageOrSection, SourceFormat


class OCRProvider(ABC):
    @abstractmethod
    def extract_page_text(self, image_bytes: bytes, page_ref: str, prompt: str) -> tuple[str, list[str]]:
        """Return OCR text and warnings for one rendered page image."""


class StubOCRProvider(OCRProvider):
    def extract_page_text(self, image_bytes: bytes, page_ref: str, prompt: str) -> tuple[str, list[str]]:
        return (
            "",
            [
                (
                    f"{page_ref}: OCR/VLM provider is not configured. "
                    "Подключите image input Yandex/OpenAI-compatible provider или fallback pytesseract/easyocr."
                )
            ],
        )


class ImageTextGenerator(Protocol):
    def generate_text_from_image(
        self,
        *,
        instructions: str,
        prompt: str,
        image_bytes: bytes,
        mime_type: str = "image/png",
        temperature: float | None = None,
        max_output_tokens: int | None = None,
    ) -> str:
        ...


class YandexVLMOCRProvider(OCRProvider):
    def __init__(self, llm_client: ImageTextGenerator) -> None:
        self.llm_client = llm_client

    def extract_page_text(self, image_bytes: bytes, page_ref: str, prompt: str) -> tuple[str, list[str]]:
        text = self.llm_client.generate_text_from_image(
            instructions=prompt,
            prompt=f"Распознай текст страницы {page_ref}. Верни только текст страницы без комментариев.",
            image_bytes=image_bytes,
            mime_type="image/png",
            temperature=0.1,
            max_output_tokens=5000,
        )
        warnings: list[str] = []
        if not text.strip():
            warnings.append(f"{page_ref}: Yandex VLM OCR returned empty text.")
        return text, warnings


class PDFOCRExtractor(DocumentExtractor):
    def __init__(
        self,
        ocr_provider: OCRProvider | None = None,
        dpi: int = 180,
        max_pages: int = 40,
        concurrency: int = 1,
    ) -> None:
        self.ocr_provider = ocr_provider or StubOCRProvider()
        self.dpi = dpi
        self.max_pages = max_pages
        self.concurrency = max(1, concurrency)

    def extract(self, file_path: str | Path, source_file_id: str, filename: str) -> CanonicalDocument:
        path = Path(file_path)
        warnings: list[str] = []
        pages: list[PageOrSection] = []
        text_parts: list[str] = []
        zoom = self.dpi / 72
        matrix = fitz.Matrix(zoom, zoom)

        rendered_pages: list[tuple[int, str, bytes]] = []
        metadata: dict[str, int] = {}
        with fitz.open(path) as pdf:
            for index, page in enumerate(pdf, start=1):
                if index > self.max_pages:
                    warnings.append(f"PDF содержит больше {self.max_pages} страниц; оставшиеся страницы не распознаны.")
                    break
                ref = f"page_{index}"
                pixmap = page.get_pixmap(matrix=matrix, alpha=False)
                rendered_pages.append((index, ref, pixmap.tobytes("png")))
            metadata = {"page_count": pdf.page_count, "ocr_dpi": self.dpi}

        ocr_results: dict[int, tuple[str, list[str]]] = {}
        with ThreadPoolExecutor(max_workers=self.concurrency) as executor:
            futures = {}
            for index, ref, image_bytes in rendered_pages:
                context = copy_context()
                future = executor.submit(
                    context.run,
                    self.ocr_provider.extract_page_text,
                    image_bytes,
                    ref,
                    OCR_PAGE_PROMPT,
                )
                futures[future] = index
            for future in as_completed(futures):
                index = futures[future]
                try:
                    ocr_results[index] = future.result()
                except Exception as exc:
                    ocr_results[index] = ("", [f"page_{index}: OCR/VLM failed: {exc}"])

        for index, ref, _image_bytes in rendered_pages:
            text, page_warnings = ocr_results.get(index, ("", [f"{ref}: OCR/VLM did not return a result."]))
            warnings.extend(page_warnings)
            quality = 0.2 if not text.strip() else 0.7
            pages.append(
                PageOrSection(
                    ref=ref,
                    title=f"Страница {index}",
                    text=text,
                    quality=quality,
                    warnings=page_warnings,
                )
            )
            if text.strip():
                text_parts.append(f"[{ref}]\n{text.strip()}")

        return CanonicalDocument(
            source_file_id=source_file_id,
            filename=filename,
            source_format=SourceFormat.PDF_SCAN,
            document_text="\n\n".join(text_parts),
            pages_or_sections=pages,
            tables=[],
            metadata=metadata,
            extraction_warnings=warnings,
            quality_score=0.2 if not text_parts else 0.7,
        )
