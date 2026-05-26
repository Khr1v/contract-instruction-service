from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path

from app.config import Settings, get_settings
from app.db.database import Database
from app.db.repository import DocumentRepository
from app.documents.pdf_mixed_extractor import PDFMixedExtractor
from app.documents.pdf_ocr_extractor import PDFOCRExtractor, StubOCRProvider, YandexVLMOCRProvider
from app.documents.router import DocumentRouter
from app.llm.chains import (
    ContractFactExtractor,
    InstructionGenerator,
    InstructionLLMValidator,
    RendererDataExtractor,
    TextGenerator,
)
from app.llm.schemas import CanonicalDocument, ContractFacts, ContractFactValue, ProcessingResult, SourceFormat
from app.llm.yandex_client import YandexLLMClient
from app.rag.retriever import TemplateRAGAgent
from app.services.instruction_docx_renderer import InstructionDocxRenderer
from app.services.file_storage import FileStorage
from app.services.instruction_service import InstructionService
from app.services.renderer_data_sanitizer import RendererDataSanitizer
from app.services.run_tracker import RunTracker
from app.services.validation_service import ValidationService

logger = logging.getLogger(__name__)


class ContractPipeline:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        database: Database | None = None,
        repository: DocumentRepository | None = None,
        storage: FileStorage | None = None,
        router: DocumentRouter | None = None,
        rag_agent: TemplateRAGAgent | None = None,
        llm_client: TextGenerator | None = None,
        fact_extractor: ContractFactExtractor | None = None,
        instruction_service: InstructionService | None = None,
        validation_service: ValidationService | None = None,
        docx_renderer: InstructionDocxRenderer | None = None,
        renderer_data_sanitizer: RendererDataSanitizer | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.database = database or Database(self.settings)
        self.database.init_db()
        self.repository = repository or DocumentRepository(self.database)
        self.storage = storage or FileStorage(self.settings)
        self.rag_agent = rag_agent or TemplateRAGAgent(self.settings)
        self.llm_client = llm_client or YandexLLMClient(self.settings)
        self.router = router or self._build_document_router()
        facts_fallback_model = None
        if self.settings.yandex_generation_model_mode.strip().lower() != "primary":
            facts_fallback_model = self.settings.yandex_generation_model or None
        self.fact_extractor = fact_extractor or ContractFactExtractor(
            self.llm_client,
            fallback_model_name=facts_fallback_model,
        )
        self.renderer_data_extractor = RendererDataExtractor(self.llm_client)
        llm_validator = InstructionLLMValidator(self.llm_client) if self.settings.enable_llm_instruction_validation else None
        self.instruction_service = instruction_service or InstructionService(
            generator=InstructionGenerator(self.llm_client),
            llm_validator=llm_validator,
        )
        self.validation_service = validation_service or ValidationService()
        self.docx_renderer = docx_renderer or InstructionDocxRenderer(self.settings.instruction_renderer_path)
        self.renderer_data_sanitizer = renderer_data_sanitizer or RendererDataSanitizer()

    def _build_document_router(self) -> DocumentRouter:
        ocr_provider = self._build_ocr_provider()
        return DocumentRouter(
            pdf_ocr_extractor=PDFOCRExtractor(
                ocr_provider=ocr_provider,
                dpi=self.settings.ocr_dpi,
                max_pages=self.settings.ocr_max_pages,
                concurrency=self.settings.ocr_concurrency,
            ),
            pdf_mixed_extractor=PDFMixedExtractor(
                ocr_provider=ocr_provider,
                dpi=self.settings.ocr_dpi,
                max_pages=self.settings.ocr_max_pages,
            ),
        )

    def _build_ocr_provider(self):
        if self.settings.ocr_provider.lower() == "yandex_vlm":
            return YandexVLMOCRProvider(self.llm_client)
        return StubOCRProvider()

    async def process_contract(
        self,
        file_path: str,
        original_filename: str,
        external_user_id: str,
        source_channel: str,
        external_entity_id: str | None = None,
    ) -> ProcessingResult:
        return await asyncio.to_thread(
            self._process_contract_sync,
            file_path,
            original_filename,
            external_user_id,
            source_channel,
            external_entity_id,
        )

    def _process_contract_sync(
        self,
        file_path: str,
        original_filename: str,
        external_user_id: str,
        source_channel: str,
        external_entity_id: str | None = None,
    ) -> ProcessingResult:
        stored_path = self.storage.save_upload(file_path, original_filename)
        record = self.repository.create_document(
            source_channel=source_channel,
            external_user_id=external_user_id,
            external_entity_id=external_entity_id,
            original_filename=original_filename,
            stored_path=str(stored_path),
        )
        document_id = record.id
        warnings: list[str] = []
        tracker = RunTracker(
            document_id=document_id,
            filename=original_filename,
            source_channel=source_channel,
            external_user_id=external_user_id,
            external_entity_id=external_entity_id,
        )
        tracker.artifacts["uploaded_file"] = str(stored_path)
        tracker.extra["models"] = {
            "ocr_reader": self.settings.yandex_cloud_model,
            "facts_extractor": self.settings.yandex_cloud_model,
            "instruction_data_generator": self.settings.yandex_generation_model or self.settings.yandex_cloud_model,
            "instruction_data_generator_mode": self.settings.yandex_generation_model_mode,
            "reviewer": self.settings.yandex_reviewer_model,
        }
        tracker.extra["ocr"] = {
            "provider": self.settings.ocr_provider,
            "dpi": self.settings.ocr_dpi,
            "max_pages": self.settings.ocr_max_pages,
            "concurrency": self.settings.ocr_concurrency,
        }
        usage_scope_token = self._start_usage_tracking()
        try:
            logger.info("Processing document_id=%s filename=%s", document_id, original_filename)
            self.repository.update_document(document_id, status="routing")
            with tracker.stage("routing"):
                routing = self.router.route(stored_path)
            if routing.source_format == SourceFormat.UNSUPPORTED or routing.extractor is None:
                raise ValueError(routing.reason)
            tracker.source_format = routing.source_format.value
            tracker.extra["routing_reason"] = routing.reason
            self.repository.update_document(
                document_id,
                status="extracting",
                source_format=routing.source_format.value,
            )

            with tracker.stage("document_extraction"):
                canonical_document = routing.extractor.extract(
                    stored_path,
                    source_file_id=document_id,
                    filename=original_filename,
                )
            tracker.source_format = canonical_document.source_format.value
            tracker.page_count = len(canonical_document.pages_or_sections)
            tracker.quality_score = canonical_document.quality_score
            if not canonical_document.document_text.strip():
                raise RuntimeError(
                    "Не удалось извлечь текст договора. "
                    "Если это сканированный PDF, подключите OCR_PROVIDER=yandex_vlm или внешний OCR."
                )
            warnings.extend(canonical_document.extraction_warnings)
            canonical_path = self.storage.write_json(document_id, "canonical_document.json", canonical_document)
            extracted_text_path = self.storage.write_text(document_id, "extracted_text.txt", canonical_document.document_text)
            tracker.artifacts["canonical_document"] = str(canonical_path)
            tracker.artifacts["extracted_text"] = str(extracted_text_path)

            self.repository.update_document(document_id, status="retrieving_context")
            with tracker.stage("rag_retrieval"):
                instruction_template = self.rag_agent.get_instruction_template()
                retrieval_query = self._build_retrieval_query(canonical_document.document_text)
                internal_rules = self.rag_agent.get_relevant_rules(retrieval_query)
                examples = self.rag_agent.get_relevant_examples(retrieval_query)

            self.repository.update_document(document_id, status="extracting_facts")
            try:
                with tracker.stage("contract_facts_extraction"):
                    facts = self.fact_extractor.extract(canonical_document)
            except Exception as exc:
                warnings.append(f"Contract facts extraction failed, used fallback facts: {exc}")
                tracker.extra["contract_facts_recovery_error"] = str(exc)
                with tracker.stage("contract_facts_recovery"):
                    facts = self._build_fallback_facts(canonical_document, str(exc))
            with tracker.stage("contract_facts_validation"):
                fact_validation = self.validation_service.validate_contract_facts(facts)
            if fact_validation.warnings:
                warnings.extend(fact_validation.warnings)
            facts_path = self.storage.write_json(document_id, "contract_facts.json", facts)
            tracker.artifacts["contract_facts"] = str(facts_path)

            self.repository.update_document(document_id, status="generating_instruction")
            renderer_data_path = None
            instruction_docx_path = None
            try:
                with tracker.stage("renderer_data_extraction"):
                    renderer_data, renderer_model, renderer_retry_reason = self._extract_renderer_data(
                        canonical_document,
                        facts,
                    )
                tracker.extra["renderer_generation"] = {
                    "mode": self.settings.yandex_generation_model_mode,
                    "model_used": renderer_model,
                    "premium_retry_reason": renderer_retry_reason,
                }
                with tracker.stage("renderer_data_sanitization"):
                    renderer_data, renderer_warnings = self.renderer_data_sanitizer.sanitize(renderer_data)
                warnings.extend(renderer_warnings)
                renderer_data_path = self.storage.write_json(document_id, "renderer_instruction_data.json", renderer_data)
                tracker.artifacts["renderer_data"] = str(renderer_data_path)
                with tracker.stage("instruction_markdown_render"):
                    instruction_markdown = self.docx_renderer.render_template_markdown(
                        renderer_data=renderer_data,
                        template_path=self.settings.instruction_template_docx_path,
                    )
                instruction_path = self.storage.write_text(document_id, "instruction.md", instruction_markdown)
                tracker.artifacts["instruction_markdown"] = str(instruction_path)
                with tracker.stage("instruction_docx_render"):
                    instruction_docx_path = self.docx_renderer.render_template_instruction(
                        renderer_data=renderer_data,
                        template_path=self.settings.instruction_template_docx_path,
                        output_path=self.storage.create_processing_dir(document_id)
                        / f"{FileStorage.safe_filename(Path(original_filename).stem)}_instruction.docx",
                    )
            except Exception as exc:
                if self.settings.strict_template_renderer:
                    raise RuntimeError(
                        "Template renderer failed and STRICT_TEMPLATE_RENDERER=true. "
                        "Check INSTRUCTION_RENDERER_PATH and INSTRUCTION_TEMPLATE_DOCX_PATH."
                    ) from exc
                warnings.append(f"Template renderer failed, used LLM markdown fallback: {exc}")
                with tracker.stage("instruction_markdown_generation_fallback"):
                    instruction_markdown = self.instruction_service.generate_instruction(
                        facts=facts,
                        instruction_template=instruction_template,
                        internal_rules=internal_rules,
                        examples=examples,
                    )
                instruction_path = self.storage.write_text(document_id, "instruction.md", instruction_markdown)
                tracker.artifacts["instruction_markdown"] = str(instruction_path)
                with tracker.stage("instruction_docx_render_fallback"):
                    instruction_docx_path = self.docx_renderer.render_markdown_to_docx(
                        instruction_markdown,
                        self.storage.create_processing_dir(document_id)
                        / f"{FileStorage.safe_filename(Path(original_filename).stem)}_instruction.docx",
                    )
            tracker.artifacts["instruction_docx"] = str(instruction_docx_path)

            self.repository.update_document(document_id, status="validating_instruction")
            with tracker.stage("instruction_validation"):
                instruction_validation = self.instruction_service.validate_instruction(
                    facts=facts,
                    instruction_markdown=instruction_markdown,
                )
            validation_payload = {
                "fact_validation": fact_validation.to_dict(),
                "instruction_validation": instruction_validation,
                "routing_reason": routing.reason,
                "source_format": canonical_document.source_format.value,
                "warnings": warnings,
                "renderer_data_path": str(renderer_data_path) if renderer_data_path else None,
            }
            if hasattr(self.llm_client, "usage_summary"):
                validation_payload["llm_usage"] = self.llm_client.usage_summary()
                tracker.extra["llm_usage"] = self.llm_client.usage_summary()
            validation_path = self.storage.write_json(document_id, "validation_result.json", validation_payload)
            tracker.artifacts["validation_result"] = str(validation_path)

            human_review_required = self._human_review_required(facts, fact_validation.to_dict(), instruction_validation)
            tracker.human_review_required = human_review_required
            tracker.warnings = warnings
            tracker.risk_flags = facts.risk_flags
            self.repository.save_processing_result(
                document_id=document_id,
                extracted_text_path=str(extracted_text_path),
                canonical_document_path=str(canonical_path),
                facts_json_path=str(facts_path),
                instruction_path=str(instruction_docx_path),
                validation_json_path=str(validation_path),
                human_review_required=human_review_required,
            )
            self.repository.update_document(document_id, status="completed")
            tracker.finish("completed")
            self._finish_usage_tracking(usage_scope_token)
            report_payload = tracker.to_dict()
            run_report_path = self.storage.write_json(document_id, "run_report.json", report_payload)

            return ProcessingResult(
                document_id=document_id,
                status="completed",
                instruction_markdown=instruction_markdown,
                instruction_path=str(instruction_path),
                instruction_docx_path=str(instruction_docx_path),
                facts_json_path=str(facts_path),
                warnings=warnings,
                risk_flags=facts.risk_flags,
                human_review_required=human_review_required,
                run_report_path=str(run_report_path),
                **self._result_metrics(report_payload),
            )
        except Exception as exc:
            logger.exception("Contract processing failed document_id=%s", document_id)
            self.repository.update_document(document_id, status="failed", error_message=str(exc))
            tracker.warnings = [*warnings, str(exc)]
            if hasattr(self.llm_client, "usage_summary"):
                tracker.extra["llm_usage"] = self.llm_client.usage_summary()
            tracker.finish("failed", error=str(exc))
            self._finish_usage_tracking(usage_scope_token)
            report_payload = tracker.to_dict()
            run_report_path = self.storage.write_json(document_id, "run_report.json", report_payload)
            return ProcessingResult(
                document_id=document_id,
                status="failed",
                warnings=[*warnings, str(exc)],
                human_review_required=True,
                run_report_path=str(run_report_path),
                **self._result_metrics(report_payload),
            )

    def _build_retrieval_query(self, document_text: str) -> str:
        if not document_text.strip():
            return "договор условия оплаты штрафы сроки ЭДО документооборот приложения"
        return document_text[:4000]

    def _human_review_required(
        self,
        facts: ContractFacts,
        fact_validation: dict[str, object],
        instruction_validation: dict[str, object],
    ) -> bool:
        if facts.human_review_required or facts.risk_flags:
            return True
        if bool(fact_validation.get("human_review_required")):
            return True
        code_validation = instruction_validation.get("code_validation")
        if isinstance(code_validation, dict) and not code_validation.get("is_valid", False):
            return True
        llm_validation = instruction_validation.get("llm_validation")
        if isinstance(llm_validation, dict) and not llm_validation.get("is_valid", True):
            return True
        return False

    def _start_usage_tracking(self) -> object | None:
        start_scope = getattr(self.llm_client, "start_usage_scope", None)
        if callable(start_scope):
            return start_scope()
        return None

    def _finish_usage_tracking(self, token: object | None) -> dict[str, object] | None:
        if token is None:
            return None
        finish_scope = getattr(self.llm_client, "finish_usage_scope", None)
        if callable(finish_scope):
            return finish_scope(token)
        return None

    def _result_metrics(self, report_payload: dict[str, object]) -> dict[str, object]:
        extra = report_payload.get("extra") if isinstance(report_payload.get("extra"), dict) else {}
        llm_usage = extra.get("llm_usage") if isinstance(extra, dict) and isinstance(extra.get("llm_usage"), dict) else {}
        requests = llm_usage.get("requests") if isinstance(llm_usage, dict) else []
        totals = llm_usage.get("totals") if isinstance(llm_usage, dict) and isinstance(llm_usage.get("totals"), dict) else {}
        return {
            "duration_seconds": report_payload.get("duration_seconds"),
            "source_format": report_payload.get("source_format"),
            "page_count": report_payload.get("page_count"),
            "quality_score": report_payload.get("quality_score"),
            "llm_requests": len(requests) if isinstance(requests, list) else None,
            "llm_total_tokens": totals.get("total_tokens") if isinstance(totals, dict) else None,
            "estimated_cost_usd": totals.get("estimated_cost_usd") if isinstance(totals, dict) else None,
            "estimated_cost_rub": totals.get("estimated_cost_rub") if isinstance(totals, dict) else None,
        }

    def _extract_renderer_data(
        self,
        canonical_document: CanonicalDocument,
        facts: ContractFacts,
    ) -> tuple[dict[str, object], str, str | None]:
        mode = self.settings.yandex_generation_model_mode.strip().lower()
        premium_model = self.settings.yandex_generation_model or None
        primary_model_label = self.settings.yandex_cloud_model

        if mode == "premium" and premium_model:
            payload = self.renderer_data_extractor.extract(canonical_document, facts, model_name=premium_model)
            return payload, premium_model, None

        if mode == "primary" or not premium_model:
            payload = self.renderer_data_extractor.extract(canonical_document, facts, model_name=None)
            return payload, primary_model_label, None

        payload = self.renderer_data_extractor.extract(canonical_document, facts, model_name=None)
        sanitized_payload, sanitizer_warnings = self.renderer_data_sanitizer.sanitize(payload)
        retry_reason = self._renderer_data_retry_reason(sanitized_payload)
        if retry_reason is None and sanitizer_warnings:
            retry_reason = "; ".join(sanitizer_warnings[:3])
        if retry_reason is None:
            return payload, primary_model_label, None

        logger.warning("Renderer data needs premium retry: %s", retry_reason)
        premium_payload = self.renderer_data_extractor.extract(canonical_document, facts, model_name=premium_model)
        return premium_payload, premium_model, retry_reason

    def _renderer_data_retry_reason(self, payload: dict[str, object]) -> str | None:
        critical_string_fields = [
            "client_name",
            "contract_legal_entity",
            "work_format",
            "payment_term",
            "edo_workflow",
        ]
        missing_fields = [field for field in critical_string_fields if not str(payload.get(field) or "").strip()]

        critical_list_fields = [
            "loading_requirements",
            "unloading_requirements",
            "penalties",
            "incident_actions",
            "payment_document_package",
            "document_format_requirements",
        ]
        missing_lists = [
            field
            for field in critical_list_fields
            if not isinstance(payload.get(field), list) or not payload.get(field)
        ]
        if len(missing_fields) >= 2:
            return f"missing critical fields: {', '.join(missing_fields)}"
        if len(missing_lists) >= 3:
            return f"missing critical lists: {', '.join(missing_lists)}"
        return None

    def _build_fallback_facts(self, canonical_document: CanonicalDocument, error: str) -> ContractFacts:
        text = canonical_document.document_text
        first_ref = canonical_document.pages_or_sections[0].ref if canonical_document.pages_or_sections else None
        facts = ContractFacts(
            human_review_required=True,
            missing_information=[
                "Структурированное извлечение ContractFacts не прошло из-за невалидного JSON модели.",
                "Итоговую инструкцию обязательно проверить человеком.",
            ],
            risk_flags=[f"ContractFacts fallback: {error}"],
        )
        contract_type_quote = self._first_regex(text, r"(ДОГОВОР\s+[А-ЯЁA-Z\s-]+)", flags=re.IGNORECASE)
        if contract_type_quote:
            facts.contract_type = self._fact(contract_type_quote.title(), first_ref, contract_type_quote)

        contract_number = self._first_regex(text, r"№\s*([A-Za-zА-Яа-яЁё0-9/_-]+)")
        if contract_number:
            facts.contract_number = self._fact(contract_number, first_ref, f"№ {contract_number}")

        contract_date = self._first_regex(
            text,
            r"(«?\s*\d{1,2}\s*»?\s+[а-яА-ЯёЁ]+\s+\d{4}\s*(?:года|г\.)?)",
        )
        if contract_date:
            facts.contract_date = self._fact(contract_date, first_ref, contract_date)

        client = self._first_regex(
            text,
            r"([А-ЯA-ZЁ][^,\n]{2,120}),\s+именуем(?:ое|ый|ая)\s+в\s+дальнейшем\s+[«\"]Клиент[»\"]",
        )
        if client:
            facts.parties.client = self._fact(client, first_ref, client)

        contractor = self._first_regex(
            text,
            r"([А-ЯA-ZЁ][^,\n]{2,120}),\s+именуем(?:ое|ый|ая)\s+в\s+дальнейшем\s+[«\"]Экспедитор[»\"]",
        )
        if contractor:
            facts.parties.contractor = self._fact(contractor, first_ref, contractor)

        subject_quote = self._first_regex(
            text,
            r"(Экспедитор\s+обязуется\s+за\s+вознаграждение[^.]{40,500}\.)",
            flags=re.IGNORECASE,
        )
        if subject_quote:
            facts.subject = self._fact(subject_quote, first_ref, subject_quote)

        payment_quote = self._first_regex(
            text,
            r"(Оплата\s+производится\s+не\s+позднее[^.]{20,500}\.)",
            flags=re.IGNORECASE,
        )
        if payment_quote:
            facts.payment_terms = self._fact(payment_quote, first_ref, payment_quote)

        edo_quote = self._first_regex(
            text,
            r"(Стороны\s+пришли\s+к\s+соглашению\s+о\s+внедрении\s+системы\s+электронного\s+документооборота[^.]{20,500}\.)",
            flags=re.IGNORECASE,
        )
        if edo_quote:
            facts.edo_terms = self._fact(edo_quote, first_ref, edo_quote)

        document_flow_quote = self._first_regex(
            text,
            r"(Отч[её]тные\s+документы\s+направляются\s+Клиенту[^.]{20,500}\.)",
            flags=re.IGNORECASE,
        )
        if document_flow_quote:
            facts.document_flow = self._fact(document_flow_quote, first_ref, document_flow_quote)

        return facts

    def _fact(self, value: object, source_ref: str | None, quote: str | None) -> ContractFactValue:
        return ContractFactValue(
            value=value,
            source_ref=source_ref,
            source_quote=quote,
            confidence="low",
            needs_human_review=True,
            comment="Fallback extraction, проверить человеком",
        )

    def _first_regex(self, text: str, pattern: str, *, flags: int = 0) -> str | None:
        match = re.search(pattern, text, flags)
        if not match:
            return None
        value = match.group(1) if match.groups() else match.group(0)
        return re.sub(r"\s+", " ", value).strip()


def build_default_pipeline() -> ContractPipeline:
    return ContractPipeline()
