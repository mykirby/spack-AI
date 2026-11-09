"""GNU Autotools: configure.ac / configure.in (and a shipped configure script)."""

from __future__ import annotations

import re
from pathlib import Path

from spack_ai.naming import clean_version, minimum_version_range, pep440_to_spack
from spack_ai.schemas import BuildOption, BuildSpec, BuildSystem, DetectedDependency
from spack_ai.skills.build_analysis.base import Analyzer
from spack_ai.skills.build_analysis.parsing import iter_m4_macros, split_top_level, unquote_m4

LANGUAGE_MACROS = {
    "AC_PROG_CC": "c", "AC_PROG_CC_C99": "c", "AC_PROG_CXX": "cxx",
    "AC_PROG_FC": "fortran", "AC_PROG_F77": "fortran",
}
# Autoconf-archive macros that look up a well-known dependency: macro -> upstream name.
LOOKUP_MACROS = {
    "AX_MPI": "MPI", "ACX_MPI": "MPI", "AX_PROG_CC_MPI": "MPI", "AX_PROG_CXX_MPI": "MPI",
    "AX_PROG_FC_MPI": "MPI", "AX_BLAS": "BLAS", "ACX_BLAS": "BLAS", "AX_LAPACK": "LAPACK",
    "ACX_LAPACK": "LAPACK", "AX_BOOST_BASE": "Boost", "AX_LIB_HDF5": "HDF5",
    "AX_LIB_NETCDF4": "netCDF", "AX_PATH_GSL": "GSL", "AM_PATH_PYTHON": "Python",
    "AX_PYTHON_DEVEL": "Python", "AC_PROG_LEX": "FLEX", "AC_PROG_YACC": "BISON",
    "AX_PROG_FLEX": "FLEX", "AX_PROG_BISON": "BISON", "AX_LIB_SQLITE3": "SQLite3",
    "AX_CHECK_ZLIB": "ZLIB", "AX_CHECK_OPENSSL": "OpenSSL", "AX_LIB_CURL": "CURL",
}


class AutotoolsAnalyzer(Analyzer):
    build_system = BuildSystem.AUTOTOOLS
    markers = ("configure.ac", "configure.in", "configure")
    priority = 30

    def discover(self, root: Path) -> list[Path]:
        for name in ("configure.ac", "configure.in"):
            if (root / name).exists():
                return [root / name]
        return []

    def analyze(self, root: Path, files: list[Path]) -> BuildSpec:
        spec = BuildSpec(root=str(root), build_system=self.build_system)
        uses_automake = uses_libtool = False

        if not files:
            spec.notes.append(
                "Only a generated configure script is present; options were not parsed. "
                "Run `./configure --help` to list them."
            )
        for path in files:
            for macro, args, line in iter_m4_macros(path.read_text(errors="replace")):
                rel = path.name
                if macro == "AC_INIT" and args:
                    spec.project_name = args[3] if len(args) > 3 and args[3] else args[0]
                    spec.version = clean_version(args[1]) if len(args) > 1 else None
                    if len(args) > 4 and args[4]:
                        spec.metadata["homepage"] = args[4]
                elif macro == "AC_PREREQ" and args:
                    spec.build_tool_version = minimum_version_range(args[0])
                elif macro in LANGUAGE_MACROS:
                    spec.add_language(LANGUAGE_MACROS[macro])
                elif macro == "AM_INIT_AUTOMAKE":
                    uses_automake = True
                elif macro in ("LT_INIT", "AC_PROG_LIBTOOL", "AM_PROG_LIBTOOL"):
                    uses_libtool = True
                elif macro in ("AC_OPENMP", "AX_OPENMP"):
                    spec.metadata["openmp"] = True
                elif macro == "AC_CHECK_LIB" and args:
                    self._library(spec, args[0], rel, line)
                elif macro == "AC_SEARCH_LIBS" and len(args) > 1:
                    for lib in args[1].split():
                        self._library(spec, lib, rel, line)
                elif macro == "PKG_CHECK_MODULES" and len(args) > 1:
                    self._pkg_config(spec, args[1], rel, line)
                elif macro in ("AC_ARG_ENABLE", "AC_ARG_WITH") and args:
                    self._option(spec, macro, args)
                elif macro in LOOKUP_MACROS or macro.startswith("AX_BOOST_"):
                    self._lookup_macro(spec, macro, args, rel, line)

        if not (root / "configure").exists():
            spec.metadata["needs_autoreconf"] = True
            spec.notes.append(
                "No configure script is shipped, so Spack runs autoreconf; the Autotools "
                "build dependencies were added. Prefer a release tarball that ships configure."
            )
            tools = ["autoconf", "m4"]
            if uses_automake:
                tools.append("automake")
            if uses_libtool:
                tools.append("libtool")
            for tool in tools:
                spec.add_dependency(
                    DetectedDependency(
                        name=tool, source="build_tool", spack_name=tool, spack_spec=tool,
                        dep_types=["build"], resolved=True,
                    )
                )
        spec.has_install_target = True if uses_automake else None
        if not spec.languages:
            spec.languages = ["c"]
        return spec

    def _library(self, spec: BuildSpec, lib: str, file: str, line: int) -> None:
        lib = unquote_m4(lib)
        if lib and not lib.startswith("$"):
            spec.add_dependency(
                DetectedDependency(name=lib, source="library", file=file, line=line)
            )

    def _pkg_config(self, spec: BuildSpec, modules: str, file: str, line: int) -> None:
        # "glib-2.0 >= 2.56 gio-2.0" -> [("glib-2.0", ">=2.56"), ("gio-2.0", None)]
        tokens = unquote_m4(modules).replace(",", " ").split()
        i = 0
        while i < len(tokens):
            name, constraint = tokens[i], None
            if i + 2 < len(tokens) and tokens[i + 1] in (">=", "<=", "=", "<", ">"):
                constraint = pep440_to_spack(tokens[i + 1] + tokens[i + 2])
                i += 2
            i += 1
            spec.add_dependency(
                DetectedDependency(
                    name=name, source="pkg_config", version_constraint=constraint,
                    file=file, line=line,
                )
            )

    def _option(self, spec: BuildSpec, macro: str, args: list[str]) -> None:
        name = args[0]
        description = ""
        if len(args) > 1:
            help_args = re.search(r"AS_HELP_STRING\((.*)\)", args[1], re.S)
            if help_args:
                parts = split_top_level(help_args.group(1), ",", "")
                description = unquote_m4(parts[1]) if len(parts) > 1 else ""
            else:
                description = re.sub(r"^\s*--\S+\s*", "", args[1])
        spec.add_option(
            BuildOption(
                name=name,
                kind="enable" if macro == "AC_ARG_ENABLE" else "with",
                description=" ".join(description.split()),
                variant=name.replace("-", "_"),
            )
        )

    def _lookup_macro(self, spec, macro: str, args: list[str], file: str, line: int) -> None:
        if macro.startswith("AX_BOOST_") and macro != "AX_BOOST_BASE":
            name, components = "Boost", [macro.removeprefix("AX_BOOST_").lower()]
        else:
            name, components = LOOKUP_MACROS[macro], []
        version = None
        if macro == "AX_BOOST_BASE" and args:
            version = minimum_version_range(args[0])
        spec.add_dependency(
            DetectedDependency(
                name=name, source="macro", version_constraint=version, components=components,
                file=file, line=line,
            )
        )
