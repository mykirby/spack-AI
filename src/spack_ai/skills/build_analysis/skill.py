from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from spack_ai.schemas import BuildSpec, BuildSystem, SkillResult
from spack_ai.skills import register
from spack_ai.skills.base import Skill
from spack_ai.skills.build_analysis.autotools import AutotoolsAnalyzer
from spack_ai.skills.build_analysis.base import Analyzer, source_languages
from spack_ai.skills.build_analysis.cmake import CMakeAnalyzer
from spack_ai.skills.build_analysis.makefile import MakefileAnalyzer
from spack_ai.skills.build_analysis.meson import MesonAnalyzer
from spack_ai.skills.build_analysis.pyproject import PythonAnalyzer

ANALYZERS: list[type[Analyzer]] = sorted(
    [CMakeAnalyzer, MesonAnalyzer, AutotoolsAnalyzer, PythonAnalyzer, MakefileAnalyzer],
    key=lambda a: a.priority,
)


def detect(path: Path) -> tuple[type[Analyzer] | None, Path, list[Path] | None]:
    """Pick an analyzer for a directory (by root markers) or a single build file."""
    if path.is_file():
        for analyzer in ANALYZERS:
            if analyzer.claims_file(path):
                return analyzer, path.parent, [path]
        return None, path.parent, None
    for analyzer in ANALYZERS:
        if any((path / marker).exists() for marker in analyzer.markers):
            return analyzer, path, None
    return None, path, None


def analyze_path(path: Path, build_system: BuildSystem | None = None) -> BuildSpec:
    analyzer, root, files = detect(path)
    if build_system:
        analyzer = next((a for a in ANALYZERS if a.build_system == build_system), None)
    if analyzer is None:
        spec = BuildSpec(root=str(root), build_system=BuildSystem.UNKNOWN,
                         project_name=root.name, languages=source_languages(root))
        spec.notes.append(
            "No recognised build system. Inspect the tree (list_source_tree/read_source_file) "
            "and write a generic Package with a custom install()."
        )
        return spec
    return analyzer().run(root, files)


class AnalyzeInput(BaseModel):
    path: str = Field(description="Source tree directory, or a single build file "
                      "(CMakeLists.txt, Makefile, configure.ac, meson.build, pyproject.toml).")
    build_system: BuildSystem | None = Field(
        default=None, description="Force a build system instead of auto-detecting."
    )


@register
class AnalyzeBuildSystem(Skill):
    name = "analyze_build_system"
    category = "analysis"
    description = (
        "Detect the build system of a source tree and extract project name, version, "
        "languages, dependencies (find_package, pkg-config, -l flags, ...), build options, "
        "and install behavior. Stores the result for map_dependencies and draft_package_recipe."
    )
    Input = AnalyzeInput
    knowledge_sections = ("build_systems",)

    def run(self, params: AnalyzeInput) -> SkillResult:
        path = self.ctx.resolve_source(params.path)
        if not path.exists():
            raise FileNotFoundError(f"{path} does not exist")
        spec = analyze_path(path, params.build_system)
        self.ctx.state["build_spec"] = spec
        self.ctx.state["source_root"] = spec.root
        deps = ", ".join(d.name for d in spec.dependencies) or "none"
        return SkillResult(
            summary=(
                f"{spec.build_system.value} project {spec.project_name or '?'} "
                f"{spec.version or ''}; languages: {', '.join(spec.languages) or '?'}; "
                f"{len(spec.dependencies)} dependencies ({deps}); {len(spec.options)} options."
            ),
            data=spec.model_dump(mode="json", exclude_none=True),
            warnings=spec.notes,
        )
