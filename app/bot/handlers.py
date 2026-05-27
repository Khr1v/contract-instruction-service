from __future__ import annotations

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import Message

from app.config import get_settings
from app.integrations.telegram_adapter import TelegramTestAdapter
from app.rag.index_templates import TemplateRAGIndexer
from app.services.contract_pipeline import ContractPipeline
from app.utils.file_utils import is_supported_document

router = Router()
pipeline = ContractPipeline()
telegram_adapter = TelegramTestAdapter(pipeline)


@router.message(Command("start"))
async def start(message: Message) -> None:
    await message.answer(
        "Тестовый Telegram-интерфейс для обработки договоров. "
        "Отправьте PDF, DOCX или DOC договор. Бизнес-логика находится в backend pipeline, не в боте."
    )


@router.message(Command("help"))
async def help_command(message: Message) -> None:
    await message.answer(
        "Команды:\n"
        "/start — описание тестового интерфейса\n"
        "/status — статус сервиса\n"
        "/reindex_templates — переиндексировать RAG, только ADMIN_IDS\n\n"
        "Поддерживаются файлы .pdf, .docx и .doc."
    )


@router.message(Command("status"))
async def status(message: Message) -> None:
    await message.answer("Сервис запущен. Telegram используется только как тестовый adapter.")


@router.message(Command("reindex_templates"))
async def reindex_templates(message: Message) -> None:
    settings = get_settings()
    user_id = message.from_user.id if message.from_user else None
    if user_id not in settings.admin_id_list:
        await message.answer("Недостаточно прав.")
        return
    try:
        count = TemplateRAGIndexer(settings).reindex()
        await message.answer(f"RAG переиндексирован. Chunks: {count}")
    except Exception as exc:
        await message.answer(f"Ошибка переиндексации: {exc}")


@router.message()
async def handle_document(message: Message, bot: Bot) -> None:
    if message.document is None:
        await message.answer("Отправьте PDF, DOCX или DOC договор файлом.")
        return
    filename = message.document.file_name or "document"
    if not is_supported_document(filename):
        await message.answer("Поддерживаются только PDF и DOCX.")
        return

    try:
        result = await telegram_adapter.process_document_message(message, bot)
        await telegram_adapter.send_result_to_message(message, result, bot)
    except Exception as exc:
        await message.answer(f"Ошибка обработки: {exc}")
