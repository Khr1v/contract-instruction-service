from __future__ import annotations

import logging
import shutil

from app.config import Settings, get_settings
from app.rag.loaders import EXAMPLES_FILE, INTERNAL_RULES_FILE, TEMPLATE_FILE, TemplateLoader
from app.rag.vectorstore import IndexedSource, VectorStoreService

logger = logging.getLogger(__name__)


class TemplateRAGIndexer:
    def __init__(
        self,
        settings: Settings | None = None,
        loader: TemplateLoader | None = None,
        vectorstore: VectorStoreService | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.loader = loader or TemplateLoader(self.settings)
        self.vectorstore = vectorstore or VectorStoreService(self.settings)

    def reindex(self) -> int:
        if self.settings.vectorstore_dir.exists():
            shutil.rmtree(self.settings.vectorstore_dir)
        self.settings.vectorstore_dir.mkdir(parents=True, exist_ok=True)
        sources = [
            IndexedSource(TEMPLATE_FILE, self.loader.read_template(), "template"),
            IndexedSource(INTERNAL_RULES_FILE, self.loader.read_internal_rules(), "rules"),
            IndexedSource(EXAMPLES_FILE, self.loader.read_examples(), "examples"),
        ]
        count = self.vectorstore.index_sources(sources)
        logger.info("Indexed %s RAG chunks", count)
        return count

