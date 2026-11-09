"""Turn raw material into TrainingExamples.

SessionCollector     agent transcripts (data/sessions/*.jsonl) + user feedback
SpackRepoCollector   an existing Spack package repository (e.g. a spack-packages
                     checkout): thousands of human-written recipes
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from spack_ai.agent.session import Session
from spack_ai.ml.data.schema import TrainingExample
from spack_ai.recipe_ast import spec_name, summarize


class SessionCollector:
    def __init__(self, sessions_dir: Path):
        self.sessions_dir = sessions_dir

    def collect(self) -> Iterator[TrainingExample]:
        for path in sorted(self.sessions_dir.glob("*.jsonl")):
            yield from self._from_session(path.stem, Session.read(path))

    def _from_session(self, session_id: str, events: list[dict[str, Any]]):
        feedback = [e for e in events if e["event"] == "feedback"]
        outcome = feedback[-1]["outcome"] if feedback else "unknown"
        note = feedback[-1].get("note") if feedback else None
        calls = {e["id"]: e for e in events if e["event"] == "tool_call"}
        results = [
            (calls.get(e["id"], {}), e)
            for e in events
            if e["event"] == "tool_result" and not e.get("is_error")
        ]

        build_spec = None
        final_recipe = None
        mappings: list[dict[str, Any]] = []
        logs: list[tuple[str, Any]] = []
        for call, result in results:
            payload = _json(result.get("content"))
            data = payload.get("data") if isinstance(payload, dict) else None
            name = result["name"]
            if name == "analyze_build_system" and isinstance(data, dict):
                build_spec = data
            elif name in ("draft_package_recipe", "save_package_recipe") and isinstance(data, dict):
                final_recipe = data.get("source") or final_recipe
            elif name == "map_dependencies" and isinstance(data, list):
                mappings.extend(data)
            elif name == "diagnose_build_failure" and call.get("input", {}).get("log_text"):
                logs.append((call["input"]["log_text"], data))

        common = {"outcome": outcome, "source": f"session:{session_id}"}
        meta = {"feedback": note} if note else {}
        final_deps = summarize(final_recipe).dependency_names if final_recipe else set()

        for i, row in enumerate(mappings):
            if not row.get("spack"):
                continue
            target = spec_name(row["spack"])
            yield TrainingExample(
                id=f"{session_id}:map:{i}",
                task="dependency_mapping",
                input={"name": row["upstream"], "source": row["source"]},
                target=target,
                metadata={**meta, "resolved_by": "table" if row.get("resolved") else "guess",
                          "in_final_recipe": target in final_deps},
                **common,
            )
        if build_spec and final_recipe:
            yield TrainingExample(
                id=f"{session_id}:recipe",
                task="recipe_generation",
                input={"build_spec": build_spec},
                target=final_recipe,
                metadata=meta,
                **common,
            )
        for i, (log, diagnosis) in enumerate(logs):
            ids = [m["id"] for m in (diagnosis or {}).get("matches", [])]
            yield TrainingExample(
                id=f"{session_id}:diag:{i}",
                task="failure_diagnosis",
                input={"log": log},
                target=ids,
                metadata=meta,
                **common,
            )


class SpackRepoCollector:
    """Harvest recipes from a Spack package repository's packages/ directory.

    Each recipe becomes a recipe_generation example whose input is the recipe's own
    metadata. Pairing recipes with their *upstream build files* (fetch the source of
    the newest version, run analyze_build_system, use the BuildSpec as input) turns this
    into the main supervised corpus; that step needs network access and is left to a
    batch job.
    """

    def __init__(self, packages_dir: Path, limit: int | None = None):
        self.packages_dir = packages_dir
        self.limit = limit

    def collect(self) -> Iterator[TrainingExample]:
        for count, path in enumerate(sorted(self.packages_dir.glob("*/package.py"))):
            if self.limit is not None and count >= self.limit:
                return
            source = path.read_text(errors="replace")
            summary = summarize(source)
            if summary.syntax_error or not summary.class_name:
                continue
            package = path.parent.name.replace("_", "-")
            yield TrainingExample(
                id=f"spack-repo:{package}",
                task="recipe_generation",
                input={
                    "package": package,
                    "base_classes": summary.base_classes,
                    "homepage": summary.attributes.get("homepage"),
                    "url": summary.attributes.get("url") or summary.attributes.get("git"),
                },
                target=source,
                outcome="success",
                source=f"spack-repo:{package}",
                metadata={
                    "dependencies": sorted(summary.dependency_names),
                    "variants": summary.variants,
                    "versions": summary.versions[:5],
                },
            )


def _json(text: Any) -> Any:
    if not isinstance(text, str):
        return text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None
