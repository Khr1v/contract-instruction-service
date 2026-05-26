from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.logging_config import configure_logging
from app.rag.index_templates import TemplateRAGIndexer


if __name__ == "__main__":
    settings = get_settings()
    configure_logging(settings)
    count = TemplateRAGIndexer(settings).reindex()
    print(f"Indexed RAG chunks: {count}")
    print(f"Vectorstore dir: {settings.vectorstore_dir}")
