# Evals

Benchmarks that score generated recipes. They use the same metrics as ML training
(`spack_ai.ml.evaluation.metrics`).

```bash
spack-ai eval            # deterministic pipeline: free, offline
spack-ai eval --agent    # full LLM agent per case: costs API tokens
spack-ai eval --json     # machine-readable
```

## Adding a case

```text
evals/cases/<case-name>/
    case.yaml        # required
    source/          # the source tree (or point `source:` elsewhere)
    reference.py     # optional known-good package.py
```

```yaml
package: heat-solver            # Spack package name to generate
source: source                  # relative to the case dir
prompt: "..."                   # optional custom prompt for --agent
expected:
  build_system: cmake
  base_class: CMakePackage
  dependencies: [mpi, hdf5]     # Spack names; language deps (c/cxx/fortran) are ignored
  variants: [mpi]
```

With `reference.py`, missing expectations are derived from it, which makes it easy to
turn real Spack packages into cases. Copy the upstream release's build files into
`source/` and the builtin recipe into `reference.py`.

The current cases are small synthetic fixtures (shared with `tests/fixtures/`) that check
the plumbing. Real packages with reference recipes are the next thing to add.
