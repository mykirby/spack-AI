"""Data models shared by skills, the agent, the evals, and the ML pipeline.

The flow through the system is:

    source tree --analyze--> BuildSpec --map--> BuildSpec (spack names filled in)
                --draft-->   PackageRecipe --render--> package.py
                             EnvironmentSpec --render--> spack.yaml
"""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

from spack_ai.naming import spack_class_name

DepType = Literal["build", "link", "run", "test"]


class BuildSystem(StrEnum):
    CMAKE = "cmake"
    AUTOTOOLS = "autotools"
    MAKEFILE = "makefile"
    MESON = "meson"
    PYTHON = "python"
    UNKNOWN = "unknown"

    @property
    def spack_base_class(self) -> str:
        return _BASE_CLASSES[self]

    @property
    def spack_module(self) -> str:
        """Module under spack_repo.builtin.build_systems that defines the base class."""
        return _BASE_MODULES[self]


_BASE_CLASSES = {
    BuildSystem.CMAKE: "CMakePackage",
    BuildSystem.AUTOTOOLS: "AutotoolsPackage",
    BuildSystem.MAKEFILE: "MakefilePackage",
    BuildSystem.MESON: "MesonPackage",
    BuildSystem.PYTHON: "PythonPackage",
    BuildSystem.UNKNOWN: "Package",
}

_BASE_MODULES = {
    BuildSystem.CMAKE: "cmake",
    BuildSystem.AUTOTOOLS: "autotools",
    BuildSystem.MAKEFILE: "makefile",
    BuildSystem.MESON: "meson",
    BuildSystem.PYTHON: "python",
    BuildSystem.UNKNOWN: "generic",
}


# --------------------------------------------------------------------------- analysis


class DetectedDependency(BaseModel):
    """A dependency as the upstream build system names it, plus its Spack resolution."""

    name: str = Field(description="Name as written upstream, e.g. 'HDF5', 'fftw3', 'glib-2.0'.")
    source: str = Field(
        description="How it was found: find_package, pkg_config, library, program, "
        "meson_dependency, python_requirement, macro."
    )
    required: bool = True
    version_constraint: str | None = Field(
        default=None, description="Spack-style range, e.g. '1.10:'."
    )
    components: list[str] = Field(default_factory=list)
    condition: str | None = Field(
        default=None, description="Upstream condition guarding the lookup, e.g. 'ENABLE_MPI'."
    )
    file: str | None = None
    line: int | None = None

    # Filled in by dependency mapping.
    spack_name: str | None = None
    spack_spec: str | None = None
    virtual: bool = False
    dep_types: list[DepType] = Field(default_factory=lambda: ["build", "link"])
    resolved: bool = False
    note: str | None = None


class BuildOption(BaseModel):
    """A user-facing build switch: CMake option(), --enable-/--with-, a Makefile flag."""

    name: str
    kind: Literal["cmake", "enable", "with", "make_var", "meson"]
    description: str = ""
    default: bool | str | None = None
    variant: str | None = Field(default=None, description="Proposed Spack variant name.")


class BuildSpec(BaseModel):
    """Everything the analyzers learned about a source tree."""

    root: str
    build_system: BuildSystem
    project_name: str | None = None
    version: str | None = None
    languages: list[str] = Field(default_factory=list)
    build_tool_version: str | None = Field(
        default=None, description="Minimum CMake/Meson/Autoconf version, Spack range syntax."
    )
    dependencies: list[DetectedDependency] = Field(default_factory=list)
    options: list[BuildOption] = Field(default_factory=list)
    files_analyzed: list[str] = Field(default_factory=list)
    has_install_target: bool | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)

    def add_dependency(self, dep: DetectedDependency) -> None:
        """Add a dependency, merging with an earlier detection of the same name."""
        for existing in self.dependencies:
            if existing.name.lower() == dep.name.lower() and existing.source == dep.source:
                existing.required = existing.required or dep.required
                existing.components = sorted(set(existing.components) | set(dep.components))
                existing.version_constraint = existing.version_constraint or dep.version_constraint
                if existing.condition != dep.condition:
                    # Found under two different guards (or one unguarded): treat as unconditional.
                    existing.condition = None
                return
        self.dependencies.append(dep)

    def add_option(self, option: BuildOption) -> None:
        if all(o.name != option.name for o in self.options):
            self.options.append(option)

    def add_language(self, language: str) -> None:
        if language not in self.languages:
            self.languages.append(language)


# --------------------------------------------------------------------------- recipes


class VersionEntry(BaseModel):
    version: str
    sha256: str | None = None
    url: str | None = None
    tag: str | None = None
    commit: str | None = None
    branch: str | None = None
    preferred: bool = False


class Variant(BaseModel):
    name: str
    default: bool | str = False
    description: str = ""
    values: list[str] | None = None
    multi: bool = False
    build_flag: str | None = Field(
        default=None, description="Upstream option this variant drives (BuildOption.name)."
    )
    flag_kind: str | None = None
    comment: str | None = None


class DependsOn(BaseModel):
    spec: str
    type: list[DepType] = Field(default_factory=lambda: ["build", "link"])
    when: str | None = None
    comment: str | None = None


class PackageRecipe(BaseModel):
    """Structured form of a package.py; rendered by skills.recipe.render."""

    name: str
    build_system: BuildSystem
    description: str = ""
    homepage: str | None = None
    url: str | None = None
    git: str | None = None
    license: str | None = None
    maintainers: list[str] = Field(default_factory=list)
    versions: list[VersionEntry] = Field(default_factory=list)
    variants: list[Variant] = Field(default_factory=list)
    dependencies: list[DependsOn] = Field(default_factory=list)
    extra_build_args: list[str] = Field(
        default_factory=list, description="Literal args appended in cmake_args/configure_args."
    )
    make_variables: dict[str, str] = Field(
        default_factory=dict, description="Makefile variables to rewrite in edit()."
    )
    has_install_target: bool | None = None
    notes: list[str] = Field(default_factory=list, description="Emitted as FIXME comments.")

    @property
    def class_name(self) -> str:
        return spack_class_name(self.name)

    @property
    def base_class(self) -> str:
        return self.build_system.spack_base_class


# --------------------------------------------------------------------------- environments


class EnvironmentSpec(BaseModel):
    """Structured form of a spack.yaml."""

    specs: list[str]
    view: bool | str = True
    unify: bool | Literal["when_possible"] = True
    repos: list[str] = Field(default_factory=list)
    packages: dict[str, Any] = Field(
        default_factory=dict, description="packages: section (externals, requirements)."
    )
    config: dict[str, Any] = Field(default_factory=dict)
    mirrors: dict[str, str] = Field(default_factory=dict)
    modules: dict[str, Any] = Field(default_factory=dict)


# --------------------------------------------------------------------------- skill I/O


class SkillResult(BaseModel):
    """What every skill returns. Serialized to JSON as the tool result the model reads."""

    summary: str
    data: Any = None
    files: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    def to_tool_content(self) -> str:
        payload = self.model_dump(mode="json", exclude_defaults=True)
        payload.setdefault("summary", self.summary)
        return json.dumps(payload, indent=2, default=str)
