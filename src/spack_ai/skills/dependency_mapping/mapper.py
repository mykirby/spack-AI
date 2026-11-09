"""Resolve upstream dependency names to Spack packages.

Resolution order:
  1. the curated table in knowledge_base/structured/dependency_map.yaml
  2. a trained model, if config.ml.dependency_model points at a training run
  3. a lower-cased guess, flagged as unverified
"""

from __future__ import annotations

import re
from typing import Any, Protocol

from spack_ai.schemas import DetectedDependency

TABLE_BY_SOURCE = {
    "find_package": ("cmake", "pkgconfig"),
    "macro": ("cmake",),
    "program": ("cmake",),
    "fetchcontent": ("cmake", "pkgconfig"),
    "pkg_config": ("pkgconfig", "cmake"),
    "meson_dependency": ("pkgconfig", "cmake"),
    "library": ("libraries",),
}
# Virtuals whose version means the same thing upstream (the MPI standard version).
VERSIONED_VIRTUALS = {"mpi"}


class DependencyPredictor(Protocol):
    """What the mapper needs from a trained model (see spack_ai.ml.models)."""

    def predict(self, inputs: list[dict[str, Any]]) -> list[Any]: ...


class DependencyMapper:
    def __init__(self, table: dict[str, Any], model: DependencyPredictor | None = None):
        self.table = table
        self.model = model
        # Case-insensitive views of each table.
        self._lower = {
            section: {str(k).lower(): v for k, v in (entries or {}).items()}
            for section, entries in table.items()
            if isinstance(entries, dict)
        }

    def resolve(self, dep: DetectedDependency) -> DetectedDependency:
        dep = dep.model_copy(deep=True)
        if dep.resolved:
            dep.spack_spec = dep.spack_spec or dep.spack_name
            return dep

        entry = self._lookup(dep)
        if entry is not None:
            self._apply(dep, entry)
            return dep

        if self.model is not None:
            prediction = self.model.predict([{"name": dep.name, "source": dep.source}])[0]
            if prediction:
                self._apply(dep, {"spack": prediction})
                dep.note = "Predicted by the trained dependency model; verify with `spack info`."
                return dep

        guess = re.sub(r"[^a-z0-9]+", "-", dep.name.lower()).strip("-")
        if dep.source == "python_requirement":
            # Spack's naming convention for PyPI distributions is reliable enough to accept.
            self._apply(dep, {"spack": f"py-{guess}",
                              "note": "Spack naming convention (py-<name>); verify it exists."})
            return dep
        dep.spack_name = guess
        dep.spack_spec = self._spec(guess, dep, {})
        dep.resolved = False
        dep.note = f"Unverified guess; confirm with `spack list {guess}` or `spack providers`."
        return dep

    # ------------------------------------------------------------------------------

    def _lookup(self, dep: DetectedDependency) -> Any | None:
        name = dep.name.lower()
        if dep.source == "python_requirement":
            return self._lower.get("python", {}).get(re.sub(r"[._]+", "-", name))
        for section in TABLE_BY_SOURCE.get(dep.source, ("cmake", "pkgconfig", "libraries")):
            entries = self._lower.get(section, {})
            if name in entries:
                return entries[name]
        if dep.source == "library":
            for prefix, entry in self._lower.get("library_prefixes", {}).items():
                if name.startswith(prefix):
                    if isinstance(entry, dict) and entry.get("component_from_suffix"):
                        dep.components = sorted({*dep.components, name[len(prefix):]})
                        return {**entry, "component_template": "+{component}"}
                    return entry
        return None

    def _apply(self, dep: DetectedDependency, entry: Any) -> None:
        if isinstance(entry, str):
            entry = {"spack": entry}
        dep.resolved = True
        dep.virtual = bool(entry.get("virtual"))
        dep.note = entry.get("note")
        if entry.get("type"):
            dep.dep_types = list(entry["type"])
        name = entry.get("spack")
        if name is None:
            dep.spack_name = dep.spack_spec = None
            dep.note = dep.note or "No Spack dependency needed."
            return
        dep.spack_name = name
        if dep.virtual and name not in VERSIONED_VIRTUALS and dep.version_constraint:
            # A virtual's version is its API version (fftw-api@3), not the provider release.
            upstream = dep.version_constraint
            dep.version_constraint = None
            dep.note = " ".join(filter(None, [
                dep.note, f"Upstream wants version {upstream} of the implementation; constrain "
                "the provider (e.g. in spack.yaml requirements) if it matters."]))
        dep.spack_spec = self._spec(name, dep, entry)

    @staticmethod
    def _spec(name: str, dep: DetectedDependency, entry: dict[str, Any]) -> str:
        spec = name
        if dep.version_constraint:
            spec += f"@{dep.version_constraint}"
        variants: list[str] = []
        components = entry.get("components") or {}
        if "_" in components:  # entry-level variants (e.g. libhdf5_hl -> +hl)
            variants.append(components["_"])
        template = entry.get("component_template")
        for component in dep.components:
            if component in components:
                variants.append(components[component])
            elif template:
                variants.append(template.format(component=component.lower()))
        for variant in variants:
            for part in re.findall(r"[+~][\w-]+", variant):
                if part not in spec:
                    spec += part
        return spec
