"""Configuration: config/default.yaml, an optional site file, and environment overrides."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = REPO_ROOT / "config" / "default.yaml"


class LLMConfig(BaseModel):
    provider: str = "anthropic"
    model: str = "claude-opus-5-5"
    max_tokens: int = 64000
    effort: Literal["low", "medium", "high", "xhigh", "max"] = "high"
    fallbacks: str | None = "default"


class AgentConfig(BaseModel):
    max_turns: int = 40
    auto_approve: bool = False


class PathsConfig(BaseModel):
    knowledge_base: Path = Path("knowledge_base")
    data_dir: Path = Path("data")
    output_dir: Path = Path("output")


class SpackConfig(BaseModel):
    executable: str | None = None
    target_version: str = "1.0"
    command_timeout: int = 900

    @property
    def is_v1(self) -> bool:
        major = self.target_version.split(".", 1)[0]
        return major.isdigit() and int(major) >= 1


class KnowledgeConfig(BaseModel):
    chunk_size: int = 1500
    chunk_overlap: int = 200
    top_k: int = 6


class RecipeConfig(BaseModel):
    namespace: str = "spack_ai_local"
    maintainers: list[str] = Field(default_factory=list)


class SiteConfig(BaseModel):
    name: str | None = None
    scheduler: Literal["slurm", "pbs", "lsf", "none"] = "slurm"
    partition: str | None = None
    account: str | None = None
    modules: list[str] = Field(default_factory=list)
    build_jobs: int = 16


class MLConfig(BaseModel):
    dependency_model: Path | None = None


class Settings(BaseModel):
    llm: LLMConfig = Field(default_factory=LLMConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    spack: SpackConfig = Field(default_factory=SpackConfig)
    knowledge: KnowledgeConfig = Field(default_factory=KnowledgeConfig)
    recipe: RecipeConfig = Field(default_factory=RecipeConfig)
    site: SiteConfig = Field(default_factory=SiteConfig)
    ml: MLConfig = Field(default_factory=MLConfig)
    root: Path = REPO_ROOT

    def resolve(self, path: Path | str) -> Path:
        """Resolve a configured path against the repository root."""
        path = Path(path).expanduser()
        return path if path.is_absolute() else (self.root / path).resolve()

    @property
    def knowledge_dir(self) -> Path:
        return self.resolve(self.paths.knowledge_base)

    @property
    def data_dir(self) -> Path:
        return self.resolve(self.paths.data_dir)

    @property
    def output_dir(self) -> Path:
        return self.resolve(self.paths.output_dir)

    @property
    def sessions_dir(self) -> Path:
        return self.data_dir / "sessions"


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open() as fh:
        return yaml.safe_load(fh) or {}


def load_settings(path: Path | str | None = None) -> Settings:
    """Load default.yaml, layer a site config (argument or $SPACK_AI_CONFIG) on top,
    then apply environment overrides."""
    data = _read_yaml(DEFAULT_CONFIG) if DEFAULT_CONFIG.exists() else {}
    site_path = path or os.environ.get("SPACK_AI_CONFIG")
    if site_path:
        data = _deep_merge(data, _read_yaml(Path(site_path).expanduser()))

    if model := os.environ.get("SPACK_AI_MODEL"):
        data.setdefault("llm", {})["model"] = model
    if (spack_root := os.environ.get("SPACK_ROOT")) and not data.get("spack", {}).get("executable"):
        candidate = Path(spack_root) / "bin" / "spack"
        if candidate.exists():
            data.setdefault("spack", {})["executable"] = str(candidate)

    return Settings.model_validate(data)
