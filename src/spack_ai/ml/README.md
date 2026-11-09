# ML framework

The scaffolding for training models that make the agent better. The ML software itself
has not been chosen yet. Everything here is built so it can be plugged in without
touching the rest of the system.

## Pieces

| Module | Role |
|---|---|
| `data/schema.py` | `TrainingExample`: `task`, `input`, `target`, `outcome`, `source`, `metadata` |
| `data/dataset.py` | JSONL persistence, filtering, de-duplication, and hash-based splits that stay stable as data grows |
| `data/collector.py` | `SessionCollector` (agent transcripts + feedback) and `SpackRepoCollector` (existing Spack recipes) |
| `models/base.py` | `TrainableModel`: `fit`, `predict`, `save`, `load`, `evaluate` |
| `models/lookup_baseline.py` | `dependency_lookup`, a frequency-table baseline that proves the pipeline end to end |
| `training/trainer.py` | `TrainingConfig` (YAML) → filter → split → fit → test → `data/runs/<stamp>-<model>/` |
| `evaluation/metrics.py` | Metrics shared with `spack-ai eval`: exact match, set precision/recall/F1, `recipe_scores` |
| `serving.py` | `load_model(run_dir)`, used by `map_dependencies` when `ml.dependency_model` is set |

## Tasks

- `dependency_mapping`: upstream name and source kind → Spack package. Directly usable
  today through the mapper hook.
- `recipe_generation`: BuildSpec (or raw build files) → `package.py`. This is the main
  target for a fine-tuned generative model.
- `environment_generation`: requirements and site → `spack.yaml`.
- `failure_diagnosis`: build log → failure category and fix.

## Workflow

```bash
spack-ai chat --path ~/src/some-code       # use the agent; every session is logged
spack-ai feedback <session-id> --outcome success
spack-ai ml collect                         # -> data/datasets/sessions.jsonl
spack-ai ml collect --spack-repo ~/spack-packages/repos/spack_repo/builtin/packages
spack-ai ml train config/training/dependency_baseline.yaml
# then in your config:  ml: { dependency_model: data/runs/<run> }
```

## Plugging in the real ML software

1. Add its packages to the `ml` extra in `pyproject.toml`.
2. Create `models/<name>.py` with a `TrainableModel` subclass decorated with
   `@register_model`, and import it in `models/__init__.py::_load_builtin`.
3. Write a training config in `config/training/`.
4. Integrate it:
   - **Predictive model** (classification, ranking, mapping): call it from the relevant
     skill, following `ml.dependency_model` in `skills/dependency_mapping/skill.py`.
   - **Generative model** (writes recipes or text): serve it behind an `LLMProvider`
     (`spack_ai/llm/base.py`) and select it with `llm.provider`. The agent, skills, and
     evals then work unchanged.
5. Compare it against the baseline and the Claude agent with `spack-ai eval`.

## Data notes

- Session examples carry `outcome` from user feedback and `metadata.in_final_recipe`,
  so training can keep only mappings that survived into an accepted recipe.
- The strongest supervised corpus for `recipe_generation` is the Spack package
  repository itself: pair each recipe with its upstream source (fetch the newest version,
  run `analyze_build_system`) to get (BuildSpec → package.py) pairs. `SpackRepoCollector`
  harvests the recipe side. The fetch-and-analyze batch job is the next step.
