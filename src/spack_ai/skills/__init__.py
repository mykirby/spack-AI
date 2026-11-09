"""Skill registry.

Every subpackage of spack_ai.skills is imported on first use; modules register their
skills with the @register decorator. To add a skill, create a subpackage with a
skill.py (and optionally a SKILL.md playbook) and import it from the subpackage's
__init__.py. See docs/ARCHITECTURE.md.
"""

from __future__ import annotations

import importlib
import pkgutil

from spack_ai.skills.base import Skill, SkillContext, SkillError

__all__ = ["Skill", "SkillContext", "SkillError", "register", "all_skills", "get_skill"]

_REGISTRY: dict[str, type[Skill]] = {}
_loaded = False


def register(cls: type[Skill]) -> type[Skill]:
    if cls.name in _REGISTRY and _REGISTRY[cls.name] is not cls:
        raise ValueError(f"duplicate skill name: {cls.name}")
    _REGISTRY[cls.name] = cls
    return cls


def _load_builtin() -> None:
    global _loaded
    if _loaded:
        return
    for module in pkgutil.iter_modules(__path__):
        if module.ispkg:
            importlib.import_module(f"{__name__}.{module.name}")
    _loaded = True


def all_skills() -> dict[str, type[Skill]]:
    """Registered skills, sorted by name so tool order (and the prompt cache) is stable."""
    _load_builtin()
    return dict(sorted(_REGISTRY.items()))


def get_skill(name: str) -> type[Skill]:
    skills = all_skills()
    if name not in skills:
        raise KeyError(f"unknown skill {name!r}; known: {', '.join(skills)}")
    return skills[name]
