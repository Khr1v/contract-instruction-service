from __future__ import annotations

import logging
from typing import Protocol

import orjson
from langchain_core.prompts import PromptTemplate

from app.llm.prompts import (
    CONTRACT_FACT_EXTRACTION_PROMPT,
    INSTRUCTION_GENERATION_PROMPT,
    INSTRUCTION_VALIDATION_PROMPT,
    JSON_REPAIR_PROMPT,
    RENDERER_DATA_EXTRACTION_PROMPT,
)
from app.llm.schemas import CanonicalDocument, ContractFacts, InstructionValidationResult
from app.utils.json_utils import parse_json_object
from app.utils.text_utils import trim_for_prompt

logger = logging.getLogger(__name__)


class TextGenerator(Protocol):
    def generate_text(
        self,
        *,
        instructions: str,
        input: str,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
        model_name: str | None = None,
    ) -> str:
        ...


class ContractFactExtractor:
    def __init__(self, llm_client: TextGenerator, fallback_model_name: str | None = None) -> None:
        self.llm_client = llm_client
        self.fallback_model_name = fallback_model_name
        self.prompt = PromptTemplate.from_template(
            """Документ в CanonicalDocument:
filename: {filename}
source_format: {source_format}
quality_score: {quality_score}
extraction_warnings: {warnings}

Текст договора с source_ref:
{document_text}
"""
        )

    def extract(self, canonical_document: CanonicalDocument) -> ContractFacts:
        prompt_input = self.prompt.format(
            filename=canonical_document.filename,
            source_format=canonical_document.source_format.value,
            quality_score=canonical_document.quality_score,
            warnings="\n".join(canonical_document.extraction_warnings) or "Нет",
            document_text=trim_for_prompt(canonical_document.document_text),
        )
        payload = self._extract_payload(prompt_input, model_name=None)
        facts = ContractFacts.model_validate(payload)
        if canonical_document.quality_score < 0.5 or canonical_document.extraction_warnings:
            facts.human_review_required = True
            for warning in canonical_document.extraction_warnings:
                if warning not in facts.risk_flags:
                    facts.risk_flags.append(warning)
        return facts

    def _extract_payload(self, prompt_input: str, *, model_name: str | None) -> dict[str, object]:
        raw = self.llm_client.generate_text(
            instructions=CONTRACT_FACT_EXTRACTION_PROMPT,
            input=prompt_input,
            temperature=0.2,
            max_output_tokens=12_000,
            model_name=model_name,
        )
        try:
            return self._parse_or_repair_json(raw, context="contract_facts", model_name=model_name)
        except Exception:
            if model_name is None and self.fallback_model_name:
                logger.warning("Contract facts extraction failed on primary model; retrying with %s", self.fallback_model_name)
                return self._extract_payload(prompt_input, model_name=self.fallback_model_name)
            raise

    def _parse_or_repair_json(self, raw: str, *, context: str, model_name: str | None = None) -> dict[str, object]:
        try:
            return parse_json_object(raw)
        except Exception as exc:
            logger.warning("Could not parse %s JSON, requesting repair: %s", context, exc)
            repaired = self.llm_client.generate_text(
                instructions=JSON_REPAIR_PROMPT,
                input=raw,
                temperature=0.0,
                max_output_tokens=12_000,
                model_name=model_name,
            )
            return parse_json_object(repaired)


class InstructionGenerator:
    def __init__(self, llm_client: TextGenerator) -> None:
        self.llm_client = llm_client
        self.prompt = PromptTemplate.from_template(
            """contract_facts_json:
{contract_facts_json}

instruction_template:
{instruction_template}

internal_rules:
{internal_rules}

examples:
{examples}
"""
        )

    def generate(
        self,
        *,
        facts: ContractFacts,
        instruction_template: str,
        internal_rules: list[str],
        examples: list[str],
    ) -> str:
        prompt_input = self.prompt.format(
            contract_facts_json=orjson.dumps(facts.model_dump(mode="json"), option=orjson.OPT_INDENT_2).decode("utf-8"),
            instruction_template=instruction_template,
            internal_rules="\n\n---\n\n".join(internal_rules) if internal_rules else "Нет релевантных правил.",
            examples="\n\n---\n\n".join(examples) if examples else "Нет релевантных примеров.",
        )
        return self.llm_client.generate_text(
            instructions=INSTRUCTION_GENERATION_PROMPT,
            input=prompt_input,
            temperature=0.2,
        )


class RendererDataExtractor:
    def __init__(self, llm_client: TextGenerator, model_name: str | None = None) -> None:
        self.llm_client = llm_client
        self.model_name = model_name
        self.prompt = PromptTemplate.from_template(
            """canonical_document:
filename: {filename}
source_format: {source_format}
quality_score: {quality_score}
warnings: {warnings}

contract_facts_json:
{contract_facts_json}

document_text_with_source_refs:
{document_text}
"""
        )

    def extract(
        self,
        canonical_document: CanonicalDocument,
        facts: ContractFacts,
        *,
        model_name: str | None = None,
    ) -> dict[str, object]:
        prompt_input = self.prompt.format(
            filename=canonical_document.filename,
            source_format=canonical_document.source_format.value,
            quality_score=canonical_document.quality_score,
            warnings="\n".join(canonical_document.extraction_warnings) or "Нет",
            contract_facts_json=orjson.dumps(
                facts.model_dump(mode="json"),
                option=orjson.OPT_INDENT_2,
            ).decode("utf-8"),
            document_text=trim_for_prompt(canonical_document.document_text, max_chars=140_000),
        )
        raw = self.llm_client.generate_text(
            instructions=RENDERER_DATA_EXTRACTION_PROMPT,
            input=prompt_input,
            temperature=0.1,
            max_output_tokens=16_000,
            model_name=model_name if model_name is not None else self.model_name,
        )
        try:
            return parse_json_object(raw)
        except Exception as exc:
            logger.warning("Could not parse renderer data JSON, requesting repair: %s", exc)
            repaired = self.llm_client.generate_text(
                instructions=JSON_REPAIR_PROMPT,
                input=raw,
                temperature=0.0,
                max_output_tokens=16_000,
                model_name=model_name if model_name is not None else self.model_name,
            )
            return parse_json_object(repaired)


class InstructionLLMValidator:
    def __init__(self, llm_client: TextGenerator) -> None:
        self.llm_client = llm_client
        self.prompt = PromptTemplate.from_template(
            """contract_facts_json:
{contract_facts_json}

instruction_markdown:
{instruction_markdown}
"""
        )

    def validate(self, facts: ContractFacts, instruction_markdown: str) -> InstructionValidationResult:
        prompt_input = self.prompt.format(
            contract_facts_json=orjson.dumps(facts.model_dump(mode="json"), option=orjson.OPT_INDENT_2).decode("utf-8"),
            instruction_markdown=trim_for_prompt(instruction_markdown, max_chars=60_000),
        )
        raw = self.llm_client.generate_text(
            instructions=INSTRUCTION_VALIDATION_PROMPT,
            input=prompt_input,
            temperature=0.1,
            max_output_tokens=2000,
        )
        try:
            payload = parse_json_object(raw)
        except Exception as exc:
            logger.warning("Could not parse instruction validation JSON, requesting repair: %s", exc)
            repaired = self.llm_client.generate_text(
                instructions=JSON_REPAIR_PROMPT,
                input=raw,
                temperature=0.0,
                max_output_tokens=2000,
            )
            payload = parse_json_object(repaired)
        return InstructionValidationResult.model_validate(payload)
