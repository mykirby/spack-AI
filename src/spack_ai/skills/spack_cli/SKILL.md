### Spack CLI (`spack_command`)

When Spack is available, use it to ground your work:
- `list <name>` / `info <name>`: does a package already exist? If it does, the user
  may only need an environment, not a new recipe.
- `providers mpi`: which implementations exist.
- `checksum <pkg> <version>`: real sha256 values for `version()`.
- `-D <env dir> spec`: does the environment concretize?

`install` is expensive and changes the machine, so propose it and run it only after the
user confirms. Prefer handing them the generated job script.
