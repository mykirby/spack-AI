from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

from spack_ai.ml.data.schema import TrainingExample


@dataclass
class Split:
    train: list[TrainingExample]
    val: list[TrainingExample]
    test: list[TrainingExample]


class Dataset:
    """An in-memory list of examples with JSONL persistence and deterministic splits."""

    def __init__(self, examples: Iterable[TrainingExample] = ()):
        self.examples = list(examples)

    def __len__(self) -> int:
        return len(self.examples)

    def __iter__(self) -> Iterator[TrainingExample]:
        return iter(self.examples)

    @classmethod
    def load(cls, path: Path) -> Dataset:
        with path.open() as fh:
            return cls(TrainingExample.model_validate_json(line) for line in fh if line.strip())

    def save(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w") as fh:
            for example in self.examples:
                fh.write(example.model_dump_json() + "\n")
        return path

    def filter(self, predicate: Callable[[TrainingExample], bool]) -> Dataset:
        return Dataset(e for e in self.examples if predicate(e))

    def deduplicate(self) -> Dataset:
        seen: dict[str, TrainingExample] = {}
        for example in self.examples:
            key = json.dumps([example.task, example.input, example.target], sort_keys=True,
                             default=str)
            seen.setdefault(key, example)
        return Dataset(seen.values())

    def split(self, val: float = 0.1, test: float = 0.1, seed: int = 13) -> Split:
        """Hash-based split: an example stays in the same split as the dataset grows."""
        out = Split([], [], [])
        for example in self.examples:
            digest = hashlib.sha256(f"{seed}:{example.id}".encode()).digest()
            bucket = int.from_bytes(digest[:8], "big") / 2**64
            if bucket < test:
                out.test.append(example)
            elif bucket < test + val:
                out.val.append(example)
            else:
                out.train.append(example)
        return out

    def stats(self) -> dict[str, dict[str, int]]:
        return {
            "task": dict(Counter(e.task for e in self.examples)),
            "outcome": dict(Counter(e.outcome for e in self.examples)),
            "source": dict(Counter(e.source.split(":", 1)[0] for e in self.examples)),
        }
