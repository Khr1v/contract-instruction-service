from __future__ import annotations

from app.config import get_settings
from app.logging_config import configure_logging


def bootstrap() -> None:
    settings = get_settings()
    configure_logging(settings)

