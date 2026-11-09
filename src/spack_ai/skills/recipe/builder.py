"""BuildSpec -> PackageRecipe: the deterministic first draft of a package."""

from __future__ import annotations

import re
from pathlib import Path

from spack_ai.naming import spack_package_name
from spack_ai.schemas import (
    BuildSpec,
    BuildSystem,
    DependsOn,
    DetectedDependency,
    PackageRecipe,
    Variant,
    VersionEntry,
)

LANGUAGE_DEPS = ("c", "cxx", "fortran")
MESON_FEATURE_VALUES = {"auto", "enabled", "disabled"}
# Makefile compiler variable -> (Spack compiler wrapper, MPI wrapper attribute)
MAKE_COMPILERS = {
    "CC": ("spack_cc", "mpicc"), "MPICC": ("spack_cc", "mpicc"),
    "CXX": ("spack_cxx", "mpicxx"), "MPICXX": ("spack_cxx", "mpicxx"),
    "FC": ("spack_fc", "mpifc"), "F90": ("spack_fc", "mpifc"), "MPIFC": ("spack_fc", "mpifc"),
    "F77": ("spack_f77", "mpif77"),
}


def recipe_from_build_spec(
    spec: BuildSpec,
    name: str | None = None,
    homepage: str | None = None,
    url: str | None = None,
    git: str | None = None,
    versions: list[VersionEntry] | None = None,
    description: str | None = None,
    maintainers: list[str] | None = None,
) -> PackageRecipe:
    is_python = spec.build_system == BuildSystem.PYTHON
    recipe = PackageRecipe(
        name=name or spack_package_name(spec.project_name or Path(spec.root).name, is_python),
        build_system=spec.build_system,
        description=description or spec.metadata.get("description", ""),
        homepage=homepage or spec.metadata.get("homepage"),
        url=url,
        git=git,
        maintainers=list(maintainers or []),
        has_install_target=spec.has_install_target,
        notes=list(spec.notes),
    )
    recipe.versions = versions or _default_versions(spec, git)
    _add_variants(recipe, spec)
    _add_language_deps(recipe, spec)
    _add_build_tool_deps(recipe, spec)
    _add_dependencies(recipe, spec)
    _add_build_args(recipe, spec)
    if spec.build_system == BuildSystem.MAKEFILE:
        _add_make_variables(recipe, spec)
    return recipe


def _default_versions(spec: BuildSpec, git: str | None) -> list[VersionEntry]:
    versions = []
    if spec.version:
        versions.append(VersionEntry(version=spec.version))  # sha256 left to `spack checksum`
    if git:
        versions.append(VersionEntry(version="main", branch="main"))
    return versions


def _add_variants(recipe: PackageRecipe, spec: BuildSpec) -> None:
    names: set[str] = set()
    for option in spec.options:
        if not option.variant or option.variant in names:
            continue
        flag_kind = option.kind
        default = option.default
        if option.kind == "meson" and isinstance(default, str) and default in MESON_FEATURE_VALUES:
            flag_kind, default = "meson_feature", default == "enabled"
        variant = Variant(
            name=option.variant,
            default=default if isinstance(default, bool) else False,
            description=_sentence(option.description) or f"Enable {option.variant}",
            build_flag=option.name,
            flag_kind=flag_kind,
        )
        if option.default is None:
            variant.comment = "FIXME: upstream default unknown"
        recipe.variants.append(variant)
        names.add(option.variant)

    if spec.build_system == BuildSystem.PYTHON:
        # Optional-dependency groups ("extras") become variants.
        for dep in spec.dependencies:
            extra = dep.condition
            if extra and not extra.startswith("marker:") and extra not in names:
                recipe.variants.append(
                    Variant(name=extra.replace("-", "_"),
                            description=f"Install the '{extra}' extra")
                )
                names.add(extra)


def _add_language_deps(recipe: PackageRecipe, spec: BuildSpec) -> None:
    if spec.build_system == BuildSystem.PYTHON and not (
        set(spec.languages) & set(LANGUAGE_DEPS)
    ):
        return
    for lang in LANGUAGE_DEPS:
        if lang in spec.languages:
            recipe.dependencies.append(DependsOn(spec=lang, type=["build"]))
    if "cuda" in spec.languages and not any(d.spack_name == "cuda" for d in spec.dependencies):
        recipe.dependencies.append(
            DependsOn(spec="cuda", comment="CUDA sources found; consider inheriting CudaPackage")
        )


def _add_build_tool_deps(recipe: PackageRecipe, spec: BuildSpec) -> None:
    tool = {BuildSystem.CMAKE: "cmake", BuildSystem.MESON: "meson"}.get(spec.build_system)
    if tool and spec.build_tool_version:
        recipe.dependencies.append(
            DependsOn(spec=f"{tool}@{spec.build_tool_version}", type=["build"])
        )
    if any(d.source == "pkg_config" for d in spec.dependencies):
        recipe.dependencies.append(DependsOn(spec="pkgconfig", type=["build"]))


def _add_dependencies(recipe: PackageRecipe, spec: BuildSpec) -> None:
    option_variants = {
        v.build_flag: v for v in recipe.variants if v.build_flag
    }
    by_key: dict[tuple[str, str | None], DependsOn] = {}
    for dep in spec.dependencies:
        if not dep.spack_spec:
            if not dep.resolved and dep.spack_name is None and dep.note is None:
                recipe.notes.append(f"Dependency '{dep.name}' was not mapped to a Spack package.")
            continue
        when = _when(dep, option_variants, recipe.variants)
        comment = dep.note
        if not dep.resolved:
            comment = f"FIXME: unverified mapping of upstream '{dep.name}'"
        elif not dep.required and when is None and dep.source in ("find_package", "pkg_config"):
            comment = "optional upstream (not REQUIRED); consider a variant" + (
                f". {comment}" if comment else ""
            )
        key = (_bare_name(dep.spack_spec), when)
        existing = by_key.get(key)
        if existing:
            if len(dep.spack_spec) > len(existing.spec):
                existing.spec = dep.spack_spec
            existing.type = sorted(set(existing.type) | set(dep.dep_types), key=_type_order)
            continue
        by_key[key] = DependsOn(spec=dep.spack_spec, type=list(dep.dep_types), when=when,
                                comment=comment)
    present = {_bare_name(d.spec) for d in recipe.dependencies}
    recipe.dependencies.extend(d for d in by_key.values() if _bare_name(d.spec) not in present or
                               d.when is not None)


def _when(dep: DetectedDependency, option_variants: dict[str, Variant],
          variants: list[Variant]) -> str | None:
    parts: list[str] = []
    if dep.condition and not dep.condition.startswith("marker:"):
        negate = False
        for token in re.findall(r"[A-Za-z_][A-Za-z0-9_.-]*|\(|\)", dep.condition):
            upper = token.upper()
            if upper == "NOT":
                negate = True
                continue
            if token in ("(", ")"):
                continue
            if token in option_variants:
                parts.append(("~" if negate else "+") + option_variants[token].name)
            elif upper in ("WIN32", "MSVC") and not negate:
                parts.append("platform=windows")
            elif upper == "APPLE" and not negate:
                parts.append("platform=darwin")
            elif dep.source == "python_requirement" and token.replace("-", "_") in {
                v.name for v in variants
            }:
                parts.append("+" + token.replace("-", "_"))
            negate = False
    if not parts:
        # Name-based match: AC_ARG_WITH([hdf5]) + AC_CHECK_LIB([hdf5]), USE_FFTW + -lfftw3, ...
        spack_name = dep.spack_name or ""
        candidates = {dep.name.lower(), spack_name, spack_name.removeprefix("py-"),
                      spack_name.removesuffix("-api")}
        for variant in variants:
            optional_kind = variant.flag_kind in ("with", "enable", "make_var", "meson",
                                                  "meson_feature")
            if (not dep.required or optional_kind) and variant.name in candidates:
                parts.append(f"+{variant.name}")
                break
    return " ".join(dict.fromkeys(parts)) or None


def _add_build_args(recipe: PackageRecipe, spec: BuildSpec) -> None:
    if spec.build_system == BuildSystem.CMAKE:
        if spec.metadata.get("testing") or any(o.name == "BUILD_TESTING" for o in spec.options):
            recipe.extra_build_args.append('self.define("BUILD_TESTING", self.run_tests)')
        if spec.metadata.get("downloaded_at_configure_time"):
            recipe.extra_build_args.append(
                'self.define("FETCHCONTENT_TRY_FIND_PACKAGE_MODE", "ALWAYS")'
            )


def _add_make_variables(recipe: PackageRecipe, spec: BuildSpec) -> None:
    uses_mpi = any(d.spack_name == "mpi" for d in spec.dependencies)
    for var, value in spec.metadata.get("compiler_variables", {}).items():
        if var not in MAKE_COMPILERS:
            continue
        wrapper, mpi_attr = MAKE_COMPILERS[var]
        is_mpi_wrapper = value.split()[0].startswith("mpi") if value else False
        recipe.make_variables[var] = (
            f"spec['mpi'].{mpi_attr}" if uses_mpi and (is_mpi_wrapper or var.startswith("MPI"))
            else wrapper
        )
    if prefix_var := spec.metadata.get("prefix_variable"):
        recipe.make_variables[prefix_var] = "prefix"
    if recipe.make_variables:
        # edit() now injects the compilers; the analysis note is resolved.
        recipe.notes = [n for n in recipe.notes if not n.startswith("Compilers are hard-coded")]


def _bare_name(spec: str) -> str:
    return re.split(r"[@+~%^ ]", spec, maxsplit=1)[0]


def _type_order(t: str) -> int:
    return ["build", "link", "run", "test"].index(t)


def _sentence(text: str) -> str:
    text = " ".join(text.split()).rstrip(".")
    return text[:1].upper() + text[1:] if text else ""
