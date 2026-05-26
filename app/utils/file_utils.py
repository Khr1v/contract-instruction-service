from __future__ import annotations

from pathlib import Path


SUPPORTED_EXTENSIONS = {".pdf", ".docx"}


def is_supported_document(filename: str | Path) -> bool:
    return Path(filename).suffix.lower() in SUPPORTED_EXTENSIONS

