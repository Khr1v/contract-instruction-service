from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from fastapi import APIRouter, BackgroundTasks, Request

from app.config import get_settings
from app.integrations.bitrix_chat_adapter import BitrixAPIError, BitrixChatAdapter
from app.services.contract_pipeline import ContractPipeline
from app.services.file_storage import FileStorage
from app.utils.file_utils import is_supported_document

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/bitrix/bot", tags=["bitrix-bot"])
_pipeline: ContractPipeline | None = None
_processed_message_ids: set[str] = set()


@router.get("/health")
async def bitrix_bot_health() -> dict[str, str]:
    return {"status": "ok", "adapter": "bitrix_chat_bot"}


@router.post("/events")
async def receive_bitrix_bot_event(request: Request, background_tasks: BackgroundTasks) -> dict[str, str]:
    payload = await _read_event_payload(request)
    message_id = _extract_message_id(payload)
    if message_id and message_id in _processed_message_ids:
        return {"status": "duplicate_ignored"}
    if message_id:
        _processed_message_ids.add(message_id)
    background_tasks.add_task(process_bitrix_bot_event, payload)
    return {"status": "accepted"}


async def process_bitrix_bot_event(payload: dict[str, Any]) -> None:
    adapter = _build_bitrix_adapter(payload)
    event = _get_str(payload, "event") or _get_str(payload, "EVENT_NAME")
    data = _get_dict(payload, "data")
    if not data:
        data = payload
    supported_events = {
        "ONIMBOTV2MESSAGEADD",
        "ONIMBOTV2JOINCHAT",
        "ONIMBOTV2COMMANDADD",
        "ONIMBOTMESSAGEADD",
        "ONIMBOTJOINCHAT",
        "ONIMBOTCOMMANDADD",
    }
    if event and event not in supported_events:
        logger.debug("Ignored Bitrix bot event=%s", event)
        return

    message = _get_dict(data, "message") or _get_dict(data, "params")
    chat = _get_dict(data, "chat")
    user = _get_dict(data, "user")
    dialog_id = _extract_dialog_id(message, chat)
    if not dialog_id:
        logger.warning(
            "Bitrix bot event has no dialog_id event=%s payload_keys=%s data_keys=%s",
            event,
            sorted(payload.keys()),
            sorted(data.keys()),
        )
        return

    text = (_get_str(message, "text") or _get_str(message, "message") or "").strip()
    logger.info(
        "Bitrix bot event received event=%s dialog_id=%s text_present=%s",
        event,
        dialog_id,
        bool(text),
    )
    if event in {"ONIMBOTV2JOINCHAT", "ONIMBOTJOINCHAT"} or text.lower() in {"/start", "/help", "help"}:
        await adapter.send_message(
            dialog_id,
            "Отправьте PDF или DOCX договор в этот чат. Я обработаю файл через ContractPipeline "
            "и верну готовую инструкцию DOCX. Если данных не хватит, инструкция будет помечена "
            "как требующая проверки человеком.",
        )
        return

    files = _extract_files(message)
    logger.info("Bitrix bot files detected event=%s dialog_id=%s file_count=%s", event, dialog_id, len(files))
    supported_file = next((file for file in files if is_supported_document(_extract_filename(file))), None)
    if supported_file is None:
        if files:
            names = ", ".join(_extract_filename(file) for file in files[:3])
            await adapter.send_message(
                dialog_id,
                "Формат файла не поддерживается. Пришлите договор в PDF или DOCX.\n"
                f"Получено: {names}\n"
                "Если это старый Word .doc, откройте его в Word/LibreOffice и сохраните как .docx или PDF.",
            )
            return
        if not text:
            return
        await adapter.send_message(dialog_id, "Пришлите договор файлом в формате PDF или DOCX.")
        return

    file_id = _extract_file_id(supported_file)
    filename = _extract_filename(supported_file)
    if not file_id:
        await adapter.send_error(dialog_id, "Не удалось получить fileId из события Bitrix.")
        return

    external_user_id = (
        _get_str(user, "id")
        or _get_str(message, "authorId")
        or _get_str(message, "fromUserId")
        or "bitrix-user"
    )
    await adapter.send_processing_status(dialog_id, f"Файл получен: {filename}\nСкачиваю из Bitrix24.")

    with tempfile.TemporaryDirectory(prefix="bitrix_contract_") as tmp_dir:
        local_path = Path(tmp_dir) / FileStorage.safe_filename(filename)
        try:
            await adapter.download_file(file_id, local_path, supported_file)
            local_path, filename = _ensure_supported_download_name(local_path, filename)
            await adapter.send_processing_status(dialog_id, "Файл скачан. Запускаю обработку договора.")
            result = await _get_pipeline().process_contract(
                file_path=str(local_path),
                original_filename=filename,
                external_user_id=str(external_user_id),
                source_channel="bitrix_chat",
                external_entity_id=dialog_id,
            )
            if result.human_review_required:
                await adapter.send_message(dialog_id, "Инструкция требует проверки человеком.")
            await adapter.send_instruction_result(dialog_id, result)
        except Exception as exc:
            logger.exception("Bitrix chat document processing failed dialog_id=%s file_id=%s", dialog_id, file_id)
            try:
                await adapter.send_error(dialog_id, str(exc))
            except BitrixAPIError:
                logger.exception("Could not send Bitrix error message")


def _get_pipeline() -> ContractPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = ContractPipeline()
    return _pipeline


def _build_bitrix_adapter(payload: dict[str, Any]) -> BitrixChatAdapter:
    auth = _extract_event_auth(payload)
    if auth:
        access_token = _get_str(auth, "access_token")
        client_endpoint = _get_str(auth, "client_endpoint")
        if access_token and client_endpoint:
            return BitrixChatAdapter(
                get_settings(),
                rest_base_url=client_endpoint,
                access_token=access_token,
            )
    return BitrixChatAdapter()


def _extract_event_auth(payload: dict[str, Any]) -> dict[str, Any]:
    data = _get_dict(payload, "data")
    bot = _get_dict(data, "bot")
    settings = get_settings()
    bot_auth_candidates: list[dict[str, Any]] = []
    if bot:
        if settings.bitrix_bot_id is not None:
            bot_auth_candidates.append(_get_dict(bot, str(settings.bitrix_bot_id)))
        bot_auth_candidates.extend(value for value in bot.values() if isinstance(value, dict))

    for candidate in bot_auth_candidates:
        auth = _get_dict(candidate, "auth")
        if auth:
            return auth
        if _get_str(candidate, "access_token") and _get_str(candidate, "client_endpoint"):
            return candidate

    auth = _get_dict(payload, "auth") or _get_dict(data, "auth")
    return auth


async def _read_event_payload(request: Request) -> dict[str, Any]:
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        payload = await request.json()
        return payload if isinstance(payload, dict) else {"payload": payload}

    body = await request.body()
    parsed = parse_qs(body.decode("utf-8", errors="replace"), keep_blank_values=True)
    result: dict[str, Any] = {}
    for raw_key, values in parsed.items():
        value: Any = values[-1] if values else ""
        _insert_nested_form_value(result, raw_key, value)
    for raw_key, value in request.query_params.multi_items():
        if raw_key not in result:
            _insert_nested_form_value(result, raw_key, value)
    return result


def _insert_nested_form_value(target: dict[str, Any], raw_key: str, value: Any) -> None:
    parts = _split_form_key(raw_key)
    cursor: dict[str, Any] = target
    for part in parts[:-1]:
        next_value = cursor.get(part)
        if not isinstance(next_value, dict):
            next_value = {}
            cursor[part] = next_value
        cursor = next_value
    cursor[parts[-1]] = value


def _split_form_key(key: str) -> list[str]:
    parts: list[str] = []
    buffer = ""
    index = 0
    while index < len(key):
        char = key[index]
        if char == "[":
            if buffer:
                parts.append(buffer)
                buffer = ""
            index += 1
            inner = ""
            while index < len(key) and key[index] != "]":
                inner += key[index]
                index += 1
            if inner:
                parts.append(inner)
        else:
            buffer += char
        index += 1
    if buffer:
        parts.append(buffer)
    return parts or [key]


def _extract_message_id(payload: dict[str, Any]) -> str | None:
    data = _get_dict(payload, "data") or payload
    message = _get_dict(data, "message") or _get_dict(data, "params")
    message_id = (
        _get_str(message, "id")
        or _get_str(message, "uuid")
        or _get_str(message, "messageId")
        or _get_str(data, "eventId")
    )
    event_name = _get_str(payload, "event") or ""
    if message_id:
        return f"{event_name}:{message_id}"
    return None


def _extract_dialog_id(message: dict[str, Any], chat: dict[str, Any]) -> str | None:
    dialog_id = _get_str(chat, "dialogId") or _get_str(message, "dialogId")
    if dialog_id:
        return dialog_id
    chat_id = _get_str(chat, "id") or _get_str(message, "chatId") or _get_str(message, "toChatId")
    if chat_id:
        return f"chat{chat_id}"
    return None


def _extract_files(message: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[Any] = []
    params = _get_dict(message, "params")
    candidates.extend(
        [
            message.get("file"),
            message.get("files"),
            message.get("FILE"),
            message.get("FILES"),
            params.get("file"),
            params.get("files"),
            params.get("FILE"),
            params.get("FILES"),
            params.get("fileId"),
            params.get("FILE_ID"),
            params.get("diskFileId"),
            message.get("FILE_ID"),
            message.get("DISK_FILE_ID"),
        ]
    )
    files: list[dict[str, Any]] = []
    for candidate in candidates:
        files.extend(_normalize_files(candidate))
    return files


def _normalize_files(value: Any) -> list[dict[str, Any]]:
    if value is None or value == "":
        return []
    if isinstance(value, dict):
        if _looks_like_file(value):
            return [value]
        files: list[dict[str, Any]] = []
        for item in value.values():
            files.extend(_normalize_files(item))
        return files
    if isinstance(value, list):
        files = []
        for item in value:
            files.extend(_normalize_files(item))
        return files
    if isinstance(value, str) and value.isdigit():
        return [{"id": value, "name": f"bitrix_file_{value}"}]
    return []


def _looks_like_file(value: dict[str, Any]) -> bool:
    keys = {key.lower() for key in value.keys()}
    return bool({"id", "fileid", "name", "filename", "extension"} & keys)


def _extract_file_id(file_payload: dict[str, Any]) -> str | None:
    return (
        _get_str(file_payload, "id")
        or _get_str(file_payload, "fileId")
        or _get_str(file_payload, "FILE_ID")
        or _get_str(file_payload, "diskFileId")
    )


def _extract_filename(file_payload: dict[str, Any]) -> str:
    name = (
        _get_str(file_payload, "name")
        or _get_str(file_payload, "filename")
        or _get_str(file_payload, "fileName")
        or _get_str(file_payload, "NAME")
    )
    if name:
        return name
    file_id = _extract_file_id(file_payload) or "unknown"
    extension = (_get_str(file_payload, "extension") or "pdf").lower().lstrip(".")
    return f"bitrix_file_{file_id}.{extension}"


def _ensure_supported_download_name(local_path: Path, filename: str) -> tuple[Path, str]:
    if is_supported_document(filename):
        return local_path, filename
    signature = local_path.read_bytes()[:8]
    suffix: str | None = None
    if signature.startswith(b"%PDF"):
        suffix = ".pdf"
    elif signature.startswith(b"PK\x03\x04"):
        suffix = ".docx"
    if suffix is None:
        raise ValueError("Поддерживаются только PDF и DOCX.")
    new_filename = f"{local_path.stem}{suffix}"
    new_path = local_path.with_name(new_filename)
    local_path.rename(new_path)
    return new_path, new_filename


def _get_dict(payload: dict[str, Any], key: str) -> dict[str, Any]:
    for variant in _key_variants(key):
        value = payload.get(variant)
        if isinstance(value, dict):
            return value
    return {}


def _get_str(payload: dict[str, Any], key: str) -> str | None:
    for variant in _key_variants(key):
        value = payload.get(variant)
        if value is not None:
            text = str(value).strip()
            return text or None
    return None


def _key_variants(key: str) -> list[str]:
    variants = [key, key.upper()]
    snake = ""
    for index, char in enumerate(key):
        if char.isupper() and index > 0:
            snake += "_"
        snake += char.upper()
    if snake not in variants:
        variants.append(snake)
    lower = key.lower()
    if lower not in variants:
        variants.append(lower)
    return variants
