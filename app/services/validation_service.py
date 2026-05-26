from __future__ import annotations

from dataclasses import dataclass, field

from app.llm.schemas import Confidence, ContractFactValue, ContractFacts, InstructionValidationResult


@dataclass
class FactValidationResult:
    is_valid: bool
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    human_review_required: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "is_valid": self.is_valid,
            "problems": self.problems,
            "warnings": self.warnings,
            "human_review_required": self.human_review_required,
        }


class ValidationService:
    def validate_contract_facts(self, facts: ContractFacts) -> FactValidationResult:
        result = FactValidationResult(is_valid=True)

        required_fields: list[tuple[str, ContractFactValue]] = [
            ("contract_number", facts.contract_number),
            ("contract_date", facts.contract_date),
            ("parties.client", facts.parties.client),
            ("parties.contractor", facts.parties.contractor),
            ("subject", facts.subject),
            ("term_and_duration", facts.term_and_duration),
            ("payment_terms", facts.payment_terms),
            ("document_flow", facts.document_flow),
            ("edo_terms", facts.edo_terms),
        ]
        for name, value in required_fields:
            self._validate_fact_value(name, value, result, require_source=True)

        if not facts.responsibilities and not self._mentions(facts.missing_information, ["ответствен"]):
            result.problems.append("Ответственность сторон не найдена и не помечена как missing_information.")
        if not facts.penalties and not facts.fines and not self._mentions(facts.missing_information, ["штраф", "пен"]):
            result.problems.append("Штрафы/пени не найдены и не помечены как missing_information.")
        if not facts.appendices and not self._mentions(facts.missing_information, ["прилож"]):
            result.warnings.append("Приложения не найдены и не помечены как missing_information.")

        for group_name, values in [
            ("responsibilities", facts.responsibilities),
            ("penalties", facts.penalties),
            ("fines", facts.fines),
            ("deadlines", facts.deadlines),
            ("reporting_requirements", facts.reporting_requirements),
            ("special_conditions", facts.special_conditions),
            ("appendices", facts.appendices),
        ]:
            for index, value in enumerate(values, start=1):
                self._validate_fact_value(f"{group_name}[{index}]", value, result, require_source=True)

        low_confidence_count = self._count_low_confidence(facts)
        if low_confidence_count >= 5:
            result.warnings.append(f"Много полей с low confidence: {low_confidence_count}.")
            result.human_review_required = True

        if facts.human_review_required or facts.risk_flags:
            result.human_review_required = True
        if result.problems:
            result.is_valid = False
            result.human_review_required = True
        facts.human_review_required = facts.human_review_required or result.human_review_required
        return result

    def _validate_fact_value(
        self,
        name: str,
        value: ContractFactValue,
        result: FactValidationResult,
        *,
        require_source: bool,
    ) -> None:
        if value.value is None:
            result.problems.append(f"{name}: нет значения, требуется уточнение у человека.")
            result.human_review_required = True
            return
        if value.confidence == Confidence.LOW or value.needs_human_review:
            result.warnings.append(f"{name}: требует проверки человеком.")
            result.human_review_required = True
        if require_source and not value.source_ref:
            result.warnings.append(f"{name}: отсутствует source_ref.")
            result.human_review_required = True

    def _count_low_confidence(self, facts: ContractFacts) -> int:
        values = [
            facts.contract_type,
            facts.contract_number,
            facts.contract_date,
            facts.parties.client,
            facts.parties.contractor,
            facts.subject,
            facts.service_description,
            facts.term_and_duration,
            facts.payment_terms,
            facts.document_flow,
            facts.edo_terms,
            facts.delivery_or_service_terms,
            facts.acceptance_procedure,
            facts.termination_terms,
            facts.confidentiality,
            facts.requisites,
            *facts.responsibilities,
            *facts.penalties,
            *facts.fines,
            *facts.deadlines,
            *facts.reporting_requirements,
            *facts.special_conditions,
            *facts.appendices,
        ]
        return sum(value.confidence == Confidence.LOW for value in values)

    def _mentions(self, values: list[str], fragments: list[str]) -> bool:
        text = "\n".join(values).lower()
        return any(fragment in text for fragment in fragments)


class InstructionValidator:
    REQUIRED_SECTIONS = [
        "ИНСТРУКЦИЯ ПО РАБОТЕ",
        "С КЛИЕНТОМ",
        "1. Форма работы",
        "Гарантированные заявки",
        "Спотовые заявки",
        "2. Матрица коммуникаций Клиента",
        "5. Требования на погрузке",
        "6. Требования на выгрузке",
        "7. Особые условия",
        "8. Инструктаж для водителя",
        "9. Штрафы",
        "10. Действия логиста при проблемных ситуациях",
        "11. Информирование Клиента о статусе перевозки",
        "11. Документооборот",
    ]

    def validate(self, instruction_markdown: str, facts: ContractFacts) -> InstructionValidationResult:
        missing_sections = [
            section for section in self.REQUIRED_SECTIONS if section.lower() not in instruction_markdown.lower()
        ]
        problems: list[str] = []
        critical_warnings: list[str] = []

        if "9. штрафы" not in instruction_markdown.lower():
            critical_warnings.append("Нет обязательного раздела '9. Штрафы'.")
        if "11. документооборот" not in instruction_markdown.lower():
            critical_warnings.append("Нет обязательного раздела '11. Документооборот'.")
        if "|" not in instruction_markdown:
            critical_warnings.append("Инструкция не сохранила табличную структуру шаблона.")
        if facts.missing_information and "Уточнить у человека".lower() not in instruction_markdown.lower():
            problems.append("Есть missing_information, но в инструкции нет пометки 'Уточнить у человека'.")
        if facts.penalties or facts.fines:
            sanctions_text = " ".join(
                str(item.value) for item in [*facts.penalties, *facts.fines] if item.value is not None
            )
            if sanctions_text and "штраф" not in instruction_markdown.lower() and "пен" not in instruction_markdown.lower():
                critical_warnings.append("В фактах есть санкции, но инструкция не содержит явного упоминания штрафов/пени.")

        is_valid = not missing_sections and not problems and not critical_warnings
        return InstructionValidationResult(
            is_valid=is_valid,
            problems=problems,
            missing_sections=missing_sections,
            critical_warnings=critical_warnings,
            recommendation="approve" if is_valid else "human_review",
        )
