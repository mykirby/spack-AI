"""Analyzer interface, detection, and helpers shared by every build system."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections import Counter
from pathlib import Path
from typing import ClassVar

from spack_ai.schemas import BuildSpec, BuildSystem

# Directories that usually hold bundled third-party code or build output.
SKIP_DIRS = {
    ".git", ".svn", ".hg", "build", "_build", "builds", "node_modules", "third_party",
    "thirdparty", "3rdparty", "extern", "external", "vendor", "deps", ".spack-env",
    "__pycache__", ".tox", ".venv", "venv", "spack-build",
}
MAX_FILES = 400

LANGUAGE_EXTENSIONS = {
    ".c": "c",
    ".cc": "cxx", ".cpp": "cxx", ".cxx": "cxx", ".c++": "cxx", ".hpp": "cxx", ".hh": "cxx",
    ".f": "fortran", ".for": "fortran", ".f77": "fortran", ".f90": "fortran",
    ".f95": "fortran", ".f03": "fortran", ".f08": "fortran",
    ".cu": "cuda", ".cuh": "cuda",
    ".hip": "hip",
}


class Analyzer(ABC):
    build_system: ClassVar[BuildSystem]
    # Files whose presence at the project root identifies this build system.
    markers: ClassVar[tuple[str, ...]]
    # Lower runs first when several markers are present (CMake beats a stray Makefile).
    priority: ClassVar[int]

    @classmethod
    def claims_file(cls, path: Path) -> bool:
        return path.name in cls.markers

    @abstractmethod
    def discover(self, root: Path) -> list[Path]:
        """Build files to read, most important first."""

    @abstractmethod
    def analyze(self, root: Path, files: list[Path]) -> BuildSpec: ...

    def run(self, root: Path, files: list[Path] | None = None) -> BuildSpec:
        files = files or self.discover(root)
        spec = self.analyze(root, files)
        spec.files_analyzed = [_rel(f, root) for f in files]
        if root.is_dir():
            for lang in source_languages(root):
                spec.add_language(lang)
            vendored = vendored_dirs(root)
            if vendored:
                spec.metadata["vendored_dirs"] = vendored
                spec.notes.append(
                    "Bundled third-party code in "
                    + ", ".join(vendored)
                    + ": prefer depends_on() on the Spack package and disable the bundled copy."
                )
        return spec


def _rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def walk_files(root: Path, predicate) -> list[Path]:
    """Files under root (skipping vendored/build dirs) that satisfy predicate, shallow first."""
    found: list[Path] = []
    stack = [root]
    while stack and len(found) < MAX_FILES:
        current = stack.pop(0)
        try:
            entries = sorted(current.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.is_dir():
                if entry.name not in SKIP_DIRS and not entry.name.startswith("."):
                    stack.append(entry)
            elif predicate(entry):
                found.append(entry)
    return found


def source_languages(root: Path) -> list[str]:
    counts: Counter[str] = Counter()
    for path in walk_files(root, lambda p: p.suffix.lower() in LANGUAGE_EXTENSIONS):
        counts[LANGUAGE_EXTENSIONS[path.suffix.lower()]] += 1
    return [lang for lang, _ in counts.most_common()]


def vendored_dirs(root: Path) -> list[str]:
    hits = []
    for name in ("third_party", "thirdparty", "3rdparty", "extern", "external", "vendor", "deps"):
        if (root / name).is_dir():
            hits.append(name)
    return hits


def variant_name(option: str, project: str | None = None) -> str | None:
    """Propose a Spack variant for an upstream option name.

    'ENABLE_MPI' -> 'mpi', 'MYPROJ_USE_CUDA' -> 'cuda', 'BUILD_SHARED_LIBS' -> 'shared'.
    Returns None for options Spack manages itself (BUILD_TESTING, CMAKE_*...).
    """
    upper = option.upper()
    if upper in IGNORED_OPTIONS or upper.startswith("CMAKE_"):
        return None
    if any(word in upper for word in NOISE_OPTION_WORDS):
        return None
    if upper == "BUILD_SHARED_LIBS":
        return "shared"
    name = upper
    if project:
        prefix = re.sub(r"[^A-Z0-9]", "_", project.upper()) + "_"
        if name.startswith(prefix):
            name = name[len(prefix) :]
    # 'ENABLE_MPI', and also a short project prefix like 'HEAT_ENABLE_MPI' -> 'MPI'
    name = re.sub(r"^(?:[A-Z][A-Z0-9]*_)?(ENABLE|USE|WITH|BUILD|HAVE)_", "", name)
    name = re.sub(r"_(SUPPORT|ENABLED)$", "", name)
    name = name.lower().strip("_")
    return name or None


IGNORED_OPTIONS = {"BUILD_TESTING"}
NOISE_OPTION_WORDS = (
    "WERROR", "WARNING", "COVERAGE", "SANITIZ", "CLANG_TIDY", "CPPCHECK", "IWYU", "CCACHE",
    "VERBOSE", "PEDANTIC", "LINT", "FORMAT",
)


def parse_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    lowered = value.strip().strip('"').lower()
    if lowered in {"on", "true", "yes", "1", "y", "enabled"}:
        return True
    if lowered in {"off", "false", "no", "0", "n", "", "disabled"}:
        return False
    return None
