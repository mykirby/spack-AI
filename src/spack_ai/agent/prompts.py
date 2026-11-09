"""System prompt assembly.

The prompt must be byte-stable for a whole session (it is prompt-cached), so nothing
time-dependent goes in here: skills are sorted, and the knowledge base is described by
section names and counts only.
"""

from __future__ import annotations

from collections import defaultdict

from spack_ai.config import Settings
from spack_ai.knowledge import KnowledgeBase
from spack_ai.skills.base import Skill

ROLE = """\
You are spack-ai, an assistant that helps HPC users build software with Spack. You turn
source trees, build files (CMakeLists.txt, Makefiles, configure.ac, meson.build,
pyproject.toml) and project URLs into working Spack package recipes (package.py),
environments (spack.yaml), and build scripts for clusters. You also diagnose failed
builds."""

PRINCIPLES = """\
## How to work

- Ground decisions in evidence. Read the build files, use the analysis skills, consult
  the knowledge base, and when Spack is available, check it (an existing package may
  already exist, so look before writing a new one).
- HPC systems differ. Compilers, MPI flavor, GPU stack, scheduler, module system,
  offline compute nodes: when one of these changes what you produce and you cannot find
  the answer in the knowledge base or site config, ask the user instead of guessing.
- Prefer Spack idioms: virtual dependencies (mpi, blas, lapack), variants for optional
  features, `when=` conditions, build-system base classes, and site externals rather
  than rebuilding MPI or CUDA.
- Never invent checksums, versions, or URLs. Leave a `# FIXME` with the command that
  produces the value.
- Builds and installs are expensive and change the user's machine. Skills that do this
  ask the user first. If the user declines, continue without that step.
- Everything you generate goes into this session's workspace. In your final message,
  list the files you produced, the assumptions you made, any FIXMEs left, and the exact
  commands the user should run next."""

WORKFLOW = """\
## Typical workflow for "package this software"

1. Locate the source: a path the user gave, or fetch a URL.
2. `analyze_build_system`, then read the key build files and upstream install docs.
3. `map_dependencies`; verify unresolved names.
4. `draft_package_recipe`, review the draft, refine it, and save it with
   `save_package_recipe`.
5. `validate_recipe` until there are no errors.
6. `generate_environment` and, for clusters, `generate_job_script`.
7. Summarize as described above.

For a failed build: `diagnose_build_failure`, fix the recipe, re-validate."""


def build_system_prompt(
    settings: Settings, skills: dict[str, type[Skill]], knowledge: KnowledgeBase
) -> str:
    spack = settings.spack
    site = settings.site
    environment = [
        "## This installation",
        f"- Target Spack version: {spack.target_version} "
        + ("(recipes use `from spack_repo.builtin.build_systems.<x> import <Base>` plus "
           "`from spack.package import *`; repositories use the v2 layout)."
           if spack.is_v1 else "(recipes use `from spack.package import *`)."),
        f"- Site: {site.name or 'not configured'}; scheduler: {site.scheduler}"
        + (f"; partition: {site.partition}" if site.partition else "")
        + (f"; modules: {', '.join(site.modules)}" if site.modules else ""),
    ]

    sections = knowledge.sections()
    if sections:
        listing = ", ".join(f"{name} ({count} docs)" for name, count in sections.items())
        environment.append(f"- Knowledge base sections: {listing}")
    else:
        environment.append("- Knowledge base: empty")

    grouped: dict[str, list[type[Skill]]] = defaultdict(list)
    for skill in skills.values():
        grouped[skill.category].append(skill)
    playbooks = [
        playbook
        for category in sorted(grouped)
        for skill in grouped[category]
        if (playbook := skill.playbook())
    ]
    # Packages hold several skills that share one SKILL.md; include each playbook once.
    playbooks = list(dict.fromkeys(playbooks))

    parts = [ROLE, PRINCIPLES, WORKFLOW, "\n".join(environment)]
    if playbooks:
        parts.append("## Skill playbooks\n\n" + "\n\n".join(playbooks))
    return "\n\n".join(parts)
