"""Meson: meson.build and meson.options / meson_options.txt."""

from __future__ import annotations

import re
from pathlib import Path

from spack_ai.naming import minimum_version_range, pep440_to_spack
from spack_ai.schemas import BuildOption, BuildSpec, BuildSystem, DetectedDependency
from spack_ai.skills.build_analysis.base import Analyzer, parse_bool, walk_files
from spack_ai.skills.build_analysis.parsing import iter_meson_calls, meson_string, meson_strings

MESON_LANGUAGES = {"c": "c", "cpp": "cxx", "fortran": "fortran", "cuda": "cuda"}
NO_DEPENDENCY = {"threads", "dl", "openmp", ""}


class MesonAnalyzer(Analyzer):
    build_system = BuildSystem.MESON
    markers = ("meson.build",)
    priority = 20

    @classmethod
    def claims_file(cls, path: Path) -> bool:
        return path.name in ("meson.build", "meson.options", "meson_options.txt")

    def discover(self, root: Path) -> list[Path]:
        builds = walk_files(root, lambda p: p.name == "meson.build")
        top = root / "meson.build"
        ordered = [top, *(b for b in builds if b != top)] if top.exists() else builds
        options = [root / n for n in ("meson.options", "meson_options.txt") if (root / n).exists()]
        return ordered + options

    def analyze(self, root: Path, files: list[Path]) -> BuildSpec:
        spec = BuildSpec(root=str(root), build_system=self.build_system)
        for path in files:
            rel = path.name
            for name, args, kwargs, line in iter_meson_calls(path.read_text(errors="replace")):
                if name == "project" and args and spec.project_name is None:
                    spec.project_name = meson_string(args[0])
                    for value in args[1:]:
                        for lang in meson_strings(value):
                            if lang in MESON_LANGUAGES:
                                spec.add_language(MESON_LANGUAGES[lang])
                    if "version" in kwargs:
                        spec.version = meson_string(kwargs["version"])
                    if "meson_version" in kwargs:
                        raw = meson_string(kwargs["meson_version"]) or ""
                        spec.build_tool_version = pep440_to_spack(raw.replace(" ", ""))
                elif name == "add_languages":
                    for value in args:
                        for lang in meson_strings(value):
                            if lang in MESON_LANGUAGES:
                                spec.add_language(MESON_LANGUAGES[lang])
                elif name == "dependency" and args:
                    self._dependency(spec, args, kwargs, rel, line)
                elif name == "option" and args:
                    self._option(spec, args, kwargs)
        return spec

    def _dependency(self, spec, args, kwargs, file, line) -> None:
        dep = meson_string(args[0])
        if dep is None or dep in NO_DEPENDENCY:
            if dep == "openmp":
                spec.metadata["openmp"] = True
            return
        required_raw = kwargs.get("required", "true").strip()
        condition = None
        if option := re.search(r"get_option\(\s*'([^']+)'\s*\)", required_raw):
            condition = option.group(1)
        version = None
        if "version" in kwargs:
            raw = (meson_strings(kwargs["version"]) or [""])[0].replace(" ", "")
            version = pep440_to_spack(raw) or minimum_version_range(raw.lstrip(">="))
        spec.add_dependency(
            DetectedDependency(
                name=dep,
                source="meson_dependency",
                required=parse_bool(required_raw) is not False and condition is None,
                version_constraint=version,
                components=meson_strings(kwargs.get("modules", "")),
                condition=condition,
                file=file,
                line=line,
            )
        )

    def _option(self, spec, args, kwargs) -> None:
        name = meson_string(args[0])
        if not name:
            return
        default = meson_string(kwargs.get("value", "")) or kwargs.get("value")
        if kwargs.get("type", "").strip("' ") == "boolean":
            default = parse_bool(default)
        spec.add_option(
            BuildOption(
                name=name,
                kind="meson",
                description=meson_string(kwargs.get("description", "")) or "",
                default=default,
                variant=name.replace("-", "_"),
            )
        )
