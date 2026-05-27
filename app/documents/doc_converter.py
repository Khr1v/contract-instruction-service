from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path


class DocumentConversionError(RuntimeError):
    """Document conversion failed before extraction."""


class LegacyDocConverter:
    """Convert legacy Word .doc files to .docx via LibreOffice headless."""

    def __init__(self, executable: str | None = None) -> None:
        self.executable = executable or self._find_executable()

    def convert_doc_to_docx(self, source_path: str | Path) -> Path:
        source = Path(source_path)
        if source.suffix.lower() != ".doc":
            return source
        if not self.executable:
            raise DocumentConversionError(
                "Файл .doc требует конвертации, но LibreOffice не установлен на сервере. "
                "Установите libreoffice или отправьте договор в DOCX/PDF."
            )

        output_dir = Path(tempfile.mkdtemp(prefix="contract_doc_convert_"))
        command = [
            self.executable,
            "--headless",
            "--convert-to",
            "docx",
            "--outdir",
            str(output_dir),
            str(source),
        ]
        try:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=120, check=False)
        except subprocess.TimeoutExpired as exc:
            raise DocumentConversionError("Конвертация .doc в .docx превысила лимит времени.") from exc

        converted = output_dir / f"{source.stem}.docx"
        if completed.returncode != 0 or not converted.exists():
            details = (completed.stderr or completed.stdout or "").strip()
            raise DocumentConversionError(f"Не удалось конвертировать .doc в .docx через LibreOffice. {details}")
        return converted

    @staticmethod
    def _find_executable() -> str | None:
        for candidate in ("libreoffice", "soffice"):
            path = shutil.which(candidate)
            if path:
                return path
        return None
