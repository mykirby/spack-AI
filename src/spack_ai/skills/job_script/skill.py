from __future__ import annotations

from pathlib import Path
from typing import Literal

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from pydantic import BaseModel, Field

from spack_ai.schemas import SkillResult
from spack_ai.skills import register
from spack_ai.skills.base import Skill, SkillError

_TEMPLATES = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
    undefined=StrictUndefined,
)


class JobScriptInput(BaseModel):
    env_dir: str | None = Field(
        default=None, description="Environment directory. Defaults to the last one generated."
    )
    scheduler: Literal["slurm", "pbs", "lsf", "none"] | None = Field(
        default=None, description="Batch system; defaults to the site config."
    )
    job_name: str = "spack-build"
    nodes: int = 1
    cpus: int | None = Field(default=None, description="Cores for the build (spack install -j).")
    walltime: str = Field(default="04:00:00", description="HH:MM:SS")
    partition: str | None = None
    account: str | None = None
    modules: list[str] | None = Field(default=None, description="Modules to load first.")
    spack_root: str = Field(default="$HOME/spack", description="Spack checkout on the machine.")
    setup: list[str] = Field(
        default_factory=list,
        description="Extra shell lines run after activation (e.g. 'spack external find cmake').",
    )
    run_tests: bool = False


@register
class GenerateJobScript(Skill):
    name = "generate_job_script"
    category = "generation"
    description = (
        "Write a bash build script for an HPC machine that loads modules, activates the Spack "
        "environment, concretizes, and installs; optionally with a Slurm/PBS/LSF batch header."
    )
    Input = JobScriptInput
    knowledge_sections = ("hpc_sites",)

    def run(self, params: JobScriptInput) -> SkillResult:
        site = self.ctx.settings.site
        env_dir = params.env_dir or self.ctx.state.get("env_dir")
        if not env_dir:
            raise SkillError("No environment: run generate_environment first or pass env_dir.")
        scheduler = params.scheduler or site.scheduler
        hours, minutes, *_ = (params.walltime.split(":") + ["0", "0"])[:3]
        text = _TEMPLATES.get_template("build.sh.j2").render(
            scheduler=scheduler,
            job_name=params.job_name,
            nodes=params.nodes,
            cpus=params.cpus or site.build_jobs,
            walltime=params.walltime,
            walltime_lsf=f"{int(hours):d}:{int(minutes):02d}",
            partition=params.partition or site.partition,
            account=params.account or site.account,
            modules=site.modules if params.modules is None else params.modules,
            spack_root=params.spack_root,
            env_dir=env_dir,
            setup=params.setup,
            run_tests=params.run_tests,
        )
        path = self.ctx.resolve_output(f"scripts/build-{Path(env_dir).name}.sh")
        path.write_text(text)
        path.chmod(0o755)
        submit = {"slurm": "sbatch", "pbs": "qsub", "lsf": "bsub <"}.get(scheduler, "bash")
        return SkillResult(
            summary=f"Wrote {self.ctx.relative(path)} ({scheduler}). Submit with: {submit} {path}",
            data={"path": str(path), "script": text},
            files=[str(path)],
        )
