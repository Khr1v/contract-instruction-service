from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from app.llm.schemas import ProcessingResult


class IntegrationAdapter(ABC):
    @abstractmethod
    async def receive_document(self, payload: Any) -> Path:
        """Receive or download a document and return a local path."""

    @abstractmethod
    async def send_processing_status(self, recipient_id: str, status: str) -> None:
        """Send processing status to the external channel."""

    @abstractmethod
    async def send_instruction_result(self, recipient_id: str, result: ProcessingResult) -> None:
        """Return instruction result to the external channel."""

    @abstractmethod
    async def send_error(self, recipient_id: str, error: str) -> None:
        """Return error to the external channel."""

