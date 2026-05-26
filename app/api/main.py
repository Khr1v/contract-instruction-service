from __future__ import annotations

from fastapi import FastAPI

from app.api.bitrix_bot_routes import router as bitrix_bot_router
from app.api.bitrix_routes import router as bitrix_router
from app.api.routes import router as api_router
from app.config import get_settings
from app.logging_config import configure_logging


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings)
    app = FastAPI(title="Contract Instruction Service", version="0.1.0")
    app.include_router(api_router)
    app.include_router(bitrix_router)
    app.include_router(bitrix_bot_router)
    return app


app = create_app()
