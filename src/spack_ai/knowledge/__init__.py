"""Knowledge base: the agent's reference library, searched through the search_knowledge skill."""

from __future__ import annotations

from collections import Counter
from functools import cached_property
from pathlib import Path

import yaml

from spack_ai.knowledge.chunker import Chunk, chunk_document
from spack_ai.knowledge.loader import Document, load_documents
from spack_ai.knowledge.retriever import BM25Retriever, Retriever, SearchHit

__all__ = ["KnowledgeBase", "SearchHit", "Retriever", "Chunk", "Document"]


class KnowledgeBase:
    def __init__(
        self,
        root: Path,
        chunk_size: int = 1500,
        chunk_overlap: int = 200,
        retriever: Retriever | None = None,
    ):
        self.root = root
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self._retriever = retriever or BM25Retriever()
        self._indexed = False

    @cached_property
    def documents(self) -> list[Document]:
        return load_documents(self.root)

    @cached_property
    def chunks(self) -> list[Chunk]:
        return [
            c
            for doc in self.documents
            for c in chunk_document(doc, self.chunk_size, self.chunk_overlap)
        ]

    def search(self, query: str, k: int = 6, section: str | None = None) -> list[SearchHit]:
        if not self._indexed:
            self._retriever.index(self.chunks)
            self._indexed = True
        return self._retriever.search(query, k, section)

    def sections(self) -> dict[str, int]:
        """Section name -> number of indexed documents (empty sections included)."""
        counts = Counter(d.section for d in self.documents)
        if self.root.is_dir():
            for child in self.root.iterdir():
                if child.is_dir() and child.name != "structured":
                    counts.setdefault(child.name, 0)
        return dict(sorted(counts.items()))

    def structured(self, name: str) -> dict | list:
        """Load a machine-readable table from knowledge_base/structured/<name>.yaml."""
        path = self.root / "structured" / f"{name}.yaml"
        if not path.exists():
            return {}
        with path.open() as fh:
            return yaml.safe_load(fh) or {}
