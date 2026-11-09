from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Task = Literal[
    "dependency_mapping",      # upstream name + source kind -> Spack package
    "recipe_generation",       # BuildSpec (or build files) -> package.py
    "environment_generation",  # requirements + site -> spack.yaml
    "failure_diagnosis",       # build log -> failure category / fix
]
Outcome = Literal["success", "failure", "unknown"]


class TrainingExample(BaseModel):
    id: str
    task: Task
    input: dict[str, Any]
    target: Any
    outcome: Outcome = "unknown"
    source: str = Field(description="Provenance: session:<id>, spack-repo:<name>, manual, ...")
    metadata: dict[str, Any] = Field(default_factory=dict)
