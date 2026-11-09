from __future__ import annotations

from pydantic import BaseModel, Field

from spack_ai.schemas import SkillResult
from spack_ai.skills import register
from spack_ai.skills.base import Skill, SkillError
from spack_ai.spack_runner import is_read_only

MAX_OUTPUT = 20_000


class SpackInput(BaseModel):
    args: list[str] = Field(
        description="Arguments after `spack`, one per element, e.g. ['info', 'hdf5'] or "
        "['-D', '<env dir>', 'concretize', '-f']."
    )
    in_workspace: bool = Field(
        default=True, description="Run from the session workspace directory."
    )


@register
class SpackCommand(Skill):
    name = "spack_command"
    category = "spack"
    description = (
        "Run a Spack command on this machine. Read-only commands (list, info, versions, "
        "providers, spec, find, checksum, compilers, config get, audit, ...) run directly; "
        "anything that changes Spack state (install, external find, concretize, env create, "
        "...) asks the user first."
    )
    Input = SpackInput
    knowledge_sections = ("spack_fundamentals",)

    def confirmation_prompt(self, params: SpackInput) -> str | None:
        if is_read_only(params.args):
            return None
        return f"Run `spack {' '.join(params.args)}`? It may change Spack state or take a while."

    def run(self, params: SpackInput) -> SkillResult:
        spack = self.ctx.spack
        if not spack.available:
            raise SkillError(
                "Spack is not installed or not configured here (spack.executable / $SPACK_ROOT). "
                "Continue without it and tell the user which commands to run themselves."
            )
        cwd = self.ctx.workspace if params.in_workspace else None
        if cwd:
            cwd.mkdir(parents=True, exist_ok=True)
        result = spack.run(params.args, cwd=cwd)
        return SkillResult(
            summary=f"spack {' '.join(params.args)} exited {result.returncode}",
            data={
                "returncode": result.returncode,
                "stdout": _tail(result.stdout),
                "stderr": _tail(result.stderr),
            },
        )


def _tail(text: str) -> str:
    return text if len(text) <= MAX_OUTPUT else "...[truncated]...\n" + text[-MAX_OUTPUT:]
