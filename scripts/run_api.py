from __future__ import annotations

from pathlib import Path
import sys

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings


if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run("app.api.main:app", host=settings.api_host, port=settings.api_port, reload=settings.app_env == "dev")
