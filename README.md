# spack-AI

An AI agent that helps HPC users build software with [Spack](https://spack.io). Give it
a source tree, a single `CMakeLists.txt`/`Makefile`/`configure.ac`, or a project URL. It
analyzes the build system, maps dependencies to Spack packages, and writes:

- a **`package.py`** recipe in a local Spack repository,
- a **`spack.yaml`** environment (with site externals such as system MPI/CUDA),
- a **batch build script** (Slurm, PBS, or LSF),

and it diagnoses failed builds. An ML framework learns from every session.

## Quick start

```bash
uv venv && source .venv/bin/activate        # or python -m venv .venv
uv pip install -e ".[dev]"

# No LLM needed:
spack-ai analyze path/to/source              # what build system, deps, options?
spack-ai generate path/to/source --name mypkg  # recipe + spack.yaml + build script

# With the agent (needs Claude API access: `ant auth login` or ANTHROPIC_API_KEY):
spack-ai chat --path path/to/source
spack-ai run "Package this for our Slurm cluster, MPI is cray-mpich" --path path/to/source
```

Outputs go to `output/<session>/`:

```text
repo/spack_repo/spack_ai_local/packages/<pkg>/package.py
envs/default/spack.yaml
scripts/build-default.sh
```

On the cluster: `sbatch output/<session>/scripts/build-default.sh`.

## Commands

| Command | Description |
| --- | --- |
| `spack-ai chat` / `run` | Agent session (interactive / one-shot), `--path` for source trees, `--yes` to skip approvals |
| `spack-ai analyze` / `generate` | Offline analysis and deterministic generation |
| `spack-ai skills` | List the agent's skills |
| `spack-ai kb stats` / `kb search` | Inspect the knowledge base |
| `spack-ai feedback <session> --outcome success\|failure` | Label a session for training |
| `spack-ai eval [--agent]` | Score recipe generation on `evals/cases` |
| `spack-ai ml collect` / `train` / `models` | ML pipeline |

All commands take `--config site.yaml` to layer site settings over `config/default.yaml`.

## Project layout

```text
config/            default.yaml, training configs (add per-site configs here)
knowledge_base/    the agent's reference library (curate this!) + structured tables
src/spack_ai/
  agent/           tool-use loop, system prompt, session transcripts
  llm/             provider interface + Claude implementation
  skills/          one subpackage per capability (+ SKILL.md playbooks)
  knowledge/       loader, chunker, BM25 retriever
  ml/              datasets, collectors, model registry, trainer, metrics, serving
  pipeline.py      deterministic skill chain (no LLM)
  evals.py         benchmark harness
evals/cases/       benchmark cases
tests/             unit + integration tests (no network, no API key needed)
docs/              ARCHITECTURE.md
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for how the pieces fit together and
where to extend them.

## Development

```bash
pytest          # ~60 tests, about a second, no network
ruff check src tests
```
