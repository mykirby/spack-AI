"""Python packages: pyproject.toml, setup.cfg, setup.py, requirements.txt."""

from __future__ import annotations

import configparser
import re
import tomllib
from pathlib import Path

from spack_ai.naming import pep440_to_spack
from spack_ai.schemas import BuildSpec, BuildSystem, DetectedDependency
from spack_ai.skills.build_analysis.base import Analyzer

# PEP 517 backend module -> the distribution that provides it.
BACKENDS = {
    "setuptools": "setuptools", "hatchling": "hatchling", "flit_core": "flit-core",
    "poetry": "poetry-core", "pdm": "pdm-backend", "scikit_build_core": "scikit-build-core",
    "mesonpy": "meson-python", "maturin": "maturin",
}
# name, [extras], version specifier, ; environment marker
_REQUIREMENT = re.compile(
    r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(\[[^\]]*\])?\s*([^;]*?)\s*(?:;\s*(.*))?$"
)


class PythonAnalyzer(Analyzer):
    build_system = BuildSystem.PYTHON
    markers = ("pyproject.toml", "setup.py", "setup.cfg")
    priority = 40

    def discover(self, root: Path) -> list[Path]:
        names = ("pyproject.toml", "setup.cfg", "setup.py", "requirements.txt")
        return [root / n for n in names if (root / n).exists()]

    def analyze(self, root: Path, files: list[Path]) -> BuildSpec:
        spec = BuildSpec(root=str(root), build_system=self.build_system, languages=["python"])
        for path in files:
            if path.name == "pyproject.toml":
                self._pyproject(spec, path)
            elif path.name == "setup.cfg":
                self._setup_cfg(spec, path)
            elif path.name == "requirements.txt":
                for line in path.read_text().splitlines():
                    self._requirement(spec, line, ["build", "run"], path.name)
            elif path.name == "setup.py" and not spec.metadata.get("build_backend"):
                spec.metadata["build_backend"] = "setuptools"
                spec.notes.append(
                    "setup.py only: dependencies declared in code were not parsed; read "
                    "install_requires in setup.py."
                )
        backend = spec.metadata.get("build_backend")
        if backend:
            spec.add_dependency(
                DetectedDependency(name=backend, source="python_requirement",
                                   dep_types=["build"])
            )
        if (root / "CMakeLists.txt").exists() or (root / "meson.build").exists():
            spec.notes.append(
                "Python package with a compiled extension built by CMake/Meson: check compilers "
                "and native dependencies too."
            )
        return spec

    def _pyproject(self, spec: BuildSpec, path: Path) -> None:
        data = tomllib.loads(path.read_text())
        project = data.get("project", {})
        spec.project_name = project.get("name") or spec.project_name
        spec.version = project.get("version") or spec.version
        if project.get("description"):
            spec.metadata["description"] = project["description"]
        urls = project.get("urls", {})
        homepage = urls.get("Homepage") or urls.get("homepage") or urls.get("Source")
        if homepage:
            spec.metadata["homepage"] = homepage
        if requires_python := project.get("requires-python"):
            constraint = pep440_to_spack(requires_python.replace(" ", ""))
            spec.add_dependency(
                DetectedDependency(name="python", source="python_requirement",
                                   version_constraint=constraint, dep_types=["build", "run"])
            )
        for req in project.get("dependencies", []):
            self._requirement(spec, req, ["build", "run"], path.name)
        for extra, reqs in project.get("optional-dependencies", {}).items():
            for req in reqs:
                self._requirement(spec, req, ["build", "run"], path.name, condition=extra)

        build_system = data.get("build-system", {})
        backend = build_system.get("build-backend", "")
        for module, dist in BACKENDS.items():
            if backend.startswith(module):
                spec.metadata["build_backend"] = dist
        for req in build_system.get("requires", []):
            # PythonPackage already brings pip and wheel.
            if not re.match(r"^\s*(pip|wheel)\b", req):
                self._requirement(spec, req, ["build"], path.name)

    def _setup_cfg(self, spec: BuildSpec, path: Path) -> None:
        parser = configparser.ConfigParser()
        parser.read(path)
        if parser.has_option("metadata", "name"):
            spec.project_name = spec.project_name or parser.get("metadata", "name")
        if parser.has_option("options", "install_requires"):
            for line in parser.get("options", "install_requires").splitlines():
                self._requirement(spec, line, ["build", "run"], path.name)

    def _requirement(self, spec, text: str, dep_types, file: str, condition=None) -> None:
        text = text.split("#", 1)[0].strip()
        if not text or text.startswith(("-", "git+", "http")):
            return
        match = _REQUIREMENT.match(text)
        if not match:
            return
        name, _extras, constraint, marker = match.groups()
        spec.add_dependency(
            DetectedDependency(
                name=name,
                source="python_requirement",
                version_constraint=pep440_to_spack(constraint.replace(" ", "")) if constraint
                else None,
                condition=condition or (f"marker: {marker}" if marker else None),
                required=condition is None,
                dep_types=list(dep_types),
                file=file,
            )
        )
