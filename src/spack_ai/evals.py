"""Benchmark harness: score generated recipes against expectations in evals/cases/.

Each case directory holds:
    case.yaml      package name, expected build system / dependencies / variants
    source/        a (minimal) source tree, or set `source:` to another path
    reference.py   optional known-good package.py to compare against

`pipeline` mode scores the deterministic generator (free, offline). `agent` mode runs
the full LLM agent per case and costs API tokens.
"""

from __future__ import annotations

import traceback
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean
from typing import Any, Literal

import yaml

from spack_ai.config import Settings
from spack_ai.ml.evaluation.metrics import recipe_scores
from spack_ai.pipeline import generate


@dataclass
class CaseResult:
    name: str
    scores: dict[str, Any] = field(default_factory=dict)
    recipe_path: str | None = None
    error: str | None = None


def load_cases(cases_dir: Path) -> list[tuple[str, Path, dict[str, Any]]]:
    cases = []
    for case_file in sorted(cases_dir.glob("*/case.yaml")):
        case = yaml.safe_load(case_file.read_text())
        cases.append((case_file.parent.name, case_file.parent, case))
    return cases


def run_case(name: str, case_dir: Path, case: dict[str, Any], settings: Settings,
             mode: Literal["pipeline", "agent"]) -> CaseResult:
    source = (case_dir / case.get("source", "source")).resolve()
    expected = dict(case.get("expected", {}))
    if (case_dir / "reference.py").exists():
        expected["reference"] = (case_dir / "reference.py").read_text()
    workspace = settings.output_dir / "evals" / mode / name
    try:
        if mode == "pipeline":
            result = generate(source, settings, name=case.get("package"), workspace=workspace,
                              environment=False)
            recipe_source, recipe_path = result.recipe_source, str(result.recipe_path)
            build_system = result.build_spec.build_system.value
        else:
            recipe_source, recipe_path, build_system = _run_agent(source, case, settings)
        scores = recipe_scores(recipe_source, expected)
        if "build_system" in expected and build_system:
            scores["build_system_ok"] = build_system == expected["build_system"]
        return CaseResult(name, scores, recipe_path)
    except Exception as exc:  # noqa: BLE001 - one broken case must not stop the run
        return CaseResult(name, error=f"{exc}\n{traceback.format_exc(limit=3)}")


def _run_agent(source: Path, case: dict[str, Any], settings: Settings):
    from spack_ai.agent import Agent

    agent = Agent(settings, sources=[source])
    prompt = case.get("prompt") or (
        f"Write a Spack package recipe for the software in {source}"
        + (f" named '{case['package']}'" if case.get("package") else "")
        + ". Validate it. Do not fetch anything from the network."
    )
    agent.send(prompt)
    path = agent.ctx.state.get("recipe_path")
    if not path:
        raise RuntimeError("agent did not write a recipe")
    spec = agent.ctx.state.get("build_spec")
    return Path(path).read_text(), path, spec.build_system.value if spec else None


def summarize_results(results: list[CaseResult]) -> dict[str, Any]:
    ok = [r for r in results if not r.error]

    def avg(key: str, sub: str = "f1") -> float | None:
        values = [r.scores[key][sub] for r in ok if key in r.scores]
        return round(mean(values), 3) if values else None

    return {
        "cases": len(results),
        "errors": len(results) - len(ok),
        "syntax_ok": sum(r.scores.get("syntax_ok", False) for r in ok),
        "build_system_ok": sum(r.scores.get("build_system_ok", False) for r in ok),
        "base_class_ok": sum(r.scores.get("base_class_ok", False) for r in ok),
        "dependency_f1": avg("dependencies"),
        "variant_f1": avg("variants"),
        "mean_fixmes": round(mean(r.scores.get("fixmes", 0) for r in ok), 1) if ok else None,
    }
