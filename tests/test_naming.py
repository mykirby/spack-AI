import pytest

from spack_ai.naming import (
    clean_version,
    package_dir_name,
    pep440_to_spack,
    spack_class_name,
    spack_package_name,
)


@pytest.mark.parametrize(
    ("package", "cls"),
    [("py-numpy", "PyNumpy"), ("hdf5", "Hdf5"), ("3dtk", "_3dtk"), ("netcdf-c", "NetcdfC")],
)
def test_class_name(package, cls):
    assert spack_class_name(package) == cls


def test_package_name():
    assert spack_package_name("MyProject_Core") == "myproject-core"
    assert spack_package_name("Spack_Toolkit", python=True) == "py-spack-toolkit"


@pytest.mark.parametrize(
    ("spec", "expected"),
    [(">=1.2,<2", "1.2:1"), ("==1.4", "1.4"), ("<=3", ":3"), (">=3.9", "3.9:"),
     ("<1.5", ":1.4"), ("~=2.1", "2.1:"), ("!=1.0", None)],
)
def test_pep440_to_spack(spec, expected):
    assert pep440_to_spack(spec) == expected


def test_clean_version_and_dirs():
    assert clean_version("v1.2.3-rc1") == "1.2.3"
    assert clean_version("${PROJECT_VERSION}") is None
    assert package_dir_name("py-numpy", repo_api_v2=True) == "py_numpy"
    assert package_dir_name("py-numpy", repo_api_v2=False) == "py-numpy"
