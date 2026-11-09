"""The contract every trainable model implements.

Whatever ML software the project adopts (scikit-learn, PyTorch, a fine-tuned LLM
behind a server, ...) is wrapped in a TrainableModel subclass and registered with
@register_model. The trainer, the evals, and serving only see this interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, ClassVar

from spack_ai.ml.data.schema import Task, TrainingExample


class TrainableModel(ABC):
    name: ClassVar[str]
    task: ClassVar[Task]

    def __init__(self, **hyperparams: Any):
        self.hyperparams = hyperparams

    @abstractmethod
    def fit(
        self, train: list[TrainingExample], val: list[TrainingExample]
    ) -> dict[str, float]:
        """Train and return validation metrics."""

    @abstractmethod
    def predict(self, inputs: list[dict[str, Any]]) -> list[Any]:
        """One prediction per input, in the shape of TrainingExample.target."""

    @abstractmethod
    def save(self, directory: Path) -> None: ...

    @classmethod
    @abstractmethod
    def load(cls, directory: Path) -> TrainableModel: ...

    def evaluate(self, examples: list[TrainingExample]) -> dict[str, float]:
        """Default metric: exact-match accuracy. Override for structured targets."""
        from spack_ai.ml.evaluation.metrics import exact_match

        if not examples:
            return {"n": 0}
        predictions = self.predict([e.input for e in examples])
        return {"n": len(examples), "accuracy": exact_match(predictions,
                                                            [e.target for e in examples])}
