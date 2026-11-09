"""The Skill abstraction.

A skill is one capability of the agent: analyze a build system, map dependencies,
render a recipe, search the knowledge base, ... Each skill

* declares a pydantic `Input` model, which becomes the JSON schema of the tool the
  model calls, and validates every call before `run` executes;
* returns a `SkillResult`, which becomes the tool result the model reads;
* may ship a SKILL.md playbook next to its module, which is folded into the system
  prompt so the model knows *how* and *when* to use it;
* can be called directly from Python (the deterministic pipeline, tests, evals) with
  no LLM involved.

Skills share per-session state through `SkillContext.state`, so a large BuildSpec
produced by one skill can be consumed by the next without round-tripping it through
the model.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

from pydantic import BaseModel, ValidationError

from spack_ai.config import Settings
from spack_ai.schemas import SkillResult

if TYPE_CHECKING:
    from spack_ai.knowledge import KnowledgeBase
    from spack_ai.spack_runner import SpackRunner


class SkillError(Exception):
    """A failure the model should see and can recover from (bad path, missing input...)."""


class PathOutsideAllowedRoots(SkillError):
    pass


@dataclass
class SkillContext:
    settings: Settings
    workspace: Path
    allowed_roots: list[Path] = field(default_factory=list)
    state: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.workspace = self.workspace.resolve()
        self.allowed_roots = [p.resolve() for p in self.allowed_roots]

    @cached_property
    def knowledge(self) -> KnowledgeBase:
        from spack_ai.knowledge import KnowledgeBase

        cfg = self.settings.knowledge
        return KnowledgeBase(self.settings.knowledge_dir, cfg.chunk_size, cfg.chunk_overlap)

    @cached_property
    def spack(self) -> SpackRunner:
        from spack_ai.spack_runner import SpackRunner

        cfg = self.settings.spack
        return SpackRunner(cfg.executable, cfg.command_timeout)

    def allow_root(self, path: Path) -> None:
        path = path.resolve()
        if path not in self.allowed_roots:
            self.allowed_roots.append(path)

    def resolve_source(self, path: str | Path) -> Path:
        """Resolve a path the model wants to read; it must sit under an allowed root
        (the source trees the user pointed at, or the session workspace)."""
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            base = self.state.get("source_root") or (
                self.allowed_roots[0] if self.allowed_roots else self.workspace
            )
            candidate = Path(base) / candidate
        candidate = candidate.resolve()
        for root in [*self.allowed_roots, self.workspace]:
            if candidate == root or root in candidate.parents:
                return candidate
        raise PathOutsideAllowedRoots(
            f"{candidate} is outside the source trees this session may read. "
            "Ask the user to pass it with --path."
        )

    def resolve_output(self, relative: str | Path) -> Path:
        """Resolve a path to write; it must stay inside the session workspace."""
        candidate = (self.workspace / relative).resolve()
        if candidate != self.workspace and self.workspace not in candidate.parents:
            raise PathOutsideAllowedRoots(f"{relative} escapes the session workspace.")
        candidate.parent.mkdir(parents=True, exist_ok=True)
        return candidate

    def relative(self, path: Path) -> str:
        try:
            return str(path.resolve().relative_to(self.workspace))
        except ValueError:
            return str(path)


class Skill(ABC):
    name: ClassVar[str]
    description: ClassVar[str]
    Input: ClassVar[type[BaseModel]]
    # Category groups skills in the prompt and the CLI listing.
    category: ClassVar[str] = "general"
    # Ask the user before running (state changes, network access, long builds).
    requires_confirmation: ClassVar[bool] = False
    # Knowledge base sections this skill leans on; surfaced in the playbook.
    knowledge_sections: ClassVar[tuple[str, ...]] = ()

    def __init__(self, ctx: SkillContext):
        self.ctx = ctx

    @abstractmethod
    def run(self, params: BaseModel) -> SkillResult: ...

    def confirmation_prompt(self, params: BaseModel) -> str | None:
        """Return a question for the user if this call needs approval, else None."""
        if self.requires_confirmation:
            return f"Allow {self.name} with {params.model_dump_json(exclude_defaults=True)}?"
        return None

    # -- plumbing -----------------------------------------------------------------

    def validate(self, raw: dict[str, Any] | BaseModel) -> BaseModel:
        return raw if isinstance(raw, self.Input) else self.Input.model_validate(raw)

    def __call__(self, **kwargs: Any) -> SkillResult:
        """Direct Python invocation: skill(path='...')."""
        return self.run(self.validate(kwargs))

    @classmethod
    def tool_definition(cls) -> dict[str, Any]:
        return {
            "name": cls.name,
            "description": cls.description,
            "input_schema": inline_schema(cls.Input),
        }

    @classmethod
    def playbook(cls) -> str | None:
        """SKILL.md that sits in the skill's package directory, if any."""
        import inspect

        path = Path(inspect.getfile(cls)).parent / "SKILL.md"
        return path.read_text().strip() if path.exists() else None


def inline_schema(model: type[BaseModel]) -> dict[str, Any]:
    """JSON schema for a tool: $refs inlined, titles dropped, no extra properties."""
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return walk(defs[node["$ref"].split("/")[-1]])
            node = {k: walk(v) for k, v in node.items() if k != "title"}
            if node.get("type") == "object" and "properties" in node:
                node.setdefault("additionalProperties", False)
            return node
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    return walk(schema)


def format_validation_error(raw: Any, exc: ValidationError) -> str:
    return json.dumps(
        {"INVALID_INPUT": raw, "errors": json.loads(exc.json(include_url=False))},
        default=str,
    )
