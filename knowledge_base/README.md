# Knowledge base

This is the agent's reference library. The `search_knowledge` skill searches it, and
the agent is told to prefer it over its own general knowledge and to cite the files it
used. Anything you add here takes effect in the next session. No re-indexing step is
needed.

| Section | Put here |
|---|---|
| `spack_fundamentals/` | Spec syntax, variants, virtual packages, the concretizer, compilers as dependencies (Spack 1.x), mirrors, build caches, modules |
| `build_systems/` | How each upstream build system maps onto Spack: CMake, Autotools, Makefile, Meson, Python, Cargo/Go/Bazel... and their common pitfalls |
| `package_recipes/` | Exemplary `package.py` files (annotated) and recipe idioms: `when=` blocks, patches, `conflicts`, `flag_handler`, CUDA/ROCm mixins |
| `environments/` | `spack.yaml` patterns: unify, views, externals, requirements, stacks, `include` |
| `hpc_sites/` | One subdirectory per machine or center: compilers, MPI, modules, scheduler, filesystems, internet access on compute nodes |
| `troubleshooting/` | Failures you have hit and how they were fixed (one file per problem works well) |
| `structured/` | **Machine-readable tables loaded directly by skills** (not text-searched): `dependency_map.yaml`, `error_patterns.yaml` |

## Format

- Markdown (`.md`) is best. Headings become search context, so use them.
- Code files (`package.py`, `spack.yaml`, `CMakeLists.txt`, shell scripts) are indexed
  as-is. Put a short comment at the top saying what they illustrate.
- Keep one topic per file and give files descriptive names
  (`cuda-package-mixin.md`, `frontier-cray-mpich.md`).
- `README.md` files (like this one) are guides for contributors and are not indexed.

## Verify against your Spack version

The project defaults to Spack 1.x conventions: `spack_repo.builtin.build_systems`
imports, v2 repository layout, `depends_on("c")` language dependencies, and virtuals
such as `zlib-api`. If you run an older Spack, set `spack.target_version` in the config
and document the differences in `spack_fundamentals/`.

Check:

```bash
spack-ai kb stats
spack-ai kb search "makefile edit FileFilter"
```
