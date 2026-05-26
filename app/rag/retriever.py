from __future__ import annotations

import logging

from app.config import Settings, get_settings
from app.rag.loaders import TemplateLoader
from app.rag.vectorstore import VectorStoreService

logger = logging.getLogger(__name__)


class TemplateRAGAgent:
    """Retrieves RAG context while always returning the full current template."""

    def __init__(
        self,
        settings: Settings | None = None,
        loader: TemplateLoader | None = None,
        vectorstore: VectorStoreService | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.loader = loader or TemplateLoader(self.settings)
        self.vectorstore = vectorstore or VectorStoreService(self.settings)

    def get_instruction_template(self) -> str:
        return self.loader.read_template()

    def get_relevant_rules(self, query: str) -> list[str]:
        retrieved = self._retrieve(query=query, kind="rules")
        if retrieved:
            return retrieved
        fallback = self.loader.read_internal_rules()
        return [fallback] if fallback.strip() else []

    def get_relevant_examples(self, query: str) -> list[str]:
        retrieved = self._retrieve(query=query, kind="examples")
        if retrieved:
            return retrieved
        fallback = self.loader.read_examples()
        return [fallback] if fallback.strip() else []

    def _retrieve(self, query: str, kind: str) -> list[str]:
        try:
            store = self.vectorstore.get_store()
            documents = store.similarity_search(
                query,
                k=self.settings.rag_top_k,
                filter={"kind": kind},
            )
            return [document.page_content for document in documents]
        except Exception as exc:
            logger.warning("RAG retrieval failed for kind=%s: %s", kind, exc)
            return []
