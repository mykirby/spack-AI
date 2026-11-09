from __future__ import annotations

from pydantic import BaseModel, Field

from spack_ai.schemas import DetectedDependency, SkillResult
from spack_ai.skills import register
from spack_ai.skills.base import Skill, SkillContext, SkillError
from spack_ai.skills.dependency_mapping.mapper import DependencyMapper


class UpstreamName(BaseModel):
    name: str = Field(description="Name as the upstream build uses it, e.g. 'HDF5' or 'fftw3'.")
    source: str = Field(
        default="find_package",
        description="find_package | pkg_config | library | meson_dependency | "
        "python_requirement | program",
    )
    version_constraint: str | None = None
    components: list[str] = Field(default_factory=list)


class MapInput(BaseModel):
    names: list[UpstreamName] = Field(
        default_factory=list,
        description="Names to map. Leave empty to map every dependency found by the last "
        "analyze_build_system call.",
    )


def build_mapper(ctx: SkillContext) -> DependencyMapper:
    if "dependency_mapper" not in ctx.state:
        model = None
        if ctx.settings.ml.dependency_model:
            from spack_ai.ml.serving import load_model

            model = load_model(ctx.settings.resolve(ctx.settings.ml.dependency_model))
        ctx.state["dependency_mapper"] = DependencyMapper(
            ctx.knowledge.structured("dependency_map"), model
        )
    return ctx.state["dependency_mapper"]


@register
class MapDependencies(Skill):
    name = "map_dependencies"
    category = "analysis"
    description = (
        "Map upstream dependency names (CMake find_package, pkg-config modules, -l libraries, "
        "PyPI names) to Spack packages and virtuals, with version ranges and variants. "
        "Unresolved names are returned as flagged guesses."
    )
    Input = MapInput
    knowledge_sections = ("spack_fundamentals", "package_recipes")

    def run(self, params: MapInput) -> SkillResult:
        mapper = build_mapper(self.ctx)
        spec = self.ctx.state.get("build_spec")
        if params.names:
            deps = [DetectedDependency(**n.model_dump()) for n in params.names]
        elif spec is not None:
            deps = spec.dependencies
        else:
            raise SkillError("Nothing to map: pass names or run analyze_build_system first.")

        mapped = [mapper.resolve(d) for d in deps]
        if not params.names and spec is not None:
            spec.dependencies = mapped

        rows = [
            {
                "upstream": d.name,
                "source": d.source,
                "spack": d.spack_spec,
                "resolved": d.resolved,
                **({"virtual": True} if d.virtual else {}),
                **({"type": d.dep_types} if d.dep_types != ["build", "link"] else {}),
                **({"condition": d.condition} if d.condition else {}),
                **({"note": d.note} if d.note else {}),
            }
            for d in mapped
        ]
        unresolved = [d.name for d in mapped if not d.resolved]
        return SkillResult(
            summary=f"Mapped {len(mapped) - len(unresolved)}/{len(mapped)} dependencies."
            + (f" Unverified: {', '.join(unresolved)}." if unresolved else ""),
            data=rows,
        )
