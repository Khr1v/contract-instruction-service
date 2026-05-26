from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class GuaranteeLane:
    direction: str = ""
    cost: str = ""
    vehicles_count: str = ""
    special_conditions: str = ""


@dataclass(slots=True)
class PlatformRow:
    platform_name: str = ""
    credentials: str = ""
    bidding_rules: str = ""
    instruction_link: str = ""


@dataclass(slots=True)
class ContactRow:
    full_name: str = ""
    role: str = ""
    contacts: str = ""
    responsibility: str = ""


@dataclass(slots=True)
class StatusInforming:
    is_required: str = ""
    frequency: str = ""
    channels: list[str] = field(default_factory=list)


@dataclass(slots=True)
class CustomerInstructionData:
    client_name: str = ""
    contract_legal_entity: str = ""
    generated_date: str = ""
    work_format: str = ""
    guarantee_lanes: list[GuaranteeLane] = field(default_factory=list)
    guaranteed_application_rules: list[str] = field(default_factory=list)
    spot_application_rules: list[str] = field(default_factory=list)
    platform_rows: list[PlatformRow] = field(default_factory=list)
    communication_rows: list[ContactRow] = field(default_factory=list)
    loading_requirements: list[str] = field(default_factory=list)
    unloading_requirements: list[str] = field(default_factory=list)
    special_conditions: list[str] = field(default_factory=list)
    driver_briefing: list[str] = field(default_factory=list)
    penalties: list[str] = field(default_factory=list)
    incident_actions: list[str] = field(default_factory=list)
    status_informing: StatusInforming = field(default_factory=StatusInforming)
    payment_document_package: list[str] = field(default_factory=list)
    payment_document_package_auto: list[str] = field(default_factory=list)
    payment_document_package_rail: list[str] = field(default_factory=list)
    document_format_requirements: list[str] = field(default_factory=list)
    copies_followed_by_originals: str = ""
    edo_workflow: str = ""
    client_document_contact: str = ""
    executor_document_contact: str = ""
    copies_email: str = ""
    originals_postal_address: str = ""
    payment_term: str = ""
    payment_hold_condition: str = ""
    tax_change_notification: str = ""
    client_payment_delay_penalty: str = ""
    open_questions: list[str] = field(default_factory=list)
    extraction_notes: list[str] = field(default_factory=list)

