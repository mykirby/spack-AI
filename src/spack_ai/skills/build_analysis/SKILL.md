### Build analysis (`analyze_build_system`)

Run this first on any source tree or build file the user provides. It is a static,
heuristic parse, so treat its output as a starting point:

- Read the build files yourself (`read_source_file`) when the analysis reports
  conditions it could not resolve, options with unclear meaning, or notes.
- `condition` on a dependency is the upstream guard (e.g. `ENABLE_MPI`). These usually
  become `when="+variant"` clauses.
- `fetchcontent` dependencies are downloaded at configure time. HPC compute nodes are
  often offline, so prefer real `depends_on()` edges.
- Hand-written Makefiles almost always need an `edit()` that injects Spack's compilers
  and the install prefix. Check `compiler_variables`, `prefix_variable`, and `includes`
  in the metadata.
- If the project bundles third-party code (vendored dirs), prefer the Spack package
  and look for an upstream switch that disables the bundled copy.
