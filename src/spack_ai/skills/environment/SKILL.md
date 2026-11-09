### Environments (`generate_environment`)

On HPC systems, reuse what the site provides instead of rebuilding it. Ask the user, or
check `knowledge_base/hpc_sites/`, for:
- the system MPI (Cray MPICH, vendor OpenMPI) → an external with `buildable: false`
- the CUDA/ROCm installation → an external
- the compilers and modules that must be loaded

`unify: true` gives one consistent stack, which is the right default for a single
application. Use `when_possible` only when root specs genuinely conflict.
