# spack-AI: notes for Claude Code sessions

An agent that writes Spack recipes/environments/job scripts. Read docs/ARCHITECTURE.md first.

- Env: `.venv/` (uv). Run `.venv/bin/python -m pytest -q` and `.venv/bin/ruff check src tests` after changes.
- Every capability is a `Skill` in `src/spack_ai/skills/<pkg>/` (pydantic `Input`, `run() -> SkillResult`,
  optional `SKILL.md` playbook folded into the system prompt). The registry auto-discovers subpackages.
- Knowledge the user provides goes in `knowledge_base/<section>/` (text, searched) or
  `knowledge_base/structured/*.yaml` (tables loaded by skills). Don't hard-code domain facts in Python
  when a table or doc can hold them.
- The system prompt must stay byte-stable within a session (prompt caching): no timestamps or
  unsorted collections in `agent/prompts.py`.
- Generated recipes target Spack 1.x conventions by default (`spack.target_version`); keep the legacy
  path (`from spack.package import *` only, v1 repo layout) working.
- The ML software is not chosen yet; new models implement `ml/models/base.py::TrainableModel`.
