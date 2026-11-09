import ast

import yaml

from spack_ai.pipeline import generate
from spack_ai.schemas import VersionEntry
from spack_ai.skills.validation import static_checks

SHA = "a" * 64


def test_cmake_recipe(fixtures, settings):
    result = generate(
        fixtures / "cmake_project", settings, name="heat-solver",
        url="https://example.org/heat-2.1.0.tar.gz",
        versions=[VersionEntry(version="2.1.0", sha256=SHA)],
    )
    src = result.recipe_source
    ast.parse(src)
    assert "class HeatSolver(CMakePackage):" in src
    assert "from spack_repo.builtin.build_systems.cmake import CMakePackage" in src
    for line in [
        'version("2.1.0", sha256="' + SHA + '")',
        'variant("mpi", default=True, description="Build with MPI support")',
        'depends_on("c", type="build")',
        'depends_on("fortran", type="build")',
        'depends_on("cmake@3.18:", type="build")',
        'depends_on("mpi@3.0:", when="+mpi")',
        'depends_on("boost@1.70:+filesystem+program_options")',
        'depends_on("fftw-api")',
        'self.define_from_variant("HEAT_ENABLE_MPI", "mpi")',
        'self.define("BUILD_TESTING", self.run_tests)',
    ]:
        assert line in src, line
    assert "OpenMP" not in src and "werror" not in src.lower()
    assert result.errors == []
    # v2 repository layout
    assert result.recipe_path.parts[-5:] == (
        "spack_repo", "spack_ai_local", "packages", "heat_solver", "package.py")
    env = yaml.safe_load(result.env_path.read_text())["spack"]
    assert env["specs"] == ["heat-solver"] and env["repos"][0].endswith("spack_ai_local")
    script = result.script_path.read_text()
    assert "#SBATCH" in script and "spack install" in script


def test_legacy_imports(fixtures, settings):
    settings.spack.target_version = "0.23"
    result = generate(fixtures / "cmake_project", settings, environment=False)
    assert "spack_repo" not in result.recipe_source
    assert result.recipe_path.parts[-4:] == ("repo", "packages", "heatsolver", "package.py")


def test_makefile_recipe(fixtures, settings):
    src = generate(fixtures / "makefile_project", settings, environment=False).recipe_source
    ast.parse(src)
    assert "f\"CC = {spec['mpi'].mpicc}\"" in src
    assert 'f"PREFIX = {prefix}"' in src
    assert 'targets.append("USE_HDF5=1")' in src
    assert 'depends_on("hdf5", when="+hdf5")' in src
    assert "def install" not in src  # PREFIX is rewritten, so the default install works


def test_autotools_recipe(fixtures, settings):
    src = generate(fixtures / "autotools_project", settings, environment=False).recipe_source
    ast.parse(src)
    assert 'self.with_or_without("zlib", activation_value="prefix")' in src
    assert '"--enable-shared-memory" if self.spec.satisfies("+shared_memory")' in src
    assert 'depends_on("zlib-api", when="+zlib")' in src
    assert 'depends_on("libtool", type="build")' in src


def test_meson_and_python_recipes(fixtures, settings):
    meson = generate(fixtures / "meson_project", settings, environment=False).recipe_source
    assert '"-Dcairo=" + ("enabled"' in meson and 'depends_on("cairo", when="+cairo")' in meson
    python = generate(fixtures / "python_project", settings, environment=False).recipe_source
    assert "class PySpackToolkit(PythonPackage):" in python
    assert 'depends_on("py-matplotlib@3.5:", type=("build", "run"), when="+plot")' in python
    assert 'depends_on("c", type="build")' not in python


def test_static_checks_catch_mistakes():
    bad = '''
from spack.package import *

class Wrong(CMakePackage):
    homepage = "https://x.org"
    url = "https://x.org/x-1.0.tar.gz"
    version("1.0")
    depends_on("mpi", when="+mpi")
    def cmake_args(self):
        return [self.define_from_variant("USE_CUDA", "cuda")]
'''
    messages = [f.text for f in static_checks(bad, "right") if f.level == "error"]
    assert any("Class must be named Right" in m for m in messages)
    assert any("no sha256" in m for m in messages)
    assert any("undeclared variant 'mpi'" in m for m in messages)
    assert any("undeclared variant 'cuda'" in m for m in messages)
    assert static_checks("class (", "x")[0].message.startswith("Python syntax error")
