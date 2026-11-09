from __future__ import annotations

from pydantic import BaseModel, Field

from spack_ai.recipe_ast import spec_name
from spack_ai.schemas import DependsOn, SkillResult, Variant, VersionEntry
from spack_ai.skills import register
from spack_ai.skills.base import Skill, SkillContext, SkillError
from spack_ai.skills.recipe.builder import recipe_from_build_spec
from spack_ai.skills.recipe.render import render_recipe, write_recipe
from spack_ai.skills.validation.checks import static_checks


def save_recipe_source(ctx: SkillContext, package: str, source: str) -> SkillResult:
    settings = ctx.settings
    path = write_recipe(
        source, package, ctx.workspace, settings.recipe.namespace, settings.spack.is_v1
    )
    ctx.state["recipe_path"] = str(path)
    ctx.state["recipe_name"] = package
    findings = static_checks(source, package)
    errors = [f.text for f in findings if f.level == "error"]
    warnings = [f.text for f in findings if f.level != "error"]
    return SkillResult(
        summary=f"Wrote {ctx.relative(path)}"
        + (f" with {len(errors)} error(s)" if errors else "")
        + (f", {len(warnings)} warning(s)" if warnings else "") + ".",
        data={"path": str(path), "source": source, "errors": errors},
        files=[str(path)],
        warnings=warnings,
    )


class DraftInput(BaseModel):
    name: str | None = Field(default=None, description="Spack package name (lowercase, dashes).")
    description: str | None = None
    homepage: str | None = None
    url: str | None = Field(default=None, description="Release tarball URL for the newest version.")
    git: str | None = None
    versions: list[VersionEntry] = Field(
        default_factory=list, description="Versions with sha256 (tarballs) or tag/commit/branch."
    )
    maintainers: list[str] = Field(default_factory=list, description="GitHub handles.")
    add_variants: list[Variant] = Field(default_factory=list)
    drop_variants: list[str] = Field(default_factory=list)
    add_dependencies: list[DependsOn] = Field(default_factory=list)
    drop_dependencies: list[str] = Field(
        default_factory=list, description="Spack names to remove from the draft."
    )
    extra_build_args: list[str] = Field(
        default_factory=list,
        description="Python expressions appended in cmake_args/configure_args/meson_args, "
        "e.g. 'self.define(\"ENABLE_X\", True)'.",
    )


@register
class DraftPackageRecipe(Skill):
    name = "draft_package_recipe"
    category = "generation"
    description = (
        "Generate a first-draft package.py from the last analyze_build_system result "
        "(dependencies are mapped automatically) plus your overrides, write it into the "
        "session's local Spack repository, and return the source with static check results. "
        "Refine it afterwards with save_package_recipe."
    )
    Input = DraftInput
    knowledge_sections = ("package_recipes", "build_systems")

    def run(self, params: DraftInput) -> SkillResult:
        spec = self.ctx.state.get("build_spec")
        if spec is None:
            raise SkillError("Run analyze_build_system before draft_package_recipe.")
        if any(not d.resolved and d.spack_spec is None and d.note is None
               for d in spec.dependencies):
            from spack_ai.skills.dependency_mapping.skill import build_mapper

            mapper = build_mapper(self.ctx)
            spec.dependencies = [mapper.resolve(d) for d in spec.dependencies]

        recipe = recipe_from_build_spec(
            spec,
            name=params.name,
            homepage=params.homepage,
            url=params.url,
            git=params.git,
            versions=params.versions or None,
            description=params.description,
            maintainers=params.maintainers or self.ctx.settings.recipe.maintainers,
        )
        recipe.variants = [v for v in recipe.variants if v.name not in params.drop_variants]
        recipe.variants += params.add_variants
        drop = set(params.drop_dependencies)
        recipe.dependencies = [
            d for d in recipe.dependencies if spec_name(d.spec) not in drop
        ] + params.add_dependencies
        recipe.extra_build_args += params.extra_build_args

        self.ctx.state["recipe"] = recipe
        source = render_recipe(recipe, v1_imports=self.ctx.settings.spack.is_v1)
        return save_recipe_source(self.ctx, recipe.name, source)


class SaveInput(BaseModel):
    name: str = Field(description="Spack package name.")
    source: str = Field(description="Complete package.py contents.")


@register
class SavePackageRecipe(Skill):
    name = "save_package_recipe"
    category = "generation"
    description = (
        "Write a complete package.py you authored or edited into the session's local Spack "
        "repository and run static checks on it (syntax, class name, versions, variants "
        "referenced in when= clauses, leftover FIXMEs)."
    )
    Input = SaveInput
    knowledge_sections = ("package_recipes",)

    def run(self, params: SaveInput) -> SkillResult:
        return save_recipe_source(self.ctx, params.name, params.source)
