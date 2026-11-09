### Dependency mapping (`map_dependencies`)

- Prefer virtual packages (`mpi`, `blas`, `lapack`, `fftw-api`, `zlib-api`, `jpeg`) over
  concrete providers, so the site can pick OpenMPI, MPICH, Cray MPICH, MKL, and so on.
- `spack: null` results (OpenMP, pthreads, libm) need no `depends_on`.
- Verify every `resolved: false` guess with `spack_command` (`list <name>`, `info <name>`)
  when Spack is available. Otherwise search the knowledge base, and say plainly which names
  are still unverified.
- Build-only tools (cmake, pkgconfig, bison, swig, doxygen) get `type="build"`, test
  frameworks `type="test"`, and Python runtime dependencies `type=("build", "run")`.
- When the user corrects a mapping, tell them it can be added to
  `knowledge_base/structured/dependency_map.yaml` so the fix sticks.
