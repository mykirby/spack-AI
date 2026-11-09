"""CMake: CMakeLists.txt and *.cmake modules."""

from __future__ import annotations

import re
from pathlib import Path

from spack_ai.naming import clean_version, minimum_version_range, pep440_to_spack
from spack_ai.schemas import BuildOption, BuildSpec, BuildSystem, DetectedDependency
from spack_ai.skills.build_analysis.base import Analyzer, parse_bool, variant_name, walk_files
from spack_ai.skills.build_analysis.parsing import iter_cmake_commands

CMAKE_LANGUAGES = {"C": "c", "CXX": "cxx", "FORTRAN": "fortran", "CUDA": "cuda", "HIP": "hip"}
PROJECT_KEYWORDS = {"VERSION", "LANGUAGES", "DESCRIPTION", "HOMEPAGE_URL"}
FIND_PACKAGE_KEYWORDS = {
    "EXACT", "QUIET", "REQUIRED", "COMPONENTS", "OPTIONAL_COMPONENTS", "CONFIG", "NO_MODULE",
    "MODULE", "GLOBAL", "NO_POLICY_SCOPE", "BYPASS_PROVIDER", "NAMES", "CONFIGS", "HINTS",
    "PATHS", "PATH_SUFFIXES", "REGISTRY_VIEW", "NO_DEFAULT_PATH", "NO_CMAKE_PATH",
    "NO_CMAKE_ENVIRONMENT_PATH", "NO_SYSTEM_ENVIRONMENT_PATH", "CMAKE_FIND_ROOT_PATH_BOTH",
}
PKG_CONFIG_KEYWORDS = {"REQUIRED", "QUIET", "IMPORTED_TARGET", "GLOBAL", "NO_CMAKE_PATH",
                       "NO_CMAKE_ENVIRONMENT_PATH"}
_PKG_MODULE = re.compile(r"^([A-Za-z0-9_.+-]+?)\s*(>=|<=|=|<|>)\s*([\w.]+)$")


class CMakeAnalyzer(Analyzer):
    build_system = BuildSystem.CMAKE
    markers = ("CMakeLists.txt",)
    priority = 10

    @classmethod
    def claims_file(cls, path: Path) -> bool:
        return path.name == "CMakeLists.txt" or path.suffix == ".cmake"

    def discover(self, root: Path) -> list[Path]:
        files = walk_files(
            root,
            lambda p: p.name == "CMakeLists.txt"
            or (p.suffix == ".cmake" and not p.name.startswith("Find")),
        )
        top = root / "CMakeLists.txt"
        return [top, *(f for f in files if f != top)] if top.exists() else files

    def analyze(self, root: Path, files: list[Path]) -> BuildSpec:
        spec = BuildSpec(root=str(root), build_system=self.build_system)
        if root.is_dir():
            finders = walk_files(root, lambda p: p.name.startswith("Find") and p.suffix == ".cmake")
            if finders:
                spec.metadata["bundled_find_modules"] = sorted(p.stem[4:] for p in finders)

        saw_project = False
        for path in files:
            text = path.read_text(errors="replace")
            rel = str(path.relative_to(root)) if path.is_relative_to(root) else str(path)
            conditions: list[str] = []
            for cmd, args, line in iter_cmake_commands(text):
                if cmd == "if":
                    conditions.append(" ".join(args))
                elif cmd == "elseif" and conditions:
                    conditions[-1] = " ".join(args)
                elif cmd == "else" and conditions:
                    conditions[-1] = f"NOT ({conditions[-1]})"
                elif cmd == "endif" and conditions:
                    conditions.pop()
                elif cmd == "project" and not saw_project and args:
                    self._project(spec, args)
                    saw_project = True
                elif cmd == "cmake_minimum_required":
                    self._minimum_required(spec, args)
                elif cmd in ("enable_language", "check_language"):
                    for arg in args:
                        if arg.upper() in CMAKE_LANGUAGES:
                            spec.add_language(CMAKE_LANGUAGES[arg.upper()])
                elif cmd == "find_package" and args:
                    self._find_package(spec, args, _guard(conditions), rel, line)
                elif cmd in ("pkg_check_modules", "pkg_search_module") and len(args) > 1:
                    self._pkg_config(spec, args, _guard(conditions), rel, line)
                elif cmd == "find_library" and len(args) > 1:
                    self._find_library(spec, args, _guard(conditions), rel, line)
                elif cmd in ("option", "cmake_dependent_option") and args:
                    self._option(spec, args)
                elif cmd in ("fetchcontent_declare", "externalproject_add") and args:
                    self._fetched(spec, cmd, args, rel, line)
                elif cmd == "set" and len(args) >= 2 and args[0] in (
                    "CMAKE_CXX_STANDARD", "CMAKE_C_STANDARD", "CMAKE_CUDA_STANDARD",
                ):
                    spec.metadata[args[0].lower()] = args[1]
                elif cmd == "install":
                    spec.has_install_target = True
                elif cmd == "enable_testing" or (cmd == "include" and args[:1] == ["CTest"]):
                    spec.metadata["testing"] = True

        if not saw_project:
            spec.notes.append("No project() call found; languages default to C and C++.")
        if not spec.languages:
            spec.languages = ["c", "cxx"]
        if spec.has_install_target is None:
            spec.has_install_target = False
            spec.notes.append(
                "No install() rules found: `make install` may install nothing. The recipe "
                "may need an install() override or a patch adding install rules."
            )
        return spec

    # -- commands -------------------------------------------------------------------

    def _project(self, spec: BuildSpec, args: list[str]) -> None:
        spec.project_name = args[0]
        keyword = None
        languages: list[str] = []
        explicit_none = False
        for arg in args[1:]:
            upper = arg.upper()
            if upper in PROJECT_KEYWORDS:
                keyword = upper
            elif keyword == "VERSION":
                spec.version = clean_version(arg) or spec.version
            elif keyword == "DESCRIPTION":
                spec.metadata["description"] = arg
            elif keyword == "HOMEPAGE_URL":
                spec.metadata["homepage"] = arg
            elif keyword in ("LANGUAGES", None) and upper in CMAKE_LANGUAGES:
                languages.append(CMAKE_LANGUAGES[upper])
            elif keyword in ("LANGUAGES", None) and upper == "NONE":
                explicit_none = True
        if not languages and not explicit_none:
            languages = ["c", "cxx"]  # CMake's default when LANGUAGES is omitted
        for lang in languages:
            spec.add_language(lang)

    def _minimum_required(self, spec: BuildSpec, args: list[str]) -> None:
        if "VERSION" in args:
            raw = args[args.index("VERSION") + 1] if len(args) > args.index("VERSION") + 1 else ""
            spec.build_tool_version = minimum_version_range(raw.split("...")[0])

    def _find_package(self, spec, args, condition, file, line) -> None:
        name = args[0]
        if name.startswith("$"):
            return
        version = None
        required = False
        components: list[str] = []
        mode = None
        for arg in args[1:]:
            upper = arg.upper()
            if upper == "REQUIRED":
                required, mode = True, "components"
            elif upper == "COMPONENTS":
                mode = "components"
            elif upper == "OPTIONAL_COMPONENTS":
                mode = "optional"
            elif upper in FIND_PACKAGE_KEYWORDS:
                mode = "skip"
            elif mode == "components":
                components.append(arg)
            elif mode is None and version is None and re.match(r"^\d", arg):
                version = arg.split("...")[0]
        spec.add_dependency(
            DetectedDependency(
                name=name,
                source="find_package",
                required=required,
                version_constraint=minimum_version_range(version),
                components=components,
                condition=condition,
                file=file,
                line=line,
            )
        )

    def _pkg_config(self, spec, args, condition, file, line) -> None:
        required = "REQUIRED" in (a.upper() for a in args[1:])
        modules = [a for a in args[1:] if a.upper() not in PKG_CONFIG_KEYWORDS]
        for module in _join_operators(modules):
            name, constraint = module, None
            if match := _PKG_MODULE.match(module):
                name, constraint = match.group(1), pep440_to_spack(match.group(2) + match.group(3))
            spec.add_dependency(
                DetectedDependency(
                    name=name,
                    source="pkg_config",
                    required=required,
                    version_constraint=constraint,
                    condition=condition,
                    file=file,
                    line=line,
                )
            )

    def _find_library(self, spec, args, condition, file, line) -> None:
        names = args[args.index("NAMES") + 1 :] if "NAMES" in args else args[1:2]
        name = next((n for n in names if not n.startswith("$") and n.upper() not in
                     FIND_PACKAGE_KEYWORDS), None)
        if name:
            spec.add_dependency(
                DetectedDependency(
                    name=name.removeprefix("lib"),
                    source="library",
                    required="REQUIRED" in args,
                    condition=condition,
                    file=file,
                    line=line,
                )
            )

    def _option(self, spec: BuildSpec, args: list[str]) -> None:
        name = args[0]
        description = args[1] if len(args) > 1 else ""
        default = parse_bool(args[2]) if len(args) > 2 else False
        spec.add_option(
            BuildOption(
                name=name,
                kind="cmake",
                description=description,
                default=default,
                variant=variant_name(name, spec.project_name),
            )
        )

    def _fetched(self, spec, cmd, args, file, line) -> None:
        name = args[0]
        url = None
        for key in ("GIT_REPOSITORY", "URL"):
            if key in args and args.index(key) + 1 < len(args):
                url = args[args.index(key) + 1]
        spec.metadata.setdefault("downloaded_at_configure_time", []).append(
            {"name": name, "via": cmd, "url": url}
        )
        spec.add_dependency(
            DetectedDependency(name=name, source="fetchcontent", file=file, line=line)
        )
        note = (
            "Dependencies are downloaded at configure time (FetchContent/ExternalProject). "
            "Compute nodes are often offline: add depends_on() for them and set "
            "FETCHCONTENT_TRY_FIND_PACKAGE_MODE=ALWAYS or FETCHCONTENT_FULLY_DISCONNECTED=ON."
        )
        if note not in spec.notes:
            spec.notes.append(note)


def _guard(conditions: list[str]) -> str | None:
    return " AND ".join(f"({c})" if " " in c else c for c in conditions) if conditions else None


def _join_operators(tokens: list[str]) -> list[str]:
    """Re-attach 'glib-2.0 >= 2.56' written as three tokens."""
    joined: list[str] = []
    i = 0
    while i < len(tokens):
        if i + 2 < len(tokens) and tokens[i + 1] in (">=", "<=", "=", "<", ">"):
            joined.append(f"{tokens[i]}{tokens[i + 1]}{tokens[i + 2]}")
            i += 3
        else:
            joined.append(tokens[i])
            i += 1
    return joined
