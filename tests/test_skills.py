import json

import pytest

from spack_ai.agent.prompts import build_system_prompt
from spack_ai.skills import all_skills, get_skill
from spack_ai.skills.base import PathOutsideAllowedRoots
from spack_ai.skills.troubleshooting import diagnose
from spack_ai.spack_runner import is_read_only

EXPECTED_SKILLS = {
    "analyze_build_system", "diagnose_build_failure", "draft_package_recipe", "fetch_source",
    "generate_environment", "generate_job_script", "list_source_tree", "map_dependencies",
    "read_source_file", "save_package_recipe", "search_knowledge", "spack_command",
    "validate_recipe",
}


def test_registry_and_tool_schemas():
    skills = all_skills()
    assert set(skills) == EXPECTED_SKILLS
    for name, skill in skills.items():
        tool = skill.tool_definition()
        assert tool["name"] == name and len(tool["description"]) > 40
        schema = tool["input_schema"]
        assert schema["type"] == "object" and "$ref" not in json.dumps(schema)
        assert schema.get("additionalProperties") is False


def test_system_prompt_is_stable(ctx, settings):
    skills = all_skills()
    first = build_system_prompt(settings, skills, ctx.knowledge)
    assert first == build_system_prompt(settings, skills, ctx.knowledge)
    assert "Skill playbooks" in first and "draft_package_recipe" in first


def test_paths_are_sandboxed(ctx, tmp_path):
    reader = get_skill("read_source_file")(ctx)
    assert "cmake_minimum_required" in reader(path="cmake_project/CMakeLists.txt").data
    with pytest.raises(PathOutsideAllowedRoots):
        reader(path="/etc/passwd")
    with pytest.raises(PathOutsideAllowedRoots):
        ctx.resolve_output("../escape.txt")


def test_list_tree(ctx):
    tree = get_skill("list_source_tree")(ctx)(path="cmake_project").data
    assert "third_party/  [not expanded]" in tree and "main.cpp" in tree


def test_diagnose(ctx):
    log = "\n".join([
        "-- Configuring",
        "CMake Error: Could NOT find HDF5 (missing: HDF5_LIBRARIES)",
        "/usr/bin/ld: cannot find -lfftw3",
        "main.c:3:10: fatal error: netcdf.h: No such file or directory",
    ])
    result = diagnose(log, ctx.knowledge.structured("error_patterns"))
    ids = [m["id"] for m in result["matches"]]
    assert ids == ["cmake-package-not-found", "library-not-found", "missing-header"]
    assert "find_package(HDF5)" in result["matches"][0]["explanation"]
    assert diagnose("all good\nsomething failed here", [])["error_lines"] == [
        "2: something failed here"]


@pytest.mark.parametrize(
    ("args", "safe"),
    [(["info", "hdf5"], True), (["-D", "env", "spec", "x"], True),
     (["compiler", "list"], True), (["install", "x"], False), (["compiler", "find"], False),
     (["external", "find"], False), (["-e", "myenv", "concretize"], False), ([], False)],
)
def test_spack_read_only_policy(args, safe):
    assert is_read_only(args) is safe


def test_spack_command_confirmation(ctx):
    skill = get_skill("spack_command")(ctx)
    assert skill.confirmation_prompt(skill.validate({"args": ["list", "hdf5"]})) is None
    assert "install" in skill.confirmation_prompt(skill.validate({"args": ["install", "x"]}))
