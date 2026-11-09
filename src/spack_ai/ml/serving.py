"""Load trained runs for use inside skills.

Current integration point: `ml.dependency_model` in the config makes map_dependencies
consult the model for names the curated table does not know. A generative model
(e.g. a fine-tuned LLM) would instead be served behind an LLMProvider
(spack_ai.llm.get_provider).
"""

from __future__ import annotations

import json
from pathlib import Path

from spack_ai.ml.models import TrainableModel, get_model


def load_model(run_dir: Path) -> TrainableModel:
    run = json.loads((run_dir / "run.json").read_text())
    return get_model(run["model"]).load(run_dir / "model")
