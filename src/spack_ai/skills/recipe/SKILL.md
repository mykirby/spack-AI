### Package recipes (`draft_package_recipe`, `save_package_recipe`)

1. Call `draft_package_recipe` after analysis. Pass whatever you already know: name,
   homepage, url/git, versions with checksums, variants or dependencies to add or drop.
2. Read the returned source critically and fix what the heuristics could not know: which
   options deserve variants, `when=` conditions, CUDA/ROCm mixins (`CudaPackage`,
   `ROCmPackage`), `conflicts()`, patches, and `edit()`/`install()` logic for Makefiles.
   Then call `save_package_recipe` with the full file.
3. Keep every placeholder you cannot fill as a `# FIXME` comment so the user can find it.
   Do not invent a sha256. Leave the `spack checksum` hint in place.

Conventions:
- Package names are lowercase with dashes. Python distributions get the `py-` prefix.
- Spack 1.x recipes declare the languages they compile:
  `depends_on("c", type="build")`, `"cxx"`, `"fortran"`.
- Use `self.define_from_variant()` in `cmake_args`. Use `enable_or_disable()` /
  `with_or_without()` in `configure_args`.
- Prefer `depends_on("mpi")` over a specific implementation, and make it conditional on
  `+mpi` when MPI is optional upstream.
