"""Split documents into retrievable chunks that keep their heading context."""

from __future__ import annotations

import re
from dataclasses import dataclass

from spack_ai.knowledge.loader import Document

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")


@dataclass
class Chunk:
    id: str
    path: str
    section: str
    heading: str
    text: str


def _windows(text: str, size: int, overlap: int) -> list[str]:
    """Pack paragraphs into windows of about `size` characters."""
    paragraphs = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    step = max(size - overlap, size // 2, 1)
    windows: list[str] = []
    current = ""
    for para in paragraphs:
        if current and len(current) + len(para) > size:
            windows.append(current)
            current = current[-overlap:] if overlap else ""
        while len(para) > size:  # a single huge paragraph or code block
            windows.append(f"{current}\n\n{para[:size]}".strip())
            para = para[step:]
            current = ""
        current = f"{current}\n\n{para}" if current else para
    if current.strip():
        windows.append(current)
    return [w.strip() for w in windows]


def _markdown_sections(doc: Document) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    trail: list[str] = []
    buffer: list[str] = []

    def flush() -> None:
        body = "\n".join(buffer).strip()
        if body:
            sections.append((" > ".join(trail) or doc.title, body))
        buffer.clear()

    in_fence = False
    for line in doc.text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        match = None if in_fence else _HEADING.match(line)
        if match:
            flush()
            level = len(match.group(1))
            trail[:] = trail[: level - 1] + [match.group(2).strip()]
        else:
            buffer.append(line)
    flush()
    return sections


def chunk_document(doc: Document, size: int = 1500, overlap: int = 200) -> list[Chunk]:
    parts = _markdown_sections(doc) if doc.kind == "markdown" else [(doc.title, doc.text)]
    chunks: list[Chunk] = []
    for heading, body in parts:
        for window in _windows(body, size, overlap):
            chunks.append(
                Chunk(
                    id=f"{doc.path}#{len(chunks)}",
                    path=doc.path,
                    section=doc.section,
                    heading=heading,
                    text=window,
                )
            )
    return chunks
