from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Any

import httpx

from app.config import Settings, get_settings
from app.llm.schemas import ProcessingResult

logger = logging.getLogger(__name__)


class BitrixAPIError(RuntimeError):
    """Bitrix REST call failed without exposing webhook secrets."""


class BitrixChatAdapter:
    """Bitrix24 chat-bot adapter.

    Business logic stays in ContractPipeline. This class only talks to Bitrix REST:
    sends status messages, downloads incoming files, and uploads generated DOCX.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    @property
    def _rest_base_url(self) -> str:
        if not self.settings.bitrix_webhook_url:
            raise BitrixAPIError("BITRIX_WEBHOOK_URL is not configured")
        return self.settings.bitrix_webhook_url.rstrip("/")

    @property
    def _bot_id(self) -> int:
        if self.settings.bitrix_bot_id is None:
            raise BitrixAPIError("BITRIX_BOT_ID is not configured")
        return self.settings.bitrix_bot_id

    @property
    def _bot_token(self) -> str:
        if not self.settings.bitrix_bot_token:
            raise BitrixAPIError("BITRIX_BOT_TOKEN is not configured")
        return self.settings.bitrix_bot_token

    async def call_method(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._rest_base_url}/{method}"
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(url, json=payload)
        try:
            data = response.json()
        except ValueError as exc:
            raise BitrixAPIError(f"Bitrix method {method} returned non-JSON response") from exc
        if response.status_code >= 400 or data.get("error"):
            error = data.get("error") or response.status_code
            description = data.get("error_description") or data.get("error_description_raw") or response.text[:300]
            raise BitrixAPIError(f"Bitrix method {method} failed: {error}: {description}")
        return data

    async def register_bot(self, event_url: str) -> dict[str, Any]:
        payload = {
            "fields": {
                "code": self.settings.bitrix_bot_code,
                "botToken": self._bot_token,
                "properties": {
                    "name": self.settings.bitrix_bot_name,
                    "workPosition": "Генератор инструкций по договорам",
                },
                "type": self.settings.bitrix_bot_type,
                "eventMode": "webhook",
                "webhookUrl": event_url,
                "isHidden": False,
                "isReactionsEnabled": True,
            }
        }
        return await self.call_method("imbot.v2.Bot.register", payload)

    async def send_processing_status(self, dialog_id: str, status: str) -> None:
        await self.send_message(dialog_id, status)

    async def send_message(self, dialog_id: str, message: str) -> None:
        await self.call_method(
            "imbot.v2.Chat.Message.send",
            {
                "botId": self._bot_id,
                "botToken": self._bot_token,
                "dialogId": dialog_id,
                "fields": {
                    "message": message[:19_500],
                    "urlPreview": False,
                },
            },
        )

    async def download_file(self, file_id: str | int, target_path: Path) -> Path:
        data = await self.call_method(
            "imbot.v2.File.download",
            {
                "botId": self._bot_id,
                "botToken": self._bot_token,
                "fileId": int(file_id),
            },
        )
        result = data.get("result") if isinstance(data.get("result"), dict) else {}
        download_url = result.get("downloadUrl")
        if not download_url:
            raise BitrixAPIError("Bitrix file download URL is missing")

        target_path.parent.mkdir(parents=True, exist_ok=True)
        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
            response = await client.get(download_url)
            response.raise_for_status()
            target_path.write_bytes(response.content)
        return target_path

    async def upload_file(self, dialog_id: str, file_path: str | Path, message: str | None = None) -> dict[str, Any]:
        path = Path(file_path)
        content = base64.b64encode(path.read_bytes()).decode("ascii")
        return await self.call_method(
            "imbot.v2.File.upload",
            {
                "botId": self._bot_id,
                "botToken": self._bot_token,
                "dialogId": dialog_id,
                "fields": {
                    "name": path.name,
                    "content": content,
                    "message": message or "",
                },
            },
        )

    async def send_instruction_result(self, dialog_id: str, result: ProcessingResult) -> None:
        summary = format_processing_result_message(result)
        if result.status != "completed":
            await self.send_message(dialog_id, summary)
            return

        if result.instruction_docx_path and Path(result.instruction_docx_path).exists():
            await self.upload_file(dialog_id, result.instruction_docx_path, summary)
            return

        await self.send_message(dialog_id, summary)

    async def send_error(self, dialog_id: str, error: str) -> None:
        await self.send_message(dialog_id, f"Не удалось обработать договор.\n{error}")


def format_processing_result_message(result: ProcessingResult) -> str:
    lines = [
        "Отчет обработки договора",
        f"Document ID: {result.document_id}",
        f"Статус: {result.status}",
        f"Время: {_format_float(result.duration_seconds)} сек",
        f"Тип: {result.source_format or 'unknown'}",
        f"Страниц/секций: {result.page_count if result.page_count is not None else 'unknown'}",
        f"Quality score: {_format_float(result.quality_score)}",
        f"Human review: {'yes' if result.human_review_required else 'no'}",
        f"LLM calls: {result.llm_requests if result.llm_requests is not None else 'unknown'}",
        f"Tokens total: {result.llm_total_tokens if result.llm_total_tokens is not None else 'unknown'}",
        f"Estimated cost: {_format_float(result.estimated_cost_rub)} ₽",
    ]
    if result.instruction_docx_path:
        lines.append(f"DOCX: {Path(result.instruction_docx_path).name}")
    if result.run_report_path:
        lines.append(f"Run report: {result.run_report_path}")
    if result.warnings:
        lines.append("")
        lines.append("Warnings:")
        lines.extend(f"- {warning}" for warning in result.warnings[:5])
    if result.risk_flags:
        lines.append("")
        lines.append("Risk flags:")
        lines.extend(f"- {risk}" for risk in result.risk_flags[:5])
    return "\n".join(lines)


def _format_float(value: float | int | None) -> str:
    if value is None:
        return "unknown"
    return f"{float(value):.3f}".rstrip("0").rstrip(".")
