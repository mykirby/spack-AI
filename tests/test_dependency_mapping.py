import pytest

from spack_ai.schemas import DetectedDependency
from spack_ai.skills.dependency_mapping import DependencyMapper


@pytest.fixture
def mapper(ctx):
    return DependencyMapper(ctx.knowledge.structured("dependency_map"))


def resolve(mapper, name, source="find_package", **kw):
    return mapper.resolve(DetectedDependency(name=name, source=source, **kw))


def test_components_and_versions(mapper):
    boost = resolve(mapper, "Boost", version_constraint="1.70:", components=["filesystem"])
    assert boost.spack_spec == "boost@1.70:+filesystem" and boost.resolved
    hdf5 = resolve(mapper, "HDF5", components=["C", "HL"])
    assert hdf5.spack_spec == "hdf5+hl"


def test_virtuals(mapper):
    mpi = resolve(mapper, "MPI", version_constraint="3.0:")
    assert mpi.virtual and mpi.spack_spec == "mpi@3.0:"
    # Provider versions do not apply to a virtual's API version.
    fftw = resolve(mapper, "fftw3", source="pkg_config", version_constraint="3.3:")
    assert fftw.spack_spec == "fftw-api" and "3.3:" in fftw.note
    assert resolve(mapper, "z", source="library").spack_spec == "zlib-api"


def test_no_dependency_needed(mapper):
    openmp = resolve(mapper, "OpenMP")
    assert openmp.resolved and openmp.spack_spec is None


def test_case_insensitive_and_prefixes(mapper):
    assert resolve(mapper, "zlib", source="find_package").spack_spec == "zlib-api"
    boost = resolve(mapper, "boost_filesystem", source="library")
    assert boost.spack_spec == "boost+filesystem"


def test_python_and_guesses(mapper):
    assert resolve(mapper, "PyYAML", source="python_requirement").spack_spec == "py-pyyaml"
    assert resolve(mapper, "numpy", source="python_requirement").spack_name == "py-numpy"
    guess = resolve(mapper, "FooBarLib")
    assert not guess.resolved and guess.spack_name == "foobarlib" and "Unverified" in guess.note


def test_trained_model_fallback(ctx):
    class Model:
        def predict(self, inputs):
            return ["foobar-pkg" if i["name"] == "FooBarLib" else None for i in inputs]

    mapper = DependencyMapper(ctx.knowledge.structured("dependency_map"), Model())
    dep = resolve(mapper, "FooBarLib")
    assert dep.resolved and dep.spack_name == "foobar-pkg" and "trained" in dep.note
