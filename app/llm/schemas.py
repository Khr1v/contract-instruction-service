from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SourceFormat(str, Enum):
    DOCX = "docx"
    PDF_TEXT = "pdf_text"
    PDF_SCAN = "pdf_scan"
    PDF_MIXED = "pdf_mixed"
    UNSUPPORTED = "unsupported"


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class PageOrSection(BaseModel):
    ref: str
    title: str | None = None
    text: str = ""
    tables: list[str] = Field(default_factory=list)
    quality: float = 1.0
    warnings: list[str] = Field(default_factory=list)


class CanonicalDocument(BaseModel):
    source_file_id: str
    filename: str
    source_format: SourceFormat
    document_text: str
    pages_or_sections: list[PageOrSection] = Field(default_factory=list)
    tables: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    extraction_warnings: list[str] = Field(default_factory=list)
    quality_score: float = 1.0


class ContractFactValue(BaseModel):
    value: Any | None = None
    source_ref: str | None = None
    source_quote: str | None = None
    confidence: Confidence = Confidence.LOW
    needs_human_review: bool = True
    comment: str | None = None

    @classmethod
    def missing(cls, comment: str = "Уточнить у человека") -> "ContractFactValue":
        return cls(
            value=None,
            source_ref=None,
            source_quote=None,
            confidence=Confidence.LOW,
            needs_human_review=True,
            comment=comment,
        )

    @model_validator(mode="after")
    def mark_missing_values_for_review(self) -> "ContractFactValue":
        if self.value is None:
            self.confidence = Confidence.LOW
            self.needs_human_review = True
            if not self.comment:
                self.comment = "Уточнить у человека"
        return self


class ContractParties(BaseModel):
    client: ContractFactValue = Field(default_factory=ContractFactValue.missing)
    contractor: ContractFactValue = Field(default_factory=ContractFactValue.missing)

    @field_validator("client", "contractor", mode="before")
    @classmethod
    def coerce_party_fact(cls, value: object) -> object:
        return coerce_fact_value(value)


class ContractFacts(BaseModel):
    model_config = ConfigDict(extra="allow")

    contract_type: ContractFactValue = Field(default_factory=ContractFactValue.missing)
    contract_number: ContractFactValue = Field(default_factory=ContractFactValue.missing)
    contract_date: ContractFactValue = Field(default_factory=ContractFactValue.missing)
    parties: ContractParties = Field(default_factory=ContractParties)
    subject: ContractFactValue = Field(default_factory=ContractFactValue.missing)
    service_description: ContractFactValue = Field(default_factory=ContractFactValue.missing)
    term_and_duration: ContractFactValue = Field(default_factory=ContractFactValue.missing)
    payment_terms: ContractFactValue = Field(default_factory=ContractFactValue.missing)
    document_flow: ContractFactValue = Field(default_factory=ContractFactValue.missing)
    edo_terms: ContractFactValue = Field(default_factory=ContractFactValue.missing)
    delivery_or_service_terms: ContractFactValue = Field(default_factory=ContractFactValue.missing)
    responsibilities: list[ContractFactValue] = Field(default_factory=list)
    penalties: list[ContractFactValue] = Field(default_factory=list)
    fines: list[ContractFactValue] = Field(default_factory=list)
    deadlines: list[ContractFactValue] = Field(default_factory=list)
    reporting_requirements: list[ContractFactValue] = Field(default_factory=list)
    acceptance_procedure: ContractFactValue = Field(default_factory=ContractFactValue.missing)
    termination_terms: ContractFactValue = Field(default_factory=ContractFactValue.missing)
    confidentiality: ContractFactValue = Field(default_factory=ContractFactValue.missing)
    special_conditions: list[ContractFactValue] = Field(default_factory=list)
    appendices: list[ContractFactValue] = Field(default_factory=list)
    requisites: ContractFactValue = Field(default_factory=ContractFactValue.missing)
    missing_information: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    human_review_required: bool = False

    @field_validator(
        "contract_type",
        "contract_number",
        "contract_date",
        "subject",
        "service_description",
        "term_and_duration",
        "payment_terms",
        "document_flow",
        "edo_terms",
        "delivery_or_service_terms",
        "acceptance_procedure",
        "termination_terms",
        "confidentiality",
        "requisites",
        mode="before",
    )
    @classmethod
    def coerce_fact_fields(cls, value: object) -> object:
        return coerce_fact_value(value)

    @field_validator(
        "responsibilities",
        "penalties",
        "fines",
        "deadlines",
        "reporting_requirements",
        "special_conditions",
        "appendices",
        mode="before",
    )
    @classmethod
    def normalize_fact_lists(cls, value: object) -> list[object]:
        if value is None:
            return []
        if isinstance(value, list):
            return [coerce_fact_value(item) for item in value]
        return [coerce_fact_value(value)]


def coerce_fact_value(value: object) -> object:
    if value is None:
        return ContractFactValue.missing().model_dump(mode="json")
    if isinstance(value, ContractFactValue):
        return value
    if isinstance(value, dict):
        fact_keys = {"value", "source_ref", "source_quote", "confidence", "needs_human_review", "comment"}
        if fact_keys.intersection(value.keys()):
            return value
        return {
            "value": value,
            "source_ref": None,
            "source_quote": None,
            "confidence": "low",
            "needs_human_review": True,
            "comment": "Уточнить у человека",
        }
    return {
        "value": value,
        "source_ref": None,
        "source_quote": None,
        "confidence": "medium",
        "needs_human_review": True,
        "comment": "Проверить источник",
    }


class InstructionValidationResult(BaseModel):
    is_valid: bool
    problems: list[str] = Field(default_factory=list)
    missing_sections: list[str] = Field(default_factory=list)
    critical_warnings: list[str] = Field(default_factory=list)
    recommendation: str = "review"


class ProcessingResult(BaseModel):
    document_id: str
    status: str
    instruction_markdown: str | None = None
    instruction_path: str | None = None
    instruction_docx_path: str | None = None
    facts_json_path: str | None = None
    run_report_path: str | None = None
    duration_seconds: float | None = None
    source_format: str | None = None
    page_count: int | None = None
    quality_score: float | None = None
    llm_requests: int | None = None
    llm_total_tokens: int | None = None
    estimated_cost_usd: float | None = None
    estimated_cost_rub: float | None = None
    warnings: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    human_review_required: bool = True
