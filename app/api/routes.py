from __future__ import annotations

from fastapi import APIRouter

from app.config import get_settings
from app.rag.index_templates import TemplateRAGIndexer

router = APIRouter(prefix="/api")


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/reindex-templates")
async def reindex_templates() -> dict[str, int | str]:
    settings = get_settings()
    count = TemplateRAGIndexer(settings).reindex()
    return {"status": "completed", "chunks": count}

