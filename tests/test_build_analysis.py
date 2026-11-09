from spack_ai.schemas import BuildSystem
from spack_ai.skills.build_analysis import analyze_path, detect
from spack_ai.skills.build_analysis.base import variant_name


def deps(spec):
    return {d.name: d for d in spec.dependencies}


def test_cmake(fixtures):
    spec = analyze_path(fixtures / "cmake_project")
    assert spec.build_system == BuildSystem.CMAKE
    assert (spec.project_name, spec.version) == ("HeatSolver", "2.1.0")
    assert spec.languages[:3] == ["c", "cxx", "fortran"]
    assert spec.build_tool_version == "3.18:"
    d = deps(spec)
    assert d["MPI"].condition == "HEAT_ENABLE_MPI" and d["MPI"].version_constraint == "3.0:"
    assert d["HDF5"].components == ["C", "HL"]
    assert d["Boost"].components == ["filesystem", "program_options"]
    assert d["fftw3"].source == "pkg_config" and d["fftw3"].version_constraint == "3.3:"
    assert "ZLIB" in d                      # found in src/CMakeLists.txt
    assert "NotARealDependency" not in d    # only mentioned in a comment
    assert "Bundled" not in d               # third_party/ is skipped
    variants = {o.name: o.variant for o in spec.options}
    assert variants == {"HEAT_ENABLE_MPI": "mpi", "HEAT_USE_HDF5": "hdf5",
                        "BUILD_SHARED_LIBS": "shared", "HEAT_WERROR": None}
    assert spec.has_install_target and spec.metadata["testing"]
    assert spec.metadata["vendored_dirs"] == ["third_party"]


def test_single_file_detection(fixtures):
    analyzer, root, files = detect(fixtures / "cmake_project" / "CMakeLists.txt")
    assert analyzer.build_system == BuildSystem.CMAKE and files and root.name == "cmake_project"


def test_makefile(fixtures):
    spec = analyze_path(fixtures / "makefile_project")
    assert spec.build_system == BuildSystem.MAKEFILE
    d = deps(spec)
    assert set(d) == {"MPI", "fftw3", "m", "lapack", "blas", "hdf5"}
    assert d["hdf5"].condition == "USE_HDF5"
    assert spec.metadata["compiler_variables"] == {"CC": "mpicc", "FC": "gfortran"}
    assert spec.metadata["prefix_variable"] == "PREFIX"
    assert spec.has_install_target
    assert [o.variant for o in spec.options] == ["hdf5"]


def test_autotools(fixtures):
    spec = analyze_path(fixtures / "autotools_project")
    assert spec.build_system == BuildSystem.AUTOTOOLS
    assert (spec.project_name, spec.version) == ("libwidget", "0.9.1")
    assert spec.languages == ["c", "cxx"]            # bare AC_PROG_CC / AC_PROG_CXX
    d = deps(spec)
    assert {"z", "glib-2.0", "MPI", "libtool", "automake"} <= set(d)
    assert d["glib-2.0"].version_constraint == "2.56:"
    assert {o.name: o.kind for o in spec.options} == {"shared-memory": "enable", "zlib": "with"}
    assert spec.metadata["needs_autoreconf"]


def test_meson(fixtures):
    spec = analyze_path(fixtures / "meson_project")
    assert spec.build_system == BuildSystem.MESON
    d = deps(spec)
    assert set(d) == {"zlib", "libpng", "cairo"}     # threads needs no dependency
    assert d["cairo"].condition == "cairo" and not d["cairo"].required
    assert d["libpng"].version_constraint == "1.6:"
    assert spec.build_tool_version == "0.60.0:"


def test_python(fixtures):
    spec = analyze_path(fixtures / "python_project")
    assert spec.build_system == BuildSystem.PYTHON
    d = deps(spec)
    assert d["numpy"].version_constraint == "1.22:1"
    assert d["matplotlib"].condition == "plot"
    assert "wheel" not in d and d["setuptools"].dep_types == ["build"]


def test_unknown(tmp_path):
    (tmp_path / "main.c").write_text("int main(){}")
    spec = analyze_path(tmp_path)
    assert spec.build_system == BuildSystem.UNKNOWN and spec.languages == ["c"]


def test_variant_names():
    assert variant_name("ENABLE_MPI") == "mpi"
    assert variant_name("FOO_USE_CUDA") == "cuda"
    assert variant_name("BUILD_SHARED_LIBS") == "shared"
    assert variant_name("BUILD_TESTING") is None
    assert variant_name("CMAKE_CXX_STANDARD") is None
    assert variant_name("MYLIB_OPENMP_SUPPORT", project="mylib") == "openmp"
