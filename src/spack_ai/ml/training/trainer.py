"""Train a registered model on a JSONL dataset and checkpoint the run.

A run directory (data/runs/<timestamp>-<model>/) holds:
    run.json     config, dataset stats, validation and test metrics
    model/       whatever TrainableModel.save writes
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from spack_ai.config import Settings
from spack_ai.ml.data.dataset import Dataset
from spack_ai.ml.data.schema import Outcome
from spack_ai.ml.models import get_model


class TrainingConfig(BaseModel):
    model: str = Field(description="Registered model name (spack-ai ml models).")
    dataset: Path = Field(description="JSONL dataset produced by `spack-ai ml collect`.")
    hyperparams: dict[str, Any] = Field(default_factory=dict)
    outcomes: list[Outcome] = Field(
        default_factory=lambda: ["success", "unknown"],
        description="Keep only examples with these outcomes.",
    )
    require_metadata: dict[str, Any] = Field(
        default_factory=dict, description="Keep only examples whose metadata matches these values."
    )
    val_fraction: float = 0.1
    test_fraction: float = 0.1
    seed: int = 13
    output_dir: Path = Path("data/runs")

    @classmethod
    def from_yaml(cls, path: Path) -> TrainingConfig:
        return cls.model_validate(yaml.safe_load(path.read_text()))


@dataclass
class TrainingRun:
    directory: Path
    metrics: dict[str, Any]


def train(config: TrainingConfig, settings: Settings) -> TrainingRun:
    model_cls = get_model(config.model)
    dataset = Dataset.load(settings.resolve(config.dataset)).filter(
        lambda e: e.task == model_cls.task
        and e.outcome in config.outcomes
        and all(e.metadata.get(k) == v for k, v in config.require_metadata.items())
    ).deduplicate()
    if not len(dataset):
        raise ValueError(f"No {model_cls.task} examples in {config.dataset} after filtering.")

    split = dataset.split(config.val_fraction, config.test_fraction, config.seed)
    model = model_cls(**config.hyperparams)
    val_metrics = model.fit(split.train, split.val)
    test_metrics = model.evaluate(split.test)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    directory = settings.resolve(config.output_dir) / f"{stamp}-{config.model}"
    model.save(directory / "model")
    metrics = {
        "counts": {"train": len(split.train), "val": len(split.val), "test": len(split.test)},
        "val": val_metrics,
        "test": test_metrics,
    }
    (directory / "run.json").write_text(json.dumps(
        {"model": config.model, "task": model_cls.task,
         "config": config.model_dump(mode="json"), "dataset_stats": dataset.stats(),
         "metrics": metrics},
        indent=2,
    ))
    return TrainingRun(directory, metrics)
