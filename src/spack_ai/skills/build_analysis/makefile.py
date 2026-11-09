"""Hand-written Makefiles (GNU make)."""

from __future__ import annotations

import re
from pathlib import Path

from spack_ai.schemas import BuildOption, BuildSpec, BuildSystem, DetectedDependency
from spack_ai.skills.build_analysis.base import Analyzer, parse_bool, variant_name

MAKEFILE_NAMES = ("GNUmakefile", "Makefile", "makefile")
COMPILER_VARS = {"CC": "c", "CXX": "cxx", "FC": "fortran", "F77": "fortran", "F90": "fortran",
                 "MPICC": "c", "MPICXX": "cxx", "MPIFC": "fortran", "NVCC": "cuda"}
PREFIX_VARS = ("PREFIX", "prefix", "INSTALL_DIR", "INSTALLDIR", "DESTDIR", "INSTALL_PREFIX")
MPI_WRAPPERS = {"mpicc", "mpicxx", "mpic++", "mpiCC", "mpif77", "mpif90", "mpifort", "mpiicc",
                "mpiicpc", "mpiifort", "cc", "CC", "ftn"}
LANG_BY_COMPILER = {
    "gcc": "c", "clang": "c", "icc": "c", "icx": "c", "mpicc": "c", "mpiicc": "c",
    "g++": "cxx", "c++": "cxx", "clang++": "cxx", "icpc": "cxx", "icpx": "cxx", "mpicxx": "cxx",
    "mpic++": "cxx", "mpiCC": "cxx", "mpiicpc": "cxx",
    "gfortran": "fortran", "ifort": "fortran", "ifx": "fortran", "flang": "fortran",
    "mpif90": "fortran", "mpif77": "fortran", "mpifort": "fortran", "mpiifort": "fortran",
    "nvcc": "cuda",
}
FLAG_OPTION = re.compile(r"^(USE|WITH|ENABLE|HAVE|BUILD)_\w+$|^\w+_SUPPORT$")
_ASSIGN = re.compile(
    r"^(?:override\s+|export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*(\?=|:=|::=|\+=|!=|=)\s*(.*)$"
)
_TARGET = re.compile(r"^([^\s:=#][^:=#]*?)\s*::?(?!=)(.*)$")
_LIB_FLAG = re.compile(r"(?<![\w$(])-l([A-Za-z0-9_+.-]+)")
_PKG_CONFIG = re.compile(r"pkg-config\s+((?:--[\w-]+\s+)*)([\w.+\s-]+?)\s*\)")


class MakefileAnalyzer(Analyzer):
    build_system = BuildSystem.MAKEFILE
    markers = MAKEFILE_NAMES
    priority = 50

    @classmethod
    def claims_file(cls, path: Path) -> bool:
        return path.name in MAKEFILE_NAMES or path.suffix in (".mk", ".make")

    def discover(self, root: Path) -> list[Path]:
        for name in MAKEFILE_NAMES:
            if (root / name).exists():
                main = root / name
                extras = sorted(p for p in root.glob("*.mk")) + sorted(root.glob("make.inc*"))
                return [main, *extras]
        return []

    def analyze(self, root: Path, files: list[Path]) -> BuildSpec:
        spec = BuildSpec(root=str(root), build_system=self.build_system,
                         project_name=root.name if root.is_dir() else None)
        variables: dict[str, str] = {}
        targets: set[str] = set()
        includes: list[str] = []

        for path in files:
            conditions: list[str] = []
            for line_no, line in _logical_lines(path.read_text(errors="replace")):
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                if line.startswith("\t"):  # recipe line
                    self._scan_flags(spec, stripped, conditions, path.name, line_no)
                    continue
                directive = stripped.split(None, 1)
                keyword = directive[0]
                if keyword in ("ifeq", "ifneq", "ifdef", "ifndef"):
                    conditions.append(self._condition(spec, keyword, stripped, variables))
                elif keyword == "else" and conditions:
                    conditions[-1] = _negate(conditions[-1])
                elif keyword == "endif" and conditions:
                    conditions.pop()
                elif keyword in ("include", "-include", "sinclude") and len(directive) > 1:
                    includes.extend(directive[1].split())
                elif match := _ASSIGN.match(stripped):
                    name, _, value = match.groups()
                    variables.setdefault(name, value.strip())
                    self._assignment(spec, name, value.strip(), conditions, path.name, line_no)
                elif match := _TARGET.match(stripped):
                    targets.update(t for t in match.group(1).split() if "%" not in t)

        compilers = {k: v for k, v in variables.items() if k in COMPILER_VARS}
        prefix_var = next((v for v in PREFIX_VARS if v in variables), None)
        spec.metadata.update(
            {
                "targets": sorted(t for t in targets if not t.startswith(".")),
                "compiler_variables": compilers,
                "prefix_variable": prefix_var,
            }
        )
        spec.has_install_target = "install" in targets
        if includes:
            spec.metadata["includes"] = includes
            spec.notes.append(
                f"Makefile includes {', '.join(includes)}: the recipe usually has to write "
                "this file in edit() with Spack's compilers and dependency paths."
            )
        if compilers:
            spec.notes.append(
                "Compilers are hard-coded (" + ", ".join(f"{k}={v}" for k, v in compilers.items())
                + "): override them in edit() with spack_cc/spack_cxx/spack_fc or the MPI wrappers."
            )
        if not spec.has_install_target:
            spec.notes.append(
                "No install target: the recipe needs an install() method that copies binaries, "
                "libraries and headers into prefix."
            )
        elif not prefix_var:
            spec.notes.append(
                "install target found but no PREFIX-like variable: check where it installs and "
                "patch it to honor Spack's prefix."
            )
        if not spec.languages:
            for value in compilers.values():
                lang = LANG_BY_COMPILER.get(Path(value.split()[0]).name) if value else None
                if lang:
                    spec.add_language(lang)
        return spec

    def _condition(self, spec, keyword: str, line: str, variables: dict[str, str]) -> str:
        names = re.findall(r"\$[({]([A-Za-z_]\w*)[)}]", line)
        if keyword in ("ifdef", "ifndef"):
            names = line.split()[1:2]
        for name in names:
            if FLAG_OPTION.match(name):
                spec.add_option(
                    BuildOption(
                        name=name,
                        kind="make_var",
                        default=parse_bool(variables.get(name)),
                        variant=variant_name(name),
                    )
                )
        guard = names[0] if names else line
        return _negate(guard) if keyword in ("ifndef", "ifneq") else guard

    def _assignment(self, spec, name: str, value: str, conditions, file: str, line: int) -> None:
        if name in COMPILER_VARS and value:
            exe = Path(value.split()[0]).name
            if exe in MPI_WRAPPERS and exe not in ("cc", "CC"):
                spec.add_dependency(
                    DetectedDependency(name="MPI", source="program", file=file, line=line,
                                       condition=_join(conditions))
                )
            if exe == "nvcc":
                spec.add_dependency(
                    DetectedDependency(name="CUDA", source="program", file=file, line=line,
                                       condition=_join(conditions))
                )
            if lang := LANG_BY_COMPILER.get(exe):
                spec.add_language(lang)
        if FLAG_OPTION.match(name) and not conditions:
            spec.add_option(
                BuildOption(name=name, kind="make_var", default=parse_bool(value),
                            variant=variant_name(name))
            )
        self._scan_flags(spec, value, conditions, file, line)

    def _scan_flags(self, spec, text: str, conditions, file: str, line: int) -> None:
        for lib in _LIB_FLAG.findall(text):
            spec.add_dependency(
                DetectedDependency(name=lib, source="library", condition=_join(conditions),
                                   file=file, line=line)
            )
        for _, modules in _PKG_CONFIG.findall(text):
            for module in modules.split():
                spec.add_dependency(
                    DetectedDependency(name=module, source="pkg_config",
                                       condition=_join(conditions), file=file, line=line)
                )


def _logical_lines(text: str):
    """Join backslash continuations; yield (first line number, logical line)."""
    buffer: list[str] = []
    start = 1
    for number, raw in enumerate(text.splitlines(), 1):
        if not buffer:
            start = number
        if raw.endswith("\\"):
            buffer.append(raw[:-1])
            continue
        buffer.append(raw)
        yield start, " ".join(buffer) if len(buffer) > 1 else buffer[0]
        buffer = []
    if buffer:
        yield start, " ".join(buffer)


def _negate(condition: str) -> str:
    return condition[4:] if condition.startswith("NOT ") else f"NOT {condition}"


def _join(conditions: list[str]) -> str | None:
    return " AND ".join(conditions) if conditions else None
