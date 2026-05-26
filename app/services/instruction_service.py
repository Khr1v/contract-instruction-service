from __future__ import annotations

import logging

from app.llm.chains import InstructionGenerator, InstructionLLMValidator
from app.llm.schemas import ContractFacts, InstructionValidationResult
from app.services.validation_service import InstructionValidator

logger = logging.getLogger(__name__)


class InstructionService:
    def __init__(
        self,
        generator: InstructionGenerator,
        code_validator: InstructionValidator | None = None,
        llm_validator: InstructionLLMValidator | None = None,
    ) -> None:
        self.generator = generator
        self.code_validator = code_validator or InstructionValidator()
        self.llm_validator = llm_validator

    def generate_instruction(
        self,
        *,
        facts: ContractFacts,
        instruction_template: str,
        internal_rules: list[str],
        examples: list[str],
    ) -> str:
        return self.generator.generate(
            facts=facts,
            instruction_template=instruction_template,
            internal_rules=internal_rules,
            examples=examples,
        )

    def validate_instruction(
        self,
        *,
        facts: ContractFacts,
        instruction_markdown: str,
    ) -> dict[str, object]:
        code_validation = self.code_validator.validate(instruction_markdown, facts)
        payload: dict[str, object] = {"code_validation": code_validation.model_dump(mode="json")}
        if self.llm_validator is not None:
            try:
                llm_validation: InstructionValidationResult = self.llm_validator.validate(facts, instruction_markdown)
                payload["llm_validation"] = llm_validation.model_dump(mode="json")
            except Exception as exc:
                logger.exception("Instruction LLM validation failed")
                payload["llm_validation_error"] = str(exc)
        return payload

