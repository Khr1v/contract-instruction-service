from __future__ import annotations

from pathlib import Path
from typing import Any

from app.integrations.base import IntegrationAdapter
from app.llm.schemas import ProcessingResult


class BitrixFutureAdapter(IntegrationAdapter):
    """Production Bitrix24 adapter scaffold.

    Planned flow:
    - receive a deal webhook;
    - download the contract file from Bitrix24;
    - run ContractPipeline;
    - attach instruction.md to the deal;
    - write a deal comment with warnings/human review flag;
    - update processing status in a custom field.
    """

    async def receive_document(self, payload: Any) -> Path:
        return await self.receive_document_from_deal(payload)

    async def receive_document_from_deal(self, payload: dict[str, Any]) -> Path:
        raise NotImplementedError("TODO: parse Bitrix deal payload and choose contract file")

    async def download_file(self, file_url: str, target_path: Path) -> Path:
        raise NotImplementedError("TODO: download authorized Bitrix file")

    async def send_comment_to_deal(self, deal_id: str, comment: str) -> None:
        raise NotImplementedError("TODO: call Bitrix CRM timeline/comment API")

    async def attach_instruction_to_deal(self, deal_id: str, instruction_path: Path) -> None:
        raise NotImplementedError("TODO: upload instruction.md and attach it to Bitrix deal")

    async def update_processing_status(self, deal_id: str, status: str) -> None:
        raise NotImplementedError("TODO: update Bitrix custom processing status field")

    async def send_processing_status(self, recipient_id: str, status: str) -> None:
        await self.update_processing_status(recipient_id, status)

    async def send_instruction_result(self, recipient_id: str, result: ProcessingResult) -> None:
        if result.instruction_path:
            await self.attach_instruction_to_deal(recipient_id, Path(result.instruction_path))
        comment = "Инструкция по договору сформирована."
        if result.human_review_required:
            comment += "\nТребуется проверка человеком."
        if result.warnings:
            comment += "\nПредупреждения:\n" + "\n".join(result.warnings)
        await self.send_comment_to_deal(recipient_id, comment)

    async def send_error(self, recipient_id: str, error: str) -> None:
        await self.send_comment_to_deal(recipient_id, f"Ошибка обработки договора: {error}")
        await self.update_processing_status(recipient_id, "failed")

