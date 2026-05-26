from __future__ import annotations

from app.llm.schemas import Confidence, ContractFactValue, ContractFacts
from app.services.validation_service import InstructionValidator, ValidationService


def test_contract_validator_requires_critical_fields():
    facts = ContractFacts()

    result = ValidationService().validate_contract_facts(facts)

    assert not result.is_valid
    assert result.human_review_required
    assert any("contract_number" in problem for problem in result.problems)


def test_instruction_validator_requires_sections_and_human_review_phrase():
    facts = ContractFacts(
        missing_information=["Штрафы/пени/ответственность не найдены, уточнить у человека"]
    )
    instruction = "# Краткая карточка договора\nНет данных."

    result = InstructionValidator().validate(instruction, facts)

    assert not result.is_valid
    assert result.missing_sections
    assert result.problems


def test_validator_accepts_sourced_fact_value():
    facts = ContractFacts(
        contract_number=ContractFactValue(value="1", source_ref="page_1", source_quote="№ 1", confidence=Confidence.HIGH, needs_human_review=False),
        contract_date=ContractFactValue(value="01.01.2026", source_ref="page_1", source_quote="01.01.2026", confidence=Confidence.HIGH, needs_human_review=False),
        parties={
            "client": {"value": "Клиент", "source_ref": "page_1", "source_quote": "Клиент", "confidence": "high", "needs_human_review": False},
            "contractor": {"value": "Исполнитель", "source_ref": "page_1", "source_quote": "Исполнитель", "confidence": "high", "needs_human_review": False},
        },
        subject={"value": "Услуги", "source_ref": "page_1", "source_quote": "услуги", "confidence": "high", "needs_human_review": False},
        term_and_duration={"value": "1 год", "source_ref": "page_2", "source_quote": "1 год", "confidence": "high", "needs_human_review": False},
        payment_terms={"value": "10 дней", "source_ref": "page_3", "source_quote": "10 дней", "confidence": "high", "needs_human_review": False},
        document_flow={"value": "Акт", "source_ref": "page_4", "source_quote": "акт", "confidence": "high", "needs_human_review": False},
        edo_terms={"value": "Диадок", "source_ref": "page_4", "source_quote": "Диадок", "confidence": "high", "needs_human_review": False},
        responsibilities=[{"value": "По закону", "source_ref": "page_5", "source_quote": "ответственность", "confidence": "medium", "needs_human_review": False}],
        penalties=[{"value": "0,1%", "source_ref": "page_5", "source_quote": "0,1%", "confidence": "medium", "needs_human_review": False}],
        appendices=[{"value": "Приложение №1", "source_ref": "page_6", "source_quote": "Приложение №1", "confidence": "medium", "needs_human_review": False}],
    )

    result = ValidationService().validate_contract_facts(facts)

    assert result.is_valid

