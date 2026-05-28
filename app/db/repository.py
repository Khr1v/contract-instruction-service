from __future__ import annotations

from datetime import datetime

from app.db.database import Database
from app.db.models import BitrixAppInstallationRecord, DocumentRecord, ProcessingResultRecord


class DocumentRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create_document(
        self,
        *,
        source_channel: str,
        external_user_id: str,
        external_entity_id: str | None,
        original_filename: str,
        stored_path: str,
    ) -> DocumentRecord:
        with self.database.session() as session:
            record = DocumentRecord(
                source_channel=source_channel,
                external_user_id=external_user_id,
                external_entity_id=external_entity_id,
                original_filename=original_filename,
                stored_path=stored_path,
                status="created",
            )
            session.add(record)
            session.commit()
            session.refresh(record)
            return record

    def update_document(
        self,
        document_id: str,
        *,
        status: str | None = None,
        source_format: str | None = None,
        error_message: str | None = None,
    ) -> None:
        with self.database.session() as session:
            record = session.get(DocumentRecord, document_id)
            if record is None:
                raise ValueError(f"Document not found: {document_id}")
            if status is not None:
                record.status = status
            if source_format is not None:
                record.source_format = source_format
            if error_message is not None:
                record.error_message = error_message
            session.commit()

    def save_processing_result(
        self,
        *,
        document_id: str,
        extracted_text_path: str | None,
        canonical_document_path: str | None,
        facts_json_path: str | None,
        instruction_path: str | None,
        validation_json_path: str | None,
        human_review_required: bool,
    ) -> ProcessingResultRecord:
        with self.database.session() as session:
            existing = (
                session.query(ProcessingResultRecord)
                .filter(ProcessingResultRecord.document_id == document_id)
                .one_or_none()
            )
            if existing is None:
                existing = ProcessingResultRecord(document_id=document_id)
                session.add(existing)
            existing.extracted_text_path = extracted_text_path
            existing.canonical_document_path = canonical_document_path
            existing.facts_json_path = facts_json_path
            existing.instruction_path = instruction_path
            existing.validation_json_path = validation_json_path
            existing.human_review_required = human_review_required
            session.commit()
            session.refresh(existing)
            return existing


class BitrixAppInstallationRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def upsert_installation(
        self,
        *,
        domain: str,
        member_id: str | None,
        access_token: str,
        refresh_token: str | None,
        expires_at: datetime | None,
        application_token: str | None,
        client_endpoint: str | None,
        server_endpoint: str | None,
    ) -> BitrixAppInstallationRecord:
        with self.database.session() as session:
            query = session.query(BitrixAppInstallationRecord).filter(BitrixAppInstallationRecord.domain == domain)
            record = query.one_or_none()
            if record is None and member_id:
                record = (
                    session.query(BitrixAppInstallationRecord)
                    .filter(BitrixAppInstallationRecord.member_id == member_id)
                    .one_or_none()
                )
            if record is None:
                record = BitrixAppInstallationRecord(domain=domain)
                session.add(record)

            record.domain = domain
            record.member_id = member_id
            record.access_token = access_token
            record.refresh_token = refresh_token
            record.expires_at = expires_at
            record.application_token = application_token
            record.client_endpoint = client_endpoint
            record.server_endpoint = server_endpoint
            session.commit()
            session.refresh(record)
            return record

    def save_bot_state(
        self,
        *,
        installation_id: str,
        bot_id: int,
        bot_code: str,
        bot_client_id: str | None,
    ) -> None:
        with self.database.session() as session:
            record = session.get(BitrixAppInstallationRecord, installation_id)
            if record is None:
                raise ValueError(f"Bitrix installation not found: {installation_id}")
            record.bot_id = bot_id
            record.bot_code = bot_code
            record.bot_client_id = bot_client_id
            session.commit()

    def get_by_domain(self, domain: str) -> BitrixAppInstallationRecord | None:
        with self.database.session() as session:
            return (
                session.query(BitrixAppInstallationRecord)
                .filter(BitrixAppInstallationRecord.domain == domain)
                .one_or_none()
            )

    def get_latest(self) -> BitrixAppInstallationRecord | None:
        with self.database.session() as session:
            return (
                session.query(BitrixAppInstallationRecord)
                .order_by(BitrixAppInstallationRecord.updated_at.desc())
                .first()
            )
