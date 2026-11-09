"""Model registry. Add a model by subclassing TrainableModel in a module here,
decorating it with @register_model, and importing the module in _load_builtin()."""

from __future__ import annotations

from spack_ai.ml.models.base import TrainableModel

__all__ = ["TrainableModel", "register_model", "get_model", "all_models"]

_REGISTRY: dict[str, type[TrainableModel]] = {}


def register_model(cls: type[TrainableModel]) -> type[TrainableModel]:
    _REGISTRY[cls.name] = cls
    return cls


def _load_builtin() -> None:
    from spack_ai.ml.models import lookup_baseline  # noqa: F401


def all_models() -> dict[str, type[TrainableModel]]:
    _load_builtin()
    return dict(sorted(_REGISTRY.items()))


def get_model(name: str) -> type[TrainableModel]:
    models = all_models()
    if name not in models:
        raise KeyError(f"unknown model {name!r}; registered: {', '.join(models) or 'none'}")
    return models[name]
