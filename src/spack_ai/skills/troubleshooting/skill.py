from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field, model_validator

from spack_ai.schemas import SkillResult
from spack_ai.skills import register
from spack_ai.skills.base import Skill

_ERROR_LINE = re.compile(r"\b(error|Error|ERROR|failed|FAILED)\b")


class DiagnoseInput(BaseModel):
    log_text: str | None = Field(default=None, description="Pasted build output.")
    log_path: str | None = Field(
        default=None, description="Path to a log, e.g. spack-build-out.txt or spack-build-env.txt."
    )
    max_matches: int = Field(default=15, ge=1, le=100)

    @model_validator(mode="after")
    def _one_source(self) -> DiagnoseInput:
        if not (self.log_text or self.log_path):
            raise ValueError("pass log_text or log_path")
        return self


def diagnose(text: str, patterns: list[dict[str, Any]], max_matches: int = 15) -> dict[str, Any]:
    compiled = [(p, re.compile(p["pattern"], re.IGNORECASE)) for p in patterns]
    lines = text.splitlines()
    matches: list[dict[str, Any]] = []
    seen: set[tuple[str, tuple[str, ...]]] = set()
    for number, line in enumerate(lines, 1):
        for pattern, regex in compiled:
            found = regex.search(line)
            if not found:
                continue
            groups = tuple(g or "" for g in found.groups())
            key = (pattern["id"], groups)
            if key in seen:
                continue
            seen.add(key)

            def fill(template: str, groups: tuple[str, ...] = groups) -> str:
                for i, value in enumerate(groups, 1):
                    template = template.replace(f"{{{i}}}", value)
                return template

            matches.append(
                {
                    "id": pattern["id"],
                    "category": pattern.get("category"),
                    "line": number,
                    "context": "\n".join(lines[max(0, number - 3) : number + 2]),
                    "explanation": fill(pattern.get("explanation", "")),
                    "suggestions": [fill(s) for s in pattern.get("suggestions", [])],
                    **({"search": pattern["search"]} if pattern.get("search") else {}),
                }
            )
            if len(matches) >= max_matches:
                return {"matches": matches}
    result: dict[str, Any] = {"matches": matches}
    if not matches:
        result["error_lines"] = [
            f"{i}: {line.strip()}" for i, line in enumerate(lines, 1) if _ERROR_LINE.search(line)
        ][:40]
    return result


@register
class DiagnoseBuildFailure(Skill):
    name = "diagnose_build_failure"
    category = "troubleshooting"
    description = (
        "Scan a failed build or concretization log for known failure signatures (missing "
        "dependencies, link errors, compiler incompatibilities, fetch and quota problems) and "
        "return explanations with fix suggestions. Falls back to listing error lines."
    )
    Input = DiagnoseInput
    knowledge_sections = ("troubleshooting",)

    def run(self, params: DiagnoseInput) -> SkillResult:
        text = params.log_text or self.ctx.resolve_source(params.log_path).read_text(
            errors="replace"
        )
        patterns = self.ctx.knowledge.structured("error_patterns") or []
        result = diagnose(text, patterns, params.max_matches)
        matches = result["matches"]
        summary = (
            f"{len(matches)} known failure signature(s): "
            + ", ".join(dict.fromkeys(m["id"] for m in matches))
            if matches
            else f"No known signature; {len(result.get('error_lines', []))} error line(s) listed."
        )
        return SkillResult(summary=summary, data=result)
