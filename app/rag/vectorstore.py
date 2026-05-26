from __future__ import annotations

import hashlib
import logging
import math
import os
import re
from dataclasses import dataclass

from chromadb.config import Settings as ChromaClientSettings
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")


@dataclass(frozen=True)
class IndexedSource:
    name: str
    content: str
    kind: str


class LocalHashEmbeddings(Embeddings):
    """Offline fallback embeddings.

    This is not as semantically strong as sentence-transformers, but it lets the
    MVP build and query Chroma without downloading a HuggingFace model.
    """

    def __init__(self, dimensions: int = 384) -> None:
        self.dimensions = dimensions

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        tokens = re.findall(r"[\wа-яА-ЯёЁ]+", text.lower())
        for token in tokens:
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            bucket = int.from_bytes(digest[:4], "little") % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[bucket] += sign
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return vector
        return [value / norm for value in vector]


class VectorStoreService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._embeddings: Embeddings | None = None
        self._store: Chroma | None = None

    def embeddings(self) -> Embeddings:
        if self._embeddings is not None:
            return self._embeddings
        try:
            self._embeddings = HuggingFaceEmbeddings(
                model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
            )
        except Exception as exc:
            logger.warning(
                "Could not load HuggingFace embeddings, falling back to LocalHashEmbeddings: %s",
                exc,
            )
            self._embeddings = LocalHashEmbeddings()
        return self._embeddings

    def get_store(self) -> Chroma:
        if self._store is not None:
            return self._store
        self._store = Chroma(
            collection_name="contract_instruction_rag",
            embedding_function=self.embeddings(),
            persist_directory=str(self.settings.vectorstore_dir),
            client_settings=ChromaClientSettings(
                is_persistent=True,
                anonymized_telemetry=False,
                persist_directory=str(self.settings.vectorstore_dir),
            ),
        )
        return self._store

    def index_sources(self, sources: list[IndexedSource]) -> int:
        splitter = RecursiveCharacterTextSplitter(chunk_size=1200, chunk_overlap=180)
        documents: list[Document] = []
        for source in sources:
            if not source.content.strip():
                continue
            chunks = splitter.split_text(source.content)
            for index, chunk in enumerate(chunks):
                documents.append(
                    Document(
                        page_content=chunk,
                        metadata={"source": source.name, "kind": source.kind, "chunk": index},
                    )
                )
        store = self.get_store()
        if documents:
            store.add_documents(documents)
            store.persist()
        return len(documents)
