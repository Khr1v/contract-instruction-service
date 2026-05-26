from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.contract_pipeline import ContractPipeline

router = APIRouter(prefix="/api/bitrix", tags=["bitrix"])
pipeline = ContractPipeline()


class BitrixDocumentWebhook(BaseModel):
    bitrix_deal_id: str
    bitrix_company_id: str | None = None
    bitrix_user_id: str
    file_url: str
    filename: str
    metadata: dict[str, Any] = Field(default_factory=dict)


@router.post("/webhook/document")
async def process_bitrix_document(payload: BitrixDocumentWebhook) -> dict[str, object]:
    # TODO: add Bitrix webhook signature/auth validation before production use.
    suffix = Path(payload.filename).suffix
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.close()
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.get(payload.file_url)
            response.raise_for_status()
        Path(tmp.name).write_bytes(response.content)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to download Bitrix file: {exc}") from exc

    result = await pipeline.process_contract(
        file_path=tmp.name,
        original_filename=payload.filename,
        external_user_id=payload.bitrix_user_id,
        source_channel="bitrix",
        external_entity_id=payload.bitrix_deal_id,
    )
    return {
        "status": result.status,
        "document_id": result.document_id,
        "instruction_path": result.instruction_path,
        "instruction_docx_path": result.instruction_docx_path,
        "run_report_path": result.run_report_path,
        "duration_seconds": result.duration_seconds,
        "source_format": result.source_format,
        "page_count": result.page_count,
        "llm_requests": result.llm_requests,
        "llm_total_tokens": result.llm_total_tokens,
        "estimated_cost_usd": result.estimated_cost_usd,
        "estimated_cost_rub": result.estimated_cost_rub,
        "warnings": result.warnings,
        "human_review_required": result.human_review_required,
    }
