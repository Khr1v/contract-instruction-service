from __future__ import annotations

import base64
import hashlib
import hmac
import logging
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

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

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        rest_base_url: str | None = None,
        access_token: str | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._rest_base_url_override = rest_base_url.rstrip("/") if rest_base_url else None
        self._access_token = access_token

    @property
    def _rest_base_url(self) -> str:
        if self._rest_base_url_override:
            return self._rest_base_url_override
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
        if self._access_token and "auth" not in payload:
            payload = {**payload, "auth": self._access_token}
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
        try:
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
        except BitrixAPIError as exc:
            logger.info("Bitrix v2 message send failed, trying legacy imbot.message.add: %s", exc)
            await self.call_method(
                "imbot.message.add",
                {
                    "BOT_ID": self._bot_id,
                    "CLIENT_ID": self._bot_token,
                    "DIALOG_ID": dialog_id,
                    "MESSAGE": message[:19_500],
                    "SYSTEM": "N",
                    "URL_PREVIEW": "N",
                },
            )

    async def download_file(
        self,
        file_id: str | int,
        target_path: Path,
        file_payload: dict[str, Any] | None = None,
    ) -> Path:
        download_url = self._extract_download_url(file_payload or {})
        try:
            if not download_url:
                data = await self.call_method(
                    "imbot.v2.File.download",
                    {
                        "botId": self._bot_id,
                        "botToken": self._bot_token,
                        "fileId": int(file_id),
                    },
                )
                result = data.get("result") if isinstance(data.get("result"), dict) else {}
                download_url = result.get("downloadUrl") or result.get("DOWNLOAD_URL")
        except BitrixAPIError as exc:
            logger.info("Bitrix v2 file download failed, trying disk.file.get: %s", exc)
            data = await self.call_method("disk.file.get", {"id": int(file_id)})
            result = data.get("result") if isinstance(data.get("result"), dict) else {}
            download_url = result.get("DOWNLOAD_URL") or result.get("downloadUrl")
        if not download_url:
            raise BitrixAPIError("Bitrix file download URL is missing")

        target_path.parent.mkdir(parents=True, exist_ok=True)
        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
            response = await client.get(download_url)
            response.raise_for_status()
            target_path.write_bytes(response.content)
        return target_path

    def _extract_download_url(self, payload: dict[str, Any]) -> str | None:
        for key in ("urlDownload", "downloadUrl", "DOWNLOAD_URL", "url_download", "URL_DOWNLOAD"):
            value = payload.get(key)
            if value:
                return self._absolute_portal_url(str(value))
        links = payload.get("links") or payload.get("LINKS")
        if isinstance(links, dict):
            for key in ("download", "DOWNLOAD", "urlDownload", "downloadUrl"):
                value = links.get(key)
                if value:
                    return self._absolute_portal_url(str(value))
        return None

    async def upload_file(self, dialog_id: str, file_path: str | Path, message: str | None = None) -> dict[str, Any]:
        path = Path(file_path)
        content = base64.b64encode(path.read_bytes()).decode("ascii")
        fields = {
            "name": path.name,
            "content": content,
            "message": message or "",
        }
        try:
            return await self.call_method(
                "imbot.v2.File.upload",
                {
                    "botId": self._bot_id,
                    "botToken": self._bot_token,
                    "dialogId": dialog_id,
                    "fields": fields,
                },
            )
        except BitrixAPIError as exc:
            logger.info("Bitrix v2 bot file upload failed, trying im.v2.File.upload: %s", exc)
            try:
                return await self.call_method(
                    "im.v2.File.upload",
                    {
                        "dialogId": dialog_id,
                        "fields": fields,
                    },
                )
            except BitrixAPIError as legacy_exc:
                logger.info("Bitrix im.v2 file upload failed, trying disk upload + chat commit: %s", legacy_exc)
                return await self.upload_file_via_disk(dialog_id, path, message)

    async def upload_file_via_disk(
        self,
        dialog_id: str,
        file_path: str | Path,
        message: str | None = None,
    ) -> dict[str, Any]:
        path = Path(file_path)
        content = base64.b64encode(path.read_bytes()).decode("ascii")
        try:
            folder_id = await self._resolve_chat_file_folder_id(dialog_id)
            file_payload = await self._upload_file_to_folder(folder_id, path.name, content)
            upload_target = {"chat_folder_id": folder_id}
        except BitrixAPIError as exc:
            logger.info("Bitrix chat folder upload failed, trying user disk storage upload: %s", exc)
            storage_id = await self._resolve_disk_storage_id()
            file_payload = await self._upload_file_to_storage(storage_id, path.name, content)
            upload_target = {"storage_id": storage_id}

        file_id = self._extract_disk_file_id(file_payload)
        absolute_url = self._extract_disk_file_url(file_payload)

        try:
            commit = await self.call_method(
                "im.disk.file.commit",
                {
                    "DIALOG_ID": dialog_id,
                    "FILE_ID": [int(file_id)],
                    "MESSAGE": message or "",
                },
            )
            return {
                "result": {
                    "disk_file": file_payload,
                    "chat_commit": commit.get("result"),
                    **upload_target,
                }
            }
        except BitrixAPIError as exc:
            logger.info("Bitrix im.disk.file.commit failed, sending disk file link instead: %s", exc)
            link_text = absolute_url or f"Файл загружен в Bitrix Disk, file ID: {file_id}"
            await self.send_message(dialog_id, f"{message or 'Инструкция готова.'}\n\nDOCX: {link_text}")
            return {"result": {"disk_file": file_payload, "link_sent": link_text, **upload_target}}

    async def _resolve_chat_file_folder_id(self, dialog_id: str) -> int:
        data = await self.call_method("im.disk.folder.get", {"DIALOG_ID": dialog_id})
        result = data.get("result")
        if isinstance(result, dict):
            folder_id = result.get("ID") or result.get("id")
        else:
            folder_id = result
        if not folder_id:
            raise BitrixAPIError("Bitrix chat disk folder ID is missing")
        return int(folder_id)

    async def _upload_file_to_folder(self, folder_id: int, filename: str, content_base64: str) -> dict[str, Any]:
        upload = await self.call_method(
            "disk.folder.uploadfile",
            {
                "id": folder_id,
                "data": {
                    "NAME": filename,
                },
                "fileContent": [
                    filename,
                    content_base64,
                ],
                "generateUniqueName": True,
            },
        )
        result = upload.get("result")
        if not isinstance(result, dict):
            raise BitrixAPIError("Bitrix folder upload returned empty result")
        return result

    async def _upload_file_to_storage(self, storage_id: int, filename: str, content_base64: str) -> dict[str, Any]:
        upload = await self.call_method(
            "disk.storage.uploadfile",
            {
                "id": storage_id,
                "data": {
                    "NAME": filename,
                },
                "fileContent": [
                    filename,
                    content_base64,
                ],
                "generateUniqueName": True,
            },
        )
        result = upload.get("result")
        if not isinstance(result, dict):
            raise BitrixAPIError("Bitrix storage upload returned empty result")
        return result

    def _extract_disk_file_id(self, file_payload: dict[str, Any]) -> int:
        file_id = file_payload.get("ID") or file_payload.get("id")
        if not file_id:
            raise BitrixAPIError("Bitrix disk upload result does not contain file ID")
        return int(file_id)

    def _extract_disk_file_url(self, file_payload: dict[str, Any]) -> str | None:
        file_url = (
            file_payload.get("DETAIL_URL")
            or file_payload.get("detailUrl")
            or file_payload.get("DOWNLOAD_URL")
            or file_payload.get("downloadUrl")
        )
        return self._absolute_portal_url(str(file_url)) if file_url else None

    async def _resolve_disk_storage_id(self) -> int:
        if self.settings.bitrix_disk_storage_id is not None:
            return self.settings.bitrix_disk_storage_id
        data = await self.call_method("disk.storage.getlist", {})
        result = data.get("result")
        if not isinstance(result, list) or not result:
            raise BitrixAPIError("Bitrix disk storage list is empty")

        rest_user_id = self._rest_user_id()
        if rest_user_id:
            for storage in result:
                if not isinstance(storage, dict):
                    continue
                entity_type = str(storage.get("ENTITY_TYPE") or storage.get("entityType") or "").lower()
                entity_id = str(storage.get("ENTITY_ID") or storage.get("entityId") or "")
                if entity_type == "user" and entity_id == rest_user_id:
                    return int(storage["ID"] if "ID" in storage else storage["id"])

        for storage in result:
            if isinstance(storage, dict) and (storage.get("ID") or storage.get("id")):
                return int(storage["ID"] if "ID" in storage else storage["id"])
        raise BitrixAPIError("Could not resolve Bitrix disk storage ID")

    def _rest_user_id(self) -> str | None:
        parts = [part for part in urlsplit(self._rest_base_url).path.split("/") if part]
        if len(parts) >= 2 and parts[0] == "rest":
            return parts[1]
        return None

    def _absolute_portal_url(self, url: str) -> str:
        if url.startswith("http://") or url.startswith("https://"):
            return url
        parsed = urlsplit(self._rest_base_url)
        return f"{parsed.scheme}://{parsed.netloc}/{url.lstrip('/')}"

    async def send_instruction_result(self, dialog_id: str, result: ProcessingResult) -> None:
        summary = format_processing_result_message(result)
        if result.status != "completed":
            await self.send_message(dialog_id, summary)
            return

        if result.instruction_docx_path and Path(result.instruction_docx_path).exists():
            download_url = self._build_instruction_download_url(result)
            if download_url:
                await self.send_message(dialog_id, f"{summary}\n\nСкачать DOCX: {download_url}")
                return
            try:
                await self.upload_file(dialog_id, result.instruction_docx_path, summary)
            except BitrixAPIError as exc:
                logger.exception("Could not upload instruction DOCX to Bitrix")
                await self.send_message(
                    dialog_id,
                    f"{summary}\n\nНе удалось прикрепить DOCX в чат: {exc}\n"
                    f"Файл сохранен на сервере: {result.instruction_docx_path}",
                )
            return

        await self.send_message(dialog_id, summary)

    async def send_error(self, dialog_id: str, error: str) -> None:
        await self.send_message(dialog_id, f"Не удалось обработать договор.\n{error}")

    def _build_instruction_download_url(self, result: ProcessingResult) -> str | None:
        if not self.settings.public_base_url or not result.instruction_docx_path:
            return None
        filename = Path(result.instruction_docx_path).name
        token = self._build_download_token(result.document_id, filename)
        return (
            f"{self.settings.public_base_url.rstrip('/')}/api/bitrix/bot/download/"
            f"{quote(result.document_id)}/{quote(filename)}?token={token}"
        )

    def _build_download_token(self, document_id: str, filename: str) -> str:
        secret = (
            self.settings.bitrix_bot_token
            or self.settings.bitrix_webhook_url
            or self.settings.yandex_cloud_api_key
            or "dev-download-secret"
        ).encode("utf-8")
        payload = f"{document_id}:{filename}".encode("utf-8")
        return hmac.new(secret, payload, hashlib.sha256).hexdigest()


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
