# spack_fundamentals

Core Spack concepts the agent must get right. Suggested files:

- `spec-syntax.md`: `@` versions and ranges, `+`/`~` variants, `%` compilers, `^` dependencies, `key=value`
- `virtual-packages.md`: mpi, blas, lapack, fftw-api, zlib-api, ... and how providers are chosen
- `compilers-as-dependencies.md`: Spack 1.x `depends_on("c"/"cxx"/"fortran")`, toolchains
- `concretizer.md`: unify, reuse, requirements vs preferences, reading UNSAT errors
- `directives.md`: version, variant, depends_on, conflicts, requires, provides, patch, resource
- `repositories.md`: repo layout (v2 for Spack 1.x), namespaces, `spack repo create`
