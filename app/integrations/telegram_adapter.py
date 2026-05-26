from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import orjson
from aiogram import Bot
from aiogram.types import BufferedInputFile, FSInputFile, Message

from app.config import Settings
from app.integrations.base import IntegrationAdapter
from app.llm.schemas import ProcessingResult
from app.services.contract_pipeline import ContractPipeline
from app.utils.file_utils import is_supported_document


class TelegramTestAdapter(IntegrationAdapter):
    """Telegram adapter for MVP testing. Business workflow lives in ContractPipeline."""

    def __init__(self, pipeline: ContractPipeline, settings: Settings | None = None) -> None:
        self.pipeline = pipeline
        self.settings = settings or pipeline.settings

    async def receive_document(self, payload: tuple[Message, Bot]) -> Path:
        message, bot = payload
        if message.document is None:
            raise ValueError("Message does not contain a document")
        filename = message.document.file_name or "document"
        if not is_supported_document(filename):
            raise ValueError("Поддерживаются только PDF и DOCX.")
        file = await bot.get_file(message.document.file_id)
        suffix = Path(filename).suffix
        temp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        temp.close()
        await bot.download_file(file.file_path, destination=temp.name)
        return Path(temp.name)

    async def process_document_message(self, message: Message, bot: Bot) -> ProcessingResult:
        if message.document is None:
            raise ValueError("Message does not contain a document")
        filename = message.document.file_name or "document"
        local_path = await self.receive_document((message, bot))

        await message.answer("Файл получен")
        await message.answer("Определяю тип документа")
        await message.answer("Извлекаю текст")
        await message.answer("Анализирую условия")
        await message.answer("Генерирую инструкцию")
        await message.answer("Проверяю результат")

        result = await self.pipeline.process_contract(
            file_path=str(local_path),
            original_filename=filename,
            external_user_id=str(message.from_user.id if message.from_user else message.chat.id),
            source_channel="telegram",
            external_entity_id=str(message.chat.id),
        )
        return result

    async def send_processing_status(self, recipient_id: str, status: str) -> None:
        # The concrete Message object is used in handlers for sending status updates.
        return None

    async def send_instruction_result(self, recipient_id: str, result: ProcessingResult) -> None:
        # The handler sends result using message context.
        return None

    async def send_error(self, recipient_id: str, error: str) -> None:
        return None

    async def send_result_to_message(self, message: Message, result: ProcessingResult, bot: Bot | None = None) -> None:
        try:
            if result.status != "completed":
                await message.answer("Не удалось обработать договор.\n" + "\n".join(result.warnings[-3:]))
                return

            review_note = "\n\nИнструкция требует проверки человеком." if result.human_review_required else ""
            if result.instruction_docx_path:
                await message.answer_document(
                    FSInputFile(result.instruction_docx_path),
                    caption="Инструкция сформирована в DOCX." + review_note,
                )
                return

            instruction = result.instruction_markdown or ""
            if len(instruction) <= 3500:
                await message.answer(instruction + review_note)
                return

            payload = instruction.encode("utf-8")
            await message.answer_document(
                BufferedInputFile(payload, filename=f"instruction_{result.document_id}.md"),
                caption="Инструкция сформирована." + review_note,
            )
        finally:
            await self.send_admin_run_report(result, bot)

    async def send_admin_run_report(self, result: ProcessingResult, bot: Bot | None) -> None:
        if bot is None or not self.settings.admin_id_list:
            return

        report = self._load_run_report(result.run_report_path)
        text = self._format_admin_report(result, report)
        for admin_id in self.settings.admin_id_list:
            try:
                await bot.send_message(admin_id, text[:3900])
            except Exception:
                # Do not fail user delivery because of an admin notification problem.
                continue

    def _load_run_report(self, path: str | None) -> dict[str, Any]:
        if not path:
            return {}
        report_path = Path(path)
        if not report_path.exists():
            return {}
        try:
            payload = orjson.loads(report_path.read_bytes())
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _format_admin_report(self, result: ProcessingResult, report: dict[str, Any]) -> str:
        extra = report.get("extra") if isinstance(report.get("extra"), dict) else {}
        llm_usage = extra.get("llm_usage") if isinstance(extra.get("llm_usage"), dict) else {}
        totals = llm_usage.get("totals") if isinstance(llm_usage.get("totals"), dict) else {}
        by_model = llm_usage.get("by_model") if isinstance(llm_usage.get("by_model"), dict) else {}
        requests = llm_usage.get("requests") if isinstance(llm_usage.get("requests"), list) else []
        stages = report.get("stages") if isinstance(report.get("stages"), list) else []
        slowest_stages = sorted(
            [stage for stage in stages if isinstance(stage, dict)],
            key=lambda stage: float(stage.get("duration_seconds") or 0),
            reverse=True,
        )[:3]
        warnings = report.get("warnings") if isinstance(report.get("warnings"), list) else result.warnings
        risk_flags = report.get("risk_flags") if isinstance(report.get("risk_flags"), list) else result.risk_flags
        artifacts = report.get("artifacts") if isinstance(report.get("artifacts"), dict) else {}

        lines = [
            "Отчет обработки договора",
            f"Файл: {report.get('filename') or 'unknown'}",
            f"Document ID: {result.document_id}",
            f"Статус: {result.status}",
            f"Время: {result.duration_seconds or report.get('duration_seconds') or 'n/a'} сек",
            f"Тип: {result.source_format or report.get('source_format') or 'n/a'}",
            f"Страниц/секций: {result.page_count or report.get('page_count') or 'n/a'}",
            f"Quality score: {result.quality_score or report.get('quality_score') or 'n/a'}",
            f"Human review: {'yes' if result.human_review_required else 'no'}",
            f"LLM calls: {result.llm_requests if result.llm_requests is not None else len(requests)}",
            f"Tokens total: {result.llm_total_tokens or totals.get('total_tokens') or 0}",
            f"Estimated cost: {result.estimated_cost_rub or totals.get('estimated_cost_rub') or 0} ₽",
            f"Estimated cost USD: ${result.estimated_cost_usd or totals.get('estimated_cost_usd') or 0}",
            f"Warnings: {len(warnings)}",
            f"Risk flags: {len(risk_flags)}",
            f"DOCX: {result.instruction_docx_path or artifacts.get('instruction_docx') or 'not generated'}",
            f"Run report: {result.run_report_path or 'not generated'}",
        ]
        if slowest_stages:
            lines.append("")
            lines.append("Самые долгие этапы:")
            lines.extend(
                f"- {stage.get('name')}: {stage.get('duration_seconds')} сек"
                for stage in slowest_stages
            )
        if by_model:
            lines.append("")
            lines.append("Стоимость по моделям:")
            for model, model_totals in by_model.items():
                if not isinstance(model_totals, dict):
                    continue
                lines.append(
                    f"- {model}: {model_totals.get('estimated_cost_rub', 0)} ₽, "
                    f"{model_totals.get('total_tokens', 0)} tokens, "
                    f"{model_totals.get('requests', 0)} calls"
                )
        if warnings:
            lines.append("")
            lines.append("Warnings:")
            lines.extend(f"- {warning}" for warning in warnings[:5])
        return "\n".join(lines)
