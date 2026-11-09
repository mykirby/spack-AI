### Job scripts (`generate_job_script`)

Many centers forbid long builds on login nodes, so default to a batch script when the
user is on a cluster. Partition and account names are site-specific: use the site
config or ask the user, and never guess them. If the build needs internet access
(fetching sources) and compute nodes are offline, tell the user to run
`spack fetch` / `spack mirror create` on a login node first.
