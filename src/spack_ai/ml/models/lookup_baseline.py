"""A frequency-table baseline for dependency mapping.

It exists to exercise the whole pipeline (collect -> train -> evaluate -> serve inside
map_dependencies) before the real model is chosen, and as the score to beat.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from spack_ai.ml.data.schema import TrainingExample
from spack_ai.ml.models import register_model
from spack_ai.ml.models.base import TrainableModel

SOURCE_GROUPS = {
    "find_package": "cmake", "macro": "cmake", "program": "cmake", "fetchcontent": "cmake",
    "pkg_config": "pkgconfig", "meson_dependency": "pkgconfig",
    "library": "library", "python_requirement": "python",
}


def _key(example_input: dict[str, Any]) -> tuple[str, str]:
    group = SOURCE_GROUPS.get(example_input.get("source", ""), "other")
    return group, str(example_input.get("name", "")).lower()


@register_model
class DependencyLookupModel(TrainableModel):
    name = "dependency_lookup"
    task = "dependency_mapping"

    def __init__(self, min_count: int = 1, **hyperparams: Any):
        super().__init__(min_count=min_count, **hyperparams)
        self.min_count = min_count
        self.table: dict[str, str] = {}      # "group|name" -> spack package
        self.by_name: dict[str, str] = {}    # name -> spack package, any source

    def fit(self, train: list[TrainingExample], val: list[TrainingExample]) -> dict[str, float]:
        keyed: dict[str, Counter[str]] = defaultdict(Counter)
        named: dict[str, Counter[str]] = defaultdict(Counter)
        for example in train:
            group, name = _key(example.input)
            keyed[f"{group}|{name}"][example.target] += 1
            named[name][example.target] += 1
        self.table = {k: c.most_common(1)[0][0] for k, c in keyed.items()
                      if c.most_common(1)[0][1] >= self.min_count}
        self.by_name = {k: c.most_common(1)[0][0] for k, c in named.items()
                        if c.most_common(1)[0][1] >= self.min_count}
        return self.evaluate(val)

    def predict(self, inputs: list[dict[str, Any]]) -> list[str | None]:
        out = []
        for item in inputs:
            group, name = _key(item)
            out.append(self.table.get(f"{group}|{name}") or self.by_name.get(name))
        return out

    def save(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "lookup.json").write_text(json.dumps(
            {"hyperparams": self.hyperparams, "table": self.table, "by_name": self.by_name},
            indent=2, sort_keys=True,
        ))

    @classmethod
    def load(cls, directory: Path) -> DependencyLookupModel:
        data = json.loads((directory / "lookup.json").read_text())
        model = cls(**data["hyperparams"])
        model.table, model.by_name = data["table"], data["by_name"]
        return model
