"""Retrieval backends.

`Retriever` is the extension point: BM25 works offline with no dependencies and is the
default. An embedding or hybrid retriever (e.g. backed by a vector store, or by the
project's own trained model) only needs to implement `index` and `search`.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Protocol

from spack_ai.knowledge.chunker import Chunk

_TOKEN = re.compile(r"[a-z0-9_+.-]+")


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for raw in _TOKEN.findall(text.lower()):
        token = raw.strip(".+-")
        if not token:
            continue
        tokens.append(token)
        # 'depends_on' also matches 'depends' and 'on'; 'netcdf-c' matches 'netcdf'.
        parts = [p for p in re.split(r"[_.+-]", token) if p]
        if len(parts) > 1:
            tokens.extend(parts)
    return tokens


@dataclass
class SearchHit:
    chunk: Chunk
    score: float


class Retriever(Protocol):
    def index(self, chunks: list[Chunk]) -> None: ...

    def search(self, query: str, k: int, section: str | None = None) -> list[SearchHit]: ...


class BM25Retriever:
    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.chunks: list[Chunk] = []
        self._tf: list[Counter[str]] = []
        self._lengths: list[int] = []
        self._idf: dict[str, float] = {}
        self._avg_len = 0.0

    def index(self, chunks: list[Chunk]) -> None:
        self.chunks = chunks
        self._tf = [Counter(tokenize(f"{c.heading}\n{c.text}")) for c in chunks]
        self._lengths = [sum(tf.values()) for tf in self._tf]
        self._avg_len = (sum(self._lengths) / len(self._lengths)) if chunks else 0.0
        df: Counter[str] = Counter()
        for tf in self._tf:
            df.update(tf.keys())
        n = len(chunks)
        self._idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def search(self, query: str, k: int, section: str | None = None) -> list[SearchHit]:
        terms = set(tokenize(query))
        hits: list[SearchHit] = []
        for i, chunk in enumerate(self.chunks):
            if section and chunk.section != section:
                continue
            tf = self._tf[i]
            norm = self.k1 * (1 - self.b + self.b * self._lengths[i] / (self._avg_len or 1))
            score = sum(
                self._idf[t] * tf[t] * (self.k1 + 1) / (tf[t] + norm) for t in terms if t in tf
            )
            if score > 0:
                hits.append(SearchHit(chunk, score))
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:k]
