from __future__ import annotations

from pathlib import Path

from app.config import Settings, get_settings


TEMPLATE_FILE = "instruction_template.md"
INTERNAL_RULES_FILE = "internal_rules.md"
EXAMPLES_FILE = "examples.md"


class TemplateLoader:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def read_template(self) -> str:
        return self._read_required(TEMPLATE_FILE)

    def read_internal_rules(self) -> str:
        return self._read_optional(INTERNAL_RULES_FILE)

    def read_examples(self) -> str:
        return self._read_optional(EXAMPLES_FILE)

    def _read_required(self, filename: str) -> str:
        path = Path(self.settings.templates_dir) / filename
        if not path.exists():
            raise FileNotFoundError(f"Required template file not found: {path}")
        return path.read_text(encoding="utf-8")

    def _read_optional(self, filename: str) -> str:
        path = Path(self.settings.templates_dir) / filename
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

