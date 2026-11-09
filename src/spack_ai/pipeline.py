"""Deterministic generation: the same skills the agent uses, chained without an LLM.

This is the baseline the agent must beat, what the evals score by default, and a
useful offline mode: `spack-ai generate <path>`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from spack_ai.config import Settings
from spack_ai.schemas import BuildSpec, VersionEntry
from spack_ai.skills import get_skill
from spack_ai.skills.base import SkillContext


@dataclass
class PipelineResult:
    workspace: Path
    build_spec: BuildSpec
    recipe_path: Path
    recipe_source: str
    errors: list[str]
    warnings: list[str]
    env_path: Path | None = None
    script_path: Path | None = None
    files: list[Path] = field(default_factory=list)


def generate(
    source: Path,
    settings: Settings,
    name: str | None = None,
    url: str | None = None,
    git: str | None = None,
    versions: list[VersionEntry] | None = None,
    workspace: Path | None = None,
    environment: bool = True,
    job_script: bool = True,
) -> PipelineResult:
    source = source.resolve()
    root = source if source.is_dir() else source.parent
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", name or root.name)
    ctx = SkillContext(
        settings,
        workspace=workspace or settings.output_dir / "generated" / slug,
        allowed_roots=[root],
    )

    def run(skill: str, **params):
        return get_skill(skill)(ctx)(**params)

    run("analyze_build_system", path=str(source))
    run("map_dependencies")
    draft = run(
        "draft_package_recipe",
        name=name,
        url=url,
        git=git,
        versions=[v.model_dump() for v in versions or []],
    )
    result = PipelineResult(
        workspace=ctx.workspace,
        build_spec=ctx.state["build_spec"],
        recipe_path=Path(draft.data["path"]),
        recipe_source=draft.data["source"],
        errors=draft.data["errors"],
        warnings=draft.warnings,
    )
    result.files.append(result.recipe_path)
    if environment:
        env = run("generate_environment")
        result.env_path = Path(env.data["path"])
        result.files.append(result.env_path)
        if job_script:
            script = run("generate_job_script")
            result.script_path = Path(script.data["path"])
            result.files.append(result.script_path)
    return result
