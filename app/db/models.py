from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def new_uuid() -> str:
    return str(uuid.uuid4())


class DocumentRecord(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    source_channel: Mapped[str] = mapped_column(String(32), nullable=False)
    external_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    external_entity_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    stored_path: Mapped[str] = mapped_column(Text, nullable=False)
    source_format: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="created")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    result: Mapped["ProcessingResultRecord | None"] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
    )


class ProcessingResultRecord(Base):
    __tablename__ = "processing_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), nullable=False, unique=True)
    extracted_text_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    canonical_document_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    facts_json_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    instruction_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    validation_json_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    human_review_required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    document: Mapped[DocumentRecord] = relationship(back_populates="result")


class BitrixAppInstallationRecord(Base):
    __tablename__ = "bitrix_app_installations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    domain: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    member_id: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    access_token: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    application_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    client_endpoint: Mapped[str | None] = mapped_column(Text, nullable=True)
    server_endpoint: Mapped[str | None] = mapped_column(Text, nullable=True)
    bot_id: Mapped[int | None] = mapped_column(nullable=True)
    bot_code: Mapped[str | None] = mapped_column(String(255), nullable=True)
    bot_client_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )
