"""Read documents from the knowledge_base/ directory tree.

Each top-level directory is a *section* (spack_fundamentals, build_systems, ...).
README.md files describe what belongs in a section and are not indexed;
knowledge_base/structured/ holds machine-readable tables that skills load directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

TEXT_SUFFIXES = {".md", ".txt", ".rst", ".py", ".yaml", ".yml", ".cmake", ".sh", ".json", ".toml"}
TEXT_NAMES = {"CMakeLists.txt", "Makefile", "configure.ac", "meson.build", "package.py"}
SKIP_NAMES = {"README.md"}
SKIP_SECTIONS = {"structured"}
MAX_BYTES = 2_000_000


@dataclass
class Document:
    path: str  # relative to the knowledge base root
    section: str
    title: str
    text: str
    kind: str  # "markdown" | "code" | "text"


def _kind(path: Path) -> str:
    if path.suffix in {".md", ".rst", ".txt"} and path.name not in TEXT_NAMES:
        return "markdown"
    if path.suffix in {".py", ".cmake", ".sh", ".yaml", ".yml", ".json", ".toml"} or (
        path.name in TEXT_NAMES
    ):
        return "code"
    return "text"


def _title(path: Path, text: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem.replace("_", " ").replace("-", " ")


def load_documents(root: Path) -> list[Document]:
    if not root.is_dir():
        return []
    docs: list[Document] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name in SKIP_NAMES or path.name.startswith("."):
            continue
        rel = path.relative_to(root)
        section = rel.parts[0] if len(rel.parts) > 1 else "general"
        if section in SKIP_SECTIONS:
            continue
        if path.suffix not in TEXT_SUFFIXES and path.name not in TEXT_NAMES:
            continue
        if path.stat().st_size > MAX_BYTES:
            continue
        text = path.read_text(errors="replace")
        docs.append(
            Document(
                path=str(rel),
                section=section,
                title=_title(path, text),
                text=text,
                kind=_kind(path),
            )
        )
    return docs
