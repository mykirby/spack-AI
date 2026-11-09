from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from spack_ai.schemas import SkillResult
from spack_ai.skills import register
from spack_ai.skills.base import Skill, SkillError
from spack_ai.skills.validation.checks import static_checks


class ValidateInput(BaseModel):
    path: str | None = Field(
        default=None, description="package.py to check. Defaults to the last recipe written."
    )
    package: str | None = Field(default=None, description="Expected Spack package name.")
    concretize: bool = Field(
        default=True,
        description="Also run `spack spec` in the session environment when Spack is available.",
    )


@register
class ValidateRecipe(Skill):
    name = "validate_recipe"
    category = "validation"
    description = (
        "Check a package.py: static checks (syntax, naming, versions, variants used in when= "
        "and build arguments, language dependencies, FIXMEs), then `spack spec` against the "
        "session environment if Spack is installed and an environment was generated."
    )
    Input = ValidateInput
    knowledge_sections = ("package_recipes", "troubleshooting")

    def run(self, params: ValidateInput) -> SkillResult:
        raw_path = params.path or self.ctx.state.get("recipe_path")
        if not raw_path:
            raise SkillError("No recipe to validate: pass path or write a recipe first.")
        path = self.ctx.resolve_source(raw_path)
        package = params.package or self.ctx.state.get("recipe_name") or path.parent.name
        package = package.replace("_", "-")
        findings = static_checks(path.read_text(), package)

        data: dict = {"findings": [f.__dict__ for f in findings]}
        spack = self.ctx.spack
        env_dir = self.ctx.state.get("env_dir")
        if params.concretize and spack.available and env_dir:
            result = spack.run(["-D", str(env_dir), "spec", "-I", package])
            data["spack_spec"] = {
                "ok": result.ok,
                "output": (result.stdout + result.stderr)[-8000:],
            }
        elif params.concretize:
            data["spack_spec"] = "skipped: " + (
                "spack not available" if not spack.available else "no environment generated yet"
            )

        errors = sum(f.level == "error" for f in findings)
        concretized = isinstance(data.get("spack_spec"), dict) and data["spack_spec"]["ok"]
        return SkillResult(
            summary=f"{Path(raw_path).name}: {errors} error(s), "
            f"{sum(f.level == 'warning' for f in findings)} warning(s)"
            + ("; concretizes." if concretized else "."),
            data=data,
        )
