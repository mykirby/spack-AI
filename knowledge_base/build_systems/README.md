# build_systems

One file per upstream build system: how it maps onto a Spack base class and which
overrides are typical. Suggested files:

- `cmake.md`: CMakePackage, `cmake_args`, `define_from_variant`, FetchContent, CMAKE_PREFIX_PATH
- `autotools.md`: AutotoolsPackage, `configure_args`, `enable_or_disable`, `with_or_without`, autoreconf
- `makefile.md`: MakefilePackage, `edit()` with FileFilter, `build_targets`, `install()`, make.inc files
- `meson.md`, `python.md` (PythonPackage, pypi=, build backends), `cargo.md`, `go.md`, ...
- `custom.md`: generic `Package` with hand-written `install()`
