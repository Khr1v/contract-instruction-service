from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from app.llm.schemas import CanonicalDocument


class DocumentExtractor(ABC):
    @abstractmethod
    def extract(self, file_path: str | Path, source_file_id: str, filename: str) -> CanonicalDocument:
        """Extract a document into CanonicalDocument."""

