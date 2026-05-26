from __future__ import annotations

import re
import shutil
import uuid
from pathlib import Path
from typing import Any

import orjson

from app.config import Settings, get_settings


class FileStorage:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.settings.ensure_directories()

    def save_upload(self, source_path: str | Path, original_filename: str) -> Path:
        upload_id = str(uuid.uuid4())
        safe_name = self.safe_filename(original_filename)
        target_dir = self.settings.uploads_dir / upload_id
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / safe_name
        shutil.copy2(source_path, target_path)
        return target_path

    def create_processing_dir(self, document_id: str) -> Path:
        path = self.settings.processed_dir / document_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def write_json(self, document_id: str, filename: str, payload: Any) -> Path:
        target = self.create_processing_dir(document_id) / filename
        if hasattr(payload, "model_dump"):
            payload = payload.model_dump(mode="json")
        target.write_bytes(orjson.dumps(payload, option=orjson.OPT_INDENT_2 | orjson.OPT_APPEND_NEWLINE))
        return target

    def write_text(self, document_id: str, filename: str, text: str) -> Path:
        target = self.create_processing_dir(document_id) / filename
        target.write_text(text, encoding="utf-8")
        return target

    @staticmethod
    def safe_filename(filename: str) -> str:
        filename = filename.strip().replace("\\", "_").replace("/", "_")
        filename = re.sub(r"[^A-Za-zА-Яа-я0-9_.() -]+", "_", filename)
        return filename or "document"

