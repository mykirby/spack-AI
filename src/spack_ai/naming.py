"""Spack naming and version-range conventions."""

from __future__ import annotations

import re
import string

_VERSION_RE = re.compile(r"^v?(\d+(?:\.\d+)*)")


def spack_package_name(project: str, python: bool = False) -> str:
    """'MyProject_Core' -> 'myproject-core'; Python distributions get the 'py-' prefix."""
    name = re.sub(r"[^a-z0-9]+", "-", project.strip().lower()).strip("-") or "unnamed"
    if python and not name.startswith("py-"):
        name = f"py-{name}"
    return name


def spack_class_name(package: str) -> str:
    """Mirror of spack.util.naming.pkg_name_to_class_name: 'py-numpy' -> 'PyNumpy'."""
    class_name = re.sub(r"[-_]+", "-", package)
    class_name = string.capwords(class_name, "-").replace("-", "")
    if class_name and class_name[0].isdigit():
        class_name = f"_{class_name}"
    return class_name


def package_dir_name(package: str, repo_api_v2: bool) -> str:
    """Directory name for a package inside a repository (v2 repos are Python packages)."""
    if not repo_api_v2:
        return package
    name = package.replace("-", "_")
    return f"_{name}" if name[0].isdigit() else name


def clean_version(text: str | None) -> str | None:
    """Pull a dotted version out of strings like 'v1.2.3', '1.2', '${PROJECT_VERSION}'."""
    if not text:
        return None
    match = _VERSION_RE.match(text.strip())
    return match.group(1) if match else None


def minimum_version_range(version: str | None) -> str | None:
    """A 'version or newer' requirement ('3.16' -> '3.16:')."""
    version = clean_version(version)
    return f"{version}:" if version else None


def pep440_to_spack(specifier: str) -> str | None:
    """Translate a PEP 440 / pkg-config constraint into a Spack version range.

    '>=1.2,<2' -> '1.2:1'   '==1.4' -> '1.4'   '<=3' -> ':3'
    Spack ranges are inclusive and a bare '1' contains every 1.x, so '<2' maps to ':1'.
    Constraints that do not translate cleanly return None (callers keep the raw text).
    """
    low: str | None = None
    high: str | None = None
    for part in re.split(r"\s*,\s*", specifier.strip()):
        if not part:
            continue
        match = re.match(r"^(>=|<=|==|~=|>|<|=)\s*v?([\w.*]+)$", part)
        if not match:
            return None
        op, ver = match.groups()
        ver = ver.rstrip(".*")
        if op in ("==", "="):
            return ver
        if op in (">=", "~="):
            low = ver
        elif op == ">":
            low = ver  # Spack has no exclusive lower bound; caller should treat as approximate.
        elif op == "<=":
            high = ver
        elif op == "<":
            high = _previous_series(ver)
            if high is None:
                return None
    if low is None and high is None:
        return None
    return f"{low or ''}:{high or ''}"


def _previous_series(version: str) -> str | None:
    """'2' -> '1', '2.0' -> '1', '1.5' -> '1.4' (the newest series strictly below)."""
    parts = [int(p) for p in version.split(".") if p.isdigit()]
    while parts and parts[-1] == 0:
        parts.pop()
    if not parts:
        return None
    parts[-1] -= 1
    return ".".join(str(p) for p in parts)
