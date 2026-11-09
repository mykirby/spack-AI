# hpc_sites

One subdirectory per machine or center, for example `hpc_sites/frontier/`. Useful contents:

- `overview.md`: architecture (CPU/GPU), OS, scheduler, partitions, account conventions
- `compilers-and-mpi.md`: available compilers and MPI, which modules provide them
- `packages.yaml` / `compilers.yaml`: externals and compiler definitions that work there
- `gotchas.md`: offline compute nodes, filesystem quotas, where to put build_stage

Pair each site with a config file (copy `config/default.yaml`, fill in `site:`) and run
`spack-ai --config config/sites/<name>.yaml chat`.
