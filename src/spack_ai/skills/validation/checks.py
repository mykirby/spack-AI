"""Static checks on package.py source. No Spack installation required."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from spack_ai.naming import spack_class_name
from spack_ai.recipe_ast import summarize

KNOWN_BASES = {
    "Package", "BundlePackage", "CMakePackage", "AutotoolsPackage", "MakefilePackage",
    "MesonPackage", "PythonPackage", "PerlPackage", "RPackage", "CudaPackage", "ROCmPackage",
    "SConsPackage", "WafPackage", "QMakePackage", "SIPPackage", "GoPackage", "CargoPackage",
    "MavenPackage", "LuaPackage", "OctavePackage", "RubyPackage", "IntelPackage",
    "BazelPackage", "NMakePackage", "MSBuildPackage", "CompilerPackage",
}
# Variants a recipe inherits from its base classes.
INHERITED_VARIANTS = {
    "CMakePackage": {"build_type", "generator", "ipo"},
    "MesonPackage": {"buildtype", "default_library", "strip"},
    "CudaPackage": {"cuda", "cuda_arch"},
    "ROCmPackage": {"rocm", "amdgpu_target"},
    "PythonPackage": set(),
}
COMPILED_BASES = {"CMakePackage", "AutotoolsPackage", "MakefilePackage", "MesonPackage"}
_WHEN_VARIANT = re.compile(r"[+~]([A-Za-z_][\w-]*)")


@dataclass
class Finding:
    level: Literal["error", "warning", "info"]
    message: str
    line: int | None = None

    @property
    def text(self) -> str:
        return f"line {self.line}: {self.message}" if self.line else self.message


def static_checks(source: str, package: str | None = None) -> list[Finding]:
    findings: list[Finding] = []
    summary = summarize(source)
    if summary.syntax_error:
        return [Finding("error", f"Python syntax error at {summary.syntax_error}")]
    if summary.class_name is None:
        return [Finding("error", "No package class defined.")]

    if re.search(r"^\s*from spack import \*", source, re.M):
        findings.append(Finding("error", "`from spack import *` was removed; use "
                                "`from spack.package import *`."))
    if package and summary.class_name != spack_class_name(package):
        findings.append(Finding("error", f"Class must be named {spack_class_name(package)} "
                                f"for package '{package}', found {summary.class_name}."))
    bases = {b.split(".")[-1] for b in summary.base_classes}
    for base in sorted(bases - KNOWN_BASES):
        findings.append(Finding("warning", f"Unrecognized base class {base}."))

    attrs = summary.attributes
    if "homepage" not in attrs or "example.com" in attrs.get("homepage", ""):
        findings.append(Finding("warning", "homepage is missing or a placeholder."))
    has_source = any(k in attrs for k in ("url", "git", "pypi", "list_url"))
    if not has_source and not any(
        d.kwargs.get("url") or d.kwargs.get("git") for d in summary.calls("version")
    ):
        findings.append(Finding("error", "No download source: set url, git, or pypi."))

    versions = summary.calls("version")
    if not versions:
        findings.append(Finding("error", "No version() directives; Spack cannot install it."))
    for call in versions:
        if not any(k in call.kwargs for k in ("sha256", "tag", "commit", "branch", "md5")):
            findings.append(Finding("error", f"version({call.args[0] if call.args else '?'}) "
                                    "has no sha256/tag/commit/branch.", call.line))
        if "tag" in call.kwargs and "commit" not in call.kwargs:
            findings.append(Finding("info", "Pinning a commit alongside tag= is recommended.",
                                    call.line))

    declared = set(summary.variants)
    for base in bases:
        declared |= INHERITED_VARIANTS.get(base, set())
    for call in summary.directives:
        when = call.kwargs.get("when", "")
        own_part = when.split("^", 1)[0]  # after ^ the variants belong to a dependency
        for name in _WHEN_VARIANT.findall(own_part):
            if name not in declared:
                findings.append(Finding("error", f"when='{when}' references undeclared variant "
                                        f"'{name}'.", call.line))
    used_in_code = (
        re.findall(r"define_from_variant\(\s*\"[^\"]+\"\s*,\s*\"([\w-]+)\"", source)
        + re.findall(r"(?:enable_or_disable|with_or_without)\(\s*\"([\w-]+)\"", source)
        + re.findall(r"spec\.satisfies\(\s*\"[+~]([\w-]+)\"\s*\)", source)
    )
    for name in sorted(set(used_in_code) - declared):
        findings.append(Finding("error", f"Build logic uses undeclared variant '{name}'."))

    if bases & COMPILED_BASES:
        languages = {"c", "cxx", "fortran"} & summary.dependency_names
        if not languages:
            findings.append(Finding("warning", "No language dependencies. Spack 1.x recipes "
                                    "declare depends_on('c'/'cxx'/'fortran', type='build')."))

    if summary.fixmes:
        findings.append(Finding("warning", f"{len(summary.fixmes)} FIXME(s) left on lines "
                                + ", ".join(map(str, summary.fixmes[:15]))))
    return findings
